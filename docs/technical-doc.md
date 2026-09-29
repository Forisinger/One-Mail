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
    message_id TEXT,
    from_addr TEXT, from_name TEXT,
    subject TEXT, body_text TEXT,
    has_attachment INTEGER DEFAULT 0,
    received_at TEXT, fetched_at TEXT,
    is_read INTEGER DEFAULT 0,
    UNIQUE(account_id, uid)
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

### 10. Footprint guarantees
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
3. **Live test**: real NetEase 163 mailbox — connect, auto-poll fallback, fetch with source label, end-to-end OK
4. **Packaged exe**: boots to tray, connects, fetches, no stderr output
