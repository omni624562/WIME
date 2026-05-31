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


if __name__ == "__main__":
    unittest.main()
