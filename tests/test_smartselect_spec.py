"""智慧選字規格測試：純上下文預測，不做全域重排。

判定準則：
  - 全域重排 = 「沒有前一字」時順序被改變 → 違反規格
  - 上下文預測 = 只有「前一字命中學習紀錄」時才提前 → 規格行為

案例以使用者實測情境建模：大易三碼 aex（人一水）= [使, 便, 仗]，
連續選「便」三次後回報「便變第一」。
"""
import os
import sys
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


TABLE_ORDER = ["使", "便", "仗"]  # dayi3 aex 的碼表原始順序


class SmartSelectSpecTests(unittest.TestCase):
    def make_cin(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "cin_module_spec", os.path.join(PYTHON_DIR, "cinbase", "cin.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cin = mod.Cin.__new__(mod.Cin)
        cin.cincount = {}
        cin._count_dirty = False
        return cin

    def replay_user_session(self, cin, now):
        """重演使用者操作：宜→使、使→使、使→使、使→便、便→便、便→便"""
        with mock.patch("time.time", return_value=now):
            cin.addCount("aex", "使", "宜")
            cin.addCount("aex", "使", "使")
            cin.addCount("aex", "使", "使")
            cin.addCount("aex", "便", "使")
            cin.addCount("aex", "便", "便")
            cin.addCount("aex", "便", "便")

    def test_case1_no_context_keeps_table_order(self):
        """【全域重排判定】無前一字 → 必須是碼表順序，不論選過幾次"""
        cin = self.make_cin()
        now = 1000000.0
        self.replay_user_session(cin, now)

        with mock.patch("time.time", return_value=now + 1):
            ordered = cin.sortByCount("aex", list(TABLE_ORDER), previousChar="")

        self.assertEqual(ordered, TABLE_ORDER)

    def test_case2_unrelated_previous_char_keeps_table_order(self):
        """【全域重排判定】前一字無紀錄（天）→ 碼表順序"""
        cin = self.make_cin()
        now = 1000000.0
        self.replay_user_session(cin, now)

        with mock.patch("time.time", return_value=now + 1):
            ordered = cin.sortByCount("aex", list(TABLE_ORDER), previousChar="天")

        self.assertEqual(ordered, TABLE_ORDER)

    def test_case3_self_context_promotes_repeated_char(self):
        """【上下文預測】前一字=便（剛連選過）→「便」提前（截圖情境）"""
        cin = self.make_cin()
        now = 1000000.0
        self.replay_user_session(cin, now)

        with mock.patch("time.time", return_value=now + 1):
            ordered = cin.sortByCount("aex", list(TABLE_ORDER), previousChar="便")

        self.assertEqual(ordered[0], "便")

    def test_case4_huge_count_without_context_never_reorders(self):
        """【全域重排判定】count 灌到 999、無上下文命中 → 仍是碼表順序"""
        cin = self.make_cin()
        now = 1000000.0
        cin.cincount = {"aex": {
            "便": {"count": 999, "last": now, "prev": {"使": 50, "便": 50}},
        }}

        with mock.patch("time.time", return_value=now + 1):
            no_ctx = cin.sortByCount("aex", list(TABLE_ORDER), previousChar="")
            other_ctx = cin.sortByCount("aex", list(TABLE_ORDER), previousChar="天")

        self.assertEqual(no_ctx, TABLE_ORDER)
        self.assertEqual(other_ctx, TABLE_ORDER)

    def test_case5_context_toggle_off_disables_all_reorder(self):
        """【開關】關閉「前一字上下文」→ 即使上下文命中也維持碼表順序"""
        cin = self.make_cin()
        now = 1000000.0
        self.replay_user_session(cin, now)

        with mock.patch("time.time", return_value=now + 1):
            ordered = cin.sortByCount("aex", list(TABLE_ORDER),
                                      previousChar="便", useContext=False)

        self.assertEqual(ordered, TABLE_ORDER)

    def test_case6_focus_switch_clears_context(self):
        """【邊界】焦點切換清掉 lastCommitString 後 → 等同無上下文"""
        import cinbase

        cbTS = type("FakeTS", (), {})()
        cbTS.lastCommitString = "便"
        cbTS.showmenu = False
        cbTS.keepComposition = False
        cbTS.compositionBufferMode = False
        # 只驗證 forced 終止會清 lastCommitString（resetComposition 需要完整
        # cbTS，這裡攔掉）
        with mock.patch.object(cinbase.CinBase, "resetComposition"):
            cinbase.CinBase.onCompositionTerminated(cbTS, True)

        self.assertEqual(cbTS.lastCommitString, "")


if __name__ == "__main__":
    unittest.main()
