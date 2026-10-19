"""What the WIME installer (installer/installer.nsi, built with /DNO_SIMP_CHINESE
/DONLY_DAYI_CHEWING_CHECJ) really contains: build() compiles it with makensis /V4
into a temporary file (never over the release installer in installer\\) and reads
from the log every file it adds, every Start-menu shortcut and every registry
string it writes.

Paths are relative to $INSTDIR, with backslashes, e.g. "cinbase_rs\\wime-config.exe".
Files under $PLUGINSDIR (the installer's own temporary copies) are left out.

The build needs the outputs of build.bat (the DLLs, PIMELauncher.exe,
cinbase-rs's wime-cinbase.exe and wime-config.exe, both the 32-bit x86 and the
ARM64 builds of those three, python/cinbase/json/*.json).
missing_outputs() lists the ones that are not there.

Run as a script to print the installer's size and file list:
    python\\python3\\python.exe tests\\installer_layout.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
INSTALLER_DIR = os.path.join(ROOT, "installer")
SCRIPT = os.path.join(INSTALLER_DIR, "installer.nsi")
DEFINES = ("/DNO_SIMP_CHINESE", "/DONLY_DAYI_CHEWING_CHECJ")
RUST_TARGET = os.path.join(ROOT, "cinbase-rs", "target", "i686-pc-windows-msvc", "release")
# the native ARM64 builds the installer puts in the same places on ARM64 Windows
# (source_of() and stage() give the 32-bit x86 ones, which run on any test machine)
ARM64_PROGRAMS = {
    "PIMELauncher.exe": os.path.join(ROOT, "PIMELauncher", "target", "aarch64-pc-windows-msvc", "release", "PIMELauncher.exe"),
    r"cinbase_rs\wime-cinbase.exe": os.path.join(ROOT, "cinbase-rs", "target", "aarch64-pc-windows-msvc", "release", "wime-cinbase.exe"),
    r"cinbase_rs\wime-config.exe": os.path.join(ROOT, "cinbase-rs", "target", "aarch64-pc-windows-msvc", "release", "wime-config.exe"),
}

_PROGRAM_FILES = (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                  os.environ.get("ProgramFiles", r"C:\Program Files"))
MAKENSIS = next((path for path in [shutil.which("makensis")] + [
    os.path.join(base, "NSIS", *sub, "makensis.exe")
    for base in _PROGRAM_FILES for sub in ((), ("Bin",))] if path and os.path.isfile(path)), None)

# build outputs the installer packs (relative to the repo)
BUILD_OUTPUTS = (
    r"build\PIMETextService\Release\PIMETextService.dll",
    r"build64\PIMETextService\Release\PIMETextService.dll",
    r"build\PIMELauncher\PIMELauncher.exe",
    r"cinbase-rs\target\i686-pc-windows-msvc\release\wime-cinbase.exe",
    r"cinbase-rs\target\i686-pc-windows-msvc\release\wime-config.exe",
    r"PIMELauncher\target\aarch64-pc-windows-msvc\release\PIMELauncher.exe",
    r"cinbase-rs\target\aarch64-pc-windows-msvc\release\wime-cinbase.exe",
    r"cinbase-rs\target\aarch64-pc-windows-msvc\release\wime-config.exe",
    r"python\cinbase\json\dayi3.json",
)


def missing_outputs():
    return [path for path in BUILD_OUTPUTS if not os.path.isfile(os.path.join(ROOT, path))]


def _join(*parts):
    return "\\".join(p for p in parts if p)


def _instdir_rel(path):
    """$INSTDIR\\a\\b -> a\\b; None for anything outside $INSTDIR."""
    path = path.replace("/", "\\")
    if path == "$INSTDIR":
        return ""
    if path.lower().startswith("$instdir\\"):
        return path[len("$INSTDIR\\"):]
    return None


class Layout:
    """The parsed /V4 log of one installer build."""

    def __init__(self, log, size):
        self.log, self.size = log, size
        self.files = []        # dest relative to $INSTDIR, in the order added (repeats kept)
        self.sources = {}      # dest -> source relative to installer\ when the log names it
        self.shortcuts = []    # (link, target, parameters, icon)
        self.registry = []     # (key\value, data) of WriteRegStr
        self._parse()

    def _parse(self):
        outpath, pending = None, None
        for line in self.log.splitlines():
            line = line.strip()
            match = re.match(r'SetOutPath: "(.*)"$', line)
            if match:
                outpath = _instdir_rel(match.group(1))
                continue
            match = re.match(r'File: Descending to: "(.*)"$', line)
            if match:
                pending = (pending or []) + [("d", match.group(1).rstrip("\\"))]
                continue
            match = re.match(r'File: Returning to: "(.*)"$', line)
            if match:
                base, current, source_dir = match.group(1).rstrip("\\"), "", match.group(1).rstrip("\\")
                for kind, value in pending or []:
                    if kind == "d":
                        if value.lower() == base.lower():
                            current = ""
                        elif value.lower().startswith(base.lower() + "\\"):
                            current = value[len(base) + 1:]
                        else:
                            raise AssertionError("cannot place %r under %r" % (value, base))
                        source_dir = value
                    elif outpath is not None:
                        self._add(_join(outpath, current, value), _join(source_dir, value))
                pending = None
                continue
            match = re.match(r'File: "([^"]*)"->"([^"]*)"( |$)', line)
            if match:
                # File /oname=: a path of its own, or a name in the current SetOutPath
                target = match.group(2)
                dest = _instdir_rel(target) if "$" in target else (
                    None if outpath is None else _join(outpath, target))
                if dest is not None:
                    self._add(dest, None)
                continue
            match = re.match(r'File: "([^"]*)"( |$)', line)
            if match:
                if pending is not None:
                    pending.append(("f", match.group(1)))
                elif outpath is not None:
                    self._add(_join(outpath, match.group(1)), None)
                continue
            match = re.match(r'CreateShortcut: "([^"]*)"->"([^"]*)" (.*?) icon:(.*),\d+, nwd=', line)
            if match:
                self.shortcuts.append(match.groups())
                continue
            match = re.match(r"WriteRegStr: (\w+\\.*?)=(.*)$", line)
            if match:
                self.registry.append(match.groups())

    def _add(self, dest, source):
        self.files.append(dest)
        if source:
            self.sources[dest] = source

    def installed(self):
        """The installed files, case-folded for lookups: {lower path: path}."""
        return {path.lower(): path for path in self.files}

    def source_of(self, dest):
        """The repo file a destination comes from: the log names the source of
        files added by File /r; the others follow the layout (data\\ mirrors the
        repo's python\\ folder). None when unknown."""
        if dest in self.sources:
            return os.path.normpath(os.path.join(INSTALLER_DIR, self.sources[dest]))
        parts = dest.split("\\")
        fixed = {
            "version.txt": os.path.join(ROOT, "version.txt"),
            "backends.json": os.path.join(INSTALLER_DIR, "backends-dayi-chewing-checj.json"),
            "PIMELauncher.exe": os.path.join(ROOT, "build", "PIMELauncher", "PIMELauncher.exe"),
            r"x86\PIMETextService.dll": os.path.join(ROOT, "build", "PIMETextService", "Release", "PIMETextService.dll"),
            r"x64\PIMETextService.dll": os.path.join(ROOT, "build64", "PIMETextService", "Release", "PIMETextService.dll"),
            r"arm64\PIMETextService.dll": os.path.join(ROOT, "build_arm64", "PIMETextService", "Release", "PIMETextService.dll"),
        }
        if dest in fixed:
            return fixed[dest]
        if parts[0] == "data":
            return os.path.join(ROOT, "python", *parts[1:])
        if parts[0] == "cinbase_rs" and len(parts) == 2:
            return os.path.join(RUST_TARGET, parts[1])
        if parts[:2] == ["cinbase_rs", "input_methods"] and len(parts) == 4:
            if parts[3] == "ime.json":
                return os.path.join(ROOT, "cinbase-rs", "input_methods", parts[2], "ime.json")
            return os.path.join(ROOT, "python", "input_methods", parts[2], parts[3])
        return None

    def stage(self, target):
        """Copy every installed file to its place under `target` (a fake $INSTDIR)."""
        for dest in sorted(set(self.files)):
            source = self.source_of(dest)
            if source is None or not os.path.isfile(source):
                raise AssertionError("no source for %s (%s)" % (dest, source))
            path = os.path.join(target, *dest.split("\\"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copyfile(source, path)


def build(log_path=None):
    """Compile the limited installer into a temporary file with /V4; returns a Layout."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "wime-test-build.exe")  # not *setup*: NSIS warns about compatibility shims
        result = subprocess.run([MAKENSIS] + list(DEFINES) + ["/V4", "/DOUTFILE=" + out, SCRIPT],
                                cwd=INSTALLER_DIR, capture_output=True, timeout=1800)
        # makensis echoes the script's UTF-8 text in the console code page; only the
        # ASCII paths matter here
        log = result.stdout.decode("utf-8", "replace")
        if result.returncode != 0:
            raise AssertionError("makensis failed (%d):\n%s\n%s" % (
                result.returncode, log[-4000:], result.stderr.decode("utf-8", "replace")[-2000:]))
        size = os.path.getsize(out)
    if log_path:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(log)
    return Layout(log, size)


_CACHE = {}


def cached_build():
    """build(), once per test run."""
    if "layout" not in _CACHE:
        _CACHE["layout"] = build()
    return _CACHE["layout"]


if __name__ == "__main__":
    layout = build(sys.argv[1] if len(sys.argv) > 1 else None)
    print("installer size: %d bytes" % layout.size)
    total = 0
    for path in sorted(set(layout.files), key=str.lower):
        source = layout.source_of(path)
        size = os.path.getsize(source) if source and os.path.isfile(source) else 0
        total += size
        print("%10d  %s" % (size, path))
    print("%d files, %d bytes" % (len(set(layout.files)), total))
