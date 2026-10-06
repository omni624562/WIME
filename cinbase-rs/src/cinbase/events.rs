//! The requests other than onKeyDown: python/cinbase/__init__.py CB:275-571
//! (onActivate, onDeactivate, filterKeyDown, candidate header helpers) and
//! CB:2532-2918 (filterKeyUp, onKeyUp, onPreservedKey, onCommand, onMenu,
//! onKeyboardStatusChanged, onCompositionTerminated, mode switching, buttons).

use super::pyutil::{py_eq_int, py_len};
use super::*;
use crate::config::{SWITCH_LANG_WITH_BOTH_SHIFT, SWITCH_LANG_WITH_LEFT_SHIFT, SWITCH_LANG_WITH_RIGHT_SHIFT};
use crate::keycodes::*;
use crate::paths;
use crate::textservice::{COMMAND_LEFT_CLICK, COMMAND_MENU};

/// os.path.join(self.icondir, name)
pub fn icon_path(name: &str) -> String {
    paths::join_str(&paths::icon_dir(), name)
}

fn obj(pairs: &[(&str, Value)]) -> Map<String, Value> {
    let mut m = Map::new();
    for (k, v) in pairs {
        m.insert(k.to_string(), v.clone());
    }
    m
}

impl CbTs {
    // CB:275 onActivate
    pub fn on_activate(&mut self) -> Result<(), String> {
        // the changeButton queued while the service was created is replaced by
        // the addButton below (which carries the full state)
        self.ts.current_reply.shift_remove("changeButton");
        let mut keyboard_will_open = self.ts.keyboard_open;
        if self.client.is_windows8_above {
            keyboard_will_open = !self.cfg.disable_on_startup;
        }
        self.restore_chinese_mode_on_keyboard_open(Some(keyboard_will_open), false);

        // Shift + Space (full / half shape)
        self.update_shift_space_key(Some(true));

        let icon_name = if self.lang_mode == CHINESE_MODE { "chi.ico" } else { "eng.ico" };
        self.ts.add_button(
            "switch-lang",
            obj(&[("icon", json!(icon_path(icon_name))), ("tooltip", json!("中英文切換")), ("commandId", json!(ID_SWITCH_LANG))]),
        );

        // Windows 8+: the systray IME mode icon
        if self.client.is_windows8_above {
            let open = !self.cfg.disable_on_startup;
            self.ts.set_keyboard_open(open);

            let (icon, tooltip) = self.mode_icon_state();
            self.ts.add_button(
                "windows-mode-icon",
                obj(&[("icon", json!(icon)), ("tooltip", json!(tooltip)), ("commandId", json!(ID_MODE_ICON))]),
            );
        }

        let icon_name = if self.shape_mode == FULLSHAPE_MODE { "full.ico" } else { "half.ico" };
        self.ts.add_button(
            "switch-shape",
            obj(&[("icon", json!(icon_path(icon_name))), ("tooltip", json!("全形/半形切換")), ("commandId", json!(ID_SWITCH_SHAPE))]),
        );

        self.ts.add_button("settings", obj(&[("icon", json!(icon_path("config.ico"))), ("tooltip", json!("設定")), ("type", json!("menu"))]));
        self.customize_candidate_ui(true);
        Ok(())
    }

    // CB:329 unicodeInputCodePoint(hexDigits): the code point to commit for a
    // `U input, None when invalid (not hex, > U+10FFFF, surrogates, C0, DEL)
    pub fn unicode_input_code_point(hex_digits: &str) -> Option<u32> {
        // int(hexDigits, 16): whitespace, a sign, a 0x prefix and single
        // underscores between digits are accepted
        let t = hex_digits.trim_matches(|c: char| c.is_whitespace());
        let (neg, t) = match t.chars().next() {
            Some('-') => (true, &t[1..]),
            Some('+') => (false, &t[1..]),
            _ => (false, t),
        };
        let t = if t.len() >= 2 && (t.starts_with("0x") || t.starts_with("0X")) {
            let rest = &t[2..];
            rest.strip_prefix('_').unwrap_or(rest)
        } else {
            t
        };
        if t.is_empty() || t.starts_with('_') || t.ends_with('_') || t.contains("__") {
            return None;
        }
        let mut value: u128 = 0;
        for c in t.chars() {
            if c == '_' {
                continue;
            }
            let d = c.to_digit(16)?;
            value = value.saturating_mul(16).saturating_add(d as u128);
        }
        if neg && value != 0 {
            return None; // < 0x20
        }
        if value < 0x20 || value == 0x7F || (0xD800..=0xDFFF).contains(&value) || value > 0x10FFFF {
            return None;
        }
        Some(value as u32)
    }

