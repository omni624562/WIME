//! Port of python/libchewing/libchewing.py: the libchewing context the 新酷音
//! frontend drives.
//!
//! The Python backend loads python/libchewing/chewing.dll through ctypes; that
//! DLL is libchewing's C API crate (chewing_capi, tag v0.13.1) built by
//! tools/build_libchewing.ps1. Here the same crate is linked in-process and the
//! same C API functions are called directly, so every key goes through exactly
//! the code the DLL runs (KB types, selection keys, the logger trick used to
//! detect a broken user dictionary, CHEWING_USER_PATH, ...).

use chewing_capi::candidates::*;
use chewing_capi::globals::*;
use chewing_capi::input::*;
use chewing_capi::layout::*;
use chewing_capi::modes::*;
use chewing_capi::output::*;
use chewing_capi::setup::*;
use chewing_capi::userphrase::*;
use std::cell::RefCell;
use std::ffi::{c_char, c_int, c_uint, c_void, CStr, CString};

// from libchewing/include/global.h (libchewing/__init__.py)
pub const CHINESE_MODE: i64 = 1;
pub const ENGLISH_MODE: i64 = 0;
pub const FULLSHAPE_MODE: i64 = 1;
pub const HALFSHAPE_MODE: i64 = 0;

/// SYSTEM_DICTIONARIES: only the built-in dictionaries (see libchewing.py)
const SYSTEM_DICTIONARIES: &CStr = c"word.dat,tsi.dat";
const LOG_ERROR: c_int = 5;
const USER_DICT_FAILED: &[u8] = b"Failed to load user dict";
const SYSTEM_DICT_FAILED: &[u8] = b"Failed to load any system dictionaries";

thread_local! {
    /// ChewingContext._errors of the context being created
    static LOG_ERRORS: RefCell<Vec<Vec<u8>>> = const { RefCell::new(Vec::new()) };
}

/// ChewingContext._log. libchewing calls its logger as
/// logger(data, level, "%s\n", message): declared with two string arguments
/// and cast to the C-variadic type the API takes (cdecl: the caller cleans the
/// stack, exactly what the ctypes CFUNCTYPE in libchewing.py relies on).
unsafe extern "C" fn log_callback(_data: *mut c_void, level: c_int, _fmt: *const c_char, message: *const c_char) {
    if level < LOG_ERROR || message.is_null() {
        return;
    }
    let mut text = unsafe { CStr::from_ptr(message) }.to_bytes().to_vec();
    while text.last() == Some(&b'\n') {
        text.pop();
    }
    if text.is_empty() {
        return;
    }
    // "[src/editor/mod.rs:203 chewing::editor] Failed to load user dict: ..."
    if text.starts_with(b"[") {
        if let Some(pos) = text.windows(2).position(|w| w == b"] ") {
            text = text[pos + 2..].to_vec();
        }
    }
    LOG_ERRORS.with_borrow_mut(|errors| {
        if errors.len() < 20 {
            errors.push(text);
        }
    });
}

type ExternLogger = unsafe extern "C" fn(data: *mut c_void, level: c_int, fmt: *const c_char, ...);

fn logger() -> ExternLogger {
    let f: unsafe extern "C" fn(*mut c_void, c_int, *const c_char, *const c_char) = log_callback;
    // SAFETY: same calling convention (C), the callee reads exactly the one
    // variadic argument libchewing always passes
    unsafe { std::mem::transmute::<unsafe extern "C" fn(*mut c_void, c_int, *const c_char, *const c_char), ExternLogger>(f) }
}

/// decodeText(): UTF-8 with replacement, NULL/empty -> ""
fn decode(ptr: *const c_char) -> String {
    if ptr.is_null() {
        return String::new();
    }
    String::from_utf8_lossy(unsafe { CStr::from_ptr(ptr) }.to_bytes()).into_owned()
}

/// A ctypes int argument: Python ints outside a C int raise ArgumentError.
pub fn c_int_arg(v: i64) -> Result<c_int, String> {
    c_int::try_from(v).map_err(|_| "ctypes.ArgumentError: int too long to convert".to_string())
}

/// The ChewingContext of libchewing.py.
pub struct ChewingContext {
    ctx: *mut ChewingContext_,
}

type ChewingContext_ = chewing_capi::setup::ChewingContext;

