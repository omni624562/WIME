"""End-to-end tests for the two settings tools (cinbase/configtool.py for
大易/酷倉 and input_methods/chewing/config_tool.py for 新酷音), which share
python/config_server.py.

Each test class starts the real tool as a separate process (browser launch
stubbed out, APPDATA redirected to a temp dir, idle timeout shortened) and
talks HTTP to it, covering:
- the token-in-URL login and cookie flags,
- rejection of unauthenticated / wrong-token / non-loopback-Host requests,
- that the main page and every local asset it references are served,
- that a 大易/酷倉 save that cannot write config.json answers HTTP 500 (it
  used to answer {"return": true}, so the page said 設定已套用),
- that the process really exits on its idle timeout (it used to leak forever
  because quit() called IOLoop.close() inside the running loop).
"""

import http.cookiejar
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
IDLE_TIMEOUT = 3.0

DRIVER = r"""
import os, runpy, sys
python_dir, script, idle = sys.argv[1], sys.argv[2], float(sys.argv[3])
tool_args = sys.argv[4:]
sys.path.insert(0, python_dir)
import config_server
config_server.SERVER_TIMEOUT = idle
os.startfile = lambda url, *a, **k: print("URL " + url, flush=True)
sys.argv = [script] + tool_args
runpy.run_path(script, run_name="__main__")
"""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class _Reply:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body


