from __future__ import print_function
from __future__ import unicode_literals

class extendtable(object):

    # TODO check the possiblility if the encoding is not utf-8
    encoding = 'utf-8'

    def __init__(self, fs):

        self.chardefs = {}

        for line in fs:
            # 使用者可編輯的檔案：去掉 UTF-8 BOM（否則第一行永遠比對不到），跳過空行
            # 與沒有空白分隔的行——以前這種行的候選字是字串 "Error"，例如只打了
            # 「Q」的一行會讓 Shift+Q 輸出 Error
            line = line.lstrip('\ufeff').strip()

            key, root = safeSplit(line)
            key = key.lower().strip()
            root = root.strip()
            if not key or not root:
                continue

            try:
                self.chardefs[key].append(root)
            except KeyError:
                self.chardefs[key] = [root]

    def __del__(self):
        del self.chardefs
        self.chardefs = {}

    def isInCharDef(self, key):
        return key in self.chardefs

    def getCharDef(self, key):
        """ 
        will return a list conaining all possible result
        """
        return self.chardefs[key]


def safeSplit(line):
    if ' ' in line:
        return line.split(' ', 1)
    elif '\t' in line:
        return line.split('\t', 1)
    else:
        return line, ""

__all__ = ["extendtable"]
