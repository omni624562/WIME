"""Regression tests for CinBase states that did not raise but left the IME in a
wrong or stuck state (keys eaten, stale lists on screen, the wrong item picked).
Driven through handleRequest with the real 大易/酷倉 tables (cinbase_harness).
"""

import os
import time
import unittest

import cinbase_harness as h
from cinbase import ID_MODE_ICON, ID_SWITCH_LANG, ID_SWITCH_SHAPE, CHINESE_MODE, ENGLISH_MODE
from cinbase import FULLSHAPE_MODE, HALFSHAPE_MODE, SHIFT_SPACE_GUID


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
class ShiftSpaceTests(unittest.TestCase):
    """Shift + 空白鍵切換全形/半形。以前大易/酷倉一律宣告並吃掉這個鍵：鍵盤關閉
    （Ctrl+Space）時打英文的空白不見、偷偷切成全形，也沒有新酷音那樣的開關。"""

    def activate(self, ime="chedayi", **config):
        service = h.make_service(ime, user_config=config or None)
        reply = h.request(service, "onActivate", isKeyboardOpen=True)
        return service, reply

    def shift_space(self, service):
        return h.request(service, "onPreservedKey", guid=SHIFT_SPACE_GUID).get("return")

    def apply_user_config(self, service, config):
        """Save config.json the way the settings page does and send the next
        request: checkConfigChange notices the new file and applies it."""
        path = h.write_user_config(service.imeDirName, config)
        self.addCleanup(h.remove_user_config, service.imeDirName)
        # time.time() 約 15 ms 才跳一次，連續兩次存檔可能拿到同一個 mtime
        self.stamp = max(getattr(self, "stamp", 0.0), time.time() + 10) + 1
        os.utime(path, (self.stamp, self.stamp))
        service.cfg._lastUpdateTime = 0.0      # not 3 seconds since the last read
        return h.request(service, "ping")

    def test_open_keyboard_toggles_the_shape(self):
        for ime in ("chedayi", "checj"):
            with self.subTest(ime=ime):
                service, reply = self.activate(ime)
                self.assertEqual([key["guid"] for key in reply.get("addPreservedKey", [])],
                                 [SHIFT_SPACE_GUID])
                self.assertTrue(self.shift_space(service))
                self.assertEqual(service.shapeMode, FULLSHAPE_MODE)

    def test_closed_keyboard_passes_it_on(self):
        for ime in ("chedayi", "checj"):
            with self.subTest(ime=ime):
                service, _ = self.activate(ime)
                h.request(service, "onKeyboardStatusChanged", opened=False)
                self.assertFalse(self.shift_space(service))
                h.request(service, "onKeyboardStatusChanged", opened=True)
                self.assertEqual(service.shapeMode, HALFSHAPE_MODE)

    def test_disabled_at_startup_passes_it_on(self):
        # 「預設以停用輸入法模式啟動」：啟用時鍵盤就是關的
        service, _ = self.activate(disableOnStartup=True)
        self.assertFalse(service.keyboardOpen)
        self.assertFalse(self.shift_space(service))
        self.assertEqual(service.shapeMode, HALFSHAPE_MODE)

    def test_option_off_does_not_claim_the_key(self):
        service, reply = self.activate(enableShiftSpace=False)
        self.assertNotIn("addPreservedKey", reply)
        self.assertFalse(self.shift_space(service))
        self.assertEqual(service.shapeMode, HALFSHAPE_MODE)
        self.assertNotIn("removePreservedKey", h.request(service, "onDeactivate"))

    def test_shape_button_works_without_the_shortcut(self):
        service, _ = self.activate(enableShiftSpace=False)
        h.request(service, "onCommand", id=ID_SWITCH_SHAPE, type=0)
        self.assertEqual(service.shapeMode, FULLSHAPE_MODE)

    def test_turning_the_option_off_and_on_while_active(self):
        service, _ = self.activate()
        reply = self.apply_user_config(service, {"enableShiftSpace": False})
        self.assertEqual(reply.get("removePreservedKey"), [SHIFT_SPACE_GUID])
        self.assertNotIn("addPreservedKey", reply)
        self.assertFalse(self.shift_space(service))
        self.assertEqual(service.shapeMode, HALFSHAPE_MODE)

        reply = self.apply_user_config(service, {"enableShiftSpace": True, "candPerPage": 5})
        self.assertEqual([key["guid"] for key in reply.get("addPreservedKey", [])], [SHIFT_SPACE_GUID])
        self.assertTrue(self.shift_space(service))

        # 其他設定改變時不重複宣告（libIME2 會把同一個 GUID 登記兩次）
        reply = self.apply_user_config(service, {"enableShiftSpace": True, "candPerPage": 4})
        self.assertNotIn("addPreservedKey", reply)
        self.assertEqual(h.request(service, "onDeactivate").get("removePreservedKey"), [SHIFT_SPACE_GUID])


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

    def test_settings_item_is_not_started_by_tests(self):
        # 選單的「開啟設定視窗…」用 ShellExecuteW 執行 configtool.py，它會打開使用者的
        # 瀏覽器，而且頁面開著就不會結束。游標 fuzz 測試會按到這一項：以前每跑一次
        # 完整測試就多開兩個設定頁。IsolatedAppData 必須把它換成記錄，先確認再按
        self.assertTrue(h.launches_blocked())
        start = len(_appdata.launches)
        service = h.make_service("chedayi")
        for _ in range(3):
            h.press(service, "`")
            if "特殊符號" in (service.candidateList or []):
                break
        settings = next(item for item in service.candidateList
                        if h.cinbase.menu.mainMenuId(item) == "settings")
        h.press(service, service.selKeys[service.candidateList.index(settings)])
        launches = _appdata.launches[start:]
        self.assertEqual(len(launches), 1, launches)
        name, args = launches[0]
        self.assertEqual(name, "ShellExecuteW")
        self.assertTrue(args[3].endswith('configtool.py" config chedayi'), args)
        self.assertFalse(service.showmenu)


