//! Port of python/cinbase (CinBase, the shared engine of the table-based input
//! methods), python/cinbase/ime_base.py (CinBaseTextService) and
//! python/input_methods/chedayi/chedayi_ime.py (大易).
//!
//! Layout (mirrors the Python, so the remaining parts can be translated line
//! by line):
//! - `CbTs` is Python's `cbTS`: the text service instance with every
//!   attribute CinBase sets on it (snake_case of the Python name) plus the
//!   `TextService` reply builder in `ts`. Python's `CinBase.xxx(cbTS, ...)`
//!   methods are `impl CbTs` methods named `xxx` in snake_case; each starts with
//!   a `// CB:<line>` comment pointing at python/cinbase/__init__.py
//!   (`IB:` = ime_base.py, `DY:` = chedayi_ime.py).
//! - The process-wide singletons (Python module globals) are thread-locals:
//!   the per-IME `CinTable` / `RCinTable` / `HCinTable` (`SharedTables`), the
//!   shared `PhraseData`, and `CinBase.emoji`. The server is single-threaded.
//!   Python loads tables in background threads; here (as in the reference
//!   backend of tests/diffharness) they load synchronously.
//! - Files: `events.rs` (requests other than onKeyDown, CB:275-571 and
//!   CB:2532-2918), `keydown.rs` / `keydown_core.rs` / `keydown_modes.rs` (onKeyDown), `helpers.rs` (CB:2920-3609),
//!   `context.rs` (config / tables, CB:3615-4123), `selkeys.rs`, `menu.rs`,
//!   `compositionbuffer.rs`, `pyutil.rs` (Python string semantics).
//!
//! A Python exception is `Err(String)`: the request is answered
//! {"success": false} and (like Python) whatever was already written to the
//! reply stays in `ts.current_reply` for the next request.

pub mod compositionbuffer;
pub mod context;
pub mod events;
pub mod helpers;
pub mod keydown;
pub mod keydown_core;
pub mod keydown_modes;
pub mod menu;
pub mod pyutil;
pub mod selkeys;
#[cfg(test)]
mod tests;

use crate::cin::Cin;
use crate::config::{CinBaseConfig, ConfigVersion};
use crate::data::{DSymbols, Emoji, ExtendTable, FLangs, FSymbols, MSymbols, Phrase, Swkb, Symbols, UserPhrase};
use crate::env;
use crate::hcin::HCin;
use crate::keycodes::VK_CAPITAL;
use crate::rcin::RCin;
use crate::textservice::{KeyEvent, Service, TextService};
use crate::ClientInfo;
use indexmap::IndexMap;
use serde_json::{json, Map, Value};
use std::cell::{Ref, RefCell, RefMut};
use std::collections::HashMap;
use std::path::PathBuf;
use std::rc::Rc;

// CB:49 ---------------------------------------------------------------------
pub const CHINESE_MODE: i64 = 1;
pub const ENGLISH_MODE: i64 = 0;
pub const FULLSHAPE_MODE: i64 = 1;
pub const HALFSHAPE_MODE: i64 = 0;

/// seconds after an auto-commit in which the next Space is swallowed
pub const AUTO_COMMIT_SPACE_GRACE: f64 = 1.0;

pub const SHIFT_SPACE_GUID: &str = "{f1dae0fb-8091-44a7-8a0c-3082a1515447}";
pub const TF_MOD_SHIFT: u32 = 0x0004;

// menu / language bar command ids
pub const ID_SWITCH_LANG: i64 = 1;
pub const ID_SWITCH_SHAPE: i64 = 2;
pub const ID_SETTINGS: i64 = 3;
pub const ID_MODE_ICON: i64 = 4;
pub const ID_WEBSITE: i64 = 5;
pub const ID_BUGREPORT: i64 = 6;
pub const ID_MOEDICT: i64 = 8;
pub const ID_DICT: i64 = 9;
pub const ID_SIMPDICT: i64 = 10;
pub const ID_LITTLEDICT: i64 = 11;
pub const ID_PROVERBDICT: i64 = 12;
pub const ID_OUTPUT_SIMP_CHINESE: i64 = 13;

