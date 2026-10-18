//! 新酷音 (chewing): port of python/input_methods/chewing/chewing_ime.py.
//! `// CI:<line>` marks the ported Python code (chewing_ime.py lines).
//!
//! The engine is upstream libchewing linked in-process (engine.rs); settings
//! are chewing_config.py (config.rs), the candidate column count is
//! candidate_layout.py (layout.rs) and the old user dictionary conversion is
//! libchewing/userdict.py (userdict.rs).
//!
//! Not ported: ChewingTextService.handleRequest's ChewingFault recovery
//! (CI:162-192). It catches access violations ctypes reports from inside
//! chewing.dll (the old C libchewing had some); the engine linked here is Rust
//! code in the same process, so there is no such error to recover from.

pub mod config;
pub mod engine;
pub mod layout;
pub mod userdict;

use crate::candidate_theme::{colors_for_theme, resolve_theme_name};
use crate::env;
use crate::keycodes::*;
use crate::paths;
use crate::textservice::{KeyEvent, Service, TextService, COMMAND_LEFT_CLICK, COMMAND_MENU, TF_MOD_SHIFT};
use crate::ClientInfo;
use config::{ChewingConfig, Version, SWITCH_LANG_WITH_BOTH_SHIFT, SWITCH_LANG_WITH_LEFT_SHIFT, SWITCH_LANG_WITH_RIGHT_SHIFT};
use engine::{c_int_arg, ChewingContext, CHINESE_MODE, ENGLISH_MODE, FULLSHAPE_MODE, HALFSHAPE_MODE};
use serde_json::{json, Map, Value};
use std::cell::{Cell, RefCell};
use std::path::PathBuf;

pub const CHEWING_GUID: &str = "{f80736aa-28db-423a-92c9-5540f501c939}";

/// CI:51 shift + space 熱鍵的 GUID
const SHIFT_SPACE_GUID: &str = "{f1dae0fb-8091-44a7-8a0c-3082a1515447}";

// CI:54 選單項目和語言列按鈕的 command ID
const ID_SWITCH_LANG: i64 = 1;
const ID_SWITCH_SHAPE: i64 = 2;
const ID_SETTINGS: i64 = 3;
const ID_MODE_ICON: i64 = 4;
const ID_WEBSITE: i64 = 6;
const ID_GROUP: i64 = 7;
const ID_BUGREPORT: i64 = 8;
const ID_DICT_BUGREPORT: i64 = 9;
const ID_MOEDICT: i64 = 13;
const ID_DICT: i64 = 14;
const ID_SIMPDICT: i64 = 15;
const ID_LITTLEDICT: i64 = 16;
const ID_PROVERBDICT: i64 = 17;
const ID_USER_PHRASE_EDITOR: i64 = 19;

/// CI:112 from libchewing/include/global.h
const AUTOLEARN_ENABLED: i32 = 0;
const AUTOLEARN_DISABLED: i32 = 1;
/// CI:116 MAX_CHI_SYMBOL_LEN
const MAX_CHI_SYMBOL_LEN: i32 = 39;
/// CI:119 掃描碼
const LEFT_SHIFT_SCAN_CODE: u32 = 0x2A;
const RIGHT_SHIFT_SCAN_CODE: u32 = 0x36;

/// CI:126 LAYOUT_BOPOMOFO_SYMBOL_KEYS
fn layout_bopomofo_symbol_keys(layout: i64) -> &'static str {
    match layout {
        3 => "=['",
        4 => "='",
        6 => "['",
        _ => "",
    }
}

/// CI:34 keyNames
fn key_name(key_code: u32) -> Option<&'static str> {
    Some(match key_code {
        VK_ESCAPE => "Esc",
        VK_RETURN => "Enter",
        VK_TAB => "Tab",
        VK_DELETE => "Del",
        VK_BACK => "Backspace",
        VK_UP => "Up",
        VK_DOWN => "Down",
        VK_LEFT => "Left",
        VK_RIGHT => "Right",
        VK_HOME => "Home",
        VK_END => "End",
        VK_PRIOR => "PageUp",
        VK_NEXT => "PageDown",
        _ => return None,
    })
}

/// CI:84 isBopomofoChar
fn is_bopomofo_char(ch: char) -> bool {
    let code = ch as u32;
    (0x3100..=0x312F).contains(&code) || (0x31A0..=0x31BF).contains(&code) || "˙ˊˇˋ".contains(ch)
}

/// CI:93 splitTrailingBopomofo
fn split_trailing_bopomofo(text: &str) -> (String, String) {
    let chars: Vec<char> = text.chars().collect();
    let mut root_start = chars.len();
    while root_start > 0 && is_bopomofo_char(chars[root_start - 1]) {
        root_start -= 1;
    }
    (chars[..root_start].iter().collect(), chars[root_start..].iter().collect())
}

// --- Python str methods on one character -----------------------------------

fn py_isalpha(c: char) -> bool {
    c.is_alphabetic()
}

fn py_isupper(c: char) -> bool {
    c.is_uppercase()
}

fn py_isdigit(c: char) -> bool {
    c.is_ascii_digit()
        || crate::config::decimal_digit(c).is_some()
        || matches!(c as u32, 0xB2 | 0xB3 | 0xB9 | 0x2070 | 0x2074..=0x2079 | 0x2080..=0x2089 | 0x2460..=0x2468 | 0x2474..=0x247C | 0x2488..=0x2490 | 0x24F5..=0x24FD | 0x24EA | 0x24FF | 0x2776..=0x277E | 0x2780..=0x2788 | 0x278A..=0x2792 | 0x1369..=0x1371 | 0x19DA)
}

/// ord(s) for a str: TypeError unless it is one character
fn py_ord(s: &str) -> Result<i32, String> {
    let mut it = s.chars();
    match (it.next(), it.next()) {
        (Some(c), None) => Ok(c as i32),
        _ => Err(format!("TypeError: ord() expected a character, but string of length {} found", s.chars().count())),
    }
}

fn py_upper(c: char) -> String {
    c.to_uppercase().collect()
}

fn py_lower(c: char) -> String {
    c.to_lowercase().collect()
}

thread_local! {
    /// the module-level chewingConfig, created when the module is first imported
    static CHEWING_CONFIG: RefCell<Option<ChewingConfig>> = const { RefCell::new(None) };
    /// CI:108 _userPhraseWarningShown
    static USER_PHRASE_WARNING_SHOWN: Cell<bool> = const { Cell::new(false) };
}

/// `import chewing_ime`: chewingConfig = ChewingConfig()
fn ensure_config() {
    CHEWING_CONFIG.with_borrow_mut(|c| {
        if c.is_none() {
            *c = Some(ChewingConfig::new(true));
        }
    });
}

