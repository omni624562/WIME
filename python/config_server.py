#! python3
# 設定工具共用的本機 HTTP 伺服器骨架（token 認證、Host 檢查、閒置逾時、
# 開瀏覽器登入）。cinbase/configtool.py（大易/酷倉）與
# input_methods/chewing/config_tool.py（新酷音）只提供自己的 handler 與頁面。
# 位於 python/ 頂層；內嵌式 Python 的 ._pth 不會自動把指令碼目錄加入
# sys.path，呼叫端須自行把 python/ 加進 sys.path 再 import。
#
# 只用標準函式庫（http.server）：以前用 tornado 6.4.0，它沒有 multipart 解析等
# 多個 CVE 的修正，又一定要匯入 ssl，安裝檔因此得附上已停止支援的 OpenSSL 3.0；
# 換掉後安裝檔約小 1.5 MB、設定工具啟動快一倍。介面刻意跟以前的 tornado 版相同
# （BaseHandler / @authenticated / HTTPError / NoCacheStaticFileHandler /
# ConfigServerApp），兩個工具只需換掉 import。

import email.parser
import email.policy
import hmac  # constant-time token comparison
import http.cookies
import http.server
import json
import os
import re
import socket
import sys
import threading
import traceback
import urllib.parse
import uuid  # use to generate a random auth token

# 閒置多久（秒）沒有任何請求就結束伺服器行程；設定頁會定期打 /keep_alive。
SERVER_TIMEOUT = 120

# 請求本文上限：最大的是新酷音匯入的使用者詞庫（SQLite 檔），其餘都是幾 KB 的 JSON
MAX_BODY_SIZE = 64 * 1024 * 1024

# 靜態檔案的 Content-Type 用固定的表：mimetypes 會讀登錄檔（使用者的設定可能把
# .js 對應成 text/plain，頁面就不能執行），第一次查詢還要多花幾十 ms
CONTENT_TYPES = {
    ".html": "text/html; charset=UTF-8",
    ".htm": "text/html; charset=UTF-8",
    ".js": "application/javascript; charset=UTF-8",
    ".css": "text/css; charset=UTF-8",
    ".json": "application/json; charset=UTF-8",
    ".txt": "text/plain; charset=UTF-8",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".eot": "application/vnd.ms-fontobject",
    ".map": "application/json; charset=UTF-8",
}


class HTTPError(Exception):
    """A response with this status (and reason phrase), like tornado.web.HTTPError."""

    def __init__(self, status_code, reason=None):
        super().__init__(status_code, reason)
        self.status_code = status_code
        self.reason = reason


def authenticated(method):
    """Like @tornado.web.authenticated: requests without a valid token cookie get 403
    (there is no interactive login page; see BaseHandler.get_login_url)."""
    def wrapper(self, *args, **kwargs):
        if not self.current_user:
            self.get_login_url()
        return method(self, *args, **kwargs)
    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    return wrapper


class Request:
    """What a handler sees of the HTTP request (the subset of tornado's
    HTTPServerRequest the tools use)."""

    def __init__(self, method, target, headers, body):
        self.method = method
        self.uri = target
        parts = urllib.parse.urlsplit(target)
        self.path = parts.path
        self.query = parts.query
        self.query_arguments = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        self.headers = headers
        self.host = headers.get("Host", "")
        self.body = body
        self._files = None

    @property
    def files(self):
        """multipart/form-data uploads: {field: [{"filename", "body", "content_type"}]}"""
        if self._files is None:
            self._files = {}
            content_type = self.headers.get("Content-Type", "")
            if content_type.lower().startswith("multipart/form-data"):
                message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                    b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + self.body)
                for part in message.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    filename = part.get_filename()
                    if name is None or filename is None:
                        continue
                    self._files.setdefault(name, []).append({
                        "filename": filename,
                        "body": part.get_payload(decode=True) or b"",
                        "content_type": part.get_content_type(),
                    })
        return self._files

    def body_arguments(self):
        content_type = self.headers.get("Content-Type", "").lower()
        if self.method == "POST" and content_type.startswith("application/x-www-form-urlencoded"):
            return urllib.parse.parse_qs(self.body.decode("utf-8", "replace"), keep_blank_values=True)
        return {}


