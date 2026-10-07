//! Port of python/cinbase/cin.py (class Cin): the main code table of a
//! table-based input method, plus the user's selection counts (cincount.json)
//! used by 智慧選字.
//!
//! Faithful-port notes (Python behaviour kept on purpose):
//! - the table JSON's "cincount" key (cintojson's charset statistics) is dropped
//!   so it never mixes with the user's counts;
//! - with ignorePrivateUseArea, each listed private-use value is removed once
//!   (first occurrence, list.remove) from its chardefs entry; a privateuse key
//!   missing from chardefs fails the load (KeyError);
//! - the reverse index keeps chardefs order and repeats a key once per
//!   occurrence of the char in it;
//! - getCharEncode lists at most 10 codes, `查無字根...` when there is none;
//! - getCharSet maps the Big5 symbol range (big5S) to "big5LF", and anything
//!   in U+0000..=U+9FEB that is not bopomofo / CJK / Ext A to "cjkOther";
//! - wildcard results: high-frequency charsets first (deduplicated), then the
//!   low-frequency groups in a fixed group order; the candMaxItems check of the
//!   second loop runs after every char, even skipped ones (so a limit <= the
//!   current length returns right away);
//! - `close()` (Python `__del__`) saves the counts (errors ignored) and clears
//!   keynames / cincount / chardefs / privateuse / dupchardefs but NOT the
//!   reverse index, so getKey / getCharEncode keep answering afterwards;
//! - cincount entries are normalized to {"count": int, "last": float, "prev":
//!   {str: int}}; "last" stays an int 0 when it could not be converted, which
//!   shows as `0` instead of `0.0` in the saved file.
//!
//! - cincount.json is read with a Python-json-compatible parser (NaN,
//!   Infinity, 1e400 -> inf, correctly rounded floats); a file Python cannot
//!   read (or whose count is int(inf)) is backed up as `.broken-<mtime>`; a
//!   float "last" always counts as unchanged, even NaN (float(x) is x and dict
//!   == treats identical objects as equal);
//! - sortByCount raises "math domain error" when a candidate with context has
//!   a count <= -1.
//!
//! Known differences (inputs the program never writes): ints beyond i64
//! saturate (Python ints are unbounded); int()/float() of strings accept only
//! ASCII digits (Python also takes other Unicode decimal digits); a lone
//! surrogate escape in cincount.json makes the file unreadable here; table
//! fields of an unexpected type fail the load instead of failing later.
//!
//! Python exceptions are `Err(String)` ("KeyError: ...", "ValueError: ...").

use crate::env;
use indexmap::IndexMap;
use serde_json::Value;
use std::cell::{OnceCell, RefCell};
use std::collections::{HashMap, HashSet, VecDeque};
use std::io::Write;
use std::path::{Path, PathBuf};

pub const MAX_CONTEXT_ENTRIES: usize = 32;
pub const COUNT_SAVE_INTERVAL_SECONDS: f64 = 60.0;
pub const WILDCARD_CACHE_SIZE: usize = 32;
pub const COUNT_FILE_NAME: &str = "cincount.json";

const ENCODE_NUMBERS: [&str; 10] = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];

// ---------------------------------------------------------------------------
// table JSON (shared with rcin.rs / hcin.rs)

/// The fields of a cintojson table that the Cin classes use.
#[derive(Debug, Default, Clone)]
pub struct TableData {
    pub ename: String,
    pub cname: String,
    pub selkey: String,
    pub keynames: IndexMap<String, String>,
    pub chardefs: IndexMap<String, Vec<String>>,
    pub privateuse: IndexMap<String, Vec<String>>,
    pub dupchardefs: IndexMap<String, Vec<String>>,
}

fn take_string(v: Value, name: &str) -> Result<String, String> {
    match v {
        Value::String(s) => Ok(s),
        _ => Err(format!("table field '{}' is not a string", name)),
    }
}

fn take_string_map(v: Value, name: &str) -> Result<IndexMap<String, String>, String> {
    match v {
        Value::Object(m) => m.into_iter().map(|(k, v)| Ok((k, take_string(v, name)?))).collect(),
        _ => Err(format!("table field '{}' is not an object", name)),
    }
}

fn take_list_map(v: Value, name: &str) -> Result<IndexMap<String, Vec<String>>, String> {
    match v {
        Value::Object(m) => {
            let mut out = IndexMap::with_capacity(m.len());
            for (k, v) in m {
                let list = match v {
                    Value::Array(items) => items.into_iter().map(|s| take_string(s, name)).collect::<Result<Vec<_>, _>>()?,
                    _ => return Err(format!("table field '{}' has a non-list value", name)),
                };
                out.insert(k, list);
            }
            Ok(out)
        }
        _ => Err(format!("table field '{}' is not an object", name)),
    }
}

/// Parses a table JSON (what `self.__dict__.update(data)` picks up). Unknown
/// keys are ignored, missing ones keep their empty defaults. "cincount" is not
/// read (Cin drops it; RCin / HCin never use it).
pub fn parse_table(text: &str) -> Result<TableData, String> {
    let value: Value = serde_json::from_str(text).map_err(|e| format!("JSONDecodeError: {}", e))?;
    let Value::Object(map) = value else {
        return Err("table JSON is not an object".into());
    };
    let mut t = TableData::default();
    for (k, v) in map {
        match k.as_str() {
            "ename" => t.ename = take_string(v, "ename")?,
            "cname" => t.cname = take_string(v, "cname")?,
            "selkey" => t.selkey = take_string(v, "selkey")?,
            "keynames" => t.keynames = take_string_map(v, "keynames")?,
            "chardefs" => t.chardefs = take_list_map(v, "chardefs")?,
            "privateuse" => t.privateuse = take_list_map(v, "privateuse")?,
            "dupchardefs" => t.dupchardefs = take_list_map(v, "dupchardefs")?,
            _ => {}
        }
    }
    Ok(t)
}

/// Reads a table file like `io.open(path, 'r', encoding='utf8')` (strict UTF-8).
pub fn read_table_file(path: &Path) -> Result<String, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("OSError: {}: {}", path.display(), e))?;
    String::from_utf8(bytes).map_err(|e| format!("UnicodeDecodeError: {}", e))
}

/// `_build_reverse_index`: char -> codes, in chardefs order, a code repeated
/// once per occurrence of the char in its list.
pub fn build_reverse_index(chardefs: &IndexMap<String, Vec<String>>) -> HashMap<String, Vec<String>> {
    let mut index: HashMap<String, Vec<String>> = HashMap::new();
    for (chardef, chars) in chardefs {
        for ch in chars {
            match index.get_mut(ch.as_str()) {
                Some(keys) => keys.push(chardef.clone()),
                None => {
                    index.insert(ch.clone(), vec![chardef.clone()]);
                }
            }
        }
    }
    index
}

