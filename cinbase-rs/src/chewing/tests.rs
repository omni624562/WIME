//! Tests of the 新酷音 port that the differential harness cannot reach: the
//! config file format and normalisation (checked against the Python code when
//! the embedded Python is there), files in the ANSI code page, and the
//! conversion of the old user dictionary. The key handling itself is checked
//! against the Python backend by tests/diffharness (tests/test_diffharness.py).

use super::config::{normalize_values, default_values, ChewingConfig};
use super::engine::ChewingContext;
use super::userdict;
use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
}

fn python() -> Option<PathBuf> {
    let p = repo_root().join("python").join("python3").join("python.exe");
    p.exists().then_some(p)
}

fn syspath() -> String {
    repo_root().join("python").join("libchewing").join("data").to_string_lossy().into_owned()
}

struct TempDir(PathBuf);

impl TempDir {
    fn new(tag: &str) -> TempDir {
        use std::sync::atomic::{AtomicU32, Ordering};
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!("wime-chewing-test-{}-{}-{}", tag, std::process::id(), N.fetch_add(1, Ordering::SeqCst)));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        TempDir(dir)
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn odd_cases() -> Vec<Value> {
    vec![
        json!({}),
        json!({"candPerPage": "7", "keyboardLayout": 99, "selKeyType": 1.0, "fontSize": null}),
        json!({"easySymbolsWithShift": "off", "escCleanAllBuf": 0, "addPhraseForward": 2, "autoLearn": 0.0}),
        json!({"candidatePerRow": true, "candidateMaxWidth": 300, "candidateTheme": 5, "candidateLayout": null}),
        json!({"candidateMaxWidth": 300, "candidateMaxWidthMigrated": true}),
        json!({"candidateMaxWidth": 300.0, "candidateMaxWidthMigrated": "yes"}),
        json!({"candidateStyle": {"contentMargin": 3, "textMargin": "x", "borderRadius": true, "a": 1.5}}),
        json!({"candidateStyle": [1], "candidateColors": "red", "candidateKeyStyle": "keycap"}),
        json!({"candPerRow": 4, "candidateMessageBehavior": "x", "unknown": [1, 2]}),
        json!({"upDownAction": " 1 ", "leftRightAction": "2", "spaceKeyAction": -1, "fontSize": 6.5}),
        json!({"defaultEnglish": "TRUE", "defaultFullSpace": "maybe", "disableOnStartup": [], "enableCapsLock": {}}),
        json!({"switchLangWithWhichShift": false, "candPerPage": true, "candidateOpacity": 29, "candidateMinWidth": 4000}),
    ]
}

#[test]
fn normalize_matches_python() {
    let Some(python) = python() else {
        eprintln!("skipped: no embedded Python");
        return;
    };
    let cases = Value::Array(odd_cases());
    let tmp = TempDir::new("normalize");
    let script = r#"
import json, sys
sys.path.insert(0, sys.argv[1])
from input_methods.chewing import chewing_config as c
cases = json.loads(sys.stdin.read())
print(json.dumps([c.normalizeValues(case, c.defaultValues()) for case in cases]))
"#;
    let mut child = Command::new(python)
        .args(["-c", script])
        .arg(repo_root().join("python"))
        .env("APPDATA", &tmp.0)
        .env("USERPROFILE", &tmp.0)
        .env("PYTHONIOENCODING", "utf-8")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    use std::io::Write;
    child.stdin.take().unwrap().write_all(cases.to_string().as_bytes()).unwrap();
    let out = child.wait_with_output().unwrap();
    assert!(out.status.success());
    let expected: Value = serde_json::from_slice(&out.stdout).unwrap();
    let defaults = default_values();
    for (case, want) in odd_cases().iter().zip(expected.as_array().unwrap()) {
        let got = normalize_values(case.as_object().unwrap(), &defaults);
        assert_eq!(Value::Object(got), *want, "case {}", case);
    }
}

#[test]
fn saved_config_is_byte_identical_to_python() {
    let Some(python) = python() else {
        eprintln!("skipped: no embedded Python");
        return;
    };
    let py_dir = TempDir::new("save-py");
    let script = r##"
import sys
sys.path.insert(0, sys.argv[1])
from input_methods.chewing import chewing_config as c
cfg = c.ChewingConfig(load=False)
cfg.candidateColors = {"panelBackground": "#FFF\"\\", "x": 1.5, "y": None, "新": "酷\n"}
cfg.save()
"##;
    let status = Command::new(python)
        .args(["-c", script])
        .arg(repo_root().join("python"))
        .env("APPDATA", &py_dir.0)
        .env("USERPROFILE", &py_dir.0)
        .status()
        .unwrap();
    assert!(status.success());
    let expected = std::fs::read(py_dir.0.join("PIME").join("chewing").join("config.json")).unwrap();

    let rs_dir = TempDir::new("save-rs");
    let mut cfg = ChewingConfig::with_dirs(rs_dir.0.clone(), rs_dir.0.clone(), false);
    let mut colors = Map::new();
    colors.insert("panelBackground".into(), json!("#FFF\"\\"));
    colors.insert("x".into(), json!(1.5));
    colors.insert("y".into(), Value::Null);
    colors.insert("新".into(), json!("酷\n"));
    cfg.set("candidateColors", Value::Object(colors));
    assert!(cfg.save());
    let got = std::fs::read(rs_dir.0.join("PIME").join("chewing").join("config.json")).unwrap();
    assert_eq!(String::from_utf8_lossy(&got), String::from_utf8_lossy(&expected));
}

#[test]
fn load_writes_defaults_and_reads_them_back() {
    let dir = TempDir::new("load");
    let cfg = ChewingConfig::with_dirs(dir.0.clone(), dir.0.clone(), true);
    let file = dir.0.join("PIME").join("chewing").join("config.json");
    assert!(file.exists());
    assert_eq!(cfg.int("candPerPage"), 9);
    std::fs::write(&file, "\u{feff}{\"candPerPage\": 5, \"bad\": 1}").unwrap();
    let cfg = ChewingConfig::with_dirs(dir.0.clone(), dir.0.clone(), true);
    assert_eq!(cfg.int("candPerPage"), 5);
    assert!(cfg.to_json().get("bad").is_none());
    // a broken file is kept (and copied aside), the settings stay as they were
    std::fs::write(&file, "{\"candPerPage\": 5,}").unwrap();
    let cfg = ChewingConfig::with_dirs(dir.0.clone(), dir.0.clone(), true);
    assert_eq!(cfg.int("candPerPage"), 9);
    assert_eq!(std::fs::read_to_string(&file).unwrap(), "{\"candPerPage\": 5,}");
    let backups = std::fs::read_dir(file.parent().unwrap()).unwrap().filter(|e| {
        e.as_ref().unwrap().file_name().to_string_lossy().starts_with("config.json.broken-")
    });
    assert_eq!(backups.count(), 1);
}

#[test]
fn ansi_symbol_files_become_utf8_with_a_backup() {
    let dir = TempDir::new("ansi");
    let config_dir = dir.0.join("PIME").join("chewing");
    std::fs::create_dir_all(&config_dir).unwrap();
    let ansi = b"A \xa1\x40\xa1\xf5\nB \xa4\xa4\n".to_vec();
    std::fs::write(config_dir.join("swkb.dat"), &ansi).unwrap();
    std::fs::write(config_dir.join("symbols.dat"), "\u{2026}\n\n\r\nx=y\n\nend").unwrap();
    let _cfg = ChewingConfig::with_dirs(dir.0.clone(), dir.0.clone(), true);
    let converted = std::fs::read(config_dir.join("swkb.dat")).unwrap();
    assert_eq!(String::from_utf8(converted).unwrap(), crate::config::decode_mbcs(&ansi).unwrap());
    assert_eq!(std::fs::read(config_dir.join("swkb.dat.ansi-backup")).unwrap(), ansi);
    assert_eq!(std::fs::read_to_string(config_dir.join("symbols.dat")).unwrap(), "\u{2026}\nx=y\nend");
}

fn legacy_sqlite(path: &Path) {
    let conn = rusqlite::Connection::open(path).unwrap();
    let cols: Vec<String> = (0..11).map(|i| format!("phone_{}", i)).collect();
    conn.execute_batch(&format!(
        "CREATE TABLE config_v1 (id INTEGER, value INTEGER, PRIMARY KEY (id));
         CREATE TABLE userphrase_v1 (time INTEGER, user_freq INTEGER, max_freq INTEGER, orig_freq INTEGER,
            length INTEGER, {}, phrase TEXT, PRIMARY KEY ({}, phrase));",
        cols.iter().map(|c| format!("{} INTEGER", c)).collect::<Vec<_>>().join(", "),
        cols.join(", ")
    ))
    .unwrap();
    for (freq, phrase) in [(9318, "測試"), (9900, "策事")] {
        conn.execute(
            "INSERT INTO userphrase_v1 VALUES (186613, ?1, ?1, ?1, 2, 10268, 8708, 0, 0, 0, 0, 0, 0, 0, 0, 0, ?2)",
            rusqlite::params![freq, phrase],
        )
        .unwrap();
    }
    conn.execute(
        "INSERT INTO userphrase_v1 VALUES (186613, 5, 5, 5, 2, 10268, 8708, 0, 0, 0, 0, 0, 0, 0, 0, 0, CAST(X'FFFE' AS TEXT))",
        [],
    )
    .unwrap();
}

#[test]
fn legacy_dictionary_is_converted_and_left_alone() {
    let dir = TempDir::new("legacy");
    let legacy = dir.0.join("chewing.sqlite3");
    legacy_sqlite(&legacy);
    let before = std::fs::read(&legacy).unwrap();
    let dat = userdict::prepare_user_dictionary(&dir.0, &syspath()).unwrap();
    assert_eq!(dat, dir.0.join("chewing.dat"));
    assert!(dat.exists());
    assert_eq!(std::fs::read(&legacy).unwrap(), before, "the old file must not change");
    let backup = dir.0.join("chewing-backup-before-0.13.sqlite3");
    assert!(backup.exists());
    assert_eq!(userdict::check_sqlite_user_db(&backup).unwrap(), 3);
    // the invalid phrase is dropped, the other two are there
    let mut ctx = ChewingContext::new(&syspath(), &dat.to_string_lossy(), Some(&dir.0.to_string_lossy()), true).unwrap();
    let mut phrases: Vec<String> = ctx.user_phrases().into_iter().map(|(p, _)| p).collect();
    phrases.sort();
    assert_eq!(phrases, vec!["測試".to_string(), "策事".to_string()]);
    drop(ctx);
    // no work directory is left behind; a second call keeps the converted file
    let leftovers: Vec<_> = std::fs::read_dir(&dir.0).unwrap().map(|e| e.unwrap().file_name()).collect();
    assert!(leftovers.iter().all(|n| !n.to_string_lossy().starts_with("migrate_")), "{:?}", leftovers);
    let modified = std::fs::metadata(&dat).unwrap().modified().unwrap();
    userdict::prepare_user_dictionary(&dir.0, &syspath()).unwrap();
    assert_eq!(std::fs::metadata(&dat).unwrap().modified().unwrap(), modified);
}

#[test]
fn broken_legacy_dictionary_is_not_converted() {
    let dir = TempDir::new("broken");
    std::fs::write(dir.0.join("chewing.sqlite3"), "not a database\n").unwrap();
    assert!(userdict::prepare_user_dictionary(&dir.0, &syspath()).is_err());
    assert!(!dir.0.join("chewing.dat").exists());
    assert_eq!(std::fs::read(dir.0.join("chewing.sqlite3")).unwrap(), b"not a database\n");
}

#[test]
fn empty_legacy_dictionary_gives_an_empty_one() {
    let dir = TempDir::new("empty");
    std::fs::write(dir.0.join("chewing.sqlite3"), "").unwrap();
    let dat = userdict::prepare_user_dictionary(&dir.0, &syspath()).unwrap();
    assert!(dat.exists());
    assert!(!dir.0.join("chewing-backup-before-0.13.sqlite3").exists());
    assert_eq!(std::fs::metadata(dir.0.join("chewing.sqlite3")).unwrap().len(), 0);
}

#[test]
fn engine_types_a_word() {
    let mut ctx = ChewingContext::new(&syspath(), ":memory:", None, true).unwrap();
    for key in "su3cl3".chars() {
        ctx.handle_default(key as i32);
    }
    assert_eq!(ctx.buffer_string(), "你好");
    ctx.handle_named("Enter");
    assert!(ctx.commit_check());
    assert_eq!(ctx.commit_string(), "你好");
    assert_eq!(super::engine::version(), "0.13.1");
}