fn with_cfg<R>(f: impl FnOnce(&ChewingConfig) -> R) -> R {
    CHEWING_CONFIG.with_borrow(|c| f(c.as_ref().expect("chewingConfig")))
}

fn with_cfg_mut<R>(f: impl FnOnce(&mut ChewingConfig) -> R) -> R {
    CHEWING_CONFIG.with_borrow_mut(|c| f(c.as_mut().expect("chewingConfig")))
}

fn cfg_truthy(key: &str) -> bool {
    with_cfg(|c| c.truthy(key))
}

fn cfg_int(key: &str) -> i64 {
    with_cfg(|c| c.int(key))
}

fn cfg_value(key: &str) -> Value {
    with_cfg(|c| c.get(key).clone())
}

/// a setting passed to libchewing (ctypes converts bool/int to a C int)
fn cfg_c_int(key: &str) -> Result<i32, String> {
    c_int_arg(cfg_int(key))
}

/// CHEWING_DATA_DIR (python/libchewing/data)
fn chewing_data_dir() -> PathBuf {
    paths::chewing_data_dir()
}

/// libchewing.searchPath(*dirs): ";"-joined
fn search_path(dirs: &[&PathBuf]) -> String {
    dirs.iter().map(|d| d.to_string_lossy().into_owned()).filter(|s| !s.is_empty()).collect::<Vec<_>>().join(";")
}

fn obj(pairs: Vec<(&str, Value)>) -> Map<String, Value> {
    pairs.into_iter().map(|(k, v)| (k.to_string(), v)).collect()
}

/// CI:133 ChewingTextService
pub struct ChewingService {
    ts: TextService,
    client: ClientInfo,
    curdir: PathBuf,
    icon_dir: PathBuf,
    ctx: Option<ChewingContext>,
    lang_mode: i64,
    shape_mode: i64,
    last_lang_mode: Option<i64>,
    last_shape_mode: Option<i64>,
    last_key_down_time: f64,
    last_key_event: Option<KeyEvent>,
    config_version: Version,
    has_lang_buttons: bool,
    update_switch_lang_icon: bool,
    user_phrase_fallback: bool,
    composition_sync_pending: bool,
    last_candidate_ui_args: Option<Map<String, Value>>,
    sel_keys: String,
}

impl ChewingService {
    /// CI:134 __init__
    pub fn new(client: ClientInfo) -> ChewingService {
        ensure_config();
        let curdir = paths::chewing_dir();
        ChewingService {
            ts: TextService::default(),
            client,
            icon_dir: curdir.join("icons"),
            curdir,
            ctx: None,
            lang_mode: -1,
            shape_mode: -1,
            last_lang_mode: None,
            last_shape_mode: None,
            last_key_down_time: 0.0,
            last_key_event: None,
            config_version: with_cfg(|c| c.get_version()),
            has_lang_buttons: false,
            update_switch_lang_icon: false,
            user_phrase_fallback: false,
            composition_sync_pending: false,
            last_candidate_ui_args: None,
            sel_keys: String::new(),
        }
    }

    fn icon(&self, name: &str) -> String {
        paths::join_str(&self.icon_dir, name)
    }

    fn ctx(&mut self) -> &mut ChewingContext {
        self.ctx.as_mut().expect("chewingContext")
    }

    /// CI:213 rememberModes
    fn remember_modes(&mut self) {
        if self.lang_mode == CHINESE_MODE || self.lang_mode == ENGLISH_MODE {
            self.last_lang_mode = Some(self.lang_mode);
        }
        if self.shape_mode == FULLSHAPE_MODE || self.shape_mode == HALFSHAPE_MODE {
            self.last_shape_mode = Some(self.shape_mode);
        }
    }

    /// CI:219 rebuildChewingContext
    fn rebuild_chewing_context(&mut self) -> Result<(), String> {
        self.remember_modes();
        self.close_chewing_context();
        self.clear_composition_state();
        self.init_chewing_context()
    }

    /// CI:226 clearCompositionState
    fn clear_composition_state(&mut self) {
        self.composition_sync_pending = false;
        if self.ts.show_candidates || !self.ts.candidate_list.is_empty() {
            self.ts.set_candidate_list(vec![]);
            self.ts.set_candidate_cursor(0);
            self.ts.set_show_candidates(false);
        }
        if !self.ts.composition_string.is_empty() {
            self.ts.set_composition_string("");
            self.ts.set_composition_cursor(0);
        }
    }

    /// CI:236 customizeCandidateUI
    fn customize_candidate_ui(&mut self, force: bool) {
        let ui_per_row = self.candidates_per_ui_row();
        let theme_raw = cfg_value("candidateTheme");
        // str(getattr(cfg, 'candidateTheme', '') or '')
        let theme = match &theme_raw {
            Value::String(s) => s.clone(),
            _ => String::new(),
        };
        let ui_args = obj(vec![
            ("candFontName", json!(layout::FONT_NAME)),
            ("candFontSize", cfg_value("fontSize")),
            ("candPerRow", ui_per_row),
            ("candUseCursor", json!(!(cfg_truthy("leftRightAction") && cfg_truthy("upDownAction")))),
            ("candidateLayout", cfg_value("candidateLayout")),
            ("candidatePerRow", cfg_value("candidatePerRow")),
            ("candidateEdgeAvoidance", cfg_value("candidateEdgeAvoidance")),
            ("candidatePositionMode", cfg_value("candidatePositionMode")),
            ("candidateOpacity", cfg_value("candidateOpacity")),
            ("candidateTheme", json!(resolve_theme_name(&theme))),
            ("candidateKeyStyle", cfg_value("candidateKeyStyle")),
            ("candidateHeaderStyle", json!("accent")),
            ("candidateMessageStyle", cfg_value("candidateMessageStyle")),
            ("candidateColors", Value::Object(colors_for_theme(&cfg_value("candidateColors"), &theme))),
            ("candidateStyle", cfg_value("candidateStyle")),
            ("candidateStableWidth", cfg_value("candidateStableWidth")),
            ("candidateMinWidth", cfg_value("candidateMinWidth")),
            ("candidateWrapToMaxWidth", cfg_value("candidateWrapToMaxWidth")),
            ("candidateMaxWidth", cfg_value("candidateMaxWidth")),
        ]);
        if !force && self.last_candidate_ui_args.as_ref() == Some(&ui_args) {
            return;
        }
        self.last_candidate_ui_args = Some(ui_args.clone());
        self.ts.customize_ui(ui_args);
    }

