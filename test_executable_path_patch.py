# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

import executable_path_patch as patch


class ExecutablePathPatchTests(unittest.TestCase):
    def setUp(self):
        self.offset = 16
        self.data = b"H" * self.offset + patch.OLD_BRANCH + b"T" * 16
        self.digest = hashlib.sha256(self.data).hexdigest()

    def test_preserves_executable_path_without_prefixing_private(self):
        result = patch.patched_bytes(self.data, self.digest, self.offset)
        self.assertEqual(result[self.offset:self.offset + 4], patch.NEW_BRANCH)
        self.assertEqual(result[:self.offset], self.data[:self.offset])
        self.assertEqual(result[self.offset + 4:], self.data[self.offset + 4:])
        self.assertEqual(len(result), len(self.data))

    def test_branch_targets_are_identical(self):
        old = int.from_bytes(patch.OLD_BRANCH, "little")
        new = int.from_bytes(patch.NEW_BRANCH, "little")
        self.assertEqual(old & 0xFF00001F, 0x54000000)
        self.assertEqual(new & 0xFC000000, 0x14000000)
        self.assertEqual(((old >> 5) & 0x7FFFF) * 4, (new & 0x3FFFFFF) * 4)
        self.assertEqual((new & 0x3FFFFFF) * 4, 0x4C)

    def test_unknown_build_is_rejected(self):
        with self.assertRaises(ValueError):
            patch.patched_bytes(self.data, "0" * 64, self.offset)

    def test_wrong_instruction_is_rejected(self):
        altered = self.data[:self.offset] + b"\0" * 4 + self.data[self.offset + 4:]
        with self.assertRaises(ValueError):
            patch.patched_bytes(altered, hashlib.sha256(altered).hexdigest(), self.offset)

    def test_invalid_input_is_rejected(self):
        for offset in (-1, 1, len(self.data), None, True):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                patch.patched_bytes(self.data, self.digest, offset)
        for data, digest in ((None, self.digest), (self.data, None), (self.data, "abc")):
            with self.subTest(data=data, digest=digest), self.assertRaises(ValueError):
                patch.patched_bytes(data, digest, self.offset)

    def test_original_and_mode_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "source", Path(directory) / "output"
            source.write_bytes(self.data)
            source.chmod(0o755)
            patch.patch_file(source, output, self.digest, self.offset)
            self.assertEqual(source.read_bytes(), self.data)
            self.assertEqual(output.stat().st_mode & 0o777, 0o755)
            self.assertEqual(output.read_bytes()[self.offset:self.offset + 4], patch.NEW_BRANCH)

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "source", Path(directory) / "output"
            source.write_bytes(self.data)
            output.write_bytes(b"keep")
            with self.assertRaises(FileExistsError):
                patch.patch_file(source, output, self.digest, self.offset)
            self.assertEqual(output.read_bytes(), b"keep")

    def test_missing_source_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            with self.assertRaises(FileNotFoundError):
                patch.patch_file(Path(directory) / "missing", output, self.digest, self.offset)
            self.assertFalse(output.exists())


class CommandLineTests(unittest.TestCase):
    def test_success_reports_patch_result(self):
        with mock_patch("sys.argv", ["patch", "/tmp/input", "/tmp/output"]):
            with mock_patch.object(patch, "patch_file", return_value="a" * 64):
                with mock_patch("builtins.print") as printing:
                    patch.main()
        self.assertIn('"sha256":', printing.call_args.args[0])

    def test_error_is_reported_without_traceback(self):
        stderr = io.StringIO()
        with mock_patch("sys.argv", ["patch", "/tmp/input", "/tmp/output"]):
            with mock_patch.object(patch, "patch_file", side_effect=ValueError("Unknown binary")):
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as result:
                    patch.main()
        self.assertEqual(result.exception.code, 1)
        self.assertIn("Executable path repair failed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
