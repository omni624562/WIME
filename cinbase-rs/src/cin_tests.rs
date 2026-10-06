//! Tests of cin.rs / rcin.rs / hcin.rs against python/cinbase itself:
//! tools/dump_cin_reference.py runs the Python classes on the real tables
//! (python/cinbase/json, generated and gitignored) and on synthetic count
//! files, and these tests replay the same calls in Rust.
//!
//! The reference is generated at test time with `python` (or `WIME_TEST_PYTHON`);
//! `WIME_CIN_REF=<file>` reuses a dump. Without Python the comparison tests are
//! skipped (set `WIME_REQUIRE_PY_REF=1` to make that a failure); tables missing
//! from python/cinbase/json are skipped by the dump itself.

use super::*;
use crate::hcin::HCin;
use crate::rcin::RCin;
use serde_json::Value as J;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::OnceLock;

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn json_dir() -> PathBuf {
    manifest_dir().join("..").join("python").join("cinbase").join("json")
}

fn reference() -> Option<&'static J> {
    static REF: OnceLock<Option<J>> = OnceLock::new();
    REF.get_or_init(|| {
        let path = match std::env::var("WIME_CIN_REF") {
            Ok(p) if !p.is_empty() => PathBuf::from(p),
            _ => {
                let out = std::env::temp_dir().join(format!("wime_cin_ref_{}.json", std::process::id()));
                let script = manifest_dir().join("tools").join("dump_cin_reference.py");
                let python = std::env::var("WIME_TEST_PYTHON").unwrap_or_else(|_| "python".into());
                let status = std::process::Command::new(python).arg(&script).arg(&out).arg(json_dir()).status();
                match status {
                    Ok(s) if s.success() => out,
                    other => {
                        assert!(std::env::var("WIME_REQUIRE_PY_REF").is_err(), "python reference dump failed: {:?}", other);
                        eprintln!("SKIP: cannot run {} ({:?})", script.display(), other);
                        return None;
                    }
                }
            }
        };
        let text = std::fs::read_to_string(&path).expect("reference dump");
        Some(serde_json::from_str(&text).expect("reference JSON"))
    })
    .as_ref()
}

static DIR_COUNTER: AtomicUsize = AtomicUsize::new(0);

/// A count directory for tables whose counts are never written (no count
/// file in it, nothing added); reused across runs.
fn shared_count_dir() -> PathBuf {
    std::env::temp_dir().join("wime_cin_test_shared")
}

/// A fresh, empty count directory under the system temp dir.
fn temp_count_dir() -> PathBuf {
    let n = DIR_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!("wime_cin_test_{}_{}", std::process::id(), n));
    let _ = std::fs::remove_dir_all(&dir);
    dir
}

fn strs(v: &J) -> Vec<String> {
    v.as_array().unwrap().iter().map(|s| s.as_str().unwrap().to_string()).collect()
}

fn s(v: &J) -> &str {
    v.as_str().unwrap()
}

fn res_json<T: Into<J>>(r: Result<T, String>) -> J {
    match r {
        Ok(v) => v.into(),
        Err(_) => J::String("ERR".into()),
    }
}

fn fnv(chunks: impl IntoIterator<Item = Vec<u8>>) -> String {
    let mut h: u64 = 0xcbf29ce484222325;
    for chunk in chunks {
        for b in chunk {
            h ^= b as u64;
            h = h.wrapping_mul(0x100000001b3);
        }
    }
    format!("{:016x}", h)
}

fn chardefs_digest(chardefs: &IndexMap<String, Vec<String>>) -> String {
    let mut chunks = Vec::new();
    for (k, vs) in chardefs {
        chunks.push([k.as_bytes(), b"\x00"].concat());
        for v in vs {
            chunks.push([v.as_bytes(), b"\x01"].concat());
        }
        chunks.push(b"\x02".to_vec());
    }
    fnv(chunks)
}

fn reverse_digest(chars: &[String], keys_of: impl Fn(&str) -> Vec<String>) -> String {
    let mut sorted: Vec<&String> = chars.iter().collect();
    sorted.sort();
    let mut chunks = Vec::new();
    for ch in sorted {
        chunks.push([ch.as_bytes(), b"\x00"].concat());
        for k in keys_of(ch) {
            chunks.push([k.as_bytes(), b"\x01"].concat());
        }
        chunks.push(b"\x02".to_vec());
    }
    fnv(chunks)
}

