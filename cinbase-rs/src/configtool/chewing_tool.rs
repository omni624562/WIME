//! Port of python/input_methods/chewing/config_tool.py: the 新酷音 settings
//! tool and user phrase editor.
//!
//! - /config: GET {"config", "symbols", "swkb"}, POST saves them
//! - /user_phrases: GET {"data": [{"phrase", "bopomofo"}]}, POST {"add": [...],
//!   "remove": [...]} -> {"result": 1 or 0}
//! - /user_phrase_file: GET exports chewing.dat, POST (multipart field
//!   import_user_phrase) imports a chewing.dat or an old chewing.sqlite3
//!
//! The libchewing context of the editor is opened per request: libchewing 0.13
//! keeps the user dictionary in memory and writes it when the context is freed.

use super::assets::Assets;
use super::server::{log, HandlerResult, HttpError, Request, Response, Route, Target, Tool};
use super::{multipart, pyjson, save_text_file};
use crate::chewing::config::{default_values, normalize_values, ChewingConfig};
use crate::chewing::engine::ChewingContext;
use crate::chewing::userdict;
use crate::cinbase::pyutil::py_truthy;
use crate::config::decode_mbcs;
use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};

pub const COOKIE_ID: &str = "chewing_config_token";

/// The old C libchewing cut symbols.dat lines at 512 bytes; 0.13 has no limit
/// (its own symbols.dat has 800-byte emoji lines): only absurd lines are refused.
const SYMBOLS_MAX_LINE_BYTES: usize = 16384;

const IMPORT_FAILED: &str = "詞庫格式錯誤，可能檔案損毀或選到錯誤的檔案，原本的詞庫沒有變更。請按上一頁返回";
const IMPORT_DONE: &str = "\n            <script type=\"text/javascript\">\n                alert(\"匯入詞庫成功！\");\n                window.location = \"./user_phrase_editor.html\";\n            </script>\n        ";

/// read_text_file: symbols.dat / swkb.dat with a BOM, or saved in the ANSI code page
fn read_text_file(path: &Path) -> std::io::Result<String> {
    let raw = std::fs::read(path)?;
    let utf8 = raw.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(&raw);
    let text = match std::str::from_utf8(utf8) {
        Ok(t) => t.to_string(),
        Err(_) => decode_mbcs(&raw).unwrap_or_else(|| String::from_utf8_lossy(&raw).into_owned()),
    };
    Ok(text.replace("\r\n", "\n"))
}

/// normalize_symbols: no blank lines (libchewing shows them as empty ` menu
/// items), exactly one line break at the end
fn normalize_symbols(text: &str) -> String {
    text.replace("\r\n", "\n").split('\n').filter(|line| !line.trim_end_matches('\r').is_empty()).map(|line| format!("{}\n", line)).collect()
}

/// `for item in value` over a JSON value: lists, dict keys and string
/// characters iterate; anything else is a TypeError
fn py_iter(value: &Value) -> Result<Vec<Value>, HttpError> {
    match value {
        Value::Array(items) => Ok(items.clone()),
        Value::Object(map) => Ok(map.keys().map(|k| Value::String(k.clone())).collect()),
        Value::String(s) => Ok(s.chars().map(|c| Value::String(c.to_string())).collect()),
        _ => Err(HttpError::Internal("TypeError: object is not iterable".into())),
    }
}

/// item["phrase"].encode("utf8")
fn item_bytes(item: &Value, key: &str) -> Result<Vec<u8>, HttpError> {
    match item {
        Value::Object(map) => match map.get(key) {
            Some(Value::String(s)) => Ok(s.as_bytes().to_vec()),
            Some(_) => Err(HttpError::Internal(format!("AttributeError: {} has no encode()", key))),
            None => Err(HttpError::Internal(format!("KeyError: '{}'", key))),
        },
        _ => Err(HttpError::Internal("TypeError: the item is not a dict".into())),
    }
}

pub struct ChewingTool {
    assets: Assets,
    /// %APPDATA%\PIME\chewing
    config_dir: PathBuf,
    /// %LOCALAPPDATA%\PIME\chewing
    localdata_dir: PathBuf,
    /// searchPath(config_dir, CHEWING_DATA_DIR)
    search_paths: String,
}

