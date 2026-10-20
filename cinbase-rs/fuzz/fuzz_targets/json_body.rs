#![no_main]
// see wime::fuzz::json_body (cinbase-rs/src/fuzz.rs)
libfuzzer_sys::fuzz_target!(init: wime::fuzz::init_libfuzzer(), |data: &[u8]| wime::fuzz::json_body(data));