@h.requires_tables
class SelKeysSwitchTests(unittest.TestCase):
    """大易在每個新 client 的第一個鍵、進出 ` 功能選單時會換選字鍵。以前那個鍵放開時
    重送候選清單：頁碼（1/2）被清成空字串；候選窗沒在顯示時，重送的清單沒有
    showCandidates，C++ 端照樣秀出視窗卻不記成「顯示中」，切到別的程式也收不掉。
    按下時的回覆已帶 setSelKeys（C++ 先套用再畫清單），放開時什麼都不用送。"""

    def assertNoCandidateUpdate(self, up):
        for key in ("candidateList", "candidatePageInfo", "showCandidates"):
            self.assertNotIn(key, up)

    def open_function_menu(self, service):
        # 大易三碼的 ` 是字根「巷」，連按三次才是功能選單
        for _ in range(3):
            down, up = h.press_replies(service, "`")
            if "特殊符號" in (service.candidateList or []):
                return down, up
        self.fail("function menu not shown")

    def test_first_key_keeps_the_page_info(self):
        service = h.make_service("chedayi")
        down, up = h.press_replies(service, "x")
        self.assertIn("setSelKeys", down)                  # the key that switches the keys
        self.assertIs(down.get("showCandidates"), True)
        self.assertTrue(down.get("candidateList"))
        self.assertTrue(down.get("candidatePageInfo"))      # e.g. 1/2
        self.assertNoCandidateUpdate(up)

    def test_function_menu_is_shown_on_key_down(self):
        service = h.make_service("chedayi")
        h.type_keys(service, ["x", "SPACE"])                # the 大易 keys are in use
        down, up = self.open_function_menu(service)
        self.assertEqual(down.get("setSelKeys"), "1234567890")
        self.assertIs(down.get("showCandidates"), True)
        self.assertIn("選單", down.get("candidateHeader", ""))
        self.assertNoCandidateUpdate(up)                    # used to replace the menu header

    def test_escape_from_the_function_menu_leaves_no_window(self):
        service = h.make_service("chedayi")
        self.open_function_menu(service)
        down, up = h.press_replies(service, "ESC")
        self.assertIs(down.get("showCandidates"), False)
        self.assertIn("setSelKeys", down)
        self.assertNoCandidateUpdate(up)                    # used to resend the menu page

    def test_first_key_that_commits_leaves_no_window(self):
        for key, shift in (("a", True), ("~", False), ("+", False)):
            with self.subTest(key=key):
                service = h.make_service("chedayi")
                down, up = h.press_replies(service, key, shift=shift)
                self.assertTrue(down.get("commitString"))
                self.assertNoCandidateUpdate(up)


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


def auto_commit_code(service, with_phrases=False):
    """A code (lowercase letters only) with exactly one candidate that no longer
    code starts with: typing it commits that candidate when
    autoCommitSingleCandidate is on (大易三碼 3 roots, 酷倉 5 roots...).
    with_phrases: the candidate also has 聯想字詞, so the phrase list opens."""
    cin = service.cin
    for code in sorted(cin.chardefs):
        if (len(code) >= 3 and code.isascii() and code.isalpha() and code.islower()
                and len(cin.chardefs[code]) == 1 and not cin.hasLongerCharDefPrefix(code)):
            char = cin.chardefs[code][0]
            if with_phrases and not service.cinbase.phraseSuggestions(service, char):
                continue
            return code, char
    raise unittest.SkipTest("no suitable single-candidate code")


