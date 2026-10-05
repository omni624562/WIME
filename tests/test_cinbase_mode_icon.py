"""大易/酷倉的系統匣輸入模式圖示（windows-mode-icon）：Win10/11 預設不顯示語言列，
這個圖示和它的右鍵選單是唯一看得到、點得到的狀態。
Driven through handleRequest with the real tables (cinbase_harness).
"""

import unittest

import cinbase_harness as h
from cinbase import ID_MODE_ICON, ID_SWITCH_LANG, ID_SWITCH_SHAPE, SHIFT_SPACE_GUID
from cinbase import CHINESE_MODE, ENGLISH_MODE, FULLSHAPE_MODE, HALFSHAPE_MODE
from textService import COMMAND_LEFT_CLICK, COMMAND_MENU, COMMAND_RIGHT_CLICK

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
        reply = h.request(service, "onCommand", id=ID_SWITCH_SHAPE, type=COMMAND_LEFT_CLICK)
        self.assertOffIcon(mode_icon(reply, "changeButton"))


@h.requires_tables
class ModeMenuTests(unittest.TestCase):
    """Win10/11 預設不顯示語言列，右鍵選單以前沒有中英、全半形的項目：
    不小心按到 Shift+空白鍵變成全形後，只能再按一次快速鍵切回來。"""

    def mode_items(self, service, button="windows-mode-icon"):
        menu = h.request(service, "onMenu", id=button)["return"]
        return {item["id"]: item for item in menu[:2]}, menu[2]

    def test_items_show_the_current_state(self):
        for ime in IMES:
            with self.subTest(ime=ime):
                service, _ = activate(ime)
                for button in ("windows-mode-icon", "settings"):
                    items, separator = self.mode_items(service, button)
                    self.assertEqual(separator, {})
                    self.assertEqual(items[ID_SWITCH_LANG]["text"], "中文模式（Shift）")
                    self.assertIs(items[ID_SWITCH_LANG]["checked"], True)
                    self.assertEqual(items[ID_SWITCH_SHAPE]["text"], "全形（Shift+空白鍵）")
                    self.assertIs(items[ID_SWITCH_SHAPE]["checked"], False)

    def test_selecting_the_items(self):
        # 選單項目以 COMMAND_MENU 送來（以前只接受語言列按鈕的左鍵）
        for ime in IMES:
            with self.subTest(ime=ime):
                service, _ = activate(ime)
                reply = h.request(service, "onCommand", id=ID_SWITCH_SHAPE, type=COMMAND_MENU)
                self.assertEqual(service.shapeMode, FULLSHAPE_MODE)
                self.assertIn("全形", mode_icon(reply, "changeButton")["tooltip"])
                self.assertIs(self.mode_items(service)[0][ID_SWITCH_SHAPE]["checked"], True)

                h.request(service, "onCommand", id=ID_SWITCH_LANG, type=COMMAND_MENU)
                self.assertEqual(service.langMode, ENGLISH_MODE)
                self.assertIs(self.mode_items(service)[0][ID_SWITCH_LANG]["checked"], False)

                h.request(service, "onCommand", id=ID_SWITCH_SHAPE, type=COMMAND_MENU)
                h.request(service, "onCommand", id=ID_SWITCH_LANG, type=COMMAND_MENU)
                self.assertEqual((service.langMode, service.shapeMode), (CHINESE_MODE, HALFSHAPE_MODE))

    def test_right_click_on_the_language_bar_buttons_does_nothing(self):
        service, _ = activate()
        h.request(service, "onCommand", id=ID_SWITCH_LANG, type=COMMAND_RIGHT_CLICK)
        h.request(service, "onCommand", id=ID_SWITCH_SHAPE, type=COMMAND_RIGHT_CLICK)
        self.assertEqual((service.langMode, service.shapeMode), (CHINESE_MODE, HALFSHAPE_MODE))

    def test_chinese_item_reopens_a_closed_keyboard(self):
        service, _ = activate(defaultEnglish=True)
        h.request(service, "onKeyboardStatusChanged", opened=False)
        self.assertIs(self.mode_items(service)[0][ID_SWITCH_LANG]["checked"], False)
        reply = h.request(service, "onCommand", id=ID_SWITCH_LANG, type=COMMAND_MENU)
        self.assertIs(reply.get("openKeyboard"), True)
        self.assertEqual(service.langMode, CHINESE_MODE)
        self.assertIs(self.mode_items(service)[0][ID_SWITCH_LANG]["checked"], True)

    def test_closed_keyboard_unchecks_chinese(self):
        service, _ = activate()
        h.request(service, "onKeyboardStatusChanged", opened=False)
        self.assertIs(self.mode_items(service)[0][ID_SWITCH_LANG]["checked"], False)

    def test_shortcut_hints_follow_the_settings(self):
        cases = [
            ({"switchLangWithShift": False}, "中文模式", "全形（Shift+空白鍵）"),
            ({"switchLangWithWhichShift": 1}, "中文模式（左 Shift）", "全形（Shift+空白鍵）"),
            ({"switchLangWithWhichShift": 2}, "中文模式（右 Shift）", "全形（Shift+空白鍵）"),
            ({"enableShiftSpace": False}, "中文模式（Shift）", "全形"),
        ]
        for config, lang_text, shape_text in cases:
            with self.subTest(config=config):
                service, _ = activate(**config)
                items, _ = self.mode_items(service)
                self.assertEqual(items[ID_SWITCH_LANG]["text"], lang_text)
                self.assertEqual(items[ID_SWITCH_SHAPE]["text"], shape_text)


if __name__ == "__main__":
    unittest.main()
