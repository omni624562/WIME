//! phrase.py (phrase.json, the built-in 聯想詞 table) and the loading done by
//! LoadPhraseData (cinbase/__init__.py): findFile(datadirs, "phrase.json"),
//! io.open(path, encoding='utf8') — strict UTF-8, no BOM stripping (a BOM makes
//! json.load raise) — and any exception leaves PhraseData.phrase = None.

use super::{find_file, parse_keynames_chardefs, read_utf8_text, CharDefs, EMPTY};
use std::path::Path;

#[derive(Debug, Clone, Default)]
pub struct Phrase {
    pub keynames: Vec<String>,
    pub chardefs: CharDefs,
}

impl Phrase {
    /// phrase(fs) over the file text.
    pub fn parse(text: &str) -> Result<Phrase, String> {
        let (keynames, chardefs) = parse_keynames_chardefs(text)?;
        Ok(Phrase { keynames, chardefs })
    }

    /// phrase(io.open(path, 'r', encoding='utf8'))
    pub fn from_file(path: &Path) -> Result<Phrase, String> {
        Self::parse(&read_utf8_text(path)?)
    }

    /// LoadPhraseData.run: None when missing or unreadable.
    pub fn load<P: AsRef<Path>>(datadirs: &[P]) -> Option<Phrase> {
        let path = find_file(datadirs, "phrase.json")?;
        Self::from_file(&path).ok()
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
