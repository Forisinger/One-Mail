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
├── docs/                  # this doc, development plan
├── src/
│   ├── main.py            # entry point: single-instance check, engine + UI + tray
│   ├── core/
│   │   ├── account.py     # account model (IMAP+SMTP), manager, provider presets
│   │   ├── mail_client.py # IMAP client (connect/IDLE/poll/reconnect)
│   │   ├── smtp_client.py # outgoing mail: MIME building, sending, Sent sync
│   │   ├── parser.py      # MIME parsing: body, attachments, headers
│   │   ├── scheduler.py   # multi-account scheduling, event fan-out
│   │   ├── security.py    # DPAPI encrypt/decrypt (ctypes)
│   │   └── single_instance.py # Win32 named-mutex single instance + wake event
│   ├── storage/
│   │   ├── database.py    # SQLite schema & access
│   │   └── config.py      # config.json read/write
│   ├── ui/
│   │   ├── main_window.py # main window (collapsible accounts / mail list / reader)
│   │   ├── compose_window.py # compose window (CC/BCC, rich text, threaded send)
│   │   ├── richtext.py    # Tk Text rich-text tags → HTML export
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
7. **Packaged exe**: boots to tray, connects, fetches, no stderr output
