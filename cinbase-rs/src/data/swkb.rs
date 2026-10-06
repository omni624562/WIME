//! swkb.py (swkb.dat, Shift + key easy symbols): `KEY content`, space or tab
//! separated; the key is upper-cased. getCharDef raises KeyError.

use super::{clean_line, key_error, py_lines, py_strip, split1, CharDefs};

#[derive(Debug, Clone, Default)]
pub struct Swkb {
    pub chardefs: CharDefs,
}

/// safeSplit shared with extendtable.py: space, then tab, else (line, "").
pub(crate) fn safe_split_ws(line: &str) -> (&str, &str) {
    for sep in [' ', '\t'] {
        if line.contains(sep) {
            return split1(line, sep);
        }
    }
    (line, "")
}

impl Swkb {
    pub fn from_text(text: &str) -> Swkb {
        let mut chardefs = CharDefs::new();
        for line in py_lines(text) {
            let line = clean_line(line);
            let (key, root) = safe_split_ws(line);
            let key = key.to_uppercase();
            let key = py_strip(&key);
            let root = py_strip(root);
            if key.is_empty() || root.is_empty() {
                continue;
            }
            chardefs.entry(key.to_string()).or_default().push(root.to_string());
        }
        Swkb { chardefs }
    }

    pub fn parse(text: &str) -> Result<Swkb, String> {
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
