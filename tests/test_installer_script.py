"""Static checks on installer/installer.nsi and its strings in installer/locale/*.nsh
(the installer itself is never run; only installer/version.nsh goes through
makensis /PPO, and only when NSIS is installed).

Windows version: the gate in .onInit only turned away Windows XP, but the embedded
Python 3.12 supports Windows 8.1 and later, and python312.dll and PIMELauncher.exe
import Windows 8 APIs. On Vista and 7 setup finished and registered the keyboards,
and then the launcher failed to load at the end of setup and at every logon, so
the IME never worked there.

Start menu: the shortcuts went to $SMPROGRAMS\\$(PRODUCT_NAME) in the default
current-user context, i.e. to the Start menu of whoever ran the elevated installer,
in a folder named after the language picked in the installer. The uninstaller does
not know that language and removed the other language's folder, an upgrade removed
only the newly picked one, and nothing removed the folders from before the PIME ->
WIME rename, so dead or duplicate 設定大易輸入法 / 解除安裝 PIME shortcuts stayed.

Finish page: it only had the project link. Nothing told a new user to press
Win+Space, how the keyboards are named, what to do when they do not show up (they are
registered under zh-Hant-TW only, so without the 中文 (台灣) language they are not
listed), or where the settings tools are.

Metadata: the setup program had no version resource (Properties > Details showed no
name, description or version), and the Apps & features entry had no icon, no size,
and offered Change next to Uninstall.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

from test_installer_order import ROOT, read_script, script_lines

PROGRAM_FILES = (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("ProgramFiles", r"C:\Program Files"))
MAKENSIS = next((path for path in [shutil.which("makensis")] + [
    os.path.join(base, "NSIS", *sub, "makensis.exe")
    for base in PROGRAM_FILES for sub in ((), ("Bin",))] if path and os.path.isfile(path)), None)

LOCALE_DIR = os.path.join(ROOT, "installer", "locale")
# every language installer.nsi loads with LANG_LOAD (SimpChinese only in full builds)
LOCALES = ("TradChinese", "SimpChinese", "English")

# Start-menu folders earlier versions created ($(PRODUCT_NAME) before and after the
# rename, in each installer language)
OLD_START_MENU_FOLDERS = {
    "PIME 輸入法", "PIME Input Methods", "PIME 输入法",
    "WIME 輸入法", "WIME Input Methods", "WIME 输入法",
}


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


def locale_version_keys(locale):
    """key -> value of the LANG_VERSION_KEY lines in installer/locale/<locale>.nsh."""
    with open(os.path.join(LOCALE_DIR, locale + ".nsh"), encoding="utf-8-sig") as f:
        return dict(re.findall(r'^!insertmacro\s+LANG_VERSION_KEY\s+(\w+)\s+"([^"]*)"',
                               f.read(), re.MULTILINE))


def vi_version(product_version):
    """VI_VERSION as installer/version.nsh derives it from version.txt's text."""
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "probe.nsi")
        with open(script, "w", encoding="utf-8") as f:
            f.write('!define PRODUCT_VERSION "%s"\n!include "%s"\n!echo "VI_VERSION=[${VI_VERSION}]"\n'
                    % (product_version, os.path.join(ROOT, "installer", "version.nsh")))
        result = subprocess.run([MAKENSIS, "/PPO", script], capture_output=True, text=True,
                                errors="replace", timeout=60)
    match = re.search(r"VI_VERSION=\[([^\]]*)\]", result.stdout)
    if result.returncode != 0 or not match:
        raise AssertionError("makensis failed:\n" + result.stdout + result.stderr)
    return match.group(1)