fn cin_reverse_digest(c: &Cin) -> String {
    let chars: Vec<String> = c.char_to_keys.keys().cloned().collect();
    reverse_digest(&chars, |ch| c.char_to_keys[ch].clone())
}

fn bits(v: impl Iterator<Item = bool>) -> String {
    v.map(|b| if b { '1' } else { '0' }).collect()
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect()
}

fn file_hex(dir: &Path) -> J {
    match std::fs::read(dir.join(COUNT_FILE_NAME)) {
        Ok(b) => J::String(hex(&b)),
        Err(_) => J::Null,
    }
}

fn has_backup(dir: &Path) -> bool {
    std::fs::read_dir(dir)
        .map(|rd| rd.flatten().any(|e| e.file_name().to_string_lossy().starts_with("cincount.json.broken-")))
        .unwrap_or(false)
}

fn chardefs_json(m: &IndexMap<String, Vec<String>>) -> String {
    let mut out = String::from("{");
    for (i, (k, vs)) in m.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        py_json_str(&mut out, k);
        out.push_str(":[");
        for (j, v) in vs.iter().enumerate() {
            if j > 0 {
                out.push(',');
            }
            py_json_str(&mut out, v);
        }
        out.push(']');
    }
    out.push('}');
    out
}

/// Runs `f` on a fresh thread: a fresh virtual clock at env::CLOCK_START.
fn with_clock<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> T {
    std::thread::spawn(move || {
        env::set_test_mode(true);
        f()
    })
    .join()
    .unwrap()
}

// ---------------------------------------------------------------------------

#[test]
fn big5_table_matches_generator_size() {
    assert_eq!(BIG5_CHARSET.len(), (CJK_END - CJK_FIRST) as usize);
}

#[test]
fn charset_matches_python() {
    let Some(r) = reference() else { return };
    let rle = r["charset_rle"].as_array().unwrap();
    for (i, item) in rle.iter().enumerate() {
        let start = item[0].as_u64().unwrap() as u32;
        let end = rle.get(i + 1).map(|n| n[0].as_u64().unwrap() as u32).unwrap_or(0x110000);
        let name = s(&item[1]);
        for cp in start..end {
            if let Some(c) = char::from_u32(cp) {
                assert_eq!(char_set(c), name, "U+{:04X}", cp);
            }
        }
    }
}

fn check_queries(c: &Cin, q: &J, label: &str) {
    let prefixes = strs(&q["prefix_queries"]);
    assert_eq!(bits(prefixes.iter().map(|p| c.is_char_def_prefix(p))), s(&q["isPrefix"]), "{} isCharDefPrefix", label);
    assert_eq!(bits(prefixes.iter().map(|p| c.has_longer_char_def_prefix(p))), s(&q["hasLonger"]), "{} hasLonger", label);
    assert_eq!(bits(prefixes.iter().map(|p| c.is_in_char_def(p))), s(&q["inCharDef"]), "{} isInCharDef", label);
    for (key, want) in strs(&q["chardef_queries"]).iter().zip(q["chardefs"].as_array().unwrap()) {
        assert_eq!(c.get_char_def(key), strs(want), "{} getCharDef {:?}", label, key);
    }
    let chars = strs(&q["encode_queries"]);
    for ((ch, enc), key) in chars.iter().zip(q["encodes"].as_array().unwrap()).zip(q["getKey"].as_array().unwrap()) {
        assert_eq!(c.get_char_encode(ch), s(enc), "{} getCharEncode {:?}", label, ch);
        assert_eq!(res_json(c.get_key(ch)), *key, "{} getKey {:?}", label, ch);
        assert_eq!(c.is_have_key(ch), key != "ERR", "{} isHaveKey {:?}", label, ch);
    }
    for pair in q["keyName"].as_array().unwrap() {
        assert_eq!(c.get_key_name(s(&pair[0])), s(&pair[1]), "{} getKeyName", label);
    }
    for item in q["wildcard"].as_array().unwrap() {
        let (comp, wc, limit, variable) = (s(&item[0]), s(&item[1]), item[2].as_i64().unwrap(), item[3].as_bool().unwrap());
        let got = res_json(c.get_wildcard_char_defs(comp, wc, limit, variable));
        assert_eq!(got, item[4], "{} wildcard {:?} {:?} {} {}", label, comp, wc, limit, variable);
    }
}

