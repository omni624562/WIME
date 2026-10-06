//! The CinBase helpers after onKeyDown: python/cinbase/__init__.py
//! CB:2920-3609 (function menu commands, reset helpers, key classification,
//! full-shape conversion, smart select, wildcard, phrases, auto-commit,
//! header text, output string, composition buffer delegates).

use super::pyutil::{py_char_at, py_len, py_slice};
use super::*;
use crate::keycodes::*;
use crate::pager;
use std::collections::HashSet;

/// str.isprintable() for one string (approximation of Python's Unicode
/// categories: control, format, separators other than ' ', unassigned).
fn py_isprintable(s: &str) -> bool {
    s.chars().all(|c| {
        if c == ' ' {
            return true;
        }
        !(c.is_control()
            || c.is_whitespace()
            || matches!(c as u32, 0xAD | 0x600..=0x605 | 0x61C | 0x6DD | 0x70F | 0x180E | 0x200B..=0x200F | 0x202A..=0x202E | 0x2060..=0x2064 | 0x2066..=0x206F | 0xFEFF | 0xFFF9..=0xFFFB | 0xD800..=0xDFFF | 0xE000..=0xF8FF)
            || (c as u32) >= 0xF0000)
    })
}

impl CbTs {
    // CB:2920 onMenuCommand: commands of the ` function menu
    pub fn on_menu_command(&mut self, command_id: i64, command_type: i64) -> Result<(), String> {
        if command_type == 0 {
            if command_id == 0 {
                self.launch_config_tool();
            }
        } else if command_type == 1 {
            // 功能開關
            let command_item = pyutil::py_list_get(&self.smenuitems, command_id)?;
            match command_item.as_str() {
                "fullShapeSymbols" => self.full_shape_symbols = !self.full_shape_symbols,
                "easySymbolsWithShift" => self.easy_symbols_with_shift = !self.easy_symbols_with_shift,
                "supportWildcard" => self.support_wildcard = !self.support_wildcard,
                "playSoundWhenNonCand" => self.play_sound_when_non_cand = !self.play_sound_when_non_cand,
                "showPhrase" => self.show_phrase = !self.show_phrase,
                "sortByPhrase" => self.sort_by_phrase = !self.sort_by_phrase,
                "intelligentSelect" => self.intelligent_select = !self.intelligent_select,
                "intelligentSelectRecent" => self.intelligent_select_recent = !self.intelligent_select_recent,
                "intelligentSelectContext" => self.intelligent_select_context = !self.intelligent_select_context,
                "imeReverseLookup" => self.ime_reverse_lookup = !self.ime_reverse_lookup,
                "homophoneQuery" => self.homophone_query = !self.homophone_query,
                _ => {}
            }
        }
        Ok(())
    }

    // CB:2955 menuNavigateBack: up one level; to the main menu when there is
    // no recorded parent. Returns the new pages or None.
    pub fn menu_navigate_back(&mut self) -> Result<Option<Vec<Vec<String>>>, String> {
        if !self.prevmenutypelist.is_empty() {
            let prevmenutype = self.prevmenutypelist.len() - 1;
            let entry = self.prevmenutypelist[prevmenutype].clone();
            let prevmenulist: Vec<&str> = entry.splitn(3, ',').collect();
            self.menutype = pyutil::py_int(prevmenulist[0])?;
            self.prevmenucandlist = Vec::new();
            let a = pyutil::py_int(prevmenulist.get(1).ok_or("IndexError: list index out of range")?)?;
            self.prevmenucandlist.push(a);
            let b = pyutil::py_int(prevmenulist.get(2).ok_or("IndexError: list index out of range")?)?;
            self.prevmenucandlist.push(b);
            // list.remove(x) removes the first equal entry
            if let Some(pos) = self.prevmenutypelist.iter().position(|x| *x == entry) {
                self.prevmenutypelist.remove(pos);
            }
            self.menu_pop_path();
            let menutype = self.menutype;
            return Ok(Some(self.switch_menu_cand(menutype)?));
        }
        if self.menutype != 0 {
            // no recorded parent (e.g. `E straight into emoji): main menu
            self.menutype = 0;
            self.menu_reset_path();
            self.prevmenucandlist = vec![0, 0];
            return Ok(Some(self.switch_menu_cand(0)?));
        }
        Ok(None)
    }

    // CB:2975 switchMenuType
    pub fn switch_menu_type(&mut self, menutype: i64, prevmenutypelist: Vec<String>) -> bool {
        self.menutype = menutype;
        if menutype == 0 {
            self.prevmenutypelist = prevmenutypelist;
        } else if !prevmenutypelist.is_empty() {
            self.prevmenutypelist.push(prevmenutypelist[0].clone());
        } else {
            self.prevmenutypelist = prevmenutypelist;
        }
        true
    }

