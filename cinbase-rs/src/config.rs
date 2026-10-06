//! Port of python/cinbase/config.py: the per-IME settings (CinBaseConfig).
//!
//! The settings live in two forms:
//! - `values`: the raw attribute map in Python's `__dict__` order (class
//!   defaults first, then unknown keys in the order the files brought them).
//!   load()/normalize() work on this map with exactly Python's semantics, and
//!   unknown keys (e.g. "keyboardLayout" in the shipped 大易 config) are kept and
//!   written back by to_json()/save().
//! - `Settings`: one typed field per known setting (snake_case of the Python
//!   name), reachable as `cfg.cand_per_row` through Deref. After every load the
//!   fields are read from the normalized map; to_json()/save()/load() write the
//!   fields back first, so assignments like `cfg.re_load_table = false` behave
//!   like Python's `cfg.reLoadTable = False`.
//!
//! Like ime_base.py (`CinBaseConfig.__init__()` + deepcopy per text service),
//! every text service creates its own `CinBaseConfig::new()` and calls load().

use crate::env;
use serde_json::{Map, Value};
use std::fs;
use std::io::Write;
use std::ops::{Deref, DerefMut};
use std::path::{Path, PathBuf};

pub const DEF_FONT_SIZE: i64 = 12;

pub const SWITCH_LANG_WITH_BOTH_SHIFT: i64 = 0;
pub const SWITCH_LANG_WITH_LEFT_SHIFT: i64 = 1;
pub const SWITCH_LANG_WITH_RIGHT_SHIFT: i64 = 2;

/// config.selKeys (a str: getSelKeys() returns ONE character of it)
pub const SEL_KEYS: &str = "1234567890";

/// Valid ranges for integer settings (config._INT_RANGES).
pub const INT_RANGES: &[(&str, i64, i64)] = &[
    ("candPerRow", 1, 10),
    ("candPerPage", 1, 10),
    ("candidatePerRow", 1, 10),
    ("candMaxItems", 1, 10000),
    ("fontSize", 6, 200),
    ("candidateOpacity", 30, 100),
    ("candidatePositionMode", 0, 1),
    ("candidateMinWidth", 0, 4000),
    ("candidateMaxWidth", 0, 4000),
    ("selWildcardType", 0, 1),
    ("switchLangWithWhichShift", 0, 2),
    ("selCinType", 0, 999),
    ("selRCinType", 0, 999),
    ("selHCinType", 0, 999),
];

/// Settings dropped on load (config._RETIRED_KEYS).
pub const RETIRED_KEYS: &[&str] = &["candidateModernStyle", "messageDurationTime", "hidePromptMessages"];

/// Settings with only one allowed value (config._FIXED_VALUES).
pub const FIXED_VALUES: &[(&str, &str)] = &[("candidateKeyStyle", "word-first"), ("candidateHeaderStyle", "accent")];

pub const LEGACY_CANDIDATE_MAX_WIDTH: i64 = 300;

/// Reverse-lookup tables, in the settings page's selRCins order.
pub const RCIN_FILE_LIST: &[&str] = &[
    "checj.json", "mscj3.json", "mscj3-ext.json", "cj-ext.json", "cnscj.json", "thcj.json", "newcj3.json", "cj5.json", "newcj.json", "scj6.json", "cj-fast.json",
    "thphonetic.json", "CnsPhonetic.json", "bpmf.json",
    "tharray.json", "array30.json", "ar30-big.json", "array40.json",
    "thdayi.json", "dayi4.json", "dayi3.json",
    "ez.json", "ezsmall.json", "ezmid.json", "ezbig.json",
    "thpinyin.json", "pinyin.json", "roman.json",
    "simplecj.json", "simplex.json", "simplex5.json",
    "liu.json",
];

/// Attributes that are not settings (ignoreSaveList + private ones). Keys with
/// these names in a config file are ignored (Python would overwrite its
/// internal attribute with them).
const INTERNAL_KEYS: &[&str] = &["ignoreSaveList", "curdir", "cinFileList", "selCinFile", "imeDirName"];

fn is_internal_key(key: &str) -> bool {
    key.starts_with('_') || INTERNAL_KEYS.contains(&key)
}

// ---------------------------------------------------------------------------
// typed settings

trait SettingValue: Sized {
    fn to_value(&self) -> Value;
    fn from_value(v: &Value) -> Option<Self>;
}

impl SettingValue for bool {
    fn to_value(&self) -> Value {
        Value::Bool(*self)
    }
    fn from_value(v: &Value) -> Option<Self> {
        v.as_bool()
    }
}

