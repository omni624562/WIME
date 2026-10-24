//! Port of python/input_methods/chewing/chewing_config.py (CC:<line> marks the
//! ported code): the 新酷音 settings, one object shared by every text service
//! of the process (the module-level `chewingConfig`).
//!
//! The settings are kept as the raw JSON values of Python's `__dict__`, in the
//! class's attribute order: normalizeValues() keeps a bool setting written as an
//! int (0/1) an int, an int setting written as true a bool, and so on, and the
//! frontend uses them with Python's semantics (truthiness, ctypes int
//! conversion, JSON in the replies).

use crate::config::{copy2, decode_mbcs, mtime, py_float_repr, py_int_from_str, py_strip, read_user_config};
use crate::env;
use crate::paths;
use serde_json::{Map, Value};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

pub const DEF_FONT_SIZE: i64 = 16;

pub const SWITCH_LANG_WITH_BOTH_SHIFT: i64 = 0;
pub const SWITCH_LANG_WITH_LEFT_SHIFT: i64 = 1;
pub const SWITCH_LANG_WITH_RIGHT_SHIFT: i64 = 2;

pub const DB_NAME: &str = "chewing.dat";
pub const LEGACY_DB_NAME: &str = "chewing.sqlite3";
pub const USER_PHRASE_STAMP_NAME: &str = "chewing-userphrase.stamp";

/// CC:38 selKeys
pub const SEL_KEYS: [&str; 6] = ["1234567890", "asdfghjkl;", "asdfzxcv89", "asdfjkl789", "aoeuhtn789", "1234qweras"];

/// CC:50 _INT_RANGES
const INT_RANGES: &[(&str, i64, i64)] = &[
    ("candPerPage", 1, 10),
    ("keyboardLayout", 0, 12),
    ("leftRightAction", 0, 1),
    ("upDownAction", 0, 1),
    ("selKeyType", 0, SEL_KEYS.len() as i64 - 1),
    ("shiftMoveCursor", 0, 1),
    ("spaceKeyAction", 0, 1),
    ("spaceKeyCandidatesAction", 0, 1),
    ("switchLangWithWhichShift", 0, 2),
    ("fontSize", 6, 200),
    ("candidatePerRow", 1, 10),
    ("candidatePositionMode", 0, 1),
    ("candidateOpacity", 30, 100),
    ("candidateMinWidth", 0, 4000),
    ("candidateMaxWidth", 0, 4000),
];
const C_INT_RANGE: (i64, i64) = (-(1 << 31), (1 << 31) - 1);

/// CC:72 _FIXED_VALUES
const FIXED_VALUES: &[(&str, &str)] = &[("candidateKeyStyle", "word-first")];
/// CC:82 LEGACY_CANDIDATE_MAX_WIDTH
pub const LEGACY_CANDIDATE_MAX_WIDTH: i64 = 300;
/// CC:91 _RETIRED_KEYS
const RETIRED_KEYS: &[&str] = &["candPerRow", "candidateMessageBehavior"];

