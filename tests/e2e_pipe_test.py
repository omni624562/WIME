"""End-to-end tests against the deployed PIME stack.

Talks to the live PIMELauncher named pipe exactly like PIMETextService
does. Skipped automatically when the launcher pipe is not available, so
the suite stays safe to run on machines without a deployed build.

Run with:  python -m unittest tests.e2e_pipe_test -v
"""
import json
import os
import time
import unittest

PIPE = r"\\.\pipe\{}\PIME\Launcher".format(os.environ.get("USERNAME", ""))
CHEWING_GUID = "{f80736aa-28db-423a-92c9-5540f501c939}"
CHEDAYI_GUID = "{e6943374-70f5-4540-aa0f-3205c7dcca84}"
DAYI_CAND_SELKEYS = "␣'[]-\\"  # ␣'[]-\


def open_pipe(retries=20, delay=0.1):
    # the launcher creates the next pipe listener instance shortly after a
    # client connects, so a brand-new connection may need a brief retry
    last_error = None
    for _ in range(retries):
        try:
            return open(PIPE, "r+b", buffering=0)
        except OSError as error:
            last_error = error
            time.sleep(delay)
    raise last_error


_PIPE_AVAILABLE = None


def pipe_available():
    global _PIPE_AVAILABLE
    if _PIPE_AVAILABLE is None:
        try:
            f = open_pipe(retries=3)
            f.close()
            _PIPE_AVAILABLE = True
        except OSError:
            _PIPE_AVAILABLE = False
    return _PIPE_AVAILABLE


class PipeClient:
    """Minimal PIMETextService stand-in speaking the launcher protocol."""

    def __init__(self, guid):
        self.guid = guid
        self.seq = 0
        self.f = open_pipe()

    def close(self):
        try:
            self.f.close()
        except OSError:
            pass

    def rpc(self, payload, timeout=10.0):
        self.seq += 1
        payload = dict(payload)
        payload["seqNum"] = self.seq
        self.f.write((json.dumps(payload) + "\n").encode("utf-8"))
        line = b""
        deadline = time.time() + timeout
        while not line.endswith(b"\n"):
            chunk = self.f.read(1)
            if not chunk:
                raise RuntimeError("pipe closed")
            line += chunk
            if time.time() > deadline:
                raise RuntimeError("rpc timeout")
        reply = json.loads(line.decode("utf-8"))
        if reply.get("seqNum") != self.seq:
            raise RuntimeError("seqNum mismatch: %r" % reply)
        return reply

    def init(self):
        return self.rpc({
            "method": "init",
            "id": self.guid,
            "isWindows8Above": True,
            "isMetroApp": False,
            "isUiLess": False,
            "isConsole": False,
        })

    def activate(self):
        return self.rpc({"method": "onActivate", "isKeyboardOpen": True})

    def key(self, char, key_code=None, method="filterKeyDown", legacy_states=False):
        # sparse object mirrors what the C++ client sends; legacy_states
        # exercises the backward-compatible 256-element array path
        return self.rpc({
            "method": method,
            "charCode": ord(char),
            "keyCode": key_code if key_code is not None else ord(char.upper()),
            "repeatCount": 1,
            "scanCode": 0,
            "isExtended": False,
            "keyStates": [0] * 256 if legacy_states else {},
        })

    def press(self, char, key_code=None):
        """filterKeyDown + onKeyDown, mirroring the real client."""
        replies = []
        filtered = self.key(char, key_code, "filterKeyDown")
        replies.append(filtered)
        if filtered.get("return"):
            replies.append(self.key(char, key_code, "onKeyDown"))
        return replies


@unittest.skipUnless(pipe_available(), "PIMELauncher pipe not available")
class ChewingE2ETests(unittest.TestCase):
    def test_basic_lifecycle_and_typing(self):
        c = PipeClient(CHEWING_GUID)
        try:
            self.assertTrue(c.init().get("success"))
            self.assertTrue(c.activate().get("success"))
            replies = c.press("a", 0x41)
            for reply in replies:
                self.assertTrue(reply.get("success"))
            # bopomofo 'a' (ㄇ) must enter the composition, not pass through
            self.assertTrue(replies[0].get("return"))
            # legacy full-array keyStates must keep working too
            legacy = c.key("a", 0x41, legacy_states=True)
            self.assertTrue(legacy.get("success"))
            self.assertTrue(legacy.get("return"))
            self.assertTrue(c.rpc({"method": "onDeactivate"}).get("success"))
        finally:
            c.close()