class RequestHandler:
    """Minimal tornado.web.RequestHandler: write()/set_header()/redirect()/cookies."""

    def __init__(self, application, request, **kwargs):
        self.application = application
        self.request = request
        self.settings = application.settings
        self._status = 200
        self._reason = None
        self._headers = {}
        self._cookies = []
        self._body = []
        self._current_user = None
        self._user_checked = False
        self.initialize(**kwargs)

    def initialize(self, **kwargs):
        pass

    def prepare(self):
        pass

    def get_current_user(self):
        return None

    @property
    def current_user(self):
        if not self._user_checked:
            self._current_user = self.get_current_user()
            self._user_checked = True
        return self._current_user

    def get_login_url(self):
        raise HTTPError(403)

    def get_cookie(self, name, default=None):
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.request.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return default
        morsel = cookie.get(name)
        return morsel.value if morsel is not None else default

    def set_cookie(self, name, value, httponly=False, samesite=None, path="/"):
        parts = ["%s=%s" % (name, value), "Path=%s" % path]
        if httponly:
            parts.append("HttpOnly")
        if samesite:
            parts.append("SameSite=%s" % samesite)
        self._cookies.append("; ".join(parts))

    def get_argument(self, name, default=None):
        for source in (self.request.body_arguments(), self.request.query_arguments):
            values = source.get(name)
            if values:
                return values[-1]
        if default is None:
            raise HTTPError(400, reason="Missing argument %s" % name)
        return default

    def set_status(self, status_code, reason=None):
        self._status = status_code
        self._reason = reason

    def set_header(self, name, value):
        self._headers[name] = str(value)

    def write(self, chunk):
        if isinstance(chunk, dict):
            chunk = json.dumps(chunk)
            self.set_header("Content-Type", "application/json; charset=UTF-8")
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        self._body.append(chunk)

    def finish(self):
        pass

    def redirect(self, url):
        self.set_status(302)
        self.set_header("Location", url)


class BaseHandler(RequestHandler):

    def get_current_user(self):  # override the login check
        # 認證：cookie 值必須與本次啟動產生的 access_token 完全相符（常數時間比對），
        # 而非只檢查 cookie 是否存在，否則任何非空 cookie 都能通過。
        token = self.get_cookie(self.settings["cookie_id"])
        expected = self.settings.get("access_token")
        if token and expected and hmac.compare_digest(token, expected):
            return token
        return None

    def get_login_url(self):
        # There is no interactive login page - auth only happens via the
        # one-time token URL from launch_browser(): unauthenticated requests get 403.
        raise HTTPError(403)

    def prepare(self):  # called before every request
        # 只接受來自本機迴路的 Host，阻擋 DNS rebinding（惡意網頁把自身網域指向 127.0.0.1）
        host = self.request.host.rsplit(":", 1)[0].strip("[]").lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise HTTPError(403)
        self.application.reset_timeout()  # reset the quit server timeout


