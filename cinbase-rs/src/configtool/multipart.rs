//! `Request.files` of python/config_server.py: the file fields of a
//! multipart/form-data body, parsed the way Python's email package
//! (BytesParser, policy HTTP) splits it -- boundary lines, the line break
//! before a boundary belonging to the boundary, Content-Disposition
//! parameters (quoted, RFC 2231), base64 / quoted-printable transfer encodings.

/// One uploaded file: {"filename", "body", "content_type"}
#[derive(Debug, Clone, PartialEq)]
pub struct FilePart {
    pub name: String,
    pub filename: String,
    pub body: Vec<u8>,
    pub content_type: String,
}

/// The parameters of a MIME header value ("form-data; name=x; filename=y"),
/// names lowercased, values unquoted; RFC 2231 `name*=charset''value` decoded.
pub fn header_params(value: &str) -> Vec<(String, String)> {
    let mut params = Vec::new();
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut in_quotes = false;
    let mut escaped = false;
    for c in value.chars() {
        if in_quotes {
            current.push(c);
            if escaped {
                escaped = false;
            } else if c == '\\' {
                escaped = true;
            } else if c == '"' {
                in_quotes = false;
            }
        } else if c == ';' {
            parts.push(std::mem::take(&mut current));
        } else {
            if c == '"' {
                in_quotes = true;
            }
            current.push(c);
        }
    }
    parts.push(current);
    for part in parts.into_iter().skip(1) {
        let Some((name, value)) = part.split_once('=') else { continue };
        let name = name.trim().to_ascii_lowercase();
        let value = value.trim();
        if let Some(base) = name.strip_suffix('*') {
            // RFC 2231: charset'language'percent-encoded
            let mut it = value.splitn(3, '\'');
            let (charset, _lang, encoded) = (it.next().unwrap_or(""), it.next(), it.next());
            let decoded = match encoded {
                Some(enc) => {
                    let bytes = percent_decode(enc.as_bytes());
                    if charset.eq_ignore_ascii_case("utf-8") || charset.is_empty() {
                        String::from_utf8_lossy(&bytes).into_owned()
                    } else {
                        bytes.iter().map(|&b| b as char).collect()
                    }
                }
                None => unquote(value),
            };
            params.push((base.to_string(), decoded));
        } else {
            params.push((name, unquote(value)));
        }
    }
    params
}

fn param<'a>(params: &'a [(String, String)], name: &str) -> Option<&'a str> {
    params.iter().find(|(k, _)| k == name).map(|(_, v)| v.as_str())
}

fn unquote(value: &str) -> String {
    if value.len() >= 2 && value.starts_with('"') && value.ends_with('"') {
        let inner = &value[1..value.len() - 1];
        let mut out = String::new();
        let mut chars = inner.chars();
        while let Some(c) = chars.next() {
            if c == '\\' {
                if let Some(n) = chars.next() {
                    out.push(n);
                }
            } else {
                out.push(c);
            }
        }
        out
    } else {
        value.to_string()
    }
}

fn percent_decode(s: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(s.len());
    let mut i = 0;
    while i < s.len() {
        if s[i] == b'%' {
            if let (Some(h), Some(l)) = (hex(s.get(i + 1).copied()), hex(s.get(i + 2).copied())) {
                out.push(h * 16 + l);
                i += 3;
                continue;
            }
        }
        out.push(s[i]);
        i += 1;
    }
    out
}

fn hex(b: Option<u8>) -> Option<u8> {
    match b? {
        c @ b'0'..=b'9' => Some(c - b'0'),
        c @ b'a'..=b'f' => Some(c - b'a' + 10),
        c @ b'A'..=b'F' => Some(c - b'A' + 10),
        _ => None,
    }
}

