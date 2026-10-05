"""A right click on the 中/英 icon in the taskbar (the Windows 8+ input mode icon,
"windows-mode-icon") asks the backend for a menu through Client::onMenu() and
shows it: PIMETextService/PIMELangBarButton.cpp LangBarButton::OnClick().

- When no menu came back, OnClick() fell through to libIME2's
  LangBarButton::OnClick(), which sent onCommand(COMMAND_RIGHT_CLICK). Its
  reconnect reached a fresh backend that switched 中/英 instead of showing
  anything.
- No menu came back mostly because the onMenu request itself broke the pipe (a
  launcher restart or upgrade while the app kept focus). That failure removes
  every language bar button, the icon just clicked included; once the fallback
  was gone, nothing reconnected until the next key or focus ping, so the icon
  could not even be clicked again. Client::onMenu() now reconnects and asks once
  more, which puts the buttons back and still opens the menu on that click.

The C++ cannot run here, so these tests read its source the way
test_composition_placeholder.py does."""

import os
import re
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
CLIENT_CPP = os.path.join(ROOT, "PIMETextService", "PIMEClient.cpp")
BUTTON_CPP = os.path.join(ROOT, "PIMETextService", "PIMELangBarButton.cpp")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _function(source, signature):
    """The body of a function defined at column 0, without its // comments."""
    match = re.search(r"\n" + re.escape(signature) + r"\s*\{(.*?)\n\}", source, re.S)
    if match is None:
        raise AssertionError("%s not found" % signature)
    return re.sub(r"//[^\n]*", "", match.group(1))


def _block(code, header):
    """The statements inside the braces that follow header."""
    start = code.find(header)
    if start < 0:
        raise AssertionError("%s not found" % header)
    start = code.index("{", start + len(header)) + 1
    depth = 1
    for pos in range(start, len(code)):
        if code[pos] == "{":
            depth += 1
        elif code[pos] == "}":
            depth -= 1
            if depth == 0:
                return code[start:pos]
    raise AssertionError("unbalanced braces after %s" % header)


class ModeIconRightClickTests(unittest.TestCase):
    def setUp(self):
        on_click = _function(_read(BUTTON_CPP),
                             "STDMETHODIMP LangBarButton::OnClick(TfLBIClick click, POINT pt, const RECT* prcArea)")
        self.branch = _block(on_click, "if (id_ == WINDOWS_MODE_ICON_ID && click == TF_LBI_CLK_RIGHT)")

    def test_a_right_click_never_becomes_a_command(self):
        # every path out of the branch returns, also when no menu came back
        self.assertRegex(self.branch.rstrip(), r"return S_OK;$")
        self.assertNotIn("Ime::LangBarButton::OnClick", self.branch)
        self.assertNotIn("COMMAND_RIGHT_CLICK", self.branch)

    def test_the_menu_does_not_take_the_foreground(self):
        # OnClick() runs on the focused app's UI thread, which already owns the
        # foreground. Making the invisible transient window the foreground one
        # (as the audit suggested) would take the focus from the app (TSF
        # kill-focus) and may not give it back after DestroyWindow().
        self.assertIn("TrackPopupMenu(", self.branch)
        self.assertNotIn("SetForegroundWindow", self.branch)


class OnMenuReconnectTests(unittest.TestCase):
    def setUp(self):
        self.client_cpp = _read(CLIENT_CPP)
        self.body = _function(self.client_cpp, "HMENU Client::onMenu(LangBarButton* btn)")

    def test_a_request_that_lost_the_backend_client_is_sent_once_more(self):
        self.assertEqual(self.body.count("sendOnMenu("), 2, "exactly one retry")
        retry = _block(_block(self.body, "if (hadConnectedPipe)"), "if (pipe_ == INVALID_HANDLE_VALUE)")
        # the old client's composition and candidates go first, as before any
        # request that reconnects (callKeyRpcMethod(), onSetFocus())
        self.assertLess(retry.index("discardOrphanedUi();"), retry.index("sendOnMenu(buttonId, result)"))

    def test_only_a_pipe_that_was_connected_is_retried(self):
        # with no pipe the first request already tried to reconnect; trying again
        # would only double the wait while the launcher is not running
        self.assertLess(self.body.index("const bool hadConnectedPipe = pipe_ != INVALID_HANDLE_VALUE;"),
                        self.body.index("sendOnMenu("))

    def test_a_restarted_backend_that_no_longer_knows_this_client_reconnects_too(self):
        stale = _block(self.body, "if (pipe_ != INVALID_HANDLE_VALUE && isRecoverableBackendStateFailure(result))")
        self.assertRegex(stale, r"^\s*closeRpcConnection\(\);\s*resetTextServiceState\(\);\s*$")
        # ... so that the retry below sees the closed pipe
        self.assertLess(self.body.index("isRecoverableBackendStateFailure(result)"),
                        self.body.index("if (pipe_ == INVALID_HANDLE_VALUE)"))

    def test_the_button_is_not_used_after_the_first_request(self):
        # a failed request removes every button and releases btn with them
        self.assertEqual(re.findall(r"\bbtn\b", self.body), ["btn"])
        self.assertLess(self.body.index("btn->id()"), self.body.index("sendOnMenu("))

    def test_the_reconnect_puts_the_buttons_back(self):
        # what the retry relies on: a reconnect while activated sends onActivate,
        # whose reply adds the language bar buttons again
        connect = _function(self.client_cpp, "bool Client::waitForRpcConnection(int connectTimeoutMs, int connectAttempts)")
        self.assertRegex(connect, r"(?s)if \(!init\(\)\) \{.*?\}\s*if \(isActivated_\) \{\s*onActivate\(\);")


if __name__ == "__main__":
    unittest.main()
