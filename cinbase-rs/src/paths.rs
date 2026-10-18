//! Where WIME's runtime files live -- the ONE place that knows the layout
//! (configtool/assets.rs and config.rs only call the helpers below).
//!
//! Installed (no Python since 1.3.0-beta18):
//!
//! ```text
//! <PIME>\                          PIMELauncher.exe, backends.json, version.txt
//! <PIME>\cinbase_rs\               wime-cinbase.exe (backend), wime-config.exe (settings)
//! <PIME>\cinbase_rs\input_methods\<ime>\ime.json, icon.ico   (language profiles)
//! <PIME>\data\                     the data root: tables, data files, icons, pages
//! ```
//!
//! The data root has the same sub-layout as the repo's `python` folder (only
//! the data files are installed, no code), so the repo itself is a complete
//! data root for development and tests, and the Python reference
//! implementation reads exactly the same relative paths:
//!
//! | what                                   | under the data root                   |
//! |----------------------------------------|---------------------------------------|
//! | cinbase tables (*.json)                | cinbase\json                          |
//! | cinbase default data files             | cinbase\data                          |
//! | cinbase language-bar icons             | cinbase\icons                         |
//! | 大易/酷倉 shared pages, css, js, fonts  | cinbase\config                        |
//! | 大易/酷倉 shipped config, page, config.js| input_methods\<ime>\config            |
//! | 大易/酷倉 icon.ico (settings page)      | input_methods\<ime>                   |
//! | 新酷音 pages, css, images, js, icons    | input_methods\chewing                 |
//! | libchewing tsi/word/symbols/swkb.dat   | libchewing\data                       |
//! | version.txt                            | the data root's parent (<PIME>)       |
//!
//! data_root() is, in this order:
//! - `WIME_DATA_DIR` (or the older name `WIME_PY_DIR`, used by the tests) if set,
//! - `<exe dir>\..\data` if it exists (installed),
//! - the first ancestor of the exe's folder with a `python\cinbase` folder:
//!   the repo's `python` (a cargo build in cinbase-rs\target\...),
//! - else the current directory.

use std::path::{Path, PathBuf};
use std::sync::OnceLock;

/// The settings tool next to the backend (cinbase_rs\wime-config.exe).
pub const CONFIG_TOOL_EXE: &str = "wime-config.exe";

fn find_data_root(env_dir: Option<String>, exe: Option<PathBuf>, cwd: PathBuf) -> PathBuf {
    if let Some(dir) = env_dir.filter(|d| !d.is_empty()) {
        return PathBuf::from(dir);
    }
    if let Some(exe_dir) = exe.as_deref().and_then(Path::parent) {
        if let Some(pime) = exe_dir.parent() {
            let installed = pime.join("data");
            if installed.is_dir() {
                return installed;
            }
        }
        for dir in exe_dir.ancestors() {
            let repo = dir.join("python");
            if repo.join("cinbase").is_dir() {
                return repo;
            }
        }
    }
    cwd
}

pub fn data_root() -> &'static PathBuf {
    static DIR: OnceLock<PathBuf> = OnceLock::new();
    DIR.get_or_init(|| {
        let env_dir = std::env::var("WIME_DATA_DIR").ok().filter(|d| !d.is_empty()).or_else(|| std::env::var("WIME_PY_DIR").ok());
        find_data_root(env_dir, std::env::current_exe().ok(), std::env::current_dir().unwrap_or_default())
    })
}

// -- the layout under a data root (injectable for tests) ------------------------

/// <root>\cinbase (CinBase.cinbasecurdir)
pub fn cinbase_dir_in(root: &Path) -> PathBuf {
    root.join("cinbase")
}

/// <root>\cinbase\data (CinBaseConfig.getDataDir)
pub fn data_dir_in(root: &Path) -> PathBuf {
    cinbase_dir_in(root).join("data")
}

