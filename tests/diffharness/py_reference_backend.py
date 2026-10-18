"""Run python/server.py as a deterministic reference backend for the
differential harness (tests/diffharness/driver.py).

It speaks the launcher's stdio protocol exactly like server.py
("<client_id>|<json>" in, "PIME_MSG|<client_id>|<json>" out) and changes only
what would make two runs differ:

- Clock: cinbase, cinbase.cin and cinbase.config see a virtual clock that starts
  at a fixed time and moves CLOCK_STEP per request. A request with method
  "__advanceClock" and "seconds" moves it further (the driver's {"wait": s}).
- Background loading: the code table, phrase table and reverse lookup tables
  load synchronously when the service asks for them, so the first key always
  sees loaded tables.
- Launches: ShellExecuteW and os.startfile are replaced by recorders, so no
  settings tool or web page is ever opened. A reply to a request that tried to
  launch something gets "_testLaunches": [[name, target basename], ...].
  Sounds likewise become "_testSounds": [...].
- Machine state: Caps Lock reads as off, no key reads as physically down, and
  the Windows app theme reads as light.

The driver sets APPDATA/LOCALAPPDATA/USERPROFILE to a temporary directory, so
the user's real config.json / cincount.json are never read or written.
"""

import ctypes
import os
import sys

PYTHON_DIR = os.environ.get("WIME_PY_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "python"))
for path in (PYTHON_DIR, os.path.join(PYTHON_DIR, "python3")):
    if path not in sys.path:
        sys.path.insert(0, path)
os.chdir(PYTHON_DIR)

CLOCK_START = 1_700_000_000.0
CLOCK_STEP = 0.01


class VirtualTime:
    """Stands in for the time module inside the cinbase modules."""

    def __init__(self, real):
        self._real = real
        self.now = CLOCK_START

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def perf_counter(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)

    def __getattr__(self, name):   # strftime, localtime, ...
        return getattr(self._real, name)


launches = []


def _recorder(name):
    def record(*args, **kwargs):
        target = ""
        for arg in args:
            if isinstance(arg, str) and arg and arg not in ("open", "runas"):
                target = arg
                break
        launches.append([name, os.path.basename(target.strip('"').split('" ')[0])])
        return 42 if name == "ShellExecuteW" else None   # ShellExecuteW: > 32 is success
    return record


ctypes.windll.shell32.ShellExecuteW = _recorder("ShellExecuteW")
os.startfile = _recorder("startfile")

import cinbase           # noqa: E402
import cinbase.cin       # noqa: E402
import cinbase.config    # noqa: E402
import server            # noqa: E402

clock = VirtualTime(cinbase.time)
for module in (cinbase, cinbase.cin, cinbase.config):
    if getattr(module, "time", None) is not None:
        module.time = clock

for name in ("LoadPhraseData", "LoadCinTable", "LoadRCinTable", "LoadHCinTable"):
    cls = getattr(cinbase, name, None)
    if cls is not None:
        cls.start = cls.run      # load in the calling thread

# Machine state the backend would otherwise read from the real keyboard and
# registry: Caps Lock is off, no key is physically down (Shift sides come from
# the scan codes the driver sends), and Windows uses the light app theme.
cinbase.CinBase.getKeyState = lambda *args: 0
cinbase.CinBase.isPressed = lambda *args: False
import candidate_theme   # noqa: E402
candidate_theme.systemPrefersLightTheme = lambda *args, **kwargs: True
for module in list(sys.modules.values()):
    if getattr(module, "systemPrefersLightTheme", None) is not None and module is not candidate_theme:
        module.systemPrefersLightTheme = candidate_theme.systemPrefersLightTheme

# 新酷音 (input_methods/chewing) is imported when the first chewing client is
# created; patch it right after the import, before its first service exists.
# - time: Shift taps (< 0.5 s) read time.time(); the config reload throttle
#   (3 s) reads time.monotonic(). Both see the virtual clock.
# - machine state: Caps Lock off (getCapslockState), no key down (isPressed)
# - candidate_layout measures candidate widths with GDI for the Up/Down step.
#   Fonts and DPI differ between machines, so by default the harness uses a
#   fixed model on both sides (test_measure_texts below; the Rust backend has
#   the same one in test mode): DPI 96, a code point >= U+1100 is one em wide
#   (MulDiv(fontSize, 96, 72) px), any other half an em. WIME_TEST_GDI=1 keeps
#   the real GDI measurement (still at DPI 96) to compare the GDI ports.
import importlib            # noqa: E402
import serviceManager       # noqa: E402
import candidate_layout     # noqa: E402

TEST_DPI = 96


def test_measure_texts(fontName, fontSize, dpi, texts):
    em = candidate_layout.mulDiv(fontSize, dpi, 72)
    return {text: sum(em if ord(ch) >= 0x1100 else em // 2 for ch in text) for text in texts}


candidate_layout.systemDpi = lambda: TEST_DPI
if os.environ.get("WIME_TEST_GDI") != "1":
    candidate_layout.measureTexts = test_measure_texts

_patched_modules = set()


def _patch_chewing(module_name):
    if module_name in _patched_modules:
        return
    _patched_modules.add(module_name)
    mod = importlib.import_module(module_name)
    config_mod = importlib.import_module(module_name.rsplit(".", 1)[0] + ".chewing_config")
    mod.time = clock
    config_mod.time = clock
    # the config was loaded at import time with the real clock
    config_mod.chewingConfig._lastUpdateTime = clock.now
    mod.ChewingTextService.getCapslockState = lambda *args: False
    mod.ChewingTextService.isPressed = lambda *args: False


_create_instance = serviceManager.TextServiceInfo.createInstance


def createInstance(self, client):
    if self.moduleName.endswith(".chewing_ime"):
        _patch_chewing(self.moduleName)
    return _create_instance(self, client)


serviceManager.TextServiceInfo.createInstance = createInstance

sounds = []


class _Sound:
    SND_ASYNC = SND_ALIAS = SND_FILENAME = SND_NODEFAULT = 0

    def PlaySound(self, sound, flags=0):
        sounds.append(sound)

    def MessageBeep(self, kind=0):
        sounds.append("beep")

    def Beep(self, frequency=0, duration=0):
        sounds.append("beep")


cinbase.winsound = _Sound()

_handle = server.Client.handleRequest


def handleRequest(self, msg):
    if msg.get("method") == "__advanceClock":
        clock.now += float(msg.get("seconds", 0))
        return {"seqNum": msg.get("seqNum", 0), "success": True}
    clock.now += CLOCK_STEP
    del launches[:]
    del sounds[:]
    reply = _handle(self, msg)
    if isinstance(reply, dict):
        if launches:
            reply = dict(reply, _testLaunches=[list(l) for l in launches])
        if sounds:
            reply = dict(reply, _testSounds=list(sounds))
    return reply


server.Client.handleRequest = handleRequest

if __name__ == "__main__":
    server.main()