    // CB:340 clampCandidatePosition: the page / cursor of the previous key may
    // be out of range for a changed list; reset them to the first page and
    // candidate. Returns (pagecandidates, currentCandPage, candCursor).
    pub fn clamp_candidate_position(
        &mut self,
        pagecandidates: Vec<Vec<String>>,
        current_cand_page: i64,
        cand_cursor: i64,
    ) -> (Vec<Vec<String>>, i64, i64) {
        let pagecandidates = if pagecandidates.is_empty() { vec![vec![]] } else { pagecandidates };
        let mut current_cand_page = current_cand_page;
        let mut cand_cursor = cand_cursor;
        if !(0 <= current_cand_page && current_cand_page < pagecandidates.len() as i64) {
            current_cand_page = 0;
            self.set_candidate_page(0);
        }
        let n = pagecandidates[current_cand_page as usize].len().max(1) as i64;
        if !(0 <= cand_cursor && cand_cursor < n) {
            cand_cursor = 0;
            self.set_candidate_cursor(0);
        }
        (pagecandidates, current_cand_page, cand_cursor)
    }

    // CB:356 setModernCandidatePageInfo
    pub fn set_modern_candidate_page_info(&mut self, current_cand_page: i64, pagecandidates: &[Vec<String>]) {
        let total_pages = pagecandidates.len();
        let info = if total_pages > 0 { format!("{}/{}", current_cand_page + 1, total_pages) } else { String::new() };
        self.ts.current_reply.insert("candidatePageInfo".into(), json!(info));
    }

    // CB:363 ensureModernCandidateHeader
    pub fn ensure_modern_candidate_header(&mut self) {
        let reply = &self.ts.current_reply;
        if reply.get("showCandidates") == Some(&Value::Bool(false)) {
            return;
        }
        let wants_candidate_window = reply.get("showCandidates") == Some(&Value::Bool(true))
            || reply.contains_key("candidateList")
            || reply.contains_key("candidateMessage");
        let has_header = reply.get("candidateHeader").map(pyutil::py_truthy).unwrap_or(false);
        if !wants_candidate_window || has_header {
            return;
        }
        let header_label = match self.ime_dir_name.as_str() {
            "chedayi" => "大易",
            "checj" => "酷倉",
            "cheliu" => "蝦米",
            _ => "",
        };
        let label = if !self.ime_display_name.is_empty() { self.ime_display_name.clone() } else { header_label.to_string() };
        let header_text =
            if !self.ts.composition_string.is_empty() { self.ts.composition_string.clone() } else { self.composition_header_text() };
        let header = if !label.is_empty() && !header_text.is_empty() {
            format!("{} {}", label, header_text)
        } else if !label.is_empty() {
            label
        } else {
            header_text
        };
        self.ts.current_reply.insert("candidateHeader".into(), json!(header));
        if !self.ts.current_reply.contains_key("candidatePageInfo") {
            self.ts.current_reply.insert("candidatePageInfo".into(), json!(""));
        }
    }

