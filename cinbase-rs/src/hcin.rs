//! Port of python/cinbase/hcin.py (class HCin): the homophone table (同音字,
//! a phonetic table such as thphonetic.json / bpmf.json).
//!
//! Same as RCin plus getKeyList (the char's distinct codes in sorted order)
//! and getKeyNameList (each code spelled with key names).

use crate::cin::{build_reverse_index, key_name, parse_table, push_key_names, read_table_file};
use crate::rcin::char_encode_all;
use indexmap::IndexMap;
use std::collections::HashMap;
use std::path::Path;

pub struct HCin {
    pub ime_dir_name: String,
    pub ename: String,
    pub cname: String,
    pub selkey: String,
    keynames: IndexMap<String, String>,
    chardefs: IndexMap<String, Vec<String>>,
    char_to_keys: HashMap<String, Vec<String>>,
}

impl HCin {
    /// `HCin(open(path), imeDirName)`
    pub fn load(path: &Path, ime_dir_name: &str) -> Result<HCin, String> {
        HCin::from_json(&read_table_file(path)?, ime_dir_name)
    }

    pub fn from_json(text: &str, ime_dir_name: &str) -> Result<HCin, String> {
        let t = parse_table(text)?;
        let char_to_keys = build_reverse_index(&t.chardefs);
        Ok(HCin {
            ime_dir_name: ime_dir_name.to_string(),
            ename: t.ename,
            cname: t.cname,
            selkey: t.selkey,
            keynames: t.keynames,
            chardefs: t.chardefs,
            char_to_keys,
        })
    }

    /// Python `__del__`: empties keynames, chardefs and the reverse index.
    pub fn close(&mut self) {
        self.keynames = IndexMap::new();
        self.chardefs = IndexMap::new();
        self.char_to_keys = HashMap::new();
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

    pub fn is_in_key_name(&self, key: &str) -> bool {
        self.keynames.contains_key(key)
    }

    pub fn get_key_name<'a>(&'a self, key: &'a str) -> &'a str {
        key_name(&self.keynames, key)
    }

    pub fn is_have_key(&self, val: &str) -> bool {
        self.char_to_keys.contains_key(val)
    }

    /// Err (KeyError) for a char without codes.
    pub fn get_key(&self, val: &str) -> Result<&str, String> {
        self.char_to_keys.get(val).map(|k| k[0].as_str()).ok_or_else(|| format!("KeyError: '{}'", val))
    }

    /// sorted(set(codes of val)); empty for an unknown char.
    pub fn get_key_list(&self, val: &str) -> Vec<String> {
        let mut keys: Vec<String> = self.char_to_keys.get(val).cloned().unwrap_or_default();
        keys.sort_unstable();
        keys.dedup();
        keys
    }

    /// Each code spelled with key names.
    pub fn get_key_name_list(&self, key_list: &[String]) -> Vec<String> {
        key_list
            .iter()
            .map(|key| {
                let mut name = String::new();
                push_key_names(&mut name, &self.keynames, key);
                name
            })
            .collect()
    }

    pub fn is_in_char_def(&self, key: &str) -> bool {
        self.chardefs.contains_key(key)
    }

    /// Err (KeyError) for a missing code.
    pub fn get_char_def(&self, key: &str) -> Result<&[String], String> {
        self.chardefs.get(key).map(|v| v.as_slice()).ok_or_else(|| format!("KeyError: '{}'", key))
    }

    /// `字:　①..` with every code, "" when the char has none.
    pub fn get_char_encode(&self, root: &str) -> String {
        char_encode_all(root, self.char_to_keys.get(root), &self.keynames)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn key_list_sorted_distinct() {
        let h = HCin::from_json(
            r#"{"keynames":{"j":"ㄨ","4":"ˋ"},"chardefs":{"j4":["兀","兀"],"cji4":["兀"],"a":["兀"]}}"#,
            "x",
        )
        .unwrap();
        assert_eq!(h.get_key_list("兀"), ["a", "cji4", "j4"]);
        assert_eq!(h.get_key_name_list(&h.get_key_list("兀")), ["a", "cㄨiˋ", "ㄨˋ"]);
        assert_eq!(h.get_key("兀").unwrap(), "j4");
        assert_eq!(h.get_char_encode("兀"), "兀:　①ㄨˋ　②ㄨˋ　③cㄨiˋ　④a");
        assert!(h.get_key_list("無").is_empty());
    }
}