impl SettingValue for i64 {
    fn to_value(&self) -> Value {
        Value::from(*self)
    }
    fn from_value(v: &Value) -> Option<Self> {
        v.as_i64()
    }
}

impl SettingValue for String {
    fn to_value(&self) -> Value {
        Value::String(self.clone())
    }
    fn from_value(v: &Value) -> Option<Self> {
        v.as_str().map(str::to_string)
    }
}

impl SettingValue for Map<String, Value> {
    fn to_value(&self) -> Value {
        Value::Object(self.clone())
    }
    fn from_value(v: &Value) -> Option<Self> {
        v.as_object().cloned()
    }
}

macro_rules! settings {
    ($( $field:ident : $ty:ty = $key:literal => $default:expr; )*) => {
        /// One field per setting of CinBaseConfig, in the class's attribute order.
        #[derive(Debug, Clone, PartialEq)]
        pub struct Settings {
            $( pub $field: $ty, )*
        }

        impl Default for Settings {
            fn default() -> Self {
                Settings { $( $field: $default, )* }
            }
        }

        impl Settings {
            /// The Python attribute names, in class order.
            pub const KEYS: &'static [&'static str] = &[ $( $key ),* ];

            fn write_to(&self, map: &mut Map<String, Value>) {
                $( map.insert($key.to_string(), SettingValue::to_value(&self.$field)); )*
            }

            fn read_from(&mut self, map: &Map<String, Value>) {
                $(
                    if let Some(v) = map.get($key).and_then(|v| <$ty as SettingValue>::from_value(v)) {
                        self.$field = v;
                    }
                )*
            }
        }
    };
}

fn default_candidate_style() -> Map<String, Value> {
    let mut m = Map::new();
    m.insert("contentMargin".into(), Value::from(6));
    m.insert("textMargin".into(), Value::from(4));
    m.insert("borderRadius".into(), Value::from(6));
    m
}

settings! {
    cand_per_row: i64 = "candPerRow" => 3;
    default_english: bool = "defaultEnglish" => false;
    default_full_space: bool = "defaultFullSpace" => false;
    enable_shift_space: bool = "enableShiftSpace" => true;
    disable_on_startup: bool = "disableOnStartup" => false;
    switch_lang_with_shift: bool = "switchLangWithShift" => true;
    switch_lang_with_which_shift: i64 = "switchLangWithWhichShift" => SWITCH_LANG_WITH_BOTH_SHIFT;
    output_small_letter_with_shift: bool = "outputSmallLetterWithShift" => false;
    switch_page_with_space: bool = "switchPageWithSpace" => false;
    play_sound_when_non_cand: bool = "playSoundWhenNonCand" => false;
    direct_show_cand: bool = "directShowCand" => false;
    auto_commit_single_candidate: bool = "autoCommitSingleCandidate" => false;
    direct_commit_symbol: bool = "directCommitSymbol" => false;
    font_size: i64 = "fontSize" => DEF_FONT_SIZE;
    sel_cin_type: i64 = "selCinType" => 0;
    ignore_private_use_area: bool = "ignorePrivateUseArea" => true;
    sel_key_type: i64 = "selKeyType" => 0;
    cand_per_page: i64 = "candPerPage" => 9;
    cursor_cand_list: bool = "cursorCandList" => true;
    full_shape_symbols: bool = "fullShapeSymbols" => false;
    direct_out_f_symbols: bool = "directOutFSymbols" => false;
    direct_out_m_symbols: bool = "directOutMSymbols" => true;
    easy_symbols_with_shift: bool = "easySymbolsWithShift" => false;
    show_phrase: bool = "showPhrase" => false;
    sort_by_phrase: bool = "sortByPhrase" => true;
    support_wildcard: bool = "supportWildcard" => true;
    composition_buffer_mode: bool = "compositionBufferMode" => false;
    auto_move_cursor_in_brackets: bool = "autoMoveCursorInBrackets" => false;
    sel_wildcard_type: i64 = "selWildcardType" => 0;
    ime_reverse_lookup: bool = "imeReverseLookup" => false;
    homophone_query: bool = "homophoneQuery" => false;
    sel_h_cin_type: i64 = "selHCinType" => 0;
    user_extend_table: bool = "userExtendTable" => false;
    re_load_table: bool = "reLoadTable" => false;
    priority_extend_table: bool = "priorityExtendTable" => false;
    sel_r_cin_type: i64 = "selRCinType" => 0;
    cand_max_items: i64 = "candMaxItems" => 100;
    keyboard_type: i64 = "keyboardType" => 0;
    sel_dayi_symbol_char_type: i64 = "selDayiSymbolCharType" => 0;
    intelligent_select: bool = "intelligentSelect" => true;
    intelligent_select_recent: bool = "intelligentSelectRecent" => true;
    intelligent_select_context: bool = "intelligentSelectContext" => true;
    hide_composition: bool = "hideComposition" => false;
    hide_composition_label: String = "hideCompositionLabel" => String::new();
    ime_display_name: String = "imeDisplayName" => String::new();
    candidate_layout: String = "candidateLayout" => "horizontal".to_string();
    candidate_per_row: i64 = "candidatePerRow" => 6;
    candidate_edge_avoidance: bool = "candidateEdgeAvoidance" => true;
    candidate_position_mode: i64 = "candidatePositionMode" => 0;
    candidate_opacity: i64 = "candidateOpacity" => 100;
    candidate_theme: String = "candidateTheme" => "System".to_string();
    candidate_key_style: String = "candidateKeyStyle" => "word-first".to_string();
    candidate_header_style: String = "candidateHeaderStyle" => "accent".to_string();
    candidate_message_style: String = "candidateMessageStyle" => "badge".to_string();
    candidate_message_behavior: String = "candidateMessageBehavior" => "progressive".to_string();
    candidate_stable_width: bool = "candidateStableWidth" => false;
    candidate_min_width: i64 = "candidateMinWidth" => 0;
    candidate_wrap_to_max_width: bool = "candidateWrapToMaxWidth" => true;
    candidate_max_width: i64 = "candidateMaxWidth" => 320;
    candidate_max_width_migrated: bool = "candidateMaxWidthMigrated" => false;
    candidate_colors: Map<String, Value> = "candidateColors" => Map::new();
    candidate_style: Map<String, Value> = "candidateStyle" => default_candidate_style();
}

