//! Parity tests against python/cinbase: tests/fixtures/dump_data.py dumps
//! what the Python parsers make of each file; `rust_dump` builds the same
//! JSON from the port. tests/fixtures/expected.json is that dump for the
//! shipped .dat/.json files (except the big phrase.json) and the tricky
//! fixtures in tests/fixtures/data; when the repo's embedded Python is present
//! the dump is also regenerated live, phrase.json included.

use super::*;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::process::Command;

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn repo_root() -> PathBuf {
    manifest_dir().parent().unwrap().to_path_buf()
}

fn shipped_dir() -> PathBuf {
    repo_root().join("python").join("cinbase").join("data")
}

fn fixture_dir() -> PathBuf {
    manifest_dir().join("tests").join("fixtures").join("data")
}

fn items(d: &CharDefs) -> Value {
    Value::Array(d.iter().map(|(k, v)| json!([k, v])).collect())
}

fn dump_symbols(t: &Symbols) -> Value {
    let mut leaves: Vec<&String> = t.leaves.iter().collect();
    leaves.sort();
    json!({
        "keynames": t.get_key_names(),
        "chardefs": Value::Array(t.chardefs.iter().filter(|(k, _)| !t.is_leaf(k)).map(|(k, v)| json!([k, v])).collect()),
        "leaves": leaves,
        "get": t.get_key_names().iter().map(|k| json!([k, t.get_char_def(k), t.is_leaf(k), t.is_in_char_def(k)])).collect::<Vec<_>>(),
        "missing": [t.get_char_def("\0missing"), t.is_leaf("\0missing"), t.is_in_char_def("\0missing")],
    })
}

fn dump_msymbols(t: &MSymbols) -> Value {
    let mut vals: Vec<&String> = Vec::new();
    for v in t.chardefs.values() {
        for x in v {
            if !vals.contains(&x) {
                vals.push(x);
            }
        }
    }
    json!({
        "keynames": t.get_key_names(),
        "chardefs": items(&t.chardefs),
        "getKey": vals.iter().map(|x| json!([x, t.is_have_key(x), t.get_key(x).unwrap()])).collect::<Vec<_>>(),
        "missing": t.is_have_key("\0missing"),
    })
}

fn dump_emoji(t: &Emoji) -> Value {
    let groups: [(&str, &CharDefs, &Vec<String>); 5] = [
        ("dingbats", &t.dingbats, &t.dingbats_keynames),
        ("emoticons", &t.emoticons, &t.emoticons_keynames),
        ("miscellaneous", &t.miscellaneous, &t.miscellaneous_keynames),
        ("pictographs", &t.pictographs, &t.pictographs_keynames),
        ("transport", &t.transport, &t.transport_keynames),
    ];
    let mut out = serde_json::Map::new();
    for (name, dict, keynames) in groups {
        out.insert(name.into(), items(dict));
        out.insert(format!("{}_keynames", name), json!(keynames));
    }
    out.insert("modifiercolor".into(), json!(t.modifiercolor));
    let mut calls = Vec::new();
    for (typ, _, keynames) in groups.iter().map(|(n, d, k)| (*n, *d, k.as_slice())).chain([("nosuchtype", &t.dingbats, &[][..])]) {
        for name in keynames.iter().map(String::as_str).chain(["\0missing"]) {
            let r = match t.get_char_def(typ, name) {
                Ok(v) => json!(v),
                Err(_) => json!({"error": true}),
            };
            calls.push(json!([typ, name, r]));
        }
    }
    out.insert("getCharDef".into(), Value::Array(calls));
    Value::Object(out)
}

fn err() -> Value {
    json!({"error": true})
}

