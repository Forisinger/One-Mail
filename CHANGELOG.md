# Changelog · 更新日志

All notable changes to **OneMail · 一邮通** are documented here.
本文件记录 **OneMail · 一邮通** 的所有重要变更。

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/).
格式参考 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/)。

---

## [1.6.0] — 2026-09-29

Attachment saving from the reading pane (on-demand server re-fetch). · 阅读区保存附件（按需从服务器重新取原文）。

### Added · 新增

**English**

- **Save attachments**: reading-pane right-click → 保存附件… — pick a folder and OneMail fetches the raw message from the server by UID (BODY.PEEK[], read-only), extracts every attachment with proper RFC 2047 name decoding (Chinese names intact) and writes them out, deduplicating name collisions as `name(1).ext`. Runs on a worker thread with status-bar progress/errors
- `MailClient.fetch_raw()` + `parser.extract_attachments()`: reusable, offline-testable building blocks; name-collision and unnamed-attachment edge cases handled
- Verified end-to-end against a live NetEase 163 mailbox (fetch_raw returns the original bytes)

**中文**

- **保存附件**：阅读区右键 →「保存附件…」——选择目录后按 UID 从服务器重新取回邮件原文（BODY.PEEK[]，不打已读标记），解析出全部附件（RFC 2047 文件名解码、中文名完好）后写出，重名自动加 `(1)` 后缀。后台线程执行，状态栏显示进度与错误
- `MailClient.fetch_raw()` + `parser.extract_attachments()`：可复用、可离线单测的构件；处理重名与未命名附件边界
- 已对网易 163 真实邮箱端到端验证（fetch_raw 返回原始字节）

---

Sortable columns and a real-mailbox end-to-end verification tool. · 列头排序与真实邮箱端到端验证工具。

### Added · 新增

**English**

- **Sortable columns**: click 来源 / 发件人 / 主题 / 时间 headers to sort (click again to reverse, ▲/▼ indicator); sorting is UI-side so it composes with search and filters
- `tools/verify_163.py`: end-to-end verification against a real mailbox (temp DB, read-only effects) — connect, UIDVALIDITY read, folder listing with mUTF-7 decoding, incremental fetch watermark behavior. Verified live against NetEase 163: 6 folders decoded correctly (草稿箱/已发送/垃圾邮件…), first pass fetched 4 unseen mails, second pass downloaded 0 with unchanged watermark

**中文**

- **列头排序**：点击 来源 / 发件人 / 主题 / 时间 列头排序（再点反转，列头显示 ▲/▼）；UI 侧排序，与搜索、过滤器自由叠加
- `tools/verify_163.py`：真实邮箱端到端验证工具（临时数据库，只读效果）——连接、UIDVALIDITY 读取、文件夹列表 mUTF-7 解码、增量抓取水位行为。已对网易 163 实测：6 个文件夹中文名解码正确（草稿箱/已发送/垃圾邮件…），第一轮抓取 4 封未读，第二轮 0 下载且水位不变

---

## [1.5.2] — 2026-09-29

Sortable columns and a real-mailbox end-to-end verification tool. · 列头排序与真实邮箱端到端验证工具。

### Added · 新增

**English**

- **Sortable columns**: click 来源 / 发件人 / 主题 / 时间 headers to sort (click again to reverse, ▲/▼ indicator); sorting is UI-side so it composes with search and filters
- `tools/verify_163.py`: end-to-end verification against a real mailbox (temp DB, read-only effects) — connect, UIDVALIDITY read, folder listing with mUTF-7 decoding, incremental fetch watermark behavior. Verified live against NetEase 163: 6 folders decoded correctly (草稿箱/已发送/垃圾邮件…), first pass fetched 4 unseen mails, second pass downloaded 0 with unchanged watermark

**中文**

