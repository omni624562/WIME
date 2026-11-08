"""Content checks on the code tables the limited installer ships
(the python\\cinbase\\json\\*.json files listed in installer/installer.nsi).

dayi3.cin (大易三碼, the default 大易 table) had six multi-character values
wrapped in ASCII double quotes under ;; (蟲) and 06: the table author's notes
"三碼", "無詞", "第５．０版", "八八八", "背杯ＯＡ專用" and "金門". Typing ;; for 蟲
listed them as candidates, and picking one committed the quotes too. ASCII-only
values such as the emoticon "<[+_+]>" in newcj are real candidates and stay.
"""

import json
import os
import re
import unittest

import cinbase_harness as h

INSTALLER = os.path.join(h.ROOT, "installer", "installer.nsi")


def shipped_tables():
    with open(INSTALLER, encoding="utf-8-sig") as f:
        names = re.findall(r'File "\.\.\\python\\cinbase\\json\\([^"\\]+\.json)"', f.read())
    return sorted(set(names))


def quote_wrapped(value):
    """A value in .cin quotes around non-ASCII text: cin syntax, not a candidate."""
    return len(value) > 2 and value[0] == value[-1] == '"' and not value.isascii()


class ShippedTableTests(unittest.TestCase):
    def test_installer_list_is_found(self):
        tables = shipped_tables()
        for name in ("dayi3.json", "dayi4.json", "thdayi.json", "checj.json"):
            self.assertIn(name, tables)

    @unittest.skipUnless(all(os.path.exists(os.path.join(h.JSON_DIR, name)) for name in shipped_tables()),
                         "cinbase/json tables not generated (cargo run --manifest-path tools/cintojson/Cargo.toml)")
    def test_no_quoted_candidates(self):
        for name in shipped_tables():
            with self.subTest(table=name):
                with open(os.path.join(h.JSON_DIR, name), encoding="utf-8") as f:
                    chardefs = json.load(f)["chardefs"]
                quoted = [(key, value) for key, values in chardefs.items()
                          for value in values if quote_wrapped(value)]
                self.assertEqual(quoted, [])

    @h.requires_tables
    def test_dayi3_codes_that_had_notes(self):
        with open(os.path.join(h.JSON_DIR, "dayi3.json"), encoding="utf-8") as f:
            chardefs = json.load(f)["chardefs"]
        self.assertEqual(chardefs[";;"], ["蟲"])
        self.assertIn("鍆", chardefs["06"])
        for key in (";;", "06"):
            self.assertFalse(any('"' in value for value in chardefs[key]), key)


CIN_DIR = os.path.join(h.PYTHON_DIR, "cinbase", "cin")
TOOLS_DIR = os.path.join(h.PYTHON_DIR, "cinbase", "tools")
RUST_TOOL_DIR = os.path.join(h.ROOT, "tools", "cintojson")


def rust_cintojson_exe():
    """The built Rust converter, or None: the WIME_CINTOJSON_EXE variable, else
    tools/cintojson/target/release (build.bat and CI build it with cargo run)."""
    candidates = [os.environ.get("WIME_CINTOJSON_EXE") or ""]
    for name in ("wime-cintojson.exe", "wime-cintojson"):
        candidates.append(os.path.join(RUST_TOOL_DIR, "target", "release", name))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


class RustConverterTests(unittest.TestCase):
    """tools/cintojson (Rust, used by build.bat and CI) must write exactly what
    python/cinbase/tools/cintojson.py writes: the backend loads these files
    and the Python reference implementation is tested against the same tables."""

    @unittest.skipUnless(rust_cintojson_exe(), "tools/cintojson is not built")
    def test_same_output_as_the_python_converter(self):
        import shutil
        import subprocess
        import sys
        import tempfile
        sys.path.insert(0, TOOLS_DIR)
        try:
            import cintojson
        finally:
            sys.path.remove(TOOLS_DIR)
        sorted_tables = ("cnscj.cin", "CnsPhonetic.cin")
        with tempfile.TemporaryDirectory() as tmp:
            py_dir = os.path.join(tmp, "py")
            rs_dir = os.path.join(tmp, "rs")
            os.makedirs(py_dir)

            class ToDir(cintojson.CinToJson):
                def getJsonDir(self):
                    return py_dir

            for name in sorted(os.listdir(CIN_DIR)):
                if name.endswith(".cin"):
                    app = ToDir()
                    app.run(name, os.path.join(CIN_DIR, name), name in sorted_tables)
                elif name.endswith(".txt"):
                    shutil.copy2(os.path.join(CIN_DIR, name), os.path.join(py_dir, name))
            subprocess.run([rust_cintojson_exe(), "--cin-dir", CIN_DIR, "--json-dir", rs_dir],
                           check=True, stdout=subprocess.DEVNULL)
            self.assertEqual(sorted(os.listdir(py_dir)), sorted(os.listdir(rs_dir)))
            for name in sorted(os.listdir(py_dir)):
                with self.subTest(file=name):
                    with open(os.path.join(py_dir, name), "rb") as f:
                        expected = f.read()
                    with open(os.path.join(rs_dir, name), "rb") as f:
                        actual = f.read()
                    self.assertEqual(expected, actual)
            # single-table mode (the installer's liu.cin path) and the "sort" flag
            subprocess.run([rust_cintojson_exe(), "--cin-dir", CIN_DIR, "--json-dir", os.path.join(tmp, "one"),
                            "cnscj.cin", "sort"], check=True, stdout=subprocess.DEVNULL)
            with open(os.path.join(py_dir, "cnscj.json"), "rb") as f:
                expected = f.read()
            with open(os.path.join(tmp, "one", "cnscj.json"), "rb") as f:
                self.assertEqual(expected, f.read())


if __name__ == "__main__":
    unittest.main()
