"""Differential checks of the settings tools: the Python tools
(python/cinbase/configtool.py, python/input_methods/chewing/config_tool.py on
python/config_server.py) and their Rust port (cinbase-rs's wime-config.exe) get
the same requests, with the same files in their (temporary) APPDATA, and must
answer with the same bytes (status line, headers but Date, body) and leave
the same files behind, byte for byte.

The token and port differ between the two processes and are replaced by
placeholders before comparing.
"""

import os
import re
import shutil
import socket
import sqlite3
import tempfile
import unittest
import json

from config_tool_impls import IMPLEMENTATIONS, requires, start_tool
import chewing_harness


def raw_request(base, method, path, headers=None, body=b"", request_line=None):
    """One request on its own connection (Connection: close); the response as
    (status line, [(header, value)] without Date, body)."""
    host, port = base[len("http://"):].split(":")
    head = [request_line or "%s %s HTTP/1.1" % (method, path)]
    headers = dict(headers or {})
    headers.setdefault("Host", "127.0.0.1:%s" % port)
    headers.setdefault("Connection", "close")
    if body and "Content-Length" not in headers:
        headers["Content-Length"] = str(len(body))
    head += ["%s: %s" % item for item in headers.items() if item[1] is not None]
    data = ("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + body
    chunks = []
    with socket.create_connection((host, int(port)), timeout=30) as sock:
        sock.sendall(data)
        while True:
            try:
                chunk = sock.recv(65536)
            except ConnectionError:
                break
            if not chunk:
                break
            chunks.append(chunk)
    response = b"".join(chunks)
    head, _, body = response.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    headers = [tuple(line.split(": ", 1)) for line in lines[1:] if line]
    return lines[0], [h for h in headers if h[0] != "Date"], body


class Tool:
    """One implementation's running tool with its temporary folders."""

    def __init__(self, impl, ime, template):
        self.impl = impl
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        shutil.copytree(template, self.tempdir.name, dirs_exist_ok=True)  # copy2: same mtimes
        env = dict(os.environ)
        env["APPDATA"] = os.path.join(self.tempdir.name, "Roaming")
        env["LOCALAPPDATA"] = os.path.join(self.tempdir.name, "Local")
        env["USERPROFILE"] = os.path.join(self.tempdir.name, "Home")  # no legacy ~\PIME of the real user
        self.config_dir = os.path.join(env["APPDATA"], "PIME", ime)
        self.log = open(os.path.join(self.tempdir.name, "stderr.txt"), "w+", encoding="utf-8", errors="replace")
        self.proc, self.login_url = start_tool(impl, ime, "config", env, 60, stderr=self.log)
        match = re.match(r"(http://127\.0\.0\.1:(\d+))/login/[^?]+\?token=([0-9a-f]+)$", self.login_url)
        self.base, self.port, self.token = match.groups()

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.communicate()
        self.log.close()
        self.tempdir.cleanup()

    def normalize(self, data):
        pairs = ((self.token, "<TOKEN>"), (self.token[:8], "<TOKEN8>"), (self.port, "<PORT>"))
        for old, new in pairs:
            data = data.replace(old.encode(), new.encode()) if isinstance(data, bytes) else data.replace(old, new)
        return data

    def request(self, method, path, body=b"", headers=None, auth=True, request_line=None):
        headers = dict(headers or {})
        if auth:
            headers.setdefault("Cookie", "%s=%s" % (self.cookie_id, self.token))
        headers = {k: (self.normalize_back(v) if v else v) for k, v in headers.items()}
        status, response_headers, response_body = raw_request(
            self.base, method, path and self.normalize_back(path), headers, body,
            request_line and self.normalize_back(request_line))
        return (self.normalize(status), [(k, self.normalize(v)) for k, v in response_headers], self.normalize(response_body))

    def normalize_back(self, text):
        return text.replace("<TOKEN>", self.token).replace("<PORT>", self.port)

    def files(self):
        """{relative path: bytes} of everything in APPDATA and LOCALAPPDATA"""
        result = {}
        for top in ("Roaming", "Local"):
            root = os.path.join(self.tempdir.name, top)
            for folder, _, names in os.walk(root):
                for name in names:
                    path = os.path.join(folder, name)
                    rel = os.path.relpath(path, self.tempdir.name)
                    with open(path, "rb") as f:
                        result[rel] = f.read()
        return result


def sqlite_dump(data):
    """The schema and rows of an SQLite file: the bytes differ between SQLite
    versions (Python's sqlite3 and the bundled one of rusqlite), the contents may not"""
    folder = tempfile.mkdtemp()
    try:
        path = os.path.join(folder, "db.sqlite3")
        with open(path, "wb") as f:
            f.write(data)
        conn = sqlite3.connect(path)
        conn.text_factory = bytes  # the old dictionaries may hold phrases that are not UTF-8
        try:
            schema = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
            rows = {name: conn.execute('SELECT * FROM "%s"' % name.decode()).fetchall()
                    for type_, name, _ in schema if type_ == b"table"}
            return schema, rows
        finally:
            conn.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


class DiffTestBase(unittest.TestCase):
    IME = None
    COOKIE_ID = None
    maxDiff = None

    def prepare(self, config_dir):
        """Put the scenario's files into the (template) config folder."""

    def start(self):
        template = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(template.cleanup)
        for sub in ("Roaming", "Local", "Home"):
            os.makedirs(os.path.join(template.name, sub))
        config_dir = os.path.join(template.name, "Roaming", "PIME", self.IME)
        os.makedirs(config_dir)
        self.prepare(config_dir)
        self.tools = {}
        for impl in IMPLEMENTATIONS:
            tool = Tool(impl, self.IME, template.name)
            tool.cookie_id = self.COOKIE_ID
            self.addCleanup(tool.close)
            self.tools[impl] = tool

    def same(self, method, path, body=b"", headers=None, auth=True, request_line=None, check_files=True):
        """Send the request to both tools; the answers (and files) must be identical."""
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
            headers = dict(headers or {}, **{"Content-Type": "application/json"})
        replies = {impl: tool.request(method, path, body, headers, auth, request_line) for impl, tool in self.tools.items()}
        label = "%s %s %r" % (method, path, body[:80])
        self.assertEqual(replies["rust"], replies["python"], label)
        if check_files:
            self.assertFiles(label)
        return replies["python"]

    def assertFiles(self, label=""):
        files = {impl: tool.files() for impl, tool in self.tools.items()}
        self.assertEqual(sorted(files["rust"]), sorted(files["python"]), label)
        for name in files["python"]:
            rust, python = files["rust"][name], files["python"][name]
            if name.endswith(".sqlite3") and rust != python:
                rust, python = sqlite_dump(rust), sqlite_dump(python)
            self.assertEqual(rust, python, "%s: %s" % (label, name))


# --- 大易 / 酷倉 --------------------------------------------------------------------

CINBASE_POSTS = [
    {"config": {"candPerRow": 4, "imeDirName": "x", "curdir": "y", "_version": 1, "ignoreSaveList": [],
                "名稱": "測試", "f": 1.5, "big": 12345678901, "nested": {"b": 1, "a": [1, 2, {}], "e": []},
                "neg": -0.0, "exp": 1e300, "s": "tab\there \"quoted\" \\   \U0001F600"},
     "symbols": "a\nb\r\nc", "phrase": "測試 ㄘㄜˋ", "excludePhrase": "", "flangs": " x",
     "extendtable": "t\tab"},
    {"config": [1, "a", None, True]},
    {"config": "just a string"},
    {"symbols": 5},
    {"swkb": "ok", "fsymbols": ["not", "a", "str"], "flangs": "never written"},
    b"{",
    b"[]",
    b"",
    {"config": None, "swkb": "x"},
    b'\xef\xbb\xbf{"swkb": "with a BOM"}',
    {},
]


class CinbaseDiffMixin:
    COOKIE_ID = "cinbase_config_token"

    def test_get_config_and_saves(self):
        self.start()
        self.assertFiles("startup")
        self.same("GET", "/config")
        self.same("GET", "/config")  # the cincount cache, the reloaded settings
        for body in CINBASE_POSTS:
            self.same("POST", "/config", body)
        self.same("GET", "/config")  # what the saves left


@requires("rust")
class DayiEmptyDiffTests(CinbaseDiffMixin, DiffTestBase):
    IME = "chedayi"


@requires("rust")
class CangjieEmptyDiffTests(CinbaseDiffMixin, DiffTestBase):
    IME = "checj"


@requires("rust")
class DayiOddFilesDiffTests(CinbaseDiffMixin, DiffTestBase):
    IME = "chedayi"

    def prepare(self, config_dir):
        config = {"candPerRow": "5", "candPerPage": 0, "fontSize": 300.0, "defaultEnglish": "yes",
                  "imeDisplayName": 123, "candidateMaxWidth": 300, "candidateStyle": "x",
                  "candidateColors": {"a": "#fff"}, "unknownKey": [1, {"b": None}], "messageDurationTime": 3,
                  "selCinType": 2, "selRCinType": 1.0, "名": "值", "selKeyType": True,
                  "hideCompositionLabel": 1.5, "candidateOpacity": "abc"}
        with open(os.path.join(config_dir, "config.json"), "w", encoding="utf-8-sig") as f:
            json.dump(config, f, ensure_ascii=False)
        with open(os.path.join(config_dir, "symbols.dat"), "wb") as f:
            f.write("﻿A\r\nB\rC\n測試".encode("utf-8"))
        with open(os.path.join(config_dir, "swkb.dat"), "wb") as f:
            f.write(b"\xff\xfeA")  # not UTF-8: ""
        with open(os.path.join(config_dir, "userphrase.dat"), "w", encoding="utf-8") as f:
            f.write("測試 ㄘㄜˋ\n")
        os.makedirs(os.path.join(config_dir, "flangs.dat"))  # unreadable: "", and saving it fails


@requires("rust")
class CangjieBrokenConfigDiffTests(CinbaseDiffMixin, DiffTestBase):
    IME = "checj"

    def prepare(self, config_dir):
        with open(os.path.join(config_dir, "config.json"), "wb") as f:
            f.write(b'{"candPerRow": 4,')  # backed up as config.json.broken-<mtime>
        with open(os.path.join(config_dir, "extendtable.dat"), "wb") as f:
            f.write("酷倉 a\r\n".encode("cp950"))


@requires("rust")
class DayiNotAnObjectDiffTests(CinbaseDiffMixin, DiffTestBase):
    IME = "chedayi"

    def prepare(self, config_dir):
        with open(os.path.join(config_dir, "config.json"), "w", encoding="ascii") as f:
            f.write('[["selCinType", 99]]')


@requires("rust")
class DayiAnsiConfigDiffTests(CinbaseDiffMixin, DiffTestBase):
    IME = "chedayi"

    def prepare(self, config_dir):
        with open(os.path.join(config_dir, "config.json"), "wb") as f:
            f.write('{"imeDisplayName": "大易", "selCinType": 99, "candidateMaxWidth": 300, "candidateMaxWidthMigrated": 1}'.encode("cp950"))


# --- 新酷音 ---------------------------------------------------------------------------

CHEWING_CONFIG_POSTS = [
    {"config": {"candPerPage": 7, "名": "值", "f": 2.0, "nested": {"z": 1, "a": [1, {}]}}, "swkb": "B ☆",
     "symbols": "\n測試=★☆\n\n \n★\n"},
    {"config": [1]},
    {"config": "x"},
    {"symbols": 1},
    {"symbols": "長=" + "\U0001F600" * 5000},
    {"swkb": 1},
    {"symbols": "a\r\nb\r\n\r\n"},
    b"nope",
    b"[1]",
    {},
]

CHEWING_PHRASE_POSTS = [
    {"add": [{"phrase": "編輯", "bopomofo": "ㄅㄧㄢ ㄐㄧˊ"}]},
    {"add": [{"phrase": "錯", "bopomofo": "abc"}]},
    {"remove": [{"phrase": "不存在", "bopomofo": "ㄅㄨˋ ㄘㄨㄣˊ ㄗㄞˋ"}]},
    {"remove": [{"phrase": "編輯", "bopomofo": "ㄅㄧㄢ ㄐㄧˊ"}]},
    {"add": [{"phrase": "x"}]},
    {"add": "abc"},
    {"add": ""},
    {"add": None},
    {"add": [{"phrase": 1, "bopomofo": "ㄅㄧㄢ"}]},
    {"add": [["phrase"]]},
    {},
    [],
]


def _multipart(field, filename, data):
    boundary = "----wimediff"
    head = ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n" % (boundary, field, filename)).encode("utf-8")
    return head + data + ("\r\n--%s--\r\n" % boundary).encode("utf-8"), "multipart/form-data; boundary=" + boundary


class ChewingDiffMixin:
    IME = "chewing"
    COOKIE_ID = "chewing_config_token"

    def test_config_phrases_and_files(self):
        self.start()
        self.assertFiles("startup")  # the default config.json, converted symbols.dat ...
        self.same("GET", "/config")
        for body in CHEWING_CONFIG_POSTS:
            self.same("POST", "/config", body)
        self.same("GET", "/config")
        self.same("GET", "/user_phrases")  # converts an old chewing.sqlite3
        for body in CHEWING_PHRASE_POSTS:
            self.same("POST", "/user_phrases", body)
        self.same("GET", "/user_phrases")
        self.same("GET", "/user_phrase_file")

        legacy = os.path.join(tempfile.mkdtemp(), "old.sqlite3")
        self.addCleanup(shutil.rmtree, os.path.dirname(legacy), True)
        chewing_harness.make_legacy_user_db(legacy, chewing_harness.LEGACY_PHRASES[1:3])
        with open(legacy, "rb") as f:
            sqlite_data = f.read()
        for name, data in (("garbage", os.urandom(1000)), ("old export", sqlite_data),
                           ("damaged chewing.dat", b"\x30\x82\x10\x00\x0c\x04CHEW" + b"\0" * 64)):
            with self.subTest(name):
                body, content_type = _multipart("import_user_phrase", "x.dat", data)
                self.same("POST", "/user_phrase_file", body, {"Content-Type": content_type})
                self.same("GET", "/user_phrases")
        self.same("POST", "/user_phrase_file", b"not multipart", {"Content-Type": "text/plain"})
        body, content_type = _multipart("other_field", "x.dat", sqlite_data)
        self.same("POST", "/user_phrase_file", body, {"Content-Type": content_type})


@requires("rust")
class ChewingEmptyDiffTests(ChewingDiffMixin, DiffTestBase):
    pass


@requires("rust")
class ChewingOldFilesDiffTests(ChewingDiffMixin, DiffTestBase):

    def prepare(self, config_dir):
        config = {"candidateMinWidth": None, "candPerPage": "5", "candPerRow": 3, "candidateMaxWidth": 300,
                  "candidateStyle": {"a": 1, "b": "x", "c": True}, "unknown": [1], "selKeyType": 9,
                  "candidateKeyStyle": "x", "easySymbolsWithShift": 0, "fontSize": 18.0}
        with open(os.path.join(config_dir, "config.json"), "w", encoding="utf-8-sig") as f:
            json.dump(config, f)
        with open(os.path.join(config_dir, "symbols.dat"), "wb") as f:
            f.write("測試=★\r\n\r\n…\r\n".encode("cp950"))  # ANSI: converted (and backed up) on start
        with open(os.path.join(config_dir, "swkb.dat"), "w", encoding="utf-8-sig") as f:
            f.write("A ★\n")
        legacy = os.path.join(config_dir, "chewing.sqlite3")
        chewing_harness.make_legacy_user_db(legacy, chewing_harness.LEGACY_PHRASES[:2])
        with sqlite3.connect(legacy) as conn:  # a row whose phrase is not UTF-8
            columns = ",".join(["time", "user_freq", "max_freq", "orig_freq", "length"] +
                               ["phone_%d" % i for i in range(11)])
            conn.execute("INSERT INTO userphrase_v1 (%s, phrase) SELECT %s, CAST(X'E6B8ACFF' AS TEXT) "
                         "FROM userphrase_v1 LIMIT 1" % (columns, columns))
        conn.close()


@requires("rust")
class ChewingBrokenConfigDiffTests(ChewingDiffMixin, DiffTestBase):

    def prepare(self, config_dir):
        with open(os.path.join(config_dir, "config.json"), "wb") as f:
            f.write(b"\x81\xff{not json")
        with open(os.path.join(config_dir, "swkb.dat"), "wb") as f:
            f.write(b"\x81\xffA")  # neither UTF-8 nor (probably) the ANSI code page


# --- the HTTP layer -------------------------------------------------------------------

PROTOCOL_REQUESTS = [
    # (method, path, body, headers, auth, request line)
    ("GET", "/config", b"", None, False, None),
    ("GET", "/keep_alive", b"", None, False, None),
    ("GET", "/config", b"", {"Host": "evil.example.com"}, True, None),
    ("GET", "/config", b"", {"Host": "[::1]:80"}, True, None),
    ("GET", "/config", b"", {"Host": "LOCALHOST"}, True, None),
    ("GET", "/config", b"", {"Cookie": "junk; x=1"}, False, None),
    ("GET", "/config", b"", {"Cookie": "a=b; <COOKIE>=0123"}, False, None),
    ("GET", "/no_such_route", b"", None, True, None),
    ("GET", "/keep_alive", b"", None, True, None),
    ("POST", "/keep_alive", b"x", None, True, None),
    ("GET", "/version.txt", b"", None, False, None),
    ("GET", "/versionXtxt", b"", None, False, None),
    ("GET", "/css/..%2f..%2fconfigtool.py", b"", None, True, None),
    ("GET", "/js/..%5c..%5cconfig_server.py", b"", None, True, None),
    ("GET", "/css/C:%5cWindows%5cwin.ini", b"", None, True, None),
    ("GET", "/css/x.css:stream", b"", None, True, None),
    ("GET", "/css/", b"", None, True, None),
    ("GET", "/css/does-not-exist.css", b"", None, True, None),
    ("GET", "/css/%E6%B8%AC.css", b"", None, True, None),
    ("POST", "/config.html", b"", None, True, None),
    ("GET", "/login/config?token=" + "0" * 32, b"", None, False, None),
    ("GET", "/login/config", b"", None, False, None),
    ("GET", "/login/config?token=%E4%B8%AD", b"", None, False, None),
    ("GET", "/login/whatever?token=<TOKEN>", b"", None, False, None),
    ("GET", "/login/user_phrase_editor?token=<TOKEN>&token=<TOKEN>", b"", None, False, None),
    ("POST", "/login/config", b"token=<TOKEN>", {"Content-Type": "application/x-www-form-urlencoded"}, False, None),
    ("POST", "/login/config?token=<TOKEN>", b"token=bad", {"Content-Type": "application/x-www-form-urlencoded"}, False, None),
    ("POST", "/login/config?token=<TOKEN>", b"token=bad", {"Content-Type": "text/plain"}, False, None),
    ("GET", "/config", b"", {"Cookie": "<COOKIE>=é"}, False, None),
    ("GET", "/config", b"", {"Cookie": '<COOKIE>="<TOKEN>"'}, False, None),
    ("PUT", "/config", b"", None, True, None),
    ("POST", "/config", b"", {"Transfer-Encoding": "chunked"}, True, None),
    ("POST", "/config", b"", {"Content-Length": "abc"}, True, None),
    ("POST", "/config", b"", {"Content-Length": "-1"}, True, None),
    ("POST", "/config", b"", {"Content-Length": str(1 << 40)}, True, None),
    ("GET", None, b"", None, True, "GET /config HTTP/2.0"),
    ("GET", None, b"", None, True, "GET /config HTTP/1.x"),
    ("GET", None, b"", None, True, "GARBAGE"),
    ("GET", None, b"", None, True, "GET /keep_alive HTTP/1.0"),
    ("GET", None, b"", None, True, "GET //keep_alive HTTP/1.1"),
    ("GET", None, b"", None, True, "GET /keep_alive?x=1#frag HTTP/1.1"),
    ("GET", None, b"", None, True, "GET http://127.0.0.1:<PORT>/keep_alive HTTP/1.1"),
]


class ProtocolDiffMixin:
    STATIC = ()

    def test_protocol_and_static_files(self):
        self.start()
        for method, path, body, headers, auth, request_line in PROTOCOL_REQUESTS + [("GET", p, b"", None, False, None) for p in self.STATIC]:
            if headers and "Cookie" in headers:
                headers = dict(headers, Cookie=headers["Cookie"].replace("<COOKIE>", self.COOKIE_ID))
            with self.subTest(path=path or request_line, headers=headers):
                self.same(method, path, body, headers, auth, request_line, check_files=False)
        self.assertFiles()


@requires("rust")
class CinbaseProtocolDiffTests(ProtocolDiffMixin, DiffTestBase):
    IME = "chedayi"
    COOKIE_ID = "cinbase_config_token"
    STATIC = ("/config.html", "/config.js", "/configXjs", "/config.htm", "/help.htm", "/css/config.css",
              "/js/config.js", "/fonts/glyphicons-halflings-regular.woff2", "/data/msymbols.json",
              "/data/../data/msymbols.json", "/icon.ico", "/user_phrase_editor.html", "/login/x.html")


@requires("rust")
class ChewingProtocolDiffTests(ProtocolDiffMixin, DiffTestBase):
    IME = "chewing"
    COOKIE_ID = "chewing_config_token"
    STATIC = ("/config_tool.html", "/user_phrase_editor.html", "/css/config.css", "/js/config.js",
              "/images/logo.png", "/js/jquery-ui-1.13.2/jquery-ui.min.js", "/config_tool.py", "/icon.ico")


if __name__ == "__main__":
    unittest.main()