    /// CI:267 updateCandidateHeader
    fn update_candidate_header(&mut self, root_str: &str, force_window: bool) {
        let header = if root_str.is_empty() { "新酷音".to_string() } else { format!("新酷音 {}", root_str) };
        self.ts.current_reply.insert("candidateHeader".into(), json!(header));
        let (total_page, current_page) = match self.ctx.as_ref() {
            Some(ctx) => (ctx.cand_total_page(), ctx.cand_current_page()),
            None => (0, 0),
        };
        let info = if total_page > 0 { format!("{}/{}", current_page + 1, total_page) } else { String::new() };
        self.ts.current_reply.insert("candidatePageInfo".into(), json!(info));
        if force_window {
            if !self.ts.current_reply.contains_key("candidateList") {
                let list = if self.ts.show_candidates && !self.ts.candidate_list.is_empty() { self.ts.candidate_list.clone() } else { vec![] };
                self.ts.set_candidate_list(list);
            }
            self.ts.set_show_candidates(true);
        }
    }

    /// CI:284 applyConfig
    fn apply_config(&mut self) -> Result<(), String> {
        if self.ctx.is_none() {
            return Ok(());
        }
        self.config_version = with_cfg(|c| c.get_version());
        let add_phrase = cfg_c_int("addPhraseForward")?;
        self.ctx().set_add_phrase_direction(add_phrase);
        let advance = cfg_c_int("advanceAfterSelection")?;
        self.ctx().set_auto_shift_cur(advance);
        let per_page = cfg_c_int("candPerPage")?;
        self.ctx().set_cand_per_page(per_page);
        let esc = cfg_c_int("escCleanAllBuf")?;
        self.ctx().set_esc_clean_all_buf(esc);
        let kb = cfg_c_int("keyboardLayout")?;
        self.ctx().set_kb_type(kb);
        let space = cfg_c_int("spaceKeyAction")?;
        self.ctx().set_space_as_selection(space);
        self.customize_candidate_ui(true);
        // CI:505 setAutoLearn
        let auto_learn = cfg_truthy("autoLearn");
        self.ctx().set_auto_learn(if auto_learn { AUTOLEARN_ENABLED } else { AUTOLEARN_DISABLED });
        let keys = with_cfg(|c| c.get_sel_keys())?;
        self.set_sel_keys(keys);
        let rearward = cfg_c_int("phraseChoiceRearward")?;
        self.ctx().set_phrase_choice_rearward(rearward);
        Ok(())
    }

    /// CI:322 createChewingContext
    fn create_chewing_context(&mut self) -> Option<ChewingContext> {
        let config_dir = with_cfg(|c| c.get_config_dir());
        let search_paths = search_path(&[&config_dir, &chewing_data_dir()]);
        let config_dir_str = config_dir.to_string_lossy().into_owned();
        self.user_phrase_fallback = false;
        let first = userdict::prepare_user_dictionary(&config_dir, &search_paths)
            .and_then(|user_phrase| ChewingContext::new(&search_paths, &user_phrase.to_string_lossy(), Some(&config_dir_str), true));
        match first {
            Ok(ctx) => return Some(ctx),
            Err(err) => {
                eprintln!("chewing: cannot open the user phrase dictionary {}: {}", with_cfg(|c| c.get_user_phrase()).display(), err);
            }
        }
        let ctx = match ChewingContext::new(&search_paths, ":memory:", Some(&config_dir_str), true) {
            Ok(ctx) => ctx,
            Err(err) => {
                eprintln!("chewing: cannot create a libchewing context (data: {}): {}", chewing_data_dir().display(), err);
                return None;
            }
        };
        self.user_phrase_fallback = true;
        if !USER_PHRASE_WARNING_SHOWN.get() {
            USER_PHRASE_WARNING_SHOWN.set(true);
            self.ts.show_message("無法開啟新酷音使用者詞庫，這次學到的詞不會儲存", 5);
        }
        Some(ctx)
    }

    /// CI:354 initChewingContext
    fn init_chewing_context(&mut self) -> Result<(), String> {
        if self.ctx.is_some() && self.user_phrase_fallback && !self.ts.is_composing() {
            return self.rebuild_chewing_context();
        }
        if self.ctx.is_none() {
            let Some(ctx) = self.create_chewing_context() else { return Ok(()) };
            self.ctx = Some(ctx);
            self.ctx().set_max_chi_symbol_len(MAX_CHI_SYMBOL_LEN);
            self.lang_mode = match self.last_lang_mode {
                Some(m) => m,
                None => {
                    if cfg_truthy("defaultEnglish") {
                        ENGLISH_MODE
                    } else {
                        CHINESE_MODE
                    }
                }
            };
            let lang = self.lang_mode as i32;
            self.ctx().set_chi_eng_mode(lang);
            self.shape_mode = match self.last_shape_mode {
                Some(m) => m,
                None => {
                    if cfg_truthy("defaultFullSpace") {
                        FULLSHAPE_MODE
                    } else {
                        HALFSHAPE_MODE
                    }
                }
            };
            let shape = self.shape_mode as i32;
            self.ctx().set_shape_mode(shape);
        }
        self.apply_config()
    }

    /// CI:416 capsLockTypesEnglish
    fn caps_lock_types_english(&self) -> bool {
        cfg_truthy("enableCapsLock") && self.get_capslock_state()
    }

    /// CI:420 langIconPath
    fn lang_icon_path(&self) -> String {
        let name = if self.lang_mode == CHINESE_MODE {
            if self.caps_lock_types_english() {
                "capsEng.ico"
            } else {
                "traC.ico"
            }
        } else {
            "eng.ico"
        };
        self.icon(name)
    }

    /// CI:430 modeIconInfo
    fn mode_icon_info(&self) -> (String, String) {
        if !self.ts.keyboard_open {
            return (self.icon("eng.ico"), "新酷音：已關閉（按一下或按 Ctrl+空白鍵開啟）".into());
        }
        let lang = if self.lang_mode == CHINESE_MODE {
            if self.caps_lock_types_english() {
                "英文（CapsLock）"
            } else {
                "中文"
            }
        } else {
            "英文"
        };
        let shape = if self.shape_mode == FULLSHAPE_MODE { "全形" } else { "半形" };
        (self.lang_icon_path(), format!("新酷音：{}、{}（按一下切換中英文）", lang, shape))
    }

    /// CI:442 updateModeIcon
    fn update_mode_icon(&mut self, enable: Option<bool>) {
        let (icon, tooltip) = self.mode_icon_info();
        let mut info = obj(vec![("icon", json!(icon)), ("tooltip", json!(tooltip))]);
        if let Some(e) = enable {
            info.insert("enable".into(), json!(e));
        }
        self.ts.change_button("windows-mode-icon", info);
    }

