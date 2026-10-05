"""新酷音 keystroke behaviour with the real libchewing (see chewing_harness).

Covers the audit findings in the keystroke path:
- the modern candidate window style types like classic 新酷音 (continuous phrase
  input, inline composition, candidates only on Down/Space) - it used to open the
  candidate list after every syllable, so tone keys picked candidates (你是 -> 禰),
- keys that reach the candidate-window code while only a bopomofo is pending
  (the window is open but the list is empty): Enter, End, Ctrl+Del,
- the candidate cursor after the list changes in the "paging" configurations,
- Ctrl/Alt shortcuts during composition, non-ASCII characters,
- 中/英 toggling with a pending bopomofo, Ctrl+Shift, left/right Shift,
- Shift+Space when its toggle is disabled,
- the half-width punctuation option on layouts that type bopomofo with = [ '.
"""

import contextlib
import unittest

import cinbase_harness

_appdata = None
ch = None


def setUpModule():
    global _appdata, ch
    _appdata = cinbase_harness.IsolatedAppData()
    import chewing_harness
    ch = chewing_harness
    ch.load_module()


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

    def type(self, service, keys):
        commits, _ = ch.type_keys(service, keys)
        return "".join(commits)

    def bopomofo(self, service):
        ctx = service.chewingContext
        return ctx.bopomofo_String(None).decode("utf-8") if ctx.bopomofo_Check() else ""


class TypingTests(ChewingTestCase):
    def test_continuous_phrase_input(self):
        s = self.service()
        self.assertEqual(self.type(s, list("5j/") + ["SPACE"] + list("jp6") + ["ENTER"]), "中文")
        self.assertEqual(self.type(s, list("ji3ap7") + ["ENTER"]), "我們")
        # 3/4/6/7 are tones, not selection keys: 你 + ㄨㄛˋ used to commit 禰
        self.assertEqual(self.type(s, list("su3ji4") + ["ENTER"]), "你握")

    def test_composition_is_inline_and_no_candidates_until_asked(self):
        s = self.service()
        self.type(s, list("su3"))
        self.assertEqual(s.compositionString, "你")  # not a zero-width space
        self.assertFalse(s.showCandidates)
        self.assertEqual(s.candidateList, [])
        self.type(s, ["DOWN"])
        self.assertTrue(s.showCandidates)
        self.assertEqual(s.candidateList[0], "你")
        self.type(s, ["2"])  # pick the 2nd candidate; it stays in the composition
        self.assertEqual(s.compositionString, "妳")
        self.assertFalse(s.showCandidates)
        self.assertEqual(self.type(s, ["ENTER"]), "妳")

    def test_backspace_deletes(self):
        s = self.service()
        self.type(s, list("su3") + ["BACK"])
        self.assertEqual(s.compositionString, "")
        self.assertFalse(s.isComposing())


class EmptyCandidateWindowTests(ChewingTestCase):
    """Only a bopomofo is pending: the window shows it, but the list is empty."""

    def test_enter_does_not_type_a_selection_key(self):
        s = self.service()
        self.type(s, ["s"])
        self.assertTrue(s.showCandidates)
        self.assertEqual(s.candidateList, [])
        self.type(s, ["ENTER"])
        self.assertEqual(self.bopomofo(s), "ㄋ")  # used to become ㄅ (selKeys[0])
        self.assertEqual(self.type(s, list("u3") + ["ENTER"]), "你")

    def test_end_keeps_the_cursor_valid(self):
        s = self.service()
        self.type(s, ["s", "END"])
        self.assertGreaterEqual(s.candidateCursor, 0)  # used to be -1
        self.assertEqual(self.type(s, list("u3") + ["ENTER"]), "你")

    def test_ctrl_del_pgup_pgdn_do_not_raise(self):
        for key in ("DEL", "PGUP", "PGDN"):
            with self.subTest(key=key):
                s = self.service()
                self.type(s, ["s", (key, "C")])  # IndexError on candidateList[0] before


