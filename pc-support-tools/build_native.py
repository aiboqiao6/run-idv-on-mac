"""Rebuild the shipped, project-owned Catalyst helper with Apple's SDK."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def build() -> Path:
    sdk = Path(subprocess.check_output(
        ['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip())
    frameworks = sdk / 'System/iOSSupport/System/Library/Frameworks'
    output = ROOT / 'libIDVNativeInput-v8.dylib'
    with tempfile.TemporaryDirectory(prefix='idv-native-build-') as temporary:
        artifact = Path(temporary) / output.name
        subprocess.run([
            'xcrun', 'clang', '-target', 'arm64-apple-ios14.0-macabi',
            '-isysroot', str(sdk), '-iframework', str(frameworks),
            '-F', str(frameworks), '-L', str(sdk / 'System/iOSSupport/usr/lib'),
            '-fobjc-arc', '-fblocks', '-dynamiclib', '-Wall', '-Wextra', '-Werror',
            '-framework', 'Foundation', '-framework', 'GameController',
            '-framework', 'CoreGraphics', '-install_name',
            '@executable_path/PCSupport/libIDVNativeInput.dylib',
            str(ROOT / 'IDVNativeInput.m'), '-o', str(artifact),
        ], check=True)
        subprocess.run(['codesign', '--force', '--sign', '-', '--identifier',
                        'libIDVNativeInput.dylib', str(artifact)], check=True)
        subprocess.run(['codesign', '--verify', '--strict', str(artifact)], check=True)
        # Build on the same volume as the destination before atomic replacement.
        staged = None
        try:
            with tempfile.NamedTemporaryFile(dir=ROOT, prefix='.native-',
                                             suffix='.dylib', delete=False) as target:
                staged = Path(target.name)
                target.write(artifact.read_bytes())
            staged.chmod(0o755)
            os.replace(staged, output)
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
    return output


if __name__ == '__main__':
    print(build())
