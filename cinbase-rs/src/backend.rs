//! The request dispatch of wime-cinbase.exe (src/main.rs), a port of
//! python/server.py: one `Clients` table per process, `handle_line` for each
//! "<client_id>|<JSON request>" line. In the library so the fuzz targets
//! (src/fuzz.rs) drive exactly what the backend runs.

use crate::{chewing, cinbase, env, textservice, ClientInfo};

use serde_json::{json, Map, Value};
use std::collections::HashMap;
use textservice::Service;

/// Creates the text service for a language profile GUID (serviceManager.py).
/// Err: the service's constructor raised (init answers success:false).
fn create_service(guid: &str, client: &ClientInfo) -> Result<Option<Box<dyn Service>>, String> {
    if guid == chewing::CHEWING_GUID {
        return Ok(Some(Box::new(chewing::ChewingService::new(client.clone()))));
    }
    cinbase::create_service(guid, client)
}

pub struct Client {
    service: Option<Box<dyn Service>>,
}

/// The connected clients, by client id.
pub type Clients = HashMap<String, Client>;

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
        self.service = create_service(&info.guid.to_lowercase(), &info)?;
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

/// One request. Ok(None): no reply (the client closed).
pub fn handle_line(clients: &mut Clients, client_id: &str, msg_text: &str) -> Result<Option<Map<String, Value>>, String> {
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
