//! Port of python/textService.py: the key event and the reply a text service
//! builds while handling one request.

use serde_json::{json, Map, Value};
use std::collections::HashMap;

/// TSF modifier flag (msctf.h) used for the Shift+Space preserved key.
pub const TF_MOD_SHIFT: u32 = 0x0004;

/// onCommand type
pub const COMMAND_LEFT_CLICK: i64 = 0;
pub const COMMAND_RIGHT_CLICK: i64 = 1;
pub const COMMAND_MENU: i64 = 2;

#[derive(Debug, Clone, Default)]
pub struct KeyEvent {
    pub char_code: u32,
    pub key_code: u32,
    pub repeat_count: i64,
    pub scan_code: u32,
    pub is_extended: bool,
    /// sparse {vk: state}, like the Python dict
    pub key_states: HashMap<u32, i64>,
}

fn as_i64(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
        Value::Bool(b) => Some(*b as i64),
        Value::String(s) => s.trim().parse().ok(),
        _ => None,
    }
}

impl KeyEvent {
    /// KeyEvent(msg). Python raises KeyError on a missing field, which makes the
    /// whole request fail; Err does the same here.
    pub fn from_msg(msg: &Map<String, Value>) -> Result<KeyEvent, String> {
        let field = |name: &str| msg.get(name).ok_or_else(|| format!("KeyError: '{}'", name));
        let char_code = as_i64(field("charCode")?).unwrap_or(0).max(0) as u32;
        let key_code = as_i64(field("keyCode")?).unwrap_or(0).max(0) as u32;
        let repeat_count = as_i64(field("repeatCount")?).unwrap_or(0);
        let scan_code = as_i64(field("scanCode")?).unwrap_or(0).max(0) as u32;
        let is_extended = match field("isExtended")? {
            Value::Bool(b) => *b,
            other => as_i64(other).unwrap_or(0) != 0,
        };
        let mut key_states = HashMap::new();
        match msg.get("keyStates") {
            Some(Value::Object(states)) => {
                for (k, v) in states {
                    if let (Ok(index), Some(value)) = (k.trim().parse::<i64>(), as_i64(v)) {
                        if (0..256).contains(&index) && value != 0 {
                            key_states.insert(index as u32, value);
                        }
                    }
                }
            }
            Some(Value::Array(states)) => {
                for (i, v) in states.iter().enumerate() {
                    if let Some(value) = as_i64(v) {
                        if value != 0 {
                            key_states.insert(i as u32, value);
                        }
                    }
                }
            }
            _ => {}
        }
        Ok(KeyEvent { char_code, key_code, repeat_count, scan_code, is_extended, key_states })
    }

    pub fn is_key_down(&self, code: u32) -> bool {
        self.key_states.get(&code).copied().unwrap_or(0) & (1 << 7) != 0
    }

    pub fn is_key_toggled(&self, code: u32) -> bool {
        self.key_states.get(&code).copied().unwrap_or(0) & 1 != 0
    }

    pub fn is_char(&self) -> bool {
        self.char_code != 0
    }

    pub fn is_printable_char(&self) -> bool {
        self.char_code > 0x1f && self.char_code != 0x7f
    }

    pub fn is_symbols(&self) -> bool {
        [0x3d, 0x5b, 0x5c, 0x5d, 0x27].contains(&self.char_code)
    }

    /// chr(charCode); an invalid code point becomes U+FFFD (Python would raise
    /// only for values > 0x10FFFF, which the DLL never sends)
    pub fn char_str(&self) -> String {
        char::from_u32(self.char_code).map(String::from).unwrap_or_else(|| "\u{FFFD}".into())
    }
}

/// The text service's currentReply plus the attributes TextService keeps in
/// sync with it (compositionString, commitString, candidateList, ...).
#[derive(Debug, Default)]
pub struct TextService {
    pub is_activated: bool,
    pub keyboard_open: bool,
    pub show_candidates: bool,
    pub current_reply: Map<String, Value>,
    pub composition_string: String,
    pub commit_string: String,
    pub candidate_list: Vec<String>,
    pub composition_cursor: i64,
    pub candidate_cursor: i64,
}

