//! CinBase.onKeyDown CB:1013-2527, translated line by line (`// CB:<line>`
//! markers). The helpers it calls for the ` / Ctrl symbol modes and the
//! function menu are in keydown_modes.rs.
//!
//! Python's local variables candCursor / currentCandPage / pagecandidates /
//! candCount / currentCandPageCount are plain locals here: every read in
//! Python follows an assignment on the same path (the candidate-window block
//! at CB:2038 only runs when the one at CB:1999 did).

use super::pyutil::{py_char_at, py_in, py_len, py_list_get, py_lower, py_slice, py_str_index, py_truthy, py_upper};
use super::*;
use crate::keycodes::*;
use crate::pager;

/// CB:2492 headerCompositionLabels
fn header_composition_label(ime_dir_name: &str) -> Option<&'static str> {
    match ime_dir_name {
        "chedayi" => Some("大易"),
        "checj" => Some("酷倉"),
        "cheliu" => Some("蝦米"),
        _ => None,
    }
}

impl CbTs {
    /// setCompositionBufferChar(cbTS, cbTS.compositionBufferType, ch, cbTS.compositionBufferCursor)
    fn record_buffer_char_at_cursor(&mut self, ch: &str) {
        let t = self.composition_buffer_type.clone();
        let cursor = self.composition_buffer_cursor;
        self.set_composition_buffer_char(&t, ch, cursor);
    }

    /// cbTS.cin.getCharDef(key), then sortByPhrase (when on and non-empty) and
    /// sortByIntelligentSelect(key, ...)
    fn sorted_cin_candidates(&self, key: &str) -> Result<Vec<String>, String> {
        let mut candidates = self.cin()?.get_char_def(key).to_vec();
        if self.sort_by_phrase && !candidates.is_empty() {
            candidates = self.sort_by_phrase(candidates);
        }
        self.sort_by_intelligent_select(key, candidates)
    }

    /// RemoveStringLength = calcRemoveStringLength(cbTS) if compositionChar != '' else 0
    fn remove_len_if_composing(&self) -> Result<i64, String> {
        if !self.composition_char.is_empty() {
            self.calc_remove_string_length()
        } else {
            Ok(0)
        }
    }

    /// cin.getKeyName(c) length of the last root, 1 when it is no root
    fn last_key_length(&self) -> Result<i64, String> {
        let n = py_len(&self.composition_char);
        let last = py_slice(&self.composition_char, Some(n - 1), None);
        let cin = self.cin()?;
        Ok(if cin.is_in_key_name(&last) { py_len(cin.get_key_name(&last)) } else { 1 })
    }

