"""Test harness that drives a real CinBase IME (大易 / 酷倉) with the real code
tables, the same way the C++ side does per keystroke:
filterKeyDown -> onKeyDown -> filterKeyUp -> onKeyUp through TextService.handleRequest.

Tables come from python/cinbase/json/, which build.bat (tools/cintojson.py)
generates and git ignores; tests using this harness are skipped if they are
missing. APPDATA is redirected to a temporary directory for the whole test
class, so the user's real config.json / cincount.json are never read or written.
"""

import importlib.util
import json
import os
import sys
import tempfile
import time
import traceback
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
JSON_DIR = os.path.join(PYTHON_DIR, "cinbase", "json")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

import cinbase  # noqa: E402
from keycodes import VK_BACK, VK_CONTROL, VK_DELETE, VK_DOWN, VK_END, VK_ESCAPE  # noqa: E402
from keycodes import VK_HOME, VK_LEFT, VK_NEXT, VK_PRIOR, VK_RETURN, VK_RIGHT  # noqa: E402
from keycodes import VK_SHIFT, VK_SPACE, VK_UP  # noqa: E402

TABLES_AVAILABLE = all(os.path.exists(os.path.join(JSON_DIR, name))
                       for name in ("dayi4.json", "checj.json", "thdayi.json"))

requires_tables = unittest.skipUnless(
    TABLES_AVAILABLE, "cinbase/json tables not generated (run python/cinbase/tools/cintojson.py)")

IME_MODULES = {
    "chedayi": ("chedayi_ime.py", "CheDayiTextService"),
    "checj": ("checj_ime.py", "CheCJTextService"),
}
_modules = {}


def _ime_class(ime):
    if ime not in _modules:
        filename, _ = IME_MODULES[ime]
        name = "%s_for_tests" % ime
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(PYTHON_DIR, "input_methods", ime, filename))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _modules[ime] = module
    return getattr(_modules[ime], IME_MODULES[ime][1])


class DummyClient:
    isWindows8Above = True
    isMetroApp = False
    isUiLess = False
    isConsole = False


