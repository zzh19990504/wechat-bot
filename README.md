# 个人微信 Codex Bot

通过微信 iLink Bot 接收一对一文字消息，交给本机 Codex CLI 处理，再把结果回复到微信。支持多个联系人分别对话、实时联网搜索和会话续聊。Bot 需要在 Windows 电脑上持续运行。

> 当前只支持一对一文字消息；不支持微信群、图片、语音或文件消息。iLink 登录二维码用于绑定机器人账号，不是邀请其他用户的二维码。

## 准备工作

- Windows、Python 3.9 或更新版本，以及可用的 `pip`。
- 已安装并登录 Codex CLI。先运行 `codex login status` 确认。
- 可以在手机微信中扫描终端二维码。

本项目使用第三方 Python 包 `weixin-ilink` 连接微信；Codex++ 的登录凭据不会自动复用。

## 安装和启动

在项目目录打开 PowerShell，首次运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
codex login status
.\.venv\Scripts\python.exe bot.py serve
```

如果 `python` 或 `py` 命令不可用，请先安装 Python，再重新打开 PowerShell。本机已有 `.venv` 时，无需重新创建，直接运行最后一行即可。

首次启动会在终端显示二维码。用自己的微信扫码确认后，Bot 会保存登录凭据；后续启动通常无需再次扫码。请保持终端窗口和电脑运行。若 Codex++ 也在连接同一个机器人账号，请先停止其中一个连接，避免重复接收或丢失消息。

Windows 上也可双击 `启动微信Bot.bat`，或在 PowerShell 中运行 `.\start.ps1`。可为批处理文件创建桌面快捷方式。按 `Ctrl+C` 停止 Bot。

## 多人使用

扫码登录的微信用户自动加入授权名单。其他联系人先向机器人发送一条文字消息，Bot 会回复该联系人的用户 ID。管理员在另一个 PowerShell 窗口执行：

```powershell
.\.venv\Scripts\python.exe bot.py allow '用户ID'
```

授权后，让对方重新发一条消息。授权名单会即时生效，不用重启。常用管理命令：

```powershell
.\.venv\Scripts\python.exe bot.py users
.\.venv\Scripts\python.exe bot.py revoke '用户ID'
.\.venv\Scripts\python.exe bot.py reset '用户ID'
```

联系人也可以发送 `/reset` 开始新会话。每个联系人有独立的 Codex 会话；最多同时处理 3 人，其他消息排队，队列上限为 50 条。多人使用取决于 iLink 能否让其他微信号找到并向这个机器人发送消息，授权名单本身不提供邀请入口。

## Codex 权限

Bot 使用本机 Codex CLI，启用实时搜索，并通过 `--dangerously-bypass-approvals-and-sandbox` 给予**完全访问权限**。授权用户的请求可以触发本机命令、联网，以及读取、修改或删除当前 Windows 账号有权访问的文件。所有用户共用这台电脑的运行账号权限和 Codex 账号额度；只授权你完全信任的人。

默认工作目录是本项目目录。`CODEX_COMMAND` 环境变量可指定 Codex CLI 可执行文件路径。单次 Codex 调用超时为 300 秒。修改 `bot.py` 后需要重启 Bot。

## 本地数据

运行后会在 `data/` 下保存：

| 文件 | 用途 |
| --- | --- |
| `ilink-credentials.json` | 微信登录凭据 |
| `ilink-credentials.json.sync` | 消息轮询进度 |
| `allowed-users.json` | 已授权用户 ID |
| `sessions.json` | 用户与 Codex 会话的对应关系 |

`data/` 已被 `.gitignore` 排除。不要分享、公开上传或手动编辑登录凭据。登录过期时，先停止 Bot，运行 `.\.venv\Scripts\python.exe bot.py login` 重新扫码，再启动 Bot。

## 常见问题

- **二维码没有出现**：确认依赖已安装：`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`。
- **收不到消息**：确认扫码成功、终端仍在运行，并检查是否有另一个程序同时连接同一机器人账号。
- **收到“尚未授权”**：管理员执行 `bot.py allow '用户ID'`，随后联系人重新发送消息。
- **收到“处理失败”**：查看 Bot 终端日志，并运行 `codex login status` 检查本机 Codex 登录状态。
- **搜索没有结果**：检查网络、账号和 Codex CLI 是否支持实时搜索。