/// Mirror of dump_data.py's PARSERS.
fn rust_dump(parser: &str, path: &Path) -> Value {
    let text = || read_data_text(path);
    let r: Result<Value, String> = match parser {
        "text" => text().map(Value::String),
        "symbols" => text().map(|t| dump_symbols(&Symbols::from_text(&t))),
        "flangs" => text().map(|t| dump_symbols(&FLangs::from_text(&t))),
        "fsymbols" => text().map(|t| {
            let t = FSymbols::from_text(&t);
            json!({"keynames": t.get_key_names(), "chardefs": items(&t.chardefs)})
        }),
        "userphrase" => text().map(|t| {
            let t = UserPhrase::from_text(&t);
            json!({"keynames": t.get_key_names(), "chardefs": items(&t.chardefs)})
        }),
        "swkb" => text().map(|t| json!({"chardefs": items(&Swkb::from_text(&t).chardefs)})),
        "extendtable" => text().map(|t| json!({"chardefs": items(&ExtendTable::from_text(&t).chardefs)})),
        "msymbols" => text().and_then(|t| MSymbols::parse(&t)).map(|t| dump_msymbols(&t)),
        "dsymbols" => text().and_then(|t| DSymbols::parse(&t)).map(|t| dump_msymbols(&t)),
        "phrase" => Phrase::from_file(path).map(|t| json!({"keynames": t.get_key_names(), "chardefs": items(&t.chardefs)})),
        "emoji" => Emoji::from_file(path).map(|t| dump_emoji(&t)),
        _ => panic!("unknown parser {}", parser),
    };
    r.unwrap_or_else(|_| err())
}

fn locate(base: &str) -> PathBuf {
    let p = fixture_dir().join(base);
    if p.exists() {
        p
    } else {
        shipped_dir().join(base)
    }
}

