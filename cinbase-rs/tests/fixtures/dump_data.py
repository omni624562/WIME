#! python3
# Dumps what python/cinbase's data-file parsers make of each input file, as
# JSON on stdout. src/data/tests.rs builds the same dump from the Rust port
# and compares (ordered: every dict is dumped as a list of [key, value]).
#
#   python\python3\python.exe cinbase-rs\tests\fixtures\dump_data.py <repo root> <file>...
# Each file is dumped with every parser; the key is "<parser>|<file basename>".
import io
import json
import os
import sys

root = os.path.abspath(sys.argv[1])
sys.path[0:0] = [os.path.join(root, "python"), os.path.join(root, "python", "cinbase")]

import cinbase  # noqa: E402
from cinbase.symbols import symbols  # noqa: E402
from cinbase.flangs import flangs  # noqa: E402
from cinbase.fsymbols import fsymbols  # noqa: E402
from cinbase.swkb import swkb  # noqa: E402
from cinbase.userphrase import userphrase  # noqa: E402
from cinbase.extendtable import extendtable  # noqa: E402
from cinbase.msymbols import msymbols  # noqa: E402
from cinbase.dsymbols import dsymbols  # noqa: E402
from cinbase.phrase import phrase  # noqa: E402
from cinbase.emoji import emoji  # noqa: E402

readDataText = cinbase.readDataText


def items(d):
    return [[k, v] for k, v in d.items()]


def dumpSymbols(t):
    return {
        "keynames": t.getKeyNames(),
        "chardefs": [[k, v] for k, v in t.chardefs.items() if k not in t.leaves],
        "leaves": sorted(t.leaves),
        "get": [[k, t.getCharDef(k), t.isLeaf(k), t.isInCharDef(k)] for k in t.getKeyNames()],
        "missing": [t.getCharDef("\0missing"), t.isLeaf("\0missing"), t.isInCharDef("\0missing")],
    }


def dumpKeyed(t):
    return {"keynames": t.getKeyNames(), "chardefs": items(t.chardefs)}


def dumpPlain(t):
    return {"chardefs": items(t.chardefs)}


def dumpMSymbols(t):
    vals = []
    for v in t.chardefs.values():
        for x in v:
            if x not in vals:
                vals.append(x)
    return {
        "keynames": t.getKeyNames(),
        "chardefs": items(t.chardefs),
        "getKey": [[x, t.isHaveKey(x), t.getKey(x)] for x in vals],
        "missing": t.isHaveKey("\0missing"),
    }


EMOJI_TYPES = ["dingbats", "emoticons", "miscellaneous", "pictographs", "transport"]


def dumpEmoji(t):
    out = {}
    for name in ["dingbats", "emoticons", "miscellaneous", "pictographs", "transport"]:
        out[name] = items(getattr(t, name))
        out[name + "_keynames"] = getattr(t, name + "_keynames")
    out["modifiercolor"] = t.modifiercolor
    calls = []
    for typ in EMOJI_TYPES + ["nosuchtype"]:
        for name in getattr(t, typ + "_keynames", []) + ["\0missing"]:
            try:
                calls.append([typ, name, t.getCharDef(typ, name)])
            except Exception:
                calls.append([typ, name, {"error": True}])
    out["getCharDef"] = calls
    return out


def readUtf8(path):
    return io.open(path, "r", encoding="utf8")


PARSERS = {
    "text": (lambda p: readDataText(p).read(), lambda x: x),
    "symbols": (lambda p: symbols(readDataText(p)), dumpSymbols),
    "flangs": (lambda p: flangs(readDataText(p)), dumpSymbols),
    "fsymbols": (lambda p: fsymbols(readDataText(p)), dumpKeyed),
    "userphrase": (lambda p: userphrase(readDataText(p)), dumpKeyed),
    "swkb": (lambda p: swkb(readDataText(p)), dumpPlain),
    "extendtable": (lambda p: extendtable(readDataText(p)), dumpPlain),
    "msymbols": (lambda p: msymbols(readDataText(p)), dumpMSymbols),
    "dsymbols": (lambda p: dsymbols(readDataText(p)), dumpMSymbols),
    "phrase": (lambda p: phrase(readUtf8(p)), dumpKeyed),
    "emoji": (lambda p: emoji(readUtf8(p)), dumpEmoji),
}

# the big shipped json files are only fed to the json parsers
SHIPPED_JSON = ("phrase.json", "emoji.json", "msymbols.json", "dsymbols.json")

result = {}
for path in sys.argv[2:]:
    base = os.path.basename(path)
    for name, (load, dump) in PARSERS.items():
        if name == "emoji" and base != "emoji.json":
            continue
        if base in SHIPPED_JSON and name not in (("phrase",) if base == "phrase.json" else ("phrase", "msymbols", "dsymbols", "emoji")):
            continue
        try:
            value = dump(load(path))
        except Exception:
            value = {"error": True}
        result[name + "|" + base] = value

out = json.dumps(result, ensure_ascii=False, indent=0)
sys.stdout.buffer.write(out.encode("utf-8"))
