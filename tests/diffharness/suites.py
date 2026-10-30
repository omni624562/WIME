"""Hand-written scenarios for the differential harness, grouped by the
behaviours in docs/dayi-rust/feature-inventory.md (section numbers in the
comments). Each suite is one config.json and its scenarios; golden/<name>.jsonl
holds the Python backend's replies.

Steps are written as space-separated tokens:
    a ' SPACE        keys (see keys.py for names)
    S+a  C+;  R+SHIFT  modifier+key (S left Shift, R right Shift, C Ctrl, A Alt)
    wait:2           move the virtual clock 2 seconds
and request dicts can be mixed in: seq("a", CMD(1), "SPACE").

Regenerate the golden files after an intended behaviour change:
    python tests/diffharness/suites.py record
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN_DIR = os.path.join(HERE, "golden")
SHIFT_SPACE = {"request": "onPreservedKey", "guid": "{f1dae0fb-8091-44a7-8a0c-3082a1515447}"}


def CMD(command_id, kind=0):
    return {"request": "onCommand", "id": command_id, "type": kind}


def MENU(button_id):
    return {"request": "onMenu", "id": button_id}


def KEYBOARD(opened):
    return {"request": "onKeyboardStatusChanged", "opened": opened}


def TERMINATED(forced=True):
    return {"request": "onCompositionTerminated", "forced": forced}


KILL_FOCUS = {"request": "onKillFocus"}


def seq(*parts):
    steps = []
    for part in parts:
        if isinstance(part, dict):
            steps.append(part)
            continue
        for token in part.split():
            if token.startswith("wait:"):
                steps.append({"wait": float(token[5:])})
            elif len(token) > 2 and token[1] == "+" and token[0] in "SRCA":
                steps.append([token[2:], token[0]])
            else:
                steps.append(token)
    return steps


def scenarios(**named):
    out = []
    for name, value in named.items():
        if isinstance(value, tuple):
            steps, opened = value
            out.append({"name": name, "steps": steps, "keyboardOpen": opened})
        else:
            out.append({"name": name, "steps": value})
    return out


# --- 大易三碼 with the shipped settings -----------------------------------

DEFAULT = scenarios(
    # §4.3 / §4.5 roots, first candidate with Space, selection keys ' [ ] - \
    commit_space=seq("a SPACE o o SPACE"),
    select_keys=seq("a ' a [ a ] a - a \\"),
    select_key_out_of_range=seq("o o \\ ESC"),
    max_length_three=seq("a a a a SPACE"),
    enter_commits=seq("a ENTER"),
    # §4.3 a key that makes the code no prefix starts over from that key
    restart_on_dead_prefix=seq("b l x SPACE"),
    # §4.4 nothing found, editing keys
    not_found_space=seq("b l SPACE ESC"),
    not_found_enter=seq("b l ENTER ESC"),
    backspace=seq("a o BACK SPACE a BACK BACK ENTER"),
    escape=seq("a o ESC a SPACE"),
    keys_without_composition=seq("ENTER BACK ESC SPACE DEL LEFT TAB"),
    # §4.6 paging and cursor
    paging=seq("a PGDN PGUP PGDN SPACE"),
    cursor_moves=seq("a RIGHT RIGHT SPACE a END SPACE a RIGHT HOME SPACE"),
    up_down=seq("a DOWN UP DOWN SPACE"),
    # §4.7 wildcard: * , Shift+8, numpad *, variable length in the middle
    wildcard_tail=seq("a * SPACE"),
    wildcard_head=seq("* a SPACE"),
    wildcard_middle=seq("a * o SPACE"),
    wildcard_shift8=seq("a S+8 '"),
    wildcard_numpad=seq("o NUM* PGDN SPACE"),
    # §4.13 大易 symbols with = (and ' as the root 號 in 三碼)
    dayi_symbols=seq("= , SPACE = , ' = . [ "),
    dayi_symbols_backspace=seq("= , BACK BACK a SPACE"),
    dayi_symbol_lead_only=seq("= SPACE ESC ' SPACE"),
    # §4.14 punctuation and Shift outside roots
    shift_letters=seq("S+a S+b a S+a SPACE"),
    shift_symbols=seq("S+, S+. S+/ S+1 S+; S+'"),
    full_shape=seq(SHIFT_SPACE, "a SPACE , . S+1 SPACE", SHIFT_SPACE, "a SPACE"),
    # §4.15 Shift tap toggles Chinese/English (< 0.5 s), slow tap does not
    shift_toggle=seq("SHIFT a b SPACE SHIFT a SPACE"),
    shift_toggle_right=seq("R+SHIFT a R+SHIFT a SPACE"),
    shift_tap_while_composing=seq("a SHIFT SPACE SHIFT"),
    caps_lock=seq("CAPS a SPACE"),
    ctrl_symbols=seq("C+; SPACE C+[ C+] ENTER C+, C+, SPACE"),
    ctrl_passthrough=seq("C+a C+SPACE A+a a C+a SPACE"),
    ctrl_shortcut_while_composing=seq("a b C+v A+f SPACE"),
    # §4.16 the ` menu
    menu_open_and_leave=seq("` ` ` DOWN DOWN ESC a SPACE"),
    menu_symbols=seq("` m 1 1 1 ESC"),
    menu_navigation=seq("` m RIGHT RIGHT LEFT END HOME PGDN PGUP 2 BACK 3 1 ESC"),
    menu_settings_launch=seq("` m 6"),
    menu_toggles=seq("` m 5 1 a SPACE"),
    menu_emoji=seq("` e 1 1"),
    backtick_symbols=seq("` , SPACE ` [ ] SPACE ` ' SPACE"),
    unicode_input=seq("` u 4 e 0 0 SPACE ` u SPACE ` u 1 1 0 0 0 0 0 SPACE ESC ` SPACE"),
    # §4.17 numpad
    numpad=seq("NUM1 NUM. a NUM2 o o NUM+ NUM/"),
    # §4.12 smart select: after 器, picking 入 twice moves it to the front
    smart_select=seq("o o SPACE a ' o o SPACE a ' o o SPACE a SPACE b SPACE a SPACE"),
    smart_select_decays=seq("o o SPACE a SPACE wait:8640000 o o SPACE a SPACE"),
    # §1.5 / §4.15 language bar, mode icon, menus, keyboard on/off
    buttons=seq(CMD(1), "a SPACE", CMD(1), CMD(2), "a SPACE", CMD(2), CMD(4), CMD(4, 1),
                MENU("windows-mode-icon"), MENU("settings"), MENU("switch-lang")),
    settings_and_links=seq(CMD(3), CMD(5), CMD(6), CMD(8), CMD(9), CMD(10), CMD(11), CMD(12)),
    keyboard_off_on=seq("a", KEYBOARD(False), "a SPACE", KEYBOARD(True), "a SPACE"),
    composition_terminated=seq("a o", TERMINATED(True), "a", TERMINATED(False), "SPACE",
                               "a", KILL_FOCUS, "SPACE"),
    keyboard_closed_at_start=(seq("a SPACE", KEYBOARD(True), "a SPACE"), False),
)

# --- option variants (§3) ----------------------------------------------------

AUTO_COMMIT = scenarios(
    commits_and_skips_space=seq("b t SPACE a SPACE"),
    space_after_grace=seq("b t wait:1.5 SPACE a SPACE"),
    other_key_clears_grace=seq("b t a SPACE SPACE"),
    shift_space_not_skipped=seq("b t S+SPACE"),
    wildcard_single_match=seq("b * SPACE"),
)

PHRASE = scenarios(
    phrase_select_keys=seq("a SPACE ' a SPACE SPACE"),
    phrase_then_root=seq("a SPACE o o SPACE"),
    phrase_escape=seq("a SPACE ESC a SPACE"),
    phrase_paging=seq("a SPACE PGDN RIGHT SPACE"),
    phrase_numpad_and_backtick=seq("a SPACE NUM1 a SPACE ` m ESC"),
    phrase_dayi_symbol=seq("a SPACE = , SPACE"),
)

DAYI4 = scenarios(
    four_roots=seq("a a a a SPACE o o o SPACE"),
    select_keys=seq("a ' a [ a ]"),
    homophone=seq("a ` SPACE ESC"),
    homophone_select=seq("a ` ' a ` DOWN SPACE"),
    menu=seq("` ` ` ESC"),
)

THDAYI = scenarios(
    roots=seq("a SPACE a a a a SPACE"),
    dayi_symbols=seq("= , SPACE = SPACE"),
)

NO_DIRECT_SHOW = scenarios(
    space_opens_candidates=seq("a SPACE SPACE a SPACE '"),
    down_opens_candidates=seq("a DOWN DOWN SPACE"),
    full_code_shows=seq("a a a SPACE"),
)

SYMBOL_OPTIONS = scenarios(
    full_shape_symbols=seq("S+, SPACE S+. ' S+1 S+1 SPACE"),
    easy_symbols=seq("S+a S+b SPACE"),
    small_letters=seq("S+q S+x"),
)

REVERSE_LOOKUP = scenarios(
    lookup_after_commit=seq("a SPACE o o SPACE a *"),
    lookup_wildcard=seq("a * SPACE"),
)

QUOTE_SYMBOL_LEAD = scenarios(
    quote_lead=seq("' , SPACE ' BACK = SPACE"),
)

LEFT_SHIFT_ONLY = scenarios(
    sides=seq("R+SHIFT a SPACE SHIFT a SPACE SHIFT"),
)

ENGLISH_FULL_START = scenarios(
    starts_english_full=seq("a b S+a SPACE", CMD(1), "a SPACE"),
)

SOUND = scenarios(
    beeps=seq("b l SPACE ESC b l ENTER"),
)

VERTICAL = scenarios(
    nine_per_page=seq("a PGDN DOWN DOWN SPACE o * PGDN '"),
)

PAGE_WITH_SPACE = scenarios(
    space_pages=seq("a SPACE SPACE ENTER"),
)

NO_SMART_SELECT = scenarios(
    order_stays=seq("o o SPACE a ' o o SPACE a ' o o SPACE a SPACE"),
)

# --- 酷倉 (checj): same CinBase core, 1234567890 selection keys, up to 5 roots ---

CHECJ_DEFAULT = scenarios(
    commit_space=seq("a SPACE a b SPACE h q i SPACE o n f SPACE"),
    select_digits=seq("a 2 j j 3 j j 5 j j 0"),
    five_roots=seq("y r m m r SPACE m m m m m m SPACE"),
    dead_prefix_restart=seq("z z z z a SPACE"),
    not_found=seq("x x x x SPACE ESC"),
    zx_symbols=seq("z x a b SPACE"),
    backspace_escape=seq("y r m BACK BACK SPACE a b ESC a SPACE"),
    paging=seq("j PGDN PGUP RIGHT RIGHT SPACE j DOWN UP END SPACE"),
    wildcard=seq("a * SPACE * b SPACE y * r SPACE"),
    homophone_off=seq("o n f ` SPACE"),
    punctuation=seq("S+, S+. S+/ S+1 , . ;"),
    shift_toggle=seq("SHIFT a b SPACE SHIFT a SPACE"),
    full_shape=seq(SHIFT_SPACE, "a SPACE , SPACE", SHIFT_SPACE),
    ctrl_symbols=seq("C+; SPACE C+, C+, ENTER"),
    ctrl_shortcut_while_composing=seq("a b C+v SPACE"),
    menu=seq("` m 1 1 1 ESC ` u 4 e 0 0 SPACE"),
    numpad=seq("NUM1 a NUM2 o n f NUM+"),
    smart_select=seq("h q i SPACE j j 2 h q i SPACE j j 2 h q i SPACE j j SPACE"),
    buttons=seq(CMD(1), "a SPACE", CMD(1), CMD(2), "a SPACE", CMD(2), CMD(4), CMD(4, 1),
                MENU("windows-mode-icon"), MENU("settings")),
    settings_and_links=seq(CMD(3), CMD(5), CMD(6)),
    keyboard_off_on=seq("a", KEYBOARD(False), "a SPACE", KEYBOARD(True), "a SPACE"),
    composition_terminated=seq("o n", TERMINATED(True), "a", KILL_FOCUS, "SPACE"),
)

CHECJ_OPTIONS = scenarios(
    homophone=seq("o n f ` SPACE o n f ` DOWN SPACE"),
    reverse_lookup=seq("a SPACE h q i SPACE a * SPACE"),
    phrase=seq("o n f SPACE 1 a SPACE ESC"),
    autocommit=seq("x SPACE y r m m r SPACE a"),
)

SUITES = {
    "checj_default": {"ime": "checj", "scenarios": CHECJ_DEFAULT},
    "checj_options": {"ime": "checj",
                      "config": {"homophoneQuery": True, "imeReverseLookup": True, "selRCinType": 19,
                                 "showPhrase": True, "autoCommitSingleCandidate": True},
                      "scenarios": CHECJ_OPTIONS},
    "checj_mscj3_wildcard_z": {"ime": "checj", "config": {"selCinType": 1, "selWildcardType": 0},
                               "scenarios": scenarios(
                                   typing=seq("a SPACE h q i SPACE y r m m r SPACE"),
                                   wildcard_z=seq("a z SPACE z b SPACE"),
                               )},
    "dayi3_default": {"ime": "chedayi", "scenarios": DEFAULT},
    "dayi3_autocommit": {"ime": "chedayi", "config": {"autoCommitSingleCandidate": True},
                         "scenarios": AUTO_COMMIT},
    "dayi3_phrase": {"ime": "chedayi", "config": {"showPhrase": True}, "scenarios": PHRASE},
    "dayi4_homophone": {"ime": "chedayi", "config": {"selCinType": 1, "homophoneQuery": True},
                        "scenarios": DAYI4},
    "thdayi": {"ime": "chedayi", "config": {"selCinType": 0}, "scenarios": THDAYI},
    "dayi3_no_direct_show": {"ime": "chedayi", "config": {"directShowCand": False},
                             "scenarios": NO_DIRECT_SHOW},
    "dayi3_symbol_options": {"ime": "chedayi",
                             "config": {"fullShapeSymbols": True, "easySymbolsWithShift": True,
                                        "outputSmallLetterWithShift": True},
                             "scenarios": SYMBOL_OPTIONS},
    "dayi3_reverse_lookup": {"ime": "chedayi", "config": {"imeReverseLookup": True},
                             "scenarios": REVERSE_LOOKUP},
    "dayi3_quote_symbol_lead": {"ime": "chedayi", "config": {"selDayiSymbolCharType": 1},
                                "scenarios": QUOTE_SYMBOL_LEAD},
    "dayi3_left_shift_only": {"ime": "chedayi", "config": {"switchLangWithWhichShift": 1},
                              "scenarios": LEFT_SHIFT_ONLY},
    "dayi3_english_full_start": {"ime": "chedayi",
                                 "config": {"defaultEnglish": True, "defaultFullSpace": True},
                                 "scenarios": ENGLISH_FULL_START},
    "dayi3_sound": {"ime": "chedayi", "config": {"playSoundWhenNonCand": True}, "scenarios": SOUND},
    "dayi3_vertical": {"ime": "chedayi", "config": {"candidateLayout": "vertical", "candPerPage": 9},
                       "scenarios": VERTICAL},
    "dayi3_page_with_space": {"ime": "chedayi", "config": {"switchPageWithSpace": True},
                              "scenarios": PAGE_WITH_SPACE},
    "dayi3_no_smart_select": {"ime": "chedayi", "config": {"intelligentSelect": False},
                              "scenarios": NO_SMART_SELECT},
}


# --- 新酷音 (chewing): the libchewing frontend, input_methods/chewing ----------
#
# Standard layout keys: 你 s u 3, 好 c l 3, 中 5 j / SPACE, 文 j p 6, 測 h k 4,
# 試 g 4, 台 w 9 6, 灣 j 0 SPACE, 我 j i 3, 是 g 4, 大 2 8 4, 學 v m , 6,
# 的 2 k 7, 生 g / SPACE. Tones: SPACE 6 3 4 7. Shipped settings: Space opens
# the candidates (spaceKeyAction 1), 1234567890 select, Shift+letter types
# easy symbols, Shift taps switch Chinese/English.

SENTENCE = "j i 3 g 4 w 9 6 j 0 SPACE 2 8 4 v m , 6 2 k 7 v m , 6 g / SPACE"

CHEWING_DEFAULT = scenarios(
    # typing, the composition and committing
    type_and_enter=seq("s u 3 c l 3 ENTER"),
    bopomofo_only=seq("s u", "ENTER BACK BACK s ESC"),
    tones=seq("u SPACE u 6 u 3 u 4 u 7 ENTER"),
    long_sentence=seq(SENTENCE, "ENTER"),
    sentence_overflow=seq(SENTENCE, SENTENCE, SENTENCE, "ENTER"),
    # candidates: Space / Down open them, digits and Enter choose
    select_with_space=seq("s u 3 c l 3 SPACE 2 ENTER"),
    select_with_down=seq("s u 3 DOWN DOWN 3 ENTER"),
    candidate_cursor=seq("u 4 DOWN RIGHT RIGHT LEFT LEFT LEFT END HOME RIGHT ENTER ENTER"),
    candidate_rows=seq("u 4 DOWN DOWN DOWN UP UP UP UP ESC ESC"),
    candidate_pages=seq("u 4 DOWN PGDN PGDN PGUP SPACE SPACE SPACE ENTER ENTER"),
    phrase_candidates=seq("h k 4 g 4 HOME DOWN DOWN 1 ENTER"),
    # editing
    cursor_and_delete=seq("s u 3 c l 3 h k 4 LEFT BACK HOME DEL RIGHT END BACK ENTER"),
    escape_clears=seq("s u 3 c l 3 ESC s u ESC ENTER"),
    keys_without_composition=seq("ENTER BACK ESC SPACE DEL LEFT TAB UP PGDN HOME"),
    tab_in_composition=seq("h k 4 g 4 TAB ENTER"),
    # punctuation and symbols
    punctuation=seq(", . ; / - = [ ] \\ ' ENTER"),
    shift_symbols=seq("S+, S+. S+/ S+1 S+; S+' S+[ S+- ENTER"),
    easy_symbols=seq("S+a S+b S+z ENTER S+q ESC"),
    backtick_menu=seq("` ENTER ENTER ESC ` 1 ESC ESC"),
    backtick_navigation=seq("` DOWN RIGHT PGDN 2 BACK ESC ESC"),
    numpad=seq("NUM1 s u 3 NUM2 NUM+ NUM. ENTER"),
    # Shift taps switch Chinese/English; a slow tap or Ctrl+Shift does not
    shift_toggle=seq("SHIFT a b SPACE SHIFT s u 3 ENTER"),
    shift_toggle_right=seq("R+SHIFT a R+SHIFT s u 3 ENTER"),
    shift_with_bopomofo=seq("s u SHIFT ENTER SHIFT s u 3 ENTER"),
    shift_with_composition=seq("s u 3 c SHIFT a ENTER SHIFT ENTER"),
    shift_moves_nothing=seq("s u 3 c l 3 SHIFT R+SHIFT ENTER"),
    ctrl_shift=seq("C+SHIFT a SPACE ESC"),
    # Ctrl and Alt
    ctrl_passthrough=seq("C+a C+c A+a s u 3 C+c A+f C+SPACE ENTER"),
    ctrl_number_adds_phrase=seq("s u 3 c l 3 C+2 ENTER s u 3 c l 3 HOME DOWN ESC ESC"),
    ctrl_delete_phrase=seq("h k 4 g 4 C+2 ESC h k 4 g 4 HOME DOWN C+DEL ESC ESC h k 4 g 4 HOME DOWN C+DEL ESC ESC"),
    ctrl_page_frequency=seq("h k 4 g 4 C+2 ESC h k 4 g 4 HOME DOWN C+PGUP C+PGDN ESC ESC"),
    ctrl_page_builtin=seq("s u 3 DOWN C+PGDN C+PGUP C+DEL ESC ESC"),
    # learning: the phrase chosen once comes first next time
    learning=seq("u 4 DOWN 3 ENTER u 4 ENTER h k 4 g 4 HOME DOWN 2 ENTER h k 4 g 4 ENTER"),
    # full shape (Shift+Space), numbers and letters in English mode
    full_shape=seq(SHIFT_SPACE, "a SPACE , 1 s u 3 ENTER", SHIFT_SPACE, "a SPACE"),
    english_full_shape=seq("SHIFT", SHIFT_SPACE, "a B 1 SPACE , S+/", SHIFT_SPACE, "a SHIFT"),
    caps_lock_key=seq("CAPS a s u 3 CAPS ENTER"),
    # language bar buttons, the mode icon, menus, settings and links
    buttons=seq(CMD(1), "a s u 3 ENTER", CMD(1), CMD(2), "a SPACE", CMD(2), CMD(4), "a", CMD(4),
                CMD(4, 1), CMD(1, 1), CMD(1, 2), CMD(2, 2), CMD(2, 1)),
    menus=seq(MENU("settings"), MENU("windows-mode-icon"), MENU("switch-lang"), MENU("x")),
    settings_and_links=seq(CMD(3), CMD(19), CMD(6), CMD(7), CMD(8), CMD(9), CMD(13), CMD(14),
                           CMD(15), CMD(16), CMD(17), CMD(18), CMD(99)),
    switch_lang_with_bopomofo=seq("s u", CMD(1), "ENTER", CMD(1), "s u", CMD(4), "a ENTER"),
    # keyboard closed and reopened, the app ending the composition, focus
    keyboard_off_on=seq("s u 3", KEYBOARD(False), "a ENTER", MENU("settings"), CMD(4), KEYBOARD(True), "s u 3 ENTER"),
    keyboard_closed_at_start=(seq("a s", CMD(4), KEYBOARD(True), "s u 3 ENTER"), False),
    composition_terminated=seq("s u 3 c", TERMINATED(True), "s u 3 DOWN", TERMINATED(True),
                               "s u 3", TERMINATED(False), "ENTER"),
    kill_focus=seq("s u 3 c", KILL_FOCUS, "s u 3 DOWN", KILL_FOCUS, "s u", KILL_FOCUS, "ENTER"),
    preserved_unknown=seq({"request": "onPreservedKey", "guid": "{00000000-0000-0000-0000-000000000000}"}, "a"),
    waits=seq("s u 3 wait:4 c l 3 wait:4 ENTER"),
    # requests the Python backend fails ({"success": false}) must fail here too
    malformed_requests=seq("s u", {"request": "filterKeyDown"}, {"request": "onKeyDown", "keyCode": 65},
                           {"request": "onCommand", "id": 1}, {"request": "onMenu"},
                           {"request": "onKeyboardStatusChanged"}, {"request": "onPreservedKey"},
                           {"request": "noSuchMethod"}, {"request": "ping"}, "3 ENTER"),
)


def _chewing_layout_suite(layout):
    """Typing the same keys on another keyboard layout"""
    return {"ime": "chewing", "config": {"keyboardLayout": layout}, "scenarios": scenarios(
        letters=seq("a s d f SPACE ENTER q w e r 3 ENTER z x c v 4 ENTER"),
        digits_and_symbols=seq("1 2 3 4 5 6 7 8 9 0 - = ENTER [ ] \\ ; ' , . / ENTER ESC"),
        words=seq("j i 3 g 4 DOWN 2 ENTER k u 6 l 4 SPACE ENTER h k j l SPACE ENTER"),
        upper_row=seq("y u i o p SPACE h j k l ; 7 ENTER n m , . / 6 ENTER"),
        shift_symbols=seq("S+[ S+' S+= S+a ENTER"),
    )}


CHEWING_SPACE_OUTPUTS_SPACE = scenarios(
    space_is_tone=seq("s u SPACE s u 3 SPACE SPACE ENTER"),
    space_moves_cursor=seq("u 4 DOWN SPACE SPACE SPACE SPACE SPACE SPACE SPACE SPACE SPACE SPACE SPACE ENTER ENTER"),
    space_without_composition=seq("SPACE a SPACE"),
)

CHEWING_SELECTION_OPTIONS = scenarios(
    asdf_keys=seq("u 4 DOWN s ENTER u 4 DOWN DOWN RIGHT ENTER ENTER"),
    page_keys=seq("u 4 DOWN LEFT RIGHT UP DOWN DOWN UP HOME END ENTER ENTER"),
    five_per_page=seq("u 4 DOWN PGDN PGDN PGUP f ENTER"),
)

CHEWING_SYMBOL_OPTIONS = scenarios(
    half_symbols=seq(", . ; = [ ] ' \\ s u 3 , ENTER"),
    shift_letters_upper=seq("S+a S+b s u 3 S+c ENTER"),
    shift_symbols=seq("S+, S+1 S+/ ENTER"),
)

CHEWING_SHIFT_LOWER = scenarios(
    shift_letters_lower=seq("S+a S+b s u 3 S+c ENTER"),
)

CHEWING_CTRL_SYMBOLS = scenarios(
    ctrl_letters=seq("C+a C+b C+z s u 3 C+c ENTER C+1"),
    ctrl_in_english=seq("SHIFT C+a SHIFT"),
)

CHEWING_EDIT_OPTIONS = scenarios(
    esc_keeps_buffer=seq("s u 3 c l 3 ESC ENTER s u ESC ENTER"),
    phrase_backward=seq("s u 3 c l 3 C+2 ENTER s u 3 c l 3 h k 4 g 4 C+2 ESC ESC"),
    no_advance=seq("s u 3 c l 3 h k 4 HOME DOWN 2 DOWN 2 DOWN 2 ENTER"),
    rearward=seq("h k 4 g 4 DOWN DOWN DOWN ESC h k 4 g 4 END DOWN 1 ENTER"),
    no_learning=seq("u 4 DOWN 3 ENTER u 4 ENTER u 4 DOWN 3 ENTER u 4 ENTER"),
)

CHEWING_SHIFT_OPTIONS = scenarios(
    shift_side=seq("SHIFT a R+SHIFT a SHIFT a R+SHIFT ENTER"),
    shift_in_composition=seq("s u 3 c l 3 SHIFT R+SHIFT ENTER"),
)

CHEWING_SHIFT_MOVES_CURSOR = scenarios(
    shift_moves_cursor=seq("s u 3 c l 3 h k 4 SHIFT SHIFT R+SHIFT ENTER SHIFT a"),
    with_bopomofo=seq("s u 3 c SHIFT R+SHIFT ENTER"),
)

CHEWING_NO_SHIFT_SWITCH = scenarios(
    shift_does_nothing=seq("SHIFT a s u 3 ENTER", MENU("settings")),
)

CHEWING_STARTUP_OPTIONS = scenarios(
    english_full_start=seq("a 1 ,", CMD(1), "s u 3 ENTER", MENU("windows-mode-icon"), SHIFT_SPACE, "a"),
    reactivated=seq(CMD(2), "a"),
)

CHEWING_DISABLED_START = scenarios(
    disabled=seq("s u 3", CMD(4), "s u 3 ENTER", KEYBOARD(False), CMD(4, 1), CMD(4)),
)

CHEWING_SHIFT_SPACE_OFF = scenarios(
    shift_space=seq(SHIFT_SPACE, "a", CMD(2), "a", MENU("settings")),
    caps_off=seq("CAPS a ENTER"),
)

CHEWING_LAYOUT_OPTIONS = scenarios(
    vertical_rows=seq("u 4 DOWN DOWN DOWN UP ENTER ENTER h k 4 g 4 HOME DOWN DOWN UP ENTER ENTER"),
    narrow_rows=seq("j i 3 DOWN DOWN DOWN DOWN UP UP ENTER ENTER"),
)

CHEWING_NARROW = scenarios(
    narrow_rows=seq("u 4 DOWN DOWN DOWN DOWN UP UP UP ENTER ENTER h k 4 g 4 HOME DOWN DOWN UP ENTER ENTER"),
    long_phrases=seq("w 9 6 j 0 SPACE 2 8 4 v m , 6 HOME DOWN DOWN DOWN UP ENTER ENTER"),
)

# settings written badly: strings, floats, nulls, out of range, unknown and
# retired keys -- normalizeValues() must turn them into the same values
CHEWING_ODD_CONFIG = {
    "candPerPage": "7", "keyboardLayout": 99, "selKeyType": 1.0, "fontSize": None,
    "easySymbolsWithShift": "off", "escCleanAllBuf": 0, "addPhraseForward": 2,
    "candidatePerRow": True, "candidateMaxWidth": 300, "candidateTheme": "Graphite",
    "candidateColors": {"panelBackground": "#FFFFFF"}, "candidateStyle": {"contentMargin": 3, "textMargin": "x", "borderRadius": True},
    "candidateKeyStyle": "keycap", "candPerRow": 4, "unknownSetting": [1, 2], "upDownAction": "1",
    "candidateOpacity": 10, "candidateLayout": 5,
}

CHEWING_ODD = scenarios(
    typing=seq("u 4 DOWN DOWN UP s ENTER S+a ENTER", MENU("settings")),
)

# the user's own symbols.dat (with blank lines: removed on load) and swkb.dat.
# (Files in the ANSI code page are converted too, but that depends on the
# machine's code page: covered by the cargo tests, not by a golden file.)
CHEWING_USER_FILES = {
    "symbols.dat": "…=…‥\n\n數學=＋－×÷\n\r\n箭頭=←↑\n",
    "swkb.dat": "A \u2606\nB \u2605\n",
}

CHEWING_USER_DATA = scenarios(
    user_symbols=seq("` ENTER ENTER ` 2 1 ` 3 2 ENTER"),
    user_easy_symbols=seq("S+a S+b ENTER"),
)


def _legacy_user_dictionary():
    """chewing.sqlite3 of the old C libchewing (userphrase_v1): 測試 (frequent),
    the user's own 策事 (same reading, not in the dictionary) and a phrase that
    is not valid UTF-8 (dropped by the conversion)."""
    import base64
    import sqlite3
    conn = sqlite3.connect(":memory:")
    columns = ", ".join("phone_%d INTEGER" % i for i in range(11))
    conn.execute("CREATE TABLE config_v1 (id INTEGER, value INTEGER, PRIMARY KEY (id))")
    conn.execute("CREATE TABLE userphrase_v1 (time INTEGER, user_freq INTEGER, max_freq INTEGER, "
                 "orig_freq INTEGER, length INTEGER, %s, phrase TEXT, PRIMARY KEY (%s, phrase))"
                 % (columns, ", ".join("phone_%d" % i for i in range(11))))
    rows = [(186613, 9318, 9318, 9318, 2, 10268, 8708, "測試"),
            (186613, 9900, 9900, 1, 2, 10268, 8708, "策事"),
            (186613, 5, 5, 5, 2, 10268, 8708, b"\xff\xfe".decode("latin-1"))]
    for row in rows:
        conn.execute("INSERT INTO userphrase_v1 (time, user_freq, max_freq, orig_freq, length, phone_0, "
                     "phone_1, phone_2, phone_3, phone_4, phone_5, phone_6, phone_7, phone_8, phone_9, "
                     "phone_10, phrase) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, 0, 0, 0, ?)", row)
    # the invalid phrase as raw bytes, like a file the old version wrote
    conn.execute("UPDATE userphrase_v1 SET phrase = CAST(X'FFFE' AS TEXT) WHERE user_freq = 5")
    conn.commit()
    data = conn.serialize()
    conn.close()
    return {"base64": base64.b64encode(data).decode("ascii")}


CHEWING_LEGACY_DICT = scenarios(
    converted_phrases=seq("h k 4 g 4 HOME DOWN ESC ESC h k 4 g 4 HOME DOWN C+DEL ESC ESC"),
    deleted_stays_deleted=seq("h k 4 g 4 HOME DOWN RIGHT C+DEL ESC ESC h k 4 g 4 ENTER"),
)

# a chewing.sqlite3 that is not a dictionary: the conversion fails, the backend
# falls back to an in-memory dictionary and says so once
CHEWING_BROKEN_DICT = scenarios(
    fallback=seq("s u 3 c l 3 C+2 ENTER"),
    warned_once=seq("s u 3 ENTER"),
)

CHEWING_SUITES = {
    "chewing_default": {"ime": "chewing", "scenarios": CHEWING_DEFAULT},
    "chewing_hsu": _chewing_layout_suite(1),
    "chewing_ibm": _chewing_layout_suite(2),
    "chewing_gin_yieh": _chewing_layout_suite(3),
    "chewing_et41": _chewing_layout_suite(4),
    "chewing_et26": _chewing_layout_suite(5),
    "chewing_dvorak": _chewing_layout_suite(6),
    "chewing_dvorak_hsu": _chewing_layout_suite(7),
    "chewing_dachen26": _chewing_layout_suite(8),
    "chewing_hanyu_pinyin": _chewing_layout_suite(9),
    "chewing_thl_pinyin": _chewing_layout_suite(10),
    "chewing_mps2_pinyin": _chewing_layout_suite(11),
    "chewing_carpalx": _chewing_layout_suite(12),
    "chewing_space_outputs_space": {"ime": "chewing", "config": {"spaceKeyAction": 0, "spaceKeyCandidatesAction": 1},
                                    "scenarios": CHEWING_SPACE_OUTPUTS_SPACE},
    "chewing_selection_options": {"ime": "chewing",
                                  "config": {"selKeyType": 1, "candPerPage": 5, "leftRightAction": 1, "upDownAction": 1},
                                  "scenarios": CHEWING_SELECTION_OPTIONS},
    "chewing_symbol_options": {"ime": "chewing",
                               "config": {"fullShapeSymbols": False, "easySymbolsWithShift": False,
                                          "fullShapeSymbolsWithShift": False},
                               "scenarios": CHEWING_SYMBOL_OPTIONS},
    "chewing_shift_lower": {"ime": "chewing", "config": {"easySymbolsWithShift": False, "upperCaseWithShift": False},
                            "scenarios": CHEWING_SHIFT_LOWER},
    "chewing_ctrl_symbols": {"ime": "chewing", "config": {"easySymbolsWithCtrl": True},
                             "scenarios": CHEWING_CTRL_SYMBOLS},
    "chewing_edit_options": {"ime": "chewing",
                             "config": {"escCleanAllBuf": False, "addPhraseForward": False,
                                        "advanceAfterSelection": False, "phraseChoiceRearward": True,
                                        "autoLearn": False},
                             "scenarios": CHEWING_EDIT_OPTIONS},
    "chewing_left_shift_only": {"ime": "chewing", "config": {"switchLangWithWhichShift": 1},
                                "scenarios": CHEWING_SHIFT_OPTIONS},
    "chewing_right_shift_only": {"ime": "chewing", "config": {"switchLangWithWhichShift": 2},
                                 "scenarios": CHEWING_SHIFT_OPTIONS},
    "chewing_shift_moves_cursor": {"ime": "chewing", "config": {"shiftMoveCursor": 1},
                                   "scenarios": CHEWING_SHIFT_MOVES_CURSOR},
    "chewing_no_shift_switch": {"ime": "chewing", "config": {"switchLangWithShift": False},
                                "scenarios": CHEWING_NO_SHIFT_SWITCH},
    "chewing_english_full_start": {"ime": "chewing", "config": {"defaultEnglish": True, "defaultFullSpace": True},
                                   "scenarios": CHEWING_STARTUP_OPTIONS},
    "chewing_disabled_on_startup": {"ime": "chewing", "config": {"disableOnStartup": True},
                                    "scenarios": CHEWING_DISABLED_START},
    "chewing_shift_space_off": {"ime": "chewing", "config": {"enableShiftSpace": False, "enableCapsLock": False},
                                "scenarios": CHEWING_SHIFT_SPACE_OFF},
    "chewing_vertical": {"ime": "chewing", "config": {"candidateLayout": "vertical", "candPerPage": 10},
                         "scenarios": CHEWING_LAYOUT_OPTIONS},
    "chewing_narrow_window": {"ime": "chewing",
                              "config": {"candidatePerRow": 10, "candidateMaxWidth": 160, "fontSize": 20,
                                         "candidateStyle": {"contentMargin": 10, "textMargin": 8}},
                              "scenarios": CHEWING_NARROW},
    "chewing_odd_config": {"ime": "chewing", "config": CHEWING_ODD_CONFIG, "scenarios": CHEWING_ODD},
    "chewing_user_files": {"ime": "chewing", "files": CHEWING_USER_FILES, "scenarios": CHEWING_USER_DATA},
    "chewing_legacy_dictionary": {"ime": "chewing", "files": {"chewing.sqlite3": _legacy_user_dictionary()},
                                  "scenarios": CHEWING_LEGACY_DICT},
    "chewing_broken_dictionary": {"ime": "chewing", "files": {"chewing.sqlite3": "not a database\n"},
                                  "scenarios": CHEWING_BROKEN_DICT},
}
SUITES.update(CHEWING_SUITES)


def golden_path(name):
    return os.path.join(GOLDEN_DIR, name + ".jsonl")


def main(argv):
    sys.path.insert(0, HERE)
    import driver
    if len(argv) < 2 or argv[1] not in ("record", "check"):
        print("usage: suites.py record|check [--backend CMD] [suite ...]")
        return 2
    args = argv[2:]
    command = driver.REFERENCE
    if "--backend" in args:
        i = args.index("--backend")
        import shlex
        command = shlex.split(args[i + 1], posix=False)
        del args[i:i + 2]
    names = args or list(SUITES)
    failed = 0
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    for name in names:
        transcript = driver.run_suite(SUITES[name], command)
        if argv[1] == "record":
            driver.dump(transcript, golden_path(name))
            print("%-28s %5d replies recorded" % (name, len(transcript)))
        else:
            problems = driver.compare(driver.load(golden_path(name)), transcript)
            failed += bool(problems)
            print("%-28s %5d replies %s" % (name, len(transcript), "OK" if not problems else "DIFFERENT"))
            for p in problems[:5]:
                print("    " + p)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
