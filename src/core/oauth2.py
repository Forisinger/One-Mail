# -*- coding: utf-8 -*-
"""OAuth2 登录（v1.10.0）：Gmail 与 Outlook 的 IMAP/SMTP XOAUTH2 认证。

纯标准库实现（urllib + hashlib + http.server），零第三方依赖：
- 授权码 + PKCE(S256)，loopback 回调（127.0.0.1 随机端口），浏览器完成登录
- 令牌 JSON 经 DPAPI 加密落 secrets（键 __oauth2__::<email>），绝不明文
- get_access_token 在过期前 120s 自动刷新；模块级锁防多线程并发双刷
- 账户密码字段对 OAuth2 账户无意义：凭据完全由 email 定位的令牌承担
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets as _pysecrets
import socket
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import security

# 过期提前量：留足网络抖动 + 服务器时钟偏差
_EXPIRY_MARGIN = 120
# loopback 回调最长等待（用户在浏览器里停留的容忍时间）
_AUTH_TIMEOUT = 300
# 随机端口监听地址（Microsoft 公共客户端只认 http://localhost）
_LOOPBACK_HOST = "127.0.0.1"

SUCCESS_PAGE = ("<!doctype html><meta charset='utf-8'>"
                "<body style='font-family:sans-serif;text-align:center;padding-top:4em'>"
                "<h2>&#9989; &#30331;&#24405;&#25104;&#21151;</h2>"
                "<p>&#36866;&#29992;&#20196;&#24050;&#33719;&#21462;，&#35831;&#22238;&#21040;&#19968;&#37038;&#36890;&#32487;&#32493;&#12290;</p>"
                "<script>window.close()</script></body>")
FAILURE_PAGE = ("<!doctype html><meta charset='utf-8'>"
                "<body style='font-family:sans-serif;text-align:center;padding-top:4em'>"
                "<h2>&#10060; &#30331;&#24405;&#22833;&#36133;</h2>"
                "<p>{msg}</p></body>")


class OAuth2Error(Exception):
    """OAuth2 流程/令牌错误。文案可直接展示给用户。"""


# ---------- Provider 预置 ----------

GOOGLE = {
    "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_url": "https://oauth2.googleapis.com/token",
    # mail.google.com = IMAP/SMTP 全量访问（Gmail 官方要求的一把钥匙 scope）
    "scope": "https://mail.google.com/",
}
MICROSOFT = {
    "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    # outlook.office.com 资源 scope（不是 Graph）；offline_access 必带才能拿 refresh_token
    "scope": ("offline_access https://outlook.office.com/IMAP.AccessAsUser.All "
              "https://outlook.office.com/SMTP.Send"),
}
PROVIDERS = {"google": GOOGLE, "microsoft": MICROSOFT}


def _token_key(email: str) -> str:
    return "__oauth2__::" + (email or "").strip().lower()


# ---------- 令牌存取（DPAPI） ----------

def load_token(email: str) -> dict | None:
    raw = security.load_password(_token_key(email))
    if not raw:
        return None
    try:
        tok = json.loads(raw)
        return tok if isinstance(tok, dict) and tok.get("refresh_token") else None
    except Exception:
        return None


def save_token(email: str, tok: dict) -> None:
    security.save_password(_token_key(email), json.dumps(tok, ensure_ascii=False))


def delete_token(email: str) -> None:
    security.delete_password(_token_key(email))


# ---------- PKCE / URL / 请求体（离线可测的纯函数） ----------

def make_pkce() -> tuple[str, str]:
    """返回 (verifier, challenge_S256)。verifier 43-128 字符，满足两家要求。"""
    verifier = _pysecrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_auth_url(provider: dict, client_id: str, redirect_uri: str,
                   state: str, challenge: str) -> str:
    q = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": provider["scope"],
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # 强制每次弹 consent，确保能拿到 refresh_token
        "access_type": "offline",      # Google 专用，Microsoft 忽略
        "prompt": "consent",
        "response_mode": "query",      # Microsoft 专用，Google 忽略
    })
    return provider["auth_url"] + "?" + q


def build_token_request(provider: dict, client_id: str, client_secret: str,
                        **grant: str) -> tuple[str, bytes]:
    """构造令牌端点 POST：返回 (url, form_bytes)。secret 可选（公共客户端）。"""
    data = {"client_id": client_id, **grant}
    if client_secret:
        data["client_secret"] = client_secret
    body = urllib.parse.urlencode(data).encode("ascii")
    return provider["token_url"], body


def parse_token_response(payload: bytes, old: dict | None = None) -> dict:
    """解析令牌端点 JSON。刷新响应可能不带新 refresh_token：保留旧的。"""
    try:
        d = json.loads(payload.decode("utf-8"))
    except Exception as e:
        raise OAuth2Error(f"令牌响应解析失败: {e}") from e
    if "error" in d:
        raise OAuth2Error(f"OAuth2 错误: {d.get('error')} "
                          f"{d.get('error_description', '')}".strip())
    tok = dict(old or {})
    tok["access_token"] = d.get("access_token", "")
    if d.get("refresh_token"):
        tok["refresh_token"] = d["refresh_token"]
    if d.get("scope"):
        tok["scope"] = d["scope"]
    try:
        expires_in = int(d.get("expires_in", 3600))
    except (TypeError, ValueError):
        expires_in = 3600
    tok["expires_at"] = time.time() + max(expires_in - 30, 60)
    if not tok["access_token"] or not tok.get("refresh_token"):
        raise OAuth2Error("令牌响应缺少 access_token/refresh_token")
    return tok


def token_expired(tok: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return now >= float(tok.get("expires_at", 0)) - _EXPIRY_MARGIN


# ---------- 网络端点 ----------

def post_token(url: str, body: bytes, timeout: float = 30) -> bytes:
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise OAuth2Error(f"令牌请求失败 HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise OAuth2Error(f"网络错误: {e}") from e


def exchange_code(provider: dict, client_id: str, client_secret: str,
                  code: str, redirect_uri: str, verifier: str) -> dict:
    url, body = build_token_request(
        provider, client_id, client_secret,
        grant_type="authorization_code", code=code,
        redirect_uri=redirect_uri, code_verifier=verifier)
    return parse_token_response(post_token(url, body))


def refresh_token(provider: dict, client_id: str, client_secret: str,
                  refresh_tok: str, old: dict | None = None) -> dict:
    url, body = build_token_request(
        provider, client_id, client_secret,
        grant_type="refresh_token", refresh_token=refresh_tok)
    return parse_token_response(post_token(url, body), old=old)


# ---------- 交互式授权（loopback + 浏览器） ----------

class _CallbackHandler(BaseHTTPRequestHandler):
    """捕获 ?code=...&state=... 后立刻回页面并关服。"""

    server_version = "OneMail"

    def do_GET(self):  # noqa: N802
        q = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(q.query)
        self.server.result = {k: v[0] for k, v in params.items() if v}
        ok = "code" in self.server.result
        msg = "ok" if ok else self.server.result.get("error", "unknown error")
        page = (SUCCESS_PAGE if ok else FAILURE_PAGE).format(msg=msg)
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.server.done.set()

    def log_message(self, *a):  # 静默：不往 stderr 刷浏览器请求日志
        pass


def authorize(provider_name: str, email: str, client_id: str,
              client_secret: str = "", timeout: float = _AUTH_TIMEOUT) -> dict:
    """跑完整授权码+PKCE 流程，返回并落盘令牌。阻塞至多 timeout 秒。

    供账户对话框在后台线程调用（浏览器会弹出，不阻塞 UI 线程）。
    """
    provider = PROVIDERS.get(provider_name)
    if not provider:
        raise OAuth2Error(f"未知提供者: {provider_name}")
    if not client_id or not email:
        raise OAuth2Error("需要 client_id 与邮箱地址")

    verifier, challenge = make_pkce()
    state = _pysecrets.token_urlsafe(16)

    # 随机端口 loopback 服务器；拿不到也直接失败，不退化为 OOB（两家均已废弃）
    try:
        server = HTTPServer((_LOOPBACK_HOST, 0), _CallbackHandler)
    except OSError as e:
        raise OAuth2Error(f"本地回调端口监听失败: {e}") from e
    server.result, server.done = {}, threading.Event()
    redirect_uri = f"http://localhost:{server.server_address[1]}"

    import webbrowser
    webbrowser.open(build_auth_url(provider, client_id, redirect_uri, state, challenge))

    deadline = time.time() + timeout
    try:
        while not server.done.is_set() and time.time() < deadline:
            server.timeout = 1.0
            server.handle_request()   # 逐请求处理，循环可查超时
        if not server.done.is_set():
            raise OAuth2Error("登录超时：未在浏览器完成授权")
        result = server.result
        if "error" in result:
            raise OAuth2Error(f"授权被拒绝: {result.get('error')}")
        if result.get("state") != state or "code" not in result:
            raise OAuth2Error("回调参数不合法（state 不匹配或缺 code）")
        tok = exchange_code(provider, client_id, client_secret,
                            result["code"], redirect_uri, verifier)
    finally:
        server.server_close()

    tok["provider"] = provider_name
    tok["email"] = email
    save_token(email, tok)
    return tok


# ---------- 运行期令牌获取 ----------

_refresh_lock = threading.Lock()


def get_access_token(account, now: float | None = None) -> str:
    """取账户的可用 access_token，必要时刷新。失败抛 OAuth2Error。

    account 需要有 email / auth_type / client_id / client_secret。
    锁内「查-刷-存」原子化：scheduler 与 flag_sync 线程同时到期只刷一次。
    """
    email = account.email
    with _refresh_lock:
        tok = load_token(email)
        if tok is None:
            raise OAuth2Error("尚未完成 OAuth2 登录，请在账户设置中重新登录")
        if not token_expired(tok, now):
            return tok["access_token"]
        provider_name = tok.get("provider") or _guess_provider_name(email)
        provider = PROVIDERS.get(provider_name, MICROSOFT)
        try:
            new = refresh_token(provider, account.client_id or "",
                                getattr(account, "client_secret", "") or "",
                                tok["refresh_token"], old=tok)
        except OAuth2Error as e:
            # refresh_token 被吊销等：删掉坏令牌，逼用户重新走浏览器登录
            if "invalid_grant" in str(e):
                delete_token(email)
                raise OAuth2Error("OAuth2 令牌已失效（invalid_grant），请重新登录") from e
            raise
        save_token(email, new)
        return new["access_token"]


def _guess_provider_name(email: str) -> str:
    from .account import oauth_provider_for
    return oauth_provider_for(email) or "microsoft"


# ---------- SASL XOAUTH2 ----------

def xoauth2(user: str, access_token: str) -> bytes:
    """RFC 7628 XOAUTH2 初始响应串。"""
    raw = f"user={user}\x01auth=Bearer {access_token}\x01\x01"
    return raw.encode("utf-8")


def imap_authenticate(conn, account, access_token: str) -> None:
    """IMAP AUTHENTICATE XOAUTH2。失败时吃完 334 挑战再抛，防连接卡死。"""
    mech = lambda _: xoauth2(account.email, access_token)  # noqa: E731
    try:
        conn.authenticate("XOAUTH2", mech)
    except Exception:
        # imaplib.authenticate 失败时会 abort 连接（连不上就无所谓），
        # 但部分实现要求先回空行取消；统一补一刀，错误从重连循环走
        try:
            conn.send(b"\r\n")   # nosec: 取消 SASL 会话的协议动作
        except Exception:
            pass
        raise


def smtp_auth(srv, account, access_token: str) -> None:
    """SMTP AUTH XOAUTH2（raw docmd，兼容两家；334 挑战即失败，回空行取消）。"""
    import base64 as _b64
    b64 = _b64.b64encode(xoauth2(account.email, access_token)).decode("ascii")
    code, resp = srv.docmd("AUTH", "XOAUTH2 " + b64)
    if code == 235:
        return
    if code == 334:
        srv.docmd("")            # 吃掉挑战并取消，让会话可干净 QUIT
        detail = _b64.b64decode(resp + "===").decode("utf-8", "replace")[:200]
        raise OAuth2Error(f"SMTP 认证被拒: {detail}")
    raise OAuth2Error(f"SMTP 认证失败 HTTP {code}: {resp!r}"[:200])