/// `keynames.get(key, key)`
pub fn key_name<'a>(keynames: &'a IndexMap<String, String>, key: &'a str) -> &'a str {
    keynames.get(key).map(|s| s.as_str()).unwrap_or(key)
}

/// `for ch in chardef: result += getKeyName(ch)` (per code point)
pub fn push_key_names(out: &mut String, keynames: &IndexMap<String, String>, code: &str) {
    let mut buf = [0u8; 4];
    for ch in code.chars() {
        let s: &str = ch.encode_utf8(&mut buf);
        out.push_str(key_name(keynames, s));
    }
}

// ---------------------------------------------------------------------------
// getCharSet

static BIG5_CHARSET: &[u8] = include_bytes!("big5_charset.bin");
const CJK_FIRST: u32 = 0x4E00;
const CJK_END: u32 = 0x9FEB;

/// Cin.getCharSet for one code point.
pub fn char_set(c: char) -> &'static str {
    let m = c as u32;
    if m <= CJK_END {
        if (0x3100..0x3130).contains(&m) || matches!(m, 0x02D9 | 0x02CA | 0x02C7 | 0x02CB) {
            return "bopomofo";
        } else if (CJK_FIRST..CJK_END).contains(&m) {
            return match BIG5_CHARSET[(m - CJK_FIRST) as usize] {
                0 => "cjk",
                1 => "big5F",
                2 => "big5LF",
                _ => "big5Other",
            };
        } else if (0x3400..0x4DB6).contains(&m) {
            return "cjkExtA";
        }
    } else if (0x20000..0x2A6D7).contains(&m) {
        return "cjkExtB";
    } else if (0x2A700..0x2B735).contains(&m) {
        return "cjkExtC";
    } else if (0x2B740..0x2B81E).contains(&m) {
        return "cjkExtD";
    } else if (0x2B820..0x2CEA2).contains(&m) {
        return "cjkExtE";
    } else if (0x2CEB0..0x2EBE1).contains(&m) {
        return "cjkExtF";
    } else if matches!(m, 0xFA0E | 0xFA0F | 0xFA11 | 0xFA13 | 0xFA14 | 0xFA1F | 0xFA21 | 0xFA23 | 0xFA24 | 0xFA27 | 0xFA28 | 0xFA29) {
        return "cjkCIibm";
    } else if (0xE000..0xF900).contains(&m) || (0xF0000..0xFFFFE).contains(&m) || (0x100000..0x10FFFE).contains(&m) {
        return "pua";
    } else if (0xF900..0xFA0E).contains(&m)
        || matches!(
            m,
            0xFA10 | 0xFA12 | 0xFA15 | 0xFA16 | 0xFA17 | 0xFA18 | 0xFA19 | 0xFA1A | 0xFA1B | 0xFA1C | 0xFA1D | 0xFA1E | 0xFA20 | 0xFA22 | 0xFA25 | 0xFA26 | 0xFA2A | 0xFA2B | 0xFA2C | 0xFA2D
        )
        || (0xFA2E..0xFB00).contains(&m)
    {
        return "pua";
    } else if (0x2F800..0x2FA20).contains(&m) {
        return "pua";
    }
    "cjkOther"
}

const HIGH_FREQUENCY_CHARSETS: [&str; 6] = ["bopomofo", "bopomofoTone", "cjk", "big5F", "big5LF", "big5S"];
const LOW_FREQUENCY_CHARSETS: [&str; 10] = ["big5Other", "cjkExtA", "cjkExtB", "cjkExtC", "cjkExtD", "cjkExtE", "cjkExtF", "cjkCIibm", "pua", "cjkOther"];

// ---------------------------------------------------------------------------
// wildcard pattern: '^' + ('(.)' | '(.*)' | re.escape(c))... + '$' with re.match

#[derive(Clone, Copy, PartialEq)]
enum Tok {
    Lit(char),
    Any,
}

/// Does `key` match the tokens exactly? `Any` is '.' (one char, not '\n') or
/// '.*' (any run of non-'\n' chars) when `variable`.
fn tokens_match(toks: &[Tok], key: &[char], variable: bool) -> bool {
    if !variable {
        return toks.len() == key.len()
            && toks.iter().zip(key).all(|(t, &c)| match t {
                Tok::Lit(l) => *l == c,
                Tok::Any => c != '\n',
            });
    }
    // dp[j]: toks[..i] matches key[..j]
    let n = key.len();
    let mut dp = vec![false; n + 1];
    dp[0] = true;
    for t in toks {
        let mut next = vec![false; n + 1];
        match t {
            Tok::Any => {
                for j in 0..=n {
                    next[j] = dp[j] || (j > 0 && next[j - 1] && key[j - 1] != '\n');
                }
            }
            Tok::Lit(l) => {
                for j in 1..=n {
                    next[j] = dp[j - 1] && key[j - 1] == *l;
                }
            }
        }
        dp = next;
    }
    dp[n]
}

/// Glob matching where `Any` matches any run of chars (greedy with backtracking
/// to the last star; same answer as the regex for keys without '\n').
fn glob_match(toks: &[Tok], key: &[char]) -> bool {
    let (mut t, mut k) = (0, 0);
    let mut star: Option<(usize, usize)> = None;
    while k < key.len() {
        match toks.get(t) {
            Some(Tok::Any) => {
                star = Some((t, k));
                t += 1;
            }
            Some(Tok::Lit(l)) if *l == key[k] => {
                t += 1;
                k += 1;
            }
            _ => match star {
                Some((st, sk)) => {
                    t = st + 1;
                    k = sk + 1;
                    star = Some((st, sk + 1));
                }
                None => return false,
            },
        }
    }
    toks[t..].iter().all(|x| *x == Tok::Any)
}

/// re.match('^...$', key): '$' also matches before a final newline.
fn pattern_match(toks: &[Tok], key: &str, variable: bool) -> bool {
    if !variable && !key.ends_with('\n') {
        let mut it = key.chars();
        for t in toks {
            match (t, it.next()) {
                (_, None) => return false,
                (Tok::Lit(l), Some(c)) if *l != c => return false,
                (Tok::Any, Some('\n')) => return false,
                _ => {}
            }
        }
        return it.next().is_none();
    }
    if variable && !key.contains('\n') {
        // no newline: '.*' is a plain glob star
        let mut buf = ['\0'; 16];
        let mut n = 0;
        for c in key.chars() {
            if n == buf.len() {
                n = usize::MAX;
                break;
            }
            buf[n] = c;
            n += 1;
        }
        if n != usize::MAX {
            return glob_match(toks, &buf[..n]);
        }
    }
    let chars: Vec<char> = key.chars().collect();
    if tokens_match(toks, &chars, variable) {
        return true;
    }
    if chars.last() == Some(&'\n') {
        return tokens_match(toks, &chars[..chars.len() - 1], variable);
    }
    false
}

