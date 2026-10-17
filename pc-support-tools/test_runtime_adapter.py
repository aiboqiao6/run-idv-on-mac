"""Run the actual adapter against a minimal engine boundary, without a game."""
import ast
import os
from pathlib import Path
import socket
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent


class RuntimeAdapterTests(unittest.TestCase):
    def make_controller(self):
        timer = types.SimpleNamespace(TimerManager=Mock())
        ui_namespace = {'timer': timer}
        exec('class UIBattlePC:\n def get_dir(self): pass\n def _get_view(self): pass', ui_namespace)
        ui_type = ui_namespace['UIBattlePC']
        class UIHall:
            def get_view(self):
                return (0, 0)
        platform = types.SimpleNamespace(is_pc=lambda: False,
            check_use_pc_logic=lambda: False, _refresh_pc_like_platform=Mock())
        utils = types.SimpleNamespace(g_b_lock_cursor=True, g_b_window_focused=False,
            show_sys_cursor=Mock(), set_cursor_centered=Mock(),
            is_cursor_locked=lambda: False, set_cursor_battle_mode=Mock(), lock_cursor=Mock())
        utils.set_cursor_battle_mode.side_effect = lambda value, **kw: setattr(utils, 'g_b_lock_cursor', value)
        game3d = types.SimpleNamespace(is_pc=lambda: False,
            get_all_key_state=lambda: [], get_platform=lambda: 3)
        game = types.SimpleNamespace(set_mouse_delta=Mock(), set_mouse_pos=Mock(),
            mouse_dx=0, mouse_dy=0, MOUSE_BUTTON_LEFT=1,
            MSG_MOUSE_DOWN=1, MSG_MOUSE_UP=2, MSG_MOUSE_WHEEL=3)
        gk = types.SimpleNamespace(g_key_handler_mgr=Mock(), input=None,
            g_screen_center=(864, 540), g_design_size=(1334, 834))
        gk.g_key_handler_mgr.key2op_lst = {}
        gk.g_key_handler_mgr.load_ok = True
        gk.g_key_handler_mgr.on_mouse_wheel_pre.return_value = False
        pc = types.ModuleType('core.key_handlers.pc')
        pc.GK, pc.game, pc.game3d = gk, game, game3d
        pc.clear_all_press_state = Mock()
        modules = {name: types.ModuleType(name) for name in
            ('core', 'core.key_handlers', 'common_tools', 'ui', 'ui.UIBattlePC', 'ui.UIHall')}
        modules['core.key_handlers.pc'] = pc
        modules['cc'] = Mock()
        modules['core'].key_handlers = modules['core.key_handlers']
        modules['core.key_handlers'].pc = pc
        modules['common_tools'].PlatformUtil = platform
        modules['common_tools'].utils = utils
        modules['ui.UIBattlePC'].UIBattlePC = ui_type
        modules['ui.UIHall'].UIHall = UIHall
        tree = ast.parse((ROOT / 'runtime_adapter.py').read_text())
        tree.body.pop()  # Bootstrap is performed explicitly below.
        namespace = {'SUPPORT_DIR': str(ROOT)}
        with patch.dict(sys.modules, modules):
            exec(compile(tree, 'runtime_adapter.py', 'exec'), namespace)
        controller = namespace['PCSupport'](-1)
        controller.command = Mock()
        controller.log = Mock()
        controller.rebuild_ui = Mock()
        return controller, utils, platform, game3d

    def test_keymap_silent_failure_does_not_advertise_ready_and_retries(self):
        controller, _, _, _ = self.make_controller()
        manager = controller.install.__globals__['GK'].g_key_handler_mgr
        manager.load_ok = False
        with patch('time.monotonic', return_value=10):
            controller.install()
            controller.tick()
        self.assertFalse(controller.keymap_ready)
        self.assertFalse(any(c.kwargs.get('ready') for c in controller.command.call_args_list))
        manager.init_key_map.assert_called_once()
        manager.load_ok = True
        with patch('time.monotonic', return_value=11.1):
            controller.tick()
        self.assertTrue(controller.keymap_ready)
        self.assertTrue(any(c.kwargs.get('ready') for c in controller.command.call_args_list))
        controller.stop()

    def test_hall_camera_drains_latest_free_pointer_and_retains_game_view(self):
        controller, _, _, _ = self.make_controller()
        scope = controller.install.__globals__
        hall_type, gk = scope['UIHall'], scope['GK']
        point = lambda x, y: types.SimpleNamespace(x=x, y=y)
        scope['cc'].Vec2.side_effect = point
        seen = []
        def original(ui):
            seen.append((ui.cur_rotate_pos_pc, ui.pre_rotate_pos_pc))
            return ('game sensitivity', 'game clamps')
        hall_type.get_view = original
        controller.install()
        ui = hall_type()
        ui.cur_rotate_pos = point(80, 50)
        ui.pre_rotate_pos = point(60, 50)
        ui.cur_rotate_pos_pc = ui.pre_rotate_pos_pc = None
        ui.set_pc_rotate_pos = lambda p: setattr(ui, 'cur_rotate_pos_pc', p)
        ui.set_pc_pre_rotate_pos = lambda p: setattr(ui, 'pre_rotate_pos_pc', p)
        gk.input = ui
        controller.focus = True
        controller.drain_frames = Mock(side_effect=lambda: controller.consume(dict(
            kind='motion', active=True, locked=False, dx=0, dy=0,
            x=90, y=55, width=1334, height=834)))
        self.assertEqual(ui.get_view(), ('game sensitivity', 'game clamps'))
        self.assertEqual((seen[-1][0].x, seen[-1][0].y), (90, 55))
        self.assertEqual((seen[-1][1].x, seen[-1][1].y), (60, 50))
        self.assertIsNone(ui.cur_rotate_pos_pc)
        self.assertIsNone(ui.pre_rotate_pos_pc)
        ui.get_view()
        self.assertEqual((seen[-1][1].x, seen[-1][1].y), (90, 55))
        # Mouse samples cannot start a drag the game has not accepted.
        ui.cur_rotate_pos = None
        ui.get_view()
        self.assertEqual(seen[-1], (None, None))
        controller.stop()

    def test_free_motion_updates_pointer_without_touching_keyboard_or_captured_delta(self):
        controller, _, _, _ = self.make_controller()
        controller.focus = True
        controller.input.keys = {87}
        controller.consume(dict(kind='motion', active=True, locked=False, dx=0, dy=0,
                                x=50, y=25, width=100, height=100))
        self.assertEqual(controller.pointer_position, (667, 208.5))
        self.assertEqual(controller.input.keys, {87})
        controller.consume.__globals__['game'].set_mouse_delta.assert_not_called()

    def test_hall_camera_aborts_when_pending_input_changes_scene(self):
        controller, _, _, _ = self.make_controller()
        scope = controller.install.__globals__
        original = Mock(return_value=(1, 2))
        scope['UIHall'].get_view = original
        controller.install()
        ui = scope['UIHall']()
        scope['GK'].input = ui
        controller.drain_frames = Mock(side_effect=lambda: setattr(scope['GK'], 'input', object()))
        self.assertEqual(ui.get_view(), (0, 0))
        original.assert_not_called()
        controller.stop()

    def test_missing_window_bounds_discard_stale_hall_pointer(self):
        controller, _, _, _ = self.make_controller()
        controller.pointer_position = (50, 20)
        controller.view_pointer = (object(), (40, 20))
        controller.focus = True
        controller.consume(dict(kind='motion', active=True, locked=False, dx=0, dy=0,
                                x=0, y=0, width=0, height=0))
        self.assertIsNone(controller.pointer_position)
        self.assertIsNone(controller.view_pointer)

    def test_wheel_reaches_pc_handler_with_both_directions_and_fractional_delta(self):
        controller, _, _, _ = self.make_controller()
        scope = controller.consume.__globals__
        manager = scope['GK'].g_key_handler_mgr
        for sequence, delta in enumerate((1.0, -1.0, 0.25), 1):
            controller.consume(dict(seq=sequence, active=True, keys=[], events=[], wheel=delta))
            manager.on_mouse_wheel_pre.assert_called_with(scope['game'].MSG_MOUSE_WHEEL, delta, 0)
            manager.on_mouse_wheel.assert_called_with(scope['game'].MSG_MOUSE_WHEEL, delta, 0)

    def test_wheel_respects_game_block_and_inactive_window(self):
        controller, _, _, _ = self.make_controller()
        manager = controller.consume.__globals__['GK'].g_key_handler_mgr
        manager.on_mouse_wheel_pre.return_value = True
        controller.consume(dict(seq=1, active=True, keys=[], events=[], wheel=1))
        manager.on_mouse_wheel.assert_not_called()
        manager.on_mouse_wheel_pre.reset_mock()
        controller.consume(dict(seq=2, active=False, keys=[], events=[], wheel=-1))
        manager.on_mouse_wheel_pre.assert_not_called()
        manager.on_mouse_wheel.assert_not_called()

    def test_invalid_wheel_is_rejected_before_game_callback(self):
        for value in (float('nan'), float('inf'), '1', True):
            controller, _, _, _ = self.make_controller()
            with self.assertRaises(ValueError):
                controller.consume(dict(seq=1, active=True, keys=[], events=[], wheel=value))
            controller.consume.__globals__['GK'].g_key_handler_mgr.on_mouse_wheel.assert_not_called()

    def test_cursor_release_and_relock_observe_policy_on_ios(self):
        controller, utils, _, _ = self.make_controller()
        self.assertFalse(utils.is_cursor_locked())  # iOS's original Win32 gate
        controller.install()
        self.assertFalse(utils.is_cursor_locked())  # Installation starts released.
        # Same decision used by the retained check_show_cursor handler.
        for expected in (True, False, True, False):
            utils.g_b_lock_cursor = not utils.is_cursor_locked()
            self.assertEqual(utils.is_cursor_locked(), expected)
        controller.stop()
        self.assertFalse(utils.is_cursor_locked())

    def test_install_preserves_game_selected_city_handler_and_releases_stale_capture(self):
        controller, utils, _, _ = self.make_controller()
        manager = controller.install.__globals__['GK'].g_key_handler_mgr
        city_handler = manager.cur_handler
        controller.install()
        manager.set_mode.assert_not_called()
        self.assertIs(manager.cur_handler, city_handler)
        utils.set_cursor_battle_mode.assert_called_once_with(False, force=True)

    def test_hall_focus_regain_does_not_request_battle_capture(self):
        controller, utils, _, _ = self.make_controller()
        scope = controller.consume.__globals__
        scope['GK'].input = types.SimpleNamespace()
        manager = scope['GK'].g_key_handler_mgr
        for seq, active in enumerate((True, False, True), 1):
            controller.consume(dict(seq=seq, active=active, keys=[], events=[]))
        utils.set_cursor_battle_mode.assert_not_called()
        manager.set_mode.assert_not_called()

    def test_focus_regain_uses_current_game_ui_cursor_policy(self):
        controller, utils, _, _ = self.make_controller()
        ui = types.SimpleNamespace(check_relock_cursor=Mock())
        controller.consume.__globals__['GK'].input = ui
        controller.consume(dict(seq=1, active=True, keys=[], events=[]))
        ui.check_relock_cursor.assert_called_once_with()
        utils.set_cursor_battle_mode.assert_not_called()

    def test_scene_transition_releases_capture_without_forcing_a_key_mode(self):
        controller, utils, _, _ = self.make_controller()
        scope = controller.tick.__globals__
        scope['GK'].input = types.SimpleNamespace()
        controller.focus = True
        controller.tick()
        utils.set_cursor_battle_mode.assert_called_once_with(False, force=True)
        scope['GK'].g_key_handler_mgr.set_mode.assert_not_called()

    def test_missing_native_key_query_is_added_and_removed_on_stop(self):
        controller, _, platform, game3d = self.make_controller()
        self.assertFalse(hasattr(game3d, 'is_key_down'))
        controller.install()
        controller.input.keys.add(87)
        self.assertTrue(game3d.is_key_down(87))
        self.assertTrue(platform.is_pc())
        controller.stop()
        self.assertFalse(hasattr(game3d, 'is_key_down'))
        self.assertFalse(platform.is_pc())

    def test_shutdown_releases_native_even_if_game_key_handler_raises(self):
        controller, _, platform, _ = self.make_controller()
        controller.install()
        controller.input.keys = {87, 68}
        controller.dispatch = Mock(side_effect=RuntimeError('game handler failed'))
        controller.stop()
        controller.command.assert_called_with(stop=True, lock=False)
        self.assertFalse(controller.active)
        self.assertEqual(controller.input.keys, set())
        self.assertEqual(controller.dispatch.call_count, 2)
        self.assertFalse(platform.is_pc())

    def test_ui_pointer_is_visible_to_pc_button_validation(self):
        controller, _, _, game3d = self.make_controller()
        controller.install()
        controller.ui_pointer = (150, 724)
        self.assertTrue(game3d.is_key_down(1))
        self.assertIn(1, game3d.get_all_key_state())
        controller.ui_pointer = None
        self.assertFalse(game3d.is_key_down(1))
        controller.stop()

    def test_ui_hold_is_cancelled_on_capture_and_up_is_not_a_game_click(self):
        controller, _, _, _ = self.make_controller()
        controller.ui_pointer_event = Mock()
        controller.dispatch = Mock()
        base = dict(active=True, keys=[], width=100, height=100, x=25, y=25)
        controller.consume(dict(base, seq=1, locked=False, events=[[1, 1]]))
        self.assertIn(1, controller.key_state())
        controller.consume(dict(base, seq=2, locked=True, events=[]))
        self.assertNotIn(1, controller.key_state())
        self.assertIsNone(controller.ui_pointer)
        controller.consume(dict(base, seq=3, locked=True, events=[[2, 1]]))
        controller.dispatch.assert_not_called()
        self.assertIsNone(controller.ui_pointer)

    def test_ui_click_remains_held_until_its_end_callback(self):
        controller, _, _, _ = self.make_controller()
        states = []
        controller.ui_pointer_event = Mock(side_effect=lambda phase, point:
            states.append(1 in controller.key_state()))
        base = dict(active=True, keys=[], width=100, height=100, x=25, y=25, locked=False)
        controller.consume(dict(base, seq=1, events=[[1, 1]]))
        controller.consume(dict(base, seq=2, events=[[2, 1]]))
        self.assertTrue(all(states))
        self.assertNotIn(1, controller.key_state())

    def test_delayed_free_cursor_edge_does_not_become_gameplay_down(self):
        controller, _, _, _ = self.make_controller()
        controller.dispatch = Mock()
        base = dict(active=True, keys=[], width=100, height=100, x=25, y=25, locked=True)
        controller.consume(dict(base, seq=1, events=[[1, 1, False]]))
        controller.consume(dict(base, seq=2, events=[[2, 1, True]]))
        controller.dispatch.assert_not_called()
        self.assertNotIn(1, controller.key_state())

    def test_ui_up_uses_gesture_owner_even_if_capture_changed_twice(self):
        controller, _, _, _ = self.make_controller()
        controller.ui_pointer_event = Mock()
        controller.dispatch = Mock()
        base = dict(active=True, keys=[], width=100, height=100, x=25, y=25, locked=False)
        controller.consume(dict(base, seq=1, events=[[1, 1, False]]))
        controller.consume(dict(base, seq=2, events=[[2, 1, True]]))
        self.assertIsNone(controller.ui_pointer)
        self.assertNotIn(1, controller.key_state())
        controller.dispatch.assert_not_called()

    def test_ui_up_without_window_bounds_cancels_instead_of_sticking(self):
        controller, _, _, _ = self.make_controller()
        controller.ui_pointer_event = Mock()
        controller.consume(dict(seq=1, active=True, keys=[], locked=False, events=[[1, 1]],
                                width=100, height=100, x=25, y=25))
        controller.consume(dict(seq=2, active=True, keys=[], locked=False, events=[[2, 1]]))
        self.assertIsNone(controller.ui_pointer)
        self.assertNotIn(1, controller.key_state())

    def test_capture_error_releases_policy_and_held_inputs(self):
        controller, utils, _, _ = self.make_controller()
        controller.input.keys = {87}
        controller.consume(dict(seq=1, active=True, keys=[87], events=[], locked=False,
                                cursor_error=1000))
        utils.lock_cursor.assert_called_with(False, force=True)
        self.assertEqual(controller.input.keys, set())
        controller.command.assert_called_with(lock=False)

    def test_capture_error_does_not_dispatch_new_key_down_before_release(self):
        controller, _, _, _ = self.make_controller()
        controller.dispatch = Mock()
        controller.consume(dict(seq=1, active=True, keys=[87], events=[], locked=False,
                                cursor_error=1000))
        self.assertFalse(any(call.args == (4, 87) for call in controller.dispatch.call_args_list))

    def test_relative_camera_preserves_native_delta_direction_and_recenters(self):
        controller, utils, _, _ = self.make_controller()
        scope = controller.install.__globals__
        game, gk, ui_type = scope['game'], scope['GK'], scope['UIBattlePC']
        positions = []
        game.set_mouse_pos = Mock(side_effect=lambda x, y: positions.append((x, y)))
        game.get_and_reset_mouse_delta = Mock(return_value=(12, -9))
        gk.g_screen_center = (864, 540)
        observed = []
        ui_type._get_view = lambda ui: observed.append(positions[-1])
        controller.install()
        controller.focus = True
        utils.g_b_lock_cursor = True
        ui_type()._get_view()
        # NSEvent deltaY already follows PC view coordinates: up is negative.
        self.assertEqual(observed, [(876, 531)])
        self.assertEqual(positions[-1], (864, 540))
        controller.stop()

    def test_absolute_pointer_uses_pc_top_left_origin_for_radial_menus(self):
        controller, _, _, _ = self.make_controller()
        game = controller.consume.__globals__['game']
        for seq, x, y, expected in ((1, 665, 831, (864, 0)),
                                    (2, 665, 0, (864, 1080)),
                                    (3, 1330, 415.5, (1728, 540))):
            frame = dict(seq=seq, active=True, keys=[], events=[], locked=False,
                         width=1330, height=831, x=x, y=y)
            controller.consume(frame)
            game.set_mouse_pos.assert_called_with(*expected)
            # Cocos UI dispatch retains its bottom-left design coordinates.
            self.assertEqual(controller.ui_pointer_position(frame),
                             (x * 1334 / 1330, y * 834 / 831))

    def test_camera_reads_pending_motion_before_applying_this_frame(self):
        controller, utils, _, _ = self.make_controller()
        scope = controller.install.__globals__
        game, ui_type = scope['game'], scope['UIBattlePC']
        game.get_and_reset_mouse_delta = Mock(return_value=(0, 0))
        controller.drain_frames = Mock(side_effect=lambda:
            setattr(game.get_and_reset_mouse_delta, 'return_value', (18, -6)))
        controller.install()
        controller.focus = True
        utils.g_b_lock_cursor = True
        ui_type()._get_view()
        controller.drain_frames.assert_called_once()
        self.assertEqual(game.set_mouse_pos.call_args_list[0].args, (882, 534))
        controller.stop()

    def test_pending_key_that_changes_scene_does_not_use_destroyed_camera_ui(self):
        controller, utils, _, _ = self.make_controller()
        scope = controller.install.__globals__
        game, gk, ui_type = scope['game'], scope['GK'], scope['UIBattlePC']
        original_view = Mock(return_value=(4, 5))
        game.get_and_reset_mouse_delta = Mock(return_value=(0, 0))
        ui_type._get_view = original_view
        controller.install()
        ui = ui_type()
        gk.input = ui
        controller.focus = True
        utils.g_b_lock_cursor = True
        controller.drain_frames = Mock(side_effect=lambda: setattr(gk, 'input', object()))
        self.assertEqual(ui._get_view(), (0, 0))
        original_view.assert_not_called()
        game.set_mouse_pos.assert_not_called()
        controller.stop()

    def test_shutdown_restores_game_when_native_channel_is_already_closed(self):
        controller, _, platform, _ = self.make_controller()
        controller.install()
        controller.command = type(controller).command.__get__(controller)
        with patch('os.write', side_effect=OSError('channel closed')):
            controller.stop()
        self.assertFalse(controller.active)
        self.assertTrue(controller.channel_failed)
        self.assertFalse(platform.is_pc())

    def test_event_driven_motion_accumulates_without_releasing_held_keys(self):
        controller, utils, _, _ = self.make_controller()
        controller.install()
        utils.g_b_lock_cursor = True
        game = controller.consume.__globals__['game']
        game.set_mouse_delta.side_effect = lambda x, y: (
            setattr(game, 'mouse_dx', x), setattr(game, 'mouse_dy', y))
        controller.focus = True
        controller.input.keys = {87}
        controller.input.seq = 25
        for dx, dy in ((3.5, -2), (1.5, 4), (-1, -1)):
            controller.consume(dict(kind='motion', active=True, locked=True, dx=dx, dy=dy))
        self.assertEqual((game.mouse_dx, game.mouse_dy), (4, 1))
        self.assertEqual(controller.input.keys, {87})
        self.assertEqual(controller.input.seq, 25)

    def test_captured_motion_is_ignored_after_cursor_release(self):
        controller, utils, _, _ = self.make_controller()
        game = controller.consume.__globals__['game']
        controller.focus = True
        utils.g_b_lock_cursor = False
        controller.consume(dict(kind='motion', active=True, locked=True, dx=50, dy=20))
        game.set_mouse_delta.assert_not_called()

    def test_invalid_event_driven_motion_is_rejected_without_mutating_delta(self):
        controller, _, _, _ = self.make_controller()
        game = controller.consume.__globals__['game']
        controller.focus = True
        with self.assertRaises(ValueError):
            controller.consume(dict(kind='motion', active=True, locked=True, dx=float('nan'), dy=1))
        game.set_mouse_delta.assert_not_called()

    def test_motion_does_not_keep_stale_keyboard_snapshot_alive(self):
        controller, utils, _, _ = self.make_controller()
        original_lock = utils.lock_cursor
        controller.install()
        controller.focus = True
        controller.input.keys = {87}
        controller.last_frame = 10.0
        with patch('time.monotonic', return_value=10.4):
            controller.consume(dict(kind='motion', active=True, locked=True, dx=2, dy=0))
            controller.tick()
        self.assertEqual(controller.input.keys, set())
        original_lock.assert_called_with(False, force=True)

    def test_full_snapshot_motion_obeys_game_cursor_policy(self):
        controller, utils, _, _ = self.make_controller()
        controller.install()
        controller.focus = True
        utils.g_b_lock_cursor = False
        game = controller.consume.__globals__['game']
        controller.consume(dict(seq=1, active=True, keys=[], events=[], locked=True,
                                dx=50, dy=20))
        game.set_mouse_delta.assert_not_called()

    def test_controller_owns_fd_independently_from_native_cleanup(self):
        controller, _, _, _ = self.make_controller()
        producer, native = socket.socketpair(type=socket.SOCK_DGRAM)
        owned = type(controller)(native.fileno())
        owned.command = Mock()
        owned.log = Mock()
        try:
            self.assertNotEqual(owned.fd, native.fileno())
            native.close()
            producer.send(b'still-owned')
            self.assertEqual(os.read(owned.fd, 64), b'still-owned')
            fd = owned.fd
            owned.stop()
            with self.assertRaises(OSError):
                os.fstat(fd)
        finally:
            if owned.fd >= 0:
                os.close(owned.fd)
            native.close()
            producer.close()

    def test_cursor_policy_transition_clears_pending_relative_motion(self):
        controller, utils, _, _ = self.make_controller()
        utils.lock_cursor.side_effect = lambda value, **kw: setattr(utils, 'g_b_lock_cursor', value)
        controller.install()
        game = controller.consume.__globals__['game']
        game.set_mouse_delta.reset_mock()
        utils.g_b_lock_cursor = True
        utils.lock_cursor(False, force=True)
        game.set_mouse_delta.assert_called_once_with(0, 0)
        controller.stop()


if __name__ == '__main__':
    unittest.main()
