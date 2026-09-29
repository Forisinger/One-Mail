# OneMail · 一邮通

**OneMail** is a lightweight Windows tray application that receives mail from **multiple mailboxes at once** — every message labeled with the account it came from. Built in Python with a hard focus on a **minimal memory & CPU footprint**.

**一邮通（OneMail）** 是一款 Windows 托盘工具，**同时收发多个邮箱的邮件**，每封邮件都标注来源账户。纯 Python 实现，主打**极低的内存与 CPU 占用**。

---

## ✨ Features / 功能

| English | 中文 |
|---|---|
| 📬 Multi-account IMAP fetching | 多账户 IMAP 收信 |
| 🏷️ Every mail labeled by source account, list filterable per account | 邮件标注来源账户，可按账户筛选 |
| ✉️ Compose & reply with attachments, sent on a background thread | 写邮件与回复，支持附件，后台线程发送不卡界面 |
| 🗑️ Delete mails from the local cache (server untouched) | 本地删除邮件缓存（不动服务器） |
| 🛡️ Hardened: atomic config writes, IMAP timeouts, crash-safe event loop | 加固：配置原子写、IMAP 超时、事件循环防崩 |
| 🎨 Rich-text body (bold/italic/underline/color) with HTML + plain fallback | 富文本正文（加粗/斜体/下划线/颜色），HTML + 纯文本双版本 |
| 📋 CC & BCC support | 支持抄送与密送 |
| 🔍 Full-text search (incl. body) + Unread / Has-attachment filters | 全文搜索（含正文）+ 未读/有附件快捷筛选 |
| ↕️ Click-to-sort columns | 列头点击排序 |
| 📎 Save attachments from the reading pane (on-demand server fetch) | 阅读区保存附件（按需从服务器取原文） |
| 📁 Per-account receive-folder selection (default INBOX) | 账户级收信文件夹选择（默认 INBOX） |
| 📤 Sent-mail sync to the server's Sent folder (best-effort) | 发送后尽力同步到服务器"已发送"文件夹 |
| 🖥️ Single instance: re-launching the exe brings the window to front | 单实例：再次启动自动唤醒主窗口置前 |
| 🗂️ Collapsible account panel with unread badges | 账户面板可收起，带未读徽章 |
| 🔔 Native tray balloon notifications | 系统托盘原生通知 |
| 🔴 Unread-count badge on the tray icon | 托盘图标未读数角标 |
| 🔁 IMAP IDLE push with automatic polling fallback | IDLE 推送优先，不支持时自动降级轮询 |
| ⚡ Incremental fetching — old unseen mail is never re-downloaded | 增量收信——旧未读邮件不会被反复下载 |
| 🔒 Passwords encrypted with Windows DPAPI — never stored in plaintext | 密码经 Windows DPAPI 加密，绝不明文落盘 |
| 💾 SQLite local cache, mail history survives restarts | SQLite 本地缓存，重启不丢邮件 |
| 🚀 Auto-start on boot (registry Run key, no admin needed) | 开机自启（用户级注册表，无需管理员） |
| 🪶 ~20 MB single exe, ~0% idle CPU | 单文件约 20MB，空闲 CPU 占用≈0 |

## 📦 Download & Run / 下载运行

**Option A — release exe / 直接用打包版**

Download `OneMail.exe` from [Releases](../../releases) and double-click. No installation.

从 Releases 页下载 `OneMail.exe` 双击运行，无需安装。

**Option B — from source / 源码运行**

```bash
git clone https://github.com/<you>/OneMail.git
cd OneMail
pip install -r requirements.txt   # only pystray + Pillow / 仅两个依赖
python src/main.py
```

> Requires Python ≥ 3.9 with tkinter (any standard Windows Python works / 需带 tkinter 的 Python，Windows 官方安装包默认包含).

## 🛠️ Build the exe / 自行打包

```bash
pip install pyinstaller
pyinstaller build.spec --noconfirm
# → dist/OneMail.exe
```

## 📖 First Run / 首次使用

