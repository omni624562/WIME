#![no_main]
// see wime::fuzz::config_http (cinbase-rs/src/fuzz.rs)
libfuzzer_sys::fuzz_target!(init: wime::fuzz::init_libfuzzer(), |data: &[u8]| wime::fuzz::config_http(data));