- **列头排序**：点击 来源 / 发件人 / 主题 / 时间 列头排序（再点反转，列头显示 ▲/▼）；UI 侧排序，与搜索、过滤器自由叠加
- `tools/verify_163.py`：真实邮箱端到端验证工具（临时数据库，只读效果）——连接、UIDVALIDITY 读取、文件夹列表 mUTF-7 解码、增量抓取水位行为。已对网易 163 实测：6 个文件夹中文名解码正确（草稿箱/已发送/垃圾邮件…），第一轮抓取 4 封未读，第二轮 0 下载且水位不变

---

## [1.5.1] — 2026-09-29

Follow-up fixes from the second review pass over v1.4/v1.5. · 二轮复查对 v1.4/v1.5 新改动的修复。

### Fixed · 修复

**English**

- **(P0) New-mail loss window closed**: the incremental watermark was advanced before the mails were actually inserted (insertion used to happen on the UI thread up to 500 ms later, and quit() exits via `os._exit`) — a mail fetched in that window would be permanently skipped by `uid <= watermark` on the next run. Fetching now inserts synchronously on the worker thread, advances the watermark only after a confirmed insert, and notifies with genuinely-new mails only; quit() also drains the event queue before exiting
- **(P1) 获取 (Fetch folder list) button always failed** with a `NameError` (`_send_client_id` is a class staticmethod and was called bare)
- **(P1) Non-default folders could never receive mail**: imaplib sends commands ascii-encoded and unquoted — Chinese folder names raised `UnicodeEncodeError` and "Sent Messages"-style names were split into multiple atoms, both causing endless reconnects. Folder names are now converted back to modified-UTF-7 and quoted on the wire (`_folder_wire()`); names already in wire form are used as-is
- **(P1) A single failed FETCH no longer skips that mail forever**: the watermark now only advances past successfully fetched UIDs — a failed fetch ends the batch and the mail is retried next cycle
- IDLE continuation-line wait is bounded (10 s) and tolerates untagged lines preceding the `+` (previously misjudged as "no IDLE support" and left the protocol out of sync)
- save_to_sent APPENDs with the server's raw mUTF-7 folder name (decoded names crashed on Chinese providers) and takes the hierarchy delimiter from the LIST response instead of hardcoding `/`
- Parser recovery is depth-limited (8) against pathological nested-markup inputs; `folder_state` DDL moved into `init()`; badge font cached at module level

**中文**

- **（P0）封堵丢信窗口**：增量水位此前在真正入库之前推进（入库原本在 UI 线程、最多延迟 500ms，而退出走 `os._exit`）——窗口期内抓到的邮件下轮会因 `uid ≤ 水位` 被永久跳过。现在收信线程同步入库、确认落库后才推水位、只通知真正新入库的邮件；退出前还会排空事件队列
- **（P1）「获取文件夹列表」按钮必然报 NameError**（`_send_client_id` 是类静态方法却被裸调用）
- **（P1）非默认文件夹此前无法收信**：imaplib 命令按 ascii 编码且不加引号——中文文件夹名直接 UnicodeEncodeError，"Sent Messages" 类名字被拆成多个 atom 被服务器拒绝，均表现为无限重连。现在发送前把名字转回修改版 UTF-7 并加引号（`_folder_wire()`）；已是线格式（原始 mUTF-7）的名字原样使用
- **（P1）单封 FETCH 失败不再导致该邮件永久跳过**：水位只推进到本批实际成功抓取的 UID，失败即断批、下轮续抓
- IDLE 继续行等待改为 10 秒有界，并容忍 `+` 之前的 untagged 行（此前会被误判为不支持 IDLE 且留下协议失步）
- save_to_sent 改用服务器原始 mUTF-7 文件夹名 APPEND（解码后的中文名必然失败），层级分隔符取自 LIST 响应而非硬编码 `/`
- 解析器恢复深度限 8 层防病态输入；`folder_state` 建表挪入 `init()`；角标字体模块级缓存

---

Incremental fetching (no more re-downloading all unseen mail) and attachment names in the reading pane. · 增量收信（不再反复整封下载未读邮件）与阅读区附件名展示。

