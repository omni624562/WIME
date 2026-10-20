//! Fuzz targets: what wime-cinbase.exe and wime-config.exe do with input they
//! do not control. Each target takes arbitrary bytes and must neither panic nor
//! fail a request that is well formed.
//!
//! - cinbase-rs/fuzz (cargo-fuzz, nightly) runs them under libFuzzer:
//!   `cargo +nightly fuzz run <target>` in cinbase-rs (see fuzz/README.md);
//! - tests/fuzz_corpus.rs replays the saved inputs (fuzz/corpus, fuzz/regressions)
//!   with stable `cargo test`, so every CI run checks them again.
//!
//! The targets write only below a temporary folder: setup() points APPDATA and
//! LOCALAPPDATA there and turns test mode on (no programs launched, no sounds).

use crate::backend::{handle_line, Clients};
use crate::configtool::{assets::Assets, chewing_tool::ChewingTool, cinbase_tool::CinbaseTool, multipart, pyjson, server};
use crate::{chewing, cinbase, env};

use serde_json::{json, Map, Value};
use std::path::PathBuf;
use std::sync::Once;

/// The access token of the settings-tool apps here (the seeds log in with it).
pub const TOKEN: &str = "0123456789abcdef0123456789abcdef";

/// The temporary folder APPDATA and LOCALAPPDATA point to.
pub fn work_dir() -> PathBuf {
    std::env::temp_dir().join(format!("wime-fuzz-{}", std::process::id()))
}

/// Once per process: the temporary profile folders and the data root (the
/// repo's python folder unless WIME_DATA_DIR says otherwise); test mode on the
/// calling thread.
pub fn setup() {
    static ONCE: Once = Once::new();
    ONCE.call_once(|| {
        let dir = work_dir();
        std::fs::create_dir_all(&dir).expect("cannot create the fuzz work folder");
        std::env::set_var("APPDATA", &dir);
        std::env::set_var("LOCALAPPDATA", &dir);
        if std::env::var_os("WIME_DATA_DIR").is_none() {
            std::env::set_var("WIME_DATA_DIR", concat!(env!("CARGO_MANIFEST_DIR"), "\\..\\python"));
        }
    });
    env::set_test_mode(true);
}

/// libFuzzer (cargo-fuzz `init:`): a panic must reach libFuzzer as SIGABRT so it
/// saves the input. libfuzzer-sys's own hook calls process::abort, which on
/// Windows is __fastfail: the process dies before libFuzzer can write anything.
/// The hook runs before unwinding, so a panic the code catches (the settings
/// tool answers 500) is reported too.
pub fn init_libfuzzer() {
    unsafe extern "C" {
        fn raise(sig: i32) -> i32;
    }
    const SIGABRT: i32 = 22;
    std::panic::set_hook(Box::new(|info| {
        eprintln!("{}", info);
        unsafe { raise(SIGABRT) };
        std::process::abort();
    }));
}

/// Reads the fuzz input as a little program; past the end it returns zeros.
struct Input<'a>(&'a [u8]);

impl Input<'_> {
    fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
    fn byte(&mut self) -> u8 {
        match self.0.split_first() {
            Some((&b, rest)) => {
                self.0 = rest;
                b
            }
            None => 0,
        }
    }
    fn u16(&mut self) -> u16 {
        u16::from_le_bytes([self.byte(), self.byte()])
    }
    fn bool(&mut self) -> bool {
        self.byte() & 1 != 0
    }
    fn pick<T: Copy>(&mut self, items: &[T]) -> T {
        items[self.byte() as usize % items.len()]
    }
}

// --- the backend -------------------------------------------------------------

const IMES: [&str; 3] = [cinbase::CHEDAYI_GUID, cinbase::CHECJ_GUID, chewing::CHEWING_GUID];
const VK_SHIFT: u8 = 0x10;
const VK_CONTROL: u8 = 0x11;
const VK_MENU: u8 = 0x12;
const VK_CAPITAL: u8 = 0x14;
const GUIDS: [&str; 3] = [
    cinbase::SHIFT_SPACE_GUID,
    "{58273aad-01bb-4164-95c6-755ba0b5162d}", // GUID_COMPARTMENT_KEYBOARD_OPENCLOSE
    "{00000000-0000-0000-0000-000000000000}",
];

