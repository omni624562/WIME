"""Differential harness: drive any WIME backend through the launcher's stdio
protocol with scripted key sequences, record every reply, and compare the
replies of two backends (or of one backend against a recorded golden file).

The point is to port an input method to another implementation (the Rust 大易
backend) and prove it answers every request exactly like the Python one.

Backends are command lines that speak the protocol server.py speaks:
    stdin  "<client_id>|<json request>\\n"
    stdout "PIME_MSG|<client_id>|<json reply>\\n"
The reference is tests/diffharness/py_reference_backend.py (server.py with a
virtual clock, synchronous table loading and no program launches). Another
backend must honour the same test conventions: the "__advanceClock" request,
"_testLaunches" / "_testSounds" in replies, and no real launches.

Each backend run gets a fresh temporary APPDATA/LOCALAPPDATA/USERPROFILE, so the
user's real settings and data are never read or written.

Suites (JSON):
    {"ime": "chedayi",                 # input method folder name
     "config": {...},                  # optional user config.json
     "scenarios": [
        {"name": "...", "keyboardOpen": true,
         "steps": ["a", "SPACE", ["a", "S"], {"wait": 1.5},
                   {"request": "onCommand", "id": 4, "type": 0}]}]}
A step is a key name/char (see keys.py), [key, modifiers] with modifiers from
S (left Shift) R (right Shift) C (Ctrl) A (Alt), {"wait": seconds}, or
{"request": method, ...fields}. Every scenario is one client: init, onActivate,
the steps, onDeactivate, close. Scenarios of a suite share one backend process,
in order, so state the backend keeps across clients (tables, usage counts) is
part of what is compared.

Usage:
    python driver.py record  SUITE.json OUT.jsonl  [--backend CMD]
    python driver.py compare SUITE.json GOLDEN.jsonl [--backend CMD]
    python driver.py diff    SUITE.json --backend CMD --against CMD
    python driver.py gen     OUT.json --seed N --count M [--length L]
"""

import argparse
import json
import os
import queue
import random
import shlex
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
sys.path.insert(0, HERE)

import keys  # noqa: E402

PYTHON_EXE = os.path.join(ROOT, "python", "python3", "python.exe")
REFERENCE = [PYTHON_EXE, "-O", os.path.join(HERE, "py_reference_backend.py")]

IME_GUIDS = {
    "chedayi": "{E6943374-70F5-4540-AA0F-3205C7DCCA84}",
    "checj": "{F828D2DC-81BE-466E-9CFE-24BB03172693}",
}
REPLY_TIMEOUT = 30.0


class BackendDied(RuntimeError):
    pass


