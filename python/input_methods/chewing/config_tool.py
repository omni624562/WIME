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

current_dir = os.path.dirname(__file__)

# The libchewing package is not in the default python path.
# FIXME: set PYTHONPATH properly so we don't need to add this hack.
sys.path.append(os.path.dirname(os.path.dirname(current_dir)))
sys.path.append(current_dir)

from chewing_config import chewingConfig
from libchewing import ChewingContext, CHEWING_DATA_DIR
from ctypes import c_uint, byref, create_string_buffer
from config_server import BaseHandler, NoCacheStaticFileHandler, ConfigServerApp

config_dir = os.path.join(os.path.expandvars("%APPDATA%"), "PIME", "chewing")
localdata_dir = os.path.join(os.path.expandvars("%LOCALAPPDATA%"), "PIME", "chewing")

COOKIE_ID = "chewing_config_token"

# syspath 參數可包含多個路徑，用 ; 分隔
# 此處把 user 設定檔目錄插入到 system-wide 資料檔路徑前
# 如此使用者變更設定後，可以比系統預設值有優先權
search_paths = ";".join((chewingConfig.getConfigDir(), CHEWING_DATA_DIR)).encode("UTF-8")
user_phrase = chewingConfig.getUserPhrase().encode("UTF-8")
# print(search_paths, user_phrase)
chewing_ctx = ChewingContext(syspath = search_paths, userpath = user_phrase)  # new libchewing context


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
        # ensure the config dir exists
        os.makedirs(config_dir, exist_ok=True)
        # write the config to files
        config = data.get("config", None)
        if config is not None:
            self.save_file("config.json", json.dumps(config, indent=2))
        symbols = data.get("symbols", None)
        if symbols is not None:
            self.save_file("symbols.dat", symbols)
        swkb = data.get("swkb", None)
        if swkb is not None:
            self.save_file("swkb.dat", swkb)
        self.write('{"return":true}')

    def load_config(self):
        config = chewingConfig.toJson()  # the default settings
        try:
            with open(os.path.join(config_dir, "config.json"), "r", encoding="UTF-8") as f:
                # override default values with user config
                config.update(json.load(f))
        except Exception as e:
            print(e)
        return config

    def load_data(self, name):
        try:
            userFile = os.path.join(config_dir, name)
            with open(userFile, "r", encoding="UTF-8") as f:
                return f.read()
        except FileNotFoundError:
            with open(os.path.join(CHEWING_DATA_DIR, name), "r", encoding="UTF-8") as f:
                return f.read()
        except Exception:
            return ""

    def save_file(self, filename, data):
        target = os.path.join(config_dir, filename)
        tmp_target = target + ".tmp"
        try:
            with open(tmp_target, "w", encoding="UTF-8") as f:
                f.write(data)
                if filename == "symbols.dat":
                    f.write("\n")
            os.replace(tmp_target, target)
        except Exception:
            try:
                if os.path.exists(tmp_target):
                    os.remove(tmp_target)
            except Exception:
                pass
            pass


class UserPhraseHandler(BaseHandler):

    @tornado.web.authenticated
    def get(self):  # get all user phrases
        phrase_len = c_uint(0)
        bopomofo_len = c_uint(0)
        phrases = []
        ret = chewing_ctx.userphrase_enumerate()
        print(chewing_ctx, ret)
        while chewing_ctx.userphrase_has_next(byref(phrase_len), byref(bopomofo_len)):
            phrase_buf = create_string_buffer(phrase_len.value)
            bopomofo_buf = create_string_buffer(bopomofo_len.value)
            chewing_ctx.userphrase_get(phrase_buf, phrase_len, bopomofo_buf, bopomofo_len)
            phrase = phrase_buf.raw.decode("utf8").strip('\x00')
            bopomofo = bopomofo_buf.raw.decode("utf8").strip('\x00')
            phrases.append({
                "phrase": phrase,
                "bopomofo": bopomofo
            })
        self.write({"data": phrases})

    @tornado.web.authenticated
    def post(self):  # add new user phrases or remove existing ones
        data = tornado.escape.json_decode(self.request.body)
        added = data.get("add", [])
        removed = data.get("remove", [])
        print("add", added, "remove", removed)

        # 0: error, 1: success, default to success
        result = 1

        for item in added:  # add new phrases
            phrase = item["phrase"].encode("utf8")
            bopomofo = item["bopomofo"].encode("utf8")
            result = chewing_ctx.userphrase_add(phrase, bopomofo)

        for item in removed:  # remove existing phrases
            phrase = item["phrase"].encode("utf8")
            bopomofo = item["bopomofo"].encode("utf8")
            result = chewing_ctx.userphrase_remove(phrase, bopomofo)

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
        try:
            temp_user_phrase = os.path.join(config_dir, "chewing_tmp.sqlite3")
            origin_user_phrase = os.path.join(config_dir, "chewing.sqlite3")
            temp_user_phrase_file = open(temp_user_phrase, "wb")
            temp_user_phrase_file.write(self.request.files["import_user_phrase"][0]["body"])
            temp_user_phrase_file.close()
            # error check
            import sqlite3
            conn = sqlite3.connect(temp_user_phrase)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM config_v1")
            conn.close()

            user_phrase_file = open(origin_user_phrase, "wb")
            user_phrase_file.write(self.request.files["import_user_phrase"][0]["body"])
            user_phrase_file.close()
            os.remove(temp_user_phrase)
            response_html = """
                <script type="text/javascript">
                    alert("匯入詞庫成功！");
                    window.location = "./user_phrase_editor.html";
                </script>
            """
            self.write(response_html)
        except:
            self.write("詞庫格式錯誤，可能檔案損毀或選到錯誤的檔案，請按上一頁返回")


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