/// OEM keys on a US keyboard: (virtual key, character, with Shift)
const PUNCTUATION: [(u8, char, char); 11] = [
    (0xBA, ';', ':'), (0xBB, '=', '+'), (0xBC, ',', '<'), (0xBD, '-', '_'), (0xBE, '.', '>'), (0xBF, '/', '?'),
    (0xC0, '`', '~'), (0xDB, '[', '{'), (0xDC, '\\', '|'), (0xDD, ']', '}'), (0xDE, '\'', '"'),
];

/// The character a key gives, roughly like ToUnicode on a US keyboard.
fn char_code(key_code: u8, shift: bool) -> u32 {
    match key_code {
        b'A'..=b'Z' if shift => key_code as u32,
        b'A'..=b'Z' => (key_code + 32) as u32,
        b'0'..=b'9' if !shift => key_code as u32,
        0x20 | 0x0D | 0x08 | 0x1B | 0x09 => key_code as u32,
        _ => PUNCTUATION
            .iter()
            .find(|(vk, _, _)| *vk == key_code)
            .map(|&(_, plain, shifted)| if shift { shifted } else { plain } as u32)
            .unwrap_or(0),
    }
}

/// Keys that matter to the input methods (letters, digits, punctuation,
/// editing and paging keys), and now and then any key code at all.
fn key_code(input: &mut Input) -> u8 {
    let b = input.byte();
    match b % 4 {
        0 => b'A' + input.byte() % 26,
        1 => b'0' + input.byte() % 10,
        2 => input.pick(&[0x20, 0x0D, 0x08, 0x1B, 0x09, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E,
                          0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE, VK_SHIFT, VK_CONTROL]),
        _ => input.byte(),
    }
}

fn key_event(method: &str, key_code: u8, modifiers: u8, char_code_override: Option<u32>) -> Value {
    let shift = modifiers & 1 != 0;
    let mut states = Map::new();
    for (bit, vk) in [(1, VK_SHIFT), (2, VK_CONTROL), (4, VK_MENU)] {
        if modifiers & bit != 0 {
            states.insert(vk.to_string(), json!(0x80));
        }
    }
    if modifiers & 8 != 0 {
        states.insert(VK_CAPITAL.to_string(), json!(1));
    }
    if method.contains("Down") {
        states.insert(key_code.to_string(), json!(0x80));
    }
    json!({
        "method": method,
        "keyCode": key_code,
        "charCode": char_code_override.unwrap_or_else(|| char_code(key_code, shift)),
        "repeatCount": 1,
        "scanCode": 0,
        "isExtended": false,
        "keyStates": states,
    })
}

thread_local! {
    static COMMITTED: std::cell::RefCell<String> = const { std::cell::RefCell::new(String::new()) };
}

/// What the backend target committed on this thread since the last call (the
/// replay test checks that the typing seeds really type).
pub fn take_committed() -> String {
    COMMITTED.with_borrow_mut(std::mem::take)
}

/// Sends one request; panics on a failed request (the backend would answer
/// success:false) or a reply the TSF DLL cannot use.
fn send(clients: &mut Clients, seq: &mut u64, mut request: Value) -> Option<Map<String, Value>> {
    *seq += 1;
    request["seqNum"] = json!(*seq);
    let text = request.to_string();
    if std::env::var_os("WIME_FUZZ_TRACE").is_some() {
        eprintln!("> {}", text);
    }
    match handle_line(clients, "fuzz", &text) {
        Ok(reply) => {
            if let Some(reply) = &reply {
                check_reply(reply, &text);
                if let Some(commit) = reply.get("commitString").and_then(Value::as_str) {
                    COMMITTED.with_borrow_mut(|c| c.push_str(commit));
                }
            }
            reply
        }
        Err(e) => panic!("request failed: {}\nrequest: {}", e, text),
    }
}

