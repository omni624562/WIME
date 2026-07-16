import importlib.util
import os
import sys
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


def load_ime_module(ime_dir, filename):
    name = "%s_for_init_order_test" % ime_dir
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(PYTHON_DIR, "input_methods", ime_dir, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class DummyClient:
    isWindows8Above = True
    isMetroApp = False
    isUiLess = False
    isConsole = False


class DayiSymbolsInitTests(unittest.TestCase):
    """回歸測試：useDayiSymbols 必須在 initCinBaseContext 之前設定。

    曾發生 chedayi 在 super().__init__() 之後才設 useDayiSymbols = True，
    導致 initCinBaseContext 跳過 dsymbols 載入，使用者按 "=" 輸入大易
    標點符號時後端直接丟 AttributeError，完全無法輸入標點。
    """

    def make_service(self, mod, cls_name):
        # 不真的載入大易碼表與詞庫（多 MB JSON 且開背景執行緒），
        # 只驗證 __init__ 流程本身
        with mock.patch("cinbase.ime_base.LoadCinTable"), \
             mock.patch("cinbase.LoadPhraseData"):
            return getattr(mod, cls_name)(DummyClient())

    def test_chedayi_dsymbols_loaded_on_init(self):
        mod = load_ime_module("chedayi", "chedayi_ime.py")
        svc = self.make_service(mod, "CheDayiTextService")
        self.assertTrue(svc.useDayiSymbols)
        self.assertEqual(svc.selDayiSymbolCharType, 0)
        self.assertTrue(hasattr(svc, "dsymbols"),
                        "dsymbols 未載入：useDayiSymbols 設定時機晚於 initCinBaseContext")
        self.assertTrue(svc.dsymbols.isInCharDef("!"))

    def test_checj_has_no_dsymbols(self):
        mod = load_ime_module("checj", "checj_ime.py")
        svc = self.make_service(mod, "CheCJTextService")
        self.assertFalse(svc.useDayiSymbols)
        self.assertFalse(hasattr(svc, "dsymbols"))


if __name__ == "__main__":
    unittest.main()
