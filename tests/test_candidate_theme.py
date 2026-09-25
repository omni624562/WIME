"""Candidate-window theme names are resolved in three places that must agree:
PIMETextService/PIMEClient.cpp candidateThemeColors() (actual rendering),
python/candidate_theme.py (what the backend sends), and the settings pages'
candidate_appearance.js canonicalCandidateThemeName() (what the UI shows).
A name one of them doesn't know used to render light while the page showed
"System"."""

import os
import re
import sys
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

import candidate_theme  # noqa: E402

APPEARANCE_JS = [
    os.path.join(PYTHON_DIR, "cinbase", "config", "js", "candidate_appearance.js"),
    os.path.join(PYTHON_DIR, "input_methods", "chewing", "js", "candidate_appearance.js"),
]


class _Cfg:
    def __init__(self, theme):
        self.candidateTheme = theme


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class ResolveCandidateThemeTests(unittest.TestCase):
    def resolve(self, theme, system_light=False):
        with mock.patch.object(candidate_theme, "systemPrefersLightTheme", return_value=system_light):
            return candidate_theme.resolveCandidateTheme(_Cfg(theme))

    def test_known_names_pass_through(self):
        for name in ("Pure Black", "pureblack", "Sepia Dim", "High Contrast", "Plum", "Light", "Graphite"):
            self.assertEqual(self.resolve(name), name)

    def test_system_follows_windows(self):
        self.assertEqual(self.resolve("System", system_light=True), "Light")
        self.assertEqual(self.resolve("System", system_light=False), "Graphite")
        self.assertEqual(self.resolve("auto", system_light=True), "Light")

    def test_removed_or_missing_theme_is_treated_as_system(self):
        for name in ("Olive", "Night Comfort", "", None, "indigo"):
            self.assertEqual(self.resolve(name, system_light=True), "Light", name)
            self.assertEqual(self.resolve(name, system_light=False), "Graphite", name)


class ThemeAliasConsistencyTests(unittest.TestCase):
    def test_appearance_js_copies_are_identical(self):
        self.assertEqual(_read(APPEARANCE_JS[0]), _read(APPEARANCE_JS[1]),
                         "the two candidate_appearance.js copies have drifted apart")

    def test_js_aliases_match_python(self):
        js = _read(APPEARANCE_JS[0])
        block = re.search(r"var candidateThemeAliases = \{(.*?)\};", js, re.S).group(1)
        js_keys = set(re.findall(r"(\w+):\s*\"", block))
        self.assertEqual(js_keys, set(candidate_theme.KNOWN_CANDIDATE_THEMES))

    def test_js_aliases_map_onto_offered_themes(self):
        js = _read(APPEARANCE_JS[0])
        offered = set(re.findall(r"\"([^\"]+)\"", re.search(r"var candidateThemeNames = \[(.*?)\];", js, re.S).group(1)))
        block = re.search(r"var candidateThemeAliases = \{(.*?)\};", js, re.S).group(1)
        self.assertTrue(set(re.findall(r":\s*\"([^\"]+)\"", block)) <= offered)

    def test_cpp_theme_names_match_python(self):
        cpp = _read(os.path.join(ROOT, "PIMETextService", "PIMEClient.cpp"))
        body = re.search(r"static void candidateThemeColors\(.*?\n\}", cpp, re.S).group(0)
        cpp_names = set(re.findall(r'name == "(\w+)"', body))
        # "light" is the C++ fallback (else branch), so it is never named explicitly.
        self.assertEqual(cpp_names, set(candidate_theme.KNOWN_CANDIDATE_THEMES) - {"light"})


if __name__ == "__main__":
    unittest.main()