/// `type(self)().__dict__` restricted to the settings: the class defaults.
fn defaults_map() -> Map<String, Value> {
    let mut m = Map::new();
    Settings::default().write_to(&mut m);
    m
}

// ---------------------------------------------------------------------------
// directories

/// Where CinBaseConfig looks for files; injectable for tests.
#[derive(Debug, Clone)]
pub struct ConfigPaths {
    /// os.path.expandvars("%APPDATA%") (the literal "%APPDATA%" when unset)
    pub appdata: PathBuf,
    /// os.path.expanduser("~")
    pub home: PathBuf,
    /// the PIME `python` directory (shipped configs, cinbase data)
    pub python_dir: PathBuf,
}

impl ConfigPaths {
    pub fn from_env() -> ConfigPaths {
        let var = |name: &str| std::env::var(name).ok();
        let appdata = var("APPDATA").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("%APPDATA%"));
        // ntpath.expanduser: USERPROFILE, else HOMEDRIVE + HOMEPATH, else unchanged
        let home = match var("USERPROFILE") {
            Some(p) => PathBuf::from(p),
            None => match var("HOMEPATH") {
                Some(hp) => PathBuf::from(format!("{}{}", var("HOMEDRIVE").unwrap_or_default(), hp)),
                None => PathBuf::from("~"),
            },
        };
        ConfigPaths { appdata, home, python_dir: crate::paths::python_dir().clone() }
    }
}

fn mtime(path: &Path) -> Option<f64> {
    let modified = fs::metadata(path).ok()?.modified().ok()?;
    Some(match modified.duration_since(std::time::UNIX_EPOCH) {
        Ok(d) => d.as_secs_f64(),
        Err(e) => -e.duration().as_secs_f64(),
    })
}

fn file_size(path: &Path) -> Option<u64> {
    fs::metadata(path).ok().map(|m| m.len())
}

/// shutil.copy2: contents and modification time
fn copy2(src: &Path, dst: &Path) -> std::io::Result<()> {
    let dst = if dst.is_dir() { dst.join(src.file_name().unwrap_or_default()) } else { dst.to_path_buf() };
    fs::copy(src, &dst)?;
    if let Ok(modified) = fs::metadata(src).and_then(|m| m.modified()) {
        if let Ok(f) = fs::OpenOptions::new().write(true).open(&dst) {
            let _ = f.set_modified(modified);
        }
    }
    Ok(())
}

