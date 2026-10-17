# -*- coding: utf-8 -*-
"""SQLite 邮件缓存与账户镜像。单文件、零配置。"""
from __future__ import annotations

import json
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
    local_folder TEXT DEFAULT '',
    message_id TEXT,
    from_addr TEXT,
    from_name TEXT,
    subject TEXT,
    body_text TEXT,
    body_html TEXT,
    has_attachment INTEGER DEFAULT 0,
    received_at TEXT,
    fetched_at TEXT DEFAULT (datetime('now','localtime')),
    is_read INTEGER DEFAULT 0,
    UNIQUE(account_id, folder, uid)
);
CREATE INDEX IF NOT EXISTS idx_mails_account ON mails(account_id, received_at DESC);
DROP INDEX IF EXISTS idx_mails_unread;
CREATE INDEX IF NOT EXISTS idx_mails_account_read ON mails(account_id, is_read);
CREATE INDEX IF NOT EXISTS idx_mails_local ON mails(local_folder);
CREATE TABLE IF NOT EXISTS folder_state (
    account_id TEXT NOT NULL,
    folder TEXT NOT NULL,
    uidvalidity INTEGER DEFAULT 0,
    max_uid INTEGER DEFAULT 0,
    PRIMARY KEY(account_id, folder)
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """旧库升级：v1.2 及之前的 mails 表无 folder 列且唯一键为 (account_id, uid)。

    策略：建新表 -> 拷贝数据（folder 记为 INBOX）-> 删旧表 -> 改名。
    脚本开头 DROP 旧的新表保证幂等；显式 BEGIN IMMEDIATE 包住全程，
    防止 executescript 逐句提交留下半迁移状态。
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mails'").fetchone()
    if not exists:
        return  # 全新库，交给 _SCHEMA 建表
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(mails)")}
    if "folder" in cols:
        return
    # 兼容更老的库：缺列时用默认值填充，避免 SELECT 直接失败
    fetched_at = "fetched_at" if "fetched_at" in cols else "''"
    has_attach = "has_attachment" if "has_attachment" in cols else "0"
    is_read = "is_read" if "is_read" in cols else "0"
    message_id = "message_id" if "message_id" in cols else "''"
    from_addr = "from_addr" if "from_addr" in cols else "''"
    from_name = "from_name" if "from_name" in cols else "''"
    subject = "subject" if "subject" in cols else "''"
    body_text = "body_text" if "body_text" in cols else "''"
    received_at = "received_at" if "received_at" in cols else "''"
    conn.executescript(f"""
        BEGIN IMMEDIATE;
        DROP TABLE IF EXISTS mails_new;
        CREATE TABLE mails_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            uid TEXT NOT NULL,
            folder TEXT DEFAULT 'INBOX',
            local_folder TEXT DEFAULT '',
            message_id TEXT,
            from_addr TEXT,
            from_name TEXT,
            subject TEXT,
            body_text TEXT,
            body_html TEXT,
            has_attachment INTEGER DEFAULT 0,
            received_at TEXT,
            fetched_at TEXT DEFAULT (datetime('now','localtime')),
            is_read INTEGER DEFAULT 0,
            UNIQUE(account_id, folder, uid)
        );
        INSERT OR IGNORE INTO mails_new
            (id, account_id, uid, folder, local_folder, message_id, from_addr,
             from_name, subject, body_text, body_html, has_attachment,
             received_at, fetched_at, is_read)
        SELECT id, account_id, uid, 'INBOX', '', {message_id}, {from_addr},
               {from_name}, {subject}, {body_text}, '', {has_attach},
               {received_at}, {fetched_at}, {is_read}
        FROM mails;
        DROP TABLE mails;
        ALTER TABLE mails_new RENAME TO mails;
        CREATE INDEX IF NOT EXISTS idx_mails_account ON mails(account_id, received_at DESC);
        CREATE INDEX IF NOT EXISTS idx_mails_unread ON mails(is_read);
        CREATE INDEX IF NOT EXISTS idx_mails_local ON mails(local_folder);
        COMMIT;
    """)


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """连接上下文：yield 一个连接，退出时提交并**关闭**。

    注意不能只用 `with sqlite3.connect(...)`——那个只管事务不管关闭，
    Windows 上会一直占用 db 文件句柄。
    """
    conn = sqlite3.connect(_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # v1.12.0：WAL 允许收信后台写与 UI 大搜索（LIKE 扫 body_text）读写并发，
    # 原先默认 journal 模式下写会阻塞读；busy_timeout 兜底锁竞争
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.DatabaseError:
        pass
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """旧库增列兼容（须在 _SCHEMA 之前执行）。

    _SCHEMA 里 `CREATE INDEX idx_mails_local ON mails(local_folder)` 依赖
    local_folder 列——v1.3~v1.8 的库有 folder 列（_migrate 会提前返回）却
    缺 v1.9.0 新增的 local_folder，若先建索引会报
    "no such column: local_folder" 且程序无法启动。所以顺序必须是：
    先补列，再跑 _SCHEMA。
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mails'").fetchone()
    if not exists:
        return  # 全新库：_SCHEMA 建表时自带全部列
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(mails)")}
    if "attachment_names" not in cols:   # v1.5.0 新增
        conn.execute("ALTER TABLE mails ADD COLUMN attachment_names TEXT")
    if "body_html" not in cols:          # v1.9.0 新增
        conn.execute("ALTER TABLE mails ADD COLUMN body_html TEXT")
    if "local_folder" not in cols:       # v1.9.0 新增
        conn.execute("ALTER TABLE mails ADD COLUMN local_folder TEXT DEFAULT ''")


