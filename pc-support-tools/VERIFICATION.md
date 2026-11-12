# Native PC input — current runtime verification

Target: `.pc-launcher/DWRG-PC.app`, iOS client 26.243.2117, Catalyst arm64.
PlayCover `keymapping=false`. The project-root `Launch-DWRG.command` now
discovers supported installations, prepares a signed private copy and starts
the native helper through LC_LOAD_DYLIB. The bridge remains experimental;
this does not establish complete Windows-client parity.

## Installation detection without version/hash allowlists — 2026-11-12

- Removed the fixed game-version constant, executable SHA-256 allowlist and
  source/managed-client hash checks from the launcher. Manifests no longer
  store game hashes; reuse removes those fields from older manifests. Version
  metadata is descriptive only and may be absent. Payload integrity and macOS
  signing checks remain. The standalone historical patch utility is not used
  by this launch path.
- Every normal launch automatically searches for an installed bundle by
  `com.netease.id5` and its executable. `--scan` reports installation paths
  without version/hash matching and returns 1 with an installation hint if none
  are found. Real scanning found the PlayCover installation on this Mac.
- Removed the native fixed-UUID restriction. Before reading interpreter
  addresses, check the loaded Mach-O segments for readable/executable memory,
  then verify the existing interpreter entry instructions. Startup patching
  still verifies its actual target instruction. This removes metadata/hash
  gates without claiming compatibility with unknown internal layouts.
- 102 tests pass, including new/missing version metadata, no hashing of game
  executables during preparation/reuse, old-manifest migration, installed and
  absent scan results, normal-launch detection before cache reuse, patch-byte
  refusal and native memory-range/protection validation. Catalyst compilation
  and helper signing pass. The signed managed workcopy has been rebuilt.

Source backup: `.pc-launcher/source-before-discovery-20261112/`.

## v10 native rendering identity, Space and unlock position — 2026-11-12

- No shortcut or action is assigned by the bridge. The retained game handler
  and keymap continue to decide capture/release; a regression asserts that
  the original cursor-shortcut callback and selected mode remain intact.
- Reproduced logical key clearing followed by a held Space producing a second
  DOWN after a scene/watchdog release or focus loss. Released keys can now be
  suppressed until an active snapshot confirms physical UP. Text/IME focus
  suppresses gameplay DOWN and releases previously accepted gameplay keys.
  This fixes reproducible input lifecycle defects; the user's unspecified
  Space symptom still requires verification in its original scenario.
- An intentional, focused game unlock requests one native cursor recenter.
  Content-view center converts through window/screen coordinates to Quartz
  display coordinates. Failed association release delays the warp; losing
  focus cancels it. No explicit recenter is sent on focus-loss cleanup. Native
  tests fake the warp boundary and cover displays left of/above the main
  display, pending requests, and focus cancellation without moving a real cursor.
- Removed the global replacement of `game3d.is_pc`. `PlatformUtil.is_pc` and
  `check_use_pc_logic` now opt in only direct UI/input callers and the UI-name
  selection entry point. Resource loaders nested inside UI calls retain
  native identity; cached battle-platform refresh sees the native identity.
  Tests cover both direct and nested resource calls. The v9 global overrides
  were broader than its input-only intent and could affect LOD/resource policy.
- Earlier game logs include missing `lod/merge_alpha.png` for ordnance_factory1
  and h55_demo. v10 has initialized and entered UIBattlePC without a new adapter
  error; its current map differs from the earlier missing-LOD observation.
  Absence of that warning on a different map does not prove every distant model
  is repaired. No render-distance, quality setting, or resource file was forced.
- 96 tests pass. Native Catalyst build uses `-Wall -Wextra -Werror`; signed helper
  and rebuilt app verify. Startup logged `READY v10 bindings=123 native_platform=3`
  at 19:02:13 and `SCENE input=UIBattlePC` at 19:02:55 Asia/Shanghai.

Source backup: `.pc-launcher/source-before-v10-20261112/`. Optional local
`Documents/idv-input-diagnostic-request` exports existing input/platform/resource
bytecode at installation to `idv-input-diagnostics.txt`, then renames the request
to `.consumed`. It executes no requested script and changes no render settings.
All verification for v10 used terminal tools, logs and offline tests.

## v9 capture and game-mode adaptation — 2026-11-12

