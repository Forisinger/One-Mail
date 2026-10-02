# OneMail — Technical Documentation

> Version: v1.0｜Date: 2026-09-28｜Companion doc: [development-plan.md](development-plan.md)

## 1. Technology Stack

| Module | Choice | Rationale |
|---|---|---|
| Language | Python 3.12 | As required; mature ecosystem |
| Fetch protocol | IMAP4 (stdlib `imaplib`) + IMAP IDLE | IDLE is server push — no polling loops, ~0% idle CPU |
| Mail parsing | stdlib `email` | Zero third-party deps; full MIME/attachment/encoding coverage |
| GUI | tkinter (stdlib) | Tiny footprint — the key to "minimal resource usage" |
| Tray | pystray + Pillow | Lightweight tray icon & menu |
| Notifications | pystray balloon (Shell_NotifyIcon) | Native bubbles, zero extra processes |
| Storage | SQLite (stdlib `sqlite3`) | Single file, zero config |
| Password crypto | Windows DPAPI (pure ctypes) | OS-level encryption bound to the user; no key management |
| Auto-start | Registry `HKCU\...\Run` (stdlib `winreg`) | Per-user, no admin rights |
| Packaging | PyInstaller (`--onefile`, no console) | Single-exe distribution |

**Dependency budget**: third-party runtime deps are exactly two — `pystray` and `Pillow`. Everything else is stdlib. Packaged size ≈ 20 MB; resident memory target < 50 MB.

## 2. Architecture

```
┌─────────────────────────────────────────────┐
│                  OneMail.exe                │
│                                             │
│  ┌─────────┐   event queue   ┌────────────┐ │
│  │ UI layer │◄───────────────│ Fetch core │ │
│  │ tkinter │                 │ (core/)    │ │
│  │ main win│                 │            │ │
│  │ tray    │                 │ Scheduler  │ │──► config.json (accounts/settings)
│  └─────────┘                 │ MailClient │ │──► onemail.db   (mail cache)
│       ▲                      │ (per acct) │ │──► secrets.bin  (DPAPI passwords)
│       │ notifications        └─────┬──────┘ │
│  ┌─────────┐                       │ IMAP   │
│  │ Windows │                       ▼        │
│  │ tray    │              [Mailbox A] [Mailbox B] ...
│  └─────────┘                              │
└─────────────────────────────────────────────┘
```

**Thread model** (the core of the low-footprint design):

- Main thread: tkinter UI + tray
- **1 daemon thread per enabled account**, running an IMAP IDLE long connection — the server pushes new-mail events; between pushes the thread blocks on the socket, consuming no CPU
- IDLE is refreshed every ≤ 24 minutes (RFC 2177); broken connections reconnect with exponential backoff
- Accounts without IDLE support (e.g. NetEase) fall back to polling, interval user-configurable (default 300 s)
- UI consumes engine events through a `queue.Queue` polled every 500 ms

## 3. Repository Layout

```
OneMail/
├── docs/                  # technical docs (English & Chinese)
├── src/
│   ├── main.py            # entry point: single-instance check, engine + UI + tray
│   ├── core/
│   │   ├── account.py     # account model (IMAP+SMTP), manager, provider presets
│   │   ├── mail_client.py # IMAP client (connect/IDLE/poll/reconnect)
│   │   ├── smtp_client.py # outgoing mail: MIME building, sending, Sent sync
│   │   ├── flag_sync.py   # read-flag sync (short-connection batched STORE)
│   │   ├── ai_client.py   # AI client (OpenAI-compatible, v1.9.0)
│   │   ├── oauth2.py      # OAuth2 (Gmail/Outlook XOAUTH2, v1.10.0)
│   │   ├── parser.py      # MIME parsing: body (plain + HTML), attachments, headers
│   │   ├── scheduler.py   # multi-account scheduling, event fan-out
│   │   ├── security.py    # DPAPI encrypt/decrypt (ctypes)
│   │   └── single_instance.py # Win32 named-mutex single instance + wake event
│   ├── storage/
│   │   ├── database.py    # SQLite schema & access
│   │   └── config.py      # config.json read/write
│   ├── ui/
│   │   ├── main_window.py # main window (accounts / local folders / mail list / reader)
│   │   ├── compose_window.py # compose window (CC/BCC, rich text, AI write, threaded send)
│   │   ├── settings_dialog.py # settings: language / theme / AI (v1.9.0)
│   │   ├── htmltext.py    # HTML → Tk Text rich-text renderer (incoming, v1.9.0)
│   │   ├── imgload.py     # mail image loading (CID/remote, v1.10.0)
│   │   ├── richtext.py    # Tk Text rich-text tags → HTML export (outgoing)
│   │   ├── theme.py       # theme palettes: light / dark (v1.9.0)
│   │   ├── i18n.py        # zh/en string table (v1.9.0)
│   │   ├── tray.py        # tray icon, menu, unread badge
│   │   ├── icon.py        # programmatic icon + badge rendering
│   │   └── account_dialog.py
│   ├── notify.py          # tray balloon notifications
│   └── autostart.py       # registry auto-start toggle
├── tests/                 # unit tests (parser, provider presets)
├── assets/                # generated .ico
├── build.spec             # PyInstaller config
└── requirements.txt
```