#[test]
fn tables_match_python() {
    let Some(r) = reference() else { return };
    for t in r["tables"].as_array().unwrap() {
        let file = s(&t["file"]);
        let ignore = t["ignorePUA"].as_bool().unwrap();
        let label = format!("{} ignorePUA={}", file, ignore);
        let path = json_dir().join(file);
        let started = std::time::Instant::now();
        let mut c = Cin::load(&path, "x", ignore, shared_count_dir()).unwrap();
        eprintln!("{}: loaded in {:?}", label, started.elapsed());
        assert_eq!(c.get_ename(), s(&t["ename"]));
        assert_eq!(c.get_cname(), s(&t["cname"]));
        assert_eq!(c.get_selection(), s(&t["selkey"]));
        let keynames: Vec<J> = c.keynames().iter().map(|(k, v)| J::from(vec![k.clone(), v.clone()])).collect();
        assert_eq!(J::from(keynames), t["keynames"]);
        assert_eq!(cincount_json(c.cincount()), s(&t["cincount"]), "{} stats key dropped", label);
        assert_eq!(chardefs_digest(c.chardefs()), s(&t["digest_chardefs"]), "{} chardefs", label);
        assert_eq!(cin_reverse_digest(&c), s(&t["digest_reverse"]), "{} reverse index", label);
        assert_eq!(fnv(c.sorted_char_def_keys().iter().map(|k| [k.as_bytes(), b"\x00"].concat())), s(&t["sorted_digest"]));
        check_queries(&c, &t["queries"], &label);

        let ext: IndexMap<String, Vec<String>> =
            t["extend"].as_array().unwrap().iter().map(|p| (s(&p[0]).to_string(), strs(&p[1]))).collect();
        let keys: Vec<String> = c.chardefs().keys().cloned().collect();
        for after in t["after_update"].as_array().unwrap() {
            let priority = after["priority"].as_bool().unwrap();
            let mut c2 = Cin::load(&path, "x", ignore, shared_count_dir()).unwrap();
            c2.get_wildcard_char_defs("*", "*", 100, false).unwrap();
            c2.is_char_def_prefix(&keys[0]);
            c2.update_cin_table(true, priority, &ext, ignore);
            c2.update_cin_table(false, priority, &ext, ignore);
            let l2 = format!("{} after update priority={}", label, priority);
            assert_eq!(chardefs_digest(c2.chardefs()), s(&after["digest_chardefs"]), "{}", l2);
            assert_eq!(cin_reverse_digest(&c2), s(&after["digest_reverse"]), "{}", l2);
            check_queries(&c2, &after["queries"], &l2);
        }

        c.close();
        let ac = &t["after_close"];
        for ((ch, enc), key) in strs(&ac["chars"]).iter().zip(ac["encodes"].as_array().unwrap()).zip(ac["getKey"].as_array().unwrap()) {
            assert_eq!(c.get_char_encode(ch), s(enc), "{} after close", label);
            assert_eq!(res_json(c.get_key(ch)), *key, "{} after close", label);
        }
        let pre: Vec<J> = keys[..20].iter().map(|k| J::Bool(c.is_char_def_prefix(k))).collect();
        assert_eq!(J::from(pre), ac["isPrefix"]);
        assert_eq!(J::from(c.get_wildcard_char_defs("*", "*", 100, false).unwrap()), ac["wild"]);
    }
}