def init() -> None:
    try:
        _init_db()
    except sqlite3.DatabaseError as e:
        # 数据库损坏自愈（v1.11.7）：断电/杀软干扰可致 onemail.db 损坏，
        # 原先每次启动都抛 DatabaseError，应用永久无法启动只能手删文件。
        # 现在改名留证后重建空库（邮件历史丢失但应用可用）。
        import time
        backup = f"{_DB}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            os.replace(_DB, backup)
        except OSError:
            try:
                os.remove(_DB)
            except OSError:
                raise e   # 无法腾出路径：只能继续抛
        # 同名 -wal/-shm 残留一并清掉，防止新库读到旧日志
        for suffix in ("-wal", "-shm"):
            p = _DB + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        _init_db()


def _init_db() -> None:
    with _LOCK, _conn() as conn:
        _migrate(conn)
        _ensure_columns(conn)   # 旧库先补列：_SCHEMA 建索引依赖 local_folder
        conn.executescript(_SCHEMA)
        # 全新库由 _SCHEMA 建表（不含 attachment_names），再补一次（幂等）
        _ensure_columns(conn)


# 增量收信状态表建表语句已并入 _SCHEMA（见 init）


def get_folder_state(account_id: str, folder: str) -> tuple[int, int]:
    """返回 (uidvalidity, max_uid)，无记录为 (0, 0)。"""
    with _LOCK, _conn() as conn:
        row = conn.execute(
            "SELECT uidvalidity, max_uid FROM folder_state"
            " WHERE account_id=? AND folder=?", (account_id, folder)).fetchone()
    return (row["uidvalidity"], row["max_uid"]) if row else (0, 0)


def existing_uids(account_id: str, folder: str, uids: list[str]) -> set[str]:
    """返回本地已缓存的 UID 集合（低频对账用，v1.12.0）。

    传入的 uid 列表分批查询（调用方控制批量），返回其中已存在的子集。
    """
    if not uids:
        return set()
    out: set[str] = set()
    with _LOCK, _conn() as conn:
        for i in range(0, len(uids), 500):
            chunk = uids[i:i + 500]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT uid FROM mails WHERE account_id=? AND folder=?"
                f" AND uid IN ({placeholders})",
                (account_id, folder, *chunk)).fetchall()
            out.update(r["uid"] for r in rows)
    return out