/// shutil.copytree: fails if dst exists
fn shutil_copytree(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir(dst).or_else(|e| if e.kind() == std::io::ErrorKind::NotFound { fs::create_dir_all(dst) } else { Err(e) })?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let s = entry.path();
        let d = dst.join(entry.file_name());
        if s.is_dir() {
            shutil_copytree(&s, &d)?;
        } else {
            copy2(&s, &d)?;
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Python value semantics

/// str.isspace() (Rust's White_Space plus the \x1c-\x1f separators)
pub(crate) fn py_isspace(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// str.strip()
pub(crate) fn py_strip(s: &str) -> &str {
    s.trim_matches(py_isspace)
}

/// Value of a Unicode decimal digit (the Nd blocks int() accepts).
fn decimal_digit(c: char) -> Option<u32> {
    const ZEROS: &[u32] = &[
        0x30, 0x660, 0x6F0, 0x7C0, 0x966, 0x9E6, 0xA66, 0xAE6, 0xB66, 0xBE6, 0xC66, 0xCE6, 0xD66, 0xDE6, 0xE50, 0xED0,
        0xF20, 0x1040, 0x1090, 0x17E0, 0x1810, 0x1946, 0x19D0, 0x1A80, 0x1A90, 0x1B50, 0x1BB0, 0x1C40, 0x1C50, 0xA620,
        0xA8D0, 0xA900, 0xA9D0, 0xA9F0, 0xAA50, 0xABF0, 0xFF10, 0x104A0, 0x11066, 0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC,
        0x1D7F6,
    ];
    let cp = c as u32;
    ZEROS.iter().find(|&&z| cp >= z && cp < z + 10).map(|&z| cp - z)
}

/// int(s) for a base-10 string; None for ValueError (and, unlike Python, for
/// values beyond i64).
pub(crate) fn py_int_from_str(s: &str) -> Option<i64> {
    let s = py_strip(s);
    let (neg, body) = match s.chars().next() {
        Some('-') => (true, &s[1..]),
        Some('+') => (false, &s[1..]),
        _ => (false, s),
    };
    if body.is_empty() || body.starts_with('_') || body.ends_with('_') || body.contains("__") {
        return None;
    }
    let mut n: i128 = 0;
    for c in body.chars() {
        if c == '_' {
            continue;
        }
        n = n * 10 + decimal_digit(c)? as i128;
        if n > i64::MAX as i128 + 1 {
            return None;
        }
    }
    let n = if neg { -n } else { n };
    i64::try_from(n).ok()
}

/// repr(float) / str(float)
pub(crate) fn py_float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf".into() } else { "-inf".into() };
    }
    let sci = format!("{:e}", f); // shortest round-trip digits: "-1.2345e-7"
    let (mantissa, exp) = sci.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let (sign, mantissa) = match mantissa.strip_prefix('-') {
        Some(m) => ("-", m),
        None => ("", mantissa),
    };
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let decpt = exp + 1;
    if decpt > -4 && decpt <= 16 {
        let n = digits.len() as i32;
        if decpt <= 0 {
            format!("{}0.{}{}", sign, "0".repeat((-decpt) as usize), digits)
        } else if decpt >= n {
            format!("{}{}{}.0", sign, digits, "0".repeat((decpt - n) as usize))
        } else {
            format!("{}{}.{}", sign, &digits[..decpt as usize], &digits[decpt as usize..])
        }
    } else {
        let m = if digits.len() > 1 { format!("{}.{}", &digits[..1], &digits[1..]) } else { digits.clone() };
        format!("{}{}e{}{:02}", sign, m, if exp < 0 { '-' } else { '+' }, exp.abs())
    }
}

/// An integer JSON number (Python int), if it fits i64.
fn json_int(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) if !n.is_f64() => n.as_i64(),
        _ => None,
    }
}

fn json_float(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) if n.is_f64() => n.as_f64(),
        _ => None,
    }
}

/// config._toInt(value, default)
fn to_int(value: &Value, default: &Value) -> Value {
    match value {
        Value::Bool(b) => Value::from(*b as i64),
        Value::String(s) => py_int_from_str(s).map(Value::from).unwrap_or_else(|| default.clone()),
        Value::Number(_) => {
            if let Some(i) = json_int(value) {
                return Value::from(i);
            }
            if let Some(f) = json_float(value) {
                if f.is_finite() && f.fract() == 0.0 && f >= -9.223372036854776e18 && f < 9.223372036854776e18 {
                    return Value::from(f as i64);
                }
            }
            default.clone()
        }
        _ => default.clone(),
    }
}