    /// CB:1013 CinBase.onKeyDown
    pub fn on_key_down(&mut self, key_event: &KeyEvent) -> Result<bool, String> {
        // CB:1014
        let mut char_code = key_event.char_code;
        let key_code = key_event.key_code;
        let mut char_str = key_event.char_str();
        let char_str_low = py_lower(&char_str);

        // CB:1019
        if self.is_space_after_auto_commit(key_event) {
            self.skip_space_deadline = 0.0;
            return Ok(true);
        }

        // CB:1023
        if self.tables.cin.borrow().loading || self.cin.is_none() {
            if !self.client.is_ui_less {
                let messagestr = if self.cin.is_none() && self.tables.cin.borrow().load_failed {
                    "輸入法碼表載入失敗，請重新安裝 WIME 或檢查碼表檔案"
                } else {
                    "正在載入輸入法碼表，請稍候..."
                };
                self.is_show_message = true;
                self.show_message(messagestr);
            }
            return Ok(true);
        }

        // CB:1037 NumPad
        if key_event.is_key_toggled(VK_NUMLOCK) && key_event.key_code >= VK_NUMPAD0 && key_event.key_code <= VK_DIVIDE {
            if self.is_wildcard_input_key(&char_str, key_event) {
                // pass
            } else {
                let handled = self.numpad_while_composing(&char_str)?;
                if let Some(h) = handled {
                    return Ok(h);
                }
                if !self.composition_buffer_mode || self.ts.show_candidates {
                    return Ok(true);
                }
            }
        }

        // CB:1049
        if self.composition_buffer_mode && !self.is_composing() {
            self.composition_buffer_type = "default".into();
            self.composition_buffer_char = IndexMap::new();
        }

        // CB:1053
        if self.lang_mode == ENGLISH_MODE {
            if self.is_composing() || self.ts.show_candidates {
                self.temp_english_mode = true;
            }
        } else {
            self.temp_english_mode = false;
        }

        // CB:1059
        if self.temp_english_mode && !self.ts.show_candidates && key_event.is_printable_char() && !key_event.is_key_down(VK_CONTROL) {
            if self.shape_mode == HALFSHAPE_MODE {
                self.composition_buffer_type = "english".into();
                self.set_composition_buffer_string(&char_str, 0);
            } else {
                let c_str = if self.is_symbols_char(key_code) || self.is_number_char(key_code) {
                    self.symbols_char_code_to_fullshape(char_code)
                } else {
                    self.char_code_to_fullshape(char_code, key_code)?
                };
                self.composition_buffer_type = "fullshape".into();
                self.set_composition_buffer_string(&c_str, 0);
            }
            self.record_buffer_char_at_cursor(&char_str);
        }

        // CB:1074 鍵盤對映 (注音): cbTS.kbtypelist only exists for the phonetic IMEs
        if self.keyboard_layout != 0 {
            return Err(super::attr_error("kbtypelist"));
        }

        // CB:1081
        let cin_has_char_str_low = self.cin()?.is_in_key_name(&char_str_low);

        // CB:1084 檢查選字鍵
        if self.ime_dir_name != "chedayi" {
            self.apply_default_sel_keys();
        }

        // CB:1087
        if self.auto_move_cursor_in_brackets
            && self.composition_buffer_mode
            && key_event.is_printable_char()
            && !key_event.is_key_down(VK_SPACE)
            && py_len(&self.composition_buffer_string) >= 2
            && self.composition_buffer_cursor >= 2
        {
            self.move_cursor_in_brackets()?;
        }

        // CB:1092
        let mut candidates: Vec<String> = Vec::new();
        self.is_wildcard_chardefs = false;
        self.can_set_commit_string = true;
        self.key_used_state = false;

        if self.is_show_message {
            self.is_show_message = false;
            self.hide_message();
        }

        // CB:1102 多功能前導字元
        if self.multifunctionmode {
            self.can_use_sel_key = true;
        }

        if self.lang_mode == CHINESE_MODE && !self.showmenu {
            // CB:1106
            let cc_len = py_len(&self.composition_char);
            if cc_len == 0 && char_str == "`" && self.ime_dir_name != "cheez" {
                self.composition_char.push_str(&char_str);
                if self.composition_buffer_mode {
                    let cc = self.composition_char.clone();
                    self.set_composition_buffer_string(&cc, 0);
                } else {
                    let cc = self.composition_char.clone();
                    self.set_composition_string(&cc);
                }
                self.multifunctionmode = true;
            } else if cc_len == 1 && self.multifunctionmode {
                // CB:1114
                if char_str_low == "m" || char_str_low == "u" || char_str_low == "e" {
                    let up = py_upper(&char_str);
                    self.composition_char.push_str(&up);
                    if self.composition_buffer_mode {
                        self.set_composition_buffer_string(&up, 0);
                    } else {
                        let cc = self.composition_char.clone();
                        self.set_composition_string(&cc);
                    }
                    if char_str_low == "m" {
                        self.multifunctionmode = false;
                        self.closemenu = false;
                    } else if char_str_low == "e" {
                        self.multifunctionmode = false;
                        self.closemenu = false;
                        self.emojimenumode = true;
                    }
                } else if self.is_symbols_char(key_code) || self.is_number_char(key_code) {
                    // CB:1128
                    if self.ime_dir_name == "chedayi" {
                        if py_in(&char_str, "'[]-\\") {
                            self.can_use_sel_key = false;
                        }
                    } else if self.is_number_char(key_code) {
                        self.can_use_sel_key = false;
                    }
                    self.composition_char.push_str(&char_str);
                }
            } else if cc_len > 1 && self.multifunctionmode {
                // CB:1136
                let key = py_slice(&self.composition_char, Some(1), None) + &char_str;
                if self.msymbols()?.is_in_char_def(&key) {
                    if self.ime_dir_name == "chedayi" && py_in(&char_str, "'[]-\\") {
                        self.can_use_sel_key = false;
                    }
                    self.menusymbolsmode = false;
                    self.composition_char.push_str(&char_str);
                } else if py_slice(&self.composition_char, None, Some(2)) == "`U" {
                    // CB:1145 只收十六進位字元
                    if py_len(&char_str) == 1 && py_in(&py_upper(&char_str), "0123456789ABCDEF") {
                        let up = py_upper(&char_str);
                        self.composition_char.push_str(&up);
                        if self.composition_buffer_mode {
                            self.set_composition_buffer_string(&up, 0);
                        } else {
                            let cc = self.composition_char.clone();
                            self.set_composition_string(&cc);
                        }
                    }
                } else if py_slice(&self.composition_char, None, Some(2)) == "``" && key_code == VK_OEM_3 {
                    // CB:1151
                    self.composition_char.push_str(&char_str);
                }
            }

            // CB:1155
            if py_len(&self.composition_char) == 3 && self.multifunctionmode && self.composition_char == "```" {
                self.composition_char = "`M".into();
                if self.composition_buffer_mode {
                    let cc = self.composition_char.clone();
                    self.set_composition_buffer_string(&cc, 1);
                } else {
                    let cc = self.composition_char.clone();
                    self.set_composition_string(&cc);
                }
                self.multifunctionmode = false;
                self.closemenu = false;
            }
        }

        // CB:1165
        if self.multifunctionmode {
            if key_code == VK_ESCAPE && (self.ts.show_candidates || py_len(&self.composition_char) > 0) {
                // CB:1167 按下 ESC 鍵
                if self.composition_buffer_mode {
                    let remove_string_length =
                        if self.menusymbolsmode { py_len(&self.composition_char) - 1 } else { py_len(&self.composition_char) };
                    self.remove_composition_buffer_string(remove_string_length, true);
                }
                self.reset_composition();
                return Ok(true);
            } else if key_code == VK_BACK {
                // CB:1174 刪掉一個字根
                if !self.ts.composition_string.is_empty() {
                    if self.composition_buffer_mode {
                        let remove_string_length = if self.menusymbolsmode { py_len(&self.composition_char) - 1 } else { 1 };
                        self.remove_composition_buffer_string(remove_string_length, true);
                        let n = py_len(&self.composition_char);
                        self.composition_char = if self.menusymbolsmode {
                            py_slice(&self.composition_char, None, Some(-n))
                        } else {
                            py_slice(&self.composition_char, None, Some(-1))
                        };
                    } else {
                        let s = py_slice(&self.ts.composition_string, None, Some(-1));
                        self.set_composition_string(&s);
                        self.composition_char = py_slice(&self.composition_char, None, Some(-1));
                    }
                    self.set_candidate_cursor(0);
                    self.set_candidate_page(0);
                    if self.composition_char.is_empty() {
                        self.reset_composition();
                        return Ok(true);
                    }
                }
            } else if key_code == VK_RETURN && self.menusymbolsmode && self.is_composing() && !self.ts.show_candidates {
                // CB:1188
                let s = self.ts.composition_string.clone();
                self.set_commit_string(&s);
                self.reset_composition();
                self.reset_composition_buffer();
            }

            // CB:1194 Unicode 編碼字元超過 6 + 2 個
            if py_slice(&self.composition_char, None, Some(2)) == "`U" && py_len(&self.composition_char) > 8 {
                if self.composition_buffer_mode {
                    self.remove_composition_buffer_string(1, true);
                } else {
                    let s = py_slice(&self.ts.composition_string, None, Some(-1));
                    self.set_composition_string(&s);
                }
                self.composition_char = py_slice(&self.composition_char, None, Some(-1));
            }

            // CB:1201
            let (early_ret, new_cands) = self.handle_m_symbols_in_multifunction_mode(key_event, &char_str, cin_has_char_str_low)?;
            if early_ret {
                return Ok(true);
            }
            if let Some(c) = new_cands {
                candidates = c;
            }
        }

        // CB:1208 輕鬆輸入法進入選單模式
        if self.lang_mode == CHINESE_MODE && self.ime_dir_name == "cheez" && self.composition_char.clone() + &char_str_low == "menu" {
            self.composition_char = "`M".into();
            if self.composition_buffer_mode {
                let cc = self.composition_char.clone();
                self.set_composition_buffer_string(&cc, 3);
            } else {
                let cc = self.composition_char.clone();
                self.set_composition_string(&cc);
            }
            self.multifunctionmode = false;
            self.closemenu = false;
        }

        // CB:1219 功能選單
        candidates = self.handle_menu_mode(key_event, &char_str, char_code, key_code, candidates)?;

        // CB:1224 按鍵處理
        if !self.is_composing() && self.closemenu && !self.multifunctionmode && (key_code == VK_RETURN || key_code == VK_BACK) {
            return Ok(false);
        }

        // CB:1231
        if key_event.is_key_down(VK_SHIFT) && !key_event.is_printable_char() {
            let nav = [VK_BACK, VK_RETURN, VK_ESCAPE, VK_DELETE, VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN, VK_HOME, VK_END, VK_PRIOR, VK_NEXT];
            if !(self.is_composing() && nav.contains(&key_code)) {
                return Ok(false);
            }
        }

        // CB:1238 若按下 Ctrl 鍵
        self.handle_ctrl_symbols(key_event, &char_str, key_code, cin_has_char_str_low)?;

        // CB:1241 大易須換回選字鍵
        if !self.showmenu && self.ime_dir_name == "chedayi" {
            self.apply_dayi_sel_keys();
        }

        // CB:1245
        if self.should_restart_no_candidate_composition(&char_str_low, key_event) {
            if self.composition_buffer_mode {
                let n = self.calc_remove_string_length()?;
                self.remove_composition_buffer_string(n, true);
            }
            self.reset_composition();
        }

        // CB:1253
        let in_normal_input_mode = self.closemenu
            && !self.multifunctionmode
            && !key_event.is_key_down(VK_CONTROL)
            && !self.ctrlsymbolsmode
            && !self.dayisymbolsmode
            && !self.selcandmode
            && !self.temp_english_mode
            && !self.phrasemode;

        let full = self.shape_mode == FULLSHAPE_MODE;
        if self.is_wildcard_input_key(&char_str, key_event) && in_normal_input_mode {
            // CB:1261
            self.append_wildcard_composition();
        } else if cin_has_char_str_low && in_normal_input_mode {
            // CB:1264 按下的鍵為 CIN 內有定義的字根
            if key_event.is_key_down(VK_SHIFT) && self.lang_mode == CHINESE_MODE && self.ime_dir_name != "cheez" {
                // CB:1267
                let mut commit_str = char_str.clone();
                if self.is_wildcard_input_key(&char_str, key_event) {
                    self.append_wildcard_composition();
                } else if self.easy_symbols_with_shift && self.is_letter_char(key_code) {
                    // CB:1274
                    let up = py_upper(&char_str);
                    if self.swkb()?.is_in_char_def(&up) {
                        let c = self.swkb()?.get_char_def(&up)?.to_vec();
                        commit_str = py_list_get(&c, 0)?;
                        candidates = Vec::new();
                    } else if full {
                        commit_str = self.char_code_to_fullshape(char_code, key_code)?;
                    } else if self.output_small_letter_with_shift {
                        commit_str = if self.caps_states { py_upper(&char_str) } else { py_lower(&char_str) };
                    }
                    if self.composition_buffer_mode {
                        // CB:1285
                        let remove_string_length = self.remove_len_if_composing()?;
                        self.set_composition_buffer_string(&commit_str, remove_string_length);

                        if self.swkb()?.is_in_char_def(&up) {
                            self.composition_buffer_type = "swkb".into();
                            for ch in commit_str.chars() {
                                let idx = py_str_index(&commit_str, &ch.to_string())?;
                                let t = self.composition_buffer_type.clone();
                                let cursor = self.composition_buffer_cursor - idx;
                                self.set_composition_buffer_char(&t, &char_str, cursor);
                            }
                        } else {
                            self.composition_buffer_type = if full { "fullshape".into() } else { "english".into() };
                            self.record_buffer_char_at_cursor(&char_str);
                        }
                    } else {
                        self.set_commit_string(&commit_str);
                    }
                    self.reset_composition();
                } else if self.full_shape_symbols {
                    // CB:1301 如果啟用 Shift 輸入全形標點
                    if self.is_symbols_char(key_code) || self.is_number_char(key_code) {
                        if self.fsymbols()?.is_in_char_def(&char_str) {
                            self.set_output_f_symbols(&char_str)?;
                        } else if cin_has_char_str_low {
                            // CB:1308
                            let mut remove_string_length = 0;
                            if self.composition_buffer_mode {
                                remove_string_length = self.remove_len_if_composing()?;
                            }
                            self.composition_char = char_str_low.clone();
                            let keyname = self.cin()?.get_key_name(&char_str_low).to_string();
                            if self.composition_buffer_mode {
                                self.set_composition_buffer_string(&keyname, remove_string_length);
                                if !self.direct_show_cand {
                                    self.reset_composition();
                                }
                            } else {
                                self.set_composition_string(&keyname);
                                let n = py_len(&self.ts.composition_string);
                                self.set_composition_cursor(n);
                            }
                        } else {
                            // CB:1324
                            if full {
                                commit_str = self.symbols_char_code_to_fullshape(char_code);
                            }
                            if self.composition_buffer_mode {
                                let remove_string_length = self.remove_len_if_composing()?;
                                self.set_composition_buffer_string(&commit_str, remove_string_length);
                                self.composition_buffer_type = "fullshape".into();
                                self.record_buffer_char_at_cursor(&char_str);
                            } else {
                                self.set_commit_string(&commit_str);
                            }
                            self.reset_composition();
                        }
                    } else {
                        // CB:1337 如果是字母
                        if full {
                            commit_str = self.char_code_to_fullshape(char_code, key_code)?;
                        } else if self.output_small_letter_with_shift {
                            commit_str = if self.caps_states { py_upper(&char_str) } else { py_lower(&char_str) };
                        }
                        if self.composition_buffer_mode {
                            let remove_string_length = self.remove_len_if_composing()?;
                            self.set_composition_buffer_string(&commit_str, remove_string_length);
                            self.composition_buffer_type = if full { "fullshape".into() } else { "english".into() };
                            self.record_buffer_char_at_cursor(&char_str);
                        } else {
                            self.set_commit_string(&commit_str);
                        }
                        self.reset_composition();
                    }
                } else {
                    // CB:1353 如果未使用 SHIFT 輸入快速符號或全形標點
                    if cin_has_char_str_low && (self.is_symbols_char(key_code) || self.is_number_char(key_code)) {
                        self.composition_char = char_str_low.clone();
                        let keyname = self.cin()?.get_key_name(&char_str_low).to_string();
                        if self.composition_buffer_mode {
                            self.set_composition_buffer_string(&keyname, 0);
                        } else {
                            self.set_composition_string(&keyname);
                            let n = py_len(&self.ts.composition_string);
                            self.set_composition_cursor(n);
                        }
                    } else {
                        // CB:1362
                        if full {
                            if self.is_symbols_char(key_code) || self.is_number_char(key_code) {
                                commit_str = self.symbols_char_code_to_fullshape(char_code);
                            } else {
                                commit_str = self.char_code_to_fullshape(char_code, key_code)?;
                            }
                        } else if self.is_letter_char(key_code) && self.output_small_letter_with_shift {
                            commit_str = if self.caps_states { py_upper(&char_str) } else { py_lower(&char_str) };
                        }
                        if self.composition_buffer_mode && self.is_composing() {
                            let remove_string_length = self.remove_len_if_composing()?;
                            self.set_composition_buffer_string(&commit_str, remove_string_length);
                            self.composition_buffer_type = if full { "fullshape".into() } else { "english".into() };
                            self.record_buffer_char_at_cursor(&char_str);
                        } else {
                            self.set_commit_string(&commit_str);
                        }
                        self.reset_composition();
                    }
                }
            } else {
                // CB:1381 若沒按下 Shift 鍵
                if full && self.lang_mode == ENGLISH_MODE {
                    let commit_str = if self.is_symbols_char(key_code) || self.is_number_char(key_code) {
                        self.symbols_char_code_to_fullshape(char_code)
                    } else {
                        self.char_code_to_fullshape(char_code, key_code)?
                    };
                    self.set_commit_string(&commit_str);
                    if self.composition_buffer_mode {
                        self.reset_composition_buffer();
                    }
                    self.reset_composition();
                } else if !self.direct_show_cand && self.ts.show_candidates && self.is_in_sel_keys(char_code) {
                    // CB:1394 不送出 CIN 所定義的字根
                } else if self.ime_dir_name == "chedayi" && self.ts.show_candidates && self.is_in_sel_keys(char_code) {
                    // CB:1397 不送出 CIN 所定義的字根
                } else if self.ime_dir_name == "chephonetic" {
                    // CB:1402 注音: only the phonetic IMEs (not ported in this backend)
                    return Err("NotImplementedError: chephonetic onKeyDown".into());
                } else if !self.menusymbolsmode {
                    // CB:1418
                    self.composition_char.push_str(&char_str_low);
                    let keyname = self.cin()?.get_key_name(&char_str_low).to_string();
                    if self.composition_buffer_mode {
                        if py_len(&self.composition_char) <= self.max_char_length {
                            self.set_composition_buffer_string(&keyname, 0);
                        } else {
                            self.composition_char = py_slice(&self.composition_char, None, Some(-1));
                        }
                    } else {
                        let s = self.ts.composition_string.clone() + &keyname;
                        self.set_composition_string(&s);
                        let n = py_len(&self.ts.composition_string);
                        self.set_composition_cursor(n);
                    }
                } else {
                    self.menusymbolsmode = false;
                }
            }
        } else if !cin_has_char_str_low && in_normal_input_mode {
            // CB:1432 按下的鍵不存在於 CIN 所定義的字根
            if key_event.is_key_down(VK_SHIFT) && self.lang_mode == CHINESE_MODE && key_event.is_printable_char() {
                if self.is_wildcard_input_key(&char_str, key_event) {
                    self.append_wildcard_composition();
                } else if !self.full_shape_symbols {
                    // CB:1440
                    if full {
                        let commit_str = if self.is_symbols_char(key_code) || self.is_number_char(key_code) {
                            self.symbols_char_code_to_fullshape(char_code)
                        } else {
                            self.char_code_to_fullshape(char_code, key_code)?
                        };
                        if self.composition_buffer_mode {
                            let remove_string_length = self.remove_len_if_composing()?;
                            self.set_composition_buffer_string(&commit_str, remove_string_length);
                            self.composition_buffer_type = "fullshape".into();
                            self.record_buffer_char_at_cursor(&char_str);
                        } else {
                            self.set_commit_string(&commit_str);
                        }
                        self.reset_composition();
                    } else {
                        // CB:1458 半形模式直接輸出不作處理
                        let mut commit_str = char_str.clone();
                        if self.is_letter_char(key_code) && self.output_small_letter_with_shift {
                            commit_str = if self.caps_states { py_upper(&char_str) } else { py_lower(&char_str) };
                        }
                        if self.composition_buffer_mode {
                            let remove_string_length = self.remove_len_if_composing()?;
                            self.set_composition_buffer_string(&commit_str, remove_string_length);
                            self.composition_buffer_type = "english".into();
                            self.record_buffer_char_at_cursor(&char_str);
                        } else {
                            self.set_commit_string(&commit_str);
                        }
                        self.reset_composition();
                    }
                } else {
                    // CB:1472 如果啟用 Shift 輸入全形標點
                    if self.is_symbols_char(key_code) || self.is_number_char(key_code) {
                        if self.fsymbols()?.is_in_char_def(&char_str) {
                            self.set_output_f_symbols(&char_str)?;
                        } else {
                            let commit_str = if self.is_symbols_char(key_code) || self.is_number_char(key_code) {
                                self.symbols_char_code_to_fullshape(char_code)
                            } else {
                                self.char_code_to_fullshape(char_code, key_code)?
                            };
                            if self.composition_buffer_mode {
                                let remove_string_length = self.remove_len_if_composing()?;
                                self.set_composition_buffer_string(&commit_str, remove_string_length);
                                self.composition_buffer_type = "fullshape".into();
                                self.record_buffer_char_at_cursor(&char_str);
                            } else {
                                self.set_commit_string(&commit_str);
                            }
                            self.reset_composition();
                        }
                    }
                }
            } else {
                // CB:1493 若沒按下 Shift 鍵
                if full && py_len(&self.composition_char) == 0 {
                    if key_event.is_printable_char() && !(self.phrasemode && (self.is_number_char(key_code) || key_code == VK_SPACE)) {
                        // CB:1498
                        let commit_str = if self.is_symbols_char(key_code) || self.is_number_char(key_code) {
                            self.symbols_char_code_to_fullshape(char_code)
                        } else {
                            self.char_code_to_fullshape(char_code, key_code)?
                        };

                        if !self.composition_buffer_mode {
                            self.set_commit_string(&commit_str);
                            self.reset_composition();
                        } else {
                            if self.lang_mode == ENGLISH_MODE {
                                self.set_commit_string(&commit_str);
                                self.reset_composition_buffer();
                            } else {
                                self.set_composition_buffer_string(&commit_str, 0);
                                self.composition_buffer_type = "fullshape".into();
                                self.record_buffer_char_at_cursor(&char_str);
                            }
                            self.reset_composition();
                        }
                    }
                } else if self.composition_buffer_mode
                    && self.is_composing()
                    && key_event.is_printable_char()
                    && !self.ts.show_candidates
                    && self.composition_char.is_empty()
                {
                    // CB:1517 半形模式
                    self.set_composition_buffer_string(&char_str, 0);
                    self.composition_buffer_type = "english".into();
                    self.record_buffer_char_at_cursor(&char_str);
                    self.reset_composition();
                }
            }
        }

        // CB:1524
        if self.lang_mode == CHINESE_MODE && py_len(&self.composition_char) >= 1 && !self.menumode && !self.multifunctionmode {
            self.showmenu = false;
            if self.ime_dir_name == "chedayi" {
                self.apply_dayi_sel_keys();
            }
            if !self.direct_show_cand && !self.selcandmode && self.last_composition_char_length != py_len(&self.composition_char) {
                self.last_composition_char_length = py_len(&self.composition_char);
                self.is_show_candidates = false;
                self.set_show_candidates(false);
            }

            // CB:1537 按下 ESC 鍵
            if key_code == VK_ESCAPE && (self.ts.show_candidates || py_len(&self.composition_char) > 0) {
                self.last_composition_char_length = 0;
                if !self.direct_show_cand {
                    self.is_show_candidates = false;
                }
                if self.composition_buffer_mode {
                    if !self.composition_char.is_empty() {
                        if !self.selcandmode {
                            let key_length = self.calc_remove_string_length()?;
                            self.remove_composition_buffer_string(key_length, true);
                        }
                        self.reset_composition();
                        self.key_used_state = true;
                    }
                } else {
                    self.reset_composition();
                }
            }

            // CB:1552 刪掉一個字根
            if key_code == VK_BACK {
                if self.homophone_query && self.homophonemode {
                    self.reset_homophone_mode();
                }

                // CB:1560
                let dayi_symbol_back = self.dayisymbolsmode && !self.composition_char.is_empty() && !self.selcandmode;
                if !self.composition_buffer_mode {
                    if dayi_symbol_back {
                        let s = if py_len(&self.composition_char) > 1 { self.dayi_symbol_string.clone() } else { String::new() };
                        self.set_composition_string(&s);
                        self.key_used_state = true;
                    } else if !self.ts.composition_string.is_empty() {
                        let key_length = self.last_key_length()?;
                        let s = py_slice(&self.ts.composition_string, None, Some(-key_length));
                        self.set_composition_string(&s);
                        self.key_used_state = true;
                    }
                } else if dayi_symbol_back && !self.composition_buffer_string.is_empty() {
                    // CB:1573
                    if py_len(&self.composition_char) > 1 {
                        let s = self.dayi_symbol_string.clone();
                        self.set_composition_buffer_string(&s, 1);
                    } else {
                        let n = py_len(&self.dayi_symbol_string);
                        self.remove_composition_buffer_string(n, true);
                    }
                    self.key_used_state = true;
                } else if !self.composition_buffer_string.is_empty() && !self.composition_char.is_empty() && !self.selcandmode {
                    // CB:1579
                    let key_length = self.last_key_length()?;
                    self.remove_composition_buffer_string(key_length, true);
                    self.key_used_state = true;
                }

                // CB:1588
                if self.key_used_state {
                    self.composition_char = py_slice(&self.composition_char, None, Some(-1));
                    self.last_composition_char_length -= 1;
                    self.set_candidate_cursor(0);
                    self.set_candidate_page(0);
                    self.wildcardcandidates = Vec::new();
                    self.wildcardpagecandidates = Vec::new();
                    if !self.direct_show_cand {
                        self.is_show_candidates = false;
                        self.set_show_candidates(false);
                    }
                    if self.composition_char.is_empty() {
                        self.reset_composition();
                    }
                }
            }

            // CB:1602 組字字根超過最大值
            if py_len(&self.composition_char) > self.max_char_length {
                let key_length = self.last_key_length()?;
                if self.composition_buffer_mode {
                    self.remove_composition_buffer_string(key_length, false);
                } else {
                    let s = py_slice(&self.ts.composition_string, None, Some(-key_length));
                    self.set_composition_string(&s);
                }
                self.composition_char = py_slice(&self.composition_char, None, Some(-1));
            }

            // CB:1613
            let cc = self.composition_char.clone();
            if self.homophone_query && self.homophonemode && self.homophone_char == cc {
                candidates = self.homophonecandidates.clone();
            } else if self.cin()?.is_in_char_def(&cc) && self.closemenu && !self.ctrlsymbolsmode && !self.dayisymbolsmode {
                // CB:1615
                candidates = self.sorted_cin_candidates(&cc)?;
                if self.composition_buffer_mode && !self.selcandmode {
                    self.composition_buffer_type = "default".into();
                }
            } else if self.ime_dir_name == "chepinyin"
                && py_list_get(&self.cin_file_list, table_index(self.cfg.sel_cin_type, self.cin_file_list.len()))? == "thpinyin.json"
                && !self.ctrlsymbolsmode
            {
                // CB:1622
                let key = cc.clone() + "1";
                if self.cin()?.is_in_char_def(&key) && self.closemenu && !self.ctrlsymbolsmode {
                    candidates = self.sorted_cin_candidates(&key)?;
                    if self.composition_buffer_mode && !self.selcandmode {
                        self.composition_buffer_type = "default".into();
                    }
                }
            } else if self.full_shape_symbols && self.fsymbols()?.is_in_char_def(&cc) && self.closemenu {
                // CB:1630
                candidates = self.fsymbols()?.get_char_def(&cc).to_vec();
                if self.composition_buffer_mode && !self.selcandmode {
                    self.composition_buffer_type = "fsymbols".into();
                }
            } else if self.msymbols()?.is_in_char_def(&cc) && self.closemenu && self.ctrlsymbolsmode {
                // CB:1634
                candidates = self.msymbols()?.get_char_def(&cc)?.to_vec();
                if self.composition_buffer_mode && !self.selcandmode {
                    self.composition_buffer_type = "msymbols".into();
                }
            } else if self.dayisymbolsmode && self.closemenu {
                // CB:1638
                let key = py_slice(&cc, Some(1), None);
                if self.dsymbols()?.is_in_char_def(&key) {
                    candidates = self.dsymbols()?.get_char_def(&key)?.to_vec();
                    let first = py_list_get(&candidates, 0)?;
                    if self.composition_buffer_mode && !self.selcandmode {
                        self.set_composition_buffer_string(&first, 1);
                        self.composition_buffer_type = "dayisymbols".into();
                    } else {
                        self.set_composition_string(&first);
                    }
                }
            } else if self.support_wildcard && py_in(&self.sel_wildcard_char, &cc) && self.closemenu {
                // CB:1646
                if !self.wildcardcandidates.is_empty() && self.wildcardcomposition_char == cc {
                    candidates = self.wildcardcandidates.clone();
                } else {
                    self.set_candidate_cursor(0);
                    self.set_candidate_page(0);
                    let variable = self.is_variable_wildcard_query();
                    let w = self.cin()?.get_wildcard_char_defs(&cc, &self.sel_wildcard_char, self.cand_max_items, variable)?;
                    self.wildcardcandidates = w;
                    if self.ime_dir_name == "chepinyin"
                        && py_list_get(&self.cin_file_list, table_index(self.cfg.sel_cin_type, self.cin_file_list.len()))? == "thpinyin.json"
                        && self.wildcardcandidates.is_empty()
                    {
                        let w = self.cin()?.get_wildcard_char_defs(&(cc.clone() + "1"), &self.sel_wildcard_char, self.cand_max_items, false)?;
                        self.wildcardcandidates = w;
                    }
                    self.wildcardpagecandidates = Vec::new();
                    self.wildcardcomposition_char = cc.clone();
                    candidates = self.wildcardcandidates.clone();
                    if self.composition_buffer_mode && !self.selcandmode {
                        self.composition_buffer_type = "default".into();
                    }
                }
                self.is_wildcard_chardefs = true;
                if self.sort_by_phrase && !candidates.is_empty() {
                    candidates = self.sort_by_phrase(candidates);
                }
                candidates = self.sort_by_intelligent_select(&cc, candidates)?;
            }
        }

        // CB:1672 組字編輯模式
        if self.composition_buffer_mode
            && self.is_composing()
            && self.composition_char.is_empty()
            && self.closemenu
            && !self.multifunctionmode
            && !self.phrasemode
            && !self.selcandmode
        {
            let mut changelast_commit_string = false;
            if key_code == VK_LEFT {
                if self.composition_buffer_cursor > 0 {
                    self.composition_buffer_cursor -= 1;
                    self.set_composition_cursor(self.composition_buffer_cursor);
                    changelast_commit_string = true;
                }
            } else if key_code == VK_RIGHT {
                if self.composition_buffer_cursor < py_len(&self.composition_buffer_string) {
                    self.composition_buffer_cursor += 1;
                    self.set_composition_cursor(self.composition_buffer_cursor);
                    changelast_commit_string = true;
                }
            } else if key_code == VK_HOME {
                self.composition_buffer_cursor = 0;
                self.set_composition_cursor(self.composition_buffer_cursor);
                changelast_commit_string = true;
            } else if key_code == VK_END {
                self.composition_buffer_cursor = py_len(&self.composition_buffer_string);
                self.set_composition_cursor(self.composition_buffer_cursor);
                changelast_commit_string = true;
            } else if key_code == VK_BACK {
                // CB:1692
                if self.composition_buffer_cursor != 0 && !self.composition_buffer_string.is_empty() && !self.key_used_state {
                    self.buffer_drop_char_at(self.composition_buffer_cursor - 1);
                    self.remove_composition_buffer_string(1, true);
                    changelast_commit_string = true;
                }
                if self.composition_buffer_string.is_empty() {
                    self.composition_buffer_char = IndexMap::new();
                    self.reset_composition();
                    self.reset_composition_buffer();
                    self.temp_english_mode = false;
                }
            } else if key_code == VK_DELETE {
                // CB:1702
                if self.composition_buffer_cursor != py_len(&self.composition_buffer_string) && !self.composition_buffer_string.is_empty() {
                    self.buffer_drop_char_at(self.composition_buffer_cursor);
                    self.remove_composition_buffer_string(1, false);
                    changelast_commit_string = true;
                }
                if self.composition_buffer_string.is_empty() {
                    self.composition_buffer_char = IndexMap::new();
                    self.reset_composition();
                    self.reset_composition_buffer();
                    self.temp_english_mode = false;
                }
            } else if key_code == VK_ESCAPE && !self.key_used_state {
                self.reset_composition();
                self.reset_composition_buffer();
                self.composition_buffer_char = IndexMap::new();
                self.temp_english_mode = false;
            } else if key_code == VK_RETURN {
                let s = self.composition_buffer_string.clone();
                self.set_commit_string(&s);
                self.reset_composition();
                self.reset_composition_buffer();
                self.composition_buffer_char = IndexMap::new();
                self.temp_english_mode = false;
            } else if key_code == VK_DOWN {
                // CB:1723
                self.tempengcandidates = Vec::new();
                let sel_string_pos = if self.composition_buffer_cursor <= py_len(&self.composition_buffer_string) - 1 {
                    self.composition_buffer_cursor
                } else {
                    self.composition_buffer_cursor - 1
                };

                if let Some(sellist) = self.composition_buffer_char.get(&sel_string_pos).cloned() {
                    let (stype, skeys) = sellist;
                    if stype == "msymbols" {
                        self.composition_char =
                            if py_char_at(&skeys, 0)? != "`" { skeys.clone() } else { py_slice(&skeys, Some(1), None) };
                        candidates = self.msymbols()?.get_char_def(&self.composition_char)?.to_vec();
                        self.selcandmode = true;
                    } else if stype == "dayisymbols" {
                        self.composition_char = skeys.clone();
                        candidates = self.dsymbols()?.get_char_def(&py_slice(&skeys, Some(1), None))?.to_vec();
                        self.selcandmode = true;
                    } else if stype == "fsymbols" {
                        self.composition_char = "none".into();
                        candidates = self.fsymbols()?.get_char_def(&skeys).to_vec();
                        self.selcandmode = true;
                    } else if stype == "menusymbols" {
                        self.composition_char = "none".into();
                        candidates = self.symbols()?.get_char_def(&skeys).to_vec();
                        self.selcandmode = true;
                    } else if stype == "menubopomofo" {
                        self.composition_char = "none".into();
                        candidates = self.bopomofolist.clone();
                        self.selcandmode = true;
                    } else if stype == "menuflangs" {
                        self.composition_char = "none".into();
                        candidates = self.flangs()?.get_char_def(&skeys).to_vec();
                        self.selcandmode = true;
                    } else if stype == "menuemoji" {
                        self.composition_char = "none".into();
                        let elist: Vec<&str> = skeys.splitn(3, ',').collect();
                        let e0 = elist.first().copied().unwrap_or("");
                        let e1 = *elist.get(1).ok_or("IndexError: list index out of range")?;
                        candidates = emoji()?.get_char_def(e0, e1)?.to_vec();
                        self.selcandmode = true;
                    } else if stype == "default" {
                        if self.cin()?.is_in_char_def(&skeys) {
                            self.composition_char = skeys.clone();
                            candidates = self.sorted_cin_candidates(&skeys)?;
                            self.selcandmode = true;
                        }
                    } else {
                        // CB:1767
                        let ch = py_char_at(&self.composition_buffer_string, sel_string_pos)?;
                        if self.cin()?.is_have_key(&ch) {
                            let k = self.cin()?.get_key(&ch)?.to_string();
                            self.composition_char = k;
                            let cc = self.composition_char.clone();
                            candidates = self.sorted_cin_candidates(&cc)?;
                            self.selcandmode = true;
                        } else {
                            self.selcandmode = false;
                            if !self.client.is_ui_less {
                                self.is_show_message = true;
                                self.show_message("沒有候選字...");
                            }
                        }
                    }

                    if self.selcandmode {
                        self.is_show_candidates = true;
                        self.can_set_commit_string = false;
                        self.tempengcandidates = candidates.clone();
                    }
                }
            }

            // CB:1787
            if changelast_commit_string && !self.composition_buffer_string.is_empty() && self.composition_buffer_cursor > 0 {
                self.last_commit_string = py_char_at(&self.composition_buffer_string, self.composition_buffer_cursor - 1)?;
            }
        }

        // CB:1791
        if self.selcandmode && !self.composition_char.is_empty() {
            candidates = self.tempengcandidates.clone();
        }

        // CB:1795 候選清單處理
        if (self.lang_mode == CHINESE_MODE && py_len(&self.composition_char) >= 1 && !self.menumode)
            || (self.temp_english_mode && self.is_composing())
        {
            // CB:1797 如果字根首字是符號就直接輸出
            if self.direct_commit_symbol && !self.temp_english_mode && !self.phrasemode && !self.selcandmode {
                // CB:1799 如果是全形標點
                if self.full_shape_symbols && self.fullsymbolsmode {
                    if py_len(&self.composition_char) >= 2 && self.fsymbols()?.is_in_char_def(&py_char_at(&self.composition_char, 0)?) {
                        self.fullsymbolsmode = false;
                        if !self.cin()?.is_in_char_def(&self.composition_char) {
                            if self.composition_buffer_mode {
                                let t = self.composition_buffer_type.clone();
                                let c0 = py_char_at(&self.composition_char, 0)?;
                                let cursor = self.composition_buffer_cursor - 1;
                                self.set_composition_buffer_char(&t, &c0, cursor);
                                self.composition_char = py_slice(&self.composition_char, Some(1), None);
                            } else {
                                self.keep_composition = true;
                                let commit_str = py_slice(&self.ts.composition_string, None, Some(1));
                                let composition_str = py_slice(&self.ts.composition_string, Some(1), None);
                                let composition_char = py_slice(&self.composition_char, Some(1), None);
                                self.set_commit_string(&commit_str);
                                self.composition_char = composition_char;
                                self.set_composition_string(&composition_str);
                                let n = py_len(&self.ts.composition_string);
                                self.set_composition_cursor(n);
                            }
                        }
                        if self.cin()?.is_in_char_def(&self.composition_char) {
                            let cc = self.composition_char.clone();
                            candidates = self.sorted_cin_candidates(&cc)?;
                        }
                    }
                }
                // CB:1821 如果是碼表標點
                let c0 = py_char_at(&self.composition_char, 0)?;
                if self.cin()?.is_in_key_name(&c0) {
                    let kn0 = self.cin()?.get_key_name(&c0).to_string();
                    if self.direct_commit_symbol_list.contains(&kn0) {
                        if !self.cin()?.is_in_char_def(&self.composition_char) {
                            if self.composition_buffer_mode {
                                // CB:1825
                                let mut cursor_pos = self.composition_buffer_cursor;
                                let head = py_slice(&self.composition_char, None, Some(-1));
                                if self.cin()?.is_in_char_def(&head) {
                                    cursor_pos = self.composition_buffer_cursor - py_len(&head);
                                }
                                self.composition_buffer_type = "default".into();
                                let t = self.composition_buffer_type.clone();
                                self.set_composition_buffer_char(&t, &c0, cursor_pos);
                                self.composition_char = py_slice(&self.composition_char, Some(1), None);
                            } else if py_len(&self.composition_char) >= 2 {
                                // CB:1832
                                let c1 = py_char_at(&self.composition_char, 1)?;
                                let kn1 = self.cin()?.get_key_name(&c1).to_string();
                                if !self.direct_commit_symbol_list.contains(&kn1) {
                                    self.keep_composition = true;
                                    let head = py_slice(&self.composition_char, None, Some(1));
                                    let commit_str = self.cin()?.get_key_name(&head).to_string();
                                    let composition_str = py_slice(&self.ts.composition_string, Some(1), None);
                                    let composition_char = py_slice(&self.composition_char, Some(1), None);
                                    self.set_commit_string(&commit_str);
                                    self.composition_char = composition_char;
                                    self.set_composition_string(&composition_str);
                                    let n = py_len(&self.ts.composition_string);
                                    self.set_composition_cursor(n);
                                }
                            }
                        }
                        if self.cin()?.is_in_char_def(&self.composition_char) {
                            let cc = self.composition_char.clone();
                            candidates = self.sorted_cin_candidates(&cc)?;
                        }
                    }
                }
            }

            // CB:1847
            if self.lang_mode == CHINESE_MODE
                && self.dayisymbolsmode
                && py_len(&self.composition_char) == 1
                && (key_code == VK_SPACE || key_code == VK_RETURN)
                && self.cin()?.is_in_char_def(&self.composition_char)
            {
                candidates = self.cin()?.get_char_def(&self.composition_char).to_vec();
                if self.composition_buffer_mode && self.direct_show_cand {
                    self.remove_composition_buffer_string(1, true);
                }
            }

            // CB:1852
            let mut auto_committed_single_candidate = false;
            if !candidates.is_empty() && !self.phrasemode && self.should_auto_commit_single_candidate(&candidates)? {
                let first = py_list_get(&candidates, 0)?;
                self.commit_single_candidate(&first)?;
                auto_committed_single_candidate = true;
                self.ignore_next_space();
            }

            let mut cand_cursor: i64 = 0;
            let mut current_cand_page: i64 = 0;
            let mut pagecandidates: Vec<Vec<String>> = Vec::new();
            let mut cand_count: i64 = 0;
            let mut current_cand_page_count: i64 = 0;

            if !candidates.is_empty() && !self.phrasemode && !auto_committed_single_candidate {
                // CB:1861
                if !self.selcandmode {
                    if !self.direct_show_cand {
                        // CB:1864 EndKey 處理 (拼音、注音)
                        if self.use_end_key {
                            if self.end_key_list.contains(&char_str) && py_len(&self.composition_char) > 1 {
                                if !self.is_show_candidates {
                                    if self.composition_buffer_mode {
                                        let commit_str = py_list_get(&candidates, 0)?;
                                        self.last_commit_string = commit_str.clone();
                                        self.set_output_string(&commit_str)?;
                                        if self.show_phrase && !self.selcandmode {
                                            self.phrasemode = true;
                                        }
                                        self.reset_composition();
                                        self.can_set_commit_string = true;
                                        self.is_show_candidates = false;
                                    } else {
                                        self.is_show_candidates = true;
                                        self.can_use_sel_key = false;
                                    }
                                } else {
                                    self.can_use_sel_key = true;
                                }
                            } else if self.is_show_candidates {
                                self.can_use_sel_key = true;
                            }
                        }

                        // CB:1888 字滿及符號處理 (大易、注音、輕鬆)
                        if self.auto_show_cand_when_max_char || self.dayisymbolsmode {
                            if py_len(&self.composition_char) == self.max_char_length || self.dayisymbolsmode {
                                if !self.is_show_candidates {
                                    if self.composition_buffer_mode {
                                        if self.dayisymbolsmode && py_len(&self.composition_char) != 1 {
                                            let commit_str = py_list_get(&candidates, 0)?;
                                            self.last_commit_string = commit_str.clone();
                                            self.set_output_string(&commit_str)?;
                                            if self.show_phrase && !self.selcandmode {
                                                self.phrasemode = true;
                                            }
                                            self.reset_composition();
                                            self.can_set_commit_string = true;
                                            self.is_show_candidates = false;
                                        }
                                    } else {
                                        self.is_show_candidates = true;
                                        self.can_use_sel_key = false;
                                    }
                                } else if self.ime_dir_name != "chephonetic" {
                                    self.can_use_sel_key = true;
                                }
                            } else if self.is_show_candidates && self.ime_dir_name != "chephonetic" {
                                self.can_use_sel_key = true;
                            }
                        }

                        // CB:1915 按下空白鍵和向下鍵
                        if (key_code == VK_SPACE || key_code == VK_DOWN) && !self.is_show_candidates {
                            if self.composition_buffer_mode && !self.direct_show_cand {
                                if key_code == VK_SPACE {
                                    // CB:1919
                                    let commit_str = py_list_get(&candidates, 0)?;
                                    self.last_commit_string = commit_str.clone();
                                    self.can_use_space_as_page_key = false;

                                    // CB:1924 如果使用萬用字元解碼
                                    if self.is_wildcard_chardefs {
                                        if !self.client.is_ui_less {
                                            self.is_show_message = true;
                                            self.show_message_on_key_up = true;
                                            let m = self.cin()?.get_char_encode(&commit_str);
                                            self.on_key_up_message = m;
                                        }
                                        self.wildcardcandidates = Vec::new();
                                        self.wildcardpagecandidates = Vec::new();
                                        self.is_wildcard_chardefs = false;
                                    }

                                    // CB:1933
                                    if self.ime_reverse_lookup {
                                        let rcin_table = self.tables.rcin.clone();
                                        let rcin_table = rcin_table.borrow();
                                        if let Some(rcin) = &rcin_table.cin {
                                            let message = rcin.get_char_encode(&commit_str);
                                            if message != "查無字根..." && !self.client.is_ui_less {
                                                self.is_show_message = true;
                                                if !self.client.is_metro_app {
                                                    self.show_message_on_key_up = true;
                                                    self.on_key_up_message = message;
                                                } else {
                                                    self.show_message(&message);
                                                }
                                            }
                                        } else if !self.client.is_ui_less {
                                            self.is_show_message = true;
                                            self.show_message_on_key_up = true;
                                            if rcin_table.file_not_exist.unwrap_or(self.r_cin_file_not_exist) {
                                                self.on_key_up_message = "反查字根碼表檔案不存在！".into();
                                            } else {
                                                self.on_key_up_message = "反查字根碼表尚在載入中！".into();
                                            }
                                        }
                                    }

                                    // CB:1952
                                    if self.composition_buffer_mode {
                                        let mut remove_string_length = 0;
                                        if !self.menusymbolsmode {
                                            for c in self.composition_char.chars() {
                                                let c_str = c.to_string();
                                                let cin = self.cin()?;
                                                if cin.is_in_key_name(&c_str) {
                                                    remove_string_length += py_len(cin.get_key_name(&c_str));
                                                } else {
                                                    remove_string_length += 1;
                                                }
                                            }
                                        } else {
                                            remove_string_length = py_len(&self.composition_char) - 1;
                                            self.menusymbolsmode = false;
                                        }
                                        self.set_composition_buffer_string(&commit_str, remove_string_length);
                                        let cc = self.composition_char.clone();
                                        self.record_buffer_char_at_cursor(&cc);
                                    } else {
                                        self.set_commit_string(&commit_str);
                                    }

                                    if self.show_phrase {
                                        self.phrasemode = true;
                                    }
                                    self.reset_composition();
                                    self.is_show_candidates = false;
                                    self.can_set_commit_string = true;
                                } else {
                                    self.is_show_candidates = true;
                                    self.can_set_commit_string = false;
                                }
                            } else {
                                self.is_show_candidates = true;
                                self.can_set_commit_string = false;
                                if key_code == VK_SPACE {
                                    self.can_use_space_as_page_key = false;
                                }
                            }
                        }
                    } else if candidates.len() == 1
                        && !self.selcandmode
                        && !self.multifunctionmode
                        && py_len(&self.composition_char) >= self.max_char_length
                        && self.auto_commit_single_candidate
                    {
                        // CB:1984
                        let commit_str = py_list_get(&candidates, 0)?;
                        let cc = self.composition_char.clone();
                        self.add_intelligent_select_count(&cc, &commit_str)?;
                        self.last_commit_string = commit_str.clone();
                        self.set_output_string(&commit_str)?;
                        if self.show_phrase && !self.selcandmode {
                            self.phrasemode = true;
                        }
                        self.reset_composition();
                        self.ignore_next_space();
                    } else {
                        self.is_show_candidates = true;
                        self.can_set_commit_string = true;
                    }
                }

                // CB:1999
                if self.is_show_candidates {
                    cand_cursor = self.ts.candidate_cursor;
                    current_cand_page_count = pager::page_count(candidates.len(), self.cand_per_page) as i64;
                    current_cand_page = self.current_cand_page;

                    // CB:2006 候選清單分頁
                    if self.is_wildcard_chardefs {
                        if !self.wildcardpagecandidates.is_empty() {
                            pagecandidates = self.wildcardpagecandidates.clone();
                        } else {
                            self.wildcardpagecandidates = pager::paginate(&candidates, self.cand_per_page);
                            pagecandidates = self.wildcardpagecandidates.clone();
                        }
                    } else {
                        pagecandidates = pager::paginate(&candidates, self.cand_per_page);
                    }
                    let (pc, ccp, ccur) = self.clamp_candidate_position(pagecandidates, current_cand_page, cand_cursor);
                    pagecandidates = pc;
                    current_cand_page = ccp;
                    cand_cursor = ccur;
                    let page = py_list_get(&pagecandidates, current_cand_page)?;
                    self.set_candidate_list(page);
                    cand_count = self.ts.candidate_list.len() as i64;

                    // CB:2022
                    self.set_show_candidates(true);

                    self.set_modern_candidate_page_info(current_cand_page, &pagecandidates);
                }

                // CB:2027 多功能前導字元
                if self.multifunctionmode && self.direct_commit_symbol && !self.selcandmode && candidates.len() == 1 {
                    let cand = py_list_get(&candidates, 0)?;
                    if self.composition_buffer_mode {
                        self.set_composition_buffer_string(&cand, 0);
                    } else {
                        self.set_commit_string(&cand);
                    }
                    self.reset_composition();
                    cand_cursor = 0;
                    current_cand_page = 0;
                }

                // CB:2038
                if self.is_show_candidates {
                    self.handle_candidate_keys(
                        key_event,
                        &char_str,
                        char_code,
                        key_code,
                        &mut cand_cursor,
                        &mut current_cand_page,
                        &mut pagecandidates,
                        cand_count,
                        current_cand_page_count,
                    )?;
                }
            } else if !auto_committed_single_candidate {
                // CB:2200 沒有候選字
                let mut keep_no_candidate_message_in_candidate_window = false;
                if (key_code == VK_SPACE || key_code == VK_RETURN) && !self.temp_english_mode {
                    if candidates.is_empty() {
                        if self.multifunctionmode {
                            if self.composition_char == "`" {
                                // CB:2206
                                if self.composition_buffer_mode {
                                    self.composition_buffer_type = "english".into();
                                    let cc = self.composition_char.clone();
                                    self.set_composition_buffer_string(&cc, 1);
                                    self.record_buffer_char_at_cursor(&cc);
                                } else {
                                    let cc = self.composition_char.clone();
                                    self.set_commit_string(&cc);
                                }
                                self.reset_composition();
                            } else if py_slice(&self.composition_char, None, Some(2)) == "`U" {
                                // CB:2215
                                let code_point = CbTs::unicode_input_code_point(&py_slice(&self.composition_char, Some(2), None));
                                if py_len(&self.composition_char) > 2 && code_point.is_none() {
                                    if !self.client.is_ui_less {
                                        self.is_show_message = true;
                                        self.show_message("無效的 Unicode 編碼...");
                                    }
                                } else if py_len(&self.composition_char) > 2 {
                                    // CB:2224
                                    let commit_str = char::from_u32(code_point.unwrap())
                                        .map(String::from)
                                        .ok_or("ValueError: chr() arg not in range")?;
                                    self.last_commit_string = commit_str.clone();
                                    if !self.client.is_ui_less {
                                        self.is_show_message = true;
                                        self.show_message_on_key_up = true;
                                        let m = self.cin()?.get_char_encode(&commit_str);
                                            self.on_key_up_message = m;
                                    }

                                    if self.composition_buffer_mode {
                                        self.composition_buffer_type = "menuunicode".into();
                                        let n = py_len(&self.composition_char);
                                        self.set_composition_buffer_string(&commit_str, n);
                                        let hex = py_slice(&self.composition_char, Some(2), None);
                                        self.record_buffer_char_at_cursor(&hex);
                                    } else {
                                        self.set_commit_string(&commit_str);
                                    }

                                    if self.show_phrase {
                                        self.phrasemode = true;
                                    }
                                    self.reset_composition();
                                } else if !self.client.is_ui_less {
                                    self.is_show_message = true;
                                    self.show_message("請輸入 Unicode 編碼...");
                                }
                            }
                        } else {
                            // CB:2246
                            keep_no_candidate_message_in_candidate_window = self.should_keep_no_candidate_message_in_candidate_window();
                            if keep_no_candidate_message_in_candidate_window {
                                self.set_no_candidate_message_in_candidate_window(true);
                            } else if !self.client.is_ui_less {
                                self.is_show_message = true;
                                self.show_message("查無組字...");
                            }
                            if self.play_sound_when_non_cand {
                                env::play_sound("alert");
                            }
                        }
                    }
                } else if self.use_end_key && self.end_key_list.contains(&char_str) {
                    // CB:2254
                    if candidates.is_empty() && py_len(&self.composition_char) != 1 && self.composition_char != char_str_low {
                        keep_no_candidate_message_in_candidate_window = self.should_keep_no_candidate_message_in_candidate_window();
                        if keep_no_candidate_message_in_candidate_window {
                            self.set_no_candidate_message_in_candidate_window(true);
                        } else if !self.client.is_ui_less {
                            self.is_show_message = true;
                            self.show_message("查無組字...");
                        }
                        if self.play_sound_when_non_cand {
                            env::play_sound("alert");
                        }
                    }
                }

                // CB:2266
                if !keep_no_candidate_message_in_candidate_window {
                    self.set_show_candidates(false);
                    self.is_show_candidates = false;
                }
            }
        }

        // CB:2271 聯想字模式
        if phrase_data().borrow().phrase.is_none() {
            self.phrasemode = false;
        }

        if self.show_phrase && self.phrasemode {
            if self.is_number_char(key_code) && key_event.is_key_down(VK_SHIFT) && self.ime_dir_name != "chedayi" {
                char_code = key_code;
                char_str = char::from_u32(char_code).map(String::from).unwrap_or_default();
            }
            self.phrase_mode_keys(key_event, &char_str, char_code, key_code, &char_str_low, cin_has_char_str_low, &mut candidates)?;
        }

        // CB:2454
        if self.lang_mode == CHINESE_MODE
            && self.is_composing()
            && !self.ts.show_candidates
            && self.closemenu
            && !self.multifunctionmode
            && !self.phrasemode
            && !self.selcandmode
            && key_code == VK_RETURN
            && self.cin()?.is_in_key_name(&self.composition_char)
            && py_len(&self.composition_char) == 1
            && self.is_symbols_and_number_char(&self.composition_char)?
        {
            let s = self.ts.composition_string.clone();
            self.set_commit_string(&s);
            self.reset_composition();
            self.reset_composition_buffer();
        }

        // CB:2462
        if self.auto_move_cursor_in_brackets && self.composition_buffer_mode {
            if key_code == VK_SPACE || key_code == VK_RETURN {
                let mut move_cursor = false;
                if self.bracket_symbol_list.contains(&self.last_commit_string) {
                    move_cursor = true;
                } else if py_len(&self.composition_buffer_string) >= 2 && self.composition_buffer_cursor >= 2 {
                    let cur = self.composition_buffer_cursor;
                    let bracket_str =
                        py_char_at(&self.composition_buffer_string, cur - 2)? + &py_char_at(&self.composition_buffer_string, cur - 1)?;
                    if self.bracket_symbol_list.contains(&bracket_str) {
                        move_cursor = true;
                    }
                }
                if move_cursor {
                    self.composition_buffer_cursor -= 1;
                    self.set_composition_cursor(self.composition_buffer_cursor);
                    self.reset_composition();
                    self.last_commit_string = String::new();
                }
            } else if py_len(&self.composition_buffer_string) >= 2
                && self.composition_buffer_cursor >= 2
                && !self.ts.show_candidates
                && key_code != VK_RIGHT
            {
                self.move_cursor_in_brackets()?;
            }
        }

        // CB:2480
        if !self.can_use_space_as_page_key {
            self.can_use_space_as_page_key = true;
        }

        if !self.closemenu {
            self.closemenu = true;
        }

        // CB:2492
        let header_label = header_composition_label(&self.ime_dir_name);
        let force_header_composition = header_label.is_some();
        if self.hide_composition || force_header_composition {
            let header_text =
                if !self.ts.composition_string.is_empty() { self.ts.composition_string.clone() } else { self.composition_header_text() };
            if !header_text.is_empty() {
                self.ts.current_reply.insert("compositionString".into(), json!(""));
                self.ts.current_reply.insert("compositionCursor".into(), json!(0));
                let label = if force_header_composition {
                    if !self.ime_display_name.is_empty() { self.ime_display_name.clone() } else { header_label.unwrap().to_string() }
                } else {
                    self.hide_composition_label.clone()
                };
                // CB:2508
                if !self.ts.current_reply.get("candidateHeader").map(py_truthy).unwrap_or(false) {
                    let header = if !label.is_empty() { format!("{} {}", label, header_text) } else { header_text.clone() };
                    self.ts.current_reply.insert("candidateHeader".into(), json!(header));
                }
                if !self.ts.current_reply.contains_key("candidateList") {
                    if force_header_composition && !self.is_composition_char_prefix() {
                        if !self.ts.current_reply.contains_key("candidateMessage") {
                            self.set_no_candidate_message_in_candidate_window(false);
                        }
                        self.set_candidate_list(Vec::new());
                    } else {
                        let list = if self.ts.show_candidates && !self.ts.candidate_list.is_empty() {
                            self.ts.candidate_list.clone()
                        } else {
                            Vec::new()
                        };
                        self.set_candidate_list(list);
                    }
                }
                self.set_show_candidates(true);
                if !self.ts.current_reply.get("candidatePageInfo").map(py_truthy).unwrap_or(false) {
                    self.ts.current_reply.insert("candidatePageInfo".into(), json!(""));
                }
            }
        }

        // CB:2522
        self.ensure_modern_candidate_header();

        if self.ts.current_reply.contains_key("candidateList") || self.ts.current_reply.contains_key("showCandidates") {
            self.customize_candidate_ui(false);
        }

        Ok(true)
    }