def set_folder_state(account_id: str, folder: str,
                     uidvalidity: int, max_uid: int) -> None:
    with _LOCK, _conn() as conn:
        conn.execute(
            """INSERT INTO folder_state (account_id, folder, uidvalidity, max_uid)
               VALUES (?,?,?,?)
               ON CONFLICT(account_id, folder)
               DO UPDATE SET uidvalidity=excluded.uidvalidity,
                             max_uid=excluded.max_uid""",
            (account_id, folder, uidvalidity, max_uid))


def insert_mails(account_id: str, mails: list[dict],
                 folder: str = "INBOX") -> list[dict]:
    """插入邮件，返回真正新入库的（用于通知）。已存在的按 (account_id, folder, uid) 去重。"""
    new: list[dict] = []
    with _LOCK, _conn() as conn:
        for m in mails:
            if not m.get("uid"):
                continue  # 无 UID 的异常批次不入库，避免炸掉整批
            cur = conn.execute(
                """INSERT OR IGNORE INTO mails
                   (account_id, uid, folder, local_folder, message_id, from_addr,
                    from_name, subject, body_text, body_html, has_attachment,
                    received_at, attachment_names)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    account_id, m["uid"], folder or "INBOX", "",
                    m.get("message_id", ""),
                    m.get("from_addr", ""), m.get("from_name", ""),
                    m.get("subject", ""), m.get("body_text", ""),
                    m.get("body_html", ""),
                    1 if m.get("attachment_names") else 0,
                    m.get("received_at", ""),
                    json.dumps(m.get("attachment_names") or [], ensure_ascii=False),
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


def _escape_like(kw: str) -> str:
    """LIKE 通配符转义：搜「100%」「a_b」时按字面匹配。"""
    return kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_mails(account_id: str | None = None, keyword: str = "",
                 unread_only: bool = False, has_attach: bool = False,
                 local_folder: str | None = None,
                 limit: int = 500) -> tuple[list[sqlite3.Row], int]:
    """组合搜索：账户筛选 + 关键字（主题/发件人/正文）+ 未读/附件/本地文件夹过滤。

    返回 (结果行, 未筛选前总数)：总数用于状态栏显示「共 N 封（筛选后 M）」。
    两条查询在同一连接内完成，避免中途写入导致数字不一致。
    local_folder: None=不过滤；''=收件箱；其他=对应本地文件夹（v1.9.0）。
    """
    sql = "SELECT * FROM mails"
    conds: list[str] = []
    args: list = []
    if account_id:
        conds.append("account_id = ?")
        args.append(account_id)
    base_args = tuple(args)   # 账户筛选：total 只按账户计
    if local_folder is not None:
        conds.append("COALESCE(local_folder, '') = ?")
        args.append(local_folder)
    kw = keyword.strip()
    if kw:
        like = f"%{_escape_like(kw)}%"
        conds.append("(subject LIKE ? ESCAPE '\\' OR from_name LIKE ? ESCAPE '\\'"
                     " OR from_addr LIKE ? ESCAPE '\\' OR body_text LIKE ? ESCAPE '\\')")
        args += [like, like, like, like]
    if unread_only:
        conds.append("is_read = 0")
    if has_attach:
        conds.append("has_attachment = 1")
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with _LOCK, _conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM mails WHERE account_id = ?"
                             if account_id else "SELECT COUNT(*) c FROM mails",
                             base_args).fetchone()["c"]
        rows = conn.execute(
            sql + where + " ORDER BY received_at DESC, id DESC LIMIT ?",
            tuple(args) + (limit,)).fetchall()
    return rows, total


def get_mail(mail_id: int) -> sqlite3.Row | None:
    with _LOCK, _conn() as conn:
        return conn.execute("SELECT * FROM mails WHERE id=?", (mail_id,)).fetchone()


def delete_mail(mail_id: int) -> None:
    """删除单封本地缓存邮件（不动服务器）。"""
    with _LOCK, _conn() as conn:
        conn.execute("DELETE FROM mails WHERE id=?", (mail_id,))


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


def mark_all_read_synced(account_id: str | None = None) -> list[sqlite3.Row]:
    """全部标已读，并在**同一事务**内返回同步所需的未读行（v1.8.1）。

    先 SELECT 未读 (account_id, folder, uid) 再 UPDATE 置已读——若无事务包裹，
    间隙中入库的新邮件会被置已读却不在投递集合里，造成"本地已读、服务器
    永久未读"且水位机制不会自愈。rows 供 flag_sync 投递。
    （v1.11.7：显式 BEGIN IMMEDIATE——sqlite3 legacy 模式下 SELECT 不会
    开启事务，读-写间隙真实存在，docstring 声称的不变量原先只是靠进程内
    全局锁间接成立。）
    """
    with _LOCK, _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")   # 读-写置于同一写事务（见 docstring）
        if account_id:
            rows = conn.execute(
                "SELECT account_id, folder, uid FROM mails "
                "WHERE is_read=0 AND account_id=?", (account_id,)).fetchall()
            conn.execute("UPDATE mails SET is_read=1 WHERE account_id=?",
                         (account_id,))
        else:
            rows = conn.execute(
                "SELECT account_id, folder, uid FROM mails "
                "WHERE is_read=0").fetchall()
            conn.execute("UPDATE mails SET is_read=1")
        return rows


def unread_rows(account_id: str | None = None) -> list[sqlite3.Row]:
    """未读邮件的最小字段行 (account_id, folder, uid)，供已读同步投递（v1.7.0）。"""
    sql, args = "SELECT account_id, folder, uid FROM mails WHERE is_read=0", ()
    if account_id:
        sql, args = ("SELECT account_id, folder, uid FROM mails "
                     "WHERE is_read=0 AND account_id=?"), (account_id,)
    with _LOCK, _conn() as conn:
        return conn.execute(sql, args).fetchall()


def delete_account_mails(account_id: str) -> None:
    with _LOCK, _conn() as conn:
        conn.execute("DELETE FROM mails WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM folder_state WHERE account_id=?", (account_id,))


# ---------- 本地文件夹（v1.9.0） ----------

def set_mail_local_folder(mail_id: int, local_folder: str) -> None:
    """移动邮件到本地文件夹（'' = 收件箱）。不改 folder（服务器来源文件夹）。"""
    with _LOCK, _conn() as conn:
        conn.execute("UPDATE mails SET local_folder=? WHERE id=?",
                     (local_folder, mail_id))


def move_mails_to_folder(mail_ids: list[int], local_folder: str) -> int:
    """批量移动，返回实际移动的封数（同一事务）。"""
    if not mail_ids:
        return 0
    with _LOCK, _conn() as conn:
        cur = conn.execute(
            f"UPDATE mails SET local_folder=? WHERE id IN "
            f"({','.join('?' * len(mail_ids))})",
            (local_folder, *mail_ids))
        return cur.rowcount


def empty_local_folder(local_folder: str) -> int:
    """清空本地文件夹：其中邮件全部移回收件箱（删除文件夹时用）。"""
    with _LOCK, _conn() as conn:
        cur = conn.execute(
            "UPDATE mails SET local_folder='' WHERE local_folder=?",
            (local_folder,))
        return cur.rowcount


def local_folder_counts() -> dict[str, tuple[int, int]]:
    """各本地文件夹的 (总封数, 未读数)，含 ''（收件箱）。"""
    with _LOCK, _conn() as conn:
        rows = conn.execute(
            "SELECT COALESCE(local_folder, '') lf, COUNT(*) c,"
            " SUM(CASE WHEN is_read=0 THEN 1 ELSE 0 END) u"
            " FROM mails GROUP BY lf").fetchall()
    return {r["lf"]: (r["c"], r["u"]) for r in rows}