    // CB:2989 commitMenuItem: commit the picked symbol and close the menu (in
    // the composition buffer, remember where it came from for VK_DOWN)
    pub fn commit_menu_item(&mut self, text: &str, buffer_type: &str, buffer_menu_item: &str) {
        if self.composition_buffer_mode {
            let n = py_len(&self.composition_char);
            self.remove_composition_buffer_string(n, true);
            self.set_composition_buffer_string(text, 0);
            self.composition_buffer_type = buffer_type.to_string();
            let t = self.composition_buffer_type.clone();
            let cursor = self.composition_buffer_cursor;
            self.set_composition_buffer_char(&t, buffer_menu_item, cursor);
        } else {
            self.set_commit_string(text);
        }
        self.reset_menu_cand = self.close_menu_cand();
    }

    // CB:3000 closeMenuCand
    pub fn close_menu_cand(&mut self) -> bool {
        self.showmenu = false;
        self.emojimenumode = false;
        self.menutype = 0;
        self.prevmenutypelist = Vec::new();
        self.menu_reset_path();
        self.reset_composition();
        true
    }

    // CB:3010 switchMenuCand: the candidates of a menu type, paginated
    pub fn switch_menu_cand(&mut self, menutype: i64) -> Result<Vec<Vec<String>>, String> {
        if menutype == 0 {
            self.menucandidates = menu::main_menu_labels();
        }
        if menutype == 1 {
            self.menucandidates = menu::with_back(&self.smenucandidates);
        }
        if menutype == 2 {
            self.menucandidates = menu::with_back(self.symbols()?.get_key_names());
        }
        if menutype == 5 {
            self.menucandidates = menu::with_back(self.flangs()?.get_key_names());
        }
        if menutype == 7 {
            let list: Vec<String> = EMOJI_MENU_LIST.iter().map(|s| s.to_string()).collect();
            self.menucandidates = menu::with_back(&list);
        }
        if menutype == 8 {
            let e = emoji()?;
            match self.emojitype {
                0 => self.menucandidates = menu::with_back(&e.emoticons_keynames),
                1 => self.menucandidates = menu::with_back(&e.pictographs_keynames),
                2 => self.menucandidates = menu::with_back(&e.miscellaneous_keynames),
                3 => self.menucandidates = menu::with_back(&e.dingbats_keynames),
                4 => self.menucandidates = menu::with_back(&e.transport_keynames),
                5 => self.menucandidates = menu::with_back(&e.modifiercolor),
                _ => {}
            }
        }
        Ok(pager::paginate(&self.menucandidates, self.cand_per_page))
    }

    // CB:3040 resetComposition
    pub fn reset_composition(&mut self) {
        self.composition_char = String::new();
        if !self.composition_buffer_mode {
            self.set_composition_string("");
        }
        self.is_show_candidates = false;
        self.set_candidate_cursor(0);
        self.set_candidate_page(0);
        self.set_candidate_list(Vec::new());
        self.set_show_candidates(false);
        self.wildcardcandidates = Vec::new();
        self.wildcardpagecandidates = Vec::new();
        self.menumode = false;
        self.multifunctionmode = false;
        self.menusymbolsmode = false;
        self.ctrlsymbolsmode = false;
        self.fullsymbolsmode = false;
        self.dayisymbolsmode = false;
        self.keep_composition = false;
        self.homophonemode = false;
        self.homophoneselpinyinmode = false;
        self.homophone_char = String::new();
        self.homophone_str = String::new();
        self.is_homophone_chardefs = false;
        self.homophonecandidates = Vec::new();
        self.selcandmode = false;
        self.last_composition_char_length = 0;
    }

    // CB:3068 resetCompositionBuffer
    pub fn reset_composition_buffer(&mut self) {
        if self.composition_buffer_mode {
            self.composition_buffer_cursor = 0;
            self.composition_buffer_string = String::new();
            self.set_composition_string("");
        }
    }

    // CB:3075 resetHomophoneMode
    pub fn reset_homophone_mode(&mut self) {
        self.homophonemode = false;
        self.homophoneselpinyinmode = false;
        self.homophone_char = String::new();
        self.homophone_str = String::new();
        self.is_homophone_chardefs = false;
        self.homophonecandidates = Vec::new();
    }

    // CB:3084 isNumberChar
    pub fn is_number_char(&self, key_code: u32) -> bool {
        (0x30..=0x39).contains(&key_code)
    }

    // CB:3088 isSymbolsChar
    pub fn is_symbols_char(&self, key_code: u32) -> bool {
        (0xBA..=0xDF).contains(&key_code)
    }

