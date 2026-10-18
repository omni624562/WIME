//! Port of python/libchewing/userdict.py (UD:<line>): converting the user
//! phrase dictionary of the old C libchewing (chewing.sqlite3) to the
//! chewing.dat of libchewing 0.13, without ever touching the old file:
//!
//! 1. the old file is backed up as chewing-backup-before-0.13.sqlite3 (an
//!    existing backup is kept);
//! 2. a consistent copy (SQLite backup API) goes to a work directory inside the
//!    config directory, minus the phrases that are not valid UTF-8;
//! 3. libchewing converts the copy into work_dir\chewing.dat (and writes it
//!    when the context is closed);
//! 4. the new file is reopened to check it holds phrases;
//! 5. it is renamed into the config directory, never over an existing file.
//!
//! A failure leaves no chewing.dat behind, so the caller falls back to an
//! in-memory dictionary instead of letting libchewing convert (and modify) the
//! old file itself.

use super::engine::ChewingContext;
use rusqlite::{Connection, OpenFlags};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const USER_DICT_NAME: &str = "chewing.dat";
pub const LEGACY_DB_NAME: &str = "chewing.sqlite3";
pub const LEGACY_BACKUP_NAME: &str = "chewing-backup-before-0.13.sqlite3";
pub const CHANGE_STAMP_NAME: &str = "chewing-userphrase.stamp";

/// UD:52 USER_PHRASE_V1_COLUMNS
fn user_phrase_v1_columns() -> Vec<String> {
    let mut cols: Vec<String> = ["time", "user_freq", "max_freq", "orig_freq", "length", "phrase"].iter().map(|s| s.to_string()).collect();
    cols.extend((0..11).map(|i| format!("phone_{}", i)));
    cols
}

/// UserDictionaryError / ChewingError, as the message Python prints
pub type DictError = String;

pub fn user_dict_path(config_dir: &Path) -> PathBuf {
    config_dir.join(USER_DICT_NAME)
}

pub fn legacy_db_path(config_dir: &Path) -> PathBuf {
    config_dir.join(LEGACY_DB_NAME)
}

fn sql_err(e: rusqlite::Error) -> String {
    e.to_string()
}

/// sqlite3.connect(path): read-write, created when missing
fn connect(path: &Path) -> rusqlite::Result<Connection> {
    Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_CREATE | OpenFlags::SQLITE_OPEN_URI)
}

/// UD:83 _copySqlite: a consistent snapshot through the backup API
fn copy_sqlite(src: &Path, dst: &Path) -> rusqlite::Result<()> {
    let source = connect(src)?;
    source.busy_timeout(Duration::from_secs(5))?;
    let mut target = connect(dst)?;
    {
        let backup = rusqlite::backup::Backup::new(&source, &mut target)?;
        // source.backup(target): every page in one step
        loop {
            match backup.step(-1)? {
                rusqlite::backup::StepResult::Done => break,
                rusqlite::backup::StepResult::More => continue,
                rusqlite::backup::StepResult::Busy | rusqlite::backup::StepResult::Locked => {
                    std::thread::sleep(Duration::from_millis(100));
                }
                _ => break,
            }
        }
    }
    Ok(())
}

fn table_names(conn: &Connection) -> rusqlite::Result<Vec<String>> {
    let mut stmt = conn.prepare("SELECT name FROM sqlite_master WHERE type='table'")?;
    let names = stmt.query_map([], |row| row.get::<_, String>(0))?.collect::<rusqlite::Result<Vec<_>>>()?;
    Ok(names)
}

