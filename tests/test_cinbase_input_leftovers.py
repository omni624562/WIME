"""Regression tests for smaller input issues left over from the CinBase audit:
emoji split into several candidates, "Error" candidates from malformed lines in
user data files, and which Shift key switches Chinese/English.
"""

import io
import os
import unittest
from unittest import mock

import cinbase_harness as h
from cinbase import CHINESE_MODE, ENGLISH_MODE
from cinbase.textclusters import symbolClusters


def setUpModule():
    global _appdata, _real_play
    _appdata = h.IsolatedAppData()
    _real_play = h.cinbase.winsound.PlaySound
    h.cinbase.winsound.PlaySound = lambda *a, **k: None


def tearDownModule():
    h.cinbase.winsound.PlaySound = _real_play
    _appdata.close()


class SymbolClusterTests(unittest.TestCase):
    def test_emoji_sequences_stay_whole(self):
        cases = {
            "❤️": ["❤️"],                        # + VS16
            "👍🏻👍🏿": ["👍🏻", "👍🏿"],            # skin tones
            "1️⃣#️⃣": ["1️⃣", "#️⃣"],                # keycaps
            "🇹🇼🇯🇵": ["🇹🇼", "🇯🇵"],              # flags: regional indicator pairs
            "👨‍👩‍👧": ["👨‍👩‍👧"],                  # ZWJ sequence
            "🏴󠁧󠁢󠁥󠁮󠁧󠁿": ["🏴󠁧󠁢󠁥󠁮󠁧󠁿"],                  # tag sequence
            "é": ["é"],                         # e + combining acute
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(symbolClusters(text), expected)
                self.assertEqual("".join(symbolClusters(text)), text)

    def test_plain_symbols_are_split_per_character(self):
        self.assertEqual(symbolClusters("，、。★☆←→"), list("，、。★☆←→"))
        self.assertEqual(symbolClusters("🇹🇼🇯"), ["🇹🇼", "🇯"])   # odd regional indicator stays alone

    def test_symbol_file_parsers(self):
        line = "表情=❤️👍🏻🇹🇼★\n"
        for parser in (h.cinbase.symbols, h.cinbase.fsymbols, h.cinbase.flangs):
            with self.subTest(parser=parser.__name__):
                table = parser(io.StringIO(line))
                self.assertEqual(table.getCharDef("表情"), ["❤️", "👍🏻", "🇹🇼", "★"])


class MalformedDataLineTests(unittest.TestCase):
    def test_quick_symbols_without_a_symbol(self):
        table = h.cinbase.swkb(io.StringIO("﻿Q —\nW\n\nA ←\n"))
        self.assertEqual(table.getCharDef("Q"), ["—"])      # BOM stripped from the first key
        self.assertFalse(table.isInCharDef("W"))            # used to give the candidate "Error"
        self.assertFalse(table.isInCharDef(""))
        self.assertEqual(table.getCharDef("A"), ["←"])

    def test_extend_table_without_a_candidate(self):
        table = h.cinbase.extendtable(io.StringIO("﻿abc 字\nxyz\n\n"))
        self.assertEqual(table.getCharDef("abc"), ["字"])
        self.assertFalse(table.isInCharDef("xyz"))
        self.assertFalse(table.isInCharDef(""))


LEFT, RIGHT = 0x2A, 0x36


@h.requires_tables
class ShiftSideTests(unittest.TestCase):
    """switchLangWithWhichShift: 1 = left Shift only, 2 = right Shift only."""

    def tap_shift(self, service, scan_code):
        down, up = h.key_event("SHIFT"), h.key_event("SHIFT", down=False)
        down["scanCode"] = up["scanCode"] = scan_code
        h._send(service, "filterKeyDown", down, "Shift")
        if h._send(service, "filterKeyUp", up, "Shift").get("return"):
            h._send(service, "onKeyUp", up, "Shift")

    def test_the_other_shift_does_not_switch(self):
        for which, same, other in ((1, LEFT, RIGHT), (2, RIGHT, LEFT)):
            with self.subTest(which=which):
                service = h.make_service("chedayi", user_config={
                    "switchLangWithShift": True, "switchLangWithWhichShift": which})
                # the unreliable "pressed since the last call" bit of GetAsyncKeyState,
                # e.g. left Shift was used for a capital letter earlier
                with mock.patch.object(h.cinbase.CinBase, "isPressed", return_value=True):
                    self.tap_shift(service, other)
                    self.assertEqual(service.langMode, CHINESE_MODE)
                    self.tap_shift(service, same)
                    self.assertEqual(service.langMode, ENGLISH_MODE)

    def test_without_a_scan_code_falls_back_to_the_key_state(self):
        # older PIMETextService.dll always sent scanCode 0; SendInput may too
        service = h.make_service("chedayi", user_config={
            "switchLangWithShift": True, "switchLangWithWhichShift": 1})
        with mock.patch.object(h.cinbase.CinBase, "isPressed", return_value=False):
            self.tap_shift(service, 0)
            self.assertEqual(service.langMode, CHINESE_MODE)
        with mock.patch.object(h.cinbase.CinBase, "isPressed", return_value=True):
            self.tap_shift(service, 0)
            self.assertEqual(service.langMode, ENGLISH_MODE)

    def test_either_shift_when_both_are_allowed(self):
        service = h.make_service("chedayi", user_config={
            "switchLangWithShift": True, "switchLangWithWhichShift": 0})
        self.tap_shift(service, RIGHT)
        self.assertEqual(service.langMode, ENGLISH_MODE)
        self.tap_shift(service, LEFT)
        self.assertEqual(service.langMode, CHINESE_MODE)


@h.requires_tables
class EmojiInTheSymbolMenuTests(unittest.TestCase):
    def test_emoji_category_in_the_function_menu(self):
        ime_dir = _appdata.ime_dir("chedayi")
        path = os.path.join(ime_dir, "symbols.dat")
        with open(path, "w", encoding="utf-8") as f:
            f.write("表情=❤️👍🏻🇹🇼\n")
        try:
            for buffer_mode in (False, True):
                with self.subTest(compositionBufferMode=buffer_mode):
                    service = h.make_service("chedayi", compositionBufferMode=buffer_mode)
                    for _ in range(3):
                        h.press(service, "`")
                        if "特殊符號" in (service.candidateList or []):
                            break
                    h.press(service, service.selKeys[service.candidateList.index("特殊符號")])
                    h.press(service, service.selKeys[service.candidateList.index("表情")])
                    self.assertEqual([c for c in service.candidateList if c != "↩ 返回"][:3],
                                     ["❤️", "👍🏻", "🇹🇼"])
                    commits, _ = h.type_keys(service, [service.selKeys[service.candidateList.index("❤️")]])
                    if buffer_mode:
                        self.assertEqual(service.compositionBufferString, "❤️")
                        h.type_keys(service, ["LEFT", "DOWN", "ESC", "BACK", "BACK", "ENTER"])
                    else:
                        self.assertEqual(commits, ["❤️"])
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
