"""Order of operations in installer/installer.nsi.

.onInit runs before the license and components pages. An upgrade used to remove the
old version right there, after the 舊版 prompt: it unregistered the TSF DLLs and
deleted the Apps & features entry, the autostart, the Start-menu folder and the python
tree. Clicking Cancel on one of the following pages then left the PC with no WIME at
all and nothing to repair or uninstall it with. These checks read the script (the
installer itself is never run): nothing reachable from .onInit may change the system,
the removal runs in a hidden section declared before every section that installs
files, and silent installs still answer the prompt with OK.
"""

import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
INSTALLER = os.path.join(ROOT, "installer", "installer.nsi")

# commands that change files, the registry or running processes
CHANGING_COMMANDS = {
    "delete", "rmdir", "rename", "copyfiles", "createdirectory", "createshortcut",
    "deleteregkey", "deleteregvalue", "writeregstr", "writeregexpandstr", "writeregdword",
    "writeregbin", "writeregmultistr", "writeuninstaller", "regdll", "unregdll",
    "exec", "execwait", "reboot",
}
# helpers whose whole purpose is to stop processes or move files aside
CHANGING_FUNCTIONS = {"killProcessesInInstDir", "moveAsideIfLocked"}


def read_script():
    """Return (functions, sections): function name -> body lines, and the install
    sections in declaration order as (header, body lines). Comment lines are dropped
    and continuation lines joined; both branches of !if blocks are kept."""
    with open(INSTALLER, encoding="utf-8-sig") as f:
        raw = f.read().splitlines()
    lines, pending = [], ""
    for line in raw:
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        line = (pending + line).strip()
        pending = ""
        if line and not line.startswith((";", "#")):
            # functions defined by the DEFINE_* macros, as the installer's copy
            lines.append(line.replace("${UN}", ""))
    functions, sections, current = {}, [], None
    for line in lines:
        word = line.split(None, 1)[0].lower()
        if word == "function":
            current = functions.setdefault(line.split(None, 1)[1].strip(), [])
        elif word == "section":
            current = []
            sections.append((line, current))
        elif word in ("functionend", "sectionend"):
            current = None
        elif current is not None:
            current.append(line)
    sections = [(header, body) for header, body in sections
                if not re.match(r'Section\s+"?(Uninstall|un\.)', header)]
    return functions, sections


def expand(body, functions, seen=()):
    """The body with every Call replaced by the called function's lines (kept after
    the Call line itself), recursively and in order."""
    out = []
    for line in body:
        out.append(line)
        parts = line.split()
        if parts[0].lower() == "call" and parts[1] in functions and parts[1] not in seen:
            out.extend(expand(functions[parts[1]], functions, seen + (parts[1],)))
    return out


def called(lines):
    return {line.split()[1] for line in lines if line.split()[0].lower() == "call"}


def is_teardown(line):
    """regsvr32 /u of the old TSF DLL: the first step that removes the old version."""
    return line.lower().startswith("execwait") and "regsvr32" in line and " /u " in line


def installs_files(line):
    word = line.split()[0].lower()
    return word == "file" and "$PLUGINSDIR" not in line


class OnInitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.functions, cls.sections = read_script()
        cls.on_init = expand(cls.functions[".onInit"], cls.functions)

    def test_onInit_changes_nothing(self):
        # .onInit only asks: what it removes stays removed when the user cancels later
        changing = [line for line in self.on_init
                    if line.split()[0].lower() in CHANGING_COMMANDS or installs_files(line)]
        self.assertEqual(changing, [])
        self.assertEqual(called(self.on_init) & CHANGING_FUNCTIONS, set())

    def test_onInit_still_asks_about_the_old_version(self):
        prompts = [line for line in self.on_init if "$(UNINSTALL_OLD)" in line]
        self.assertEqual(len(prompts), 1)
        self.assertTrue(prompts[0].startswith("MessageBox"))
        # silent installs (/S) go on as if OK was clicked
        self.assertIn("/SD IDOK", prompts[0])
        # declining still quits the installer
        follow = self.on_init[self.on_init.index(prompts[0]) + 1]
        self.assertTrue(follow.startswith("Abort"), follow)


class SectionOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.functions, sections = read_script()
        cls.sections = [(header, expand(body, cls.functions)) for header, body in sections]

    def first(self, predicate):
        for index, (header, body) in enumerate(self.sections):
            if any(predicate(line) for line in body):
                return index
        self.fail("no section matches %s" % predicate.__name__)

    def test_old_version_is_removed_before_new_files_are_written(self):
        teardown = self.first(is_teardown)
        self.assertLess(teardown, self.first(installs_files))
        header = self.sections[teardown][0]
        # hidden: not on the components page, so it cannot be unticked
        self.assertRegex(header, r'^Section\s+"(-[^"]*)?"')

    def test_removal_helpers_run_in_that_section(self):
        body = self.sections[self.first(is_teardown)][1]
        self.assertLessEqual(CHANGING_FUNCTIONS, called(body))

    def test_ucrt_check_runs_before_anything_is_removed(self):
        # a missing runtime aborts the install; that must not happen after the removal
        body = self.sections[self.first(is_teardown)][1]
        self.assertIn("Call ensureUCRT", body)
        self.assertLess(body.index("Call ensureUCRT"),
                        next(i for i, line in enumerate(body) if is_teardown(line)))

    def test_sections_abort_instead_of_calling_onInstFailed(self):
        # NSIS calls .onInstFailed itself once a section aborts; calling it from a
        # section as well would show the failure message twice
        for header, body in self.sections:
            with self.subTest(section=header):
                self.assertNotIn(".onInstFailed", called(body))


if __name__ == "__main__":
    unittest.main()
