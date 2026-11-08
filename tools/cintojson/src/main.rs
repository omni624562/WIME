//! Converts the cinbase `*.cin` tables (python/cinbase/cin) to the JSON the
//! backend loads (python/cinbase/json), a line-by-line port of
//! python/cinbase/tools/cintojson.py: the output is byte-identical to the
//! Python tool's (keys sorted, no indentation, non-ASCII unescaped).
//!
//! Usage (defaults are the repository's directories, found from this crate's
//! location, so it runs from any working directory):
//!
//!     wime-cintojson                       convert every *.cin whose JSON is
//!                                          missing or older (batch mode),
//!                                          copy the *.txt notices along
//!     wime-cintojson <file.cin> [sort]     convert one table (sort: merge the
//!                                          chardefs by charset, like
//!                                          cnscj.cin / CnsPhonetic.cin)
//!     --cin-dir DIR / --json-dir DIR       override the directories

use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use serde_json::{json, Value};

const CIN_HEAD: &str = "%gen_inp";
const ENAME_HEAD: &str = "%ename";
const CNAME_HEAD: &str = "%cname";
const ENCODING_HEAD: &str = "%encoding";
const SELKEY_HEAD: &str = "%selkey";
const KEYNAME_HEAD: &str = "%keyname";
const CHARDEF_HEAD: &str = "%chardef";

/// Tables whose key names contain '#': only comment lines of the header are
/// skipped there (haveHashtagInKeynames)
const HASHTAG_IN_KEYNAMES: [&str; 4] = ["ez.cin", "ezsmall.cin", "ezmid.cin", "ezbig.cin"];
/// Batch mode merges these by charset (sortList)
const SORT_LIST: [&str; 2] = ["cnscj.cin", "CnsPhonetic.cin"];

/// Python's 'big5' codec class of U+4E00..U+9FEA (gen_big5_classes.py):
/// 0 not encodable, 1 big5F, 2 big5LF, 3 big5S, 4 big5Other
static BIG5_CLASSES: &[u8] = include_bytes!("../big5_classes.bin");
const CJK_FIRST: u32 = 0x4E00;
const CJK_END: u32 = 0x9FEB;

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
enum State {
    Head,
    Keyname,
    Chardef,
}

/// The per-charset dictionaries of getCharSet, in mergeDicts order
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
enum Set {
    Big5F,
    Big5LF,
    Big5S,
    Big5Other,
    Bopomofo,
    Cjk,
    CjkExtA,
    CjkExtB,
    CjkExtC,
    CjkExtD,
    CjkExtE,
    CjkExtF,
    CjkCIibm,
    CjkOther,
    Phrases,
    Privateuse,
}

const MERGE_ORDER: [Set; 16] = [
    Set::Big5F,
    Set::Big5LF,
    Set::Big5S,
    Set::Big5Other,
    Set::Bopomofo,
    Set::Cjk,
    Set::CjkExtA,
    Set::CjkExtB,
    Set::CjkExtC,
    Set::CjkExtD,
    Set::CjkExtE,
    Set::CjkExtF,
    Set::CjkCIibm,
    Set::CjkOther,
    Set::Phrases,
    Set::Privateuse,
];

const COUNT_KEYS: [&str; 18] = [
    "bopomofo",
    "big5F",
    "big5LF",
    "big5S",
    "big5Other",
    "cjk",
    "cjkExtA",
    "cjkExtB",
    "cjkExtC",
    "cjkExtD",
    "cjkExtE",
    "cjkExtF",
    "cjkOther",
    "phrases",
    "cjkCI",
    "cjkCIS",
    "privateuse",
    "totalchardefs",
];

type Defs = HashMap<String, Vec<String>>;

#[derive(Default)]
struct CinToJson {
    ename: String,
    cname: String,
    selkey: String,
    keynames: BTreeMap<String, String>,
    chardefs: Defs,
    dupchardefs: Defs,
    sets: HashMap<Set, Defs>,
    cincount: BTreeMap<&'static str, u64>,
}

fn push(defs: &mut Defs, key: &str, root: &str) {
    defs.entry(key.to_string()).or_default().push(root.to_string());
}

/// line[len(head):].strip()
fn head_rest(head: &str, line: &str) -> String {
    let rest: String = line.chars().skip(head.chars().count()).collect();
    rest.trim().to_string()
}

/// safeSplit: at the first space, else the first tab, else (line, "Error")
fn safe_split(line: &str) -> (String, String) {
    if let Some(i) = line.find(' ') {
        (line[..i].to_string(), line[i + 1..].to_string())
    } else if let Some(i) = line.find('\t') {
        (line[..i].to_string(), line[i + 1..].to_string())
    } else {
        (line.to_string(), "Error".to_string())
    }
}