/// CC:197 ChewingConfig.__init__: the settings in attribute order
pub fn default_values() -> Map<String, Value> {
    let mut m = Map::new();
    let mut b = |k: &str, v: Value| {
        m.insert(k.to_string(), v);
    };
    b("addPhraseForward", Value::Bool(true));
    b("advanceAfterSelection", Value::Bool(true));
    b("autoLearn", Value::Bool(true));
    b("candPerPage", Value::from(9));
    b("defaultEnglish", Value::Bool(false));
    b("defaultFullSpace", Value::Bool(false));
    b("disableOnStartup", Value::Bool(false));
    b("easySymbolsWithCtrl", Value::Bool(false));
    b("easySymbolsWithShift", Value::Bool(true));
    b("enableCapsLock", Value::Bool(true));
    b("enableShiftSpace", Value::Bool(true));
    b("escCleanAllBuf", Value::Bool(true));
    b("fontSize", Value::from(DEF_FONT_SIZE));
    b("fullShapeSymbols", Value::Bool(true));
    b("fullShapeSymbolsWithShift", Value::Bool(true));
    b("keyboardLayout", Value::from(0));
    b("leftRightAction", Value::from(0));
    b("phraseChoiceRearward", Value::Bool(false));
    b("selKeyType", Value::from(0));
    b("shiftMoveCursor", Value::from(0));
    b("spaceKeyAction", Value::from(1));
    b("spaceKeyCandidatesAction", Value::from(0));
    b("switchLangWithShift", Value::Bool(true));
    b("switchLangWithWhichShift", Value::from(SWITCH_LANG_WITH_BOTH_SHIFT));
    b("upDownAction", Value::from(0));
    b("upperCaseWithShift", Value::Bool(true));
    b("candidateLayout", Value::from("horizontal"));
    b("candidatePerRow", Value::from(6));
    b("candidateEdgeAvoidance", Value::Bool(true));
    b("candidatePositionMode", Value::from(0));
    b("candidateOpacity", Value::from(100));
    b("candidateTheme", Value::from("System"));
    b("candidateKeyStyle", Value::from("word-first"));
    b("candidateMessageStyle", Value::from("badge"));
    b("candidateStableWidth", Value::Bool(true));
    b("candidateMinWidth", Value::from(286));
    b("candidateWrapToMaxWidth", Value::Bool(true));
    b("candidateMaxWidth", Value::from(340));
    b("candidateMaxWidthMigrated", Value::Bool(false));
    b("candidateColors", Value::Object(Map::new()));
    let mut style = Map::new();
    style.insert("contentMargin".into(), Value::from(6));
    style.insert("textMargin".into(), Value::from(4));
    style.insert("borderRadius".into(), Value::from(6));
    b("candidateStyle", Value::Object(style));
    m
}

// ---------------------------------------------------------------------------
// Python value semantics of the settings

/// int(value) of a setting as Python uses it (True -> 1); None for a non-number
pub fn py_int_value(v: &Value) -> Option<i64> {
    match v {
        Value::Bool(b) => Some(*b as i64),
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
        _ => None,
    }
}

/// bool(value)
pub fn py_truthy(v: &Value) -> bool {
    crate::cinbase::pyutil::py_truthy(v)
}

/// An int JSON number (not a float), even beyond i64
fn is_json_int(v: &Value) -> bool {
    matches!(v, Value::Number(n) if !n.is_f64())
}

/// CC:94 _toInt (None -> invalid)
fn to_int(value: &Value) -> Option<Value> {
    match value {
        Value::Bool(_) => Some(value.clone()), // bool is an int
        Value::Number(n) if !n.is_f64() => Some(value.clone()),
        Value::Number(n) => {
            let f = n.as_f64()?;
            if f.is_finite() && f.fract() == 0.0 {
                if f.abs() < 9.2e18 {
                    Some(Value::from(f as i64))
                } else {
                    Some(Value::from(f64::MAX as u64)) // out of every range below
                }
            } else {
                None
            }
        }
        Value::String(s) => py_int_from_str(s).map(Value::from),
        _ => None,
    }
}

/// CC:108 _toBool (None -> invalid)
fn to_bool(value: &Value) -> Option<Value> {
    match value {
        Value::Bool(_) => Some(value.clone()),
        Value::Number(n) if !n.is_f64() => Some(value.clone()), // ints stay ints
        Value::Number(n) => Some(Value::Bool(n.as_f64().map(|f| f != 0.0).unwrap_or(true))),
        Value::String(s) => match py_strip(s).to_lowercase().as_str() {
            "true" | "1" | "yes" | "on" => Some(Value::Bool(true)),
            "false" | "0" | "no" | "off" | "" => Some(Value::Bool(false)),
            _ => None,
        },
        _ => None,
    }
}

/// low <= value <= high for a Python int (bool included)
fn in_range(value: &Value, low: i64, high: i64) -> bool {
    match value {
        Value::Bool(b) => low <= *b as i64 && *b as i64 <= high,
        Value::Number(n) => match n.as_i64() {
            Some(i) => low <= i && i <= high,
            None => false, // beyond i64
        },
        _ => false,
    }
}

