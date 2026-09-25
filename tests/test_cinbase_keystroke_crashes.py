"""Regression tests for keystrokes that raised inside the CinBase backend.

Every exception here used to make server.py reply {"success": false}, which
makes the C++ side reset the whole pipe connection - to the user, typing
stops working. Each test drives the real 大易/酷倉 text service with the real
tables (see cinbase_harness).
"""

import json
import os
import unittest

import cinbase_harness as h


def setUpModule():
    global _appdata, _real_play
    _appdata = h.IsolatedAppData()
    _real_play = h.cinbase.winsound.PlaySound
    h.cinbase.winsound.PlaySound = lambda *a, **k: None   # no beeps from tests


def tearDownModule():
    h.cinbase.winsound.PlaySound = _real_play
    _appdata.close()


def open_function_menu(service):
    for _ in range(3):
        h.press(service, "`")
        if "特殊符號" in (service.candidateList or []):
            return
    raise AssertionError("function menu did not open: %r" % service.candidateList)


@h.requires_tables
class StalePageAndCursorTests(unittest.TestCase):
    def test_typing_another_root_after_paging_forward(self):
        # 2+ pages, move to page 2, then a root whose code has only one page
        for ime, keys in (("chedayi", ["x", "PGDN", "a"]),
                          ("chedayi", ["x", "DOWN", "a"]),
                          ("checj", ["h", "n", "PGDN", "a"])):
            with self.subTest(ime=ime, keys=keys):
                service = h.make_service(ime, directShowCand=True, **h.MODERN_LAYOUT)
                h.type_keys(service, keys)
                self.assertEqual(service.currentCandPage, 0)
                # and the IME keeps working afterwards
                commits, _ = h.type_keys(service, ["SPACE"])
                self.assertEqual(len(commits), 1)

    def test_ctrl_symbol_after_moving_the_cursor(self):
        for ime, keys, then in (("chedayi", ["8", "END", ("'", "C")], "SPACE"),
                                ("checj", ["h", "n"] + ["RIGHT"] * 5 + [(";", "C")], "ENTER")):
            with self.subTest(ime=ime):
                service = h.make_service(ime, directShowCand=True, **h.MODERN_LAYOUT)
                h.type_keys(service, keys)
                self.assertLess(service.candidateCursor, len(service.candidateList))
                commits, _ = h.type_keys(service, [then])
                self.assertEqual(len(commits), 1)
                self.assertIn(commits[0], service.candidateList or commits)


@h.requires_tables
class UnicodeInputTests(unittest.TestCase):
    def unicode_input(self, ime, digits):
        service = h.make_service(ime)
        return h.type_keys(service, ["`", "u"] + list(digits) + ["SPACE"]), service

    def test_valid_code_point_is_committed(self):
        (commits, _), _ = self.unicode_input("chedayi", "4e00")
        self.assertEqual(commits, ["一"])

    def test_invalid_input_is_rejected_without_raising(self):
        for digits in ("!", "@", "ffffff", "110000", "d800", "dfff"):
            for ime in ("chedayi", "checj"):
                with self.subTest(ime=ime, digits=digits):
                    (commits, last), _ = self.unicode_input(ime, digits)
                    self.assertEqual(commits, [])
                    # every reply must be serializable (lone surrogates broke orjson in server.py)
                    json.dumps(last, ensure_ascii=False).encode("utf-8")


@h.requires_tables
class KeyNameLookupTests(unittest.TestCase):
    def test_char_encode_with_keys_missing_from_keyname(self):
        # thdayi codes such as "=," use '=', which is not in %keyname
        service = h.make_service("chedayi", selCinType=0)
        encode = service.cin.getCharEncode("，")
        self.assertIsInstance(encode, str)

    def test_wildcard_after_punctuation_key_in_thcj(self):
        service = h.make_service("checj", user_config={"selCinType": 5, "supportWildcard": True,
                                                       "selWildcardType": 1, "directCommitSymbol": True})
        self.assertTrue(service.cin.isInKeyName(","))   # thcj names ',' as a root
        h.type_keys(service, [",", "*"])   # used to raise KeyError('*')


@h.requires_tables
class CompositionBufferTests(unittest.TestCase):
    def test_down_at_end_of_buffer_after_non_table_char(self):
        for ime, keys in (("checj", ["h", "q", "i", "SPACE", ("A", "S"), "DOWN"]),
                          ("chedayi", ["x", "SPACE", ("1", "S"), "DOWN"])):
            with self.subTest(ime=ime):
                service = h.make_service(ime, compositionBufferMode=True)
                h.type_keys(service, keys)

    def test_function_menu_does_not_survive_forced_termination(self):
        service = h.make_service("chedayi", compositionBufferMode=True)
        open_function_menu(service)
        h.request(service, "onCompositionTerminated", forced=True)
        self.assertFalse(service.showmenu)
        h.type_keys(service, ["1", "ESC", "`", "*", "UP"])
        self.assertGreaterEqual(service.compositionBufferCursor, 0)


@h.requires_tables
class PhraseTableMissingTests(unittest.TestCase):
    def test_typing_while_phrase_table_is_unavailable(self):
        service = h.make_service("chedayi", sortByPhrase=True, directShowCand=True)
        saved = h.cinbase.PhraseData.phrase
        h.cinbase.PhraseData.phrase = None
        try:
            _, reply = h.type_keys(service, ["x"])
            self.assertTrue(reply.get("candidateList"))
        finally:
            h.cinbase.PhraseData.phrase = saved


@h.requires_tables
class UserSymbolFileTests(unittest.TestCase):
    def test_category_with_empty_value_in_user_symbol_files(self):
        ime_dir = _appdata.ime_dir("chedayi")
        with open(os.path.join(ime_dir, "symbols.dat"), "w", encoding="utf-8") as f:
            f.write("常用符號=，、。\r\n我的符號=\r\n箭頭=←↑→↓\r\n")
        try:
            service = h.make_service("chedayi")
            open_function_menu(service)
            h.press(service, service.selKeys[service.candidateList.index("特殊符號")])
            self.assertNotIn("我的符號", service.candidateList)   # empty category is not offered
            self.assertIn("箭頭", service.candidateList)
        finally:
            os.remove(os.path.join(ime_dir, "symbols.dat"))


if __name__ == "__main__":
    unittest.main()
