"""Regression tests for CinBase states that did not raise but left the IME in a
wrong or stuck state (keys eaten, stale lists on screen, the wrong item picked).
Driven through handleRequest with the real 大易/酷倉 tables (cinbase_harness).
"""

import os
import unittest

import cinbase_harness as h
from cinbase import ID_MODE_ICON, ID_SWITCH_LANG, CHINESE_MODE, ENGLISH_MODE


def setUpModule():
    global _appdata, _real_play
    _appdata = h.IsolatedAppData()
    _real_play = h.cinbase.winsound.PlaySound
    h.cinbase.winsound.PlaySound = lambda *a, **k: None


def tearDownModule():
    h.cinbase.winsound.PlaySound = _real_play
    _appdata.close()


def show_phrases_after_commit(ime="chedayi"):
    service = h.make_service(ime, showPhrase=True, directShowCand=True)
    commits, _ = h.type_keys(service, ["x", "SPACE"])
    assert len(commits) == 1, commits
    assert service.phrasemode and service.candidateList, "phrase list not shown"
    return service


@h.requires_tables
class ModeSwitchTests(unittest.TestCase):
    def test_language_button_mid_composition(self):
        for command in (ID_MODE_ICON, ID_SWITCH_LANG):
            with self.subTest(command=command):
                service = h.make_service("chedayi", directShowCand=True)
                h.type_keys(service, ["x"])
                self.assertTrue(service.showCandidates)
                h.request(service, "onCommand", id=command, type=0)
                self.assertEqual(service.langMode, ENGLISH_MODE)
                self.assertEqual(service.compositionChar, "")
                self.assertFalse(service.showCandidates)
                # English letters reach the application again
                reply = h._send(service, "filterKeyDown", h.key_event("b"), "b")
                self.assertFalse(reply.get("return"))

    def test_shift_toggle_closes_the_phrase_list(self):
        service = show_phrases_after_commit()
        h.press(service, "SHIFT")
        self.assertEqual(service.langMode, ENGLISH_MODE)
        self.assertFalse(service.phrasemode)
        self.assertFalse(service.showCandidates)

    def test_mode_switch_shows_no_prompt(self):
        # 「中文模式／英數模式」提示已移除：新版候選窗沒有計時器，切到英數模式後輸入法
        # 不再處理按鍵，提示會一直留在畫面上。舊設定檔裡的 hidePromptMessages 不再有作用
        service = h.make_service("chedayi", user_config={"hidePromptMessages": False})
        up = h.key_event("SHIFT", down=False)
        h._send(service, "filterKeyDown", h.key_event("SHIFT"), "SHIFT")
        h._send(service, "filterKeyUp", up, "SHIFT")
        reply = h._send(service, "onKeyUp", up, "SHIFT")
        self.assertEqual(service.langMode, ENGLISH_MODE)
        self.assertNotIn("showMessage", reply)
        self.assertNotIn("candidateMessage", reply)

    def test_keyboard_reopen_forgets_the_phrase_list(self):
        service = show_phrases_after_commit()
        h.request(service, "onKeyboardStatusChanged", opened=False)
        h.request(service, "onKeyboardStatusChanged", opened=True)
        commits, _ = h.type_keys(service, ["'"])   # 大易's first selection key
        self.assertEqual(commits, [])
        self.assertEqual(service.langMode, CHINESE_MODE)


@h.requires_tables
class PhraseListTests(unittest.TestCase):
    def test_new_composition_does_not_show_the_old_phrases(self):
        for ime, keys in (("chedayi", ["x", "SPACE", "SPACE", "a"]),
                          ("checj", ["m", "f", "SPACE", "SPACE", "a"])):
            with self.subTest(ime=ime):
                service = h.make_service(ime, showPhrase=True, directShowCand=False)
                commits, _ = h.type_keys(service, keys[:-1])
                self.assertEqual(len(commits), 1)
                phrases = list(service.candidateList)
                self.assertTrue(phrases)
                h.type_keys(service, keys[-1:])
                self.assertEqual(service.compositionChar, keys[-1])
                self.assertFalse(service.showCandidates and service.candidateList == phrases)

    def test_app_shortcut_closes_the_phrase_list(self):
        service = show_phrases_after_commit()
        reply = h._send(service, "filterKeyDown", h.key_event("s", ctrl=True), "Ctrl+S")
        self.assertFalse(reply.get("return"))
        self.assertIs(reply.get("showCandidates"), False)
        self.assertFalse(service.phrasemode)


@h.requires_tables
class FunctionMenuTests(unittest.TestCase):
    def test_toggle_whose_state_changed_while_the_menu_was_open(self):
        service = h.make_service("chedayi")
        for _ in range(3):
            h.press(service, "`")
            if "特殊符號" in (service.candidateList or []):
                break
        toggles = next(item for item in service.candidateList if "功能開關" in item)
        h.press(service, service.selKeys[service.candidateList.index(toggles)])
        item = next(item for item in service.candidateList if "聯想字詞" in item)
        before = service.showPhrase
        service.showPhrase = not before     # changed in the settings page meanwhile
        h.press(service, service.selKeys[service.candidateList.index(item)])   # used to raise ValueError
        self.assertEqual(service.showPhrase, before)