    // CB:392 onDeactivate
    pub fn on_deactivate(&mut self) -> Result<(), String> {
        self.last_key_down_code = 0;
        self.update_shift_space_key(Some(false));

        self.ts.remove_button("switch-lang");
        self.ts.remove_button("switch-shape");
        self.ts.remove_button("settings");
        if self.client.is_windows8_above {
            self.ts.remove_button("windows-mode-icon");
        }

        self.swkb = None;
        self.symbols = None;
        self.fsymbols = None;
        self.flangs = None;
        self.userphrase = None;
        self.msymbols = None;
        self.extendtable = None;
        self.dsymbols = None;

        // cin is None when the table failed to load
        if let Some(cin) = &self.cin {
            cin.borrow_mut().save_count_file(true)?;
        }
        Ok(())
    }

    // CB:428 filterKeyDown: True when the IME wants the key (onKeyDown follows)
    pub fn filter_key_down(&mut self, key_event: &KeyEvent) -> Result<bool, String> {
        let char_str = key_event.char_str();

        // the last key down and when it was pressed, for filterKeyUp
        self.last_key_down_code = key_event.key_code;
        if self.last_key_down_time == 0.0 {
            self.last_key_down_time = env::time();
        }

        if self.is_space_after_auto_commit(key_event) {
            return Ok(true); // onKeyDown swallows it
        }

        let cin_table_loading = self.tables.cin.borrow().loading;
        if cin_table_loading || self.cin.is_none() {
            // table not ready: only the printable keys of the Chinese mode
            if self.is_composing() || self.ts.show_candidates {
                return Ok(true);
            }
            if key_event.is_key_down(VK_MENU) || key_event.is_key_down(VK_CONTROL) {
                return Ok(false);
            }
            return Ok(self.lang_mode == CHINESE_MODE && key_event.is_printable_char());
        }

        // only the phrase list is open: Ctrl/Alt shortcuts close it and go to
        // the application (Ctrl+symbol keys stay symbol input)
        if self.show_phrase
            && self.phrasemode
            && self.is_show_phrase_candidates
            && self.ts.composition_string.is_empty()
            && (key_event.is_key_down(VK_MENU) || key_event.is_key_down(VK_CONTROL))
            && !(key_event.is_key_down(VK_CONTROL) && self.is_ctrl_symbols_char(key_event.key_code) && self.lang_mode == CHINESE_MODE)
        {
            self.phrasemode = false;
            self.is_show_phrase_candidates = false;
            self.set_candidate_list(Vec::new());
            self.set_show_candidates(false);
            return Ok(false);
        }

        if self.is_composing() || self.ts.show_candidates {
            return Ok(true);
        }

        if self.show_phrase && self.phrasemode && self.is_show_phrase_candidates {
            return Ok(true);
        }

        // ---- nothing is being composed below ----

        // Alt: an application shortcut
        if key_event.is_key_down(VK_MENU) {
            if self.is_show_message {
                self.hide_message_on_key_up = true;
            }
            return Ok(false);
        }

        if key_event.is_key_down(VK_CONTROL) {
            if self.is_ctrl_symbols_char(key_event.key_code) && self.lang_mode == CHINESE_MODE {
                return Ok(true);
            } else {
                if self.is_show_message {
                    self.hide_message_on_key_up = true;
                }
                return Ok(false);
            }
        }

        if key_event.is_key_down(VK_SHIFT) {
            if self.lang_mode == CHINESE_MODE && !key_event.is_key_down(VK_CONTROL) {
                if self.easy_symbols_with_shift && self.is_letter_char(key_event.key_code) {
                    return Ok(true);
                }
                if self.full_shape_symbols && (self.is_symbols_char(key_event.key_code) || self.is_number_char(key_event.key_code)) {
                    return Ok(true);
                }
                if self.is_wildcard_input_key(&char_str, key_event) {
                    return Ok(true);
                }
                if !self.is_composing() && self.composition_buffer_mode && !self.direct_show_cand && self.shape_mode == HALFSHAPE_MODE {
                    return Ok(false);
                }
            }
        }

        // numpad * has no Shift and is a wildcard too
        if self.lang_mode == CHINESE_MODE && self.is_wildcard_input_key(&char_str, key_event) {
            return Ok(true);
        }

        // NumLock on: numpad keys go to the application
        if key_event.is_key_toggled(VK_NUMLOCK) && key_event.key_code >= VK_NUMPAD0 && key_event.key_code <= VK_DIVIDE {
            if self.is_show_message {
                self.hide_message_on_key_up = true;
            }
            return Ok(false);
        }

        // full shape: every printable char or space is converted
        if self.shape_mode == FULLSHAPE_MODE {
            if key_event.is_printable_char() || key_event.key_code == VK_SPACE {
                return Ok(true);
            } else {
                if self.is_show_message && !key_event.is_key_down(VK_SHIFT) {
                    self.hide_message_on_key_up = true;
                }
                return Ok(false);
            }
        }

        // ---- half shape below ----
        if self.lang_mode == ENGLISH_MODE {
            if self.is_show_message && !key_event.is_key_down(VK_SHIFT) {
                self.hide_message_on_key_up = true;
            }
            return Ok(false);
        }

        // ---- Chinese mode below ----
        if self.ime_dir_name == "chepinyin" && self.composition_char.is_empty() && self.end_key_list.contains(&char_str) {
            return Ok(false);
        }

        // a root of the table
        if self.cin()?.is_in_key_name(&char_str.to_lowercase()) {
            return Ok(true);
        }

        // roots of another keyboard layout (not the default)
        if self.keyboard_layout != 0 {
            // cbTS.kbtypelist only exists for the phonetic IMEs
            return Err(super::attr_error("kbtypelist"));
        }

        // `
        if key_event.is_key_down(VK_OEM_3) {
            return Ok(true);
        }

        if self.use_dayi_symbols {
            if self.sel_dayi_symbol_char_type == 0 {
                if key_event.is_key_down(VK_OEM_PLUS) {
                    return Ok(true);
                }
            } else if key_event.is_key_down(VK_OEM_7) {
                return Ok(true);
            }
        }

        if self.is_show_message && !key_event.is_key_down(VK_SHIFT) {
            self.hide_message_on_key_up = true;
        }
        Ok(false)
    }

