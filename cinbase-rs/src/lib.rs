//! The WIME input methods (大易, 酷倉, 新酷音) as a library, so that more than one
//! executable can use them. `wime-cinbase.exe` (src/main.rs) is the backend process
//! for PIMELauncher, a port of python/server.py, the cinbase package and
//! input_methods/chewing.

#![allow(dead_code)] // the port is filled in module by module

pub mod candidate_theme;
pub mod chewing;
pub mod cin;
pub mod cinbase;
pub mod config;
pub mod data;
pub mod env;
pub mod hcin;
pub mod keycodes;
pub mod pager;
pub mod paths;
pub mod rcin;
pub mod textservice;

/// What server.py's Client keeps from the init request.
#[derive(Debug, Clone, Default)]
pub struct ClientInfo {
    pub guid: String,
    pub is_windows8_above: bool,
    pub is_metro_app: bool,
    pub is_ui_less: bool,
    pub is_console: bool,
}