class CandidateCursorTests(ChewingTestCase):
    def assert_cursor_in_range(self, s):
        if s.candidateList:
            self.assertTrue(0 <= s.candidateCursor < len(s.candidateList),
                            (s.candidateCursor, s.candidateList))

    def test_cursor_reset_when_paging_with_left_right_and_up_down(self):
        s = self.service(leftRightAction=1, upDownAction=1)
        for key in list("su3") + ["SPACE", "END", "RIGHT", "RIGHT", "RIGHT"]:
            self.type(s, [key])
            self.assert_cursor_in_range(s)
        chosen = s.candidateList[s.candidateCursor]
        self.type(s, ["ENTER"])
        self.assertEqual(s.compositionString, chosen)  # Enter picks what is highlighted

    def test_up_down_move_by_a_visual_row(self):
        s = self.service(candidateLayout="horizontal", candidatePerRow=6, candPerPage=9)
        self.type(s, list("su3") + ["DOWN"])
        self.assertEqual(s.candidateCursor, 0)
        self.type(s, ["DOWN"])
        self.assertEqual(s.candidateCursor, 6)  # a row of the window holds candidatePerRow (6)
        self.type(s, ["UP"])
        self.assertEqual(s.candidateCursor, 0)

    def columns_shown(self, s):
        """Columns the candidate window gives this page (test_candidate_width's model of
        CandidateWindow::recalculateSize(), at the DPI the backend assumes)."""
        import candidate_layout
        import test_candidate_width
        cfg = ch.config()
        return test_candidate_width.page_columns(
            cfg.fontSize, cfg.candidatePerRow, cfg.getSelKeys(), s.candidateList, cfg.candidateKeyStyle,
            candidate_layout.systemDpi(), cfg.candidateMaxWidth,
            cfg.candidateStyle["contentMargin"], cfg.candidateStyle["textMargin"])

    def test_up_down_follow_the_columns_shown(self):
        # 9 to a row does not fit the default 最大寬度: the window shows 6 + 3
        s = self.service(candidateLayout="horizontal", candidatePerRow=9, candPerPage=9)
        self.type(s, list("su3") + ["DOWN"])
        columns = self.columns_shown(s)
        self.assertLess(columns, 9)
        self.type(s, ["DOWN"])
        self.assertEqual(s.candidateCursor, columns)  # did not move before
        self.type(s, ["UP"])
        self.assertEqual(s.candidateCursor, 0)

    def test_up_down_on_a_page_of_phrases(self):
        # two-character phrases are wider: 4 to a row with the default settings
        s = self.service(candidateLayout="horizontal", candidatePerRow=6, candPerPage=9)
        self.type(s, list("u4u4") + ["HOME", "DOWN"])
        self.assertEqual({len(candidate) for candidate in s.candidateList}, {2})
        columns = self.columns_shown(s)
        self.assertLess(columns, 6)
        self.type(s, ["DOWN"])
        self.assertEqual(s.candidateCursor, columns)  # 6 before: the next row, two columns right
        self.type(s, ["UP"])
        self.assertEqual(s.candidateCursor, 0)

    def test_down_into_a_shorter_last_row(self):
        s = self.service(candidateLayout="horizontal", candidatePerRow=6, candPerPage=9)
        self.type(s, list("su3") + ["DOWN"] + ["RIGHT"] * 4)
        self.assertEqual((self.columns_shown(s), len(s.candidateList), s.candidateCursor), (6, 9, 4))
        self.type(s, ["DOWN"])
        self.assertEqual(s.candidateCursor, 8)  # nothing under column 5: the last one (stayed at 4 before)
        self.type(s, ["UP"])
        self.assertEqual(s.candidateCursor, 2)

    def test_ctrl_del_with_the_list_open(self):
        s = self.service()
        self.type(s, list("su3") + ["DOWN", "END", ("DEL", "C")])
        self.assert_cursor_in_range(s)


