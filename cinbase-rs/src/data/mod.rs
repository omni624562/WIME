//! The data-file tables of python/cinbase: symbols.dat, fsymbols.dat,
//! flangs.dat, swkb.dat, userphrase.dat / excludephrase.dat, extendtable.dat,
//! msymbols.json, dsymbols.json, phrase.json and emoji.json — plus the file
//! reading helpers of python/cinbase/__init__.py (readDataText, loadDataFile)
//! and config.py (findFile).
//!
//! Faithful port: same parsing, same ordering, same fallbacks. A Python
//! exception is `Err(String)` (message in Python's "KeyError: 'x'" style).

pub mod dsymbols;
pub mod emoji;
pub mod extendtable;
pub mod flangs;
pub mod fsymbols;
pub mod marks;
pub mod msymbols;
pub mod phrase;
pub mod swkb;
pub mod symbols;
pub mod textclusters;
pub mod userphrase;

#[cfg(test)]
mod tests;

// re-exports for the text service (not wired up yet)
#[allow(unused_imports)]
pub use self::{
    dsymbols::DSymbols, emoji::Emoji, extendtable::ExtendTable, flangs::FLangs, fsymbols::FSymbols, msymbols::MSymbols,
    phrase::Phrase, swkb::Swkb, symbols::Symbols, userphrase::UserPhrase,
};

use indexmap::IndexMap;
use serde_json::Value;
use std::path::{Path, PathBuf};

/// Ordered `str -> list[str]` table, like the Python `chardefs` dicts.
pub type CharDefs = IndexMap<String, Vec<String>>;

pub(crate) static EMPTY: [String; 0] = [];

/// Python's repr-ish KeyError message.
pub(crate) fn key_error(key: &str) -> String {
    format!("KeyError: '{}'", key)
}

// ---------------------------------------------------------------------------
// str helpers with Python semantics