type WildcardCacheKey = (String, String, i64, bool);

// ---------------------------------------------------------------------------
// counts (cincount.json)

/// A Python number as stored in a count entry: "last" is a float, except the
/// int 0 that `_normalizeCountEntry` uses when it cannot convert the value.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum PyNum {
    Int(i64),
    Float(f64),
}

impl PyNum {
    pub fn as_f64(self) -> f64 {
        match self {
            PyNum::Int(i) => i as f64,
            PyNum::Float(f) => f,
        }
    }
}

/// One normalized cincount entry: {"count": int, "last": float, "prev": {char: int}}.
/// Counts are i64 (Python ints are unbounded; larger values saturate).
#[derive(Debug, Clone, PartialEq)]
pub struct CountEntry {
    pub count: i64,
    pub last: PyNum,
    pub prev: IndexMap<String, i64>,
}

fn is_py_space(c: char) -> bool {
    c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)
}

/// Removes PEP 515 underscores (only allowed between two ASCII digits).
fn strip_underscores(s: &str) -> Option<String> {
    if !s.contains('_') {
        return Some(s.to_string());
    }
    let chars: Vec<char> = s.chars().collect();
    let mut out = String::with_capacity(s.len());
    for (i, &c) in chars.iter().enumerate() {
        if c == '_' {
            let before = i > 0 && chars[i - 1].is_ascii_digit();
            let after = i + 1 < chars.len() && chars[i + 1].is_ascii_digit();
            if !before || !after {
                return None;
            }
        } else {
            out.push(c);
        }
    }
    Some(out)
}

/// int(str) in base 10 (ASCII digits only; saturates beyond i64).
fn py_int_str(s: &str) -> Option<i64> {
    let s = s.trim_matches(is_py_space);
    let (neg, digits) = match s.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, s.strip_prefix('+').unwrap_or(s)),
    };
    if digits.is_empty() || !digits.starts_with(|c: char| c.is_ascii_digit()) {
        return None;
    }
    let digits = strip_underscores(digits)?;
    if !digits.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let mut v: i64 = 0;
    for c in digits.bytes() {
        v = v.saturating_mul(10).saturating_add((c - b'0') as i64);
    }
    Some(if neg { -v } else { v })
}

/// float(str) (ASCII digits only).
fn py_float_str(s: &str) -> Option<f64> {
    let s = s.trim_matches(is_py_space);
    if s.is_empty() {
        return None;
    }
    let body = s.strip_prefix(['+', '-']).unwrap_or(s);
    let lower = body.to_ascii_lowercase();
    if matches!(lower.as_str(), "inf" | "infinity" | "nan") {
        let v = if lower == "nan" { f64::NAN } else { f64::INFINITY };
        return Some(if s.starts_with('-') { -v } else { v });
    }
    // decimal: digits [. digits] | . digits, optional exponent
    if !body.chars().all(|c| c.is_ascii_digit() || matches!(c, '.' | 'e' | 'E' | '+' | '-' | '_')) {
        return None;
    }
    let cleaned = strip_underscores(s)?;
    cleaned.parse::<f64>().ok()
}

/// A value parsed the way Python's `json.load` parses it (see `py_json_parse`).
#[derive(Debug, Clone, PartialEq)]
pub enum PyVal {
    Null,
    Bool(bool),
    /// Python ints are unbounded; larger literals saturate.
    Int(i64),
    Float(f64),
    Str(String),
    List(Vec<PyVal>),
    Dict(IndexMap<String, PyVal>),
}

/// Python's json.loads (strict mode): NaN / Infinity / -Infinity accepted,
/// numbers with a fraction or exponent are floats (1e400 is inf), duplicate
/// keys keep the first position and the last value, a BOM is an error.
/// Lone surrogate escapes (accepted by Python) are an error here, since a
/// Rust String cannot hold them.
pub fn py_json_parse(text: &str) -> Result<PyVal, String> {
    let mut p = JsonParser { s: text.as_bytes(), text, i: 0 };
    p.ws();
    let v = p.value(0)?;
    p.ws();
    if p.i != p.s.len() {
        return Err(format!("JSONDecodeError: Extra data at {}", p.i));
    }
    Ok(v)
}

struct JsonParser<'a> {
    s: &'a [u8],
    text: &'a str,
    i: usize,
}