    // CB:2532 filterKeyUp
    pub fn filter_key_up(&mut self, key_event: &KeyEvent) -> Result<bool, String> {
        if key_event.key_code == VK_SPACE {
            self.skip_space_deadline = 0.0;
        }
        if self.cfg.switch_lang_with_shift {
            // the last key pressed and the key released are both Shift
            if self.last_key_down_code == VK_SHIFT && key_event.key_code == VK_SHIFT {
                let which = self.cfg.switch_lang_with_which_shift;
                if which == SWITCH_LANG_WITH_BOTH_SHIFT {
                } else if which == SWITCH_LANG_WITH_LEFT_SHIFT && !self.is_shift_side(key_event, VK_LSHIFT) {
                    self.last_key_down_code = 0;
                    self.last_key_down_time = 0.0;
                    return Ok(false);
                } else if which == SWITCH_LANG_WITH_RIGHT_SHIFT && !self.is_shift_side(key_event, VK_RSHIFT) {
                    self.last_key_down_code = 0;
                    self.last_key_down_time = 0.0;
                    return Ok(false);
                }

                let pressed_duration = env::time() - self.last_key_down_time;
                if pressed_duration < 0.5 {
                    self.is_lang_mode_changed = true;
                }
            }
        }

        // CapsLock released: always handled
        if self.last_key_down_code == VK_CAPITAL && key_event.key_code == VK_CAPITAL {
            return Ok(true);
        }

        self.last_key_down_code = 0;
        self.last_key_down_time = 0.0;

        if self.is_lang_mode_changed {
            return Ok(true);
        }
        if self.is_shape_mode_changed {
            return Ok(true);
        }
        if self.is_sel_keys_changed {
            return Ok(true);
        }
        if self.show_phrase && self.phrasemode && self.is_show_phrase_candidates {
            return Ok(true);
        }
        if self.show_message_on_key_up {
            return Ok(true);
        }
        if self.hide_message_on_key_up {
            return Ok(true);
        }
        Ok(false)
    }

