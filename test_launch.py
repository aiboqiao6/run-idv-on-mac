# SPDX-License-Identifier: GPL-3.0-only
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.launcher = self.root / "Launch-DWRG.command"
        source = Path(__file__).with_name('Launch-Legacy-DWRG.command')
        if source.exists():
            shutil.copyfile(source, self.launcher)
        self.app = self.root / "work/DWRG-PathFixed.app"
        self.app.mkdir(parents=True)
        (self.app / "client").write_bytes(b"fixture")
        self.documents = self.root / "Library/Containers/com.netease.id5/Data/Documents"
        self.documents.mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls"
        tools = {
            "codesign": '#!/bin/bash\nprintf "codesign\\n" >> "$CALLS"\nexit "${SIGN_STATUS:-0}"\n',
            "open": '#!/bin/bash\nprintf "%s\\n" "$@" >> "$CALLS"\n',
        }
        for name, body in tools.items():
            path = self.bin / name
            path.write_text(body)
            path.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.root),
                        PATH=f"{self.bin}:/usr/bin:/bin", CALLS=str(self.log))

    def run_launcher(self):
        return subprocess.run(["/bin/bash", str(self.launcher)], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_creates_cache_and_opens_app_without_restoration_or_duplicate(self):
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.documents / "local_shader_cache/res3").is_dir())
        self.assertEqual(self.log.read_text().splitlines(),
                         ["codesign", str(self.app), "--args",
                          "-ApplePersistenceIgnoreState", "YES"])

    def test_existing_data_is_preserved(self):
        cache = self.documents / "local_shader_cache/res3"
        cache.mkdir(parents=True)
        sentinel = cache / "keep"
        sentinel.write_bytes(b"unchanged")
        self.assertEqual(self.run_launcher().returncode, 0)
        self.assertEqual(sentinel.read_bytes(), b"unchanged")

    def test_bad_signature_does_not_launch_or_create_cache(self):
        self.env["SIGN_STATUS"] = "7"
        self.assertEqual(self.run_launcher().returncode, 7)
        self.assertEqual(self.log.read_text(), "codesign\n")
        self.assertFalse((self.documents / "local_shader_cache").exists())

    def test_missing_bundle_is_reported_without_launch(self):
        (self.app / "client").unlink()
        result = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing repaired application", result.stderr)
        self.assertFalse(self.log.exists())

    def test_missing_container_is_reported_without_creating_it(self):
        self.documents.rmdir()
        result = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing game Documents directory", result.stderr)
        self.assertFalse(self.documents.exists())
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