#[test]
fn rcin_hcin_match_python() {
    let Some(r) = reference() else { return };
    for t in r["rtables"].as_array().unwrap() {
        let file = s(&t["file"]);
        let path = json_dir().join(file);
        let chars = strs(&t["chars"]);
        let codes = strs(&t["codes"]);
        let label = format!("{} {}", s(&t["kind"]), file);
        if s(&t["kind"]) == "RCin" {
            let mut rc = RCin::load(&path, "x").unwrap();
            assert_eq!((rc.get_ename(), rc.get_cname(), rc.get_selection()), (s(&t["ename"]), s(&t["cname"]), s(&t["selkey"])));
            assert_eq!(chardefs_digest(rc.chardefs()), s(&t["digest_chardefs"]), "{}", label);
            let all: Vec<String> = rc.chardefs().values().flatten().cloned().collect::<HashSet<_>>().into_iter().collect();
            let idx = build_reverse_index(rc.chardefs());
            assert_eq!(reverse_digest(&all, |ch| idx[ch].clone()), s(&t["digest_reverse"]), "{}", label);
            for (i, ch) in chars.iter().enumerate() {
                assert_eq!(rc.get_char_encode(ch), s(&t["encodes"][i]), "{} {:?}", label, ch);
                assert_eq!(res_json(rc.get_key(ch)), t["getKey"][i], "{} {:?}", label, ch);
                assert_eq!(J::Bool(rc.is_have_key(ch)), t["isHaveKey"][i]);
            }
            for (i, code) in codes.iter().enumerate() {
                assert_eq!(res_json(rc.get_char_def(code).map(|v| v.to_vec())), t["chardefs"][i], "{} {:?}", label, code);
            }
            rc.close();
            for (i, ch) in chars.iter().take(20).enumerate() {
                assert_eq!(rc.get_char_encode(ch), s(&t["after_close"][i]));
            }
        } else {
            let mut hc = HCin::load(&path, "x").unwrap();
            assert_eq!((hc.get_ename(), hc.get_cname(), hc.get_selection()), (s(&t["ename"]), s(&t["cname"]), s(&t["selkey"])));
            assert_eq!(chardefs_digest(hc.chardefs()), s(&t["digest_chardefs"]), "{}", label);
            for (i, ch) in chars.iter().enumerate() {
                assert_eq!(hc.get_char_encode(ch), s(&t["encodes"][i]), "{} {:?}", label, ch);
                assert_eq!(res_json(hc.get_key(ch)), t["getKey"][i], "{} {:?}", label, ch);
                assert_eq!(J::Bool(hc.is_have_key(ch)), t["isHaveKey"][i]);
                let kl = hc.get_key_list(ch);
                assert_eq!(J::from(kl.clone()), t["keyList"][i], "{} getKeyList {:?}", label, ch);
                assert_eq!(J::from(hc.get_key_name_list(&kl)), t["keyNameList"][i], "{} getKeyNameList {:?}", label, ch);
            }
            for (i, code) in codes.iter().enumerate() {
                assert_eq!(res_json(hc.get_char_def(code).map(|v| v.to_vec())), t["chardefs"][i], "{} {:?}", label, code);
            }
            hc.close();
            for (i, ch) in chars.iter().take(20).enumerate() {
                assert_eq!(hc.get_char_encode(ch), s(&t["after_close"][i]));
            }
        }
    }
}

#[test]
fn normalize_and_trim_match_python() {
    let Some(r) = reference() else { return };
    for case in r["counts"]["normalize"].as_array().unwrap() {
        let text = s(&case[0]);
        let value = py_json_parse(text).unwrap();
        match normalize_count_entry(&value) {
            Err(_) => assert_eq!(case[1], "ERR", "normalize {}", text),
            Ok(n) => {
                let mut out = String::new();
                count_entry_json(&mut out, &n);
                assert_eq!(out, s(&case[1]), "normalize {}", text);
                assert_eq!(!count_entry_equals(&n, &value), case[2].as_bool().unwrap(), "changed {}", text);
            }
        }
    }
    for case in r["counts"]["trim"].as_array().unwrap() {
        let PyVal::Dict(prev) = py_json_parse(s(&case[0])).unwrap() else { panic!() };
        let prev: IndexMap<String, i64> = prev.into_iter().map(|(k, v)| (k, if let PyVal::Int(i) = v { i } else { panic!() })).collect();
        let got = trim_context_counts(&prev, s(&case[1]));
        let entry = CountEntry { count: 0, last: PyNum::Int(0), prev: got };
        let mut out = String::new();
        count_entry_json(&mut out, &entry);
        let want = format!("{{\"count\":0,\"last\":0,\"prev\":{}}}", s(&case[2]));
        assert_eq!(out, want, "trim {} keep {:?}", s(&case[0]), s(&case[1]));
    }
}

