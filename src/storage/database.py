# -*- coding: utf-8 -*-
"""SQLite 邮件缓存与账户镜像。单文件、零配置。"""
from __future__ import annotations

import os
import sqlite3
import threading

from .config import data_dir

_DB = os.path.join(data_dir(), "onemail.db")
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    uid TEXT NOT NULL,
    message_id TEXT,
    from_addr TEXT,
    from_name TEXT,
    subject TEXT,
    body_text TEXT,
    has_attachment INTEGER DEFAULT 0,
    received_at TEXT,
    fetched_at TEXT DEFAULT (datetime('now','localtime')),
    is_read INTEGER DEFAULT 0,
    UNIQUE(account_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_mails_account ON mails(account_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_mails_unread ON mails(is_read);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _LOCK, _conn() as conn:
        conn.executescript(_SCHEMA)


def insert_mails(account_id: str, mails: list[dict]) -> list[dict]:
    """插入邮件，返回真正新入库的（用于通知）。已存在的按 (account_id, uid) 去重。"""
    new: list[dict] = []
    with _LOCK, _conn() as conn:
        for m in mails:
            cur = conn.execute(
                """INSERT OR IGNORE INTO mails
                   (account_id, uid, message_id, from_addr, from_name, subject,
                    body_text, has_attachment, received_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    account_id, m["uid"], m.get("message_id", ""),
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
