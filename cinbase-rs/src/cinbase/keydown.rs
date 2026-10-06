//! onKeyDown: DY:33 (the 大易 prelude, ported) and CB:1013-2527 with its
//! helpers CB:573-1011 (PART 2 OF THE PORT, still to do).
//!
//! # What part 2 must port (python/cinbase/__init__.py)
//!
//! - `on_key_down` = `CinBase.onKeyDown` CB:1013-2527, line by line, as a method
//!   on `CbTs`. The signature drops CinTable/RCinTable/HCinTable: use
//!   `self.tables.cin` / `.rcin` / `.hcin` (`Rc<RefCell<..>>`; RCinTable.cin is
//!   `self.tables.rcin.borrow().cin: Option<RCin>`, HCinTable likewise) and
//!   `self.cin()?` / `self.cin_mut()?` for `cbTS.cin`.
//! - `handle_m_symbols_in_multifunction_mode` = `_handleMSymbolsInMultifunctionMode` CB:593-662
//! - `handle_ctrl_symbols` = `_handleCtrlSymbols` CB:664-737
//! - `handle_menu_mode` = `_handleMenuMode` CB:739-1011
//! - `fill_m_symbols_buffer_char` = `_fillMSymbolsBufferChar` CB:573-591 (already ported below)
//!
//! Conventions already in place:
//! - every `cbTS.attr` is `self.attr` in snake_case (see the `CbTs` struct in
//!   mod.rs); `cbTS.compositionString` etc. live in `self.ts`; the TextService
//!   setters have delegates on `CbTs` (`self.set_composition_string(..)`,
//!   `self.show_message(..)`, `self.set_candidate_page(..)` ...); direct
//!   `cbTS.currentReply[...]` writes go to `self.ts.current_reply`.
//! - every other `self.xxx(cbTS, ...)` helper of CinBase already exists as
//!   `self.xxx(...)` (helpers.rs, events.rs, context.rs, selkeys.rs, menu.rs,
//!   compositionbuffer.rs), e.g. `self.reset_composition()`,
//!   `self.set_output_string(..)?`, `self.clamp_candidate_position(..)`,
//!   `self.set_modern_candidate_page_info(..)`, `self.ensure_modern_candidate_header()`,
//!   `self.composition_header_text()`, `self.set_no_candidate_message_in_candidate_window(..)`,
//!   `self.should_restart_no_candidate_composition(..)`, `self.numpad_while_composing(..)?`,
//!   `self.apply_dayi_sel_keys()`, `self.switch_menu_cand(..)?`, `self.on_menu_command(..)?`,
//!   `CbTs::unicode_input_code_point(..)`, `self.customize_candidate_ui(false)`.
//!   `menu.xxx(cbTS)` is `self.menu_xxx()`; `pager.paginate` is `crate::pager::paginate`.
//! - Python strings index by code point: use `pyutil::{py_len, py_slice,
//!   py_char_at, py_list_get}`; `x in "'[]-\\"` is substring containment
//!   (`pyutil::py_in`, note "" is in every string).
//! - `winsound.PlaySound('alert', ...)` is `env::play_sound("alert")`;
//!   `time.time()` / `time.monotonic()` are `env::time()` / `env::monotonic()`.
//! - An exception in Python is `Err(..)` (the request answers success:false).

use super::pyutil::{py_len, py_slice};
use super::*;
use crate::keycodes::*;

impl CbTs {
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

    /// CB:1013 CinBase.onKeyDown — PART 2: NOT PORTED YET.
    ///
    /// Must become a line-by-line translation of CB:1013-2527 (see the module
    /// doc for the conventions). Until then it handles nothing.
    pub fn on_key_down(&mut self, _key_event: &KeyEvent) -> Result<bool, String> {
        // CB:1013
        Ok(false)
    }

    /// CB:573 _fillMSymbolsBufferChar(commitStrList, compositionCharOffset=0):
    /// find the committed symbol at the end of the buffer, then record the
    /// key of each of its chars.
    pub fn fill_m_symbols_buffer_char(&mut self, commit_str_list: &[String], composition_char_offset: i64) -> Result<(), String> {
        use super::pyutil::py_char_at;
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

    /// CB:593 _handleMSymbolsInMultifunctionMode — PART 2: NOT PORTED YET.
    /// Returns (should_early_return, updated_candidates_or_None).
    pub fn handle_m_symbols_in_multifunction_mode(
        &mut self,
        _key_event: &KeyEvent,
        _char_str: &str,
        _cin_has_char_str_low: bool,
    ) -> Result<(bool, Option<Vec<String>>), String> {
        // CB:593
        Ok((false, None))
    }

    /// CB:664 _handleCtrlSymbols — PART 2: NOT PORTED YET.
    pub fn handle_ctrl_symbols(&mut self, _key_event: &KeyEvent, _char_str: &str, _key_code: u32, _cin_has_char_str_low: bool) -> Result<(), String> {
        // CB:664
        Ok(())
    }

    /// CB:739 _handleMenuMode — PART 2: NOT PORTED YET.
    /// Returns the (possibly updated) candidates.
    pub fn handle_menu_mode(
        &mut self,
        _key_event: &KeyEvent,
        _char_str: &str,
        _char_code: u32,
        _key_code: u32,
        candidates: Vec<String>,
    ) -> Result<Vec<String>, String> {
        // CB:739
        Ok(candidates)
    }
}