    // CB:2587 onKeyUp
    pub fn on_key_up(&mut self, key_event: &KeyEvent) -> Result<(), String> {
        let key_code = key_event.key_code;
        self.last_key_down_code = 0;
        self.last_key_down_time = 0.0;

        // Shift released after a language toggle
        if self.is_lang_mode_changed && key_code == VK_SHIFT {
            self.toggle_language_mode();
            self.is_lang_mode_changed = false;
            self.abandon_composition()?;
        }

        if key_event.key_code == VK_CAPITAL {
            self.update_lang_buttons();
        }

        if self.is_shape_mode_changed {
            self.is_shape_mode_changed = false;
            self.abandon_composition()?;
        }

        if self.is_sel_keys_changed {
            // the key-down reply already carried setSelKeys and the list
            self.is_sel_keys_changed = false;
        }

        if self.show_phrase && self.phrasemode && self.is_show_phrase_candidates {
            self.set_show_candidates(true);
        }

        if self.show_message_on_key_up {
            if !self.on_key_up_message.is_empty() && !self.client.is_ui_less {
                let m = self.on_key_up_message.clone();
                self.show_message(&m);
            }
            self.show_message_on_key_up = false;
            self.on_key_up_message = String::new();
        }

        if self.hide_message_on_key_up {
            self.hide_message();
            self.is_show_message = false;
            self.hide_message_on_key_up = false;
        }

        self.ensure_modern_candidate_header();

        if self.ts.current_reply.contains_key("candidateList") || self.ts.current_reply.contains_key("showCandidates") {
            self.customize_candidate_ui(false);
        }
        Ok(())
    }

    // CB:2634 onPreservedKey
    pub fn on_preserved_key(&mut self, guid: &str) -> Result<bool, String> {
        self.last_key_down_code = 0;
        if guid == SHIFT_SPACE_GUID {
            // keyboard closed or the shortcut disabled: leave it to the application
            if !self.ts.keyboard_open || !self.cfg.enable_shift_space {
                return Ok(false);
            }
            self.is_shape_mode_changed = true;
            self.toggle_shape_mode();
            return Ok(true);
        }
        Ok(false)
    }

    // CB:2652 updateShiftSpaceKey(activated=None): declare Shift+Space only
    // while active and enableShiftSpace is on
    pub fn update_shift_space_key(&mut self, activated: Option<bool>) {
        let activated = activated.unwrap_or(self.ts.is_activated);
        let wanted = activated && self.cfg.enable_shift_space;
        if wanted && !self.shift_space_key_added {
            self.ts.add_preserved_key(VK_SPACE, TF_MOD_SHIFT, SHIFT_SPACE_GUID);
        } else if !wanted && self.shift_space_key_added {
            self.ts.remove_preserved_key(SHIFT_SPACE_GUID);
        }
        self.shift_space_key_added = wanted;
    }

    /// The settings tool launch of CB:2680-2685 / CB:2923-2928:
    /// ShellExecuteW(None, "open", sys.executable, '"<configtool.py>" config <ime>', cinbasecurdir, SW_HIDE)
    pub fn launch_config_tool(&self) {
        let cinbasecurdir = paths::cinbase_dir();
        let tool_name = "config";
        let config_tool = format!("\"{}\" {} {}", paths::join_str(&cinbasecurdir, "configtool.py"), tool_name, self.ime_dir_name);
        let python_exe = paths::join_str(&paths::python_dir().join("python3"), "python.exe");
        env::shell_execute_in(&python_exe, &config_tool, &cinbasecurdir.to_string_lossy(), 0);
    }