    // CB:3092 isCtrlSymbolsChar
    pub fn is_ctrl_symbols_char(&self, key_code: u32) -> bool {
        (0xBA..=0xDF).contains(&key_code) && key_code != 0xBB && key_code != 0xBD && key_code != 0xC0
    }

    // CB:3096 isLetterChar
    pub fn is_letter_char(&self, key_code: u32) -> bool {
        (0x41..=0x5A).contains(&key_code)
    }

    // CB:3100 isSymbolsAndNumberChar(char): ord() of a one-char string
    pub fn is_symbols_and_number_char(&self, ch: &str) -> Result<bool, String> {
        let mut it = ch.chars();
        let (Some(c), None) = (it.next(), it.next()) else {
            return Err("TypeError: ord() expected a character".into());
        };
        let o = c as u32;
        Ok((33..=64).contains(&o) || (91..=96).contains(&o) || (123..=126).contains(&o))
    }

    // CB:3104 isInSelKeys
    pub fn is_in_sel_keys(&self, char_code: u32) -> bool {
        self.sel_keys.chars().any(|k| k as u32 == char_code)
    }

    // CB:3111 charCodeToFullshape
    pub fn char_code_to_fullshape(&self, char_code: u32, key_code: u32) -> Result<String, String> {
        let mut char_code = char_code;
        if self.lang_mode == CHINESE_MODE && self.output_small_letter_with_shift && self.is_letter_char(key_code) {
            let c = char::from_u32(char_code).unwrap_or('\u{FFFD}');
            let s: String = if self.caps_states { c.to_uppercase().collect() } else { c.to_lowercase().collect() };
            let mut it = s.chars();
            match (it.next(), it.next()) {
                (Some(c), None) => char_code = c as u32,
                _ => return Err("TypeError: ord() expected a character".into()),
            }
        }
        // non-ASCII (£, ä...) has no full-shape form: as is
        if !(0x0020..=0x7e).contains(&char_code) {
            return Ok(char::from_u32(char_code).map(String::from).unwrap_or_default());
        }
        if char_code == 0x0020 {
            return Ok("\u{3000}".into());
        }
        Ok(char::from_u32(char_code + 0xfee0).unwrap().to_string())
    }

    // CB:3128 SymbolscharCodeToFullshape
    pub fn symbols_char_code_to_fullshape(&self, char_code: u32) -> String {
        if !(0x0020..=0x7e).contains(&char_code) {
            return char::from_u32(char_code).map(String::from).unwrap_or_default();
        }
        let c = match char_code {
            0x0020 => 0x3000,
            0x0022 => 0x3001, // " -> 、
            0x0027 => 0x3001, // ' -> 、
            0x002e => 0x3002, // . -> 。
            0x003c => 0xff0c, // < -> ，
            0x003e => 0x3002, // > -> 。
            0x005f => 0xff0d, // _ -> －
            other => other + 0xfee0,
        };
        char::from_u32(c).unwrap().to_string()
    }

    // CB:3151 getIntelligentSelectPreviousChar
    pub fn get_intelligent_select_previous_char(&self) -> String {
        if self.last_commit_string.is_empty() {
            return String::new();
        }
        py_slice(&self.last_commit_string, Some(-1), None)
    }

    // CB:3157 sortByIntelligentSelect
    pub fn sort_by_intelligent_select(&self, key: &str, candidates: Vec<String>) -> Result<Vec<String>, String> {
        if !self.intelligent_select || candidates.is_empty() {
            return Ok(candidates);
        }
        let prev = self.get_intelligent_select_previous_char();
        self.cin()?.sort_by_count(key, &candidates, &prev, self.intelligent_select_recent, self.intelligent_select_context)
    }

    // CB:3168 addIntelligentSelectCount
    pub fn add_intelligent_select_count(&self, key: &str, commit_str: &str) -> Result<(), String> {
        if self.intelligent_select && !key.is_empty() {
            let prev = self.get_intelligent_select_previous_char();
            self.cin_mut()?.add_count(key, commit_str, &prev);
        }
        Ok(())
    }

    // CB:3172 isVariableWildcardQuery: 大易 `a*b` matches any length
    pub fn is_variable_wildcard_query(&self) -> bool {
        let composition_char = &self.composition_char;
        let wildcard_char = &self.sel_wildcard_char;
        self.ime_dir_name == "chedayi"
            && wildcard_char == "*"
            && composition_char.matches(wildcard_char.as_str()).count() == 1
            && !composition_char.starts_with(wildcard_char.as_str())
            && !composition_char.ends_with(wildcard_char.as_str())
    }

