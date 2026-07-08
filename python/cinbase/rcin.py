from __future__ import print_function
from __future__ import unicode_literals
import os
import re
import json


class RCin(object):

    # TODO check the possiblility if the encoding is not utf-8
    encoding = 'utf-8'

    def __init__(self, fs, imeDirName):
        self.imeDirName = imeDirName
        self.curdir = os.path.abspath(os.path.dirname(__file__))

        self.ename = ""
        self.cname = ""
        self.selkey = ""
        self.keynames = {}
        self.cincount = {}
        self.chardefs = {}

        try:
            import orjson
            content = fs.read()
            self.__dict__.update(orjson.loads(content))
        except Exception:
            try:
                import ujson
                fs.seek(0)
                self.__dict__.update(ujson.load(fs))
            except Exception:
                try:
                    fs.seek(0)
                except Exception:
                    pass
                self.__dict__.update(json.load(fs))

        self._build_reverse_index()


    def __del__(self):
        del self.keynames
        del self.chardefs
        self.keynames = {}
        self.chardefs = {}
        self._char_to_keys = {}

    def _build_reverse_index(self):
        # char → [keys]，鍵序與 chardefs 迭代順序一致，同一鍵內重複出現會重複收錄
        # （getCharEncode 依出現次數輸出，須保留）
        index = {}
        for chardef, chars in self.chardefs.items():
            for char in chars:
                if char not in index:
                    index[char] = []
                index[char].append(chardef)
        self._char_to_keys = index

    def getEname(self):
        return self.ename

    def getCname(self):
        return self.cname

    def getSelection(self):
        return self.selkey

    def isInKeyName(self, key):
        return key in self.keynames

    def getKeyName(self, key):
        return self.keynames[key]

    def isHaveKey(self, val):
        return val in self._char_to_keys

    def getKey(self, val):
        return self._char_to_keys[val][0]

    def isInCharDef(self, key):
        return key in self.chardefs

    def getCharDef(self, key):
        """ 
        will return a list conaining all possible result
        """
        return self.chardefs[key]

    def getCharEncode(self, root):
        nunbers = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']
        i = 0
        result = root + ':'
        for chardef in self._char_to_keys.get(root, ()):
            result += '　' + nunbers[i]
            if i < 9:
                i = i + 1
            for str in chardef:
                result += self.getKeyName(str)

        if result == root + ':':
            result = ''
        return result


__all__ = ["RCin"]
