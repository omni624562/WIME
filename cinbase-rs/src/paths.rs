//! Where the shared data lives. The Rust backend uses the same files as the
//! Python one (tables, data files, icons, shipped configs, the settings tool),
//! found under the PIME `python` directory:
//! - `WIME_PY_DIR` if set,
//! - else `<exe dir>\..\python` (installed next to the python directory),
//! - else the current directory if it looks like it (the harness runs backends
//!   with the repo's python directory as working directory).

use std::path::PathBuf;
use std::sync::OnceLock;

pub fn python_dir() -> &'static PathBuf {
    static DIR: OnceLock<PathBuf> = OnceLock::new();
    DIR.get_or_init(|| {
        if let Ok(dir) = std::env::var("WIME_PY_DIR") {
            if !dir.is_empty() {
                return PathBuf::from(dir);
            }
        }
        if let Ok(exe) = std::env::current_exe() {
            if let Some(parent) = exe.parent().and_then(|p| p.parent()) {
                let candidate = parent.join("python");
                if candidate.join("cinbase").is_dir() {
                    return candidate;
                }
            }
        }
        std::env::current_dir().unwrap_or_default()
    })
}

/// python/cinbase (CinBase.cinbasecurdir)
pub fn cinbase_dir() -> PathBuf {
    python_dir().join("cinbase")
}

/// python/cinbase/data (CinBaseConfig.getDataDir)
pub fn data_dir() -> PathBuf {
    cinbase_dir().join("data")
}

/// python/cinbase/json (CinBaseConfig.getJsonDir)
pub fn json_dir() -> PathBuf {
    cinbase_dir().join("json")
}

/// python/cinbase/icons
pub fn icon_dir() -> PathBuf {
    cinbase_dir().join("icons")
}

/// python/input_methods/<ime>/config (CinBaseConfig.getDefaultConfigDir)
pub fn default_config_dir(ime_dir_name: &str) -> PathBuf {
    python_dir().join("input_methods").join(ime_dir_name).join("config")
}

/// %APPDATA%\PIME\<ime>, created if missing (CinBaseConfig.getConfigDir)
pub fn config_dir(ime_dir_name: &str) -> PathBuf {
    let appdata = std::env::var("APPDATA").unwrap_or_default();
    let dir = PathBuf::from(appdata).join("PIME").join(ime_dir_name);
    let _ = std::fs::create_dir_all(&dir);
    dir
}

/// Python's os.path.join for display / launch strings: a backslash separator.
pub fn join_str(dir: &std::path::Path, name: &str) -> String {
    dir.join(name).to_string_lossy().into_owned()
}