    /// CB:2038-2199: keys while the candidate window is shown (the body of
    /// `if cbTS.isShowCandidates:` after the list was paginated).
    #[allow(clippy::too_many_arguments)]
    fn handle_candidate_keys(
        &mut self,
        key_event: &KeyEvent,
        char_str: &str,
        char_code: u32,
        key_code: u32,
        cand_cursor: &mut i64,
        current_cand_page: &mut i64,
        pagecandidates: &mut Vec<Vec<String>>,
        cand_count: i64,
        current_cand_page_count: i64,
    ) -> Result<(), String> {
        // CB:2040 使用選字鍵執行項目或輸出候選字
        if self.is_in_sel_keys(char_code) && !key_event.is_key_down(VK_SHIFT) && self.can_use_sel_key {
            if !self.homophoneselpinyinmode {
                let i = if self.ime_dir_name == "chedayi" {
                    py_str_index(&self.sel_keys, char_str)? + 1
                } else {
                    py_str_index(&self.sel_keys, char_str)?
                };
                if i < self.cand_per_page && i < self.ts.candidate_list.len() as i64 {
                    // CB:2047
                    let commit_str = py_list_get(&self.ts.candidate_list, i)?;
                    let cc = self.composition_char.clone();
                    self.add_intelligent_select_count(&cc, &commit_str)?;
                    self.last_commit_string = commit_str.clone();
                    self.set_output_string(&commit_str)?;
                    if self.show_phrase && !self.selcandmode {
                        self.phrasemode = true;
                    }
                    self.reset_composition();
                    *cand_cursor = 0;
                    *current_cand_page = 0;

                    if !self.direct_show_cand {
                        self.can_set_commit_string = true;
                        self.is_show_candidates = false;
                    }
                }
            } else {
                // CB:2064
                let local = py_str_index(&self.sel_keys, char_str)? + if self.ime_dir_name == "chedayi" { 1 } else { 0 };
                let i = *current_cand_page * self.cand_per_page + local;
                let hcin_table = self.tables.hcin.clone();
                let hcin_table = hcin_table.borrow();
                if let Some(hcin) = &hcin_table.cin {
                    let key_list = hcin.get_key_list(&self.homophone_str);
                    if local < self.ts.candidate_list.len() as i64 && i < key_list.len() as i64 {
                        *cand_cursor = 0;
                        *current_cand_page = 0;
                        self.homophoneselpinyinmode = false;
                        self.homophonemode = true;
                        self.homophone_char = self.composition_char.clone();
                        self.is_homophone_chardefs = true;
                        self.homophonecandidates = hcin.get_char_def(&py_list_get(&key_list, i)?)?.to_vec();
                        *pagecandidates = pager::paginate(&self.homophonecandidates, self.cand_per_page);
                        let page = py_list_get(pagecandidates, *current_cand_page)?;
                        self.set_candidate_list(page);
                    }
                }
            }
        } else if key_code == VK_UP {
            // CB:2080 游標上移
            if (*cand_cursor - self.cand_per_row) < 0 {
                if *current_cand_page > 0 {
                    *current_cand_page -= 1;
                    *cand_cursor = 0;
                }
            } else if (*cand_cursor - self.cand_per_row) >= 0 {
                *cand_cursor -= self.cand_per_row;
            }
        } else if key_code == VK_DOWN && self.can_set_commit_string {
            // CB:2088 游標下移
            if (*cand_cursor + self.cand_per_row) >= self.cand_per_page {
                if (*current_cand_page + 1) < current_cand_page_count {
                    *current_cand_page += 1;
                    *cand_cursor = 0;
                }
            } else if (*cand_cursor + self.cand_per_row) < py_list_get(pagecandidates, *current_cand_page)?.len() as i64 {
                *cand_cursor += self.cand_per_row;
            }
        } else if key_code == VK_LEFT {
            if *cand_cursor > 0 {
                *cand_cursor -= 1;
            } else if *current_cand_page > 0 {
                *current_cand_page -= 1;
                *cand_cursor = 0;
            }
        } else if key_code == VK_RIGHT {
            if (*cand_cursor + 1) < cand_count {
                *cand_cursor += 1;
            } else if (*current_cand_page + 1) < current_cand_page_count {
                *current_cand_page += 1;
                *cand_cursor = 0;
            }
        } else if key_code == VK_HOME {
            *cand_cursor = 0;
        } else if key_code == VK_END {
            *cand_cursor = py_list_get(pagecandidates, *current_cand_page)?.len() as i64 - 1;
        } else if key_code == VK_PRIOR {
            if *current_cand_page > 0 {
                *current_cand_page -= 1;
                *cand_cursor = 0;
            }
        } else if key_code == VK_NEXT {
            if (*current_cand_page + 1) < current_cand_page_count {
                *current_cand_page += 1;
                *cand_cursor = 0;
            }
        } else if self.homophone_query
            && !self.homophonemode
            && !self.multifunctionmode
            && !self.fullsymbolsmode
            && key_code == VK_OEM_3
            && !self.homophone_key_is_root()
        {
            // CB:2122 同音字查詢啟用下按下`鍵
            let hcin_table = self.tables.hcin.clone();
            let hcin_table = hcin_table.borrow();
            if let Some(hcin) = &hcin_table.cin {
                let commit_str = py_list_get(&self.ts.candidate_list, *cand_cursor)?;
                if hcin.is_have_key(&commit_str) {
                    *cand_cursor = 0;
                    *current_cand_page = 0;
                    if hcin.get_key_list(&commit_str).len() > 1 {
                        self.homophonemode = true;
                        self.homophoneselpinyinmode = true;
                        self.homophone_char = self.composition_char.clone();
                        self.homophone_str = commit_str.clone();
                        self.homophonecandidates = hcin.get_key_name_list(&hcin.get_key_list(&commit_str));
                    } else {
                        self.homophonemode = true;
                        self.homophone_char = self.composition_char.clone();
                        self.is_homophone_chardefs = true;
                        self.homophonecandidates = hcin.get_char_def(hcin.get_key(&commit_str)?)?.to_vec();
                    }
                    *pagecandidates = pager::paginate(&self.homophonecandidates, self.cand_per_page);
                    let page = py_list_get(pagecandidates, *current_cand_page)?;
                    self.set_candidate_list(page);
                }
            } else if !self.client.is_ui_less {
                self.is_show_message = true;
                self.show_message_on_key_up = true;
                if hcin_table.file_not_exist.unwrap_or(false) {
                    self.on_key_up_message = "同音字碼表檔案不存在！".into();
                } else {
                    self.on_key_up_message = "同音字碼表尚在載入中！".into();
                }
            }
        } else if (key_code == VK_RETURN || (key_code == VK_SPACE && !self.switch_page_with_space)) && self.can_set_commit_string {
            // CB:2151 按下 Enter 鍵或空白鍵
            if !self.homophoneselpinyinmode {
                let commit_str = py_list_get(&self.ts.candidate_list, *cand_cursor)?;
                let cc = self.composition_char.clone();
                self.add_intelligent_select_count(&cc, &commit_str)?;
                self.last_commit_string = commit_str.clone();
                self.set_output_string(&commit_str)?;
                if self.show_phrase && !self.selcandmode {
                    self.phrasemode = true;
                    if key_code == VK_SPACE {
                        self.can_use_space_as_page_key = false;
                    }
                }
                self.reset_composition();
                *cand_cursor = 0;
                *current_cand_page = 0;

                if !self.direct_show_cand {
                    self.is_show_candidates = false;
                }
            } else {
                // CB:2172
                let i = *current_cand_page * self.cand_per_page + *cand_cursor;
                let hcin_table = self.tables.hcin.clone();
                let hcin_table = hcin_table.borrow();
                if let Some(hcin) = &hcin_table.cin {
                    let key_list = hcin.get_key_list(&self.homophone_str);
                    if i < key_list.len() as i64 {
                        self.homophoneselpinyinmode = false;
                        self.homophonemode = true;
                        self.homophone_char = self.composition_char.clone();
                        self.is_homophone_chardefs = true;
                        self.homophonecandidates = hcin.get_char_def(&py_list_get(&key_list, i)?)?.to_vec();
                        *cand_cursor = 0;
                        *current_cand_page = 0;
                        *pagecandidates = pager::paginate(&self.homophonecandidates, self.cand_per_page);
                        let page = py_list_get(pagecandidates, *current_cand_page)?;
                        self.set_candidate_list(page);
                    }
                }
            }
        } else if key_code == VK_SPACE && self.switch_page_with_space {
            // CB:2183 按下空白鍵
            if self.can_use_space_as_page_key {
                if (*current_cand_page + 1) < current_cand_page_count {
                    *current_cand_page += 1;
                    *cand_cursor = 0;
                } else {
                    *current_cand_page = 0;
                    *cand_cursor = 0;
                }
            }
        } else if !self.ctrlsymbolsmode {
            // CB:2191 按下其它鍵，先將候選字游標位址及目前頁數歸零
            *cand_cursor = 0;
            *current_cand_page = 0;
        }
        // CB:2195 更新選字視窗游標位置及頁數
        self.set_candidate_cursor(*cand_cursor);
        self.set_candidate_page(*current_cand_page);
        let page = py_list_get(pagecandidates, *current_cand_page)?;
        self.set_candidate_list(page);
        self.set_modern_candidate_page_info(*current_cand_page, pagecandidates);
        Ok(())
    }

