# -*- coding: utf-8 -*-
"""config.json 读写：账户列表与全局设置。密码不存这里。"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

from core.security import data_dir

_CONFIG = os.path.join(data_dir(), "config.json")
# RLock：get_setting 在持锁状态下调用 load()（后者也加锁）
_LOCK = threading.RLock()

# 单设置项读取的 mtime 缓存（v1.12.1）：FlagSync 的 enabled 回调每批次
# 都会触发——原先每次都完整读盘解析 config.json
_cached_data: dict | None = None
_cached_mtime: float = -1.0

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
            _backup_corrupt()
            return json.loads(json.dumps(_DEFAULT))
        # 合法 JSON 但类型不对（[1,2] / "x" / null 等）同样要兜住：
        # 否则 data.setdefault 抛 AttributeError 逃出 load()，exe 无控制台
        # 表现为"双击无反应"，且 .corrupt 备份逻辑完全不触发（v1.11.7）
        if not isinstance(data, dict) or not isinstance(
                data.get("accounts", []), list):
            _backup_corrupt()
            return json.loads(json.dumps(_DEFAULT))
    # 补齐缺失键
    for k, v in _DEFAULT["settings"].items():
        settings = data.setdefault("settings", {})
        if not isinstance(settings, dict):
            data["settings"] = dict(_DEFAULT["settings"])
            break
        settings.setdefault(k, v)
    return data


def _backup_corrupt() -> None:
    """备份损坏配置。目标已存在时改用带时间戳的名字，避免覆盖上一次留证。"""
    dst = _CONFIG + ".corrupt"
    try:
        if os.path.exists(dst):
            import time
            dst = f"{_CONFIG}.corrupt.{time.strftime('%Y%m%d-%H%M%S')}"
        os.replace(_CONFIG, dst)
    except OSError:
        pass


def get_setting(key: str, default=None):
    """读取单个设置项（按 mtime 缓存，v1.12.1）。

    save() 落盘后 mtime 变化自动失效；文件不存在时 mtime=-1 也命中缓存。
    """
    global _cached_data, _cached_mtime
    with _LOCK:
        try:
            mtime = (os.path.getmtime(_CONFIG)
                     if os.path.exists(_CONFIG) else -1.0)
        except OSError:
            mtime = -1.0
        if _cached_data is None or mtime != _cached_mtime:
            _cached_data = load()
            _cached_mtime = mtime
        return _cached_data.get("settings", {}).get(key, default)


def save(data: dict) -> None:
    """原子写：先写临时文件再 os.replace，进程中断也不会留下半个 JSON。"""
    global _cached_data, _cached_mtime
    tmp = _CONFIG + ".tmp"
    with _LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            # flush+fsync：断电/崩溃时防止 rename 先于数据块落盘，
            # 否则 config.json 可能变成空/截断文件，表现为账户全消失
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _CONFIG)
        # 显式失效缓存（v1.13.0）：NTFS mtime 更新粒度受系统时钟计时器
        # 影响，同 tick 内双写可能返回相同 mtime，get_setting 会读到陈旧值
        _cached_data = None
        _cached_mtime = -1.0