/// CC:122 normalizeValues(values, defaults)
pub fn normalize_values(values: &Map<String, Value>, defaults: &Map<String, Value>) -> Map<String, Value> {
    let mut result: Map<String, Value> =
        values.iter().filter(|(k, _)| !RETIRED_KEYS.contains(&k.as_str())).map(|(k, v)| (k.clone(), v.clone())).collect();
    for (key, default) in defaults {
        let Some(value) = result.get(key) else { continue };
        let new = match default {
            Value::Bool(_) => to_bool(value),
            Value::Number(_) => to_int(value).filter(|v| {
                let (low, high) = INT_RANGES
                    .iter()
                    .find(|(k, _, _)| k == key)
                    .map(|(_, l, h)| (*l, *h))
                    .unwrap_or(C_INT_RANGE);
                in_range(v, low, high)
            }),
            Value::String(_) => value.is_string().then(|| value.clone()),
            Value::Object(_) => match value {
                Value::Object(m) if key == "candidateStyle" => {
                    Some(Value::Object(m.iter().filter(|(_, v)| is_json_int(v)).map(|(k, v)| (k.clone(), v.clone())).collect()))
                }
                Value::Object(_) => Some(value.clone()),
                _ => None,
            },
            _ => Some(value.clone()),
        };
        result.insert(key.clone(), new.unwrap_or_else(|| default.clone()));
    }
    for (key, value) in FIXED_VALUES {
        if result.contains_key(*key) {
            result.insert(key.to_string(), Value::from(*value));
        }
    }
    let legacy = matches!(result.get("candidateMaxWidth"), Some(v) if is_python_eq_int(v, LEGACY_CANDIDATE_MAX_WIDTH));
    if legacy
        && defaults.contains_key("candidateMaxWidth")
        && !result.get("candidateMaxWidthMigrated").map(py_truthy).unwrap_or(false)
    {
        result.insert("candidateMaxWidth".into(), defaults["candidateMaxWidth"].clone());
    }
    result
}

fn is_python_eq_int(v: &Value, n: i64) -> bool {
    crate::cinbase::pyutil::py_eq_int(v, n)
}

fn has_content(path: &Path) -> bool {
    fs::metadata(path).map(|m| m.len() > 0).unwrap_or(false)
}

// ---------------------------------------------------------------------------
// json.dump(obj, f, ensure_ascii=False, indent=4)

fn dump_string(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

fn dump_value(value: &Value, level: usize, out: &mut String) {
    let indent = |n: usize, out: &mut String| out.push_str(&" ".repeat(n * 4));
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => {
            if n.is_f64() {
                out.push_str(&py_float_repr(n.as_f64().unwrap_or(0.0)))
            } else {
                out.push_str(&n.to_string())
            }
        }
        Value::String(s) => dump_string(s, out),
        Value::Array(items) => {
            if items.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push('\n');
                indent(level + 1, out);
                dump_value(item, level + 1, out);
            }
            out.push('\n');
            indent(level, out);
            out.push(']');
        }
        Value::Object(map) => {
            if map.is_empty() {
                out.push_str("{}");
                return;
            }
            out.push('{');
            for (i, (key, v)) in map.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push('\n');
                indent(level + 1, out);
                dump_string(key, out);
                out.push_str(": ");
                dump_value(v, level + 1, out);
            }
            out.push('\n');
            indent(level, out);
            out.push('}');
        }
    }
}

pub fn json_dump_unsorted(value: &Value) -> String {
    let mut out = String::new();
    dump_value(value, 0, &mut out);
    out
}

/// version: mtimes of (config.json, symbols.dat, swkb.dat, the user phrase stamp)
pub type Version = [f64; 4];

/// CC:195 ChewingConfig
#[derive(Debug, Clone)]
pub struct ChewingConfig {
    /// the public attributes (toJson()), class order
    values: Map<String, Value>,
    version: Version,
    last_update_time: Option<f64>,
    appdata: PathBuf,
    home: PathBuf,
}

