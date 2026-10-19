//! The WIME input methods (大易, 酷倉, 新酷音) as a library shared by the two
//! executables of this crate:
//! - `wime-cinbase.exe` (src/main.rs): the backend process for PIMELauncher,
//!   a port of python/server.py, the cinbase package and input_methods/chewing;
//! - `wime-config.exe` (src/bin/wime-config.rs): the settings tools, a port of
//!   python/cinbase/configtool.py, python/input_methods/chewing/config_tool.py
//!   and python/config_server.py (module `configtool`).

#![allow(dead_code)] // the port is filled in module by module

pub mod backend;
pub mod candidate_theme;
pub mod chewing;
pub mod cin;
pub mod cinbase;
pub mod config;
pub mod configtool;
pub mod data;
pub mod env;
#[doc(hidden)]
pub mod fuzz;
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