/// A root containing an ideographic space becomes just that space, otherwise
/// it is stripped
fn normalize_root(root: &str) -> String {
    if root.contains('\u{3000}') {
        "\u{3000}".to_string()
    } else {
        root.trim().to_string()
    }
}

/// re.sub('^ | $|\n$', '', line) on a line without its newline: one leading
/// space and one trailing space go
fn trim_one_space(line: &str) -> &str {
    let line = line.strip_prefix(' ').unwrap_or(line);
    line.strip_suffix(' ').unwrap_or(line)
}

impl CinToJson {
    fn new() -> Self {
        let mut app = Self::default();
        for key in COUNT_KEYS {
            app.cincount.insert(key, 0);
        }
        app
    }

    fn count(&mut self, key: &'static str) {
        *self.cincount.get_mut(key).expect("known count key") += 1;
    }

    fn add(&mut self, set: Set, key: &str, root: &str) {
        push(self.sets.entry(set).or_default(), key, root);
    }

    /// getCharSet: files the root under its charset and counts it
    fn get_char_set(&mut self, key: &str, root: &str) {
        let mut chars = root.chars();
        let (first, second) = (chars.next(), chars.next());
        let m = match (first, second) {
            (Some(c), None) => c as u32,
            _ => {
                // len(root) > 1 (an empty root cannot reach here: safeSplit's
                // "Error" stops the file and a stripped root keeps one char)
                self.add(Set::Phrases, key, root);
                self.count("phrases");
                return;
            }
        };

        if m <= CJK_END {
            if (0x3100..0x3130).contains(&m) || matches!(m, 0x02D9 | 0x02CA | 0x02C7 | 0x02CB) {
                self.add(Set::Bopomofo, key, root);
                self.count("bopomofo");
                return;
            } else if (CJK_FIRST..CJK_END).contains(&m) {
                let (set, count) = match BIG5_CLASSES[(m - CJK_FIRST) as usize] {
                    1 => (Set::Big5F, "big5F"),
                    2 => (Set::Big5LF, "big5LF"),
                    3 => (Set::Big5S, "big5S"),
                    4 => (Set::Big5Other, "big5Other"),
                    _ => (Set::Cjk, "cjk"),
                };
                self.add(set, key, root);
                self.count(count);
                return;
            } else if (0x3400..0x4DB6).contains(&m) {
                self.add(Set::CjkExtA, key, root);
                self.count("cjkExtA");
                return;
            }
        } else {
            let ext = if (0x20000..0x2A6D7).contains(&m) {
                Some((Set::CjkExtB, "cjkExtB"))
            } else if (0x2A700..0x2B735).contains(&m) {
                Some((Set::CjkExtC, "cjkExtC"))
            } else if (0x2B740..0x2B81E).contains(&m) {
                Some((Set::CjkExtD, "cjkExtD"))
            } else if (0x2B820..0x2CEA2).contains(&m) {
                Some((Set::CjkExtE, "cjkExtE"))
            } else if (0x2CEB0..0x2EBE1).contains(&m) {
                Some((Set::CjkExtF, "cjkExtF"))
            } else {
                None
            };
            if let Some((set, count)) = ext {
                self.add(set, key, root);
                self.count(count);
                return;
            }
            if matches!(m, 0xFA0E | 0xFA0F | 0xFA11 | 0xFA13 | 0xFA14 | 0xFA1F | 0xFA21 | 0xFA23 | 0xFA24 | 0xFA27 | 0xFA28 | 0xFA29) {
                self.add(Set::CjkCIibm, key, root);
                self.count("cjkCI");
                return;
            }
            if (0xE000..0xF900).contains(&m) || (0xF0000..0xFFFFE).contains(&m) || (0x100000..0x10FFFE).contains(&m) {
                self.add(Set::Privateuse, key, root);
                self.count("privateuse");
                return;
            }
            if (0xF900..0xFA0E).contains(&m)
                || matches!(
                    m,
                    0xFA10 | 0xFA12 | 0xFA15 | 0xFA16 | 0xFA17 | 0xFA18 | 0xFA19 | 0xFA1A | 0xFA1B | 0xFA1C | 0xFA1D | 0xFA1E | 0xFA20 | 0xFA22 | 0xFA25 | 0xFA26 | 0xFA2A | 0xFA2B | 0xFA2C | 0xFA2D
                )
                || (0xFA2E..0xFB00).contains(&m)
            {
                self.add(Set::Privateuse, key, root);
                self.count("cjkCI");
                return;
            }
            if (0x2F800..0x2FA20).contains(&m) {
                self.add(Set::Privateuse, key, root);
                self.count("cjkCIS");
                return;
            }
        }
        self.add(Set::CjkOther, key, root);
        self.count("cjkOther");
    }