/// The reply fields PIMETextService reads have the types it expects. The
/// values may be out of range -- 大易's symbol table commits with the cursor
/// at 1 in an empty composition string, exactly like the Python backend -- and
/// the DLL clamps them (PIMEClient.cpp), which its own fuzz target checks.
fn check_reply(reply: &Map<String, Value>, request: &str) {
    let fail = |field: &str| panic!("{} has the wrong type
request: {}
reply: {:?}", field, request, reply);
    for field in ["compositionCursor", "candidateCursor"] {
        if reply.get(field).is_some_and(|v| !v.is_i64()) {
            fail(field);
        }
    }
    for field in ["compositionString", "commitString", "candidateHeader", "candidatePageInfo"] {
        if reply.get(field).is_some_and(|v| !v.is_string()) {
            fail(field);
        }
    }
    if let Some(list) = reply.get("candidateList") {
        if !list.as_array().is_some_and(|items| items.iter().all(Value::is_string)) {
            fail("candidateList");
        }
    }
}

/// One client of one input method: init, activate, then keys and commands.
pub fn backend(data: &[u8]) {
    setup();
    let mut input = Input(data);
    let mut clients = Clients::new();
    let mut seq = 0;
    let guid = input.pick(&IMES);
    let init = json!({"method": "init", "id": guid, "isWindows8Above": true, "isMetroApp": input.bool(),
                      "isUiLess": input.bool(), "isConsole": input.bool()});
    send(&mut clients, &mut seq, init.clone());
    send(&mut clients, &mut seq, json!({"method": "onActivate", "isKeyboardOpen": true}));
    let mut ops = 0;
    while !input.is_empty() && ops < 400 {
        ops += 1;
        match input.byte() % 16 {
            // a key press: down and up, like typing
            0..=7 => {
                let key = key_code(&mut input);
                let modifiers = if input.byte() % 4 == 0 { input.byte() } else { 0 };
                for method in ["filterKeyDown", "onKeyDown", "filterKeyUp", "onKeyUp"] {
                    let event = key_event(method, key, modifiers, None);
                    let reply = send(&mut clients, &mut seq, event);
                    // the DLL sends onKeyX only when filterKeyX returned true
                    if method.starts_with("filter") && reply.as_ref().and_then(|r| r.get("return")) != Some(&json!(true)) {
                        break;
                    }
                }
            }
            // one key event alone, with any character code
            8 => {
                let method = input.pick(&["filterKeyDown", "onKeyDown", "filterKeyUp", "onKeyUp"]);
                let key = key_code(&mut input);
                let modifiers = input.byte();
                let char_code = input.u16() as u32;
                let event = key_event(method, key, modifiers, Some(char_code));
                send(&mut clients, &mut seq, event);
            }
            9 => {
                let id = input.byte() as u32;
                let kind = input.byte() % 3;
                send(&mut clients, &mut seq, json!({"method": "onCommand", "id": id, "type": kind}));
            }
            10 => {
                let id = input.byte() as u32;
                send(&mut clients, &mut seq, json!({"method": "onMenu", "id": id}));
            }
            11 => {
                let guid = input.pick(&GUIDS);
                let method = input.pick(&["onCompartmentChanged", "onPreservedKey"]);
                send(&mut clients, &mut seq, json!({"method": method, "guid": guid}));
            }
            12 => {
                let opened = input.bool();
                send(&mut clients, &mut seq, json!({"method": "onKeyboardStatusChanged", "opened": opened}));
            }
            13 => {
                let forced = input.bool();
                send(&mut clients, &mut seq, json!({"method": "onCompositionTerminated", "forced": forced}));
            }
            14 => {
                send(&mut clients, &mut seq, json!({"method": "onKillFocus"}));
            }
            _ => match input.byte() % 3 {
                // switching to another keyboard and back. The DLL never activates a
                // client again: TextService::closeClient sends onDeactivate and drops
                // the connection, and the next activation is a new client (init,
                // onActivate). A deactivated 大易 client typing again fails -- the
                // symbol tables are gone, as in the Python backend -- but no DLL does that.
                0 => {
                    send(&mut clients, &mut seq, json!({"method": "onDeactivate"}));
                    send(&mut clients, &mut seq, json!({"method": "close"}));
                    let open = input.bool();
                    send(&mut clients, &mut seq, init.clone());
                    send(&mut clients, &mut seq, json!({"method": "onActivate", "isKeyboardOpen": open}));
                }
                1 => {
                    let seconds = input.byte() as f64 / 4.0;
                    send(&mut clients, &mut seq, json!({"method": "__advanceClock", "seconds": seconds}));
                }
                _ => {
                    send(&mut clients, &mut seq, json!({"method": "ping"}));
                }
            },
        }
    }
    send(&mut clients, &mut seq, json!({"method": "onDeactivate"}));
    send(&mut clients, &mut seq, json!({"method": "close"}));
}

/// Raw request lines, as the launcher passes them on: anything a TSF client
/// writes to its pipe reaches the backend this way.
pub fn backend_raw(data: &[u8]) {
    setup();
    let mut clients = Clients::new();
    for line in String::from_utf8_lossy(data).lines().take(200) {
        let line = line.trim();
        if let Some((client_id, msg)) = line.split_once('|') {
            // malformed requests may fail (success:false), never panic
            let _ = handle_line(&mut clients, client_id, msg);
        }
    }
}

// --- the settings tools --------------------------------------------------------

thread_local! {
    static APPS: Vec<server::App> = {
        setup();
        vec![
            server::App::with_token(Box::new(CinbaseTool::new("chedayi", Assets::from_env())), TOKEN),
            server::App::with_token(Box::new(CinbaseTool::new("checj", Assets::from_env())), TOKEN),
            server::App::with_token(Box::new(ChewingTool::new(Assets::from_env())), TOKEN),
        ]
    };
}

/// One connection to a settings tool: the first byte picks the tool, the rest
/// is what the browser (or any local program) sends.
pub fn config_http(data: &[u8]) {
    setup();
    let Some((&which, raw)) = data.split_first() else { return };
    APPS.with(|apps| {
        let app = &apps[which as usize % apps.len()];
        let mut reader = std::io::BufReader::new(raw);
        let mut out = Vec::new();
        for _ in 0..50 {
            match app.handle_one_request(&mut reader, &mut out) {
                Ok(true) => continue,
                _ => break,
            }
        }
    });
}

/// multipart/form-data bodies: content type, a zero byte, the body.
pub fn multipart(data: &[u8]) {
    let (content_type, body) = match data.iter().position(|&b| b == 0) {
        Some(i) => (&data[..i], &data[i + 1..]),
        None => (data, &[][..]),
    };
    let content_type = String::from_utf8_lossy(content_type);
    for part in multipart::parse_files(&content_type, body) {
        let _ = part;
    }
    let _ = multipart::header_params(&content_type);
}

/// Cookies, query strings and percent-encoding.
pub fn http_fields(data: &[u8]) {
    let text = String::from_utf8_lossy(data);
    let _ = server::get_cookie(&text, "WIMEConfig");
    let _ = server::parse_qsl(&text);
    let _ = server::unquote(&text);
}

/// The JSON a settings page posts: loads, and what dumps writes loads back the same.
pub fn json_body(data: &[u8]) {
    if let Ok(value) = pyjson::loads(data) {
        let text = pyjson::dumps(&value);
        let again = pyjson::loads(text.as_bytes()).unwrap_or_else(|e| panic!("dumps wrote JSON loads rejects: {}\n{}", e, text));
        assert_eq!(pyjson::dumps(&again), text);
        let _ = pyjson::dumps_indent(&value, 4, true);
    }
}

/// An uploaded 新酷音 user dictionary (chewing.dat, or an old chewing.sqlite3)
/// through libchewing.
pub fn user_dictionary(data: &[u8]) {
    setup();
    let config_dir = work_dir().join("PIME").join("chewing");
    let syspath = format!("{};{}", config_dir.display(), Assets::from_env().chewing_data_dir().display());
    let _ = chewing::userdict::import_user_dictionary(data, &config_dir, &syspath);
}