    // CB:2664 onCommand
    pub fn on_command(&mut self, command_id: &Value, command_type: &Value) -> Result<(), String> {
        // switching from the mouse / language bar sends no key: cancel the grace too
        self.skip_space_deadline = 0.0;
        let left_or_menu = py_eq_int(command_type, COMMAND_LEFT_CLICK) || py_eq_int(command_type, COMMAND_MENU);
        if py_eq_int(command_id, ID_SWITCH_LANG) && left_or_menu {
            self.abandon_composition()?;
            if py_eq_int(command_type, COMMAND_MENU) && self.keyboard_closed() {
                // 中文模式 picked while the keyboard is closed: open it in Chinese
                self.lang_mode = CHINESE_MODE;
                self.reopen_keyboard();
            } else {
                self.toggle_language_mode();
            }
        } else if py_eq_int(command_id, ID_SWITCH_SHAPE) && left_or_menu {
            self.abandon_composition()?;
            self.toggle_shape_mode();
        } else if py_eq_int(command_id, ID_SETTINGS) {
            self.launch_config_tool();
        } else if py_eq_int(command_id, ID_MODE_ICON) && py_eq_int(command_type, COMMAND_LEFT_CLICK) {
            // windows 8 mode icon: left click only
            self.abandon_composition()?;
            if self.keyboard_closed() {
                self.reopen_keyboard();
            } else {
                self.toggle_language_mode();
            }
        } else if py_eq_int(command_id, ID_WEBSITE) {
            env::startfile("https://github.com/omni624562/WIME");
        } else if py_eq_int(command_id, ID_BUGREPORT) {
            env::startfile("https://github.com/omni624562/WIME/issues");
        } else if py_eq_int(command_id, ID_MOEDICT) {
            env::startfile("https://www.moedict.tw/");
        } else if py_eq_int(command_id, ID_DICT) {
            env::startfile("https://dict.revised.moe.edu.tw/");
        } else if py_eq_int(command_id, ID_SIMPDICT) {
            env::startfile("https://dict.concised.moe.edu.tw/");
        } else if py_eq_int(command_id, ID_LITTLEDICT) {
            env::startfile("https://dict.mini.moe.edu.tw/");
        } else if py_eq_int(command_id, ID_PROVERBDICT) {
            env::startfile("https://dict.idioms.moe.edu.tw/");
        }
        Ok(())
    }

    // CB:2714 onMenu
    pub fn on_menu(&mut self, button_id: &Value) -> Result<Option<Value>, String> {
        // the settings button (the Windows 8 mode icon uses the same menu)
        let id = button_id.as_str();
        if id == Some("settings") || id == Some("windows-mode-icon") {
            let mut items = self.mode_menu_items();
            items.extend([
                json!({"text": "參觀 WIME 官方網站(&W)", "id": ID_WEBSITE}),
                json!({}),
                json!({"text": "WIME 錯誤回報(&B)", "id": ID_BUGREPORT}),
                json!({}),
                json!({"text": "設定輸入法模組(&C)", "id": ID_SETTINGS}),
                json!({}),
                json!({"text": "網路辭典 (&D)", "submenu": [
                    {"text": "萌典 (moedict)", "id": ID_MOEDICT},
                    {},
                    {"text": "教育部國語辭典", "id": ID_DICT},
                    {"text": "教育部國語辭典簡編本", "id": ID_SIMPDICT},
                    {"text": "教育部國語小字典", "id": ID_LITTLEDICT},
                    {"text": "教育部成語典", "id": ID_PROVERBDICT},
                ]}),
            ]);
            return Ok(Some(Value::Array(items)));
        }
        Ok(None)
    }

    // CB:2740 modeMenuItems: 中文模式 / 全形 with check marks
    pub fn mode_menu_items(&self) -> Vec<Value> {
        let cfg = &self.cfg;
        let mut lang_key = "";
        if cfg.switch_lang_with_shift {
            lang_key = match cfg.switch_lang_with_which_shift {
                SWITCH_LANG_WITH_LEFT_SHIFT => "左 Shift",
                SWITCH_LANG_WITH_RIGHT_SHIFT => "右 Shift",
                _ => "Shift",
            };
        }
        let lang_text = format!("中文模式{}", if !lang_key.is_empty() { format!("（{}）", lang_key) } else { String::new() });
        let shape_text = format!("全形{}", if cfg.enable_shift_space { "（Shift+空白鍵）" } else { "" });
        vec![
            json!({"text": lang_text, "id": ID_SWITCH_LANG, "checked": self.lang_mode == CHINESE_MODE && !self.keyboard_closed()}),
            json!({"text": shape_text, "id": ID_SWITCH_SHAPE, "checked": self.shape_mode == FULLSHAPE_MODE}),
            json!({}),
        ]
    }

