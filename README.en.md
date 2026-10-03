# OneMail

**OneMail** is a lightweight Windows tray application that receives mail from **multiple mailboxes at once** — every message labeled with the account it came from. Built in Python with a hard focus on a **minimal memory & CPU footprint**.

（中文版：[README.md](README.md)）

---

## ✨ Features

| Feature | Description |
|---|---|
| 📬 Multi-account IMAP fetching | Every mail labeled by source account, list filterable per account |
| 🔑 Gmail / Outlook OAuth2 | Authorization-code + PKCE browser sign-in, DPAPI-encrypted tokens with auto refresh — no app passwords |
| 🎨 Rich-text mail display | HTML mails rendered with formatting (bold/italic/underline/color/headings/lists/links/images); images shown after safety checks |
| 🌗 Themes | Light (default) / Dark, with a **custom accent color** in settings (unread text and selection background are derived automatically) |
| 🌐 Language | 中文 / English UI |
| 🗂️ Account manager | Add / edit / remove / enable-disable in one dialog (left panel "Mail" → "⚙ Accounts…") |
| ⚙ Centralised settings | Three tabs — Appearance / AI / Other: accent color, AI config, auto-start, read-state sync |
| ✉️ Compose & reply | Attachments, rich-text body (HTML + plain fallback), CC & BCC, sent on a background thread |
| 🤖 AI summary / AI write | OpenAI-compatible endpoints (DeepSeek, GPT, Qwen, …) with user-provided base URL / model / key; key encrypted via DPAPI |
| 📁 Local mail folders | Create/delete custom folders (folder section of the left "Mail" panel), move mails in/out, unread badges |
| 🔍 Full-text search | Body search included, plus Unread / Has-attachment filters and click-to-sort columns |
| 📎 Attachments | Open (system default app), Save As, Save All (on-demand server fetch) |
| ✅ Read-state sync | Batched \Seen writes back to the server (tray toggle), mark-as-unread supported |
| 🗑️ Local delete | Removes the local cache only, server untouched |
| 🗂️ Fetch folder | Per-account receive-folder selection (default INBOX), best-effort Sent-folder sync |
| 🔔 Tray notifications | Native balloon notifications + unread-count badge on the tray icon |
| 🔁 IMAP IDLE push | Long-connection push with automatic polling fallback |
| ⚡ Incremental fetching | Old unseen mail is never re-downloaded |
| 🔒 Encrypted passwords | Windows DPAPI — never stored in plaintext |
| 💾 SQLite cache | Mail history survives restarts |
| 🖥️ Single instance | Re-launching the exe brings the window to front |
| 🚀 Auto-start on boot | Registry Run key (per-user, no admin) |
| 🪶 Tiny footprint | ~20 MB single exe, ~0% idle CPU |

## 📦 Download & Run

**Option A — release exe**

Download `OneMail.exe` from [Releases](../../releases) and double-click. No installation.

**Option B — from source**

```bash
git clone https://github.com/<you>/OneMail.git
cd OneMail
pip install -r requirements.txt   # only pystray + Pillow
python src/main.py
```

> Requires Python ≥ 3.9 with tkinter (any standard Windows Python works).

## 🛠️ Build the exe

```bash
pip install pyinstaller
pyinstaller build.spec --noconfirm
# → dist/OneMail.exe
```

## 📖 First Run

1. Double-clicking the exe opens the main window directly; when launched by auto-start it goes silently to the tray (red badge shows unread count). Re-launching the exe while running wakes the window to front.
2. Click **⚙ Accounts…** at the bottom of the left "Mail" panel, then **＋ Add Account** in the account manager: enter your address and **authorization code** (add / edit / remove / enable-disable all live in that one dialog; double-click a row to edit).
3. Done — new mail shows up in the list, labeled by source, with balloon notifications.
4. Right-click to copy subject / sender / address / body anywhere; the reading-pane context menu also offers **attachment open / save-as**, **move to folder** and **AI summary**. **New mail folder** lives in the folder section of the left "Mail" panel ("＋ New" in the section header, or right-click it). Click column headers to sort, and use the 🔍 search box + All/Unread/Attachments filter — body text is searched too.
5. The **⚙ Settings** button sits at the top-left of the toolbar, with three tabs: **Appearance** (language, theme, custom accent color), **AI** (base URL / model / key) and **Other** (launch at startup, sync read state to server, open log folder). Language/theme/accent apply after restart.

