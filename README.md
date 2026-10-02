# OneMail · 一邮通

**一邮通（OneMail）** 是一款 Windows 托盘工具，**同时收发多个邮箱的邮件**，每封邮件都标注来源账户。纯 Python 实现，主打**极低的内存与 CPU 占用**。

（English version: [README.en.md](README.en.md)）

---

## ✨ 功能

| 功能 | 说明 |
|---|---|
| 📬 多账户 IMAP 收信 | 每封邮件标注来源账户，可按账户筛选 |
| 🔑 Gmail / Outlook OAuth2 | 授权码 + PKCE 浏览器登录，令牌 DPAPI 加密，自动刷新，无需应用专用密码 |
| 🎨 富文本邮件显示 | HTML 邮件按富文本渲染（加粗/斜体/下划线/颜色/标题/列表/链接/图片），图片经安全校验后显示 |
| 🌗 主题设置 | 浅色（默认）/ 深色，设置对话框切换 |
| 🌐 语言选择 | 中文 / English 界面 |
| ✉️ 写邮件与回复 | 支持附件、富文本正文（HTML + 纯文本双版本）、抄送密送，后台线程发送不卡界面 |
| 🤖 AI 总结 / AI 写信 | OpenAI 兼容接口（DeepSeek、GPT、通义等均可），用户自填 API 地址 / 模型 / Key，Key 经 DPAPI 加密 |
| 📁 本地信件文件夹 | 新建/删除自定义文件夹（账户面板或邮件列表右键均可），邮件移动/移回，未读徽章 |
| 🔍 全文搜索 | 含正文搜索 + 未读/有附件快捷筛选，列头点击排序 |
| 📎 附件操作 | 打开（系统默认程序）、另存为、全部保存（按需从服务器取原文） |
| ✅ 已读状态同步 | 本地标记同步回服务器（成批 \Seen 写回，托盘可关），支持标记为未读 |
| 🗑️ 本地删除 | 仅删本地缓存，不动服务器 |
| 🗂️ 收信文件夹 | 账户级收信文件夹选择（默认 INBOX），发信后尽力同步"已发送" |
| 🔔 托盘通知 | 原生气泡通知 + 托盘图标未读数角标 |
| 🔁 IDLE 推送 | IMAP IDLE 长连接推送，不支持时自动降级轮询 |
| ⚡ 增量收信 | 旧未读邮件不会被反复下载 |
| 🔒 密码加密 | Windows DPAPI 加密，绝不明文落盘 |
| 💾 SQLite 缓存 | 邮件历史重启不丢 |
| 🖥️ 单实例 | 再次启动自动唤醒主窗口置前 |
| 🚀 开机自启 | 用户级注册表，无需管理员 |
| 🪶 极低占用 | 单文件约 20MB，空闲 CPU 占用≈0 |

## 📦 下载运行

**方式 A — 直接用打包版**

从 [Releases](../../releases) 页下载 `OneMail.exe` 双击运行，无需安装。

**方式 B — 源码运行**

```bash
git clone https://github.com/<you>/OneMail.git
cd OneMail
pip install -r requirements.txt   # 仅 pystray + Pillow 两个依赖
python src/main.py
```

> 需要 Python ≥ 3.9 且带 tkinter（Windows 官方安装包默认包含）。

## 🛠️ 自行打包

```bash
pip install pyinstaller
pyinstaller build.spec --noconfirm
# → dist/OneMail.exe
```

## 📖 首次使用

1. 双击 exe 直接打开主窗口；开机自启时静默进入托盘（红色角标显示未读数）。运行中再次启动 exe 会唤醒主窗口置前。
2. 点击 **＋ 添加账户**，输入邮箱地址和**授权码**。
3. 完成——新邮件会标注来源出现在列表里，并弹出气泡通知。
4. 右键即可复制：邮件列表可复制主题/发件人/邮箱地址/正文，账户面板可复制自己的邮箱地址，阅读区任意选中文本均可复制。右键菜单还提供**附件打开/另存**、**移动到文件夹**、**新建文件夹**、**AI 总结**。点列头可排序，🔍 搜索框 + 全部/只看未读/有附件 过滤器可筛选——正文也会被搜索。
5. 工具栏**左上角 ⚙ 设置**：切换语言与主题（重启生效）、配置 AI（API 地址 / 模型 / Key）。