#[test]
fn tiny_table_matches_python() {
    let Some(r) = reference() else { return };
    let table = s(&r["tiny_table"]);
    for ignore in [false, true] {
        let want = &r["tiny"][format!("ignore{}", ignore as u8)];
        let c = Cin::from_json(table, "x", ignore, shared_count_dir()).unwrap();
        assert_eq!(chardefs_json(c.chardefs()), s(&want["chardefs"]));
        assert_eq!(cincount_json(c.cincount()), s(&want["cincount"]));
        assert_eq!(c.get_char_encode("曰"), s(&want["encode"]));
        assert_eq!(J::from(c.get_wildcard_char_defs("*", "*", 100, true).unwrap()), want["wild"]);
    }
    let bad = Cin::from_json(s(&r["tiny"]["bad_privateuse_text"]), "x", true, shared_count_dir());
    assert_eq!(bad.is_err(), r["tiny"]["bad_privateuse"] == "ERR");
}

#[test]
fn count_file_loading_matches_python() {
    let Some(r) = reference() else { return };
    let table = s(&r["tiny_table"]).to_string();
    for case in r["load"].as_array().unwrap() {
        let case = case.clone();
        let table = table.clone();
        with_clock(move || {
            let dir = temp_count_dir();
            std::fs::create_dir_all(&dir).unwrap();
            std::fs::write(dir.join(COUNT_FILE_NAME), unhex(s(&case["file_hex"]))).unwrap();
            let mut c = Cin::from_json(&table, "x", false, dir.clone()).unwrap();
            let label = s(&case["file_hex"]).to_string();
            assert_eq!(cincount_json(c.cincount()), s(&case["cincount"]), "load {}", label);
            assert_eq!(c.count_dirty(), case["dirty"].as_bool().unwrap(), "dirty {}", label);
            assert_eq!(has_backup(&dir), case["backup"].as_bool().unwrap(), "backup {}", label);
            c.save_count_file(true).unwrap();
            assert_eq!(file_hex(&dir), case["saved_hex"], "saved {}", label);
            assert_eq!(c.count_dirty(), case["dirty_after"].as_bool().unwrap());
            c.closed = true;
            let _ = std::fs::remove_dir_all(&dir);
        });
    }
}

#[test]
fn sort_by_count_matches_python() {
    let Some(r) = reference() else { return };
    let table = s(&r["tiny_table"]).to_string();
    for case in r["sort"].as_array().unwrap() {
        let case = case.clone();
        let table = table.clone();
        with_clock(move || {
            let delta: f64 = s(&case["delta"]).parse().unwrap();
            env::advance_clock(delta);
            let dir = temp_count_dir();
            std::fs::create_dir_all(&dir).unwrap();
            std::fs::write(dir.join(COUNT_FILE_NAME), s(&case["file"])).unwrap();
            let mut c = Cin::from_json(&table, "x", false, dir.clone()).unwrap();
            for q in case["queries"].as_array().unwrap() {
                let cands = strs(&q[1]);
                let got = c.sort_by_count(s(&q[0]), &cands, s(&q[2]), q[3].as_bool().unwrap(), q[4].as_bool().unwrap());
                assert_eq!(res_json(got), q[5], "sortByCount {} {:?} in {}", delta, q, s(&case["file"]));
            }
            c.closed = true;
            let _ = std::fs::remove_dir_all(&dir);
        });
    }
}

