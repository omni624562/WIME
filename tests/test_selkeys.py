import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class FakeTextService:
    """Stands in for textService.TextService: records setSelKeys per client."""

    @staticmethod
    def setSelKeys(cbTS, selKeys):
        cbTS.sentSelKeys.append(selKeys)


class FakeClient:
    def __init__(self, imeDirName="chedayi"):
        self.imeDirName = imeDirName
        self.sentSelKeys = []


class SelKeysCacheTests(unittest.TestCase):
    """每個應用程式視窗是獨立的 C++ TextService；「上次送出的選字鍵」
    快取必須跟著 client 走，否則第二個視窗會停留在預設 1234567890。"""

    def setUp(self):
        import cinbase
        self.cinbase = cinbase.CinBase

    def test_cache_is_per_client(self):
        a = FakeClient()
        b = FakeClient()
        self.cinbase.initTextService(a, FakeTextService)
        self.cinbase.initTextService(b, FakeTextService)

        self.assertEqual(a.candselKeys, "1234567890")
        self.assertEqual(b.candselKeys, "1234567890")
        self.assertEqual(a.sentSelKeys, ["1234567890"])
        self.assertEqual(b.sentSelKeys, ["1234567890"])

        # client A 切到大易選字鍵後，client B 的快取不能跟著變
        a.candselKeys = "␣'[]-\\"
        self.assertEqual(b.candselKeys, "1234567890")

    def test_no_shared_cache_on_singleton(self):
        # 共享單例上不可再存有 candselKeys（曾造成大易選字符顯示 12345）
        self.assertFalse(hasattr(self.cinbase, "candselKeys"))

    def test_fresh_dayi_client_resends_dayi_selkeys(self):
        """模擬曾出問題的情境：client A 已是大易選字鍵，新連上的 client B
        從預設值出發，必定觸發重送。"""
        a = FakeClient()
        self.cinbase.initTextService(a, FakeTextService)
        a.candselKeys = "␣'[]-\\"  # A 已切到大易選字鍵

        b = FakeClient()
        self.cinbase.initTextService(b, FakeTextService)
        # B 的快取仍是預設，所以大易組字時 candselKeys != "␣'[]-\" 會重送
        self.assertNotEqual(b.candselKeys, "␣'[]-\\")


class SelKeysManagerTests(unittest.TestCase):
    """selkeys 模組是選字鍵切換的唯一入口：只在實際變更時送 setSelKeys。"""

    def setUp(self):
        from cinbase import selkeys
        self.selkeys = selkeys
        self.cbTS = FakeClient()
        self.cbTS.TextService = FakeTextService
        self.cbTS.isSelKeysChanged = False
        self.selkeys.initSelKeys(self.cbTS)

    def test_init_sends_default_keys(self):
        self.assertEqual(self.cbTS.candselKeys, "1234567890")
        self.assertEqual(self.cbTS.sentSelKeys, ["1234567890"])

    def test_switch_to_dayi_sends_once(self):
        changed = self.selkeys.applyDayiSelKeys(self.cbTS)

        self.assertTrue(changed)
        self.assertEqual(self.cbTS.selKeys, "'[]-\\")
        self.assertEqual(self.cbTS.candselKeys, "␣'[]-\\")
        self.assertEqual(self.cbTS.sentSelKeys, ["1234567890", "␣'[]-\\"])
        self.assertTrue(self.cbTS.isSelKeysChanged)

    def test_repeated_apply_is_idempotent(self):
        self.selkeys.applyDayiSelKeys(self.cbTS)
        self.cbTS.isSelKeysChanged = False

        changed = self.selkeys.applyDayiSelKeys(self.cbTS)

        self.assertFalse(changed)
        # 不重送、不重設變更旗標，但顯示用 selKeys 仍維持正確
        self.assertEqual(len(self.cbTS.sentSelKeys), 2)
        self.assertFalse(self.cbTS.isSelKeysChanged)
        self.assertEqual(self.cbTS.selKeys, "'[]-\\")

    def test_round_trip_dayi_menu_dayi(self):
        # 大易組字 → 功能選單（數字鍵）→ 回到組字
        self.selkeys.applyDayiSelKeys(self.cbTS)
        self.assertTrue(self.selkeys.applyDefaultSelKeys(self.cbTS))
        self.assertEqual(self.cbTS.selKeys, "1234567890")
        self.assertTrue(self.selkeys.applyDayiSelKeys(self.cbTS))
        self.assertEqual(
            self.cbTS.sentSelKeys,
            ["1234567890", "␣'[]-\\", "1234567890", "␣'[]-\\"])

    def test_two_clients_do_not_share_state(self):
        other = FakeClient()
        other.TextService = FakeTextService
        other.isSelKeysChanged = False
        self.selkeys.initSelKeys(other)

        self.selkeys.applyDayiSelKeys(self.cbTS)

        # 另一個 client 的快取不受影響，切換時必定重送
        self.assertEqual(other.candselKeys, "1234567890")
        self.assertTrue(self.selkeys.applyDayiSelKeys(other))


class CandPerPageClampTests(unittest.TestCase):
    def setUp(self):
        import cinbase
        self.cinbase = cinbase.CinBase

    def test_dayi_page_limited_to_six_keys(self):
        # 大易候選選字鍵為「␣'[]-\」共 6 鍵
        self.assertEqual(self.cinbase.maxCandPerPage("chedayi"), 6)

    def test_other_imes_limited_to_ten_keys(self):
        for ime in ("checj", "chearray", "cheliu", "chephonetic", "chepinyin"):
            self.assertEqual(self.cinbase.maxCandPerPage(ime), 10)


if __name__ == "__main__":
    unittest.main()