/// config._toBool(value, default)
fn to_bool(value: &Value, default: &Value) -> Value {
    match value {
        Value::Bool(b) => Value::Bool(*b),
        Value::Number(n) => Value::Bool(n.as_f64().map(|f| f != 0.0).unwrap_or(true)),
        Value::String(s) => {
            let lowered = py_strip(s).to_lowercase();
            match lowered.as_str() {
                "true" | "1" | "yes" | "on" => Value::Bool(true),
                "false" | "0" | "no" | "off" | "" => Value::Bool(false),
                _ => default.clone(),
            }
        }
        _ => default.clone(),
    }
}

fn truthy_bool(value: Option<&Value>) -> bool {
    to_bool(value.unwrap_or(&Value::Null), &Value::Bool(false)).as_bool().unwrap_or(false)
}

/// str(value) for an int or float JSON number
fn py_number_str(n: &serde_json::Number) -> String {
    if n.is_f64() {
        py_float_repr(n.as_f64().unwrap_or(0.0))
    } else {
        n.to_string()
    }
}

/// json.dumps(obj, sort_keys=True, indent=4) with the default ensure_ascii=True
pub(crate) fn py_json_dumps_sorted(value: &Value) -> String {
    let mut out = String::new();
    dump_value(value, 0, &mut out);
    out
}

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
            ' '..='~' => out.push(c),
            _ => {
                let mut buf = [0u16; 2];
                for unit in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{:04x}", unit));
                }
            }
        }
    }
    out.push('"');
}

fn dump_value(value: &Value, level: usize, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => {
            if n.is_f64() {
                let f = n.as_f64().unwrap_or(0.0);
                if f.is_nan() {
                    out.push_str("NaN")
                } else if f.is_infinite() {
                    out.push_str(if f > 0.0 { "Infinity" } else { "-Infinity" })
                } else {
                    out.push_str(&py_float_repr(f))
                }
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
                out.push_str(&" ".repeat((level + 1) * 4));
                dump_value(item, level + 1, out);
            }
            out.push('\n');
            out.push_str(&" ".repeat(level * 4));
            out.push(']');
        }
        Value::Object(map) => {
            if map.is_empty() {
                out.push_str("{}");
                return;
            }
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort(); // UTF-8 byte order == code point order
            out.push('{');
            for (i, key) in keys.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push('\n');
                out.push_str(&" ".repeat((level + 1) * 4));
                dump_string(key, out);
                out.push_str(": ");
                dump_value(&map[key.as_str()], level + 1, out);
            }
            out.push('\n');
            out.push_str(&" ".repeat(level * 4));
            out.push('}');
        }
    }
}

/// bytes.decode("mbcs"): the ANSI code page, strict
fn decode_mbcs(raw: &[u8]) -> Option<String> {
    if raw.is_empty() {
        return Some(String::new());
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn MultiByteToWideChar(code_page: u32, flags: u32, src: *const u8, src_len: i32, dst: *mut u16, dst_len: i32) -> i32;
    }
    const CP_ACP: u32 = 0;
    const MB_ERR_INVALID_CHARS: u32 = 0x8;
    let len = i32::try_from(raw.len()).ok()?;
    unsafe {
        let n = MultiByteToWideChar(CP_ACP, MB_ERR_INVALID_CHARS, raw.as_ptr(), len, std::ptr::null_mut(), 0);
        if n <= 0 {
            return None;
        }
        let mut buf = vec![0u16; n as usize];
        let n = MultiByteToWideChar(CP_ACP, MB_ERR_INVALID_CHARS, raw.as_ptr(), len, buf.as_mut_ptr(), n);
        if n <= 0 {
            return None;
        }
        String::from_utf16(&buf[..n as usize]).ok()
    }
}

fn decode_utf8_sig(raw: &[u8]) -> Option<&str> {
    let raw = raw.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(raw);
    std::str::from_utf8(raw).ok()
}

/// CinBaseConfig._readUserConfig
fn read_user_config(filename: &Path) -> Result<Map<String, Value>, String> {
    let raw = fs::read(filename).map_err(|e| e.to_string())?;
    let text = match decode_utf8_sig(&raw) {
        Some(t) => t.to_string(),
        None => decode_mbcs(&raw).ok_or("UnicodeDecodeError")?,
    };
    match serde_json::from_str::<Value>(&text).map_err(|e| e.to_string())? {
        Value::Object(m) => Ok(m),
        _ => Err("config.json is not a JSON object".into()),
    }
}

// ---------------------------------------------------------------------------

/// Version: mtimes of (config.json, symbols.dat, swkb.dat, fsymbols.dat,
/// flangs.dat, userphrase.dat, excludephrase.dat)
pub type ConfigVersion = [f64; 7];