impl JsonParser<'_> {
    fn err<T>(&self, what: &str) -> Result<T, String> {
        Err(format!("JSONDecodeError: {} at {}", what, self.i))
    }

    fn ws(&mut self) {
        while self.i < self.s.len() && matches!(self.s[self.i], b' ' | b'\t' | b'\n' | b'\r') {
            self.i += 1;
        }
    }

    fn eat(&mut self, lit: &str) -> bool {
        if self.s[self.i..].starts_with(lit.as_bytes()) {
            self.i += lit.len();
            true
        } else {
            false
        }
    }

    fn value(&mut self, depth: usize) -> Result<PyVal, String> {
        if depth > 900 {
            return self.err("RecursionError");
        }
        let Some(&c) = self.s.get(self.i) else {
            return self.err("Expecting value");
        };
        match c {
            b'{' => {
                self.i += 1;
                let mut map = IndexMap::new();
                self.ws();
                if self.s.get(self.i) == Some(&b'}') {
                    self.i += 1;
                    return Ok(PyVal::Dict(map));
                }
                loop {
                    if self.s.get(self.i) != Some(&b'"') {
                        return self.err("Expecting property name enclosed in double quotes");
                    }
                    let key = self.string()?;
                    self.ws();
                    if self.s.get(self.i) != Some(&b':') {
                        return self.err("Expecting ':' delimiter");
                    }
                    self.i += 1;
                    self.ws();
                    let v = self.value(depth + 1)?;
                    map.insert(key, v);
                    self.ws();
                    match self.s.get(self.i) {
                        Some(b',') => {
                            self.i += 1;
                            self.ws();
                        }
                        Some(b'}') => {
                            self.i += 1;
                            return Ok(PyVal::Dict(map));
                        }
                        _ => return self.err("Expecting ',' delimiter"),
                    }
                }
            }
            b'[' => {
                self.i += 1;
                let mut list = Vec::new();
                self.ws();
                if self.s.get(self.i) == Some(&b']') {
                    self.i += 1;
                    return Ok(PyVal::List(list));
                }
                loop {
                    list.push(self.value(depth + 1)?);
                    self.ws();
                    match self.s.get(self.i) {
                        Some(b',') => {
                            self.i += 1;
                            self.ws();
                        }
                        Some(b']') => {
                            self.i += 1;
                            return Ok(PyVal::List(list));
                        }
                        _ => return self.err("Expecting ',' delimiter"),
                    }
                }
            }
            b'"' => Ok(PyVal::Str(self.string()?)),
            b'n' if self.eat("null") => Ok(PyVal::Null),
            b't' if self.eat("true") => Ok(PyVal::Bool(true)),
            b'f' if self.eat("false") => Ok(PyVal::Bool(false)),
            b'N' if self.eat("NaN") => Ok(PyVal::Float(f64::NAN)),
            b'I' if self.eat("Infinity") => Ok(PyVal::Float(f64::INFINITY)),
            b'-' if self.eat("-Infinity") => Ok(PyVal::Float(f64::NEG_INFINITY)),
            b'-' | b'0'..=b'9' => self.number(),
            _ => self.err("Expecting value"),
        }
    }

    /// (-?(?:0|[1-9]\d*))(\.\d+)?([eE][-+]?\d+)?
    fn number(&mut self) -> Result<PyVal, String> {
        let start = self.i;
        let s = self.s;
        let mut i = self.i;
        if s.get(i) == Some(&b'-') {
            i += 1;
        }
        match s.get(i) {
            Some(b'0') => i += 1,
            Some(b'1'..=b'9') => {
                while i < s.len() && s[i].is_ascii_digit() {
                    i += 1;
                }
            }
            _ => return self.err("Expecting value"),
        }
        let mut is_float = false;
        if s.get(i) == Some(&b'.') && s.get(i + 1).is_some_and(|c| c.is_ascii_digit()) {
            i += 1;
            while i < s.len() && s[i].is_ascii_digit() {
                i += 1;
            }
            is_float = true;
        }
        if matches!(s.get(i), Some(b'e' | b'E')) {
            let mut j = i + 1;
            if matches!(s.get(j), Some(b'+' | b'-')) {
                j += 1;
            }
            if s.get(j).is_some_and(|c| c.is_ascii_digit()) {
                while j < s.len() && s[j].is_ascii_digit() {
                    j += 1;
                }
                i = j;
                is_float = true;
            }
        }
        self.i = i;
        let lit = &self.text[start..i];
        if is_float {
            Ok(PyVal::Float(lit.parse::<f64>().map_err(|e| e.to_string())?))
        } else {
            let neg = lit.starts_with('-');
            let mut v: i64 = 0;
            for c in lit.trim_start_matches('-').bytes() {
                v = v.saturating_mul(10).saturating_add((c - b'0') as i64);
            }
            Ok(PyVal::Int(if neg { -v } else { v }))
        }
    }

    fn hex4(&mut self) -> Result<u32, String> {
        let h = self.s.get(self.i..self.i + 4).and_then(|h| std::str::from_utf8(h).ok()).and_then(|h| {
            if h.bytes().all(|b| b.is_ascii_hexdigit()) {
                u32::from_str_radix(h, 16).ok()
            } else {
                None
            }
        });
        match h {
            Some(v) => {
                self.i += 4;
                Ok(v)
            }
            None => self.err("Invalid \\uXXXX escape"),
        }
    }

    fn string(&mut self) -> Result<String, String> {
        self.i += 1; // opening quote
        let mut out = String::new();
        loop {
            let start = self.i;
            while self.i < self.s.len() && !matches!(self.s[self.i], b'"' | b'\\') && self.s[self.i] >= 0x20 {
                self.i += 1;
            }
            out.push_str(&self.text[start..self.i]);
            match self.s.get(self.i) {
                None => return self.err("Unterminated string"),
                Some(b'"') => {
                    self.i += 1;
                    return Ok(out);
                }
                Some(b'\\') => {
                    self.i += 1;
                    let Some(&e) = self.s.get(self.i) else {
                        return self.err("Unterminated string");
                    };
                    self.i += 1;
                    match e {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{08}'),
                        b'f' => out.push('\u{0c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let mut cp = self.hex4()?;
                            if (0xD800..0xDC00).contains(&cp) && self.s[self.i..].starts_with(b"\\u") {
                                let save = self.i;
                                self.i += 2;
                                let lo = self.hex4()?;
                                if (0xDC00..0xE000).contains(&lo) {
                                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                                } else {
                                    self.i = save;
                                }
                            }
                            match char::from_u32(cp) {
                                Some(c) => out.push(c),
                                None => return self.err("lone surrogate (not representable)"),
                            }
                        }
                        _ => return self.err("Invalid \\escape"),
                    }
                }
                Some(_) => return self.err("Invalid control character"),
            }
        }
    }
}

fn val_num(v: &PyVal) -> Option<PyNum> {
    match v {
        PyVal::Bool(b) => Some(PyNum::Int(*b as i64)),
        PyVal::Int(i) => Some(PyNum::Int(*i)),
        PyVal::Float(f) => Some(PyNum::Float(*f)),
        _ => None,
    }
}

/// Python int(value): Ok(None) for the TypeError / ValueError the callers
/// catch, Err for the OverflowError of int(inf) that they do not.
fn py_int(v: &PyVal) -> Result<Option<i64>, String> {
    match v {
        PyVal::Str(s) => Ok(py_int_str(s)),
        _ => match val_num(v) {
            None => Ok(None),
            Some(PyNum::Int(i)) => Ok(Some(i)),
            Some(PyNum::Float(f)) => {
                if f.is_nan() {
                    Ok(None)
                } else if f.is_infinite() {
                    Err("OverflowError: cannot convert float infinity to integer".into())
                } else {
                    Ok(Some(f.trunc() as i64)) // saturating
                }
            }
        },
    }
}

/// Python float(value); None for TypeError / ValueError.
fn py_float(v: &PyVal) -> Option<f64> {
    match v {
        PyVal::Str(s) => py_float_str(s),
        _ => val_num(v).map(PyNum::as_f64),
    }
}

/// Python `==` between a parsed value and a number (bool == int, int == float).
fn py_num_eq(v: &PyVal, n: PyNum) -> bool {
    let Some(a) = val_num(v) else { return false };
    match (a, n) {
        (PyNum::Int(x), PyNum::Int(y)) => x == y,
        (PyNum::Float(x), PyNum::Float(y)) => x == y,
        (PyNum::Int(i), PyNum::Float(f)) | (PyNum::Float(f), PyNum::Int(i)) => {
            f.fract() == 0.0 && (-9.223372036854776e18..9.223372036854776e18).contains(&f) && f as i64 == i
        }
    }
}