/// libchewing._setUserDataDir: CHEWING_USER_PATH for the process
fn set_user_data_dir(userdir: &str) {
    if !userdir.is_empty() {
        // SAFETY: the backend is single-threaded
        unsafe { std::env::set_var("CHEWING_USER_PATH", userdir) };
    }
}

impl ChewingContext {
    /// ChewingContext(syspath=..., userpath=..., userdir=..., detectErrors=...)
    pub fn new(syspath: &str, userpath: &str, userdir: Option<&str>, detect_errors: bool) -> Result<ChewingContext, String> {
        let userdir = match userdir {
            Some(d) => d.to_string(),
            None if !userpath.is_empty() && userpath != ":memory:" => std::path::Path::new(userpath)
                .parent()
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_default(),
            None => String::new(),
        };
        set_user_data_dir(&userdir);
        let sys = CString::new(syspath).map_err(|e| e.to_string())?;
        let user = CString::new(userpath).map_err(|e| e.to_string())?;
        LOG_ERRORS.with_borrow_mut(|e| e.clear());
        let log = if detect_errors { Some(logger()) } else { None };
        let ctx = unsafe { chewing_new3(sys.as_ptr(), user.as_ptr(), SYSTEM_DICTIONARIES.as_ptr(), log, std::ptr::null_mut()) };
        if !ctx.is_null() && log.is_some() {
            unsafe { chewing_set_logger(ctx, None, std::ptr::null_mut()) };
        }
        if ctx.is_null() {
            return Err("chewing_new3() failed".into());
        }
        let context = ChewingContext { ctx };
        let errors = LOG_ERRORS.with_borrow_mut(std::mem::take);
        let failed: Vec<Vec<u8>> = errors
            .into_iter()
            .filter(|m| m.starts_with(USER_DICT_FAILED) || m.starts_with(SYSTEM_DICT_FAILED))
            .collect();
        if !failed.is_empty() {
            drop(context);
            return Err(String::from_utf8_lossy(&failed.join(&b"; "[..])).into_owned());
        }
        Ok(context)
    }

    fn p(&self) -> *mut ChewingContext_ {
        self.ctx
    }

    // -- settings -----------------------------------------------------------
    pub fn set_max_chi_symbol_len(&mut self, n: c_int) {
        unsafe { chewing_set_maxChiSymbolLen(self.p(), n) }
    }
    pub fn set_chi_eng_mode(&mut self, mode: c_int) {
        unsafe { chewing_set_ChiEngMode(self.p(), mode) }
    }
    pub fn get_chi_eng_mode(&self) -> i64 {
        unsafe { chewing_get_ChiEngMode(self.p()) as i64 }
    }
    pub fn set_shape_mode(&mut self, mode: c_int) {
        unsafe { chewing_set_ShapeMode(self.p(), mode) }
    }
    pub fn get_shape_mode(&self) -> i64 {
        unsafe { chewing_get_ShapeMode(self.p()) as i64 }
    }
    pub fn set_add_phrase_direction(&mut self, v: c_int) {
        unsafe { chewing_set_addPhraseDirection(self.p(), v) }
    }
    pub fn set_auto_shift_cur(&mut self, v: c_int) {
        unsafe { chewing_set_autoShiftCur(self.p(), v) }
    }
    pub fn set_cand_per_page(&mut self, v: c_int) {
        unsafe { chewing_set_candPerPage(self.p(), v) }
    }
    pub fn set_esc_clean_all_buf(&mut self, v: c_int) {
        unsafe { chewing_set_escCleanAllBuf(self.p(), v) }
    }
    pub fn set_kb_type(&mut self, v: c_int) {
        unsafe { chewing_set_KBType(self.p(), v) };
    }
    pub fn set_space_as_selection(&mut self, v: c_int) {
        unsafe { chewing_set_spaceAsSelection(self.p(), v) }
    }
    pub fn set_auto_learn(&mut self, v: c_int) {
        unsafe { chewing_set_autoLearn(self.p(), v) }
    }
    pub fn set_phrase_choice_rearward(&mut self, v: c_int) {
        unsafe { chewing_set_phraseChoiceRearward(self.p(), v) }
    }
    pub fn set_easy_symbol_input(&mut self, v: c_int) {
        unsafe { chewing_set_easySymbolInput(self.p(), v) }
    }
    pub fn get_easy_symbol_input(&self) -> i64 {
        unsafe { chewing_get_easySymbolInput(self.p()) as i64 }
    }
    /// set_selKeys(str)
    pub fn set_sel_keys(&mut self, keys: &str) {
        let codes: Vec<c_int> = keys.chars().map(|c| c as c_int).collect();
        unsafe { chewing_set_selKey(self.p(), codes.as_ptr(), codes.len() as c_int) }
    }