### Added · 新增

**English**

- **Incremental fetch**: a new `folder_state` table records `UIDVALIDITY` + the highest fetched UID per account/folder; the (cheap, server-side) UNSEEN search is unchanged, but only UIDs above the watermark are actually downloaded. A mailbox with hundreds of old unread mail no longer re-downloads everything on every push/poll cycle; interrupted batches resume from the last fully fetched UID
- **UIDVALIDITY handling**: if the server resets UIDs, the folder's local cache is cleared and resynced, preventing new mail from being deduplicated against recycled UIDs
- **Attachment names in the reading pane**: the `mails` table gains an `attachment_names` column (auto-ALTER for old DBs) and the reading pane shows `📎 附件：a.pdf、b.zip`
- Tray badge digits now render with a TrueType font (larger/clearer at 64 px, graceful fallback); the tray degrades gracefully on systems without a shell; all accounts missing auth codes are prompted one after another at startup

**中文**

- **增量收信**：新增 `folder_state` 表，按账户/文件夹记录 `UIDVALIDITY` + 已抓取最大 UID；UNSEEN 搜索照旧（服务端执行、开销极小），但只有超过水位的 UID 才真正下载原文。几百封旧未读的邮箱不再在每次推送/轮询时全部重新下载；中断的批次从最后完整抓取的 UID 续传
- **UIDVALIDITY 处理**：服务器重置 UID 时清空该文件夹本地缓存重新对账，防止 UID 复用导致新旧邮件错配去重
- **阅读区附件名**：`mails` 表新增 `attachment_names` 列（旧库自动 ALTER），阅读区显示「📎 附件：a.pdf、b.zip」
- 托盘角标数字改用 TrueType 字体（64px 下更大更清晰，失败回退）；无 Shell/托盘环境优雅降级；启动时逐个提示全部缺授权码的账户

---

## [1.5.0] — 2026-09-29

Incremental fetching (no more re-downloading all unseen mail) and attachment names in the reading pane. · 增量收信（不再反复整封下载未读邮件）与阅读区附件名展示。

### Added · 新增

**English**

- **Incremental fetch**: a new `folder_state` table records `UIDVALIDITY` + the highest fetched UID per account/folder; the (cheap, server-side) UNSEEN search is unchanged, but only UIDs above the watermark are actually downloaded. A mailbox with hundreds of old unread mail no longer re-downloads everything on every push/poll cycle; interrupted batches resume from the last fully fetched UID
- **UIDVALIDITY handling**: if the server resets UIDs, the folder's local cache is cleared and resynced, preventing new mail from being deduplicated against recycled UIDs
- **Attachment names in the reading pane**: the `mails` table gains an `attachment_names` column (auto-ALTER for old DBs) and the reading pane shows `📎 附件：a.pdf、b.zip`
- Tray badge digits now render with a TrueType font (larger/clearer at 64 px, graceful fallback); the tray degrades gracefully on systems without a shell; all accounts missing auth codes are prompted one after another at startup

**中文**

- **增量收信**：新增 `folder_state` 表，按账户/文件夹记录 `UIDVALIDITY` + 已抓取最大 UID；UNSEEN 搜索照旧（服务端执行、开销极小），但只有超过水位的 UID 才真正下载原文。几百封旧未读的邮箱不再在每次推送/轮询时全部重新下载；中断的批次从最后完整抓取的 UID 续传
- **UIDVALIDITY 处理**：服务器重置 UID 时清空该文件夹本地缓存重新对账，防止 UID 复用导致新旧邮件错配去重
- **阅读区附件名**：`mails` 表新增 `attachment_names` 列（旧库自动 ALTER），阅读区显示「📎 附件：a.pdf、b.zip」
- 托盘角标数字改用 TrueType 字体（64px 下更大更清晰，失败回退）；无 Shell/托盘环境优雅降级；启动时逐个提示全部缺授权码的账户

---