1. Double-clicking the exe opens the **main window** directly; when launched by auto-start it goes silently to the tray (red badge shows unread count / 红色角标显示未读数). Re-launching the exe while running wakes the window to front.
2. Click **添加账户 / Add Account**, enter your address and **authorization code**.
3. Done — new mail shows up in the list, labeled by source, with balloon notifications.
4. Copy anything with a right-click: subject / sender / e-mail address from the mail list, your own account address from the account panel, or any selected text in the reading pane. The reading pane's right-click also offers **保存附件… (save attachments)**. Click the column headers (来源 / 发件人 / 主题 / 时间) to sort, and use the 🔍 search box + 全部/只看未读/有附件 filter to find mails — body text is searched too.

右键即可复制：邮件列表可复制主题/发件人/邮箱地址，账户面板可复制自己的邮箱地址，阅读区任意选中文本均可复制。

**Provider note / 邮箱服务商须知**: QQ Mail / NetEase 163/126 and most Chinese providers require an **authorization code (授权码)** instead of your login password — enable IMAP **and SMTP** in the web settings, generate the code, and paste it into OneMail. The same code is used for both receiving and sending. NetEase additionally requires the IMAP `ID` handshake, which OneMail sends automatically.

QQ 邮箱、网易 163/126 等国内邮箱需在网页设置中开启 IMAP **和 SMTP** 并使用**授权码**（不是登录密码），收信发信共用同一个授权码。网易还要求客户端上报 `ID` 命令，OneMail 已自动处理。

## 🔒 Privacy & Security / 隐私与安全

- Passwords are encrypted with **Windows DPAPI**, bound to your Windows user; they never touch `config.json` or the network beyond IMAP.
- Mail data stays in a local SQLite file (`%APPDATA%/OneMail/`). No telemetry, no network calls other than your own mail servers.

密码使用 Windows DPAPI 加密并绑定当前系统用户，不会出现在配置文件中；所有邮件数据仅存本地，除你自己的邮件服务器外无任何网络请求，无遥测。

## 🧱 Tech Overview / 技术概览

- One daemon thread per account: IMAP IDLE long-connection push (blocked socket, zero idle CPU), auto fallback to polling for providers without IDLE
- SMTP sending on a worker thread: MIME assembled by the stdlib `email` package, RFC 2231-encoded attachment names, best-effort Sent-folder sync
- Single-instance via Win32 named mutex/event (no third-party IPC)
- Full stdlib-first design — third-party runtime dependencies are exactly `pystray` + `Pillow`
- Exponential-backoff reconnect, connection-state verification before every fetch
- GBK/GB2312/Big5 encoding fallback chain for Chinese mail

每个账户一条守护线程：优先 IDLE 长连接推送（阻塞等待、空闲 CPU 为零），服务器不支持时自动降级轮询；断线指数退避重连；SMTP 发信跑在独立线程（标准库组装 MIME、中文附件名 RFC 2231 编码、尽力同步已发送文件夹）；单实例经 Win32 命名互斥体实现；GBK 等中文编码兜底解析。

Details in the docs / 详细文档：[English](docs/technical-doc.md) · [中文技术文档](docs/技术文档.md) · [Dev Plan](docs/development-plan.md) · [中文开发计划](docs/开发计划.md) · [发邮件开发计划](docs/发邮件开发计划.md) · [搜索过滤与文件夹开发计划](docs/搜索过滤与文件夹开发计划.md) · [稳定性加固开发计划](docs/稳定性加固开发计划.md) · [增量收信开发计划](docs/增量收信开发计划.md)

## 🗺️ Roadmap / 后续计划

- [x] Send & reply / 发信与回复 ✅ v1.1.0
- [x] CC/BCC fields, rich-text (HTML) mail / 抄送密送、富文本邮件 ✅ v1.2.0
- [x] Mail search & filter rules / 邮件搜索与过滤规则 ✅ v1.3.0
- [x] Folder selection / 收信文件夹选择 ✅ v1.3.0
- [ ] OAuth2 for Gmail/Outlook / Gmail 与 Outlook 的 OAuth2 登录

## 📄 License / 许可证

Released under the [MIT License](LICENSE).
基于 [MIT 许可证](LICENSE) 开源，可自由使用、修改与分发。