/// `_trimContextCounts(prev, keepKey)`
pub fn trim_context_counts(prev: &IndexMap<String, i64>, keep_key: &str) -> IndexMap<String, i64> {
    if prev.len() <= MAX_CONTEXT_ENTRIES {
        return prev.clone();
    }
    let mut items: Vec<(&String, &i64)> = prev.iter().collect();
    items.sort_by(|a, b| b.1.cmp(a.1).then_with(|| a.0.cmp(b.0)));
    let mut trimmed: IndexMap<String, i64> = items[..MAX_CONTEXT_ENTRIES].iter().map(|(k, v)| ((*k).clone(), **v)).collect();
    if !keep_key.is_empty() && prev.contains_key(keep_key) && !trimmed.contains_key(keep_key) {
        let drop_key = trimmed
            .iter()
            .filter(|(k, _)| k.as_str() != keep_key)
            .min_by(|a, b| a.1.cmp(b.1).then_with(|| a.0.cmp(b.0)))
            .map(|(k, _)| k.clone());
        if let Some(k) = drop_key {
            trimmed.shift_remove(&k);
        }
        trimmed.insert(keep_key.to_string(), prev[keep_key]);
    }
    trimmed
}

/// `_normalizeCountEntry(value)` for a value read from cincount.json. Err is
/// the uncaught OverflowError of int(inf).
pub fn normalize_count_entry(value: &PyVal) -> Result<CountEntry, String> {
    if let PyVal::Dict(m) = value {
        let count = py_int(m.get("count").unwrap_or(&PyVal::Int(0)))?.unwrap_or(0);
        let last = match m.get("last") {
            None => PyNum::Float(0.0),
            Some(v) => py_float(v).map(PyNum::Float).unwrap_or(PyNum::Int(0)),
        };
        let mut normalized_prev = IndexMap::new();
        if let Some(PyVal::Dict(prev)) = m.get("prev") {
            for (k, v) in prev {
                if let Some(i) = py_int(v)? {
                    normalized_prev.insert(k.clone(), i);
                }
            }
        }
        let prev = trim_context_counts(&normalized_prev, "");
        return Ok(CountEntry { count, last, prev });
    }
    Ok(CountEntry { count: py_int(value)?.unwrap_or(0), last: PyNum::Int(0), prev: IndexMap::new() })
}

/// `_normalizeCountEntry(entry)` for an entry that is already normalized.
fn renormalize(entry: &CountEntry) -> CountEntry {
    CountEntry { count: entry.count, last: PyNum::Float(entry.last.as_f64()), prev: trim_context_counts(&entry.prev, "") }
}

/// Python `normalizedEntry == entry`
pub fn count_entry_equals(entry: &CountEntry, value: &PyVal) -> bool {
    let PyVal::Dict(m) = value else { return false };
    if m.len() != 3 {
        return false;
    }
    let (Some(count), Some(last), Some(PyVal::Dict(prev))) = (m.get("count"), m.get("last"), m.get("prev")) else {
        return false;
    };
    // float(x) of a float returns x itself and dict == compares identical
    // objects as equal, so a float "last" always compares equal (even NaN)
    let last_eq = matches!(last, PyVal::Float(_)) || py_num_eq(last, entry.last);
    py_num_eq(count, PyNum::Int(entry.count))
        && last_eq
        && prev.len() == entry.prev.len()
        && entry.prev.iter().all(|(k, v)| prev.get(k).is_some_and(|p| py_num_eq(p, PyNum::Int(*v))))
}

/// Python's float repr (what json.dumps writes for a float).
pub fn py_float_repr(x: f64) -> String {
    if x.is_nan() {
        return "NaN".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "Infinity".into() } else { "-Infinity".into() };
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0".into() } else { "0.0".into() };
    }
    let s = format!("{:e}", x);
    let (mant, exp) = s.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let neg = mant.starts_with('-');
    let digits: String = mant.chars().filter(|c| c.is_ascii_digit()).collect();
    let mut out = String::new();
    if neg {
        out.push('-');
    }
    if (-4..16).contains(&exp) {
        if exp >= 0 {
            let int_len = exp as usize + 1;
            if digits.len() <= int_len {
                out.push_str(&digits);
                out.extend(std::iter::repeat('0').take(int_len - digits.len()));
                out.push_str(".0");
            } else {
                out.push_str(&digits[..int_len]);
                out.push('.');
                out.push_str(&digits[int_len..]);
            }
        } else {
            out.push_str("0.");
            out.extend(std::iter::repeat('0').take((-exp - 1) as usize));
            out.push_str(&digits);
        }
    } else {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        out.push(if exp < 0 { '-' } else { '+' });
        out.push_str(&format!("{:02}", exp.abs()));
    }
    out
}

/// json.dumps string with ensure_ascii=False.
pub fn py_json_str(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

fn py_json_num(out: &mut String, n: PyNum) {
    match n {
        PyNum::Int(i) => out.push_str(&i.to_string()),
        PyNum::Float(f) => out.push_str(&py_float_repr(f)),
    }
}

/// json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
pub fn count_entry_json(out: &mut String, e: &CountEntry) {
    out.push_str("{\"count\":");
    py_json_num(out, PyNum::Int(e.count));
    out.push_str(",\"last\":");
    py_json_num(out, e.last);
    out.push_str(",\"prev\":{");
    for (i, (k, v)) in e.prev.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        py_json_str(out, k);
        out.push(':');
        out.push_str(&v.to_string());
    }
    out.push_str("}}");
}

pub type CinCount = IndexMap<String, IndexMap<String, CountEntry>>;

/// json.dumps(cincount, ensure_ascii=False, separators=(",", ":"))
pub fn cincount_json(cincount: &CinCount) -> String {
    let mut out = String::from("{");
    for (i, (key, entries)) in cincount.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        py_json_str(&mut out, key);
        out.push_str(":{");
        for (j, (ch, e)) in entries.iter().enumerate() {
            if j > 0 {
                out.push(',');
            }
            py_json_str(&mut out, ch);
            out.push(':');
            count_entry_json(&mut out, e);
        }
        out.push('}');
    }
    out.push('}');
    out
}

/// Python's max(0.0, x)
fn py_max0(x: f64) -> f64 {
    if x > 0.0 {
        x
    } else {
        0.0
    }
}

/// math.log2 (ValueError for x <= 0)
fn py_log2(x: f64) -> Result<f64, String> {
    if x <= 0.0 {
        return Err("ValueError: math domain error".into());
    }
    Ok(x.log2())
}

// ---------------------------------------------------------------------------

/// Lazily built query indexes; dropped whenever chardefs changes
/// (Python: `_sorted_chardef_keys`, `_keys_by_length`, `_wildcard_results`).
#[derive(Default)]
struct Indexes {
    sorted_keys: OnceCell<Vec<String>>,
    /// code length (in chars) -> indexes into sorted_keys, ascending
    keys_by_length: OnceCell<HashMap<usize, Vec<u32>>>,
    wildcard_results: RefCell<VecDeque<(WildcardCacheKey, Vec<String>)>>,
}