/// IME_SHORT_NAMES: the name in the mode icon tooltip
pub fn ime_short_name(ime_dir_name: &str) -> &'static str {
    match ime_dir_name {
        "chedayi" => "大易",
        "checj" => "酷倉",
        "chearray" => "行列",
        "cheliu" => "蝦米",
        "cheez" => "輕鬆",
        "chephonetic" => "注音",
        "chepinyin" => "拼音",
        "chesimplex" => "速成",
        _ => "",
    }
}

pub const LEFT_SHIFT_SCAN_CODE: u32 = 0x2A;
pub const RIGHT_SHIFT_SCAN_CODE: u32 = 0x36;

/// seconds before retrying a table that failed to load
pub const TABLE_RETRY_INTERVAL: f64 = 5.0;

/// CB:139 CinBase.imeNameList
pub const IME_NAME_LIST: &[&str] = &["checj", "chephonetic", "chearray", "chedayi", "cheez", "chepinyin", "chesimplex", "cheliu"];
/// CB:140 CinBase.hcinFileList
pub const HCIN_FILE_LIST: &[&str] = &["thphonetic.json", "CnsPhonetic.json", "bpmf.json"];
/// CB:138 CinBase.emojimenulist
pub const EMOJI_MENU_LIST: &[&str] = &["表情與手勢", "圖形符號", "其他符號", "雜錦符號", "交通運輸", "調色盤"];

/// CB:94 tableIndex(value, count): bad / negative / out of range -> 0.
/// (Settings are typed after normalize, so the bool/type checks cannot fail.)
pub fn table_index(value: i64, count: usize) -> i64 {
    if value < 0 || value >= count as i64 {
        return 0;
    }
    value
}

// ---------------------------------------------------------------------------
// process-wide singletons

/// DY:68 CinTable
#[derive(Default)]
pub struct CinTableState {
    pub cin: Option<Rc<RefCell<Cin>>>,
    pub cur_cin_type: Option<i64>,
    pub user_extend_table: Option<bool>,
    pub priority_extend_table: Option<bool>,
    pub ignore_private_use_area: Option<bool>,
    pub loading: bool,
    /// getattr(table, 'lastLoadFailure', 0.0)
    pub last_load_failure: f64,
    /// getattr(table, 'loadFailed', False)
    pub load_failed: bool,
}

/// DY:79 RCinTable
#[derive(Default)]
pub struct RCinTableState {
    pub cin: Option<RCin>,
    pub cur_cin_type: Option<i64>,
    pub loading: bool,
    pub last_load_failure: f64,
    /// getattr(table, 'fileNotExist', <default>): None when never set
    pub file_not_exist: Option<bool>,
}

/// DY:86 HCinTable
#[derive(Default)]
pub struct HCinTableState {
    pub cin: Option<HCin>,
    pub cur_cin_type: Option<i64>,
    pub loading: bool,
    pub last_load_failure: f64,
    pub file_not_exist: Option<bool>,
}

/// The three table singletons of one input method module.
#[derive(Clone, Default)]
pub struct SharedTables {
    pub cin: Rc<RefCell<CinTableState>>,
    pub rcin: Rc<RefCell<RCinTableState>>,
    pub hcin: Rc<RefCell<HCinTableState>>,
}

/// CB:3944 PhraseData (shared by every cinbase input method)
#[derive(Default)]
pub struct PhraseDataState {
    pub phrase: Option<Phrase>,
    pub loading: bool,
}

thread_local! {
    static TABLES: RefCell<HashMap<String, SharedTables>> = RefCell::new(HashMap::new());
    static PHRASE_DATA: Rc<RefCell<PhraseDataState>> = Rc::new(RefCell::new(PhraseDataState::default()));
    static EMOJI: RefCell<Option<Rc<Emoji>>> = const { RefCell::new(None) };
}

/// The CinTable / RCinTable / HCinTable of an input method module.
pub fn shared_tables(ime_dir_name: &str) -> SharedTables {
    TABLES.with(|t| t.borrow_mut().entry(ime_dir_name.to_string()).or_default().clone())
}

pub fn phrase_data() -> Rc<RefCell<PhraseDataState>> {
    PHRASE_DATA.with(|p| p.clone())
}

/// CB:133 CinBase.emoji, read from data/emoji.json once (Python: at import;
/// a failure there kills the backend, here it fails the request).
pub fn emoji() -> Result<Rc<Emoji>, String> {
    if let Some(e) = EMOJI.with(|e| e.borrow().clone()) {
        return Ok(e);
    }
    let e = Rc::new(Emoji::from_file(&crate::paths::data_dir().join("emoji.json"))?);
    EMOJI.with(|slot| *slot.borrow_mut() = Some(e.clone()));
    Ok(e)
}

