# SPDX-License-Identifier: GPL-3.0-only
import signal
import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import stop


class SelectionTests(unittest.TestCase):
    def test_matches_only_exact_executable_and_its_arguments(self):
        path = "/tmp/work copy/DWRG-PathFixed.app/client"
        processes = (
            f"100 {path}\n101 {path} -ApplePersistenceIgnoreState YES\n"
            f"102 {path}-other\n103 /tmp/original.app/client\n"
            f"104 /bin/bash -c {path}\ninvalid\n0 {path}\n")
        self.assertEqual(stop.matching_pids(processes, path), [100, 101])

    def test_invalid_inputs_are_rejected(self):
        for text, path in ((None, "/tmp/client"), ("", None), ("", "relative")):
            with self.subTest(text=text, path=path), self.assertRaises(ValueError):
                stop.matching_pids(text, path)


class StopTests(unittest.TestCase):
    def setUp(self):
        self.app = Path("/tmp/work/DWRG-PathFixed.app").resolve()
        self.executable = str(self.app / "client")
        self.addCleanup(patch.stopall)
        self.run = patch("stop.subprocess.run").start()
        self.kill = patch("stop.os.kill").start()

    def command_result(self, text="", code=0):
        return subprocess.CompletedProcess(["ps"], code, stdout=text, stderr="")

    def test_stops_matching_copy_with_sigterm_not_sigkill(self):
        self.run.side_effect = [self.command_result(f"200 {self.executable}\n"),
                                self.command_result(self.executable)]
        self.assertEqual(stop.stop_game(self.app), 1)
        self.kill.assert_called_once_with(200, signal.SIGTERM)

    def test_no_match_is_successful_and_kills_nothing(self):
        self.run.return_value = self.command_result("201 /tmp/other.app/client")
        self.assertEqual(stop.stop_game(self.app), 0)
        self.kill.assert_not_called()

    def test_reused_pid_is_rechecked_before_signal(self):
        self.run.side_effect = [self.command_result(f"200 {self.executable}"),
                                self.command_result("/tmp/other.app/client")]
        self.assertEqual(stop.stop_game(self.app), 0)
        self.kill.assert_not_called()

    def test_process_exiting_before_signal_is_tolerated(self):
        self.run.side_effect = [self.command_result(f"200 {self.executable}"),
                                self.command_result(self.executable)]
        self.kill.side_effect = ProcessLookupError()
        self.assertEqual(stop.stop_game(self.app), 0)

    def test_process_exiting_before_recheck_is_tolerated(self):
        self.run.side_effect = [self.command_result(f"200 {self.executable}"),
                                self.command_result(code=1)]
        self.assertEqual(stop.stop_game(self.app), 0)
        self.kill.assert_not_called()

    def test_ps_failure_is_not_silently_ignored(self):
        self.run.side_effect = subprocess.CalledProcessError(7, ["ps"])
        with self.assertRaises(subprocess.CalledProcessError):
            stop.stop_game(self.app)
        self.kill.assert_not_called()


class CommandLineTests(unittest.TestCase):
    def test_main_stops_both_owned_layouts(self):
        with patch.object(stop.sys, 'platform', 'darwin'), \
                patch.object(stop, 'stop_game', return_value=0) as stop_game, \
                patch('builtins.print'):
            self.assertEqual(stop.main(), 0)
        root = Path(stop.__file__).resolve().parent
        self.assertEqual([c.args[0] for c in stop_game.call_args_list],
                         [root / '.pc-launcher/DWRG-PC.app', root / 'work/DWRG-PathFixed.app'])

    def test_no_running_game_is_successful(self):
        with patch.object(stop.sys, "platform", "darwin"):
            with patch.object(stop, "stop_game", return_value=0), patch("builtins.print"):
                self.assertEqual(stop.main(), 0)

    def test_unsupported_platform_is_reported(self):
        with patch.object(stop.sys, "platform", "linux"):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(stop.main(), 1)

    def test_permission_error_is_reported(self):
        with patch.object(stop.sys, "platform", "darwin"):
            with patch.object(stop, "stop_game", side_effect=PermissionError()):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(stop.main(), 1)


@unittest.skipUnless(sys.platform == "darwin", "Native shutdown integration requires macOS")
class NativeIntegrationTests(unittest.TestCase):
    def test_only_self_created_process_is_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory).resolve() / "fixture.app"
            app.mkdir()
            executable = app / "client"
            shutil.copy("/bin/sleep", executable)
            subprocess.run(["codesign", "--force", "--sign", "-", str(executable)],
                           check=True, capture_output=True, timeout=10)
            child = subprocess.Popen([str(executable), "30"])
            try:
                self.assertEqual(stop.stop_game(app), 1)
                self.assertEqual(child.wait(timeout=5), -signal.SIGTERM)
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
