"""Writes the hand-made seed inputs of the fuzz targets (fuzz/seeds/<target>/).

    python\\python3\\python.exe cinbase-rs\\fuzz\\make_seeds.py

The seeds are what each target normally gets -- typing in every input method,
logged-in requests to every settings-tool endpoint, real dictionary files -- so
libFuzzer starts from inputs that get deep into the code. A real chewing.dat
comes from the repo's wime-config.exe (cargo build --release first), run in a
temporary profile with the browser launch stubbed out.
"""

import http.cookiejar
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = os.path.join(HERE, "seeds")
CONFIG_EXE = os.path.join(HERE, os.pardir, "target", "i686-pc-windows-msvc", "release", "wime-config.exe")
TOKEN = "0123456789abcdef0123456789abcdef"   # wime::fuzz::TOKEN
CHEDAYI, CHECJ, CHEWING = 0, 1, 2           # wime::fuzz::IMES / APPS order


def write(target, name, data):
    folder = os.path.join(SEEDS, target)
    os.makedirs(folder, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    with open(os.path.join(folder, name), "wb") as f:
        f.write(data)


# --- backend: little programs (see wime::fuzz::backend) ------------------------

def key(code, modifiers=None):
    """op 0 (a key press), key class 3 (any key code), the code, modifiers"""
    if modifiers is None:
        return bytes([0, 3, code, 1])            # modifiers byte % 4 != 0: none
    return bytes([0, 3, code, 0, modifiers])


def typing(text):
    return b"".join(key(ord(c.upper())) if c.isalpha() else key(ord(c)) if c.isdigit() else key(
        {" ": 0x20, "\n": 0x0D, "\b": 0x08, ",": 0xBC, ".": 0xBE, ";": 0xBA, "/": 0xBF, "'": 0xDE, "[": 0xDB,
         "]": 0xDD, "-": 0xBD, "=": 0xBB, "`": 0xC0, "\\": 0xDC}[c]) for c in text)


def backend_seeds():
    head = lambda ime: bytes([ime, 0, 0, 0])   # IME, isMetroApp, isUiLess, isConsole
    write("backend", "chedayi_typing", head(CHEDAYI) + typing("bt ab4 ,. \n"))
    write("backend", "chedayi_candidates", head(CHEDAYI) + typing("a") + bytes([0, 3, 0x22, 1, 0, 3, 0x28, 1]) + typing("2\b\b"))
    write("backend", "chedayi_symbols", head(CHEDAYI) + typing("`") + typing("1") + key(0x20) + key(ord("'"), 1))
    write("backend", "checj_typing", head(CHECJ) + typing("a a ab hqi \n"))
    write("backend", "checj_wildcard", head(CHECJ) + typing("a") + key(ord("8"), 1) + typing("b ") + key(ord("Z")) + typing(" x"))
    write("backend", "chewing_typing", head(CHEWING) + typing("su3cl3\n"))
    write("backend", "chewing_select", head(CHEWING) + typing("su3") + bytes([0, 3, 0x28, 1]) + typing("1") + typing("\n"))
    write("backend", "chewing_shift_and_caps", head(CHEWING) + key(0x10, 1) + typing("ji3") + key(0x14, 8) + typing("abc\n"))
    write("backend", "commands_and_menus", head(CHEWING) + bytes([9, 3, 0, 9, 19, 0, 10, 1, 11, 0, 0, 12, 0, 12, 1, 13, 1, 14, 15, 0, 1, 15, 1, 40]))
    write("backend", "commands_cinbase", head(CHEDAYI) + bytes([9, 3, 0, 9, 5, 0, 10, 2, 11, 1, 0, 15, 0, 0]) + typing("bt"))
    write("backend", "ctrl_alt_keys", head(CHECJ) + key(ord("A"), 2) + key(ord("A"), 4) + key(0x20, 1) + key(0x20, 2))
    write("backend", "odd_char_codes", head(CHEDAYI) + bytes([8, 0, 0, 0, 0, 0xFF, 0xFF, 8, 1, 0, 1, 0, 0x00, 0xD8]))


def backend_raw_seeds():
    guids = {"chedayi": "{e6943374-70f5-4540-aa0f-3205c7dcca84}", "chewing": "{f80736aa-28db-423a-92c9-5540f501c939}"}
    lines = []
    for ime, guid in guids.items():
        lines.append('%s|{"method":"init","id":"%s","isWindows8Above":true,"isMetroApp":false,"isUiLess":false,"isConsole":false,"seqNum":1}' % (ime, guid))
        lines.append('%s|{"method":"onActivate","isKeyboardOpen":true,"seqNum":2}' % ime)
        lines.append('%s|{"method":"filterKeyDown","keyCode":65,"charCode":97,"repeatCount":1,"scanCode":30,"isExtended":false,"keyStates":{"65":128},"seqNum":3}' % ime)
        lines.append('%s|{"method":"onKeyDown","keyCode":65,"charCode":97,"repeatCount":1,"scanCode":30,"isExtended":false,"keyStates":[0,0,128],"seqNum":4}' % ime)
        lines.append('%s|{"method":"onCommand","id":3,"type":0,"seqNum":5}' % ime)
    write("backend_raw", "two_clients", "\n".join(lines) + "\n")
    write("backend_raw", "malformed", 'x|not json\nx|[1,2]\nx|{"method":"onKeyDown"}\nnobar\n|{}\nx|{"method":"init","id":5,"isWindows8Above":"","isMetroApp":null,"isUiLess":[],"isConsole":{}}\n')
    write("backend_raw", "keystates_odd", 'c|{"method":"init","id":"%s","isWindows8Above":1,"isMetroApp":0,"isUiLess":0,"isConsole":0}\n'
          'c|{"method":"onKeyDown","keyCode":"66","charCode":-5,"repeatCount":1e300,"scanCode":null,"isExtended":"yes","keyStates":{"999":1,"-1":2,"x":3}}\n' % guids["chedayi"])


# --- config_http: the first byte picks the tool, then raw HTTP ------------------

def request(method, path, cookie=None, body=b"", content_type="application/json", extra=""):
    headers = "Host: 127.0.0.1:12345\r\n"
    if cookie:
        headers += "Cookie: %s=%s\r\n" % (cookie, TOKEN)
    if body or method == "POST":
        headers += "Content-Type: %s\r\nContent-Length: %d\r\n" % (content_type, len(body))
    return ("%s %s HTTP/1.1\r\n%s%s\r\n" % (method, path, headers, extra)).encode("latin-1") + body


def multipart_body(boundary, filename, data):
    return (("--%s\r\nContent-Disposition: form-data; name=\"import_user_phrase\"; filename=\"%s\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n" % (boundary, filename)).encode() + data
            + ("\r\n--%s--\r\n" % boundary).encode())


def config_http_seeds(chewing_dat, old_sqlite):
    cin = "cinbase_config_token"
    chewing = "chewing_config_token"
    with open(os.path.join(HERE, os.pardir, os.pardir, "python", "input_methods", "chedayi", "config", "config.json"), "rb") as f:
        dayi_config = f.read()
    for ime, name in ((CHEDAYI, "chedayi"), (CHECJ, "checj")):
        write("config_http", name + "_get", bytes([ime]) + request("GET", "/config", cin) + request("GET", "/keep_alive", cin))
        write("config_http", name + "_login", bytes([ime]) + request("GET", "/login/config?token=" + TOKEN) + request("POST", "/login/user_phrase_editor", body=("token=" + TOKEN).encode(), content_type="application/x-www-form-urlencoded"))
        write("config_http", name + "_pages", bytes([ime]) + request("GET", "/config.html", cin) + request("GET", "/config.js", cin) + request("GET", "/css/../../../version.txt", cin) + request("GET", "/data/emoji.json", cin) + request("GET", "//config.htm", cin))
    write("config_http", "chedayi_save", bytes([CHEDAYI]) + request("POST", "/config", cin, b'{"config":' + dayi_config + b'}') + request("GET", "/config", cin))
    write("config_http", "chedayi_save_odd", bytes([CHEDAYI]) + request("POST", "/config", cin, b'{"config":{"candPerRow":"x","keyboardLayout":1e999},"symbols":5}') + request("POST", "/config", cin, b'[1]'))
    write("config_http", "chewing_get", bytes([CHEWING]) + request("GET", "/config", chewing) + request("GET", "/user_phrases", chewing) + request("GET", "/user_phrase_file", chewing) + request("GET", "/version.txt", chewing))
    write("config_http", "chewing_save", bytes([CHEWING]) + request("POST", "/config", chewing, json.dumps({"config": {"candPerPage": 9, "keyboardLayout": 0}, "symbols": "測試=★☆\n", "swkb": "a b\n"}, ensure_ascii=False).encode()))
    write("config_http", "chewing_phrases", bytes([CHEWING]) + request("POST", "/user_phrases", chewing, json.dumps({"add": [{"phrase": "測試", "bopomofo": "ㄘㄜˋ ㄕˋ"}], "remove": [{"phrase": "你好", "bopomofo": "ㄋㄧˇ ㄏㄠˇ"}]}, ensure_ascii=False).encode()) + request("GET", "/user_phrases", chewing))
    for name, data in (("dat", chewing_dat), ("sqlite", old_sqlite)):
        body = multipart_body("XyZ", "chewing." + name, data)
        write("config_http", "chewing_import_" + name, bytes([CHEWING]) + request("POST", "/user_phrase_file", chewing, body, "multipart/form-data; boundary=XyZ"))
    write("config_http", "protocol_errors", bytes([CHEWING]) + b"GET /\r\n" + b"BREW /config HTTP/1.1\r\n\r\n")
    write("config_http", "protocol_versions", bytes([CHEDAYI]) + b"GET /config HTTP/2.0\r\nHost: localhost\r\n\r\n")
    write("config_http", "bad_host_and_length", bytes([CHEDAYI]) + request("GET", "/config", cin).replace(b"127.0.0.1:12345", b"evil.example") + b"POST /config HTTP/1.1\r\nHost: [::1]:1\r\nContent-Length: -1\r\n\r\n")
    write("config_http", "chunked_and_expect", bytes([CHEWING]) + b"POST /config HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n" + request("POST", "/config", chewing, b"{}", extra="Expect: 100-continue\r\n"))
    write("config_http", "folded_headers_cookies", bytes([CHEDAYI]) + b"GET /config HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: a=1;\r\n  cinbase_config_token=\"" + TOKEN.encode() + b"\"; b=\"\\\\\\042x\"\r\nConnection: keep-alive\r\n\r\n")


def multipart_seeds(chewing_dat):
    write("multipart", "one_file", b"multipart/form-data; boundary=XyZ\0" + multipart_body("XyZ", "a.dat", chewing_dat[:64]))
    write("multipart", "encodings", b'multipart/form-data; boundary="b b"; charset=utf-8\0'
          b'--b b\r\nContent-Disposition: form-data; name="f"; filename*=UTF-8\'\'%E6%B8%AC.dat\r\nContent-Transfer-Encoding: base64\r\n\r\nQUJD\r\n'
          b'--b b\r\nContent-Disposition: form-data; name="g"; filename="q.txt"\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\na=3D=\r\nb\r\n--b b--\r\n')
    write("multipart", "no_boundary", b"multipart/form-data\0--x\r\n\r\n")


def text_seeds():
    write("http_fields", "cookie", 'a=b; cinbase_config_token="%s"; c="\\"q\\\\"; WIMEConfig=v' % TOKEN)
    write("http_fields", "query", "token=%E6%B8%AC&x=1&y=&z&%zz=%ff+%2B")
    write("json_body", "config", '{"config": {"a": [1, 2.5, -0.0, 1e300, true, null, "\\u6e2c\\ud83d\\ude00"]}, "b": {}}')
    write("json_body", "floats", "[0.1, 1e-42, 5e-324, 1.7976931348623157e308, 123456789012345678901234567890, -0]")
    write("json_body", "python_extras", '{"a": NaN, "b": Infinity, "c": -Infinity, "d": "\\ud800"}')


# --- the dictionaries ------------------------------------------------------------

def old_sqlite_dictionary():
    """an old chewing.sqlite3 (userphrase_v1, libchewing before 0.13)"""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "chewing.sqlite3")
        conn = sqlite3.connect(path)
        phones = ", ".join("phone_%d INTEGER" % i for i in range(11))
        conn.execute("CREATE TABLE config_v1 (id INTEGER PRIMARY KEY, value INTEGER)")
        conn.execute("CREATE TABLE userphrase_v1 (time INTEGER, user_freq INTEGER, max_freq INTEGER, orig_freq INTEGER, "
                     "length INTEGER, phrase TEXT, %s, PRIMARY KEY (phone_0, phone_1, phone_2, phone_3, phone_4, phone_5, "
                     "phone_6, phone_7, phone_8, phone_9, phone_10, phrase))" % phones)
        # 測試 ㄘㄜˋ ㄕˋ, 你好 ㄋㄧˇ ㄏㄠˇ (libchewing phone codes)
        for phrase, codes in (("測試", (6732, 2316)), ("你好", (2499, 4995))):
            row = [1, 1, 1, 1, len(codes), phrase] + list(codes) + [0] * (11 - len(codes))
            conn.execute("INSERT INTO userphrase_v1 VALUES (%s)" % ", ".join("?" * len(row)), row)
        conn.commit()
        conn.close()
        with open(path, "rb") as f:
            return f.read()


