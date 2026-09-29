#! python3
# Copyright (C) 2016 Hong Jen Yee (PCMan) <pcman.tw@gmail.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

import tornado.escape
import tornado.web
import sys
import os
import json
import sqlite3
import tempfile
from contextlib import closing

current_dir = os.path.dirname(__file__)

# The libchewing package is not in the default python path.
# FIXME: set PYTHONPATH properly so we don't need to add this hack.
sys.path.append(os.path.dirname(os.path.dirname(current_dir)))
sys.path.append(current_dir)

from chewing_config import chewingConfig, defaultValues, normalizeValues, readUserConfig
from libchewing import ChewingContext, ChewingError, CHEWING_DATA_DIR, encodeDataPath
from ctypes import c_uint, byref, create_string_buffer
from config_server import BaseHandler, NoCacheStaticFileHandler, ConfigServerApp

config_dir = os.path.join(os.path.expandvars("%APPDATA%"), "PIME", "chewing")
localdata_dir = os.path.join(os.path.expandvars("%LOCALAPPDATA%"), "PIME", "chewing")

COOKIE_ID = "chewing_config_token"

# libchewing 以 512 bytes 的緩衝區逐行讀取 symbols.dat (含換行 \r\n 與結尾的 \0)，
# 更長的一行會被截斷在字的中間，選字清單出現亂碼
SYMBOLS_MAX_LINE_BYTES = 500

# libchewing 使用者詞庫 (userphrase_v1) 的欄位
USER_PHRASE_COLUMNS = {"time", "user_freq", "max_freq", "orig_freq", "length", "phrase"} | \
    {"phone_%d" % i for i in range(11)}

# syspath 參數可包含多個路徑，用 ; 分隔
# 此處把 user 設定檔目錄插入到 system-wide 資料檔路徑前
# 如此使用者變更設定後，可以比系統預設值有優先權
search_paths = b";".join(
    path for path in (encodeDataPath(chewingConfig.getConfigDir()), encodeDataPath(CHEWING_DATA_DIR)) if path)
user_phrase = chewingConfig.getUserPhrase().encode("UTF-8")
# print(search_paths, user_phrase)
_chewing_ctx = None


def get_chewing_ctx():
    """詞庫編輯器用的 libchewing context，第一次用到時才建立。以前在啟動時建立且不檢查，
    詞庫剛好被鎖住或損毀時設定工具打不開、或詞庫編輯器的每個操作都靜靜地失敗"""
    global _chewing_ctx
    if _chewing_ctx is None:
        try:
            _chewing_ctx = ChewingContext(syspath=search_paths, userpath=user_phrase)
        except ChewingError:
            raise tornado.web.HTTPError(503, reason="Cannot open the user phrase database")
    return _chewing_ctx


def read_text_file(path):
    """讀取 symbols.dat / swkb.dat：容許 BOM 與以 ANSI 字碼頁存檔的舊檔 (以前讀成
    "\\ufeffA ..." 或 ""，設定頁的格式檢查就擋下每一次儲存)"""
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "mbcs"):
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            pass
    else:
        text = raw.decode("utf-8", "replace")
    return text.replace("\r\n", "\n")  # 與以前的文字模式讀檔相同


def save_file(filename, data):
    """寫入 config_dir 下的檔案 (先寫暫存檔再取代)；失敗時丟出例外"""
    target = os.path.join(config_dir, filename)
    tmp_target = target + ".tmp"
    try:
        with open(tmp_target, "w", encoding="UTF-8") as f:
            f.write(data)
            if filename == "symbols.dat":
                f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_target, target)
    except Exception:
        try:
            if os.path.exists(tmp_target):
                os.remove(tmp_target)
        except Exception:
            pass
        raise


