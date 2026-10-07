use super::*;
use serde_json::json;
use std::sync::atomic::{AtomicUsize, Ordering};

const T1: u64 = 1_600_000_000;
const T2: u64 = 1_600_000_500;

fn hex(s: &str) -> Vec<u8> {
    (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect()
}

fn set_mtime(path: &Path, secs: u64) {
    let f = fs::OpenOptions::new().write(true).open(path).unwrap();
    f.set_modified(std::time::UNIX_EPOCH + std::time::Duration::from_secs(secs)).unwrap();
}

fn write(path: &Path, data: &[u8]) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, data).unwrap();
}

fn listing(dir: &Path) -> Value {
    if !dir.is_dir() {
        return Value::Null;
    }
    let mut names: Vec<String> = fs::read_dir(dir).unwrap().map(|e| e.unwrap().file_name().to_string_lossy().into_owned()).collect();
    names.sort();
    json!(names)
}

fn repo_python_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("python")
}

fn temp_root() -> PathBuf {
    static N: AtomicUsize = AtomicUsize::new(0);
    let dir = std::env::temp_dir().join(format!("wime-cfg-rs-{}-{}", std::process::id(), N.fetch_add(1, Ordering::SeqCst)));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

fn keys(m: &Map<String, Value>) -> Value {
    json!(m.keys().collect::<Vec<_>>())
}

fn run_case(input: &Map<String, Value>, root: &Path) -> Map<String, Value> {
    let ime = input["ime"].as_str().unwrap();
    let appdata = root.join("appdata");
    let home = root.join("home");
    fs::create_dir_all(&appdata).unwrap();
    fs::create_dir_all(&home).unwrap();
    let cfgdir = appdata.join("PIME").join(ime);
    if input.contains_key("user") || input.contains_key("appdata_extra") {
        fs::create_dir_all(&cfgdir).unwrap();
    }
    if let Some(user) = input.get("user") {
        let path = cfgdir.join("config.json");
        write(&path, &hex(user.as_str().unwrap()));
        set_mtime(&path, T1);
    }
    if let Some(extra) = input.get("appdata_extra") {
        for (rel, data) in extra.as_object().unwrap() {
            write(&cfgdir.join(rel), &hex(data.as_str().unwrap()));
        }
    }
    if let Some(legacy) = input.get("legacy") {
        for (rel, data) in legacy.as_object().unwrap() {
            let path = home.join("PIME").join(ime).join(rel);
            write(&path, &hex(data.as_str().unwrap()));
            set_mtime(&path, T1);
        }
    }
    let python_dir = if let Some(shipped) = input.get("shipped") {
        let pyroot = root.join("python");
        write(&pyroot.join("input_methods").join(ime).join("config").join("config.json"), &hex(shipped.as_str().unwrap()));
        fs::create_dir_all(pyroot.join("cinbase").join("data")).unwrap();
        pyroot
    } else {
        repo_python_dir()
    };

    let mut cfg = CinBaseConfig::with_paths(ConfigPaths { appdata: appdata.clone(), home: home.clone(), python_dir });
    cfg.ime_dir_name = ime.to_string();
    cfg.load();
    let mut out = Map::new();
    let j = cfg.to_json();
    out.insert("after_load_keys".into(), keys(&j));
    out.insert("after_load".into(), Value::Object(j));
    out.insert("appdata_files".into(), listing(&cfgdir));
    out.insert("home_files".into(), listing(&home.join("PIME").join(ime)));
    out.insert("version_nonzero".into(), json!(cfg.get_version().iter().map(|v| *v != 0.0).collect::<Vec<_>>()));

    cfg.re_load_table = false;
    cfg.save();
    out.insert("saved".into(), Value::String(fs::read_to_string(cfgdir.join("config.json")).unwrap()));

    if let Some(user2) = input.get("user2") {
        let path = cfgdir.join("config.json");
        write(&path, &hex(user2.as_str().unwrap()));
        set_mtime(&path, T2);
        let before = cfg.get_version();
        cfg.last_update_time = 0.0;
        cfg.update();
        let j = cfg.to_json();
        out.insert("after_reload_keys".into(), keys(&j));
        out.insert("after_reload".into(), Value::Object(j));
        out.insert("reload_config_changed".into(), json!(cfg.is_config_changed(&before)));
        out.insert("reload_full_needed".into(), json!(cfg.is_full_reload_needed(&before)));
    }
    out
}

#[cfg(windows)]
fn acp() -> u32 {
    #[link(name = "kernel32")]
    extern "system" {
        fn GetACP() -> u32;
    }
    unsafe { GetACP() }
}

#[cfg(not(windows))]
fn acp() -> u32 {
    0
}

/// Every case recorded from python/cinbase/config.py by
/// tests/fixtures/gen_config_fixtures.py must come out identical.
#[test]
fn matches_python_config() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/config_cases.json");
    let cases: Value = serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
    let mut failures = Vec::new();
    let cases = cases.as_array().unwrap();
    for case in cases {
        let input = case["input"].as_object().unwrap();
        // decoded with the ANSI code page: the fixtures were recorded on cp950
        if input["name"].as_str().unwrap_or("").contains("cp950") && acp() != 950 {
            continue;
        }
        let expected = case["expected"].as_object().unwrap();
        let root = temp_root();
        let got = run_case(input, &root);
        let _ = fs::remove_dir_all(&root);
        for (key, want) in expected {
            if got.get(key) != Some(want) {
                failures.push(format!("{} / {}:\n  python: {}\n  rust:   {}", input["name"], key, want, got.get(key).unwrap_or(&Value::Null)));
            }
        }
    }
    assert!(cases.len() > 50);
    assert!(failures.is_empty(), "{} mismatches:\n{}", failures.len(), failures.join("\n"));
}

