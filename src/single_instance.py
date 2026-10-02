# -*- coding: utf-8 -*-
"""单实例保护：防止重复运行，二次启动时唤醒已运行实例并置前窗口。

实现方式（纯 Win32，零依赖）：
- 命名互斥体 CreateMutexW：首个实例持有；第二实例检测到已存在即退出
- 命名事件 CreateEventW：第二实例 SetEvent 发唤醒信号；首个实例的
  守护线程 WaitForSingleObject 收到后回调 UI

互斥体随进程退出由系统自动释放，无需手动清理。
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

_MUTEX_NAME = "Local\\OneMail_SingleInstance_Mutex"
_EVENT_NAME = "Local\\OneMail_SingleInstance_Wakeup"

_ERROR_ALREADY_EXISTS = 183
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF
_EVENT_MODIFY_STATE = 0x0002  # SetEvent 所需权限

_mutex_handle = None


def acquire() -> bool:
    """尝试成为唯一实例。

    返回 True：本实例是首个实例，可以继续启动。
    返回 False：已有实例在运行（应先 notify_running_instance 再退出）。
    """
    global _mutex_handle
    _mutex_handle = _k32.CreateMutexW(None, False, _MUTEX_NAME)
    # CreateMutexW 失败返回 INVALID_HANDLE_VALUE(-1) 而非 NULL：只查 NULL 会把
    # ACCESS_DENIED 等失败误判成"成功且不存在"，双开保护静默失效（v1.10.2）
    if not _mutex_handle or _mutex_handle == -1:
        # 互斥体创建失败，绝不假阳性地放行双开
        return False
    return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS


def notify_running_instance() -> bool:
    """第二实例调用：唤醒已运行的实例。返回是否成功发信号。"""
    ev = _k32.OpenEventW(_EVENT_MODIFY_STATE, False, _EVENT_NAME)
    if not ev:
        return False
    _k32.SetEvent(ev)
    _k32.CloseHandle(ev)
    return True


def start_watcher(on_wakeup, error_log=None) -> None:
    """启动守护线程，等待其他实例的唤醒信号并回调 on_wakeup()。

    回调在工作线程中执行——Tk 不允许跨线程操作，调用方应把动作
    投递回 UI 线程（例如塞进命令队列）。
    """
    # 自动复位事件：WaitForSingleObject 返回后自动清除信号
    ev = _k32.CreateEventW(None, False, False, _EVENT_NAME)
    if not ev:
        return

    def _run():
        while True:
            ret = _k32.WaitForSingleObject(ev, _INFINITE)
            if ret != _WAIT_OBJECT_0:
                return
            try:
                on_wakeup()
            except Exception as e:  # 唤醒失败不应让守护线程死掉
                if error_log:
                    try:
                        error_log(f"唤醒回调异常: {e!r}")
                    except OSError:
                        pass

    t = threading.Thread(target=_run, name="onemail-single-instance", daemon=True)
    t.start()
