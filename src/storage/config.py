# -*- coding: utf-8 -*-
"""config.json 读写：账户列表与全局设置。密码不存这里。"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

from core.security import data_dir

_CONFIG = os.path.join(data_dir(), "config.json")
_LOCK = threading.Lock()

_DEFAULT: dict[str, Any] = {
    "accounts": [],
    "settings": {
        "autostart": True,
        "poll_interval_fallback": 300,   # 不支持 IDLE 时的轮询秒数
        "notify_sound": True,
        "sync_read_flags": True,   # 本地标已读后同步到服务器 \Seen（v1.7.0）
        "start_minimized": False,   # 仅作记录；实际静默与否取决于启动参数 --minimized
    },
}


def load() -> dict:
    with _LOCK:
        if not os.path.exists(_CONFIG):
            return json.loads(json.dumps(_DEFAULT))
        try:
            with open(_CONFIG, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            # 损坏的配置先备份留证，再回默认——绝不静默丢弃用户数据
            try:
                os.replace(_CONFIG, _CONFIG + ".corrupt")
            except OSError:
                pass
            return json.loads(json.dumps(_DEFAULT))
    # 补齐缺失键
    for k, v in _DEFAULT["settings"].items():
        data.setdefault("settings", {}).setdefault(k, v)
    return data


def save(data: dict) -> None:
    """原子写：先写临时文件再 os.replace，进程中断也不会留下半个 JSON。"""
    tmp = _CONFIG + ".tmp"
    with _LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            # flush+fsync：断电/崩溃时防止 rename 先于数据块落盘，
            # 否则 config.json 可能变成空/截断文件，表现为账户全消失
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _CONFIG)
