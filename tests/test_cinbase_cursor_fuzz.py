"""Randomized regression test for the candidate cursor.

After every key, the cursor the backend last sent must point inside the
candidate list it last sent, which is what the C++ window shows. The C++ side
does not crash on a cursor past the end: CandidateWindow::setCurrentSel() resets
it to 0. But then the highlighted candidate and the one Space/Enter commits
differ, and before the CinBase audit the backend also raised on the next key
(stale page after paging, Ctrl+symbol keeping the old cursor, ...).

The key sequences are generated from a fixed seed, so every run sends the same
keys. Keys are weighted towards paging and cursor movement (with mostly letters,
compositions rarely reach a second page). On the code before the audit
(584a419) this finds several cursor mismatches and IndexErrors.
"""

import random
import unittest

import cinbase_harness as h

SEED = 20260925
SEQUENCES = 1000

LETTERS = list("abcdefghijklmnopqrstuvwxyz")
NAV = ["PGDN", "PGUP", "DOWN", "UP", "LEFT", "RIGHT", "HOME", "END"]
KEYS = (LETTERS + list("0123456789") + list(",./;'[]-=") + NAV * 6
        + ["SPACE"] * 5 + ["ENTER", "ESC", "BACK", "BACK", "`", "`", "`"]
        + [("'", "C"), (";", "C"), (",", "C"), ("[", "C")] * 3
        + [("A", "S"), ("1", "S"), ("*", "S")])
CONFIGS = [
    dict(directShowCand=True, **h.MODERN_LAYOUT),
    dict(directShowCand=False),
    dict(directShowCand=True, showPhrase=True, **h.MODERN_LAYOUT),
    dict(directShowCand=True, compositionBufferMode=True),
    dict(directShowCand=True, homophoneQuery=True, supportWildcard=True),
    dict(directShowCand=False, showPhrase=True, candidateModernStyle=False),
]


def setUpModule():
    global _appdata, _real_play
    _appdata = h.IsolatedAppData()
    _real_play = h.cinbase.winsound.PlaySound
    h.cinbase.winsound.PlaySound = lambda *a, **k: None


def tearDownModule():
    h.cinbase.winsound.PlaySound = _real_play
    _appdata.close()


@h.requires_tables
class CandidateCursorFuzzTests(unittest.TestCase):
    def test_cursor_stays_inside_the_candidate_list(self):
        rng = random.Random(SEED)
        problems = []
        for _ in range(SEQUENCES):
            ime = rng.choice(("chedayi", "checj"))
            cfg = rng.choice(CONFIGS)
            service = h.make_service(ime, **cfg)
            keys = []
            for _ in range(rng.randint(5, 40)):
                key = rng.choice(KEYS)
                keys.append(key)
                try:
                    if isinstance(key, tuple):
                        h.press(service, key[0], shift="S" in key[1], ctrl="C" in key[1])
                    else:
                        h.press(service, key)
                except h.BackendError as error:
                    problems.append("%s %s raised %s after %r" % (
                        ime, cfg, str(error).strip().splitlines()[-1], keys))
                    break
                candidates, cursor = service.candidateList or [], service.candidateCursor
                if candidates and not 0 <= cursor < len(candidates):
                    problems.append("%s %s cursor %d with %d candidates after %r" % (
                        ime, cfg, cursor, len(candidates), keys))
                    break
        self.assertEqual(problems, [], "\n" + "\n".join(problems[:5]))


if __name__ == "__main__":
    unittest.main()
