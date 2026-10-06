"""Key events as PIMEClient.cpp sends them (Client::addKeyEventToRpcRequest),
for the differential harness. Standalone: it must not import the backend.

key_event("a")              plain a
key_event("A")              Shift+a (an upper-case letter implies Shift)
key_event("a", "C")         Ctrl+a; modifiers: S left Shift, R right Shift,
                            C Ctrl, A Alt
key_event("SHIFT", "R")     the right Shift key pressed on its own
Named keys: SPACE ENTER ESC BACK TAB LEFT RIGHT UP DOWN HOME END PGUP PGDN DEL
SHIFT CTRL CAPS, NUM0-NUM9 NUM* NUM+ NUM- NUM. NUM/.

keyStates is the sparse {"vk": state} object the DLL sends: 0x80 for keys that
are down, 0x01 for toggled keys. Num Lock is always on, Caps Lock always off.
"""

VK_BACK, VK_TAB, VK_RETURN, VK_SHIFT, VK_CONTROL, VK_MENU, VK_CAPITAL = 0x08, 0x09, 0x0D, 0x10, 0x11, 0x12, 0x14
VK_ESCAPE, VK_SPACE, VK_PRIOR, VK_NEXT, VK_END, VK_HOME = 0x1B, 0x20, 0x21, 0x22, 0x23, 0x24
VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN, VK_DELETE = 0x25, 0x26, 0x27, 0x28, 0x2E
VK_NUMPAD0, VK_MULTIPLY, VK_ADD, VK_SUBTRACT, VK_DECIMAL, VK_DIVIDE = 0x60, 0x6A, 0x6B, 0x6D, 0x6E, 0x6F
VK_NUMLOCK = 0x90
VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_LMENU = 0xA0, 0xA1, 0xA2, 0xA4
LEFT_SHIFT_SCAN, RIGHT_SHIFT_SCAN = 0x2A, 0x36

SYMBOL_VK = {
    "'": 0xDE, '"': 0xDE, "[": 0xDB, "{": 0xDB, "]": 0xDD, "}": 0xDD,
    "-": 0xBD, "_": 0xBD, "\\": 0xDC, "|": 0xDC, "=": 0xBB, "+": 0xBB,
    ";": 0xBA, ":": 0xBA, ",": 0xBC, "<": 0xBC, ".": 0xBE, ">": 0xBE,
    "/": 0xBF, "?": 0xBF, "`": 0xC0, "~": 0xC0,
}
SHIFTED_DIGITS = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
                  "^": "6", "&": "7", "*": "8", "(": "9", ")": "0"}
SHIFTED_SYMBOLS = set('"{}_|+:<>?~') | set(SHIFTED_DIGITS)
NAMED = {
    "SPACE": (0x20, VK_SPACE), "ENTER": (0x0D, VK_RETURN), "ESC": (0x1B, VK_ESCAPE),
    "BACK": (0x08, VK_BACK), "TAB": (0x09, VK_TAB),
    "LEFT": (0, VK_LEFT), "RIGHT": (0, VK_RIGHT), "UP": (0, VK_UP), "DOWN": (0, VK_DOWN),
    "HOME": (0, VK_HOME), "END": (0, VK_END), "PGUP": (0, VK_PRIOR), "PGDN": (0, VK_NEXT),
    "DEL": (0, VK_DELETE), "SHIFT": (0, VK_SHIFT), "CTRL": (0, VK_CONTROL), "CAPS": (0, VK_CAPITAL),
    "NUM*": (ord("*"), VK_MULTIPLY), "NUM+": (ord("+"), VK_ADD), "NUM-": (ord("-"), VK_SUBTRACT),
    "NUM.": (ord("."), VK_DECIMAL), "NUM/": (ord("/"), VK_DIVIDE),
}
for _d in range(10):
    NAMED["NUM%d" % _d] = (ord(str(_d)), VK_NUMPAD0 + _d)


def key_event(key, mods="", down=True):
    """The fields of a filterKeyDown/onKeyDown (down=True) or
    filterKeyUp/onKeyUp request for one key."""
    shift = "S" in mods or "R" in mods
    ctrl, alt = "C" in mods, "A" in mods
    scan = 0
    if key in NAMED:
        char_code, key_code = NAMED[key]
        if key == "SHIFT":
            shift = True
            scan = RIGHT_SHIFT_SCAN if "R" in mods else LEFT_SHIFT_SCAN
        elif key == "CTRL":
            ctrl = True
    else:
        if len(key) != 1:
            raise ValueError("unknown key %r" % (key,))
        char_code = ord(key)
        if key.isascii() and key.isalpha():
            key_code = ord(key.upper())
            if key.isupper():
                shift = True
            elif shift:
                char_code = ord(key.upper())
        elif key.isdigit():
            key_code = ord(key)
        elif key in SHIFTED_DIGITS:
            key_code = ord(SHIFTED_DIGITS[key])
            shift = True
        elif key in SYMBOL_VK:
            key_code = SYMBOL_VK[key]
            shift = shift or key in SHIFTED_SYMBOLS
        else:
            raise ValueError("unknown key %r" % (key,))
        if ctrl and key.isascii() and key.isalpha():
            char_code = ord(key.upper()) - 0x40     # Ctrl+A -> 0x01
    if alt:
        char_code = 0
    states = {str(VK_NUMLOCK): 0x01}
    if down:
        states[str(key_code)] = 0x80
    side = VK_RSHIFT if "R" in mods else VK_LSHIFT
    # a modifier key released on its own is no longer down in its key-up event
    if shift and not (key == "SHIFT" and not down):
        states[str(VK_SHIFT)] = 0x80
        states[str(side)] = 0x80
    if ctrl and not (key == "CTRL" and not down):
        states[str(VK_CONTROL)] = 0x80
        states[str(VK_LCONTROL)] = 0x80
    if alt:
        states[str(VK_MENU)] = 0x80
        states[str(VK_LMENU)] = 0x80
    return {"charCode": char_code, "keyCode": key_code, "repeatCount": 1,
            "scanCode": scan, "isExtended": False, "keyStates": states}
