# -*- coding: utf-8 -*-
"""v1.11.1 缩放适配的纯计算测试（不依赖 tkinter）。

回归目标：窗口/DPI 缩放后
1. 邮件列表四列（来源/发件人/主题/时间）永远拿得到最小宽度 —— 不会被裁掉；
2. 分栏分隔条位置不会被允许把某一栏压成 0 像素 —— 整栏（含列头）不会消失。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ui.layout import (COL_MIN, COL_RATIO, PANE_MIN_BODY, PANE_MIN_LEFT,  # noqa: E402
                       PANE_MIN_MAIL, PANE_MIN_RIGHT, clamp_sash,
                       pane_minimums, plan_column_widths)


class PlanColumnTests(unittest.TestCase):
    def test_constants_are_consistent(self):
        self.assertEqual(set(COL_MIN), set(COL_RATIO))
        self.assertAlmostEqual(sum(COL_RATIO.values()), 1.0, places=6)
        for cid, w in COL_MIN.items():
            self.assertGreater(w, 0, cid)

    def test_fills_available_width(self):
        for avail in (420, 520, 770, 1200, 2000):
            w = plan_column_widths(avail)
            self.assertEqual(sum(w.values()), avail, f"avail={avail}")

    def test_every_column_keeps_minimum(self):
        # 含极窄容器：不得出现 0 宽列（0 宽 = 列"消失"）
        for avail in (1, 50, 200, 300, 411, 412, 520, 900):
            w = plan_column_widths(avail)
            for cid, width in w.items():
                self.assertGreaterEqual(width, COL_MIN[cid],
                                        f"avail={avail} 列 {cid} 太窄：{width}")
                self.assertGreater(width, 0)

    def test_too_narrow_falls_back_to_minimums(self):
        w = plan_column_widths(120)
        self.assertEqual(w, dict(COL_MIN))

    def test_ratio_is_respected_when_roomy(self):
        w = plan_column_widths(1000)
        # 主题列最大、发件人次之、时间与来源最小
        self.assertGreater(w["subject"], w["from"])
        self.assertGreater(w["from"], w["account"])
        self.assertGreaterEqual(w["date"], COL_MIN["date"])

    def test_deficit_goes_to_flex_column(self):
        # 窄到必须抬最小宽时，主题列仍承担伸缩（不会出现负宽）
        w = plan_column_widths(500)
        self.assertGreaterEqual(w["subject"], COL_MIN["subject"])
        self.assertEqual(sum(w.values()), 500)

    def test_custom_ratio_without_subject(self):
        w = plan_column_widths(300, col_min={"a": 50, "b": 50},
                               col_ratio={"a": 0.5, "b": 0.5})
        self.assertEqual(sum(w.values()), 300)
        self.assertGreaterEqual(w["a"], 50)


class ClampSashTests(unittest.TestCase):
    def test_within_range_untouched(self):
        self.assertEqual(clamp_sash(300, 600, 130, 80), 300)

    def test_clamped_up_to_before_min(self):
        # 邮件列表被拖到 3px（正是用户报的"整栏消失"）
        self.assertEqual(clamp_sash(3, 600, 130, 80), 130)

    def test_clamped_down_to_after_min(self):
        # 阅读区被压到 2px
        self.assertEqual(clamp_sash(598, 600, 130, 80), 520)

    def test_too_small_total_is_noop(self):
        self.assertEqual(clamp_sash(10, 200, 130, 80), 10)

    def test_never_returns_negative(self):
        for total in (0, 1, 50, 209, 210, 211, 400, 1000):
            out = clamp_sash(-5, total, 130, 80)
            self.assertGreaterEqual(out, 0)
            out2 = clamp_sash(10 ** 6, total, 130, 80)
            self.assertLessEqual(out2, max(total, 0))


class PaneMinimumsTests(unittest.TestCase):
    def test_large_window_uses_wanted_minimums(self):
        self.assertEqual(pane_minimums(600, PANE_MIN_MAIL, PANE_MIN_BODY),
                         (PANE_MIN_MAIL, PANE_MIN_BODY))

    def test_small_window_shrinks_proportionally(self):
        top, bot = pane_minimums(240, PANE_MIN_MAIL, PANE_MIN_BODY)
        self.assertEqual(top, 80)      # max(60, 240//3)
        self.assertEqual(bot, 60)      # max(40, 240//4)
        self.assertLessEqual(top + bot, 240)

    def test_side_pane_minimums(self):
        # 小窗口：两侧最小值按比例收缩，但仍都 > 0（不会有一栏被压没）
        left, right = pane_minimums(1000, PANE_MIN_LEFT, PANE_MIN_RIGHT)
        self.assertLessEqual(left, PANE_MIN_LEFT)
        self.assertLessEqual(right, PANE_MIN_RIGHT)
        self.assertGreater(left, 0)
        self.assertGreater(right, 0)
        # 窗口足够大时拿到期望值
        left2, right2 = pane_minimums(2060, PANE_MIN_LEFT, PANE_MIN_RIGHT)
        self.assertEqual((left2, right2), (PANE_MIN_LEFT, PANE_MIN_RIGHT))


class RegressionScenarioTests(unittest.TestCase):
    """把用户报告的场景写成断言：缩放后邮件列表必须仍然可见。"""

    def test_shrinking_window_keeps_mail_list_visible(self):
        # 从 1060x660 缩到 800x500（最小窗口）：垂直分栏可用高度约 410px
        total = 410
        top_min, bot_min = pane_minimums(total, PANE_MIN_MAIL, PANE_MIN_BODY)
        for pos in (0, 5, 20, 100, total - 1, total + 50):
            new = clamp_sash(pos, total, top_min, bot_min)
            self.assertGreaterEqual(new, top_min - 0)
            self.assertGreaterEqual(total - new, bot_min - 0)
            self.assertGreater(new, 0, "邮件列表高度归零 = 整栏消失")

    def test_narrow_window_keeps_all_four_columns(self):
        # 800px 宽窗口下邮件列表可视宽度约 520px
        for width in (300, 520, 732):
            w = plan_column_widths(width)
            self.assertEqual(len(w), 4)
            for cid in ("account", "from", "subject", "date"):
                self.assertGreaterEqual(w[cid], COL_MIN[cid])
                # 时间列（最右）宽度必须够放下 "10-02 14:29"
                if cid == "date":
                    self.assertGreaterEqual(w[cid], 90)


if __name__ == "__main__":
    unittest.main()
