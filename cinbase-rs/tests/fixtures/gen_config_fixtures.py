#! python3
"""Records what the Python modules do, for the Rust ports' unit tests:

- config_cases.json: python/cinbase/config.py (CinBaseConfig.load/save/update)
  for many shipped + user config.json combinations
- candidate_theme_cases.json: python/candidate_theme.py
- pager_cases.json: python/cinbase/pager.py

Run from anywhere:  python cinbase-rs/tests/fixtures/gen_config_fixtures.py
Only temporary directories are used as APPDATA / USERPROFILE.
"""

import copy
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PYDIR = os.path.join(REPO, "python")
sys.path[:0] = [PYDIR, os.path.join(PYDIR, "cinbase")]

from cinbase import config as config_mod  # noqa: E402
import candidate_theme  # noqa: E402
from cinbase import pager  # noqa: E402

T1 = 1600000000
T2 = 1600000500

ConfigClass = type(config_mod.CinBaseConfig)
KEYS = list(ConfigClass().toJson().keys())


def j(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def make_cases():
    cases = []

    def add(name, ime="chedayi", **kw):
        kw["name"] = name
        kw["ime"] = ime
        cases.append(kw)

    add("no user file")
    add("no user file checj", ime="checj")
    add("ime without shipped config", ime="nonexistentime")
    add("valid user", user=j({"candPerPage": 5, "fontSize": 20, "candidateTheme": "Plum", "defaultEnglish": True}))
    add("valid user checj", ime="checj", user=j({"selCinType": 3, "imeDisplayName": "倉頡"}))

    bad_values = ["", "5", " 7 ", "abc", 5, 5.0, 5.5, -1, 0, 1, 2, 300, 100000, True, False, None,
                  [1], {"a": 1}, "true", "off", "yes", " On ", "NO", 1e16, 1e-7, 123.456, -0.0,
                  "１２", "1_0", "_1", "+3", "-4", "0x10", 0.0001, "　 8\t"]
    for i, v in enumerate(bad_values):
        data = {k: v for k in KEYS}
        add("all keys = %r" % (v,), user=j(data))
        if i % 3 == 0:
            add("checj all keys = %r" % (v,), ime="checj", user=j(data))

    add("retired keys", user=j({"candidateModernStyle": True, "messageDurationTime": 3, "hidePromptMessages": True, "fontSize": 14}))
    add("BOM", user=b"\xef\xbb\xbf" + j({"fontSize": 16, "imeDisplayName": "大易四碼"}))
    add("cp950 file", user=json.dumps({"imeDisplayName": "大易", "hideCompositionLabel": "測試", "fontSize": 18},
                                       ensure_ascii=False).encode("cp950"))
    add("invalid json", user=b'{"fontSize": 14,')
    add("non-object list", user=b"[1, 2]")
    add("non-object string", user=b'"abc"')
    add("non-object number", user=b"5")
    add("empty user file, no legacy", user=b"")
    add("legacy home config", legacy={"config.json": j({"fontSize": 22, "candPerPage": 4}), "symbols.dat": b"x"})
    add("legacy with subdir", legacy={"config.json": j({"fontSize": 22}), "sub/a.txt": b"a"})
    add("legacy, dst subdir exists", legacy={"config.json": j({"fontSize": 23}), "sub/a.txt": b"a"},
        appdata_extra={"sub/b.txt": b"b"})
    add("empty user file + legacy", user=b"", legacy={"config.json": j({"fontSize": 24})})
    add("invalid legacy", legacy={"config.json": b"{bad"})
    add("maxWidth 300", user=j({"candidateMaxWidth": 300}))
    add("maxWidth 300 migrated", user=j({"candidateMaxWidth": 300, "candidateMaxWidthMigrated": True}))
    add("maxWidth 300 migrated yes", user=j({"candidateMaxWidth": 300, "candidateMaxWidthMigrated": "yes"}))
    add("maxWidth 300 migrated 0", user=j({"candidateMaxWidth": 300, "candidateMaxWidthMigrated": 0}))
    add("maxWidth '300'", user=j({"candidateMaxWidth": "300"}))
    add("maxWidth 300.0", user=j({"candidateMaxWidth": 300.0}))
    add("unknown keys", user=j({"zeta": 1, "alpha": [1, {"b": 2.5, "a": None}], "keyboardLayout": 3,
                                "ünï": "é😀\u0001\u007f\"\\\n", "emptyD": {}, "emptyL": [], "f": 1e16,
                                "nested": {"z": {"y": []}}}))
    add("dict values", user=j({"candidateColors": {"panelBackground": "#000000"}, "candidateStyle": 5}))
    add("legacy light colors", user=j({"candidateColors": dict(candidate_theme.LEGACY_LIGHT_CANDIDATE_COLORS)}))
    add("ranges with shipped fallback", user=j({"candPerPage": 11, "candidateMinWidth": -1, "selCinType": 1000,
                                                  "candidateOpacity": 29, "fontSize": 201, "selWildcardType": 2}))
    add("string numbers", user=j({"imeDisplayName": 123, "hideCompositionLabel": 1.5, "candidateTheme": True,
                                  "candidateLayout": None, "candidateMessageStyle": 1e100}))
    add("fixed values", user=j({"candidateKeyStyle": "keycap", "candidateHeaderStyle": "badge"}))
    add("duplicate keys", user=b'{"fontSize": 14, "x": 1, "fontSize": 15}')
    add("reload removes keys", user=j({"fontSize": 30, "selKeyType": 5, "extra": 1, "keyboardType": 2}),
        user2=j({"candPerPage": 3}))
    add("reload broken", user=j({"fontSize": 30}), user2=b"{oops")
    add("reload 300", user=j({"candidateMaxWidth": 280}), user2=j({"candidateMaxWidth": 300}))
    add("no user then reload", user2=j({"fontSize": 9}))

    shipped_variants = [
        ("wrong types", j({"fontSize": "14", "candPerPage": 5.0, "directShowCand": "yes", "imeDisplayName": 7,
                           "candidateStyle": [], "selCinType": 5000, "candidateOpacity": 10, "keyboardLayout": 0})),
        ("BOM", b"\xef\xbb\xbf" + j({"fontSize": 13, "imeDisplayName": "大易"})),
        ("invalid", b"{nope"),
        ("not utf-8", json.dumps({"imeDisplayName": "大易"}, ensure_ascii=False).encode("cp950")),
        ("array of pairs", j([["fontSize", 19], ["zz", 1], "ab", ["a", "b", "c"], ["candPerPage", 2]])),
        ("number", b"5"),
        ("empty", b""),
        ("maxWidth 300", j({"candidateMaxWidth": 300})),
        ("retired", j({"messageDurationTime": 3, "fontSize": 15})),
        ("crlf", b'{\r\n"fontSize": 17,\r"candPerRow": 4\r\n}'),
    ]
    for name, data in shipped_variants:
        add("shipped " + name, shipped=data)
        add("shipped " + name + " + user", shipped=data,
            user=j({"fontSize": "x", "candPerPage": None, "imeDisplayName": [], "candidateMaxWidth": 300,
                    "selCinType": -5, "directShowCand": None}))
    return cases


def run_case(case, root):
    ime = case["ime"]
    appdata = os.path.join(root, "appdata")
    home = os.path.join(root, "home")
    os.makedirs(appdata)
    os.makedirs(home)
    os.environ["APPDATA"] = appdata
    os.environ["USERPROFILE"] = home
    cfgdir = os.path.join(appdata, "PIME", ime)
    if "user" in case or "appdata_extra" in case:
        os.makedirs(cfgdir, exist_ok=True)
    if "user" in case:
        path = os.path.join(cfgdir, "config.json")
        with open(path, "wb") as f:
            f.write(case["user"])
        os.utime(path, (T1, T1))
    for rel, data in case.get("appdata_extra", {}).items():
        path = os.path.join(cfgdir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    if "legacy" in case:
        for rel, data in case["legacy"].items():
            path = os.path.join(home, "PIME", ime, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            os.utime(path, (T1, T1))

    saved_methods = (ConfigClass.getDefaultConfigDir, ConfigClass.getDataDir)
    if "shipped" in case:
        pyroot = os.path.join(root, "python")
        shipped_dir = os.path.join(pyroot, "input_methods", ime, "config")
        os.makedirs(shipped_dir)
        os.makedirs(os.path.join(pyroot, "cinbase", "data"))
        with open(os.path.join(shipped_dir, "config.json"), "wb") as f:
            f.write(case["shipped"])
        ConfigClass.getDefaultConfigDir = lambda self: shipped_dir
        ConfigClass.getDataDir = lambda self: os.path.join(pyroot, "cinbase", "data")
    try:
        # ime_base.py: re-initialised singleton, deep-copied per text service
        config_mod.CinBaseConfig.__init__()
        cfg = copy.deepcopy(config_mod.CinBaseConfig)
        cfg.imeDirName = ime
        cfg.cinFileList = []
        cfg.load()
        out = {"after_load": cfg.toJson(), "after_load_keys": list(cfg.toJson().keys())}
        out["appdata_files"] = sorted(os.listdir(cfgdir)) if os.path.isdir(cfgdir) else None
        legacy_dir = os.path.join(home, "PIME", ime)
        out["home_files"] = sorted(os.listdir(legacy_dir)) if os.path.isdir(legacy_dir) else None
        out["version_nonzero"] = [v != 0.0 for v in cfg.getVersion()]

        cfg.reLoadTable = False
        cfg.save()
        with open(os.path.join(cfgdir, "config.json"), "rb") as f:
            out["saved"] = f.read().decode("ascii")

        if "user2" in case:
            path = os.path.join(cfgdir, "config.json")
            with open(path, "wb") as f:
                f.write(case["user2"])
            os.utime(path, (T2, T2))
            before = cfg.getVersion()
            cfg._lastUpdateTime = 0.0
            cfg.update()
            out["after_reload"] = cfg.toJson()
            out["after_reload_keys"] = list(cfg.toJson().keys())
            out["reload_config_changed"] = cfg.isConfigChanged(before)
            out["reload_full_needed"] = cfg.isFullReloadNeeded(before)
        return out
    finally:
        ConfigClass.getDefaultConfigDir, ConfigClass.getDataDir = saved_methods


def config_fixture():
    results = []
    base = tempfile.mkdtemp(prefix="wime-cfg-gen-")
    try:
        for i, case in enumerate(make_cases()):
            root = os.path.join(base, str(i))
            os.makedirs(root)
            expected = run_case(case, root)
            inputs = {k: (v.hex() if isinstance(v, bytes) else
                          {rk: rv.hex() for rk, rv in v.items()} if isinstance(v, dict) else v)
                      for k, v in case.items()}
            results.append({"input": inputs, "expected": expected})
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return results


def theme_fixture():
    names = ["System", "system", "Follow System", "auto", "AUTO", "Graphite", "dark", "Night", "Sepia Dim",
             "sepia", "Plum", "Light", "light", " Light ", "Pure Black", "black", "OLED", "High Contrast",
             "contrast", "Olive", "", "Dark!", "dark-mode", "Ｄａｒｋ", "ＤＡＲＫ", "大易", "lightK", "li_ght",
             "Ǆark", "blacK", "İight"]

    class Cfg:
        pass

    resolve = []
    for name in names:
        row = {"theme": name}
        for light in (True, False):
            candidate_theme._systemThemeCache["light"] = light
            candidate_theme._systemThemeCache["ts"] = candidate_theme.time.time()
            cfg = Cfg()
            cfg.candidateTheme = name
            row["light" if light else "dark"] = candidate_theme.resolveCandidateTheme(cfg)
        resolve.append(row)

    legacy = dict(candidate_theme.LEGACY_LIGHT_CANDIDATE_COLORS)
    legacy_lower = {k: " " + v.lower() + "\t" for k, v in legacy.items()}
    legacy_changed = dict(legacy, panelBackground="#FFFFFE")
    legacy_extra = dict(legacy, extra="#000000")
    legacy_missing = dict(legacy)
    legacy_missing.pop("panelBorder")
    legacy_number = dict(legacy, panelBackground=5)
    color_sets = [{}, [], None, "x", legacy, legacy_lower, legacy_changed, legacy_extra, legacy_missing,
                  legacy_number, {"panelBackground": "#000000"}]
    colors = []
    for c in color_sets:
        for theme in ["", "Light", "light ", "Graphite", "System", "Olive", "L-i-g-h-t"]:
            cfg = Cfg()
            cfg.candidateColors = c
            cfg.candidateTheme = theme
            colors.append({"colors": c, "theme": theme, "expected": candidate_theme.candidateColorsForTheme(cfg)})
    return {"resolve": resolve, "colors": colors}


def pager_fixture():
    imes = ["chedayi", "checj", "", "CHEDAYI", "chephonetic"]
    out = {"max": [[ime, pager.maxCandPerPage(ime)] for ime in imes], "clamp": [], "paginate": [], "count": []}
    for ime in imes:
        for n in [-5, 0, 1, 5, 6, 7, 9, 10, 11, 100]:
            out["clamp"].append([n, ime, pager.clampCandPerPage(n, ime)])
    for total in [0, 1, 5, 6, 7, 12, 13]:
        items = ["c%d" % i for i in range(total)]
        for per in [-1, 0, 1, 3, 6, 10]:
            out["paginate"].append([items, per, pager.paginate(items, per)])
            out["count"].append([total, per, pager.pageCount(total, per)])
    return out


def write(name, data, indent=1):
    with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
        f.write("\n")


if __name__ == "__main__":
    write("config_cases.json", config_fixture(), indent=None)
    write("candidate_theme_cases.json", theme_fixture())
    write("pager_cases.json", pager_fixture())
    print("ok")