    // CB:2756 onKeyboardStatusChanged (Ctrl+Space on Windows 10)
    pub fn on_keyboard_status_changed(&mut self, opened: bool) -> Result<(), String> {
        self.skip_space_deadline = 0.0;
        if opened {
            self.abandon_composition()?;
            self.reset_composition_buffer();
            self.restore_chinese_mode_on_keyboard_open(Some(opened), false);
        } else {
            self.abandon_composition()?;
            self.reset_composition_buffer();
        }
        self.update_lang_buttons();
        Ok(())
    }

    // CB:2771 keyboardClosed: keyboardOpen only means something while active
    pub fn keyboard_closed(&self) -> bool {
        self.ts.is_activated && !self.ts.keyboard_open
    }

    // CB:2778 reopenKeyboard
    pub fn reopen_keyboard(&mut self) {
        self.ts.set_keyboard_open(true);
        self.restore_chinese_mode_on_keyboard_open(Some(true), false);
        self.update_lang_buttons();
    }

    // CB:2787 onCompositionTerminated(forced)
    pub fn on_composition_terminated(&mut self, forced: bool) -> Result<(), String> {
        if forced {
            self.skip_space_deadline = 0.0;
            // the previous-char context is no longer reliable
            self.last_commit_string = String::new();
            // close the function menu too
            if self.showmenu {
                self.close_menu_cand();
            }
        }

        if !self.showmenu && !self.keep_composition {
            self.reset_composition();
        }

        if self.composition_buffer_mode {
            self.reset_composition_buffer();
        }

        if self.keep_composition {
            self.keep_composition = false;

            if !self.keep_type.is_empty() {
                if self.keep_type == "menusymbols" && self.composition_char == "`" {
                    self.reset_composition();
                    self.multifunctionmode = true;
                    self.composition_char = "`".into();
                    self.set_composition_string("`");
                }
                if self.keep_type == "fullShapeSymbols" {
                    let first = {
                        let fsymbols = self.fsymbols()?;
                        if fsymbols.is_in_char_def(&self.composition_char) {
                            Some(pyutil::py_list_get(fsymbols.get_char_def(&self.composition_char), 0)?)
                        } else {
                            None
                        }
                    };
                    if let Some(first) = first {
                        self.fullsymbolsmode = true;
                        self.set_composition_string(&first);
                    }
                }
                if self.keep_type == "ctrlsymbols" {
                    let first = {
                        let msymbols = self.msymbols()?;
                        if msymbols.is_in_char_def(&self.composition_char) {
                            Some(pyutil::py_list_get(msymbols.get_char_def(&self.composition_char)?, 0)?)
                        } else {
                            None
                        }
                    };
                    if let Some(first) = first {
                        self.ctrlsymbolsmode = true;
                        self.set_composition_string(&first);
                    }
                }
                self.keep_type = String::new();
            } else {
                let mut text = self.ts.composition_string.clone();
                for c in self.composition_char.chars() {
                    let c_str = c.to_string();
                    let cin = self.cin()?;
                    if cin.is_in_key_name(&c_str) {
                        text.push_str(cin.get_key_name(&c_str));
                    } else if self.support_wildcard && self.sel_wildcard_char == "*" && c_str == "*" {
                        text.push('＊');
                    }
                }
                self.ts.composition_string = text;
            }
            let len = py_len(&self.ts.composition_string);
            self.set_composition_cursor(len);
        }
        Ok(())
    }