#[test]
fn float_repr_like_python() {
    for (f, s) in [
        (1.0, "1.0"),
        (1e16, "1e+16"),
        (1e15, "1000000000000000.0"),
        (123.456, "123.456"),
        (0.0001, "0.0001"),
        (0.00001, "1e-05"),
        (1e-7, "1e-07"),
        (-0.0, "-0.0"),
        (1.5e300, "1.5e+300"),
        (0.1, "0.1"),
        (5.5, "5.5"),
        (1234567890123456.7, "1234567890123456.8"),
    ] {
        assert_eq!(py_float_repr(f), s);
    }
}

#[test]
fn int_parsing_like_python() {
    assert_eq!(py_int_from_str(" 7 "), Some(7));
    assert_eq!(py_int_from_str("１２"), Some(12));
    assert_eq!(py_int_from_str("1_0"), Some(10));
    assert_eq!(py_int_from_str("_1"), None);
    assert_eq!(py_int_from_str("1__0"), None);
    assert_eq!(py_int_from_str("+3"), Some(3));
    assert_eq!(py_int_from_str("-4"), Some(-4));
    assert_eq!(py_int_from_str("0x10"), None);
    assert_eq!(py_int_from_str(""), None);
}

#[test]
fn sel_keys_is_one_character() {
    let mut cfg = CinBaseConfig::with_paths(ConfigPaths { appdata: temp_root(), home: temp_root(), python_dir: repo_python_dir() });
    assert_eq!(cfg.get_sel_keys().unwrap(), "1");
    cfg.sel_key_type = -1;
    assert_eq!(cfg.get_sel_keys().unwrap(), "0");
    cfg.sel_key_type = 10;
    assert!(cfg.get_sel_keys().is_err());
}

#[test]
fn update_is_throttled() {
    let root = temp_root();
    let mut cfg = CinBaseConfig::with_paths(ConfigPaths { appdata: root.join("a"), home: root.join("h"), python_dir: repo_python_dir() });
    cfg.ime_dir_name = "chedayi".into();
    cfg.load();
    assert_eq!(cfg.cand_per_page, 6);
    let path = cfg.get_config_file("config.json");
    write(&path, br#"{"candPerPage": 4}"#);
    cfg.update(); // within 3 seconds: not re-read
    assert_eq!(cfg.cand_per_page, 6);
    cfg.last_update_time = 0.0;
    cfg.update();
    assert_eq!(cfg.cand_per_page, 4);
    assert_eq!(cfg.get("keyboardLayout"), Some(json!(0)));
    let _ = fs::remove_dir_all(&root);
}
