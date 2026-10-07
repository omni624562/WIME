//! msymbols.py (msymbols.json, Ctrl / ` symbol tables). dsymbols.py is the
//! same class. `self.keynames = []; self.chardefs = {}` then
//! `self.__dict__.update(json.load(fs))`.
//!
//! Not modelled: JSON whose keynames/chardefs are not a list of str / a dict
//! of lists of str (Python would load it and fail later, or behave oddly; here
//! the parse fails, so loadDataFile falls back to the shipped file), and keys
//! that would shadow methods (e.g. "getCharDef"). serde_json also rejects
//! NaN/Infinity and lone surrogate escapes that Python's json accepts.

use super::{key_error, parse_keynames_chardefs, CharDefs};

#[derive(Debug, Clone, Default)]
pub struct MSymbols {
    pub keynames: Vec<String>,
    pub chardefs: CharDefs,
}

impl MSymbols {
    /// msymbols(fs) over readDataText text; Err = json.load / update raised.
    pub fn parse(text: &str) -> Result<MSymbols, String> {
        let (keynames, chardefs) = parse_keynames_chardefs(text)?;
        Ok(MSymbols { keynames, chardefs })
    }

    pub fn is_in_char_def(&self, key: &str) -> bool {
        self.chardefs.contains_key(key)
    }

    /// chardefs[key]: KeyError when missing.
    pub fn get_char_def(&self, key: &str) -> Result<&[String], String> {
        self.chardefs.get(key).map(|v| v.as_slice()).ok_or_else(|| key_error(key))
    }

    pub fn get_key_names(&self) -> &[String] {
        &self.keynames
    }

    /// Some key's candidate list contains val.
    pub fn is_have_key(&self, val: &str) -> bool {
        self.chardefs.values().any(|v| v.iter().any(|x| x == val))
    }

    /// The first key (in table order) whose candidates contain val;
    /// IndexError when there is none.
    pub fn get_key(&self, val: &str) -> Result<&str, String> {
        self.chardefs
            .iter()
            .find(|(_, v)| v.iter().any(|x| x == val))
            .map(|(k, _)| k.as_str())
            .ok_or_else(|| "IndexError: list index out of range".to_string())
    }
}