/// CB:102 tableLoadRecentlyFailed(table)
pub fn table_load_recently_failed(last_load_failure: f64) -> bool {
    env::time() - last_load_failure < TABLE_RETRY_INTERVAL
}

// ---------------------------------------------------------------------------

/// Python's cbTS: one text service instance (one client) of a cinbase IME.
pub struct CbTs {
    pub ts: TextService,
    pub client: ClientInfo,

    // ime_base.py
    pub ime_dir_name: String,
    pub max_char_length: i64,
    pub cin_file_list: Vec<String>,
    pub cfg: CinBaseConfig,
    pub config_version: ConfigVersion,
    pub jsondir: PathBuf,
    pub cindir: PathBuf,
    /// _cin_table / _rcin_table / _hcin_table
    pub tables: SharedTables,
    /// cbTS.cin (shared with CinTable.cin); None = missing or None
    pub cin: Option<Rc<RefCell<Cin>>>,
    /// class attribute compositionChar = ''
    pub composition_char: String,

    // initTextService (CB:143)
    /// candselKeys: the selection keys last sent (selkeys.py)
    pub cand_sel_keys: String,
    pub keyboard_layout: i64,
    pub sel_keys: String,
    pub lang_mode: i64,
    pub shape_mode: i64,
    pub switch_page_with_space: bool,
    pub play_sound_when_non_cand: bool,
    pub direct_show_cand: bool,
    pub auto_commit_single_candidate: bool,
    pub direct_commit_symbol: bool,
    pub direct_commit_symbol_list: Vec<String>,
    pub bracket_symbol_list: Vec<String>,
    pub ignore_private_use_area: bool,
    pub direct_out_m_symbols: bool,
    pub full_shape_symbols: bool,
    pub direct_out_f_symbols: bool,
    pub easy_symbols_with_shift: bool,
    pub show_phrase: bool,
    pub sort_by_phrase: bool,
    pub intelligent_select: bool,
    pub intelligent_select_recent: bool,
    pub intelligent_select_context: bool,
    pub hide_composition: bool,
    pub hide_composition_label: String,
    pub ime_display_name: String,
    pub composition_buffer_mode: bool,
    pub auto_move_cursor_in_brackets: bool,
    pub ime_reverse_lookup: bool,
    pub homophone_query: bool,
    pub user_extend_table: bool,
    pub re_load_table: bool,
    pub priority_extend_table: bool,

    pub sel_dayi_symbol_char_type: i64,
    pub last_key_down_code: u32,
    pub last_key_down_time: f64,

    pub menucandidates: Vec<String>,
    pub smenucandidates: Vec<String>,
    pub wildcardcandidates: Vec<String>,
    pub wildcardpagecandidates: Vec<Vec<String>>,
    pub wildcardcomposition_char: String,
    pub current_cand_page: i64,

    pub emojitype: i64,
    pub prevmenutypelist: Vec<String>,
    pub prevmenucandlist: Vec<i64>,

    pub composition_buffer_string: String,
    pub composition_buffer_cursor: i64,
    pub composition_buffer_type: String,
    /// {index: [type, keys]}
    pub composition_buffer_char: IndexMap<i64, (String, String)>,
    pub composition_buffer_menu_item: String,
    pub tempengcandidates: Vec<String>,
    pub key_used_state: bool,
    pub selcandmode: bool,

    pub init_cin_base_state: bool,
    pub showmenu: bool,
    pub switchmenu: bool,
    pub closemenu: bool,
    pub temp_english_mode: bool,
    pub multifunctionmode: bool,
    pub menumode: bool,
    pub emojimenumode: bool,
    pub menusymbolsmode: bool,
    pub ctrlsymbolsmode: bool,
    pub fullsymbolsmode: bool,
    pub phrasemode: bool,
    pub is_sel_keys_changed: bool,
    pub is_wildcard_chardefs: bool,
    pub is_lang_mode_changed: bool,
    pub is_shape_mode_changed: bool,
    pub shift_space_key_added: bool,
    pub is_show_candidates: bool,
    pub is_show_phrase_candidates: bool,
    pub is_show_message: bool,
    pub can_set_commit_string: bool,
    pub can_set_phrase_commit_string: bool,
    pub can_use_sel_key: bool,
    pub can_use_space_as_page_key: bool,
    pub end_key_list: Vec<String>,
    pub use_end_key: bool,
    pub use_dayi_symbols: bool,
    pub dayisymbolsmode: bool,
    pub auto_show_cand_when_max_char: bool,
    pub last_commit_string: String,
    pub last_composition_char_length: i64,
    pub menutype: i64,
    pub reset_menu_cand: bool,
    pub keep_composition: bool,
    pub keep_type: String,

