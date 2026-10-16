import os

from .libchewing import ChewingContext, ChewingError, ChewingFault, version
from .userdict import UserDictionaryError, prepareUserDictionary, importUserDictionary, \
    touchChangeStamp, changeStampTime, USER_DICT_NAME, LEGACY_DB_NAME, LEGACY_BACKUP_NAME

_current_dir = os.path.dirname(__file__)

CHEWING_DATA_DIR = os.path.join(_current_dir, "data")


def encodeDataPath(path):
    """Encode a directory for the syspath argument of ChewingContext.

    libchewing 0.13 (Rust) takes every path as UTF-8, so a non-ASCII user name
    works without the old work-arounds (the C version needed the ANSI code page
    and, failing that, the 8.3 short name)."""
    if path is None:
        return None
    return path.encode("utf-8")


def searchPath(*dirs):
    """syspath 參數：用 ; 分隔的多個目錄，前面的優先 (使用者設定目錄放在內建資料前面，
    使用者自己的 symbols.dat / swkb.dat 才會蓋過預設值)"""
    return b";".join(encodeDataPath(path) for path in dirs if path)


# from libchewing/include/global.h
CHINESE_MODE = 1
ENGLISH_MODE = 0
FULLSHAPE_MODE = 1
HALFSHAPE_MODE = 0
