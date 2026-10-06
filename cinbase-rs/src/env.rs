//! Everything the backend reads from or does to the machine, behind one switch.
//!
//! Production: the real clock, ShellExecuteW / PlaySound, GetKeyState and the
//! Windows app theme. Test mode (environment variable `WIME_TEST_MODE=1`, set by
//! tests/diffharness/driver.py) follows the harness conventions of
//! tests/diffharness/README.md, exactly like py_reference_backend.py:
//! - a virtual clock starting at CLOCK_START that moves CLOCK_STEP per request
//!   and by `__advanceClock` requests
//! - nothing is launched or played; the attempts are reported in the reply as
//!   `_testLaunches` / `_testSounds`
//! - Caps Lock reads as off, no key reads as physically down, the theme is light

use std::cell::RefCell;
use std::time::{SystemTime, UNIX_EPOCH};

pub const CLOCK_START: f64 = 1_700_000_000.0;
pub const CLOCK_STEP: f64 = 0.01;

struct State {
    test_mode: bool,
    virtual_now: f64,
    launches: Vec<(String, String)>,
    sounds: Vec<String>,
}

thread_local! {
    static STATE: RefCell<State> = RefCell::new(State {
        test_mode: std::env::var("WIME_TEST_MODE").map(|v| v == "1").unwrap_or(false),
        virtual_now: CLOCK_START,
        launches: Vec::new(),
        sounds: Vec::new(),
    });
}

pub fn test_mode() -> bool {
    STATE.with(|s| s.borrow().test_mode)
}

#[cfg(test)]
pub fn set_test_mode(on: bool) {
    STATE.with(|s| s.borrow_mut().test_mode = on);
}

/// Python's time.time(): seconds since the epoch.
pub fn time() -> f64 {
    STATE.with(|s| {
        let s = s.borrow();
        if s.test_mode {
            s.virtual_now
        } else {
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_secs_f64())
                .unwrap_or(0.0)
        }
    })
}

/// Python's time.monotonic(). The virtual clock serves both, like the reference.
pub fn monotonic() -> f64 {
    if test_mode() {
        return time();
    }
    use std::sync::OnceLock;
    use std::time::Instant;
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed().as_secs_f64() + 1.0
}

/// Called by the server before every request (test mode only moves the clock).
pub fn begin_request() {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        if s.test_mode {
            s.virtual_now += CLOCK_STEP;
        }
        s.launches.clear();
        s.sounds.clear();
    });
}

pub fn advance_clock(seconds: f64) {
    STATE.with(|s| s.borrow_mut().virtual_now += seconds);
}

/// What the request tried to launch / play, for `_testLaunches` / `_testSounds`.
pub fn take_side_effects() -> (Vec<(String, String)>, Vec<String>) {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        (std::mem::take(&mut s.launches), std::mem::take(&mut s.sounds))
    })
}

fn basename(path: &str) -> String {
    let trimmed = path.trim_matches('"');
    let first = trimmed.split("\" ").next().unwrap_or(trimmed);
    first.rsplit(['\\', '/']).next().unwrap_or(first).to_string()
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// ShellExecuteW(None, "open", file, params, None, SW_SHOWNORMAL) as the Python
/// code calls it (python.exe "<configtool.py>" ...).
pub fn shell_execute(file: &str, params: &str) {
    if test_mode() {
        STATE.with(|s| s.borrow_mut().launches.push(("ShellExecuteW".into(), basename(file))));
        return;
    }
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;
    let verb = wide("open");
    let file_w = wide(file);
    let params_w = wide(params);
    unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            verb.as_ptr(),
            file_w.as_ptr(),
            if params.is_empty() { std::ptr::null() } else { params_w.as_ptr() },
            std::ptr::null(),
            SW_SHOWNORMAL,
        );
    }
}

/// os.startfile(url)
pub fn startfile(target: &str) {
    if test_mode() {
        STATE.with(|s| s.borrow_mut().launches.push(("startfile".into(), basename(target))));
        return;
    }
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;
    let target_w = wide(target);
    unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            std::ptr::null(),
            target_w.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            SW_SHOWNORMAL,
        );
    }
}

/// winsound.PlaySound(alias, SND_ASYNC)
pub fn play_sound(alias: &str) {
    if test_mode() {
        STATE.with(|s| s.borrow_mut().sounds.push(alias.to_string()));
        return;
    }
    use windows_sys::Win32::Media::Audio::{PlaySoundW, SND_ALIAS, SND_ASYNC};
    let alias_w = wide(alias);
    unsafe {
        PlaySoundW(alias_w.as_ptr(), std::ptr::null_mut(), SND_ASYNC | SND_ALIAS);
    }
}

/// windll.user32.GetKeyState(vk)
pub fn get_key_state(vk: u32) -> i16 {
    if test_mode() {
        return 0;
    }
    unsafe { windows_sys::Win32::UI::Input::KeyboardAndMouse::GetKeyState(vk as i32) }
}

/// windll.user32.GetAsyncKeyState(vk) >= 1
pub fn is_pressed(vk: u32) -> bool {
    if test_mode() {
        return false;
    }
    unsafe { windows_sys::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState(vk as i32) >= 1 }
}

/// HKCU\...\Themes\Personalize\AppsUseLightTheme (candidate_theme.systemPrefersLightTheme,
/// which caches for 5 seconds; callers keep that cache)
pub fn system_prefers_light_theme() -> bool {
    if test_mode() {
        return true;
    }
    use windows_sys::Win32::System::Registry::{RegGetValueW, HKEY_CURRENT_USER, RRF_RT_REG_DWORD};
    let key = wide(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
    let value = wide("AppsUseLightTheme");
    let mut data: u32 = 0;
    let mut size: u32 = 4;
    let status = unsafe {
        RegGetValueW(
            HKEY_CURRENT_USER,
            key.as_ptr(),
            value.as_ptr(),
            RRF_RT_REG_DWORD,
            std::ptr::null_mut(),
            &mut data as *mut u32 as *mut _,
            &mut size,
        )
    };
    status == 0 && data != 0
}
