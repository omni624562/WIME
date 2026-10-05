"""新酷音's taskbar mode icon (windows-mode-icon) and its right-click menu, with
the real libchewing (see chewing_harness).

- A right click toggled 中/英 when the menu could not be shown: the C++ side
  then sends the click as onCommand(ID_MODE_ICON, COMMAND_RIGHT_CLICK).
- The tooltip was always 「中英文切換」, and nothing on the taskbar showed 全形:
  it now names the IME and the state, and follows Shift+Space.
- A closed keyboard only disabled the icon, which kept showing 中.
"""

import os
import unittest

import cinbase_harness

_appdata = None
ch = None
module = None

CHINESE, ENGLISH = 1, 0
LEFT_CLICK, RIGHT_CLICK, MENU = 0, 1, 2


def setUpModule():
    global _appdata, ch, module
    _appdata = cinbase_harness.IsolatedAppData()
    import chewing_harness
    ch = chewing_harness
    module = ch.load_module()


def tearDownModule():
    ch.close_all()
    _appdata.close()


class ChewingTestCase(unittest.TestCase):
    def service(self, **overrides):
        override = ch.ConfigOverride(**overrides)
        self.addCleanup(override.restore)
        return ch.make_service()

    def tearDown(self):
        ch.close_all()

    def click(self, s, command_type=LEFT_CLICK, command=None):
        return ch.request(s, "onCommand", id=module.ID_MODE_ICON if command is None else command,
                          type=command_type)


def mode_icon(reply, action="changeButton"):
    """the last windows-mode-icon entry of reply[action], or None"""
    entries = [entry for entry in reply.get(action, []) if entry.get("id") == "windows-mode-icon"]
    return entries[-1] if entries else None


def icon_name(entry):
    return entry["icon"].rsplit("\\", 1)[-1]


class ModeIconTooltipTests(ChewingTestCase):
    """The tooltip was always 「中英文切換」: it said what a click does, not the state,
    and Shift+Space only changed the language bar's 全/半形 button, which Windows
    10/11 do not show - the mode icon has no full-width look of its own."""

    def activate(self, **overrides):
        override = ch.ConfigOverride(**overrides)
        self.addCleanup(override.restore)
        s = module.ChewingTextService(ch.DummyClient())
        ch._services.append(s)  # deactivated in tearDown
        return s, ch.request(s, "onActivate", isKeyboardOpen=True)

    def test_tooltip_on_activation(self):
        s, reply = self.activate()
        icon = mode_icon(reply, "addButton")
        self.assertEqual(icon["tooltip"], "新酷音：中文、半形（按一下切換中英文）")
        self.assertEqual(icon_name(icon), "traC.ico")
        s, reply = self.activate(defaultEnglish=True, defaultFullSpace=True)
        icon = mode_icon(reply, "addButton")
        self.assertEqual(icon["tooltip"], "新酷音：英文、全形（按一下切換中英文）")
        self.assertEqual(icon_name(icon), "eng.ico")

    def test_shift_space_updates_the_mode_icon(self):
        s = self.service(enableShiftSpace=True)
        reply = ch.request(s, "onPreservedKey", guid=module.SHIFT_SPACE_GUID)
        self.assertEqual(mode_icon(reply)["tooltip"], "新酷音：中文、全形（按一下切換中英文）")  # no change before
        reply = ch.request(s, "onPreservedKey", guid=module.SHIFT_SPACE_GUID)
        self.assertEqual(mode_icon(reply)["tooltip"], "新酷音：中文、半形（按一下切換中英文）")

    def test_language_changes_update_the_tooltip(self):
        s = self.service()
        reply = self.click(s)
        self.assertEqual(mode_icon(reply)["tooltip"], "新酷音：英文、半形（按一下切換中英文）")
        self.assertEqual(icon_name(mode_icon(reply)), "eng.ico")
        ch.request(s, "filterKeyDown", **ch.key_event("SHIFT"))  # a Shift tap: back to Chinese
        reply = ch.request(s, "filterKeyUp", **ch.key_event("SHIFT", down=False))
        self.assertEqual(s.chewingContext.get_ChiEngMode(), CHINESE)
        self.assertEqual(mode_icon(reply)["tooltip"], "新酷音：中文、半形（按一下切換中英文）")

    def test_caps_lock(self):
        for enabled, icon, tooltip in ((True, "capsEng.ico", "新酷音：英文（CapsLock）、半形（按一下切換中英文）"),
                                       (False, "traC.ico", "新酷音：中文、半形（按一下切換中英文）")):
            with self.subTest(enableCapsLock=enabled):
                s = self.service(enableCapsLock=enabled)
                s.getCapslockState = lambda: True
                s.updateSwitchLangIcon = True  # what releasing CapsLock does (filterKeyUp)
                s.updateLangButtons()
                entry = mode_icon(s.currentReply)
                s.currentReply = {}
                # without 使用 CapsLock 切換中英文模式, CapsLock does not switch to English:
                # the icon used to show it anyway
                self.assertEqual((icon_name(entry), entry["tooltip"]), (icon, tooltip))