impl TextService {
    fn push(&mut self, key: &str, value: Value) {
        let entry = self.current_reply.entry(key.to_string()).or_insert_with(|| Value::Array(vec![]));
        if let Value::Array(items) = entry {
            items.push(value);
        }
    }

    /// addButton(button_id, **kwargs): kwargs in call order, then "id"
    pub fn add_button(&mut self, button_id: &str, mut info: Map<String, Value>) {
        info.insert("id".into(), json!(button_id));
        self.push("addButton", Value::Object(info));
    }

    pub fn remove_button(&mut self, button_id: &str) {
        self.push("removeButton", json!(button_id));
    }

    pub fn change_button(&mut self, button_id: &str, mut info: Map<String, Value>) {
        info.insert("id".into(), json!(button_id));
        self.push("changeButton", Value::Object(info));
    }

    pub fn add_preserved_key(&mut self, key_code: u32, modifiers: u32, guid: &str) {
        self.push("addPreservedKey", json!({"keyCode": key_code, "modifiers": modifiers, "guid": guid.to_lowercase()}));
    }

    pub fn remove_preserved_key(&mut self, guid: &str) {
        self.push("removePreservedKey", json!(guid.to_lowercase()));
    }

    pub fn set_composition_string(&mut self, s: &str) {
        self.composition_string = s.to_string();
        self.current_reply.insert("compositionString".into(), json!(s));
    }

    pub fn set_composition_cursor(&mut self, pos: i64) {
        self.composition_cursor = pos;
        self.current_reply.insert("compositionCursor".into(), json!(pos));
    }

    pub fn set_commit_string(&mut self, s: &str) {
        self.commit_string = s.to_string();
        self.current_reply.insert("commitString".into(), json!(s));
    }

    pub fn set_candidate_list(&mut self, cand: Vec<String>) {
        self.current_reply.insert("candidateList".into(), json!(cand));
        self.candidate_list = cand;
    }

    pub fn set_candidate_cursor(&mut self, pos: i64) {
        self.candidate_cursor = pos;
        self.current_reply.insert("candidateCursor".into(), json!(pos));
    }

    pub fn set_show_candidates(&mut self, show: bool) {
        self.show_candidates = show;
        self.current_reply.insert("showCandidates".into(), json!(show));
    }

    pub fn set_sel_keys(&mut self, keys: &str) {
        self.current_reply.insert("setSelKeys".into(), json!(keys));
    }

    pub fn set_keyboard_open(&mut self, opened: bool) {
        self.keyboard_open = opened;
        self.current_reply.insert("openKeyboard".into(), json!(opened));
    }

    /// customizeUI(**kwargs): merged into one object
    pub fn customize_ui(&mut self, values: Map<String, Value>) {
        let entry = self.current_reply.entry("customizeUI".to_string()).or_insert_with(|| Value::Object(Map::new()));
        if let Value::Object(data) = entry {
            for (k, v) in values {
                data.insert(k, v);
            }
        }
    }

    pub fn is_composing(&self) -> bool {
        !self.composition_string.is_empty() || self.show_candidates
    }

    pub fn show_message(&mut self, message: &str, duration: i64) {
        self.current_reply.insert("showMessage".into(), json!({"message": message, "duration": duration}));
    }

    pub fn hide_message(&mut self) {
        self.current_reply.insert("hideMessage".into(), json!(true));
    }

    /// Base-class behaviour of the events the subclass extends.
    pub fn base_on_composition_terminated(&mut self) {
        self.commit_string.clear();
        self.composition_string.clear();
    }

    pub fn base_on_kill_focus(&mut self) {
        self.commit_string.clear();
        self.composition_string.clear();
        self.candidate_list.clear();
        self.candidate_cursor = 0;
        self.show_candidates = false;
    }
}