/// <root>\cinbase\json (CinBaseConfig.getJsonDir)
pub fn json_dir_in(root: &Path) -> PathBuf {
    cinbase_dir_in(root).join("json")
}

/// <root>\cinbase\cin (CinBaseConfig.getCinDir; not installed)
pub fn cin_dir_in(root: &Path) -> PathBuf {
    cinbase_dir_in(root).join("cin")
}

/// <root>\cinbase\config: the 大易/酷倉 shared pages, css, fonts, images, js
pub fn cinbase_pages_dir_in(root: &Path) -> PathBuf {
    cinbase_dir_in(root).join("config")
}

/// <root>\input_methods\<ime>: icon.ico for the settings page; 新酷音's pages and icons
pub fn ime_dir_in(root: &Path, ime: &str) -> PathBuf {
    root.join("input_methods").join(ime)
}

/// <root>\input_methods\<ime>\config (CinBaseConfig.getDefaultConfigDir)
pub fn default_config_dir_in(root: &Path, ime: &str) -> PathBuf {
    ime_dir_in(root, ime).join("config")
}

/// <root>\libchewing\data (libchewing.CHEWING_DATA_DIR)
pub fn chewing_data_dir_in(root: &Path) -> PathBuf {
    root.join("libchewing").join("data")
}

/// version.txt's folder: <root>\.. (the PIME folder, or the repo root)
pub fn version_dir_in(root: &Path) -> PathBuf {
    root.join("..")
}

// -- the same for the data root of this process ---------------------------------

/// python/cinbase (CinBase.cinbasecurdir)
pub fn cinbase_dir() -> PathBuf {
    cinbase_dir_in(data_root())
}

/// python/cinbase/data (CinBaseConfig.getDataDir)
pub fn data_dir() -> PathBuf {
    data_dir_in(data_root())
}

/// python/cinbase/json (CinBaseConfig.getJsonDir)
pub fn json_dir() -> PathBuf {
    json_dir_in(data_root())
}

/// python/cinbase/icons
pub fn icon_dir() -> PathBuf {
    cinbase_dir().join("icons")
}

/// python/input_methods/<ime>/config (CinBaseConfig.getDefaultConfigDir)
pub fn default_config_dir(ime_dir_name: &str) -> PathBuf {
    default_config_dir_in(data_root(), ime_dir_name)
}

/// python/input_methods/chewing (ChewingTextService.curdir: icons\)
pub fn chewing_dir() -> PathBuf {
    ime_dir_in(data_root(), "chewing")
}

/// python/libchewing/data (libchewing.CHEWING_DATA_DIR)
pub fn chewing_data_dir() -> PathBuf {
    chewing_data_dir_in(data_root())
}

/// %APPDATA%\PIME\<ime>, created if missing (CinBaseConfig.getConfigDir)
pub fn config_dir(ime_dir_name: &str) -> PathBuf {
    let appdata = std::env::var("APPDATA").unwrap_or_default();
    let dir = PathBuf::from(appdata).join("PIME").join(ime_dir_name);
    let _ = std::fs::create_dir_all(&dir);
    dir
}

// -- the settings tool ------------------------------------------------------------

/// wime-config.exe in the folder of `exe` (the running backend).
pub fn config_tool_exe_beside(exe: &Path) -> PathBuf {
    exe.parent().map(|dir| dir.join(CONFIG_TOOL_EXE)).unwrap_or_else(|| PathBuf::from(CONFIG_TOOL_EXE))
}

/// What the backends run for the settings menu items: (program, parameters,
/// working directory). The Python backends ran `python.exe "<configtool.py>"
/// config <ime>` and `python.exe "<config_tool.py>" <config_tool|user_phrase_editor>`;
/// wime-config.exe takes `<config|user_phrase_editor> <ime>` (the same argv as
/// the Start-menu shortcuts and ime.json's configToolParams).
pub fn config_tool_command(tool: &str, ime: &str) -> (String, String, String) {
    let exe = config_tool_exe_beside(&std::env::current_exe().unwrap_or_default());
    let dir = exe.parent().map(|d| d.to_string_lossy().into_owned()).unwrap_or_default();
    (exe.to_string_lossy().into_owned(), format!("{} {}", tool, ime), dir)
}