@unittest.skipUnless(pipe_available(), "PIMELauncher pipe not available")
class DayiSelKeysE2ETests(unittest.TestCase):
    """Regression for: 大易候選窗的選字符有時顯示 1234567890。

    Every dayi client must receive setSelKeys with the dayi key set when
    it starts composing, regardless of what other clients did before.
    """

    def collect_selkeys(self, client, presses):
        seen = []
        for char, key_code in presses:
            for reply in client.press(char, key_code):
                value = reply.get("setSelKeys")
                if value:
                    seen.append(value)
        return seen

    def test_every_dayi_client_gets_dayi_selkeys(self):
        a = PipeClient(CHEDAYI_GUID)
        b = PipeClient(CHEDAYI_GUID)
        try:
            for c in (a, b):
                self.assertTrue(c.init().get("success"))
                self.assertTrue(c.activate().get("success"))

            # client A types first and switches the (formerly shared) cache
            a_selkeys = self.collect_selkeys(a, [("v", 0x56)])
            self.assertIn(DAYI_CAND_SELKEYS, a_selkeys,
                          "client A never received dayi selkeys: %r" % a_selkeys)
            # clear A's composition
            a.press("\x1b", 0x1B)

            # client B starts composing afterwards: it MUST also receive
            # the dayi selkeys (with the shared cache it never did and the
            # candidate window showed 12345)
            b_selkeys = self.collect_selkeys(b, [("v", 0x56)])
            self.assertIn(DAYI_CAND_SELKEYS, b_selkeys,
                          "client B stuck on default 1234567890: %r" % b_selkeys)
            b.press("\x1b", 0x1B)
        finally:
            a.close()
            b.close()

    def test_dayi_candidate_page_within_selkey_count(self):
        c = PipeClient(CHEDAYI_GUID)
        try:
            self.assertTrue(c.init().get("success"))
            self.assertTrue(c.activate().get("success"))
            # 'v' 單根有多個候選；空白鍵叫出候選窗
            c.press("v", 0x56)
            replies = c.press(" ", 0x20)
            page = None
            for reply in replies:
                if isinstance(reply.get("candidateList"), list) and reply["candidateList"]:
                    page = reply["candidateList"]
            if page is not None:
                self.assertLessEqual(
                    len(page), len(DAYI_CAND_SELKEYS),
                    "candidate page larger than dayi selkey count: %r" % page)
            c.press("\x1b", 0x1B)
        finally:
            c.close()


@unittest.skipUnless(pipe_available(), "PIMELauncher pipe not available")
class DayiMenuE2ETests(unittest.TestCase):
    """功能選單重新設計：麵包屑 header、子頁「↩ 返回」項目。"""

    def last_value(self, replies, key):
        value = None
        for reply in replies:
            if key in reply:
                value = reply[key]
        return value

    def wait_table_ready(self, client, timeout=30.0):
        """剛重啟的後端可能還在載入碼表（每鍵回「正在載入…」訊息）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            replies = client.press("v", 0x56)
            loading = any(
                "載入" in reply.get("showMessage", {}).get("message", "")
                for reply in replies if isinstance(reply.get("showMessage"), dict)
            )
            client.press("\x1b", 0x1B)
            if not loading:
                return
            time.sleep(0.5)
        self.fail("dayi table still loading after %.0fs" % timeout)

    def test_menu_breadcrumb_and_back_item(self):
        c = PipeClient(CHEDAYI_GUID)
        try:
            self.assertTrue(c.init().get("success"))
            self.assertTrue(c.activate().get("success"))
            self.wait_table_ready(c)

            # ``` 進入功能選單
            replies = []
            for _ in range(3):
                replies = c.press("`", 0xC0)
            header = self.last_value(replies, "candidateHeader")
            items = self.last_value(replies, "candidateList")
            self.assertEqual(header, "選單 功能選單")
            self.assertIn("特殊符號", items)
            self.assertNotIn("↩ 返回", items)  # 主選單沒有返回項

            # 選 1（特殊符號）→ 子頁第一項是「↩ 返回」，header 顯示路徑
            replies = c.press("1", 0x31)
            header = self.last_value(replies, "candidateHeader")
            items = self.last_value(replies, "candidateList")
            self.assertEqual(header, "選單 特殊符號")
            self.assertEqual(items[0], "↩ 返回")

            # 選 1（↩ 返回）→ 回主選單
            replies = c.press("1", 0x31)
            header = self.last_value(replies, "candidateHeader")
            self.assertEqual(header, "選單 功能選單")

            c.press("\x1b", 0x1B)
        finally:
            c.close()


@unittest.skipUnless(pipe_available(), "PIMELauncher pipe not available")
class RecoveryE2ETests(unittest.TestCase):
    def test_new_connection_after_idle_backend_exit(self):
        # Repeated fresh connections must always succeed: the launcher
        # restarts the backend on demand after it exits when idle.
        for _ in range(2):
            c = PipeClient(CHEWING_GUID)
            try:
                self.assertTrue(c.init().get("success"))
                self.assertTrue(c.rpc({"method": "ping"}).get("success"))
            finally:
                c.close()


if __name__ == "__main__":
    unittest.main()
