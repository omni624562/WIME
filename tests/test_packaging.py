"""Guards for what the limited installer leaves out (installer/installer.nsi and
installer/trim_python_zip.py).

The installer ships a trimmed standard library zip, skips some extension modules,
tornado modules and cinbase/tools/, and the backend must not need any of them. The
check imports everything the backend (大易 / 新酷音 / 酷倉 services), the settings
tools and the shared config server load, in a separate process with APPDATA
redirected, and fails if a trimmed module shows up in sys.modules. If you add an
import that hits this, take the module off the deny list (or the installer's /x
list) instead of silencing the test.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
sys.path.insert(0, os.path.join(ROOT, "installer"))
import trim_python_zip  # noqa: E402

# extension modules, tornado modules and cinbase files the limited installer skips
# (the /x lists in installer/installer.nsi)
EXCLUDED_MODULES = {
    "_decimal", "_elementtree", "_msi", "_multiprocessing", "_zoneinfo", "pyexpat",
    "tornado.auth", "tornado.autoreload", "tornado.curl_httpclient", "tornado.httpclient",
    "tornado.locks", "tornado.options", "tornado.queues", "tornado.simple_httpclient",
    "tornado.tcpclient", "tornado.testing", "tornado.websocket", "tornado.wsgi",
    "tornado.platform.caresresolver", "tornado.platform.twisted",
    "cinbase.debug", "cinbase.tools", "cinbase.tools.cpuinfo",
}

PROBE = r"""
import json, os, sys
sys.path.insert(0, PYTHON_DIR)
sys.path.insert(0, os.path.join(PYTHON_DIR, "input_methods", "chewing"))
import server  # noqa: F401  (the backend entry point, without starting it)
import importlib
for name in ("input_methods.chedayi.chedayi_ime", "input_methods.checj.checj_ime",
             "input_methods.chewing.chewing_ime", "config_server", "tornado.web",
             "tornado.httpserver", "tornado.ioloop"):
    importlib.import_module(name)
# the two settings tools, imported as their scripts would be (configtool.py reads
# its arguments at import time, like the Start Menu shortcut passes them)
sys.path.insert(0, os.path.join(PYTHON_DIR, "cinbase"))
sys.argv = ["configtool.py", "config", "chedayi"]
import configtool  # noqa: F401
import config_tool  # noqa: F401
# create the services so their constructors run too
class Client:
    isWindows8Above = True; isMetroApp = False; isUiLess = False; isConsole = False
for module, cls in (("input_methods.chewing.chewing_ime", "ChewingTextService"),):
    getattr(importlib.import_module(module), cls)(Client())
print(json.dumps(sorted(sys.modules)))
"""


class TrimmedInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.addClassCleanup(tmp.cleanup)
        env = dict(os.environ)
        for key in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME"):
            env[key] = tmp.name
        result = subprocess.run(
            [sys.executable, "-O", "-c", "PYTHON_DIR = %r\n" % PYTHON_DIR + PROBE],
            cwd=PYTHON_DIR, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
        if result.returncode != 0:
            raise AssertionError("probe failed:\n" + result.stderr)
        cls.modules = set(json.loads(result.stdout.strip().splitlines()[-1]))

    def test_no_trimmed_stdlib_module_is_imported(self):
        trimmed = sorted(m for m in self.modules
                         if m.split(".")[0] in trim_python_zip.DENY_PACKAGES
                         or m in trim_python_zip.DENY_MODULES)
        self.assertEqual(trimmed, [])

    def test_no_excluded_module_is_imported(self):
        self.assertEqual(sorted(self.modules & EXCLUDED_MODULES), [])

    def test_trimmed_zip_keeps_what_is_imported(self):
        # every probe module that would come from the zip is kept by keep()
        import zipfile
        with zipfile.ZipFile(trim_python_zip.SOURCE) as source:
            names = {os.path.splitext(n)[0].replace("/", ".").removesuffix(".__init__"): n
                     for n in source.namelist()}
        dropped = sorted(m for m in self.modules if m in names and not trim_python_zip.keep(names[m]))
        self.assertEqual(dropped, [])


if __name__ == "__main__":
    unittest.main()
