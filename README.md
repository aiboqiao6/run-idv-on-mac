# run-idv-on-mac

第五人格在 Apple Silicon Mac / PlayCover 下的启动兼容性修复。
只提供本地修复工具，不提供游戏、IPA、砸壳服务或下载地址。

## 适用范围

- Apple Silicon Mac，已安装 PlayCover 和 PlayTools。
- Python 3.10 或更新版本，系统中可用的 `codesign`。
- 自己合法取得、已经解密并安装到 PlayCover 的第五人格应用。
- 已验证的应用版本：`26.243.2117`，Bundle ID：`com.netease.id5`。
- 原始 `client` 的 SHA-256 必须为：

```text
7d6f8003d51f93c8682b01619b193af2b79d600de3b78340f9ac2e8d4aa6405d
```

不同版本、重新签名后字节不同的程序或加密 IPA 不适用。
脚本会拒绝未知二进制，不会尝试猜测补丁位置。

实机验证环境：macOS 27.2、PlayCover 3.1.0、PlayTools 1.1.7。
已验证普通启动、补丁更新和完整客户端资源下载画面。
**登录、反作弊兼容性、实战和完整键鼠映射尚未验证。**

## 使用步骤

1. 获取本仓库，打开终端，进入仓库目录。先退出正在运行的第五人格。
2. 在 PlayCover 中关闭此游戏的「根目录作为工作目录」选项
   （`rootWorkDir=false`）。本工具不会自动更改 PlayCover 设置。
3. 生成修复副本：

```bash
python3 prepare.py
```

默认读取：

```text
~/Library/Containers/io.playcover.PlayCover/Applications/com.netease.id5.app
```

安装位置不同，可以明确指定原应用路径：

```bash
python3 prepare.py --source "/path/to/com.netease.id5.app"
```

脚本校验原始文件和签名后，将应用复制到 `work/DWRG-PathFixed.app`，
修复路径转换逻辑、从原应用读取权限并仅增加工作副本所在目录的访问权限，
然后在本机重新签名、验证签名。原应用不替换。
它不下载游戏、不处理登录凭据，也不自动启动应用。

4. 双击 `Launch-DWRG.command`，或者在终端执行：

```bash
./Launch-DWRG.command
```

启动器校验签名，仅在原游戏数据目录下补齐缺失的
`local_shader_cache/res3` 缓存目录，然后启动修复副本，并跳过
macOS 的崩溃窗口恢复提示。已在运行时不会强制创建第二个游戏进程。

需要关闭时，双击 `Stop-DWRG.command`，或者执行：

```bash
./Stop-DWRG.command
```

关闭脚本仅对本仓库 `work/DWRG-PathFixed.app/client` 的进程发送
`SIGTERM`，发送前再次核对进程路径。不会结束原 PlayCover 应用、
其他名为 `client` 的进程，也不会清除数据。没有运行中的副本时可重复执行。
它不使用 `SIGKILL`；如果应用拒绝退出，请自行关闭游戏窗口。

5. 让游戏完成自身的补丁和核心玩法资源下载，再自行登录。
   后续使用本仓库的启动器，不要打开未修复的旧副本。

**不要移动仓库或 `work/DWRG-PathFixed.app`：签名中的沙盒规则包含
本机工作副本的绝对路径。移动后需要在新位置重新生成副本。**

本工具保留原应用的 Bundle ID 和已注入的 PlayTools，不复制或改写
PlayCover 的游戏设置。PlayTools 设置的额外配置流程暂不在本项目范围内。

## 常见问题

| 提示或现象 | 处理方式 |
|---|---|
| `Unknown or changed executable` | 版本或哈希不匹配，停止使用此补丁；不要强行改校验 |
| `Output already exists` | 工具不会覆盖旧副本；保留旧目录，在新的仓库目录生成 |
| `Missing game Documents directory` | 先确认原应用已通过 PlayCover 安装和启动过；工具不会伪造整个数据容器 |
| 签名失败 | 输出副本会保留供检查；原应用不会被替换，未通过校验的副本不要运行 |
| 下载界面可以打开，但仍不能进入游戏 | 先等待必需资源下载完成；这不等同于实战兼容性已验证 |
| 启动时出现 `PlayTools ... Toucher.touchcam` 崩溃 | 在 PlayCover 中临时关闭本游戏按键映射再测试；不要修改共享 PlayTools |

可手工检查生成的应用：

```bash
codesign --verify --deep --strict --verbose=2 work/DWRG-PathFixed.app
```

需要使用自定义 `--output` 时，默认启动器不会自动跟随该目录。
从仓库目录对自定义副本执行以下命令；仍需事先补齐上述缓存目录：

```bash
open "/path/to/output/DWRG-PathFixed.app" --args -ApplePersistenceIgnoreState YES
```

## 修复原理

本版本引擎会给 macOS 的 `/Users/...` 可执行文件路径增加 iOS 使用的
`/private` 前缀，导致无法进入实际应用目录，随后找不到 `neox3.xml`。
补丁只将文件偏移 `0x572e108` 的条件跳转改为通往同一目标的无条件跳转，
使用引擎已有的路径复制分支，不修改资源、账户逻辑或反作弊逻辑。

另一个已复现故障是缺失的着色器缓存目录导致资源文件系统创建失败，
之后引擎解引用空指针。启动器只补齐目录，不跳过空指针检查或屏蔽崩溃。
工作副本仍保留应用沙盒；工具不关闭 SIP，不修改共享 PlayTools。

## 隐私与回退

- 本仓库没有游戏二进制、日志、截图、个人路径、账号数据或签名配置。
- `work/` 下的应用和本机生成的权限文件由 `.gitignore` 排除。
- 测试只使用临时合成文件。工具没有上传功能，也不读取 GitHub 凭据。
- 游戏运行时自身的网络请求和数据收集不受本工具控制。
- 不要把 `work/`、原应用或游戏数据容器加入提交或 Issues。
- 回退时退出修复副本，使用原 PlayCover 应用。原应用和存档未被替换。
- 不要自动删除已下载的游戏资源或缓存，避免丢失运行数据。

## 测试

仅使用 Python 标准库，无额外 Python 依赖：

```bash
python3 -m unittest discover -v
/bin/bash -n Launch-DWRG.command
/bin/bash -n Stop-DWRG.command
```

验证范围和局限见 [TESTING.md](TESTING.md)。

## 许可证

本仓库原创脚本和文档使用 **GNU General Public License v3.0 only**
（`GPL-3.0-only`），全文见 [LICENSE](LICENSE)。
该许可证不适用于第五人格、PlayCover、PlayTools 或用户提供的游戏文件；
这些第三方内容遵循各自的权利和许可证。
