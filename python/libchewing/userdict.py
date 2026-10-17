"""新酷音使用者詞庫的檔案：舊版詞庫的轉換、匯入與驗證。

libchewing 0.13 (Rust) 的使用者詞庫是 chewing.dat (Trie 格式)，舊的 C 版是 SQLite 的
chewing.sqlite3 (userphrase_v1 表格)。0.13 自己就會轉換：開啟一個還不存在的 chewing.dat
時，若同一個目錄有 chewing.sqlite3，就把它的詞匯入新檔。但它是直接開啟舊檔「寫入」：
改成 WAL 模式、加上新版的表格。為了能退回舊版，這裡改成：

1. 舊檔先備份成 chewing-backup-before-0.13.sqlite3 (已有備份就不覆寫)；
2. 在設定目錄下的暫存目錄裡放一份舊檔的複本 (sqlite backup API，一致的快照)，
   拿掉複本中不是合法 UTF-8 的詞 (0.13 讀到這種詞整個轉換就失敗)；
3. 讓 libchewing 在暫存目錄建立 chewing.dat (自己轉換)，關閉 context (同步寫檔)；
4. 重新開啟暫存的 chewing.dat 驗證：舊檔有詞、新檔卻是空的就算失敗；
5. 以 os.rename 搬到設定目錄 (目的地已存在就不覆寫：其他行程已經轉好了)。

原本的 chewing.sqlite3 完全不會被改動：退回舊版時，舊版照樣讀它 (升級後才學到的詞
只在 chewing.dat 裡)。轉換失敗時不建立 chewing.dat，下次再試；呼叫端改用記憶體中的
詞庫，不會讓 libchewing 自己去改舊檔。
"""

import os
import shutil
import sqlite3
import tempfile
from contextlib import closing

from .libchewing import ChewingContext, ChewingError

USER_DICT_NAME = "chewing.dat"
LEGACY_DB_NAME = "chewing.sqlite3"
LEGACY_BACKUP_NAME = "chewing-backup-before-0.13.sqlite3"
# 設定工具改了使用者詞庫之後更新這個檔案的時間，輸入法看到就重建 context
# (0.13 的 context 把詞庫讀進記憶體，不會自己發現別的行程改了檔案)
CHANGE_STAMP_NAME = "chewing-userphrase.stamp"

SQLITE_MAGIC = b"SQLite format 3\x00"

# libchewing userphrase_v1 (舊 C 版) 的欄位
USER_PHRASE_V1_COLUMNS = {"time", "user_freq", "max_freq", "orig_freq", "length", "phrase"} | \
    {"phone_%d" % i for i in range(11)}


class UserDictionaryError(RuntimeError):
    """The old user phrase database cannot be converted, or a file is not a
    usable user phrase dictionary."""


def userDictPath(config_dir):
    return os.path.join(config_dir, USER_DICT_NAME)


def legacyDbPath(config_dir):
    return os.path.join(config_dir, LEGACY_DB_NAME)


def touchChangeStamp(config_dir):
    """通知輸入法使用者詞庫被設定工具改過了"""
    path = os.path.join(config_dir, CHANGE_STAMP_NAME)
    try:
        with open(path, "a"):
            pass
        os.utime(path, None)
    except OSError:
        pass


def changeStampTime(config_dir):
    try:
        return os.path.getmtime(os.path.join(config_dir, CHANGE_STAMP_NAME))
    except OSError:
        return 0.0


def _copySqlite(src, dst):
    """以 sqlite backup API 複製一份一致的快照 (來源可能正在被舊版寫入，或有 -wal 檔)"""
    with closing(sqlite3.connect(src, timeout=5)) as source, closing(sqlite3.connect(dst)) as target:
        source.backup(target)


