"""Test harness that drives the real 新酷音 (ChewingTextService) with the real
libchewing (python/libchewing/chewing.dll, 32-bit, and its dictionary), the way
the C++ side does per keystroke: onActivate, then filterKeyDown -> onKeyDown ->
filterKeyUp -> onKeyUp through TextService.handleRequest.

chewingConfig reads %APPDATA%\\PIME\\chewing when the module is imported and the
user phrase database lives there too, so call isolate() (or create an
cinbase_harness.IsolatedAppData) before load_module(): the user's real settings
and learned phrases are never read or written.
"""

import copy
import importlib
import os
import sys

import cinbase_harness as _base
from cinbase_harness import (BackendError, IsolatedAppData, key_event, press,  # noqa: F401
                             request, type_keys)

ROOT = _base.ROOT
PYTHON_DIR = _base.PYTHON_DIR

_module = None
_services = []


def load_module():
    """Import input_methods.chewing.chewing_ime (APPDATA must already be isolated)."""
    global _module
    if _module is None:
        if PYTHON_DIR not in sys.path:
            sys.path.insert(0, PYTHON_DIR)
        _module = importlib.import_module("input_methods.chewing.chewing_ime")
    return _module


def config():
    return load_module().chewingConfig


class DummyClient:
    isWindows8Above = True
    isMetroApp = False
    isUiLess = False
    isConsole = False


class ConfigOverride:
    """Set attributes on the shared chewingConfig; restore() puts them back."""

    def __init__(self, **overrides):
        self.cfg = config()
        self.saved = copy.deepcopy(self.cfg.__dict__)
        for key, value in overrides.items():
            setattr(self.cfg, key, value)

    def restore(self):
        self.cfg.__dict__.clear()
        self.cfg.__dict__.update(self.saved)


def make_service(**overrides):
    """A new ChewingTextService, activated like the C++ side does.
    overrides: set on the shared chewingConfig before activation; the caller must
    restore them (use ConfigOverride, or config_override() in a TestCase)."""
    module = load_module()
    for key, value in overrides.items():
        setattr(module.chewingConfig, key, value)
    service = module.ChewingTextService(DummyClient())
    request(service, "onActivate", isKeyboardOpen=True)
    service.currentReply = {}
    _services.append(service)
    return service


def close_all():
    """Deactivate every service made so far and free the libchewing contexts, so
    the user phrase database under the temporary APPDATA is closed."""
    import gc
    while _services:
        service = _services.pop()
        try:
            service.onDeactivate()
        except Exception:
            pass
        service.chewingContext = None
    gc.collect()


def commit_text(replies):
    return "".join(r.get("commitString", "") for r in replies if r)
