#! python3
# Writes the tricky input files of cinbase-rs/tests/fixtures/data/ (exact bytes:
# BOMs, CRLF / lone CR, ANSI cp950, invalid bytes). Run from anywhere:
#   python\python3\python.exe cinbase-rs\tests\fixtures\gen_fixtures.py
import os

here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(here, exist_ok=True)


def write(name, data):
    with open(os.path.join(here, name), "wb") as f:
        f.write(data)


BOM = b"\xef\xbb\xbf"

symbols = "\r\n".join([
    "﻿﻿ 標點=，。、",          # BOM (twice) on the first line
    "",
    "   ",
    "…",                                  # leaf
    "※",                                  # leaf
    "※",                                  # duplicate leaf
    "名稱=",                              # no content: skipped
    "=abc",                               # no name: skipped
    "標點=！？",                          # duplicate category: appended
    "愛心 ❤️👍🏻🇹🇼🇯🇵🇺👨‍👩‍👧1️⃣é‍",
    "分頁\t①②③",
    "混合 a=b c",                        # '=' wins over ' '
    "　全形空白　=　ＡＢ　",
    "\x1c控制\x1d=x\x1f",
    "葉也是分類",                          # leaf that is also a category below
    "葉也是分類=甲乙",
    "  ﻿內藏BOM=丙",                  # BOM after whitespace is kept
    "a\rb=c\rlone=cr",                    # lone CR line endings
    "\x85NEL=next line",
    "最後=結尾",
]).encode("utf-8")
write("tricky_symbols.dat", BOM + symbols)
write("tricky_symbols_lf.dat", symbols.replace(b"\r\n", b"\n") + b"\n\n")

# cp950 bytes (not UTF-8), an invalid 0xFF, a lead byte + bad trail byte and
# a truncated lead byte at EOF: decoded as 'mbcs' with errors='replace'
cp950 = "標點=，。、\r\n希臘字母=αβγ\r\nQ 「\r\n中=文,字\r\n".encode("cp950")
write("ansi_cp950.dat", cp950 + b"\xff\xff=x\r\n\x81\x20=y\r\n" + "尾".encode("cp950")[:1])
write("ansi_cp950_bom.dat", BOM + "標點=，。".encode("cp950"))
write("bad_utf8_ascii.dat", b"a=b\r\n\x80\xfe c\r\n")

swkb = "\r\n".join([
    "q 「",
    "Q 」",                                # same key after upper()
    "w\t『",
    "e",                                   # no separator: skipped
    "ß ss",                                # upper() -> SS
    "ﬁ fi",                                # upper() -> FI
    "  r   』 x ",
    "﻿T ‘",
    "Σ σ",
    "ΑΣ final",
    "İ dotted",
    "=x y",
]).encode("utf-8")
write("tricky_swkb.dat", swkb)

userphrase = "\r\n".join([
    "﻿我=們,的,,  ,是,",
    "=詞",
    "你 好,們",
    "他\t們",
    "a,b",                                 # no separator: key "a,b"
    "我=們",                               # duplicate key: extended
    "空=,,,",
    "",
]).encode("utf-8")
write("tricky_userphrase.dat", userphrase)

write("msym_bom_crlf.json", BOM + b'{\r\n "keynames": ["a", "b"],\r\n "chardefs": {"a": ["1", "2"], "b": ["2", "3"]}\r\n}\r\n')
write("msym_dupkeys.json", '{"chardefs": {"x": ["1"], "y": ["2"], "x": ["3"]}, "keynames": ["y"], "other": 5}'.encode("utf-8"))
write("msym_bad.json", b'{"chardefs": {"x": ["1"],}}')
write("msym_pairs.json", b'[["keynames", ["k"]], ["chardefs", {"k": ["v", "w"]}], "ab", {"p": 1, "q": 2}, [1, 2]]')
write("msym_emptystr.json", b'""')
write("msym_str.json", b'"ab"')
write("msym_number.json", b'5')
write("msym_empty.json", b'')
write("phrase_bom.json", BOM + b'{"keynames": [], "chardefs": {"a": ["b"]}}')
write("phrase_crlf.json", b'{"keynames": ["a"],\r\n"chardefs": {"a": ["b", "c"], "d": []}}\r\n')
write("phrase_cp950.json", '{"chardefs": {"字": ["詞"]}}'.encode("cp950"))