fn appdata_dir() -> PathBuf {
    // os.path.expandvars("%APPDATA%") keeps the literal when unset
    std::env::var("APPDATA").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("%APPDATA%"))
}

fn home_dir() -> PathBuf {
    let var = |name: &str| std::env::var(name).ok();
    match var("USERPROFILE") {
        Some(p) => PathBuf::from(p),
        None => match var("HOMEPATH") {
            Some(hp) => PathBuf::from(format!("{}{}", var("HOMEDRIVE").unwrap_or_default(), hp)),
            None => PathBuf::from("~"),
        },
    }
}

impl ChewingConfig {
    /// ChewingConfig(load=...)
    pub fn new(load: bool) -> ChewingConfig {
        Self::with_dirs(appdata_dir(), home_dir(), load)
    }

    /// ChewingConfig with %APPDATA% and the home directory given (tests)
    pub fn with_dirs(appdata: PathBuf, home: PathBuf, load: bool) -> ChewingConfig {
        let mut cfg = ChewingConfig { values: default_values(), version: [0.0; 4], last_update_time: None, appdata, home };
        if load {
            cfg.load();
        }
        cfg
    }

    // -- attributes ---------------------------------------------------------------
    pub fn get(&self, key: &str) -> &Value {
        static NULL: Value = Value::Null;
        self.values.get(key).unwrap_or(&NULL)
    }
    pub fn truthy(&self, key: &str) -> bool {
        py_truthy(self.get(key))
    }
    /// int(getattr(cfg, key)); 0 for a non-number (cannot happen after normalize)
    pub fn int(&self, key: &str) -> i64 {
        py_int_value(self.get(key)).unwrap_or(0)
    }
    #[cfg(test)]
    pub fn set(&mut self, key: &str, value: Value) {
        self.values.insert(key.to_string(), value);
    }
    pub fn to_json(&self) -> Map<String, Value> {
        self.values.clone()
    }