    pub homophonemode: bool,
    pub homophoneselpinyinmode: bool,
    pub homophone_char: String,
    pub homophone_str: String,
    pub is_homophone_chardefs: bool,
    pub homophonecandidates: Vec<String>,

    pub show_message_on_key_up: bool,
    pub hide_message_on_key_up: bool,
    pub on_key_up_message: String,
    pub re_load_cin_table: bool,
    pub r_cin_file_not_exist: bool,
    pub caps_states: bool,

    pub bopomofolist: Vec<String>,

    // attributes created later (getattr defaults in Python)
    /// getattr(cbTS, 'skipSpaceDeadline', 0.0)
    pub skip_space_deadline: f64,
    /// _lastCandidateUIArgs (None until the first customizeCandidateUI)
    pub last_candidate_ui_args: Option<Map<String, Value>>,
    /// DayiSymbolChar / DayiSymbolString, set by every 大易 onKeyDown ("" before)
    pub dayi_symbol_char: String,
    pub dayi_symbol_string: String,
    /// smenuitems (the toggle attribute names of the 功能開關 page)
    pub smenuitems: Vec<String>,
    /// menupathlist (menu.py)
    pub menupathlist: Vec<String>,

    // applyConfig (CB:3716)
    pub cand_per_row: i64,
    pub cand_per_page: i64,
    pub output_small_letter_with_shift: bool,
    pub support_wildcard: bool,
    pub sel_wildcard_char: String,
    pub cand_max_items: i64,
    pub sel_r_cin_type: i64,
    pub sel_h_cin_type: i64,
    pub sel_cin_type: i64,

    // per-instance data tables (None = attribute deleted / not loaded yet)
    pub swkb: Option<Swkb>,
    pub symbols: Option<Symbols>,
    pub fsymbols: Option<FSymbols>,
    pub flangs: Option<FLangs>,
    pub userphrase: Option<UserPhrase>,
    pub excludephrase: Option<UserPhrase>,
    pub msymbols: Option<MSymbols>,
    pub extendtable: Option<ExtendTable>,
    pub dsymbols: Option<DSymbols>,
}

fn attr_error(name: &str) -> String {
    format!("AttributeError: object has no attribute '{}'", name)
}