    /// CI:448 addLangButtons
    fn add_lang_buttons(&mut self) {
        if self.has_lang_buttons {
            return;
        }
        let lang_icon = self.lang_icon_path();
        self.ts.add_button(
            "switch-lang",
            obj(vec![("icon", json!(lang_icon)), ("tooltip", json!("中英文切換")), ("commandId", json!(ID_SWITCH_LANG))]),
        );
        let shape_icon = self.icon(if self.shape_mode == FULLSHAPE_MODE { "full.ico" } else { "half.ico" });
        self.ts.add_button(
            "switch-shape",
            obj(vec![("icon", json!(shape_icon)), ("tooltip", json!("全形/半形切換")), ("commandId", json!(ID_SWITCH_SHAPE))]),
        );
        let config_icon = self.icon("config.ico");
        self.ts.add_button("settings", obj(vec![("icon", json!(config_icon)), ("tooltip", json!("設定")), ("type", json!("menu"))]));
        self.has_lang_buttons = true;
    }

    /// CI:474 removeLangButtons
    fn remove_lang_buttons(&mut self) {
        if self.has_lang_buttons {
            self.ts.remove_button("switch-lang");
            self.ts.remove_button("switch-shape");
            self.ts.remove_button("settings");
        }
        self.has_lang_buttons = false;
    }

    /// CI:498 closeChewingContext
    fn close_chewing_context(&mut self) {
        self.ctx = None;
    }

    /// CI:512 setSelKeys
    fn set_sel_keys(&mut self, sel_keys: &str) {
        self.ts.set_sel_keys(sel_keys);
        self.sel_keys = sel_keys.to_string();
        if let Some(ctx) = self.ctx.as_mut() {
            ctx.set_sel_keys(sel_keys);
        }
    }

    /// CI:604 isImeCtrlKey
    fn is_ime_ctrl_key(&self, ev: &KeyEvent) -> bool {
        if ev.is_key_down(VK_MENU) || !ev.is_key_down(VK_CONTROL) {
            return false;
        }
        let c = char::from_u32(ev.char_code).unwrap_or('\u{FFFD}');
        if py_isdigit(c) {
            return true;
        }
        cfg_truthy("easySymbolsWithCtrl") && self.lang_mode == CHINESE_MODE
    }

    /// CI:613 candidatesPerUiRow
    fn candidates_per_ui_row(&self) -> Value {
        if cfg_value("candidateLayout") == json!("vertical") {
            json!(1)
        } else {
            cfg_value("candidatePerRow")
        }
    }

    /// CI:621 candidatesPerVisibleRow
    fn candidates_per_visible_row(&self) -> Result<i64, String> {
        let style = match cfg_value("candidateStyle") {
            Value::Object(m) => m,
            _ => Map::new(),
        };
        let style_int = |key: &str, default: i64| style.get(key).and_then(config::py_int_value).unwrap_or(default);
        let sel_keys = with_cfg(|c| c.get_sel_keys())?;
        let per_row = config::py_int_value(&self.candidates_per_ui_row()).unwrap_or(0);
        let key_style = match cfg_value("candidateKeyStyle") {
            Value::String(s) => s,
            _ => String::new(),
        };
        layout::candidate_columns(
            &self.ts.candidate_list,
            sel_keys,
            per_row,
            cfg_int("fontSize"),
            cfg_int("candidateMaxWidth"),
            cfg_truthy("candidateWrapToMaxWidth"),
            style_int("contentMargin", 8),
            style_int("textMargin", 6),
            &key_style,
            layout::FONT_NAME,
        )
    }

    /// CI:633 maintainUserPhrase
    fn maintain_user_phrase(&mut self, key_code: u32, target_phrase: &str) {
        let readings: Vec<String> = self
            .ctx()
            .user_phrases()
            .into_iter()
            .filter(|(phrase, _)| phrase == target_phrase)
            .map(|(_, bopomofo)| bopomofo)
            .collect();
        if readings.is_empty() {
            if key_code == VK_DELETE {
                self.ts.show_message(&format!("詞彙「{}」不存在，無法刪除", target_phrase), 2);
            } else if key_code == VK_NEXT {
                self.ts.show_message(&format!("詞彙「{}」不存在，無法降低詞頻", target_phrase), 2);
            } else if key_code == VK_PRIOR {
                self.ts.show_message(&format!("詞彙「{}」不存在，無法提昇詞頻", target_phrase), 2);
            }
            return;
        }
        if key_code == VK_DELETE {
            for b in &readings {
                self.ctx().userphrase_remove(target_phrase, b);
            }
            self.ts.show_message(&format!("刪除「{}」成功", target_phrase), 2);
        } else if key_code == VK_PRIOR {
            for b in &readings {
                self.ctx().userphrase_remove(target_phrase, b);
                self.ctx().userphrase_add(target_phrase, b);
            }
            self.ts.show_message(&format!("↑提昇「{}」詞頻成功", target_phrase), 2);
        } else if key_code == VK_NEXT {
            for b in &readings {
                self.ctx().userphrase_remove(target_phrase, b);
            }
            let total = self.ctx().cand_total_choice().max(0);
            let mut found = false;
            for i in 0..total {
                if self.ctx().cand_string_by_index(i as i32) == target_phrase {
                    found = true;
                }
            }
            if found {
                self.ts.show_message(&format!("↓降低「{}」詞頻成功", target_phrase), 2);
            } else {
                for b in &readings {
                    self.ctx().userphrase_add(target_phrase, b);
                }
                self.ts.show_message(&format!("「{}」是自訂詞，無法再降低詞頻；要刪除請按 Ctrl+Del", target_phrase), 3);
            }
        }
    }

    /// CI:1016 isPressed
    fn is_pressed(&self, key_code: u32) -> bool {
        env::is_pressed(key_code)
    }

    /// CI:1019 isModifierHeld
    fn is_modifier_held(ev: &KeyEvent) -> bool {
        ev.is_key_down(VK_CONTROL) || ev.is_key_down(VK_MENU)
    }

    /// CI:1026 isShiftSide
    fn is_shift_side(&self, ev: &KeyEvent, side_vk: u32) -> bool {
        if ev.scan_code == LEFT_SHIFT_SCAN_CODE || ev.scan_code == RIGHT_SHIFT_SCAN_CODE {
            return ev.scan_code == if side_vk == VK_LSHIFT { LEFT_SHIFT_SCAN_CODE } else { RIGHT_SHIFT_SCAN_CODE };
        }
        self.is_pressed(side_vk)
    }

    /// CI:1033 getCapslockState
    fn get_capslock_state(&self) -> bool {
        env::get_key_state(VK_CAPITAL) & 0x0001 != 0
    }

