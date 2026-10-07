//! extendtable.py (extendtable.dat, user additions to the cin table):
//! `key candidate`, space or tab separated; the key is lower-cased.
//! getCharDef raises KeyError. cin.updateCinTable iterates `chardefs` in order.

use super::swkb::safe_split_ws;
use super::{clean_line, key_error, py_lines, py_strip, CharDefs};

#[derive(Debug, Clone, Default)]
pub struct ExtendTable {
    pub chardefs: CharDefs,
}

impl ExtendTable {
    pub fn from_text(text: &str) -> ExtendTable {
        let mut chardefs = CharDefs::new();
        for line in py_lines(text) {
            let line = clean_line(line);
            let (key, root) = safe_split_ws(line);
            let key = key.to_lowercase();
            let key = py_strip(&key);
            let root = py_strip(root);
            if key.is_empty() || root.is_empty() {
                continue;
            }
            chardefs.entry(key.to_string()).or_default().push(root.to_string());
        }
        ExtendTable { chardefs }
    }

    pub fn parse(text: &str) -> Result<ExtendTable, String> {
        Ok(Self::from_text(text))
    }

    pub fn is_in_char_def(&self, key: &str) -> bool {
        self.chardefs.contains_key(key)
    }

    /// chardefs[key]: KeyError when missing.
    pub fn get_char_def(&self, key: &str) -> Result<&[String], String> {
        self.chardefs.get(key).map(|v| v.as_slice()).ok_or_else(|| key_error(key))
    }
}
