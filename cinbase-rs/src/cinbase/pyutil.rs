//! Small helpers with Python's string / list semantics, for the line-by-line
//! translation of python/cinbase/__init__.py.
//!
//! Python strings index by code point; these helpers work on chars. Errors use
//! Python's exception names so a failing request reads like the traceback.

use serde_json::Value;

/// len(s) for a str (code points).
pub fn py_len(s: &str) -> i64 {
    s.chars().count() as i64
}

/// Normalize a Python slice bound against `len`.
fn bound(i: Option<i64>, len: i64, default: i64) -> i64 {
    match i {
        None => default,
        Some(i) if i < 0 => (i + len).max(0),
        Some(i) => i.min(len),
    }
}

/// s[start:end] (step 1) with Python's negative / out-of-range semantics.
pub fn py_slice(s: &str, start: Option<i64>, end: Option<i64>) -> String {
    let chars: Vec<char> = s.chars().collect();
    let len = chars.len() as i64;
    let a = bound(start, len, 0);
    let b = bound(end, len, len);
    if a >= b {
        return String::new();
    }
    chars[a as usize..b as usize].iter().collect()
}

/// s[i] (one code point); IndexError when out of range.
pub fn py_char_at(s: &str, i: i64) -> Result<String, String> {
    let chars: Vec<char> = s.chars().collect();
    let len = chars.len() as i64;
    let j = if i < 0 { i + len } else { i };
    if j < 0 || j >= len {
        return Err("IndexError: string index out of range".into());
    }
    Ok(chars[j as usize].to_string())
}

/// list[i] with negative indexing; IndexError when out of range.
pub fn py_list_get<T: Clone>(list: &[T], i: i64) -> Result<T, String> {
    let len = list.len() as i64;
    let j = if i < 0 { i + len } else { i };
    if j < 0 || j >= len {
        return Err("IndexError: list index out of range".into());
    }
    Ok(list[j as usize].clone())
}

/// The characters of s as one-char strings (`for c in s`).
pub fn py_chars(s: &str) -> Vec<String> {
    s.chars().map(|c| c.to_string()).collect()
}

/// str.lower()
pub fn py_lower(s: &str) -> String {
    s.to_lowercase()
}

/// `a in b` for strings (substring containment; "" is in everything).
pub fn py_in(a: &str, b: &str) -> bool {
    b.contains(a)
}

/// int(text, 10): surrounding whitespace allowed, ValueError otherwise.
pub fn py_int(text: &str) -> Result<i64, String> {
    let t = text.trim();
    let t2 = t.replace('_', "");
    if t.is_empty() || t.starts_with('_') || t.ends_with('_') || t.contains("__") {
        return Err(format!("ValueError: invalid literal for int() with base 10: '{}'", text));
    }
    t2.parse::<i64>().map_err(|_| format!("ValueError: invalid literal for int() with base 10: '{}'", text))
}

/// `value == n` for a JSON value as Python compares it (True == 1, 1.0 == 1).
pub fn py_eq_int(v: &Value, n: i64) -> bool {
    match v {
        Value::Bool(b) => (*b as i64) == n,
        Value::Number(x) => {
            if let Some(i) = x.as_i64() {
                i == n
            } else {
                x.as_f64() == Some(n as f64)
            }
        }
        _ => false,
    }
}

/// Python truthiness of a JSON value.
pub fn py_truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slices_like_python() {
        assert_eq!(py_slice("abcde", Some(1), Some(-1)), "bcd");
        assert_eq!(py_slice("abcde", Some(-2), None), "de");
        assert_eq!(py_slice("abcde", None, Some(-7)), "");
        assert_eq!(py_slice("大易輸入", Some(1), Some(3)), "易輸");
        assert_eq!(py_slice("abc", Some(5), None), "");
        assert_eq!(py_char_at("abc", -1).unwrap(), "c");
        assert!(py_char_at("abc", 3).is_err());
        assert_eq!(py_int(" 12 ").unwrap(), 12);
        assert!(py_int("x").is_err());
    }
}