#[derive(Debug, Clone)]
pub struct CinBaseConfig {
    settings: Settings,
    /// __dict__ minus the internal attributes, in Python's order
    values: Map<String, Value>,
    pub ime_dir_name: String,
    pub cin_file_list: Vec<String>,
    pub sel_cin_file: String,
    version: ConfigVersion,
    /// _lastUpdateTime (checkConfigChange resets it to 0.0 to force a re-read)
    pub last_update_time: f64,
    in_update: bool,
    pub paths: ConfigPaths,
}

impl Deref for CinBaseConfig {
    type Target = Settings;
    fn deref(&self) -> &Settings {
        &self.settings
    }
}

impl DerefMut for CinBaseConfig {
    fn deref_mut(&mut self) -> &mut Settings {
        &mut self.settings
    }
}

impl Default for CinBaseConfig {
    fn default() -> Self {
        Self::new()
    }
}

impl CinBaseConfig {
    /// CinBaseConfig() with directories from the environment.
    pub fn new() -> CinBaseConfig {
        Self::with_paths(ConfigPaths::from_env())
    }

    pub fn with_paths(paths: ConfigPaths) -> CinBaseConfig {
        CinBaseConfig {
            settings: Settings::default(),
            values: defaults_map(),
            ime_dir_name: String::new(),
            cin_file_list: Vec::new(),
            sel_cin_file: String::new(),
            version: [0.0; 7],
            last_update_time: 0.0,
            in_update: false,
            paths,
        }
    }

    /// For a text service: new config for `ime_dir_name`, loaded (ime_base.py).
    pub fn for_ime(ime_dir_name: &str, cin_file_list: &[&str]) -> CinBaseConfig {
        let mut cfg = Self::new();
        cfg.ime_dir_name = ime_dir_name.to_string();
        cfg.cin_file_list = cin_file_list.iter().map(|s| s.to_string()).collect();
        cfg.load();
        cfg
    }

    // -- directories ------------------------------------------------------

    /// getConfigDir(): %APPDATA%\PIME\<ime>, created if missing
    pub fn get_config_dir(&self) -> PathBuf {
        let dir = self.paths.appdata.join("PIME").join(&self.ime_dir_name);
        let _ = fs::create_dir_all(&dir);
        dir
    }

    pub fn get_config_file(&self, name: &str) -> PathBuf {
        self.get_config_dir().join(name)
    }

    pub fn get_data_dir(&self) -> PathBuf {
        self.paths.python_dir.join("cinbase").join("data")
    }

    pub fn get_cin_dir(&self) -> PathBuf {
        self.paths.python_dir.join("cinbase").join("cin")
    }

    pub fn get_json_dir(&self) -> PathBuf {
        self.paths.python_dir.join("cinbase").join("json")
    }

    pub fn get_default_config_dir(&self) -> PathBuf {
        self.paths.python_dir.join("input_methods").join(&self.ime_dir_name).join("config")
    }

    /// findFile(dirs, name): the first dirs[i]\name that exists
    pub fn find_file<P: AsRef<Path>>(&self, dirs: &[P], name: &str) -> Option<PathBuf> {
        dirs.iter().map(|d| d.as_ref().join(name)).find(|p| p.exists())
    }

    /// getSelKeys(): selKeys[selKeyType] -- ONE character of "1234567890"
    /// (Python indexing; IndexError when out of range).
    pub fn get_sel_keys(&self) -> Result<String, String> {
        let chars: Vec<char> = SEL_KEYS.chars().collect();
        let n = chars.len() as i64;
        let i = self.sel_key_type;
        let index = if i < 0 { i + n } else { i };
        if index < 0 || index >= n {
            return Err("IndexError: string index out of range".into());
        }
        Ok(chars[index as usize].to_string())
    }

    // -- raw attribute access -------------------------------------------------

    /// getattr(cfg, key, None) for any setting, including unknown keys.
    pub fn get(&self, key: &str) -> Option<Value> {
        if Settings::KEYS.contains(&key) {
            let mut m = Map::new();
            self.settings.write_to(&mut m);
            return m.remove(key);
        }
        self.values.get(key).cloned()
    }

    /// setattr(cfg, key, value) for a setting or an unknown key. A known
    /// setting given a value of the wrong type is ignored.
    pub fn set(&mut self, key: &str, value: Value) {
        if is_internal_key(key) {
            return;
        }
        self.store_fields();
        self.values.insert(key.to_string(), value);
        self.settings.read_from(&self.values);
    }

