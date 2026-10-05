"""The 新酷音 settings tool (input_methods/chewing/config_tool.py) end to end:
the real tool runs as a separate process (see test_config_server) with APPDATA in
a temporary directory, prepared with problem files before it starts.

- A failed save used to be answered with {"return": true}.
- config.json / swkb.dat with a BOM, and emptied number fields (null), used to
  reach the page as-is (the swkb format check then blocked every save).
- A symbols.dat line over 511 bytes is cut by libchewing in the middle of a
  character, so the tool must refuse it.
- Each 特殊符號 editing session added a blank line to symbols.dat (an empty
  item in the ` menu).
- One user phrase that is not valid UTF-8 made the whole phrase list fail.
- 匯入詞庫 always said "format error" (the validation cursor kept the temp file
  open) but had already overwritten the live database, and it accepted any file
  that had a config_v1 table.
"""

import hashlib
import http.cookiejar
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import uuid

from test_config_server import DRIVER, PYTHON_DIR, _NoRedirect, _get

sys.path.insert(0, PYTHON_DIR)
from libchewing import ChewingContext, CHEWING_DATA_DIR, encodeDataPath  # noqa: E402


def make_phrase_db(path, phrases):
    ctx = ChewingContext(syspath=encodeDataPath(CHEWING_DATA_DIR), userpath=path.encode("utf-8"))
    try:
        for phrase, bopomofo in phrases:
            assert ctx.userphrase_add(phrase.encode("utf-8"), bopomofo.encode("utf-8")) == 1
    finally:
        ctx.close()