    // CB:3183 isWildcardInputKey
    pub fn is_wildcard_input_key(&self, char_str: &str, key_event: &KeyEvent) -> bool {
        if !self.support_wildcard {
            return false;
        }
        let wildcard_char = &self.sel_wildcard_char;
        if wildcard_char.is_empty() {
            return false;
        }
        if char_str == wildcard_char {
            return true;
        }
        if wildcard_char == "*" && key_event.key_code == VK_MULTIPLY {
            return true;
        }
        if wildcard_char == "*" && key_event.key_code == 0x38 && key_event.is_key_down(VK_SHIFT) {
            return true;
        }
        false
    }

    // CB:3197 appendWildcardComposition
    pub fn append_wildcard_composition(&mut self) -> bool {
        let wildcard_char = self.sel_wildcard_char.clone();
        if wildcard_char.is_empty() {
            return false;
        }
        let keyname = if wildcard_char == "*" { "＊".to_string() } else { wildcard_char.clone() };
        if self.composition_buffer_mode {
            if py_len(&self.composition_char) >= self.max_char_length {
                return false;
            }
            self.composition_char.push_str(&wildcard_char);
            self.set_composition_buffer_string(&keyname, 0);
        } else {
            self.composition_char.push_str(&wildcard_char);
            let s = format!("{}{}", self.ts.composition_string, keyname);
            self.set_composition_string(&s);
            let len = py_len(&self.ts.composition_string);
            self.set_composition_cursor(len);
        }
        true
    }

    // CB:3213 filterExcludedPhrases: a new list without the user's excluded phrases
    pub fn filter_excluded_phrases(&self, lead_char: &str, phraselist: Vec<String>) -> Vec<String> {
        let mut excluded: HashSet<String> = HashSet::new();
        if let Some(exclude) = &self.excludephrase {
            if !phraselist.is_empty() && exclude.is_in_char_def(lead_char) {
                excluded = exclude.get_char_def(lead_char).iter().cloned().collect();
            }
        }
        phraselist.into_iter().filter(|p| !excluded.contains(p)).collect()
    }

    // CB:3221 phraseSuggestions: user phrases first, then the built-in table
    // (None while loading / after a failed load), minus the excluded ones
    pub fn phrase_suggestions(&self, lead_char: &str) -> Vec<String> {
        let mut suggestions: Vec<String> = Vec::new();
        if let Some(userphrase) = &self.userphrase {
            if userphrase.is_in_char_def(lead_char) {
                suggestions = userphrase.get_char_def(lead_char).to_vec();
            }
        }
        let data = phrase_data();
        let data = data.borrow();
        if let Some(table) = &data.phrase {
            if table.is_in_char_def(lead_char) {
                let mut seen: HashSet<String> = suggestions.iter().cloned().collect();
                for pstr in table.get_char_def(lead_char) {
                    if !seen.contains(pstr) {
                        suggestions.push(pstr.clone());
                        seen.insert(pstr.clone());
                    }
                }
            }
        }
        self.filter_excluded_phrases(lead_char, suggestions)
    }

    // CB:3238 sortByPhrase: the previous char's phrases found in the list move
    // to the front (in phrase order); each moves from its first position only
    pub fn sort_by_phrase(&self, candidates: Vec<String>) -> Vec<String> {
        let sortbyphraselist = self.phrase_suggestions(&self.last_commit_string);
        if sortbyphraselist.is_empty() {
            return candidates;
        }
        let candidate_set: HashSet<&String> = candidates.iter().collect();
        let mut front: Vec<String> = Vec::new();
        let mut front_set: HashSet<String> = HashSet::new();
        for p in &sortbyphraselist {
            if candidate_set.contains(p) && !front_set.contains(p) {
                front.push(p.clone());
                front_set.insert(p.clone());
            }
        }
        if front.is_empty() {
            return candidates;
        }
        let mut moved: HashSet<String> = HashSet::new();
        let mut rest = Vec::new();
        for candidate in candidates {
            if front_set.contains(&candidate) && !moved.contains(&candidate) {
                moved.insert(candidate);
                continue;
            }
            rest.push(candidate);
        }
        front.extend(rest);
        front
    }

    // CB:3263 shouldAutoCommitSingleCandidate
    pub fn should_auto_commit_single_candidate(&self, candidates: &[String]) -> Result<bool, String> {
        if !self.auto_commit_single_candidate {
            return Ok(false);
        }
        if candidates.len() != 1 {
            return Ok(false);
        }
        if self.composition_char.is_empty() || !self.cin()?.is_in_char_def(&self.composition_char) {
            return Ok(false);
        }
        if self.cin()?.has_longer_char_def_prefix(&self.composition_char) {
            return Ok(false);
        }
        Ok(!(self.selcandmode
            || self.multifunctionmode
            || self.temp_english_mode
            || self.phrasemode
            || self.ctrlsymbolsmode
            || self.dayisymbolsmode
            || self.fullsymbolsmode
            || self.homophonemode
            || self.is_wildcard_chardefs))
    }

