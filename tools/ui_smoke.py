# -*- coding: utf-8 -*-
"""程序化 UI 冒烟：真实启动 App，驱动搜索/过滤器/排序/打开邮件，验证无异常。

使用真实配置与数据库（与正常使用一致）。运行约 25 秒后自动退出。
注意：Tk 窗口进程在某些沙箱/CI 中会被拦截，请在交互式桌面环境运行：
    python tools/ui_smoke.py      （或 venv 的 python.exe，建议加 -u）
退出走 os._exit，结果打印在退出前完成。
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from main import App


def main():
    results: list[str] = []
    holder: dict = {}

    def drive():
        app = holder["app"]
        w = app.window
        try:
            # 1) 搜索防抖链路
            w._search_var.set("a")
            w.root.after(400, lambda: results.append("搜索OK") or w._search_var.set(""))

            # 2) 过滤器切换
            def filters():
                for mode in ("只看未读", "有附件", "全部"):
                    w._filter_var.set(mode)
                    w.refresh_mails()
                results.append("过滤器OK")
            w.root.after(800, filters)

            # 3) 列头排序
            def sorts():
                for cid in ("from", "subject", "account", "date"):
                    w._on_sort(cid)
                w._on_sort("date")      # 回到默认（反转一次）
                results.append("排序OK")
            w.root.after(1200, sorts)

            # 4) 打开第一封邮件（触发已读/阅读区/附件名渲染）
            def open_first():
                kids = w.tree.get_children()
                if kids:
                    w.tree.selection_set(kids[0])
                    w._on_mail_open()
                results.append("打开邮件OK")
            w.root.after(1600, open_first)

            # 5) 状态刷新（账户卡片状态）
            def status():
                if w.manager.all():
                    acc = w.manager.all()[0]
                    w.set_account_status(acc.id, "冒烟测试状态")
                    w.refresh_accounts()
                results.append("状态OK")
            w.root.after(2000, status)

            # 6) 先打印结果再退出（quit 走 os._exit，之后任何代码都不会执行）
            def done():
                print("---- UI SMOKE 结果 ----")
                for r in results:
                    print(r)
                ok = all(not r.startswith("DRIVE") for r in results) and \
                    sum(1 for r in results if r.endswith("OK")) >= 5
                print("UI_SMOKE_OK" if ok else "UI_SMOKE_FAIL")
                w.root.after(200, app.quit)
            w.root.after(2400, done)
        except Exception:
            results.append("DRIVE 异常:\n" + traceback.format_exc())
            print("UI_SMOKE_FAIL")
            print(traceback.format_exc())
            app.quit()

    def report():
        print("---- UI SMOKE 结果 ----")
        for r in results:
            print(r)
        ok = all(not r.startswith("DRIVE") for r in results) and \
            sum(1 for r in results if r.endswith("OK")) >= 5
        print("UI_SMOKE_OK" if ok else "UI_SMOKE_FAIL")

    # App.__init__ 以 mainloop() 结尾且不返回——驱动回调必须在 mainloop
    # 启动**之前**挂上，且 App 实例要在其构造期间就注册进 holder。
    import tkinter as tk

    class SmokeApp(App):
        def __init__(self, *a, **kw):
            holder["app"] = self
            super().__init__(*a, **kw)

    orig_mainloop = tk.Tk.mainloop
    patched = {"done": False}

    def mainloop_with_drive(self, *a, **kw):
        if not patched["done"]:
            patched["done"] = True
            self.after(5000, drive)   # 等收信线程先连上
        return orig_mainloop(self, *a, **kw)

    tk.Tk.mainloop = mainloop_with_drive
    SmokeApp(False)                   # 正常情况下不会走到这里（os._exit 退出）
    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