    // -- keys -----------------------------------------------------------------
    pub fn handle_default(&mut self, key: c_int) {
        unsafe { chewing_handle_Default(self.p(), key) };
    }
    pub fn handle_ctrl_num(&mut self, key: c_int) {
        unsafe { chewing_handle_CtrlNum(self.p(), key) };
    }
    pub fn handle_numlock(&mut self, key: c_int) {
        unsafe { chewing_handle_Numlock(self.p(), key) };
    }
    pub fn handle_space(&mut self) {
        unsafe { chewing_handle_Space(self.p()) };
    }
    pub fn handle_page_down(&mut self) {
        unsafe { chewing_handle_PageDown(self.p()) };
    }
    pub fn handle_page_up(&mut self) {
        unsafe { chewing_handle_PageUp(self.p()) };
    }
    pub fn handle_down(&mut self) {
        unsafe { chewing_handle_Down(self.p()) };
    }
    pub fn handle_left(&mut self) {
        unsafe { chewing_handle_Left(self.p()) };
    }
    pub fn handle_right(&mut self) {
        unsafe { chewing_handle_Right(self.p()) };
    }
    /// getattr(chewingContext, "handle_" + keyNames[keyCode])()
    pub fn handle_named(&mut self, name: &str) {
        let p = self.p();
        unsafe {
            match name {
                "Esc" => chewing_handle_Esc(p),
                "Enter" => chewing_handle_Enter(p),
                "Tab" => chewing_handle_Tab(p),
                "Del" => chewing_handle_Del(p),
                "Backspace" => chewing_handle_Backspace(p),
                "Up" => chewing_handle_Up(p),
                "Down" => chewing_handle_Down(p),
                "Left" => chewing_handle_Left(p),
                "Right" => chewing_handle_Right(p),
                "Home" => chewing_handle_Home(p),
                "End" => chewing_handle_End(p),
                "PageUp" => chewing_handle_PageUp(p),
                "PageDown" => chewing_handle_PageDown(p),
                _ => 0,
            }
        };
    }

    // -- output -----------------------------------------------------------------
    pub fn keystroke_check_ignore(&self) -> bool {
        unsafe { chewing_keystroke_CheckIgnore(self.p()) != 0 }
    }
    pub fn cand_total_choice(&self) -> i64 {
        unsafe { chewing_cand_TotalChoice(self.p()) as i64 }
    }
    pub fn cand_total_page(&self) -> i64 {
        unsafe { chewing_cand_TotalPage(self.p()) as i64 }
    }
    pub fn cand_current_page(&self) -> i64 {
        unsafe { chewing_cand_CurrentPage(self.p()) as i64 }
    }
    pub fn cand_choice_per_page(&self) -> i64 {
        unsafe { chewing_cand_ChoicePerPage(self.p()) as i64 }
    }
    pub fn cand_enumerate(&mut self) {
        unsafe { chewing_cand_Enumerate(self.p()) }
    }
    pub fn cand_has_next(&mut self) -> bool {
        unsafe { chewing_cand_hasNext(self.p()) != 0 }
    }
    pub fn cand_string(&mut self) -> String {
        decode(unsafe { chewing_cand_String_static(self.p()) })
    }
    pub fn cand_string_by_index(&mut self, i: c_int) -> String {
        decode(unsafe { chewing_cand_string_by_index_static(self.p(), i) })
    }
    pub fn cand_close(&mut self) {
        unsafe { chewing_cand_close(self.p()) };
    }
    pub fn commit_check(&self) -> bool {
        unsafe { chewing_commit_Check(self.p()) != 0 }
    }
    pub fn commit_string(&self) -> String {
        decode(unsafe { chewing_commit_String_static(self.p()) })
    }
    pub fn buffer_check(&self) -> bool {
        unsafe { chewing_buffer_Check(self.p()) != 0 }
    }
    pub fn buffer_string(&self) -> String {
        decode(unsafe { chewing_buffer_String_static(self.p()) })
    }
    pub fn bopomofo_check(&self) -> bool {
        unsafe { chewing_bopomofo_Check(self.p()) != 0 }
    }
    pub fn bopomofo_string(&self) -> String {
        decode(unsafe { chewing_bopomofo_String_static(self.p()) })
    }
    pub fn cursor_current(&self) -> i64 {
        unsafe { chewing_cursor_Current(self.p()) as i64 }
    }
    pub fn aux_check(&self) -> bool {
        unsafe { chewing_aux_Check(self.p()) != 0 }
    }
    pub fn aux_string(&self) -> String {
        decode(unsafe { chewing_aux_String_static(self.p()) })
    }
    pub fn clean_bopomofo_buf(&mut self) {
        unsafe { chewing_clean_bopomofo_buf(self.p()) };
    }
    pub fn clean_preedit_buf(&mut self) {
        unsafe { chewing_clean_preedit_buf(self.p()) };
    }
    pub fn commit_preedit_buf(&mut self) {
        unsafe { chewing_commit_preedit_buf(self.p()) };
    }

