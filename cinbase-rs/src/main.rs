//! wime-cinbase: WIME's table-based input methods (大易; 酷倉 later) as a
//! backend process for PIMELauncher, a port of python/server.py and the
//! cinbase package. The goal of the port is identical replies: every change is
//! checked with tests/diffharness against the Python backend.
//!
//! Protocol (one request per line, like server.py):
//!   stdin  "<client_id>|<JSON request>"
//!   stdout "PIME_MSG|<client_id>|<JSON reply>"

#![allow(dead_code)] // the port is filled in module by module

mod data;
mod env;
mod keycodes;
mod paths;
mod textservice;

use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::io::{self, BufRead, Write};
use std::panic::{self, AssertUnwindSafe};
use textservice::Service;

/// Creates the text service for a language profile GUID (serviceManager.py).
fn create_service(_guid: &str, _client: &ClientInfo) -> Option<Box<dyn Service>> {
    None
}

/// What server.py's Client keeps from the init request.
#[derive(Debug, Clone, Default)]
pub struct ClientInfo {
    pub guid: String,
    pub is_windows8_above: bool,
    pub is_metro_app: bool,
    pub is_ui_less: bool,
    pub is_console: bool,
}

struct Client {
    service: Option<Box<dyn Service>>,
}

fn flag(msg: &Map<String, Value>, name: &str) -> Result<bool, String> {
    match msg.get(name) {
        None => Err(format!("KeyError: '{}'", name)),
        Some(Value::Bool(b)) => Ok(*b),
        Some(Value::Number(n)) => Ok(n.as_f64().unwrap_or(0.0) != 0.0),
        Some(Value::Null) => Ok(false),
        Some(Value::String(s)) => Ok(!s.is_empty()),
        Some(_) => Ok(true),
    }
}

impl Client {
    fn init(&mut self, msg: &Map<String, Value>) -> Result<bool, String> {
        let info = ClientInfo {
            guid: msg.get("id").and_then(|v| v.as_str()).ok_or("KeyError: 'id'")?.to_string(),
            is_windows8_above: flag(msg, "isWindows8Above")?,
            is_metro_app: flag(msg, "isMetroApp")?,
            is_ui_less: flag(msg, "isUiLess")?,
            is_console: flag(msg, "isConsole")?,
        };
        self.service = create_service(&info.guid.to_lowercase(), &info);
        Ok(self.service.is_some())
    }

    fn handle_request(&mut self, msg: &Map<String, Value>) -> Result<Map<String, Value>, String> {
        if let Some(service) = self.service.as_mut() {
            return textservice::handle_request(service.as_mut(), msg);
        }
        let mut reply = Map::new();
        reply.insert("seqNum".into(), msg.get("seqNum").cloned().unwrap_or(json!(0)));
        let success = if msg.get("method").and_then(|m| m.as_str()) == Some("init") {
            self.init(msg)?
        } else {
            false
        };
        reply.insert("success".into(), json!(success));
        Ok(reply)
    }
}

fn handle_line(clients: &mut HashMap<String, Client>, client_id: &str, msg_text: &str) -> Result<Option<Map<String, Value>>, String> {
    let value: Value = serde_json::from_str(msg_text).map_err(|e| e.to_string())?;
    let msg = match value {
        Value::Object(m) => m,
        _ => return Err("request is not a JSON object".into()),
    };
    let client = clients.entry(client_id.to_string()).or_insert_with(|| {
        eprintln!("new client: {}", client_id);
        Client { service: None }
    });
    let method = msg.get("method").and_then(|m| m.as_str()).unwrap_or("");
    if method == "close" {
        eprintln!("client disconnected: {}", client_id);
        clients.remove(client_id);
        return Ok(None);
    }
    if method == "__advanceClock" && env::test_mode() {
        env::advance_clock(msg.get("seconds").and_then(|s| s.as_f64()).unwrap_or(0.0));
        let mut reply = Map::new();
        reply.insert("seqNum".into(), msg.get("seqNum").cloned().unwrap_or(json!(0)));
        reply.insert("success".into(), json!(true));
        return Ok(Some(reply));
    }
    env::begin_request();
    let mut reply = client.handle_request(&msg)?;
    let (launches, sounds) = env::take_side_effects();
    if !launches.is_empty() {
        reply.insert("_testLaunches".into(), json!(launches.iter().map(|(a, b)| json!([a, b])).collect::<Vec<_>>()));
    }
    if !sounds.is_empty() {
        reply.insert("_testSounds".into(), json!(sounds));
    }
    Ok(Some(reply))
}

fn main() {
    // a panic in one request is reported like a Python exception: the request
    // gets {"success":false} and the backend keeps serving the other clients
    panic::set_hook(Box::new(|info| eprintln!("ERROR: {}", info)));
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut clients: HashMap<String, Client> = HashMap::new();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let Some((client_id, msg_text)) = line.split_once('|') else {
            eprintln!("ERROR: malformed request: {}", line);
            continue;
        };
        let result = panic::catch_unwind(AssertUnwindSafe(|| handle_line(&mut clients, client_id, msg_text)));
        let reply_text = match result {
            Ok(Ok(None)) => continue,
            Ok(Ok(Some(reply))) => serde_json::to_string(&Value::Object(reply)).unwrap_or_else(|_| "{\"success\":false}".into()),
            Ok(Err(e)) => {
                eprintln!("ERROR: {} {}", e, line);
                "{\"success\":false}".into()
            }
            Err(_) => "{\"success\":false}".into(),
        };
        let mut out = stdout.lock();
        let _ = writeln!(out, "PIME_MSG|{}|{}", client_id, reply_text);
        let _ = out.flush();
    }
}