class ShortcutKeyTests(ChewingTestCase):
    def test_ctrl_and_alt_letters_during_composition_go_to_the_app(self):
        s = self.service()
        self.type(s, list("su3"))
        for key in "cvzas":
            with self.subTest(key=key):
                down = ch.key_event(key, ctrl=True)
                self.assertFalse(ch.request(s, "filterKeyDown", **down).get("return"))
        alt_f = ch.key_event("f")
        alt_f["keyStates"]["18"] = 0x80  # VK_MENU
        self.assertFalse(ch.request(s, "filterKeyDown", **alt_f).get("return"))
        self.assertEqual(s.compositionString, "你")  # nothing was added (Ctrl+C used to add ㄏ)
        self.assertEqual(self.bopomofo(s), "")

    def test_ctrl_digit_still_adds_a_phrase(self):
        s = self.service()
        self.type(s, list("su3"))
        down = ch.key_event("1", ctrl=True)
        self.assertTrue(ch.request(s, "filterKeyDown", **down).get("return"))

    def test_non_ascii_characters_pass_through(self):
        s = self.service()
        for char in "éß€":
            down = ch.key_event("a")
            down["charCode"] = ord(char)
            with self.subTest(char=char):
                self.assertFalse(ch.request(s, "filterKeyDown", **down).get("return"))


class LanguageToggleTests(ChewingTestCase):
    def test_shift_tap_with_a_pending_bopomofo_closes_the_root_window(self):
        s = self.service()
        self.type(s, ["s", "SHIFT"])
        self.assertEqual(s.langMode, 0)  # English
        self.assertFalse(s.showCandidates)
        self.assertEqual(s.compositionString, "")
        self.assertFalse(s.isComposing())
        self.assertEqual(self.type(s, ["ENTER"]), "")  # used to commit "1"

    def test_shift_tap_keeps_composed_text(self):
        s = self.service()
        self.type(s, list("su3") + ["s", "SHIFT"])
        self.assertEqual(s.compositionString, "你")
        self.assertFalse(s.showCandidates)

    def test_mode_icon_click_with_a_pending_bopomofo(self):
        s = self.service()
        self.type(s, ["s"])
        ch.request(s, "onCommand", id=4, type=0)  # ID_MODE_ICON, left click
        self.assertEqual(s.langMode, 0)
        # the command reply has no edit session; the next key updates the screen
        down = ch.key_event("ENTER")
        if ch.request(s, "filterKeyDown", **down).get("return"):
            reply = ch.request(s, "onKeyDown", **down)
            self.assertFalse(reply.get("return"))  # Enter goes to the app
            self.assertEqual(reply.get("compositionString"), "")
        self.assertFalse(s.isComposing())

    def test_ctrl_shift_and_alt_shift_do_not_toggle(self):
        s = self.service()
        self.type(s, [("SHIFT", "C")])
        self.assertEqual(s.langMode, 1)
        down, up = ch.key_event("SHIFT"), ch.key_event("SHIFT", down=False)
        for event in (down, up):
            event["keyStates"]["18"] = 0x80  # Alt held
        ch.request(s, "filterKeyDown", **down)
        ch.request(s, "filterKeyUp", **up)
        self.assertEqual(s.langMode, 1)

    def shift_tap(self, s, scan_code):
        down, up = ch.key_event("SHIFT"), ch.key_event("SHIFT", down=False)
        down["scanCode"] = up["scanCode"] = scan_code
        ch.request(s, "filterKeyDown", **down)
        if ch.request(s, "filterKeyUp", **up).get("return"):
            ch.request(s, "onKeyUp", **up)

    def test_only_the_configured_shift_side_toggles(self):
        module = ch.load_module()
        s = self.service(switchLangWithWhichShift=1)  # left Shift only
        s.isPressed = lambda vk: True  # the unreliable GetAsyncKeyState fallback must not decide
        self.shift_tap(s, module.RIGHT_SHIFT_SCAN_CODE)
        self.assertEqual(s.langMode, 1)
        self.shift_tap(s, module.LEFT_SHIFT_SCAN_CODE)
        self.assertEqual(s.langMode, 0)


