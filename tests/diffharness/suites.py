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

SUITES = {
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
