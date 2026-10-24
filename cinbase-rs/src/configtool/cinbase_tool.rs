//! Port of python/cinbase/configtool.py: the 大易/酷倉 (cinbase) settings tool.
//!
//! GET /config answers {"imename", "config", "cincount", "rcinAvailable",
//! "symbols", "swkb", "fsymbols", "phrase", "excludePhrase", "flangs",
//! "extendtable"}; POST /config writes the parts it is given into
//! %APPDATA%\PIME\<ime>. Like the Python tool the settings object lives as long
//! as the process (the module-level CinBaseConfig), and is reloaded for every GET.

use super::assets::Assets;
use super::server::{log, HandlerResult, HttpError, Request, Response, Route, Target, Tool};
use super::{pyjson, save_text_file};
use crate::config::{mtime, CinBaseConfig, RCIN_FILE_LIST};
use serde::de::{Deserializer, IgnoredAny, MapAccess, Visitor};
use serde_json::{Map, Value};
use std::collections::HashMap;
use std::fmt;
use std::path::{Path, PathBuf};

pub const COOKIE_ID: &str = "cinbase_config_token";

/// CinBaseConfig.ignoreSaveList: never written to config.json by a POST
const IGNORE_SAVE_LIST: &[&str] = &["ignoreSaveList", "curdir", "cinFileList", "selCinFile", "imeDirName", "_version", "_lastUpdateTime"];

/// load_cindata's CinDict: the tables of each IME, indexed by selCinType
fn cin_files(ime: &str) -> Option<&'static [&'static str]> {
    Some(match ime {
        "checj" => &["checj.json", "mscj3.json", "mscj3-ext.json", "cj-ext.json", "cnscj.json", "thcj.json", "newcj3.json", "cj5.json", "newcj.json", "scj6.json", "cj-fast.json"],
        "chephonetic" => &["thphonetic.json", "CnsPhonetic.json", "bpmf.json"],
        "chearray" => &["tharray.json", "array30.json", "ar30-big.json", "array40.json"],
        "chedayi" => &["thdayi.json", "dayi4.json", "dayi3.json"],
        "cheez" => &["ez.json", "ezsmall.json", "ezmid.json", "ezbig.json"],
        "chepinyin" => &["thpinyin.json", "pinyin.json", "roman.json"],
        "chesimplex" => &["simplecj.json", "simplex.json", "simplex5.json"],
        "cheliu" => &["liu.json"],
        _ => return None,
    })
}

/// json.load(f).get("cincount") without building the whole table: only the
/// top-level "cincount" (the last one, like a dict) is kept. Err: the file is
/// not JSON, or its top level is not an object (Python's .get fails).
fn read_cincount(path: &Path) -> Result<Value, String> {
    struct TopLevel;
    impl<'de> Visitor<'de> for TopLevel {
        type Value = Value;
        fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
            f.write_str("a JSON object")
        }
        fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
            let mut cincount = Value::Null;
            while let Some(key) = map.next_key::<std::borrow::Cow<'de, str>>()? {
                if key == "cincount" {
                    cincount = map.next_value::<Value>()?;
                } else {
                    map.next_value::<IgnoredAny>()?;
                }
            }
            Ok(cincount)
        }
    }
    let data = std::fs::read(path).map_err(|e| e.to_string())?;
    // open(..., encoding="UTF-8"): a BOM is not skipped (json.load then fails)
    let mut de = serde_json::Deserializer::from_slice(&data);
    let value = (&mut de).deserialize_map(TopLevel).map_err(|e| e.to_string())?;
    de.end().map_err(|e| e.to_string())?;
    Ok(value)
}

/// open(path, "r", encoding="UTF-8").read(): strict UTF-8, universal newlines
fn read_text(path: &Path) -> std::io::Result<String> {
    let raw = std::fs::read(path)?;
    let text = String::from_utf8(raw).map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
    Ok(text.replace("\r\n", "\n").replace('\r', "\n"))
}

pub struct CinbaseTool {
    ime: String,
    cfg: CinBaseConfig,
    assets: Assets,
    /// %APPDATA%\PIME\<ime>
    config_dir: PathBuf,
    /// (table path -> (mtime, cincount)): a table JSON can be several MB
    cincount_cache: HashMap<PathBuf, (f64, Value)>,
}

