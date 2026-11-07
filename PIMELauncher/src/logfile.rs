//! The background log: %LOCALAPPDATA%\PIME\PIMELauncher.log.
//!
//! In background mode (no /console) tracing used to go to a sink, so a backend
//! that was killed as hung, restarted, or that wrote ERROR lines left no trace;
//! the DLL's PIMETextService.log then showed keys timing out with no reason.
//! Warnings and errors from both the watchdog and the worker process are
//! appended here; the file starts over once it exceeds 1 MB.

use std::fs::{File, OpenOptions};
use std::io::{self, Write};
use std::path::PathBuf;
use tracing_subscriber::fmt::MakeWriter;

pub const MAX_BYTES: u64 = 1024 * 1024;

#[derive(Clone)]
pub struct LogFile {
    path: PathBuf,
}

impl LogFile {
    /// None when LOCALAPPDATA is not set (nowhere to write).
    pub fn default_location() -> Option<LogFile> {
        let base = std::env::var_os("LOCALAPPDATA")?;
        Some(LogFile::at(PathBuf::from(base).join("PIME").join("PIMELauncher.log")))
    }

    pub fn at(path: PathBuf) -> LogFile {
        LogFile { path }
    }

    pub fn path(&self) -> &PathBuf {
        &self.path
    }

    fn open(&self) -> io::Result<File> {
        if let Some(dir) = self.path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let start_over = std::fs::metadata(&self.path).map(|m| m.len() > MAX_BYTES).unwrap_or(false);
        OpenOptions::new().create(true).append(!start_over).write(true).truncate(start_over).open(&self.path)
    }
}

/// Opens the file per write (one line per tracing event), so two processes
/// appending at once stay consistent and a deleted file is simply recreated.
pub struct LogWriter(LogFile);

impl Write for LogWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        // a failure to log must never fail the launcher
        if let Ok(mut file) = self.0.open() {
            let _ = file.write_all(buf);
        }
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

impl<'a> MakeWriter<'a> for LogFile {
    type Writer = LogWriter;

    fn make_writer(&'a self) -> LogWriter {
        LogWriter(self.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn appends_lines_and_starts_over_past_the_limit() {
        let dir = tempfile::tempdir().unwrap();
        let log = LogFile::at(dir.path().join("sub").join("PIMELauncher.log"));
        let mut w = log.make_writer();
        w.write_all(b"first\n").unwrap();
        w.write_all(b"second\n").unwrap();
        assert_eq!(std::fs::read_to_string(log.path()).unwrap(), "first\nsecond\n");

        std::fs::write(log.path(), vec![b'x'; MAX_BYTES as usize + 1]).unwrap();
        w.write_all(b"after\n").unwrap();
        assert_eq!(std::fs::read_to_string(log.path()).unwrap(), "after\n");
    }

    #[test]
    fn an_unwritable_location_is_not_an_error() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("a-file");
        std::fs::write(&file, "").unwrap();
        // the parent of the log path is a file, so the directory cannot be created
        let log = LogFile::at(file.join("PIMELauncher.log"));
        assert_eq!(log.make_writer().write(b"x").unwrap(), 1);
    }
}
