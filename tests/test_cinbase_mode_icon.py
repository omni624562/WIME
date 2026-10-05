"""大易/酷倉的系統匣輸入模式圖示（windows-mode-icon）：Win10/11 預設不顯示語言列，
這個圖示和它的右鍵選單是唯一看得到、點得到的狀態。
Driven through handleRequest with the real tables (cinbase_harness).
"""

import unittest

import cinbase_harness as h
from cinbase import ID_MODE_ICON, CHINESE_MODE, SHIFT_SPACE_GUID
from textService import COMMAND_LEFT_CLICK, COMMAND_RIGHT_CLICK

IMES = ("chedayi", "checj")
NAMES = {"chedayi": "大易", "checj": "酷倉"}


def setUpModule():
    global _appdata
    _appdata = h.IsolatedAppData()


def tearDownModule():
    _appdata.close()


def activate(ime="chedayi", **config):
    service = h.make_service(ime, user_config=config or None)
    reply = h.request(service, "onActivate", isKeyboardOpen=True)
    return service, reply


def mode_icon(reply, action):
    """The last windows-mode-icon entry of reply[action] ("addButton"/"changeButton")."""
    buttons = [b for b in reply.get(action, []) if b["id"] == "windows-mode-icon"]
    return buttons[-1] if buttons else None


@h.requires_tables
class ModeIconTooltipTests(unittest.TestCase):
    """大易、酷倉用同一組圖示，提示以前固定是「中英文切換」：看不出是哪個輸入法，
    也看不出現在的狀態（全形只是圖示右半邊不是灰色）。"""

    def test_tooltip_names_the_ime_and_its_state(self):
        for ime in IMES:
            with self.subTest(ime=ime):
                service, reply = activate(ime)
                self.assertEqual(mode_icon(reply, "addButton")["tooltip"],
                                 NAMES[ime] + "：中文、半形（按一下切換中英文）")

                reply = h.request(service, "onCommand", id=ID_MODE_ICON, type=COMMAND_LEFT_CLICK)
                icon = mode_icon(reply, "changeButton")
                self.assertEqual(icon["tooltip"], NAMES[ime] + "：英文、半形（按一下切換中英文）")
                self.assertTrue(icon["icon"].endswith("eng_half_capsoff.ico") or
                                icon["icon"].endswith("eng_half_capson.ico"), icon["icon"])

                reply = h.request(service, "onPreservedKey", guid=SHIFT_SPACE_GUID)
                self.assertEqual(mode_icon(reply, "changeButton")["tooltip"],
                                 NAMES[ime] + "：英文、全形（按一下切換中英文）")

    def test_shift_updates_the_tooltip(self):
        service, _ = activate()
        down, up = h.press_replies(service, "SHIFT")
        self.assertEqual(mode_icon(up, "changeButton")["tooltip"], "大易：英文、半形（按一下切換中英文）")

    def test_display_name_setting_is_used(self):
        service, reply = activate(imeDisplayName="易")
        self.assertEqual(mode_icon(reply, "addButton")["tooltip"], "易：中文、半形（按一下切換中英文）")


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
