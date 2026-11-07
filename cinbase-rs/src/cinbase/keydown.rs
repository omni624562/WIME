//! onKeyDown, part 1: DY:33 CheDayiTextService.onKeyDown (the 大易 prelude),
//! which then calls the shared `CbTs::on_key_down`.
//!
//! - `on_key_down` = `CinBase.onKeyDown` CB:1013-2527: keydown_core.rs
//! - `fill_m_symbols_buffer_char` / `handle_m_symbols_in_multifunction_mode` /
//!   `handle_ctrl_symbols` / `handle_menu_mode` = CB:573-1011: keydown_modes.rs
//!
//! Conventions: every `cbTS.attr` is `self.attr` in snake_case; Python strings
//! index by code point (`pyutil`); a Python exception is `Err(..)` (the request
//! answers success:false).

use super::pyutil::{py_char_at, py_len, py_list_get, py_slice, py_str_index};
use super::*;
use crate::keycodes::*;

impl CbTs {
    /// `cbTS.kbtypelist[cbTS.keyboardLayout]`: the keys of the configured
    /// layout, indexed like a Python list (AttributeError in an IME without
    /// kbtypelist, IndexError for a layout that does not exist).
    fn layout_keys(&self) -> Result<String, String> {
        if self.kbtypelist.is_empty() {
            return Err(super::attr_error("kbtypelist"));
        }
        py_list_get(&self.kbtypelist, self.keyboard_layout)
    }

    /// `key in cbTS.kbtypelist[cbTS.keyboardLayout]` (substring test, like Python)
    pub fn layout_has_key(&self, key: &str) -> Result<bool, String> {
        Ok(self.layout_keys()?.contains(key))
    }

    /// CB:1084 `cbTS.kbtypelist[0][kbtypelist[layout].index(key)]`: the standard
    /// layout's key at the position of `key` on the configured layout
    pub fn standard_layout_key(&self, key: &str) -> Result<String, String> {
        let keys = self.layout_keys()?;
        let index = py_str_index(&keys, key)?;
        py_char_at(&self.kbtypelist[0], index)
    }

    /// PH:57 ChePhoneticTextService.updateCompositionChar: a syllable has one key
    /// per part (initial, medial, final, tone); a new key replaces its part, and
    /// the parts are shown in that order
    pub fn chephonetic_update_composition_char(&mut self, char_str: &str) -> Result<(), String> {
        if self.zhuintab.len() < 4 {
            return Err(super::attr_error("zhuintab"));
        }
        let mut parts: [String; 4] = Default::default();
        let char_length = py_len(&self.composition_char);
        let composition_char = self.composition_char.clone();
        for c in composition_char.chars() {
            if let Some(i) = self.zhuintab.iter().position(|group| group.contains(c)) {
                parts[i] = c.to_string();
            }
        }
        if let Some(i) = self.zhuintab.iter().position(|group| group.contains(char_str)) {
            parts[i] = char_str.to_string();
        }
        let mut keynames = String::new();
        let mut compchar = String::new();
        for part in &parts {
            if !part.is_empty() {
                compchar.push_str(part);
                keynames.push_str(self.cin()?.get_key_name(part));
            }
        }
        self.composition_char = compchar;
        if self.composition_buffer_mode {
            self.set_composition_buffer_string(&keynames, char_length);
        } else {
            self.set_composition_string(&keynames);
            let n = py_len(&self.ts.composition_string);
            self.set_composition_cursor(n);
        }
        Ok(())
    }

    // DY:33 CheDayiTextService.onKeyDown: per-key maxCharLength and the 大易
    // symbol lead key (= or '), then the shared onKeyDown
    pub fn chedayi_on_key_down(&mut self, key_event: &KeyEvent) -> Result<bool, String> {
        if self.cfg.sel_cin_type == 0 || self.cfg.sel_cin_type == 1 {
            self.max_char_length = 4;
        } else if self.cfg.sel_cin_type == 2 {
            self.max_char_length = 3;
        }

        let char_str = key_event.char_str();

        // 大易符號
        self.dayi_symbol_char = if self.sel_dayi_symbol_char_type == 0 { "=".into() } else { "'".into() };
        self.dayi_symbol_string = if self.sel_dayi_symbol_char_type == 0 { "＝".into() } else { "號".into() };

        // DY:47 聯想字清單開著時 = 要先關掉清單，才能照下面的規則進入大易符號模式
        self.close_phrase_list_for_key(key_event);

        if self.lang_mode == 1 && !self.showmenu {
            if self.composition_char.is_empty()
                && !self.phrasemode
                && char_str == self.dayi_symbol_char
                && !key_event.is_key_down(VK_CONTROL)
            {
                self.composition_char.push_str(&char_str);
                self.dayisymbolsmode = true;
                let s = self.dayi_symbol_string.clone();
                if self.composition_buffer_mode {
                    self.set_composition_buffer_string(&s, 0);
                } else {
                    self.set_composition_string(&s);
                }
            } else if self.dayisymbolsmode && self.is_show_candidates {
                self.can_use_sel_key = true;
            } else if py_len(&self.composition_char) >= 1 && self.dayisymbolsmode {
                let key = py_slice(&self.composition_char, Some(1), None) + &char_str;
                if self.dsymbols()?.is_in_char_def(&key) {
                    self.composition_char.push_str(&char_str);
                    self.can_use_sel_key = false;
                    // DY:61 `candidates = ...getCharDef(...)` is dead code (it can
                    // only raise, and cannot: the key was just checked)
                    let _ = self.dsymbols()?.get_char_def(&py_slice(&self.composition_char, Some(1), None))?;
                }
            }
        }

        if !self.direct_show_cand {
            self.auto_show_cand_when_max_char = true;
        }
        self.on_key_down(key_event)
    }
}
