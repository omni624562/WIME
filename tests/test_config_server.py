"""End-to-end tests for the two settings tools (cinbase/configtool.py for
大易/酷倉 and input_methods/chewing/config_tool.py for 新酷音), which share
python/config_server.py -- and for their Rust port, cinbase-rs's
wime-config.exe: every test class runs once per implementation
(config_tool_impls.py; the Rust classes are named Rust*).

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

from config_tool_impls import DRIVER, PYTHON_DIR, ROOT, requires, start_tool  # noqa: F401 (DRIVER: older importers)

IDLE_TIMEOUT = 3.0


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
    IMPL = "python"    # or "rust" (config_tool_impls)
    IME = None         # "chedayi", ... or "chewing"
    TOOL = "config"
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
        cls.proc, cls.login_url = start_tool(cls.IMPL, cls.IME, cls.TOOL, env, IDLE_TIMEOUT)
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

    def test_6b_paths_outside_the_page_folders_are_not_served(self):
        opener, _ = self._logged_in_opener()
        for path in ("/css/..%2f..%2fconfigtool.py", "/css/..%2F..%2F..%2Fconfig_server.py",
                     "/js/..%5c..%5cconfig_server.py", "/css/%2e%2e/%2e%2e/version.txt.bak",
                     "/css/C:%5cWindows%5cwin.ini", "/no_such_route", "/config_server.py"):
            with self.subTest(path=path):
                self.assertIn(_get(opener, self.base + path).status, (403, 404))

    def test_6c_login_by_form_post_and_method_checks(self):
        # the fallback launch_<tool>.html posts the token as a form
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())
        request = urllib.request.Request(self.base + "/login/" + self.MAIN_PAGE, method="POST",
                                         data=("token=" + self.token).encode("ascii"),
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.code, 302)
        self.assertEqual([c.name for c in jar], [self.COOKIE_ID])
        logged_in = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        # POST to a GET-only resource
        request = urllib.request.Request(self.base + "/keep_alive", method="POST", data=b"x")
        try:
            response = logged_in.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.code, 405)

    def test_6d_oversized_body_is_refused_unread(self):
        import socket
        host, port = self.base[len("http://"):].split(":")
        with socket.create_connection((host, int(port)), timeout=10) as sock:
            sock.sendall(("POST /config HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                          "Content-Length: %d\r\n\r\n" % (1 << 40)).encode("ascii"))
            status_line = sock.makefile("rb").readline().decode("ascii")
        self.assertIn(" 413 ", status_line)

    def _raw_status(self, head, body=b""):
        import socket
        host, port = self.base[len("http://"):].split(":")
        with socket.create_connection((host, int(port)), timeout=30) as sock:
            sock.sendall(head.encode("ascii") + body)
            return sock.makefile("rb").readline().decode("ascii")

    def test_6f_big_bodies_only_for_a_logged_in_dictionary_upload(self):
        size = 5 * 1024 * 1024   # over MAX_SMALL_BODY_SIZE (4 MB), under MAX_BODY_SIZE
        cookie = "Cookie: %s=%s\r\n" % (self.COOKIE_ID, self.token)
        # refused before the body is read: without a login, or not the upload
        for path, extra in (("/user_phrase_file", ""), ("/config", cookie), ("/config", "")):
            with self.subTest(path=path, logged_in=bool(extra)):
                status = self._raw_status("POST %s HTTP/1.1\r\nHost: 127.0.0.1\r\n%sContent-Length: %d\r\n\r\n"
                                          % (path, extra, size))
                self.assertIn(" 413 ", status)
        # the logged-in upload is read (and then judged on its content)
        status = self._raw_status("POST /user_phrase_file HTTP/1.1\r\nHost: 127.0.0.1\r\n%s"
                                  "Content-Type: application/octet-stream\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
                                  % (cookie, size), b"x" * size)
        self.assertNotIn(" 413 ", status)

    def test_6g_posts_from_other_origins_are_refused(self):
        opener, _ = self._logged_in_opener()
        host = self.base[len("http://"):]

        def post(headers):
            request = urllib.request.Request(self.base + "/config", method="POST", data=b"{}",
                                             headers=dict({"Content-Type": "application/json"}, **headers))
            try:
                response = opener.open(request, timeout=10)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.code

        for headers in ({"Origin": "http://127.0.0.1:1"}, {"Origin": "http://evil.example"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "same-site"}, {"Sec-Fetch-Site": "cross-site"},
                        {"Origin": "http://" + host, "Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(post(headers), 403)
        for headers in ({}, {"Origin": "http://" + host, "Sec-Fetch-Site": "same-origin"},
                        {"Origin": "HTTP://" + host.upper()}, {"Sec-Fetch-Site": "none"}):
            with self.subTest(headers=headers):
                self.assertEqual(post(headers), 200)

    def test_6e_no_python_details_in_headers(self):
        reply = _get(urllib.request.build_opener(), self.base + "/config")
        self.assertNotIn("Python", reply.headers.get("Server", ""))
        self.assertNotIn("Tornado", reply.headers.get("Server", ""))
        self.assertEqual(reply.headers.get("X-Content-Type-Options"), "nosniff")

    def test_9_process_exits_on_idle_timeout(self):
        # Runs last (unittest sorts by name). No requests from here on, so the
        # tool must terminate by itself shortly after IDLE_TIMEOUT.
        try:
            code = self.proc.wait(timeout=IDLE_TIMEOUT + 10)
        except subprocess.TimeoutExpired:
            self.fail("settings tool still running %.0fs after its idle timeout" % (IDLE_TIMEOUT + 10))
        self.assertEqual(code, 0, self.proc.stderr.read())


class CinbaseConfigToolTests(ConfigToolTestMixin, unittest.TestCase):
    IME = "chedayi"
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
    IME = "chewing"
    MAIN_PAGE = "config_tool"
    COOKIE_ID = "chewing_config_token"


@requires("rust")
class RustCinbaseConfigToolTests(CinbaseConfigToolTests):
    IMPL = "rust"


@requires("rust")
class RustChewingConfigToolTests(ChewingConfigToolTests):
    IMPL = "rust"


class LaunchFallbackMixin:
    """When the login URL cannot be opened, the tool writes launch_<tool>.html,
    a page that POSTs the token, opens it, and removes it when it exits."""
    IMPL = "python"
    IME = None
    TOOL = "config"
    LAUNCH_FILE = None  # relative to the temporary folder
    PAGE = None

    def test_login_page_posts_the_token_and_is_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ)
            env["APPDATA"] = os.path.join(temp, "Roaming")
            env["LOCALAPPDATA"] = os.path.join(temp, "Local")
            proc, path = start_tool(self.IMPL, self.IME, self.TOOL, env, IDLE_TIMEOUT,
                                    extra_env={"WIME_CONFIG_TEST_LAUNCH": "fail-url"})
            try:
                self.assertEqual(os.path.normcase(path), os.path.normcase(os.path.join(temp, self.LAUNCH_FILE)))
                with open(path, "rb") as f:
                    html = f.read().decode("ascii")
                match = re.search(r'action="(http://127\.0\.0\.1:\d+)/login/(\w+)" method="POST">\r\n'
                                  r'        <input type="hidden" name="token" value="([0-9a-f]{32})">', html)
                self.assertTrue(match, html)
                base, page, token = match.groups()
                self.assertEqual(page, self.PAGE)
                expected = ('<html>\n    <form id="auth" action="%s/login/%s" method="POST">\n'
                            '        <input type="hidden" name="token" value="%s">\n    </form>\n'
                            '    <script type="text/javascript">\n        document.getElementById("auth").submit();\n'
                            '    </script>\n    </html>' % (base, page, token)).replace("\n", "\r\n")
                self.assertEqual(html, expected)
                jar = http.cookiejar.CookieJar()
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())
                request = urllib.request.Request(base + "/login/" + page, data=("token=" + token).encode("ascii"),
                                                 method="POST",
                                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
                try:
                    response = opener.open(request, timeout=10)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    self.assertEqual(response.code, 302)
                    self.assertTrue(response.headers["Location"].startswith("/%s.html" % page))
                self.assertEqual(proc.wait(timeout=IDLE_TIMEOUT + 10), 0)
                self.assertFalse(os.path.exists(path))  # removed when the tool exits
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.communicate()


class CinbaseLaunchFallbackTests(LaunchFallbackMixin, unittest.TestCase):
    IME = "checj"
    LAUNCH_FILE = os.path.join("Roaming", "PIME", "checj", "launch_config.html")
    PAGE = "config"


class ChewingLaunchFallbackTests(LaunchFallbackMixin, unittest.TestCase):
    IME = "chewing"
    TOOL = "user_phrase_editor"
    LAUNCH_FILE = os.path.join("Local", "PIME", "chewing", "launch_user_phrase_editor.html")
    PAGE = "user_phrase_editor"


@requires("rust")
class RustCinbaseLaunchFallbackTests(CinbaseLaunchFallbackTests):
    IMPL = "rust"


@requires("rust")
class RustChewingLaunchFallbackTests(ChewingLaunchFallbackTests):
    IMPL = "rust"


if __name__ == "__main__":
    unittest.main()
