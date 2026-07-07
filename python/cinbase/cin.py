from __future__ import print_function
from __future__ import unicode_literals
import math
import os
import re
import json
import copy
import time


class Cin(object):

    # TODO check the possiblility if the encoding is not utf-8
    encoding = 'utf-8'
    MAX_CONTEXT_ENTRIES = 32
    COUNT_SAVE_INTERVAL_SECONDS = 60.0
    # big5 encoding cache shared across all Cin instances (encoding is deterministic)
    _big5_cache: dict = {}

    # Unicode range boundaries; computed once at class definition.
    # Two-element entries are [lo, hi) bounds; multi-element entries are
    # frozensets of individual codepoints for O(1) membership tests.
    charsetRange = {
        'bopomofo':    [0x3100, 0x3130],
        'bopomofoTone': frozenset((0x02D9, 0x02CA, 0x02C7, 0x02CB)),
        'cjk':         [0x4E00, 0x9FEB],
        'big5F':       [0xA440, 0xC67F],
        'big5LF':      [0xC940, 0xF9D6],
        'big5S':       [0xA140, 0xA3C0],
        'cjkExtA':     [0x3400, 0x4DB6],
        'cjkExtB':     [0x20000, 0x2A6D7],
        'cjkExtC':     [0x2A700, 0x2B735],
        'cjkExtD':     [0x2B740, 0x2B81E],
        'cjkExtE':     [0x2B820, 0x2CEA2],
        'cjkExtF':     [0x2CEB0, 0x2EBE1],
        'pua':         [0xE000, 0xF900],
        'puaA':        [0xF0000, 0xFFFFE],
        'puaB':        [0x100000, 0x10FFFE],
        'cjkCIa':      [0xF900, 0xFA0E],
        'cjkCIb':      frozenset((0xFA0E, 0xFA0F, 0xFA11, 0xFA13, 0xFA14, 0xFA1F,
                                   0xFA21, 0xFA23, 0xFA24, 0xFA27, 0xFA28, 0xFA29)),
        'cjkCIc':      frozenset((0xFA10, 0xFA12, 0xFA15, 0xFA16, 0xFA17, 0xFA18,
                                   0xFA19, 0xFA1A, 0xFA1B, 0xFA1C, 0xFA1D, 0xFA1E,
                                   0xFA20, 0xFA22, 0xFA25, 0xFA26, 0xFA2A, 0xFA2B,
                                   0xFA2C, 0xFA2D)),
        'cjkCId':      [0xFA2E, 0xFB00],
        'cjkCIS':      [0x2F800, 0x2FA20],
    }

    def __init__(self, fs, imeDirName, ignorePrivateUseArea):
        self.imeDirName = imeDirName
        self.ignorePrivateUseArea = ignorePrivateUseArea
        self.curdir = os.path.abspath(os.path.dirname(__file__))

        self.ename = ""
        self.cname = ""
        self.selkey = ""
        self.keynames = {}
        self.cincount = {}
        self._count_dirty = False
        self._last_count_save_time = 0.0
        self.chardefs = {}
        self.privateuse = {}
        self.dupchardefs = {}

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

        if self.ignorePrivateUseArea:
            for key in self.privateuse:
                newvalue = list(self.chardefs[key])
                for value in self.privateuse[key]:
                    if value in newvalue:
                        newvalue.remove(value)
                self.chardefs[key] = newvalue

        self._chardef_prefix_cache_count = None
        self._chardef_prefixes = set()
        self._chardef_proper_prefixes = set()
        self._char_to_keys = {}
        self._count_dirty = False
        self._last_count_save_time = 0.0

        self._build_reverse_index()
        self.loadCountFile()


    def __del__(self):
        try:
            self.saveCountFile(force=True)
        except Exception:
            pass
        for name in ("keynames", "cincount", "chardefs", "privateuse", "dupchardefs"):
            if hasattr(self, name):
                delattr(self, name)

        self.keynames = {}
        self.cincount = {}
        self.chardefs = {}
        self.privateuse = {}
        self.dupchardefs = {}


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


    def _build_reverse_index(self):
        index = {}
        for chardef, chars in self.chardefs.items():
            for char in chars:
                if char not in index:
                    index[char] = []
                index[char].append(chardef)
        self._char_to_keys = index

    def _rebuild_prefix_cache(self):
        prefixes = set()
        proper_prefixes = set()
        for chardef in self.chardefs:
            n = len(chardef)
            for length in range(1, n + 1):
                prefixes.add(chardef[:length])
            for length in range(1, n):
                proper_prefixes.add(chardef[:length])
        self._chardef_prefixes = prefixes
        self._chardef_proper_prefixes = proper_prefixes
        self._chardef_prefix_cache_count = len(self.chardefs)

    def isHaveKey(self, val):
        return val in self._char_to_keys

    def getKey(self, val):
        return self._char_to_keys[val][0]

    def isInCharDef(self, key):
        return key in self.chardefs

    def getCharDef(self, key):
        return self.chardefs.get(key, [])

    def isCharDefPrefix(self, key):
        if not key:
            return False
        if key in self.chardefs:
            return True
        if self._chardef_prefix_cache_count != len(self.chardefs):
            self._rebuild_prefix_cache()
        return key in self._chardef_prefixes

    def hasLongerCharDefPrefix(self, key):
        if not key:
            return False
        if self._chardef_prefix_cache_count != len(self.chardefs):
            self._rebuild_prefix_cache()
        return key in self._chardef_proper_prefixes


    def sortedCharDefKeys(self):
        # sorted() over all chardef keys is expensive on large tables
        # (dayi3 has ~12k keys); cache until the table content changes
        chardef_count = len(self.chardefs)
        cached = getattr(self, "_sorted_chardef_keys", None)
        if cached is None or getattr(self, "_sorted_chardef_keys_count", -1) != chardef_count:
            cached = sorted(self.chardefs.keys())
            self._sorted_chardef_keys = cached
            self._sorted_chardef_keys_count = chardef_count
        return cached

    def getWildcardCharDefs(self, CompositionChar, WildcardChar, candMaxItems, variableWildcard=False):
        wildcardchardefs = []
        lowFrequencyChardefs = {}
        highFrequencyCharSetList = ["bopomofo", "bopomofoTone", "cjk", "big5F", "big5LF", "big5S"]
        lowFrequencyCharSetList = ["big5Other", "cjkExtA", "cjkExtB", "cjkExtC", "cjkExtD", "cjkExtE", "cjkExtF", "cjkCIibm", "pua", "cjkOther"]

        for i in range(len(lowFrequencyCharSetList)):
            lowFrequencyChardefs[i] = []
        lowFrequencySeen = set()

        keyLength = len(CompositionChar)
        matchstring = ''
        for char in CompositionChar:
            if char == WildcardChar:
                matchstring += '(.*)' if variableWildcard else '(.)'
            else:
                matchstring += re.escape(char)
        pattern = re.compile('^' + matchstring + '$')

        sortedchardefs = self.sortedCharDefKeys()
        if variableWildcard:
            matchchardefs = [self.chardefs[key] for key in sortedchardefs if pattern.match(key)]
        else:
            matchchardefs = [self.chardefs[key] for key in sortedchardefs if len(key) == keyLength and pattern.match(key)]

        if matchchardefs:
            for chardef in matchchardefs:
                for matchstr in chardef:
                    if len(matchstr) > 1:
                        charSet = self.getCharSet(matchstr[0])
                    else:
                        charSet = self.getCharSet(matchstr)

                    if charSet in highFrequencyCharSetList:
                        wildcardchardefs.append(matchstr)
                        if len(wildcardchardefs) >= candMaxItems:
                            return wildcardchardefs
                    else:
                        i = lowFrequencyCharSetList.index(charSet) if charSet in lowFrequencyCharSetList else len(lowFrequencyCharSetList) - 1
                        if matchstr not in lowFrequencySeen:
                            lowFrequencyChardefs[i].append(matchstr)
                            lowFrequencySeen.add(matchstr)

            highFrequencySeen = set(wildcardchardefs)
            for key in lowFrequencyChardefs:
                for char in lowFrequencyChardefs[key]:
                    if char not in highFrequencySeen:
                        wildcardchardefs.append(char)
                        highFrequencySeen.add(char)
                    if len(wildcardchardefs) >= candMaxItems:
                        return wildcardchardefs
        return wildcardchardefs


    def getCharEncode(self, root):
        keys = self._char_to_keys.get(root)
        if not keys:
            return '查無字根...'
        numbers = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']
        result = root + ':'
        for i, chardef in enumerate(keys[:10]):
            result += '　' + numbers[i]
            for ch in chardef:
                result += self.getKeyName(ch)
        return result


    def updateCinTable(self, userExtendTable, priorityExtendTable, extendtable, ignorePrivateUseArea):
        if userExtendTable:
            for key in extendtable.chardefs:
                for root in extendtable.chardefs[key]:
                    if priorityExtendTable:
                        i = extendtable.chardefs[key].index(root)
                        try:
                            self.chardefs[key.lower()].insert(i, root)
                        except KeyError:
                            self.chardefs[key.lower()] = [root]
                    else:
                        try:
                            self.chardefs[key.lower()].append(root)
                        except KeyError:
                            self.chardefs[key.lower()] = [root]
            self._chardef_prefix_cache_count = None
            self._chardef_prefixes = set()
            self._chardef_proper_prefixes = set()
            self._build_reverse_index()


    def loadCountFile(self):
        filename = self.getCountFile()
        if os.path.exists(filename) and os.stat(filename).st_size > 0:
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        normalized = {}
                        changed = False
                        for key, value in data.items():
                            if not isinstance(key, str) or not isinstance(value, dict):
                                changed = True
                                continue
                            normalized[key] = {}
                            for char, entry in value.items():
                                if not isinstance(char, str):
                                    changed = True
                                    continue
                                normalizedEntry = self._normalizeCountEntry(entry)
                                normalized[key][char] = normalizedEntry
                                if normalizedEntry != entry:
                                    changed = True
                        self.cincount.update(normalized)
                        if changed:
                            self._count_dirty = True
            except Exception:
                pass

    def saveCountFile(self, force=False):
        if not self._count_dirty:
            return
        now = time.time()
        if (
            not force and
            self._last_count_save_time > 0 and
            now - self._last_count_save_time < self.COUNT_SAVE_INTERVAL_SECONDS
        ):
            return
        filename = self.getCountFile()
        try:
            # 先序列化、寫暫存檔再原子取代，中途中斷不會留下半寫入的計數檔
            payload = json.dumps(self.cincount, ensure_ascii=False, separators=(",", ":"))
            tempname = filename + ".tmp"
            with open(tempname, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tempname, filename)
            self._count_dirty = False
            self._last_count_save_time = now
        except Exception:
            pass

    def _trimContextCounts(self, prev, keepKey=""):
        if len(prev) <= self.MAX_CONTEXT_ENTRIES:
            return prev

        items = sorted(prev.items(), key=lambda item: (-item[1], item[0]))
        trimmed = dict(items[:self.MAX_CONTEXT_ENTRIES])
        if keepKey and keepKey in prev and keepKey not in trimmed:
            removable = [key for key in trimmed if key != keepKey]
            if removable:
                dropKey = min(removable, key=lambda key: (trimmed[key], key))
                del trimmed[dropKey]
            trimmed[keepKey] = prev[keepKey]
        return trimmed

    def _normalizeCountEntry(self, value):
        if isinstance(value, dict):
            count = value.get("count", 0)
            try:
                count = int(count)
            except (TypeError, ValueError):
                count = 0
            last = value.get("last", 0)
            try:
                last = float(last)
            except (TypeError, ValueError):
                last = 0
            prev = value.get("prev", {})
            if not isinstance(prev, dict):
                prev = {}
            normalized_prev = {}
            for k, v in prev.items():
                if not isinstance(k, str):
                    continue
                try:
                    normalized_prev[k] = int(v)
                except (TypeError, ValueError):
                    pass
            prev = self._trimContextCounts(normalized_prev)
            return {"count": count, "last": last, "prev": prev}
        try:
            count = int(value)
        except (TypeError, ValueError):
            count = 0
        return {"count": count, "last": 0, "prev": {}}

    def _countEntryScoreParts(self, value, previousChar=""):
        if isinstance(value, dict):
            try:
                count = int(value.get("count", 0))
            except (TypeError, ValueError):
                count = 0
            try:
                last = float(value.get("last", 0))
            except (TypeError, ValueError):
                last = 0
            prevCount = 0
            prev = value.get("prev", {})
            if isinstance(previousChar, str) and previousChar and isinstance(prev, dict):
                try:
                    prevCount = int(prev.get(previousChar, 0))
                except (TypeError, ValueError):
                    prevCount = 0
            return count, last, prevCount

        try:
            count = int(value)
        except (TypeError, ValueError):
            count = 0
        return count, 0, 0

    def addCount(self, key, char, previousChar=""):
        if not isinstance(key, str) or not isinstance(char, str):
            return
        if key not in self.cincount or not isinstance(self.cincount[key], dict):
            self.cincount[key] = {}
        entry = self._normalizeCountEntry(self.cincount[key].get(char, 0))
        entry["count"] += 1
        entry["last"] = time.time()
        if isinstance(previousChar, str) and previousChar:
            entry["prev"][previousChar] = entry["prev"].get(previousChar, 0) + 1
            entry["prev"] = self._trimContextCounts(entry["prev"], previousChar)
        self.cincount[key][char] = entry
        self._count_dirty = True

    def sortByCount(self, key, candidates, previousChar="", useRecent=True, useContext=True):
        if key not in self.cincount or not isinstance(self.cincount[key], dict):
            return candidates
        counts = self.cincount[key]
        now = time.time()

        def score(candidate):
            count, last, prevCount = self._countEntryScoreParts(counts.get(candidate, 0), previousChar)
            contextCount = prevCount if (useContext and isinstance(previousChar, str) and previousChar) else 0
            # 智慧選字 = 上下文預測，不是頻率重排：沒有「前一字上下文」
            # 訊號時一律維持碼表順序，保護選字鍵的肌肉記憶與空白鍵的
            # 預設輸出。只有在相同前一字之後選過這個字（例如常打
            # 「詹智丞」，打完「詹」再組「智」的字碼），它才會被提前。
            if contextCount < 1:
                return 0.0
            value = math.log2(1.0 + contextCount) * 3.0
            # 同一個上下文有多個後續字時，全域次數與新近度當次要訊號
            value += math.log2(1.0 + count)
            if useRecent and last > 0:
                age_days = max(0.0, (now - last) / 86400.0)
                value += 2.0 / (1.0 + age_days / 7.0)
            return value

        return [candidate for _, candidate in sorted(
            enumerate(candidates),
            key=lambda item: (-score(item[1]), item[0])
        )]


    def getCountDir(self):
        count_dir = os.path.join(os.path.expandvars("%APPDATA%"), "PIME", self.imeDirName)
        os.makedirs(count_dir, mode=0o700, exist_ok=True)
        return count_dir


    def getCountFile(self, name="cincount.json"):
        return os.path.join(self.getCountDir(), name)


    def getCharSet(self, root):
        matchint = ord(root)
        cr = self.charsetRange  # local alias avoids repeated global dict lookup

        if matchint <= cr['cjk'][1]:
            if (cr['bopomofo'][0] <= matchint < cr['bopomofo'][1] or  # Bopomofo 區域
                    matchint in cr['bopomofoTone']):
                return "bopomofo"
            elif cr['cjk'][0] <= matchint < cr['cjk'][1]:  # CJK Unified Ideographs 區域
                cached = self._big5_cache.get(matchint)
                if cached is None:
                    try:
                        big5codeint = int(root.encode('big5').hex(), 16)
                    except Exception:
                        big5codeint = -1
                    self._big5_cache[matchint] = big5codeint
                else:
                    big5codeint = cached
                if big5codeint < 0:  # not encodable as Big5 → generic CJK
                    return "cjk"
                if cr['big5F'][0] <= big5codeint < cr['big5F'][1]:
                    return "big5F"
                elif cr['big5LF'][0] <= big5codeint < cr['big5LF'][1]:
                    return "big5LF"
                elif cr['big5S'][0] <= big5codeint < cr['big5S'][1]:
                    return "big5LF"
                else:
                    return "big5Other"
            elif cr['cjkExtA'][0] <= matchint < cr['cjkExtA'][1]:  # Extension A 區域
                return "cjkExtA"
        else:
            if cr['cjkExtB'][0] <= matchint < cr['cjkExtB'][1]:
                return "cjkExtB"
            elif cr['cjkExtC'][0] <= matchint < cr['cjkExtC'][1]:
                return "cjkExtC"
            elif cr['cjkExtD'][0] <= matchint < cr['cjkExtD'][1]:
                return "cjkExtD"
            elif cr['cjkExtE'][0] <= matchint < cr['cjkExtE'][1]:
                return "cjkExtE"
            elif cr['cjkExtF'][0] <= matchint < cr['cjkExtF'][1]:
                return "cjkExtF"
            elif matchint in cr['cjkCIb']:
                return "cjkCIibm"
            elif (cr['pua'][0] <= matchint < cr['pua'][1] or
                    cr['puaA'][0] <= matchint < cr['puaA'][1] or
                    cr['puaB'][0] <= matchint < cr['puaB'][1]):
                return "pua"
            elif (cr['cjkCIa'][0] <= matchint < cr['cjkCIa'][1] or
                    matchint in cr['cjkCIc'] or
                    cr['cjkCId'][0] <= matchint < cr['cjkCId'][1]):
                return "pua"
            elif cr['cjkCIS'][0] <= matchint < cr['cjkCIS'][1]:
                return "pua"
        return "cjkOther"


__all__ = ["Cin"]