    // CB:3282 numpadWhileComposing: commit the highlighted candidate, then the
    // numpad char; closes a lone phrase list. Returns onKeyDown's return
    // value, None when it does not apply.
    pub fn numpad_while_composing(&mut self, char_str: &str) -> Result<Option<bool>, String> {
        if !py_isprintable(char_str) {
            return Ok(None);
        }
        if self.composition_char.is_empty() && self.phrasemode && self.is_show_phrase_candidates {
            self.phrasemode = false;
            self.is_show_phrase_candidates = false;
            self.set_candidate_list(Vec::new());
            self.set_show_candidates(false);
            return Ok(Some(false));
        }
        let in_normal_composition = !self.composition_char.is_empty()
            && self.lang_mode == CHINESE_MODE
            && self.closemenu
            && !(self.multifunctionmode
                || self.menumode
                || self.ctrlsymbolsmode
                || self.dayisymbolsmode
                || self.fullsymbolsmode
                || self.homophonemode
                || self.selcandmode
                || self.temp_english_mode
                || self.phrasemode);
        if !in_normal_composition {
            return Ok(None);
        }

        let commit_str = self.highlighted_candidate()?;
        if !commit_str.is_empty() {
            if self.composition_buffer_mode {
                self.composition_buffer_type = "default".into();
            }
            self.commit_single_candidate(&commit_str)?;
        } else {
            if self.composition_buffer_mode {
                let n = self.calc_remove_string_length()?;
                self.remove_composition_buffer_string(n, true);
            }
            self.reset_composition();
        }

        if self.composition_buffer_mode {
            self.set_composition_buffer_string(char_str, 0);
            self.composition_buffer_type = "english".into();
            let t = self.composition_buffer_type.clone();
            let cursor = self.composition_buffer_cursor;
            self.set_composition_buffer_char(&t, char_str, cursor);
        } else {
            let prev = match self.ts.current_reply.get("commitString") {
                Some(Value::String(s)) => s.clone(),
                Some(_) => return Err("TypeError: can only concatenate str".into()),
                None => String::new(),
            };
            self.set_commit_string(&(prev + char_str));
        }
        self.phrasemode = false;
        self.is_show_phrase_candidates = false;
        self.last_commit_string = char_str.to_string();
        Ok(Some(true))
    }

    // CB:3323 highlightedCandidate: the candidate under the cursor; without a
    // candidate window the first candidate in display order
    pub fn highlighted_candidate(&self) -> Result<String, String> {
        if self.ts.show_candidates && !self.ts.candidate_list.is_empty() {
            let len = self.ts.candidate_list.len() as i64;
            let cursor = if 0 <= self.ts.candidate_cursor && self.ts.candidate_cursor < len { self.ts.candidate_cursor } else { 0 };
            return Ok(self.ts.candidate_list[cursor as usize].clone());
        }
        let key = self.composition_char.clone();
        let candidates: Vec<String> = if self.support_wildcard && key.contains(self.sel_wildcard_char.as_str()) {
            let variable = self.is_variable_wildcard_query();
            self.cin()?.get_wildcard_char_defs(&key, &self.sel_wildcard_char, self.cand_max_items, variable)?
        } else if self.cin()?.is_in_char_def(&key) {
            self.cin()?.get_char_def(&key).to_vec()
        } else {
            return Ok(String::new());
        };
        let mut candidates = candidates;
        if self.sort_by_phrase && !candidates.is_empty() {
            candidates = self.sort_by_phrase(candidates);
        }
        let candidates = self.sort_by_intelligent_select(&key, candidates)?;
        Ok(candidates.first().cloned().unwrap_or_default())
    }

    // CB:3343 ignoreNextSpace
    pub fn ignore_next_space(&mut self) {
        self.skip_space_deadline = env::monotonic() + AUTO_COMMIT_SPACE_GRACE;
    }

    // CB:3346 isSpaceAfterAutoCommit: the Space right after an auto-commit
    // (cleared by onKeyDown when swallowed, by any other key here)
    pub fn is_space_after_auto_commit(&mut self, key_event: &KeyEvent) -> bool {
        let deadline = self.skip_space_deadline;
        if deadline == 0.0 {
            return false;
        }
        if key_event.key_code != VK_SPACE
            || env::monotonic() > deadline
            || self.lang_mode != CHINESE_MODE
            || key_event.is_key_down(VK_SHIFT)
            || key_event.is_key_down(VK_CONTROL)
            || key_event.is_key_down(VK_MENU)
        {
            self.skip_space_deadline = 0.0;
            return false;
        }
        true
    }