def _get(opener, url, headers=None):
    """GET url and return a _Reply with the body already read and the connection closed."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        response = opener.open(request, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return _Reply(getattr(response, "status", None) or response.code, response.headers, response.read())


class ConfigToolTestMixin:
    SCRIPT = None      # path relative to python/
    TOOL_ARGS = None   # argv after the script
    MAIN_PAGE = None   # page the login redirects to (without .html)
    COOKIE_ID = None

    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        env = dict(os.environ)
        env["APPDATA"] = os.path.join(cls.tempdir.name, "Roaming")
        env["LOCALAPPDATA"] = os.path.join(cls.tempdir.name, "Local")
        os.makedirs(env["APPDATA"])
        os.makedirs(env["LOCALAPPDATA"])
        cls.proc = subprocess.Popen(
            [sys.executable, "-c", DRIVER, PYTHON_DIR,
             os.path.join(PYTHON_DIR, *cls.SCRIPT.split("/")), str(IDLE_TIMEOUT)] + cls.TOOL_ARGS,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True, encoding="utf-8")
        line = cls.proc.stdout.readline()
        if not line.startswith("URL "):
            cls.proc.kill()
            raise RuntimeError("tool did not start: %r %s" % (line, cls.proc.stderr.read()))
        cls.login_url = line[4:].strip()
        match = re.match(r"(http://127\.0\.0\.1:\d+)/login/[^?]+\?token=([0-9a-f]+)$", cls.login_url)
        cls.base, cls.token = match.group(1), match.group(2)

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            cls.proc.kill()
        cls.proc.communicate()
        cls.tempdir.cleanup()

    def _logged_in_opener(self):
        jar = http.cookiejar.CookieJar()
        no_redirect = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())
        reply = _get(no_redirect, self.login_url)
        self.assertEqual(reply.status, 302)
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), reply

    def test_1_unauthenticated_api_is_rejected(self):
        opener = urllib.request.build_opener()
        self.assertEqual(_get(opener, self.base + "/config").status, 403)
        self.assertEqual(_get(opener, self.base + "/keep_alive").status, 403)

    def test_2_non_loopback_host_is_rejected(self):
        opener = urllib.request.build_opener()
        self.assertEqual(_get(opener, self.base + "/config", {"Host": "evil.example.com"}).status, 403)

    def test_3_wrong_token_grants_nothing(self):
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())
        self.assertNotEqual(_get(opener, self.base + "/login/config?token=" + "0" * 32).status, 302)
        self.assertEqual(len(jar), 0)

    def test_4_login_sets_hardened_cookie_and_redirects(self):
        _, reply = self._logged_in_opener()
        self.assertTrue(reply.headers["Location"].startswith("/%s.html" % self.MAIN_PAGE))
        cookie = reply.headers["Set-Cookie"]
        self.assertIn(self.COOKIE_ID + "=" + self.token, cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_5_authenticated_config_and_keep_alive(self):
        opener, _ = self._logged_in_opener()
        reply = _get(opener, self.base + "/config")
        self.assertEqual(reply.status, 200)
        self.assertIsInstance(json.loads(reply.body.decode("utf-8"))["config"], dict)
        self.assertEqual(_get(opener, self.base + "/keep_alive").status, 200)

    def test_6_main_page_and_all_local_assets_are_served(self):
        opener, _ = self._logged_in_opener()
        reply = _get(opener, "%s/%s.html" % (self.base, self.MAIN_PAGE))
        self.assertEqual(reply.status, 200)
        html = reply.body.decode("utf-8")
        refs = set(re.findall(r'(?:src|href)="([^"#?]+)', html))
        local = sorted(ref for ref in refs if not re.match(r"(https?:|mailto:|javascript:|//)", ref))
        self.assertTrue(local, "no local assets found on the main page")
        missing = [ref for ref in local if _get(opener, self.base + "/" + ref.lstrip("./")).status != 200]
        self.assertEqual(missing, [], "assets referenced by the page but not served")

    def test_9_process_exits_on_idle_timeout(self):
        # Runs last (unittest sorts by name). No requests from here on, so the
        # tool must terminate by itself shortly after IDLE_TIMEOUT.
        try:
            code = self.proc.wait(timeout=IDLE_TIMEOUT + 10)
        except subprocess.TimeoutExpired:
            self.fail("settings tool still running %.0fs after its idle timeout" % (IDLE_TIMEOUT + 10))
        self.assertEqual(code, 0, self.proc.stderr.read())


class CinbaseConfigToolTests(ConfigToolTestMixin, unittest.TestCase):
    SCRIPT = "cinbase/configtool.py"
    TOOL_ARGS = ["config", "chedayi"]
    MAIN_PAGE = "config"
    COOKIE_ID = "cinbase_config_token"

    def test_7_only_installed_reverse_lookup_tables_are_offered(self):
        if PYTHON_DIR not in sys.path:
            sys.path.insert(0, PYTHON_DIR)
        from cinbase.config import RCIN_FILE_LIST
        opener, _ = self._logged_in_opener()
        data = json.loads(_get(opener, self.base + "/config").body.decode("utf-8"))
        json_dir = os.path.join(PYTHON_DIR, "cinbase", "json")
        expected = [i for i, name in enumerate(RCIN_FILE_LIST) if os.path.exists(os.path.join(json_dir, name))]
        self.assertEqual(data["rcinAvailable"], expected)

    def test_8_failed_save_is_reported(self):
        opener, _ = self._logged_in_opener()
        config_dir = os.path.join(self.tempdir.name, "Roaming", "PIME", "chedayi")
        config_file = os.path.join(config_dir, "config.json")

        def post(data):
            request = urllib.request.Request(self.base + "/config", data=json.dumps(data).encode("utf-8"),
                                             method="POST", headers={"Content-Type": "application/json"})
            try:
                response = opener.open(request, timeout=10)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return getattr(response, "status", None) or response.code

        def saved_config():
            with open(config_file, encoding="utf-8") as f:
                return json.load(f)

        self.assertEqual(post({"config": {"candidatePerRow": 4}}), 200)
        self.assertEqual(saved_config(), {"candidatePerRow": 4})

        # Another process reading config.json (Python's open(), like the backend
        # does, shares read/write but not delete) makes os.replace() fail.
        with open(config_file, "rb"):
            status = post({"config": {"candidatePerRow": 5}, "symbols": "測試=★"})
        self.assertEqual(status, 500)  # 200 {"return": true} before, shown as 設定已套用
        self.assertEqual(saved_config(), {"candidatePerRow": 4})
        # config.json is written first, so nothing after it was saved either
        self.assertFalse(os.path.exists(os.path.join(config_dir, "symbols.dat")))
        self.assertEqual([name for name in os.listdir(config_dir) if name.endswith(".tmp")], [])

        self.assertEqual(post({"config": {"candidatePerRow": 5}}), 200)  # once the file is free again
        self.assertEqual(saved_config(), {"candidatePerRow": 5})


class ChewingConfigToolTests(ConfigToolTestMixin, unittest.TestCase):
    SCRIPT = "input_methods/chewing/config_tool.py"
    TOOL_ARGS = ["config"]
    MAIN_PAGE = "config_tool"
    COOKIE_ID = "chewing_config_token"


if __name__ == "__main__":
    unittest.main()
