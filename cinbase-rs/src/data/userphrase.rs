//! userphrase.py (userphrase.dat, and excludephrase.dat which uses the same
//! class): `字=詞,詞,...` (or space / tab separated); a line without a
//! separator is `key = line`, its candidates are `line` split on commas.
//! Empty candidates are dropped; lines without key or candidates are skipped.

use super::{clean_line, py_lines, py_strip, split1, CharDefs, EMPTY};
use std::collections::HashSet;

#[derive(Debug, Clone, Default)]
pub struct UserPhrase {
    pub keynames: Vec<String>,
    pub chardefs: CharDefs,
}

fn safe_split(line: &str) -> (&str, &str) {
    for sep in ['=', ' ', '\t'] {
        if line.contains(sep) {
            return split1(line, sep);
        }
    }
    (line, line)
}

impl UserPhrase {
    pub fn from_text(text: &str) -> UserPhrase {
        let mut keynames = Vec::new();
        let mut chardefs = CharDefs::new();
        let mut seen: HashSet<String> = HashSet::new();
        for line in py_lines(text) {
            let line = clean_line(line);
            let (key, root) = safe_split(line);
            let key = py_strip(key);
            // rootSplit: line.split(',') (a string without ',' is [line])
            let candidates: Vec<String> =
                root.split(',').map(py_strip).filter(|s| !s.is_empty()).map(str::to_string).collect();
            if key.is_empty() || candidates.is_empty() {
                continue;
            }
            chardefs.entry(key.to_string()).or_default().extend(candidates);
            if seen.insert(key.to_string()) {
                keynames.push(key.to_string());
            }
        }
        UserPhrase { keynames, chardefs }
    }

    pub fn parse(text: &str) -> Result<UserPhrase, String> {
        Ok(Self::from_text(text))
    }

    pub fn is_in_char_def(&self, key: &str) -> bool {
        self.chardefs.contains_key(key)
    }

    /// chardefs.get(key, [])
    pub fn get_char_def(&self, key: &str) -> &[String] {
        self.chardefs.get(key).map(|v| v.as_slice()).unwrap_or(&EMPTY)
    }

    pub fn get_key_names(&self) -> &[String] {
        &self.keynames
    }
}