def check_user_phrase_db(path):
    """確認 path 是可以用的 libchewing 使用者詞庫，否則丟出例外。以前只檢查有沒有
    config_v1 表格，欄位不對的檔案匯入後，輸入法就再也開不了詞庫"""
    with closing(sqlite3.connect(path)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("integrity check failed")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"userphrase_v1", "config_v1"} <= tables:
            raise ValueError("not a libchewing user phrase database")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(userphrase_v1)")}
        if not USER_PHRASE_COLUMNS <= columns:
            raise ValueError("unexpected userphrase_v1 columns")
        conn.execute("SELECT phrase FROM userphrase_v1").fetchall()  # 詞彙必須是合法的 UTF-8


def import_user_phrase_db(data):
    """以上傳的檔案內容取代使用者詞庫；格式不對時丟出例外，原本的詞庫不變"""
    os.makedirs(config_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(suffix=".sqlite3", prefix="import_", dir=config_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        check_user_phrase_db(temp_path)
        # 用 sqlite 的 backup API 寫進原本的詞庫：輸入法的 libchewing 一直開著這個檔案，
        # 以前直接覆寫檔案內容 (不是原子操作)，寫到一半時輸入法可能讀到損毀的資料庫
        with closing(sqlite3.connect(temp_path)) as src, \
                closing(sqlite3.connect(chewingConfig.getUserPhrase(), timeout=5)) as dst:
            src.backup(dst)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


class ConfigHandler(BaseHandler):

    @tornado.web.authenticated
    def get(self):  # get config
        data = {
            "config": self.load_config(),
            "symbols": self.load_data("symbols.dat"),
            "swkb": self.load_data("swkb.dat"),
        }
        self.write(data)

    @tornado.web.authenticated
    def post(self):  # save config
        data = tornado.escape.json_decode(self.request.body)
        #print(data)
        config = data.get("config", None)
        symbols = data.get("symbols", None)
        swkb = data.get("swkb", None)
        if config is not None and not isinstance(config, dict):
            raise tornado.web.HTTPError(400, reason="config must be an object")
        if symbols is not None:
            if not isinstance(symbols, str):
                raise tornado.web.HTTPError(400, reason="symbols must be a string")
            if any(len(line.encode("utf-8")) > SYMBOLS_MAX_LINE_BYTES for line in symbols.split("\n")):
                raise tornado.web.HTTPError(400, reason="symbols.dat line too long")
        if swkb is not None and not isinstance(swkb, str):
            raise tornado.web.HTTPError(400, reason="swkb must be a string")
        try:
            # ensure the config dir exists
            os.makedirs(config_dir, exist_ok=True)
            # write the config to files
            if config is not None:
                save_file("config.json", json.dumps(config, indent=2))
            if symbols is not None:
                save_file("symbols.dat", symbols)
            if swkb is not None:
                save_file("swkb.dat", swkb)
        except OSError as err:
            # 以前錯誤被吞掉、一律回答成功，設定頁顯示「已儲存」但檔案沒變
            print("cannot save settings:", err, file=sys.stderr)
            raise tornado.web.HTTPError(500, reason="Cannot save the settings")
        self.write('{"return":true}')

    def load_config(self):
        defaults = defaultValues()
        config = dict(defaults)  # the default settings
        try:
            # override default values with user config
            config.update(readUserConfig(os.path.join(config_dir, "config.json")))
        except FileNotFoundError:
            pass
        except Exception as e:
            print(e)
        # 設定頁清空的欄位 (null)、超出範圍的值以預設值顯示
        return normalizeValues(config, defaults)

    def load_data(self, name):
        for path in (os.path.join(config_dir, name), os.path.join(CHEWING_DATA_DIR, name)):
            try:
                return read_text_file(path)
            except FileNotFoundError:
                continue
            except OSError:
                return ""
        return ""


class UserPhraseHandler(BaseHandler):

    @tornado.web.authenticated
    def get(self):  # get all user phrases
        chewing_ctx = get_chewing_ctx()
        phrase_len = c_uint(0)
        bopomofo_len = c_uint(0)
        phrases = []
        ret = chewing_ctx.userphrase_enumerate()
        print(chewing_ctx, ret)
        while chewing_ctx.userphrase_has_next(byref(phrase_len), byref(bopomofo_len)):
            phrase_buf = create_string_buffer(phrase_len.value)
            bopomofo_buf = create_string_buffer(bopomofo_len.value)
            chewing_ctx.userphrase_get(phrase_buf, phrase_len, bopomofo_buf, bopomofo_len)
            # 匯入的詞庫可能有不是 UTF-8 的詞，以前整個清單載入失敗
            phrase = phrase_buf.value.decode("utf-8", "replace")
            bopomofo = bopomofo_buf.value.decode("utf-8", "replace")
            phrases.append({
                "phrase": phrase,
                "bopomofo": bopomofo
            })
        self.write({"data": phrases})

    @tornado.web.authenticated
    def post(self):  # add new user phrases or remove existing ones
        chewing_ctx = get_chewing_ctx()
        data = tornado.escape.json_decode(self.request.body)
        added = data.get("add", [])
        removed = data.get("remove", [])
        print("add", added, "remove", removed)

        # 0: error (any item failed), 1: success
        result = 1

        for item in added:  # add new phrases
            phrase = item["phrase"].encode("utf8")
            bopomofo = item["bopomofo"].encode("utf8")
            if chewing_ctx.userphrase_add(phrase, bopomofo) <= 0:
                result = 0

        for item in removed:  # remove existing phrases
            phrase = item["phrase"].encode("utf8")
            bopomofo = item["bopomofo"].encode("utf8")
            if chewing_ctx.userphrase_remove(phrase, bopomofo) <= 0:
                result = 0

        self.write({"result": result})


class UserPhraseFileHandler(BaseHandler):

    @tornado.web.authenticated
    def get(self):  # download user phrase file
        user_phrase_file = os.path.join(config_dir, "chewing.sqlite3")
        if not os.path.exists(user_phrase_file):
            raise tornado.web.HTTPError(404)
        self.set_header("Content-Type", "application/force-download")
        self.set_header("Content-Disposition", "attachment; filename=chewing.sqlite3")
        with open(user_phrase_file, "rb") as f:
            try:
                self.write(f.read())
                f.close()
                self.finish()
                return
            except:
                raise tornado.web.HTTPError(404)
        raise tornado.web.HTTPError(500)

    @tornado.web.authenticated
    def post(self):  # upload file
        # 以前驗證用的 cursor 沒關，暫存檔刪不掉，每次都回報「格式錯誤」，
        # 但原本的詞庫其實已經被覆寫了
        try:
            import_user_phrase_db(self.request.files["import_user_phrase"][0]["body"])
        except Exception as err:
            print("cannot import the user phrase database:", err, file=sys.stderr)
            self.write("詞庫格式錯誤，可能檔案損毀或選到錯誤的檔案，原本的詞庫沒有變更。請按上一頁返回")
            return
        response_html = """
            <script type="text/javascript">
                alert("匯入詞庫成功！");
                window.location = "./user_phrase_editor.html";
            </script>
        """
        self.write(response_html)


class ConfigApp(ConfigServerApp):

    def __init__(self):
        handlers = [
            (r"/(.*\.html)", NoCacheStaticFileHandler, {"path": current_dir}),
            (r"/((css|images|js|fonts)/.*)", NoCacheStaticFileHandler, {"path": current_dir}),
            (r"/(version.txt)", NoCacheStaticFileHandler, {"path": os.path.join(current_dir, "../../../")}),
            (r"/config", ConfigHandler),  # main configuration handler
            (r"/user_phrases", UserPhraseHandler),  # user phrase editor
            (r"/user_phrase_file", UserPhraseFileHandler),  # export user phrase
        ]
        super().__init__(handlers, cookie_id=COOKIE_ID, main_page="config_tool", localdata_dir=localdata_dir)


def main():
    app = ConfigApp()
    if len(sys.argv) >= 2 and sys.argv[1] == "user_phrase_editor":
        tool_name = "user_phrase_editor"
    else:
        tool_name = "config_tool"
    app.run(tool_name)


if __name__ == "__main__":
    main()
