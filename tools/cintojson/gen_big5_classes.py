"""Generates big5_classes.bin for src/main.rs (getCharSet of the table generator).

cintojson.py classifies the CJK Unified Ideographs U+4E00..U+9FEA with Python's
'big5' codec (not the WHATWG Big5 of Rust crates). One byte per code point:

    0 = not encodable as Big5 ("cjk")
    1 = big5F      (0xA440 <= code < 0xC67F)
    2 = big5LF     (0xC940 <= code < 0xF9D6)
    3 = big5S      (0xA140 <= code < 0xA3C0; counted apart from big5LF)
    4 = big5Other

Only needed again if the classification changes; any CPython 3 will do:
    python tools/cintojson/gen_big5_classes.py [--check]
"""
import os
import sys

FIRST, END = 0x4E00, 0x9FEB


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
        return 3
    return 4


def main():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "big5_classes.bin")
    data = bytes(category(cp) for cp in range(FIRST, END))
    if "--check" in sys.argv:
        with open(path, "rb") as f:
            same = f.read() == data
        print("up to date" if same else "DIFFERENT")
        return 0 if same else 1
    with open(path, "wb") as f:
        f.write(data)
    print("wrote %s (%d bytes)" % (path, len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
