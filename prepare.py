# SPDX-License-Identifier: GPL-3.0-only
"""Prepare a local workcopy of an already-installed PlayCover application."""

import argparse
import copy
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import executable_path_patch as binary_patch

SANDBOX = "com.apple.security.app-sandbox"
SBPL = "com.apple.security.temporary-exception.sbpl"


def scoped_entitlements(entitlements, app):
    """Preserve the existing sandbox and allow access only to this workcopy."""
    if not isinstance(entitlements, dict) or entitlements.get(SANDBOX) is not True:
        raise ValueError("Expected sandboxed PlayCover entitlements")
    rules = entitlements.get(SBPL, [])
    if not isinstance(rules, list) or not all(isinstance(rule, str) for rule in rules):
        raise ValueError("Expected a list of sandbox rules")
    result = copy.deepcopy(entitlements)
    quoted_path = json.dumps(str(app), ensure_ascii=False)
    rule = f"(allow file* file-read* file-read-metadata file-ioctl (subpath {quoted_path}))"
    result[SBPL] = list(rules) + [rule]
    return result


def build_workcopy(source, output):
    """Create and sign a new copy; failures leave originals untouched."""
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    if not source.is_dir() or source.suffix != ".app":
        raise ValueError("Source must be an installed .app bundle")
    if output == source or source in output.parents:
        raise ValueError("Output cannot be inside the source application")
    app = output / "DWRG-PathFixed.app"
    entitlement_path = output / "workcopy-entitlements.plist"
    if app.exists() or entitlement_path.exists():
        raise FileExistsError("Output already exists; choose a fresh output directory")
    info = plistlib.loads((source / "Info.plist").read_bytes())
    if (not isinstance(info, dict) or info.get("CFBundleIdentifier") != "com.netease.id5"
            or info.get("CFBundleExecutable") != "client"):
        raise ValueError("Expected the com.netease.id5 client bundle")
    data = (source / "client").read_bytes()
    repaired = binary_patch.patched_bytes(
        data, binary_patch.BUILD_SHA256, binary_patch.BRANCH_OFFSET)

    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(source)],
                   check=True, capture_output=True, timeout=60)
    extracted = subprocess.run(["codesign", "-d", "--entitlements", "-", "--xml", str(source)],
                               check=True, capture_output=True, timeout=60)
    entitlements = scoped_entitlements(plistlib.loads(extracted.stdout), app)

    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copytree(source, app, symlinks=True)
    executable = app / "client"
    # Do not follow an unexpected executable symlink back into the original.
    if executable.is_symlink():
        raise ValueError("Executable symlinks are not supported; copy retained for inspection")
    executable.write_bytes(repaired)
    with entitlement_path.open("xb") as stream:
        plistlib.dump(entitlements, stream)
    entitlement_path.chmod(0o600)
    subprocess.run(["codesign", "--force", "--sign", "-", "--entitlements",
                    str(entitlement_path), str(app)],
                   check=True, capture_output=True, timeout=60)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)],
                   check=True, capture_output=True, timeout=60)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.home() /
                        "Library/Containers/io.playcover.PlayCover/Applications/com.netease.id5.app")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "work")
    args = parser.parse_args()
    if sys.platform != "darwin" or not shutil.which("codesign"):
        parser.exit(1, "Preparation requires macOS and codesign.\n")
    try:
        app = build_workcopy(args.source, args.output)
    except (OSError, ValueError, plistlib.InvalidFileException,
            subprocess.SubprocessError) as error:
        parser.exit(1, f"Preparation failed: {error}\n"
                    "Original application was not replaced. Inspect local output before retrying.\n")
    print(f"Prepared local copy: {app}")
    print("Use Launch-DWRG.command for the default output; do not move the signed bundle.")


if __name__ == "__main__":
    main()
