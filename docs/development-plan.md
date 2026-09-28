# OneMail — Development Plan

> Version: v1.0｜Date: 2026-09-28｜Companion doc: [technical-doc.md](technical-doc.md)

## 1. Project Positioning

OneMail is a lightweight Windows desktop utility that aggregates multiple mailboxes:

- Configure multiple email accounts (QQ Mail, NetEase 163/126, Gmail, Outlook, corporate mailboxes, etc.)
- Fetch mail from all accounts, **labeled by source** (which account received it)
- Auto-start on boot, live in the system tray, notify on new mail
- **Minimal memory & CPU footprint** (target: < 50 MB resident, ~0% idle CPU)

## 2. Feature List

| ID | Feature | Priority |
|---|---|---|
| F1 | Multi-account management: add / remove / enable / disable | P0 |
| F2 | Mail fetching via IMAP (body + attachment list) | P0 |
| F3 | Source labeling: every mail shows its account; list filterable by account | P0 |
| F4 | New-mail notification: tray balloon | P0 |
| F5 | Auto-start on boot via HKCU registry Run key (toggleable) | P0 |
| F6 | Low resource usage: IMAP IDLE push instead of high-frequency polling | P1 |
| F7 | Local cache: mail index in SQLite, browsable offline | P1 |
| F8 | Mail viewer: read body, download attachments, mark as read | P1 |
| F9 | Secure storage: passwords encrypted (Windows DPAPI), never plaintext | P1 |
| F10 | Sending / replying | P2 (phase 2) |

## 3. Development Phases

### Phase 0 — Technical Validation (done)
- Prototype: IMAP login with provider auth codes, IDLE push availability probe
- Verified tkinter + pystray tray-resident memory baseline
- **Outcome: final stack locked (see technical doc)**

### Phase 1 — Fetch Engine (done)
- `core/`: IMAP client (connect, IDLE, polling fallback, exponential-backoff reconnect)
- Per-account scheduler: one lightweight daemon thread per account
- Mail parsing: MIME, body extraction (HTML→plain fallback), attachment detection
- **Outcome: working engine, source-labeled new-mail events**

### Phase 2 — Data & Config (done)
- SQLite mail cache (accounts, mails, read state)
- JSON config + DPAPI-encrypted password store
- **Outcome: mail history survives restarts**

### Phase 3 — UI & Notifications (done)
- Tray icon + context menu (open / fetch now / pause / mark all read / quit)
- Main window: account list (source labeling), mail list, reading pane
- Unread-count badge rendered on the tray icon
- Missing-password prompt on startup; account add/edit dialogs
- **Outcome: daily-usable release**

### Phase 4 — Packaging (done)
- PyInstaller single-file build, no console window, app icon
- **Outcome: distributable OneMail.exe (~20 MB)**

### Phase 5 — Hardening (ongoing)
- Provider quirks: client `ID` command for NetEase, IDLE-unsupported fallback, BYE handling
- Live-tested against a real NetEase 163 mailbox
- Resource profiling: idle CPU ≈ 0%, resident memory within target

## 4. Milestones & Acceptance

| Milestone | Acceptance criteria |
|---|---|
| M1 Fetch engine | Two different mailboxes fetched concurrently, source labels correct |
| M2 Usable build | Tray resident, new-mail notification, data persists across restarts |
| M3 Release build | Single exe, auto-start, idle memory < 50 MB, idle CPU ≈ 0% |

## 5. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| IDLE support varies across providers (NetEase has none) | Auto-detect; fall back to configurable polling (default 5 min) |
| Gmail/Outlook require OAuth2 | Phase 1 ships auth-code/app-password flow; OAuth interface reserved |
| Antivirus false positives on PyInstaller builds | UPX disabled; directory-style release as fallback |
| HTML/attachment edge cases crash parsing | Parser never raises; raw-text fallback on failure |

## 6. Phase 2 Backlog (planned, not implemented)

- OAuth2 (Gmail/Outlook), sending & replying, folder selection
- Mail search, filter rules, per-account settings UI, i18n
