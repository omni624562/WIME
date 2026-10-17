"""The bundled 新酷音 engine (python/libchewing): chewing.dll and its data are
built from the libchewing submodule by tools/build_libchewing.ps1 and committed.

- Up to 1.3.0-beta17 the DLL was a 2021 build of the old C libchewing (with
  access violations on some key sequences), while the submodule pointed at the
  Rust rewrite: nothing tied the shipped binary to a source version.
- The C version's data files (dictionary.dat, index_tree.dat, pinyin.tab) are
  not read by libchewing 0.13; shipping them only made the installer bigger.
"""

import os
import struct
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBCHEWING_DIR = os.path.join(ROOT, "python", "libchewing")
EXPECTED_VERSION = "0.13.1"


class BundledLibchewingTests(unittest.TestCase):
    def test_dll_reports_the_expected_version(self):
        import sys
        sys.path.insert(0, os.path.join(ROOT, "python"))
        import libchewing
        self.assertEqual(libchewing.version(), EXPECTED_VERSION)

    def test_dll_is_32_bit_and_needs_no_vc_runtime(self):
        with open(os.path.join(LIBCHEWING_DIR, "chewing.dll"), "rb") as f:
            data = f.read()
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        self.assertEqual(data[pe:pe + 4], b"PE\0\0")
        self.assertEqual(struct.unpack_from("<H", data, pe + 4)[0], 0x14C)  # i386: the embedded Python is 32-bit
        lowered = data.lower()
        for runtime in (b"vcruntime140.dll", b"msvcp140.dll", b"api-ms-win-crt-"):
            self.assertNotIn(runtime, lowered)  # +crt-static

    def test_only_the_data_files_libchewing_reads_are_shipped(self):
        data = os.path.join(LIBCHEWING_DIR, "data")
        self.assertEqual(sorted(os.listdir(data)), ["swkb.dat", "symbols.dat", "tsi.dat", "word.dat"])
        for name in ("tsi.dat", "word.dat"):
            with open(os.path.join(data, name), "rb") as f:
                self.assertIn(b"\x0c\x04CHEW", f.read(12))  # libchewing 0.13 trie dictionary
        for name in ("swkb.dat", "symbols.dat"):
            with open(os.path.join(data, name), "rb") as f:
                f.read().decode("utf-8")  # 0.13 ignores the whole file otherwise

    def test_submodule_is_at_the_same_version(self):
        if not os.path.exists(os.path.join(ROOT, "libchewing", "Cargo.toml")):
            self.skipTest("libchewing submodule not checked out")
        with open(os.path.join(ROOT, "libchewing", "Cargo.toml"), encoding="utf-8") as f:
            self.assertIn('version = "%s"' % EXPECTED_VERSION, f.read())
        try:
            url = subprocess.run(["git", "config", "-f", os.path.join(ROOT, ".gitmodules"),
                                  "submodule.libchewing.url"], capture_output=True, text=True).stdout.strip()
        except OSError:
            self.skipTest("git not found")
        self.assertEqual(url, "https://codeberg.org/chewing/libchewing.git")


if __name__ == "__main__":
    unittest.main()