## [1.4.0] — 2026-09-29

Hardening release from a three-way multi-agent code audit: data-loss prevention, concurrency fixes, and UI robustness. · 基于三路多 Agent 代码审查的加固版本：防丢数据、并发修复与 UI 健壮性。

### Fixed · 修复

**English**

- **No more silent data loss** (audit P0): `config.json` and `secrets.bin` are now written atomically (temp file + `os.replace`); a corrupt config is backed up as `*.corrupt` instead of being silently replaced by defaults; a corrupt password store aborts the save instead of wiping all other passwords
- **「立即收信」 actually works now**: the button previously did nothing at all — `MailClient` gained a wake event that interrupts the IDLE wait / polling sleep and fetches immediately (also wired to the tray command)
- **IDLE no longer reconnects every 24 minutes**: waiting now uses `select.select` slices instead of a 24-min socket timeout; `imaplib`'s file object was permanently poisoned by the first timeout (`SocketIO._timeout_occurred`), so every keep-alive cycle used to abort and re-login (triggering provider rate limits)
- **stop() closes the socket**: account edit/remove/pause now terminates the old worker immediately instead of leaving it blocked in a read for up to 24 minutes with two connections fetching the same mailbox
- **Unclosed `<script>`/`<style>` no longer swallows the whole body**: HTML is CDATA-scanned, so broken marketing mail could produce empty bodies; parsing now recovers at the first real markup and re-parses the remainder
- **`search_mails` escapes `%`/`_`** (`ESCAPE '\'`) — searching `100%` no longer prefix-matches everything; count + rows now run in one connection (no racy totals)
- **`guess_host` domain boundary**: `user@myqq.com` / `user@x163.com` no longer resolve to `imap.qq.com` / `imap.163.com` — credentials could be sent to the wrong server
- **Edit-account no longer demands re-typing the auth code**: leave the password field empty to keep the stored one (still required for new accounts)
- **Emoji no longer corrupt rich text**: HTML export and formatting now walk Tcl indices (UTF-16 code units) instead of Python code points, so styling after astral chars stays aligned
- **Save-to-sent on 163/126 fixed**: folder names from `LIST` are modified-UTF-7 (`&XfJT0ZAB-`) and were never matched before; now decoded and the real folder name is APPENDed
- **Event loop can no longer go deaf**: `_poll_events` is exception-guarded and always re-arms its `after` — a single handler exception previously killed all mail/tray events permanently
- **Composing**: closing during send asks for confirmation and the completion callback tolerates a destroyed window; picking a color first clears existing color tags (no stacking/unpredictable output)
- **Single-instance false positive fixed**: a NULL mutex handle (creation failure) is no longer treated as "first instance"
- **Migration hardening**: half-completed upgrades (stale `mails_new` table) and older schemas with missing columns now recover instead of crashing at every startup
- **Right-click menus are destroyed after popup** (long-running tray apps accumulated dead menu widgets); IMAP connections get a 15 s timeout; malformed FETCH replies are skipped

**中文**