/// UD:89 checkSqliteUserDb: the number of phrases to convert
pub fn check_sqlite_user_db(path: &Path) -> Result<i64, DictError> {
    let invalid = |e: rusqlite::Error| format!("not a valid SQLite database: {}", e);
    let conn = connect(path).map_err(invalid)?;
    let integrity: String = conn.query_row("PRAGMA integrity_check", [], |r| r.get(0)).map_err(invalid)?;
    if integrity != "ok" {
        return Err("integrity check failed".into());
    }
    let tables = table_names(&conn).map_err(invalid)?;
    if tables.iter().any(|t| t == "dictionary_v1") {
        return conn.query_row("SELECT count(*) FROM dictionary_v1", [], |r| r.get(0)).map_err(invalid);
    }
    if !(tables.iter().any(|t| t == "userphrase_v1") && tables.iter().any(|t| t == "config_v1")) {
        return Err("not a libchewing user phrase database".into());
    }
    let columns: Vec<String> = {
        let mut stmt = conn.prepare("PRAGMA table_info(userphrase_v1)").map_err(invalid)?;
        let cols = stmt.query_map([], |r| r.get::<_, String>(1)).map_err(invalid)?.collect::<rusqlite::Result<Vec<_>>>().map_err(invalid)?;
        cols
    };
    if !user_phrase_v1_columns().iter().all(|c| columns.contains(c)) {
        return Err("unexpected userphrase_v1 columns".into());
    }
    conn.query_row("SELECT count(*) FROM userphrase_v1", [], |r| r.get(0)).map_err(invalid)
}

/// UD:111 _dropInvalidPhrases: the number of phrases left
fn drop_invalid_phrases(path: &Path) -> rusqlite::Result<i64> {
    let conn = connect(path)?;
    let tables = table_names(&conn)?;
    let table = if tables.iter().any(|t| t == "dictionary_v1") { "dictionary_v1" } else { "userphrase_v1" };
    let mut bad: Vec<Vec<u8>> = Vec::new();
    {
        let mut stmt = conn.prepare(&format!("SELECT CAST(phrase AS BLOB) FROM {}", table))?;
        let rows = stmt.query_map([], |r| r.get::<_, Option<Vec<u8>>>(0))?;
        for phrase in rows {
            let phrase = phrase?;
            let bytes = phrase.clone().unwrap_or_default();
            if std::str::from_utf8(&bytes).is_err() && !bad.contains(&bytes) {
                bad.push(bytes);
            }
        }
    }
    if !bad.is_empty() {
        let sql = format!("DELETE FROM {} WHERE CAST(phrase AS BLOB) = ?", table);
        let tx = conn.unchecked_transaction()?;
        for p in &bad {
            tx.execute(&sql, [p])?;
        }
        tx.commit()?;
    }
    conn.query_row(&format!("SELECT count(*) FROM {}", table), [], |r| r.get(0))
}

/// UD:129 countPhrases: open dat_path with libchewing and count its phrases
pub fn count_phrases(dat_path: &Path, syspath: &str) -> Result<usize, DictError> {
    let abs = std::path::absolute(dat_path).unwrap_or_else(|_| dat_path.to_path_buf());
    let userdir = abs.parent().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default();
    let mut ctx = ChewingContext::new(syspath, &dat_path.to_string_lossy(), Some(&userdir), true)?;
    Ok(ctx.user_phrases().len())
}

/// UD:142 convertSqlite: work_dir\chewing.dat converted from sqlite_path
pub fn convert_sqlite(sqlite_path: &Path, work_dir: &Path, syspath: &str) -> Result<PathBuf, DictError> {
    let expected = check_sqlite_user_db(sqlite_path)?;
    let copy = work_dir.join(LEGACY_DB_NAME); // libchewing only knows this name
    copy_sqlite(sqlite_path, &copy).map_err(|e| format!("cannot copy {}: {}", sqlite_path.display(), e))?;
    let remaining = drop_invalid_phrases(&copy).map_err(sql_err)?;
    let dat = work_dir.join(USER_DICT_NAME);
    // no log callback (it makes the conversion quadratic); checked below instead
    let ctx = ChewingContext::new(syspath, &dat.to_string_lossy(), Some(&work_dir.to_string_lossy()), false)?;
    drop(ctx); // writes the file
    let count = count_phrases(&dat, syspath)?;
    if remaining != 0 && count == 0 {
        return Err(format!("converted {} but no phrase was imported ({} expected)", sqlite_path.display(), expected));
    }
    Ok(dat)
}