- Reproduced captured idle snapshots restoring an off-center system pointer,
  and the no-op PC recenter function. The retained PC view bytecode calculates
  rotation from `game.mouse_x/y` minus `GK.g_screen_center`. Captured snapshots
  now leave a neutral logical pointer; free samples awaiting capture
  acknowledgement cannot overwrite it. Relative camera calls restore center
  and zero delta in `finally`, including when the game callback raises.
- Hook the selected UI's actual `get_view` / `_get_view` method owners, including
  independent classes and special-mode overrides. Nested calls share one sample
  through both absolute-position and relative-delta APIs. The game keeps its
  own sensitivity, watcher/skill logic, keymap and CITY/BRANCH/BATTLE/FIREWORK/
  WOLVES handler selection. Hall retains its gesture-aware free-pointer path.
- Historical runtime log at 2026-10-17 21:00:01 shows
  `UI_REBUILD UIBattleGoldRushPC -> UIBattleGoldRushPC`, followed by a missing
  skill-manager error. Matching PC UI names now skip rebuilding; UI conversion
  tolerates modes without a skill manager. Both defects have regression cases.
- Scene identity includes UI, world, controlled unit and selected key handler.
  Changes release held inputs, discard pending motion and refresh camera hooks.
  UP is delivered to the handler that received DOWN. A handler change while
  draining aborts the old camera call.
- Native packets and commands carry a capture/scene generation. Old packets
  cannot replay after relocking or changing modes. Native pending events clear
  when focus changes, including unsent events retained during backpressure.
  Duplicate snapshot sequences cannot replay wheel/button payloads. Mouse
  buttons 4/5 now reach Windows VK 5/6; actions depend on the game's keymap.
- **88 tests pass** with `/opt/homebrew/bin/python3 -B -m unittest discover -q`.
  Native tests compile the real producer with fake cursor boundaries and check
  capture failures, focus clearing, generation changes and mouse-button mapping.
  Catalyst arm64 compilation uses `-Wall -Wextra -Werror`; helper signing passes.

The managed app was rebuilt and launched on 2026-11-12. System logs confirm
`IDVPC input producer started v9` at 18:45:47 Asia/Shanghai. After the client
downloaded its resource update, adapter logs confirm `READY v9 bindings=123
native_platform=3` at 18:47:59 and `SCENE input=UIHall` at 18:48:18. No new
adapter error was logged during this startup. A second `--prepare-only` run
verified payload reuse and the complete application signature. This confirms
installation and initialization, not physical keyboard/mouse behavior.

These are executable regression and static-code results. Full physical coverage
of every game mode, character, menu drag, chat/IME and sustained camera
smoothness remains unverified. No automated multiplayer matches are used.
The earlier source is preserved in `.pc-launcher/source-before-v9-20261112/`;
launcher rebuilds preserve previous signed applications.

## v8 global sampling and launcher — 2026-10-17

- Native motion events now publish free-cursor coordinates as well as captured
  displacement. Camera reads in UIHall and UIBattlePC drain pending samples
  immediately, without waiting for the independent snapshot timer.
- UIHall receives temporary PC rotate/pre-rotate coordinates through its own
  setters only while its original gesture state permits rotation. Its original
  view function keeps sensitivity, axis selection and clamps; no action keys or
  mouse-button-to-action bindings were added. The temporary fields are restored.
- Native free-cursor coordinates also update game PC mouse position for menus.
  Missing window bounds discard stale Hall coordinates; focus/scene changes
  release input and pending scene transitions abort the old camera call.
- PC presentation/input gates install before a player unit is required. Existing
  CITY/BRANCH/BATTLE handlers remain game-selected. Hall no longer inherits
  battle capture; focus restoration asks the current UI for its own policy.
- READY requires the game's keymap load_ok flag, with one-second retries while
  dependent game data is unavailable. Native event interception waits for READY.
- --rebuild --restart validates a source and closes the owned running copy before
  rebuilding. --metal-hud --restart scopes MTL_HUD_ENABLED=1 to the game process.
- 73 tests pass, including real native-code event publication and cursor failure
  injection. Catalyst compilation with -Wall -Wextra -Werror and signing pass.
  Independent review found no confirmed HIGH/CRITICAL issue; its missing-window
  pointer finding was reproduced in a regression test and fixed.