    // -- directories (CC:252) ---------------------------------------------------------
    pub fn get_config_dir(&self) -> PathBuf {
        let dir = self.appdata.join("PIME").join("chewing");
        let _ = fs::create_dir_all(&dir);
        dir
    }
    pub fn get_config_file(&self, name: &str) -> PathBuf {
        self.get_config_dir().join(name)
    }
    pub fn get_user_phrase(&self) -> PathBuf {
        self.get_config_dir().join(DB_NAME)
    }
    pub fn get_legacy_user_phrase(&self) -> PathBuf {
        self.get_config_dir().join(LEGACY_DB_NAME)
    }
    /// CC:267 getSelKeys(): selKeys[selKeyType]
    pub fn get_sel_keys(&self) -> Result<&'static str, String> {
        let i = self.int("selKeyType");
        let n = SEL_KEYS.len() as i64;
        let index = if i < 0 { i + n } else { i };
        if !(0..n).contains(&index) {
            return Err("IndexError: tuple index out of range".into());
        }
        Ok(SEL_KEYS[index as usize])
    }
    /// CC:428 getDataDir(): the chewing module directory's data (not shipped)
    pub fn get_data_dir(&self) -> PathBuf {
        paths::chewing_dir().join("data")
    }

    // -- load / save ------------------------------------------------------------------
    /// CC:273 load()
    pub fn load(&mut self) {
        let filename = self.get_config_file("config.json");
        if !has_content(&filename) {
            self.migrate_legacy_config();
        }
        self.convert_legacy_encoding();
        self.remove_blank_symbol_lines();
        let mut version = self.current_version();
        if has_content(&filename) {
            match read_user_config(&filename) {
                Err(err) => {
                    eprintln!("chewing: cannot read {}: {}", filename.display(), err);
                    backup_broken_config(&filename);
                }
                Ok(values) => self.apply_values(&values),
            }
        } else {
            self.save();
            version = self.current_version();
        }
        self.version = version;
        self.last_update_time = Some(env::monotonic());
    }

    /// CC:296 _applyValues
    fn apply_values(&mut self, values: &Map<String, Value>) {
        let defaults = default_values();
        let known: Map<String, Value> =
            values.iter().filter(|(k, _)| defaults.contains_key(*k)).map(|(k, v)| (k.clone(), v.clone())).collect();
        for (k, v) in normalize_values(&known, &defaults) {
            self.values.insert(k, v);
        }
    }

    /// CC:312 migrateLegacyConfig
    fn migrate_legacy_config(&mut self) {
        let src_dir = self.home.join("PIME").join("chewing");
        let dst_dir = self.get_config_dir();
        if same_path(&src_dir, &dst_dir) {
            return;
        }
        if !has_content(&src_dir.join("config.json"))
            || self.get_user_phrase().exists()
            || self.get_legacy_user_phrase().exists()
        {
            return;
        }
        if let Err(err) = copytree_keep(&src_dir, &dst_dir) {
            eprintln!("chewing: cannot migrate {}: {}", src_dir.display(), err);
        }
    }

    /// CC:332 convertLegacyEncoding
    pub fn convert_legacy_encoding(&self) -> bool {
        let mut changed = false;
        for name in ["symbols.dat", "swkb.dat"] {
            let path = self.get_config_file(name);
            let Ok(raw) = fs::read(&path) else { continue };
            if std::str::from_utf8(&raw).is_ok() {
                continue;
            }
            let text = decode_mbcs(&raw).unwrap_or_else(|| String::from_utf8_lossy(&raw).into_owned());
            let backup = with_suffix(&path, ".ansi-backup");
            let tmp_path = with_suffix(&path, &format!(".{}.tmp", std::process::id()));
            let result = (|| -> std::io::Result<()> {
                if !backup.exists() {
                    copy2(&path, &backup)?;
                }
                write_synced(&tmp_path, text.as_bytes())?;
                fs::rename(&tmp_path, &path)
            })();
            match result {
                Ok(()) => changed = true,
                Err(err) => {
                    eprintln!("chewing: cannot convert {} to UTF-8: {}", path.display(), err);
                    if tmp_path.exists() {
                        let _ = fs::remove_file(&tmp_path);
                    }
                }
            }
        }
        changed
    }

    /// CC:376 removeBlankSymbolLines
    pub fn remove_blank_symbol_lines(&self) -> bool {
        let path = self.get_config_file("symbols.dat");
        let Ok(raw) = fs::read(&path) else { return false };
        let mut lines: Vec<&[u8]> = raw.split(|&b| b == b'\n').collect();
        let rest = lines.pop().unwrap_or(&[]);
        let kept: Vec<&[u8]> = lines
            .iter()
            .copied()
            .filter(|line| {
                let mut l = *line;
                while let Some(stripped) = l.strip_suffix(b"\r") {
                    l = stripped;
                }
                !l.is_empty()
            })
            .collect();
        if kept.len() == lines.len() {
            return false;
        }
        let tmp_path = with_suffix(&path, &format!(".{}.tmp", std::process::id()));
        let mut data = Vec::new();
        for line in &kept {
            data.extend_from_slice(line);
            data.push(b'\n');
        }
        data.extend_from_slice(rest);
        match write_synced(&tmp_path, &data).and_then(|_| fs::rename(&tmp_path, &path)) {
            Ok(()) => true,
            Err(err) => {
                eprintln!("chewing: cannot remove the blank lines of {}: {}", path.display(), err);
                if tmp_path.exists() {
                    let _ = fs::remove_file(&tmp_path);
                }
                false
            }
        }
    }

    /// CC:408 save(): json.dump(indent=4, ensure_ascii=False) + "\n", text mode
    pub fn save(&mut self) -> bool {
        let filename = self.get_config_file("config.json");
        let tmp_filename = super::userdict::temp_path_for(&filename);
        let text = (json_dump_unsorted(&Value::Object(self.to_json())) + "\n").replace('\n', "\r\n");
        match write_synced(&tmp_filename, text.as_bytes()).and_then(|_| super::userdict::replace_file(&tmp_filename, &filename)) {
            Ok(()) => true,
            Err(err) => {
                eprintln!("chewing: cannot save {}: {}", filename.display(), err);
                if tmp_filename.exists() {
                    let _ = fs::remove_file(&tmp_filename);
                }
                false
            }
        }
    }

    /// CC:450 _currentVersion
    fn current_version(&self) -> Version {
        let config_time = mtime(&self.get_config_file("config.json")).unwrap_or(0.0);
        let datadirs = [self.get_config_dir(), self.get_data_dir()];
        let find = |name: &str| datadirs.iter().map(|d| d.join(name)).find(|p| p.exists());
        let symbols_time = find("symbols.dat").and_then(|p| mtime(&p)).unwrap_or(0.0);
        let ez_symbols_time = find("swkb.dat").and_then(|p| mtime(&p)).unwrap_or(0.0);
        let user_phrase_time = mtime(&self.get_config_dir().join(USER_PHRASE_STAMP_NAME)).unwrap_or(0.0);
        [config_time, symbols_time, ez_symbols_time, user_phrase_time]
    }

    /// CC:479 update(): check the files at most every 3 seconds
    pub fn update(&mut self) {
        let now = env::monotonic();
        if let Some(last) = self.last_update_time {
            if now - last < 3.0 {
                return;
            }
        }
        self.last_update_time = Some(now);
        let mut version = self.current_version();
        if version[1..3] != self.version[1..3] {
            let converted = self.convert_legacy_encoding();
            if (version[1] != self.version[1] && self.remove_blank_symbol_lines()) || converted {
                version = self.current_version();
            }
        }
        let config_changed = version[0] != self.version[0];
        self.version = version;
        if config_changed {
            self.load();
        }
    }

    pub fn get_version(&self) -> Version {
        self.version
    }
    pub fn is_config_changed(&self, current: &Version) -> bool {
        current[0] != self.version[0]
    }
    pub fn is_full_reload_needed(&self, current: &Version) -> bool {
        current[1..] != self.version[1..]
    }
}

