"""大易與酷倉的 Rust 後端（cinbase-rs）怎麼接到啟動器與安裝程式。

啟動器（PIMELauncher/src/backend_registry.rs）與 TSF DLL（PIMEImeModule.cpp 的
loadImeInfo、DllEntry.cpp 的 DllRegisterServer）都依 backends.json 列出的後端資料夾，
掃描 <後端>\\input_methods\\*\\ime.json 找語言設定檔的 GUID。所以一個輸入法由哪個後端
處理，取決於它的 ime.json 放在哪個後端的資料夾，而同一個 GUID 只能放一份。
新酷音仍由 Python 後端處理。
"""

import json
import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
RUST_IMES = {
    "chedayi": "{E6943374-70F5-4540-AA0F-3205C7DCCA84}",
    "checj": "{F828D2DC-81BE-466E-9CFE-24BB03172693}",
}


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as f:
        return f.read()


class BackendsJsonTests(unittest.TestCase):
    def test_both_backends_listed(self):
        for path in (("backends.json",), ("installer", "backends-dayi-chewing-checj.json")):
            with self.subTest(path=os.path.join(*path)):
                backends = json.loads(read(*path))
                names = [b["name"] for b in backends]
                self.assertEqual(names, ["python", "cinbase_rs"])
                rust = backends[1]
                self.assertEqual(rust["command"], "cinbase_rs\\wime-cinbase.exe")
                self.assertEqual(rust["workingDir"], "cinbase_rs")


class RustImeJsonTests(unittest.TestCase):
    def test_same_profile_as_python_with_paths_from_its_folder(self):
        moved = {"configTool", "configToolDir"}
        for ime, guid in RUST_IMES.items():
            with self.subTest(ime=ime):
                python = json.loads(read("python", "input_methods", ime, "ime.json"))
                rust = json.loads(read("cinbase-rs", "input_methods", ime, "ime.json"))
                self.assertEqual(rust["guid"], guid)
                self.assertEqual({k: v for k, v in rust.items() if k not in moved},
                                 {k: v for k, v in python.items() if k not in moved})
                # the DLL joins these to the folder of ime.json: both must land on the
                # same files as the Python copy (<PIME>\python\...)
                python_dir = os.path.join("PIME", "python", "input_methods", ime)
                rust_dir = os.path.join("PIME", "cinbase_rs", "input_methods", ime)
                for key in moved:
                    self.assertEqual(os.path.normpath(os.path.join(rust_dir, rust[key])),
                                     os.path.normpath(os.path.join(python_dir, python[key])))

    def test_chewing_stays_on_python(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "cinbase-rs", "input_methods", "chewing")))


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.nsi = read("installer", "installer.nsi").replace("\r\n", "\n")

    def test_no_installer_option(self):
        # it used to be an "experimental" checkbox for 大易; now always used
        self.assertNotIn("chedayi_rust", self.nsi)
        self.assertNotIn("INST_DAYI_RUST", self.nsi)
        for locale in ("English", "TradChinese", "SimpChinese"):
            self.assertNotIn("CHEDAYI_RUST", read("installer", "locale", locale + ".nsh"))

    def test_backend_installed_when_either_ime_is(self):
        block = re.search(r"\$\{If\} \$\{SectionIsSelected\} \$\{chedayi\}\n\t\$\{OrIf\} \$\{SectionIsSelected\} \$\{checj\}\n"
                          r"(.*?)\$\{EndIf\}", self.nsi, re.S)
        self.assertIsNotNone(block)
        self.assertIn(r'File "..\cinbase-rs\target\i686-pc-windows-msvc\release\wime-cinbase.exe"', block.group(1))

    def test_rust_backend_takes_over_each_profile(self):
        registration = self.nsi.index(r'regsvr32.exe" /s "$INSTDIR\x86\PIMETextService.dll')
        for ime in RUST_IMES:
            with self.subTest(ime=ime):
                pattern = r"\$\{If\} \$\{SectionIsSelected\} \$\{%s\}\n.*?\$\{EndIf\}" % ime
                blocks = [m.group(0) for m in re.finditer(pattern, self.nsi, re.S)
                          if "cinbase_rs\\input_methods\\%s" % ime in m.group(0)]
                self.assertEqual(len(blocks), 1)
                body = blocks[0]
                self.assertIn(r'File "..\cinbase-rs\input_methods\%s\ime.json"' % ime, body)
                # one GUID, one backend: the Python copy of ime.json goes away
                self.assertIn(r'Delete "$INSTDIR\python\input_methods\%s\ime.json"' % ime, body)
                # before the DLL registration that scans the backend folders
                self.assertLess(self.nsi.index(body), registration)

    def test_upgrade_and_uninstall_remove_the_folder(self):
        self.assertIn('RMDir /r "$INSTDIR\\cinbase_rs"', self.nsi)
        self.assertIn('RMDir /REBOOTOK /r "$INSTDIR\\cinbase_rs"', self.nsi)

    def test_build_bat_builds_the_shipped_binary(self):
        bat = read("build.bat")
        self.assertIn("pushd cinbase-rs", bat)
        config = read("cinbase-rs", ".cargo", "config.toml")
        self.assertIn('target = "i686-pc-windows-msvc"', config)
        self.assertIn("+crt-static", config)


if __name__ == "__main__":
    unittest.main()