The v8 workcopy has been rebuilt and launched with 123 bindings and Metal HUD.
Physical Hall camera smoothness, sustained 60 FPS and all Windows UI layouts
remain unproven. A pre-v8 HUD observation showed about 52.6 FPS / 19 ms frame
interval / 17.8 ms GPU; it is not a before/after performance benchmark.
No persistent debugger or diagnostic sampling hook is part of normal startup.

## v6 follow-up fixes — 2026-10-17

- Cancel a held UI gesture on capture, suppress its eventual UP, and retain
  gesture ownership when capture changes twice or window bounds disappear.
  Ordinary paired UI clicks still expose the left button through END validation.
- Native edges include their capture state; the adapter accepts both the new
  three-field and legacy two-field records. An old DOWN cannot become a new
  action just because the snapshot's capture state changed while queued.
- Commit native association state only after success. Undo only an owned cursor
  hide, stop capturing input on failure, and retry failed release even during
  shutdown. A safe unlocked state acknowledges a failed capture attempt.
- Publish cursor failures to Python; it releases held input and requests unlock
  before dispatching any new key DOWN from the error frame.
- Ignore non-finite native wheel samples before JSON encoding so one invalid
  wheel value cannot prevent the complete keyboard snapshot from being sent.

61 tests pass. The new native test compiles actual Objective-C producer code
with startup disabled and fake association/cursor boundaries; no system cursor
is captured by the test. The earlier left-button reproduction and failure-path
tests fail on the old implementation and pass on v6. Independent review found
no remaining CRITICAL/HIGH issue in this change; unrelated audit limitations
remain open.

The v6 helper was built for arm64 Catalyst / minimum iOS 14 using
`-Wall -Wextra -Werror`, Foundation, GameController and CoreGraphics, then ad-hoc
signed with identifier `libIDVNativeInput.dylib`. Strict signature verification
passed. The launcher now packages v6; the earlier v5 library remains available
as a historical binary. Current payload SHA-256:

```text
native v6: 34bdb0ce8b55beb861f8dfbcb3b4144f9e94ffe051a4dee0e36a75fb14a1da77
adapter:   04b3f8f3c4cb5d268bf42c02378adf6feb87bf793f314045d9e0ca0c7cd7be24
```

No new physical mouse, scroll or game smoothness result is claimed for v6.
After confirming that no game process was running, the launcher rebuilt the
managed copy with `--rebuild --prepare-only`, preserving one previous app.
A second `--prepare-only` invocation verified reuse and the full app signature;
installed payloads match the new manifest and source hashes. The game was not
started during this update. Normal double-click startup now uses this v6 copy.

## Static compatibility audit baseline — 2026-10-17

The later [input compatibility audit](INPUT-COMPATIBILITY-AUDIT.md) identifies
two priority defects: UI left-button ownership can survive a capture switch,
and failed native cursor release commits an unlocked state that prevents retry.
The first was reproduced offline against the actual Python consumer; the
second is a confirmed failure-path defect, without an observed system API
failure. Earlier change-specific review conclusions below do not supersede
these findings. The audit itself did not deploy fixes; the v6 follow-up above
addresses these two defects in the current source and launcher payload.

Installed PlayTools binary and its recorded source commit confirm that
`keymapping=false` bypasses ControlMode initialization, including its 125 Hz
mouse cap and mapping wheel monitor. `enableScrollWheel=true` alone does not
enable that monitor. Wheel events here come from the native bridge. Builtin
mouse handling and unrelated PlayTools hooks remain present. See the audit
for remaining wheel, focus, capture and UI gesture limitations.

## Integrated launcher — 2026-10-17

- Scan common PlayCover/Application locations plus Spotlight; identify bundles
  by ID/executable and accept only the three recorded exact-build hashes.
- Apply the verified executable-path branch and add the bundle-relative v5
  helper load command. Preserve helper bytes/signature, sign the outer app,
  keep its sandbox and add the exact output path to its existing rules.
- Verify manifest, executable/payload hashes and strict deep signature on
  reuse. Preserve previous managed builds and failed output for inspection.
- Refresh the LaunchServices registration after signing. The first physical
  startup failed with -10670 and a stale unsigned registration; explicitly
  refreshing registration resolved it. This is now part of startup.
- Back up four owned PlayCover settings once, enable native mouse/wheel and
  disable touch keymapping; restore this invocation's prior values on launch
  failure, including cache-directory failure. Restore-settings preserves other
  preferences. No shared PlayTools or installed game modification.
