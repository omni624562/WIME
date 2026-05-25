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

    def test_load_count_file_ignores_malformed_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {
                "abc": {"A": 3},
                "bad": ["not", "a", "dict"],
                "also_bad": 2,
            })

            cin.loadCountFile()

            self.assertEqual(cin.cincount, {"abc": {"A": 3}})

    def test_add_and_sort_count_tolerate_bad_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cin = self.make_cin(temp_dir, {})
            cin.cincount = {"abc": "bad"}

            cin.addCount("abc", "A")
            cin.addCount(None, "B")

            self.assertEqual(cin.cincount["abc"], {"A": 1})
            self.assertEqual(cin.sortByCount("abc", ["B", "A"]), ["A", "B"])
            self.assertEqual(cin.sortByCount("missing", ["B", "A"]), ["B", "A"])


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