impl CbTs {
    fn blank(client: ClientInfo, ime_dir_name: &str, max_char_length: i64, cin_file_list: &[&str], tables: SharedTables) -> CbTs {
        CbTs {
            ts: TextService::default(),
            client,
            ime_dir_name: ime_dir_name.to_string(),
            max_char_length,
            cin_file_list: cin_file_list.iter().map(|s| s.to_string()).collect(),
            cfg: CinBaseConfig::new(),
            config_version: [0.0; 7],
            jsondir: PathBuf::new(),
            cindir: PathBuf::new(),
            tables,
            cin: None,
            composition_char: String::new(),
            cand_sel_keys: String::new(),
            keyboard_layout: 0,
            sel_keys: String::new(),
            lang_mode: -1,
            shape_mode: -1,
            switch_page_with_space: false,
            play_sound_when_non_cand: false,
            direct_show_cand: false,
            auto_commit_single_candidate: false,
            direct_commit_symbol: false,
            direct_commit_symbol_list: Vec::new(),
            bracket_symbol_list: Vec::new(),
            ignore_private_use_area: true,
            direct_out_m_symbols: true,
            full_shape_symbols: false,
            direct_out_f_symbols: false,
            easy_symbols_with_shift: false,
            show_phrase: false,
            sort_by_phrase: false,
            intelligent_select: false,
            intelligent_select_recent: false,
            intelligent_select_context: false,
            hide_composition: false,
            hide_composition_label: String::new(),
            ime_display_name: String::new(),
            composition_buffer_mode: false,
            auto_move_cursor_in_brackets: false,
            ime_reverse_lookup: false,
            homophone_query: false,
            user_extend_table: false,
            re_load_table: false,
            priority_extend_table: false,
            sel_dayi_symbol_char_type: 0,
            last_key_down_code: 0,
            last_key_down_time: 0.0,
            menucandidates: Vec::new(),
            smenucandidates: Vec::new(),
            wildcardcandidates: Vec::new(),
            wildcardpagecandidates: Vec::new(),
            wildcardcomposition_char: String::new(),
            current_cand_page: 0,
            emojitype: 0,
            prevmenutypelist: Vec::new(),
            prevmenucandlist: Vec::new(),
            composition_buffer_string: String::new(),
            composition_buffer_cursor: 0,
            composition_buffer_type: "default".into(),
            composition_buffer_char: IndexMap::new(),
            composition_buffer_menu_item: String::new(),
            tempengcandidates: Vec::new(),
            key_used_state: false,
            selcandmode: false,
            init_cin_base_state: false,
            showmenu: false,
            switchmenu: false,
            closemenu: true,
            temp_english_mode: false,
            multifunctionmode: false,
            menumode: false,
            emojimenumode: false,
            menusymbolsmode: false,
            ctrlsymbolsmode: false,
            fullsymbolsmode: false,
            phrasemode: false,
            is_sel_keys_changed: false,
            is_wildcard_chardefs: false,
            is_lang_mode_changed: false,
            is_shape_mode_changed: false,
            shift_space_key_added: false,
            is_show_candidates: false,
            is_show_phrase_candidates: false,
            is_show_message: false,
            can_set_commit_string: true,
            can_set_phrase_commit_string: false,
            can_use_sel_key: true,
            can_use_space_as_page_key: true,
            end_key_list: Vec::new(),
            use_end_key: false,
            use_dayi_symbols: false,
            dayisymbolsmode: false,
            auto_show_cand_when_max_char: false,
            last_commit_string: String::new(),
            last_composition_char_length: 0,
            menutype: 0,
            reset_menu_cand: false,
            keep_composition: false,
            keep_type: String::new(),
            homophonemode: false,
            homophoneselpinyinmode: false,
            homophone_char: String::new(),
            homophone_str: String::new(),
            is_homophone_chardefs: false,
            homophonecandidates: Vec::new(),
            show_message_on_key_up: false,
            hide_message_on_key_up: false,
            on_key_up_message: String::new(),
            re_load_cin_table: false,
            r_cin_file_not_exist: false,
            caps_states: false,
            bopomofolist: Vec::new(),
            skip_space_deadline: 0.0,
            last_candidate_ui_args: None,
            dayi_symbol_char: String::new(),
            dayi_symbol_string: String::new(),
            smenuitems: Vec::new(),
            menupathlist: Vec::new(),
            cand_per_row: 0,
            cand_per_page: 0,
            output_small_letter_with_shift: false,
            support_wildcard: false,
            sel_wildcard_char: String::new(),
            cand_max_items: 0,
            sel_r_cin_type: 0,
            sel_h_cin_type: 0,
            sel_cin_type: 0,
            swkb: None,
            symbols: None,
            fsymbols: None,
            flangs: None,
            userphrase: None,
            excludephrase: None,
            msymbols: None,
            extendtable: None,
            dsymbols: None,
        }
    }

    /// IB:48 CinBaseTextService.__init__ (with the subclass's class attributes
    /// and its initTextServiceExtra hook).
    pub fn new(
        client: ClientInfo,
        ime_dir_name: &str,
        max_char_length: i64,
        cin_file_list: &[&str],
        init_text_service_extra: fn(&mut CbTs),
    ) -> Result<CbTs, String> {
        // CinBase.__init__ (module import) reads emoji.json
        emoji()?;
        let tables = shared_tables(ime_dir_name);
        let mut st = CbTs::blank(client, ime_dir_name, max_char_length, cin_file_list, tables);
        st.init_text_service();
        // flags of the subclass must be set before initCinBaseContext
        init_text_service_extra(&mut st);

        let mut cfg = CinBaseConfig::new();
        cfg.ime_dir_name = st.ime_dir_name.clone();
        cfg.cin_file_list = st.cin_file_list.clone();
        cfg.load();
        st.config_version = cfg.get_version();
        st.cfg = cfg;
        st.jsondir = st.cfg.get_json_dir();
        st.cindir = st.cfg.get_cin_dir();
        st.ignore_private_use_area = st.cfg.ignore_private_use_area;
        st.init_cin_base_context()?;

        // an out-of-range index loads table 0: compare with the same value
        let sel_cin_type = table_index(st.cfg.sel_cin_type, st.cin_file_list.len());
        let (cur, loading, last_failure) = {
            let t = st.tables.cin.borrow();
            (t.cur_cin_type, t.loading, t.last_load_failure)
        };
        if cur != Some(sel_cin_type) && !loading && !table_load_recently_failed(last_failure) {
            // the first load is synchronous (try: ... except Exception: pass)
            let _ = st.load_cin_table();
        } else if !loading {
            st.cin = st.tables.cin.borrow().cin.clone();
        }
        Ok(st)
    }

