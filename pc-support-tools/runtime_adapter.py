"""Adapt native keyboard/mouse events to the retained release PC client logic.

Executed by the exact-build native helper on the engine's main thread with GIL.
The inherited socketpair is private to this process; frames never touch disk.
"""
import json
import math
import os
import sys
import time
import traceback
import types

import core.key_handlers.pc as pc
import cc
from common_tools import PlatformUtil, utils
from ui.UIBattlePC import UIBattlePC
from ui.UIHall import UIHall

GK = pc.GK
game = pc.game
game3d = pc.game3d
timer = UIBattlePC.get_dir.__globals__['timer']
namespace = {}
with open(os.path.join(SUPPORT_DIR, 'input_state.py'), encoding='utf-8') as source:
    exec(compile(source.read(), 'idv_input_state.py', 'exec'), namespace)
InputState = namespace['InputState']


class PCSupport:
    MISSING = object()
    def __init__(self, fd):
        # Own a descriptor: native cleanup may close/reuse its original FD.
        self.fd = os.dup(fd) if fd >= 0 else -1
        self.active = True
        self.focus = False
        self.input = InputState()
        self.mouse_down = set()
        self.suppressed_mouse = set()
        self.ui_pointer = None
        self.cursor_error = 0
        self.last_frame = time.monotonic()
        self.last_ui = None
        self.tick_count = 0
        self.event_count = 0
        self.errors = 0
        self.saved = []
        self.logpath = os.path.expanduser('~/Documents/idv-pc-support.log')
        self.failed_scenes = set()
        self.draining = False
        self.channel_failed = False
        self.keymap_ready = False
        self.keymap_retry_at = 0
        self.pointer_position = None
        self.view_pointer = None

    def log(self, message):
        try:
            if os.path.exists(self.logpath) and os.path.getsize(self.logpath) > 1048576:
                os.replace(self.logpath, self.logpath + '.previous')
            with open(self.logpath, 'a', encoding='utf-8') as out:
                print(time.strftime('%Y-%m-%d %H:%M:%S'), message, file=out)
        except OSError as error:
            print('IDVPC logging failed:', error, file=sys.stderr)

    def command(self, **command):
        if self.channel_failed:
            return
        try:
            os.write(self.fd, json.dumps(command).encode('ascii'))
        except BlockingIOError:
            pass  # A later heartbeat carries the latest desired cursor state.
        except OSError as error:
            self.channel_failed = True
            self.log('NATIVE_COMMAND_FAILED ' + repr(error))
            # Native capture has a separate 0.5s heartbeat watchdog. Do not
            # throw a broken-channel exception through engine camera callbacks.

    def patch(self, obj, name, value):
        self.saved.append((obj, name, getattr(obj, name, self.MISSING)))
        setattr(obj, name, value)

    def rebuild_ui(self):
        manager = getattr(GK, 'g_world_mgr', None)
        world = getattr(manager, 'cur_world', None)
        if not world or not manager.is_world_battle() or not getattr(GK, 'g_unit', None):
            return
        old = GK.input
        if not old or isinstance(old, UIBattlePC):
            return
        name = world.get_ui_battle_name()
        if not name.endswith('PC') or id(world) in self.failed_scenes:
            return
        oldname = vars(old).get('_class_name', type(old).__name__)
        self.release()
        self.log('UI_REBUILD ' + oldname + ' -> ' + name)
        try:
            GK.g_ui_mgr.hide_ui(oldname)
            ui = GK.g_ui_mgr.get_ui(name, True)
            if not ui or not vars(ui).get('root_node'):
                raise RuntimeError('PC UI factory returned an incomplete object')
            GK.input_proxy.set_input_handler(name, ui)
            GK.g_ui_mgr.show_ui(name)
            GK.g_unit.skill_mgr.update_skill_icon_ui()
        except Exception:
            self.failed_scenes.add(id(world))
            self.log('UI_REBUILD_FAILED ' + traceback.format_exc())
            GK.g_ui_mgr.hide_ui(name)
            # Restore the original UI under its original layout-selection gate.
            gate = PlatformUtil.check_use_pc_logic
            try:
                PlatformUtil.check_use_pc_logic = lambda *a, **k: False
                ui = GK.g_ui_mgr.get_ui(oldname, True)
                GK.input_proxy.set_input_handler(oldname, ui)
                GK.g_ui_mgr.show_ui(oldname)
            finally:
                PlatformUtil.check_use_pc_logic = gate

    def dispatch(self, msg, key):
        handler = GK.g_key_handler_mgr.cur_handler
        if handler is None:
            return
        handler(msg, key)
        self.event_count += 1

    def release(self):
        self.pointer_position = self.view_pointer = None
        events = self.input.release()
        events += [(game.MSG_MOUSE_UP, key) for key in sorted(self.mouse_down)]
        self.mouse_down.clear()
        self.suppressed_mouse.clear()
        actions = [lambda msg=msg, key=key: self.dispatch(msg, key) for msg, key in events]
        if isinstance(GK.input, UIBattlePC):
            actions.append(GK.input.clear_press_info)
        actions.extend((pc.clear_all_press_state, lambda: game.set_mouse_delta(0, 0)))
        if self.ui_pointer is not None:
            x, y = self.ui_pointer
            self.ui_pointer = None
            actions.append(lambda: self.ui_pointer_event(cc.EVENTTOUCH_EVENTCODE_CANCELLED, (x, y)))
        for action in actions:
            try:
                action()
            except Exception:
                self.log('RELEASE_FAILED ' + traceback.format_exc())

    def ui_pointer_event(self, phase, point):
        # Per-phase fake events allocate different Touch objects, which cannot
        # match Cocos claimed-touch pointers. Paired clicks share one object.
        if phase != cc.EVENTTOUCH_EVENTCODE_ENDED:
            return
        director = cc.Director.getInstance()
        director.getEventDispatcher().dispatchSingleFakeTouchBeginEndEventByScreen(
            director.convertToUI(cc.Vec2(*point)))

    def ui_pointer_position(self, frame):
        width, height = frame.get('width', 0), frame.get('height', 0)
        if width <= 0 or height <= 0:
            return None
        dw, dh = GK.g_design_size
        return (frame.get('x', 0) * dw / width, frame.get('y', 0) * dh / height)

    def key_state(self):
        keys = self.input.keys | self.mouse_down
        if self.ui_pointer is not None:
            keys = keys | {game.MOUSE_BUTTON_LEFT}
        return keys

    def resume_cursor(self):
        """Ask the current game UI to restore its own capture policy.

        City UIs intentionally have no battle capture callback. In particular,
        gaining focus must not lock a city cursor whose handler cannot unlock it.
        """
        callback = getattr(GK.input, 'check_relock_cursor', None)
        if self.focus and callable(callback):
            callback()

    def prepare_view(self):
        """Sample immediately before any supported camera consumes input."""
        if not self.active or self.draining:
            return False
        previous = (GK.input, getattr(GK, 'g_unit', None),
                    getattr(getattr(GK, 'g_world_mgr', None), 'cur_world', None))
        try:
            self.drain_frames()
        except Exception:
            self.log('VIEW_INPUT_FAILED ' + traceback.format_exc())
            self.stop('camera input channel failed')
            return False
        current = (GK.input, getattr(GK, 'g_unit', None),
                   getattr(getattr(GK, 'g_world_mgr', None), 'cur_world', None))
        return self.active and all(a is b for a, b in zip(previous, current))

    def init_keymap(self):
        """The game's initializer swallows failures; acknowledge actual readiness."""
        now = time.monotonic()
        if self.keymap_ready or now < self.keymap_retry_at:
            return
        self.keymap_retry_at = now + 1
        manager = GK.g_key_handler_mgr
        manager.init_key_map(use_default=False, do_not_set=True)
        if manager.load_ok is not True:
            if not getattr(self, 'keymap_wait_logged', False):
                self.log('WAIT_KEYMAP game data is not ready')
                self.keymap_wait_logged = True
            return
        self.keymap_ready = True
        self.rebuild_ui()
        self.command(ready=True, lock=False)
        self.log('READY bindings=%d native_platform=%s' % (
            len(manager.key2op_lst), game3d.get_platform()))

    def install(self):
        old = getattr(pc, '_idv_native_bridge', None)
        if old:
            old['restore']('replaced by complete input adapter')
        # Scope PC identity to presentation/input logic. Native platform stays iOS.
        self.patch(PlatformUtil, 'is_pc', lambda: True)
        self.patch(PlatformUtil, 'check_use_pc_logic', lambda *a, **k: True)
        self.patch(game3d, 'is_pc', lambda: True)
        self.patch(game3d, 'is_key_down', lambda key: key in self.key_state())
        self.patch(game3d, 'get_all_key_state', lambda: sorted(self.key_state()))
        PlatformUtil._refresh_pc_like_platform()
        # Native cursor operations are absent on iOS. Keep game's menu/aiming
        # policy, and implement only its platform-specific effects here.
        self.patch(utils, 'show_sys_cursor', lambda *a, **k: None)
        self.patch(utils, 'set_cursor_centered', lambda *a, **k: None)
        # The retained query gates on is_win32(), unlike lock_cursor's is_pc().
        # Catalyst must report the same policy flag that drives native capture.
        self.patch(utils, 'is_cursor_locked', lambda: bool(utils.g_b_lock_cursor))
        original_lock = utils.lock_cursor

        def lock_cursor(*args, **kwargs):
            before = utils.is_cursor_locked()
            result = original_lock(*args, **kwargs)
            if before != utils.is_cursor_locked():
                game.set_mouse_delta(0, 0)
            return result

        self.patch(utils, 'lock_cursor', lock_cursor)
        original_view = UIBattlePC._get_view

        def relative_view(ui, *args, **kwargs):
            # The engine timer may run after camera input in a given frame.
            # Drain pending native samples here so a timer phase cannot make
            # the camera reuse a previous frame or alternate zero/bursts.
            # A queued key/button may close this UI or transition the world.
            # Do not resume a camera call against an object just invalidated.
            if not self.prepare_view():
                return (0, 0)
            if not self.focus or not utils.is_cursor_locked():
                return original_view(ui, *args, **kwargs)
            dx, dy = game.get_and_reset_mouse_delta()
            cx, cy = GK.g_screen_center
            # NSEvent deltaY already has the PC view sign (up is negative).
            # Absolute AppKit pointer coordinates use a different convention.
            game.set_mouse_pos(int(cx) + dx, int(cy) + dy)
            try:
                # Retain the game's sensitivity, skill aiming and view clamps.
                return original_view(ui, *args, **kwargs)
            finally:
                game.set_mouse_pos(int(cx), int(cy))

        self.patch(UIBattlePC, '_get_view', relative_view)
        original_hall_view = UIHall.get_view

        def hall_view(ui, *args, **kwargs):
            if not self.prepare_view():
                return (0, 0)
            # The game decides whether a pointer gesture owns camera rotation.
            # Supply its retained PC coordinate inputs, preserving its original
            # sensitivity, axis selection and clamps. No button/action binding.
            point = self.pointer_position
            if (not self.focus or point is None or
                    getattr(ui, 'cur_rotate_pos', None) is None):
                self.view_pointer = None
                return original_hall_view(ui, *args, **kwargs)
            previous = self.view_pointer
            if previous is None or previous[0] is not ui:
                pre = getattr(ui, 'pre_rotate_pos', None) or ui.cur_rotate_pos
            else:
                pre = cc.Vec2(*previous[1])
            self.view_pointer = (ui, point)
            old_cur = ui.cur_rotate_pos_pc
            old_pre = ui.pre_rotate_pos_pc
            ui.set_pc_pre_rotate_pos(pre)
            ui.set_pc_rotate_pos(cc.Vec2(*point))
            try:
                return original_hall_view(ui, *args, **kwargs)
            finally:
                ui.set_pc_rotate_pos(old_cur)
                ui.set_pc_pre_rotate_pos(old_pre)

        self.patch(UIHall, 'get_view', hall_view)
        # World/input transitions select CITY/BRANCH/BATTLE/etc themselves.
        # Starting this bridge must not replace a game-selected handler or
        # leave an old scene's capture flag set before the first native frame.
        utils.set_cursor_battle_mode(False, force=True)
        self.init_keymap()
        self.scheduled = timer.TimerManager.add_timer(0.01, self.tick)

    def add_motion(self, dx, dy):
        """Preserve the sum of independently delivered relative samples."""
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (dx, dy)):
            raise ValueError('invalid mouse displacement')
        game.set_mouse_delta(game.mouse_dx + dx, game.mouse_dy + dy)

    def consume(self, frame):
        if not isinstance(frame, dict):
            raise ValueError('native packet must be an object')
        if frame.get('kind') == 'motion':
            if type(frame.get('active')) is not bool or type(frame.get('locked')) is not bool:
                raise ValueError('invalid motion capture state')
            dx, dy = frame.get('dx'), frame.get('dy')
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (dx, dy)):
                raise ValueError('invalid mouse displacement')
            if self.focus and frame['active'] and frame['locked'] and utils.is_cursor_locked():
                self.add_motion(dx, dy)
            if self.focus and frame['active'] and not frame['locked']:
                self.update_pointer(frame)
            return  # Motion-only packets never reconcile keyboard snapshots.
        events = self.input.update(frame)
        self.last_frame = time.monotonic()
        active = frame['active']
        if self.focus != active:
            self.focus = active
            utils.g_b_window_focused = active
            if not active:
                self.release()
                utils.lock_cursor(False, force=True)
            else:
                self.resume_cursor()
        cursor_error = frame.get('cursor_error', 0)
        if type(cursor_error) is not int:
            raise ValueError('invalid cursor error status')
        if active and cursor_error:
            if cursor_error != self.cursor_error:
                self.log('CURSOR_FAILED code=%d' % cursor_error)
            self.cursor_error = cursor_error
            self.release()
            utils.lock_cursor(False, force=True)
            self.command(lock=False)
            return
        self.cursor_error = 0
        for msg, key in events:
            self.dispatch(msg, key)
        if not active:
            return
        if not frame.get('locked'):
            self.update_pointer(frame)
        if frame.get('locked') and self.ui_pointer is not None:
            point, self.ui_pointer = self.ui_pointer, None
            self.suppressed_mouse.add(game.MOUSE_BUTTON_LEFT)
            self.ui_pointer_event(cc.EVENTTOUCH_EVENTCODE_CANCELLED, point)
        for event in frame.get('events', []):
            if not isinstance(event, list) or len(event) not in (2, 3):
                raise ValueError('invalid mouse event')
            msg, key = event[:2]
            edge_locked = event[2] if len(event) == 3 else bool(frame.get('locked'))
            if type(edge_locked) is not bool:
                raise ValueError('invalid mouse capture state')
            if msg not in (1, 2) or key not in (1, 2, 4, 5, 6):
                raise ValueError('invalid mouse button')
            # A cancelled UI gesture owns its eventual UP. Never turn that
            # release into a battle click after changing capture mode.
            if key in self.suppressed_mouse:
                if msg == game.MSG_MOUSE_UP:
                    self.suppressed_mouse.discard(key)
                continue
            if key == game.MOUSE_BUTTON_LEFT and msg == game.MSG_MOUSE_UP and self.ui_pointer is not None:
                point = self.ui_pointer_position(frame)
                phase = cc.EVENTTOUCH_EVENTCODE_ENDED
                if edge_locked or frame.get('locked') or point is None:
                    phase = cc.EVENTTOUCH_EVENTCODE_CANCELLED
                    point = self.ui_pointer
                try:
                    # Keep the originating button visible until END validates it.
                    self.ui_pointer_event(phase, point)
                finally:
                    self.ui_pointer = None
                continue
            if msg == game.MSG_MOUSE_DOWN and edge_locked != bool(frame.get('locked')):
                self.suppressed_mouse.add(key)
                continue
            # The iOS host has no desktop UI pointer producer. Use the shared
            # Cocos UI event backend for free-cursor clicks, without gameplay
            # touch regions or mapping keyboard keys to screen coordinates.
            if key == game.MOUSE_BUTTON_LEFT and not edge_locked and not frame.get('locked') and key not in self.mouse_down:
                point = self.ui_pointer_position(frame)
                if point is None:
                    continue
                if msg == game.MSG_MOUSE_DOWN:
                    self.ui_pointer = point
                    self.ui_pointer_event(cc.EVENTTOUCH_EVENTCODE_BEGAN, point)
                continue
            if frame.get('locked') or key in self.mouse_down:
                if msg == game.MSG_MOUSE_DOWN:
                    self.mouse_down.add(key)
                else:
                    self.mouse_down.discard(key)
                self.dispatch(msg, key)
        if self.ui_pointer is not None:
            point = self.ui_pointer_position(frame)
            if point is not None and point != self.ui_pointer:
                self.ui_pointer = point
                self.ui_pointer_event(cc.EVENTTOUCH_EVENTCODE_MOVED, point)
        dx, dy = frame.get('dx', 0), frame.get('dy', 0)
        if self.focus and frame.get('locked') and utils.is_cursor_locked():
            self.add_motion(dx, dy)
        width, height = frame.get('width', 0), frame.get('height', 0)
        if width > 0 and height > 0:
            # Retained PC consumers use Neox screen coordinates, with Y down.
            # nx_pos_to_cocosui_pos then flips Y for Cocos hit tests (radial
            # actions, quick chat, Witch/friend selection and widget hover).
            cx, cy = GK.g_screen_center
            game.set_mouse_pos(frame.get('x', 0) * cx * 2 / width,
                               (height - frame.get('y', 0)) * cy * 2 / height)
        scroll = frame.get('wheel', 0)
        if type(scroll) not in (int, float) or not math.isfinite(scroll):
            raise ValueError('invalid mouse wheel displacement')
        # Retain the PC global-block policy before dispatching its wheel events.
        # Preserve signed fractional input for smooth wheels/trackpads.
        if scroll and not GK.g_key_handler_mgr.on_mouse_wheel_pre(game.MSG_MOUSE_WHEEL, scroll, 0):
            GK.g_key_handler_mgr.on_mouse_wheel(game.MSG_MOUSE_WHEEL, scroll, 0)

    def update_pointer(self, frame):
        """Keep the newest AppKit sample in Cocos design coordinates (Y up)."""
        values = [frame.get(k, 0) for k in ('x', 'y', 'width', 'height')]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('invalid pointer coordinates')
        if values[2] > 0 and values[3] > 0:
            self.pointer_position = self.ui_pointer_position(frame)
            cx, cy = GK.g_screen_center
            game.set_mouse_pos(values[0] * cx * 2 / values[2],
                               (values[3] - values[1]) * cy * 2 / values[3])
        else:
            self.pointer_position = self.view_pointer = None

    def drain_frames(self):
        """Drain the private channel once; key callbacks may re-enter view code."""
        if not self.active or self.fd < 0 or self.draining:
            return
        if self.channel_failed:
            raise RuntimeError('native command channel failed')
        self.draining = True
        try:
            for _ in range(256):
                if not self.active:
                    break
                try:
                    raw = os.read(self.fd, 32768)
                except BlockingIOError:
                    break
                if not raw:
                    raise RuntimeError('native channel closed')
                self.consume(json.loads(raw))
        finally:
            self.draining = False

    def tick(self):
        if not self.active:
            return
        try:
            if not self.keymap_ready:
                self.init_keymap()
                if not self.keymap_ready:
                    self.scheduled = timer.TimerManager.add_timer(0.01, self.tick)
                    return
            ui = GK.input
            if ui is not self.last_ui:
                self.release()
                utils.set_cursor_battle_mode(False, force=True)
                self.rebuild_ui()
                self.last_ui = GK.input
                self.resume_cursor()
                self.log('SCENE input=' + type(self.last_ui).__name__)
            self.drain_frames()
            if not self.active:
                return
            if time.monotonic() - self.last_frame > 0.3:
                self.release()
                utils.lock_cursor(False, force=True)
            self.command(lock=bool(self.focus and utils.g_b_lock_cursor))
            self.tick_count += 1
            self.errors = 0
        except Exception:
            self.errors += 1
            self.log('ERROR ' + traceback.format_exc())
            try:
                self.release()
            except Exception:
                self.log('RELEASE_FAILED ' + traceback.format_exc())
            self.command(lock=False)
            if self.errors >= 3:
                self.stop('repeated errors')
                return
        self.scheduled = timer.TimerManager.add_timer(0.01, self.tick)

    def stop(self, reason='manual', keep_native=False):
        if not self.active:
            return
        self.active = False
        try:
            self.release()
        finally:
            try:
                self.command(stop=not keep_native, lock=False)
            finally:
                try:
                    for obj, name, original in reversed(self.saved):
                        if original is self.MISSING:
                            delattr(obj, name)
                        else:
                            setattr(obj, name, original)
                    PlatformUtil._refresh_pc_like_platform()
                    self.log('STOP ' + reason)
                finally:
                    if self.fd >= 0:
                        fd, self.fd = self.fd, -1
                        try:
                            os.close(fd)
                        except OSError as error:
                            self.log('CHANNEL_CLOSE_FAILED ' + repr(error))


if '_idv_pc_support' not in sys.modules:
    module = types.ModuleType('_idv_pc_support')
    module.controller = PCSupport(NATIVE_FD)
    sys.modules[module.__name__] = module
    try:
        module.controller.install()
    except Exception:
        module.controller.log('INSTALL_FAILED ' + traceback.format_exc())
        module.controller.stop('install failed')
        raise
