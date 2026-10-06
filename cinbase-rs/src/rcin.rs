//! Port of python/cinbase/rcin.py (class RCin): the reverse-lookup table that
//! shows the code of a committed char in another input method (反查).
//!
//! Unlike Cin: no private-use removal, no counts, getCharDef raises KeyError
//! for a missing code, and getCharEncode lists every code (the marker stops
//! advancing at ⑩) and returns "" for a char without codes.

use crate::cin::{build_reverse_index, key_name, parse_table, push_key_names, read_table_file};
use indexmap::IndexMap;
use std::collections::HashMap;
use std::path::Path;

const ENCODE_NUMBERS: [&str; 10] = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];

pub struct RCin {
    pub ime_dir_name: String,
    pub ename: String,
    pub cname: String,
    pub selkey: String,
    keynames: IndexMap<String, String>,
    chardefs: IndexMap<String, Vec<String>>,
    char_to_keys: HashMap<String, Vec<String>>,
}

/// getCharEncode shared by RCin and HCin.
pub(crate) fn char_encode_all(root: &str, keys: Option<&Vec<String>>, keynames: &IndexMap<String, String>) -> String {
    let Some(keys) = keys.filter(|k| !k.is_empty()) else {
        return String::new();
    };
    let mut result = format!("{}:", root);
    let mut i = 0;
    for chardef in keys {
        result.push('　');
        result.push_str(ENCODE_NUMBERS[i]);
        if i < 9 {
            i += 1;
        }
        push_key_names(&mut result, keynames, chardef);
    }
    result
}

impl RCin {
    /// `RCin(open(path), imeDirName)`
    pub fn load(path: &Path, ime_dir_name: &str) -> Result<RCin, String> {
        RCin::from_json(&read_table_file(path)?, ime_dir_name)
    }

    pub fn from_json(text: &str, ime_dir_name: &str) -> Result<RCin, String> {
        let t = parse_table(text)?;
        let char_to_keys = build_reverse_index(&t.chardefs);
        Ok(RCin {
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

    const TABLE: &str = r#"{"ename":"t","cname":"測","selkey":"123","keynames":{"a":"日","b":"月"},
        "chardefs":{"ab":["明","朋"],"a":["日","明"],"b":["月"],"bb":["朋","朋"],
        "c1":["多"],"c2":["多"],"c3":["多"],"c4":["多"],"c5":["多"],"c6":["多"],"c7":["多"],"c8":["多"],"c9":["多"],"ca":["多"],"cb":["多"]},
        "cincount":{"big5F":1}}"#;

    #[test]
    fn basics() {
        let mut r = RCin::from_json(TABLE, "x").unwrap();
        assert_eq!(r.get_char_encode("明"), "明:　①日月　②日");
        assert_eq!(r.get_char_encode("朋"), "朋:　①日月　②月月　③月月");
        assert_eq!(r.get_char_encode("無"), "");
        assert_eq!(
            r.get_char_encode("多"),
            "多:　①c1　②c2　③c3　④c4　⑤c5　⑥c6　⑦c7　⑧c8　⑨c9　⑩c日　⑩c月"
        );
        assert_eq!(r.get_key("朋").unwrap(), "ab");
        assert!(r.get_key("無").is_err());
        assert!(r.get_char_def("zz").is_err());
        assert_eq!(r.get_char_def("a").unwrap(), ["日", "明"]);
        r.close();
        assert!(!r.is_have_key("明"));
        assert_eq!(r.get_char_encode("明"), "");
    }
}
