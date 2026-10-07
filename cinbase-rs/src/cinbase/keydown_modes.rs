//! The onKeyDown helpers CB:573-1011: `_fillMSymbolsBufferChar`,
//! `_handleMSymbolsInMultifunctionMode`, `_handleCtrlSymbols` and
//! `_handleMenuMode`, translated line by line (`// CB:<line>` markers).

use super::pyutil::{py_char_at, py_in, py_len, py_list_get, py_slice, py_str_index};
use super::*;
use crate::keycodes::*;
use crate::pager;

impl CbTs {
    /// CB:573 _fillMSymbolsBufferChar(commitStrList, compositionCharOffset=0):
    /// find the committed symbol at the end of the buffer, then record the
    /// key of each of its chars.
    pub fn fill_m_symbols_buffer_char(&mut self, commit_str_list: &[String], composition_char_offset: i64) -> Result<(), String> {
        let cur = self.composition_buffer_cursor;
        let buf = self.composition_buffer_string.clone();
        let last1 = py_char_at(&buf, cur - 1)?;
        let commit_str = if commit_str_list.contains(&last1) {
            last1
        } else {
            let last2 = py_char_at(&buf, cur - 2)? + &last1;
            if commit_str_list.contains(&last2) {
                last2
            } else {
                return Ok(());
            }
        };
        let base = cur - py_len(&commit_str);
        for i in 0..py_len(&commit_str) {
            let c_char = py_char_at(&self.composition_char, i + composition_char_offset)?;
            let t = self.composition_buffer_type.clone();
            self.set_composition_buffer_char(&t, &c_char, base + i + 1);
        }
        Ok(())
    }

    /// CB:593 _handleMSymbolsInMultifunctionMode.
    /// Returns (should_early_return, updated_candidates_or_None).
    pub fn handle_m_symbols_in_multifunction_mode(
        &mut self,
        key_event: &KeyEvent,
        char_str: &str,
        cin_has_char_str_low: bool,
    ) -> Result<(bool, Option<Vec<String>>), String> {
        // CB:599
        let mut candidates: Option<Vec<String>> = None;

        // CB:602
        let key1 = py_slice(&self.composition_char, Some(1), None);
        if self.msymbols()?.is_in_char_def(&key1) && self.closemenu && py_len(&self.composition_char) >= 2 {
            let cands = self.msymbols()?.get_char_def(&key1)?.to_vec();
            candidates = Some(cands.clone());
            if self.composition_buffer_mode {
                // CB:605
                if char_str == "`" && self.menusymbolsmode {
                    self.composition_buffer_type = "msymbols".into();
                    let composition_char_offset = if py_char_at(&self.composition_char, 0)? == "`" { 1 } else { 0 };
                    self.fill_m_symbols_buffer_char(&cands, composition_char_offset)?;
                    self.reset_composition();
                    self.menusymbolsmode = false;
                    self.multifunctionmode = true;
                    self.composition_char = "`".into();
                    let n = if self.direct_show_cand && !self.direct_out_m_symbols { 1 } else { 0 };
                    self.set_composition_buffer_string(char_str, n);
                } else {
                    // CB:615
                    if py_len(&self.composition_buffer_string) >= 2 {
                        let cur = self.composition_buffer_cursor;
                        let prev_str = py_char_at(&self.composition_buffer_string, cur - 2)? + &py_char_at(&self.composition_buffer_string, cur - 1)?;
                        if prev_str == py_list_get(&cands, 0)? {
                            self.remove_composition_buffer_string(1, true);
                        }
                    }
                    self.composition_buffer_type = "msymbols".into();
                    let first = py_list_get(&cands, 0)?;
                    self.set_composition_buffer_string(&first, 1);
                }
            } else {
                // CB:623
                if char_str == "`" && self.menusymbolsmode {
                    let commit_str = self.ts.composition_string.clone();
                    self.reset_composition();
                    if self.direct_out_m_symbols {
                        self.set_commit_string(&commit_str);
                        self.keep_composition = true;
                        self.keep_type = "menusymbols".into();
                    }
                    self.menusymbolsmode = false;
                    self.multifunctionmode = true;
                    self.composition_char = "`".into();
                    self.set_composition_string("`");
                    if self.direct_out_m_symbols {
                        return Ok((true, None));
                    }
                } else {
                    let first = py_list_get(&cands, 0)?;
                    self.set_composition_string(&first);
                }
                // CB:638
                let n = py_len(&self.ts.composition_string);
                self.set_composition_cursor(n);
            }
        }

        // CB:642 directCommitSymbol
        if !self.menusymbolsmode && self.direct_commit_symbol {
            let key1 = py_slice(&self.composition_char, Some(1), None);
            if self.msymbols()?.is_in_char_def(&key1) {
                self.menusymbolsmode = true;
            }
        } else if self.menusymbolsmode && self.direct_commit_symbol && key_event.is_printable_char() {
            // CB:646
            let key = py_slice(&self.composition_char, Some(1), None) + char_str;
            if !self.msymbols()?.is_in_char_def(&key) && cin_has_char_str_low {
                if !self.composition_buffer_mode {
                    let s = self.ts.composition_string.clone();
                    self.set_commit_string(&s);
                    self.reset_composition();
                    self.keep_composition = true;
                } else {
                    self.composition_buffer_type = "msymbols".into();
                    let key1 = py_slice(&self.composition_char, Some(1), None);
                    let commit_str_list = self.msymbols()?.get_char_def(&key1)?.to_vec();
                    let composition_char_offset = if py_char_at(&self.composition_char, 0)? == "`" { 1 } else { 0 };
                    self.fill_m_symbols_buffer_char(&commit_str_list, composition_char_offset)?;
                    self.reset_composition();
                    self.menusymbolsmode = false;
                }
            }
        } else if !self.menusymbolsmode && !self.direct_commit_symbol {
            // CB:658
            let key1 = py_slice(&self.composition_char, Some(1), None);
            if self.msymbols()?.is_in_char_def(&key1) {
                self.menusymbolsmode = true;
            }
        }

        Ok((false, candidates))
    }