def _post(opener, url, body, content_type):
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": content_type})
    try:
        response = opener.open(request, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return getattr(response, "status", None) or response.code, response.read().decode("utf-8", "replace")


def _multipart(field, filename, data):
    boundary = "----wime" + uuid.uuid4().hex
    head = ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n" % (boundary, field, filename)).encode("utf-8")
    return head + data + ("\r\n--%s--\r\n" % boundary).encode("utf-8"), "multipart/form-data; boundary=" + boundary


class ChewingConfigToolDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        env = dict(os.environ)
        env["APPDATA"] = os.path.join(cls.tempdir.name, "Roaming")
        env["LOCALAPPDATA"] = os.path.join(cls.tempdir.name, "Local")
        cls.dir = os.path.join(env["APPDATA"], "PIME", "chewing")
        os.makedirs(cls.dir)
        os.makedirs(env["LOCALAPPDATA"])
        cls.db = os.path.join(cls.dir, "chewing.sqlite3")
        make_phrase_db(cls.db, [("測試", "ㄘㄜˋ ㄕˋ")])
        with sqlite3.connect(cls.db) as conn:  # a copy of that row whose phrase is not UTF-8
            columns = ",".join(["time", "user_freq", "max_freq", "orig_freq", "length"] +
                               ["phone_%d" % i for i in range(11)])
            conn.execute("INSERT INTO userphrase_v1 (%s, phrase) SELECT %s, CAST(X'E6B8ACFF' AS TEXT) "
                         "FROM userphrase_v1 WHERE phrase = '測試'" % (columns, columns))
        conn.close()
        with open(os.path.join(cls.dir, "config.json"), "w", encoding="utf-8-sig") as f:
            json.dump({"candidateMinWidth": None, "candPerPage": 5, "candidateMaxWidth": 300, "candPerRow": 3}, f)
        with open(os.path.join(cls.dir, "swkb.dat"), "w", encoding="utf-8-sig") as f:
            f.write("A ★\n")

        cls.proc = subprocess.Popen(
            [sys.executable, "-c", DRIVER, PYTHON_DIR,
             os.path.join(PYTHON_DIR, "input_methods", "chewing", "config_tool.py"), "60", "config"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True, encoding="utf-8")
        line = cls.proc.stdout.readline()
        if not line.startswith("URL "):
            cls.proc.kill()
            raise RuntimeError("tool did not start: %r %s" % (line, cls.proc.stderr.read()))
        login_url = line[4:].strip()
        cls.base = re.match(r"(http://127\.0\.0\.1:\d+)/", login_url).group(1)
        jar = http.cookiejar.CookieJar()
        no_redirect = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())
        assert _get(no_redirect, login_url).status == 302
        cls.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            cls.proc.kill()
        cls.proc.communicate()
        cls.tempdir.cleanup()

    def post_json(self, path, data):
        return _post(self.opener, self.base + path, json.dumps(data).encode("utf-8"), "application/json")

    def get_json(self, path):
        reply = _get(self.opener, self.base + path)
        self.assertEqual(reply.status, 200, reply.body)
        return json.loads(reply.body.decode("utf-8"))

    def phrases(self):
        return [item["phrase"] for item in self.get_json("/user_phrases")["data"]]

    def db_digest(self):
        with open(self.db, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def leftover_temp_files(self):
        return [name for name in os.listdir(self.dir) if name.startswith("import_") or name.endswith(".tmp")]

    def test_1_config_is_normalized_and_bom_is_stripped(self):
        data = self.get_json("/config")
        self.assertEqual(data["config"]["candidateMinWidth"], 286)  # null on disk
        self.assertEqual(data["config"]["candPerPage"], 5)
        self.assertNotIn("candPerRow", data["config"])  # retired: saving the page drops it from the file
        self.assertEqual(data["config"]["candidateMaxWidth"], 340)  # the old default, as the backend loads it
        self.assertEqual(data["swkb"], "A ★\n")  # "﻿A ..." failed the page's format check

    def test_2_phrase_list_survives_invalid_utf8(self):
        phrases = self.phrases()  # HTTP 500 (UnicodeDecodeError) before
        self.assertIn("測試", phrases)
        self.assertTrue(any("�" in phrase for phrase in phrases))

    def test_3_failed_save_is_reported(self):
        blocker = os.path.join(self.dir, "symbols.dat")
        os.makedirs(blocker)  # os.replace() onto a directory fails
        try:
            status, _ = self.post_json("/config", {"symbols": "測試=★"})
        finally:
            os.rmdir(blocker)
        self.assertEqual(status, 500)  # 200 {"return": true} before
        self.assertEqual(self.leftover_temp_files(), [])

    def test_4_too_long_symbols_line_is_refused(self):
        status, _ = self.post_json("/config", {"symbols": "長=" + "\U0001F600" * 200})
        self.assertEqual(status, 400)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "symbols.dat")))

    def test_5_save_config(self):
        status, body = self.post_json("/config", {"config": {"candPerPage": 7}, "swkb": "B ☆"})
        self.assertEqual((status, json.loads(body)), (200, {"return": True}))
        with open(os.path.join(self.dir, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"candPerPage": 7})

    def test_5b_symbols_are_saved_without_blank_lines(self):
        # The page adds a "\n" when the text does not end with one, and the tool used
        # to write another: each editing session left one more blank line, which
        # libchewing shows as an empty ` menu item
        path = os.path.join(self.dir, "symbols.dat")
        self.addCleanup(os.remove, path)
        text = "測試=★☆\n★\n"
        for _ in range(3):  # load the page, save the text it shows unchanged
            status, _ = self.post_json("/config", {"symbols": text})
            self.assertEqual(status, 200)
            text = self.get_json("/config")["symbols"]
            self.assertEqual(text, "測試=★☆\n★\n")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), "測試=★☆\r\n★\r\n".encode("utf-8"))
        # blank lines already in the text go too; a line of spaces is a symbol
        self.post_json("/config", {"symbols": "\n測試=★☆\n\n\n \n★\n\n\n"})
        self.assertEqual(self.get_json("/config")["symbols"], "測試=★☆\n \n★\n")

    def test_6_invalid_imports_leave_the_database_alone(self):
        before = self.db_digest()
        wrong_columns = os.path.join(self.tempdir.name, "wrong.sqlite3")
        with sqlite3.connect(wrong_columns) as conn:
            conn.execute("CREATE TABLE config_v1 (id INTEGER, value INTEGER)")
            conn.execute("CREATE TABLE userphrase_v1 (phrase TEXT)")
        conn.close()
        with open(wrong_columns, "rb") as f:
            wrong_columns_data = f.read()
        for name, data in (("garbage", os.urandom(4096)), ("wrong columns", wrong_columns_data)):
            with self.subTest(name):
                status, body = _post(self.opener, self.base + "/user_phrase_file",
                                     *_multipart("import_user_phrase", "x.sqlite3", data))
                self.assertEqual(status, 200)
                self.assertIn("格式錯誤", body)
                self.assertEqual(self.db_digest(), before)
                self.assertEqual(self.leftover_temp_files(), [])

    def test_7_valid_import_replaces_the_database(self):
        source = os.path.join(self.tempdir.name, "export.sqlite3")
        make_phrase_db(source, [("匯入", "ㄏㄨㄟˋ ㄖㄨˋ")])
        with open(source, "rb") as f:
            data = f.read()
        self.assertIn("測試", self.phrases())  # the tool's own libchewing context has the database open
        status, body = _post(self.opener, self.base + "/user_phrase_file",
                             *_multipart("import_user_phrase", "export.sqlite3", data))
        self.assertEqual(status, 200)
        self.assertIn("匯入詞庫成功", body)  # "format error" before, although the file was replaced
        self.assertEqual(self.phrases(), ["匯入"])
        self.assertEqual(self.leftover_temp_files(), [])


if __name__ == "__main__":
    unittest.main()