**邮箱服务商须知**：QQ 邮箱、网易 163/126 等国内邮箱需在网页设置中开启 IMAP **和 SMTP** 并使用**授权码**（不是登录密码），收信发信共用同一个授权码。网易还要求客户端上报 `ID` 命令，OneMail 已自动处理。

**Gmail / Outlook（OAuth2）**：添加账户时认证方式选 **OAuth2**，OneMail 会自动填好官方服务器地址。你需要一个自己的 **Client ID**：
- Gmail：[Google Cloud Console](https://console.cloud.google.com/) 创建项目 → OAuth 同意屏幕（External，添加自己为测试用户）→ 凭据 → 创建 **OAuth 客户端 ID（桌面应用）**，把 Client ID（和 Client Secret）填进 OneMail，点 **浏览器登录** 完成授权；
- Outlook：[Azure 门户 - 应用注册](https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) 注册**公共客户端**应用（重定向 URI 选「移动和桌面应用程序」的 `http://localhost`，勾选委托权限 `IMAP.AccessAsUser.All`、`SMTP.Send`），把应用程序(客户端) ID 填进 OneMail，点 **浏览器登录**。
令牌（含刷新令牌）经 DPAPI 加密只存本机，过期自动刷新；除了你自己的邮箱服务商与所配置的 AI 服务外无任何网络请求。

**AI 功能说明**：任何 OpenAI 兼容接口均可，例如 DeepSeek（`https://api.deepseek.com/v1`，模型 `deepseek-chat`）或 OpenAI（`https://api.openai.com/v1`，模型 `gpt-4o-mini`）。API Key 只存在本机（DPAPI 加密绑定当前 Windows 用户），除你配置的 AI 服务外无任何网络请求。

## 🔒 隐私与安全

- 密码、API Key 与 OAuth2 令牌使用 **Windows DPAPI** 加密并绑定当前系统用户，不会出现在配置文件中。
- 所有邮件数据仅存本地（`%APPDATA%/OneMail/`）；除你自己的邮件服务器、图片所在站点与所配置的 AI 服务外无任何网络请求，无遥测。
- 富文本渲染不执行任何脚本内容；邮件图片经大小/魔数校验后才显示。

## 🧱 技术概览

- 每个账户一条守护线程：优先 IDLE 长连接推送（阻塞等待、空闲 CPU 为零），服务器不支持时自动降级轮询
- SMTP 发信跑在独立线程：标准库 `email` 组装 MIME、中文附件名 RFC 2231 编码、尽力同步已发送文件夹
- 单实例经 Win32 命名互斥体实现，无第三方 IPC
- 全标准库优先设计——运行时第三方依赖只有 `pystray` + `Pillow`
- 指数退避重连，每次收信前校验连接状态
- GBK/GB2312/Big5 中文编码兜底解析
- 收件 HTML 富文本渲染零依赖（`html.parser`）；邮件图片按安全约束加载（≤3MB/张、≤10 张、魔数校验、640px 缩宽，全后台线程）
- OAuth2 为纯标准库实现（授权码 + PKCE + loopback 回调），零新增依赖

详细文档：[中文技术文档](docs/技术文档.md) · [Technical Doc (English)](docs/technical-doc.md)

## 🗺️ 后续计划

- [x] 发信与回复 ✅ v1.1.0
- [x] 抄送密送、富文本邮件 ✅ v1.2.0
- [x] 邮件搜索与过滤规则 ✅ v1.3.0
- [x] 收信文件夹选择 ✅ v1.3.0
- [x] 已读状态同步到服务器 ✅ v1.7.0
- [x] 标记为未读 ✅ v1.8.0
- [x] 富文本显示 / 主题 / 语言 / 附件打开 / AI 总结与写信 / 本地文件夹 ✅ v1.9.0
- [x] 邮件图片显示 / 左上角设置入口 / 右键新建文件夹 ✅ v1.10.0
- [x] Gmail 与 Outlook 的 OAuth2 登录 ✅ v1.10.0

## 📄 许可证

基于 [MIT 许可证](LICENSE) 开源，可自由使用、修改与分发。
