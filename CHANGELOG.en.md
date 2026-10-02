# Changelog

All notable changes to **OneMail** are documented here. (中文版见 [CHANGELOG.md](CHANGELOG.md))

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/).

## [1.10.1] — 2026-10-02

Multi-agent review round: 12 hardening fixes for OAuth2 & image modules + 4 UX improvements.

### Fixed

- SMTP: socket leak on STARTTLS handshake failure; explicit certificate verification on both 465 and 587 paths; OAuth2 errors no longer fake a 334 response code
- OAuth2: token expiry margin clamped by lifetime (short-lived tokens no longer refresh on every connection); corrupt expires_at treated as expired instead of raising; unknown provider raises a clear error (no more sending Google tokens to Microsoft); no stray CRLF after a failed IMAP XOAUTH2 exchange
- Security: Client Secret now DPAPI-encrypted (was plaintext in config.json via the Account); editing an account no longer wipes the stored secret
- Images: PIL decode moved off the main thread + 12 MP pixel cap (huge images no longer freeze the UI); reading-pane read-only state restored in a finally; WebP magic added; data URIs accept URL-safe base64; duplicate method definition removed; single source for the image-count limit
- Threading discipline: all tk variables captured before starting background threads in the account dialog

### Added

- Expired/revoked OAuth2 tokens now show an explicit "sign in again" status and back off immediately instead of retrying forever
- Friendly mail-list dates: time-only today, month-day+time this year, full date across years
- Enter opens the selected mail; Esc clears the search box
- "Open Log Folder" in the settings dialog; AI-key hint and save-failure text now localized

## [1.10.0] — 2026-10-02

Gmail/Outlook OAuth2 sign-in, mail image display, top-left settings entry, right-click new folder in the mail list.

### Added

- Gmail / Outlook OAuth2: accounts can pick the OAuth2 auth method — authorization code + PKCE + loopback browser sign-in (stdlib only, zero new dependencies); tokens (incl. the refresh token) are DPAPI-encrypted and stored locally with automatic refresh (locked check-refresh-save, no concurrent double refresh); IMAP/SMTP both use XOAUTH2 (Outlook SMTP 587 STARTTLS handled); Gmail/Outlook domains auto-fill official server presets. Users register their own app in Google Cloud / Azure for a Client ID (steps in the README)
- Mail image display: `<img>` in HTML mails is no longer just a placeholder — CID inline images (parsed from the raw mail), data: URIs and remote http(s) images all display; safety limits: ≤3 MB each, ≤10 per mail, PNG/JPEG/GIF magic-byte checks, 640px width cap, all loaded on background threads, and images for a mail you already left are discarded
- Top-left settings entry: the ⚙ Settings button moved to the first position of the toolbar
- "New Folder…" added to the mail-list context menu

### Changed

- OAuth2 adaptations for raw-fetch & image loading: flag_sync no longer treats password-less OAuth2 accounts as missing auth codes; the compose sender list includes OAuth2 accounts
- Docs: bilingual README / CHANGELOG updated with OAuth2 and image details

## [1.9.0] — 2026-09-30

Rich-text display fix, theme & language settings, attachment open/save-as, AI summary & write, local mail folders.

### Fixed

- Rich-text mails now render properly in the reading pane (bold/italic/underline/color/headings/lists/links) instead of stripped plain text. The HTML body is stored at fetch time (truncated to 128 KB) and rendered by a built-in zero-dependency HTML-to-Text renderer; no remote resource is ever loaded (images ignored) and script/style content is dropped
- Automatic migration: the mails table gains body_html and local_folder columns at startup, no manual action needed

### Added

- Themes: Light (default) and Dark palettes, switchable in the settings dialog (applies after restart)
- Language: 中文 / English UI, switchable in the settings dialog (applies after restart)
- Attachment Open / Save As: reading-pane right-click → Attachments → open each file with the system default program (temp files are reused per mail, no re-download) or save to a chosen path; "Save All To…" kept
- AI summary & AI write: OpenAI-compatible endpoints (DeepSeek, OpenAI GPT, Qwen, …) with user-provided base URL / model / API key in the settings dialog; the key is stored encrypted via Windows DPAPI, never in plaintext; all network calls run on background threads, UI never blocks
- Local mail folders: create/delete custom folders, move mails in and back to the inbox via right-click, filter and unread badges per folder in the account panel (deleting a folder moves its mails back to the inbox; the server source folder is kept separately so attachment fetch and read-sync stay correct)

### Changed

- New settings dialog (toolbar ⚙): unified entry for language / theme / AI configuration
- Docs reorganized: bilingual README and CHANGELOG split into separate Chinese and English files (README.md / README.en.md, CHANGELOG.md / CHANGELOG.en.md); all historical development-plan documents removed

## [1.8.1] — 2026-09-29