    // -- user phrases -------------------------------------------------------------
    /// userPhrases(): [(phrase, bopomofo)]
    pub fn user_phrases(&mut self) -> Vec<(String, String)> {
        let mut phrases = Vec::new();
        let mut phrase_len: c_uint = 0;
        let mut bopomofo_len: c_uint = 0;
        unsafe {
            chewing_userphrase_enumerate(self.p());
            while chewing_userphrase_has_next(self.p(), &mut phrase_len, &mut bopomofo_len) == 1 {
                let mut phrase_buf = vec![0u8; phrase_len as usize + 1];
                let mut bopomofo_buf = vec![0u8; bopomofo_len as usize + 1];
                if chewing_userphrase_get(
                    self.p(),
                    phrase_buf.as_mut_ptr() as *mut c_char,
                    phrase_len,
                    bopomofo_buf.as_mut_ptr() as *mut c_char,
                    bopomofo_len,
                ) != 0
                {
                    break;
                }
                // create_string_buffer(n).value: up to the first NUL
                let cut = |b: &[u8]| {
                    let end = b.iter().position(|&c| c == 0).unwrap_or(b.len());
                    String::from_utf8_lossy(&b[..end]).into_owned()
                };
                phrases.push((cut(&phrase_buf[..phrase_len as usize]), cut(&bopomofo_buf[..bopomofo_len as usize])));
            }
        }
        phrases
    }

    pub fn userphrase_add(&mut self, phrase: &str, bopomofo: &str) {
        if let (Ok(p), Ok(b)) = (CString::new(phrase), CString::new(bopomofo)) {
            unsafe { chewing_userphrase_add(self.p(), p.as_ptr(), b.as_ptr()) };
        }
    }

    /// chewing_userphrase_add(ctx, bytes, bytes) as ctypes calls it: the strings
    /// end at their first NUL. The C API's return value (<= 0: failed).
    pub fn userphrase_add_bytes(&mut self, phrase: &[u8], bopomofo: &[u8]) -> c_int {
        let (p, b) = (c_string_until_nul(phrase), c_string_until_nul(bopomofo));
        unsafe { chewing_userphrase_add(self.p(), p.as_ptr(), b.as_ptr()) }
    }

    /// chewing_userphrase_remove, like userphrase_add_bytes
    pub fn userphrase_remove_bytes(&mut self, phrase: &[u8], bopomofo: &[u8]) -> c_int {
        let (p, b) = (c_string_until_nul(phrase), c_string_until_nul(bopomofo));
        unsafe { chewing_userphrase_remove(self.p(), p.as_ptr(), b.as_ptr()) }
    }

    pub fn userphrase_remove(&mut self, phrase: &str, bopomofo: &str) {
        if let (Ok(p), Ok(b)) = (CString::new(phrase), CString::new(bopomofo)) {
            unsafe { chewing_userphrase_remove(self.p(), p.as_ptr(), b.as_ptr()) };
        }
    }
}

impl Drop for ChewingContext {
    /// close(): frees the context (and writes the user dictionary)
    fn drop(&mut self) {
        if !self.ctx.is_null() {
            unsafe { chewing_delete(self.ctx) };
            self.ctx = std::ptr::null_mut();
        }
    }
}

/// a C string of bytes up to the first NUL (what C sees of a Python bytes argument)
fn c_string_until_nul(bytes: &[u8]) -> CString {
    let end = bytes.iter().position(|&b| b == 0).unwrap_or(bytes.len());
    CString::new(&bytes[..end]).unwrap_or_default()
}

/// libchewing.version()
pub fn version() -> String {
    decode(chewing_capi::version::chewing_version())
}