    // -- access to attributes Python would raise AttributeError for ----------

    /// cbTS.cin (AttributeError when missing / None)
    pub fn cin(&self) -> Result<Ref<'_, Cin>, String> {
        match &self.cin {
            Some(c) => Ok(c.borrow()),
            None => Err(attr_error("cin")),
        }
    }

    pub fn cin_mut(&self) -> Result<RefMut<'_, Cin>, String> {
        match &self.cin {
            Some(c) => Ok(c.borrow_mut()),
            None => Err(attr_error("cin")),
        }
    }

    pub fn swkb(&self) -> Result<&Swkb, String> {
        self.swkb.as_ref().ok_or_else(|| attr_error("swkb"))
    }
    pub fn symbols(&self) -> Result<&Symbols, String> {
        self.symbols.as_ref().ok_or_else(|| attr_error("symbols"))
    }
    pub fn fsymbols(&self) -> Result<&FSymbols, String> {
        self.fsymbols.as_ref().ok_or_else(|| attr_error("fsymbols"))
    }
    pub fn flangs(&self) -> Result<&FLangs, String> {
        self.flangs.as_ref().ok_or_else(|| attr_error("flangs"))
    }
    pub fn userphrase(&self) -> Result<&UserPhrase, String> {
        self.userphrase.as_ref().ok_or_else(|| attr_error("userphrase"))
    }
    pub fn msymbols(&self) -> Result<&MSymbols, String> {
        self.msymbols.as_ref().ok_or_else(|| attr_error("msymbols"))
    }
    pub fn extendtable(&self) -> Result<&ExtendTable, String> {
        self.extendtable.as_ref().ok_or_else(|| attr_error("extendtable"))
    }
    pub fn dsymbols(&self) -> Result<&DSymbols, String> {
        self.dsymbols.as_ref().ok_or_else(|| attr_error("dsymbols"))
    }

    // -- TextService methods as Python calls them on cbTS ---------------------

    pub fn set_composition_string(&mut self, s: &str) {
        self.ts.set_composition_string(s);
    }
    pub fn set_composition_cursor(&mut self, pos: i64) {
        self.ts.set_composition_cursor(pos);
    }
    pub fn set_commit_string(&mut self, s: &str) {
        self.ts.set_commit_string(s);
    }
    pub fn set_candidate_list(&mut self, cand: Vec<String>) {
        self.ts.set_candidate_list(cand);
    }
    pub fn set_candidate_cursor(&mut self, pos: i64) {
        self.ts.set_candidate_cursor(pos);
    }
    pub fn set_show_candidates(&mut self, show: bool) {
        self.ts.set_show_candidates(show);
    }
    pub fn show_message(&mut self, message: &str) {
        self.ts.show_message(message, 3);
    }
    pub fn hide_message(&mut self) {
        self.ts.hide_message();
    }
    pub fn is_composing(&self) -> bool {
        self.ts.is_composing()
    }
    /// IB:152 setCandidatePage
    pub fn set_candidate_page(&mut self, page: i64) {
        self.current_cand_page = page;
    }
    /// CB:3439 getKeyState(keyCode)
    pub fn get_key_state(&self, key_code: u32) -> i16 {
        env::get_key_state(key_code)
    }
    /// CB:3445 isPressed(keyCode)
    pub fn is_pressed(&self, key_code: u32) -> bool {
        env::is_pressed(key_code)
    }

    // CB:143 initTextService
    pub fn init_text_service(&mut self) {
        self.init_sel_keys();

        self.keyboard_layout = 0;
        self.sel_keys = "1234567890".into();
        self.lang_mode = -1;
        self.shape_mode = -1;
        self.switch_page_with_space = false;
        self.play_sound_when_non_cand = false;
        self.direct_show_cand = false;
        self.auto_commit_single_candidate = false;
        self.direct_commit_symbol = false;
        self.direct_commit_symbol_list = ["，", "。", "、", "；", "？", "！"].iter().map(|s| s.to_string()).collect();
        self.bracket_symbol_list = ["「」", "『』", "［］", "【】", "〖〗", "〔〕", "﹝﹞", "（）", "﹙﹚", "〈〉", "《》", "＜＞", "﹤﹥", "｛｝", "﹛﹜"]
            .iter()
            .map(|s| s.to_string())
            .collect();
        self.ignore_private_use_area = true;
        self.direct_out_m_symbols = true;
        self.full_shape_symbols = false;
        self.direct_out_f_symbols = false;
        self.easy_symbols_with_shift = false;
        self.show_phrase = false;
        self.sort_by_phrase = false;
        self.intelligent_select = false;
        self.intelligent_select_recent = false;
        self.intelligent_select_context = false;
        self.hide_composition = false;
        self.hide_composition_label = String::new();
        self.ime_display_name = String::new();
        self.composition_buffer_mode = false;
        self.auto_move_cursor_in_brackets = false;
        self.ime_reverse_lookup = false;
        self.homophone_query = false;
        self.user_extend_table = false;
        self.re_load_table = false;
        self.priority_extend_table = false;

        self.sel_dayi_symbol_char_type = 0;
        self.last_key_down_code = 0;
        self.last_key_down_time = 0.0;

        self.menucandidates = Vec::new();
        self.smenucandidates = Vec::new();
        self.wildcardcandidates = Vec::new();
        self.wildcardpagecandidates = Vec::new();
        self.wildcardcomposition_char = String::new();
        self.current_cand_page = 0;

        self.emojitype = 0;
        self.prevmenutypelist = Vec::new();
        self.prevmenucandlist = Vec::new();

        self.composition_buffer_string = String::new();
        self.composition_buffer_cursor = 0;
        self.composition_buffer_type = "default".into();
        self.composition_buffer_char = IndexMap::new();
        self.composition_buffer_menu_item = String::new();
        self.tempengcandidates = Vec::new();
        self.key_used_state = false;
        self.selcandmode = false;

        self.init_cin_base_state = false;
        self.showmenu = false;
        self.switchmenu = false;
        self.closemenu = true;
        self.temp_english_mode = false;
        self.multifunctionmode = false;
        self.menumode = false;
        self.emojimenumode = false;
        self.menusymbolsmode = false;
        self.ctrlsymbolsmode = false;
        self.fullsymbolsmode = false;
        self.phrasemode = false;
        self.is_sel_keys_changed = false;
        self.is_wildcard_chardefs = false;
        self.is_lang_mode_changed = false;
        self.is_shape_mode_changed = false;
        self.shift_space_key_added = false;
        self.is_show_candidates = false;
        self.is_show_phrase_candidates = false;
        self.is_show_message = false;
        self.can_set_commit_string = true;
        self.can_set_phrase_commit_string = false;
        self.can_use_sel_key = true;
        self.can_use_space_as_page_key = true;
        self.end_key_list = Vec::new();
        self.use_end_key = false;
        self.use_dayi_symbols = false;
        self.dayisymbolsmode = false;
        self.auto_show_cand_when_max_char = false;
        self.last_commit_string = String::new();
        self.last_composition_char_length = 0;
        self.menutype = 0;
        self.reset_menu_cand = false;
        self.keep_composition = false;
        self.keep_type = String::new();

        self.homophonemode = false;
        self.homophoneselpinyinmode = false;
        self.homophone_char = String::new();
        self.homophone_str = String::new();
        self.is_homophone_chardefs = false;
        self.homophonecandidates = Vec::new();

        self.show_message_on_key_up = false;
        self.hide_message_on_key_up = false;
        self.on_key_up_message = String::new();
        self.re_load_cin_table = false;
        self.r_cin_file_not_exist = false;
        self.caps_states = self.get_key_state(VK_CAPITAL) != 0;

        let mut list = Vec::new();
        for i in 0x3105..0x311A {
            list.push(char::from_u32(i).unwrap().to_string());
        }
        for i in 0x3127..0x312A {
            list.push(char::from_u32(i).unwrap().to_string());
        }
        for i in 0x311A..0x3127 {
            list.push(char::from_u32(i).unwrap().to_string());
        }
        for c in ['\u{02D9}', '\u{02CA}', '\u{02C7}', '\u{02CB}'] {
            list.push(c.to_string());
        }
        self.bopomofolist = list;
    }
}

