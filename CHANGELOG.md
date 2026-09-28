# Changelog · 更新日志

All notable changes to **OneMail · 一邮通** are documented here.
本文件记录 **OneMail · 一邮通** 的所有重要变更。

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/).
格式参考 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/)。

---

## [1.0.0] — 2026-09-28

First public release. · 首个公开发布版本。

### Added · 新增

**English**

- Multi-account IMAP fetching: add/remove/enable/disable mailboxes from the tray app
- Source labeling: every received mail is tagged with the account it came from; the mail list is filterable per account
- IMAP IDLE push (long-connection, ~0% idle CPU) with automatic fallback to configurable polling for providers without IDLE support (e.g. NetEase 163/126)
- One lightweight daemon thread per account, with exponential-backoff reconnect (5 s → 10 min) and connection-state verification before every fetch
- New-mail balloon notifications via the system tray
- Unread-count badge rendered on the tray icon (caps at `99+`)
- Main window: account list / mail list / reading pane; double-click to read, mark as read
- Mail parsing with encoding fallback chain (utf-8 → gbk → gb2312 → big5 → latin-1), HTML-to-plain conversion, attachment detection
- Passwords encrypted with Windows DPAPI (pure ctypes, no plaintext on disk)
- SQLite local mail cache — history survives restarts, offline browsing of fetched mail
- Auto-start on boot via HKCU registry Run key (user level, no admin rights), silent start to tray
- NetEase compatibility: automatic IMAP `ID` handshake after login
- PyInstaller single-file build with app icon (~20 MB, no console window)
- Preset IMAP hosts for common Chinese providers (QQ/Foxmail, 163, 126, Sina, Sohu, Aliyun, 139)
- Status/error logging to `%APPDATA%/OneMail/onemail.log`
- Unit tests for the parser and provider presets; docs in English and Chinese

**中文**

- 多账户 IMAP 收信：在托盘应用中添加/删除/启用/停用邮箱
- 来源标注：每封收到的邮件都标记所属账户，邮件列表可按账户筛选
- IMAP IDLE 长连接推送（空闲 CPU 占用≈0），服务器不支持 IDLE 时（如网易 163/126）自动降级为可配置间隔的轮询
- 每账户一条轻量守护线程，断线指数退避重连（5 秒 → 10 分钟），每次收信前校验连接状态
- 新邮件系统托盘气泡通知
- 托盘图标渲染未读数角标（上限 `99+`）
- 主窗口：账户列表 / 邮件列表 / 阅读区，双击阅读并标记已读
- 邮件解析含编码兜底链（utf-8 → gbk → gb2312 → big5 → latin-1）、HTML 转纯文本、附件识别
- 密码使用 Windows DPAPI 加密（纯 ctypes 实现，磁盘无明文）
- SQLite 本地邮件缓存——重启不丢记录，已收邮件可离线查看
- 注册表 HKCU Run 键实现开机自启（用户级，无需管理员），静默启动至托盘
- 网易兼容性：登录后自动发送 IMAP `ID` 握手命令
- PyInstaller 单文件打包，带应用图标（约 20MB，无控制台窗口）
- 国内常见邮箱 IMAP 服务器预置（QQ/foxmail、163、126、新浪、搜狐、阿里、139）
- 状态/错误日志写入 `%APPDATA%/OneMail/onemail.log`
- 解析器与服务器预置的单元测试；中英双语文档

### Fixed · 修复

**English**

- `AccountDialog` crashed on open due to a missing argument in the layout helper
- Event loop stalled after the first status event (log helper displaced the scheduler call), freezing tray badge and status bar updates
- Raw IDLE desync with servers replying non-standard continuation lines, previously surfaced as `command ... allowed in states SELECTED` reconnect loops

**中文**

- 修复账户编辑对话框因布局函数缺参而打开即崩溃的问题
- 修复首个状态事件后事件循环卡死（日志函数错位覆盖了事件调度），导致托盘角标与状态栏不再刷新的问题
- 修复服务器返回非标准 IDLE 继续行导致的收发不同步，该问题曾表现为 `command ... allowed in states SELECTED` 的反复重连

### Known Limitations · 已知限制

**English**

- NetEase mailboxes have no IDLE push; new-mail latency equals the polling interval (default 5 min, configurable in `config.json`)
- Sending/replying, OAuth2 (Gmail/Outlook), search and filter rules are planned for later releases

**中文**

- 网易邮箱不支持 IDLE 推送，新邮件延迟等于轮询间隔（默认 5 分钟，可在 `config.json` 中调整）
- 发信/回复、Gmail/Outlook 的 OAuth2、搜索与过滤规则将在后续版本提供
