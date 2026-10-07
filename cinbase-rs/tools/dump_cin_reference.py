"""Reference answers of python/cinbase/cin.py, rcin.py and hcin.py for the
Rust port (cinbase-rs/src/cin_tests.rs runs this and compares).

    python cinbase-rs/tools/dump_cin_reference.py <out.json> [<json dir>]

Everything is deterministic (seeded). Count files are written under a fresh
temporary APPDATA, never the real %APPDATA%\\PIME. Tables that are missing
from the json directory (they are generated, not committed) are skipped.
"""
import json
import os
import random
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path[:0] = [os.path.join(REPO, 'python', 'cinbase'), os.path.join(REPO, 'python')]

TMP = tempfile.mkdtemp(prefix='cin_ref_')
os.environ['APPDATA'] = TMP

import cin as cin_module  # noqa: E402
from cin import Cin  # noqa: E402
from rcin import RCin  # noqa: E402
from hcin import HCin  # noqa: E402

CLOCK_START = 1700000000.0


class FakeTime(object):
    def __init__(self):
        self.now = CLOCK_START

    def time(self):
        return self.now


FAKE = FakeTime()
cin_module.time = FAKE


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


def fnv(chunks):
    h = 0xcbf29ce484222325
    for chunk in chunks:
        for b in chunk:
            h ^= b
            h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return '%016x' % h


def chardefs_digest(chardefs):
    chunks = []
    for k, vs in chardefs.items():
        chunks.append(k.encode('utf-8') + b'\x00')
        for v in vs:
            chunks.append(v.encode('utf-8') + b'\x01')
        chunks.append(b'\x02')
    return fnv(chunks)


def reverse_digest(index):
    chunks = []
    for ch in sorted(index):
        chunks.append(ch.encode('utf-8') + b'\x00')
        for k in index[ch]:
            chunks.append(k.encode('utf-8') + b'\x01')
        chunks.append(b'\x02')
    return fnv(chunks)