- Existing target processes are activated without claiming a settings reload.
  Explicit `--restart` uses only SIGTERM, rechecks exact process paths and
  waits for exit; it includes an already running managed target.
- 53 tests pass, including version refusal, synthetic bundle preparation,
  signature failure, tampering, settings preservation, restart/identity change,
  timeout and failure compensation. Native v5 source/binary is unchanged.

Actual ordinary startup on this Mac (Asia/Tokyo timestamps): native helper
started at 14:22:31.873, Python adapter logged `READY bindings=123
native_platform=3` at 14:23:52, and `SCENE input=UIHall` at 14:23:55. The
game window was observed in the hall. No debugger was attached for this check.
The prepared copy passed a second reuse/signature verification.

Wheel support keeps signed fractional deltas and calls the retained
`on_mouse_wheel_pre` global-block check before the PC manager handler.
Tests cover both signs, fractional input, inactive-window suppression,
global blocking and invalid numeric input. Individual menus' physical wheel
behavior has not been exhaustively checked.

## User-confirmed behavior

- WASD movement stops when keys are released.
- Relative mouse camera, Shift/Ctrl, and cursor toggle.
- Free-cursor menu buttons respond to the physical mouse.
- 2026-10-17: camera Y direction corrected from `cy-dy` to `cy+dy`.
  The user confirmed normal direction after live reload.
- 2026-10-17: action-wheel direction corrected by supplying Neox absolute
  coordinates with a top-left origin. The user confirmed normal selection.

## Coordinate audit

Read-only inspection of loaded release Python bytecode found 28 references
to mouse position/delta interfaces, including duplicated/inherited methods.
This did not enumerate every unloaded game mode.

| Boundary | Convention | Current conversion |
| --- | --- | --- |
| NSEvent relative delta | positive Y down | camera position `center + delta` |
| NSEvent absolute window position | origin bottom left | invert Y, scale to Neox screen size |
| `game.mouse_x/y` | Neox screen pixels, origin top left | shared absolute PC input |
| Cocos menu pointer | design coordinates, origin bottom left | separate `Director.convertToUI` conversion |

Action wheels, quick-chat wheel/dropdown, friend selection, Witch control,
and common widget hover helpers consume `game.mouse_x/y` through
`utils.nx_pos_to_cocosui_pos`, which flips Y and divides by `GK.g_ui_scale`.
Correcting the producer establishes the right convention for these consumers.
Only the action wheel has new physical verification; other modes have code
inspection evidence, not individual physical tests.

Paired Cocos click dispatch shares one Touch for BEGIN/END. PC widget callbacks
also validate left-button state through `game3d.get_all_key_state`; the UI
gesture must remain visible during END. Menu dragging is still incomplete:
paired clicks do not retain one Touch for MOVE/CANCEL across frames.

## Capture cadence investigation — unresolved

The user reports that captured mouse camera feels like a lower frame rate.
The native producer requests a 120 Hz timer; this does not prove a 120 Hz
physical event rate. The adapter previously consumed its private channel only
in an independent engine timer, which could run after camera input and leave
that camera call reading old/empty displacement.

Current change: drain pending native packets immediately before the retained
PC camera consumes relative input. The normal timer remains for keyboard/UI,
scene reconciliation and watchdog handling. Draining is bounded and guarded
against reentry. If callbacks change UI/world/unit or stop the controller,
return zero rather than access an invalidated UI. Broken-channel shutdown
restores patches without propagating socket errors through the camera.

The foreground v3 sample on 2026-10-17 contains about 30 seconds of captured
physical movement. Render rate median was 59.9854 FPS and script rate median
59.9964 FPS. Captured camera intervals had a 16.66 ms median, 17.32 ms p95,
and 17.85 ms p99. All 1802 examined camera intervals consumed exactly the sum
of incoming displacement; no interval had nonzero input and zero consumed
displacement. Motion-packet frequency during continuous segments was roughly
80–101/s, after the producer's 120 Hz aggregation. This is not a measurement
of the mouse's hardware polling rate. Some motion gaps lasted 33–67 ms, but
v3 did not record original NSEvent timestamps, so the sample cannot distinguish
source event merging from pauses in physical movement.

The original PC camera's `view_unlock=False` chooses a dominant axis. A zero
rotation on one axis with nonzero two-axis input is expected in that mode;
this setting has not been changed.

### v5 capture experiment (loaded)

- Send captured motion directly from each NSEvent instead of waiting for the
  independent 120 Hz full-state timer. Preserve displacement under backpressure.