## 4. Key Data Structures

**config.json** (passwords are NOT stored here — they live DPAPI-encrypted in `secrets.bin`):

```json
{
  "accounts": [
    {
      "id": "a1b2c3",
      "name": "Work mailbox",
      "email": "user@example.com",
      "imap_host": "imap.example.com",
      "imap_port": 993,
      "ssl": true,
      "enabled": true,
      "folder": "INBOX",
      "idle_supported": false,
      "poll_interval": 300,
      "smtp_host": "",
      "smtp_port": 465
    }
  ],
  "settings": {
    "autostart": true,
    "poll_interval_fallback": 300,
    "notify_sound": true,
    "start_minimized": false,
    "accounts_collapsed": false
  }
}
```

**SQLite**:

```sql
CREATE TABLE mails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,       -- source labeling key
    uid TEXT NOT NULL,
    folder TEXT DEFAULT 'INBOX',    -- receive folder (v1.3.0)
    message_id TEXT,
    from_addr TEXT, from_name TEXT,
    subject TEXT, body_text TEXT,
    has_attachment INTEGER DEFAULT 0,
    received_at TEXT, fetched_at TEXT,
    is_read INTEGER DEFAULT 0,
    UNIQUE(account_id, folder, uid)
);
CREATE INDEX idx_mails_account ON mails(account_id, received_at DESC);
```

## 5. Key Technical Points

### 1. IMAP IDLE push (low-footprint core)
- `imaplib` has no native IDLE; implemented at the socket layer: send `tag IDLE`, block on `readline()` for untagged `* n EXISTS`, then `DONE` and re-IDLE
- Continuation-line detection accepts any `+ ...` reply (provider messages differ)
- Servers close IDLE after ≤ 29 min; client re-issues IDLE every 24 min
- Connection state is verified before every fetch; on `BYE`/state loss the client raises an abort and reconnects — no busy error loops

### 2. Provider compatibility
- **NetEase (163/126) requires the IMAP `ID` extension** right after login; sent via `imaplib.Commands["ID"]` registration (`name/version` payload), failures ignored
- Common Chinese providers (QQ/163/126/Sina/Sohu/Aliyun/139) get preset IMAP hosts; unknown domains guess `imap.<domain>`
- Encoding fallback chain: `utf-8 → gbk → gb2312 → big5 → latin-1` (Chinese providers send lots of GBK)

### 3. Outgoing mail (SMTP, smtp_client.py)
- SMTP endpoint derived from the IMAP host (`imap.x.com → smtp.x.com:465`, SSL); overridable via `smtp_host`/`smtp_port` on the account
- `build_mime()` is offline-testable: UTF-8 headers via `email.header`; non-ASCII attachment filenames encoded per RFC 2231 (recipients see them decoded correctly)
- **v1.2**: `cc_addrs`/`bcc_addrs`/`html_body` — Cc written as a header; Bcc written as a header and stripped by `send_message` (still included in the envelope); `html_body` produces `multipart/alternative` (plain-text fallback + HTML)
- **v1.2 rich text**: `ui/richtext.py` walks the Tk Text tags character-by-character and exports `<b>/<i>/<u>/<span style>` HTML; a per-character combined font-tag model (7 b/i/u combos + independent color tags) avoids Tk tag-priority conflicts
- `send_mail()` runs on a **worker thread** (`SMTP_SSL → login → send_message`); the UI stays responsive and the send button is locked against double-clicks
- `save_to_sent()` is best-effort: a short IMAP connection probes the Sent/已发送 folder and APPENDs; any failure degrades silently (163 keeps sent mail server-side anyway)
- SMTP server rejections (554/551 etc.) are surfaced verbatim in the error dialog for easy diagnosis

