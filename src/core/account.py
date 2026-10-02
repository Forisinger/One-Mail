# -*- coding: utf-8 -*-
"""账户模型与账户管理器。

账户元数据存 config.json；密码经 DPAPI 加密后存 secrets.bin，两者分离。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict

from . import security
from storage import config

# 国内常见邮箱 -> IMAP 服务器预置（一期范围：国内邮箱 + 任意 IMAP）
KNOWN_HOSTS = {
    "qq.com": ("imap.qq.com", 993),
    "foxmail.com": ("imap.qq.com", 993),
    "163.com": ("imap.163.com", 993),
    "126.com": ("imap.126.com", 993),
    "sina.com": ("imap.sina.com", 993),
    "sohu.com": ("imap.sohu.com", 993),
    "aliyun.com": ("imap.aliyun.com", 993),
    "139.com": ("imap.139.com", 993),
    # OAuth2 大厂（v1.10.0）：域名必须显式预置，guess_host 的 imap.<域> 推导会猜错
    "gmail.com": ("imap.gmail.com", 993),
    "googlemail.com": ("imap.gmail.com", 993),
    "outlook.com": ("outlook.office365.com", 993),
    "hotmail.com": ("outlook.office365.com", 993),
    "hotmail.co.uk": ("outlook.office365.com", 993),
    "live.com": ("outlook.office365.com", 993),
    "msn.com": ("outlook.office365.com", 993),
}

# OAuth2 提供者预置：域名 -> (provider, smtp_host, smtp_port)
OAUTH_DOMAINS = {
    "gmail.com": ("google", "smtp.gmail.com", 465),
    "googlemail.com": ("google", "smtp.gmail.com", 465),
    "outlook.com": ("microsoft", "smtp.office365.com", 587),
    "hotmail.com": ("microsoft", "smtp.office365.com", 587),
    "hotmail.co.uk": ("microsoft", "smtp.office365.com", 587),
    "live.com": ("microsoft", "smtp.office365.com", 587),
    "msn.com": ("microsoft", "smtp.office365.com", 587),
}


def oauth_provider_for(email_addr: str) -> str | None:
    """按邮箱域名猜 OAuth2 提供者（google / microsoft / None=未知）。"""
    domain = (email_addr or "").rsplit("@", 1)[-1].lower()
    for d, (provider, _smtp_h, _smtp_p) in OAUTH_DOMAINS.items():
        if domain == d or domain.endswith("." + d):
            return provider
    return None


@dataclass
class Account:
    id: str
    name: str                 # 用户起的显示名（来源标注用）
    email: str
    imap_host: str
    imap_port: int = 993
    ssl: bool = True
    enabled: bool = True
    folder: str = "INBOX"                # 收信文件夹（IDLE/轮询均以此为准）
    idle_supported: bool | None = None   # None=未知，连接后探测
    poll_interval: int = 300             # IDLE 不可用时的轮询间隔
    smtp_host: str = ""                  # 留空则由 imap_host 推导
    smtp_port: int = 465                 # SMTP SSL 标准端口
    auth_type: str = "password"          # password | oauth2（v1.10.0）
    client_id: str = ""                  # OAuth2 应用注册的 client_id
    client_secret: str = ""              # 可选（Google 桌面应用通常有）
    extra: dict = field(default_factory=dict)

    @staticmethod
    def guess_host(email_addr: str) -> tuple[str, int]:
        domain = email_addr.rsplit("@", 1)[-1].lower()
        for d, (host, port) in KNOWN_HOSTS.items():
            # 边界匹配：myqq.com / x163.com 不能命中 qq.com/163.com，
            # 否则授权码会被发给错误的服务器
            if domain == d or domain.endswith("." + d):
                return host, port
        return ("imap." + domain if domain else "", 993)

    def smtp_endpoint(self) -> tuple[str, int]:
        """SMTP 服务器地址。未显式配置时由 IMAP 主机推导（imap.x → smtp.x）。"""
        if self.smtp_host:
            return self.smtp_host, self.smtp_port
        host = self.imap_host
        if host.startswith("imap."):
            host = "smtp." + host[len("imap."):]
        elif host.startswith("imap"):
            host = "smtp" + host[len("imap"):]
        return host, self.smtp_port

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Account":
        fields = {f for f in Account.__dataclass_fields__}
        return Account(**{k: v for k, v in d.items() if k in fields})


class AccountManager:
    """负责账户的增删改查与持久化。"""

    def __init__(self):
        self._accounts: dict[str, Account] = {}
        for d in config.load().get("accounts", []):
            try:
                acc = Account.from_dict(d)
                self._accounts[acc.id] = acc
            except TypeError:
                pass  # 字段不兼容的旧配置直接跳过，不崩溃

    # ---- 查询 ----
    def all(self) -> list[Account]:
        return list(self._accounts.values())

    def enabled(self) -> list[Account]:
        return [a for a in self._accounts.values() if a.enabled]

    def get(self, account_id: str) -> Account | None:
        return self._accounts.get(account_id)

    def password(self, account_id: str) -> str:
        return security.load_password(account_id)

    # ---- 增删改 ----
    def add(self, name: str, email_addr: str, password: str,
            imap_host: str = "", imap_port: int = 0, ssl: bool = True) -> Account:
        if not imap_host:
            imap_host, default_port = Account.guess_host(email_addr)
            imap_port = imap_port or default_port
        acc = Account(
            id=uuid.uuid4().hex[:8], name=name or email_addr, email=email_addr,
            imap_host=imap_host, imap_port=imap_port or 993, ssl=ssl,
        )
        self._accounts[acc.id] = acc
        security.save_password(acc.id, password)
        self._persist()
        return acc

    def update(self, acc: Account, password: str | None = None) -> None:
        self._accounts[acc.id] = acc
        if password:
            security.save_password(acc.id, password)
        self._persist()

    def remove(self, account_id: str) -> None:
        acc = self._accounts.get(account_id)
        self._accounts.pop(account_id, None)
        security.delete_password(account_id)
        if acc is not None:
            from .oauth2 import delete_token
            try:
                delete_token(acc.email)
            except Exception:
                pass
        self._persist()

    def _persist(self) -> None:
        data = config.load()
        data["accounts"] = [a.to_dict() for a in self._accounts.values()]
        config.save(data)
