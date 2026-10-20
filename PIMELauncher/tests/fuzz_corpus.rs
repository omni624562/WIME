//! Replays the saved fuzz inputs (fuzz/seeds, fuzz/regressions) through
//! pimelauncher::fuzz with the stable toolchain, so every CI run checks them.

use std::path::Path;

#[test]
fn saved_fuzz_inputs_do_not_panic() {
    let fuzz = Path::new(env!("CARGO_MANIFEST_DIR")).join("fuzz");
    let mut count = 0;
    for kind in ["seeds", "regressions"] {
        let Ok(entries) = std::fs::read_dir(fuzz.join(kind).join("lines")) else { continue };
        for entry in entries {
            let path = entry.unwrap().path();
            let data = std::fs::read(&path).unwrap();
            if std::panic::catch_unwind(|| pimelauncher::fuzz::lines(&data)).is_err() {
                panic!("{} panicked", path.display());
            }
            count += 1;
        }
    }
    assert!(count > 0, "no saved inputs in fuzz/seeds/lines");
}
