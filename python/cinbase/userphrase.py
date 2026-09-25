from __future__ import print_function
from __future__ import unicode_literals

class userphrase(object):

    # TODO check the possiblility if the encoding is not utf-8
    encoding = 'utf-8'

    def __init__(self, fs):

        self.keynames = []
        self.chardefs = {}
        # 以前用 list 判斷重複，詞庫有上萬行時每次建立輸入法實例都要跑數秒
        seen = set()

        for line in fs:

            line = line.lstrip('﻿').strip()

            key, root = safeSplit(line)
            key = key.strip()
            # 空行、「=詞」這種沒有字的行，以及結尾多打的逗號都略過，
            # 否則聯想清單會出現空白候選字
            candidates = [rootstr.strip() for rootstr in rootSplit(root) if rootstr.strip()]
            if not key or not candidates:
                continue

            self.chardefs.setdefault(key, []).extend(candidates)
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

def rootSplit(line):
    if ',' in line:
        return line.split(',')
    else:
        return [line]

__all__ = ["userphrase"]
