"""新酷音's taskbar mode icon (windows-mode-icon) and its right-click menu, with
the real libchewing (see chewing_harness).

- A right click toggled 中/英 when the menu could not be shown: the C++ side
  then sends the click as onCommand(ID_MODE_ICON, COMMAND_RIGHT_CLICK).
"""

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