impl ChewingTool {
    pub fn new(assets: Assets) -> ChewingTool {
        // importing chewing_config creates the module's ChewingConfig: it migrates
        // old files, converts ANSI symbols.dat / swkb.dat, drops their blank lines
        // and writes the default config.json when there is none
        let cfg = ChewingConfig::new(true);
        let config_dir = cfg.get_config_dir();
        drop(cfg);
        let _ = config_dir;
        let appdata = std::env::var("APPDATA").unwrap_or_else(|_| "%APPDATA%".into());
        let localappdata = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| "%LOCALAPPDATA%".into());
        let config_dir_py = PathBuf::from(appdata).join("PIME").join("chewing");
        let search_paths = [config_dir_py.to_string_lossy().into_owned(), assets.chewing_data_dir().to_string_lossy().into_owned()]
            .into_iter()
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join(";");
        ChewingTool {
            assets,
            config_dir: config_dir_py,
            localdata_dir: PathBuf::from(localappdata).join("PIME").join("chewing"),
            search_paths,
        }
    }

    /// open_chewing_ctx: 503 when the dictionary is damaged, locked, or the old
    /// one cannot be converted
    fn open_chewing_ctx(&self) -> Result<ChewingContext, HttpError> {
        let opened = userdict::prepare_user_dictionary(&self.config_dir, &self.search_paths).and_then(|user_phrase| {
            ChewingContext::new(&self.search_paths, &user_phrase.to_string_lossy(), Some(&self.config_dir.to_string_lossy()), true)
        });
        opened.map_err(|err| {
            log(&format!("cannot open the user phrase dictionary: {}", err));
            HttpError::reason(503, "Cannot open the user phrase database")
        })
    }

    /// ConfigHandler.load_config: defaults, the user's config.json over them, normalized
    fn load_config(&self) -> Value {
        let defaults = default_values();
        let mut config = defaults.clone();
        let path = self.config_dir.join("config.json");
        match std::fs::read(&path) {
            Ok(raw) => {
                let text = match std::str::from_utf8(raw.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(&raw)) {
                    Ok(t) => Some(t.to_string()),
                    Err(_) => decode_mbcs(&raw),
                };
                match text.map(|t| serde_json::from_str::<Value>(&t)) {
                    Some(Ok(Value::Object(values))) => {
                        for (k, v) in values {
                            config.insert(k, v);
                        }
                    }
                    Some(Ok(_)) => log("config.json is not a JSON object"),
                    Some(Err(e)) => log(&e.to_string()),
                    None => log("config.json: cannot decode"),
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => log(&e.to_string()),
        }
        // emptied fields (null) and values out of range show as the defaults
        Value::Object(normalize_values(&config, &defaults))
    }

    /// ConfigHandler.load_data: the user's file, else libchewing's
    fn load_data(&self, name: &str) -> String {
        for path in [self.config_dir.join(name), self.assets.chewing_data_dir().join(name)] {
            match read_text_file(&path) {
                Ok(text) => return text,
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
                Err(_) => return String::new(),
            }
        }
        String::new()
    }

    fn get_config(&self) -> HandlerResult {
        let mut data = Map::new();
        data.insert("config".into(), self.load_config());
        data.insert("symbols".into(), Value::String(self.load_data("symbols.dat")));
        data.insert("swkb".into(), Value::String(self.load_data("swkb.dat")));
        let mut response = Response::new();
        response.write_json(&Value::Object(data));
        Ok(response)
    }

    fn post_config(&self, request: &Request) -> HandlerResult {
        let data = pyjson::loads(&request.body).map_err(HttpError::Internal)?;
        let Value::Object(data) = data else {
            return Err(HttpError::Internal("AttributeError: the request is not a JSON object".into()));
        };
        let get = |key: &str| data.get(key).filter(|v| !v.is_null());
        let (config, symbols, swkb) = (get("config"), get("symbols"), get("swkb"));
        if config.is_some_and(|c| !c.is_object()) {
            return Err(HttpError::reason(400, "config must be an object"));
        }
        if let Some(symbols) = symbols {
            let Some(text) = symbols.as_str() else {
                return Err(HttpError::reason(400, "symbols must be a string"));
            };
            if text.split('\n').any(|line| line.len() > SYMBOLS_MAX_LINE_BYTES) {
                return Err(HttpError::reason(400, "symbols.dat line too long"));
            }
        }
        if swkb.is_some_and(|s| !s.is_string()) {
            return Err(HttpError::reason(400, "swkb must be a string"));
        }
        let saved = (|| -> std::io::Result<()> {
            std::fs::create_dir_all(&self.config_dir)?;
            if let Some(config) = config {
                save_text_file(&self.config_dir.join("config.json"), &pyjson::dumps_indent(config, 2, false), true)?;
            }
            if let Some(symbols) = symbols.and_then(Value::as_str) {
                save_text_file(&self.config_dir.join("symbols.dat"), &normalize_symbols(symbols), true)?;
            }
            if let Some(swkb) = swkb.and_then(Value::as_str) {
                save_text_file(&self.config_dir.join("swkb.dat"), swkb, true)?;
            }
            Ok(())
        })();
        if let Err(err) = saved {
            // used to be swallowed: the page said 已儲存 although nothing changed
            log(&format!("cannot save settings: {}", err));
            return Err(HttpError::reason(500, "Cannot save the settings"));
        }
        let mut response = Response::new();
        response.write(br#"{"return":true}"#);
        Ok(response)
    }

    fn get_user_phrases(&self) -> HandlerResult {
        let mut ctx = self.open_chewing_ctx()?;
        let phrases: Vec<Value> = ctx.user_phrases().into_iter().map(|(phrase, bopomofo)| json!({"phrase": phrase, "bopomofo": bopomofo})).collect();
        drop(ctx);
        let mut response = Response::new();
        response.write_json(&json!({ "data": phrases }));
        Ok(response)
    }

    fn post_user_phrases(&self, request: &Request) -> HandlerResult {
        let data = pyjson::loads(&request.body).map_err(HttpError::Internal)?;
        let Value::Object(data) = data else {
            return Err(HttpError::Internal("AttributeError: the request is not a JSON object".into()));
        };
        let added = data.get("add").cloned().unwrap_or(json!([]));
        let removed = data.get("remove").cloned().unwrap_or(json!([]));
        // 0: error (any item failed), 1: success
        let mut result = 1;
        let mut ctx = self.open_chewing_ctx()?;
        let edited = (|| -> Result<(), HttpError> {
            for item in py_iter(&added)? {
                let (phrase, bopomofo) = (item_bytes(&item, "phrase")?, item_bytes(&item, "bopomofo")?);
                if ctx.userphrase_add_bytes(&phrase, &bopomofo) <= 0 {
                    result = 0;
                }
            }
            for item in py_iter(&removed)? {
                let (phrase, bopomofo) = (item_bytes(&item, "phrase")?, item_bytes(&item, "bopomofo")?);
                if ctx.userphrase_remove_bytes(&phrase, &bopomofo) <= 0 {
                    result = 0;
                }
            }
            Ok(())
        })();
        drop(ctx); // writes chewing.dat
        edited?;
        if py_truthy(&added) || py_truthy(&removed) {
            userdict::touch_change_stamp(&self.config_dir); // the IME reloads the dictionary
        }
        let mut response = Response::new();
        response.write_json(&json!({ "result": result }));
        Ok(response)
    }

    fn get_user_phrase_file(&self) -> HandlerResult {
        let user_phrase_file = userdict::prepare_user_dictionary(&self.config_dir, &self.search_paths)
            .map_err(|_| HttpError::reason(503, "Cannot convert the old user phrase database"))?;
        // libchewing replaces the whole file: what is read is always complete
        let content = std::fs::read(&user_phrase_file).map_err(|_| HttpError::status(404))?;
        let mut response = Response::new();
        response.set_header("Content-Type", "application/force-download");
        response.set_header("Content-Disposition", "attachment; filename=chewing.dat");
        response.write(&content);
        Ok(response)
    }

    /// import_user_phrase_db
    fn import_user_phrase_db(&self, data: &[u8]) -> Result<usize, String> {
        std::fs::create_dir_all(&self.config_dir).map_err(|e| e.to_string())?;
        // convert (and back up) an old dictionary first, or it would replace the import on the next start
        userdict::prepare_user_dictionary(&self.config_dir, &self.search_paths)?;
        userdict::import_user_dictionary(data, &self.config_dir, &self.search_paths)
    }

    fn post_user_phrase_file(&self, request: &Request) -> HandlerResult {
        let files = multipart::parse_files(request.header("Content-Type").unwrap_or(""), &request.body);
        let imported = match files.iter().find(|f| f.name == "import_user_phrase") {
            Some(file) => self.import_user_phrase_db(&file.body),
            None => Err("KeyError: 'import_user_phrase'".into()),
        };
        let mut response = Response::new();
        match imported {
            Ok(_) => response.write(IMPORT_DONE.as_bytes()),
            Err(err) => {
                log(&format!("cannot import the user phrase database: {}", err));
                response.write(IMPORT_FAILED.as_bytes());
            }
        }
        Ok(response)
    }
}

impl Tool for ChewingTool {
    fn cookie_id(&self) -> &'static str {
        COOKIE_ID
    }

    fn main_page(&self) -> &'static str {
        "config_tool"
    }

    fn localdata_dir(&self) -> PathBuf {
        self.localdata_dir.clone()
    }

    fn routes(&self) -> Vec<Route> {
        let pages = self.assets.chewing_pages_dir();
        vec![
            Route::suffix(r"/(.*\.html)", ".html", Target::Static(pages.clone())),
            Route::dirs(r"/((css|images|js|fonts)/.*)", &["css", "images", "js", "fonts"], Target::Static(pages)),
            Route::exact_dot(r"/(version.txt)", "version.txt", Target::Static(self.assets.version_dir())),
            Route::exact("/config", Target::Api("config")),
            Route::exact("/user_phrases", Target::Api("user_phrases")),
            Route::exact("/user_phrase_file", Target::Api("user_phrase_file")),
        ]
    }

    fn handle(&mut self, api: &'static str, method: &str, request: &Request) -> HandlerResult {
        match (api, method) {
            ("config", "GET") => self.get_config(),
            ("config", "POST") => self.post_config(request),
            ("user_phrases", "GET") => self.get_user_phrases(),
            ("user_phrases", "POST") => self.post_user_phrases(request),
            ("user_phrase_file", "GET") => self.get_user_phrase_file(),
            ("user_phrase_file", "POST") => self.post_user_phrase_file(request),
            _ => Err(HttpError::status(405)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn symbols_lose_blank_lines() {
        assert_eq!(normalize_symbols("\n測試=★☆\n\n\n \n★\n\n\n"), "測試=★☆\n \n★\n");
        assert_eq!(normalize_symbols("a\r\n\r\nb\r"), "a\nb\r\n");
        assert_eq!(normalize_symbols(""), "");
    }
}
