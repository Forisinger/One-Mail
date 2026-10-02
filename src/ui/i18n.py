# -*- coding: utf-8 -*-
"""界面多语言（v1.9.0）：中文/英文。

用法：t("立即收信")。键名即中文原文——中文环境零翻译成本，英文表缺键时
自动回退中文，不会崩。带占位符的字符串用 t("共 {n} 封").format(n=total)。

语言在设置对话框切换，存 config.settings.language，**重启生效**。
"""
from __future__ import annotations

from storage import config as config_store

LANGS = ("zh", "en")
DEFAULT_LANG = "zh"

_lang = DEFAULT_LANG

_EN = {
    # ---- 主窗口 ----
    "一邮通 OneMail": "OneMail",
    "⟳ 立即收信": "⟳ Fetch Now",
    "✉ 写邮件": "✉ Compose",
    "↩ 回复": "↩ Reply",
    "✓ 全部已读": "✓ Mark All Read",
    "＋ 添加账户": "＋ Add Account",
    "✎ 编辑账户": "✎ Edit Account",
    "－ 删除账户": "－ Remove Account",
    "✓ 标记已读": "✓ Mark Read",
    "🤖 AI 总结": "🤖 AI Summary",
    "⚙ 设置": "⚙ Settings",
    "全部": "All",
    "只看未读": "Unread",
    "有附件": "Attachments",
    "邮箱账户": "Accounts",
    "文件夹": "Folders",
    "收件箱": "Inbox",
    "来源": "Account",
    "发件人": "From",
    "主题": "Subject",
    "时间": "Date",
    "就绪": "Ready",
    "共 {n} 封，显示 {m} 封": "{n} mails, showing {m}",
    "共 {n} 封": "{n} mails",
    "（已停用）": " (disabled)",
    "（无正文/解析失败）": "(no body / parse failed)",
    "来自 {name} <{addr}>　·　{date}　·　来源：{acc}":
        "From {name} <{addr}>　·　{date}　·　via {acc}",
    "📎 附件：{names}": "📎 Attachments: {names}",
    "账户 {name} 缺少授权码，请输入": "Account {name} has no auth code, please enter it",
    "账户 {name} 已保存，开始连接 {host} …":
        "Account {name} saved, connecting {host} …",
    "全部邮件": "All Mail",
    "请先选中要回复的邮件": "Select a mail to reply first",
    "请先在左侧列表选中要编辑的账户": "Select an account to edit first",
    "请先在左侧列表选中要删除的账户": "Select an account to remove first",
    "删除账户 {name}？\n该账户的本地邮件缓存将一并删除。":
        "Remove account {name}?\nIts local mail cache will be deleted too.",
    "回复：{subj}": "Re: {subj}",
    "原始邮件": "Original Mail",
    # ---- 附件 ----
    "正在从服务器取回邮件原文…": "Fetching raw mail from server…",
    "该邮件的来源账户已被删除，无法取回附件":
        "Source account was removed, cannot fetch attachments",
    "选择附件保存位置": "Choose folder for attachments",
    "未在服务器原文中解析出附件": "No attachment found in server raw mail",
    "附件保存失败：{err}": "Attachment save failed: {err}",
    "已保存 {n} 个附件到 {dest}": "Saved {n} attachment(s) to {dest}",
    "已打开：{name}": "Opened: {name}",
    "已保存：{path}": "Saved: {path}",
    # ---- 右键菜单 ----
    "复制": "Copy",
    "全选": "Select All",
    "复制主题": "Copy Subject",
    "复制发件人": "Copy Sender Name",
    "复制发件人邮箱": "Copy Sender Address",
    "复制正文": "Copy Body",
    "复制邮箱地址": "Copy Email Address",
    "复制账户名": "Copy Account Name",
    "复制选中内容": "Copy Selection",
    "标记为未读": "Mark as Unread",
    "删除（仅本地缓存）": "Delete (local cache only)",
    "已从本地缓存删除该邮件（服务器不受影响）":
        "Deleted from local cache (server untouched)",
    "附件": "Attachments",
    "打开": "Open",
    "另存为…": "Save As…",
    "全部保存到…": "Save All To…",
    "移动到文件夹": "Move to Folder",
    "移回收件箱": "Move to Inbox",
    "新建文件夹…": "New Folder…",
    "删除文件夹": "Delete Folder",
    "移动成功：{n} 封 → {folder}": "Moved {n} mail(s) → {folder}",
    "新建文件夹": "New Folder",
    "文件夹名称：": "Folder name:",
    "文件夹已存在": "Folder already exists",
    "删除文件夹 {name}？其中邮件将移回收件箱。":
        "Delete folder {name}? Mails inside will move back to Inbox.",
    # ---- 状态 ----
    "已复制{label}：{preview}": "Copied {label}: {preview}",
    "主题": "Subject",
    "发件人名称": "sender name",
    "发件人邮箱": "sender address",
    "正文": "body",
    "选中内容": "selection",
    "邮箱地址": "email address",
    "账户名": "account name",
    "内容": "content",
    "已请求 {n} 个账户立即收信": "Requested fetch for {n} account(s)",
    "收信已暂停": "Fetching paused",
    "收信已恢复": "Fetching resumed",
    "已读状态同步到服务器：已开启": "Read-state sync to server: ON",
    "已读状态同步到服务器：已关闭": "Read-state sync to server: OFF",
    "已开启": "ON",
    "已关闭": "OFF",
    "[{name}] 收到 {n} 封新邮件": "[{name}] {n} new mail(s)",
    "程序启动": "Started",
    # ---- 写信窗口 ----
    "写邮件 · 一邮通": "Compose · OneMail",
    "发件账户": "From Account",
    "收件人": "To",
    "抄送": "Cc",
    "密送": "Bcc",
    "颜色": "Color",
    "清除格式": "Clear Format",
    "添加附件…": "Add Attachment…",
    "移除选中": "Remove Selected",
    "发送": "Send",
    "AI 写信": "AI Write",
    "正在发送…": "Sending…",
    "已发送": "Sent",
    "发送失败": "Send failed",
    "发送成功": "Sent successfully",
    "没有可用账户：请先在主窗口添加账户并填入授权码":
        "No available account: add one in the main window first",
    "请填写收件人": "Please fill in recipients",
    "地址格式有误：{addrs}": "Invalid address(es): {addrs}",
    "选择附件": "Select attachments",
    "邮件正在发送，关闭窗口后发送仍会继续但看不到结果。确定关闭？":
        "Still sending. It continues in background but you won't see the result. Close anyway?",
    "发送失败：{err}\n\n常见原因：授权码错误、未开启 SMTP 服务、附件过大或网络中断。":
        "Send failed: {err}\n\nCommon causes: wrong auth code, SMTP disabled, oversized attachment, or network issue.",
    # ---- 账户对话框 ----
    "编辑账户": "Edit Account",
    "添加账户": "Add Account",
    "显示名：": "Display name:",
    "邮箱地址：": "Email address:",
    "密码/授权码：": "Password / Auth code:",
    "IMAP 服务器：": "IMAP server:",
    "端口：": "Port:",
    "SSL：": "SSL:",
    "收信文件夹：": "Fetch folder:",
    "获取": "Fetch",
    "取消": "Cancel",
    "保存": "Save",
    "提示：QQ/163 等国内邮箱需在网页邮箱设置中开启 IMAP，并使用「授权码」而非登录密码。":
        "Note: QQ/163 and most Chinese providers require IMAP enabled in web settings, using an authorization code instead of the login password.",
    "请填写正确的邮箱地址": "Please enter a valid email address",
    "请填写密码或授权码": "Please enter the password / auth code",
    "端口必须是数字": "Port must be a number",
    "该账户尚无已存授权码，请填写": "This account has no stored auth code, please enter one",
    "请先填写邮箱与服务器": "Fill in email and server first",
    "正在连接…": "Connecting…",
    "共 {n} 个文件夹": "{n} folders",
    "获取失败：{err}": "Fetch failed: {err}",
    # ---- 账户对话框 · OAuth2（v1.10.0） ----
    "授权码 / 密码": "Auth code / password",
    "OAuth2（Gmail / Outlook）": "OAuth2 (Gmail / Outlook)",
    "认证方式：": "Auth method:",
    "OAuth2 Client ID：": "OAuth2 Client ID:",
    "Client Secret（可选）：": "Client Secret (optional):",
    "浏览器登录": "Sign in via Browser",
    "请先填写邮箱与 Client ID": "Fill in email and Client ID first",
    "未识别的 OAuth2 域名（仅支持 Gmail/Outlook）":
        "Unrecognized OAuth2 domain (Gmail/Outlook only)",
    "已打开浏览器，请完成登录…": "Browser opened, please sign in…",
    "登录成功，令牌已保存": "Signed in, token saved",
    "登录失败：{err}": "Sign-in failed: {err}",
    "OAuth2 需要填写 Client ID": "OAuth2 requires a Client ID",
    "请先点「浏览器登录」完成 OAuth2 授权":
        "Click \"Sign in via Browser\" to finish OAuth2 authorization first",
    "提示：QQ/163 等国内邮箱用「授权码」；Gmail/Outlook 选 OAuth2，需先在 Google Cloud / Azure 注册应用拿到 Client ID。":
        "Note: Chinese providers use an auth code; for Gmail/Outlook pick OAuth2 and register an app in Google Cloud / Azure to get a Client ID.",
    # ---- 图片（v1.10.0） ----
    "已加载 {n} 张邮件图片": "Loaded {n} mail image(s)",
    # ---- v1.10.1 增强 ----
    "OAuth2 令牌已失效，请编辑账户重新登录":
        "OAuth2 token expired/revoked — edit the account to sign in again",
    "（已保存，留空沿用）": "(saved; leave empty to keep)",
    "保存失败：{err}": "Save failed: {err}",
    "打开日志文件夹": "Open Log Folder",
    # ---- 设置对话框 ----
    "设置": "Settings",
    "语言（重启生效）": "Language (restart to apply)",
    "主题（重启生效）": "Theme (restart to apply)",
    "浅色": "Light",
    "深色": "Dark",
    "AI 功能（OpenAI 兼容接口）": "AI (OpenAI-compatible API)",
    "API 地址：": "API base URL:",
    "模型：": "Model:",
    "API Key：": "API Key:",
    "Key 经 Windows DPAPI 加密存储": "Key stored encrypted via Windows DPAPI",
    "设置已保存，语言/主题重启后生效。": "Saved. Language/theme apply after restart.",
    "示例：https://api.deepseek.com/v1": "e.g. https://api.deepseek.com/v1",
    # ---- AI ----
    "AI 总结": "AI Summary",
    "正在请求 AI…": "Requesting AI…",
    "AI 总结失败：{err}": "AI summary failed: {err}",
    "AI 写信": "AI Write",
    "请描述要写的邮件内容：": "Describe the mail to write:",
    "生成": "Generate",
    "AI 生成中…": "AI generating…",
    "AI 生成失败：{err}": "AI generation failed: {err}",
    "正文非空，是否替换为 AI 生成的内容？": "Body is not empty. Replace with AI content?",
    "请先配置 AI（设置 → AI 功能）": "Configure AI first (Settings → AI)",
    "复制结果": "Copy Result",
    "关闭": "Close",
    "AI 未返回内容": "AI returned nothing",
    # ---- 托盘 ----
    "打开主界面": "Open OneMail",
    "立即收信": "Fetch Now",
    "恢复收信": "Resume Fetching",
    "暂停收信": "Pause Fetching",
    "全部标为已读": "Mark All Read",
    "同步已读到服务器": "Sync Read State to Server",
    "退出": "Quit",
    "一邮通 OneMail｜未读 {n}": "OneMail | Unread {n}",
    "一邮通 · {name}": "OneMail · {name}",
    "一邮通": "OneMail",
    # ---- core 状态映射 ----
    "已连接": "Connected",
    "收到新邮件推送": "New mail push received",
    "手动收信": "Manual fetch",
    "服务器不支持 IDLE，转为轮询": "Server has no IDLE, falling back to polling",
    "连接异常：{err}": "Connection error: {err}",
    "未知错误，稍后重连": "Unknown error, retrying later",
    "未设置密码/授权码，请在界面中编辑账户":
        "No auth code set, please edit the account in UI",
    "{n}s 后重连": "reconnect in {n}s",
}


def init(lang: str | None = None) -> None:
    """启动时调用一次：从配置读语言（可显式传参覆盖，供测试用）。"""
    global _lang
    if lang is None:
        try:
            lang = config_store.load().get("settings", {}).get("language",
                                                               DEFAULT_LANG)
        except Exception:
            lang = DEFAULT_LANG
    _lang = lang if lang in LANGS else DEFAULT_LANG


def t(key: str) -> str:
    """翻译。英文表缺键时回退中文键名本身，永不抛错。"""
    if _lang == "en":
        return _EN.get(key, key)
    return key