    /// CI:1167 updateLangButtons
    fn update_lang_buttons(&mut self) {
        let Some(ctx) = self.ctx.as_ref() else { return };
        let lang_mode = ctx.get_chi_eng_mode();
        let shape_mode = ctx.get_shape_mode();
        let lang_changed = lang_mode != self.lang_mode || self.update_switch_lang_icon;
        let shape_changed = shape_mode != self.shape_mode;
        self.update_switch_lang_icon = false;
        self.lang_mode = lang_mode;
        self.shape_mode = shape_mode;
        if lang_changed && self.has_lang_buttons {
            let icon = self.lang_icon_path();
            self.ts.change_button("switch-lang", obj(vec![("icon", json!(icon))]));
        }
        if shape_changed && self.has_lang_buttons {
            let icon = self.icon(if shape_mode == FULLSHAPE_MODE { "full.ico" } else { "half.ico" });
            self.ts.change_button("switch-shape", obj(vec![("icon", json!(icon))]));
        }
        if (lang_changed || shape_changed) && self.client.is_windows8_above {
            self.update_mode_icon(None);
        }
    }

    /// CI:1191 toggleLanguageMode
    fn toggle_language_mode(&mut self) {
        let Some(ctx) = self.ctx.as_mut() else { return };
        let new_mode = if ctx.get_chi_eng_mode() == CHINESE_MODE { ENGLISH_MODE } else { CHINESE_MODE };
        ctx.set_chi_eng_mode(new_mode as i32);
        if ctx.bopomofo_check() {
            ctx.clean_bopomofo_buf();
        }
        if self.ts.show_candidates && self.ts.candidate_list.is_empty() {
            self.composition_sync_pending = true;
        }
        self.update_lang_buttons();
    }

    /// CI:1210 syncComposition
    fn sync_composition(&mut self) {
        self.composition_sync_pending = false;
        let Some(ctx) = self.ctx.as_ref() else { return };
        let comp_str = if ctx.buffer_check() { ctx.buffer_string() } else { String::new() };
        let cursor = ctx.cursor_current();
        let visible = split_trailing_bopomofo(&comp_str).0;
        if self.ts.candidate_list.is_empty() {
            self.ts.set_show_candidates(false);
            self.ts.set_candidate_cursor(0);
        }
        self.ts.set_composition_string(&visible);
        self.ts.set_composition_cursor(cursor.min(visible.chars().count() as i64));
    }

    /// CI:1225 toggleShapeMode
    fn toggle_shape_mode(&mut self) {
        let Some(ctx) = self.ctx.as_mut() else { return };
        let new_mode = if ctx.get_shape_mode() == HALFSHAPE_MODE { FULLSHAPE_MODE } else { HALFSHAPE_MODE };
        ctx.set_shape_mode(new_mode as i32);
        self.update_lang_buttons();
    }
}

impl Service for ChewingService {
    fn ts(&mut self) -> &mut TextService {
        &mut self.ts
    }

    /// CI:195 checkConfigChange
    fn check_config_change(&mut self) -> Result<(), String> {
        with_cfg_mut(|c| c.update());
        if self.ctx.is_none() {
            return Ok(());
        }
        let version = self.config_version;
        if with_cfg(|c| c.is_full_reload_needed(&version)) {
            if !self.ts.is_composing() {
                self.rebuild_chewing_context()?;
            }
        } else if with_cfg(|c| c.is_config_changed(&version)) {
            self.apply_config()?;
        }
        Ok(())
    }

    /// CI:386 onActivate
    fn on_activate(&mut self) -> Result<(), String> {
        self.init_chewing_context()?;
        self.ts.add_preserved_key(VK_SPACE, TF_MOD_SHIFT, SHIFT_SPACE_GUID);
        if self.client.is_windows8_above {
            let open = !cfg_truthy("disableOnStartup");
            self.ts.set_keyboard_open(open);
        }
        if self.ts.keyboard_open {
            self.add_lang_buttons();
        }
        if self.client.is_windows8_above {
            let (icon, tooltip) = self.mode_icon_info();
            self.ts.add_button(
                "windows-mode-icon",
                obj(vec![("icon", json!(icon)), ("tooltip", json!(tooltip)), ("commandId", json!(ID_MODE_ICON))]),
            );
        }
        Ok(())
    }

    /// CI:482 onDeactivate
    fn on_deactivate(&mut self) -> Result<(), String> {
        self.close_chewing_context();
        self.last_key_event = None;
        self.last_lang_mode = None;
        self.last_shape_mode = None;
        self.remove_lang_buttons();
        if self.client.is_windows8_above {
            self.ts.remove_button("windows-mode-icon");
        }
        Ok(())
    }

    /// CI:521 filterKeyDown
    fn filter_key_down(&mut self, ev: &KeyEvent) -> Result<Value, String> {
        self.last_key_event = Some(ev.clone());
        if self.last_key_down_time == 0.0 {
            self.last_key_down_time = env::time();
        }
        if self.ctx.is_none() {
            return Ok(json!(false));
        }
        if self.ts.is_composing() {
            if ev.is_printable_char() && (ev.is_key_down(VK_CONTROL) || ev.is_key_down(VK_MENU)) {
                return Ok(json!(self.is_ime_ctrl_key(ev)));
            }
            return Ok(json!(true));
        }
        if ev.is_printable_char() && ev.char_code > 0x7E {
            return Ok(json!(false));
        }
        if ev.is_key_down(VK_MENU) {
            return Ok(json!(false));
        }
        if ev.is_key_down(VK_CONTROL) {
            return Ok(json!(cfg_truthy("easySymbolsWithCtrl") && ev.is_printable_char() && self.lang_mode == CHINESE_MODE));
        }
        if ev.is_key_down(VK_SHIFT) && cfg_truthy("easySymbolsWithShift") && ev.is_printable_char() && self.lang_mode == CHINESE_MODE {
            return Ok(json!(true));
        }
        if ev.is_key_toggled(VK_NUMLOCK) && ev.key_code >= VK_NUMPAD0 && ev.key_code <= VK_DIVIDE {
            return Ok(json!(false));
        }
        if self.shape_mode == FULLSHAPE_MODE {
            return Ok(json!(ev.is_printable_char() || ev.key_code == VK_SPACE));
        }
        if self.lang_mode == ENGLISH_MODE {
            return Ok(json!(false));
        }
        if cfg_truthy("enableCapsLock") && ev.is_key_toggled(VK_CAPITAL) {
            let alpha = ev.is_char() && char::from_u32(ev.char_code).map(py_isalpha).unwrap_or(false);
            return Ok(json!(alpha));
        }
        if ev.is_printable_char() && ev.key_code != VK_SPACE {
            return Ok(json!(true));
        }
        Ok(json!(false))
    }

