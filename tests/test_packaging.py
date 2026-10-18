"""The installed WIME contains no Python (since 1.3.0-beta18).

大易、酷倉與新酷音 run on cinbase-rs's wime-cinbase.exe and their settings tools on
wime-config.exe; the installer (built with /DNO_SIMP_CHINESE /DONLY_DAYI_CHEWING_CHECJ)
ships those, the language profiles and the data files, laid out as
cinbase-rs/src/paths.rs describes:

    <PIME>\\cinbase_rs\\wime-cinbase.exe, wime-config.exe
    <PIME>\\cinbase_rs\\input_methods\\<ime>\\ime.json, icon.ico
    <PIME>\\data\\...   the data files, in the same sub-layout as the repo's python\\

The repo keeps the Python sources: they are the reference implementation the
tests compare the Rust code against, and build.bat still generates the code tables
with the repo's Python.

- ScriptTests read installer/installer.nsi with the limited build's !ifdef choices
  applied (no NSIS needed).
- BuiltInstallerTests compile the real installer (tests/installer_layout.py, into a
  temporary file) and check the files inside it: no Python, and every path that
  backends.json, the ime.json files, the Start-menu shortcuts and the Apps entry
  name is a file the installer puts there.
- StagedInstallTests copy that file list into a temporary folder and run the
  installed programs from there, with no access to the repo's python\\ folder:
  every settings tool serves its page and all the page's local files, and the
  backend types in all three input methods and starts the settings tool beside it.

The last two need NSIS and the build outputs (build.bat); they are skipped without
them, unless WIME_REQUIRE_INSTALLER=1 (CI, after the build) makes that a failure.
"""

import http.cookiejar
import json
import ntpath
import os
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error
import urllib.request

import installer_layout

ROOT = installer_layout.ROOT
sys.path.insert(0, os.path.join(ROOT, "tests", "diffharness"))
import driver  # noqa: E402

LIMITED_DEFINES = {"NO_SIMP_CHINESE", "ONLY_DAYI_CHEWING_CHECJ"}
IMES = driver.IME_GUIDS        # chedayi / checj / chewing -> GUID
TABLES = ("checj", "mscj3", "mscj3-ext", "cj-ext", "cnscj", "thcj", "newcj3", "cj5", "newcj",
          "scj6", "cj-fast", "thdayi", "dayi4", "dayi3", "thphonetic", "CnsPhonetic", "bpmf")

# what an install with Python had and this one must not
PYTHON_NAME = re.compile(r"(^|\\)(python[^\\]*\.(exe|dll|zip|cat)|pythonw\.exe|vcruntime\d*\.dll|"
                         r"chewing\.dll|[^\\]*\.(py|pyc|pyd|pyo|pth)|__pycache__)$", re.I)


def limited_lines():
    """installer.nsi's lines that the limited build compiles: comment lines dropped,
    continuation lines joined, !ifdef/!ifndef/!else/!endif resolved for
    LIMITED_DEFINES (other !if conditions count as true)."""
    with open(installer_layout.SCRIPT, encoding="utf-8-sig") as f:
        raw = f.read().splitlines()
    lines, pending, stack = [], "", []
    for line in raw:
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        line, pending = (pending + line).strip(), ""
        if not line or line.startswith((";", "#")):
            continue
        words = line.split()
        if words[0] in ("!ifdef", "!ifndef"):
            stack.append([(words[1] in LIMITED_DEFINES) == (words[0] == "!ifdef"), False])
            stack[-1][1] = stack[-1][0]
            continue
        if words[0] == "!if":
            stack.append([True, True])
            continue
        if words[0] == "!else":
            taken = stack[-1][1]
            if len(words) >= 3 and words[1] in ("ifdef", "ifndef"):
                cond = (words[2] in LIMITED_DEFINES) == (words[1] == "ifdef")
            else:
                cond = True
            stack[-1][0] = not taken and cond
            stack[-1][1] = taken or stack[-1][0]
            continue
        if words[0] == "!endif":
            stack.pop()
            continue
        if all(active for active, _ in stack):
            lines.append(line)
    return lines


class ScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines = limited_lines()

    def test_no_python_is_installed_or_run(self):
        for line in self.lines:
            with self.subTest(line=line):
                word = line.split()[0]
                if word in ("SetOutPath", "File", "CreateShortCut", "CreateDirectory"):
                    self.assertNotIn("$INSTDIR\\python", line)
                    self.assertNotRegex(line, r"python3|pythonw?\.exe|\*\.py\b|\\python\\\*\.\*|\.py\"")
                if word.startswith("nsExec::") or word.startswith("Exec"):
                    self.assertNotRegex(line.lower(), r"python|compileall")

    def test_trimmed_python_zip_is_gone(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "installer", "trim_python_zip.py")))
        text = "\n".join(self.lines)
        for word in ("python314.zip", "compileall", "INST_PYTHON", "INST_CINBASE", "ensureUCRT", "PSF.txt"):
            self.assertNotIn(word, text)

    def test_settings_entry_points_are_wime_config(self):
        links = [line for line in self.lines if line.startswith("CreateShortCut")]
        tools = [line for line in links if "Uninstall.exe" not in line]
        self.assertEqual(len(tools), 4)     # 大易, 酷倉, 新酷音 and its user phrase editor
        for line in tools:
            with self.subTest(line=line):
                self.assertIn('"$INSTDIR\\cinbase_rs\\wime-config.exe"', line)
                self.assertRegex(line, r'wime-config\.exe" "(config (chedayi|checj|chewing)|user_phrase_editor chewing)"')


def _require_build():
    if os.environ.get("WIME_REQUIRE_INSTALLER") == "1":
        return
    if not installer_layout.MAKENSIS:
        raise unittest.SkipTest("NSIS is not installed")
    missing = installer_layout.missing_outputs()
    if missing:
        raise unittest.SkipTest("not built (build.bat): " + ", ".join(missing))


class BuiltInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _require_build()
        cls.layout = installer_layout.cached_build()
        cls.installed = cls.layout.installed()

    def assertInstalled(self, path):
        self.assertIn(path.lower(), self.installed, path)

    def resolve(self, path):
        """$INSTDIR\\x -> x"""
        self.assertTrue(path.startswith("$INSTDIR\\"), path)
        return path[len("$INSTDIR\\"):]

    def test_no_python_inside(self):
        self.assertTrue(self.layout.files)
        offending = sorted(path for path in set(self.layout.files)
                           if path.lower().startswith("python\\") or PYTHON_NAME.search(path))
        self.assertEqual(offending, [])
        # nothing it runs is a Python either
        for line in self.layout.log.splitlines():
            self.assertNotRegex(line.lower(), r"pythonw?\.exe|compileall", line)

    def test_programs_profiles_and_data_are_inside(self):
        for path in ("PIMELauncher.exe", "backends.json", "version.txt",
                     r"x86\PIMETextService.dll", r"x64\PIMETextService.dll",
                     r"cinbase_rs\wime-cinbase.exe", r"cinbase_rs\wime-config.exe"):
            self.assertInstalled(path)
        for ime in IMES:
            self.assertInstalled(r"cinbase_rs\input_methods\%s\ime.json" % ime)
            self.assertInstalled(r"cinbase_rs\input_methods\%s\icon.ico" % ime)
        for table in TABLES:
            self.assertInstalled(r"data\cinbase\json\%s.json" % table)
        for ime in ("chedayi", "checj"):
            for name in ("config.html", "config.js", "config.json"):
                self.assertInstalled(r"data\input_methods\%s\config\%s" % (ime, name))
            self.assertInstalled(r"data\input_methods\%s\icon.ico" % ime)
        for name in ("emoji.json", "symbols.dat", "swkb.dat", "phrase.json"):
            self.assertInstalled(r"data\cinbase\data\%s" % name)
        self.assertInstalled(r"data\cinbase\config\config.htm")
        self.assertInstalled(r"data\cinbase\icons\chi.ico")
        for name in ("config_tool.html", "user_phrase_editor.html", r"icons\eng.ico", r"icons\traC.ico",
                     r"images\setting.ico", r"images\phrase_editor.ico"):
            self.assertInstalled(r"data\input_methods\chewing\%s" % name)
        for name in ("tsi.dat", "word.dat", "symbols.dat", "swkb.dat"):
            self.assertInstalled(r"data\libchewing\data\%s" % name)

    def test_data_mirrors_the_repo_python_folder(self):
        # the data root has the repo python folder's sub-layout (paths.rs): each
        # file under data\ is the file at the same place under python\
        for dest, source in self.layout.sources.items():
            with self.subTest(dest=dest):
                parts = dest.split("\\")
                if parts[0] == "data":
                    self.assertEqual(os.path.normcase(installer_layout.os.path.normpath(
                        os.path.join(installer_layout.INSTALLER_DIR, source))),
                        os.path.normcase(os.path.join(ROOT, "python", *parts[1:])))
        for dest in set(self.layout.files):
            with self.subTest(dest=dest):
                source = self.layout.source_of(dest)
                self.assertIsNotNone(source)
                self.assertTrue(os.path.isfile(source), source)

    def test_backends_and_profiles_resolve(self):
        with open(self.layout.source_of("backends.json"), encoding="utf-8-sig") as f:
            backends = json.load(f)
        guids = {}
        for backend in backends:
            self.assertInstalled(backend["command"])
            for path in self.installed.values():
                parts = path.split("\\")
                if parts[0].lower() == backend["name"].lower() and parts[1:2] == ["input_methods"] \
                        and parts[-1] == "ime.json" and len(parts) == 4:
                    with open(self.layout.source_of(path), encoding="utf-8-sig") as f:
                        profile = json.load(f)
                    self.assertNotIn(profile["guid"], guids, path)
                    guids[profile["guid"]] = parts[2]
                    folder = ntpath.dirname(path)
                    with self.subTest(profile=path):
                        self.assertInstalled(ntpath.normpath(ntpath.join(folder, profile["icon"])))
                        self.assertInstalled(ntpath.normpath(ntpath.join(folder, profile["configTool"])))
                        tool_dir = ntpath.normpath(ntpath.join(folder, profile["configToolDir"])).lower() + "\\"
                        self.assertTrue(any(p.startswith(tool_dir) for p in self.installed), tool_dir)
                        self.assertEqual(profile["configToolParams"], "config " + parts[2])
        self.assertEqual(guids, {guid: ime for ime, guid in IMES.items()})

    def test_shortcuts_and_apps_entry_resolve(self):
        self.assertEqual(len(self.layout.shortcuts), 5)
        for link, target, params, icon in self.layout.shortcuts:
            with self.subTest(link=link):
                target = self.resolve(target)
                if target == "Uninstall.exe":
                    continue
                self.assertEqual(target, r"cinbase_rs\wime-config.exe")
                self.assertInstalled(self.resolve(icon))
                tool, ime = params.split()
                self.assertIn(tool, ("config", "user_phrase_editor"))
                self.assertIn(ime, IMES)
        icons = [value for key, value in self.layout.registry if key.endswith("\\DisplayIcon")]
        self.assertTrue(icons)
        for icon in icons:
            if icon != "$INSTDIR\\Uninstall.exe":
                self.assertInstalled(self.resolve(icon))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(opener, url):
    try:
        response = opener.open(url, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return getattr(response, "status", None) or response.code, response.read()


class StagedInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _require_build()
        layout = installer_layout.cached_build()
        cls.tmp = tempfile.TemporaryDirectory(prefix="wime-staged-", ignore_cleanup_errors=True)
        cls.pime = os.path.join(cls.tmp.name, "PIME")
        layout.stage(cls.pime)
        # the programs must find everything from where they are installed: never
        # through these variables, the repo's python folder, or the current directory
        cls.env = dict(os.environ)
        for key in ("WIME_PY_DIR", "WIME_DATA_DIR", "WIME_E2E", "WIME_CONFIG_EXE"):
            cls.env.pop(key, None)
        profile = os.path.join(cls.tmp.name, "profile")
        for key in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME"):
            cls.env[key] = profile
        os.makedirs(profile)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def start_tool(self, tool, ime):
        env = dict(self.env, WIME_CONFIG_TEST_LAUNCH="print", WIME_CONFIG_IDLE_TIMEOUT="3")
        exe = os.path.join(self.pime, "cinbase_rs", "wime-config.exe")
        proc = subprocess.Popen([exe, tool, ime], cwd=self.tmp.name, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.addCleanup(lambda: (proc.poll() is None and proc.kill(), proc.communicate()))
        line = proc.stdout.readline()
        self.assertTrue(line.startswith("URL "), line + (proc.stderr.read() if proc.poll() is not None else ""))
        return line[4:].strip()

    def test_settings_tools_serve_their_pages_from_the_install(self):
        for tool, ime, page in (("config", "chedayi", "config"), ("config", "checj", "config"),
                                ("config", "chewing", "config_tool"),
                                ("user_phrase_editor", "chewing", "user_phrase_editor")):
            with self.subTest(tool=tool, ime=ime):
                login = self.start_tool(tool, ime)
                base = re.match(r"(http://127\.0\.0\.1:\d+)/", login).group(1)
                jar = http.cookiejar.CookieJar()
                status, _ = _get(urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect()), login)
                self.assertEqual(status, 302)
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
                status, body = _get(opener, "%s/%s.html" % (base, page))
                self.assertEqual(status, 200)
                html = body.decode("utf-8")
                refs = set(re.findall(r'(?:src|href)="([^"#?]+)', html))
                local = sorted(r for r in refs if not re.match(r"(https?:|mailto:|javascript:|//)", r))
                self.assertTrue(local)
                missing = [r for r in local if _get(opener, base + "/" + r.lstrip("./"))[0] != 200]
                self.assertEqual(missing, [])
                status, body = _get(opener, base + "/config")
                self.assertEqual(status, 200)
                self.assertIsInstance(json.loads(body.decode("utf-8"))["config"], dict)
                self.assertEqual(_get(opener, base + "/version.txt")[0], 200)
                if ime != "chewing":
                    # the tables offered for reverse lookup are the installed ones
                    config = json.loads(body.decode("utf-8"))
                    self.assertTrue(config.get("rcinAvailable"))
                    self.assertEqual(_get(opener, base + "/icon.ico")[0], 200)

    def test_backend_types_in_all_three_input_methods(self):
        exe = os.path.join(self.pime, "cinbase_rs", "wime-cinbase.exe")
        typing = {"chedayi": ("b", "t", "SPACE"), "checj": ("a", "SPACE"), "chewing": ("s", "u", "3", "ENTER")}
        settings_commands = {"chedayi": [3], "checj": [3], "chewing": [3, 19]}
        with unittest.mock.patch.dict(os.environ, self.env, clear=True):
            for ime, keys in typing.items():
                with self.subTest(ime=ime):
                    backend = driver.Backend([exe], ime)
                    try:
                        log = []
                        session = driver.Session(backend, "c1", ime, log)
                        session.start()
                        self.assertTrue(log[0]["reply"].get("success"), log[0])
                        for key in keys:
                            session.key(key, key)
                        texts = "".join(str(entry["reply"].get(field, "")) for entry in log
                                        for field in ("commitString", "compositionString", "candidateList"))
                        self.assertRegex(texts, r"[一-鿿]", log[-4:])
                        for command in settings_commands[ime]:
                            reply = session.call("settings", "onCommand", id=command, type=0)
                            self.assertEqual(reply.get("_testLaunches"), [["ShellExecuteW", "wime-config.exe"]])
                        session.stop()
                    finally:
                        backend.close()


if __name__ == "__main__":
    unittest.main()
