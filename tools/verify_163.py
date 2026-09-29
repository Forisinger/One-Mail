# -*- coding: utf-8 -*-
"""真实 163 IMAP 端到端验证：连接/UIDVALIDITY/增量抓取/水位。
使用临时数据库，不影响真实 APPDATA 数据。运行：python tools/verify_163.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from storage import database as db
from storage import config as config_store
from core.account import AccountManager
from core.mail_client import MailClient


def main():
    tmp = tempfile.TemporaryDirectory()
    db._DB = os.path.join(tmp.name, "verify.db")
    db.init()

    mgr = AccountManager()
    accs = mgr.enabled()
    if not accs:
        print("无可用账户")
        return 1
    acc = accs[0]
    pwd = mgr.password(acc.id)
    print(f"账户: {acc.email}  IMAP: {acc.imap_host}:{acc.imap_port}  folder={acc.folder}")

    client = MailClient(acc, pwd, on_new_mail=lambda a, m: print(f"  回调: {len(m)} 封新邮件"),
                        on_status=lambda a, t: print(f"  [状态] {t}"))

    conn = client._connect()
    print(f"SELECT 状态: {conn.state}")

    # UIDVALIDITY 读取
    uv = conn.untagged_responses.get("UIDVALIDITY")
    print(f"UIDVALIDITY 响应: {uv}")
    assert uv, "SELECT 后应能读到 UIDVALIDITY"

    # 文件夹列表
    folders = MailClient.list_folders(acc, pwd)
    print(f"文件夹列表({len(folders)}): {folders[:10]}")

    # 第一轮抓取（水位 0 -> 全量未读）
    client._fetch_new(conn)
    uv1, max1 = db.get_folder_state(acc.id, client._folder())
    rows1, total1 = db.search_mails()
    print(f"第一轮: uidvalidity={uv1} max_uid={max1} 本地邮件数={total1}")

    # 第二轮抓取（应全部被水位过滤，0 下载）
    client._fetch_new(conn)
    uv2, max2 = db.get_folder_state(acc.id, client._folder())
    rows2, total2 = db.search_mails()
    print(f"第二轮: uidvalidity={uv2} max_uid={max2} 本地邮件数={total2}")
    assert (uv1, max1) == (uv2, max2) and total1 == total2, \
        "无新邮件时第二轮不应改变水位或数量"

    conn.logout()
    print("VERIFY_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
