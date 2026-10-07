//! fsymbols.py (fsymbols.dat, full-shape symbols keyed by the half-shape key).
//! Unlike symbols.dat, a line without a separator is `key = content = line`.

use super::textclusters::symbol_clusters;
use super::{clean_line, py_lines, py_strip, split1, CharDefs, EMPTY};
use std::collections::HashSet;

#[derive(Debug, Clone, Default)]
pub struct FSymbols {
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

impl FSymbols {
    pub fn from_text(text: &str) -> FSymbols {
        let mut keynames = Vec::new();
        let mut chardefs = CharDefs::new();
        let mut seen: HashSet<String> = HashSet::new();
        for line in py_lines(text) {
            let line = clean_line(line);
            if line.is_empty() {
                continue;
            }
            let (key, root) = safe_split(line);
            let key = py_strip(key);
            let root = py_strip(root);
            if key.is_empty() || root.is_empty() {
                continue;
            }
            chardefs.entry(key.to_string()).or_default().extend(symbol_clusters(root));
            if seen.insert(key.to_string()) {
                keynames.push(key.to_string());
            }
        }
        FSymbols { keynames, chardefs }
    }

    pub fn parse(text: &str) -> Result<FSymbols, String> {
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
