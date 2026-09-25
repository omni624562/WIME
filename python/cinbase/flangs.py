from __future__ import print_function
from __future__ import unicode_literals

class flangs(object):

    # TODO check the possiblility if the encoding is not utf-8
    encoding = 'utf-8'

    def __init__(self, fs):

        self.keynames = []
        self.chardefs = {}
        seen = set()

        for line in fs:
            # 使用者可編輯的檔案：去掉 UTF-8 BOM（否則第一個分類永遠比對不到），
            # 跳過空行，以及沒有名稱或沒有內容的分類——「名稱=」這種行原本會列進
            # 選單，選到時 getCharDef KeyError，整條管道被重置
            line = line.lstrip('﻿').strip()
            if not line:
                continue

            key, root = safeSplit(line)
            key = key.strip()
            root = root.strip()
            if not key or not root:
                continue

            for rootstr in root:
                try:
                    self.chardefs[key].append(rootstr)
                except KeyError:
                    self.chardefs[key] = [rootstr]

            if key not in seen:
                seen.add(key)
                self.keynames.append(key)

    def __del__(self):
        del self.keynames
        del self.chardefs
        self.keynames = []
        self.chardefs = {}

    def isInCharDef(self, key):
        return key in self.chardefs

    def getCharDef(self, key):
        """ 
        will return a list conaining all possible result
        """
        return self.chardefs.get(key, [])

    def getKeyNames(self):
        return self.keynames


def safeSplit(line):
    if '=' in line:
        return line.split('=', 1)
    elif ' ' in line:
        return line.split(' ', 1)
    elif '\t' in line:
        return line.split('\t', 1)
    else:
        return line, line

__all__ = ["flangs"]
