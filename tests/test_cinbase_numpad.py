"""Number pad keys (NumLock on) while composing.

Without a composition the number pad always types digits (filterKeyDown passes
it to the application). During a composition it used to be swallowed, so the
key did nothing at all. Now the highlighted candidate is committed first and
then the key's character; the main-row digits keep their meaning (selection
keys in 酷倉, roots in 大易).
"""

import unittest

import cinbase_harness as h

VK_NUMLOCK = 0x90
NUMPAD_VK = {str(d): 0x60 + d for d in range(10)}
NUMPAD_VK.update({"*": 0x6A, "+": 0x6B, "-": 0x6D, ".": 0x6E, "/": 0x6F})


def setUpModule():
    global _appdata, _real_play
    _appdata = h.IsolatedAppData()
    _real_play = h.cinbase.winsound.PlaySound
    h.cinbase.winsound.PlaySound = lambda *a, **k: None


def tearDownModule():
    h.cinbase.winsound.PlaySound = _real_play
    _appdata.close()


def numpad(service, char):
    """Press a number pad key like the C++ side does; return (filterKeyDown, onKeyDown reply)."""
    vk = NUMPAD_VK[char]
    down = {"charCode": ord(char), "keyCode": vk, "repeatCount": 1, "scanCode": 0, "isExtended": False,
            "keyStates": {str(VK_NUMLOCK): 0x01, str(vk): 0x80}}
    up = dict(down, keyStates={str(VK_NUMLOCK): 0x01})
    filtered = h._send(service, "filterKeyDown", down, "numpad " + char).get("return")
    reply = h._send(service, "onKeyDown", down, "numpad " + char) if filtered else {}
    if h._send(service, "filterKeyUp", up, "numpad " + char).get("return"):
        h._send(service, "onKeyUp", up, "numpad " + char)
    return filtered, reply


@h.requires_tables
class NumpadWhileComposingTests(unittest.TestCase):
    def test_commits_the_highlighted_candidate_then_the_digit(self):
        for ime, roots in (("checj", ["h", "n"]), ("chedayi", ["x"])):
            with self.subTest(ime=ime):
                service = h.make_service(ime, directShowCand=True)
                h.type_keys(service, roots)
                first = service.candidateList[0]
                _, reply = numpad(service, "2")
                self.assertEqual(reply.get("commitString"), first + "2")
                self.assertEqual(service.compositionChar, "")

                service = h.make_service(ime, directShowCand=True)
                h.type_keys(service, roots + ["RIGHT"])
                second = service.candidateList[service.candidateCursor]
                _, reply = numpad(service, "7")
                self.assertEqual(reply.get("commitString"), second + "7")

    def test_main_row_digits_keep_their_meaning(self):
        service = h.make_service("checj", directShowCand=True)
        h.type_keys(service, ["h", "n"])
        second = service.candidateList[1]
        commits, _ = h.type_keys(service, ["2"])          # 酷倉: selection key
        self.assertEqual(commits, [second])
        service = h.make_service("chedayi", directShowCand=True)
        h.type_keys(service, ["x", "1"])                   # 大易: a root
        self.assertEqual(service.compositionChar, "x1")

    def test_candidate_window_not_shown_yet(self):
        # 直接顯示候選字 off: the first candidate as it would be listed
        service = h.make_service("checj", directShowCand=False)
        h.type_keys(service, ["h", "n"])
        # the window only shows the composition header, no candidates yet
        self.assertFalse(service.candidateList)
        expected = h.cinbase.CinBase.highlightedCandidate(service)
        self.assertTrue(expected)
        _, reply = numpad(service, "3")
        self.assertEqual(reply.get("commitString"), expected + "3")

    def test_roots_without_a_match_are_dropped(self):
        service = h.make_service("chedayi", directShowCand=True)
        h.type_keys(service, ["b", "l"])                  # "bl" starts no 大易 code
        _, reply = numpad(service, "5")
        self.assertEqual(reply.get("commitString"), "5")
        self.assertEqual(service.compositionChar, "")

    def test_number_pad_operators(self):
        for op in "+-./":
            with self.subTest(op=op):
                service = h.make_service("checj", directShowCand=True)
                h.type_keys(service, ["h", "n"])
                first = service.candidateList[0]
                _, reply = numpad(service, op)
                self.assertEqual(reply.get("commitString"), first + op)

    def test_number_pad_star_is_still_the_wildcard(self):
        service = h.make_service("checj", directShowCand=True, supportWildcard=True)
        service.selWildcardChar = "*"
        h.type_keys(service, ["h"])
        _, reply = numpad(service, "*")
        self.assertIsNone(reply.get("commitString"))
        self.assertEqual(service.compositionChar, "h*")
        self.assertTrue(service.candidateList)

    def test_wildcard_composition(self):
        service = h.make_service("checj", directShowCand=True, supportWildcard=True)
        service.selWildcardChar = "*"
        h.type_keys(service, ["h"])
        numpad(service, "*")
        first = service.candidateList[0]
        _, reply = numpad(service, "9")
        self.assertEqual(reply.get("commitString"), first + "9")

    def test_open_phrase_list_is_closed_and_the_key_passed_on(self):
        service = h.make_service("chedayi", showPhrase=True, directShowCand=True)
        commits, _ = h.type_keys(service, ["x", "SPACE"])
        self.assertTrue(service.phrasemode and service.candidateList)
        filtered, reply = numpad(service, "4")
        self.assertTrue(filtered)
        self.assertIs(reply.get("return"), False)          # the application types the digit
        self.assertIs(reply.get("showCandidates"), False)
        self.assertFalse(service.phrasemode)

    def test_composition_buffer_mode(self):
        service = h.make_service("chedayi", compositionBufferMode=True, directShowCand=True)
        h.type_keys(service, ["x"])
        first = service.candidateList[0]
        _, reply = numpad(service, "1")
        self.assertIsNone(reply.get("commitString"))       # still in the buffer
        self.assertEqual(service.compositionBufferString, first + "1")
        commits, _ = h.type_keys(service, ["ENTER"])
        self.assertEqual(commits, [first + "1"])

    def test_not_composing_passes_the_key_to_the_application(self):
        service = h.make_service("checj")
        filtered, _ = numpad(service, "5")
        self.assertFalse(filtered)

    def test_function_menu_is_unchanged(self):
        service = h.make_service("chedayi")
        for _ in range(3):
            h.press(service, "`")
            if "特殊符號" in (service.candidateList or []):
                break
        _, reply = numpad(service, "1")
        self.assertIsNone(reply.get("commitString"))
        self.assertTrue(service.showmenu)


if __name__ == "__main__":
    unittest.main()
