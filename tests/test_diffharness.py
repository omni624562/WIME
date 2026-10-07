"""The differential harness (tests/diffharness) itself: the Python reference
backend must answer the same requests the same way every run, otherwise
comparing another backend against it means nothing. Also checks the recorded
golden transcripts in tests/diffharness/golden still match the Python backend.

Each run starts the embedded Python backend with a temporary APPDATA, so the
user's real settings are never touched.
"""

import glob
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "diffharness")
sys.path.insert(0, HARNESS)

import driver  # noqa: E402
import keys    # noqa: E402

TABLES = os.path.join(HERE, os.pardir, "python", "cinbase", "json")
AVAILABLE = (os.path.exists(driver.PYTHON_EXE)
             and all(os.path.exists(os.path.join(TABLES, n)) for n in ("dayi4.json", "dayi3.json")))
requires_backend = unittest.skipUnless(
    AVAILABLE, "embedded Python or the generated cinbase/json tables are missing")


class KeyEventTests(unittest.TestCase):
    def test_letters_digits_and_symbols(self):
        a = keys.key_event("a")
        self.assertEqual((a["charCode"], a["keyCode"]), (ord("a"), ord("A")))
        self.assertEqual(a["keyStates"][str(ord("A"))], 0x80)
        up = keys.key_event("a", down=False)
        self.assertNotIn(str(ord("A")), up["keyStates"])
        self.assertEqual(keys.key_event("'")["keyCode"], 0xDE)
        self.assertEqual(keys.key_event("?")["keyStates"][str(keys.VK_SHIFT)], 0x80)

    def test_modifiers(self):
        big = keys.key_event("a", "S")
        self.assertEqual(big["charCode"], ord("A"))
        self.assertEqual(big["keyStates"][str(keys.VK_LSHIFT)], 0x80)
        self.assertEqual(keys.key_event("a", "C")["charCode"], 1)
        self.assertEqual(keys.key_event("a", "A")["charCode"], 0)

    def test_shift_alone_carries_its_side(self):
        left, right = keys.key_event("SHIFT"), keys.key_event("SHIFT", "R")
        self.assertEqual(left["scanCode"], keys.LEFT_SHIFT_SCAN)
        self.assertEqual(right["scanCode"], keys.RIGHT_SHIFT_SCAN)
        self.assertEqual(right["keyStates"][str(keys.VK_RSHIFT)], 0x80)
        released = keys.key_event("SHIFT", down=False)
        self.assertNotIn(str(keys.VK_SHIFT), released["keyStates"])


class CompareTests(unittest.TestCase):
    def record(self, reply):
        return {"scenario": "s", "step": "0:a", "method": "onKeyDown", "reply": reply}

    def test_identical_and_different(self):
        a = [self.record({"commitString": "人", "candidateList": ["人", "入"]})]
        self.assertEqual(driver.compare(a, a), [])
        b = [self.record({"commitString": "入", "candidateList": ["人", "入"]})]
        problems = driver.compare(a, b)
        self.assertEqual(len(problems), 1)
        self.assertIn("commitString", problems[0])
        self.assertTrue(driver.compare(a, a + a))

    def test_icon_paths_are_compared_by_name(self):
        reply = {"addButton": [{"icon": r"C:\PIME\python\cinbase\icons\chi.ico"}]}
        self.assertEqual(driver.normalize(reply), {"addButton": [{"icon": "chi.ico"}]})