    fn current_values(&self) -> Map<String, Value> {
        let mut values = self.values.clone();
        self.settings.write_to(&mut values);
        values
    }

    fn store_fields(&mut self) {
        self.values = self.current_values();
    }

    fn load_fields(&mut self) {
        let values = std::mem::take(&mut self.values);
        self.settings.read_from(&values);
        self.values = values;
    }

    /// self.__dict__.update(data) for a file's JSON object
    fn apply(&mut self, data: Map<String, Value>) {
        for (k, v) in data {
            if !is_internal_key(&k) {
                self.values.insert(k, v);
            }
        }
    }

    /// self.__dict__.update(json.load(shipped)): dict.update also takes a
    /// sequence of pairs (applied up to the first bad element).
    fn apply_shipped(&mut self, data: Value) {
        match data {
            Value::Object(m) => self.apply(m),
            Value::Array(items) => {
                for item in items {
                    let pair = match item {
                        Value::Array(pair) if pair.len() == 2 => match &pair[0] {
                            Value::String(k) => Some((k.clone(), pair[1].clone())),
                            _ => None,
                        },
                        Value::String(s) if s.chars().count() == 2 => {
                            let mut it = s.chars();
                            let (a, b) = (it.next().unwrap(), it.next().unwrap());
                            Some((a.to_string(), Value::String(b.to_string())))
                        }
                        _ => None,
                    };
                    let Some((k, v)) = pair else { return };
                    if !is_internal_key(&k) {
                        self.values.insert(k, v);
                    }
                }
            }
            _ => {}
        }
    }

    // -- load / normalize ----------------------------------------------------

    /// CinBaseConfig.load(): shipped defaults, then the user's config.json.
    pub fn load(&mut self) {
        self.store_fields();

        // Layer 1: the shipped per-IME defaults
        let default_config = self.get_default_config_dir().join("config.json");
        if default_config.exists() && file_size(&default_config).unwrap_or(0) > 0 {
            if let Ok(raw) = fs::read(&default_config) {
                if let Some(text) = decode_utf8_sig(&raw) {
                    // text mode: universal newlines
                    let text = text.replace("\r\n", "\n").replace('\r', "\n");
                    if let Ok(data) = serde_json::from_str::<Value>(&text) {
                        self.apply_shipped(data);
                    }
                }
            }
        }
        self.normalize(None);
        let shipped = self.values.clone();

        // Layer 2: the user's config (APPDATA, or the legacy home-dir copy)
        let mut filename: Option<PathBuf> = Some(self.get_config_file("config.json"));
        let mut user_values = Map::new();
        let result = (|| -> Result<(), String> {
            let f = filename.clone().unwrap();
            if !f.exists() || file_size(&f).unwrap_or(0) == 0 {
                let legacy_dir = self.paths.home.join("PIME").join(&self.ime_dir_name);
                let legacy = legacy_dir.join("config.json");
                if !legacy.exists() || file_size(&legacy).unwrap_or(0) == 0 {
                    filename = None;
                } else {
                    filename = Some(legacy);
                    let dst_dir = self.get_config_dir();
                    for entry in fs::read_dir(&legacy_dir).map_err(|e| e.to_string())? {
                        let entry = entry.map_err(|e| e.to_string())?;
                        let s = entry.path();
                        let d = dst_dir.join(entry.file_name());
                        if s.is_dir() {
                            shutil_copytree(&s, &d).map_err(|e| e.to_string())?;
                        } else {
                            copy2(&s, &d).map_err(|e| e.to_string())?;
                        }
                    }
                    filename = Some(self.get_config_file("config.json"));
                }
            }
            if let Some(f) = &filename {
                user_values = read_user_config(f)?;
                self.apply(user_values.clone());
            }
            Ok(())
        })();
        if result.is_err() {
            backup_broken_config(filename.as_deref());
        }
        for key in RETIRED_KEYS {
            self.values.shift_remove(*key);
        }
        self.normalize(Some(&shipped));
        if self.values.get("candidateMaxWidth").and_then(json_int) == Some(LEGACY_CANDIDATE_MAX_WIDTH)
            && !truthy_bool(user_values.get("candidateMaxWidthMigrated"))
        {
            let v = shipped.get("candidateMaxWidth").cloned().unwrap_or(Value::from(320));
            self.values.insert("candidateMaxWidth".into(), v);
        }
        self.load_fields();
        self.update();
    }

