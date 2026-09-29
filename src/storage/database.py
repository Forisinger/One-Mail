# -*- coding: utf-8 -*-
"""SQLite 邮件缓存与账户镜像。单文件、零配置。"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from .config import data_dir

_DB = os.path.join(data_dir(), "onemail.db")
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    uid TEXT NOT NULL,
    folder TEXT DEFAULT 'INBOX',
    message_id TEXT,
    from_addr TEXT,
    from_name TEXT,
    subject TEXT,
    body_text TEXT,
    has_attachment INTEGER DEFAULT 0,
    received_at TEXT,
    fetched_at TEXT DEFAULT (datetime('now','localtime')),
    is_read INTEGER DEFAULT 0,
    UNIQUE(account_id, folder, uid)
);
CREATE INDEX IF NOT EXISTS idx_mails_account ON mails(account_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_mails_unread ON mails(is_read);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """旧库升级：v1.2 及之前的 mails 表无 folder 列且唯一键为 (account_id, uid)。

    策略：建新表 -> 拷贝数据（folder 记为 INBOX）-> 删旧表 -> 改名，单事务原子完成。
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mails'").fetchone()
    if not exists:
        return  # 全新库，交给 _SCHEMA 建表
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(mails)")}
    if "folder" in cols:
        return
    conn.executescript("""
        CREATE TABLE mails_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            uid TEXT NOT NULL,
            folder TEXT DEFAULT 'INBOX',
            message_id TEXT,
            from_addr TEXT,
            from_name TEXT,
            subject TEXT,
            body_text TEXT,
            has_attachment INTEGER DEFAULT 0,
            received_at TEXT,
            fetched_at TEXT DEFAULT (datetime('now','localtime')),
            is_read INTEGER DEFAULT 0,
            UNIQUE(account_id, folder, uid)
        );
        INSERT OR IGNORE INTO mails_new
            (id, account_id, uid, folder, message_id, from_addr, from_name,
             subject, body_text, has_attachment, received_at, fetched_at, is_read)
        SELECT id, account_id, uid, 'INBOX', message_id, from_addr, from_name,
               subject, body_text, has_attachment, received_at, fetched_at, is_read
        FROM mails;
        DROP TABLE mails;
        ALTER TABLE mails_new RENAME TO mails;
        CREATE INDEX IF NOT EXISTS idx_mails_account ON mails(account_id, received_at DESC);
        CREATE INDEX IF NOT EXISTS idx_mails_unread ON mails(is_read);
    """)


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """连接上下文：yield 一个连接，退出时提交并**关闭**。

    注意不能只用 `with sqlite3.connect(...)`——那个只管事务不管关闭，
    Windows 上会一直占用 db 文件句柄。
    """
    conn = sqlite3.connect(_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init() -> None:
    with _LOCK, _conn() as conn:
        _migrate(conn)
        conn.executescript(_SCHEMA)


def insert_mails(account_id: str, mails: list[dict],
                 folder: str = "INBOX") -> list[dict]:
    """插入邮件，返回真正新入库的（用于通知）。已存在的按 (account_id, folder, uid) 去重。"""
    new: list[dict] = []
    with _LOCK, _conn() as conn:
        for m in mails:
            cur = conn.execute(
                """INSERT OR IGNORE INTO mails
                   (account_id, uid, folder, message_id, from_addr, from_name, subject,
                    body_text, has_attachment, received_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    account_id, m["uid"], folder or "INBOX", m.get("message_id", ""),
                    m.get("from_addr", ""), m.get("from_name", ""),
                    m.get("subject", ""), m.get("body_text", ""),
                    1 if m.get("attachment_names") else 0,
                    m.get("received_at", ""),
                ),
            )
            if cur.rowcount > 0:
                new.append(m)
    return new


def list_mails(account_id: str | None = None, limit: int = 200) -> list[sqlite3.Row]:
    sql = "SELECT * FROM mails"
    args: tuple = ()
    if account_id:
        sql += " WHERE account_id = ?"
        args = (account_id,)
    sql += " ORDER BY received_at DESC, id DESC LIMIT ?"
    args = args + (limit,)
    with _LOCK, _conn() as conn:
        return conn.execute(sql, args).fetchall()


def search_mails(account_id: str | None = None, keyword: str = "",
                 unread_only: bool = False, has_attach: bool = False,
                 limit: int = 500) -> tuple[list[sqlite3.Row], int]:
    """组合搜索：账户筛选 + 关键字（主题/发件人/正文）+ 未读/附件过滤。

    返回 (结果行, 未筛选前总数)：总数用于状态栏显示「共 N 封（筛选后 M）」。
    """
    base_sql = "SELECT COUNT(*) c FROM mails"
    base_args: tuple = ()
    if account_id:
        base_sql += " WHERE account_id = ?"
        base_args = (account_id,)
    with _LOCK, _conn() as conn:
        total = conn.execute(base_sql, base_args).fetchone()["c"]

    sql = "SELECT * FROM mails"
    conds: list[str] = []
    args: list = []
    if account_id:
        conds.append("account_id = ?")
        args.append(account_id)
    kw = keyword.strip()
    if kw:
        like = f"%{kw}%"
        conds.append("(subject LIKE ? OR from_name LIKE ? OR from_addr LIKE ?"
                     " OR body_text LIKE ?)")
        args += [like, like, like, like]
    if unread_only:
        conds.append("is_read = 0")
    if has_attach:
        conds.append("has_attachment = 1")
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY received_at DESC, id DESC LIMIT ?"
    args.append(limit)
    with _LOCK, _conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return rows, total


def get_mail(mail_id: int) -> sqlite3.Row | None:
    with _LOCK, _conn() as conn:
        return conn.execute("SELECT * FROM mails WHERE id=?", (mail_id,)).fetchone()


def mark_read(mail_id: int, read: bool = True) -> None:
    with _LOCK, _conn() as conn:
        conn.execute("UPDATE mails SET is_read=? WHERE id=?", (1 if read else 0, mail_id))


def mark_all_read(account_id: str | None = None) -> None:
    sql, args = "UPDATE mails SET is_read=1", ()
    if account_id:
        sql, args = "UPDATE mails SET is_read=1 WHERE account_id=?", (account_id,)
    with _LOCK, _conn() as conn:
        conn.execute(sql, args)


def unread_count(account_id: str | None = None) -> int:
    sql, args = "SELECT COUNT(*) c FROM mails WHERE is_read=0", ()
    if account_id:
        sql, args = "SELECT COUNT(*) c FROM mails WHERE is_read=0 AND account_id=?", (account_id,)
    with _LOCK, _conn() as conn:
        return conn.execute(sql, args).fetchone()["c"]


def delete_account_mails(account_id: str) -> None:
    with _LOCK, _conn() as conn:
        conn.execute("DELETE FROM mails WHERE account_id=?", (account_id,))
