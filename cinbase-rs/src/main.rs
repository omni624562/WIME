//! wime-cinbase: WIME's input methods (大易 and 酷倉 on the table-based
//! cinbase core, 新酷音 on libchewing) as a backend process for PIMELauncher,
//! a port of python/server.py, the cinbase package and input_methods/chewing.
//! The goal of the port is identical replies: every change is checked with
//! tests/diffharness against the Python backend.
//!
//! Protocol (one request per line, like server.py):
//!   stdin  "<client_id>|<JSON request>"
//!   stdout "PIME_MSG|<client_id>|<JSON reply>"

use wime::backend::{handle_line, Clients};

use serde_json::Value;
use std::io::{self, BufRead, Write};
use std::panic::{self, AssertUnwindSafe};

fn main() {
    // a panic in one request is reported like a Python exception: the request
    // gets {"success":false} and the backend keeps serving the other clients
    panic::set_hook(Box::new(|info| eprintln!("ERROR: {}", info)));
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut clients = Clients::new();
    if std::env::args().any(|arg| arg == "--preload") {
        // a failure here only means the first real client loads the tables itself
        let _ = panic::catch_unwind(AssertUnwindSafe(|| wime::backend::preload(&mut clients)));
        clients.clear();
    }
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