impl CinbaseTool {
    pub fn new(ime: &str, assets: Assets) -> CinbaseTool {
        let mut cfg = CinBaseConfig::new();
        cfg.ime_dir_name = ime.to_string();
        let config_dir = cfg.get_config_dir(); // created, like the Python module does on import
        CinbaseTool { ime: ime.to_string(), cfg, assets, config_dir, cincount_cache: HashMap::new() }
    }

    /// ConfigHandler.load_config: reload and return the settings
    fn load_config(&mut self) -> Value {
        self.cfg.load();
        Value::Object(self.cfg.to_json())
    }

    /// ConfigHandler.load_rcin_available: the reverse-lookup tables installed
    fn load_rcin_available(&self) -> Value {
        let json_dir = self.assets.cinbase_json_dir();
        Value::Array(
            RCIN_FILE_LIST.iter().enumerate().filter(|(_, name)| json_dir.join(name).exists()).map(|(i, _)| Value::from(i)).collect(),
        )
    }

    /// ConfigHandler.load_cindata: the selected table's "cincount" (None when
    /// the IME has no table list or the table is missing / unreadable)
    fn load_cindata(&mut self) -> Value {
        let Some(files) = cin_files(&self.ime) else { return Value::Null };
        let sel = self.cfg.sel_cin_type;
        let idx = if sel >= 0 && (sel as usize) < files.len() { sel as usize } else { 0 };
        let datafile = self.assets.cinbase_json_dir().join(files[idx]);
        if !datafile.exists() {
            return Value::Null;
        }
        let Some(t) = mtime(&datafile) else { return Value::Null };
        if let Some((cached_mtime, cincount)) = self.cincount_cache.get(&datafile) {
            if *cached_mtime == t {
                return cincount.clone();
            }
        }
        match read_cincount(&datafile) {
            Ok(cincount) => {
                self.cincount_cache.insert(datafile, (t, cincount.clone()));
                cincount
            }
            Err(e) => {
                log(&e);
                Value::Null
            }
        }
    }

    /// ConfigHandler.load_data: the user's file, else the shipped one (whose
    /// errors are not caught: the whole GET fails), "" for an unreadable user file
    fn load_data(&self, name: &str) -> Result<Value, HttpError> {
        match read_text(&self.config_dir.join(name)) {
            Ok(text) => Ok(Value::String(text)),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                let default = self.assets.cinbase_data_dir().join(name);
                read_text(&default).map(Value::String).map_err(|e| HttpError::Internal(format!("{}: {}", default.display(), e)))
            }
            Err(_) => Ok(Value::String(String::new())),
        }
    }

    fn get_config(&mut self) -> HandlerResult {
        let mut data = Map::new();
        data.insert("imename".into(), Value::String(self.ime.clone()));
        let config = self.load_config();
        data.insert("config".into(), config);
        let cincount = self.load_cindata();
        data.insert("cincount".into(), cincount);
        data.insert("rcinAvailable".into(), self.load_rcin_available());
        for (key, file) in [
            ("symbols", "symbols.dat"),
            ("swkb", "swkb.dat"),
            ("fsymbols", "fsymbols.dat"),
            ("phrase", "userphrase.dat"),
            ("excludePhrase", "excludephrase.dat"),
            ("flangs", "flangs.dat"),
            ("extendtable", "extendtable.dat"),
        ] {
            data.insert(key.into(), self.load_data(file)?);
        }
        let mut response = Response::new();
        response.write_json(&Value::Object(data));
        Ok(response)
    }

    /// ConfigHandler.save_all: Err(io) is an OSError (answered 500 "Cannot save
    /// the settings"), Err(other) any other exception
    fn save_all(&self, data: &Map<String, Value>) -> Result<(), Result<std::io::Error, String>> {
        std::fs::create_dir_all(&self.config_dir).map_err(Ok)?;
        if let Some(config) = data.get("config").filter(|v| !v.is_null()) {
            let mut config = config.clone();
            // internal attributes must never come from a POST (they would move file paths on the next load)
            if let Value::Object(map) = &mut config {
                for key in IGNORE_SAVE_LIST {
                    map.shift_remove(*key);
                }
            }
            save_text_file(&self.config_dir.join("config.json"), &pyjson::dumps_indent(&config, 4, true), true).map_err(Ok)?;
        }
        for (key, file) in [
            ("symbols", "symbols.dat"),
            ("swkb", "swkb.dat"),
            ("fsymbols", "fsymbols.dat"),
            ("phrase", "userphrase.dat"),
            ("excludePhrase", "excludephrase.dat"),
            ("flangs", "flangs.dat"),
            ("extendtable", "extendtable.dat"),
        ] {
            match data.get(key) {
                None | Some(Value::Null) => {}
                Some(Value::String(text)) => save_text_file(&self.config_dir.join(file), text, true).map_err(Ok)?,
                // f.write(<not a str>): TypeError (the temporary file is removed)
                Some(_) => return Err(Err(format!("TypeError: write() argument must be str ({})", key))),
            }
        }
        Ok(())
    }

    fn post_config(&mut self, request: &Request) -> HandlerResult {
        let data = pyjson::loads(&request.body).map_err(HttpError::Internal)?;
        let Value::Object(data) = data else {
            return Err(HttpError::Internal("AttributeError: the request is not a JSON object".into()));
        };
        match self.save_all(&data) {
            Ok(()) => {}
            Err(Ok(err)) => {
                // used to be swallowed: the page said 設定已套用 although config.json was unchanged
                log(&format!("cannot save settings: {}", err));
                return Err(HttpError::reason(500, "Cannot save the settings"));
            }
            Err(Err(err)) => return Err(HttpError::Internal(err)),
        }
        let mut response = Response::new();
        response.write(br#"{"return":true}"#);
        Ok(response)
    }
}