class KeyboardClosedTests(ChewingTestCase):
    """With the keyboard closed (Ctrl+Space, 預設以停用輸入法模式啟動) the mode icon
    was only disabled: it still showed 中, input was English, and a click could
    not open the keyboard (Ctrl+Space was the only way, and nothing said so)."""

    CLOSED = ("eng.ico", "新酷音：已關閉（按一下或按 Ctrl+空白鍵開啟）")

    def state(self, entry):
        return icon_name(entry), entry["tooltip"]

    def test_closed_keyboard_shows_it_and_a_click_reopens(self):
        s = self.service()
        reply = ch.request(s, "onKeyboardStatusChanged", opened=False)
        self.assertEqual(self.state(mode_icon(reply)), self.CLOSED)  # still traC.ico before
        self.assertIs(mode_icon(reply)["enable"], True)  # False before
        reply = self.click(s)
        self.assertIs(reply.get("openKeyboard"), True)  # nothing before
        # the C++ side opens the keyboard and reports it
        reply = ch.request(s, "onKeyboardStatusChanged", opened=True)
        self.assertEqual(self.state(mode_icon(reply)), ("traC.ico", "新酷音：中文、半形（按一下切換中英文）"))
        self.assertEqual("".join(ch.type_keys(s, list("su3") + ["ENTER"])[0]), "你")  # still Chinese

    def test_reopening_keeps_the_modes(self):
        s = self.service(enableShiftSpace=True)
        self.click(s)  # English
        ch.request(s, "onPreservedKey", guid=module.SHIFT_SPACE_GUID)  # full width
        ch.request(s, "onKeyboardStatusChanged", opened=False)
        self.click(s)
        reply = ch.request(s, "onKeyboardStatusChanged", opened=True)
        self.assertEqual(self.state(mode_icon(reply)), ("eng.ico", "新酷音：英文、全形（按一下切換中英文）"))

    def test_disabled_on_startup(self):
        override = ch.ConfigOverride(disableOnStartup=True)
        self.addCleanup(override.restore)
        s = module.ChewingTextService(ch.DummyClient())
        ch._services.append(s)
        reply = ch.request(s, "onActivate", isKeyboardOpen=True)
        self.assertIs(reply.get("openKeyboard"), False)
        # when the keyboard was closed already, no onKeyboardStatusChanged follows
        self.assertEqual(self.state(mode_icon(reply, "addButton")), self.CLOSED)
        self.assertIs(self.click(s).get("openKeyboard"), True)

    def test_settings_page_says_how_to_open_it(self):
        with open(os.path.join(ch.PYTHON_DIR, "input_methods", "chewing", "config_tool.html"),
                  encoding="utf-8-sig") as f:
            page = f.read()
        self.assertRegex(page, r'for="disableOnStartup">[^<]*</label>\s*<div class="setting-hint">[^<]*'
                               r'<kbd>Ctrl</kbd>\+<kbd>空白鍵</kbd>[^<]*輸入法圖示')


class ModeIconClickTests(ChewingTestCase):
    def test_only_a_left_click_toggles_the_language(self):
        s = self.service()
        for command_type in (RIGHT_CLICK, MENU):
            with self.subTest(command_type=command_type):
                self.click(s, command_type)
                self.assertEqual(s.chewingContext.get_ChiEngMode(), CHINESE)  # English before
        self.click(s)
        self.assertEqual(s.chewingContext.get_ChiEngMode(), ENGLISH)
        self.click(s)
        self.assertEqual(s.chewingContext.get_ChiEngMode(), CHINESE)


if __name__ == "__main__":
    unittest.main()
