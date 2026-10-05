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

    def test_settings_applied_before_activation_do_not_override_the_icon(self):
        # 建立時（initCinBaseContext、applyConfig）就送的 changeButton 會跟著
        # onActivate 的回覆送出，C++ 端套用在 addButton 之後。那時 keyboardOpen 還是
        # TextService 預設的 False，不能因此把圖示蓋成停用
        service = h.make_service("chedayi")
        h.cinbase.CinBase.applyConfig(service)
        reply = h.request(service, "onActivate", isKeyboardOpen=True)
        added = mode_icon(reply, "addButton")
        changed = mode_icon(reply, "changeButton")
        if changed is not None:
            self.assertEqual((changed["icon"], changed["tooltip"]), (added["icon"], added["tooltip"]))

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


@h.requires_tables
class ClosedKeyboardTests(unittest.TestCase):
    """鍵盤關閉（Ctrl+空白鍵、「預設以停用輸入法模式啟動」）時，以前只把圖示設成
    disabled：照樣顯示「中」，點了也只是在中、英之間切換，鍵盤不會重新開啟。"""

    def assertOffIcon(self, icon, ime="chedayi"):
        self.assertIsNotNone(icon)
        self.assertTrue(icon["icon"].endswith("eng_half_capsoff.ico"), icon["icon"])
        self.assertEqual(icon["tooltip"], NAMES[ime] + "：已停用（按一下或 Ctrl+空白鍵開啟）")
        self.assertNotEqual(icon.get("enable"), False)

    def test_closing_shows_the_off_state(self):
        for ime in IMES:
            with self.subTest(ime=ime):
                service, _ = activate(ime)
                reply = h.request(service, "onKeyboardStatusChanged", opened=False)
                self.assertOffIcon(mode_icon(reply, "changeButton"), ime)

                reply = h.request(service, "onKeyboardStatusChanged", opened=True)
                icon = mode_icon(reply, "changeButton")
                self.assertTrue(icon["icon"].endswith("chi_half_capsoff.ico") or
                                icon["icon"].endswith("chi_half_capson.ico"), icon["icon"])
                self.assertEqual(icon["tooltip"], NAMES[ime] + "：中文、半形（按一下切換中英文）")

    def test_click_reopens_the_keyboard(self):
        for ime in IMES:
            with self.subTest(ime=ime):
                service, _ = activate(ime)
                h.request(service, "onKeyboardStatusChanged", opened=False)
                reply = h.request(service, "onCommand", id=ID_MODE_ICON, type=COMMAND_LEFT_CLICK)
                self.assertIs(reply.get("openKeyboard"), True)
                self.assertTrue(service.keyboardOpen)
                self.assertEqual(service.langMode, CHINESE_MODE)
                self.assertIn("中文", mode_icon(reply, "changeButton")["tooltip"])
                # C++ 端套用 openKeyboard 後送來的通知不會再切換一次
                h.request(service, "onKeyboardStatusChanged", opened=True)
                self.assertEqual(service.langMode, CHINESE_MODE)

    def test_click_reopens_in_english_with_default_english(self):
        # 重新開啟和 Ctrl+空白鍵一樣回到中文（defaultEnglish 時留在英文）
        service, _ = activate(defaultEnglish=True)
        self.assertNotEqual(service.langMode, CHINESE_MODE)
        h.request(service, "onKeyboardStatusChanged", opened=False)
        reply = h.request(service, "onCommand", id=ID_MODE_ICON, type=COMMAND_LEFT_CLICK)
        self.assertIs(reply.get("openKeyboard"), True)
        self.assertNotEqual(service.langMode, CHINESE_MODE)

    def test_disabled_at_startup(self):
        service, reply = activate(disableOnStartup=True)
        self.assertIs(reply.get("openKeyboard"), False)
        self.assertOffIcon(mode_icon(reply, "addButton"))
        reply = h.request(service, "onCommand", id=ID_MODE_ICON, type=COMMAND_LEFT_CLICK)
        self.assertIs(reply.get("openKeyboard"), True)
        self.assertEqual(service.langMode, CHINESE_MODE)

    def test_shape_toggle_while_closed_keeps_the_off_icon(self):
        service, _ = activate()
        h.request(service, "onKeyboardStatusChanged", opened=False)
        reply = h.request(service, "onCommand", id=h.cinbase.ID_SWITCH_SHAPE, type=COMMAND_LEFT_CLICK)
        self.assertOffIcon(mode_icon(reply, "changeButton"))


if __name__ == "__main__":
    unittest.main()