@h.requires_tables
class DayiSymbolTests(unittest.TestCase):
    def test_backspace_clears_the_symbol_prefix(self):
        service = h.make_service("chedayi", directShowCand=True)
        h.type_keys(service, ["=", "0"])
        self.assertEqual(service.compositionChar, "=0")
        h.type_keys(service, ["BACK"])
        self.assertEqual(service.compositionChar, "=")
        self.assertEqual(service.compositionString, "＝")
        h.type_keys(service, ["BACK"])
        self.assertEqual(service.compositionChar, "")
        commits, _ = h.type_keys(service, ["x", "SPACE"])
        self.assertEqual(len(commits), 1)

    def test_backspace_in_composition_buffer_mode(self):
        service = h.make_service("chedayi", compositionBufferMode=True, directShowCand=True)
        h.type_keys(service, ["x", "SPACE"])
        first = service.compositionBufferString
        self.assertEqual(len(first), 1)
        h.type_keys(service, ["=", "0", "BACK"])
        self.assertEqual(service.compositionBufferString, first + "＝")
        h.type_keys(service, ["BACK"])
        self.assertEqual(service.compositionBufferString, first)   # the earlier character stays


@h.requires_tables
class CompositionBufferTests(unittest.TestCase):
    def test_dead_roots_are_not_committed(self):
        keys = ["b", "l", "x", "SPACE", "ENTER"]    # "bl" is not the start of any 大易 code
        plain, _ = h.type_keys(h.make_service("chedayi"), keys[:-1])
        service = h.make_service("chedayi", compositionBufferMode=True)
        commits, _ = h.type_keys(service, keys)
        self.assertEqual(commits, plain)


@h.requires_tables
@unittest.skipUnless(os.path.exists(os.path.join(h.JSON_DIR, "thphonetic.json")), "thphonetic.json missing")
class HomophoneTests(unittest.TestCase):
    # 泰瑞大易四碼 (selCinType 0): in 大易三碼, the default table, ` is the root 巷,
    # so after a root it continues the code instead of opening the homophone list
    THDAYI = {"selCinType": 0}

    def test_reading_selection_key(self):
        service = h.make_service("chedayi", user_config=self.THDAYI, homophoneQuery=True, directShowCand=True)
        hcin = h._modules["chedayi"].HCinTable
        if hcin.cin is None:
            h.cinbase.LoadHCinTable(service, hcin).run()
        # find a candidate with 3+ readings on the first page of some root
        for root in "abcdefghijklmnopqrstuvwxyz":
            service = h.make_service("chedayi", user_config=self.THDAYI, homophoneQuery=True, directShowCand=True)
            h.type_keys(service, [root])
            char = service.candidateList[0] if service.candidateList else ""
            if char and hcin.cin.isHaveKey(char) and len(hcin.cin.getKeyList(char)) >= 3:
                break
        else:
            self.skipTest("no character with 3 readings found")
        h.press(service, "`")
        self.assertTrue(service.homophoneselpinyinmode)
        h.press(service, "'")        # 大易: the key labelled on the 2nd item
        self.assertEqual(service.homophonecandidates,
                         hcin.cin.getCharDef(hcin.cin.getKeyList(char)[1]))

    def test_disabled_when_backtick_is_a_root(self):
        # 大易三碼的 ` 是字根「巷」：打一、兩碼時 ` 是字根，打滿三碼後才會查同音字，
        # 時有時無，所以三碼一律不查（設定頁也停用）
        dayi3 = {"selCinType": 2}
        service = h.make_service("chedayi", user_config=dayi3, homophoneQuery=True, directShowCand=True)
        hcin = h._modules["chedayi"].HCinTable
        if hcin.cin is None:
            h.cinbase.LoadHCinTable(service, hcin).run()
        for code in ("aaa", "aab", "abc", "abd"):
            service = h.make_service("chedayi", user_config=dayi3, homophoneQuery=True, directShowCand=True)
            h.type_keys(service, list(code))
            if service.candidateList:
                break
        else:
            self.skipTest("no full 3-root code with candidates found")
        self.assertTrue(h.cinbase.menu.homophoneKeyIsRoot(service))
        h.press(service, "`")
        self.assertFalse(service.homophonemode)
        labels, attrs = h.cinbase.menu.buildToggleItems(service)
        self.assertNotIn("homophoneQuery", attrs)


@h.requires_tables
class SmallKeyHandlingTests(unittest.TestCase):
    def test_shift_backspace_while_composing(self):
        service = h.make_service("chedayi", directShowCand=True)
        h.type_keys(service, ["x", "a"])
        reply = h.press(service, "BACK", shift=True)
        self.assertTrue(reply.get("return"))       # handled, not passed to the application
        self.assertEqual(service.compositionChar, "x")

    def test_fullshape_keeps_non_ascii_characters(self):
        service = h.make_service("chedayi")
        for ch in "£äé":
            self.assertEqual(h.cinbase.CinBase.charCodeToFullshape(service, ord(ch), 0), ch)
            self.assertEqual(h.cinbase.CinBase.SymbolscharCodeToFullshape(ord(ch)), ch)
        self.assertEqual(h.cinbase.CinBase.charCodeToFullshape(service, ord("a"), ord("A")), "ａ")

    def test_wildcard_results_have_no_duplicates(self):
        # 酷倉 p* 與 *n 以前各有 2 個重複（同一字出現在多個相符的碼）
        for ime, pattern in (("checj", "p*"), ("checj", "*n"), ("chedayi", "a*")):
            with self.subTest(ime=ime, pattern=pattern):
                cin = h.make_service(ime).cin
                result = cin.getWildcardCharDefs(pattern, "*", 100)
                self.assertEqual(len(result), len(set(result)))


if __name__ == "__main__":
    unittest.main()