Hardening round 2 (agent review): write-order, locking & transaction fixes.

### Fixed


- Flag-sync retries are now inlined within the group instead of re-queued: a re-queued retry could land *after* a newer opposite-direction task (mark read → immediately mark unread) and leave the server flag opposite to the user's last intent, permanently inconsistent
- `mark_all_read` now selects the pending rows and flips the flags inside one SQLite transaction — mails arriving in the gap can no longer end up "read locally, unread on server forever" (the watermark would never revisit them)
- `load_password` now takes the secrets lock: the flag-sync worker thread could race `os.replace` in `save/delete_password` on Windows and make account saving fail with PermissionError
- Editing an account builds a brand-new `Account` and swaps it atomically instead of mutating fields in place, so worker threads can never observe a torn "new host + old port" combination (IDLE probe resets when connection settings change)
- "Mark as unread" short-circuits when the mail is already unread (no pointless server round-trip)
- `tools/verify_163.py --store`: live-mailbox round-trip for the STORE path (clear `\Seen` → assert SEARCH UNSEEN → restore → assert gone), verifying real-server permission for non-readonly writes

## [1.8.0] — 2026-09-29

Mark as unread (local + server).

### Added


- Right-click a mail in the list → "标记为未读": resets local read state and clears the server `\Seen` flag through the same background flag-sync channel (v1.7.0), so webmail/phone show it unread again
- Server writes stay batched/deduplicated/toggleable exactly like read-sync; with the tray toggle off only local state changes

## [1.7.0] — 2026-09-29

Server read-flag sync.

### Added


- Read-state sync: marking a mail read (open / mark-read / mark-all-read, from window or tray) now writes the `\Seen` flag back to the server via a short-lived background IMAP connection, so phones and webmail no longer show everything as unread
- Batched and grouped: jobs are deduplicated, grouped per (account, folder), UIDs numerically sorted and sent in 50-UID `.SILENT` chunks — one connection per group even for "mark all read"; failed chunks (only) retry once, then drop silently (idempotent operation, no data loss); everything is logged to onemail.log
- New tray toggle "同步已读到服务器" (config `sync_read_flags`, default on) for users who want OneMail to stay strictly read-only

### Security


- Fetch path stays strictly `readonly` + `BODY.PEEK`; flag writes run on a separate short-lived connection so the polling channel's socket state can never be affected

## [1.6.2] — 2026-09-29

Per-account connection status in the account panel.

### Added


- Account cards now show the latest connection status inline (已连接 / 收到新邮件推送 / 轮询中 / 连接异常…), so a broken account is visible at a glance instead of only flashing through the status bar

## [1.6.1] — 2026-09-29

Third review pass fixes over the save-attachment and folder-wire changes.

### Fixed


- **Save attachments used the account's *current* folder instead of the mail's source folder** — after changing an account's receive folder, saving attachments of an old mail could silently fetch a *different* mail sharing the same UID; now uses the per-mail `folder` column
- **`folder_to_wire` mishandled bare `&` in ASCII folder names** (`A&B` is invalid mUTF-7; `Tom&Jerry-x` was misdetected as a wire-format name): ASCII `&` is now always escaped to `&-`, no guessing
- **A permanently failing UID could head-block all newer mail**: first failure ends the batch (one retry), repeated failures are skipped via a per-client failure memory
- **IDLE stop no longer downgrades the account**: a stop/pause landing in the continuation-line window no longer sets `idle_supported=False` on the reusable account object
- `message/rfc822` (.eml) attachments are now saved via `part.as_bytes()` (previously skipped silently); parts with encoding defects are skipped rather than saved as garbage; Windows reserved device names (con/nul/…) suffixed with `_`
- Deleting the currently-open mail now clears the reading pane and the attachment action

## [1.6.0] — 2026-09-29

Attachment saving from the reading pane (on-demand server re-fetch).

### Added


- **Save attachments**: reading-pane right-click → 保存附件… — pick a folder and OneMail fetches the raw message from the server by UID (BODY.PEEK[], read-only), extracts every attachment with proper RFC 2047 name decoding (Chinese names intact) and writes them out, deduplicating name collisions as `name(1).ext`. Runs on a worker thread with status-bar progress/errors
- `MailClient.fetch_raw()` + `parser.extract_attachments()`: reusable, offline-testable building blocks; name-collision and unnamed-attachment edge cases handled
- Verified end-to-end against a live NetEase 163 mailbox (fetch_raw returns the original bytes)

## [1.5.2] — 2026-09-29

Sortable columns and a real-mailbox end-to-end verification tool.

### Added