- Disable NSEvent movement coalescing only during capture, restore its previous
  value on release/stop. This does not change the hardware polling rate.
- Full-state packets have priority after backpressure. Motion-only packets
  never renew the keyboard watchdog, which releases stale state after 0.3s.
- Use the same capture gate for both packet kinds; clear relative displacement
  when game cursor policy changes, avoiding stale movement after relocking.
- Python owns a duplicated socket descriptor. Native cleanup removes its event
  monitor, invalidates its timer, restores cursor/coalescing and closes its own
  endpoints without risking descriptor reuse in Python.
- A bounded temporary probe records native event first/last timestamps and
  counts, send times, packet receive times, actual delta reads inside the camera,
  camera intervals, render/script rates and focus. It restores wrapped functions
  after 30 seconds of movement (or a 10-minute timeout), then writes once.

All 25 tool tests pass. Native v5 compiles with `-Wall -Wextra -Werror`.
Independent review found no remaining HIGH issue in these changes. The
backpressure policy has code-review evidence, not a native saturation test.
The v5 foreground sample recorded 720 camera delta reads. All 719 examined
intervals matched incoming displacement exactly. Render median was 59.9579
FPS, script median 60.0019 FPS, camera interval median 16.6638 ms. The 800
nonzero motion packets each contained one NSEvent; event-to-send median was
0.294 ms (p95 0.508 ms). Receive-minus-send after subtracting its minimum
clock offset had an 8.366 ms median; this measures excess queue delay, not
end-to-end display latency. Source event spacing includes physical pauses and
cannot be interpreted as a stable hardware polling rate.

The user clarified that isolated camera movement was smooth and the issue
was movement plus camera. A later combined test was reported normal. This
does not establish a reproducible root cause or prove the problem is gone.
The pre-v5 sample is retained at
`/tmp/idv-capture-cadence-v3.json`; v5 writes
`/tmp/idv-capture-cadence-v5.json` (temporary diagnostic files).

### Combined movement/camera and intermittent freeze investigation

A temporary observer recorded 5192 calls each to view input, unit movement
and FollowMode camera update over about 88s. Of these, 159 camera calls had
WASD held: median camera interval 16.616 ms, p99 18.617 ms. Visual unit
position changed in 157 of 158 adjacent movement intervals. The sample
therefore does not show a persistent 30 Hz movement/follow-camera mismatch.
The player's visual-position getter and follow-camera path were inspected;
no PC-platform gate disabling visual interpolation was found in those paths.

One whole-game gap lasted 1.229s, approximately 13:56:36–13:56:37 Asia/Tokyo
time (UTC+9). It coincides with the LLDB bytecode inspection output written at
13:56:37.118 Tokyo time. That observed pause was caused by debugging, not evidence of
a runtime bridge stall. This does not explain every user-reported freeze.

At 13:57:55 Tokyo time, all temporary probes were confirmed inactive and LLDB detached
from PID 4964. The v5 bridge remained active, with zero consecutive adapter
errors and no marked channel failure. A preceding non-stopping 3s system
sample showed ordinary run-loop/render activity, not a sustained blocked
main thread during that interval. Historical system logs after detachment,
13:57:56.958–14:11:45.423 Tokyo time, contain 828 existing main-thread timer
messages, with a maximum 1.580s gap and no gap over 2s. This is not a
frame-level or end-to-end responsiveness measurement. Earlier game ping
timeouts remain incompletely attributed. See [the freeze investigation](FREEZE-INVESTIGATION.md)
for the verified WindowServer connection, debugging overlaps, and limitations.
Further freeze capture should use the system `sample` tool without LLDB
attach/interrupt. No new in-game probe was installed for this historical analysis.

The speculative raw GameController motion path has NOT been loaded. Its draft
was moved to the recoverable cleanup directory with other unused experiments;
see the project-root cleanup manifest. The v5 adapter is retained, with the
wheel validation/global-block addition described above in the new startup copy.

## Remaining work

- Capture cadence measurement and physical smoothness verification.
- Stable menu drag/cancellation and UI button ownership on capture changes.
- Quick key edges; physical verification of auxiliary mouse buttons.
- Full application rollback selection (previous builds are preserved; settings
  restoration and reuse validation are implemented).
- Broader skill/character, chat/IME, remapping and transition verification.

Windows package remains read-only. No complete-PC-support claim is made.