@requires_backend
class ReferenceBackendTests(unittest.TestCase):
    def test_typing_commits_through_the_real_backend(self):
        suite = {"ime": "chedayi", "scenarios": [{"name": "人器", "steps": ["a", "SPACE", "o", "o", "SPACE"]}]}
        transcript = driver.run_suite(suite, driver.REFERENCE)
        self.assertTrue(transcript[0]["reply"].get("success"), transcript[0])
        commits = [r["reply"]["commitString"] for r in transcript if r["reply"].get("commitString")]
        self.assertEqual(commits, ["人", "器"])

    def test_random_sessions_are_deterministic(self):
        suite = driver.generate(seed=11, count=12, length=60)
        first = driver.run_suite(suite, driver.REFERENCE)
        second = driver.run_suite(suite, driver.REFERENCE)
        self.assertEqual(driver.compare(first, second), [])
        failed = [r for r in first if r["reply"].get("success") is False or "error" in r["reply"]]
        self.assertEqual(failed, [], "requests failed inside the backend")

    def test_wait_moves_the_virtual_clock(self):
        # with auto-commit on, bt commits 孫 at once and a Space within
        # AUTO_COMMIT_SPACE_GRACE (1 s) is swallowed; after 2 s it reaches the app
        suite = {"ime": "chedayi", "config": {"autoCommitSingleCandidate": True}, "scenarios": [
            {"name": "fast", "steps": ["b", "t", "SPACE"]},
            {"name": "slow", "steps": ["b", "t", {"wait": 2.0}, "SPACE"]}]}
        transcript = driver.run_suite(suite, driver.REFERENCE)

        def space_taken(scenario):
            for r in transcript:
                if r["scenario"] == scenario and r["step"].endswith(":SPACE") and r["method"] == "filterKeyDown":
                    return r["reply"]["return"]

        commits = [r["reply"]["commitString"] for r in transcript if r["reply"].get("commitString")]
        self.assertEqual(commits, ["孫", "孫"])
        self.assertTrue(space_taken("fast"))
        self.assertFalse(space_taken("slow"))

    def test_golden_transcripts(self):
        for suite_path in sorted(glob.glob(os.path.join(HARNESS, "suites", "*.json"))):
            golden = os.path.join(HARNESS, "golden", os.path.basename(suite_path)[:-5] + ".jsonl")
            if not os.path.exists(golden):
                continue
            with self.subTest(suite=os.path.basename(suite_path)):
                with open(suite_path, encoding="utf-8") as f:
                    suite = json.load(f)
                problems = driver.compare(driver.load(golden), driver.run_suite(suite, driver.REFERENCE))
                self.assertEqual(problems, [], "re-record with: python tests/diffharness/driver.py "
                                               "record %s %s" % (suite_path, golden))


def _rust_backend():
    if os.environ.get("WIME_CINBASE_EXE"):
        return os.environ["WIME_CINBASE_EXE"]
    target = os.path.join(HERE, os.pardir, "cinbase-rs", "target")
    # cinbase-rs/.cargo/config.toml builds for i686 by default (like the installer ships)
    for sub in (("i686-pc-windows-msvc", "release"), ("release",)):
        path = os.path.join(target, *sub, "wime-cinbase.exe")
        if os.path.exists(path):
            return path
    return os.path.join(target, "i686-pc-windows-msvc", "release", "wime-cinbase.exe")


RUST_BACKEND = _rust_backend()


@requires_backend
@unittest.skipUnless(os.path.exists(RUST_BACKEND), "cinbase-rs is not built (cargo build --release)")
class RustBackendTests(unittest.TestCase):
    """The Rust 大易 backend must answer exactly like the Python one."""

    def test_golden_transcripts(self):
        import suites
        for name, suite in suites.SUITES.items():
            golden = suites.golden_path(name)
            if not os.path.exists(golden):
                continue
            with self.subTest(suite=name):
                problems = driver.compare(driver.load(golden), driver.run_suite(suite, [RUST_BACKEND]))
                self.assertEqual(problems, [])

    def test_random_sessions_match_python(self):
        suite = driver.generate(seed=2026, count=20, length=80)
        expected = driver.run_suite(suite, driver.REFERENCE)
        self.assertEqual(driver.compare(expected, driver.run_suite(suite, [RUST_BACKEND])), [])


if __name__ == "__main__":
    unittest.main()
