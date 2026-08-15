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


class SyncLoadFallbackTests(unittest.TestCase):
    """回歸測試：碼表首次載入採同步；若同步載入失敗（檔案缺失/損毀/被鎖，
    LoadCinTable.run() 內部吞例外並使 self.cin 留在 None），__init__ 不得
    崩潰，且須回退為非同步 .start() 重載，避免停在「無碼表卻不重試」。
    """

    def test_sync_failure_falls_back_to_async(self):
        mod = load_ime_module("chedayi", "chedayi_ime.py")
        # LoadCinTable 被 mock：run() 為 no-op（不設 self.cin，模擬失敗）。
        with mock.patch("cinbase.ime_base.LoadCinTable") as MockLoad, \
             mock.patch("cinbase.LoadPhraseData"):
            svc = getattr(mod, "CheDayiTextService")(DummyClient())
            self.assertTrue(MockLoad.return_value.run.called,
                            "首次載入應先嘗試同步 run()")
            self.assertTrue(MockLoad.return_value.start.called,
                            "同步後 self.cin 仍為 None 時應回退非同步 start()")
        self.assertIsNone(getattr(svc, "cin", None))  # mock 未載入，仍為 None，但無崩潰


class CheckConfigChangeResilienceTests(unittest.TestCase):
    """回歸測試：碼表載入期間建立的實例沒有 cin 屬性，checkConfigChange
    不得丟 AttributeError（否則該實例每個請求都失敗、永久失效——
    使用者看到的症狀是輸入法「有時」完全沒反應，直到重新聚焦視窗）。
    """

    def test_missing_cin_attribute_self_heals(self):
        mod = load_ime_module("chedayi", "chedayi_ime.py")
        with mock.patch("cinbase.ime_base.LoadCinTable"), \
             mock.patch("cinbase.LoadPhraseData"):
            svc = getattr(mod, "CheDayiTextService")(DummyClient())
        if hasattr(svc, "cin"):
            del svc.cin

        # 讓 checkConfigChange 走「不需重載碼表」的 else 分支（出事的那條路）
        sentinel = object()
        mod.CinTable.loading = False
        mod.CinTable.cin = sentinel
        mod.CinTable.curCinType = svc.cfg.selCinType
        mod.CinTable.ignorePrivateUseArea = svc.cfg.ignorePrivateUseArea
        mod.CinTable.userExtendTable = svc.cfg.userExtendTable
        mod.CinTable.priorityExtendTable = svc.cfg.priorityExtendTable
        svc.cfg.reLoadTable = False
        svc.cfg.imeReverseLookup = False
        svc.imeReverseLookup = False
        svc.cfg.homophoneQuery = False
        svc.homophoneQuery = False

        with mock.patch("cinbase.LoadRCinTable"), mock.patch("cinbase.LoadHCinTable"):
            svc.checkConfigChange()  # 修復前這裡直接 AttributeError

        self.assertIs(svc.cin, sentinel, "checkConfigChange 應把共享碼表回填給實例")


if __name__ == "__main__":
    unittest.main()
