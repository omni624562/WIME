import contextlib
import importlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class CinCountTests(unittest.TestCase):
    def make_cin(self, temp_dir, count_data):
        spec = importlib.util.spec_from_file_location("cin_module_for_test", os.path.join(PYTHON_DIR, "cinbase", "cin.py"))
        cin_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cin_module)
        Cin = cin_module.Cin

        cin = Cin.__new__(Cin)
        cin.keynames = {}
        cin.cincount = {}
        cin.chardefs = {}
        cin.privateuse = {}
        cin.dupchardefs = {}
        cin._count_dirty = False
        cin.getCountFile = lambda name="cincount.json": os.path.join(temp_dir, name)
        with open(cin.getCountFile(), "w", encoding="utf-8") as f:
            json.dump(count_data, f)
        return cin

    def make_wildcard_cin(self):
        spec = importlib.util.spec_from_file_location("cin_module_for_test", os.path.join(PYTHON_DIR, "cinbase", "cin.py"))
        cin_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cin_module)
        cin = cin_module.Cin.__new__(cin_module.Cin)
        cin.charsetRange = {
            "bopomofo": [int("0x3100", 16), int("0x3130", 16)],
            "bopomofoTone": [int("0x02D9", 16), int("0x02CB", 16)],
            "cjk": [int("0x4E00", 16), int("0x9FEB", 16)],
            "big5F": [int("0xA440", 16), int("0xC67F", 16)],
            "big5LF": [int("0xC940", 16), int("0xF9D6", 16)],
            "big5S": [int("0xA140", 16), int("0xA3C0", 16)],
            "cjkExtA": [int("0x3400", 16), int("0x4DB6", 16)],
        }
        cin.chardefs = {
            "ab": ["木"],
            "acb": ["林"],
            "acdb": ["森"],
            "ba": ["火"],
            "n1": ["尼"],
            "nx1": ["屋"],
        }
        return cin

    def test_variable_wildcard_can_span_zero_or_more_roots(self):
        cin = self.make_wildcard_cin()

        self.assertEqual(cin.getWildcardCharDefs("a*b", "*", 10), ["林"])
        self.assertEqual(cin.getWildcardCharDefs("a*b", "*", 10, variableWildcard=True), ["木", "林", "森"])
        self.assertEqual(cin.getWildcardCharDefs("n*1", "*", 10, variableWildcard=True), ["尼", "屋"])

    def test_get_char_def_returns_empty_for_missing_key(self):
        cin = self.make_wildcard_cin()

        self.assertEqual(cin.getCharDef("="), [])

    def test_wildcard_keeps_low_frequency_other_charset_matches(self):
        cin = self.make_wildcard_cin()
        cin.chardefs["azb"] = ["A"]

        self.assertIn("A", cin.getWildcardCharDefs("a*b", "*", 10, variableWildcard=True))

    def test_wildcard_keeps_low_frequency_unlisted_charset_matches(self):
        cin = self.make_wildcard_cin()
        cin.chardefs["ayb"] = ["B"]
        original_get_char_set = cin.getCharSet
        cin.getCharSet = lambda root: "unlisted" if root == "B" else original_get_char_set(root)

        self.assertIn("B", cin.getWildcardCharDefs("a*b", "*", 10, variableWildcard=True))

    def test_sorted_chardef_keys_cache_refreshes_on_table_change(self):
        cin = self.make_wildcard_cin()
        self.assertEqual(cin.getWildcardCharDefs("a*b", "*", 10), ["林"])

        # 表格內容改變（如載入擴充表）後，快取必須跟著更新
        cin.chardefs["azb"] = ["新"]
        self.assertIn("新", cin.getWildcardCharDefs("a*b", "*", 10))

    def test_load_count_file_ignores_malformed_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {
                "abc": {"A": 3},
                "bad": ["not", "a", "dict"],
                "also_bad": 2,
            })

            cin.loadCountFile()

            self.assertEqual(cin.cincount, {
                "abc": {"A": {"count": 3, "last": 0, "prev": {}}}
            })

    def test_add_and_sort_count_tolerate_bad_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {})
            cin.cincount = {"abc": "bad"}

            cin.addCount("abc", "A")
            cin.addCount(None, "B")

            self.assertEqual(cin.cincount["abc"]["A"]["count"], 1)
            self.assertEqual(cin.cincount["abc"]["A"]["prev"], {})
            # 沒有上下文訊號就維持碼表順序（不論選過幾次）
            self.assertEqual(cin.sortByCount("abc", ["B", "A"]), ["B", "A"])
            cin.addCount("abc", "A")
            self.assertEqual(cin.sortByCount("abc", ["B", "A"]), ["B", "A"])
            # 有上下文紀錄時才提前
            cin.addCount("abc", "A", "前")
            self.assertEqual(cin.sortByCount("abc", ["B", "A"], previousChar="前"), ["A", "B"])
            self.assertEqual(cin.sortByCount("missing", ["B", "A"]), ["B", "A"])

    def test_context_counts_are_capped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {})

            for i in range(40):
                cin.addCount("abc", "A", "prev{0:02d}".format(i))

            prev = cin.cincount["abc"]["A"]["prev"]
            self.assertEqual(len(prev), cin.MAX_CONTEXT_ENTRIES)
            self.assertIn("prev39", prev)

    def test_recent_context_picks_overtake_old_heavy_counts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {})
            now = 1000000.0
            old = now - 90 * 86400.0
            cin.cincount = {"abc": {
                "舊": {"count": 200, "last": old, "prev": {}},
                "新": {"count": 3, "last": now - 60.0, "prev": {"前": 2}},
            }}

            with mock.patch("time.time", return_value=now):
                with_context = cin.sortByCount("abc", ["舊", "新"], previousChar="前")
                without_context = cin.sortByCount("abc", ["舊", "新"])

            self.assertEqual(with_context, ["新", "舊"])
            # 沒有上下文訊號時維持碼表順序
            self.assertEqual(without_context, ["舊", "新"])

    def test_global_frequency_never_reorders_without_context(self):
        # 肌肉記憶保證：不論全域選了多少次，沒有前一字上下文就不重排
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {})
            now = 1000000.0
            cin.cincount = {"abc": {
                "魚": {"count": 500, "last": now - 60.0, "prev": {"前": 9}},
            }}

            with mock.patch("time.time", return_value=now):
                ordered = cin.sortByCount("abc", ["夕", "刀", "角", "魚"])

            self.assertEqual(ordered, ["夕", "刀", "角", "魚"])

    def test_context_prediction_follows_previous_char(self):
        # 常打「詹智丞」：打完「詹」再組「智」的字碼時，「智」提前
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {})
            for _ in range(3):
                cin.addCount("keyZ", "智", "詹")

            self.assertEqual(
                cin.sortByCount("keyZ", ["知", "智", "蜘"], previousChar="詹"),
                ["智", "知", "蜘"])
            # 前一字不是「詹」時維持碼表順序
            self.assertEqual(
                cin.sortByCount("keyZ", ["知", "智", "蜘"], previousChar="無"),
                ["知", "智", "蜘"])
            self.assertEqual(
                cin.sortByCount("keyZ", ["知", "智", "蜘"]),
                ["知", "智", "蜘"])

    def test_single_pick_does_not_jump_over_established_habit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {})
            now = 1000000.0
            cin.cincount = {"abc": {
                "慣": {"count": 30, "last": now - 86400.0, "prev": {}},
                "偶": {"count": 1, "last": now - 60.0, "prev": {}},
            }}

            with mock.patch("time.time", return_value=now):
                ordered = cin.sortByCount("abc", ["慣", "偶"])

            self.assertEqual(ordered, ["慣", "偶"])

    def test_single_pick_keeps_table_order_against_untouched(self):
        # 誤選一次（count=1、無上下文）不可超越從未選過的字，
        # 否則空白鍵的預設輸出（candidates[0]）會被偷換
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {})
            now = 1000000.0
            cin.cincount = {"abc": {
                "偶": {"count": 1, "last": now - 60.0, "prev": {}},
            }}

            with mock.patch("time.time", return_value=now):
                ordered = cin.sortByCount("abc", ["土", "士", "偶"])

            self.assertEqual(ordered, ["土", "士", "偶"])

    def test_single_pick_with_matching_context_reorders(self):
        # 同樣 count=1，但在相同前一字的上下文中選過 → 精準訊號，參與重排
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {})
            now = 1000000.0
            cin.cincount = {"abc": {
                "偶": {"count": 1, "last": now - 60.0, "prev": {"前": 1}},
            }}

            with mock.patch("time.time", return_value=now):
                with_context = cin.sortByCount("abc", ["土", "偶"], previousChar="前")
                without_context = cin.sortByCount("abc", ["土", "偶"])

            self.assertEqual(with_context, ["偶", "土"])
            self.assertEqual(without_context, ["土", "偶"])

    def test_save_count_file_is_throttled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {})
            cin.cincount = {"abc": {"A": {"count": 1, "last": 0, "prev": {}}}}
            cin._count_dirty = True
            cin._last_count_save_time = 100.0

            with mock.patch("time.time", return_value=110.0):
                cin.saveCountFile()
            with open(cin.getCountFile(), "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f), {})

            with mock.patch("time.time", return_value=111.0):
                cin.saveCountFile(force=True)
            with open(cin.getCountFile(), "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f), cin.cincount)


class ServerResilienceTests(unittest.TestCase):
    def import_server(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return importlib.import_module("server")

    def input_then_eof(self, lines):
        iterator = iter(lines)

        def fake_input():
            try:
                return next(iterator)
            except StopIteration:
                raise EOFError

        return fake_input

    def test_server_continues_after_client_exception(self):
        server_mod = self.import_server()
        server = server_mod.Server()

        class FailingClient:
            def handleRequest(self, msg):
                raise RuntimeError("boom")

        server.clients["client-1"] = FailingClient()

        with mock.patch("builtins.input", side_effect=self.input_then_eof(['client-1|{"method":"onKeyDown"}'])), \
                mock.patch.object(server_mod, "append_error_log"), \
                contextlib.redirect_stdout(io.StringIO()) as stdout, \
                contextlib.redirect_stderr(io.StringIO()):
            server.run()

        self.assertIn('PIME_MSG|client-1|{"success":false}', stdout.getvalue())

    def test_server_ignores_malformed_request_line(self):
        server_mod = self.import_server()
        server = server_mod.Server()

        with mock.patch("builtins.input", side_effect=self.input_then_eof(["malformed-request"])), \
                mock.patch.object(server_mod, "append_error_log") as append_error_log, \
                contextlib.redirect_stdout(io.StringIO()) as stdout, \
                contextlib.redirect_stderr(io.StringIO()):
            server.run()

            self.assertEqual(stdout.getvalue(), "")
            append_error_log.assert_called_once()


class KeyEventTests(unittest.TestCase):
    def make_event(self, keyStates):
        import textService

        msg = {"charCode": 97, "keyCode": 65, "repeatCount": 1,
               "scanCode": 30, "isExtended": False}
        if keyStates is not None:
            msg["keyStates"] = keyStates
        return textService.KeyEvent(msg)

    def test_accepts_legacy_256_array(self):
        states = [0] * 256
        states[16] = 0x81
        event = self.make_event(states)
        self.assertTrue(event.isKeyDown(16))
        self.assertTrue(event.isKeyToggled(16))
        self.assertFalse(event.isKeyDown(65))

    def test_accepts_sparse_object(self):
        event = self.make_event({"16": 0x80, "20": 1})
        self.assertTrue(event.isKeyDown(16))
        self.assertFalse(event.isKeyToggled(16))
        self.assertTrue(event.isKeyToggled(20))
        self.assertFalse(event.isKeyDown(65))

    def test_sparse_object_ignores_bad_entries(self):
        # out-of-range, non-integer, and non-integer-value entries are all dropped
        event = self.make_event({"abc": 0x80, "300": 0x80, "-1": 0x80, "16": "bad"})
        self.assertEqual(event.keyStates, {})

    def test_missing_keystates_defaults_to_all_zero(self):
        # absent keyStates yields an empty sparse dict; all keys read as not-down
        event = self.make_event(None)
        self.assertEqual(event.keyStates, {})
        self.assertFalse(event.isKeyDown(16))


class SortByPhraseTests(unittest.TestCase):
    class StubDef:
        def __init__(self, defs):
            self.defs = defs

        def isInCharDef(self, key):
            return key in self.defs

        def getCharDef(self, key):
            return self.defs[key]

    def test_phrase_candidates_move_to_front_preserving_rest(self):
        import cinbase

        cbTS = type("FakeTS", (), {})()
        cbTS.lastCommitString = "你"
        cbTS.userphrase = self.StubDef({"你": ["好", "們", "不在清單"]})
        old_phrase = cinbase.PhraseData.phrase
        cinbase.PhraseData.phrase = self.StubDef({})
        try:
            original = ["甲", "們", "乙", "好"]
            result = cinbase.CinBase.sortByPhrase(cbTS, list(original))
            self.assertEqual(result, ["好", "們", "甲", "乙"])
            # 沒有詞庫建議時原樣返回
            cbTS.lastCommitString = "無"
            self.assertEqual(
                cinbase.CinBase.sortByPhrase(cbTS, list(original)), original)
        finally:
            cinbase.PhraseData.phrase = old_phrase


class ExcludePhraseTests(unittest.TestCase):
    class StubDef:
        def __init__(self, defs):
            self.defs = defs

        def isInCharDef(self, key):
            return key in self.defs

        def getCharDef(self, key):
            return self.defs[key]

    def filter(self, cbTS, lead, phrases):
        import cinbase
        return cinbase.CinBase.filterExcludedPhrases(cbTS, lead, phrases)

    def test_excluded_phrases_are_dropped(self):
        cbTS = type("FakeTS", (), {})()
        cbTS.excludephrase = self.StubDef({"毛": ["澤東"]})

        result = self.filter(cbTS, "毛", ["豬", "澤東", "病", "巾"])

        self.assertEqual(result, ["豬", "病", "巾"])

    def test_other_lead_chars_unaffected(self):
        cbTS = type("FakeTS", (), {})()
        cbTS.excludephrase = self.StubDef({"毛": ["澤東"]})

        self.assertEqual(self.filter(cbTS, "羽", ["毛球", "澤東"]), ["毛球", "澤東"])

    def test_returns_new_list_to_protect_phrase_table(self):
        # 過濾結果必須是新清單，呼叫端 append 不可污染詞庫內部資料
        cbTS = type("FakeTS", (), {})()
        cbTS.excludephrase = self.StubDef({})
        original = ["豬", "病"]

        result = self.filter(cbTS, "毛", original)
        result.append("外加")

        self.assertEqual(original, ["豬", "病"])

    def test_missing_exclude_table_is_safe(self):
        cbTS = type("FakeTS", (), {})()
        self.assertEqual(self.filter(cbTS, "毛", ["豬"]), ["豬"])


class TextServiceProtocolTests(unittest.TestCase):
    def test_ping_is_a_successful_noop(self):
        import textService

        service = textService.TextService(client=object())
        reply = service.handleRequest({"method": "ping", "seqNum": 7})

        self.assertTrue(reply["success"])
        self.assertEqual(reply["seqNum"], 7)
        self.assertNotIn("return", reply)

    def test_kill_focus_clears_composition_and_candidates(self):
        import textService

        service = textService.TextService(client=object())
        service.commitString = "送出"
        service.compositionString = "組字"
        service.candidateList = ["候", "選"]
        service.candidateCursor = 1
        service.showCandidates = True

        reply = service.handleRequest({"method": "onKillFocus", "seqNum": 8})

        self.assertTrue(reply["success"])
        self.assertEqual(reply["seqNum"], 8)
        self.assertEqual(service.commitString, "")
        self.assertEqual(service.compositionString, "")
        self.assertEqual(service.candidateList, [])
        self.assertEqual(service.candidateCursor, 0)
        self.assertFalse(service.showCandidates)


if __name__ == "__main__":
    unittest.main()
