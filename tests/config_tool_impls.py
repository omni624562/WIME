"""How the tests start a settings tool, in either implementation:

- "python": python/cinbase/configtool.py (大易/酷倉) and
  python/input_methods/chewing/config_tool.py (新酷音) on python/config_server.py,
  with os.startfile stubbed to print the login URL and SERVER_TIMEOUT shortened;
- "rust": cinbase-rs's wime-config.exe (`wime-config.exe <tool> <ime>`), with
  the same stubs through its test hooks (WIME_CONFIG_TEST_LAUNCH=print,
  WIME_CONFIG_IDLE_TIMEOUT) and the pages/data of the repo's python folder
  (WIME_PY_DIR).

Never start a tool without these stubs: it would open the user's browser.
The Rust tests are skipped when wime-config.exe is not built (cd cinbase-rs;
cargo build --release), unless WIME_REQUIRE_RUST_CONFIG=1 (CI) makes that a
failure. WIME_CONFIG_EXE overrides the executable's path.
"""

import os
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")

DRIVER = r"""
import os, runpy, sys
python_dir, script, idle = sys.argv[1], sys.argv[2], float(sys.argv[3])
tool_args = sys.argv[4:]
sys.path.insert(0, python_dir)
import config_server
config_server.SERVER_TIMEOUT = idle
def startfile(url, *args, **kwargs):
    # WIME_CONFIG_TEST_LAUNCH=fail-url: the browser cannot open the URL, so the
    # tool writes launch_<tool>.html and opens that instead (like wime-config.exe)
    if os.environ.get("WIME_CONFIG_TEST_LAUNCH") == "fail-url" and url.startswith("http:"):
        raise OSError("no browser")
    print("URL " + url, flush=True)
os.startfile = startfile
sys.argv = [script] + tool_args
runpy.run_path(script, run_name="__main__")
"""

PYTHON_SCRIPTS = {
    "cinbase": os.path.join(PYTHON_DIR, "cinbase", "configtool.py"),
    "chewing": os.path.join(PYTHON_DIR, "input_methods", "chewing", "config_tool.py"),
}


def _rust_config_exe():
    if os.environ.get("WIME_CONFIG_EXE"):
        return os.environ["WIME_CONFIG_EXE"]
    target = os.path.join(ROOT, "cinbase-rs", "target")
    # cinbase-rs/.cargo/config.toml builds for i686 by default (like the installer ships)
    for sub in (("i686-pc-windows-msvc", "release"), ("release",)):
        path = os.path.join(target, *sub, "wime-config.exe")
        if os.path.exists(path):
            return path
    return os.path.join(target, "i686-pc-windows-msvc", "release", "wime-config.exe")


RUST_CONFIG_EXE = _rust_config_exe()
IMPLEMENTATIONS = ("python", "rust")


def requires(impl):
    """Class decorator: skip the Rust variant when wime-config.exe is missing."""
    if impl != "rust" or os.path.exists(RUST_CONFIG_EXE) or os.environ.get("WIME_REQUIRE_RUST_CONFIG") == "1":
        return lambda cls: cls
    return unittest.skip("wime-config.exe is not built (cd cinbase-rs; cargo build --release)")


def tool_command(impl, ime, tool, idle):
    """The command line (and extra environment) that starts the settings tool
    of `ime` ("chedayi", "checj", ... or "chewing"); tool is "config" or
    "user_phrase_editor"."""
    if impl == "rust":
        env = {"WIME_PY_DIR": PYTHON_DIR, "WIME_CONFIG_TEST_LAUNCH": "print", "WIME_CONFIG_IDLE_TIMEOUT": str(idle)}
        return [RUST_CONFIG_EXE, tool, ime], env
    if ime == "chewing":
        return [sys.executable, "-c", DRIVER, PYTHON_DIR, PYTHON_SCRIPTS["chewing"], str(idle), tool], {}
    return [sys.executable, "-c", DRIVER, PYTHON_DIR, PYTHON_SCRIPTS["cinbase"], str(idle), tool, ime], {}


def start_tool(impl, ime, tool, env, idle, extra_env=None, stderr=subprocess.PIPE):
    """Start the tool with `env` (APPDATA/LOCALAPPDATA already redirected).
    Returns (process, login URL). Pass a file as stderr when the test makes
    many requests fail: the tools log each error there, and a full pipe that
    nobody reads blocks them."""
    command, tool_env = tool_command(impl, ime, tool, idle)
    env = dict(env)
    env.update(tool_env)
    env.update(extra_env or {})
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr, env=env,
                            text=True, encoding="utf-8")
    line = proc.stdout.readline()
    if not line.startswith("URL "):
        proc.kill()
        raise RuntimeError("tool did not start: %r %s" % (line, proc.stderr.read() if proc.stderr else ""))
    return proc, line[4:].strip()