    /// CB:2280-2452: the phrase (聯想字) candidates, inside
    /// `if cbTS.showPhrase and cbTS.phrasemode:`.
    fn phrase_mode_keys(
        &mut self,
        key_event: &KeyEvent,
        char_str: &str,
        char_code: u32,
        key_code: u32,
        char_str_low: &str,
        cin_has_char_str_low: bool,
        candidates: &mut Vec<String>,
    ) -> Result<(), String> {
        // CB:2280
        let last = self.last_commit_string.clone();
        let phrasecandidates = self.phrase_suggestions(&last);

        if phrasecandidates.is_empty() {
            // CB:2450
            self.phrasemode = false;
            self.is_show_phrase_candidates = false;
            return Ok(());
        }

        // CB:2283
        let mut cand_cursor = self.ts.candidate_cursor;
        let current_cand_page_count = pager::page_count(phrasecandidates.len(), self.cand_per_page) as i64;
        let mut current_cand_page = self.current_cand_page;

        self.can_set_phrase_commit_string = self.is_show_phrase_candidates;

        // CB:2294 候選清單分頁
        let pagecandidates = pager::paginate(&phrasecandidates, self.cand_per_page);
        let (pc, ccp, ccur) = self.clamp_candidate_position(pagecandidates, current_cand_page, cand_cursor);
        let mut pagecandidates = pc;
        current_cand_page = ccp;
        cand_cursor = ccur;
        let page = py_list_get(&pagecandidates, current_cand_page)?;
        self.set_candidate_list(page);
        let cand_count = self.ts.candidate_list.len() as i64;
        self.set_show_candidates(true);

        let in_sel = self.is_in_sel_keys(char_code);
        let shift = key_event.is_key_down(VK_SHIFT);
        let dayi = self.ime_dir_name == "chedayi";
        // CB:2302 使用選字鍵執行項目或輸出候選字
        if (in_sel && shift && !dayi) || (in_sel && !shift && dayi) {
            if self.is_show_phrase_candidates {
                let i = if dayi { py_str_index(&self.sel_keys, char_str)? + 1 } else { py_str_index(&self.sel_keys, char_str)? };
                if i < self.cand_per_page && i < self.ts.candidate_list.len() as i64 {
                    let commit_str = py_list_get(&self.ts.candidate_list, i)?;
                    self.composition_buffer_type = "phrase".into();
                    self.set_output_string(&commit_str)?;

                    self.phrasemode = false;
                    self.is_show_phrase_candidates = false;

                    self.reset_composition();
                    cand_cursor = 0;
                    current_cand_page = 0;

                    if !self.direct_show_cand {
                        self.can_set_commit_string = true;
                        self.is_show_candidates = false;
                    }
                }
            } else {
                self.is_show_phrase_candidates = true;
            }
        } else if key_code == VK_UP {
            // CB:2325
            if (cand_cursor - self.cand_per_row) < 0 {
                if current_cand_page > 0 {
                    current_cand_page -= 1;
                    cand_cursor = 0;
                }
            } else if (cand_cursor - self.cand_per_row) >= 0 {
                cand_cursor -= self.cand_per_row;
            }
        } else if key_code == VK_DOWN && self.can_set_commit_string {
            if (cand_cursor + self.cand_per_row) >= self.cand_per_page {
                if (current_cand_page + 1) < current_cand_page_count {
                    current_cand_page += 1;
                    cand_cursor = 0;
                }
            } else if (cand_cursor + self.cand_per_row) < py_list_get(&pagecandidates, current_cand_page)?.len() as i64 {
                cand_cursor += self.cand_per_row;
            }
        } else if key_code == VK_LEFT {
            if cand_cursor > 0 {
                cand_cursor -= 1;
            } else if current_cand_page > 0 {
                current_cand_page -= 1;
                cand_cursor = 0;
            }
        } else if key_code == VK_RIGHT {
            if (cand_cursor + 1) < cand_count {
                cand_cursor += 1;
            } else if (current_cand_page + 1) < current_cand_page_count {
                current_cand_page += 1;
                cand_cursor = 0;
            }
        } else if key_code == VK_HOME {
            cand_cursor = 0;
        } else if key_code == VK_END {
            cand_cursor = py_list_get(&pagecandidates, current_cand_page)?.len() as i64 - 1;
        } else if key_code == VK_PRIOR {
            if current_cand_page > 0 {
                current_cand_page -= 1;
                cand_cursor = 0;
            }
        } else if key_code == VK_NEXT {
            if (current_cand_page + 1) < current_cand_page_count {
                current_cand_page += 1;
                cand_cursor = 0;
            }
        } else if key_code == VK_SPACE && !self.switch_page_with_space {
            // CB:2367
            if self.is_show_phrase_candidates {
                let commit_str = py_list_get(&self.ts.candidate_list, cand_cursor)?;
                self.composition_buffer_type = "phrase".into();
                self.set_output_string(&commit_str)?;

                self.phrasemode = false;
                self.is_show_phrase_candidates = false;

                self.reset_composition();
                cand_cursor = 0;
                current_cand_page = 0;

                if !self.direct_show_cand {
                    self.is_show_candidates = false;
                }
            }
        } else if key_code == VK_SPACE && self.switch_page_with_space {
            // CB:2383
            if self.can_use_space_as_page_key {
                if (current_cand_page + 1) < current_cand_page_count {
                    current_cand_page += 1;
                    cand_cursor = 0;
                } else {
                    current_cand_page = 0;
                    cand_cursor = 0;
                }
            }
        } else if self.can_set_phrase_commit_string || self.multifunctionmode || key_code == VK_ESCAPE {
            // CB:2391 按下其它鍵
            self.phrasemode = false;
            self.is_show_phrase_candidates = false;
            self.reset_composition();
            cand_cursor = 0;
            current_cand_page = 0;

            // charStrLow is not recomputed after the Shift+digit remap (CB:2276)
            let outer_low = char_str_low.to_string();
            if key_code != VK_ESCAPE && cin_has_char_str_low && !key_event.is_key_down(VK_SHIFT) {
                // CB:2400
                self.composition_char = outer_low.clone();
                let mut keyname = self.cin()?.get_key_name(&outer_low).to_string();

                if self.ime_dir_name == "chedayi" {
                    if self.sel_dayi_symbol_char_type == 0 {
                        if self.composition_char == "=" {
                            keyname = self.dayi_symbol_string.clone();
                            self.dayisymbolsmode = true;
                        }
                    } else if self.composition_char == "'" {
                        keyname = self.dayi_symbol_string.clone();
                        self.dayisymbolsmode = true;
                    }
                }

                if !self.composition_buffer_mode {
                    self.set_composition_string(&keyname);
                    let n = py_len(&self.ts.composition_string);
                    self.set_composition_cursor(n);
                }

                // CB:2417
                if self.direct_show_cand && !self.dayisymbolsmode {
                    if self.cin()?.is_in_char_def(&self.composition_char) {
                        let cc = self.composition_char.clone();
                        *candidates = self.sorted_cin_candidates(&cc)?;
                    }
                    if !candidates.is_empty() {
                        pagecandidates = pager::paginate(candidates, self.cand_per_page);
                        let page = py_list_get(&pagecandidates, current_cand_page)?;
                        self.set_candidate_list(page);
                        self.set_modern_candidate_page_info(current_cand_page, &pagecandidates);
                        self.set_show_candidates(true);
                    }
                }
            } else if py_len(&self.composition_char) == 0 && char_str == "`" {
                // CB:2428
                self.composition_char.push_str(char_str);
                self.multifunctionmode = true;
                if !self.composition_buffer_mode {
                    let cc = self.composition_char.clone();
                    self.set_composition_string(&cc);
                }
            } else if key_event.is_printable_char() && !key_event.is_key_down(VK_SHIFT) && self.shape_mode == HALFSHAPE_MODE {
                // CB:2433
                if self.composition_buffer_mode {
                    self.set_composition_buffer_string(char_str, 0);
                } else {
                    self.set_commit_string(char_str);
                }
            }
        }

        // CB:2442 更新選字視窗游標位置及頁數
        if self.phrasemode {
            self.set_candidate_cursor(cand_cursor);
            self.set_candidate_page(current_cand_page);
            let page = py_list_get(&pagecandidates, current_cand_page)?;
            self.set_candidate_list(page);
            self.set_modern_candidate_page_info(current_cand_page, &pagecandidates);
        }

        if self.show_phrase && self.phrasemode {
            self.is_show_phrase_candidates = true;
        }
        Ok(())
    }
}