    /// CB:664 _handleCtrlSymbols
    pub fn handle_ctrl_symbols(&mut self, key_event: &KeyEvent, char_str: &str, key_code: u32, cin_has_char_str_low: bool) -> Result<(), String> {
        // CB:668 Ctrl+symbol key: enter / advance / wrap ctrlsymbolsmode
        if self.lang_mode == CHINESE_MODE && key_event.is_key_down(VK_CONTROL) {
            if self.is_ctrl_symbols_char(key_code) {
                if self.msymbols()?.is_in_char_def(char_str) && self.closemenu && !self.multifunctionmode {
                    if self.homophone_query && self.homophonemode {
                        self.reset_homophone_mode();
                    }
                    if !self.composition_buffer_mode {
                        // CB:674
                        let joined = self.composition_char.clone() + char_str;
                        if !self.ctrlsymbolsmode {
                            self.ctrlsymbolsmode = true;
                            self.composition_char = char_str.to_string();
                        } else if self.msymbols()?.is_in_char_def(&joined) {
                            self.composition_char.push_str(char_str);
                        } else if self.ctrlsymbolsmode && !self.composition_char.is_empty() {
                            let commit_str = self.ts.composition_string.clone();
                            self.reset_composition();
                            if self.direct_out_m_symbols {
                                self.set_commit_string(&commit_str);
                                self.keep_composition = true;
                                self.keep_type = "ctrlsymbols".into();
                                self.ctrlsymbolsmode = true;
                            }
                            self.composition_char = char_str.to_string();
                        }
                        let candidates = self.msymbols()?.get_char_def(&self.composition_char)?.to_vec();
                        let first = py_list_get(&candidates, 0)?;
                        self.set_composition_string(&first);
                    } else {
                        // CB:691
                        let joined = self.composition_char.clone() + char_str;
                        if !self.ctrlsymbolsmode && self.composition_char.is_empty() {
                            self.ctrlsymbolsmode = true;
                            self.composition_char = char_str.to_string();
                            let candidates = self.msymbols()?.get_char_def(&self.composition_char)?.to_vec();
                            let first = py_list_get(&candidates, 0)?;
                            self.set_composition_buffer_string(&first, 0);
                        } else if self.msymbols()?.is_in_char_def(&joined) {
                            let candidates = self.msymbols()?.get_char_def(&self.composition_char)?.to_vec();
                            let n = py_len(&py_list_get(&candidates, 0)?);
                            self.remove_composition_buffer_string(n, true);
                            self.composition_char.push_str(char_str);
                            let candidates = self.msymbols()?.get_char_def(&self.composition_char)?.to_vec();
                            let first = py_list_get(&candidates, 0)?;
                            self.set_composition_buffer_string(&first, 0);
                        } else if self.ctrlsymbolsmode && !self.composition_char.is_empty() {
                            let remove_string_length =
                                if self.direct_show_cand && !self.direct_out_m_symbols { self.calc_remove_string_length()? } else { 0 };
                            self.composition_buffer_type = "msymbols".into();
                            let commit_str_list = self.msymbols()?.get_char_def(&self.composition_char)?.to_vec();
                            self.fill_m_symbols_buffer_char(&commit_str_list, 0)?;
                            self.composition_char = char_str.to_string();
                            let candidates = self.msymbols()?.get_char_def(&self.composition_char)?.to_vec();
                            let first = py_list_get(&candidates, 0)?;
                            self.set_composition_buffer_string(&first, remove_string_length);
                        }
                    }
                    // CB:713 a new symbol list: cursor and page start over
                    self.set_candidate_cursor(0);
                    self.set_candidate_page(0);
                    if self.ime_dir_name == "chedayi" && py_in(char_str, "'[]-\\") {
                        self.can_use_sel_key = false;
                    }
                }
            }
        }

        // CB:720 Enter commits current ctrlsymbols composition
        if self.ctrlsymbolsmode && key_code == VK_RETURN && self.is_composing() && !self.ts.show_candidates {
            let s = self.ts.composition_string.clone();
            self.set_commit_string(&s);
            self.reset_composition();
            self.reset_composition_buffer();
        }

        // CB:726 Non-Ctrl CIN key when directCommitSymbol: auto-commit and exit ctrlsymbolsmode
        if self.ctrlsymbolsmode && self.direct_commit_symbol && !key_event.is_key_down(VK_CONTROL) && key_event.is_printable_char() {
            let joined = self.composition_char.clone() + char_str;
            if !self.msymbols()?.is_in_char_def(&joined) && cin_has_char_str_low {
                if !self.composition_buffer_mode {
                    let s = self.ts.composition_string.clone();
                    self.set_commit_string(&s);
                    self.reset_composition();
                    self.keep_composition = true;
                } else {
                    self.composition_buffer_type = "msymbols".into();
                    let commit_str_list = self.msymbols()?.get_char_def(&self.composition_char)?.to_vec();
                    self.fill_m_symbols_buffer_char(&commit_str_list, 0)?;
                    self.reset_composition();
                }
                self.ctrlsymbolsmode = false;
            }
        }
        Ok(())
    }