def checkSqliteUserDb(path):
    """確認 path 是 libchewing 的 SQLite 使用者詞庫 (舊 C 版的 userphrase_v1，或 Rust 版
    0.8–0.13 的 dictionary_v1)，否則丟出 UserDictionaryError。傳回可轉換的詞數"""
    try:
        with closing(sqlite3.connect(path)) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise UserDictionaryError("integrity check failed")
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "dictionary_v1" in tables:
                return conn.execute("SELECT count(*) FROM dictionary_v1").fetchone()[0]
            if not {"userphrase_v1", "config_v1"} <= tables:
                raise UserDictionaryError("not a libchewing user phrase database")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(userphrase_v1)")}
            if not USER_PHRASE_V1_COLUMNS <= columns:
                raise UserDictionaryError("unexpected userphrase_v1 columns")
            return conn.execute("SELECT count(*) FROM userphrase_v1").fetchone()[0]
    except sqlite3.Error as err:
        raise UserDictionaryError("not a valid SQLite database: %s" % err) from err


def _dropInvalidPhrases(path):
    """拿掉複本裡不是合法 UTF-8 的詞 (libchewing 0.13 讀到就整個轉換失敗)。
    傳回剩下的詞數"""
    with closing(sqlite3.connect(path)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        table = "dictionary_v1" if "dictionary_v1" in tables else "userphrase_v1"
        bad = set()
        for (phrase,) in conn.execute("SELECT CAST(phrase AS BLOB) FROM %s" % table):
            try:
                (phrase or b"").decode("utf-8")
            except UnicodeDecodeError:
                bad.add(phrase)
        if bad:
            conn.executemany("DELETE FROM %s WHERE CAST(phrase AS BLOB) = ?" % table, [(p,) for p in bad])
            conn.commit()
        return conn.execute("SELECT count(*) FROM %s" % table).fetchone()[0]


def countPhrases(dat_path, syspath):
    """開啟 dat_path 並傳回裡面的詞數；讀不了 (不是詞庫檔、損毀) 時丟出 UserDictionaryError"""
    try:
        ctx = ChewingContext(syspath=syspath, userpath=dat_path,
                             userdir=os.path.dirname(os.path.abspath(dat_path)))
    except ChewingError as err:
        raise UserDictionaryError(str(err)) from err
    try:
        return len(ctx.userPhrases())
    finally:
        ctx.close()


def convertSqlite(sqlite_path, work_dir, syspath):
    """把 SQLite 使用者詞庫轉成 work_dir 下的 chewing.dat 並傳回它的路徑。
    sqlite_path 本身不會被改動。失敗時丟出 UserDictionaryError"""
    expected = checkSqliteUserDb(sqlite_path)
    copy = os.path.join(work_dir, LEGACY_DB_NAME)  # libchewing 只認這個名字
    try:
        _copySqlite(sqlite_path, copy)
    except sqlite3.Error as err:
        raise UserDictionaryError("cannot copy %s: %s" % (sqlite_path, err)) from err
    remaining = _dropInvalidPhrases(copy)
    dat = os.path.join(work_dir, USER_DICT_NAME)
    # 不接 log 回呼 (接了的話轉換的時間和詞數的平方成正比)；成功與否由下面重新開檔驗證
    ctx = ChewingContext(syspath=syspath, userpath=dat, userdir=work_dir, detectErrors=False)
    ctx.close()  # 寫完檔才傳回
    count = countPhrases(dat, syspath)
    if remaining and not count:
        raise UserDictionaryError("converted %s but no phrase was imported (%d expected)"
                                  % (sqlite_path, expected))
    return dat


def _makeWorkDir(config_dir, prefix):
    return tempfile.mkdtemp(prefix=prefix, dir=config_dir)


def backupLegacyDb(config_dir):
    """舊版詞庫備份一份 (已有備份就不動)。傳回備份路徑，沒有舊檔時傳回 None"""
    legacy = legacyDbPath(config_dir)
    backup = os.path.join(config_dir, LEGACY_BACKUP_NAME)
    if not os.path.exists(legacy):
        return None
    if os.path.exists(backup):
        return backup
    tmp = backup + ".%d.tmp" % os.getpid()
    try:
        _copySqlite(legacy, tmp)
        os.rename(tmp, backup)
    except (OSError, sqlite3.Error):
        # 其他行程剛好也在備份 (目的地已存在)，或是檔案讀不了：退而直接複製檔案
        if not os.path.exists(backup):
            try:
                shutil.copy2(legacy, backup)
            except OSError:
                pass
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
    return backup if os.path.exists(backup) else None


def prepareUserDictionary(config_dir, syspath):
    """傳回輸入法要用的使用者詞庫路徑 (config_dir\\chewing.dat)。

    還沒有 chewing.dat、卻有舊版的 chewing.sqlite3 時，先備份舊檔，再把它轉成
    chewing.dat (見本模組說明)。轉換失敗時丟出 UserDictionaryError，而且不建立
    chewing.dat：呼叫端不可以把這個路徑交給 libchewing (它會自己去改舊檔)，
    應改用記憶體中的詞庫，下次再試"""
    dat = userDictPath(config_dir)
    legacy = legacyDbPath(config_dir)
    if os.path.exists(dat) or not os.path.exists(legacy):
        return dat
    try:
        empty = os.path.getsize(legacy) == 0  # 舊版建立到一半的空檔：沒有詞可以轉換
    except OSError:
        empty = False
    if not empty:
        backupLegacyDb(config_dir)
    work_dir = _makeWorkDir(config_dir, "migrate_")
    try:
        if empty:
            # 一樣在暫存目錄建立 (空的) chewing.dat：讓 libchewing 直接開設定目錄裡不存在的
            # chewing.dat，它會去「轉換」旁邊的 chewing.sqlite3 而改到舊檔
            converted = os.path.join(work_dir, USER_DICT_NAME)
            countPhrases(converted, syspath)
        else:
            converted = convertSqlite(legacy, work_dir, syspath)
        try:
            os.rename(converted, dat)  # 不覆寫：其他行程可能已經轉好、開始用了
        except FileExistsError:
            pass
        except OSError as err:
            if not os.path.exists(dat):
                raise UserDictionaryError("cannot create %s: %s" % (dat, err)) from err
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return dat


def _looksLikeTrieDictionary(data):
    """0.13 的詞庫檔是 DER 編碼：SEQUENCE { UTF8String "CHEW", ... }"""
    if len(data) < 8 or data[0] != 0x30:
        return False
    length_byte = data[1]
    offset = 2 if length_byte < 0x80 else 2 + (length_byte & 0x7F)
    return data[offset:offset + 6] == b"\x0c\x04CHEW"


def importUserDictionary(data, config_dir, syspath):
    """以上傳的檔案內容 (chewing.dat，或舊版的 chewing.sqlite3) 取代使用者詞庫。
    格式不對時丟出 UserDictionaryError，原本的詞庫不變；原本的 chewing.dat 先複製成
    chewing.dat.bak。傳回匯入的詞數"""
    os.makedirs(config_dir, exist_ok=True)
    work_dir = _makeWorkDir(config_dir, "import_")
    try:
        if data.startswith(SQLITE_MAGIC):
            upload = os.path.join(work_dir, "upload.sqlite3")
            with open(upload, "wb") as f:
                f.write(data)
            convert_dir = os.path.join(work_dir, "convert")
            os.mkdir(convert_dir)
            converted = convertSqlite(upload, convert_dir, syspath)
        elif _looksLikeTrieDictionary(data):
            converted = os.path.join(work_dir, USER_DICT_NAME)
            with open(converted, "wb") as f:
                f.write(data)
        else:
            raise UserDictionaryError("not a libchewing user phrase dictionary")
        count = countPhrases(converted, syspath)  # libchewing 讀得了才換上去
        dat = userDictPath(config_dir)
        if os.path.exists(dat):
            try:
                shutil.copy2(dat, dat + ".bak")
            except OSError:
                pass
        os.replace(converted, dat)  # 輸入法隨時可能讀這個檔：整個換掉，不寫一半
        touchChangeStamp(config_dir)
        return count
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