    // CB:3361 commitSingleCandidate
    pub fn commit_single_candidate(&mut self, commit_str: &str) -> Result<(), String> {
        let key = self.composition_char.clone();
        self.add_intelligent_select_count(&key, commit_str)?;
        self.last_commit_string = commit_str.to_string();
        self.set_output_string(commit_str)?;
        if self.show_phrase && !self.selcandmode {
            self.phrasemode = true;
        }
        self.reset_composition();
        Ok(())
    }

    // CB:3369 compositionHeaderText: the root names of compositionChar
    pub fn composition_header_text(&self) -> String {
        let composition_char = &self.composition_char;
        if composition_char.is_empty() {
            return String::new();
        }
        if self.ime_dir_name == "chedayi" && self.dayisymbolsmode && *composition_char == self.dayi_symbol_char {
            return self.dayi_symbol_string.clone();
        }
        let mut text = String::new();
        let cin = self.cin.as_ref().map(|c| c.borrow());
        for c in composition_char.chars() {
            let c_str = c.to_string();
            match &cin {
                Some(cin) if cin.is_in_key_name(&c_str) => text.push_str(cin.get_key_name(&c_str)),
                _ => {
                    if self.support_wildcard && self.sel_wildcard_char == "*" && c == '*' {
                        text.push('＊');
                    } else {
                        text.push(c);
                    }
                }
            }
        }
        text
    }

    // CB:3390 isCompositionCharPrefix
    pub fn is_composition_char_prefix(&self) -> bool {
        if self.composition_char.is_empty() {
            return false;
        }
        match &self.cin {
            None => true,
            Some(cin) => cin.borrow().is_char_def_prefix(&self.composition_char),
        }
    }

    // CB:3401 shouldKeepNoCandidateMessageInCandidateWindow
    pub fn should_keep_no_candidate_message_in_candidate_window(&self) -> bool {
        matches!(self.ime_dir_name.as_str(), "chedayi" | "checj" | "cheliu") && !self.is_composition_char_prefix()
    }

    // CB:3404 shouldRestartNoCandidateComposition: a root key after a code
    // that is no prefix starts a new composition
    pub fn should_restart_no_candidate_composition(&self, char_str_low: &str, key_event: &KeyEvent) -> bool {
        if !matches!(self.ime_dir_name.as_str(), "chedayi" | "checj" | "cheliu") {
            return false;
        }
        if self.composition_char.is_empty() {
            return false;
        }
        let wildcard_char = &self.sel_wildcard_char;
        if self.support_wildcard && !wildcard_char.is_empty() && self.composition_char.contains(wildcard_char.as_str()) {
            return false;
        }
        if self.is_composition_char_prefix() {
            return false;
        }
        if !self.closemenu
            || self.multifunctionmode
            || self.ctrlsymbolsmode
            || self.dayisymbolsmode
            || self.selcandmode
            || self.temp_english_mode
            || self.phrasemode
        {
            return false;
        }
        if key_event.is_key_down(VK_CONTROL) || key_event.is_key_down(VK_MENU) || key_event.is_key_down(VK_SHIFT) {
            return false;
        }
        match &self.cin {
            Some(cin) => cin.borrow().is_in_key_name(char_str_low),
            None => false,
        }
    }

    // CB:3427 setNoCandidateMessageInCandidateWindow(confirmed=False)
    pub fn set_no_candidate_message_in_candidate_window(&mut self, confirmed: bool) {
        self.ts.current_reply.insert("candidateMessage".into(), json!("查無組字"));
        self.ts.current_reply.insert("candidatePageInfo".into(), json!(""));
        if !confirmed && self.cfg.candidate_message_behavior == "progressive" {
            self.ts.current_reply.insert("candidateMessageStyle".into(), json!("dot"));
        } else {
            self.ts.current_reply.remove("candidateMessageStyle");
        }
        self.is_show_candidates = true;
    }

    // CB:3453 isShiftSide: the scan code (left 0x2A, right 0x36) decides;
    // other scan codes fall back to GetAsyncKeyState
    pub fn is_shift_side(&self, key_event: &KeyEvent, side_vk: u32) -> bool {
        let scan_code = key_event.scan_code;
        if scan_code == LEFT_SHIFT_SCAN_CODE || scan_code == RIGHT_SHIFT_SCAN_CODE {
            return scan_code == if side_vk == VK_LSHIFT { LEFT_SHIFT_SCAN_CODE } else { RIGHT_SHIFT_SCAN_CODE };
        }
        self.is_pressed(side_vk)
    }

    // CB:3460 setCompositionBufferString
    pub fn set_composition_buffer_string(&mut self, composition_string: &str, remove_string_length: i64) {
        self.buffer_insert_string(composition_string, remove_string_length);
    }

