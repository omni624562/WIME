//! wime-config.exe: the settings tools, a port of python/config_server.py,
//! python/cinbase/configtool.py (大易/酷倉) and
//! python/input_methods/chewing/config_tool.py (新酷音). The web pages are the
//! same files the Python tools serve (see assets.rs); every endpoint answers
//! like the Python tool (tests/test_config_server.py and
//! tests/test_chewing_config_tool.py run against both).
//!
//! Usage, like `configtool.py <tool> <ime>`:
//!   wime-config.exe config chedayi            大易 settings
//!   wime-config.exe config checj              酷倉 settings
//!   wime-config.exe config chewing            新酷音 settings (config_tool)
//!   wime-config.exe user_phrase_editor chewing  新酷音 user phrase editor

pub mod assets;
pub mod chewing_tool;
pub mod cinbase_tool;
pub mod multipart;
pub mod pyjson;
pub mod server;

use std::io::Write;
use std::path::Path;

/// save_file: write `text` through a temporary file (text mode: "\n" becomes
/// "\r\n", UTF-8), optionally fsynced, then os.replace() it over the target.
/// On failure the temporary file is removed and the error returned.
pub fn save_text_file(target: &Path, text: &str, fsync: bool) -> std::io::Result<()> {
    let tmp = crate::chewing::userdict::temp_path_for(target);
    let result = (|| -> std::io::Result<()> {
        let mut f = std::fs::File::create(&tmp)?;
        f.write_all(text.replace('\n', "\r\n").as_bytes())?;
        f.flush()?;
        if fsync {
            f.sync_all()?;
        }
        drop(f);
        crate::chewing::userdict::replace_file(&tmp, target)
    })();
    if result.is_err() && tmp.exists() {
        let _ = std::fs::remove_file(&tmp);
    }
    result
}

/// The entry point of wime-config.exe; returns the exit code on a usage error
/// (the server itself exits the process).
pub fn main(args: &[String]) -> i32 {
    let (Some(tool_arg), Some(ime)) = (args.get(1), args.get(2)) else {
        server::log("usage: wime-config.exe <config|user_phrase_editor> <ime directory name, or chewing>");
        return 2;
    };
    let assets = assets::Assets::from_env();
    let editor = tool_arg == "user_phrase_editor";
    if ime == "chewing" {
        let tool_name = if editor { "user_phrase_editor" } else { "config_tool" };
        server::App::new(Box::new(chewing_tool::ChewingTool::new(assets))).run(tool_name)
    } else {
        let tool_name = if editor { "user_phrase_editor" } else { "config" };
        server::App::new(Box::new(cinbase_tool::CinbaseTool::new(ime, assets))).run(tool_name)
    }
}
