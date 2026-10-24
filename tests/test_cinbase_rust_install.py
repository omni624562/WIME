"""大易、酷倉與新酷音的 Rust 後端（cinbase-rs）怎麼接到啟動器與安裝程式。

啟動器（PIMELauncher/src/backend_registry.rs）與 TSF DLL（PIMEImeModule.cpp 的
loadImeInfo、DllEntry.cpp 的 DllRegisterServer）都依 backends.json 列出的後端資料夾，
掃描 <後端>\\input_methods\\*\\ime.json 找語言設定檔的 GUID。所以一個輸入法由哪個後端
處理，取決於它的 ime.json 放在哪個後端的資料夾，而同一個 GUID 只能放一份。
從 1.3.0-beta18 起三個輸入法都由 cinbase_rs\\wime-cinbase.exe 處理，WIME 的安裝檔
（backends-dayi-chewing-checj.json）只列 cinbase_rs，不再安裝 Python；設定工具是
cinbase_rs\\wime-config.exe。完整版（不加 /DONLY_DAYI_CHEWING_CHECJ，WIME 不發行）
的其他輸入法仍是 Python 的，所以 repo 根目錄的 backends.json 兩個都列。
安裝檔實際內容的檢查在 tests/test_packaging.py。
"""

import json
import ntpath
import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
RUST_IMES = {
    "chedayi": "{E6943374-70F5-4540-AA0F-3205C7DCCA84}",
    "checj": "{F828D2DC-81BE-466E-9CFE-24BB03172693}",
    "chewing": "{F80736AA-28DB-423A-92C9-5540F501C939}",
}
RUST_BACKEND = {
    "name": "cinbase_rs",
    "command": "cinbase_rs\\wime-cinbase.exe",
    "workingDir": "cinbase_rs",
    # load the tables of the input methods this user has used before the first
    # key (backend.rs preload); the launcher starts the backend at logon
    "params": "--preload",
}


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as f:
        return f.read()


class BackendsJsonTests(unittest.TestCase):
    def test_wime_installer_lists_only_the_rust_backend(self):
        backends = json.loads(read("installer", "backends-dayi-chewing-checj.json"))
        self.assertEqual(backends, [RUST_BACKEND])

    def test_full_build_keeps_python_for_its_other_input_methods(self):
        backends = json.loads(read("backends.json"))
        self.assertEqual([b["name"] for b in backends], ["python", "cinbase_rs"])
        self.assertEqual(backends[1], RUST_BACKEND)


