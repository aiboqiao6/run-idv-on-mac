"""Discover, prepare and launch the verified native-PC Identity V workcopy.

Only a private copy is patched. Installation is version guarded and transactional;
normal startup uses LC_LOAD_DYLIB, never a debugger. No third-party Python package
or compiler is needed: the reviewed arm64 Catalyst helper is shipped alongside.
"""
import argparse
import copy
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import time

from macho_load import add_dylib

BUNDLE_ID = 'com.netease.id5'
VERSION = '26.243.2117'
APP_NAME = 'DWRG-PC.app'
LOAD_PATH = '@executable_path/PCSupport/libIDVNativeInput.dylib'
BRANCH_OFFSET = 0x572E108
OLD_BRANCH = bytes.fromhex('60020054')
NEW_BRANCH = bytes.fromhex('13000014')
SUPPORTED = {
    '7d6f8003d51f93c8682b01619b193af2b79d600de3b78340f9ac2e8d4aa6405d': 'original',
    # The same installed build re-signed by the earlier startup repair tooling.
    '71c075785c13ce2b3b177f6b03999cef4ad1c8966eb8ff2846f3d1fdf43d168b': 'original',
    '219272c4af5164476bcc6d8a3c0f0b623c595b5fb44fe982ff979255f4118f6d': 'repaired',
}
PAYLOAD = ('libIDVNativeInput-v8.dylib', 'runtime_adapter.py', 'input_state.py')
INSTALLED_NAMES = {'libIDVNativeInput-v8.dylib': 'libIDVNativeInput.dylib'}
SANDBOX = 'com.apple.security.app-sandbox'
SBPL = 'com.apple.security.temporary-exception.sbpl'
SETTINGS = {'keymapping': False, 'disableBuiltinMouse': False,
            'rootWorkDir': False, 'enableScrollWheel': True}
TOOLS = Path(__file__).resolve().parent
PROJECT = TOOLS.parent
LSREGISTER = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def run(args: list[str], timeout: int = 90) -> subprocess.CompletedProcess:
    """Run argv directly and retain command errors without a shell."""
    return subprocess.run(args, check=True, capture_output=True, timeout=timeout)


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
        return digest.hexdigest()


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Replace one local control file, preserving the old file on write failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.writing-', delete=False) as out:
        temporary = Path(out.name)
        try:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def read_info(app: Path) -> dict:
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    if (not isinstance(info, dict) or info.get('CFBundleIdentifier') != BUNDLE_ID
            or info.get('CFBundleExecutable') != 'client'):
        raise ValueError(f'不是第五人格的 PlayCover 包体：{app}')
    return info


def validate_source(app: Path) -> tuple[str, str]:
    info = read_info(app)
    executable = app / 'client'
    if executable.is_symlink():
        raise ValueError(f'不支持符号链接可执行文件：{executable}')
    if info.get('CFBundleShortVersionString') != VERSION:
        raise ValueError(f'不支持的游戏版本：{app}')
    digest = sha256(executable)
    if digest not in SUPPORTED:
        raise ValueError(f'不支持或已变化的可执行文件：{app} (SHA256 {digest})')
    return digest, SUPPORTED[digest]


def scan_roots(roots: list[Path], max_depth: int = 3) -> list[Path]:
    """Bounded scan, pruning entire bundles, symlinks and unrelated hidden dirs."""
    found = []
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        def on_error(error):
            print(f'扫描跳过无法读取的目录：{error.filename}', file=sys.stderr)
        for base, dirs, _ in os.walk(root, followlinks=False, onerror=on_error):
            parent = Path(base)
            depth = len(parent.relative_to(root).parts)
            for name in list(dirs):
                path = parent / name
                if path.suffix == '.app':
                    dirs.remove(name)
                    try:
                        read_info(path)
                        resolved = path.resolve()
                        if resolved not in seen:
                            found.append(resolved)
                            seen.add(resolved)
                    except (OSError, ValueError, plistlib.InvalidFileException):
                        continue
                elif name.startswith('.') or path.is_symlink() or depth >= max_depth:
                    dirs.remove(name)
    return found