    /// Appends root to chardefs[key] unless it is there already (then to
    /// dupchardefs), counting totalchardefs
    fn add_chardef(&mut self, key: &str, root: &str) {
        if let Some(roots) = self.chardefs.get(key) {
            if roots.iter().any(|r| r == root) {
                push(&mut self.dupchardefs, key, root);
                return;
            }
        }
        push(&mut self.chardefs, key, root);
        self.count("totalchardefs");
    }

    fn run(&mut self, file_name: &str, text: &str, sort_by_charset: bool) {
        let hashtag_keynames = HASHTAG_IN_KEYNAMES.contains(&file_name);
        let mut state = State::Head;

        // io.open's universal newlines: \r\n, \n and \r all end a line (a
        // \r\n yields an extra empty piece here, which is skipped like any
        // empty line)
        for raw in text.split_inclusive(['\n', '\r']) {
            let raw = raw.strip_suffix('\n').or_else(|| raw.strip_suffix('\r')).unwrap_or(raw);
            let line = trim_one_space(raw);
            if hashtag_keynames {
                if line.is_empty() || (line.starts_with('#') && state == State::Head) {
                    continue;
                }
            } else if line.is_empty() || line.starts_with('#') {
                continue;
            }

            if state != State::Chardef {
                if line.contains(CIN_HEAD) {
                    continue;
                }
                if line.contains(ENAME_HEAD) {
                    self.ename = head_rest(ENAME_HEAD, line);
                }
                if line.contains(CNAME_HEAD) {
                    self.cname = head_rest(CNAME_HEAD, line);
                }
                if line.contains(ENCODING_HEAD) {
                    continue;
                }
                if line.contains(SELKEY_HEAD) {
                    self.selkey = head_rest(SELKEY_HEAD, line);
                }
                if line.contains(CHARDEF_HEAD) {
                    state = if line.contains("begin") { State::Chardef } else { State::Head };
                    continue;
                }
                if line.contains(KEYNAME_HEAD) {
                    state = if line.contains("begin") { State::Keyname } else { State::Head };
                    continue;
                }
                if state == State::Keyname {
                    let (key, root) = safe_split(line);
                    let key = key.trim().to_lowercase();
                    self.keynames.insert(key, normalize_root(&root));
                    continue;
                }
            } else {
                if line.contains(CHARDEF_HEAD) {
                    continue;
                }
                let mut line = line.to_string();
                if self.cname == "中標倉頡" {
                    // re.sub('#.+', '', line): from the first '#' that has
                    // something after it
                    if let Some(i) = line.find('#') {
                        if line[i + '#'.len_utf8()..].chars().next().is_some() {
                            line.truncate(i);
                        }
                    }
                }
                let (key, root) = safe_split(&line);
                let key = key.trim().to_lowercase();
                if root == "Error" {
                    break;
                }
                let root = normalize_root(&root);
                self.get_char_set(&key, &root);
                if !sort_by_charset {
                    self.add_chardef(&key, &root);
                }
            }
        }

        if sort_by_charset {
            self.merge_dicts();
        }
    }

    /// mergeDicts(big5F, big5LF, ..., privateuse): the per-charset
    /// dictionaries become the chardefs, in that order
    fn merge_dicts(&mut self) {
        for set in MERGE_ORDER {
            let Some(defs) = self.sets.remove(&set) else { continue };
            // the order of the keys does not matter for the output (sorted):
            // only each key's root order does, and that is per dictionary
            let mut keys: Vec<&String> = defs.keys().collect();
            keys.sort();
            for key in keys {
                for root in &defs[key] {
                    self.add_chardef(key, root);
                }
            }
            if set == Set::Privateuse {
                self.sets.insert(set, defs);
            }
        }
    }

    /// toJson() dumped with sort_keys=True, separators=(',', ':'), ensure_ascii=False
    fn to_json(&self) -> String {
        fn defs(d: &Defs) -> Value {
            let map: BTreeMap<&String, &Vec<String>> = d.iter().collect();
            json!(map)
        }
        let empty = Defs::new();
        let value = json!({
            "ename": self.ename,
            "cname": self.cname,
            "selkey": self.selkey,
            "keynames": self.keynames,
            "cincount": self.cincount,
            "chardefs": defs(&self.chardefs),
            "dupchardefs": defs(&self.dupchardefs),
            "privateuse": defs(self.sets.get(&Set::Privateuse).unwrap_or(&empty)),
        });
        serde_json::to_string(&value).expect("JSON of strings and integers")
    }
}

