//! Fuzz targets of the launcher: what it does with bytes from the pipe clients
//! and the backends. PIMELauncher/fuzz (cargo-fuzz, nightly) runs them under
//! libFuzzer; tests/fuzz_corpus.rs replays fuzz/seeds and fuzz/regressions with
//! the stable toolchain. See cinbase-rs/fuzz/README.md for how to run them.

use crate::protocol::{self, LossyLinesCodec};
use tokio_util::bytes::BytesMut;
use tokio_util::codec::Decoder;

/// libFuzzer (cargo-fuzz `init:`): report a panic as SIGABRT so libFuzzer saves
/// the input (libfuzzer-sys's hook calls process::abort, which on Windows is
/// __fastfail and kills the process before libFuzzer can write anything).
pub fn init_libfuzzer() {
    unsafe extern "C" {
        fn raise(sig: i32) -> i32;
    }
    const SIGABRT: i32 = 22;
    std::panic::set_hook(Box::new(|info| {
        eprintln!("{}", info);
        unsafe { raise(SIGABRT) };
        std::process::abort();
    }));
}

fn decode_all(codec: &mut LossyLinesCodec, chunks: &[&[u8]]) -> Vec<Option<String>> {
    let mut buf = BytesMut::new();
    let mut lines = Vec::new();
    for chunk in chunks {
        buf.extend_from_slice(chunk);
        while let Some(item) = codec.decode(&mut buf).expect("only over-long lines can fail, and they are dropped") {
            lines.push(item);
        }
    }
    while let Some(item) = codec.decode_eof(&mut buf).expect("only over-long lines can fail, and they are dropped") {
        lines.push(item);
    }
    lines
}

/// Backend output as the launcher reads it: the first byte sets the line limit
/// and how the bytes arrive in pieces. However they arrive, the same lines come
/// out, none longer than the limit, and every line the launcher routes splits
/// into a client id and a payload that format back to the line.
pub fn lines(data: &[u8]) {
    let Some((&first, data)) = data.split_first() else { return };
    let max = 1 + (first & 0x3f) as usize;
    let step = 1 + (first >> 6) as usize * 7;
    let whole = decode_all(&mut LossyLinesCodec::new_with_max_length(max), &[data]);
    let pieces: Vec<&[u8]> = data.chunks(step).collect();
    let chunked = decode_all(&mut LossyLinesCodec::new_with_max_length(max), &pieces);
    assert_eq!(whole, chunked, "the lines depend on how the bytes arrived");
    for line in whole.iter().flatten() {
        assert!(line.len() <= max, "a line of {} bytes passed the limit of {}", line.len(), max);
        assert!(!line.contains('\n'));
        if let Some((client_id, payload)) = protocol::parse_backend_output(line) {
            assert!(!client_id.contains('|'));
            assert_eq!(format!("PIME_MSG|{}|{}", client_id, payload), *line);
        }
        let _ = protocol::parse_client_handshake(line);
    }
}