@h.requires_tables
class SpaceAfterAutoCommitTests(unittest.TestCase):
    """只有一個候選字時自動送出後，緊接著習慣多按的空白鍵要忽略（不打出空白）；
    隔一段時間、中間按了別的鍵、或沒開自動送出時，空白照常。"""

    def auto_commit(self, ime="chedayi", with_phrases=False, **overrides):
        config = {"selCinType": 2} if ime == "chedayi" else {}
        config.update(autoCommitSingleCandidate=True, **overrides)
        service = h.make_service(ime, user_config=config)
        if with_phrases:
            h.wait_for_phrase_table()
        code, char = auto_commit_code(service, with_phrases)
        commits, _ = h.type_keys(service, list(code))
        self.assertEqual(commits, [char], code)
        return service

    def assert_space_ignored(self, service):
        down, _ = h.press_replies(service, "SPACE")
        self.assertTrue(down.get("return"), "the Space was passed to the application")
        self.assertNotIn("commitString", down)

    def assert_space_passed(self, service):
        down, _ = h.press_replies(service, "SPACE")
        self.assertEqual(down, {}, "the Space was taken by the input method")

    def test_space_right_after_auto_commit_is_ignored_once(self):
        for ime in ("chedayi", "checj"):
            with self.subTest(ime=ime):
                service = self.auto_commit(ime)
                self.assert_space_ignored(service)
                self.assert_space_passed(service)   # a second Space is a real one

    def test_another_key_first_cancels_it(self):
        service = self.auto_commit()
        h.press(service, "LEFT")
        self.assert_space_passed(service)

    def test_space_after_a_pause_is_typed(self):
        service = self.auto_commit()
        service.skipSpaceDeadline = h.cinbase.time.monotonic() - 0.01
        self.assert_space_passed(service)

    def test_shift_space_is_not_taken(self):
        service = self.auto_commit()
        h.press(service, "SPACE", shift=True)
        self.assertEqual(service.skipSpaceDeadline, 0.0)
        self.assert_space_passed(service)

    def test_focus_loss_cancels_it(self):
        service = self.auto_commit()
        h.request(service, "onKillFocus")
        self.assert_space_passed(service)

    def test_space_only_tested_does_not_stay_armed(self):
        # TSF 可能只測試按鍵（filterKeyDown）而沒有真的送 onKeyDown；放開空白鍵後
        # 就不能再留著，否則之後刻意按的空白會被吃掉
        service = self.auto_commit()
        down = h.key_event("SPACE")
        self.assertTrue(h._send(service, "filterKeyDown", down, "SPACE").get("return"))
        h._send(service, "filterKeyUp", h.key_event("SPACE", down=False), "SPACE")
        self.assert_space_passed(service)

    def test_ignored_space_does_not_pick_a_phrase(self):
        # 聯想字詞開著時，那一下空白以前會選走第一個聯想詞
        for ime in ("chedayi", "checj"):
            with self.subTest(ime=ime):
                service = self.auto_commit(ime, with_phrases=True, showPhrase=True)
                self.assertTrue(service.isShowPhraseCandidates)
                phrases = list(service.candidateList)
                self.assert_space_ignored(service)
                self.assertTrue(service.isShowPhraseCandidates)
                self.assertEqual(list(service.candidateList), phrases)

    def test_mode_switch_by_mouse_cancels_it(self):
        # 用滑鼠點語言列切換中英文或全半形不會送按鍵，也要取消
        for command in (ID_MODE_ICON, ID_SWITCH_LANG, ID_SWITCH_SHAPE):
            with self.subTest(command=command):
                service = self.auto_commit()
                h.request(service, "onCommand", id=command, type=0)
                down = h.key_event("SPACE")
                filtered = h._send(service, "filterKeyDown", down, "SPACE").get("return")
                eaten = filtered and h._send(service, "onKeyDown", down, "SPACE")
                self.assertEqual(service.skipSpaceDeadline, 0.0)
                if command == ID_SWITCH_SHAPE:   # 全形模式的空白由輸入法輸出全形空白
                    self.assertIn("commitString", eaten or {})
                else:
                    self.assertFalse(filtered)

    def test_without_auto_commit_space_still_selects(self):
        service = h.make_service("chedayi", user_config={"selCinType": 2, "autoCommitSingleCandidate": False})
        code, char = auto_commit_code(service)
        commits, _ = h.type_keys(service, list(code) + ["SPACE"])
        self.assertEqual(commits, [char])
        self.assert_space_passed(service)


if __name__ == "__main__":
    unittest.main()