fn json_name(cin_file: &str) -> String {
    format!("{}.json", cin_file.strip_suffix(".cin").unwrap_or(cin_file))
}

fn mtime(path: &Path) -> Option<SystemTime> {
    fs::metadata(path).and_then(|m| m.modified()).ok()
}

/// _jsonUpToDate: the JSON is newer than the table and than this tool
fn up_to_date(cin_file: &Path, json_file: &Path, tool: Option<SystemTime>) -> bool {
    match (mtime(json_file), mtime(cin_file)) {
        (Some(json), Some(cin)) => json >= cin && tool.map_or(true, |t| json >= t),
        _ => false,
    }
}

fn convert(cin_dir: &Path, json_dir: &Path, file_name: &str, sort_by_charset: bool) -> Result<(), String> {
    let cin_file = cin_dir.join(file_name);
    let text = fs::read_to_string(&cin_file).map_err(|e| format!("{}: {}", cin_file.display(), e))?;
    let mut app = CinToJson::new();
    app.run(file_name, &text, sort_by_charset);
    make_json_dir(json_dir)?;
    let json_file = json_dir.join(json_name(file_name));
    fs::write(&json_file, app.to_json()).map_err(|e| format!("{}: {}", json_file.display(), e))
}

fn make_json_dir(json_dir: &Path) -> Result<(), String> {
    let mut builder = fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(json_dir).map_err(|e| format!("{}: {}", json_dir.display(), e))
}

/// Batch mode: every *.cin whose JSON is missing or older, and the *.txt
/// notices (kept with the tables: the installer packs json/ without cin/)
fn convert_all(cin_dir: &Path, json_dir: &Path) -> Result<(), String> {
    make_json_dir(json_dir)?;
    let tool = std::env::current_exe().ok().and_then(|p| mtime(&p));
    let mut names: Vec<String> = fs::read_dir(cin_dir)
        .map_err(|e| format!("{}: {}", cin_dir.display(), e))?
        .filter_map(|e| e.ok())
        .filter_map(|e| e.file_name().into_string().ok())
        .collect();
    names.sort();
    for name in names {
        let src = cin_dir.join(&name);
        if name.ends_with(".txt") {
            let dst = json_dir.join(&name);
            if !up_to_date(&src, &dst, None) {
                fs::copy(&src, &dst).map_err(|e| format!("{}: {}", dst.display(), e))?;
                if let Some(t) = mtime(&src) {
                    let _ = fs::File::options().write(true).open(&dst).and_then(|f| f.set_modified(t));
                }
            }
        }
        if name.ends_with(".cin") {
            if up_to_date(&src, &json_dir.join(json_name(&name)), tool) {
                continue;
            }
            println!("轉換 {} 中...", name);
            convert(cin_dir, json_dir, &name, SORT_LIST.contains(&name.as_str()))?;
        }
    }
    Ok(())
}

