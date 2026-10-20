#![no_main]
// see pimelauncher::fuzz::lines (PIMELauncher/src/fuzz.rs)
libfuzzer_sys::fuzz_target!(init: pimelauncher::fuzz::init_libfuzzer(), |data: &[u8]| pimelauncher::fuzz::lines(data));