/// Python's os.path.join for display / launch strings: a backslash separator.
pub fn join_str(dir: &std::path::Path, name: &str) -> String {
    dir.join(name).to_string_lossy().into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("wime-paths-{}-{}", std::process::id(), name));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn env_wins() {
        let root = find_data_root(Some(r"C:\x\data".into()), Some(PathBuf::from(r"C:\PIME\cinbase_rs\wime-cinbase.exe")), PathBuf::from(r"C:\cwd"));
        assert_eq!(root, PathBuf::from(r"C:\x\data"));
    }

    #[test]
    fn installed_layout_uses_the_data_folder() {
        let pime = temp("installed");
        std::fs::create_dir_all(pime.join("cinbase_rs")).unwrap();
        std::fs::create_dir_all(pime.join("data")).unwrap();
        // a python tree an old version left behind is never used
        std::fs::create_dir_all(pime.join("python").join("cinbase")).unwrap();
        let root = find_data_root(None, Some(pime.join("cinbase_rs").join("wime-cinbase.exe")), PathBuf::from(r"C:\cwd"));
        assert_eq!(root, pime.join("data"));
        let _ = std::fs::remove_dir_all(&pime);
    }

    #[test]
    fn repo_build_uses_the_repo_python_folder() {
        let repo = temp("repo");
        let release = repo.join("cinbase-rs").join("target").join("i686-pc-windows-msvc").join("release");
        std::fs::create_dir_all(&release).unwrap();
        std::fs::create_dir_all(repo.join("python").join("cinbase")).unwrap();
        let root = find_data_root(None, Some(release.join("wime-cinbase.exe")), PathBuf::from(r"C:\cwd"));
        assert_eq!(root, repo.join("python"));
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn falls_back_to_the_current_directory() {
        let empty = temp("empty");
        let root = find_data_root(None, Some(empty.join("wime-cinbase.exe")), PathBuf::from(r"C:\cwd"));
        assert_eq!(root, PathBuf::from(r"C:\cwd"));
        let _ = std::fs::remove_dir_all(&empty);
    }

    #[test]
    fn installed_paths() {
        let root = Path::new(r"C:\PIME\data");
        assert_eq!(json_dir_in(root), Path::new(r"C:\PIME\data\cinbase\json"));
        assert_eq!(data_dir_in(root), Path::new(r"C:\PIME\data\cinbase\data"));
        assert_eq!(cinbase_pages_dir_in(root), Path::new(r"C:\PIME\data\cinbase\config"));
        assert_eq!(default_config_dir_in(root, "chedayi"), Path::new(r"C:\PIME\data\input_methods\chedayi\config"));
        assert_eq!(chewing_data_dir_in(root), Path::new(r"C:\PIME\data\libchewing\data"));
        assert_eq!(version_dir_in(root).join("version.txt"), Path::new(r"C:\PIME\data\..\version.txt"));
    }

    #[test]
    fn settings_tool_is_beside_the_backend() {
        assert_eq!(config_tool_exe_beside(Path::new(r"C:\PIME\cinbase_rs\wime-cinbase.exe")),
                   Path::new(r"C:\PIME\cinbase_rs\wime-config.exe"));
        let (exe, params, dir) = config_tool_command("config", "chedayi");
        assert!(exe.ends_with(r"\wime-config.exe"), "{}", exe);
        assert_eq!(params, "config chedayi");
        assert_eq!(Path::new(&exe).parent().unwrap(), Path::new(&dir));
        assert_eq!(config_tool_command("user_phrase_editor", "chewing").1, "user_phrase_editor chewing");
    }
}
