# 验证记录

验证日期：2026-10-12。使用合成测试数据，不附带原始日志、
本机路径、签名配置、进程列表、截图或账号信息。

## 目标

- 从兼容版本的本地 PlayCover 安装生成修复副本，不替换原程序。
- 启动前校验签名并补齐缺失的缓存目录。
- 双击关闭脚本只结束本仓库副本，不误杀其他游戏或原安装。

## TDD

准备脚本的 8 个初始用例先执行，因尚未实现而失败；实现后通过。
关闭脚本的 8 个初始用例也先执行，因尚未实现而失败；实现后通过。
随后补充命令行、可执行文件符号链接和真实临时进程集成测试。
相应 RED、GREEN 提交保留在当前分支历史中，不上传原始运行日志。

验证命令：

```bash
python3 -m unittest discover -v
python3 -m trace --count --missing --summary --coverdir coverage --module unittest discover
/bin/bash -n Launch-DWRG.command
/bin/bash -n Stop-DWRG.command
python3 -m py_compile executable_path_patch.py prepare.py stop.py
```

结果：**40 个测试通过**。本机原生关闭集成用例创建并重新签名一份
临时测试程序，确认仅该测试进程收到 `SIGTERM` 并退出；不关闭真实游戏。

| 范围 | 保证 |
|---|---|
| 二进制补丁 | 哈希、偏移和原指令校验；同目标跳转；原文件和权限保留 |
| 准备副本 | Bundle ID 校验；输出不覆盖；保留沙盒；未知版本和签名失败拒绝 |
| 启动 | 签名失败不启动；已有缓存数据保留；无强制重复实例参数 |
| 关闭 | 仅匹配完整可执行路径；PID 再核对；已退出进程容错；无 `SIGKILL` |
| 本机生成 | 使用真实原安装成功生成副本并通过严格签名校验；原哈希未变化 |

Python 标准库 `trace` 测得可执行行覆盖率：

| 模块 | 覆盖率 |
|---|---|
| `executable_path_patch.py` | 97.7% |
| `prepare.py` | 98.7% |
| `stop.py` | 94.5% |

这些数值只针对本仓库 Python 工具，不涵盖 Shell 代码、游戏或 PlayTools。
项目未配置独立类型检查器或 linter；Python 编译检查、
两个 Shell 语法检查及 `git diff --check` 通过。

## 实机边界

相同路径修复和缓存目录补齐已让实机工作副本通过非调试启动，
完成首轮补丁，并显示完整客户端资源下载界面。
发布版自动准备脚本另在本机执行，生成的副本通过
`codesign --verify --deep --strict`。

未重新操作用户游戏进行账号登录或实战测试。
反作弊、完整键鼠映射和其他游戏版本仍不保证兼容。
关闭使用正常终止请求；不对拒绝退出的游戏强制发送 `SIGKILL`。

## 发布卫生

只提交源码、测试、说明及 GNU GPL v3 许可证文本。
生成目录、游戏包、配置、日志和媒体文件均忽略。
提交作者使用 GitHub noreply 地址，不使用个人邮箱。
