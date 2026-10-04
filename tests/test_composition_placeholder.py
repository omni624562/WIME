"""新酷音 composes a lone bopomofo (shown in the candidate header) as a U+200B
placeholder that only the backend's next reply replaces
(python/input_methods/chewing/chewing_ime.py). When PIMETextService ends the
composition without such a reply, TextService::endCompositionDroppingPlaceholder()
clears a placeholder-only composition first. Ending it with plain
endComposition() left an invisible character in the user's text (search, URLs,
file names, code): the reconnect path of PR #26 (Client::discardOrphanedUi()),
closing the keyboard and switching to another keyboard (libIME2's Deactivate())
all did.

The C++ cannot run here, so the first tests read its source the way
test_candidate_theme.py does; the last ones check with the real libchewing that
the backend still composes exactly the placeholder the C++ looks for."""

import os
import re
import unittest

import cinbase_harness


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
TEXT_SERVICE_CPP = os.path.join(ROOT, "PIMETextService", "PIMETextService.cpp")
CLIENT_CPP = os.path.join(ROOT, "PIMETextService", "PIMEClient.cpp")

# every key of the standard layout that types one bopomofo symbol
BOPOMOFO_KEYS = "1qaz2wsxedcrfv5tgbyhnujm8ik,9ol.0p;/-"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _function(source, signature):
    """The body of a function defined at column 0, without its // comments."""
    match = re.search(r"\n" + re.escape(signature) + r"\s*\{(.*?)\n\}", source, re.S)
    if match is None:
        raise AssertionError("%s not found" % signature)
    return re.sub(r"//[^\n]*", "", match.group(1))


def _cpp_placeholder_char():
    match = re.search(r"static const wchar_t kZeroWidthSpace = (0x[0-9A-Fa-f]+);", _read(TEXT_SERVICE_CPP))
    if match is None:
        raise AssertionError("kZeroWidthSpace not found in PIMETextService.cpp")
    return chr(int(match.group(1), 16))


class PlaceholderSourceTests(unittest.TestCase):
    def setUp(self):
        self.service_cpp = _read(TEXT_SERVICE_CPP)
        self.client_cpp = _read(CLIENT_CPP)

    def assertDropsPlaceholder(self, code, where):
        self.assertIn("endCompositionDroppingPlaceholder()", code, where)
        # a direct endComposition() would leave the placeholder in the document
        self.assertNotRegex(code, r"\bendComposition\(", where)

    def test_lost_backend_client_drops_the_placeholder(self):
        self.assertDropsPlaceholder(_function(self.client_cpp, "void Client::discardOrphanedUi()"),
                                    "Client::discardOrphanedUi()")

    def test_closing_the_keyboard_drops_the_placeholder(self):
        self.assertDropsPlaceholder(
            _function(self.service_cpp, "void TextService::onKeyboardStatusChanged(bool opened)"),
            "TextService::onKeyboardStatusChanged()")

    def test_switching_to_another_keyboard_drops_the_placeholder(self):
        code = _function(self.service_cpp, "STDMETHODIMP TextService::Deactivate()")
        # before libIME2's Deactivate(), which ends the composition as is
        self.assertLess(code.index("endCompositionDroppingPlaceholder();"),
                        code.index("Ime::TextService::Deactivate()"))

    def test_placeholder_is_cleared_in_the_compositions_document_before_ending_it(self):
        code = _function(self.service_cpp, "void TextService::endCompositionDroppingPlaceholder()")
        # the composition's own document first: onSetFocus() may discard a
        # composition left in a document that no longer has the focus
        self.assertLess(code.index("compositionContext_"), code.index("currentContext()"))
        self.assertRegex(code, r"if \(isPlaceholderComposition\(compositionString\(session\)\)\)\s*"
                               r"setCompositionString\(session, L\"\", 0\);")
        session = re.search(r"RequestEditSession\(clientId\(\), clearPlaceholder, TF_ES_SYNC \| TF_ES_READWRITE", code)
        self.assertIsNotNone(session, "the placeholder must be cleared in a synchronous read/write session")
        self.assertLess(session.start(), code.index("endComposition(context);"))
        # the remembered document is set when the composition starts and dropped
        # whenever it ends, also when the app ends it
        self.assertRegex(_function(self.service_cpp, "void TextService::startComposition(ITfContext* context)"),
                         r"compositionContext_ = isComposing\(\) \? context : nullptr;")
        self.assertIn("compositionContext_ = nullptr;",
                      _function(self.service_cpp, "void TextService::onCompositionTerminated(bool forced)"))

    def test_only_zero_width_spaces_count_as_the_placeholder(self):
        self.assertEqual(_cpp_placeholder_char(), "\u200b")
        body = _function(self.service_cpp, "static bool isPlaceholderComposition(const std::wstring& text)")
        # real preedit text (你, 大易 codes) stays in the document as typed, and an
        # empty composition has nothing to clear
        self.assertRegex(body, r"return !text\.empty\(\) && "
                               r"text\.find_first_not_of\(kZeroWidthSpace\) == std::wstring::npos;")


class BackendPlaceholderTests(unittest.TestCase):
    """The placeholder the C++ clears is the one the real 新酷音 backend sends."""

    @classmethod
    def setUpClass(cls):
        cls.appdata = cinbase_harness.IsolatedAppData()
        import chewing_harness
        cls.ch = chewing_harness
        cls.ch.load_module()

    @classmethod
    def tearDownClass(cls):
        cls.ch.close_all()
        cls.appdata.close()

    def tearDown(self):
        self.ch.close_all()

    def test_every_lone_bopomofo_is_composed_as_the_placeholder(self):
        placeholder = _cpp_placeholder_char()
        for key in BOPOMOFO_KEYS:
            with self.subTest(key=key):
                reply = self.ch.press(self.ch.make_service(), key)
                self.assertEqual(reply.get("compositionString"), placeholder)
                self.assertTrue(reply.get("showCandidates"))
                self.assertRegex(reply.get("candidateHeader", ""), r"[\u3105-\u3129]$")
                self.ch.close_all()

    def test_a_composed_character_is_not_the_placeholder(self):
        service = self.ch.make_service()
        self.ch.type_keys(service, list("su3"))
        self.assertEqual(service.compositionString, "你")
        # ㄋ after it: the composition holds 你 and the bopomofo goes to the header
        reply = self.ch.press(service, "s")
        self.assertEqual(reply.get("compositionString"), "你")
        self.assertNotEqual(set(reply.get("compositionString")), {_cpp_placeholder_char()})


if __name__ == "__main__":
    unittest.main()