// ---------------------------------------------------------------------------
// 大易 (python/input_methods/chedayi/chedayi_ime.py)

pub const CHEDAYI_GUID: &str = "{e6943374-70f5-4540-aa0f-3205c7dcca84}";
pub const CHEDAYI_IME_DIR_NAME: &str = "chedayi";
pub const CHEDAYI_MAX_CHAR_LENGTH: i64 = 4;
pub const CHEDAYI_CIN_FILE_LIST: &[&str] = &["thdayi.json", "dayi4.json", "dayi3.json"];

/// DY:20 CheDayiTextService
pub struct CheDayiTextService {
    pub st: CbTs,
}

/// DY:28 initTextServiceExtra: must run before initCinBaseContext so the
/// dsymbols table is loaded
fn chedayi_init_text_service_extra(st: &mut CbTs) {
    st.use_dayi_symbols = true;
    st.sel_dayi_symbol_char_type = 0;
}

impl CheDayiTextService {
    pub fn new(client: ClientInfo) -> Result<CheDayiTextService, String> {
        let st = CbTs::new(client, CHEDAYI_IME_DIR_NAME, CHEDAYI_MAX_CHAR_LENGTH, CHEDAYI_CIN_FILE_LIST, chedayi_init_text_service_extra)?;
        Ok(CheDayiTextService { st })
    }
}

