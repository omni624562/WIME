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

import sys
import os
import json

current_dir = os.path.dirname(__file__)

# The libchewing package is not in the default python path.
# FIXME: set PYTHONPATH properly so we don't need to add this hack.
sys.path.append(os.path.dirname(os.path.dirname(current_dir)))
sys.path.append(current_dir)

from chewing_config import chewingConfig, defaultValues, normalizeValues, readUserConfig
from libchewing import ChewingContext, ChewingError, CHEWING_DATA_DIR, searchPath, \
    prepareUserDictionary, importUserDictionary, touchChangeStamp, UserDictionaryError
from config_server import BaseHandler, HTTPError, NoCacheStaticFileHandler, ConfigServerApp, authenticated

config_dir = os.path.join(os.path.expandvars("%APPDATA%"), "PIME", "chewing")
localdata_dir = os.path.join(os.path.expandvars("%LOCALAPPDATA%"), "PIME", "chewing")

COOKIE_ID = "chewing_config_token"

# 舊的 C 版 libchewing 以 512 bytes 的緩衝區逐行讀取 symbols.dat，更長的一行會被截斷
# 在字的中間。0.13 版沒有這個限制 (內附的 symbols.dat 就有 800 多 bytes 的表情符號列)，
# 只擋明顯異常的大小
SYMBOLS_MAX_LINE_BYTES = 16384

# syspath 參數可包含多個路徑，用 ; 分隔
# 此處把 user 設定檔目錄插入到 system-wide 資料檔路徑前
# 如此使用者變更設定後，可以比系統預設值有優先權
search_paths = searchPath(chewingConfig.getConfigDir(), CHEWING_DATA_DIR)


def open_chewing_ctx():
    """詞庫編輯器用的 libchewing context，每個請求開一個、用完關掉 (with 區塊)。
    libchewing 0.13 把整個使用者詞庫讀進記憶體，關閉時才寫回檔案：一直開著的話，
    看不到輸入法之後學到的詞，編輯的結果也要等設定工具結束才存檔。
    詞庫損毀、被鎖住，或舊詞庫轉換失敗時回 503 (以前詞庫編輯器的每個操作都靜靜地失敗)"""
    try:
        user_phrase = prepareUserDictionary(config_dir, search_paths)
        return ChewingContext(syspath=search_paths, userpath=user_phrase, userdir=config_dir)
    except (ChewingError, UserDictionaryError) as err:
        print("cannot open the user phrase dictionary:", err, file=sys.stderr)
        raise HTTPError(503, reason="Cannot open the user phrase database")


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


def normalize_symbols(text):
    """symbols.dat 的每一行都是 ` 符號選單的一項，libchewing 把空行讀成沒有名稱的
    空白選項。去掉空行、結尾剛好一個換行。以前設定頁與這裡各補一個換行，每編輯一次
    特殊符號，檔案結尾就多一個空行、選單就多一個空白選項"""
    lines = [line for line in text.replace("\r\n", "\n").split("\n") if line.rstrip("\r")]
    return "".join(line + "\n" for line in lines)


def save_file(filename, data):
    """寫入 config_dir 下的檔案 (先寫暫存檔再取代)；失敗時丟出例外"""
    target = os.path.join(config_dir, filename)
    tmp_target = target + ".tmp"
    try:
        with open(tmp_target, "w", encoding="UTF-8") as f:
            f.write(data)
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


def import_user_phrase_db(data):
    """以上傳的檔案內容取代使用者詞庫：新版的 chewing.dat，或舊版匯出的 chewing.sqlite3
    (轉換成 chewing.dat)。格式不對時丟出例外，原本的詞庫不變"""
    os.makedirs(config_dir, exist_ok=True)
    # 還沒轉換的舊詞庫先轉換、備份，匯入的內容才不會在下次開啟時又被舊詞庫取代
    prepareUserDictionary(config_dir, search_paths)
    return importUserDictionary(data, config_dir, search_paths)


class ConfigHandler(BaseHandler):

    @authenticated
    def get(self):  # get config
        data = {
            "config": self.load_config(),
            "symbols": self.load_data("symbols.dat"),
            "swkb": self.load_data("swkb.dat"),
        }
        self.write(data)

    @authenticated
    def post(self):  # save config
        data = json.loads(self.request.body)
        #print(data)
        config = data.get("config", None)
        symbols = data.get("symbols", None)
        swkb = data.get("swkb", None)
        if config is not None and not isinstance(config, dict):
            raise HTTPError(400, reason="config must be an object")
        if symbols is not None:
            if not isinstance(symbols, str):
                raise HTTPError(400, reason="symbols must be a string")
            if any(len(line.encode("utf-8")) > SYMBOLS_MAX_LINE_BYTES for line in symbols.split("\n")):
                raise HTTPError(400, reason="symbols.dat line too long")
        if swkb is not None and not isinstance(swkb, str):
            raise HTTPError(400, reason="swkb must be a string")
        try:
            # ensure the config dir exists
            os.makedirs(config_dir, exist_ok=True)
            # write the config to files
            if config is not None:
                save_file("config.json", json.dumps(config, indent=2))
            if symbols is not None:
                save_file("symbols.dat", normalize_symbols(symbols))
            if swkb is not None:
                save_file("swkb.dat", swkb)
        except OSError as err:
            # 以前錯誤被吞掉、一律回答成功，設定頁顯示「已儲存」但檔案沒變
            print("cannot save settings:", err, file=sys.stderr)
            raise HTTPError(500, reason="Cannot save the settings")
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

    @authenticated
    def get(self):  # get all user phrases
        chewing_ctx = open_chewing_ctx()
        try:
            # 匯入的詞庫可能有不是 UTF-8 的詞，以前整個清單載入失敗 (userPhrases 寬鬆解碼)
            phrases = [{"phrase": phrase, "bopomofo": bopomofo}
                       for phrase, bopomofo in chewing_ctx.userPhrases()]
        finally:
            chewing_ctx.close()
        self.write({"data": phrases})

    @authenticated
    def post(self):  # add new user phrases or remove existing ones
        data = json.loads(self.request.body)
        added = data.get("add", [])
        removed = data.get("remove", [])

        # 0: error (any item failed), 1: success
        result = 1

        chewing_ctx = open_chewing_ctx()
        try:
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
        finally:
            chewing_ctx.close()  # 寫回 chewing.dat
        if added or removed:
            touchChangeStamp(config_dir)  # 輸入法重新讀取詞庫

        self.write({"result": result})


class UserPhraseFileHandler(BaseHandler):

    @authenticated
    def get(self):  # download user phrase file
        try:
            user_phrase_file = prepareUserDictionary(config_dir, search_paths)
        except UserDictionaryError:
            raise HTTPError(503, reason="Cannot convert the old user phrase database")
        try:
            with open(user_phrase_file, "rb") as f:  # libchewing 整個換掉檔案，讀到的一定完整
                content = f.read()
        except OSError:
            raise HTTPError(404)
        self.set_header("Content-Type", "application/force-download")
        self.set_header("Content-Disposition", "attachment; filename=chewing.dat")
        self.write(content)

    @authenticated
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