    // CB:3463 setCompositionBufferChar
    pub fn set_composition_buffer_char(&mut self, composition_type: &str, composition_char: &str, composition_cursor: i64) {
        self.buffer_record_char(composition_type, composition_char, composition_cursor);
    }

    // CB:3466 removeCompositionBufferString
    pub fn remove_composition_buffer_string(&mut self, remove_string_length: i64, remove_before: bool) {
        self.buffer_remove_string(remove_string_length, remove_before);
    }

    // CB:3469 setOutputString: commit (or put into the buffer) and queue the
    // onKeyUp messages (root encoding of a wildcard / homophone pick, reverse lookup)
    pub fn set_output_string(&mut self, commit_str: &str) -> Result<(), String> {
        if self.is_wildcard_chardefs {
            if !self.client.is_ui_less {
                self.is_show_message = true;
                self.show_message_on_key_up = true;
                let message = self.cin()?.get_char_encode(commit_str);
                self.on_key_up_message = message;
            }
            self.wildcardcandidates = Vec::new();
            self.wildcardpagecandidates = Vec::new();
            self.is_wildcard_chardefs = false;
        }

        if self.ime_reverse_lookup {
            let rcin_table = self.tables.rcin.clone();
            let rcin_table = rcin_table.borrow();
            if let Some(rcin) = &rcin_table.cin {
                let message = rcin.get_char_encode(commit_str);
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

        if self.homophone_query && self.is_homophone_chardefs {
            self.is_homophone_chardefs = false;
            if !self.client.is_ui_less {
                self.is_show_message = true;
                self.show_message_on_key_up = true;
                let message = self.cin()?.get_char_encode(commit_str);
                self.on_key_up_message = message;
            }
        }

        if !self.composition_buffer_mode {
            self.set_commit_string(commit_str);
        } else {
            let mut remove_string_length = 0;
            if !self.selcandmode {
                if self.menusymbolsmode {
                    remove_string_length = py_len(&self.composition_char) - 1;
                    self.menusymbolsmode = false;
                } else if self.dayisymbolsmode {
                    remove_string_length = self.calc_remove_string_length()? - 1;
                } else {
                    remove_string_length = self.calc_remove_string_length()?;
                }
            } else {
                let before = self.composition_buffer_cursor >= py_len(&self.composition_buffer_string);
                self.remove_composition_buffer_string(1, before);
            }
            self.set_composition_buffer_string(commit_str, remove_string_length);
            if !self.selcandmode {
                let mut str_length = py_len(commit_str);
                if str_length > 1 {
                    let commit_chars: Vec<char> = commit_str.chars().collect();
                    for c in commit_chars.iter() {
                        str_length -= 1;
                        let t = self.composition_buffer_type.clone();
                        if t == "msymbols" {
                            // commitStr.index(cStr): the first occurrence
                            let index = commit_chars.iter().position(|x| x == c).unwrap() as i64;
                            let c_char = if py_char_at(&self.composition_char, 0)? != "`" {
                                py_char_at(&self.composition_char, index)?
                            } else {
                                py_char_at(&self.composition_char, index + 1)?
                            };
                            let cursor = self.composition_buffer_cursor - str_length;
                            self.set_composition_buffer_char(&t, &c_char, cursor);
                        } else {
                            let cc = self.composition_char.clone();
                            let cursor = self.composition_buffer_cursor - str_length;
                            self.set_composition_buffer_char(&t, &cc, cursor);
                        }
                    }
                } else {
                    let t = self.composition_buffer_type.clone();
                    let cc = self.composition_char.clone();
                    let cursor = self.composition_buffer_cursor;
                    self.set_composition_buffer_char(&t, &cc, cursor);
                }
            }
        }
        Ok(())
    }

    // CB:3534 setOutputFSymbols
    pub fn set_output_f_symbols(&mut self, char_str: &str) -> Result<(), String> {
        if self.homophone_query && self.homophonemode {
            self.reset_homophone_mode();
        }

        self.composition_buffer_type = "fsymbols".into();
        if self.composition_buffer_mode && self.direct_show_cand && self.direct_out_f_symbols && self.fullsymbolsmode {
            let t = self.composition_buffer_type.clone();
            let cc = self.composition_char.clone();
            let cursor = self.composition_buffer_cursor;
            self.set_composition_buffer_char(&t, &cc, cursor);
            self.reset_composition();
        }

        let mut remove_string_length = 0;
        if self.composition_buffer_mode && !self.composition_char.is_empty() {
            remove_string_length = self.calc_remove_string_length()?;
        }

        self.composition_char = char_str.to_string();
        let full_shape_symbols_list = self.fsymbols()?.get_char_def(&self.composition_char).to_vec();

        if self.composition_buffer_mode {
            let first = pyutil::py_list_get(&full_shape_symbols_list, 0)?;
            self.set_composition_buffer_string(&first, remove_string_length);
            if !self.direct_show_cand {
                let t = self.composition_buffer_type.clone();
                let cc = self.composition_char.clone();
                let cursor = self.composition_buffer_cursor;
                self.set_composition_buffer_char(&t, &cc, cursor);
                self.reset_composition();
            }
        } else {
            let commit_str = self.ts.composition_string.clone();

            if self.direct_out_f_symbols && self.fullsymbolsmode {
                self.set_commit_string(&commit_str);
                self.keep_composition = true;
                self.keep_type = "fullShapeSymbols".into();
            }

            self.composition_char = char_str.to_string();
            let first = pyutil::py_list_get(&full_shape_symbols_list, 0)?;
            self.set_composition_string(&first);
            let len = py_len(&self.ts.composition_string);
            self.set_composition_cursor(len);
        }
        self.fullsymbolsmode = true;
        Ok(())
    }

    // CB:3569 calcRemoveStringLength: the display length of compositionChar
    pub fn calc_remove_string_length(&self) -> Result<i64, String> {
        let mut remove_string_length = 0;
        if !self.composition_char.is_empty() {
            if self.menusymbolsmode {
                let key = py_slice(&self.composition_char, Some(1), None);
                let msymbols = self.msymbols()?;
                if msymbols.is_in_char_def(&key) {
                    remove_string_length = py_len(&pyutil::py_list_get(msymbols.get_char_def(&key)?, 0)?);
                }
            } else {
                for c in self.composition_char.chars() {
                    let c_str = c.to_string();
                    let cin = self.cin()?;
                    if cin.is_in_key_name(&c_str) {
                        remove_string_length += py_len(cin.get_key_name(&c_str));
                    } else {
                        remove_string_length += 1;
                    }
                }
            }
        }
        Ok(remove_string_length)
    }

    // CB:3583 moveCursorInBrackets: put the buffer cursor between a pair of brackets
    pub fn move_cursor_in_brackets(&mut self) -> Result<(), String> {
        let buf = self.composition_buffer_string.clone();
        let cursor = self.composition_buffer_cursor;
        let bracket_str = py_char_at(&buf, cursor - 2)? + &py_char_at(&buf, cursor - 1)?;
        if self.bracket_symbol_list.contains(&bracket_str) && !self.composition_char.is_empty() {
            let mut str_length = py_len(&bracket_str);
            let comp_char = if self.composition_buffer_type == "msymbols" && py_char_at(&self.composition_char, 0)? == "`" {
                py_slice(&self.composition_char, Some(1), None)
            } else {
                self.composition_char.clone()
            };
            let in_cin = {
                let cin = self.cin()?;
                cin.is_in_char_def(&self.composition_char) && cin.get_char_def(&self.composition_char).contains(&bracket_str)
            };
            // `or` short-circuits: msymbols is only looked at when cin fails
            let in_msymbols = !in_cin && {
                let m = self.msymbols()?;
                m.is_in_char_def(&comp_char) && m.get_char_def(&comp_char)?.contains(&bracket_str)
            };
            if in_cin || in_msymbols {
                let bracket_chars: Vec<char> = bracket_str.chars().collect();
                for b in bracket_chars.iter() {
                    str_length -= 1;
                    let t = self.composition_buffer_type.clone();
                    let cursor = self.composition_buffer_cursor - str_length;
                    if t == "msymbols" {
                        let index = bracket_chars.iter().position(|x| x == b).unwrap() as i64;
                        let c_char = if py_char_at(&self.composition_char, 0)? != "`" {
                            py_char_at(&self.composition_char, index)?
                        } else {
                            py_char_at(&self.composition_char, index + 1)?
                        };
                        self.set_composition_buffer_char(&t, &c_char, cursor);
                    } else {
                        self.set_composition_buffer_char(&t, &comp_char, cursor);
                    }
                }
            } else {
                let t = self.composition_buffer_type.clone();
                let cursor = self.composition_buffer_cursor;
                self.set_composition_buffer_char(&t, &comp_char, cursor);
            }
            self.composition_buffer_cursor -= 1;
            self.set_composition_cursor(self.composition_buffer_cursor);
            self.reset_composition();
        } else if self.bracket_symbol_list.contains(&bracket_str) && self.composition_buffer_type == "fsymbols" {
            self.composition_buffer_cursor -= 1;
            self.set_composition_cursor(self.composition_buffer_cursor);
            self.reset_composition();
        }
        Ok(())
    }
}