    // CB:2839 abandonComposition: drop the composition, the function menu and
    // the phrase list (language / shape switches, keyboard open / close)
    pub fn abandon_composition(&mut self) -> Result<(), String> {
        if self.ts.show_candidates || !self.composition_char.is_empty() || !self.composition_buffer_string.is_empty() {
            if self.composition_buffer_mode && !self.selcandmode && self.cin.is_some() {
                let remove_string_length = self.calc_remove_string_length()?;
                self.remove_composition_buffer_string(remove_string_length, true);
            }
            self.reset_composition();
        }
        if self.showmenu {
            self.close_menu_cand();
        }
        self.multifunctionmode = false;
        self.phrasemode = false;
        self.is_show_phrase_candidates = false;
        Ok(())
    }

    // CB:2853 toggleLanguageMode
    pub fn toggle_language_mode(&mut self) {
        if self.lang_mode == CHINESE_MODE {
            self.lang_mode = ENGLISH_MODE;
        } else if self.lang_mode == ENGLISH_MODE {
            self.lang_mode = CHINESE_MODE;
        }
        self.update_lang_buttons();
    }

    // CB:2861 restoreChineseModeOnKeyboardOpen(opened=None, updateButtons=True)
    pub fn restore_chinese_mode_on_keyboard_open(&mut self, opened: Option<bool>, update_buttons: bool) -> bool {
        let opened = opened.unwrap_or(self.ts.keyboard_open);
        if !opened || self.lang_mode != ENGLISH_MODE || self.cfg.default_english {
            return false;
        }
        self.lang_mode = CHINESE_MODE;
        if update_buttons {
            self.update_lang_buttons();
        }
        true
    }

    // CB:2873 toggleShapeMode
    pub fn toggle_shape_mode(&mut self) {
        if self.shape_mode == HALFSHAPE_MODE {
            self.shape_mode = FULLSHAPE_MODE;
        } else if self.shape_mode == FULLSHAPE_MODE {
            self.shape_mode = HALFSHAPE_MODE;
        }
        self.update_lang_buttons();
    }

    // CB:2882 updateLangButtons
    pub fn update_lang_buttons(&mut self) {
        let icon_name = if self.lang_mode == CHINESE_MODE { "chi.ico" } else { "eng.ico" };
        self.ts.change_button("switch-lang", obj(&[("icon", json!(icon_path(icon_name)))]));
        self.caps_states = self.get_key_state(VK_CAPITAL) != 0;

        if self.client.is_windows8_above {
            let (icon, tooltip) = self.mode_icon_state();
            self.ts.change_button("windows-mode-icon", obj(&[("icon", json!(icon)), ("tooltip", json!(tooltip))]));
        }

        let icon_name = if self.shape_mode == FULLSHAPE_MODE { "full.ico" } else { "half.ico" };
        self.ts.change_button("switch-shape", obj(&[("icon", json!(icon_path(icon_name)))]));
    }

    // CB:2902 modeIconState: (icon path, tooltip with the IME name and state)
    pub fn mode_icon_state(&self) -> (String, String) {
        let name = if !self.ime_display_name.is_empty() { self.ime_display_name.clone() } else { ime_short_name(&self.ime_dir_name).to_string() };
        let prefix = if !name.is_empty() { format!("{}：", name) } else { String::new() };
        if self.keyboard_closed() {
            return (icon_path("eng_half_capsoff.ico"), format!("{}已關閉（按一下或按 Ctrl+空白鍵開啟）", prefix));
        }
        let chinese = self.lang_mode == CHINESE_MODE;
        let full = self.shape_mode == FULLSHAPE_MODE;
        let icon_name = format!(
            "{}_{}_{}.ico",
            if chinese { "chi" } else { "eng" },
            if full { "full" } else { "half" },
            if self.caps_states { "capson" } else { "capsoff" }
        );
        let tooltip = format!("{}{}、{}（按一下切換中英文）", prefix, if chinese { "中文" } else { "英文" }, if full { "全形" } else { "半形" });
        (icon_path(&icon_name), tooltip)
    }
}