fn main() {
    let repo_cinbase = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..").join("python").join("cinbase");
    let mut cin_dir = repo_cinbase.join("cin");
    let mut json_dir = repo_cinbase.join("json");
    let mut positional: Vec<String> = Vec::new();
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--cin-dir" => cin_dir = PathBuf::from(args.next().unwrap_or_default()),
            "--json-dir" => json_dir = PathBuf::from(args.next().unwrap_or_default()),
            "-h" | "--help" => {
                println!("usage: wime-cintojson [--cin-dir DIR] [--json-dir DIR] [<file.cin> [sort]]");
                return;
            }
            _ => positional.push(arg),
        }
    }

    let result = match positional.as_slice() {
        [] => convert_all(&cin_dir, &json_dir),
        [file, rest @ ..] => {
            if cin_dir.join(file).exists() {
                convert(&cin_dir, &json_dir, file, rest.first().map(String::as_str) == Some("sort"))
            } else {
                Ok(()) // like the Python tool: a missing table is not an error
            }
        }
    };
    if let Err(message) = result {
        eprintln!("wime-cintojson: {}", message);
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(name: &str, text: &str, sort: bool) -> (CinToJson, Value) {
        let mut app = CinToJson::new();
        app.run(name, text, sort);
        let value: Value = serde_json::from_str(&app.to_json()).unwrap();
        (app, value)
    }

    const SAMPLE: &str = "%gen_inp\n%ename test\n%cname 測試\n%selkey 1234\n%keyname begin\na 日\nb\t月\n%keyname end\n%chardef begin\na 日\na 明\na 日\nab 日月\nb 　\nc 鿰\n%chardef end\n";

    #[test]
    fn header_keynames_and_chardefs() {
        let (_, v) = run("test.cin", SAMPLE, false);
        assert_eq!(v["ename"], "test");
        assert_eq!(v["cname"], "測試");
        assert_eq!(v["selkey"], "1234");
        assert_eq!(v["keynames"], json!({"a": "日", "b": "月"}));
        assert_eq!(v["chardefs"], json!({"a": ["日", "明"], "ab": ["日月"], "b": ["\u{3000}"], "c": ["鿰"]}));
        assert_eq!(v["dupchardefs"], json!({"a": ["日"]}));
        assert_eq!(v["cincount"]["totalchardefs"], 5);
        assert_eq!(v["cincount"]["phrases"], 1);
        assert_eq!(v["cincount"]["big5F"], 3); // 日 明 and the duplicate 日 (counted before dedupe)
        assert_eq!(v["cincount"]["cjkOther"], 2); // the ideographic space, 鿰 (U+9FF0 is past the CJK range)
    }

    #[test]
    fn cjk_not_in_big5_counts_as_cjk() {
        let i = BIG5_CLASSES.iter().position(|&c| c == 0).unwrap();
        let ch = char::from_u32(CJK_FIRST + i as u32).unwrap();
        let (_, v) = run("t.cin", &format!("%chardef begin\na {}\n%chardef end\n", ch), false);
        assert_eq!(v["cincount"]["cjk"], 1);
        assert_eq!(v["cincount"]["big5F"], 0);
    }

    #[test]
    fn output_is_compact_sorted_and_unescaped() {
        let mut app = CinToJson::new();
        app.run("test.cin", "%cname 中\n%chardef begin\nz 字\n%chardef end\n", false);
        let text = app.to_json();
        assert!(text.starts_with(r#"{"chardefs":{"z":["字"]},"cincount":{"big5F":1,"#));
        assert!(text.ends_with(r#""privateuse":{},"selkey":""}"#));
        assert!(!text.contains('\\'));
        assert!(!text.contains(' '));
    }

    #[test]
    fn sort_mode_merges_by_charset() {
        // 鿰 (cjk) before 日 (big5F) in the file; merged order puts big5F first
        let (_, v) = run("cnscj.cin", "%chardef begin\na 鿰\na 日\na 日\n%chardef end\n", true);
        assert_eq!(v["chardefs"], json!({"a": ["日", "鿰"]}));
        assert_eq!(v["dupchardefs"], json!({"a": ["日"]}));
        assert_eq!(v["cincount"]["totalchardefs"], 2);
    }

    #[test]
    fn hashtag_tables_keep_comment_like_roots() {
        let text = "# notice\n%keyname begin\n# 井\n%keyname end\n%chardef begin\n# 井\n%chardef end\n";
        let (_, v) = run("ez.cin", text, false);
        assert_eq!(v["keynames"], json!({"#": "井"}));
        assert_eq!(v["chardefs"], json!({"#": ["井"]}));
        let (_, v) = run("other.cin", text, false);
        assert_eq!(v["chardefs"], json!({}));
    }

    #[test]
    fn error_root_stops_the_file_and_zhongbiao_strips_comments() {
        let (_, v) = run("t.cin", "%cname 中標倉頡\n%chardef begin\na 日#註解\nbroken\nb 月\n%chardef end\n", false);
        assert_eq!(v["chardefs"], json!({"a": ["日"]}));
    }

    #[test]
    fn windows_newlines_and_one_space_trim() {
        let (_, v) = run("t.cin", "%ename x\r\n%chardef begin\r\n a 日 \r\n%chardef end\r\n", false);
        assert_eq!(v["ename"], "x");
        assert_eq!(v["chardefs"], json!({"a": ["日"]}));
    }

    #[test]
    fn private_use_and_compatibility_counts() {
        let (_, v) = run("t.cin", "%chardef begin\na \u{E000}\nb \u{FA0E}\nc \u{F900}\nd \u{2F800}\ne ㄅ\n%chardef end\n", false);
        assert_eq!(v["privateuse"], json!({"a": ["\u{E000}"], "c": ["\u{F900}"], "d": ["\u{2F800}"]}));
        assert_eq!(v["cincount"]["privateuse"], 1);
        assert_eq!(v["cincount"]["cjkCI"], 2);
        assert_eq!(v["cincount"]["cjkCIS"], 1);
        assert_eq!(v["cincount"]["bopomofo"], 1);
    }
}
