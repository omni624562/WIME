"""The candidate window highlights the item the backend's Enter would pick, also
when a list kept from an earlier reply is laid out again.

新酷音 keeps its candidate list and cursor when the app ends the composition
(clicking elsewhere in a browser or Word) or the keyboard is closed and opened
again; pressing ` once more re-shows the menu with a bare showCandidates:true,
no list and no cursor. Client::updateCandidateList() then laid out the kept list
with TextService::updateCandidates(), whose CandidateWindow::clear() put the
highlight back on the first item while the backend's cursor stayed put: after
` ↓ (數學符號) and the app ending the composition, ` highlighted 「…」 and Enter
opened 數學符號. 大易, 酷倉 and 新酷音 also send the shown list again unchanged,
without a cursor, to refresh the header.

TextService keeps candidateCursor_ next to candidates_ and highlights it whenever
the list is laid out. The C++ cannot run here, so the first tests read its
source the way test_composition_placeholder.py does; the last ones check with
the real 新酷音 backend that it re-shows the menu exactly that way."""

import os
import re
import unittest

import cinbase_harness


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
TEXT_SERVICE_CPP = os.path.join(ROOT, "PIMETextService", "PIMETextService.cpp")
TEXT_SERVICE_H = os.path.join(ROOT, "PIMETextService", "PIMETextService.h")
CLIENT_CPP = os.path.join(ROOT, "PIMETextService", "PIMEClient.cpp")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _function(source, signature):
    """The body of a function defined at column 0, without its // comments."""
    match = re.search(r"\n" + re.escape(signature) + r"\s*\{(.*?)\n\}", source, re.S)
    if match is None:
        raise AssertionError("%s not found" % signature)
    return re.sub(r"//[^\n]*", "", match.group(1))


class CandidateCursorSourceTests(unittest.TestCase):
    def setUp(self):
        self.service_cpp = _read(TEXT_SERVICE_CPP)
        self.client_cpp = _read(CLIENT_CPP)
        self.update_list = _function(self.client_cpp,
                                     "void Client::updateCandidateList(json& msg, Ime::EditSession* session)")

    def test_the_cursor_is_kept_next_to_the_list(self):
        self.assertRegex(_read(TEXT_SERVICE_H),
                         r"std::vector<std::wstring> candidates_;[^\n]*\n(?:\s*//[^\n]*\n)*\s*int candidateCursor_;")
        self.assertIn("candidateCursor_(0),", self.service_cpp)

    def test_laying_out_the_list_highlights_the_kept_cursor(self):
        code = _function(self.service_cpp, "void TextService::updateCandidates(Ime::EditSession* session)")
        # after clear() and the items, before the window is sized and drawn
        self.assertLess(code.index("candidateWindow_->clear();"), code.index("candidateWindow_->add("))
        self.assertLess(code.index("candidateWindow_->add("),
                        code.index("candidateWindow_->setCurrentSel(candidateCursor_);"))
        self.assertLess(code.index("candidateWindow_->setCurrentSel(candidateCursor_);"),
                        code.index("candidateWindow_->recalculateSize();"))

    def test_a_reply_cursor_is_stored_before_the_list_is_laid_out(self):
        code = self.update_list
        self.assertRegex(code, r"const bool hasCandidateCursor = candidateCursorVal\.is_number_integer\(\);\s*"
                               r"if \(hasCandidateCursor\) \{\s*"
                               r"textService_->candidateCursor_ = candidateCursorVal\.get<int>\(\);")
        self.assertLess(code.index("textService_->candidateCursor_ = candidateCursorVal.get<int>();"),
                        code.index('msg["candidateList"]'))
        # it still moves the highlight of a window that is already up
        self.assertRegex(code, r"if \(hasCandidateCursor && textService_->candidateWindow_ != nullptr\) \{\s*"
                               r"textService_->candidateWindow_->setCurrentSel\(textService_->candidateCursor_\);")

    def test_a_new_list_without_a_cursor_starts_at_its_first_item(self):
        # the shown list sent again unchanged (a header refresh) keeps the cursor
        self.assertRegex(self.update_list,
                         r"if \(!hasCandidateCursor && newCandidates != candidates\) \{\s*"
                         r"textService_->candidateCursor_ = 0;\s*\}\s*"
                         r"candidates = std::move\(newCandidates\);")

    def test_a_list_kept_without_a_new_one_is_laid_out_when_shown(self):
        self.assertRegex(self.update_list,
                         r"else if \(!wasShowingCandidates && textService_->showingCandidates\(\)\) \{\s*"
                         r"textService_->updateCandidates\(session\);")

    def test_dropping_the_list_drops_its_cursor(self):
        # a message that replaces the list
        self.assertRegex(self.update_list, r"else if \(hasCandidateMessage\) \{\s*"
                                           r"textService_->candidates_\.clear\(\);\s*"
                                           r"textService_->candidateCursor_ = 0;")
        # the UI of a lost backend client
        self.assertRegex(_function(self.client_cpp, "void Client::discardOrphanedUi()"),
                         r"textService_->candidates_\.clear\(\);\s*textService_->candidateCursor_ = 0;")
        # focus loss: the backends drop their cursor there too
        self.assertIn("candidateCursor_ = 0;", _function(self.service_cpp, "void TextService::onKillFocus()"))

    def test_hiding_the_window_keeps_the_cursor(self):
        # a forced end of the composition only hides the window while 新酷音
        # keeps its list and cursor for the next `
        self.assertNotIn("candidateCursor_", _function(self.service_cpp, "void TextService::hideCandidates()"))