#[test]
fn add_count_and_save_match_python() {
    let Some(r) = reference() else { return };
    let table = s(&r["tiny_table"]).to_string();
    for (n, case) in r["add"].as_array().unwrap().iter().enumerate() {
        let case = case.clone();
        let table = table.clone();
        with_clock(move || {
            let dir = temp_count_dir();
            if let Some(initial) = case["initial"].as_str() {
                std::fs::create_dir_all(&dir).unwrap();
                std::fs::write(dir.join(COUNT_FILE_NAME), initial).unwrap();
            }
            let mut c = Cin::from_json(&table, "x", false, dir.clone()).unwrap();
            for (i, op) in case["ops"].as_array().unwrap().iter().enumerate() {
                let label = format!("case {} op {} {:?}", n, i, op);
                match s(&op[0]) {
                    "add" => {
                        c.add_count(s(&op[1]), s(&op[2]), s(&op[3]));
                        assert_eq!(c.count_dirty(), op[4].as_bool().unwrap(), "{}", label);
                    }
                    "advance" => env::advance_clock(s(&op[1]).parse().unwrap()),
                    "save" => {
                        c.save_count_file(op[1].as_bool().unwrap()).unwrap();
                        assert_eq!(file_hex(&dir), op[2], "{}", label);
                        assert_eq!(c.count_dirty(), op[3].as_bool().unwrap(), "{}", label);
                    }
                    "close" => {
                        c.close();
                        assert_eq!(file_hex(&dir), op[1], "{}", label);
                    }
                    other => panic!("unknown op {}", other),
                }
            }
            let _ = std::fs::remove_dir_all(&dir);
        });
    }
}

// --- self-contained checks (no Python needed) ---

#[test]
fn float_repr_like_python() {
    let cases = [
        (0.0, "0.0"),
        (-0.0, "-0.0"),
        (1.0, "1.0"),
        (100.0, "100.0"),
        (1700000000.0, "1700000000.0"),
        (1700000000.01, "1700000000.01"),
        (0.1, "0.1"),
        (0.0001, "0.0001"),
        (0.00001, "1e-05"),
        (1e16, "1e+16"),
        (1.5e16, "1.5e+16"),
        (123456789012345.6, "123456789012345.6"),
        (9999999999999998.0, "9999999999999998.0"),
        (5e-324, "5e-324"),
        (1.7976931348623157e308, "1.7976931348623157e+308"),
        (f64::NAN, "NaN"),
        (f64::INFINITY, "Infinity"),
        (f64::NEG_INFINITY, "-Infinity"),
    ];
    for (x, want) in cases {
        assert_eq!(py_float_repr(x), want, "{}", x);
    }
}

#[test]
fn py_json_parse_like_python() {
    assert_eq!(py_json_parse(" 1 ").unwrap(), PyVal::Int(1));
    assert_eq!(py_json_parse("-0").unwrap(), PyVal::Int(0));
    assert_eq!(py_json_parse("1.0").unwrap(), PyVal::Float(1.0));
    assert_eq!(py_json_parse("1e400").unwrap(), PyVal::Float(f64::INFINITY));
    assert_eq!(py_json_parse("-Infinity").unwrap(), PyVal::Float(f64::NEG_INFINITY));
    assert!(matches!(py_json_parse("NaN").unwrap(), PyVal::Float(f) if f.is_nan()));
    assert_eq!(py_json_parse("\"\\ud83d\\ude00\"").unwrap(), PyVal::Str("😀".into()));
    for bad in ["", "01", "1.", ".5", "\u{feff}{}", "{\"a\":1,}", "[1,]", "\"\t\"", "{} x", "tru", "-"] {
        assert!(py_json_parse(bad).is_err(), "{:?}", bad);
    }
    let PyVal::Dict(m) = py_json_parse(r#"{"a":1,"b":2,"a":3}"#).unwrap() else { panic!() };
    assert_eq!(m.keys().collect::<Vec<_>>(), ["a", "b"]);
    assert_eq!(m["a"], PyVal::Int(3));
}

#[test]
fn wildcard_cache_is_lru_of_32() {
    let c = Cin::from_json(r#"{"chardefs":{"ab":["明"],"ac":["朋"],"b":["月"]}}"#, "x", false, shared_count_dir()).unwrap();
    for i in 0..40 {
        c.get_wildcard_char_defs("a*", "*", i, false).unwrap();
    }
    let cache = c.indexes.wildcard_results.borrow();
    assert_eq!(cache.len(), WILDCARD_CACHE_SIZE);
    assert_eq!(cache.front().unwrap().0 .2, 8);
    drop(cache);
    assert_eq!(c.get_wildcard_char_defs("a*", "*", 0, false).unwrap(), ["明"]);
    assert_eq!(c.get_wildcard_char_defs("*", "*", 100, true).unwrap(), ["明", "朋", "月"]);
}