- **不再静默丢数据**（审查 P0）：`config.json` 与 `secrets.bin` 改为原子写（临时文件 + `os.replace`）；配置损坏时先备份为 `*.corrupt` 再回默认，绝不用空配置覆盖原始数据；密码库损坏时中止保存而非清空其他所有密码
- **「立即收信」真的生效了**：此前按钮是空操作——MailClient 增加唤醒事件，打断 IDLE 等待/轮询睡眠立即抓信（托盘命令同样生效）
- **IDLE 不再每 24 分钟断线重连**：等待改用 `select.select` 分片，不再对 socket 设 24 分钟超时——imaplib 的文件对象一旦超时就被永久污染（`SocketIO._timeout_occurred`），导致每个保活周期必然报错重登（触发服务商频控）
- **stop() 直接关闭 socket**：编辑/删除/暂停账户后旧线程立刻退出，不再阻塞在 read 上最长 24 分钟、两条连接同时拉同一邮箱
- **未闭合 `<script>/<style>` 不再吞掉整封正文**：此类 HTML 处于 CDATA 模式，坏邮件正文可能整个为空；现在从第一处真实标记恢复并重新解析剩余部分
- **`search_mails` 转义 `%`/`_`**（`ESCAPE '\'`）——搜「100%」不再前缀匹配所有邮件；计数与取行同一连接完成（消除竞态）
- **`guess_host` 域名边界**：`user@myqq.com` / `user@x163.com` 不再命中 `imap.qq.com` / `imap.163.com`——授权码可能被发给错误服务器
- **编辑账户不再强制重输授权码**：密码留空即沿用已存授权码（新增账户仍必填）
- **emoji 不再打乱富文本**：HTML 导出与格式化改按 Tcl 索引（UTF-16 代码单元）推进，星形平面字符之后的样式不再错位
- **163/126 已发送同步修复**：`LIST` 返回的文件夹名是修改版 UTF-7（`&XfJT0ZAB-`），此前永远匹配不上；现在解码后用真实文件夹名 APPEND
- **事件循环不再「失聪」**：`_poll_events` 加异常防护并始终重挂 `after`——此前一次处理器异常就会永久断掉全部收信/托盘事件
- **写信窗口**：发送中关窗先确认，完成回调容忍窗口已销毁；取色先清除已有颜色标签（不再叠加导致导出不可预测）
- **单实例假阳性修复**：互斥体创建失败（句柄为 NULL）不再被当成「首个实例」
- **迁移加固**：升级中断留下的 `mails_new` 残表、缺列的更老库，都能恢复而非每次启动崩溃
- **右键菜单弹出后销毁**（长年运行的托盘应用不再累积死控件）；IMAP 连接统一 15 秒超时；跳过畸形 FETCH 应答

### Changed · 变更

**English**

- New features: **local delete** (mail list right-click / Delete key, server untouched); search debounced 300 ms; sent mail gets `Date`/`Message-ID` headers
- Unit suite grows to 43 cases (new `tests/test_robustness.py`: LIKE escaping, config atomicity, parser recovery, migration idempotency, SMTP headers, domain boundaries)

**中文**

- 新增功能：**本地删除邮件**（邮件列表右键 / Delete 键，不动服务器）；搜索 300ms 防抖；发出的邮件补齐 `Date`/`Message-ID` 头
- 单测增至 43 例（新增 `tests/test_robustness.py`：LIKE 转义、配置原子性、解析器恢复、迁移幂等、SMTP 头、域名边界）

---

## [1.3.0] — 2026-09-29

Full-text search with filters, and per-account receive-folder selection. · 全文搜索与过滤，账户级收信文件夹选择。

### Added · 新增

**English**

- **Full-text search**: the search box now also matches the mail **body**, pushed down into SQLite (LIKE) so results are no longer capped by the 200-row front-end list; subject / sender name / sender address / body all searchable
- **Quick filters**: an All / **Unread** / **Has attachment** dropdown next to the search box, composable with the account filter and keyword
- The status bar shows `N total, M shown` while a filter or keyword is active
- **Receive folder selection**: each account can fetch from any IMAP folder (default INBOX — Spam, archive folders, etc.)
- The account dialog has a **收信文件夹 (receive folder)** row with a **Fetch** button that lists the server's folders live (worker thread, `LIST "" "*"`, `\Noselect` skipped, **IMAP modified-UTF-7 decoded** so Chinese folder names like 已发送 render properly)

**中文**

- **全文搜索**：搜索框现在同时匹配邮件**正文**，并下沉到 SQLite（LIKE）执行，不再受前端 200 条列表截断；主题 / 发件人姓名 / 发件人地址 / 正文均可命中
- **快捷过滤**：搜索框旁新增 全部 / **只看未读** / **有附件** 下拉筛选，可与账户筛选、关键字任意叠加
- 筛选或搜索生效时状态栏显示「共 N 封，显示 M 封」
- **收信文件夹选择**：每个账户可指定任意 IMAP 文件夹收信（默认 INBOX——垃圾箱、归档文件夹等均可）
- 账户对话框新增**收信文件夹**行与**获取**按钮：子线程实时 `LIST "" "*"` 列出服务器全部文件夹（跳过 `\Noselect`，内置 **IMAP 修改版 UTF-7 解码**，「已发送」等中文名正常显示）