- **Sortable columns**: click 来源 / 发件人 / 主题 / 时间 headers to sort (click again to reverse, ▲/▼ indicator); sorting is UI-side so it composes with search and filters
- `tools/verify_163.py`: end-to-end verification against a real mailbox (temp DB, read-only effects) — connect, UIDVALIDITY read, folder listing with mUTF-7 decoding, incremental fetch watermark behavior. Verified live against NetEase 163: 6 folders decoded correctly (草稿箱/已发送/垃圾邮件…), first pass fetched 4 unseen mails, second pass downloaded 0 with unchanged watermark

## [1.5.1] — 2026-09-29

Follow-up fixes from the second review pass over v1.4/v1.5.

### Fixed


- **(P0) New-mail loss window closed**: the incremental watermark was advanced before the mails were actually inserted (insertion used to happen on the UI thread up to 500 ms later, and quit() exits via `os._exit`) — a mail fetched in that window would be permanently skipped by `uid <= watermark` on the next run. Fetching now inserts synchronously on the worker thread, advances the watermark only after a confirmed insert, and notifies with genuinely-new mails only; quit() also drains the event queue before exiting
- **(P1) 获取 (Fetch folder list) button always failed** with a `NameError` (`_send_client_id` is a class staticmethod and was called bare)
- **(P1) Non-default folders could never receive mail**: imaplib sends commands ascii-encoded and unquoted — Chinese folder names raised `UnicodeEncodeError` and "Sent Messages"-style names were split into multiple atoms, both causing endless reconnects. Folder names are now converted back to modified-UTF-7 and quoted on the wire (`_folder_wire()`); names already in wire form are used as-is
- **(P1) A single failed FETCH no longer skips that mail forever**: the watermark now only advances past successfully fetched UIDs — a failed fetch ends the batch and the mail is retried next cycle
- IDLE continuation-line wait is bounded (10 s) and tolerates untagged lines preceding the `+` (previously misjudged as "no IDLE support" and left the protocol out of sync)
- save_to_sent APPENDs with the server's raw mUTF-7 folder name (decoded names crashed on Chinese providers) and takes the hierarchy delimiter from the LIST response instead of hardcoding `/`
- Parser recovery is depth-limited (8) against pathological nested-markup inputs; `folder_state` DDL moved into `init()`; badge font cached at module level

### Added


- **Incremental fetch**: a new `folder_state` table records `UIDVALIDITY` + the highest fetched UID per account/folder; the (cheap, server-side) UNSEEN search is unchanged, but only UIDs above the watermark are actually downloaded. A mailbox with hundreds of old unread mail no longer re-downloads everything on every push/poll cycle; interrupted batches resume from the last fully fetched UID
- **UIDVALIDITY handling**: if the server resets UIDs, the folder's local cache is cleared and resynced, preventing new mail from being deduplicated against recycled UIDs
- **Attachment names in the reading pane**: the `mails` table gains an `attachment_names` column (auto-ALTER for old DBs) and the reading pane shows `📎 附件：a.pdf、b.zip`
- Tray badge digits now render with a TrueType font (larger/clearer at 64 px, graceful fallback); the tray degrades gracefully on systems without a shell; all accounts missing auth codes are prompted one after another at startup

## [1.5.0] — 2026-09-29

Incremental fetching (no more re-downloading all unseen mail) and attachment names in the reading pane.

### Added


- **Incremental fetch**: a new `folder_state` table records `UIDVALIDITY` + the highest fetched UID per account/folder; the (cheap, server-side) UNSEEN search is unchanged, but only UIDs above the watermark are actually downloaded. A mailbox with hundreds of old unread mail no longer re-downloads everything on every push/poll cycle; interrupted batches resume from the last fully fetched UID
- **UIDVALIDITY handling**: if the server resets UIDs, the folder's local cache is cleared and resynced, preventing new mail from being deduplicated against recycled UIDs
- **Attachment names in the reading pane**: the `mails` table gains an `attachment_names` column (auto-ALTER for old DBs) and the reading pane shows `📎 附件：a.pdf、b.zip`
- Tray badge digits now render with a TrueType font (larger/clearer at 64 px, graceful fallback); the tray degrades gracefully on systems without a shell; all accounts missing auth codes are prompted one after another at startup

## [1.4.0] — 2026-09-29

Hardening release from a three-way multi-agent code audit: data-loss prevention, concurrency fixes, and UI robustness.

### Fixed


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

### Changed


- New features: **local delete** (mail list right-click / Delete key, server untouched); search debounced 300 ms; sent mail gets `Date`/`Message-ID` headers
- Unit suite grows to 43 cases (new `tests/test_robustness.py`: LIKE escaping, config atomicity, parser recovery, migration idempotency, SMTP headers, domain boundaries)

## [1.3.0] — 2026-09-29

Full-text search with filters, and per-account receive-folder selection.

### Added


