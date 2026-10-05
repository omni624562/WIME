"""大易/酷倉的系統匣輸入模式圖示（windows-mode-icon）：Win10/11 預設不顯示語言列，
這個圖示和它的右鍵選單是唯一看得到、點得到的狀態。
Driven through handleRequest with the real tables (cinbase_harness).
"""

import unittest

import cinbase_harness as h
from cinbase import ID_MODE_ICON, CHINESE_MODE
from textService import COMMAND_LEFT_CLICK, COMMAND_RIGHT_CLICK

IMES = ("chedayi", "checj")


def setUpModule():
    global _appdata
    _appdata = h.IsolatedAppData()


def tearDownModule():
    _appdata.close()


def activate(ime="chedayi", **config):
    service = h.make_service(ime, user_config=config or None)
    reply = h.request(service, "onActivate", isKeyboardOpen=True)
    return service, reply


@h.requires_tables
class ModeIconClickTests(unittest.TestCase):
    def test_right_click_does_not_toggle(self):
        # onMenu 失敗時 C++ 端把右鍵改成 onCommand(COMMAND_RIGHT_CLICK) 送來：
        # 以前照樣切換中英文，右鍵一下就默默變成英文
        for ime in IMES:
            with self.subTest(ime=ime):
                service, _ = activate(ime)
                reply = h.request(service, "onCommand", id=ID_MODE_ICON, type=COMMAND_RIGHT_CLICK)
                self.assertEqual(service.langMode, CHINESE_MODE)
                self.assertNotIn("changeButton", reply)

    def test_left_click_toggles(self):
        for ime in IMES:
            with self.subTest(ime=ime):
                service, _ = activate(ime)
                h.request(service, "onCommand", id=ID_MODE_ICON, type=COMMAND_LEFT_CLICK)
                self.assertNotEqual(service.langMode, CHINESE_MODE)


if __name__ == "__main__":
    unittest.main()