class RustImeJsonTests(unittest.TestCase):
    MOVED = {"configTool", "configToolParams", "configToolDir"}

    def test_same_profile_as_python(self):
        for ime, guid in RUST_IMES.items():
            with self.subTest(ime=ime):
                python = json.loads(read("python", "input_methods", ime, "ime.json"))
                rust = json.loads(read("cinbase-rs", "input_methods", ime, "ime.json"))
                self.assertEqual(rust["guid"], guid)
                self.assertEqual({k: v for k, v in rust.items() if k not in self.MOVED},
                                 {k: v for k, v in python.items() if k not in self.MOVED})

    def test_settings_tool_is_wime_config(self):
        # the DLL joins configTool / configToolDir to the folder of ime.json
        # (PIMEImeModule.cpp onConfigure) and runs configTool configToolParams
        for ime in RUST_IMES:
            with self.subTest(ime=ime):
                rust = json.loads(read("cinbase-rs", "input_methods", ime, "ime.json"))
                folder = ntpath.join("PIME", "cinbase_rs", "input_methods", ime)
                self.assertEqual(ntpath.normpath(ntpath.join(folder, rust["configTool"])),
                                 ntpath.join("PIME", "cinbase_rs", "wime-config.exe"))
                self.assertEqual(ntpath.normpath(ntpath.join(folder, rust["configToolDir"])),
                                 ntpath.join("PIME", "cinbase_rs"))
                self.assertEqual(rust["configToolParams"], "config " + ime)
                self.assertNotIn("python", json.dumps(rust).lower())

    def test_one_profile_per_guid_among_the_shipped_backends(self):
        found = {}
        for ime in os.listdir(os.path.join(ROOT, "cinbase-rs", "input_methods")):
            guid = json.loads(read("cinbase-rs", "input_methods", ime, "ime.json"))["guid"]
            self.assertNotIn(guid, found, ime)
            found[guid] = ime
        self.assertEqual(found, {guid: ime for ime, guid in RUST_IMES.items()})


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.nsi = read("installer", "installer.nsi").replace("\r\n", "\n")

    def section(self, name):
        match = re.search(r"\n\s*Section \$\(\w+\) %s\n(.*?)SectionEnd" % name, self.nsi, re.S)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def macro(self, name):
        match = re.search(r"\n!macro %s\b[^\n]*\n(.*?)!macroend" % name, self.nsi, re.S)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_no_installer_option(self):
        # it used to be an "experimental" checkbox for 大易; now always used
        self.assertNotIn("chedayi_rust", self.nsi)
        self.assertNotIn("INST_DAYI_RUST", self.nsi)
        for locale in ("English", "TradChinese", "SimpChinese"):
            self.assertNotIn("CHEDAYI_RUST", read("installer", "locale", locale + ".nsh"))

    def test_binaries_installed_with_backends_json(self):
        main = re.search(r"\nSection \$\(SECTION_MAIN\) SecMain\n(.*?)SectionEnd", self.nsi, re.S).group(1)
        self.assertIn("backends.json", main)
        for exe in ("wime-cinbase.exe", "wime-config.exe"):
            self.assertIn(r'File "..\cinbase-rs\target\i686-pc-windows-msvc\release\%s"' % exe, main)

    def test_each_input_method_installs_its_profile(self):
        profile = self.macro("INSTALL_PROFILE")
        self.assertIn(r'SetOutPath "$INSTDIR\cinbase_rs\input_methods\${IME}"', profile)
        self.assertIn(r'File "..\cinbase-rs\input_methods\${IME}\ime.json"', profile)
        self.assertIn("!insertmacro INSTALL_PROFILE chewing", self.macro("INSTALL_CHEWING"))
        self.assertIn("!insertmacro INSTALL_PROFILE ${IME}", self.macro("INSTALL_CINBASE_IME"))
        expected = {"chewing": "!insertmacro INSTALL_CHEWING",
                    "checj": "!insertmacro INSTALL_CINBASE_IME checj",
                    "chedayi": "!insertmacro INSTALL_CINBASE_IME chedayi"}
        registration = self.nsi.index(r'regsvr32.exe" /s "$INSTDIR\x86\PIMETextService.dll')
        for ime, line in expected.items():
            with self.subTest(ime=ime):
                # every Section of that name (the limited and the full build)
                bodies = re.findall(r"\n\s*Section \$\(\w+\) %s\n(.*?)SectionEnd" % ime, self.nsi, re.S)
                self.assertEqual(len(bodies), 2)
                for body in bodies:
                    self.assertIn(line, body)
                    self.assertNotIn("python", body.lower())
                    # before the DLL registration that scans the backend folders
                    self.assertLess(self.nsi.index(body), registration)

    def test_upgrade_and_uninstall_remove_the_folders(self):
        for folder in ("cinbase_rs", "data", "python"):
            with self.subTest(folder=folder):
                self.assertIn('RMDir /r "$INSTDIR\\%s"' % folder, self.nsi)
                self.assertIn('RMDir /REBOOTOK /r "$INSTDIR\\%s"' % folder, self.nsi)

    def test_build_bat_builds_the_shipped_binaries(self):
        bat = read("build.bat")
        self.assertIn("pushd cinbase-rs", bat)
        self.assertNotIn("trim_python_zip", bat)
        # the tables are still generated with the repo's Python at build time
        self.assertIn(r"python\cinbase\tools\cintojson.py", bat)
        config = read("cinbase-rs", ".cargo", "config.toml")
        self.assertIn('target = "i686-pc-windows-msvc"', config)
        self.assertIn("+crt-static", config)
        cargo = read("cinbase-rs", "Cargo.toml")
        for exe in ("wime-cinbase", "wime-config"):
            self.assertIn('name = "%s"' % exe, cargo)


if __name__ == "__main__":
    unittest.main()