fn with_suffix(path: &Path, suffix: &str) -> PathBuf {
    let mut s = path.as_os_str().to_owned();
    s.push(suffix);
    PathBuf::from(s)
}

/// write + flush + fsync
fn write_synced(path: &Path, data: &[u8]) -> std::io::Result<()> {
    let mut f = fs::File::create(path)?;
    f.write_all(data)?;
    f.flush()?;
    f.sync_all()
}

/// os.path.normcase(os.path.abspath(a)) == ... (b)
fn same_path(a: &Path, b: &Path) -> bool {
    let norm = |p: &Path| {
        let abs = std::path::absolute(p).unwrap_or_else(|_| p.to_path_buf());
        abs.to_string_lossy().replace('/', "\\").to_lowercase().trim_end_matches('\\').to_string()
    };
    norm(a) == norm(b)
}

/// CC:438 copytree(): files already at the destination are kept
fn copytree_keep(src: &Path, dst: &Path) -> std::io::Result<()> {
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let s = entry.path();
        let d = dst.join(entry.file_name());
        if d.exists() {
            continue;
        }
        if s.is_dir() {
            copy_dir(&s, &d)?;
        } else {
            copy2(&s, &d)?;
        }
    }
    Ok(())
}

/// shutil.copytree
fn copy_dir(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let (s, d) = (entry.path(), dst.join(entry.file_name()));
        if s.is_dir() {
            copy_dir(&s, &d)?;
        } else {
            copy2(&s, &d)?;
        }
    }
    Ok(())
}

/// CC:304 _backupBrokenConfig
fn backup_broken_config(filename: &Path) {
    let Some(t) = mtime(filename) else { return };
    let backup = with_suffix(filename, &format!(".broken-{}", t as i64));
    if !backup.exists() {
        let _ = copy2(filename, &backup);
    }
}
