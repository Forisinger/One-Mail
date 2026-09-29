# -*- coding: utf-8 -*-
"""密码安全存储：Windows DPAPI（ctypes 实现，零第三方依赖）。

加密结果绑定当前 Windows 用户，密文落盘 %APPDATA%/OneMail/secrets.bin。
"""
from __future__ import annotations

import ctypes
import json
import os
import threading
from ctypes import wintypes

if os.name != "nt":  # 非 Windows 环境（开发/测试用）退化为明文混淆
    _DPAPI = False
else:
    _DPAPI = True
    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi_protect(plain: bytes) -> bytes:
    in_blob, out_blob = _blob(plain), _DATA_BLOB()
    if not _crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        _kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(cipher: bytes) -> bytes:
    in_blob, out_blob = _blob(cipher), _DATA_BLOB()
    if not _crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError("CryptUnprotectData failed（可能换用户/换机器）")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        _kernel32.LocalFree(out_blob.pbData)


def data_dir() -> str:
    base = os.environ.get("APPDATA") if os.name == "nt" else os.path.expanduser("~")
    path = os.path.join(base or ".", "OneMail")
    os.makedirs(path, exist_ok=True)
    return path


_SECRETS = os.path.join(data_dir(), "secrets.bin")
_LOCK = threading.Lock()   # secrets.bin 读改写序列化，与 config 的锁同语义


def _atomic_write(text: str) -> None:
    """原子写：临时文件 + os.replace，进程中断不留半截 JSON。"""
    tmp = _SECRETS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, _SECRETS)


def save_password(account_id: str, password: str) -> None:
    """保存（加密）一个账户的密码。

    读取现有密码库失败时**不清空**——备份损坏文件后把新密码并入库会
    导致其余账户密码全部丢失，因此这里选择抛出让上层感知。
    """
    with _LOCK:
        store: dict = {}
        if os.path.exists(_SECRETS):
            raw = _read_secrets()
            try:
                store = json.loads(raw)
            except Exception:
                if raw.strip():
                    # 密码库损坏：备份后报错，避免空库覆盖造成全部密码丢失
                    try:
                        os.replace(_SECRETS, _SECRETS + ".corrupt")
                    except OSError:
                        pass
                    raise OSError("secrets.bin 已损坏（已备份为 secrets.bin.corrupt），"
                                  "为防密码丢失未执行覆盖，请重新录入各账户授权码")
                store = {}
        if _DPAPI:
            store[account_id] = _dpapi_protect(password.encode("utf-8")).hex()
        else:
            store[account_id] = password  # 非 Windows 测试环境明文
        _atomic_write(json.dumps(store, ensure_ascii=False))


def load_password(account_id: str) -> str:
    # 也持锁：flag_sync 后台线程会并发读取；若与 save/delete 的 os.replace
    # 重叠，Windows 上打开中的文件会令 replace 抛 PermissionError（写侧失败）
    with _LOCK:
        if not os.path.exists(_SECRETS):
            return ""
        try:
            store = json.loads(_read_secrets())
            val = store.get(account_id, "")
            if not val:
                return ""
            if _DPAPI:
                return _dpapi_unprotect(bytes.fromhex(val)).decode("utf-8")
            return val
        except Exception:
            return ""


def delete_password(account_id: str) -> None:
    with _LOCK:
        if not os.path.exists(_SECRETS):
            return
        try:
            store = json.loads(_read_secrets())
            store.pop(account_id, None)
            _atomic_write(json.dumps(store, ensure_ascii=False))
        except Exception:
            pass


def _read_secrets() -> str:
    with open(_SECRETS, "r", encoding="utf-8") as f:
        return f.read()
