"""Generates cinbase-rs/src/big5_charset.bin for cin.rs (Cin.getCharSet).

Cin.getCharSet classifies the CJK Unified Ideographs U+4E00..U+9FEA with
Python's 'big5' codec, which is not the WHATWG Big5 that Rust crates offer.
This writes one byte per code point U+4E00..U+9FEA with the category that
cin.py returns for it:

    0 = "cjk"        (not encodable as Big5)
    1 = "big5F"      (0xA440 <= code < 0xC67F)
    2 = "big5LF"     (0xC940 <= code < 0xF9D6, and also the symbol range
                      0xA140 <= code < 0xA3C0, which cin.py maps to big5LF too)
    3 = "big5Other"

Run with the Python that ships with PIME (python/python3/python.exe) or any
CPython 3:  python cinbase-rs/tools/gen_big5_charset.py [--check]
"""
import os
import sys

FIRST = 0x4E00
END = 0x9FEB  # exclusive, cin.py's charsetRange['cjk'][1]


def category(cp):
    try:
        code = int(chr(cp).encode('big5').hex(), 16)
    except Exception:
        return 0
    if 0xA440 <= code < 0xC67F:
        return 1
    if 0xC940 <= code < 0xF9D6:
        return 2
    if 0xA140 <= code < 0xA3C0:
        return 2
    return 3


def build():
    return bytes(category(cp) for cp in range(FIRST, END))


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src', 'big5_charset.bin')
    data = build()
    if '--check' in sys.argv:
        with open(out, 'rb') as f:
            same = f.read() == data
        print('big5_charset.bin is', 'up to date' if same else 'OUT OF DATE')
        sys.exit(0 if same else 1)
    with open(out, 'wb') as f:
        f.write(data)
    print('wrote %d bytes to %s' % (len(data), os.path.normpath(out)))


if __name__ == '__main__':
    main()