    /// CinBaseConfig.normalize(fallback) on the raw values.
    fn normalize(&mut self, fallback: Option<&Map<String, Value>>) {
        let defaults = defaults_map();
        let fallback = fallback.unwrap_or(&defaults);
        for (key, default) in defaults.iter() {
            let value = self.values.get(key).cloned().unwrap_or_else(|| default.clone());
            let good = fallback.get(key).cloned().unwrap_or_else(|| default.clone());
            let new = match default {
                Value::Bool(_) => (!value.is_boolean()).then(|| to_bool(&value, &good)),
                Value::Number(_) => json_int(&value).is_none().then(|| to_int(&value, &good)),
                Value::String(_) => match &value {
                    Value::String(_) => None,
                    Value::Number(n) => Some(Value::String(py_number_str(n))),
                    _ => Some(good),
                },
                Value::Object(_) => (!value.is_object()).then_some(good),
                _ => None,
            };
            if let Some(new) = new {
                self.values.insert(key.clone(), new);
            }
        }
        for (key, low, high) in INT_RANGES {
            let v = self.values.get(*key).and_then(json_int).unwrap_or(i64::MIN);
            if !(*low <= v && v <= *high) {
                let good = fallback.get(*key).and_then(json_int).or_else(|| defaults.get(*key).and_then(json_int)).unwrap_or(0);
                let new = if *low <= good && good <= *high { good } else { defaults[*key].as_i64().unwrap_or(0) };
                self.values.insert(key.to_string(), Value::from(new));
            }
        }
        for (key, value) in FIXED_VALUES {
            self.values.insert(key.to_string(), Value::String(value.to_string()));
        }
    }

    // -- versions / reload ----------------------------------------------------

    /// update(): at most every 3 seconds, re-read the file mtimes and reload
    /// when config.json changed.
    pub fn update(&mut self) {
        if env::time() - self.last_update_time < 3.0 {
            return;
        }
        let config_time = mtime(&self.get_config_file("config.json")).unwrap_or(0.0);
        let datadirs = [self.get_config_dir(), self.get_data_dir()];
        let t = |name: &str| self.find_file(&datadirs, name).and_then(|p| mtime(&p)).unwrap_or(0.0);
        let version = [
            config_time,
            t("symbols.dat"),
            t("swkb.dat"),
            t("fsymbols.dat"),
            t("flangs.dat"),
            t("userphrase.dat"),
            t("excludephrase.dat"),
        ];
        let last_config_time = self.version[0];
        self.version = version;
        if last_config_time != config_time && !self.in_update {
            self.in_update = true;
            self.load();
            self.in_update = false;
        }
        self.last_update_time = env::time();
    }

    pub fn get_version(&self) -> ConfigVersion {
        self.version
    }

    pub fn is_config_changed(&self, current_version: &ConfigVersion) -> bool {
        current_version[0] != self.version[0]
    }

    /// The data files changed: the context must be rebuilt.
    pub fn is_full_reload_needed(&self, current_version: &ConfigVersion) -> bool {
        current_version[1..] != self.version[1..]
    }

    // -- output -----------------------------------------------------------------

    /// toJson(): every setting and unknown key, in attribute order.
    pub fn to_json(&self) -> Map<String, Value> {
        self.current_values()
    }

    /// save(): config.json via a fsynced temporary file; errors are swallowed.
    pub fn save(&mut self) {
        self.store_fields();
        let filename = self.get_config_file("config.json");
        let mut tmp = filename.clone().into_os_string();
        tmp.push(".tmp");
        let tmp = PathBuf::from(tmp);
        let text = py_json_dumps_sorted(&Value::Object(self.to_json())).replace('\n', "\r\n");
        let result = (|| -> std::io::Result<()> {
            let mut f = fs::File::create(&tmp)?;
            f.write_all(text.as_bytes())?;
            f.flush()?;
            f.sync_all()?;
            drop(f);
            fs::rename(&tmp, &filename)
        })();
        match result {
            Ok(()) => self.update(),
            Err(_) => {
                if tmp.exists() {
                    let _ = fs::remove_file(&tmp);
                }
            }
        }
    }
}

/// CinBaseConfig._backupBrokenConfig
fn backup_broken_config(filename: Option<&Path>) {
    let Some(filename) = filename else { return };
    if !filename.exists() {
        return;
    }
    let Some(t) = mtime(filename) else { return };
    let mut backup = filename.as_os_str().to_owned();
    backup.push(format!(".broken-{}", t as i64));
    let backup = PathBuf::from(backup);
    if !backup.exists() {
        let _ = copy2(filename, &backup);
    }
}

#[cfg(test)]
#[path = "config_tests.rs"]
mod tests;
