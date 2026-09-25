#! python3
# 設定工具共用的本機 HTTP 伺服器骨架（token 認證、Host 檢查、閒置逾時、
# 開瀏覽器登入）。cinbase/configtool.py（大易/酷倉）與
# input_methods/chewing/config_tool.py（新酷音）原本各複製一份，認證重導向與
# 逾時不結束的 bug 都得修兩次；現在兩者只提供自己的 handler 與頁面。
# 位於 python/ 頂層；內嵌式 Python 的 ._pth 不會自動把指令碼目錄加入
# sys.path，呼叫端須自行把 python/ 加進 sys.path 再 import。

import hmac  # constant-time token comparison
import os
import random
import sys
import uuid  # use to generate a random auth token

import tornado.ioloop
import tornado.web

# 閒置多久（秒）沒有任何請求就結束伺服器行程；設定頁會定期打 /keep_alive。
SERVER_TIMEOUT = 120


class BaseHandler(tornado.web.RequestHandler):

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
        # one-time token URL from launch_browser(). @tornado.web.authenticated
        # would otherwise redirect unauthenticated GETs to the settings-value
        # "login_url", which points nowhere and previously 404'd instead of
        # cleanly rejecting the request.
        raise tornado.web.HTTPError(403)

    def prepare(self):  # called before every request
        # 只接受來自本機迴路的 Host，阻擋 DNS rebinding（惡意網頁把自身網域指向 127.0.0.1）
        host = self.request.host.rsplit(":", 1)[0].strip("[]").lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise tornado.web.HTTPError(403)
        self.application.reset_timeout()  # reset the quit server timeout


class NoCacheStaticFileHandler(tornado.web.StaticFileHandler):

    def set_extra_headers(self, path):
        self.set_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.set_header("Pragma", "no-cache")
        self.set_header("Expires", "0")


class KeepAliveHandler(BaseHandler):

    @tornado.web.authenticated
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


class ConfigServerApp(tornado.web.Application):
    """handlers: the tool's own routes; /keep_alive and /login/<page> are added here.
    cookie_id: auth cookie name. main_page: page (without .html) to open after login.
    localdata_dir: where the POST-login fallback launch_<tool>.html is written."""

    def __init__(self, handlers, cookie_id, main_page, localdata_dir):
        # generate a new auth token using UUID
        self.access_token = uuid.uuid4().hex
        self.localdata_dir = localdata_dir
        self.timeout_handler = None
        self.port = 0
        self.tool_name = None
        handlers = list(handlers) + [
            (r"/keep_alive", KeepAliveHandler),  # keep the api server alive
            (r"/login/(.*)", LoginHandler),  # authentication
        ]
        super().__init__(
            handlers,
            access_token=self.access_token,
            cookie_id=cookie_id,
            main_page=main_page,
            # 正式環境關閉 debug：避免未攔截例外把 Python traceback（含路徑）回傳瀏覽器
            debug=False)

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

    def listen_on_random_port(self):
        random.seed()
        while True:
            port = random.randint(1025, 65535)
            try:
                self.listen(port, "127.0.0.1")
                break
            except OSError:  # it's possible that the port we want to use is already in use
                continue
        self.port = port
        return port

    def run(self, tool_name):
        self.tool_name = tool_name
        self.listen_on_random_port()
        self.launch_browser(tool_name)

        # setup the main event loop
        loop = tornado.ioloop.IOLoop.current()
        self.timeout_handler = loop.call_later(SERVER_TIMEOUT, self.quit)
        loop.start()

    def reset_timeout(self):
        loop = tornado.ioloop.IOLoop.current()
        if self.timeout_handler:
            loop.remove_timeout(self.timeout_handler)
            self.timeout_handler = loop.call_later(SERVER_TIMEOUT, self.quit)

    def quit(self):
        # terminate the server process
        # stop(), not close(): this runs as a callback inside the running loop, and
        # closing a running asyncio loop raises RuntimeError, so sys.exit() was never
        # reached - every settings session leaked a python.exe (holding the installed
        # python files open and blocking installer upgrades).
        tornado.ioloop.IOLoop.current().stop()
        if self.tool_name:
            try:
                os.remove(self._launch_file(self.tool_name))
            except OSError:
                pass
        sys.exit(0)