/// UD:162 _makeWorkDir: tempfile.mkdtemp(prefix=prefix, dir=config_dir)
fn make_work_dir(config_dir: &Path, prefix: &str) -> std::io::Result<PathBuf> {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    const CHARS: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789_";
    let seed = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos() as u64).unwrap_or(0)
        ^ ((std::process::id() as u64) << 32);
    for _ in 0..100 {
        let mut x = seed.wrapping_add(COUNTER.fetch_add(1, Ordering::Relaxed).wrapping_mul(0x9E37_79B9_7F4A_7C15));
        let mut name = String::from(prefix);
        for _ in 0..8 {
            x ^= x << 13;
            x ^= x >> 7;
            x ^= x << 17;
            name.push(CHARS[(x % CHARS.len() as u64) as usize] as char);
        }
        let dir = config_dir.join(name);
        match fs::create_dir(&dir) {
            Ok(()) => return Ok(dir),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e),
        }
    }
    Err(std::io::Error::new(std::io::ErrorKind::AlreadyExists, "No usable temporary directory name found"))
}

/// os.rename(src, dst) on Windows: fails when dst exists
pub fn rename_no_replace(src: &Path, dst: &Path) -> std::io::Result<()> {
    use windows_sys::Win32::Storage::FileSystem::MoveFileExW;
    let w = |p: &Path| -> Vec<u16> {
        use std::os::windows::ffi::OsStrExt;
        p.as_os_str().encode_wide().chain(std::iter::once(0)).collect()
    };
    let (s, d) = (w(src), w(dst));
    if unsafe { MoveFileExW(s.as_ptr(), d.as_ptr(), 0) } == 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}

fn with_suffix(path: &Path, suffix: &str) -> PathBuf {
    let mut s = path.as_os_str().to_owned();
    s.push(suffix);
    PathBuf::from(s)
}

/// UD:166 backupLegacyDb: the backup's path, None without an old file
pub fn backup_legacy_db(config_dir: &Path) -> Option<PathBuf> {
    let legacy = legacy_db_path(config_dir);
    let backup = config_dir.join(LEGACY_BACKUP_NAME);
    if !legacy.exists() {
        return None;
    }
    if backup.exists() {
        return Some(backup);
    }
    let tmp = with_suffix(&backup, &format!(".{}.tmp", std::process::id()));
    let result = copy_sqlite(&legacy, &tmp)
        .map_err(|e| e.to_string())
        .and_then(|_| rename_no_replace(&tmp, &backup).map_err(|e| e.to_string()));
    if result.is_err() && !backup.exists() {
        // another process is backing up too, or the file cannot be read: copy the bytes
        let _ = crate::config::copy2(&legacy, &backup);
    }
    if tmp.exists() {
        let _ = fs::remove_file(&tmp);
    }
    backup.exists().then_some(backup)
}

/// UD:195 prepareUserDictionary: config_dir\chewing.dat, converted from the old
/// chewing.sqlite3 first when only that exists. Err: the conversion failed and
/// no chewing.dat was created (do not give the path to libchewing).
pub fn prepare_user_dictionary(config_dir: &Path, syspath: &str) -> Result<PathBuf, DictError> {
    let dat = user_dict_path(config_dir);
    let legacy = legacy_db_path(config_dir);
    if dat.exists() || !legacy.exists() {
        return Ok(dat);
    }
    let empty = fs::metadata(&legacy).map(|m| m.len() == 0).unwrap_or(false);
    if !empty {
        backup_legacy_db(config_dir);
    }
    let work_dir = make_work_dir(config_dir, "migrate_").map_err(|e| e.to_string())?;
    let result = (|| -> Result<(), DictError> {
        let converted = if empty {
            // an empty chewing.dat, also made in the work directory
            let converted = work_dir.join(USER_DICT_NAME);
            count_phrases(&converted, syspath)?;
            converted
        } else {
            convert_sqlite(&legacy, &work_dir, syspath)?
        };
        match rename_no_replace(&converted, &dat) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => Ok(()),
            Err(e) => {
                if !dat.exists() {
                    Err(format!("cannot create {}: {}", dat.display(), e))
                } else {
                    Ok(())
                }
            }
        }
    })();
    let _ = fs::remove_dir_all(&work_dir);
    result.map(|_| dat)
}

