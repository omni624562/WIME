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

current_dir = os.path.abspath(os.path.dirname(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
# python/ 頂層（共用的 config_server）；放最後，避免蓋過同目錄的 config.py
python_dir = os.path.dirname(current_dir)
if python_dir not in sys.path:
    sys.path.append(python_dir)

from config import CinBaseConfig
from cin import Cin
from config_server import BaseHandler, NoCacheStaticFileHandler, ConfigServerApp


cfg = CinBaseConfig
cfg.imeDirName = sys.argv[2]
config_dir = os.path.join(cfg.getConfigDir())
current_ime_dir = os.path.join(cfg.getDefaultConfigDir(), os.path.pardir)
current_ime_config_dir = os.path.join(cfg.getDefaultConfigDir())
data_dir = os.path.join(current_dir, "data")
json_dir = os.path.join(current_dir, "json")
localdata_dir = os.path.join(cfg.getConfigDir())

if len(sys.argv) >= 2 and sys.argv[1] == "user_phrase_editor":
    tool_name = "user_phrase_editor"
else:
    tool_name = "config"

COOKIE_ID = "cinbase_config_token"


# syspath 參數可包含多個路徑，用 ; 分隔
# 此處把 user 設定檔目錄插入到 system-wide 資料檔路徑前
# 如此使用者變更設定後，可以比系統預設值有優先權
search_paths = ";".join((cfg.getConfigDir(), data_dir)).encode("UTF-8")

class ConfigHandler(BaseHandler):

    # (檔案路徑 → (mtime, cincount)) 快取，避免重複解析多 MB 碼表 JSON
    _cincount_cache = {}

    @tornado.web.authenticated
    def get(self):  # get config
        data = {
            "imename": cfg.imeDirName,
            "config": self.load_config(),
            "cincount": self.load_cindata(),
            "symbols": self.load_data("symbols.dat"),
            "swkb": self.load_data("swkb.dat"),
            "fsymbols": self.load_data("fsymbols.dat"),
            "phrase": self.load_data("userphrase.dat"),
            "excludePhrase": self.load_data("excludephrase.dat"),
            "flangs": self.load_data("flangs.dat"),
            "extendtable": self.load_data("extendtable.dat")
        }
        self.write(data)

    @tornado.web.authenticated
    def post(self):  # save config
        data = tornado.escape.json_decode(self.request.body)
        # print(data)
        # ensure the config dir exists
        os.makedirs(config_dir, exist_ok=True)
        # write the config to files
        config = data.get("config", None)
        if config is not None:
            # 過濾掉不應由設定檔覆寫的內部欄位（如 imeDirName/curdir），
            # 避免惡意 POST 注入這些鍵在下次 load() 時偏移檔案路徑。
            if isinstance(config, dict):
                for k in cfg.ignoreSaveList:
                    config.pop(k, None)
            self.save_file("config.json", json.dumps(config, sort_keys=True, indent=4))

        symbols = data.get("symbols", None)
        if symbols is not None:
            self.save_file("symbols.dat", symbols)

        swkb = data.get("swkb", None)
        if swkb is not None:
            self.save_file("swkb.dat", swkb)

        fsymbols = data.get("fsymbols", None)
        if fsymbols is not None:
            self.save_file("fsymbols.dat", fsymbols)

        phrase = data.get("phrase", None)
        if phrase is not None:
            self.save_file("userphrase.dat", phrase)

        excludePhrase = data.get("excludePhrase", None)
        if excludePhrase is not None:
            self.save_file("excludephrase.dat", excludePhrase)

        flangs = data.get("flangs", None)
        if flangs is not None:
            self.save_file("flangs.dat", flangs)

        extendtable = data.get("extendtable", None)
        if extendtable is not None:
            self.save_file("extendtable.dat", extendtable)

        self.write('{"return":true}')

    def load_config(self):
        cfg.load()
        config = cfg.toJson()  # the current settings
        return config

    def load_cindata(self):
        CinDict ={}
        CinDict["checj"] = ["checj.json", "mscj3.json", "mscj3-ext.json", "cj-ext.json", "cnscj.json", "thcj.json", "newcj3.json", "cj5.json", "newcj.json", "scj6.json", "cj-fast.json"]
        CinDict["chephonetic"] = ["thphonetic.json", "CnsPhonetic.json", "bpmf.json"]
        CinDict["chearray"] = ["tharray.json", "array30.json", "ar30-big.json", "array40.json"]
        CinDict["chedayi"] = ["thdayi.json", "dayi4.json", "dayi3.json"]
        CinDict["cheez"] = ["ez.json", "ezsmall.json", "ezmid.json", "ezbig.json"]
        CinDict["chepinyin"] = ["thpinyin.json", "pinyin.json", "roman.json"]
        CinDict["chesimplex"] = ["simplecj.json", "simplex.json", "simplex5.json"]
        CinDict["cheliu"] = ["liu.json"]
        fileList = CinDict.get(cfg.imeDirName)
        if not fileList:
            return
        # 對索引做範圍檢查，避免被竄改的 selCinType 造成 IndexError
        idx = cfg.selCinType if isinstance(cfg.selCinType, int) and 0 <= cfg.selCinType < len(fileList) else 0
        jsonFile = fileList[idx]

        datafile = os.path.join(json_dir, jsonFile)
        if not os.path.exists(datafile):
            return
        try:
            # cincount 只是碼表 JSON 頂層的一個小摘要，但檔案可達數 MB。
            # 依 (檔案, mtime) 快取解析結果，避免同一設定工作階段內每次 /config
            # 都重新解析整份碼表（開一次設定頁會抓 2~3 次）。
            mtime = os.path.getmtime(datafile)
            cache = ConfigHandler._cincount_cache
            cached = cache.get(datafile)
            if cached and cached[0] == mtime:
                return cached[1]
            with open(datafile, "r", encoding="UTF-8") as f:
                cincount = json.load(f).get("cincount")
            cache[datafile] = (mtime, cincount)
            return cincount
        except Exception as e:
            print(e)

    def load_data(self, name):
        try:
            userFile = os.path.join(config_dir, name)
            with open(userFile, "r", encoding="UTF-8") as f:
                return f.read()
        except FileNotFoundError:
            with open(os.path.join(data_dir, name), "r", encoding="UTF-8") as f:
                return f.read()
        except Exception:
            return ""

    def save_file(self, filename, data):
        target = os.path.join(config_dir, filename)
        tmp_target = target + ".tmp"
        try:
            with open(tmp_target, "w", encoding="UTF-8") as f:
                f.write(data)
            os.replace(tmp_target, target)
        except Exception:
            try:
                if os.path.exists(tmp_target):
                    os.remove(tmp_target)
            except Exception:
                pass
            pass


class ConfigApp(ConfigServerApp):

    def __init__(self):
        handlers = [
            (r"/(.*\.html|config.js)", NoCacheStaticFileHandler, {"path": current_ime_config_dir}),
            (r"/(.*\.htm)", NoCacheStaticFileHandler, {"path": os.path.join(current_dir, "config")}),
            (r"/((css|fonts|images|js)/.*)", NoCacheStaticFileHandler, {"path": os.path.join(current_dir, "config")}),
            (r"/(data/.*\.json)", NoCacheStaticFileHandler, {"path": current_dir}),
            (r"/(icon.ico)", NoCacheStaticFileHandler, {"path": current_ime_dir}),
            (r"/(version.txt)", NoCacheStaticFileHandler, {"path": os.path.join(current_dir, "../../")}),
            (r"/config", ConfigHandler),  # main configuration handler
        ]
        super().__init__(handlers, cookie_id=COOKIE_ID, main_page="config", localdata_dir=localdata_dir)


def main():
    app = ConfigApp()
    app.run(tool_name)


if __name__ == "__main__":
    main()