### Changed · 变更

**English**

- `mails` table gains a `folder` column; unique key moves from `(account_id, uid)` to `(account_id, folder, uid)` — UID spaces are per-folder. Old databases migrate in-place in one transaction (existing rows become INBOX), zero data loss
- `mail_client.py`: every `SELECT`/fetch site (connect / IDLE loop / polling loop) now uses the account's configured folder
- `database.py` connections are now committed **and closed** via a contextmanager — previously the raw `with sqlite3.connect()` never closed connections, leaving the db file handle permanently locked on Windows
- Unit suite grows to 29 cases (new `tests/test_search.py`: migration, folder isolation/dedup, search composition, mUTF-7)

**中文**

- `mails` 表新增 `folder` 列；唯一键由 `(account_id, uid)` 升级为 `(account_id, folder, uid)`（UID 按文件夹独立）。旧库在单事务中原地迁移（存量邮件记为 INBOX），零数据丢失
- `mail_client.py`：连接 / IDLE 循环 / 轮询循环三处 SELECT/抓取全部改用账户配置的文件夹
- `database.py` 连接改为 contextmanager——提交事务并**真正关闭连接**（原先 `with sqlite3.connect()` 从不关闭，Windows 上 db 文件句柄一直被占用）
- 单测增至 29 例（新增 `tests/test_search.py`：迁移、文件夹隔离/去重、搜索组合、mUTF-7 解码）

---

## [1.2.0] — 2026-09-29

CC/BCC recipients and rich-text (HTML) composing. · 抄送/密送与 HTML 富文本写信。

### Added · 新增

**English**

- **CC & BCC fields** in the compose window; multiple addresses per field (comma/semicolon/space separated); BCC recipients stay hidden from each other per standard semantics
- **Rich-text body**: bold / italic / underline / font color via a format toolbar in the compose window (pure tkinter tags, zero new dependencies)
- Sent as `multipart/alternative` — HTML version plus an automatic plain-text fallback, so every client renders something sensible
- Recipients without any formatting still go out as plain text (unchanged behavior)

**中文**

- 写信窗口新增**抄送（CC）/密送（BCC）**输入行；每行支持逗号/分号/空格分隔多个地址；密送收件人互相不可见（标准语义）
- **富文本正文**：写信窗口格式工具条支持**加粗 / 斜体 / 下划线 / 字体颜色**（纯 tkinter 标签实现，零新增依赖）
- 发送时生成 `multipart/alternative`——HTML 版本 + 自动纯文本兜底，任何客户端都能正常显示
- 未使用任何格式时仍按纯文本发送（行为不变）

### Changed · 变更

**English**

- `build_mime()`/`send_mail()` accept optional `cc_addrs/bcc_addrs/html_body`; envelope recipients = To + Cc + Bcc
- New `ui/richtext.py`: Text-widget tags → HTML export (offline-testable); unit suite grew to 15 cases
- Real-send verified against NetEase 163: alternative/HTML part, Cc header and self-CC delivery all confirmed

**中文**

- `build_mime()`/`send_mail()` 新增可选参数 `cc_addrs/bcc_addrs/html_body`；信封收件人 = 收件人 + 抄送 + 密送
- 新增 `ui/richtext.py`：Text 标签 → HTML 导出（可离线单测）；单测增至 15 例
- 已实测网易 163 真实链路：alternative/HTML 分部、Cc 头、抄送投递均确认正常

---

## [1.1.1] — 2026-09-29

Copy-anywhere support and a friendlier launch behavior. · 全局复制能力与更友好的启动行为。

