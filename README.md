# run-idv-on-mac

> [!WARNING]
> 本项目自2026年11月2日起本软件不接受任何形式的公开宣传，否则仓库主将随时归档隐藏该仓库并删除已编译的发行版
> 

## 启动

先通过 PlayCover 安装并启动一次自己取得的已解密游戏，然后运行：

```bash
./Launch-DWRG.command
```

脚本按 Bundle ID 扫描 PlayCover 常见安装目录、`/Applications`、`~/Applications`、
本项目附近目录，并用 Spotlight 补充自定义位置。生成的副本位于
`.pc-launcher/DWRG-PC.app`；重复启动检测安装并复用副本，不替换原应用。
未检测到安装时明确提示，`--scan` 返回失败退出码。

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
- 捕获期间不再回写系统绝对坐标；落实逻辑回中，嵌套相机调用共享一次位移，
  避免鼠标静止后仍持续旋转。当前模式覆盖的相机入口也会接入采样。
- 正常解除捕获时系统光标回到游戏内容区中央，快捷键由游戏处理。焦点丢失时
  不移动光标；持键跨场景或失焦后需先实际松键，文本输入期间不注入游戏动作。
- PC 身份判断限定于直接输入和界面选择，资源和渲染调用保留原生平台身份。
  修复淘金 PC 界面重复重建、无技能管理器时报错，并补齐两个鼠标侧键。
- v8 把相机读取前取样扩展到大厅。自由光标也逐事件传输最新位置，通过游戏已有
  的 PC 旋转坐标接口供大厅读取。只有游戏已接受的旋转手势才会转视角。
  菜单共用的 PC 绝对鼠标坐标也随事件更新，保持上下方向一致。
- 左键自由光标点击使用游戏 Cocos UI 派发器；滚轮经原版 PC 前置阻断和当前
  UI 回调分发。是否有滚轮效果由界面是否注册对应处理决定。
- 只有键表 `load_ok=True` 才发出 READY；初始化依赖未齐时每秒重试。
  启动使用 Mach-O 自动加载，无需 LLDB 或持续诊断探针。

当前属于实验性适配。菜单拖动生命周期、极短按键边沿、所有角色与模式、
完整 Windows UI 布局仍有验证缺项；大厅新取样路径的实体鼠标体感仍待确认。
不能把测试通过等同于稳定 60 FPS，也不能声称与 Windows 客户端完全一致。
空格原始异常场景及远景模型恢复仍需实机复测。

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

## 免责声明

本项目为非官方的第五人格 Mac 键鼠适配工具，与网易及游戏官方无隶属、合作或授权关系。涉及的游戏名称、商标、图标及相关资源，其知识产权归各自权利人所有。本项目不提供游戏本体，使用者应通过合法渠道获取游戏，并自行确认相关操作符合适用法律、服务协议及授权范围。

本项目用于技术研究、学习及合法授权的软件交互，不支持盗版、作弊或侵犯他人权益的用途。工具会修改本机游戏文件，不保证兼容所有设备、版本或玩法，也不保证账号不受限制。使用前请备份重要数据，并妥善保留恢复文件。

在适用法律允许的范围内，本项目按现状提供，开发者不对使用本工具造成的数据丢失、运行异常或其他损失作出保证或承担责任；依法不得免除的责任除外。

如您认为本项目中的内容侵犯了您的合法权益，请通过邮箱 【填写联系邮箱】 联系，并提供相关权利证明及具体说明。我们将在核实后及时删除、下架或作其他必要处理。

需要 Apple Silicon Mac、PlayCover 和 Python 3.10+。普通启动使用随附的 v10 桥接库，
无需编译器；自行重建桥接库和运行原生测试需要 Xcode Command Line Tools。
按 Bundle ID `com.netease.id5` 与可执行文件识别安装，不再限制固定版本号、
比对游戏包体 SHA-256 或匹配固定 UUID。实际补丁指令、解释器内存布局、
系统签名及桥接文件完整性仍会检查；检测到安装不代表任意新版内部接口已兼容。

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

新工具 102 项测试通过；构建使用 `-Wall -Wextra -Werror`，产物经本机临时签名并验证。
完整验证范围见 [TESTING.md](TESTING.md) 与
[运行时验证记录](pc-support-tools/VERIFICATION.md)。
其他技术记录：[输入与 PlayTools 审查](pc-support-tools/INPUT-COMPATIBILITY-AUDIT.md)、
[间歇无响应调查](pc-support-tools/FREEZE-INVESTIGATION.md)。