pub struct Cin {
    pub ime_dir_name: String,
    pub ignore_private_use_area: bool,
    pub ename: String,
    pub cname: String,
    pub selkey: String,
    keynames: IndexMap<String, String>,
    chardefs: IndexMap<String, Vec<String>>,
    privateuse: IndexMap<String, Vec<String>>,
    dupchardefs: IndexMap<String, Vec<String>>,
    cincount: CinCount,
    count_dirty: bool,
    last_count_save_time: f64,
    count_dir: PathBuf,
    char_to_keys: HashMap<String, Vec<String>>,
    indexes: Indexes,
    closed: bool,
}

impl Cin {
    /// `Cin(open(path), imeDirName, ignorePrivateUseArea)`. `count_dir` is the
    /// directory of cincount.json (Python: %APPDATA%\PIME\<imeDirName>, see
    /// `default_count_dir`); it is created when missing.
    pub fn load(path: &Path, ime_dir_name: &str, ignore_private_use_area: bool, count_dir: PathBuf) -> Result<Cin, String> {
        let text = read_table_file(path)?;
        Cin::from_json(&text, ime_dir_name, ignore_private_use_area, count_dir)
    }

    pub fn from_json(text: &str, ime_dir_name: &str, ignore_private_use_area: bool, count_dir: PathBuf) -> Result<Cin, String> {
        let t = parse_table(text)?;
        let mut cin = Cin {
            ime_dir_name: ime_dir_name.to_string(),
            ignore_private_use_area,
            ename: t.ename,
            cname: t.cname,
            selkey: t.selkey,
            keynames: t.keynames,
            chardefs: t.chardefs,
            privateuse: t.privateuse,
            dupchardefs: t.dupchardefs,
            cincount: IndexMap::new(),
            count_dirty: false,
            last_count_save_time: 0.0,
            count_dir,
            char_to_keys: HashMap::new(),
            indexes: Indexes::default(),
            closed: false,
        };
        if cin.ignore_private_use_area {
            for (key, values) in &cin.privateuse {
                let list = cin.chardefs.get_mut(key).ok_or_else(|| format!("KeyError: '{}'", key))?;
                for value in values {
                    if let Some(pos) = list.iter().position(|v| v == value) {
                        list.remove(pos);
                    }
                }
            }
        }
        cin.char_to_keys = build_reverse_index(&cin.chardefs);
        cin.load_count_file()?;
        Ok(cin)
    }

    /// %APPDATA%\PIME\<imeDirName> (Cin.getCountDir)
    pub fn default_count_dir(ime_dir_name: &str) -> PathBuf {
        crate::paths::config_dir(ime_dir_name)
    }

    /// Python `__del__`: save the counts (errors ignored) and empty the tables.
    /// Idempotent; also run on drop.
    pub fn close(&mut self) {
        if self.closed {
            return;
        }
        self.closed = true;
        let _ = self.save_count_file(true);
        self.keynames = IndexMap::new();
        self.cincount = IndexMap::new();
        self.chardefs = IndexMap::new();
        self.privateuse = IndexMap::new();
        self.dupchardefs = IndexMap::new();
        self.indexes = Indexes::default();
    }

    pub fn get_ename(&self) -> &str {
        &self.ename
    }

    pub fn get_cname(&self) -> &str {
        &self.cname
    }

    pub fn get_selection(&self) -> &str {
        &self.selkey
    }

    pub fn keynames(&self) -> &IndexMap<String, String> {
        &self.keynames
    }

    pub fn chardefs(&self) -> &IndexMap<String, Vec<String>> {
        &self.chardefs
    }

    pub fn privateuse(&self) -> &IndexMap<String, Vec<String>> {
        &self.privateuse
    }

    pub fn dupchardefs(&self) -> &IndexMap<String, Vec<String>> {
        &self.dupchardefs
    }

    pub fn cincount(&self) -> &CinCount {
        &self.cincount
    }

    pub fn count_dirty(&self) -> bool {
        self.count_dirty
    }

    pub fn is_in_key_name(&self, key: &str) -> bool {
        self.keynames.contains_key(key)
    }

    /// keynames.get(key, key)
    pub fn get_key_name<'a>(&'a self, key: &'a str) -> &'a str {
        key_name(&self.keynames, key)
    }

    pub fn is_have_key(&self, val: &str) -> bool {
        self.char_to_keys.contains_key(val)
    }

    /// First code of a char; Err (KeyError) when the char has none.
    pub fn get_key(&self, val: &str) -> Result<&str, String> {
        self.char_to_keys.get(val).map(|k| k[0].as_str()).ok_or_else(|| format!("KeyError: '{}'", val))
    }

    /// All codes of a char (the reverse index entry).
    pub fn get_keys(&self, val: &str) -> Option<&[String]> {
        self.char_to_keys.get(val).map(|k| k.as_slice())
    }

    pub fn is_in_char_def(&self, key: &str) -> bool {
        self.chardefs.contains_key(key)
    }

    /// chardefs.get(key, []). (Python returns the table's own list.)
    pub fn get_char_def(&self, key: &str) -> &[String] {
        self.chardefs.get(key).map(|v| v.as_slice()).unwrap_or(&[])
    }

    pub fn sorted_char_def_keys(&self) -> &[String] {
        self.indexes.sorted_keys.get_or_init(|| {
            let mut keys: Vec<String> = self.chardefs.keys().cloned().collect();
            keys.sort_unstable();
            keys
        })
    }

    pub fn is_char_def_prefix(&self, key: &str) -> bool {
        if key.is_empty() {
            return false;
        }
        if self.chardefs.contains_key(key) {
            return true;
        }
        let keys = self.sorted_char_def_keys();
        let i = keys.partition_point(|k| k.as_str() < key);
        i < keys.len() && keys[i].starts_with(key)
    }

    /// Is there a code longer than `key` that starts with it?
    pub fn has_longer_char_def_prefix(&self, key: &str) -> bool {
        if key.is_empty() {
            return false;
        }
        let keys = self.sorted_char_def_keys();
        let mut i = keys.partition_point(|k| k.as_str() < key);
        if i < keys.len() && keys[i] == key {
            i += 1;
        }
        i < keys.len() && keys[i].starts_with(key)
    }

    fn keys_by_length(&self) -> &HashMap<usize, Vec<u32>> {
        self.indexes.keys_by_length.get_or_init(|| {
            let mut map: HashMap<usize, Vec<u32>> = HashMap::new();
            for (i, key) in self.sorted_char_def_keys().iter().enumerate() {
                map.entry(key.chars().count()).or_default().push(i as u32);
            }
            map
        })
    }