/// str.isspace(): Unicode White_Space plus U+001C..U+001F (Python counts the
/// bidi classes B/S as whitespace; Rust's char::is_whitespace does not).
pub fn py_isspace(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// str.strip() with no argument.
pub fn py_strip(s: &str) -> &str {
    s.trim_matches(py_isspace)
}

/// line.lstrip('﻿').strip() — the first thing every .dat parser does.
pub(crate) fn clean_line(line: &str) -> &str {
    py_strip(line.trim_start_matches('\u{feff}'))
}

/// `line.split(sep, 1)` for a separator known to be present.
pub(crate) fn split1(line: &str, sep: char) -> (&str, &str) {
    line.split_once(sep).expect("separator present")
}

/// Iterating a text stream (StringIO / text file): lines with their '\n'
/// kept; a last line without '\n' is yielded too; "" yields nothing.
/// The text must already have universal newlines applied.
pub fn py_lines(text: &str) -> impl Iterator<Item = &str> {
    text.split_inclusive('\n')
}

/// Universal newlines (newline=None): "\r\n" and "\r" become "\n".
pub fn translate_newlines(text: &str) -> String {
    if !text.contains('\r') {
        return text.to_string();
    }
    text.replace("\r\n", "\n").replace('\r', "\n")
}

// ---------------------------------------------------------------------------
// file reading

/// raw.decode('utf-8-sig'), falling back to raw.decode('mbcs', errors='replace').
pub fn decode_data_bytes(raw: &[u8]) -> String {
    let body = raw.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(raw);
    match std::str::from_utf8(body) {
        Ok(s) => s.to_string(),
        Err(_) => mbcs_decode_replace(raw),
    }
}

/// readDataText(path) (cinbase/__init__.py): the decoded text with universal
/// newlines applied (what iterating / reading the returned StringIO gives).
pub fn read_data_text(path: &Path) -> Result<String, String> {
    let raw = std::fs::read(path).map_err(|e| format!("OSError: {}", e))?;
    Ok(translate_newlines(&decode_data_bytes(&raw)))
}

/// io.open(path, 'r', encoding='utf8').read(): strict UTF-8 (a BOM is kept as
/// U+FEFF), universal newlines. Used for phrase.json and emoji.json.
pub fn read_utf8_text(path: &Path) -> Result<String, String> {
    let raw = std::fs::read(path).map_err(|e| format!("OSError: {}", e))?;
    let text = String::from_utf8(raw).map_err(|e| format!("UnicodeDecodeError: {}", e))?;
    Ok(translate_newlines(&text))
}

/// config.findFile(dirs, name): the first dirs[i]/name that exists.
pub fn find_file<P: AsRef<Path>>(dirs: &[P], name: &str) -> Option<PathBuf> {
    dirs.iter().map(|d| d.as_ref().join(name)).find(|p| p.exists())
}

/// CinBase.loadDataFile: parse dirs[i]/name for the first existing file that
/// reads and parses, else parse `empty` ("" for .dat, "{}" for .json).
/// `parse` receives the readDataText() text.
pub fn load_data_file<T, P, F>(dirs: &[P], name: &str, parse: F, empty: &str) -> T
where
    P: AsRef<Path>,
    F: Fn(&str) -> Result<T, String>,
{
    for dir in dirs {
        let path = dir.as_ref().join(name);
        if path.exists() {
            if let Ok(text) = read_data_text(&path) {
                if let Ok(table) = parse(&text) {
                    return table;
                }
            }
        }
    }
    parse(empty).expect("parsing the empty table cannot fail")
}

/// json.load(fs) on text (serde_json, insertion order kept, a repeated key
/// keeps its first position and takes the last value like a Python dict).
pub(crate) fn parse_json(text: &str) -> Result<Value, String> {
    serde_json::from_str(text).map_err(|e| format!("JSONDecodeError: {}", e))
}

/// `self.__dict__.update(json.load(fs))` for the json tables: returns the
/// (name, value) assignments in order. dict.update accepts a mapping, or an
/// iterable of 2-item iterables (a 2-item list, a 2-character string, a dict
/// with 2 keys — its keys); anything else raises.
pub(crate) fn dict_update_items(value: Value) -> Result<Vec<(Option<String>, Value)>, String> {
    match value {
        Value::Object(map) => Ok(map.into_iter().map(|(k, v)| (Some(k), v)).collect()),
        Value::String(s) => {
            if s.is_empty() {
                Ok(Vec::new())
            } else {
                Err("ValueError: dictionary update sequence element #0 has length 1; 2 is required".into())
            }
        }
        Value::Array(items) => {
            let mut out = Vec::new();
            for (i, item) in items.into_iter().enumerate() {
                let (k, v) = match item {
                    Value::Array(mut pair) if pair.len() == 2 => {
                        let v = pair.pop().unwrap();
                        let k = pair.pop().unwrap();
                        (k, v)
                    }
                    Value::String(s) if s.chars().count() == 2 => {
                        let mut it = s.chars();
                        let a = it.next().unwrap().to_string();
                        let b = it.next().unwrap().to_string();
                        (Value::String(a), Value::String(b))
                    }
                    Value::Object(map) if map.len() == 2 => {
                        let mut it = map.into_iter();
                        let a = it.next().unwrap().0;
                        let b = it.next().unwrap().0;
                        (Value::String(a), Value::String(b))
                    }
                    _ => return Err(format!("dictionary update sequence element #{} is not a 2-item sequence", i)),
                };
                let name = match k {
                    Value::String(s) => Some(s),
                    // hashable non-str keys land in __dict__ but are never read
                    Value::Null | Value::Bool(_) | Value::Number(_) => None,
                    _ => return Err("TypeError: unhashable type".into()),
                };
                out.push((name, v));
            }
            Ok(out)
        }
        _ => Err("TypeError: object is not iterable".into()),
    }
}

pub(crate) fn json_string_list(v: Value, what: &str) -> Result<Vec<String>, String> {
    match v {
        Value::Array(items) => items
            .into_iter()
            .map(|x| match x {
                Value::String(s) => Ok(s),
                _ => Err(format!("unsupported {}: not a list of str", what)),
            })
            .collect(),
        _ => Err(format!("unsupported {}: not a list", what)),
    }
}

pub(crate) fn json_chardefs(v: Value, what: &str) -> Result<CharDefs, String> {
    match v {
        Value::Object(map) => {
            let mut out = CharDefs::with_capacity(map.len());
            for (k, v) in map {
                out.insert(k, json_string_list(v, what)?);
            }
            Ok(out)
        }
        _ => Err(format!("unsupported {}: not a dict", what)),
    }
}

/// The keynames/chardefs json tables (msymbols, dsymbols, phrase):
/// `self.keynames = []; self.chardefs = {}; self.__dict__.update(json.load(fs))`.
pub(crate) fn parse_keynames_chardefs(text: &str) -> Result<(Vec<String>, CharDefs), String> {
    let mut keynames = Vec::new();
    let mut chardefs = CharDefs::new();
    for (name, value) in dict_update_items(parse_json(text)?)? {
        match name.as_deref() {
            Some("keynames") => keynames = json_string_list(value, "keynames")?,
            Some("chardefs") => chardefs = json_chardefs(value, "chardefs")?,
            _ => {}
        }
    }
    Ok((keynames, chardefs))
}

// ---------------------------------------------------------------------------
// mbcs

/// bytes.decode('mbcs', errors='replace') as CPython does it on Windows:
/// one strict MultiByteToWideChar(CP_ACP, MB_ERR_INVALID_CHARS) over the whole
/// buffer; if that fails, character by character trying 1..=4 bytes, and a
/// byte that starts no valid character becomes U+FFFD.
#[cfg(windows)]
pub fn mbcs_decode_replace(raw: &[u8]) -> String {
    const CP_ACP: u32 = 0;
    const MB_ERR_INVALID_CHARS: u32 = 0x8;
    #[link(name = "kernel32")]
    extern "system" {
        fn MultiByteToWideChar(cp: u32, flags: u32, src: *const u8, srclen: i32, dst: *mut u16, dstlen: i32) -> i32;
    }
    fn convert(bytes: &[u8]) -> Option<Vec<u16>> {
        if bytes.is_empty() {
            return Some(Vec::new());
        }
        let n = unsafe { MultiByteToWideChar(CP_ACP, MB_ERR_INVALID_CHARS, bytes.as_ptr(), bytes.len() as i32, std::ptr::null_mut(), 0) };
        if n <= 0 {
            return None;
        }
        let mut buf = vec![0u16; n as usize];
        let m = unsafe { MultiByteToWideChar(CP_ACP, MB_ERR_INVALID_CHARS, bytes.as_ptr(), bytes.len() as i32, buf.as_mut_ptr(), n) };
        if m <= 0 {
            return None;
        }
        buf.truncate(m as usize);
        Some(buf)
    }
    if let Some(w) = convert(raw) {
        return String::from_utf16_lossy(&w);
    }
    let mut out: Vec<u16> = Vec::with_capacity(raw.len());
    let mut i = 0;
    while i < raw.len() {
        let mut decoded = None;
        let mut size = 1;
        while size <= 4 && i + size <= raw.len() {
            if let Some(w) = convert(&raw[i..i + size]) {
                decoded = Some(w);
                break;
            }
            size += 1;
        }
        match decoded {
            Some(w) => {
                out.extend_from_slice(&w);
                i += size;
            }
            None => {
                out.push(0xFFFD);
                i += 1;
            }
        }
    }
    String::from_utf16_lossy(&out)
}

#[cfg(not(windows))]
pub fn mbcs_decode_replace(raw: &[u8]) -> String {
    String::from_utf8_lossy(raw).into_owned()
}
