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
