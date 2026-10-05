"""Order of operations in installer/installer.nsi.

.onInit runs before the license and components pages. An upgrade used to remove the
old version right there, after the 舊版 prompt: it unregistered the TSF DLLs and
deleted the Apps & features entry, the autostart, the Start-menu folder and the python
tree. Clicking Cancel on one of the following pages then left the PC with no WIME at
all and nothing to repair or uninstall it with. These checks read the script (the
installer itself is never run): nothing reachable from .onInit may change the system,
the removal runs in a hidden section declared before every section that installs
files, only on the OK the prompt recorded, and silent installs still answer the
prompt with OK.
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


def script_lines():
    """The script's lines with comment lines dropped and continuation lines joined;
    both branches of !if blocks are kept."""
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
    return lines


def read_script():
    """Return (functions, sections): function name -> body lines, and the install
    sections in declaration order as (header, body lines)."""
    functions, sections, current = {}, [], None
    for line in script_lines():
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


# what removing the old version does; each step must wait for the OK on the prompt
TEARDOWN_STEPS = {
    "unregister the TSF DLLs": is_teardown,
    "delete the Apps & features entry":
        lambda line: line.startswith("DeleteRegKey") and "\\Uninstall\\PIME" in line,
    "remove the autostart":
        lambda line: line.startswith("DeleteRegValue") and "\\Run" in line,
    "delete Software\\PIME":
        lambda line: line.startswith("DeleteRegKey") and line.endswith('"Software\\PIME"'),
    "delete the python tree":
        lambda line: line.startswith("RMDir /r") and "$INSTDIR\\python" in line,
    "delete the Start-menu folder":
        lambda line: line.startswith("RMDir /r") and "$SMPROGRAMS" in line,
}


def assignment(line):
    """(variable, value) for `StrCpy $var value`, else None."""
    match = re.match(r"StrCpy\s+\$(\w+)\s+(\S+)$", line)
    return match and (match.group(1), match.group(2).strip('"'))


def guarded_range(body, start):
    """Indexes of the lines run when the ${If} at body[start] is true: up to its
    ${Else}, ${ElseIf} or ${EndIf}."""
    depth = 0
    for index in range(start + 1, len(body)):
        if re.match(r"\$\{(If|IfNot|Unless)\}", body[index]):
            depth += 1
        elif re.match(r"\$\{(EndIf|EndUnless)\}", body[index]):
            if depth == 0:
                return range(start + 1, index)
            depth -= 1
        elif depth == 0 and re.match(r"\$\{(Else|ElseIf|ElseUnless)\}", body[index]):
            return range(start + 1, index)
    raise AssertionError("no ${EndIf} for " + body[start])


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


class AnswerTests(unittest.TestCase):
    """The prompt in .onInit and the removal in the Prepare section are tied together
    only by a variable. Dropping the assignment, or renaming the variable on one side,
    still compiles and leaves the order above intact, but then every upgrade silently
    skips the removal: old DLLs stay registered, the old python tree and Start-menu
    folder stay, and so do the old registry entries."""

    @classmethod
    def setUpClass(cls):
        cls.functions, sections = read_script()
        cls.sections = [(header, expand(body, cls.functions)) for header, body in sections]
        # the function that shows the prompt, not expanded: relative jumps count
        # its own instructions
        cls.asker = next(body for body in cls.functions.values()
                         if any("$(UNINSTALL_OLD)" in line for line in body))
        cls.prompt = next(i for i, line in enumerate(cls.asker) if "$(UNINSTALL_OLD)" in line)

    def answer(self):
        """(variable, value) recorded when the user clicks OK: the instruction the
        prompt's IDOK jumps to."""
        jump = re.search(r"\bIDOK\s+(\S+)", self.asker[self.prompt].replace("/SD IDOK", ""))
        self.assertIsNotNone(jump, "OK must jump past the Abort")
        target = jump.group(1)
        if target.startswith("+"):
            target = self.prompt + int(target)
            # one line, one instruction: no macros (they expand to several) in between
            for line in self.asker[self.prompt + 1:target]:
                self.assertFalse(line.startswith(("${", "!")), line)
        else:
            target = self.asker.index(target + ":") + 1
        recorded = assignment(self.asker[target])
        self.assertIsNotNone(recorded, "OK must record the answer: " + self.asker[target])
        return recorded

    def test_ok_records_the_answer(self):
        variable, agreed = self.answer()
        # reset before asking, so the removal never runs on a stale answer
        earlier = [assignment(line) for line in self.asker[:self.prompt]]
        earlier = [value for name, value in filter(None, earlier) if name == variable]
        self.assertTrue(earlier, "no default for $" + variable)
        self.assertNotEqual(earlier[-1], agreed)

    def test_nothing_else_records_agreement(self):
        # the removal runs only because the user clicked OK: the assignment the OK
        # jumps to is the only one in the script
        variable, agreed = self.answer()
        found = [line for line in script_lines() if assignment(line) == (variable, agreed)]
        self.assertEqual(len(found), 1, found)

    def test_removal_waits_for_that_answer(self):
        variable, agreed = self.answer()
        body = next(body for header, body in self.sections if any(map(is_teardown, body)))
        guards = [i for i, line in enumerate(body)
                  if re.fullmatch(r'\$\{If\}\s+\$%s\s+==\s+"?%s"?'
                                  % (re.escape(variable), re.escape(agreed)), line)]
        self.assertEqual(len(guards), 1, "Prepare must check $%s == %s" % (variable, agreed))
        guarded = guarded_range(body, guards[0])
        for step, predicate in TEARDOWN_STEPS.items():
            with self.subTest(step=step):
                where = [i for i, line in enumerate(body) if predicate(line)]
                self.assertTrue(where, "the removal no longer does this")
                self.assertTrue(all(i in guarded for i in where), where)


if __name__ == "__main__":
    unittest.main()
