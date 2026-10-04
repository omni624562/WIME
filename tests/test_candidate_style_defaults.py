"""The built-in candidate-window styles in PIMETextService/PIMEClient.cpp must be
the ones the settings pages offer and preview: 選字符 word-first and 名稱標籤
accent.

Client::Client() applies them to 大易/酷倉/新酷音 until the backend's customizeUI
arrives, and 新酷音 sends no header style at all, so its window keeps the
built-in one. candidateKeyStyleValue() falls back to the default for a name it
does not know. While the built-in defaults were keycap/badge, the window did not
look like the settings pages' previews."""

import os
import re
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
CLIENT_CPP = os.path.join(ROOT, "PIMETextService", "PIMEClient.cpp")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class BuiltInCandidateStyleTests(unittest.TestCase):
    def setUp(self):
        self.cpp = _read(CLIENT_CPP)

    def modern_defaults(self):
        ctor = re.search(r"\nClient::Client\(.*?\n\}", self.cpp, re.S).group(0)
        return re.search(r"if \(usesModernCandidateDefault\(guid_\)\) \{(.*?)\n\t\}", ctor, re.S).group(1)

    def test_modern_ime_defaults_are_word_first_and_accent(self):
        block = self.modern_defaults()
        self.assertEqual(re.findall(r"setCandidateKeyStyle\(Ime::CandidateWindow::(\w+)\)", block),
                         ["KeyStyleWordFirst"])
        self.assertEqual(re.findall(r"setCandidateHeaderStyle\(Ime::CandidateWindow::(\w+)\)", block),
                         ["HeaderLabelAccent"])

    def test_unknown_key_style_falls_back_to_word_first(self):
        body = re.search(r"static int candidateKeyStyleValue\(.*?\n\}", self.cpp, re.S).group(0)
        # the last return is the fallback, after every named style
        self.assertEqual(re.findall(r"return Ime::CandidateWindow::(\w+);", body)[-1], "KeyStyleWordFirst")
        # an explicit keycap from the backend still selects keycap
        self.assertRegex(body, r'name == "keycap"\)\s*return Ime::CandidateWindow::KeyStyleKeycap;')


if __name__ == "__main__":
    unittest.main()