def discover() -> list[Path]:
    home = Path.home()
    playcover = home / 'Library/Containers/io.playcover.PlayCover'
    roots = [playcover / 'Applications', playcover / 'Data/Applications',
             home / 'Applications', Path('/Applications'), PROJECT,
             home / 'Library/Application Support/PlayCover/Applications']
    found = scan_roots(roots)
    # Spotlight covers custom locations without walking the user's entire disk.
    try:
        result = run(['/usr/bin/mdfind', '-0', f'kMDItemCFBundleIdentifier == "{BUNDLE_ID}"'], 15)
        for item in result.stdout.split(b'\0'):
            if item:
                path = Path(os.fsdecode(item)).resolve()
                if path not in found and path.suffix == '.app':
                    try:
                        read_info(path)
                        found.append(path)
                    except (OSError, ValueError, plistlib.InvalidFileException):
                        continue
    except (OSError, subprocess.SubprocessError) as error:
        print(f'Spotlight 不可用，已使用常见安装目录扫描：{error}', file=sys.stderr)
    return found


def scoped_entitlements(original: dict, app: Path) -> dict:
    if not isinstance(original, dict) or original.get(SANDBOX) is not True:
        raise ValueError('需要保留 PlayCover 的沙盒签名权限')
    rules = original.get(SBPL, [])
    if not isinstance(rules, list) or not all(isinstance(x, str) for x in rules):
        raise ValueError('签名中的沙盒规则格式不正确')
    result = copy.deepcopy(original)
    quoted = json.dumps(str(app), ensure_ascii=False)
    rule = f'(allow file* file-read* file-read-metadata file-ioctl (subpath {quoted}))'
    result[SBPL] = list(dict.fromkeys([*rules, rule]))
    return result


def payload_hashes(payload: Path) -> dict[str, str]:
    return {INSTALLED_NAMES.get(name, name): sha256(payload / name) for name in PAYLOAD}


def prepared_app(state: Path, payload: Path) -> Path | None:
    manifest_path = state / 'manifest.json'
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text())
    app = state / APP_NAME
    if (not isinstance(manifest, dict) or manifest.get('schema') != 1
            or manifest.get('app') != str(app) or manifest.get('payload') != payload_hashes(payload)):
        raise ValueError('启动副本位置或补丁版本变化，请使用 --rebuild 重新生成')
    read_info(app)
    if sha256(app / 'client') != manifest.get('client_sha256'):
        raise ValueError('启动副本的可执行文件校验失败，请使用 --rebuild')
    for name, digest in manifest['payload'].items():
        if sha256(app / 'PCSupport' / name) != digest:
            raise ValueError(f'键鼠补丁校验失败：{name}；请使用 --rebuild')
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])
    return app