    /// `_wildcardMatchKeys`: matching codes in sorted order.
    fn wildcard_match_keys(&self, composition: &str, wildcard: &str, toks: &[Tok], variable: bool) -> Result<Vec<&str>, String> {
        if wildcard.is_empty() {
            return Err("ValueError: empty separator".into());
        }
        let sorted = self.sorted_char_def_keys();
        let prefix = composition.split_once(wildcard).map(|(a, _)| a).unwrap_or(composition);
        let mut out = Vec::new();
        if variable {
            let start = sorted.partition_point(|k| k.as_str() < prefix);
            for key in sorted[start..].iter().take_while(|k| k.starts_with(prefix)) {
                if pattern_match(toks, key, true) {
                    out.push(key.as_str());
                }
            }
        } else {
            let length = composition.chars().count();
            let empty = Vec::new();
            let bucket = self.keys_by_length().get(&length).unwrap_or(&empty);
            let start = if prefix.is_empty() { 0 } else { bucket.partition_point(|&i| sorted[i as usize].as_str() < prefix) };
            for &i in &bucket[start..] {
                let key = sorted[i as usize].as_str();
                if !key.starts_with(prefix) {
                    break;
                }
                if pattern_match(toks, key, false) {
                    out.push(key);
                }
            }
        }
        Ok(out)
    }

    /// getWildcardCharDefs(CompositionChar, WildcardChar, candMaxItems, variableWildcard)
    /// with the 32-entry LRU cache of results.
    pub fn get_wildcard_char_defs(&self, composition: &str, wildcard: &str, cand_max_items: i64, variable: bool) -> Result<Vec<String>, String> {
        let cache_key: WildcardCacheKey = (composition.to_string(), wildcard.to_string(), cand_max_items, variable);
        {
            let mut cache = self.indexes.wildcard_results.borrow_mut();
            if let Some(pos) = cache.iter().position(|(k, _)| *k == cache_key) {
                let item = cache.remove(pos).unwrap();
                let result = item.1.clone();
                cache.push_back(item);
                return Ok(result);
            }
        }
        let result = self.compute_wildcard_char_defs(composition, wildcard, cand_max_items, variable)?;
        let mut cache = self.indexes.wildcard_results.borrow_mut();
        cache.push_back((cache_key, result.clone()));
        if cache.len() > WILDCARD_CACHE_SIZE {
            cache.pop_front();
        }
        Ok(result)
    }

    /// `_computeWildcardCharDefs` (uncached).
    pub fn compute_wildcard_char_defs(&self, composition: &str, wildcard: &str, cand_max_items: i64, variable: bool) -> Result<Vec<String>, String> {
        let mut wildcardchardefs: Vec<String> = Vec::new();
        let mut low: Vec<Vec<&str>> = vec![Vec::new(); LOW_FREQUENCY_CHARSETS.len()];
        let mut low_seen: HashSet<&str> = HashSet::new();

        let mut wc_buf = [0u8; 4];
        let toks: Vec<Tok> = composition
            .chars()
            .map(|c| if c.encode_utf8(&mut wc_buf) == wildcard { Tok::Any } else { Tok::Lit(c) })
            .collect();

        let keys = self.wildcard_match_keys(composition, wildcard, &toks, variable)?;
        if keys.is_empty() {
            return Ok(wildcardchardefs);
        }
        let mut high_seen: HashSet<&str> = HashSet::new();
        for key in &keys {
            for matchstr in &self.chardefs[*key] {
                let first = matchstr
                    .chars()
                    .next()
                    .ok_or_else(|| "TypeError: ord() expected a character, but string of length 0 found".to_string())?;
                let charset = char_set(first);
                if HIGH_FREQUENCY_CHARSETS.contains(&charset) {
                    if high_seen.contains(matchstr.as_str()) {
                        continue;
                    }
                    high_seen.insert(matchstr);
                    wildcardchardefs.push(matchstr.clone());
                    if wildcardchardefs.len() as i64 >= cand_max_items {
                        return Ok(wildcardchardefs);
                    }
                } else {
                    let i = LOW_FREQUENCY_CHARSETS.iter().position(|s| *s == charset).unwrap_or(LOW_FREQUENCY_CHARSETS.len() - 1);
                    if !low_seen.contains(matchstr.as_str()) {
                        low[i].push(matchstr);
                        low_seen.insert(matchstr);
                    }
                }
            }
        }
        for group in &low {
            for ch in group {
                if !high_seen.contains(ch) {
                    wildcardchardefs.push(ch.to_string());
                    high_seen.insert(ch);
                }
                if wildcardchardefs.len() as i64 >= cand_max_items {
                    return Ok(wildcardchardefs);
                }
            }
        }
        Ok(wildcardchardefs)
    }