class Backend:
    """One backend process with its own temporary profile directories."""

    def __init__(self, command, ime, config=None):
        self.command = command
        self._tmp = tempfile.TemporaryDirectory(prefix="wime-diff-", ignore_cleanup_errors=True)
        profile = self._tmp.name
        env = dict(os.environ)
        for key in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME"):
            env[key] = profile
        # what PIMELauncher (backend_manager.rs) sets for every backend
        env["PYTHONIOENCODING"] = "utf-8:ignore"
        env["PYTHONUNBUFFERED"] = "1"
        env["WIME_TEST_MODE"] = "1"
        env.pop("WIME_E2E", None)
        if config is not None:
            config_dir = os.path.join(profile, "PIME", ime)
            os.makedirs(config_dir)
            with open(os.path.join(config_dir, "config.json"), "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False)
        self.proc = subprocess.Popen(
            command, cwd=os.path.join(ROOT, "python"), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._lines = queue.Queue()
        self.stderr = []
        self._readers = [threading.Thread(target=self._read_stdout, daemon=True),
                         threading.Thread(target=self._read_stderr, daemon=True)]
        for reader in self._readers:
            reader.start()

    def _read_stdout(self):
        for raw in self.proc.stdout:
            self._lines.put(raw.decode("utf-8", "replace").rstrip("\r\n"))
        self._lines.put(None)

    def _read_stderr(self):
        for raw in self.proc.stderr:
            self.stderr.append(raw.decode("utf-8", "replace").rstrip("\r\n"))

    def request(self, client_id, message):
        line = "%s|%s\n" % (client_id, json.dumps(message, ensure_ascii=False))
        try:
            self.proc.stdin.write(line.encode("utf-8"))
            self.proc.stdin.flush()
        except OSError as e:
            raise BackendDied("cannot write to backend: %s\n%s" % (e, self.tail()))
        prefix = "PIME_MSG|%s|" % client_id
        while True:
            try:
                out = self._lines.get(timeout=REPLY_TIMEOUT)
            except queue.Empty:
                raise BackendDied("no reply to %s within %ss\n%s" % (message.get("method"), REPLY_TIMEOUT, self.tail()))
            if out is None:
                raise BackendDied("backend exited (code %s)\n%s" % (self.proc.poll(), self.tail()))
            if out.startswith(prefix):
                return json.loads(out[len(prefix):])
            # anything else on stdout is noise (print() debugging)

    def send_only(self, client_id, message):
        line = "%s|%s\n" % (client_id, json.dumps(message, ensure_ascii=False))
        self.proc.stdin.write(line.encode("utf-8"))
        self.proc.stdin.flush()

    def tail(self, n=20):
        return "\n".join(self.stderr[-n:])

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        for reader in self._readers:
            reader.join(timeout=5)
        for stream in (self.proc.stdout, self.proc.stderr):
            stream.close()
        self._tmp.cleanup()


def normalize(value):
    """Make a reply comparable across implementations and machines: icon paths
    become their file names (each backend installs its icons elsewhere)."""
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, str) and value.lower().endswith(".ico") and ("\\" in value or "/" in value):
        return os.path.basename(value.replace("/", "\\").split("\\")[-1])
    return value


class Session:
    """One client of a backend; records (label, request, reply) triples."""

    def __init__(self, backend, client_id, ime, log):
        self.backend, self.client_id, self.ime, self.log = backend, client_id, ime, log
        self.seq = 0

    def call(self, label, method, **fields):
        self.seq += 1
        message = dict(fields, method=method, seqNum=self.seq)
        reply = self.backend.request(self.client_id, message)
        self.log.append({"step": label, "method": method, "reply": normalize(reply)})
        return reply

    def start(self, keyboard_open=True):
        self.call("init", "init", id=IME_GUIDS[self.ime], isWindows8Above=True,
                  isMetroApp=False, isUiLess=False, isConsole=False)
        self.call("activate", "onActivate", isKeyboardOpen=keyboard_open)

    def key(self, label, key, mods=""):
        down, up = keys.key_event(key, mods, down=True), keys.key_event(key, mods, down=False)
        if self.call(label, "filterKeyDown", **down).get("return"):
            self.call(label, "onKeyDown", **down)
        if self.call(label, "filterKeyUp", **up).get("return"):
            self.call(label, "onKeyUp", **up)

    def step(self, index, step):
        if isinstance(step, str):
            self.key("%d:%s" % (index, step), step)
        elif isinstance(step, list):
            self.key("%d:%s+%s" % (index, step[1], step[0]), step[0], step[1])
        elif "wait" in step:
            self.call("%d:wait %s" % (index, step["wait"]), "__advanceClock", seconds=step["wait"])
        elif "request" in step:
            fields = {k: v for k, v in step.items() if k != "request"}
            self.call("%d:%s" % (index, step["request"]), step["request"], **fields)
        else:
            raise ValueError("bad step %r" % (step,))

    def stop(self):
        self.call("deactivate", "onDeactivate")
        self.backend.send_only(self.client_id, {"method": "close"})


def run_suite(suite, command):
    """Run every scenario of a suite on one backend process; return the transcript:
    a list of {"scenario", "step", "method", "reply"} records."""
    ime = suite.get("ime", "chedayi")
    transcript = []
    backend = Backend(command, ime, suite.get("config"))
    try:
        for number, scenario in enumerate(suite["scenarios"]):
            log = []
            session = Session(backend, "client-%d" % number, ime, log)
            try:
                session.start(scenario.get("keyboardOpen", True))
                for index, step in enumerate(scenario["steps"]):
                    session.step(index, step)
                session.stop()
            except BackendDied as e:
                log.append({"step": "backend died", "method": "", "reply": {"error": str(e).splitlines()[0]}})
                for record in log:
                    record["scenario"] = scenario.get("name", str(number))
                transcript.extend(log)
                backend.close()
                backend = Backend(command, ime, suite.get("config"))
                continue
            for record in log:
                record["scenario"] = scenario.get("name", str(number))
            transcript.extend(log)
    finally:
        backend.close()
    return transcript


def dump(transcript, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for record in transcript:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _diff_value(a, b, path=""):
    """First differences between two JSON values as 'path: a != b' strings."""
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return ["%s: %r != %r" % (path or "/", a, b)]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append("%s/%s: <missing> != %r" % (path, k, b[k]))
            elif k not in b:
                out.append("%s/%s: %r != <missing>" % (path, k, a[k]))
            else:
                out.extend(_diff_value(a[k], b[k], "%s/%s" % (path, k)))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return ["%s: %r != %r" % (path or "/", a, b)]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(_diff_value(x, y, "%s[%d]" % (path, i)))
        return out
    return [] if a == b else ["%s: %r != %r" % (path or "/", a, b)]


def compare(expected, actual, limit=20):
    """Return a list of human-readable differences (empty when identical)."""
    problems = []
    for i in range(max(len(expected), len(actual))):
        if i >= len(expected) or i >= len(actual):
            problems.append("record %d: transcript lengths differ (%d expected, %d actual)"
                            % (i, len(expected), len(actual)))
            break
        e, a = expected[i], actual[i]
        where = "%s / %s / %s" % (e.get("scenario"), e.get("step"), e.get("method"))
        if (e.get("scenario"), e.get("step"), e.get("method")) != (a.get("scenario"), a.get("step"), a.get("method")):
            problems.append("record %d: request order differs: %s vs %s / %s / %s"
                            % (i, where, a.get("scenario"), a.get("step"), a.get("method")))
            break
        for d in _diff_value(e["reply"], a["reply"]):
            problems.append("%s: %s" % (where, d))
        if len(problems) >= limit:
            break
    return problems[:limit]


# --- random scenarios ------------------------------------------------------

# 大易 roots (letters, digits, , . / ;), its selection keys (' [ ] - \),
# editing and navigation keys, Shift combinations, the ` menu and toggles.
_ROOTS = list("abcdefghijklmnopqrstuvwxyz0123456789,./;")
_SELECT = list("'[]-\\=")
_EDIT = ["SPACE", "SPACE", "ENTER", "ESC", "BACK", "LEFT", "RIGHT", "UP", "DOWN",
         "HOME", "END", "PGUP", "PGDN", "DEL"]
_SHIFTED = [["a", "S"], ["SPACE", "S"], [",", "S"], [".", "S"], ["1", "S"], ["/", "S"]]
_RARE = ["`", "SHIFT", ["SHIFT", "R"], ["SPACE", "C"], "?", "*", "CAPS", "TAB",
         "NUM1", "NUM.", "NUM+", ["a", "C"]]
SHIFT_SPACE_GUID = "{f1dae0fb-8091-44a7-8a0c-3082a1515447}"
# what the DLL sends besides keys: language bar buttons (1 中英, 2 全半形,
# 4 mode icon; type 0 left click, 1 right click), their menus, Shift+Space as a
# preserved key, focus and keyboard-open changes, the app ending a composition
_REQUESTS = [
    {"request": "onCommand", "id": 1, "type": 0},
    {"request": "onCommand", "id": 2, "type": 0},
    {"request": "onCommand", "id": 4, "type": 0},
    {"request": "onCommand", "id": 4, "type": 1},
    {"request": "onMenu", "id": "windows-mode-icon"},
    {"request": "onMenu", "id": "settings"},
    {"request": "onPreservedKey", "guid": SHIFT_SPACE_GUID},
    {"request": "onKillFocus"},
    {"request": "onCompositionTerminated", "forced": True},
    {"request": "onCompositionTerminated", "forced": False},
    {"request": "onKeyboardStatusChanged", "opened": False},
    {"request": "onKeyboardStatusChanged", "opened": True},
]


def random_steps(rng, length):
    steps = []
    while len(steps) < length:
        r = rng.random()
        if r < 0.03:
            steps.append(dict(rng.choice(_REQUESTS)))
        elif r < 0.55:
            # a burst of roots, like typing one character
            steps.extend(rng.choice(_ROOTS) for _ in range(rng.randint(1, 4)))
        elif r < 0.70:
            steps.append(rng.choice(_SELECT))
        elif r < 0.88:
            steps.append(rng.choice(_EDIT))
        elif r < 0.95:
            steps.append(rng.choice(_SHIFTED))
        elif r < 0.985:
            steps.append(rng.choice(_RARE))
        else:
            steps.append({"wait": rng.choice([0.4, 1.5, 4.0])})
    return steps[:length]


def generate(seed, count, length, ime="chedayi", config=None):
    rng = random.Random(seed)
    suite = {"ime": ime, "scenarios": []}
    if config is not None:
        suite["config"] = config
    for i in range(count):
        suite["scenarios"].append({"name": "random-%d-%d" % (seed, i),
                                   "steps": random_steps(rng, length)})
    return suite


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("record", "compare"):
        p = sub.add_parser(name)
        p.add_argument("suite")
        p.add_argument("file")
        p.add_argument("--backend", help="backend command line (default: Python reference)")
    p = sub.add_parser("diff")
    p.add_argument("suite")
    p.add_argument("--backend", required=True)
    p.add_argument("--against", help="default: Python reference")
    p = sub.add_parser("gen")
    p.add_argument("out")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--length", type=int, default=40)
    p.add_argument("--ime", default="chedayi")
    args = parser.parse_args(argv)

    def command(text):
        return shlex.split(text, posix=False) if text else REFERENCE

    if args.cmd == "gen":
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(generate(args.seed, args.count, args.length, args.ime), f, ensure_ascii=False, indent=1)
        return 0
    with open(args.suite, encoding="utf-8") as f:
        suite = json.load(f)
    if args.cmd == "record":
        transcript = run_suite(suite, command(args.backend))
        dump(transcript, args.file)
        print("recorded %d replies to %s" % (len(transcript), args.file))
        return 0
    if args.cmd == "compare":
        expected = load(args.file)
        actual = run_suite(suite, command(args.backend))
    else:
        expected = run_suite(suite, command(args.against))
        actual = run_suite(suite, command(args.backend))
    problems = compare(expected, actual)
    for p in problems:
        print(p)
    print("%d replies, %s" % (len(expected), "identical" if not problems else "%d+ differences" % len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