### Added · 新增

**English**

- Right-click **Copy** everywhere:
  - Mail list → copy subject, sender name, sender e-mail address, or the full body
  - Account panel → copy an account's e-mail address or display name (handy for grabbing your own address)
  - Reading pane → copy the selected text or select all (subject fragments included)
- Status-bar confirmation after every copy; empty fields are grayed out instead of copying nothing

**中文**

- 全局右键复制：
  - 邮件列表 → 复制主题、发件人姓名、发件人邮箱地址、整封正文
  - 账户面板 → 复制账户邮箱地址或账户名（拿自己的地址一步到位）
  - 阅读区 → 复制选中文本或全选（标题任意片段都可选）
- 每次复制在状态栏提示"已复制"；空字段置灰，避免复制到空值

### Changed · 变更

**English**

- Launch behavior: double-clicking the exe now opens the main window directly; only the auto-start entry (`--minimized`) still boots silently to the tray
- `start_minimized` config key kept for compatibility but no longer drives launch visibility

**中文**

- 启动行为：双击 exe 直接显示主窗口；仅开机自启入口（`--minimized` 参数）保持静默进托盘
- `start_minimized` 配置键保留兼容，但不再决定启动时是否显示窗口

---

## [1.1.0] — 2026-09-29

Sending mail, single-instance behavior, and UI refinements. · 新增发信能力、单实例行为与界面优化。

### Added · 新增

**English**

- **Compose & send mail**: write new mail from any configured account, with multiple recipients and attachments
- **Reply**: one click on the toolbar prefills recipient, subject (`回复：…`) and a quoted header of the original mail
- Compose window runs the SMTP transfer on a worker thread — the UI never freezes, double-sends are locked out
- Sent-mail sync: after sending, a short IMAP connection tries to APPEND the message to the server's Sent folder; failures degrade silently (NetEase keeps sent mail server-side anyway)
- Single-instance enforcement: launching the exe again wakes the running app and forces its window to the foreground (Win32 named mutex + named event, zero dependencies)
- Collapsible account panel: the left "Mailboxes" pane (incl. *All Mail*) folds away via an always-visible edge strip; state persists in `config.json`
- SMTP endpoints auto-derived from IMAP hosts (`imap.x.com → smtp.x.com:465`), overridable per account

**中文**

- **写信与发信**：用已配置的账户撰写新邮件，支持多收件人与附件
- **回复**：工具栏一键预填收件人、主题（`回复：…`）与原邮件引用头
- 写信窗口在后台线程执行 SMTP 发送，界面全程不卡顿，且锁定按钮防止重复发送
- 已发送同步：发信成功后尝试通过 IMAP 追加到服务器"已发送"文件夹，失败静默降级（网易网页端本就会保存发件记录）
- 单实例：再次双击 exe 会唤醒已运行实例并把主窗口强制置前（Win32 命名互斥体 + 命名事件，零依赖）
- 账户面板可收起：窗口左缘常驻细条一键折叠"邮箱账户"栏，状态记忆在 `config.json`
- SMTP 服务器由 IMAP 主机自动推导（`imap.x.com → smtp.x.com:465`），也可按账户覆盖

### Changed · 变更

**English**

- `Account` model gained `smtp_host`/`smtp_port` fields; old `config.json` files need no migration
- Toolbar gained "✉ 写邮件 / Compose" and "↩ 回复 / Reply" buttons; real SMTP delivery verified against NetEase 163 (smtp.163.com:465)
- New offline unit tests for MIME building, address parsing and endpoint derivation (8 cases)

**中文**

- `Account` 模型新增 `smtp_host`/`smtp_port` 字段，旧 `config.json` 无需迁移
- 工具栏新增「✉ 写邮件」「↩ 回复」按钮；已实测网易 163（smtp.163.com:465）真实投递成功
- 新增 MIME 组装、地址解析、服务器推导的离线单测（8 例）

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