class NoCacheStaticFileHandler(BaseHandler):
    """Files under one directory, never cached by the browser (the pages change
    with every WIME update)."""

    def initialize(self, path):
        self.root = os.path.realpath(path)

    def get(self, relative, *inner_groups):
        # 路由的第一個群組是檔案路徑；像 /((css|js)/.*) 這種內層群組不用
        relative = urllib.parse.unquote(relative)
        # 不可跳出根目錄：../、絕對路徑、磁碟代號（C:）、UNC、NTFS 資料流（file:stream）
        parts = relative.replace("\\", "/").split("/")
        if ":" in relative or relative.startswith("/") or ".." in parts:
            raise HTTPError(403)
        full = os.path.realpath(os.path.join(self.root, *parts))
        try:
            inside = os.path.commonpath([full, self.root]) == self.root
        except ValueError:  # different drives
            inside = False
        if not inside:
            raise HTTPError(403)
        if not os.path.isfile(full):
            raise HTTPError(404)
        with open(full, "rb") as f:
            data = f.read()
        self.set_header("Content-Type", CONTENT_TYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream"))
        self.set_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.set_header("Pragma", "no-cache")
        self.set_header("Expires", "0")
        self.write(data)


class KeepAliveHandler(BaseHandler):

    @authenticated
    def get(self):
        # the actual keep-alive is done inside BaseHandler.prepare()
        self.write('{"return":true}')


class LoginHandler(BaseHandler):

    def login(self, page_name):
        token = self.get_argument("token", "")
        if hmac.compare_digest(token, self.settings["access_token"]):
            # HttpOnly：前端不需讀取此 cookie；SameSite=Strict：阻擋跨站請求夾帶 cookie（CSRF）
            self.set_cookie(self.settings["cookie_id"], token, httponly=True, samesite="Strict")
            if page_name != "user_phrase_editor":
                page_name = self.settings["main_page"]
            self.redirect("/{}.html?v={}".format(page_name, token[:8]))

    def get(self, page_name):
        self.login(page_name)

    def post(self, page_name):
        self.login(page_name)


class _HTTPServer(http.server.ThreadingHTTPServer):
    # 瀏覽器會預先多開幾條連線：單執行緒的伺服器會卡在等待一條還沒送請求的連線。
    # 處理請求本身由 ConfigServerApp 的鎖一次一個（設定物件是共用的）
    daemon_threads = True
    # Windows 的 SO_REUSEADDR 讓別的程式也能綁同一個 port、搶走連線；改用獨占
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _RequestHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WIME"
    sys_version = ""
    timeout = 60  # an idle keep-alive connection is closed after this

    def do_GET(self):
        self.server.app.dispatch(self, "GET")

    def do_POST(self):
        self.server.app.dispatch(self, "POST")

    def log_message(self, format, *args):
        # pythonw.exe has no stderr; BaseHTTPRequestHandler would write every request to it
        pass


class ConfigServerApp:
    """handlers: the tool's own routes; /keep_alive and /login/<page> are added here.
    cookie_id: auth cookie name. main_page: page (without .html) to open after login.
    localdata_dir: where the POST-login fallback launch_<tool>.html is written."""

    def __init__(self, handlers, cookie_id, main_page, localdata_dir):
        # generate a new auth token using UUID
        self.access_token = uuid.uuid4().hex
        self.localdata_dir = localdata_dir
        self.port = 0
        self.tool_name = None
        self.server = None
        self._timer = None
        self._timer_lock = threading.Lock()
        self._request_lock = threading.Lock()
        handlers = list(handlers) + [
            (r"/keep_alive", KeepAliveHandler),  # keep the api server alive
            (r"/login/(.*)", LoginHandler),  # authentication
        ]
        self.handlers = []
        for spec in handlers:
            pattern, handler_class = spec[0], spec[1]
            kwargs = spec[2] if len(spec) > 2 else {}
            self.handlers.append((re.compile(pattern), handler_class, kwargs))
        self.settings = {
            "access_token": self.access_token,
            "cookie_id": cookie_id,
            "main_page": main_page,
        }

    # --- request handling -----------------------------------------------------

    def _read_body(self, raw):
        if raw.headers.get("Transfer-Encoding"):
            raise HTTPError(411)
        try:
            length = int(raw.headers.get("Content-Length") or 0)
        except ValueError:
            raise HTTPError(400)
        if length < 0:
            raise HTTPError(400)
        if length > MAX_BODY_SIZE:
            raise HTTPError(413)
        return raw.rfile.read(length) if length else b""

    def dispatch(self, raw, method):
        status, reason, headers, cookies, body = 500, None, {}, [], b""
        try:
            body_bytes = self._read_body(raw)
            request = Request(method, raw.path, raw.headers, body_bytes)
            for pattern, handler_class, kwargs in self.handlers:
                match = pattern.fullmatch(request.path)
                if match:
                    break
            else:
                raise HTTPError(404)
            with self._request_lock:
                handler = handler_class(self, request, **kwargs)
                handler.prepare()
                action = getattr(handler, method.lower(), None)
                if action is None:
                    raise HTTPError(405)
                action(*match.groups())
            status, reason = handler._status, handler._reason
            headers, cookies, body = handler._headers, handler._cookies, b"".join(handler._body)
        except HTTPError as e:
            status, reason = e.status_code, e.reason
            headers = {"Content-Type": "text/html; charset=UTF-8"}
            body = ("<html><title>%d</title><body>%d</body></html>" % (status, status)).encode("ascii")
        except Exception:
            # 不把 traceback（含安裝路徑）回傳給瀏覽器
            status = 500
            headers = {"Content-Type": "text/html; charset=UTF-8"}
            body = b"<html><title>500</title><body>500</body></html>"
            if sys.stderr is not None:
                traceback.print_exc()
        self._respond(raw, status, reason, headers, cookies, body)

    @staticmethod
    def _respond(raw, status, reason, headers, cookies, body):
        try:
            if reason:
                # 狀態列只能放可見的 ASCII
                reason = reason.encode("ascii", "replace").decode("ascii").replace("\r", " ").replace("\n", " ")
            raw.send_response(status, reason)
            for name, value in headers.items():
                raw.send_header(name, value)
            for cookie in cookies:
                raw.send_header("Set-Cookie", cookie)
            raw.send_header("X-Content-Type-Options", "nosniff")
            raw.send_header("Content-Length", str(len(body)))
            raw.end_headers()
            raw.wfile.write(body)
        except (ConnectionError, OSError):
            raw.close_connection = True

    # --- browser login ----------------------------------------------------------

    def _launch_file(self, tool_name):
        return os.path.join(self.localdata_dir, "launch_{}.html".format(tool_name))

    def launch_browser(self, tool_name):
        url = "http://127.0.0.1:{PORT}/login/{PAGE_NAME}?token={TOKEN}".format(
            PORT=self.port, PAGE_NAME=tool_name, TOKEN=self.access_token)
        try:
            os.startfile(url)
            return
        except Exception:
            pass

        user_html = """<html>
    <form id="auth" action="http://127.0.0.1:{PORT}/login/{PAGE_NAME}" method="POST">
        <input type="hidden" name="token" value="{TOKEN}">
    </form>
    <script type="text/javascript">
        document.getElementById("auth").submit();
    </script>
    </html>""".format(PORT=self.port, PAGE_NAME=tool_name, TOKEN=self.access_token)
        # use a local html file to send access token to our service via http POST for authentication.
        os.makedirs(self.localdata_dir, exist_ok=True)
        filename = self._launch_file(tool_name)
        with open(filename, "w") as f:
            f.write(user_html)
        os.startfile(filename)

    # --- server lifetime ----------------------------------------------------------

    def listen_on_random_port(self):
        # port 0：由系統挑一個沒在用的 port
        self.server = _HTTPServer(("127.0.0.1", 0), _RequestHandler)
        self.server.app = self
        self.port = self.server.server_address[1]
        return self.port

    def run(self, tool_name):
        self.tool_name = tool_name
        self.listen_on_random_port()
        self.launch_browser(tool_name)
        self.reset_timeout(start=True)
        try:
            self.server.serve_forever(poll_interval=0.5)
        finally:
            self.server.server_close()
            if self.tool_name:
                try:
                    os.remove(self._launch_file(self.tool_name))
                except OSError:
                    pass
        sys.exit(0)

    def reset_timeout(self, start=False):
        with self._timer_lock:
            if self._timer is None and not start:
                return
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(SERVER_TIMEOUT, self.quit)
            self._timer.daemon = True
            self._timer.start()

    def quit(self):
        # terminate the server process: serve_forever() returns in run(), which
        # removes the launch file and exits with 0 (an idle settings tool used to
        # stay alive, holding the installed python files open and blocking upgrades)
        if self.server is not None:
            threading.Thread(target=self.server.shutdown, daemon=True).start()
