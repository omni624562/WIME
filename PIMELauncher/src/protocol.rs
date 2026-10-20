use serde_json::Value;
use tokio_util::bytes::BytesMut;
use tokio_util::codec::{Decoder, LinesCodec, LinesCodecError};

/// Maximum allowed length (in bytes) for a single message line.
pub const MAX_MESSAGE_LINE_LENGTH: usize = 1048576;

/// Lines of at most `max_length` bytes of UTF-8; a longer line, or one that is
/// not UTF-8, is dropped (`None`) and reading goes on. A plain LinesCodec
/// reports those as errors, and FramedRead ends the stream after any error: a
/// backend's stdout read that way stopped at the first over-long reply, cutting
/// every client of the backend off.
pub struct LossyLinesCodec(LinesCodec);

/// The line errors LinesCodec recovers from: it has consumed (or skips) the line.
fn line_dropped(e: &LinesCodecError) -> bool {
    match e {
        LinesCodecError::MaxLineLengthExceeded => true,
        LinesCodecError::Io(e) => e.kind() == std::io::ErrorKind::InvalidData,
    }
}

impl LossyLinesCodec {
    pub fn new_with_max_length(max_length: usize) -> Self {
        Self(LinesCodec::new_with_max_length(max_length))
    }
}

impl Decoder for LossyLinesCodec {
    type Item = Option<String>;
    type Error = LinesCodecError;

    fn decode(&mut self, buf: &mut BytesMut) -> Result<Option<Self::Item>, Self::Error> {
        match self.0.decode(buf) {
            Ok(line) => Ok(line.map(Some)),
            Err(e) if line_dropped(&e) => Ok(Some(None)),
            Err(e) => Err(e),
        }
    }

    fn decode_eof(&mut self, buf: &mut BytesMut) -> Result<Option<Self::Item>, Self::Error> {
        match self.0.decode_eof(buf) {
            Ok(line) => Ok(line.map(Some)),
            Err(e) if line_dropped(&e) => Ok(Some(None)),
            Err(e) => Err(e),
        }
    }
}

/// Parses the first line received from a client to determine which backend to use.
///
/// Supports standard `{"method": "init", "id": "{GUID}"}`.
pub fn parse_client_handshake(first_line: &str) -> Result<String, String> {
    let json: Value = serde_json::from_str(first_line).map_err(|e| e.to_string())?;

    if let Some(method) = json["method"].as_str() {
        if method == "init" {
            if let Some(guid) = json["id"].as_str() {
                return Ok(guid.to_string());
            }
            return Err("Missing 'id' field in init message".to_string());
        }
        return Err(format!("Unknown method '{}' in initial message", method));
    }
    Err("Invalid initial message format: missing 'method' field".to_string())
}

/// Parses a line of output from a backend process.
///
/// Expects the format `PIME_MSG|<client_id>|<payload>`.
/// Returns `Some((client_id, payload))` if valid.
pub fn parse_backend_output(line: &str) -> Option<(String, String)> {
    let rest = line.strip_prefix("PIME_MSG|")?;
    let sep = rest.find('|')?;
    Some((rest[..sep].to_string(), rest[sep + 1..].to_string()))
}

/// Formats a message to be sent to a backend process.
///
/// Format: <client_id>|<payload>
pub fn format_backend_input(client_id: &str, message: &str) -> String {
    format!("{}|{}", client_id, message)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_client_handshake_init() {
        let json = format!(
            r#"{{"method": "init", "id": "{}"}}"#,
            crate::testing::GUID_TEST_ECHO
        );
        match parse_client_handshake(&json) {
            Ok(guid) => assert_eq!(guid, crate::testing::GUID_TEST_ECHO),
            _ => panic!("Expected Init handshake"),
        }
    }

    #[test]
    fn test_parse_client_handshake_invalid() {
        assert!(parse_client_handshake("not json").is_err());
        assert!(parse_client_handshake(r#"{"method": "unknown"}"#).is_err());
        assert!(parse_client_handshake(r#"{"method": "init"}"#).is_err()); // missing id
    }

    #[test]
    fn test_parse_backend_output_valid() {
        let line = "PIME_MSG|client123|{\"status\": \"ok\"}";
        let (client_id, payload) = parse_backend_output(line).unwrap();
        assert_eq!(client_id, "client123");
        assert_eq!(payload, "{\"status\": \"ok\"}");
    }

    #[test]
    fn test_parse_backend_output_invalid() {
        assert!(parse_backend_output("JUST_TEXT").is_none());
        assert!(parse_backend_output("PIME_MSG|incomplete").is_none());
    }

    #[test]
    fn test_lossy_lines_drop_only_the_long_line() {
        let mut codec = LossyLinesCodec::new_with_max_length(8);
        let mut buf = BytesMut::from(&b"short\nmuch too long for it\nbad \xff\nnext\n"[..]);
        let mut lines = Vec::new();
        while let Some(item) = codec.decode(&mut buf).unwrap() {
            lines.push(item);
        }
        assert_eq!(lines, vec![Some("short".to_string()), None, None, Some("next".to_string())]);
    }

    #[test]
    fn test_format_backend_input() {
        let client_id = "client123";
        let message = "{\"method\": \"test\"}";
        let formatted = format_backend_input(client_id, message);
        assert_eq!(formatted, "client123|{\"method\": \"test\"}");
    }
}
