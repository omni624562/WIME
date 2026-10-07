//! symbols.py (symbols.dat, the 特殊符號 menu). flangs.py is the same class.
//!
//! Line format `名稱=內容` (or space / tab separated): a category whose
//! content is split into symbols by symbolClusters. A line without any
//! separator is a leaf: a single symbol shown at the top level that commits
//! directly; getCharDef(leaf) is [leaf]. A name that is also a category stays
//! a category.

use super::textclusters::symbol_clusters;
use super::{clean_line, py_lines, py_strip, split1, CharDefs, EMPTY};
use indexmap::IndexSet;
use std::collections::HashSet;

#[derive(Debug, Clone, Default)]
pub struct Symbols {
    pub keynames: Vec<String>,
    /// categories in first-seen order, then the leaves (Python adds the leaves
    /// in set order, which is arbitrary; nothing iterates this dict)
    pub chardefs: CharDefs,
    pub leaves: IndexSet<String>,
}

/// safeSplit: (name, Some(content)), or (line, None) without a separator.
fn safe_split(line: &str) -> (&str, Option<&str>) {
    for sep in ['=', ' ', '\t'] {
        if line.contains(sep) {
            let (k, r) = split1(line, sep);
            return (k, Some(r));
        }
    }
    (line, None)
}

impl Symbols {
    /// symbols(fs) over readDataText text. Never fails.
    pub fn from_text(text: &str) -> Symbols {
        let mut keynames = Vec::new();
        let mut chardefs = CharDefs::new();
        let mut leaves: IndexSet<String> = IndexSet::new();
        let mut seen: HashSet<String> = HashSet::new();
        let mut categories: HashSet<String> = HashSet::new();

        for line in py_lines(text) {
            let line = clean_line(line);
            if line.is_empty() {
                continue;
            }
            let (key, root) = safe_split(line);
            let key = py_strip(key);
            match root {
                None => {
                    leaves.insert(key.to_string());
                }
                Some(root) => {
                    let root = py_strip(root);
                    if key.is_empty() || root.is_empty() {
                        continue;
                    }
                    categories.insert(key.to_string());
                    chardefs.entry(key.to_string()).or_default().extend(symbol_clusters(root));
                }
            }
            if seen.insert(key.to_string()) {
                keynames.push(key.to_string());
            }
        }

        leaves.retain(|k| !categories.contains(k));
        for key in &leaves {
            chardefs.insert(key.clone(), vec![key.clone()]);
        }
        Symbols { keynames, chardefs, leaves }
    }

    /// For CinBase.loadDataFile.
    pub fn parse(text: &str) -> Result<Symbols, String> {
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

    pub fn is_leaf(&self, key: &str) -> bool {
        self.leaves.contains(key)
    }
}
