"""Preserve _NSGetExecutablePath instead of prepending the iOS /private prefix."""

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path

BUILD_SHA256 = "7d6f8003d51f93c8682b01619b193af2b79d600de3b78340f9ac2e8d4aa6405d"
BRANCH_OFFSET = 0x572E108
OLD_BRANCH = bytes.fromhex("60020054")
NEW_BRANCH = bytes.fromhex("13000014")


def patched_bytes(data, expected_sha256, offset):
    if not isinstance(data, bytes) or not isinstance(expected_sha256, str):
        raise ValueError("Expected binary bytes and a SHA-256 string")
    if type(offset) is not int or offset < 0 or offset % 4 or offset + 4 > len(data):
        raise ValueError("Invalid instruction offset")
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected_sha256):
        raise ValueError("Unknown or changed executable; refusing to patch")
    if data[offset:offset + 4] != OLD_BRANCH:
        raise ValueError("Expected executable-path branch was not found")
    # Take the existing path-copy branch without fabricating an iOS-only prefix.
    return data[:offset] + NEW_BRANCH + data[offset + 4:]


def patch_file(source, output, expected_sha256=BUILD_SHA256, offset=BRANCH_OFFSET):
    source, output = Path(source), Path(output)
    result = patched_bytes(source.read_bytes(), expected_sha256, offset)
    mode = source.stat().st_mode & 0o777
    with output.open("xb") as stream:
        stream.write(result)
        stream.flush()
        os.fsync(stream.fileno())
    output.chmod(mode)
    return hashlib.sha256(result).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        digest = patch_file(args.source, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Executable path repair failed: {error}\n")
    print(json.dumps({"output": str(args.output), "sha256": digest, "patch_offset": hex(BRANCH_OFFSET)}))


if __name__ == "__main__":
    main()