    /// getCharSet(root): the charset group of the first char. Err for "".
    pub fn get_char_set(&self, root: &str) -> Result<&'static str, String> {
        let mut it = root.chars();
        match (it.next(), it.next()) {
            (Some(c), None) => Ok(char_set(c)),
            (None, _) => Err("TypeError: ord() expected a character, but string of length 0 found".into()),
            _ => Err("TypeError: ord() expected a character".into()),
        }
    }

    /// `字:　①..` with up to 10 codes, `查無字根...` when the char has none.
    pub fn get_char_encode(&self, root: &str) -> String {
        let keys = match self.char_to_keys.get(root) {
            Some(k) if !k.is_empty() => k,
            _ => return "查無字根...".to_string(),
        };
        let mut result = format!("{}:", root);
        for (i, chardef) in keys.iter().take(10).enumerate() {
            result.push('　');
            result.push_str(ENCODE_NUMBERS[i]);
            push_key_names(&mut result, &self.keynames, chardef);
        }
        result
    }

    /// updateCinTable: merge the user's extend table (keys lowercased); with
    /// priority each value goes to the index it has in its extend list (the
    /// index of its first occurrence), else it is appended.
    pub fn update_cin_table(&mut self, user_extend_table: bool, priority_extend_table: bool, extend_chardefs: &IndexMap<String, Vec<String>>, _ignore_private_use_area: bool) {
        if !user_extend_table {
            return;
        }
        for (key, roots) in extend_chardefs {
            let lower = key.to_lowercase();
            for root in roots {
                match self.chardefs.get_mut(&lower) {
                    Some(list) => {
                        if priority_extend_table {
                            let i = roots.iter().position(|r| r == root).unwrap();
                            list.insert(i.min(list.len()), root.clone());
                        } else {
                            list.push(root.clone());
                        }
                    }
                    None => {
                        self.chardefs.insert(lower.clone(), vec![root.clone()]);
                    }
                }
            }
        }
        self.indexes = Indexes::default();
        self.char_to_keys = build_reverse_index(&self.chardefs);
    }

    // ----- counts -----

    /// getCountFile(): creates the directory like os.makedirs(exist_ok=True).
    pub fn get_count_file(&self) -> Result<PathBuf, String> {
        std::fs::create_dir_all(&self.count_dir).map_err(|e| format!("OSError: {}", e))?;
        Ok(self.count_dir.join(COUNT_FILE_NAME))
    }

    /// loadCountFile(). Err only when the directory cannot be created.
    pub fn load_count_file(&mut self) -> Result<(), String> {
        let filename = self.get_count_file()?;
        let size = match std::fs::metadata(&filename) {
            Ok(m) => m.len(),
            Err(_) => return Ok(()),
        };
        if size == 0 {
            return Ok(());
        }
        let parsed: Result<PyVal, ()> = std::fs::read(&filename)
            .ok()
            .and_then(|b| String::from_utf8(b).ok())
            .ok_or(())
            .and_then(|text| py_json_parse(&text).map_err(|_| ()));
        // (normalized counts, changed) or Err for any exception (backup below)
        let result: Result<Option<(CinCount, bool)>, ()> = parsed.and_then(|data| {
            let PyVal::Dict(data) = data else { return Ok(None) };
            let mut normalized: CinCount = IndexMap::new();
            let mut changed = false;
            for (key, value) in &data {
                let PyVal::Dict(value) = value else {
                    changed = true;
                    continue;
                };
                let mut entries = IndexMap::new();
                for (ch, entry) in value {
                    let n = normalize_count_entry(entry).map_err(|_| ())?;
                    if !count_entry_equals(&n, entry) {
                        changed = true;
                    }
                    entries.insert(ch.clone(), n);
                }
                normalized.insert(key.clone(), entries);
            }
            Ok(Some((normalized, changed)))
        });
        match result {
            Ok(Some((normalized, changed))) => {
                for (k, v) in normalized {
                    self.cincount.insert(k, v);
                }
                if changed {
                    self.count_dirty = true;
                }
            }
            Ok(None) => {}
            Err(()) => {
                // keep a copy of the unreadable file before the next save overwrites it
                if let Ok(mtime) = std::fs::metadata(&filename).and_then(|m| m.modified()) {
                    let secs = match mtime.duration_since(std::time::UNIX_EPOCH) {
                        Ok(d) => d.as_secs_f64().trunc() as i64,
                        Err(e) => -(e.duration().as_secs_f64().trunc() as i64),
                    };
                    let mut backup = filename.clone().into_os_string();
                    backup.push(format!(".broken-{}", secs));
                    let backup = PathBuf::from(backup);
                    if !backup.exists() {
                        let _ = std::fs::copy(&filename, &backup);
                    }
                }
            }
        }
        Ok(())
    }

    /// saveCountFile(force): at most once a minute unless forced; temp file,
    /// fsync, replace. Write errors are ignored (the counts stay dirty); Err
    /// only when the directory cannot be created.
    pub fn save_count_file(&mut self, force: bool) -> Result<(), String> {
        if !self.count_dirty {
            return Ok(());
        }
        let now = env::time();
        if !force && self.last_count_save_time > 0.0 && now - self.last_count_save_time < COUNT_SAVE_INTERVAL_SECONDS {
            return Ok(());
        }
        let filename = self.get_count_file()?;
        let payload = cincount_json(&self.cincount);
        let mut tempname = filename.clone().into_os_string();
        tempname.push(".tmp");
        let tempname = PathBuf::from(tempname);
        let written = (|| -> std::io::Result<()> {
            let mut f = std::fs::File::create(&tempname)?;
            f.write_all(payload.as_bytes())?;
            f.flush()?;
            f.sync_all()?;
            drop(f);
            std::fs::rename(&tempname, &filename)
        })();
        if written.is_ok() {
            self.count_dirty = false;
            self.last_count_save_time = now;
        }
        Ok(())
    }

    /// addCount(key, char, previousChar)
    pub fn add_count(&mut self, key: &str, ch: &str, previous_char: &str) {
        let counts = self.cincount.entry(key.to_string()).or_default();
        let mut entry = match counts.get(ch) {
            Some(e) => renormalize(e),
            None => CountEntry { count: 0, last: PyNum::Float(0.0), prev: IndexMap::new() },
        };
        entry.count = entry.count.saturating_add(1);
        entry.last = PyNum::Float(env::time());
        if !previous_char.is_empty() {
            let v = entry.prev.get(previous_char).copied().unwrap_or(0).saturating_add(1);
            entry.prev.insert(previous_char.to_string(), v);
            entry.prev = trim_context_counts(&entry.prev, previous_char);
        }
        counts.insert(ch.to_string(), entry);
        self.count_dirty = true;
    }

    /// sortByCount: context prediction. Candidates chosen after the same
    /// previous char move up; everything else keeps table order. Err for the
    /// math domain error of a count <= -1.
    pub fn sort_by_count(&self, key: &str, candidates: &[String], previous_char: &str, use_recent: bool, use_context: bool) -> Result<Vec<String>, String> {
        let Some(counts) = self.cincount.get(key) else {
            return Ok(candidates.to_vec());
        };
        let now = env::time();
        let score = |candidate: &str| -> Result<f64, String> {
            let (count, last, prev_count) = match counts.get(candidate) {
                Some(e) => {
                    let prev_count = if previous_char.is_empty() { 0 } else { e.prev.get(previous_char).copied().unwrap_or(0) };
                    (e.count, e.last.as_f64(), prev_count)
                }
                None => (0, 0.0, 0),
            };
            let context_count = if use_context && !previous_char.is_empty() { prev_count } else { 0 };
            if context_count < 1 {
                return Ok(0.0);
            }
            let mut value = py_log2(1.0 + context_count as f64)? * 3.0;
            value += py_log2(1.0 + count as f64)?;
            if use_recent && last > 0.0 {
                let age_days = py_max0((now - last) / 86400.0);
                value += 2.0 / (1.0 + age_days / 7.0);
            }
            Ok(value)
        };
        let mut scored: Vec<(f64, usize)> = Vec::with_capacity(candidates.len());
        for (i, c) in candidates.iter().enumerate() {
            scored.push((-score(c)?, i));
        }
        scored.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal).then(a.1.cmp(&b.1)));
        Ok(scored.into_iter().map(|(_, i)| candidates[i].clone()).collect())
    }
}

impl Drop for Cin {
    fn drop(&mut self) {
        self.close();
    }
}

#[cfg(test)]
#[path = "cin_tests.rs"]
mod tests;
