"""Launcher regressions use synthetic bundles, never the installed game."""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

import launcher
import test_macho_load


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'renamed game.app'
        self.source.mkdir()
        self.data = test_macho_load.MachOLoadTests().sample()
        (self.source / 'client').write_bytes(self.data)
        (self.source / 'client').chmod(0o755)
        self.info = dict(CFBundleIdentifier=launcher.BUNDLE_ID,
                         CFBundleExecutable='client',
                         CFBundleShortVersionString=launcher.VERSION)
        (self.source / 'Info.plist').write_bytes(plistlib.dumps(self.info))
        self.digest = hashlib.sha256(self.data).hexdigest()
        self.addCleanup(patch.stopall)
        patch.object(launcher, 'SUPPORTED', {self.digest: 'repaired'}).start()
        patch.object(launcher, 'BRANCH_OFFSET', 4096).start()
        patch.object(launcher, 'NEW_BRANCH', self.data[4096:4100]).start()
        self.payload = self.root / 'payload'
        self.payload.mkdir()
        for name in launcher.PAYLOAD:
            (self.payload / name).write_bytes(name.encode())

    def test_discovery_uses_bundle_identity_and_skips_nested_app_contents(self):
        found = launcher.scan_roots([self.root], max_depth=3)
        self.assertEqual(found, [self.source])
        nested = self.source / 'nested.app'
        shutil.copytree(self.source, nested)
        self.assertEqual(launcher.scan_roots([self.root], max_depth=3), [self.source])

    def test_reject_unknown_build_and_executable_symlink(self):
        self.assertEqual(launcher.validate_source(self.source)[1], 'repaired')
        (self.source / 'client').write_bytes(b'unknown version')
        with self.assertRaisesRegex(ValueError, '不支持'):
            launcher.validate_source(self.source)
        (self.source / 'client').unlink()
        (self.source / 'client').symlink_to(self.root / 'outside')
        with self.assertRaisesRegex(ValueError, '符号链接'):
            launcher.validate_source(self.source)

    def test_entitlements_keep_sandbox_and_scope_to_final_location(self):
        original = {launcher.SANDBOX: True, launcher.SBPL: ['existing']}
        app = self.root / '中文 game.app'
        result = launcher.scoped_entitlements(original, app)
        self.assertTrue(result[launcher.SANDBOX])
        self.assertIn(str(app), result[launcher.SBPL][-1])
        self.assertEqual(original[launcher.SBPL], ['existing'])
        self.assertEqual(launcher.scoped_entitlements(result, app), result)
        with self.assertRaises(ValueError):
            launcher.scoped_entitlements({}, app)

    def test_settings_enable_native_scroll_and_restore_only_owned_fields(self):
        settings = self.root / 'settings.plist'
        backup = self.root / 'before.plist'
        settings.write_bytes(plistlib.dumps({'keymapping': True, 'rootWorkDir': True,
                                            'resolution': 2}))
        launcher.configure_settings(settings, backup)
        value = plistlib.loads(settings.read_bytes())
        self.assertFalse(value['keymapping'])
        self.assertFalse(value['rootWorkDir'])
        self.assertFalse(value['disableBuiltinMouse'])
        self.assertTrue(value['enableScrollWheel'])
        saved = backup.read_bytes()
        launcher.configure_settings(settings, backup)
        self.assertEqual(backup.read_bytes(), saved)
        value['resolution'] = 3
        settings.write_bytes(plistlib.dumps(value))
        launcher.restore_settings(settings, backup)
        restored = plistlib.loads(settings.read_bytes())
        self.assertTrue(restored['keymapping'])
        self.assertTrue(restored['rootWorkDir'])
        self.assertEqual(restored['resolution'], 3)
        self.assertNotIn('enableScrollWheel', restored)

    def test_bad_settings_are_not_overwritten(self):
        settings = self.root / 'bad.plist'
        settings.write_bytes(b'broken')
        with self.assertRaises(ValueError):
            launcher.configure_settings(settings, self.root / 'backup')
        self.assertEqual(settings.read_bytes(), b'broken')

    def fake_run(self, args, *positional, **kwargs):
        if args[0] == '/usr/bin/ditto':
            shutil.copytree(args[-2], args[-1], symlinks=True)
        if '--entitlements' in args and '-d' in args:
            return type('Result', (), {'stdout': plistlib.dumps({launcher.SANDBOX: True})})()
        return type('Result', (), {'stdout': b''})()

    def test_prepare_adds_autoload_signs_and_reuses_verified_output(self):
        state = self.root / 'managed'
        with patch.object(launcher, 'run', side_effect=self.fake_run) as run:
            app = launcher.prepare(self.source, state, self.payload)
            self.assertIn(launcher.LOAD_PATH.encode(), (app / 'client').read_bytes())
            for name in launcher.PAYLOAD:
                target = launcher.INSTALLED_NAMES.get(name, name)
                self.assertEqual((app / 'PCSupport' / target).read_bytes(),
                                 (self.payload / name).read_bytes())
            manifest = json.loads((state / 'manifest.json').read_text())
            self.assertEqual(manifest['app'], str(app))
            self.assertEqual(launcher.prepared_app(state, self.payload), app)
            calls = [c.args[0] for c in run.call_args_list]
            self.assertTrue(any('--sign' in c and str(app) in c for c in calls))
            (app / 'PCSupport/input_state.py').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, '校验'):
                launcher.prepared_app(state, self.payload)

    def test_failed_signing_keeps_source_and_does_not_publish_manifest(self):
        state = self.root / 'managed'
        def fail(args, *positional, **kwargs):
            if '--sign' in args:
                raise OSError('sign failure')
            return self.fake_run(args, **kwargs)
        with patch.object(launcher, 'run', side_effect=fail):
            with self.assertRaises(OSError):
                launcher.prepare(self.source, state, self.payload)
        self.assertEqual((self.source / 'client').read_bytes(), self.data)
        self.assertFalse((state / 'manifest.json').exists())
        self.assertFalse((state / launcher.APP_NAME).exists())
        self.assertTrue(list(state.glob('failed-*')))

    def test_output_inside_source_is_rejected_before_copy(self):
        with patch.object(launcher, 'run') as run:
            with self.assertRaises(ValueError):
                launcher.prepare(self.source, self.source / 'state', self.payload)
            run.assert_not_called()

    def test_existing_unmanaged_output_is_not_overwritten(self):
        state = self.root / 'managed'
        app = state / launcher.APP_NAME
        app.mkdir(parents=True)
        with patch.object(launcher, 'run') as run:
            with self.assertRaises(FileExistsError):
                launcher.prepare(self.source, state, self.payload)
            run.assert_not_called()

    def launch_fixture(self):
        documents = self.root / f'Library/Containers/{launcher.BUNDLE_ID}/Data/Documents'
        documents.mkdir(parents=True)
        settings = self.root / f'Library/Containers/io.playcover.PlayCover/App Settings/{launcher.BUNDLE_ID}.plist'
        settings.parent.mkdir(parents=True)
        settings.write_bytes(plistlib.dumps(dict(keymapping=True, enableScrollWheel=False)))
        patch.object(launcher.Path, 'home', return_value=self.root).start()
        patch.object(launcher, 'run').start()
        return self.root / launcher.APP_NAME, self.root / 'state', settings

    def test_launch_configures_scroll_and_opens_without_duplicate_flag(self):
        app, state, settings = self.launch_fixture()
        with patch.object(launcher, 'game_processes', side_effect=[{}, {100: app}]), \
                patch.object(launcher, 'run') as run:
            launcher.launch(app, state)
        run.assert_any_call([launcher.LSREGISTER, '-f', str(app)])
        run.assert_any_call(['/usr/bin/open', str(app), '--args', '-ApplePersistenceIgnoreState', 'YES'])
        self.assertEqual(run.call_count, 2)
        actual = plistlib.loads(settings.read_bytes())
        self.assertTrue(actual['enableScrollWheel'])
        self.assertFalse(actual['keymapping'])

    def test_metal_hud_is_scoped_to_the_launched_game(self):
        app, state, _ = self.launch_fixture()
        with patch.object(launcher, 'game_processes', side_effect=[{}, {100: app}]), \
                patch.object(launcher, 'run') as run:
            launcher.launch(app, state, metal_hud=True)
        run.assert_any_call(['/usr/bin/open', '--env', 'MTL_HUD_ENABLED=1',
                             str(app), '--args', '-ApplePersistenceIgnoreState', 'YES'])

    def test_metal_hud_on_running_process_requires_restart(self):
        app, state, settings = self.launch_fixture()
        before = settings.read_bytes()
        with patch.object(launcher, 'game_processes', return_value={100: app}):
            with self.assertRaisesRegex(ValueError, '--restart'):
                launcher.launch(app, state, metal_hud=True)
        self.assertEqual(before, settings.read_bytes())

    def test_restart_rebuild_closes_managed_app_before_preparing(self):
        state = self.root / '.pc-launcher'
        app = state / launcher.APP_NAME
        order = []
        with patch.object(launcher, 'PROJECT', self.root), \
                patch.object(launcher, 'discover', return_value=[self.source]), \
                patch.object(launcher, 'prepare', side_effect=lambda *a, **kw: order.append('prepare') or app), \
                patch.object(launcher, 'stop_games', side_effect=lambda p: order.append('stop')), \
                patch.object(launcher, 'game_processes', return_value={100: app}), \
                patch.object(launcher, 'launch'), \
                patch('sys.argv', ['launcher.py', '--rebuild', '--restart']):
            self.assertEqual(launcher.main(), 0)
        self.assertEqual(order, ['stop', 'prepare'])

    def test_running_managed_app_is_reused_without_claiming_settings_reload(self):
        app, state, settings = self.launch_fixture()
        before = settings.read_bytes()
        with patch.object(launcher, 'game_processes', return_value={100: app}), \
                patch.object(launcher, 'run') as run:
            launcher.launch(app, state)
        self.assertEqual(before, settings.read_bytes())
        run.assert_any_call(['/usr/bin/open', str(app)])
        self.assertEqual(run.call_count, 2)

    def test_restart_includes_current_managed_process_and_waits_for_exit(self):
        app, state, settings = self.launch_fixture()
        with patch.object(launcher, 'game_processes', side_effect=[{100: app}, {100: app}, {}, {101: app}]), \
                patch.object(launcher.os, 'kill') as kill, patch.object(launcher, 'run'):
            launcher.launch(app, state, restart=True)
        kill.assert_called_once_with(100, launcher.signal.SIGTERM)
        self.assertTrue(plistlib.loads(settings.read_bytes())['enableScrollWheel'])

    def test_other_game_requires_restart_without_touching_settings(self):
        app, state, settings = self.launch_fixture()
        before = settings.read_bytes()
        with patch.object(launcher, 'game_processes', return_value={100: self.source}), \
                patch.object(launcher.os, 'kill') as kill:
            with self.assertRaisesRegex(ValueError, '--restart'):
                launcher.launch(app, state)
        kill.assert_not_called()
        self.assertEqual(before, settings.read_bytes())

    def test_launch_failure_restores_owned_settings(self):
        app, state, settings = self.launch_fixture()
        before = plistlib.loads(settings.read_bytes())
        def fail_open(args):
            if args[0] == '/usr/bin/open':
                raise OSError('open failed')
        with patch.object(launcher, 'game_processes', return_value={}), \
                patch.object(launcher, 'run', side_effect=fail_open):
            with self.assertRaises(OSError):
                launcher.launch(app, state)
        self.assertEqual(before, plistlib.loads(settings.read_bytes()))

    def test_cache_creation_failure_restores_settings(self):
        app, state, settings = self.launch_fixture()
        cache = self.root / f'Library/Containers/{launcher.BUNDLE_ID}/Data/Documents/local_shader_cache'
        cache.write_bytes(b'not a directory')
        before = plistlib.loads(settings.read_bytes())
        with patch.object(launcher, 'game_processes', return_value={}), \
                patch.object(launcher, 'run') as run:
            with self.assertRaises(OSError):
                launcher.launch(app, state)
        self.assertEqual(before, plistlib.loads(settings.read_bytes()))
        run.assert_called_once_with([launcher.LSREGISTER, '-f', str(app)])
        self.assertTrue((state / 'settings-before.plist').is_file())

    def test_restart_rejects_process_identity_change(self):
        app, state, _ = self.launch_fixture()
        with patch.object(launcher, 'game_processes', side_effect=[{100: self.source}, {100: app}]), \
                patch.object(launcher.os, 'kill') as kill:
            with self.assertRaisesRegex(ValueError, '进程发生变化'):
                launcher.launch(app, state, restart=True)
        kill.assert_not_called()

    def test_restart_timeout_never_force_kills_or_updates_settings(self):
        app, state, settings = self.launch_fixture()
        before = settings.read_bytes()
        with patch.object(launcher, 'game_processes', return_value={100: app}), \
                patch.object(launcher.os, 'kill') as kill, \
                patch.object(launcher.time, 'monotonic', side_effect=[0, 21]):
            with self.assertRaises(TimeoutError):
                launcher.launch(app, state, restart=True)
        kill.assert_called_once_with(100, launcher.signal.SIGTERM)
        self.assertEqual(before, settings.read_bytes())


if __name__ == '__main__':
    unittest.main()