### 4. Single instance & window wake-up (single_instance.py)
- A named mutex (`CreateMutexW`) prevents a second instance; the second process signals a named event (`SetEvent`) and exits
- The running instance deiconifies its window and forces it to foreground (temporary topmost toggle to bypass cross-app focus restrictions)

### 5. Source labeling
- Data layer: every mail row binds `account_id`
- UI: mail list shows the account column; left pane groups accounts and filters; notification titles include the account name

### 6. Password security
- DPAPI `CryptProtectData` (ctypes, no pywin32) → ciphertext hex in `%APPDATA%/OneMail/secrets.bin`
- Plaintext exists only in memory at runtime; leaked config files reveal no passwords

### 7. Unread badge
- Badge (red circle, count, `99+` cap) rendered with Pillow onto the base icon
- Tray icon image swapped whenever the global unread count changes

### 8. Auto-start
- Key: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value `OneMail.exe --minimized`
- Toggled from settings; writes/deletes the registry value

### 9. Right-click copy (v1.1.1)
- Single helper `_copy_to_clipboard()`: `clipboard_clear/append` + status-bar feedback; empty values never reach the clipboard
- **Mail list right-click**: copy subject / sender name / sender address / full body (menu only on a row hit)
- **Account panel right-click**: copy the account's e-mail address / display name (not offered on the "All Mail" card)
- **Reading pane right-click**: copy selection / select-all — subject, metadata and body fragments are all selectable (native Text widget behavior + menu affordance)

### 10. Search, filters & receive folder (v1.3.0)
- **SQL-level search**: `search_mails()` LIKE-matches subject / sender name / sender address / body in one query (no more front-end truncation at 200 rows); composes freely with the account filter and the All/Unread/Has-attachment filter; returns (rows, total) for the status bar
- **Receive folder**: accounts carry a `folder` field (default INBOX); all three `SELECT`/fetch sites in `mail_client.py` honor it (both IDLE and polling paths); the DB unique key moves to `(account_id, folder, uid)` because UID spaces are per-folder
- **Old-DB migration**: `init()` rebuilds the mails table in one transaction when the `folder` column is missing — data copied with folder='INBOX', no loss for existing users
- **Folder listing**: the account dialog's 获取 (Fetch) button runs `LIST "" "*"` on a worker thread, parses `(flags) delim name` lines, skips `\Noselect`, and decodes **IMAP modified UTF-7** (`&XfJT0ZAB-` → 已发送) so Chinese folder names display correctly
- **Connection-management fix**: `database.py` now uses a contextmanager that commits **and closes** each connection (the old `with sqlite3.connect()` only managed the transaction — the db file handle stayed open forever on Windows)

