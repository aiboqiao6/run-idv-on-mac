# SPDX-License-Identifier: GPL-3.0-only
import copy
import hashlib
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import prepare
import executable_path_patch as binary_patch


class EntitlementsTests(unittest.TestCase):
    def test_preserves_sandbox_and_original_permissions(self):
        original = {"com.apple.security.app-sandbox": True,
                    "com.apple.security.temporary-exception.sbpl": ["existing-rule"]}
        before = copy.deepcopy(original)
        result = prepare.scoped_entitlements(original, Path('/tmp/example "copy".app'))
        self.assertEqual(original, before)
        self.assertTrue(result["com.apple.security.app-sandbox"])
        rules = result["com.apple.security.temporary-exception.sbpl"]
        self.assertEqual(rules[0], "existing-rule")
        self.assertIn(r'(subpath "/tmp/example \"copy\".app")', rules[1])

    def test_rejects_non_sandboxed_or_invalid_entitlements(self):
        for value in (None, {}, {"com.apple.security.app-sandbox": False},
                      {"com.apple.security.app-sandbox": True,
                       "com.apple.security.temporary-exception.sbpl": "invalid"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prepare.scoped_entitlements(value, Path("/tmp/example.app"))


class WorkcopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.app"
        self.source.mkdir()
        self.output = self.root / "work"
        self.data = b"H" * 16 + binary_patch.OLD_BRANCH + b"T" * 16
        self.executable = self.source / "client"
        self.executable.write_bytes(self.data)
        self.executable.chmod(0o755)
        (self.source / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "com.netease.id5",
            "CFBundleExecutable": "client",
        }))
        (self.source / "resource").write_text("preserve")
        digest = hashlib.sha256(self.data).hexdigest()
        self.addCleanup(patch.stopall)
        patch.object(binary_patch, "BUILD_SHA256", digest).start()
        patch.object(binary_patch, "BRANCH_OFFSET", 16).start()
        self.commands = []
        self.command = patch("prepare.subprocess.run", side_effect=self.fake_command,
                             create=True).start()

    def fake_command(self, args, **kwargs):
        self.commands.append(args)
        output = plistlib.dumps({
            "com.apple.security.app-sandbox": True,
            "com.apple.security.temporary-exception.sbpl": ["existing-rule"],
        }) if "--entitlements" in args and "-d" in args else b""
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr=b"")

    def test_builds_patched_copy_without_modifying_source(self):
        app = prepare.build_workcopy(self.source, self.output)
        self.assertEqual(app, self.output / "DWRG-PathFixed.app")
        self.assertEqual(self.executable.read_bytes(), self.data)
        self.assertEqual((app / "client").read_bytes()[16:20], binary_patch.NEW_BRANCH)
        self.assertEqual((app / "resource").read_text(), "preserve")
        self.assertEqual((app / "client").stat().st_mode & 0o777, 0o755)
        entitlements = plistlib.loads((self.output / "workcopy-entitlements.plist").read_bytes())
        self.assertTrue(entitlements["com.apple.security.app-sandbox"])
        self.assertIn(str(app), entitlements["com.apple.security.temporary-exception.sbpl"][-1])
        self.assertTrue(any("--force" in command for command in self.commands))
        self.assertEqual(self.commands[-1][:4], ["codesign", "--verify", "--deep", "--strict"])

    def test_unknown_binary_is_rejected_before_creating_output(self):
        self.executable.write_bytes(b"unknown")
        with self.assertRaises(ValueError):
            prepare.build_workcopy(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_copy_is_not_overwritten(self):
        app = self.output / "DWRG-PathFixed.app"
        app.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            prepare.build_workcopy(self.source, self.output)
        self.assertEqual(list(app.iterdir()), [])

    def test_output_inside_source_is_rejected(self):
        with self.assertRaises(ValueError):
            prepare.build_workcopy(self.source, self.source / "work")
        self.assertFalse((self.source / "work").exists())

    def test_signature_failure_does_not_create_output(self):
        self.command.side_effect = subprocess.CalledProcessError(7, ["codesign"])
        with self.assertRaises(subprocess.CalledProcessError):
            prepare.build_workcopy(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_invalid_bundle_identity_is_rejected(self):
        (self.source / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "other.app", "CFBundleExecutable": "../client"}))
        with self.assertRaises(ValueError):
            prepare.build_workcopy(self.source, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