    /// CB:739 _handleMenuMode: the `M/`E function menu. Returns the (possibly
    /// updated) candidates.
    pub fn handle_menu_mode(
        &mut self,
        key_event: &KeyEvent,
        char_str: &str,
        char_code: u32,
        key_code: u32,
        candidates: Vec<String>,
    ) -> Result<Vec<String>, String> {
        let mut candidates = candidates;
        // CB:743
        if !(self.lang_mode == CHINESE_MODE && (self.composition_char == "`M" || self.composition_char == "`E")) {
            return Ok(candidates);
        }

        // CB:747
        let (labels, items) = self.build_toggle_items();
        self.smenucandidates = labels;
        self.smenuitems = items;

        if !self.closemenu {
            // CB:750
            self.set_candidate_cursor(0);
            self.set_candidate_page(0);

            if self.ime_dir_name == "chedayi" && self.apply_default_sel_keys() {
                self.is_show_candidates = true;
            }

            if !self.emojimenumode {
                self.menutype = 0;
                self.menu_reset_path();
                self.set_candidate_list(menu::main_menu_labels());
            } else {
                self.menutype = 7;
                self.menu_reset_path();
                self.menu_push_path("表情符號");
                let list: Vec<String> = EMOJI_MENU_LIST.iter().map(|s| s.to_string()).collect();
                self.set_candidate_list(menu::with_back(&list));
            }

            // CB:768
            self.menucandidates = self.ts.candidate_list.clone();
            self.prevmenutypelist = Vec::new();
            self.prevmenucandlist = Vec::new();
            self.showmenu = true;
        }

        if self.showmenu {
            // CB:774
            self.menumode = true;
            self.closemenu = false;
            candidates = self.menucandidates.clone();
            let mut cand_cursor = self.ts.candidate_cursor;
            let current_cand_page_count = pager::page_count(candidates.len(), self.cand_per_page) as i64;
            let mut current_cand_page = self.current_cand_page;

            // CB:783 候選清單分頁
            let pagecandidates = pager::paginate(&candidates, self.cand_per_page);
            let (pc, ccp, cc) = self.clamp_candidate_position(pagecandidates, current_cand_page, cand_cursor);
            let mut pagecandidates = pc;
            current_cand_page = ccp;
            cand_cursor = cc;
            let page = py_list_get(&pagecandidates, current_cand_page)?;
            self.set_candidate_list(page);
            let cand_count = self.ts.candidate_list.len() as i64;
            self.set_show_candidates(true);
            self.reset_menu_cand = false;
            let mut item_name = String::new();

            // CB:794 選單按鍵處理
            if key_code == VK_UP {
                if (cand_cursor - self.cand_per_row) < 0 {
                    if current_cand_page > 0 {
                        current_cand_page -= 1;
                        cand_cursor = 0;
                    }
                } else if (cand_cursor - self.cand_per_row) >= 0 {
                    cand_cursor -= self.cand_per_row;
                }
            } else if key_code == VK_DOWN {
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
            } else if key_code == VK_ESCAPE {
                // CB:836
                cand_cursor = 0;
                current_cand_page = 0;
                self.showmenu = false;
                self.emojimenumode = false;
                self.menutype = 0;
                self.prevmenutypelist = Vec::new();
                self.prevmenucandlist = Vec::new();
                self.menu_reset_path();
                if self.composition_buffer_mode {
                    let n = py_len(&self.composition_char);
                    self.remove_composition_buffer_string(n, true);
                }
                self.reset_composition();
            } else if self.is_in_sel_keys(char_code) && !key_event.is_key_down(VK_SHIFT) {
                // CB:848
                let idx = py_str_index(&self.sel_keys, char_str)?;
                if idx < self.cand_per_page && idx < self.ts.candidate_list.len() as i64 {
                    cand_cursor = idx;
                    item_name = py_list_get(&self.ts.candidate_list, cand_cursor)?;
                    self.switchmenu = true;
                }
            } else if key_code == VK_RETURN {
                item_name = py_list_get(&self.ts.candidate_list, cand_cursor)?;
                self.switchmenu = true;
            } else if key_code == VK_SPACE {
                if self.switch_page_with_space {
                    if (current_cand_page + 1) < current_cand_page_count {
                        current_cand_page += 1;
                        cand_cursor = 0;
                    } else {
                        current_cand_page = 0;
                        cand_cursor = 0;
                    }
                } else {
                    item_name = py_list_get(&self.ts.candidate_list, cand_cursor)?;
                    self.switchmenu = true;
                }
            } else if key_code == VK_BACK {
                if let Some(backpages) = self.menu_navigate_back()? {
                    pagecandidates = backpages;
                }
            }

            // CB:873 選單切換及執行
            if self.switchmenu && !item_name.is_empty() {
                self.switchmenu = false;
                let main_id = menu::main_menu_id(&item_name);
                let prev = |n: i64| vec![format!("{},{},{}", n, cand_cursor, current_cand_page)];
                if item_name == menu::BACK_ITEM {
                    if let Some(backpages) = self.menu_navigate_back()? {
                        pagecandidates = backpages;
                    }
                } else if self.menutype == 0 && main_id == Some("toggles") {
                    self.menucandidates = menu::with_back(&self.smenucandidates);
                    pagecandidates = pager::paginate(&self.menucandidates, self.cand_per_page);
                    self.menu_push_path(menu::TOGGLES_PAGE_TITLE);
                    self.reset_menu_cand = self.switch_menu_type(1, prev(0));
                } else if self.menutype == 0 && main_id == Some("symbols") {
                    self.menucandidates = menu::with_back(self.symbols()?.get_key_names());
                    pagecandidates = pager::paginate(&self.menucandidates, self.cand_per_page);
                    self.menu_push_path("特殊符號");
                    self.reset_menu_cand = self.switch_menu_type(2, prev(0));
                } else if self.menutype == 0 && main_id == Some("bopomofo") {
                    self.menucandidates = menu::with_back(&self.bopomofolist);
                    pagecandidates = pager::paginate(&self.menucandidates, self.cand_per_page);
                    self.menu_push_path("注音符號");
                    self.reset_menu_cand = self.switch_menu_type(4, prev(0));
                } else if self.menutype == 0 && main_id == Some("flangs") {
                    self.menucandidates = menu::with_back(self.flangs()?.get_key_names());
                    pagecandidates = pager::paginate(&self.menucandidates, self.cand_per_page);
                    self.menu_push_path("外語文字");
                    self.reset_menu_cand = self.switch_menu_type(5, prev(0));
                } else if self.menutype == 0 && main_id == Some("emoji") {
                    let list: Vec<String> = EMOJI_MENU_LIST.iter().map(|s| s.to_string()).collect();
                    self.menucandidates = menu::with_back(&list);
                    pagecandidates = pager::paginate(&self.menucandidates, self.cand_per_page);
                    self.menu_push_path("表情符號");
                    if !self.emojimenumode {
                        self.reset_menu_cand = self.switch_menu_type(7, prev(0));
                    } else {
                        self.reset_menu_cand = self.switch_menu_type(7, Vec::new());
                    }
                } else if self.menutype == 0 && main_id == Some("settings") {
                    // CB:907
                    self.on_menu_command(0, 0)?;
                    if self.composition_buffer_mode {
                        let n = py_len(&self.composition_char);
                        self.remove_composition_buffer_string(n, true);
                    }
                    self.reset_menu_cand = self.close_menu_cand();
                } else if self.menutype == 1 {
                    // CB:912
                    if let Some(i) = menu::toggle_index(&self.smenucandidates, &item_name) {
                        self.on_menu_command(i as i64, 1)?;
                    }
                    let (labels, items) = self.build_toggle_items();
                    self.smenucandidates = labels;
                    self.smenuitems = items;
                    self.menucandidates = menu::with_back(&self.smenucandidates);
                    pagecandidates = pager::paginate(&self.menucandidates, self.cand_per_page);
                } else if self.menutype == 2 && self.symbols()?.is_leaf(&item_name) {
                    self.commit_menu_item(&item_name, "menusymbols", &item_name);
                } else if self.menutype == 2 {
                    // CB:921
                    if self.composition_buffer_mode {
                        self.composition_buffer_menu_item = item_name.clone();
                    }
                    self.menucandidates = menu::with_back(self.symbols()?.get_char_def(&item_name));
                    pagecandidates = pager::paginate(&self.menucandidates, self.cand_per_page);
                    self.menu_push_path(&item_name);
                    self.reset_menu_cand = self.switch_menu_type(3, prev(2));
                } else if self.menutype == 3 {
                    let text = py_list_get(&self.ts.candidate_list, cand_cursor)?;
                    let mi = self.composition_buffer_menu_item.clone();
                    self.commit_menu_item(&text, "menusymbols", &mi);
                } else if self.menutype == 4 {
                    // CB:930
                    let text = py_list_get(&self.ts.candidate_list, cand_cursor)?;
                    if self.composition_buffer_mode {
                        let n = py_len(&self.composition_char);
                        self.remove_composition_buffer_string(n, true);
                        self.set_composition_buffer_string(&text, 0);
                        self.composition_buffer_type = "menubopomofo".into();
                        let t = self.composition_buffer_type.clone();
                        let cursor = self.composition_buffer_cursor;
                        self.set_composition_buffer_char(&t, "none", cursor);
                    } else {
                        self.set_commit_string(&text);
                    }
                    self.reset_menu_cand = self.close_menu_cand();
                } else if self.menutype == 5 && self.flangs()?.is_leaf(&item_name) {
                    self.commit_menu_item(&item_name, "menuflangs", &item_name);
                } else if self.menutype == 5 {
                    // CB:941
                    if self.composition_buffer_mode {
                        self.composition_buffer_menu_item = item_name.clone();
                    }
                    self.menucandidates = menu::with_back(self.flangs()?.get_char_def(&item_name));
                    pagecandidates = pager::paginate(&self.menucandidates, self.cand_per_page);
                    self.menu_push_path(&item_name);
                    self.reset_menu_cand = self.switch_menu_type(6, prev(5));
                } else if self.menutype == 6 {
                    let text = py_list_get(&self.ts.candidate_list, cand_cursor)?;
                    let mi = self.composition_buffer_menu_item.clone();
                    self.commit_menu_item(&text, "menuflangs", &mi);
                } else if self.menutype == 7 {
                    // CB:950
                    let mut menutype = 8;
                    let i = EMOJI_MENU_LIST
                        .iter()
                        .position(|x| *x == item_name)
                        .ok_or_else(|| format!("ValueError: '{}' is not in list", item_name))?;
                    let e = emoji()?;
                    match i {
                        0 => {
                            self.emojitype = 0;
                            self.menucandidates = menu::with_back(&e.emoticons_keynames);
                        }
                        1 => {
                            self.emojitype = 1;
                            self.menucandidates = menu::with_back(&e.pictographs_keynames);
                        }
                        2 => {
                            self.emojitype = 2;
                            self.menucandidates = menu::with_back(&e.miscellaneous_keynames);
                        }
                        3 => {
                            self.emojitype = 3;
                            self.menucandidates = menu::with_back(&e.dingbats_keynames);
                        }
                        4 => {
                            self.emojitype = 4;
                            self.menucandidates = menu::with_back(&e.transport_keynames);
                        }
                        5 => {
                            self.emojitype = 5;
                            self.menucandidates = menu::with_back(&e.modifiercolor);
                            menutype = 9;
                        }
                        _ => {}
                    }
                    pagecandidates = pager::paginate(&self.menucandidates, self.cand_per_page);
                    self.menu_push_path(&item_name);
                    self.reset_menu_cand = self.switch_menu_type(menutype, prev(7));
                } else if self.menutype == 8 {
                    // CB:975
                    let group = match self.emojitype {
                        0 => Some("emoticons"),
                        1 => Some("pictographs"),
                        2 => Some("miscellaneous"),
                        3 => Some("dingbats"),
                        4 => Some("transport"),
                        _ => None,
                    };
                    if let Some(group) = group {
                        if self.composition_buffer_mode {
                            self.composition_buffer_menu_item = format!("{},{}", group, item_name);
                        }
                        let e = emoji()?;
                        self.menucandidates = menu::with_back(e.get_char_def(group, &item_name)?);
                    }
                    pagecandidates = pager::paginate(&self.menucandidates, self.cand_per_page);
                    self.menu_push_path(&item_name);
                    self.reset_menu_cand = self.switch_menu_type(9, prev(8));
                } else if self.menutype == 9 {
                    // CB:985
                    let text = py_list_get(&self.ts.candidate_list, cand_cursor)?;
                    if self.composition_buffer_mode {
                        let n = py_len(&self.composition_char);
                        self.remove_composition_buffer_string(n, true);
                        self.set_composition_buffer_string(&text, 0);
                        self.composition_buffer_type = "menuemoji".into();
                        let t = self.composition_buffer_type.clone();
                        let mi = self.composition_buffer_menu_item.clone();
                        let cursor = self.composition_buffer_cursor;
                        self.set_composition_buffer_char(&t, &mi, cursor);
                    } else {
                        self.set_commit_string(&text);
                    }
                    self.reset_menu_cand = self.close_menu_cand();
                }
            }

            // CB:995
            if !self.prevmenucandlist.is_empty() {
                cand_cursor = py_list_get(&self.prevmenucandlist, 0)?;
                current_cand_page = py_list_get(&self.prevmenucandlist, 1)?;
                self.prevmenucandlist = Vec::new();
            }

            if self.reset_menu_cand {
                cand_cursor = 0;
                current_cand_page = 0;
            }

            // CB:1005 更新選字視窗游標位置
            self.set_candidate_cursor(cand_cursor);
            self.set_candidate_page(current_cand_page);
            let page = py_list_get(&pagecandidates, current_cand_page)?;
            self.set_candidate_list(page);
            if self.showmenu {
                let header = self.menu_header_text();
                self.ts.current_reply.insert("candidateHeader".into(), json!(header));
            }
        }
        Ok(candidates)
    }
}