**Provider note**: QQ Mail / NetEase 163/126 and most Chinese providers require an **authorization code** instead of your login password — enable IMAP **and SMTP** in the web settings, generate the code, and paste it into OneMail. The same code is used for both receiving and sending. NetEase additionally requires the IMAP `ID` handshake, which OneMail sends automatically.

**Gmail / Outlook (OAuth2)**: when adding the account pick **OAuth2** as the auth method — OneMail fills in the official server addresses automatically. You need your own **Client ID**:
- Gmail: in [Google Cloud Console](https://console.cloud.google.com/) create a project → OAuth consent screen (External, add yourself as test user) → Credentials → create an **OAuth Client ID (Desktop app)**, paste the Client ID (and Secret) into OneMail and click **Sign in via Browser**;
- Outlook: register a **public client** app under [Azure portal - App registrations](https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) (redirect URI "Mobile and desktop applications" → `http://localhost`; delegated permissions `IMAP.AccessAsUser.All`, `SMTP.Send`), paste the Application (client) ID into OneMail and click **Sign in via Browser**.
Tokens (incl. the refresh token) are DPAPI-encrypted and stay on your machine, refreshing automatically when expired; no network calls beyond your own mail provider, the image hosts and the AI service you configure.

**AI note**: any OpenAI-compatible endpoint works, e.g. DeepSeek (`https://api.deepseek.com/v1`, model `deepseek-chat`) or OpenAI (`https://api.openai.com/v1`, model `gpt-4o-mini`). The API key stays on your machine (DPAPI-encrypted, bound to your Windows user); no network calls beyond your own mail servers and the AI service you configure.

## 🔒 Privacy & Security

- Passwords, the AI key and OAuth2 tokens are encrypted with **Windows DPAPI**, bound to your Windows user; they never appear in config files.
- Mail data stays in a local SQLite file (`%APPDATA%/OneMail/`). No telemetry; no network calls other than your own mail servers, the image hosts and the AI service you configure.
- Rich-text rendering executes no script content; mail images pass size / magic-byte checks before display.

## 🧱 Tech Overview

- One daemon thread per account: IMAP IDLE long-connection push (blocked socket, zero idle CPU), auto fallback to polling for providers without IDLE
- SMTP sending on a worker thread: MIME assembled by the stdlib `email` package, RFC 2231-encoded attachment names, best-effort Sent-folder sync
- Single-instance via Win32 named mutex/event (no third-party IPC)
- Full stdlib-first design — third-party runtime dependencies are exactly `pystray` + `Pillow`
- Exponential-backoff reconnect, connection-state verification before every fetch
- GBK/GB2312/Big5 encoding fallback chain for Chinese mail
- Zero-dependency incoming rich-text rendering (`html.parser`); mail images load under strict limits (≤3 MB each, ≤10 per mail, magic-byte checks, 640px cap, all on background threads)
- OAuth2 implemented with the stdlib only (authorization code + PKCE + loopback callback), zero new dependencies

Details in the docs: [Technical Documentation](docs/technical-doc.md) · [中文技术文档](docs/技术文档.md)

## 🗺️ Roadmap

- [x] Send & reply ✅ v1.1.0
- [x] CC/BCC fields, rich-text (HTML) mail ✅ v1.2.0
- [x] Mail search & filter rules ✅ v1.3.0
- [x] Folder selection ✅ v1.3.0
- [x] Read-state sync to the server ✅ v1.7.0
- [x] Mark as unread ✅ v1.8.0
- [x] Rich-text display / themes / language / attachment open / AI summary & write / local folders ✅ v1.9.0
- [x] Mail images / top-left settings entry / right-click new folder ✅ v1.10.0
- [x] OAuth2 for Gmail/Outlook ✅ v1.10.0
- [x] Centralised settings (Appearance/AI/Other), account manager dialog, left panel renamed "Mail" ✅ v1.11.0
- [x] Full dark-theme coverage, resize-adaptive column widths; fixed context-menu clicks doing nothing (delete mail etc.) ✅ v1.11.3

## 📄 License

Released under the [MIT License](LICENSE).
