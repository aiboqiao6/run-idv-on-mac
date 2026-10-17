# run-idv-on-mac

第五人格在 Apple Silicon Mac / PlayCover 下的启动兼容修复与原生 PC 键鼠桥接。
双击 `Launch-DWRG.command`，自动扫描安装位置、校验版本、生成签名工作副本并启动。
本仓库提供本地工具和本项目编译的桥接库，不分发游戏包体或提取的游戏脚本。

需要 Apple Silicon Mac、PlayCover 和 Python 3.10+。普通启动使用随附的 v8 桥接库，
无需编译器；自行重建桥接库和运行原生测试需要 Xcode Command Line Tools。
已验证游戏版本 `26.243.2117`，Bundle ID `com.netease.id5`。
启动器严格校验可执行文件 SHA-256 和补丁指令，遇到未知版本停止。

## 启动

先通过 PlayCover 安装并启动一次自己取得的已解密游戏，然后运行：

```bash
./Launch-DWRG.command
```

脚本按 Bundle ID 扫描 PlayCover 常见安装目录、`/Applications`、`~/Applications`、
本项目附近目录，并用 Spotlight 补充自定义位置。生成的副本位于
`.pc-launcher/DWRG-PC.app`；重复启动校验并复用，不替换原应用。

```bash
# 仅扫描，不修改文件
./Launch-DWRG.command --scan

# 手动指定原游戏
./Launch-DWRG.command --app "/path/to/com.netease.id5.app"

# 更新桥接后，正常退出旧进程、重建并启动；保留上一版
./Launch-DWRG.command --rebuild --restart

# 开启本次游戏进程的 Metal FPS / GPU 时间 / 帧间隔面板
./Launch-DWRG.command --metal-hud --restart

# 仅生成工作副本
./Launch-DWRG.command --prepare-only

# 退出游戏后恢复本工具修改前的 PlayCover 设置
./Launch-DWRG.command --restore-settings
```

另一个副本运行时，普通启动提示先退出；`--restart` 会核对路径和 Bundle ID 后
发送 SIGTERM 并等待，不强制终止。当前受管副本已运行时，普通启动只切回窗口。
重建需先退出，或使用 `--rebuild --restart`。`--prepare-only` 不会关闭运行中的游戏。
需要关闭本仓库工作副本时，可运行 `Stop-DWRG.command`。

## 键鼠处理

- 关闭 PlayCover 触屏按键映射，原生键盘转成 Windows VK 状态，交给游戏保留的
  PC 键表和当前 CITY / BRANCH / BATTLE 等处理器。动作键由游戏配置决定。
- 保留 WASD 松键释放、组合键、失焦清空、光标释放/恢复和滚轮处理。
  大厅保留自由光标；恢复焦点时由当前游戏 UI 决定是否重新捕获。
- 对局使用逐鼠标事件累计的相对位移，在相机读取前取最新样本，再调用原版 PC
  视角计算，保留游戏灵敏度、瞄准及旋转限制。
- v8 把相机读取前取样扩展到大厅。自由光标也逐事件传输最新位置，通过游戏已有
  的 PC 旋转坐标接口供大厅读取。只有游戏已接受的旋转手势才会转视角。
  菜单共用的 PC 绝对鼠标坐标也随事件更新，保持上下方向一致。
- 左键自由光标点击使用游戏 Cocos UI 派发器；滚轮经原版 PC 前置阻断和当前
  UI 回调分发。是否有滚轮效果由界面是否注册对应处理决定。
- 只有键表 `load_ok=True` 才发出 READY；初始化依赖未齐时每秒重试。
  启动使用 Mach-O 自动加载，无需 LLDB 或持续诊断探针。

当前属于实验性适配。菜单拖动生命周期、极短按键边沿、侧键、所有角色与模式、
完整 Windows UI 布局仍有验证缺项；大厅新取样路径的实体鼠标体感仍待确认。
不能把测试通过等同于稳定 60 FPS，也不能声称与 Windows 客户端完全一致。

## 文件与恢复

启动器只修改四项 PlayCover 设置：`keymapping=false`、`disableBuiltinMouse=false`、
`rootWorkDir=false`、`enableScrollWheel=true`。首次值保存在
`.pc-launcher/settings-before.plist`；失败时恢复本次运行前的设置，其余设置保留。
游戏原数据容器沿用，缓存目录只补齐缺项。不要单独移动生成的应用，签名沙盒规则
包含绝对路径；移动仓库后使用 `--rebuild`。

适配器日志：

```text
~/Library/Containers/com.netease.id5/Data/Documents/idv-pc-support.log
```

进程存在不代表键鼠初始化成功，请检查 READY。若 Documents 中存在
`idv-pc-support-disabled` 标记，启动器提示先移走它。Metal HUD 是启动参数控制，
普通重启不启用该面板；工具不设置系统全局环境变量。

旧版 `prepare.py` 与 `Launch-Legacy-DWRG.command` 保留，使用说明见
[旧版启动修复](docs/LEGACY-STARTUP.md)。新默认入口是本页的启动器。

## 构建与验证

```bash
# 旧版启动修复与关闭工具测试
python3 -B -m unittest discover -v

# 新启动器、键鼠运行时和实际原生代码失败注入测试
cd pc-support-tools
python3 -B -m unittest discover -v

# 可选：重建并签名本项目的 Catalyst 桥接库
python3 -B build_native.py
```

新工具 73 项测试通过；构建使用 `-Wall -Wextra -Werror`，产物经本机临时签名并验证。
完整验证范围见 [TESTING.md](TESTING.md) 与
[运行时验证记录](pc-support-tools/VERIFICATION.md)。
其他技术记录：[输入与 PlayTools 审查](pc-support-tools/INPUT-COMPATIBILITY-AUDIT.md)、
[间歇无响应调查](pc-support-tools/FREEZE-INVESTIGATION.md)。