    /// CI:675 onKeyDown
    fn on_key_down(&mut self, ev: &KeyEvent) -> Result<Value, String> {
        if self.ctx.is_none() {
            return Ok(json!(false));
        }
        if self.composition_sync_pending {
            self.sync_composition();
            if !self.ts.is_composing() && !crate::cinbase::pyutil::py_truthy(&self.filter_key_down(ev)?) {
                return Ok(json!(false));
            }
        }
        let mut char_code = ev.char_code as i32;
        let key_code = ev.key_code;
        let ch = char::from_u32(ev.char_code).unwrap_or('\u{FFFD}');

        let mut temporary_english_mode = false;
        let old_lang_mode = self.ctx().get_chi_eng_mode();
        let mut ignore_key = false;
        let mut key_handled = false;
        let has_candidates = self.ts.show_candidates && !self.ts.candidate_list.is_empty();

        // CI:700 easy symbol input
        if cfg_truthy("easySymbolsWithShift") && ev.is_key_down(VK_SHIFT) {
            self.ctx().set_easy_symbol_input(1);
        } else if cfg_truthy("easySymbolsWithCtrl") && ev.is_key_down(VK_CONTROL) {
            self.ctx().set_easy_symbol_input(1);
        } else {
            self.ctx().set_easy_symbol_input(0);
        }

        if ev.is_printable_char() {
            // CI:708
            key_handled = true;
            let mut invert_case = false;
            if self.lang_mode == CHINESE_MODE {
                if cfg_truthy("enableCapsLock") && ev.is_key_toggled(VK_CAPITAL) {
                    temporary_english_mode = true;
                    invert_case = true;
                }
                if !cfg_truthy("fullShapeSymbols")
                    && ev.is_symbols()
                    && !layout_bopomofo_symbol_keys(cfg_int_raw_layout()).contains(ch)
                {
                    temporary_english_mode = true;
                }
                if ev.is_key_down(VK_SHIFT) {
                    if py_isalpha(ch) {
                        if !cfg_truthy("easySymbolsWithShift") {
                            temporary_english_mode = true;
                            if !cfg_truthy("upperCaseWithShift") {
                                invert_case = true;
                            }
                        }
                    } else if !cfg_truthy("fullShapeSymbolsWithShift") {
                        temporary_english_mode = true;
                    }
                }
            }

            if self.lang_mode == ENGLISH_MODE {
                // CI:741
                self.ctx().handle_default(char_code);
            } else if temporary_english_mode {
                self.ctx().set_chi_eng_mode(ENGLISH_MODE as i32);
                if invert_case {
                    char_code = py_ord(&if py_isupper(ch) { py_lower(ch) } else { py_upper(ch) })?;
                }
                self.ctx().handle_default(char_code);
            } else if py_isalpha(ch) {
                // CI:750
                if self.ctx().get_easy_symbol_input() != 0 {
                    char_code = py_ord(&py_upper(ch))?;
                } else {
                    char_code = py_ord(&py_lower(ch))?;
                }
                self.ctx().handle_default(char_code);
            } else if ev.key_code == VK_SPACE {
                // CI:758
                if has_candidates && cfg_int("spaceKeyCandidatesAction") == 1 {
                    let mut cand_cursor = self.ts.candidate_cursor;
                    let cand_count = self.ts.candidate_list.len() as i64;
                    if cand_cursor + 1 < cand_count {
                        cand_cursor += 1;
                    } else {
                        cand_cursor = 0;
                        if self.ctx().cand_has_next() {
                            self.ctx().handle_page_down();
                        } else {
                            self.ctx().handle_down();
                        }
                    }
                    self.ts.set_candidate_cursor(cand_cursor);
                } else if has_candidates && cfg_int("spaceKeyAction") == 0 {
                    self.ctx().handle_space();
                } else if self.ts.is_composing() {
                    self.ctx().handle_space();
                } else {
                    self.ctx().handle_default(char_code);
                }
            } else if ev.is_key_down(VK_CONTROL) && py_isdigit(ch) {
                self.ctx().handle_ctrl_num(char_code);
            } else if ev.is_key_toggled(VK_NUMLOCK) && key_code >= VK_NUMPAD0 && key_code <= VK_DIVIDE {
                self.ctx().handle_numlock(char_code);
            } else {
                self.ctx().handle_default(char_code);
            }
        } else {
            // CI:796 不可見字元
            if has_candidates {
                let cand_count = self.ts.candidate_list.len() as i64;
                let mut cand_cursor = self.ts.candidate_cursor.max(0).min(cand_count - 1);

                if ev.is_key_down(VK_CONTROL) && (key_code == VK_DELETE || key_code == VK_NEXT || key_code == VK_PRIOR) {
                    let target = self.ts.candidate_list[cand_cursor as usize].clone();
                    self.maintain_user_phrase(key_code, &target);
                    ignore_key = true;
                    key_handled = true;
                }
                if key_code == VK_HOME {
                    cand_cursor = 0;
                    ignore_key = true;
                    key_handled = true;
                } else if key_code == VK_END {
                    cand_cursor = cand_count - 1;
                    ignore_key = true;
                    key_handled = true;
                }
                if cfg_int("leftRightAction") == 0 {
                    if key_code == VK_LEFT {
                        if cand_cursor > 0 {
                            cand_cursor -= 1;
                            ignore_key = true;
                            key_handled = true;
                        } else {
                            cand_cursor = cand_count - 1;
                        }
                    } else if key_code == VK_RIGHT {
                        if cand_cursor + 1 < cand_count {
                            cand_cursor += 1;
                            ignore_key = true;
                            key_handled = true;
                        } else {
                            cand_cursor = 0;
                        }
                    }
                }
                // CI:834
                if cfg_int("upDownAction") == 0 && (key_code == VK_UP || key_code == VK_DOWN) {
                    let per_row = self.candidates_per_visible_row()?;
                    if key_code == VK_UP {
                        if cand_cursor >= per_row {
                            cand_cursor -= per_row;
                            ignore_key = true;
                            key_handled = true;
                        }
                    } else if cand_cursor.div_euclid(per_row) < (cand_count - 1).div_euclid(per_row) {
                        cand_cursor = (cand_cursor + per_row).min(cand_count - 1);
                        ignore_key = true;
                        key_handled = true;
                    }
                }
                // CI:847
                if cfg_int("upDownAction") == 1 {
                    if key_code == VK_UP {
                        self.ctx().handle_page_up();
                        key_handled = true;
                    } else if key_code == VK_DOWN && self.ctx().cand_has_next() {
                        self.ctx().handle_page_down();
                        key_handled = true;
                    }
                }
                // CI:857
                if key_code == VK_RETURN {
                    let sel_keys: Vec<char> = with_cfg(|c| c.get_sel_keys())?.chars().collect();
                    let sel_key = *sel_keys.get(cand_cursor as usize).ok_or("IndexError: string index out of range")?;
                    self.ctx().handle_default(sel_key as i32);
                    key_handled = true;
                }
                self.ts.set_candidate_cursor(cand_cursor);
            }
            // CI:867
            if !key_handled {
                if let Some(name) = key_name(key_code) {
                    self.ctx().handle_named(name);
                    key_handled = true;
                } else {
                    ignore_key = true;
                }
            }
        }

        // CI:880
        if key_handled && self.ctx().keystroke_check_ignore() {
            ignore_key = true;
        }

        if !ignore_key {
            // CI:884
            let mut candidates = Vec::new();
            if self.ctx().cand_total_choice() > 0 {
                self.ctx().cand_enumerate();
                let per_page = self.ctx().cand_choice_per_page();
                for _ in 0..per_page.max(0) {
                    if !self.ctx().cand_has_next() {
                        break;
                    }
                    let cand = self.ctx().cand_string();
                    candidates.push(cand);
                }
                if candidates != self.ts.candidate_list {
                    let n = candidates.len() as i64;
                    self.ts.set_candidate_list(candidates);
                    self.ts.set_show_candidates(true);
                    if key_code == VK_LEFT && cfg_int("leftRightAction") == 0 {
                        self.ts.set_candidate_cursor(n - 1);
                    } else {
                        self.ts.set_candidate_cursor(0);
                    }
                }
                if !self.ts.show_candidates {
                    self.ts.set_show_candidates(true);
                }
            } else if self.ts.show_candidates {
                self.ts.set_show_candidates(false);
                self.ts.set_candidate_list(vec![]);
            }

            // CI:916
            if self.ctx().commit_check() {
                let commit = self.ctx().commit_string();
                self.ts.set_commit_string(&commit);
            }
            let comp_str = if self.ctx().buffer_check() { self.ctx().buffer_string() } else { String::new() };
            let bopomofo_str = if self.ctx().bopomofo_check() { self.ctx().bopomofo_string() } else { String::new() };
            let composition_cursor = self.ctx().cursor_current();

            // CI:934
            let (visible_comp_str, comp_root_str) = split_trailing_bopomofo(&comp_str);
            let root_str = if !bopomofo_str.is_empty() { bopomofo_str } else { comp_root_str };
            if !root_str.is_empty() {
                self.ts.set_composition_string(&visible_comp_str);
                if visible_comp_str.is_empty() {
                    self.ts.current_reply.insert("compositionString".into(), json!("\u{200b}"));
                    self.ts.set_composition_cursor(0);
                } else {
                    self.ts.set_composition_cursor(composition_cursor.min(visible_comp_str.chars().count() as i64));
                }
                self.update_candidate_header(&root_str, true);
            } else {
                self.ts.set_composition_string(&visible_comp_str);
                self.ts.set_composition_cursor(composition_cursor);
            }

            // CI:954
            if self.ctx().aux_check() {
                let message = self.ctx().aux_string();
                self.ts.show_message(&message, 2);
            }
        }

        // CI:961
        if temporary_english_mode {
            self.ctx().set_chi_eng_mode(old_lang_mode as i32);
        }
        self.update_lang_buttons();

        // CI:967
        if self.ts.current_reply.contains_key("candidateList") || self.ts.current_reply.contains_key("showCandidates") {
            let show = self.ts.current_reply.get("showCandidates").map(crate::cinbase::pyutil::py_truthy).unwrap_or(true);
            if !self.ts.current_reply.contains_key("candidateHeader") && show {
                self.update_candidate_header("", false);
            }
            self.customize_candidate_ui(false);
        }
        Ok(json!(key_handled))
    }