class HalfShapeSymbolKeyTests(ChewingTestCase):
    """非注音符號對應鍵輸出全形標點 off: the = [ \\ ] ' keys type half-width
    punctuation, except where the keyboard layout types bopomofo with them -
    精業 (=[' ㄦㄤㄥ), 倚天 41 鍵 (=' ㄦㄘ), DVORAK ([' ㄦㄆ). Those used to type the
    ASCII symbol as well, and the rest of the syllable became another character."""

    SYMBOL_KEYS = "=[\\]'"

    @contextlib.contextmanager
    def layout_service(self, layout, full_shape):
        override = ch.ConfigOverride(keyboardLayout=layout, fullShapeSymbols=full_shape)
        try:
            yield ch.make_service()
        finally:
            ch.close_all()  # one libchewing context at a time
            override.restore()

    def symbol_keys(self, layout, full_shape):
        """{key: (pending bopomofo, committed text)} for each key pressed on its own"""
        results = {}
        with self.layout_service(layout, full_shape) as s:
            for key in self.SYMBOL_KEYS:
                commits = self.type(s, [key])
                results[key] = (self.bopomofo(s), commits)
                self.type(s, ["ESC"])
                self.assertFalse(s.isComposing())
        return results

    def test_bopomofo_keys_of_every_layout(self):
        module = ch.load_module()
        for layout in range(13):  # the settings page's 13 layouts
            full, half = self.symbol_keys(layout, True), self.symbol_keys(layout, False)
            for key in self.SYMBOL_KEYS:
                with self.subTest(layout=layout, key=key):
                    bopomofo = full[key][0]
                    self.assertEqual(bool(bopomofo), key in module.LAYOUT_BOPOMOFO_SYMBOL_KEYS.get(layout, ""))
                    if bopomofo:
                        self.assertEqual(half[key], (bopomofo, ""))
                    else:  # half-width punctuation (DVORAK 許氏 remaps some of them)
                        self.assertEqual(half[key][0], "")
                        self.assertRegex(half[key][1], r"^[!-~]$")

    def test_words_typed_with_those_keys(self):
        for layout, keys, word in ((3, "=z", "二"), (3, "h[z", "上"), (4, "'i2", "才"), (4, "=4", "二"),
                                   (6, "'gz6", "平"), (6, "[6", "兒")):
            with self.subTest(layout=layout, keys=keys), self.layout_service(layout, False) as s:
                # "=", "[", "'捱", "'營" before
                self.assertEqual(self.type(s, list(keys) + ["ENTER"]), word)


class ShiftSpaceTests(ChewingTestCase):
    GUID = "{f1dae0fb-8091-44a7-8a0c-3082a1515447}"

    def test_disabled_shift_space_is_not_swallowed(self):
        s = self.service(enableShiftSpace=False)
        self.assertFalse(ch.request(s, "onPreservedKey", guid=self.GUID).get("return"))
        self.assertEqual(s.chewingContext.get_ShapeMode(), 0)

    def test_enabled_shift_space_toggles_the_shape(self):
        s = self.service(enableShiftSpace=True)
        self.assertTrue(ch.request(s, "onPreservedKey", guid=self.GUID).get("return"))
        self.assertEqual(s.chewingContext.get_ShapeMode(), 1)

    def test_shape_button_works_without_the_shortcut(self):
        s = self.service(enableShiftSpace=False)
        ch.request(s, "onCommand", id=2, type=0)  # ID_SWITCH_SHAPE, left click
        self.assertEqual(s.chewingContext.get_ShapeMode(), 1)


if __name__ == "__main__":
    unittest.main()
