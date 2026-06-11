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
            self.assertEqual(cin.sortByCount("abc", ["B", "A"]), ["A", "B"])
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
            # without a matching context the long-term habit stays first
            self.assertEqual(without_context, ["舊", "新"])

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