/// Lines with their line endings (\r\n, \r or \n), like email.feedparser.
fn split_lines(data: &[u8]) -> Vec<&[u8]> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut i = 0;
    while i < data.len() {
        match data[i] {
            b'\n' => {
                lines.push(&data[start..=i]);
                start = i + 1;
            }
            b'\r' => {
                let end = if data.get(i + 1) == Some(&b'\n') { i + 1 } else { i };
                lines.push(&data[start..=end]);
                i = end;
                start = end + 1;
            }
            _ => {}
        }
        i += 1;
    }
    if start < data.len() {
        lines.push(&data[start..]);
    }
    lines
}

fn strip_eol(line: &[u8]) -> &[u8] {
    let line = line.strip_suffix(b"\n").unwrap_or(line);
    line.strip_suffix(b"\r").unwrap_or(line)
}

/// "--boundary" or "--boundary--", optionally followed by blanks: Some(is_end)
fn boundary_line(line: &[u8], delimiter: &[u8]) -> Option<bool> {
    let rest = strip_eol(line).strip_prefix(delimiter)?;
    let (end, rest) = match rest.strip_prefix(b"--") {
        Some(r) => (true, r),
        None => (false, rest),
    };
    rest.iter().all(|&b| b == b' ' || b == b'\t').then_some(end)
}

/// A part's headers (name lowercased) and payload.
fn parse_part(data: &[u8]) -> (Vec<(String, String)>, Vec<u8>) {
    let lines = split_lines(data);
    let mut headers: Vec<(String, String)> = Vec::new();
    let mut i = 0;
    while i < lines.len() {
        let line = lines[i];
        let bare = strip_eol(line);
        if bare.is_empty() {
            i += 1;
            break;
        }
        if (bare[0] == b' ' || bare[0] == b'\t') && !headers.is_empty() {
            let text: String = bare.iter().map(|&b| b as char).collect();
            headers.last_mut().unwrap().1.push_str(&text);
            i += 1;
            continue;
        }
        match bare.iter().position(|&b| b == b':') {
            Some(colon) => {
                let name: String = bare[..colon].iter().map(|&b| b as char).collect();
                let value: String = bare[colon + 1..].iter().map(|&b| b as char).collect();
                headers.push((name.trim().to_ascii_lowercase(), value.trim().to_string()));
                i += 1;
            }
            None => break, // not a header: the body starts here
        }
    }
    let body: Vec<u8> = lines[i.min(lines.len())..].concat();
    (headers, body)
}

fn base64_decode(data: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut acc: u32 = 0;
    let mut bits = 0;
    for &c in data {
        let v = match c {
            b'A'..=b'Z' => c - b'A',
            b'a'..=b'z' => c - b'a' + 26,
            b'0'..=b'9' => c - b'0' + 52,
            b'+' => 62,
            b'/' => 63,
            b'=' => break,
            _ => continue,
        } as u32;
        acc = (acc << 6) | v;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((acc >> bits) as u8);
            acc &= (1 << bits) - 1;
        }
    }
    out
}

fn quoted_printable_decode(data: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < data.len() {
        if data[i] == b'=' {
            if data.get(i + 1) == Some(&b'\r') && data.get(i + 2) == Some(&b'\n') {
                i += 3;
                continue;
            }
            if data.get(i + 1) == Some(&b'\n') {
                i += 2;
                continue;
            }
            if let (Some(h), Some(l)) = (hex(data.get(i + 1).copied()), hex(data.get(i + 2).copied())) {
                out.push(h * 16 + l);
                i += 3;
                continue;
            }
        }
        out.push(data[i]);
        i += 1;
    }
    out
}

