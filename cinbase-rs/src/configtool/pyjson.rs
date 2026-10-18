//! Python's json module as the settings tools use it, byte for byte:
//! `json.dumps(obj)`, `json.dumps(obj, indent=n)` and
//! `json.dumps(obj, sort_keys=True, indent=n)`, all with the default
//! ensure_ascii=True (non-ASCII as \uXXXX, surrogate pairs beyond the BMP).

use crate::config::py_float_repr;
use serde_json::Value;

/// json.dumps(value): separators (", ", ": "), insertion order
pub fn dumps(value: &Value) -> String {
    let mut out = String::new();
    write_value(value, None, false, 0, &mut out);
    out
}

/// json.dumps(value, indent=indent, sort_keys=sort_keys): separators (",", ": ")
pub fn dumps_indent(value: &Value, indent: usize, sort_keys: bool) -> String {
    let mut out = String::new();
    write_value(value, Some(indent), sort_keys, 0, &mut out);
    out
}

/// json.encoder.py_encode_basestring_ascii
pub fn write_string(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            ' '..='~' => out.push(c),
            _ => {
                let mut buf = [0u16; 2];
                for unit in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{:04x}", unit));
                }
            }
        }
    }
    out.push('"');
}

fn newline(indent: Option<usize>, level: usize, out: &mut String) {
    if let Some(n) = indent {
        out.push('\n');
        out.push_str(&" ".repeat(n * level));
    }
}

fn write_value(value: &Value, indent: Option<usize>, sort_keys: bool, level: usize, out: &mut String) {
    let item_separator = if indent.is_some() { "," } else { ", " };
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => {
            if n.is_f64() {
                let f = n.as_f64().unwrap_or(0.0);
                if f.is_nan() {
                    out.push_str("NaN")
                } else if f.is_infinite() {
                    out.push_str(if f > 0.0 { "Infinity" } else { "-Infinity" })
                } else {
                    out.push_str(&py_float_repr(f))
                }
            } else {
                out.push_str(&n.to_string())
            }
        }
        Value::String(s) => write_string(s, out),
        Value::Array(items) => {
            if items.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(item_separator);
                }
                newline(indent, level + 1, out);
                write_value(item, indent, sort_keys, level + 1, out);
            }
            newline(indent, level, out);
            out.push(']');
        }
        Value::Object(map) => {
            if map.is_empty() {
                out.push_str("{}");
                return;
            }
            let mut keys: Vec<&String> = map.keys().collect();
            if sort_keys {
                keys.sort(); // UTF-8 byte order == code point order (Python str order)
            }
            out.push('{');
            for (i, key) in keys.iter().enumerate() {
                if i > 0 {
                    out.push_str(item_separator);
                }
                newline(indent, level + 1, out);
                write_string(key, out);
                out.push_str(": ");
                write_value(&map[key.as_str()], indent, sort_keys, level + 1, out);
            }
            newline(indent, level, out);
            out.push('}');
        }
    }
}

/// json.loads(bytes) for a request body (UTF-8, a UTF-8 BOM is skipped like
/// json.detect_encoding does). Err: what Python would raise (JSONDecodeError).
pub fn loads(body: &[u8]) -> Result<Value, String> {
    let body = body.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(body);
    serde_json::from_slice(body).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn matches_python_json_dumps() {
        let v = json!({"b": [1, 2.5, "測試", null, true], "a": {}, "c": [], "d": "\u{1F600}\"\\\n\u{7f}"});
        assert_eq!(dumps(&v), r#"{"b": [1, 2.5, "Ux6e2cUx8a66", null, true], "a": {}, "c": [], "d": "Uxd83dUxde00\"\\\nUx007f"}"#.replace("Ux", r"\u"));
        assert_eq!(dumps_indent(&json!({"b": 1, "a": [1, {"x": 1.0}]}), 4, true), "{\n    \"a\": [\n        1,\n        {\n            \"x\": 1.0\n        }\n    ],\n    \"b\": 1\n}");
        assert_eq!(dumps_indent(&json!({"b": 1, "a": 2}), 2, false), "{\n  \"b\": 1,\n  \"a\": 2\n}");
        assert_eq!(dumps(&json!(1e20)), "1e+20");
        assert_eq!(dumps(&json!(-0.0)), "-0.0");
    }

    #[test]
    fn loads_skips_a_utf8_bom() {
        assert_eq!(loads(b"\xEF\xBB\xBF{\"a\": 1}").unwrap(), json!({"a": 1}));
        assert!(loads(b"{").is_err());
    }
}