/// Files whose decoding depends on the ANSI code page (expected.json was
/// made on a cp950 machine).
fn acp_dependent(base: &str) -> bool {
    base.starts_with("ansi_") || base.starts_with("bad_utf8") || base.contains("cp950")
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

fn compare(expected: &serde_json::Map<String, Value>, skip_acp: bool) -> usize {
    let mut failures = Vec::new();
    let mut checked = 0;
    for (key, want) in expected {
        let (parser, base) = key.split_once('|').unwrap();
        if skip_acp && acp_dependent(base) {
            continue;
        }
        let got = rust_dump(parser, &locate(base));
        checked += 1;
        if &got != want {
            let g = serde_json::to_string(&got).unwrap();
            let w = serde_json::to_string(want).unwrap();
            let at = g.chars().zip(w.chars()).take_while(|(a, b)| a == b).count();
            let g_tail: String = g.chars().skip(at.saturating_sub(40)).take(160).collect();
            let w_tail: String = w.chars().skip(at.saturating_sub(40)).take(160).collect();
            failures.push(format!("{}\n  rust:   …{}\n  python: …{}", key, g_tail, w_tail));
        }
    }
    assert!(failures.is_empty(), "{} mismatches:\n{}", failures.len(), failures.join("\n"));
    checked
}

#[test]
fn matches_committed_python_dump() {
    let path = manifest_dir().join("tests").join("fixtures").join("expected.json");
    let text = std::fs::read_to_string(path).unwrap();
    let Value::Object(expected) = serde_json::from_str::<Value>(&text).unwrap() else { panic!() };
    let checked = compare(&expected, acp() != 950);
    assert!(checked > 100);
}

#[test]
fn matches_live_python() {
    let python = repo_root().join("python").join("python3").join("python.exe");
    if !python.exists() {
        eprintln!("skipped: {} not found", python.display());
        return;
    }
    let mut files: Vec<PathBuf> = std::fs::read_dir(fixture_dir()).unwrap().map(|e| e.unwrap().path()).collect();
    for name in [
        "symbols.dat", "fsymbols.dat", "flangs.dat", "swkb.dat", "userphrase.dat", "excludephrase.dat", "extendtable.dat",
        "msymbols.json", "dsymbols.json", "emoji.json", "phrase.json",
    ] {
        files.push(shipped_dir().join(name));
    }
    files.sort();
    let out = Command::new(&python)
        .arg(manifest_dir().join("tests").join("fixtures").join("dump_data.py"))
        .arg(repo_root())
        .args(&files)
        .output()
        .expect("run python");
    assert!(out.status.success(), "dump_data.py failed: {}", String::from_utf8_lossy(&out.stderr));
    let Value::Object(expected) = serde_json::from_slice::<Value>(&out.stdout).unwrap() else { panic!() };
    assert!(expected.contains_key("phrase|phrase.json"));
    let n = compare(&expected, false);
    assert_eq!(n, expected.len());
}

// --- direct checks of the helpers and Python behaviours ---

#[test]
fn readdatatext_decoding() {
    assert_eq!(decode_data_bytes(b"\xEF\xBB\xBFa=b"), "a=b");
    // only one BOM is removed by utf-8-sig
    assert_eq!(decode_data_bytes(b"\xEF\xBB\xBF\xEF\xBB\xBFx"), "\u{feff}x");
    assert_eq!(translate_newlines("a\r\nb\rc\n\rd"), "a\nb\nc\n\nd");
    assert_eq!(py_lines("a\nb").collect::<Vec<_>>(), vec!["a\n", "b"]);
    assert_eq!(py_lines("").count(), 0);
    assert_eq!(py_strip("\u{1c}\u{3000} x \u{85}"), "x");
    assert_eq!(py_strip("\u{feff}x"), "\u{feff}x");
}

#[test]
fn load_data_file_fallbacks() {
    let scratch = std::env::temp_dir().join(format!("cinbase-rs-data-{}", std::process::id()));
    let user = scratch.join("user");
    std::fs::create_dir_all(&user).unwrap();
    // user msymbols.json broken -> the shipped one
    std::fs::write(user.join("msymbols.json"), b"{broken").unwrap();
    // a directory named like the file: exists() but cannot be read -> next dir
    std::fs::create_dir_all(user.join("symbols.dat")).unwrap();
    std::fs::write(user.join("swkb.dat"), "q 甲\n").unwrap();
    let dirs = [user.clone(), shipped_dir()];
    let m = load_data_file(&dirs, "msymbols.json", MSymbols::parse, "{}");
    let shipped = MSymbols::parse(&read_data_text(&shipped_dir().join("msymbols.json")).unwrap()).unwrap();
    assert_eq!(m.chardefs, shipped.chardefs);
    let s = load_data_file(&dirs, "symbols.dat", Symbols::parse, "");
    assert_eq!(s.keynames, Symbols::from_text(&read_data_text(&shipped_dir().join("symbols.dat")).unwrap()).keynames);
    let k = load_data_file(&dirs, "swkb.dat", Swkb::parse, "");
    assert_eq!(k.get_char_def("Q").unwrap(), ["甲".to_string()]);
    assert!(k.get_char_def("W").is_err());
    // nothing anywhere -> empty table
    let none = load_data_file(&[scratch.join("nope")], "msymbols.json", MSymbols::parse, "{}");
    assert!(none.chardefs.is_empty() && none.keynames.is_empty());
    assert_eq!(find_file(&dirs, "swkb.dat"), Some(user.join("swkb.dat")));
    assert_eq!(find_file(&dirs, "phrase.json"), Some(shipped_dir().join("phrase.json")));
    assert!(Phrase::load(&dirs).is_some());
    assert!(Phrase::load(&[scratch.join("nope")]).is_none());
    let _ = std::fs::remove_dir_all(&scratch);
}

#[test]
fn errors_like_python() {
    let m = MSymbols::parse("{}").unwrap();
    assert_eq!(m.get_char_def("x").unwrap_err(), "KeyError: 'x'");
    assert!(m.get_key("x").is_err());
    let e = Emoji::from_file(&shipped_dir().join("emoji.json")).unwrap();
    assert!(e.get_char_def("emoticons", "nope").is_err());
    assert!(e.get_char_def("whatever", "nope").unwrap().is_empty());
    let x = ExtendTable::from_text("ABC 字\n");
    assert_eq!(x.get_char_def("abc").unwrap(), ["字".to_string()]);
    assert!(x.get_char_def("ABC").is_err());
}