class IsolatedAppData:
    """Point APPDATA/HOME at a temp dir; restore on close()."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = self._tmp.name
        self._saved = {k: os.environ.get(k) for k in ("APPDATA", "USERPROFILE", "HOME")}
        for key in self._saved:
            os.environ[key] = self.path

    def ime_dir(self, ime):
        path = os.path.join(self.path, "PIME", ime)
        os.makedirs(path, exist_ok=True)
        return path

    def close(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()


def wait_for_phrase_table(timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cinbase.PhraseData.phrase is not None and not cinbase.PhraseData.loading:
            return
        time.sleep(0.02)


def write_user_config(ime, config):
    """Write %APPDATA%\\PIME\\<ime>\\config.json (APPDATA must already be isolated)."""
    path = os.path.join(os.environ["APPDATA"], "PIME", ime)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "config.json"), "w", encoding="utf-8") as f:
        f.write(config if isinstance(config, str) else json.dumps(config))
    return os.path.join(path, "config.json")


def remove_user_config(ime):
    path = os.path.join(os.environ["APPDATA"], "PIME", ime, "config.json")
    if os.path.exists(path):
        os.remove(path)


# The modern horizontal layout shows candidatePerRow (6) candidates per page, so
# short codes already have 2+ pages; tests about paging pin it explicitly.
MODERN_LAYOUT = dict(candidateModernStyle=True, candidateLayout="horizontal", candidatePerRow=6)


def make_service(ime="chedayi", user_config=None, **overrides):
    """A fresh text service with the shipped defaults applied.
    user_config: written as the user's config.json before the service is created
    (use it for settings that pick a table, e.g. selCinType).
    overrides: set on the config object afterwards and applied with applyConfig."""
    if user_config is not None:
        write_user_config(ime, user_config)
    try:
        service = _ime_class(ime)(DummyClient())
    finally:
        if user_config is not None:
            remove_user_config(ime)
    wait_for_phrase_table()
    for key, value in overrides.items():
        setattr(service.cfg, key, value)
    if overrides:
        cinbase.CinBase.applyConfig(service)
    service.currentReply = {}
    return service


_SYMBOL_VK = {
    "'": 0xDE, '"': 0xDE, "[": 0xDB, "{": 0xDB, "]": 0xDD, "}": 0xDD,
    "-": 0xBD, "_": 0xBD, "\\": 0xDC, "|": 0xDC, "=": 0xBB, "+": 0xBB,
    ";": 0xBA, ":": 0xBA, ",": 0xBC, "<": 0xBC, ".": 0xBE, ">": 0xBE,
    "/": 0xBF, "?": 0xBF, "`": 0xC0, "~": 0xC0,
}
_SHIFTED_DIGITS = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
                   "^": "6", "&": "7", "*": "8", "(": "9", ")": "0"}
_SHIFTED_SYMBOLS = set('"{}_|+:<>?~') | set(_SHIFTED_DIGITS)
_NAMED = {
    "SPACE": (0x20, VK_SPACE), "ENTER": (0x0D, VK_RETURN), "ESC": (0x1B, VK_ESCAPE),
    "BACK": (0x08, VK_BACK), "LEFT": (0, VK_LEFT), "RIGHT": (0, VK_RIGHT),
    "UP": (0, VK_UP), "DOWN": (0, VK_DOWN), "HOME": (0, VK_HOME), "END": (0, VK_END),
    "PGUP": (0, VK_PRIOR), "PGDN": (0, VK_NEXT), "DEL": (0, VK_DELETE),
}


def key_event(key, shift=False, ctrl=False, down=True):
    if key in _NAMED:
        char_code, key_code = _NAMED[key]
    else:
        char_code = ord(key)
        if key.isascii() and key.isalpha():
            key_code = ord(key.upper())
            shift = shift or key.isupper()
        elif key.isdigit():
            key_code = ord(key)
        elif key in _SHIFTED_DIGITS:
            key_code = ord(_SHIFTED_DIGITS[key])
            shift = True
        elif key in _SYMBOL_VK:
            key_code = _SYMBOL_VK[key]
            shift = shift or key in _SHIFTED_SYMBOLS
        else:
            raise ValueError(key)
    states = {}
    if down and key_code:
        states[str(key_code)] = 0x80
    if shift:
        states[str(VK_SHIFT)] = 0x80
    if ctrl:
        states[str(VK_CONTROL)] = 0x80
    return {"charCode": char_code, "keyCode": key_code, "repeatCount": 1,
            "scanCode": 0, "isExtended": False, "keyStates": states}


class BackendError(AssertionError):
    """A request raised inside the backend - server.py would reply success:false
    and the C++ side would reset the whole pipe connection."""


def _send(service, method, message, key):
    try:
        return service.handleRequest(dict(message, method=method, seqNum=1))
    except Exception:
        service.currentReply = {}
        raise BackendError("%s raised on key %r:\n%s" % (method, key, traceback.format_exc()))


def press(service, key, shift=False, ctrl=False):
    """Send one key like the C++ side does (onKeyDown/onKeyUp only when the
    matching filter call returned True); return the onKeyDown reply or {}."""
    down, up = key_event(key, shift, ctrl), key_event(key, shift, ctrl, down=False)
    reply = {}
    if _send(service, "filterKeyDown", down, key).get("return"):
        reply = _send(service, "onKeyDown", down, key)
    if _send(service, "filterKeyUp", up, key).get("return"):
        _send(service, "onKeyUp", up, key)
    return reply


def type_keys(service, keys):
    """keys: iterable of key names/chars, or (key, "S"/"C"/"SC") tuples.
    Returns (list of committed strings, last onKeyDown reply)."""
    commits, last = [], {}
    for key in keys:
        if isinstance(key, tuple):
            last = press(service, key[0], shift="S" in key[1], ctrl="C" in key[1])
        else:
            last = press(service, key)
        if last.get("commitString"):
            commits.append(last["commitString"])
    return commits, last


def request(service, method, **fields):
    """Send a non-key request (onCommand, onKillFocus, ...); raise BackendError on failure."""
    try:
        return service.handleRequest(dict(fields, method=method, seqNum=1))
    except Exception:
        service.currentReply = {}
        raise BackendError("%s raised:\n%s" % (method, traceback.format_exc()))