def prepare(source: Path, state: Path, payload: Path, rebuild: bool = False) -> Path:
    """Prepare before touching settings; retain old output and failed builds."""
    source, state = source.resolve(strict=True), state.resolve()
    if source == state or source in state.parents or state in source.parents:
        raise ValueError('输出位置不能与原游戏目录重叠')
    app = state / APP_NAME
    if app.exists() and (not rebuild or not (state / 'manifest.json').is_file()):
        raise FileExistsError('输出已存在；仅 --rebuild 可更新本工具管理的副本')
    digest, kind = validate_source(source)
    data = (source / 'client').read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('复制前游戏文件已变化，请重新运行')
    expected = OLD_BRANCH if kind == 'original' else NEW_BRANCH
    if data[BRANCH_OFFSET:BRANCH_OFFSET + 4] != expected:
        raise ValueError('启动修复指令不匹配')
    if kind == 'original':
        run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(source)])
    extracted = run(['/usr/bin/codesign', '-d', '--entitlements', '-', '--xml', str(source)])
    entitlements = scoped_entitlements(plistlib.loads(extracted.stdout), app)
    repaired = bytearray(data)
    repaired[BRANCH_OFFSET:BRANCH_OFFSET + 4] = NEW_BRANCH
    installed = add_dylib(bytes(repaired), LOAD_PATH)
    expected_payload = payload_hashes(payload)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    staging = state / f'building-{stamp}.app'
    previous = state / f'previous-{stamp}.app'
    moved_previous = False
    published = False
    try:
        print(f'复制游戏并安装原生键鼠支持：{source}', flush=True)
        run(['/usr/bin/ditto', str(source), str(staging)], 600)
        if (staging / 'client').is_symlink() or sha256(staging / 'client') != digest:
            raise ValueError('复制后的可执行文件与来源不一致')
        (staging / 'client').write_bytes(installed)
        support = staging / 'PCSupport'
        if support.exists():
            support.rename(state / f'legacy-PCSupport-{stamp}')
        support.mkdir()
        for name in PAYLOAD:
            target = support / INSTALLED_NAMES.get(name, name)
            target.write_bytes((payload / name).read_bytes())
            target.chmod(0o755 if name.endswith('.dylib') else 0o644)
            if sha256(target) != expected_payload[target.name]:
                raise ValueError('复制期间补丁文件发生变化')
        entitlement_path = state / 'entitlements.plist'
        atomic_write(entitlement_path, plistlib.dumps(entitlements))
        if app.exists():
            app.rename(previous)
            moved_previous = True
        staging.rename(app)
        published = True
        # Ship the already signed helper byte-for-byte. Re-signing it under a
        # new basename changes its hash and would invalidate payload reuse.
        run(['/usr/bin/codesign', '--verify', '--strict', str(app / 'PCSupport/libIDVNativeInput.dylib')])
        run(['/usr/bin/codesign', '--force', '--sign', '-', '--entitlements', str(entitlement_path), str(app)])
        run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])
        manifest = dict(schema=1, app=str(app), source=str(source), source_sha256=digest,
                        client_sha256=sha256(app / 'client'), payload=expected_payload,
                        version=VERSION, prepared_at=datetime.now().astimezone().isoformat())
        atomic_write(state / 'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode())
    except Exception:
        if published and app.exists():
            app.rename(state / f'failed-{stamp}.app')
        elif staging.exists():
            staging.rename(state / f'failed-{stamp}.app')
        if moved_previous:
            previous.rename(app)
        raise
    return app


def load_settings(path: Path) -> dict:
    try:
        value = plistlib.loads(path.read_bytes())
    except plistlib.InvalidFileException as error:
        raise ValueError(f'PlayCover 设置损坏，未覆盖：{path}') from error
    if not isinstance(value, dict):
        raise ValueError('PlayCover 设置必须是字典')
    return value


def configure_settings(settings: Path, backup: Path) -> None:
    if settings.is_symlink():
        raise ValueError('不支持符号链接设置文件')
    current = load_settings(settings)
    if not backup.exists():
        atomic_write(backup, settings.read_bytes())
    current.update(SETTINGS)
    atomic_write(settings, plistlib.dumps(current))


def restore_settings(settings: Path, backup: Path) -> None:
    current, original = load_settings(settings), load_settings(backup)
    for name in SETTINGS:
        if name in original:
            current[name] = original[name]
        else:
            current.pop(name, None)
    atomic_write(settings, plistlib.dumps(current))


def game_processes() -> dict[int, Path]:
    """Only exact client executable paths inside identity-checked .app bundles."""
    result = run(['/bin/ps', '-axww', '-o', 'pid=,comm='])
    found = {}
    for line in result.stdout.decode(errors='replace').splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        executable = Path(fields[1])
        if executable.name != 'client' or executable.parent.suffix != '.app':
            continue
        try:
            read_info(executable.parent)
            found[int(fields[0])] = executable.parent.resolve()
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
    return found


def stop_games(closing: dict[int, Path]) -> None:
    """Close only identity-checked clients and wait without forcing termination."""
    for pid, path in closing.items():
        if game_processes().get(pid) != path:
            raise ValueError('游戏进程发生变化，请重新运行')
        print(f'正常关闭旧游戏进程 {pid}：{path}', flush=True)
        os.kill(pid, signal.SIGTERM)
    if closing:
        deadline = time.monotonic() + 20
        while any(pid in game_processes() for pid in closing):
            if time.monotonic() >= deadline:
                raise TimeoutError('游戏未正常退出；没有强制终止，请自行关闭后重试')
            time.sleep(0.25)


def launch(app: Path, state: Path, restart: bool = False, metal_hud: bool = False) -> None:
    home = Path.home()
    documents = home / f'Library/Containers/{BUNDLE_ID}/Data/Documents'
    settings = home / f'Library/Containers/io.playcover.PlayCover/App Settings/{BUNDLE_ID}.plist'
    if not documents.is_dir():
        raise FileNotFoundError('未找到游戏数据容器，请先用 PlayCover 安装并启动一次游戏')
    if (documents / 'idv-pc-support-disabled').exists():
        raise ValueError('检测到 idv-pc-support-disabled 禁用标记；请先移走该标记再启动')
    # LaunchServices can cache the pre-signing bundle while a new copy is
    # prepared. Refresh its record only after strict signature verification.
    run([LSREGISTER, '-f', str(app)])
    processes = game_processes()
    others = {pid: path for pid, path in processes.items() if path != app}
    if others and not restart:
        raise ValueError('另一个第五人格副本正在运行；退出后重试，或传入 --restart 正常关闭后启动')
    if app in processes.values() and not restart:
        if metal_hud:
            raise ValueError('Metal 面板需在启动时加载，请使用 --metal-hud --restart')
        run(['/usr/bin/open', str(app)])
        print('启动副本已在运行，已切回游戏；如需重新加载设置，请使用 --restart。')
        return
    stop_games(processes if restart else others)
    before = load_settings(settings)
    configure_settings(settings, state / 'settings-before.plist')
    try:
        (documents / 'local_shader_cache/res3').mkdir(parents=True, exist_ok=True)
        command = ['/usr/bin/open']
        if metal_hud:
            command += ['--env', 'MTL_HUD_ENABLED=1']
        run([*command, str(app), '--args', '-ApplePersistenceIgnoreState', 'YES'])
        deadline = time.monotonic() + 20
        while app not in game_processes().values():
            if time.monotonic() >= deadline:
                raise TimeoutError('系统已接收启动请求，但未发现游戏进程；请检查启动日志')
            time.sleep(0.25)
    except Exception:
        current = load_settings(settings)
        for name in SETTINGS:
            if name in before:
                current[name] = before[name]
            else:
                current.pop(name, None)
        atomic_write(settings, plistlib.dumps(current))
        raise
    print(f'游戏进程已启动：{app}\n已配置原生键鼠与滚轮；适配器将在游戏初始化完成后自动加载。', flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description='第五人格：自动扫描、启动修复、原生键鼠与滚轮支持')
    parser.add_argument('--app', type=Path, help='手动指定来源 .app，覆盖自动扫描')
    parser.add_argument('--scan', action='store_true', help='仅列出扫描结果，不更改文件')
    parser.add_argument('--prepare-only', action='store_true', help='生成并校验启动副本，不启动游戏')
    parser.add_argument('--rebuild', action='store_true', help='重新生成副本，保留上一版')
    parser.add_argument('--restart', action='store_true', help='正常关闭其他第五人格副本后启动')
    parser.add_argument('--metal-hud', action='store_true', help='本次启动显示 Metal FPS／帧时间面板')
    parser.add_argument('--restore-settings', action='store_true', help='仅恢复本工具更改的 PlayCover 设置项')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('此启动器需要 Apple Silicon macOS 与 PlayCover')
    state = PROJECT / '.pc-launcher'
    try:
        if args.scan:
            for app in discover():
                try:
                    _, kind = validate_source(app)
                    print(f'支持 ({kind})：{app}')
                except (OSError, ValueError) as error:
                    print(error)
            return 0
        state.mkdir(mode=0o700, exist_ok=True)
        with (state / 'launcher.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError('另一个启动器正在准备游戏，请稍候') from error
            if args.restore_settings:
                settings = Path.home() / f'Library/Containers/io.playcover.PlayCover/App Settings/{BUNDLE_ID}.plist'
                restore_settings(settings, state / 'settings-before.plist')
                print('已恢复启动器修改前的四项 PlayCover 设置，其余设置保留。')
                return 0
            app = None if args.rebuild or args.app else prepared_app(state, TOOLS)
            if app is None:
                running = {pid: path for pid, path in game_processes().items() if path == state / APP_NAME}
                if running and (not args.restart or args.prepare_only):
                    raise ValueError('启动副本仍在运行，请退出后再重建，或使用 --rebuild --restart')
                candidates = [args.app.resolve()] if args.app else discover()
                source = None
                for candidate in candidates:
                    try:
                        validate_source(candidate)
                        source = candidate
                        break
                    except (OSError, ValueError) as error:
                        print(f'跳过：{error}', file=sys.stderr)
                if source is None:
                    raise FileNotFoundError('没有找到受支持的第五人格；可使用 --app 指定 PlayCover 游戏包')
                if running:
                    stop_games(running)
                app = prepare(source, state, TOOLS, rebuild=args.rebuild)
            if args.prepare_only:
                print(f'启动副本与签名已校验：{app}')
            else:
                launch(app, state, restart=args.restart, metal_hud=args.metal_hud)
        return 0
    except (OSError, ValueError, KeyError, plistlib.InvalidFileException,
            subprocess.SubprocessError) as error:
        print(f'启动失败：{error}', file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stderr.decode(errors='replace')[-4000:], file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
