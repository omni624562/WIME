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