/// IB:108-150: CinBaseTextService forwards every event to CinBase.
impl Service for CheDayiTextService {
    fn ts(&mut self) -> &mut TextService {
        &mut self.st.ts
    }

    fn check_config_change(&mut self) -> Result<(), String> {
        self.st.check_config_change()
    }

    fn on_activate(&mut self) -> Result<(), String> {
        self.st.on_activate()
    }

    fn on_deactivate(&mut self) -> Result<(), String> {
        self.st.on_deactivate()
    }

    fn filter_key_down(&mut self, ev: &KeyEvent) -> Result<Value, String> {
        Ok(json!(self.st.filter_key_down(ev)?))
    }

    fn on_key_down(&mut self, ev: &KeyEvent) -> Result<Value, String> {
        Ok(json!(self.st.chedayi_on_key_down(ev)?))
    }

    fn filter_key_up(&mut self, ev: &KeyEvent) -> Result<Value, String> {
        Ok(json!(self.st.filter_key_up(ev)?))
    }

    fn on_key_up(&mut self, ev: &KeyEvent) -> Result<Option<Value>, String> {
        self.st.on_key_up(ev)?;
        Ok(None)
    }

    fn on_preserved_key(&mut self, guid: &str) -> Result<Value, String> {
        Ok(json!(self.st.on_preserved_key(guid)?))
    }

    fn on_command(&mut self, id: &Value, kind: &Value) -> Result<(), String> {
        self.st.on_command(id, kind)
    }

    fn on_menu(&mut self, button_id: &Value) -> Result<Option<Value>, String> {
        self.st.on_menu(button_id)
    }

    fn on_keyboard_status_changed(&mut self, opened: bool) -> Result<(), String> {
        self.st.ts.keyboard_open = opened;
        self.st.on_keyboard_status_changed(opened)
    }

    fn on_composition_terminated(&mut self, forced: bool) -> Result<(), String> {
        self.st.ts.base_on_composition_terminated();
        self.st.on_composition_terminated(forced)
    }

    fn on_kill_focus(&mut self) -> Result<(), String> {
        self.st.ts.base_on_kill_focus();
        self.st.on_composition_terminated(true)
    }
}

/// serviceManager.createService for the IMEs this backend implements.
pub fn create_service(guid: &str, client: &ClientInfo) -> Result<Option<Box<dyn Service>>, String> {
    if guid == CHEDAYI_GUID {
        return Ok(Some(Box::new(CheDayiTextService::new(client.clone())?)));
    }
    Ok(None)
}