/// UD:62 touchChangeStamp: tell the IME the user dictionary was changed by the
/// settings tool (libchewing 0.13 keeps it in memory)
pub fn touch_change_stamp(config_dir: &Path) {
    let path = config_dir.join(CHANGE_STAMP_NAME);
    if let Ok(f) = fs::OpenOptions::new().append(true).create(true).open(&path) {
        let _ = f.set_modified(std::time::SystemTime::now());
    }
}

/// os.replace(src, dst): MoveFileExW(MOVEFILE_REPLACE_EXISTING)
pub fn replace_file(src: &Path, dst: &Path) -> std::io::Result<()> {
    use windows_sys::Win32::Storage::FileSystem::{MoveFileExW, MOVEFILE_REPLACE_EXISTING};
    let w = |p: &Path| -> Vec<u16> {
        use std::os::windows::ffi::OsStrExt;
        p.as_os_str().encode_wide().chain(std::iter::once(0)).collect()
    };
    let (s, d) = (w(src), w(dst));
    if unsafe { MoveFileExW(s.as_ptr(), d.as_ptr(), MOVEFILE_REPLACE_EXISTING) } == 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}

pub const SQLITE_MAGIC: &[u8] = b"SQLite format 3\x00";

/// UD:230 _looksLikeTrieDictionary: DER, SEQUENCE { UTF8String "CHEW", ... }
pub fn looks_like_trie_dictionary(data: &[u8]) -> bool {
    if data.len() < 8 || data[0] != 0x30 {
        return false;
    }
    let length_byte = data[1];
    let offset = if length_byte < 0x80 { 2 } else { 2 + (length_byte & 0x7F) as usize };
    data.get(offset..offset + 6) == Some(&b"\x0c\x04CHEW"[..])
}

/// UD:239 importUserDictionary: replace the user dictionary with an uploaded
/// file (a chewing.dat, or an old chewing.sqlite3, converted). The old
/// chewing.dat is copied to chewing.dat.bak first. Err: not a usable
/// dictionary -- the current one is left alone. Ok: the number of phrases.
pub fn import_user_dictionary(data: &[u8], config_dir: &Path, syspath: &str) -> Result<usize, DictError> {
    fs::create_dir_all(config_dir).map_err(|e| e.to_string())?;
    let work_dir = make_work_dir(config_dir, "import_").map_err(|e| e.to_string())?;
    let result = (|| -> Result<usize, DictError> {
        let converted = if data.starts_with(SQLITE_MAGIC) {
            let upload = work_dir.join("upload.sqlite3");
            fs::write(&upload, data).map_err(|e| e.to_string())?;
            let convert_dir = work_dir.join("convert");
            fs::create_dir(&convert_dir).map_err(|e| e.to_string())?;
            convert_sqlite(&upload, &convert_dir, syspath)?
        } else if looks_like_trie_dictionary(data) {
            let converted = work_dir.join(USER_DICT_NAME);
            fs::write(&converted, data).map_err(|e| e.to_string())?;
            converted
        } else {
            return Err("not a libchewing user phrase dictionary".into());
        };
        let count = count_phrases(&converted, syspath)?; // only what libchewing can read
        let dat = user_dict_path(config_dir);
        if dat.exists() {
            let _ = crate::config::copy2(&dat, &with_suffix(&dat, ".bak"));
        }
        // the IME may read the file any time: replace it whole, never half-written
        replace_file(&converted, &dat).map_err(|e| e.to_string())?;
        touch_change_stamp(config_dir);
        Ok(count)
    })();
    let _ = fs::remove_dir_all(&work_dir);
    result
}