def try_call(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return 'ERR'


# ---------------------------------------------------------------- charset

def charset_rle():
    c = Cin.__new__(Cin)
    out = []
    prev = None
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        name = c.getCharSet(chr(cp))
        if name != prev:
            out.append([cp, name])
            prev = name
    return out


# ---------------------------------------------------------------- tables

def new_count_dir(name):
    d = os.path.join(TMP, 'PIME', name)
    if os.path.isdir(d):
        shutil.rmtree(d)
    return d


def table_queries(c, rng, n_random=300, n_wild=300):
    keys = sorted(c.chardefs.keys())
    alphabet = sorted(set(ch for k in keys for ch in k))
    prefixes = set()
    for k in keys:
        prefixes.add(k[:1])
        prefixes.add(k[:2])
    for _ in range(n_random):
        prefixes.add(''.join(rng.choice(alphabet) for _ in range(rng.randint(1, 6))))
    for k in rng.sample(keys, min(300, len(keys))):
        prefixes.add(k)
        prefixes.add(k + rng.choice(alphabet))
    prefixes.update(['', '~', 'zzzzzz', '日', 'A'])
    prefixes = sorted(prefixes)
    out = {
        'prefix_queries': prefixes,
        'isPrefix': ''.join('1' if c.isCharDefPrefix(p) else '0' for p in prefixes),
        'hasLonger': ''.join('1' if c.hasLongerCharDefPrefix(p) else '0' for p in prefixes),
        'inCharDef': ''.join('1' if c.isInCharDef(p) else '0' for p in prefixes),
    }
    cd_queries = prefixes[::3]
    out['chardef_queries'] = cd_queries
    out['chardefs'] = [c.getCharDef(p) for p in cd_queries]

    chars = sorted(c._char_to_keys)
    sample = chars[::max(1, len(chars) // 2500)]
    sample += [ch for ch in chars if len(c._char_to_keys[ch]) > 9]
    sample += ['', 'A', '\u0000', '\U0010FFFD', '無法']
    out['encode_queries'] = sample
    out['encodes'] = [c.getCharEncode(ch) for ch in sample]
    out['getKey'] = [try_call(c.getKey, ch) for ch in sample]
    out['keyName'] = [[k, c.getKeyName(k)] for k in alphabet + ['!', '日', 'ab']]

    wild = []
    patterns = ['*', '**', '***', '****', '*****', '?', '']
    for _ in range(n_wild):
        k = rng.choice(keys)
        chars_ = list(k)
        mode = rng.randint(0, 3)
        if mode == 0:
            for i in rng.sample(range(len(chars_)), rng.randint(1, len(chars_))):
                chars_[i] = '*'
            patterns.append(''.join(chars_))
        elif mode == 1:
            i = rng.randint(0, len(chars_))
            j = rng.randint(i, len(chars_))
            patterns.append(''.join(chars_[:i]) + '*' + ''.join(chars_[j:]))
        elif mode == 2:
            i = rng.randint(0, len(chars_))
            patterns.append(''.join(chars_[:i]) + '*' + ''.join(chars_[i:]) + rng.choice(['', '*']))
        else:
            patterns.append(''.join(rng.choice(alphabet + ['*']) for _ in range(rng.randint(1, 5))))
    seen = set()
    for p in patterns:
        for variable in (False, True):
            for limit in (100, 5, 1, 0):
                if (p, variable, limit) in seen:
                    continue
                seen.add((p, variable, limit))
                wild.append([p, '*', limit, variable, try_call(c.getWildcardCharDefs, p, '*', limit, variable)])
    for p in ['a?', '??', '?b', 'a*', '**']:
        for wc in ('?', '**', '', 'a'):
            for variable in (False, True):
                wild.append([p, wc, 100, variable, try_call(c.getWildcardCharDefs, p, wc, 100, variable)])
    # repeat some queries in a different order (exercises the LRU cache)
    for item in wild[:60][::-1] + wild[:5]:
        wild.append(item[:4] + [try_call(c.getWildcardCharDefs, *item[:4])])
    out['wildcard'] = wild
    return out


def dump_table(name, json_dir, ignore_pua, rng):
    path = os.path.join(json_dir, name)
    with open(path, 'r', encoding='utf8') as fs:
        c = Cin(fs, 'cinref_' + name, ignore_pua)
    out = {
        'file': name,
        'ignorePUA': ignore_pua,
        'ename': c.ename, 'cname': c.cname, 'selkey': c.selkey,
        'keynames': list(c.keynames.items()),
        'cincount': dumps(c.cincount),
        'digest_chardefs': chardefs_digest(c.chardefs),
        'digest_reverse': reverse_digest(c._char_to_keys),
        'sorted_digest': fnv(k.encode('utf-8') + b'\x00' for k in c.sortedCharDefKeys()),
    }
    out['queries'] = table_queries(c, rng)
    # extend table: existing codes (also upper case), new codes, repeated values
    keys = list(c.chardefs.keys())
    ext = {}
    for k in rng.sample(keys, 20):
        ext[k] = ['一', '二', '一', '\U00020000', 'xx', '三', '四'][:rng.randint(1, 7)]
    ext[keys[0].upper() + 'Q'] = ['大']
    ext['zzzz'] = ['小', '小', '中']
    ext[keys[1].upper()] = ['本']
    out['extend'] = list(ext.items())
    results = []
    for priority in (True, False):
        with open(path, 'r', encoding='utf8') as fs:
            c2 = Cin(fs, 'cinref_' + name, ignore_pua)
        c2.getWildcardCharDefs('*', '*', 100, False)  # warm caches before the update
        c2.isCharDefPrefix(keys[0])

        class Ext(object):
            pass
        e = Ext()
        e.chardefs = {k: list(v) for k, v in ext.items()}
        c2.updateCinTable(True, priority, e, ignore_pua)
        c2.updateCinTable(False, priority, e, ignore_pua)  # no-op
        r = {
            'priority': priority,
            'digest_chardefs': chardefs_digest(c2.chardefs),
            'digest_reverse': reverse_digest(c2._char_to_keys),
            'queries': table_queries(c2, random.Random(7), n_random=50, n_wild=60),
        }
        results.append(r)
    out['after_update'] = results
    # __del__ keeps the reverse index
    c.__del__()
    sample = sorted(c._char_to_keys)[:50]
    out['after_close'] = {
        'chars': sample,
        'encodes': [c.getCharEncode(ch) for ch in sample],
        'getKey': [try_call(c.getKey, ch) for ch in sample],
        'isPrefix': [c.isCharDefPrefix(k) for k in keys[:20]],
        'wild': c.getWildcardCharDefs('*', '*', 100, False),
    }
    return out


def dump_rcin(name, json_dir, cls):
    with open(os.path.join(json_dir, name), 'r', encoding='utf8') as fs:
        r = cls(fs, 'x')
    chars = sorted(r._char_to_keys)
    sample = chars[::max(1, len(chars) // 3000)]
    sample += [ch for ch in chars if len(r._char_to_keys[ch]) > 9]
    sample += ['', 'A', '無法', '\U0010FFFD']
    out = {
        'file': name, 'ename': r.ename, 'cname': r.cname, 'selkey': r.selkey,
        'digest_chardefs': chardefs_digest(r.chardefs),
        'digest_reverse': reverse_digest(r._char_to_keys),
        'chars': sample,
        'encodes': [r.getCharEncode(ch) for ch in sample],
        'getKey': [try_call(r.getKey, ch) for ch in sample],
        'isHaveKey': [r.isHaveKey(ch) for ch in sample],
    }
    codes = list(r.chardefs)[::7] + ['', 'nosuchcode']
    out['codes'] = codes
    out['chardefs'] = [try_call(r.getCharDef, k) for k in codes]
    if cls is HCin:
        out['keyList'] = [r.getKeyList(ch) for ch in sample]
        out['keyNameList'] = [r.getKeyNameList(r.getKeyList(ch)) for ch in sample]
    r.__del__()
    out['after_close'] = [r.getCharEncode(ch) for ch in sample[:20]]
    return out


# ---------------------------------------------------------------- counts

NORMALIZE_CASES = [
    '0', '5', '-3', '2.7', '-2.7', 'true', 'false', 'null', '"12"', '" 12 "', '"1_000"', '"1__0"', '"_1"',
    '"12.5"', '""', '"abc"', '"+5"', '"-0"', '"\\t7\\n"', '[]', '{}', '[1]', '1e18', 'NaN', 'Infinity',
    '{"count": NaN}', '{"count": -Infinity}', '{"last": NaN}', '{"last": 1e400}', '{"prev": {"a": NaN, "b": 1}}',
    '{"prev": {"a": 1, "b": Infinity}}', '{"count": 1e400}',
    '{"count": 3}', '{"count": "4", "last": "1.5"}', '{"count":1,"last":0,"prev":{}}',
    '{"count":1,"last":0.0,"prev":{}}', '{"count":1.0,"last":1700000000,"prev":{}}',
    '{"count":true,"last":false,"prev":{"a":1}}', '{"count":1,"last":"nan","prev":{}}',
    '{"count":1,"last":"-inf","prev":{}}', '{"count":1,"last":"Infinity","prev":{}}',
    '{"count":1,"last":"1e5","prev":{}}', '{"count":1,"last":"1_0.5","prev":{}}',
    '{"count":1,"last":" 2.5 ","prev":{}}', '{"count":1,"last":"0x10","prev":{}}',
    '{"count":1,"last":"1e500","prev":{}}', '{"count":1,"last":".5","prev":{}}', '{"count":1,"last":"5.","prev":{}}',
    '{"count":1,"last":"1_","prev":{}}', '{"count":1,"last":"e5","prev":{}}',
    '{"prev": [1]}', '{"prev": {"a":"3","b":null,"c":2.9,"d":"x","e":true,"f":-1,"g":[]}}',
    '{"count":1,"last":0,"prev":{},"extra":1}', '{"count":1,"last":1e16,"prev":{}}',
    '{"count":1,"last":1e-5,"prev":{}}', '{"count":1,"last":123.456,"prev":{}}', '{"count":1,"last":-0.0,"prev":{}}',
    '{"count":1,"last":1e22,"prev":{}}', '{"count":1,"last":5e-324,"prev":{}}',
    '{"count":1,"last":1.7976931348623157e308,"prev":{}}', '{"count":1,"last":0.0001,"prev":{}}',
    '{"count":1,"last":123456789012345.6,"prev":{}}', '{"count":1,"last":1234567890123456.7,"prev":{}}',
    '{"count":1,"last":1700000123.4567,"prev":{"\\u65e5":2}}',
    '{"count":2,"last":1,"prev":{"a":1}}', '{"count":2,"last":true,"prev":{"a":true}}',
    '{"count":2,"last":1.0,"prev":{"a":1.0}}', '{"count":2,"last":1.0,"prev":{"a":1.5}}',
    '{"count":"2","last":1.0,"prev":{"a":1}}', '{"count":2,"last":1.0}',
    '{"count":2,"last":1.0,"prev":{"a":1,"b":"2"}}', '{"last":1.0,"prev":{},"count":2}',
]


def gen_prev(rng, n):
    pool = [chr(0x4e00 + i) for i in range(60)] + list('abcdefghij')
    keys = rng.sample(pool, n)
    return {k: rng.randint(0, 5) for k in keys}


def count_cases():
    rng = random.Random(1234)
    c = Cin.__new__(Cin)
    out = {}
    norm = []
    big = {str(i): i % 4 for i in range(40)}
    cases = NORMALIZE_CASES + [dumps({'count': 1, 'last': 2.0, 'prev': big})]
    for text in cases:
        value = json.loads(text)
        try:
            n = c._normalizeCountEntry(value)
        except Exception:
            norm.append([text, 'ERR', None])
            continue
        norm.append([text, dumps(n), n != value])
    out['normalize'] = norm
    trims = []
    for _ in range(300):
        prev = gen_prev(rng, rng.randint(0, 45))
        keep = rng.choice(list(prev) + ['', 'zz']) if prev else rng.choice(['', 'zz'])
        trims.append([dumps(prev), keep, dumps(c._trimContextCounts(dict(prev), keep))])
    out['trim'] = trims
    return out


TINY_TABLE = dumps({
    'ename': 'tiny', 'cname': '小', 'selkey': '123',
    'keynames': {'a': '日', 'b': '月'},
    'chardefs': {'a': ['日', '曰', '', '曰'], 'ab': ['明', '朋', '易', '昭'],
                 'b': ['月', '', ''], 'bb': ['朋']},
    'privateuse': {'a': ['', '曰'], 'b': ['', '']},
    'dupchardefs': {},
    'cincount': {'big5F': 3, 'cjk': 1},
})


def new_tiny(dirname, ignore_pua=False, count_text=None, count_bytes=None):
    d = new_count_dir(dirname)
    if count_text is not None or count_bytes is not None:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'cincount.json'), 'wb') as f:
            f.write(count_bytes if count_bytes is not None else count_text.encode('utf-8'))
    import io
    return Cin(io.StringIO(TINY_TABLE), dirname, ignore_pua), d


def file_hex(d):
    p = os.path.join(d, 'cincount.json')
    if not os.path.exists(p):
        return None
    with open(p, 'rb') as f:
        return f.read().hex()


def has_backup(d):
    return any(n.startswith('cincount.json.broken-') for n in os.listdir(d)) if os.path.isdir(d) else False


ODD_FILES = [
    '', '   ', '{}', '[]', 'null', '{"a": 5}', '{"a": {"b": 3}}',
    '{"a": {"b": {"count": 2, "last": 1700000000.5, "prev": {"x": 1}}}}',
    '{"a": {"b": {"count": 2, "last": 1700000000.5, "prev": {"x": 1}}}, "b": [1]}',
    '{', '﻿{}', '{"a": {"b": 1}, "a": {"c": 2}}', '{"a": {"b": 1e400}}',
    '{"a": {"日": {"count": "3", "last": "x", "prev": {"月": 2}}, "月": 7}}',
    '{"ab": {"明": {"count": 4, "last": 1700000000.0, "prev": {}}}}',
    '\n{"a":{"b":{"count":1,"last":0,"prev":{}}}}\n',
    '{"a":{"b":{"count":1,"last":NaN,"prev":{}}}}', '{"a":{"b":{"last":1e400}}}', '{"a":{"b":{"count":Infinity}}}',
    '{"a":{"b":{"count":1,"last":2.5,"prev":{"x":-Infinity}}}}', '{"a":{"\\ud83d\\ude00":3}}', ' {"a":{}} ',
    '{"a":{"b":{"count":1,"last":1700000000.1234567,"prev":{"x":1}}}}', '{"a":{"b":{"count":1,"last":0.1,"prev":{}}}}',
]


def load_cases():
    out = []
    for i, text in enumerate(ODD_FILES + ['BYTES:ff fe 00', 'BYTES:7b 22 61 22 3a 7b 22 62 22 3a 31 7d 7d 80']):
        if text.startswith('BYTES:'):
            data = bytes.fromhex(text[6:].replace(' ', ''))
            c, d = new_tiny('cinref_load%d' % i, count_bytes=data)
        else:
            data = text.encode('utf-8')
            c, d = new_tiny('cinref_load%d' % i, count_text=text)
        r = {'file_hex': data.hex(), 'cincount': dumps(c.cincount), 'dirty': c._count_dirty, 'backup': has_backup(d)}
        c.saveCountFile(force=True)
        r['saved_hex'] = file_hex(d)
        r['dirty_after'] = c._count_dirty
        c._closed = True
        out.append(r)
    return out


def random_count_file(rng, now):
    chars = ['明', '朋', '易', '昭', '日', '曰']
    prevs = ['我', '你', '他', 'x']
    data = {}
    for key in ('a', 'ab', 'zz'):
        if rng.random() < 0.2:
            continue
        entries = {}
        for ch in rng.sample(chars, rng.randint(0, len(chars))):
            r = rng.random()
            if r < 0.05:
                entries[ch] = rng.randint(-1, 9)
                continue
            count = rng.randint(0, 30) if rng.random() > 0.03 else rng.choice([-1, -5, 0])
            last = rng.choice([0, now - rng.randint(0, 90) * 86400 - rng.random() * 1000, now + 500, now - 0.5,
                               now - 7 * 86400, 1e-3])
            prev = {p: rng.randint(-1, 6) for p in rng.sample(prevs, rng.randint(0, len(prevs)))}
            entries[ch] = {'count': count, 'last': last, 'prev': prev}
        data[key] = entries
    return dumps(data)


def sort_cases():
    rng = random.Random(99)
    out = []
    cands_pool = ['明', '朋', '易', '昭', '日', '曰', '水']
    for i in range(150):
        delta = rng.choice([0.0, 12.5, 86400.0 * 3, 1e6 + 0.37])
        FAKE.now = CLOCK_START + delta
        text = random_count_file(rng, FAKE.now)
        c, d = new_tiny('cinref_sort', count_text=text)
        queries = []
        for _ in range(12):
            key = rng.choice(['a', 'ab', 'zz', 'none'])
            cands = rng.sample(cands_pool, rng.randint(0, len(cands_pool)))
            prev = rng.choice(['', '我', '你', '他', 'x', 'q'])
            use_recent = rng.random() < 0.7
            use_context = rng.random() < 0.85
            queries.append([key, cands, prev, use_recent, use_context,
                            try_call(c.sortByCount, key, cands, prev, use_recent, use_context)])
        out.append({'delta': repr(delta), 'file': text, 'queries': queries})
        c._closed = True
    FAKE.now = CLOCK_START
    return out


def add_cases():
    rng = random.Random(4321)
    out = []
    chars = ['明', '朋', '易', '昭']
    prevs = ['', '', '我', '你'] + [chr(0x4e00 + i) for i in range(40)]
    for i in range(40):
        FAKE.now = CLOCK_START
        initial = random_count_file(rng, FAKE.now) if rng.random() < 0.6 else None
        c, d = new_tiny('cinref_add', count_text=initial)
        ops = []
        for _ in range(rng.randint(1, 60)):
            r = rng.random()
            if r < 0.6:
                op = ['add', rng.choice(['a', 'ab', 'new']), rng.choice(chars), rng.choice(prevs)]
                c.addCount(op[1], op[2], op[3])
                ops.append(op + [c._count_dirty])
            elif r < 0.8:
                step = rng.choice([0.01, 1.5, 30.0, 59.99, 60.0, 61.0, 3600.0])
                FAKE.now += step
                ops.append(['advance', repr(step)])
            else:
                force = rng.random() < 0.3
                c.saveCountFile(force=force)
                ops.append(['save', force, file_hex(d), c._count_dirty])
        c.__del__()
        ops.append(['close', file_hex(d)])
        out.append({'initial': initial, 'ops': ops})
    FAKE.now = CLOCK_START
    return out


def tiny_cases():
    out = {}
    for ignore in (False, True):
        c, d = new_tiny('cinref_tiny', ignore_pua=ignore)
        out['ignore%d' % ignore] = {'chardefs': dumps(c.chardefs), 'cincount': dumps(c.cincount),
                                    'encode': c.getCharEncode('曰'), 'wild': c.getWildcardCharDefs('*', '*', 100, True)}
        c.__del__()
    import io
    bad = json.loads(TINY_TABLE)
    bad['privateuse'] = {'nokey': ['']}
    try:
        Cin(io.StringIO(dumps(bad)), 'cinref_tiny', True)
        out['bad_privateuse'] = 'ok'
    except Exception:
        out['bad_privateuse'] = 'ERR'
    out['bad_privateuse_text'] = dumps(bad)
    return out


def main():
    out_path = sys.argv[1]
    json_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(REPO, 'python', 'cinbase', 'json')
    result = {'charset_rle': charset_rle()}
    rng = random.Random(20261006)
    tables = []
    for name, ignore in (('dayi3.json', True), ('dayi3.json', False), ('dayi4.json', True),
                         ('thdayi.json', True), ('checj.json', True)):
        if os.path.exists(os.path.join(json_dir, name)):
            tables.append(dump_table(name, json_dir, ignore, rng))
    result['tables'] = tables
    rtables = []
    for name, cls in (('checj.json', RCin), ('dayi3.json', RCin), ('thphonetic.json', HCin), ('bpmf.json', HCin)):
        if os.path.exists(os.path.join(json_dir, name)):
            d = dump_rcin(name, json_dir, cls)
            d['kind'] = cls.__name__
            rtables.append(d)
    result['rtables'] = rtables
    result['counts'] = count_cases()
    result['tiny_table'] = TINY_TABLE
    result['tiny'] = tiny_cases()
    result['load'] = load_cases()
    result['sort'] = sort_cases()
    result['add'] = add_cases()
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == '__main__':
    main()
