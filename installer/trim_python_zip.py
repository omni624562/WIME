"""Build the Python standard library zip shipped by the installer.

Reads python/python3/python312.zip (the embeddable distribution's library, which
the tests run against and so stays complete) and writes build/python312.zip
without the packages and modules that neither the backend (大易 / 新酷音 / 酷倉),
the two settings tools nor the installer's compileall step ever import: 404 of
599 entries are kept. Every module in the deny lists was checked against the
modules those programs actually load.

The entries are stored uncompressed: the installer compresses the whole payload
with solid LZMA anyway, which shrinks stored bytecode far better than it can
shrink already deflated data (about 1.5 MB in the installer instead of 3.8 MB).
"""

import os
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SOURCE = os.path.join(ROOT, "python", "python3", "python312.zip")
TARGET = os.path.join(ROOT, "build", "python312.zip")

DENY_PACKAGES = {
    "pydoc_data", "lib2to3", "xml", "xmlrpc", "unittest", "msilib", "wsgiref", "zoneinfo",
    "tomllib", "curses", "dbm", "__phello__", "site-packages",
}
DENY_MODULES = set("""
    _pydecimal pydoc mailbox tarfile _pyio _pydatetime doctest pickletools pdb bdb optparse
    imaplib plistlib aifc pstats nntplib ftplib smtplib cgi cgitb trace profile cProfile
    telnetlib sunau wave sndhdr xdrlib mailcap pipes tabnanny pyclbr symtable modulefinder
    timeit zipapp shelve netrc poplib imghdr chunk antigravity this turtle tracemalloc
""".split())


def keep(name):
    top = name.split("/")[0]
    if top in DENY_PACKAGES:
        return False
    if "/" not in name and os.path.splitext(name)[0] in DENY_MODULES:
        return False
    return True


def main():
    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    kept = 0
    with zipfile.ZipFile(SOURCE) as source, \
            zipfile.ZipFile(TARGET + ".tmp", "w", zipfile.ZIP_STORED) as target:
        infos = source.infolist()
        for info in infos:
            if keep(info.filename):
                target.writestr(zipfile.ZipInfo(info.filename, info.date_time), source.read(info.filename))
                kept += 1
    os.replace(TARGET + ".tmp", TARGET)
    print("python312.zip: kept %d of %d entries, %d bytes" % (kept, len(infos), os.path.getsize(TARGET)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