impl Tool for CinbaseTool {
    fn cookie_id(&self) -> &'static str {
        COOKIE_ID
    }

    fn main_page(&self) -> &'static str {
        "config"
    }

    fn localdata_dir(&self) -> PathBuf {
        self.config_dir.clone()
    }

    fn routes(&self) -> Vec<Route> {
        let a = &self.assets;
        vec![
            Route::custom(
                r"/(.*\.html|config.js)",
                |path| {
                    let rest = path.strip_prefix('/')?;
                    let html = rest.ends_with(".html") && !rest.contains('\n');
                    let js = rest.chars().count() == 9 && rest.starts_with("config") && rest.ends_with("js") && !rest.contains('\n');
                    (html || js).then(|| vec![rest.to_string()])
                },
                Target::Static(a.ime_config_dir(&self.ime)),
            ),
            Route::suffix(r"/(.*\.htm)", ".htm", Target::Static(a.cinbase_pages_dir())),
            Route::dirs(r"/((css|fonts|images|js)/.*)", &["css", "fonts", "images", "js"], Target::Static(a.cinbase_pages_dir())),
            Route::custom(
                r"/(data/.*\.json)",
                |path| {
                    let rest = path.strip_prefix('/')?;
                    (rest.starts_with("data/") && rest.len() >= "data/.json".len() && rest.ends_with(".json") && !rest.contains('\n'))
                        .then(|| vec![rest.to_string()])
                },
                Target::Static(a.cinbase_dir()),
            ),
            Route::exact_dot(r"/(icon.ico)", "icon.ico", Target::Static(a.ime_dir(&self.ime))),
            Route::exact_dot(r"/(version.txt)", "version.txt", Target::Static(a.version_dir())),
            Route::exact("/config", Target::Api("config")),
        ]
    }

    fn handle(&mut self, api: &'static str, method: &str, request: &Request) -> HandlerResult {
        match (api, method) {
            ("config", "GET") => self.get_config(),
            ("config", "POST") => self.post_config(request),
            _ => Err(HttpError::status(405)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cincount_is_read_from_the_top_level_only() {
        let dir = std::env::temp_dir().join(format!("wime-cincount-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("t.json");
        std::fs::write(&path, br#"{"chardefs": {"a": ["x"], "cincount": 5}, "cincount": {"cjk": 1, "big5": 2.5}, "x": [1]}"#).unwrap();
        assert_eq!(read_cincount(&path).unwrap(), serde_json::json!({"cjk": 1, "big5": 2.5}));
        std::fs::write(&path, b"[1]").unwrap();
        assert!(read_cincount(&path).is_err());
        std::fs::write(&path, b"\xEF\xBB\xBF{}").unwrap();
        assert!(read_cincount(&path).is_err());
        std::fs::write(&path, b"{} x").unwrap();
        assert!(read_cincount(&path).is_err());
        std::fs::write(&path, b"{\"a\": 1}").unwrap();
        assert_eq!(read_cincount(&path).unwrap(), Value::Null);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
