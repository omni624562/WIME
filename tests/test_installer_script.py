"""Static checks on installer/installer.nsi and its strings in installer/locale/*.nsh
(the installer itself is never run).

Windows version: the gate in .onInit only turned away Windows XP, but the embedded
Python 3.12 supports Windows 8.1 and later, and python312.dll and PIMELauncher.exe
import Windows 8 APIs. On Vista and 7 setup finished and registered the keyboards,
and then the launcher failed to load at the end of setup and at every logon, so
the IME never worked there.
"""

import os
import re
import unittest

from test_installer_order import ROOT, read_script, script_lines

LOCALE_DIR = os.path.join(ROOT, "installer", "locale")
# every language installer.nsi loads with LANG_LOAD (SimpChinese only in full builds)
LOCALES = ("TradChinese", "SimpChinese", "English")


def locale_strings(locale):
    """name -> value of the LANG_STRING lines in installer/locale/<locale>.nsh."""
    strings = {}
    with open(os.path.join(LOCALE_DIR, locale + ".nsh"), encoding="utf-8-sig") as f:
        for line in f:
            match = re.match(r"!insertmacro\s+LANG_STRING\s+(\S+)\s+(.*?)\s*$", line)
            if match:
                value = match.group(2)
                if len(value) >= 2 and value[0] == value[-1] == '"':
                    value = value[1:-1]
                strings[match.group(1)] = value
    return strings


class LocaleTests(unittest.TestCase):
    def test_every_string_the_script_uses_is_in_every_locale(self):
        # a string missing from one language shows up empty in that language
        used = {name for line in script_lines() for name in re.findall(r"\$\((\w+)\)", line)}
        self.assertTrue(used)
        for locale in LOCALES:
            with self.subTest(locale=locale):
                self.assertEqual(sorted(used - set(locale_strings(locale))), [])


class WindowsVersionTests(unittest.TestCase):
    def test_gate_turns_away_windows_7_and_older(self):
        functions, _ = read_script()
        on_init = functions[".onInit"]
        gates = [(index, match) for index, line in enumerate(on_init)
                 for match in [re.fullmatch(r"\$\{IfNot\}\s+\$\{AtLeastWin([\d.]+)\}", line)]
                 if match]
        self.assertEqual(len(gates), 1, "one ${IfNot} ${AtLeastWin<version>} in .onInit")
        index, match = gates[0]
        version = match.group(1)
        self.assertGreaterEqual(tuple(map(int, version.split("."))), (8, 1))
        # the message, then Quit (also in silent installs, where nobody sees it)
        message, follow = on_init[index + 1], on_init[index + 2]
        self.assertTrue(message.startswith("MessageBox"), message)
        self.assertIn("/SD IDOK", message)
        self.assertEqual(follow, "Quit")
        name = re.search(r"\$\((\w+)\)", message).group(1)
        for locale in LOCALES:
            with self.subTest(locale=locale):
                self.assertIn("Windows " + version, locale_strings(locale)[name])


if __name__ == "__main__":
    unittest.main()