/// What a service answers for each request method (textService.handleRequest).
/// `Ok(Some(v))` becomes `"return": v`; `Err` means the Python code would have
/// raised (the server then answers {"success": false}).
pub trait Service {
    fn ts(&mut self) -> &mut TextService;
    fn check_config_change(&mut self) -> Result<(), String> { Ok(()) }
    fn on_activate(&mut self) -> Result<(), String> { Ok(()) }
    fn on_deactivate(&mut self) -> Result<(), String> { Ok(()) }
    fn filter_key_down(&mut self, _ev: &KeyEvent) -> Result<Value, String> { Ok(json!(false)) }
    fn on_key_down(&mut self, _ev: &KeyEvent) -> Result<Value, String> { Ok(json!(false)) }
    fn filter_key_up(&mut self, _ev: &KeyEvent) -> Result<Value, String> { Ok(json!(false)) }
    /// onKeyUp returns None in CinBaseTextService (no "return" field)
    fn on_key_up(&mut self, _ev: &KeyEvent) -> Result<Option<Value>, String> { Ok(Some(json!(false))) }
    fn on_preserved_key(&mut self, _guid: &str) -> Result<Value, String> { Ok(json!(false)) }
    fn on_command(&mut self, _id: &Value, _kind: &Value) -> Result<(), String> { Ok(()) }
    /// None: no "return" field
    fn on_menu(&mut self, _button_id: &Value) -> Result<Option<Value>, String> { Ok(None) }
    fn on_compartment_changed(&mut self, _guid: &str) {}
    fn on_keyboard_status_changed(&mut self, opened: bool) -> Result<(), String> {
        self.ts().keyboard_open = opened;
        Ok(())
    }
    fn on_composition_terminated(&mut self, _forced: bool) -> Result<(), String> {
        self.ts().base_on_composition_terminated();
        Ok(())
    }
    fn on_kill_focus(&mut self) -> Result<(), String> {
        self.ts().base_on_kill_focus();
        Ok(())
    }
}

fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// textService.TextService.handleRequest
pub fn handle_request(service: &mut dyn Service, msg: &Map<String, Value>) -> Result<Map<String, Value>, String> {
    let method = msg.get("method").and_then(|m| m.as_str()).unwrap_or("").to_string();
    let seq_num = msg.get("seqNum").cloned().unwrap_or(json!(0));
    let mut success = true;
    let mut ret: Option<Value> = None;

    if service.ts().is_activated {
        service.check_config_change()?;
    }
    let field = |name: &str| msg.get(name).cloned().ok_or_else(|| format!("KeyError: '{}'", name));
    match method.as_str() {
        "filterKeyDown" => ret = Some(service.filter_key_down(&KeyEvent::from_msg(msg)?)?),
        "onKeyDown" => ret = Some(service.on_key_down(&KeyEvent::from_msg(msg)?)?),
        "filterKeyUp" => ret = Some(service.filter_key_up(&KeyEvent::from_msg(msg)?)?),
        "onKeyUp" => ret = service.on_key_up(&KeyEvent::from_msg(msg)?)?,
        "onPreservedKey" => {
            let guid = field("guid")?;
            let guid = guid.as_str().ok_or("AttributeError: guid")?.to_lowercase();
            ret = Some(service.on_preserved_key(&guid)?);
        }
        "onCommand" => {
            let id = field("id")?;
            let kind = field("type")?;
            service.on_command(&id, &kind)?;
        }
        "onMenu" => {
            let id = field("id")?;
            ret = service.on_menu(&id)?;
        }
        "onCompartmentChanged" => {
            let guid = field("guid")?;
            service.on_compartment_changed(&guid.as_str().ok_or("AttributeError: guid")?.to_lowercase());
        }
        "onKeyboardStatusChanged" => {
            let opened = truthy(Some(&field("opened")?));
            service.on_keyboard_status_changed(opened)?;
        }
        "onCompositionTerminated" => {
            let forced = truthy(Some(&field("forced")?));
            service.on_composition_terminated(forced)?;
        }
        "onKillFocus" => service.on_kill_focus()?,
        "onActivate" => {
            service.ts().is_activated = true;
            service.ts().keyboard_open = truthy(Some(&field("isKeyboardOpen")?));
            service.on_activate()?;
        }
        "onDeactivate" => {
            service.on_deactivate()?;
            service.ts().is_activated = false;
        }
        "ping" => {}
        _ => success = false,
    }

    let mut reply = std::mem::take(&mut service.ts().current_reply);
    if let Some(r) = ret {
        reply.insert("return".into(), r);
    }
    reply.insert("success".into(), json!(success));
    reply.insert("seqNum".into(), seq_num);
    Ok(reply)
}