class ChewingReshowTests(unittest.TestCase):
    """The 新酷音 replies the C++ above has to handle: the ` menu re-shown
    without a list or a cursor, with the backend's cursor where it was."""

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

    def open_menu_and_move_down(self):
        service = self.ch.make_service()
        menu = self.ch.press(service, "`")
        self.assertTrue(menu.get("showCandidates"))
        self.assertEqual(menu.get("candidateCursor"), 0)
        cursor = self.ch.press(service, "DOWN").get("candidateCursor")
        self.assertGreater(cursor, 0)
        return service, cursor

    def assertReshownWithoutCursor(self, service, cursor, hide):
        hide(service)
        self.assertFalse(service.showCandidates)
        reply = self.ch.press(service, "`")
        self.assertTrue(reply.get("showCandidates"))
        # nothing that would make the C++ lay out a new list or move the highlight
        self.assertNotIn("candidateList", reply)
        self.assertNotIn("candidateCursor", reply)
        self.assertEqual(service.candidateCursor, cursor)
        return self.ch.press(service, "ENTER")

    def test_menu_reshown_after_the_app_ends_the_composition(self):
        service, cursor = self.open_menu_and_move_down()
        picked = self.assertReshownWithoutCursor(
            service, cursor, lambda s: self.ch.request(s, "onCompositionTerminated", forced=True))
        self.assertEqual(picked.get("candidateList"), self.enter_without_hiding())

    def test_menu_reshown_after_the_keyboard_is_closed_and_opened(self):
        service, cursor = self.open_menu_and_move_down()

        def toggle(s):
            self.ch.request(s, "onKeyboardStatusChanged", opened=False)
            self.ch.request(s, "onKeyboardStatusChanged", opened=True)

        picked = self.assertReshownWithoutCursor(service, cursor, toggle)
        self.assertEqual(picked.get("candidateList"), self.enter_without_hiding())

    def enter_without_hiding(self):
        """The submenu Enter opens at that cursor when nothing hid the menu."""
        service, _ = self.open_menu_and_move_down()
        submenu = self.ch.press(service, "ENTER").get("candidateList")
        self.assertTrue(submenu)
        return submenu


if __name__ == "__main__":
    unittest.main()