def defines():
    """name -> value of the script's plain !define lines."""
    found = {}
    for line in script_lines():
        match = re.fullmatch(r'!define\s+(\w+)\s+"([^"]*)"', line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def macros():
    """name -> body lines of the parameterless macros the script defines."""
    found, current = {}, None
    for line in script_lines():
        parts = line.split()
        if parts[0] == "!macro":
            current = found.setdefault(parts[1], []) if len(parts) == 2 else None
        elif parts[0] == "!macroend":
            current = None
        elif current is not None:
            current.append(line)
    return found


def blocks():
    """(functions, sections): function name -> body lines and every section, the
    uninstaller's included, as (header, body lines)."""
    functions, _ = read_script()
    sections, current = [], None
    for line in script_lines():
        word = line.split(None, 1)[0].lower()
        if word == "section":
            current = []
            sections.append((line, current))
        elif word in ("sectionend", "function", "functionend"):
            current = None
        elif current is not None:
            current.append(line)
    return functions, sections


def flatten(body, functions, defined, seen=()):
    """The body with the script's own macros inserted and every Call (un. copies
    included) followed by the called function's lines, recursively and in order."""
    out = []
    for line in body:
        parts = line.split()
        if parts[0] == "!insertmacro" and len(parts) == 2 and parts[1] in defined:
            out.extend(flatten(defined[parts[1]], functions, defined, seen))
            continue
        out.append(line)
        if parts[0].lower() == "call":
            name = parts[1].removeprefix("un.")
            if name in functions and name not in seen:
                out.extend(flatten(functions[name], functions, defined, seen + (name,)))
    return out


def start_menu_uses(lines):
    """(shell context, command, folder) for each $SMPROGRAMS use, in order. Every
    block starts in NSIS's default current-user context."""
    context, uses = "current", []
    for line in lines:
        parts = line.split()
        if parts[0] == "SetShellVarContext":
            context = parts[1]
        elif "$SMPROGRAMS" in line:
            match = re.search(r'"\$SMPROGRAMS\\([^"\\]*)', line)
            uses.append((context, parts[0], match and match.group(1)))
    return uses


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


class FinishPageTests(unittest.TestCase):
    def test_finish_page_says_how_to_reach_the_keyboards_and_settings(self):
        lines = script_lines()
        finish = lines.index("!insertmacro MUI_PAGE_FINISH")
        texts = [re.fullmatch(r'!define\s+MUI_FINISHPAGE_TEXT\s+"\$\((\w+)\)"', line)
                 for line in lines[:finish]]
        texts = [match.group(1) for match in texts if match]
        self.assertEqual(len(texts), 1, "MUI_FINISHPAGE_TEXT from a language string")
        for locale in LOCALES:
            with self.subTest(locale=locale):
                text = locale_strings(locale)[texts[0]]
                self.assertIn("Win+", text)  # the keyboard switcher
                self.assertIn("(WIME)", text)  # how the keyboards are named in it
                self.assertIn("Windows 11", text)  # where to add the missing language
                self.assertIn("${START_MENU_FOLDER}", text)  # the settings tools
                # a single & in a label underlines the next letter instead of showing
                # (Settings > Time & language)
                self.assertNotRegex(text, r"(?<!&)&(?!&)")


class StartMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = defines().get("START_MENU_FOLDER", "")
        cls.functions, sections = blocks()
        defined = macros()
        cls.sections = {header: flatten(body, cls.functions, defined)
                        for header, body in sections}
        cls.remover = flatten(cls.functions.get("removeStartMenuFolders", []),
                              cls.functions, defined)

    def section(self, pattern):
        found = [body for header, body in self.sections.items() if re.match(pattern, header)]
        self.assertEqual(len(found), 1, pattern)
        return found[0]

    def test_folder_name_does_not_depend_on_the_language(self):
        self.assertRegex(self.folder, r"^[^\\/$*?]+$")
        for line in script_lines():
            self.assertNotIn("$SMPROGRAMS\\$(", line)

    def test_shortcuts_go_to_the_all_users_folder(self):
        created = [use for body in self.sections.values() for use in start_menu_uses(body)
                   if use[1] in ("CreateDirectory", "CreateShortCut")]
        self.assertTrue(created)
        for context, command, folder in created:
            self.assertEqual((context, folder), ("all", "${START_MENU_FOLDER}"), command)

    def test_upgrade_and_uninstall_remove_the_folder_and_the_old_ones(self):
        for name, body in (("Prepare", self.section(r'Section\s+"-Prepare"')),
                           ("Register", self.section(r'Section\s+""\s+Register')),
                           ("Uninstall", self.section(r'Section\s+"Uninstall"'))):
            with self.subTest(section=name):
                uses = start_menu_uses(body)
                self.assertIn(("all", "RMDir", "${START_MENU_FOLDER}"), uses)
                for context in ("current", "all"):
                    removed = {folder for where, command, folder in uses
                               if where == context and command == "RMDir"}
                    self.assertLessEqual(OLD_START_MENU_FOLDERS, removed, context)

    def test_old_folders_go_before_shortcuts_are_created(self):
        uses = start_menu_uses(self.section(r'Section\s+""\s+Register'))
        commands = [command for context, command, folder in uses]
        self.assertIn("RMDir", commands)
        last_removal = max(i for i, command in enumerate(commands) if command == "RMDir")
        self.assertLess(last_removal, commands.index("CreateDirectory"))

    def test_only_exact_folder_names_are_removed(self):
        # RMDir /r on $SMPROGRAMS itself, or on a pattern, would wipe other programs'
        # shortcuts
        uses = [use for body in list(self.sections.values()) + [self.remover]
                for use in start_menu_uses(body) if use[1] == "RMDir"]
        self.assertTrue(uses)
        for context, command, folder in uses:
            self.assertIn(folder, OLD_START_MENU_FOLDERS | {"${START_MENU_FOLDER}"})


class MetadataTests(unittest.TestCase):
    # the keys Explorer shows; makensis warns about a language that lacks some of them
    VERSION_KEYS = {"ProductName", "CompanyName", "FileDescription", "FileVersion",
                    "ProductVersion", "LegalCopyright"}

    def test_version_resource_uses_the_numeric_version(self):
        lines = script_lines()
        self.assertIn('!include "version.nsh"', [line.split(";")[0].strip() for line in lines])
        self.assertIn('VIProductVersion "${VI_VERSION}"', lines)
        self.assertIn('VIFileVersion "${VI_VERSION}"', lines)

    def test_every_language_has_the_version_keys(self):
        # FileVersion, ProductVersion and LegalCopyright are set once for every
        # language in LANG_LOAD, the translated ones in each locale file
        shared = set(re.findall(r'VIAddVersionKey\s+/LANG=\$\{LANG_\$\{LANG\}\}\s+"(\w+)"',
                                "\n".join(script_lines())))
        for locale in LOCALES:
            with self.subTest(locale=locale):
                keys = locale_version_keys(locale)
                strings = locale_strings(locale)
                self.assertEqual(shared | set(keys), self.VERSION_KEYS)
                self.assertEqual(shared & set(keys), set())
                # the same names the installer and Apps & features show
                self.assertEqual(keys["ProductName"], strings["PRODUCT_NAME"])
                self.assertEqual(keys["CompanyName"], strings["PRODUCT_PUBLISHER"])

    @unittest.skipUnless(MAKENSIS, "NSIS is not installed")
    def test_version_txt_maps_to_four_numbers(self):
        for text, numeric in (("1.3.0-beta14", "1.3.0.14"), ("1.3.0", "1.3.0.0"),
                              ("1.3.0-beta", "1.3.0.0"), ("1.3.0-alpha2", "1.3.0.2"),
                              ("1.3.0-rc1", "1.3.0.1"), ("1.10.2-beta.3", "1.10.2.3")):
            with self.subTest(version=text):
                self.assertEqual(vi_version(text), numeric)
        # stops the build instead of writing a version resource with a wrong version
        with self.assertRaises(AssertionError):
            vi_version("1.3")
        # the real one: its numbers in order, like CMakeLists.txt reads them for the DLL
        with open(os.path.join(ROOT, "version.txt"), encoding="utf-8") as f:
            text = f.read().strip()
        numbers = (re.findall(r"\d+", text) + ["0"])[:4]
        self.assertEqual(vi_version(text), ".".join(numbers))

    def test_apps_entry_has_icon_size_and_no_change_button(self):
        functions, sections = read_script()
        register = next(body for header, body in sections if re.match(r'Section\s+""\s+Register', header))
        writes = {}
        for index, line in enumerate(register):
            match = re.match(r'(WriteReg\w+)\s+HKLM\s+"\$\{PRODUCT_UNINST_KEY\}"\s+"(\w+)"\s+(.*)$', line)
            if match:
                writes.setdefault(match.group(2), []).append((index, match.group(1), match.group(3)))
        for name in ("NoModify", "NoRepair"):
            self.assertEqual([(command, value) for index, command, value in writes.get(name, [])],
                             [("WriteRegDWORD", "1")], name)
        # the size counts the .pyc files compileall writes
        [(size_at, command, value)] = writes.get("EstimatedSize", [(-1, None, None)])
        self.assertEqual(command, "WriteRegDWORD")
        compiled = max(i for i, line in enumerate(register) if "compileall" in line)
        self.assertGreater(size_at, compiled)
        # every icon is a file the installer puts there
        uninstaller = next(line.split('"')[1] for line in register
                           if line.startswith("WriteUninstaller"))
        icons = [value.strip('"') for index, command, value in writes["DisplayIcon"]]
        self.assertTrue(icons)
        for icon in icons:
            with self.subTest(icon=icon):
                if icon.startswith("$INSTDIR\\python\\"):
                    source = os.path.join(ROOT, *icon.split("\\")[1:])
                    self.assertTrue(os.path.isfile(source), source)
                else:
                    self.assertEqual(icon, uninstaller)


if __name__ == "__main__":
    unittest.main()