    /// CI:977 filterKeyUp
    fn filter_key_up(&mut self, ev: &KeyEvent) -> Result<Value, String> {
        let last_is_shift = self.last_key_event.as_ref().map(|l| l.key_code == VK_SHIFT && !Self::is_modifier_held(l)).unwrap_or(false);
        if last_is_shift && ev.key_code == VK_SHIFT && !Self::is_modifier_held(ev) {
            if cfg_truthy("shiftMoveCursor") {
                return Ok(json!(true));
            }
            if cfg_truthy("switchLangWithShift") {
                let which = cfg_int("switchLangWithWhichShift");
                if which == SWITCH_LANG_WITH_BOTH_SHIFT {
                } else if which == SWITCH_LANG_WITH_LEFT_SHIFT && !self.is_shift_side(ev, VK_LSHIFT) {
                    self.last_key_down_time = 0.0;
                    return Ok(json!(false));
                } else if which == SWITCH_LANG_WITH_RIGHT_SHIFT && !self.is_shift_side(ev, VK_RSHIFT) {
                    self.last_key_down_time = 0.0;
                    return Ok(json!(false));
                }
                let pressed_duration = env::time() - self.last_key_down_time;
                if pressed_duration < 0.5 {
                    self.toggle_language_mode();
                    if self.composition_sync_pending {
                        return Ok(json!(true));
                    }
                }
            }
        }
        // CI:1006
        if cfg_truthy("enableCapsLock") && self.last_key_event.is_some() && self.is_pressed(VK_CAPITAL) {
            self.update_switch_lang_icon = true;
            self.update_lang_buttons();
        }
        self.last_key_down_time = 0.0;
        Ok(json!(false))
    }

    /// CI:1039 onKeyUp
    fn on_key_up(&mut self, _ev: &KeyEvent) -> Result<Option<Value>, String> {
        if self.ctx.is_none() {
            return Ok(Some(json!(false)));
        }
        if self.composition_sync_pending {
            self.sync_composition();
            self.last_key_down_time = 0.0;
            return Ok(Some(json!(true)));
        }
        let pressed_duration = env::time() - self.last_key_down_time;
        if pressed_duration < 0.5 && self.ts.is_composing() && !self.ctx().bopomofo_check() {
            if let Some(last) = self.last_key_event.clone() {
                let comp_len = self.ts.composition_string.chars().count() as i64;
                if last.is_key_down(VK_RSHIFT) && self.ts.composition_cursor < comp_len {
                    self.ctx().handle_right();
                    let c = self.ctx().cursor_current();
                    self.ts.set_composition_cursor(c);
                }
                if last.is_key_down(VK_LSHIFT) && self.ts.composition_cursor > 0 {
                    self.ctx().handle_left();
                    let c = self.ctx().cursor_current();
                    self.ts.set_composition_cursor(c);
                }
            }
            self.last_key_down_time = 0.0;
            return Ok(Some(json!(true)));
        }
        Ok(Some(json!(false)))
    }

    /// CI:1063 onPreservedKey
    fn on_preserved_key(&mut self, guid: &str) -> Result<Value, String> {
        self.last_key_event = None;
        if guid == SHIFT_SPACE_GUID {
            if !cfg_truthy("enableShiftSpace") || self.ctx.is_none() {
                return Ok(json!(false));
            }
            self.toggle_shape_mode();
            return Ok(json!(true));
        }
        Ok(json!(false))
    }