- **Full-text search**: the search box now also matches the mail **body**, pushed down into SQLite (LIKE) so results are no longer capped by the 200-row front-end list; subject / sender name / sender address / body all searchable
- **Quick filters**: an All / **Unread** / **Has attachment** dropdown next to the search box, composable with the account filter and keyword
- The status bar shows `N total, M shown` while a filter or keyword is active
- **Receive folder selection**: each account can fetch from any IMAP folder (default INBOX — Spam, archive folders, etc.)
- The account dialog has a **收信文件夹 (receive folder)** row with a **Fetch** button that lists the server's folders live (worker thread, `LIST "" "*"`, `\Noselect` skipped, **IMAP modified-UTF-7 decoded** so Chinese folder names like 已发送 render properly)

### Changed


- `mails` table gains a `folder` column; unique key moves from `(account_id, uid)` to `(account_id, folder, uid)` — UID spaces are per-folder. Old databases migrate in-place in one transaction (existing rows become INBOX), zero data loss
- `mail_client.py`: every `SELECT`/fetch site (connect / IDLE loop / polling loop) now uses the account's configured folder
- `database.py` connections are now committed **and closed** via a contextmanager — previously the raw `with sqlite3.connect()` never closed connections, leaving the db file handle permanently locked on Windows
- Unit suite grows to 29 cases (new `tests/test_search.py`: migration, folder isolation/dedup, search composition, mUTF-7)

## [1.2.0] — 2026-09-29

CC/BCC recipients and rich-text (HTML) composing.

### Added


- **CC & BCC fields** in the compose window; multiple addresses per field (comma/semicolon/space separated); BCC recipients stay hidden from each other per standard semantics
- **Rich-text body**: bold / italic / underline / font color via a format toolbar in the compose window (pure tkinter tags, zero new dependencies)
- Sent as `multipart/alternative` — HTML version plus an automatic plain-text fallback, so every client renders something sensible
- Recipients without any formatting still go out as plain text (unchanged behavior)

### Changed


- `build_mime()`/`send_mail()` accept optional `cc_addrs/bcc_addrs/html_body`; envelope recipients = To + Cc + Bcc
- New `ui/richtext.py`: Text-widget tags → HTML export (offline-testable); unit suite grew to 15 cases
- Real-send verified against NetEase 163: alternative/HTML part, Cc header and self-CC delivery all confirmed

## [1.1.1] — 2026-09-29

Copy-anywhere support and a friendlier launch behavior.

### Added


- Right-click **Copy** everywhere:
  - Mail list → copy subject, sender name, sender e-mail address, or the full body
  - Account panel → copy an account's e-mail address or display name (handy for grabbing your own address)
  - Reading pane → copy the selected text or select all (subject fragments included)
- Status-bar confirmation after every copy; empty fields are grayed out instead of copying nothing

### Changed


- Launch behavior: double-clicking the exe now opens the main window directly; only the auto-start entry (`--minimized`) still boots silently to the tray
- `start_minimized` config key kept for compatibility but no longer drives launch visibility

## [1.1.0] — 2026-09-29

Sending mail, single-instance behavior, and UI refinements.

### Added


- **Compose & send mail**: write new mail from any configured account, with multiple recipients and attachments
- **Reply**: one click on the toolbar prefills recipient, subject (`回复：…`) and a quoted header of the original mail
- Compose window runs the SMTP transfer on a worker thread — the UI never freezes, double-sends are locked out
- Sent-mail sync: after sending, a short IMAP connection tries to APPEND the message to the server's Sent folder; failures degrade silently (NetEase keeps sent mail server-side anyway)
- Single-instance enforcement: launching the exe again wakes the running app and forces its window to the foreground (Win32 named mutex + named event, zero dependencies)
- Collapsible account panel: the left "Mailboxes" pane (incl. *All Mail*) folds away via an always-visible edge strip; state persists in `config.json`
- SMTP endpoints auto-derived from IMAP hosts (`imap.x.com → smtp.x.com:465`), overridable per account

### Changed


- `Account` model gained `smtp_host`/`smtp_port` fields; old `config.json` files need no migration
- Toolbar gained "✉ 写邮件 / Compose" and "↩ 回复 / Reply" buttons; real SMTP delivery verified against NetEase 163 (smtp.163.com:465)
- New offline unit tests for MIME building, address parsing and endpoint derivation (8 cases)

## [1.0.0] — 2026-09-28

First public release.

### Added


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

### Fixed


- `AccountDialog` crashed on open due to a missing argument in the layout helper
- Event loop stalled after the first status event (log helper displaced the scheduler call), freezing tray badge and status bar updates
- Raw IDLE desync with servers replying non-standard continuation lines, previously surfaced as `command ... allowed in states SELECTED` reconnect loops

### Known Limitations


- NetEase mailboxes have no IDLE push; new-mail latency equals the polling interval (default 5 min, configurable in `config.json`)
- Sending/replying, OAuth2 (Gmail/Outlook), search and filter rules are planned for later releases
