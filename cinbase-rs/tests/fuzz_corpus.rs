//! Replays the saved fuzz inputs with the stable toolchain: every file in
//! fuzz/seeds/<target>/ and fuzz/regressions/<target>/ runs through
//! wime::fuzz::<target> (src/fuzz.rs). A panic anywhere fails the test, also
//! one the code catches (the settings tool answers 500): the hook sees it first.
//!
//! cargo-fuzz finds the inputs (fuzz/README.md); a crash it found is fixed and
//! its input kept in fuzz/regressions/<target>/ so it stays fixed.

use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

static PANICS: AtomicUsize = AtomicUsize::new(0);
static LAST_PANIC: Mutex<String> = Mutex::new(String::new());

type Target = fn(&[u8]);

const TARGETS: &[(&str, Target)] = &[
    ("backend", wime::fuzz::backend),
    ("backend_raw", wime::fuzz::backend_raw),
    ("config_http", wime::fuzz::config_http),
    ("multipart", wime::fuzz::multipart),
    ("http_fields", wime::fuzz::http_fields),
    ("json_body", wime::fuzz::json_body),
    ("user_dictionary", wime::fuzz::user_dictionary),
];

fn inputs(target: &str) -> Vec<std::path::PathBuf> {
    let fuzz = Path::new(env!("CARGO_MANIFEST_DIR")).join("fuzz");
    let mut files = Vec::new();
    for kind in ["seeds", "regressions"] {
        if let Ok(entries) = std::fs::read_dir(fuzz.join(kind).join(target)) {
            files.extend(entries.filter_map(|e| e.ok()).map(|e| e.path()).filter(|p| p.is_file()));
        }
    }
    files.sort();
    files
}

/// One test for all targets: they share the process-wide panic hook and the
/// temporary profile folder.
#[test]
fn saved_fuzz_inputs_do_not_panic() {
    std::panic::set_hook(Box::new(|info| {
        PANICS.fetch_add(1, Ordering::SeqCst);
        *LAST_PANIC.lock().unwrap_or_else(|e| e.into_inner()) = info.to_string();
    }));
    let mut failures = Vec::new();
    let mut count = 0;
    for &(name, target) in TARGETS {
        let files = inputs(name);
        assert!(!files.is_empty(), "no saved inputs for {} (fuzz/seeds/{})", name, name);
        for path in files {
            let data = std::fs::read(&path).unwrap();
            let before = PANICS.load(Ordering::SeqCst);
            let _ = std::panic::catch_unwind(|| target(&data));
            count += 1;
            if PANICS.load(Ordering::SeqCst) != before {
                let message = LAST_PANIC.lock().unwrap_or_else(|e| e.into_inner()).clone();
                failures.push(format!("{}: {}", path.display(), message));
            }
        }
    }
    let _ = std::panic::take_hook();
    let _ = std::fs::remove_dir_all(wime::fuzz::work_dir());
    assert!(failures.is_empty(), "{} of {} saved inputs panicked:\n{}", failures.len(), count, failures.join("\n\n"));
    eprintln!("{} saved fuzz inputs replayed", count);
}

/// The typing seeds must type: with the tables or the dictionaries missing, the
/// fuzzer would only ever see the backend's error paths.
#[test]
fn typing_seeds_commit_chinese() {
    let seeds = Path::new(env!("CARGO_MANIFEST_DIR")).join("fuzz").join("seeds").join("backend");
    for name in ["chedayi_typing", "checj_typing", "chewing_typing"] {
        wime::fuzz::take_committed();
        wime::fuzz::backend(&std::fs::read(seeds.join(name)).unwrap());
        let committed = wime::fuzz::take_committed();
        assert!(committed.chars().any(|c| ('\u{4e00}'..='\u{9fff}').contains(&c)), "{} committed {:?}", name, committed);
        eprintln!("{}: {}", name, committed);
    }
}