### 12. Hardening (v1.4.0, from a multi-agent audit)
- **No silent data loss**: config.json / secrets.bin written atomically (temp + `os.replace`); corrupt config backed up as `*.corrupt`; corrupt password store aborts the save instead of wiping everything
- **Concurrency**: IDLE wait uses `select.select` slices (never `settimeout` on the socket — imaplib's file object is permanently poisoned after a timeout, causing a reconnect every keep-alive cycle); `stop()` closes the socket for instant worker termination; 「立即收信」 fetch-now wakes workers via an event; `_poll_events` is exception-guarded so the event chain can never silently die
- **Parsing**: unclosed `<script>/<style>` (CDATA mode emits no events at all) is recovered from the parser buffer at the first real markup tag — broken marketing mail no longer yields empty bodies
- **Matching**: `%`/`_` escaped in LIKE (`ESCAPE '\'`); `guess_host` uses exact/suffix-with-dot matching so `myqq.com` can't send credentials to `imap.qq.com`
- **UI**: account editing keeps the stored auth code when the password field is left empty; richtext walks Tcl indices (emoji-safe); dialog worker threads never touch tk variables; context menus destroyed after popup; confirm dialog when closing during send
- **Misc**: 15 s IMAP connect timeout everywhere; local delete (right-click/Delete, server untouched); outbound mail gets `Date`/`Message-ID`; 300 ms search debounce; save_to_sent decodes modified-UTF-7 folder names (163 已发送 sync finally works); single-instance treats a NULL mutex handle as failure; migration is idempotent (`DROP TABLE IF EXISTS mails_new` + `BEGIN IMMEDIATE` + missing-column fallbacks)

### 13. Incremental fetch & attachments (v1.5.0)
- **folder_state table**: per (account, folder) `UIDVALIDITY` + highest fetched UID; the UNSEEN search is unchanged (cheap, server-side) but FETCH runs only for UIDs above the watermark — with readonly+PEEK the server-side UNSEEN never clears, so every push/poll used to re-download all unseen bodies
- **Resumable**: max_uid counts only fully fetched UIDs (interrupted batches resume); a UIDVALIDITY change clears that folder's cache and resyncs, guarding against UID reuse
- **Attachment names**: `mails.attachment_names TEXT` column (auto-ALTER via PRAGMA check), stored as JSON, shown in the reading pane
- **Misc**: tray degrades gracefully without a shell; badge digits use a TrueType font with fallback; all accounts missing auth codes are prompted chain-wise at startup
- **v1.5.1 corrections**: watermark advances only after confirmed synchronous insert (worker-thread insert, new-only notifications, event-queue drained on quit) — closing the loss window where a fetched mail could be permanently skipped; a failed FETCH ends the batch (resume next cycle); folder names go through `_folder_wire()` (mUTF-7 + quoting) since imaplib sends ascii-encoded unquoted commands; `list_folders` NameError fixed; IDLE continuation wait bounded with untagged-line tolerance; save_to_sent APPENDs the raw mUTF-7 name

### 14. Attachment saving & sorting (v1.6.0)
- **Save attachments**: reading-pane right-click → worker thread calls `MailClient.fetch_raw()` (BODY.PEEK[] by UID, read-only), `parser.extract_attachments()` decodes RFC 2047 names and writes files with `(n)` collision suffixes; raw messages are never stored locally, fetched on demand
- **Sortable columns**: click-to-sort (toggle direction), UI-side so it composes with search/filters
- `tools/verify_163.py`: live-mailbox end-to-end verification harness (temp DB): connect / UIDVALIDITY / folder list / incremental watermark / raw fetch

### 15. Footprint guarantees
- No Electron/Qt/browser engine — tkinter is the whole UI
- IDLE blocks on the socket = 0% idle CPU; polling accounts wake briefly per interval
- Body text truncated to 64 KB on ingest to bound DB growth
- All worker threads are daemons; process exit reclaims everything

### 16. Read-flag sync (v1.7.0, flag_sync.py; v1.8.0 adds mark-as-unread)
- **Separation of concerns**: the fetch channel stays strictly `readonly`; flag writes run on a dedicated **short-lived connection** (connect → non-readonly SELECT → `UID STORE .SILENT` → logout), fully isolated from the long-lived polling socket; the SELECT result is checked (imaplib returns `NO` — not an exception — for a missing folder, which would otherwise misdirect debugging to a bogus state-machine error)
- **Async batching**: the UI thread only `submit()`s jobs (deduped by account/folder/uid/seen); the worker merges a batch, groups by (account, folder, seen), sorts UIDs numerically (non-numeric UIDs are filtered defensively) and STOREs them in chunks of 50 — "mark all read" costs one connection per group; the tray "mark all read" covers all accounts, the toolbar button respects the current account filter
- **Failure policy**: failed chunks are retried once **inline within the group** (never re-queued — a re-queued retry could land after a newer opposite-direction task and permanently invert the server flag), then dropped with a log entry (successful chunks are never resent; the operation is idempotent); deleted accounts / missing passwords are dropped immediately; every exception path releases the dedup keys so a leaked key can never permanently silence future syncs for that mail; `mark_all_read` selects pending rows and flips flags in one SQLite transaction; `load_password` takes the secrets lock; account editing swaps in a brand-new `Account` atomically
- **Mark as unread (v1.8.0)**: list right-click → "标记为未读" resets local read state and sends `seen=False` (`-FLAGS \Seen`) through the same channel; the seen direction is part of the dedup key, so read/unread jobs never interfere
- **Toggle**: tray check item "同步已读到服务器" reads/writes `settings.sync_read_flags` (default on; the `enabled` callback re-reads config each time so toggling takes effect immediately); when off, jobs are discarded before touching the network
- **Testability**: `connector` / `get_credentials` / `enabled` are all constructor-injected (default `MailClient.mark_seen`), and `start_thread=False` allows direct offline testing of grouping/chunking/retry (14 tests)

### 17. Incoming rich-text rendering (v1.9.0, htmltext.py)

- **Fix**: before v1.9.0 the reading pane only showed tag-stripped plain text, losing all formatting of HTML mails. The HTML body is now stored at fetch time (`mails.body_html`, truncated to 128 KB; plain text stays 64 KB for search/quoting) and rendered in the reading pane
- **Renderer**: built on `html.parser` — supports b/strong/i/em/u/s, inline span color, font color, h1-h6, br/p/div, lists, a (colored + underlined), blockquote, pre; lenient parsing with stack-based recovery for unclosed tags, worst case degrades to plain text, never raises
- **Security**: no remote resource is ever loaded (images ignored); script/style/head content is dropped entirely; Tk Text rendering has no script execution capability
- **Outgoing side unchanged**: compose rich text is still exported by `richtext.text_to_html`; reply quotes stay plain text

### 18. Themes (v1.9.0, theme.py)

- All UI colors centralized; `light` (original blue/white) and `dark` palettes; `colors()` reads the config, each window captures it once at construction
- Switching writes `settings.theme`, **applies after restart** (Tk widget colors are fixed at construction; a runtime full repaint is not worth the complexity)

### 19. Languages (v1.9.0, i18n.py)

- Dictionary keyed by the Chinese string itself: `t("立即收信")` — zero cost in Chinese, automatic fallback to Chinese for missing English keys
- `init()` runs before any UI is constructed; covers main window / tray / compose / account dialog / settings / AI dialogs; engine status texts are mapped at display time in `set_account_status`

### 20. AI summary & write (v1.9.0, ai_client.py)

- OpenAI-compatible `/chat/completions` via pure `urllib` (zero new dependencies); `build_request` is offline-unit-testable, `chat/summarize/draft` run on background threads only
- Config: `settings.ai = {base_url, model}` in config.json; the API key goes through `security.save_password("__ai__", key)` (DPAPI), never plaintext
- Summary truncates the body to 12 KB; drafting accepts optional context (reply quote); generated text replaces the body only after user confirmation
- No streaming: outputs are small; a single response is simpler and more robust

### 21. Local mail folders (v1.9.0)

- `mails.local_folder` ('' = inbox) is kept **strictly separate** from `folder` (the server source folder) — attachment fetch and read-sync locate server mails by (uid, folder), so moving a mail only touches local_folder
- Folder list lives in `settings.local_folders`; the account panel shows folders with unread badges; filtering is pushed down to SQL (`COALESCE(local_folder,'') = ?`); deleting a folder moves its mails back to the inbox

### 22. Attachment open / save-as (v1.9.0)

- Reuses the on-demand raw-fetch channel: background thread `fetch_raw` → `extract_attachments` → write to `%TEMP%/OneMail/<mail_id>/` → `os.startfile`; temp files are reused per mail (no re-download)
- "Save As" uses `asksaveasfilename` (default name = attachment name); Windows reserved device names (CON/NUL/…) are sanitized

### 23. OAuth2 sign-in (v1.10.0, oauth2.py)

- **Flow**: authorization code + PKCE(S256) → loopback callback (127.0.0.1 random port, http.server per-request handling with a 1s poll timeout, 5 min total) → browser consent → token exchange. Gmail scope `https://mail.google.com/`; Microsoft uses `/common/oauth2/v2.0` endpoints with scopes `offline_access + IMAP.AccessAsUser.All + SMTP.Send` (outlook.office.com resource, not Graph)
- **Storage**: token JSON (access/refresh/expires_at/provider) DPAPI-encrypted under secrets key `__oauth2__::<email>`, never plaintext
- **Refresh**: `get_access_token` fires 120 s before expiry; the check-refresh-save is atomic inside a module lock so the scheduler and flag_sync threads never double-refresh; `invalid_grant` deletes the bad token and forces re-login
- **Integration**: `mail_client.imap_login` is the single login entry (4 call sites); SMTP uses raw `AUTH XOAUTH2` (a 334 challenge means failure — send an empty line to cancel); Outlook SMTP on port 587 uses STARTTLS (465 stays SSL)
- **Account model**: new `auth_type` (password|oauth2), `client_id`, `client_secret` fields; the "no password" gates in scheduler / prompt_missing_password / compose all let OAuth2 accounts through; deleting an account deletes its tokens
- **UI**: account dialog gains an auth-method dropdown, Client ID/Secret inputs and a background-thread "Sign in via Browser" button; picking OAuth2 hides the password row (whole row, label included)

### 24. Mail image display (v1.10.0, imgload.py)

- htmltext inserts an alt-text placeholder for `<img>` and records `(tag, src)`; render_html returns the list
- Three sources: `cid:` inline images (background fetch_raw → email parsing by Content-ID → bytes), `data:` URIs (base64), remote http(s) (urllib download)
- **Safety limits**: http/https only; ≤3 MB per image (oversized dropped); ≤10 per mail; PNG/JPEG/GIF magic-byte validation; 10 s download timeout
- **Threading**: download/parse on background threads; `to_photo` (Pillow decode + 640px downscale) and Text insertion happen on the main thread via `after`; a `_img_gen` generation counter discards images arriving after the user switched mail; `_photo_refs` holds references against GC
- Pillow is an existing dependency (tray icon), zero additions

### 25. UI tweaks (v1.10.0)

- The ⚙ Settings button moved to the first toolbar position (top-left)
- The mail-list context menu gains "New Folder…" (reuses create_folder)

## 6. Runtime & Data Locations

```
%APPDATA%/OneMail/
├── config.json   # accounts (no passwords) & settings
├── secrets.bin   # DPAPI-encrypted passwords
├── onemail.db    # SQLite mail cache
└── onemail.log   # status/error log
```

Run from source: `python src/main.py [--minimized]` (needs a Python with tkinter + `pystray`, `Pillow`).
Build: `pyinstaller build.spec --noconfirm` → `dist/OneMail.exe`.

## 7. Testing

1. **Parser unit tests**: GBK headers, nested MIME, HTML stripping, attachment detection, garbage-input robustness — all passing
2. **Smoke tests**: DB insert/dedup/unread counts, DPAPI round-trip (incl. non-ASCII auth codes), badge rendering 0/99+/100
3. **Search/migration unit tests** (test_search.py, offline): old-schema migration, folder isolation & dedup, body/subject/sender keyword hits, unread+attachment+account filter composition, mUTF-7 decoding
4. **Hardening regression tests** (test_robustness.py, offline): LIKE escaping, config atomicity + corrupt backup, unclosed script/style body recovery, migration idempotency, SMTP Date/Message-ID, domain-boundary matching, local delete
5. **SMTP unit tests** (test_smtp.py, offline): MIME header encoding, multi-recipient parsing, ASCII/Chinese attachment filenames (RFC 2231), SMTP host derivation — all passing
6. **Live test**: real NetEase 163 mailbox — connect, auto-poll fallback, fetch with source label, end-to-end OK
7. **Flag-sync unit tests** (test_flag_sync.py, offline, v1.7.0): dedup, per-account/folder grouping, numeric UID sort, 50-UID chunking, inline retry then drop, kill switch, missing-account safety, invalid-UID defense, plus imaplib-mock coverage of `mark_seen` (non-readonly SELECT, `.SILENT` seq-set, SELECT-NO/STORE-NO error paths, logout)
8. **v1.9.0 tests** (test_v19.py, offline): body_html parsing & DB round-trip, local folder move/counts/move-back, AI build_request validation, i18n fallback & English coverage check
9. **UI smoke** (tools/ui_smoke.py): search debounce, filters, sorting, open-mail rendering, account status — full chain green
10. **v1.10.0 tests** (test_oauth2.py, offline): PKCE, auth URLs, token request/response handling, expiry/refresh decision, XOAUTH2 string, token store round-trip, image magic/CID/data-URI, img placeholder rendering
10. **Packaged exe**: boots to tray, connects, fetches, no stderr output
