import os

from .libchewing import ChewingContext, ChewingError, ChewingFault

_current_dir = os.path.dirname(__file__)

CHEWING_DATA_DIR = os.path.join(_current_dir, "data")


def encodeDataPath(path):
    """Encode a directory for the syspath argument of ChewingContext.

    The bundled (old C) libchewing opens its data files with ANSI APIs (fopen,
    ...), so the path must be in the system code page (mbcs). With UTF-8, the
    user's own symbols.dat / swkb.dat were ignored when the Windows user name is
    not ASCII. A path the code page cannot represent falls back to its 8.3 short
    name; None if that does not work either (leave the directory out).
    The user phrase database is opened by sqlite, which takes UTF-8 instead."""
    candidates = [path]
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if 0 < ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf)) < len(buf):
                candidates.append(buf.value)
        except Exception:
            pass
    encoding = "mbcs" if os.name == "nt" else "utf-8"
    for candidate in candidates:
        try:
            return candidate.encode(encoding)
        except UnicodeEncodeError:
            pass
    return None

# from libchewing/include/global.h
CHINESE_MODE = 1
ENGLISH_MODE = 0
FULLSHAPE_MODE = 1
HALFSHAPE_MODE = 0