    /// CI:1076 onCommand
    fn on_command(&mut self, id: &Value, kind: &Value) -> Result<(), String> {
        use crate::cinbase::pyutil::py_eq_int;
        let is = |n: i64| py_eq_int(id, n);
        let left_or_menu = py_eq_int(kind, COMMAND_LEFT_CLICK) || py_eq_int(kind, COMMAND_MENU);
        if is(ID_SWITCH_LANG) && left_or_menu {
            self.toggle_language_mode();
        } else if is(ID_SWITCH_SHAPE) && left_or_menu {
            self.toggle_shape_mode();
        } else if is(ID_SETTINGS) || is(ID_USER_PHRASE_EDITOR) {
            // CI:1085 ran python.exe "<config_tool.py>" <config_tool|user_phrase_editor>
            // (SW_HIDE, in the chewing folder); installed, it is wime-config.exe
            // beside this backend, with the Start-menu shortcuts' arguments
            let tool = if is(ID_USER_PHRASE_EDITOR) { "user_phrase_editor" } else { "config" };
            let (exe, params, dir) = paths::config_tool_command(tool, "chewing");
            env::shell_execute_in(&exe, &params, &dir, 0);
        } else if is(ID_MODE_ICON) && py_eq_int(kind, COMMAND_LEFT_CLICK) {
            if !self.ts.keyboard_open {
                self.ts.set_keyboard_open(true);
            } else {
                self.toggle_language_mode();
            }
        } else if is(ID_WEBSITE) {
            env::startfile("https://chewing.im/");
        } else if is(ID_GROUP) {
            env::startfile("https://groups.google.com/g/chewing");
        } else if is(ID_BUGREPORT) {
            env::startfile("https://github.com/omni624562/WIME/issues");
        } else if is(ID_DICT_BUGREPORT) {
            env::startfile("https://codeberg.org/chewing/libchewing/issues");
        } else if is(ID_MOEDICT) {
            env::startfile("https://www.moedict.tw/");
        } else if is(ID_DICT) {
            env::startfile("https://dict.revised.moe.edu.tw/");
        } else if is(ID_SIMPDICT) {
            env::startfile("https://dict.concised.moe.edu.tw/");
        } else if is(ID_LITTLEDICT) {
            env::startfile("https://dict.mini.moe.edu.tw/");
        } else if is(ID_PROVERBDICT) {
            env::startfile("https://dict.idioms.moe.edu.tw/");
        }
        Ok(())
    }

    /// CI:1129 onMenu
    fn on_menu(&mut self, button_id: &Value) -> Result<Option<Value>, String> {
        if button_id != "settings" && button_id != "windows-mode-icon" {
            return Ok(None);
        }
        let can_switch = self.ctx.is_some();
        let lang_text = if cfg_truthy("switchLangWithShift") { "中文模式（Shift）" } else { "中文模式" };
        let shape_text = if cfg_truthy("enableShiftSpace") { "全形（Shift+空白鍵）" } else { "全形" };
        Ok(Some(json!([
            {"text": lang_text, "id": ID_SWITCH_LANG, "checked": self.lang_mode == CHINESE_MODE, "enabled": can_switch},
            {"text": shape_text, "id": ID_SWITCH_SHAPE, "checked": self.shape_mode == FULLSHAPE_MODE, "enabled": can_switch},
            {},
            {"text": "新酷音官方網站 (&W)", "id": ID_WEBSITE},
            {"text": "新酷音線上討論區 (&G)", "id": ID_GROUP},
            {},
            {"text": "軟體本身的建議及錯誤回報 (&B)", "id": ID_BUGREPORT},
            {"text": "注音及選字選詞錯誤回報 (&P)", "id": ID_DICT_BUGREPORT},
            {},
            {"text": "編輯使用者詞庫 (&E)", "id": ID_USER_PHRASE_EDITOR},
            {"text": "設定新酷音輸入法 (&C)", "id": ID_SETTINGS},
            {},
            {"text": "網路辭典 (&D)", "submenu": [
                {"text": "萌典 (moedict)", "id": ID_MOEDICT},
                {},
                {"text": "教育部國語辭典", "id": ID_DICT},
                {"text": "教育部國語辭典簡編本", "id": ID_SIMPDICT},
                {"text": "教育部國語小字典", "id": ID_LITTLEDICT},
                {"text": "教育部成語典", "id": ID_PROVERBDICT},
            ]}
        ])))
    }

    /// CI:1236 onKeyboardStatusChanged
    fn on_keyboard_status_changed(&mut self, opened: bool) -> Result<(), String> {
        self.ts.keyboard_open = opened;
        if opened {
            self.init_chewing_context()?;
            self.add_lang_buttons();
        } else {
            if self.ts.show_candidates {
                self.ts.set_show_candidates(false);
            }
            self.last_lang_mode = Some(self.lang_mode);
            self.last_shape_mode = Some(self.shape_mode);
            self.close_chewing_context();
            self.remove_lang_buttons();
        }
        if self.client.is_windows8_above {
            self.update_mode_icon(Some(true));
        }
        self.update_lang_buttons();
        Ok(())
    }

    /// CI:1265 onCompositionTerminated
    fn on_composition_terminated(&mut self, forced: bool) -> Result<(), String> {
        self.ts.base_on_composition_terminated();
        self.composition_sync_pending = false;
        if forced {
            let show = self.ts.show_candidates;
            if let Some(ctx) = self.ctx.as_mut() {
                if show {
                    ctx.cand_close();
                    self.ts.set_show_candidates(false);
                }
                if ctx.bopomofo_check() {
                    ctx.clean_bopomofo_buf();
                }
                if ctx.buffer_check() {
                    ctx.commit_preedit_buf();
                }
            }
        }
        Ok(())
    }

    /// CI:1280 onKillFocus
    fn on_kill_focus(&mut self) -> Result<(), String> {
        self.composition_sync_pending = false;
        let was_showing = self.ts.show_candidates;
        if let Some(ctx) = self.ctx.as_mut() {
            if was_showing {
                ctx.cand_close();
            }
            if ctx.bopomofo_check() {
                ctx.clean_bopomofo_buf();
            }
            if ctx.buffer_check() {
                ctx.clean_preedit_buf();
            }
        }
        self.ts.base_on_kill_focus();
        self.ts.set_show_candidates(false);
        self.ts.set_candidate_list(vec![]);
        self.ts.set_candidate_cursor(0);
        Ok(())
    }
}

/// cfg.keyboardLayout as the dict key of LAYOUT_BOPOMOFO_SYMBOL_KEYS.get()
/// (True == 1 as a dict key, like Python)
fn cfg_int_raw_layout() -> i64 {
    cfg_int("keyboardLayout")
}

#[cfg(test)]
mod tests;
