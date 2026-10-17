# 输入兼容性静态审查 — 2026-10-17

当前版本为 v8，共 73 项工具测试通过。v7 已取消大厅强制 BATTLE 与强制捕获；
v8 将相机读取前取样扩展到大厅，补齐自由光标逐事件坐标与菜单 PC 坐标更新，
并以 load_ok 校验键表初始化。原生窗口尺寸无效时清空旧大厅坐标。
这些改动保留游戏 CITY／BATTLE 等处理器和原版按键表，不增加动作键分支。
尚未验证新大厅路径的实体鼠标体感与稳定 60 FPS；下文历史缺项仍按各项说明保留。

后续状态：下文记录审查时的 v5 基线。两个 P1 项已在 v6 中修复，并补充跨捕获
UI 手势回归及原生接口失败注入测试；当前共 61 项通过。启动器已改为打包 v6。
本报告中的旧版哈希、复现结果及“尚未实施”描述保留为审查证据，不代表新版状态。
滚轮横向／手势阶段、通用菜单滚动、焦点代次等其余缺项仍未解决。
新版验证见 [v6 修复记录](VERIFICATION.md#v6-follow-up-fixes--2026-10-17)。

结论：当前方案可与本机 PlayTools 在关闭键鼠映射的配置下共存，但审查发现两个
优先修复的状态机缺陷。垂直滚轮已有 PC 回调路径，不能据此认定所有菜单、
触控板手势及 Windows 滚轮语义均完整支持。本次仅审查、离线复现及更新文档，
未修改运行时代码、签名、游戏设置或正在运行的游戏，未附加调试器。

## 审查对象与证据

- iOS 游戏 `26.243.2117`，受管副本 `.pc-launcher/DWRG-PC.app`。
- `runtime_adapter.py` SHA-256：
  `b254f26576dd1afae650f0d6ab9380e1b95ff0e0438cf9b394922f903cb33eb8`。
- v5 原生库 SHA-256：
  `24c8fc8375db4176e6073105e7511206d944dbbc90a65ba1a8bfbbadca947df6`。
  上述两个文件均与启动副本内的文件逐项哈希一致。
- 实际加载路径由客户端 `LC_LOAD_DYLIB` 确认：
  `~/Library/Frameworks/PlayTools.framework/PlayTools`。
  它与 `/Applications/PlayCover.app/Contents/Frameworks/PlayTools.framework/PlayTools`
  哈希相同：`a4f9d06341204f949d555797afafacb09732ab166e2f9732d16373edcf4586cc`。
- PlayTools 元数据版本为 `1.1.7`，但二进制 OSO 构建路径记录的提交是
  `e222ce0e75ad8f89d6f6372ae7bea7a3741cdbbd`。审查以该提交官方源码和
  关键分支反汇编相互核对，没有使用同名旧版本源码推断当前行为。
- AKInterface 插件 SHA-256：
  `ac00b6a84b5618c3d54c6ba16e7ed2c03b38c9aab4fdb47d22a17e61011cac5c`。
  本次没有逐函数反汇编核对整个插件；其细节以下标明为源码证据。

## 优先修复项

### P1：按住 UI 左键跨越捕获切换，会遗留按下状态（已离线复现）

位置：`runtime_adapter.py:275–300`、`key_state():152`。

触发：释放光标时按住左键，然后切换至捕获，再松开左键。UI 的 DOWN 设置
`ui_pointer`，但 UP 根据快照当前 `locked=True` 被送往战斗按键分支，未清除
`ui_pointer`。`key_state()` 因此持续报告左键按下，直至失焦等路径调用 release。

直接使用现有测试夹具执行实际 `consume()`，输出为：

```text
after free-cursor DOWN: ui_pointer=(333.5, 208.5), left_pressed=True
after captured UP:     ui_pointer=(333.5, 208.5), left_pressed=True, gameplay_buttons=[]
```

修复方向：一次手势的归属从 DOWN 保持到 UP/CANCEL；捕获或界面变化时显式
取消 UI 手势。原生边沿也应记录发生时的捕获状态／代次，不能只依靠发送时状态。

### P1：系统释放捕获失败后，内部状态会阻止重试（控制流确认）

位置：`IDVNativeInput.m:52–69`。

当已捕获时调用 `Cursor(NO)`，若 `CGAssociateMouseAndMouseCursorPosition(TRUE)`
失败，函数仍把 `locked` 写为 NO。下次释放与 Cleanup 均会被
`if (locked == value) return` 跳过；系统可能仍处于鼠标分离状态。捕获失败分支
也会调用未对应本次 hide 的 unhide，使光标隐藏计数的所有权不可靠。

这是失败恢复路径的确定缺陷；本次没有观察到系统 API 实际失败，不能据此认定
它解释了用户之前的捕获异常。

修复方向：区分期望状态、已成功应用状态和待重试的释放；成功后才提交状态，
只撤销本模块拥有的 hide，并将失败状态反馈给 Python。

## 滚轮审查

| 项目 | 当前行为／结论 |
| --- | --- |
| 垂直滚轮 | 原生读取 `scrollingDeltaY`，快照累计后传给 PC 管理器 |
| PC 入口 | 先 `on_mouse_wheel_pre(MSG_MOUSE_WHEEL, delta, 0)`，未阻断再调用 `on_mouse_wheel` |
| 数值 | Python 保留正负和小数，拒绝非有限数、布尔值及字符串 |
| 失焦 | Python 忽略 inactive 快照的滚轮；原生仅在应用 active 时收事件 |
| 横向滚动 | 未采集 `scrollingDeltaX`，回调第三参数始终为 0 |
| 触控板阶段 | 未传递 phase、momentumPhase、精确滚动标志及自然滚动标志 |
| 单位 | 原样传递 AppKit 数值，尚未证明与所有游戏 PC 消费者所需单位一致 |
| 菜单滚动 | 只有注册相应 PC 回调的界面有桥接路径；未实现通用 UI 列表滚动派发 |

PlayTools 对非精确滚轮在 AKPlugin 源码中乘 16，这是其触屏滚动适配的处理；
不能直接移植到游戏 PC 回调，也没有证据应一律乘 Windows 的 120。
当前没有根据静态证据修改滚轮符号或倍率。

另有事件保留问题：原生的 wheel／mouseEvents 在发送失败时保留，失焦转换没有
清空或标记代次。若通道背压覆盖整个失焦再恢复过程、且期间没有成功发送 inactive
快照，旧点击或滚轮可能在恢复后执行。普通 inactive 快照的单元测试不覆盖此条件。
同一快照内相反方向滚轮会相消；这是累计位移协议，不保证离散滚轮事件逐个执行。

## PlayTools 共存结论

本机配置文件 `~/Library/Containers/io.playcover.PlayCover/App Settings/com.netease.id5.plist`
与启动器一致：

| 配置 | 值 | 对本方案的影响 |
| --- | --- | --- |
| keymapping | false | PlayInput 提前返回，不初始化 ControlMode 键鼠监视器 |
| disableBuiltinMouse | false | 保留 GCMouse／系统鼠标通路，不触发 PlayTools 的模拟断开 |
| enableScrollWheel | true | 映射关闭时不会单独建立 PlayTools 的映射滚轮入口；当前桥接自己采集滚轮 |
| rootWorkDir | false | 保持既有启动目录策略，不参与鼠标捕获 |

已在安装二进制核对 `PlayInput.initialize`：`0x378e4` 读取 keymapping，
`0x378e8` 的 `tbz` 在 false 时跳至返回路径 `0x37b80`，绕过
`0x37b68` 的 `ControlMode.initialize` 调用。因此：

- 当前映射前端的 125Hz 鼠标限频不执行，不能用它解释原生桥接的相机采样卡顿。
- 当前没有 PlayTools 映射前端重复派发滚轮或常规竞争捕获的证据。
- 再开启 PlayCover 映射会同时引入另一套鼠标监视器、滚轮转换与光标所有权，
  不属于当前支持组合。
- `keymapping=false` 不等于卸载 PlayTools。其 CADisplayLink 的主队列处理仍会建立；
  这段代码存在本身不证明是间歇性卡死的原因。
- PlayTools 对 `IOSViewController.prefersPointerLocked` 的 hook 在源码中不受映射开关
  控制；安装二进制 `0x5cec` 为 `mov w0,#0; ret`。当前捕获依靠桥接直接调用
  CGAssociate／NSCursor，不能假设 UIKit 请求指针锁定可正常接管。
- 因内置鼠标保留，自由光标事件在桥接记录后仍返回原事件，UIKit／游戏原有通路
  仍可能处理。是否重复点击或滚动取决于下游是否注册监听，本次未证明重复处理。
  不应为消除一个未确认的重复路径直接关闭内置鼠标，以免破坏已验证的菜单行为。

## 其他边界与缺项

- UI 当前只在松开时合成同一 Touch 的 BEGIN/END；BEGIN/MOVE/CANCEL 本身无派发。
  从按钮 A 按下移到 B 松开会在 B 合成点击，不具备标准拖动／取消语义。
- `Active()` 只判断应用激活，没有限制为游戏内容窗口；同进程其他窗口成为 keyWindow
  时仍可能采集按键、计算错误坐标或吞掉鼠标事件。
- 0.5 秒原生捕获看门狗与 0.3 秒 Python 输入看门狗都依赖各自回调执行。
  主线程整体阻塞时不保证按时释放，不能将它们视为独立于游戏卡死的保险。
- 原生只生成左／右／中键。Python 接受侧键编号不等于上游已提供侧键支持。

## 验证与后续优先级

现有 53 项测试全部通过；本次另对实际 Python 消费逻辑执行上面的跨捕获手势复现。
现有测试通过不能覆盖这些新增发现。无实体鼠标滚轮的新实测结论。

建议顺序：先为跨捕获手势补回归并修复归属；再修复捕获释放重试与隐藏计数；
随后补焦点代次隔离，最后按游戏消费者确定滚轮单位、横向支持与菜单滚动需求。
这些建议尚未实施，本次审查没有替换正在运行的 v5。

## 上游源码定位

所有链接固定到二进制构建记录对应提交：

- [PlayInput：初始化开关与内置鼠标断开](https://github.com/PlayCover/PlayTools/blob/e222ce0e75ad8f89d6f6372ae7bea7a3741cdbbd/PlayTools/Controls/PlayInput.swift#L18)
- [ControlMode：滚轮、125Hz 与捕获](https://github.com/PlayCover/PlayTools/blob/e222ce0e75ad8f89d6f6372ae7bea7a3741cdbbd/PlayTools/Controls/Frontend/ControlMode.swift#L34)
- [AKPlugin：系统捕获与滚轮转换](https://github.com/PlayCover/PlayTools/blob/e222ce0e75ad8f89d6f6372ae7bea7a3741cdbbd/AKPlugin.swift#L267)
- [Swizzle：指针锁定与 GCMouse](https://github.com/PlayCover/PlayTools/blob/e222ce0e75ad8f89d6f6372ae7bea7a3741cdbbd/PlayTools/Controls/PTFakeTouch/NSObject%2BSwizzle.m#L336)