/// Request.files: the parts that have both a field name and a file name.
pub fn parse_files(content_type: &str, body: &[u8]) -> Vec<FilePart> {
    let mut files = Vec::new();
    if !content_type.to_lowercase().starts_with("multipart/form-data") {
        return files;
    }
    let params = header_params(content_type);
    let Some(boundary) = param(&params, "boundary") else { return files };
    let mut delimiter = b"--".to_vec();
    delimiter.extend_from_slice(boundary.as_bytes());

    let lines = split_lines(body);
    let mut parts: Vec<Vec<u8>> = Vec::new();
    let mut current: Option<Vec<u8>> = None;
    for line in lines {
        match boundary_line(line, &delimiter) {
            Some(is_end) => {
                if let Some(mut part) = current.take() {
                    // the line break before a boundary belongs to the boundary
                    if part.ends_with(b"\r\n") {
                        part.truncate(part.len() - 2);
                    } else if part.ends_with(b"\n") || part.ends_with(b"\r") {
                        part.truncate(part.len() - 1);
                    }
                    parts.push(part);
                }
                if is_end {
                    break;
                }
                current = Some(Vec::new());
            }
            None => {
                if let Some(part) = current.as_mut() {
                    part.extend_from_slice(line);
                }
            }
        }
    }
    if let Some(part) = current.take() {
        parts.push(part); // no closing boundary: the rest is the last part
    }

    for part in parts {
        let (headers, payload) = parse_part(&part);
        let header = |name: &str| headers.iter().find(|(k, _)| k == name).map(|(_, v)| v.as_str());
        let disposition = header_params(header("content-disposition").unwrap_or(""));
        let content_type_value = header("content-type").unwrap_or("");
        let Some(name) = param(&disposition, "name") else { continue };
        // get_filename(): the filename parameter, else the Content-Type name
        let filename = match param(&disposition, "filename") {
            Some(f) => f.trim().to_string(),
            None => match param(&header_params(content_type_value), "name") {
                Some(f) => f.trim().to_string(),
                None => continue,
            },
        };
        let body = match header("content-transfer-encoding").map(|v| v.to_ascii_lowercase()) {
            Some(e) if e == "base64" => base64_decode(&payload),
            Some(e) if e == "quoted-printable" => quoted_printable_decode(&payload),
            _ => payload,
        };
        let content_type = content_type_value.split(';').next().unwrap_or("").trim().to_ascii_lowercase();
        let content_type = if content_type.contains('/') { content_type } else { "text/plain".to_string() };
        files.push(FilePart { name: name.to_string(), filename, body, content_type });
    }
    files
}

#[cfg(test)]
mod tests {
    use super::*;

    fn multipart(boundary: &str, field: &str, filename: &str, data: &[u8]) -> Vec<u8> {
        let mut body = format!(
            "--{b}\r\nContent-Disposition: form-data; name=\"{f}\"; filename=\"{n}\"\r\nContent-Type: application/octet-stream\r\n\r\n",
            b = boundary,
            f = field,
            n = filename
        )
        .into_bytes();
        body.extend_from_slice(data);
        body.extend_from_slice(format!("\r\n--{}--\r\n", boundary).as_bytes());
        body
    }

    #[test]
    fn binary_file_is_kept_byte_for_byte() {
        let data: Vec<u8> = (0..=255u8).chain(b"\r\n\r\n--not-the-boundary\r\n\n\r".iter().copied()).collect();
        let body = multipart("----wimeabc", "import_user_phrase", "x.sqlite3", &data);
        let files = parse_files("multipart/form-data; boundary=----wimeabc", &body);
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].name, "import_user_phrase");
        assert_eq!(files[0].filename, "x.sqlite3");
        assert_eq!(files[0].content_type, "application/octet-stream");
        assert_eq!(files[0].body, data);
    }

    #[test]
    fn quoted_boundary_and_non_file_fields() {
        let body = b"preamble\r\n--b\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\nhello\r\n--b\r\nContent-Disposition: form-data; name=\"f\"; filename*=utf-8''%E6%B8%AC.dat\r\nContent-Transfer-Encoding: base64\r\n\r\nQUJD\r\n--b--\r\nepilogue";
        let files = parse_files("Multipart/Form-Data; boundary=\"b\"", body);
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].filename, "測.dat");
        assert_eq!(files[0].body, b"ABC");
        assert!(parse_files("application/json", body).is_empty());
        assert!(parse_files("multipart/form-data", body).is_empty());
    }
}
