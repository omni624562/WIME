//! emoji.py (emoji.json, the 表情符號 menu; always the shipped file, opened
//! by CinBase.__init__ with io.open(..., encoding='utf8')).
//!
//! getCharDef maps a group's keyname to its sub-dict by POSITION in a fixed
//! key list (not by name): keynames.index(keyname) -> keys[index] -> dict[key].

use super::{dict_update_items, json_chardefs, json_string_list, parse_json, read_utf8_text, CharDefs, EMPTY};
use std::path::Path;

#[derive(Debug, Clone, Default)]
pub struct Emoji {
    pub dingbats: CharDefs,
    pub dingbats_keynames: Vec<String>,
    pub emoticons: CharDefs,
    pub emoticons_keynames: Vec<String>,
    pub miscellaneous: CharDefs,
    pub miscellaneous_keynames: Vec<String>,
    pub modifiercolor: Vec<String>,
    pub pictographs: CharDefs,
    pub pictographs_keynames: Vec<String>,
    pub transport: CharDefs,
    pub transport_keynames: Vec<String>,
}

const DINGBATS_KEYS: &[&str] =
    &["miscellaneous", "crosses", "starsandsnows", "fleurons", "punctuationmarks", "brackets", "digits", "arrows", "arithmetics"];
const EMOTICONS_KEYS: &[&str] = &["faces", "catfaces", "animal", "gesture"];
const MISCELLANEOUS_KEYS: &[&str] = &[
    "weathers", "miscellaneous", "chess", "pointinghand", "warningsigns", "medical", "religiousandpolitical", "yijingtrigram", "emoticons",
    "zodiacal", "musical", "syriaccross", "recycling", "map", "gender", "circlesandpentagram", "genealogical", "sport", "trafficsigns",
];
const PICTOGRAPHS_KEYS: &[&str] = &[
    "portraitandrole", "animal", "plant", "romance", "heart", "comicstyle", "bubble", "weatherandlandscape", "globe", "moonsunandstar",
    "food", "fruitandvegetable", "beverage", "celebration", "musical", "entertainment", "game", "sport", "buildingandmap", "flag",
    "miscellaneous", "facialparts", "hand", "clothing", "personalcare", "medical", "schoolgrade", "money", "office", "communication",
    "audioandvideo", "religious", "userinterface", "wordswitharrows", "tool", "geometricshapes", "clockface", "computer",
];
const TRANSPORT_KEYS: &[&str] = &["vehicles", "trafficsigns", "accommodation", "miscellaneous"];

fn lookup<'a>(keynames: &[String], keys: &[&str], dict: &'a CharDefs, keyname: &str) -> Result<&'a [String], String> {
    let index = keynames
        .iter()
        .position(|k| k == keyname)
        .ok_or_else(|| format!("ValueError: '{}' is not in list", keyname))?;
    let key = keys.get(index).ok_or_else(|| "IndexError: list index out of range".to_string())?;
    dict.get(*key).map(|v| v.as_slice()).ok_or_else(|| format!("KeyError: '{}'", key))
}

impl Emoji {
    /// emoji(fs) over the file text. Every attribute the callers read must be
    /// present (Python would raise AttributeError when it is used instead).
    pub fn parse(text: &str) -> Result<Emoji, String> {
        let mut e = Emoji::default();
        let mut have = std::collections::HashSet::new();
        for (name, value) in dict_update_items(parse_json(text)?)? {
            let Some(name) = name else { continue };
            match name.as_str() {
                "dingbats" => e.dingbats = json_chardefs(value, &name)?,
                "emoticons" => e.emoticons = json_chardefs(value, &name)?,
                "miscellaneous" => e.miscellaneous = json_chardefs(value, &name)?,
                "pictographs" => e.pictographs = json_chardefs(value, &name)?,
                "transport" => e.transport = json_chardefs(value, &name)?,
                "dingbats_keynames" => e.dingbats_keynames = json_string_list(value, &name)?,
                "emoticons_keynames" => e.emoticons_keynames = json_string_list(value, &name)?,
                "miscellaneous_keynames" => e.miscellaneous_keynames = json_string_list(value, &name)?,
                "pictographs_keynames" => e.pictographs_keynames = json_string_list(value, &name)?,
                "transport_keynames" => e.transport_keynames = json_string_list(value, &name)?,
                "modifiercolor" => e.modifiercolor = json_string_list(value, &name)?,
                _ => continue,
            }
            have.insert(name);
        }
        if have.len() != 11 {
            return Err("AttributeError: emoji.json lacks a group".into());
        }
        Ok(e)
    }

    /// emoji(io.open(path, 'r', encoding='utf8'))
    pub fn from_file(path: &Path) -> Result<Emoji, String> {
        Self::parse(&read_utf8_text(path)?)
    }

    /// getCharDef(emojitype, keyname): ValueError / IndexError / KeyError as
    /// Err; an unknown emojitype gives [].
    pub fn get_char_def(&self, emojitype: &str, keyname: &str) -> Result<&[String], String> {
        match emojitype {
            "dingbats" => lookup(&self.dingbats_keynames, DINGBATS_KEYS, &self.dingbats, keyname),
            "emoticons" => lookup(&self.emoticons_keynames, EMOTICONS_KEYS, &self.emoticons, keyname),
            "miscellaneous" => lookup(&self.miscellaneous_keynames, MISCELLANEOUS_KEYS, &self.miscellaneous, keyname),
            "pictographs" => lookup(&self.pictographs_keynames, PICTOGRAPHS_KEYS, &self.pictographs, keyname),
            "transport" => lookup(&self.transport_keynames, TRANSPORT_KEYS, &self.transport, keyname),
            _ => Ok(&EMPTY),
        }
    }

    /// getKeyNames(emojidict) returns its argument.
    pub fn get_key_names<'a>(&self, emojidict: &'a [String]) -> &'a [String] {
        emojidict
    }
}