def chewing_dat_dictionary(old_sqlite):
    """a real chewing.dat: wime-config.exe imports the old dictionary, adds a
    phrase, and exports the file (all in a temporary profile)"""
    if not os.path.isfile(CONFIG_EXE):
        sys.exit("build wime-config.exe first (cd cinbase-rs && cargo build --release)")
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, APPDATA=tmp, LOCALAPPDATA=tmp, WIME_CONFIG_TEST_LAUNCH="print", WIME_CONFIG_IDLE_TIMEOUT="5")
        proc = subprocess.Popen([CONFIG_EXE, "user_phrase_editor", "chewing"], env=env, stdout=subprocess.PIPE, text=True)
        try:
            url = proc.stdout.readline().strip()[4:]
            base = url.split("/login/")[0]
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            opener.open(url, timeout=10).read()
            body = multipart_body("XyZ", "chewing.sqlite3", old_sqlite)
            opener.open(urllib.request.Request(base + "/user_phrase_file", body, {"Content-Type": "multipart/form-data; boundary=XyZ"}), timeout=30).read()
            add = json.dumps({"add": [{"phrase": "模糊", "bopomofo": "ㄇㄛˊ ㄏㄨˊ"}]}, ensure_ascii=False).encode()
            opener.open(urllib.request.Request(base + "/user_phrases", add, {"Content-Type": "application/json"}), timeout=30).read()
            return opener.open(base + "/user_phrase_file", timeout=30).read()
        finally:
            proc.kill()
            proc.wait()


def main():
    old_sqlite = old_sqlite_dictionary()
    chewing_dat = chewing_dat_dictionary(old_sqlite)
    assert chewing_dat[:1] == b"\x30" and b"CHEW" in chewing_dat[:16], chewing_dat[:16]
    write("user_dictionary", "chewing.dat", chewing_dat)
    write("user_dictionary", "chewing.sqlite3", old_sqlite)
    write("user_dictionary", "not_a_dictionary", b"0\x06\x0c\x04CHEW")
    backend_seeds()
    backend_raw_seeds()
    config_http_seeds(chewing_dat, old_sqlite)
    multipart_seeds(chewing_dat)
    text_seeds()
    for target in sorted(os.listdir(SEEDS)):
        print("%-16s %d seeds" % (target, len(os.listdir(os.path.join(SEEDS, target)))))


if __name__ == "__main__":
    main()
