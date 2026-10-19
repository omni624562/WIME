//! Port of python/config_server.py: the local HTTP server both settings tools
//! run on (token login, Host check, idle exit, browser launch).
//!
//! Invariants kept from the Python server (see tests/test_config_server.py):
//! - binds 127.0.0.1 on a random port with SO_EXCLUSIVEADDRUSE;
//! - a one-time access token (uuid4 hex) per start, accepted only from the
//!   login URL (GET query or the launch_<tool>.html form POST) and compared in
//!   constant time; the cookie is HttpOnly and SameSite=Strict;
//! - every API request without the right cookie gets 403, every request with
//!   a Host other than 127.0.0.1 / localhost / ::1 gets 403 (DNS rebinding);
//! - static files never leave their folder (.., drive letters, ADS, links);
//! - request bodies over 64 MB get 413 without being read;
//! - errors never show details (paths, messages) to the browser;
//! - no version in the Server header, X-Content-Type-Options: nosniff;
//! - the process exits with 0 after SERVER_TIMEOUT seconds without requests
//!   (the pages call /keep_alive), so it never keeps the install folder busy.
//!
//! Requests are handled one at a time (one lock around the handlers, like
//! the Python server), each connection on its own thread.

use super::pyjson;
use serde_json::Value;
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// Seconds without requests before the server exits (config_server.SERVER_TIMEOUT).
pub const SERVER_TIMEOUT: f64 = 120.0;
/// MAX_BODY_SIZE: the biggest body is an imported 新酷音 user dictionary
pub const MAX_BODY_SIZE: u64 = 64 * 1024 * 1024;
/// http.server: request line / header line limit (_MAXLINE) and header count
const MAX_LINE: usize = 65536;
const MAX_HEADERS: usize = 100;
/// _RequestHandler.timeout: an idle keep-alive connection is closed after this
const CONNECTION_TIMEOUT: Duration = Duration::from_secs(60);

/// Test hooks, never set in production:
/// - WIME_CONFIG_TEST_LAUNCH=print: print "URL <target>" on stdout instead of
///   opening the browser (what tests/test_config_server.py does to os.startfile);
///   `fail-url`: the URL "cannot be opened", so the launch_<tool>.html fallback
///   is written and its path printed instead.
/// - WIME_CONFIG_IDLE_TIMEOUT=<seconds>: SERVER_TIMEOUT
pub const TEST_LAUNCH_ENV: &str = "WIME_CONFIG_TEST_LAUNCH";
pub const IDLE_TIMEOUT_ENV: &str = "WIME_CONFIG_IDLE_TIMEOUT";

/// Content-Type by extension: a fixed table (the registry can map .js to text/plain)
const CONTENT_TYPES: &[(&str, &str)] = &[
    (".html", "text/html; charset=UTF-8"),
    (".htm", "text/html; charset=UTF-8"),
    (".js", "application/javascript; charset=UTF-8"),
    (".css", "text/css; charset=UTF-8"),
    (".json", "application/json; charset=UTF-8"),
    (".txt", "text/plain; charset=UTF-8"),
    (".ico", "image/x-icon"),
    (".png", "image/png"),
    (".jpg", "image/jpeg"),
    (".jpeg", "image/jpeg"),
    (".gif", "image/gif"),
    (".svg", "image/svg+xml"),
    (".woff", "font/woff"),
    (".woff2", "font/woff2"),
    (".ttf", "font/ttf"),
    (".otf", "font/otf"),
    (".eot", "application/vnd.ms-fontobject"),
    (".map", "application/json; charset=UTF-8"),
];

/// Writes to stderr (pythonw has none: errors only show when started from a console).
pub fn log(message: &str) {
    let _ = writeln!(std::io::stderr(), "{}", message);
}

// ---------------------------------------------------------------------------
// requests and responses

/// What a handler sees of the HTTP request.
pub struct Request {
    pub method: String,
    pub path: String,
    pub query: String,
    /// header lines as received (ISO-8859-1), in order
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

impl Request {
    /// headers.get(name): the first header of that name
    pub fn header(&self, name: &str) -> Option<&str> {
        self.headers.iter().find(|(k, _)| k.eq_ignore_ascii_case(name)).map(|(_, v)| v.as_str())
    }

    /// urllib.parse.parse_qs(query, keep_blank_values=True) as pairs
    pub fn query_arguments(&self) -> Vec<(String, String)> {
        parse_qsl(&self.query)
    }

    /// form arguments of a POST with Content-Type application/x-www-form-urlencoded
    pub fn body_arguments(&self) -> Vec<(String, String)> {
        let content_type = self.header("Content-Type").unwrap_or("").to_lowercase();
        if self.method == "POST" && content_type.starts_with("application/x-www-form-urlencoded") {
            parse_qsl(&String::from_utf8_lossy(&self.body))
        } else {
            Vec::new()
        }
    }

    /// RequestHandler.get_argument(name, default): body first, then query; the last value
    pub fn get_argument(&self, name: &str, default: &str) -> String {
        for source in [self.body_arguments(), self.query_arguments()] {
            if let Some((_, v)) = source.iter().rev().find(|(k, _)| k == name) {
                return v.clone();
            }
        }
        default.to_string()
    }
}

/// A handler's answer (status, headers in order, cookies, body).
pub struct Response {
    pub status: u16,
    pub reason: Option<String>,
    headers: Vec<(String, String)>,
    cookies: Vec<String>,
    pub body: Vec<u8>,
}

impl Default for Response {
    fn default() -> Self {
        Response { status: 200, reason: None, headers: Vec::new(), cookies: Vec::new(), body: Vec::new() }
    }
}

impl Response {
    pub fn new() -> Response {
        Response::default()
    }

    /// set_header: replaces a header of the same name (keeping its place)
    pub fn set_header(&mut self, name: &str, value: &str) {
        match self.headers.iter_mut().find(|(k, _)| k == name) {
            Some(h) => h.1 = value.to_string(),
            None => self.headers.push((name.to_string(), value.to_string())),
        }
    }

    /// write(str / bytes)
    pub fn write(&mut self, data: &[u8]) {
        self.body.extend_from_slice(data);
    }

    /// write(dict): json.dumps and the JSON Content-Type
    pub fn write_json(&mut self, value: &Value) {
        self.write(pyjson::dumps(value).as_bytes());
        self.set_header("Content-Type", "application/json; charset=UTF-8");
    }

    pub fn redirect(&mut self, url: &str) {
        self.status = 302;
        self.reason = None;
        self.set_header("Location", url);
    }

    fn set_cookie(&mut self, name: &str, value: &str) {
        // HttpOnly: the pages never read it; SameSite=Strict: no cross-site requests carry it (CSRF)
        self.cookies.push(format!("{}={}; Path=/; HttpOnly; SameSite=Strict", name, value));
    }
}

/// HTTPError (a status for the browser, no details) or an unexpected error
/// (500, the message only goes to stderr).
#[derive(Debug)]
pub enum HttpError {
    Status(u16, Option<String>),
    Internal(String),
}

impl HttpError {
    pub fn status(code: u16) -> HttpError {
        HttpError::Status(code, None)
    }
    pub fn reason(code: u16, reason: &str) -> HttpError {
        HttpError::Status(code, Some(reason.to_string()))
    }
}

pub type HandlerResult = Result<Response, HttpError>;

// ---------------------------------------------------------------------------
// routes

/// What a route leads to.
pub enum Target {
    /// NoCacheStaticFileHandler(path=root): the first group is the file
    Static(PathBuf),
    /// a tool's own (authenticated) handler, by name
    Api(&'static str),
    KeepAlive,
    /// /login/(.*)
    Login,
}

/// A route: a matcher standing for the Python regular expression (fullmatch on
/// the path; Some(groups) when it matches) and its target.
pub struct Route {
    pub pattern: &'static str,
    pub matcher: Box<dyn Fn(&str) -> Option<Vec<String>> + Send + Sync>,
    pub target: Target,
}

/// `.` of a regular expression: any character but a newline
fn regex_dot_eq(pattern: &str, text: &str) -> bool {
    let (p, t): (Vec<char>, Vec<char>) = (pattern.chars().collect(), text.chars().collect());
    p.len() == t.len() && p.iter().zip(&t).all(|(a, b)| if *a == '.' { *b != '\n' } else { a == b })
}

impl Route {
    /// r"/(.*<suffix>)" where suffix is literal (escaped dots)
    pub fn suffix(pattern: &'static str, suffix: &'static str, target: Target) -> Route {
        Route {
            pattern,
            matcher: Box::new(move |path| {
                let rest = path.strip_prefix('/')?;
                (rest.ends_with(suffix) && !rest.contains('\n')).then(|| vec![rest.to_string()])
            }),
            target,
        }
    }

    /// r"/(name)" where the dots of name match any character
    pub fn exact_dot(pattern: &'static str, name: &'static str, target: Target) -> Route {
        Route {
            pattern,
            matcher: Box::new(move |path| {
                let rest = path.strip_prefix('/')?;
                regex_dot_eq(name, rest).then(|| vec![rest.to_string()])
            }),
            target,
        }
    }

    /// r"/((a|b|c)/.*)"
    pub fn dirs(pattern: &'static str, dirs: &'static [&'static str], target: Target) -> Route {
        Route {
            pattern,
            matcher: Box::new(move |path| {
                let rest = path.strip_prefix('/')?;
                let dir = dirs.iter().find(|d| rest.len() > d.len() && rest.starts_with(*d) && rest[d.len()..].starts_with('/'))?;
                (!rest.contains('\n')).then(|| vec![rest.to_string(), dir.to_string()])
            }),
            target,
        }
    }

    /// any matcher
    pub fn custom(pattern: &'static str, matcher: impl Fn(&str) -> Option<Vec<String>> + Send + Sync + 'static, target: Target) -> Route {
        Route { pattern, matcher: Box::new(matcher), target }
    }

    /// a fixed path such as r"/config"
    pub fn exact(path: &'static str, target: Target) -> Route {
        Route { pattern: path, matcher: Box::new(move |p| (p == path).then(Vec::new)), target }
    }
}

/// What differs between the two tools.
pub trait Tool: Send {
    /// the auth cookie's name
    fn cookie_id(&self) -> &'static str;
    /// the page (without .html) the login redirects to
    fn main_page(&self) -> &'static str;
    /// where the POST-login fallback launch_<tool>.html is written
    fn localdata_dir(&self) -> PathBuf;
    /// the tool's routes; /keep_alive and /login/(.*) are added after them
    fn routes(&self) -> Vec<Route>;
    /// an API route (always authenticated), GET or POST
    fn handle(&mut self, api: &'static str, method: &str, request: &Request) -> HandlerResult;
}

// ---------------------------------------------------------------------------
// Python's URL and cookie parsing

/// urllib.parse.unquote(s): %XX runs decoded as UTF-8 with replacement,
/// non-ASCII characters left as they are
pub fn unquote(s: &str) -> String {
    if !s.contains('%') {
        return s.to_string();
    }
    let mut out = String::new();
    let mut ascii_run = String::new();
    let flush = |run: &mut String, out: &mut String| {
        if !run.is_empty() {
            out.push_str(&String::from_utf8_lossy(&unquote_to_bytes(run.as_bytes())));
            run.clear();
        }
    };
    for c in s.chars() {
        if c.is_ascii() {
            ascii_run.push(c);
        } else {
            flush(&mut ascii_run, &mut out);
            out.push(c);
        }
    }
    flush(&mut ascii_run, &mut out);
    out
}

fn hex_value(b: u8) -> Option<u8> {
    match b {
        b'0'..=b'9' => Some(b - b'0'),
        b'a'..=b'f' => Some(b - b'a' + 10),
        b'A'..=b'F' => Some(b - b'A' + 10),
        _ => None,
    }
}

fn unquote_to_bytes(s: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(s.len());
    let mut i = 0;
    while i < s.len() {
        if s[i] == b'%' {
            if let (Some(h), Some(l)) = (s.get(i + 1).and_then(|&b| hex_value(b)), s.get(i + 2).and_then(|&b| hex_value(b))) {
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

/// urllib.parse.parse_qsl(qs, keep_blank_values=True) ('&'-separated)
pub fn parse_qsl(qs: &str) -> Vec<(String, String)> {
    let mut pairs = Vec::new();
    for field in qs.split('&') {
        if field.is_empty() {
            continue;
        }
        let (name, value) = field.split_once('=').unwrap_or((field, ""));
        pairs.push((unquote(&name.replace('+', " ")), unquote(&value.replace('+', " "))));
    }
    pairs
}

/// urllib.parse.urlsplit(target): (path, query)
fn split_target(target: &str) -> (String, String) {
    let target = target.split('#').next().unwrap_or("");
    let (mut rest, query) = match target.split_once('?') {
        Some((a, b)) => (a, b),
        None => (target, ""),
    };
    // scheme://netloc/path
    if let Some(colon) = rest.find(':') {
        let scheme = &rest[..colon];
        if !scheme.is_empty()
            && scheme.chars().next().is_some_and(|c| c.is_ascii_alphabetic())
            && scheme.chars().all(|c| c.is_ascii_alphanumeric() || "+-.".contains(c))
        {
            rest = &rest[colon + 1..];
            if let Some(after) = rest.strip_prefix("//") {
                rest = after.find('/').map(|i| &after[i..]).unwrap_or("");
            }
        }
    }
    (rest.to_string(), query.to_string())
}

/// http.cookies: characters of keys and unquoted values (ASCII \w plus these)
fn legal_cookie_char(c: char, value: bool) -> bool {
    c.is_ascii_alphanumeric() || "_!#%&'~`><@,:/$*+-.^|)(?}{=".contains(c) || (value && (c == '[' || c == ']'))
}

/// http.cookies._is_legal_key
fn legal_morsel_key(key: &str) -> bool {
    !key.is_empty() && key.chars().all(|c| c.is_ascii_alphanumeric() || "!#$%&'*+-.^_`|~:".contains(c))
}

const COOKIE_RESERVED: &[&str] = &["expires", "path", "comment", "domain", "max-age", "secure", "httponly", "version", "samesite", "partitioned"];
const COOKIE_FLAGS: &[&str] = &["secure", "httponly", "partitioned"];

/// http.cookies._unquote
fn cookie_unquote(value: &str) -> String {
    let chars: Vec<char> = value.chars().collect();
    if chars.len() < 2 || chars[0] != '"' || chars[chars.len() - 1] != '"' {
        return value.to_string();
    }
    let inner = &chars[1..chars.len() - 1];
    let mut out = String::new();
    let mut i = 0;
    while i < inner.len() {
        if inner[i] == '\\' && i + 1 < inner.len() {
            let octal: String = inner[i + 1..inner.len().min(i + 4)].iter().collect();
            if octal.len() == 3 && octal.chars().all(|c| ('0'..='7').contains(&c)) {
                out.push(char::from_u32(u32::from_str_radix(&octal, 8).unwrap_or(0)).unwrap_or('\u{fffd}'));
                i += 4;
            } else {
                out.push(inner[i + 1]);
                i += 2;
            }
        } else {
            out.push(inner[i]);
            i += 1;
        }
    }
    out
}

fn is_cookie_space(c: char) -> bool {
    matches!(c, ' ' | '\t' | '\n' | '\r' | '\x0b' | '\x0c')
}

/// SimpleCookie().load(header) then cookie.get(name).value: None when the
/// header is invalid (nothing is applied) or has no such cookie.
pub fn get_cookie(header: &str, name: &str) -> Option<String> {
    let chars: Vec<char> = header.chars().collect();
    let n = chars.len();
    let mut i = 0;
    // (is_attribute, key, value)
    let mut items: Vec<(bool, String, Option<String>)> = Vec::new();
    let mut morsel_seen = false;
    'parse: while i < n {
        let mut j = i;
        while j < n && is_cookie_space(chars[j]) {
            j += 1;
        }
        let key_start = j;
        while j < n && chars[j] != '=' && legal_cookie_char(chars[j], false) {
            j += 1;
        }
        if j == key_start {
            break 'parse;
        }
        let key: String = chars[key_start..j].iter().collect();
        let mut k = j;
        while k < n && is_cookie_space(chars[k]) {
            k += 1;
        }
        let mut value: Option<String> = None;
        if k < n && chars[k] == '=' {
            k += 1;
            while k < n && is_cookie_space(chars[k]) {
                k += 1;
            }
            let v_start = k;
            if k < n && chars[k] == '"' {
                let mut m = k + 1;
                let mut closed = false;
                while m < n {
                    if chars[m] == '\\' && m + 1 < n {
                        m += 2;
                    } else if chars[m] == '"' {
                        closed = true;
                        m += 1;
                        break;
                    } else {
                        m += 1;
                    }
                }
                if closed {
                    k = m;
                }
            } else {
                while k < n && legal_cookie_char(chars[k], true) {
                    k += 1;
                }
            }
            value = Some(chars[v_start..k].iter().collect());
            j = k;
        }
        // \s*(\s+|;|$)
        let mut m = j;
        while m < n && is_cookie_space(chars[m]) {
            m += 1;
        }
        if m < n {
            if chars[m] == ';' {
                m += 1;
            } else if m == j {
                break 'parse; // no match: stop, keep what was parsed
            }
        }
        i = m;

        let lower = key.to_lowercase();
        if let Some(attr) = key.strip_prefix('$') {
            if morsel_seen {
                items.push((true, attr.to_string(), value));
            }
        } else if COOKIE_RESERVED.contains(&lower.as_str()) {
            if !morsel_seen {
                return None;
            }
            match value {
                None if COOKIE_FLAGS.contains(&lower.as_str()) => items.push((true, key, None)),
                None => return None,
                Some(v) => items.push((true, key, Some(v))),
            }
        } else if let Some(v) = value {
            items.push((false, key, Some(v)));
            morsel_seen = true;
        } else {
            return None;
        }
    }
    let mut found = None;
    for (is_attribute, key, value) in items {
        if is_attribute {
            if !COOKIE_RESERVED.contains(&key.to_lowercase().as_str()) {
                return None; // CookieError: get_cookie returns the default
            }
        } else {
            if !legal_morsel_key(&key) {
                return None;
            }
            if key == name {
                found = value.map(|v| cookie_unquote(&v));
            }
        }
    }
    found
}

/// hmac.compare_digest for two ASCII strings
fn constant_time_eq(a: &str, b: &str) -> bool {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    let mut diff = (a.len() != b.len()) as u8;
    for i in 0..a.len().max(b.len()) {
        diff |= a.get(i).copied().unwrap_or(0) ^ b.get(i).copied().unwrap_or(1);
    }
    diff == 0
}

/// hmac.compare_digest(str, str): TypeError (a 500) for non-ASCII strings
fn compare_token(given: &str, expected: &str) -> Result<bool, HttpError> {
    if !given.is_ascii() || !expected.is_ascii() {
        return Err(HttpError::Internal("TypeError: comparing strings with non-ASCII characters is not supported".into()));
    }
    Ok(constant_time_eq(given, expected))
}

// ---------------------------------------------------------------------------
// static files

/// os.path.realpath for an existing path (None when it does not exist)
fn real_path(path: &Path) -> Option<PathBuf> {
    let canonical = std::fs::canonicalize(path).ok()?;
    let s = canonical.to_string_lossy();
    Some(match s.strip_prefix(r"\\?\UNC\") {
        Some(unc) => PathBuf::from(format!(r"\\{}", unc)),
        None => PathBuf::from(s.strip_prefix(r"\\?\").unwrap_or(&s)),
    })
}

/// os.path.splitext(path)[1].lower()
fn extension(path: &Path) -> String {
    let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    let stripped = name.trim_start_matches('.');
    match stripped.rfind('.') {
        Some(i) => stripped[i..].to_lowercase(),
        None => String::new(),
    }
}

/// NoCacheStaticFileHandler.get
fn serve_static(root: &Path, relative: &str) -> HandlerResult {
    let relative = unquote(relative);
    // never outside the folder: ../, absolute paths, drive letters (C:), UNC, NTFS streams (file:stream)
    let parts: Vec<String> = relative.replace('\\', "/").split('/').map(str::to_string).collect();
    if relative.contains(':') || relative.starts_with('/') || parts.iter().any(|p| p == "..") {
        return Err(HttpError::status(403));
    }
    let root = real_path(root).unwrap_or_else(|| root.to_path_buf());
    let mut full = root.clone();
    for part in parts.iter().filter(|p| !p.is_empty()) {
        full.push(part);
    }
    let Some(full) = real_path(&full) else {
        return Err(HttpError::status(404));
    };
    // os.path.commonpath([full, root]) == root (case-insensitive, like ntpath)
    let (f, r) = (full.to_string_lossy().to_lowercase(), root.to_string_lossy().to_lowercase());
    let r = r.trim_end_matches('\\');
    if !(f == r || f.starts_with(&format!("{}\\", r))) {
        return Err(HttpError::status(403));
    }
    if !full.is_file() {
        return Err(HttpError::status(404));
    }
    let data = std::fs::read(&full).map_err(|e| HttpError::Internal(format!("{}: {}", full.display(), e)))?;
    let ext = extension(&full);
    let content_type = CONTENT_TYPES.iter().find(|(e, _)| *e == ext).map(|(_, t)| *t).unwrap_or("application/octet-stream");
    let mut response = Response::new();
    response.set_header("Content-Type", content_type);
    response.set_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
    response.set_header("Pragma", "no-cache");
    response.set_header("Expires", "0");
    response.write(&data);
    Ok(response)
}

// ---------------------------------------------------------------------------
// the server

fn http_reason(code: u16) -> (&'static str, &'static str) {
    match code {
        100 => ("Continue", "Request received, please continue"),
        200 => ("OK", "Request fulfilled, document follows"),
        302 => ("Found", "Object moved temporarily -- see URI list"),
        400 => ("Bad Request", "Bad request syntax or unsupported method"),
        403 => ("Forbidden", "Request forbidden -- authorization will not help"),
        404 => ("Not Found", "Nothing matches the given URI"),
        405 => ("Method Not Allowed", "Specified method is invalid for this resource"),
        411 => ("Length Required", "Client must specify Content-Length"),
        413 => ("Content Too Large", "Content is too large"),
        414 => ("URI Too Long", "URI is too long"),
        431 => (
            "Request Header Fields Too Large",
            "The server is unwilling to process the request because its header fields are too large",
        ),
        500 => ("Internal Server Error", "Server got itself in trouble"),
        501 => ("Not Implemented", "Server does not support this operation"),
        503 => ("Service Unavailable", "The server cannot process the request due to a high load"),
        505 => ("HTTP Version Not Supported", "Cannot fulfill request"),
        _ => ("???", "???"),
    }
}

/// email.utils.formatdate(usegmt=True)
fn http_date() -> String {
    let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0);
    let days = secs.div_euclid(86400);
    let rem = secs.rem_euclid(86400);
    let weekday = ["Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Wed"][(days.rem_euclid(7)) as usize];
    // civil_from_days (Howard Hinnant)
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    let month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][(m - 1) as usize];
    format!("{}, {:02} {} {:04} {:02}:{:02}:{:02} GMT", weekday, d, month, y, rem / 3600, rem % 3600 / 60, rem % 60)
}

/// Server header: server_version + " " + sys_version (empty), no Python version
const SERVER_HEADER: &str = "WIME ";

fn status_line(code: u16, reason: Option<&str>) -> String {
    let reason = match reason {
        // the status line takes visible ASCII only
        Some(r) => r.chars().map(|c| if c == '\r' || c == '\n' { ' ' } else if c.is_ascii() { c } else { '?' }).collect(),
        None => http_reason(code).0.to_string(),
    };
    format!("HTTP/1.1 {} {}\r\n", code, reason)
}

/// BaseHTTPRequestHandler.send_error (protocol errors before dispatch)
fn send_error(stream: &mut impl Write, code: u16, message: Option<&str>, http09: bool) {
    let (short, long) = http_reason(code);
    let message = message.unwrap_or(short);
    let escape = |s: &str| s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;");
    let body = format!(
        "<!DOCTYPE HTML>\n<html lang=\"en\">\n    <head>\n        <meta charset=\"utf-8\">\n        <style type=\"text/css\">\n            :root {{\n                color-scheme: light dark;\n            }}\n        </style>\n        <title>Error response</title>\n    </head>\n    <body>\n        <h1>Error response</h1>\n        <p>Error code: {code}</p>\n        <p>Message: {message}.</p>\n        <p>Error code explanation: {code} - {explain}.</p>\n    </body>\n</html>\n",
        code = code,
        message = escape(message),
        explain = escape(long)
    );
    let mut out = Vec::new();
    if !http09 {
        out.extend_from_slice(status_line(code, Some(message)).as_bytes());
        out.extend_from_slice(format!("Server: {}\r\nDate: {}\r\nConnection: close\r\n", SERVER_HEADER, http_date()).as_bytes());
        out.extend_from_slice(format!("Content-Type: text/html;charset=utf-8\r\nContent-Length: {}\r\n\r\n", body.len()).as_bytes());
    }
    out.extend_from_slice(body.as_bytes());
    let _ = stream.write_all(&out);
    let _ = stream.flush();
}

pub struct App {
    tool: Mutex<Box<dyn Tool>>,
    routes: Vec<Route>,
    access_token: String,
    cookie_id: &'static str,
    main_page: &'static str,
    localdata_dir: PathBuf,
    /// the last request (None until the timer starts, like reset_timeout)
    activity: Mutex<Option<Instant>>,
    timeout: Duration,
    launch_file: Mutex<Option<PathBuf>>,
}

/// uuid.uuid4().hex
fn new_token() -> String {
    let mut bytes = [0u8; 16];
    let ok = unsafe {
        windows_sys::Win32::Security::Cryptography::BCryptGenRandom(
            std::ptr::null_mut(),
            bytes.as_mut_ptr(),
            bytes.len() as u32,
            windows_sys::Win32::Security::Cryptography::BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    } == 0;
    if !ok {
        panic!("BCryptGenRandom failed");
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

fn idle_timeout() -> Duration {
    let seconds = std::env::var(IDLE_TIMEOUT_ENV).ok().and_then(|s| s.trim().parse::<f64>().ok()).filter(|s| s.is_finite() && *s > 0.0);
    Duration::from_secs_f64(seconds.unwrap_or(SERVER_TIMEOUT))
}

impl App {
    pub fn new(tool: Box<dyn Tool>) -> App {
        let mut routes = tool.routes();
        routes.push(Route::exact("/keep_alive", Target::KeepAlive));
        routes.push(Route::custom("/login/(.*)", |p| p.strip_prefix("/login/").map(|r| vec![r.to_string()]), Target::Login));
        App {
            cookie_id: tool.cookie_id(),
            main_page: tool.main_page(),
            localdata_dir: tool.localdata_dir(),
            tool: Mutex::new(tool),
            routes,
            access_token: new_token(),
            activity: Mutex::new(None),
            timeout: idle_timeout(),
            launch_file: Mutex::new(None),
        }
    }

    /// An app with a known access token: the fuzz targets (src/fuzz.rs) log in with it.
    #[doc(hidden)]
    pub fn with_token(tool: Box<dyn Tool>, token: &str) -> App {
        App { access_token: token.to_string(), ..App::new(tool) }
    }

    fn reset_timeout(&self, start: bool) {
        let mut activity = self.activity.lock().unwrap_or_else(|e| e.into_inner());
        if activity.is_some() || start {
            *activity = Some(Instant::now());
        }
    }

    fn current_user(&self, request: &Request) -> Result<bool, HttpError> {
        let header = request.header("Cookie").unwrap_or("");
        match get_cookie(header, self.cookie_id) {
            Some(token) if !token.is_empty() => compare_token(&token, &self.access_token),
            _ => Ok(false),
        }
    }

    fn authenticated(&self, request: &Request) -> Result<(), HttpError> {
        if self.current_user(request)? {
            Ok(())
        } else {
            Err(HttpError::status(403))
        }
    }

    /// LoginHandler.login
    fn login(&self, request: &Request, page_name: &str) -> HandlerResult {
        let token = request.get_argument("token", "");
        let mut response = Response::new();
        if compare_token(&token, &self.access_token)? {
            response.set_cookie(self.cookie_id, &token);
            let page = if page_name == "user_phrase_editor" { page_name } else { self.main_page };
            response.redirect(&format!("/{}.html?v={}", page, &token[..8.min(token.len())]));
        }
        Ok(response)
    }

    /// BaseHandler.prepare: loopback Host only, then the idle timer restarts
    fn prepare(&self, request: &Request) -> Result<(), HttpError> {
        let host_header = request.header("Host").unwrap_or("");
        let host = match host_header.rfind(':') {
            Some(i) => &host_header[..i],
            None => host_header,
        };
        let host = host.trim_matches(|c| c == '[' || c == ']').to_lowercase();
        if !["127.0.0.1", "localhost", "::1"].contains(&host.as_str()) {
            return Err(HttpError::status(403));
        }
        self.reset_timeout(false);
        Ok(())
    }

    fn route_and_handle(&self, request: &Request) -> HandlerResult {
        let (route, groups) = self
            .routes
            .iter()
            .find_map(|r| (r.matcher)(&request.path).map(|g| (r, g)))
            .ok_or(HttpError::status(404))?;
        let mut tool = self.tool.lock().unwrap_or_else(|e| e.into_inner());
        self.prepare(request)?;
        let method = request.method.as_str();
        match &route.target {
            Target::Static(root) => {
                if method != "GET" {
                    return Err(HttpError::status(405));
                }
                serve_static(root, &groups[0])
            }
            Target::KeepAlive => {
                if method != "GET" {
                    return Err(HttpError::status(405));
                }
                // the keep-alive itself happened in prepare()
                self.authenticated(request)?;
                let mut response = Response::new();
                response.write(br#"{"return":true}"#);
                Ok(response)
            }
            Target::Login => self.login(request, &groups[0]),
            Target::Api(name) => {
                self.authenticated(request)?;
                tool.handle(name, method, request)
            }
        }
    }

    /// ConfigServerApp.dispatch after the body was read
    fn dispatch(&self, request: &Request) -> Response {
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| self.route_and_handle(request)))
            .unwrap_or_else(|_| Err(HttpError::Internal("panic".into())));
        match result {
            Ok(response) => response,
            Err(err) => {
                let (status, reason) = match err {
                    HttpError::Status(code, reason) => (code, reason),
                    HttpError::Internal(message) => {
                        // never the details (they contain the install path) to the browser
                        log(&format!("ERROR: {} {}: {}", request.method, request.path, message));
                        (500, None)
                    }
                };
                let mut response = Response { status, reason, ..Response::default() };
                response.set_header("Content-Type", "text/html; charset=UTF-8");
                response.write(format!("<html><title>{0}</title><body>{0}</body></html>", status).as_bytes());
                response
            }
        }
    }

    fn respond(stream: &mut impl Write, response: &Response, http09: bool) -> std::io::Result<()> {
        let mut out = Vec::new();
        if !http09 {
            out.extend_from_slice(status_line(response.status, response.reason.as_deref()).as_bytes());
            out.extend_from_slice(format!("Server: {}\r\nDate: {}\r\n", SERVER_HEADER, http_date()).as_bytes());
            for (name, value) in &response.headers {
                out.extend_from_slice(format!("{}: {}\r\n", name, value).as_bytes());
            }
            for cookie in &response.cookies {
                out.extend_from_slice(format!("Set-Cookie: {}\r\n", cookie).as_bytes());
            }
            out.extend_from_slice(b"X-Content-Type-Options: nosniff\r\n");
            out.extend_from_slice(format!("Content-Length: {}\r\n\r\n", response.body.len()).as_bytes());
        }
        out.extend_from_slice(&response.body);
        stream.write_all(&out)?;
        stream.flush()
    }

    /// One connection: requests until it closes (HTTP/1.1 keep-alive).
    fn serve_connection(self: &Arc<Self>, stream: TcpStream) {
        let _ = stream.set_read_timeout(Some(CONNECTION_TIMEOUT));
        let _ = stream.set_nodelay(true);
        let Ok(read_half) = stream.try_clone() else { return };
        let mut reader = BufReader::new(read_half);
        let mut stream = stream;
        loop {
            match self.handle_one_request(&mut reader, &mut stream) {
                Ok(true) => continue,
                _ => break,
            }
        }
        let _ = stream.shutdown(std::net::Shutdown::Both);
    }

    /// handle_one_request: Ok(true) to keep the connection open
    pub fn handle_one_request(&self, reader: &mut impl BufRead, stream: &mut impl Write) -> std::io::Result<bool> {
        let raw = read_line(reader, MAX_LINE + 1)?;
        if raw.is_empty() {
            return Ok(false);
        }
        if raw.len() > MAX_LINE {
            send_error(stream, 414, None, false);
            return Ok(false);
        }
        let line: String = raw.iter().map(|&b| b as char).collect();
        let line = line.trim_end_matches(['\r', '\n']);
        let words: Vec<&str> = line.split_whitespace().collect();
        if words.is_empty() {
            return Ok(false);
        }
        let mut close = true;
        let mut http09 = false;
        let mut version_11 = false;
        if words.len() >= 3 {
            let version = words[words.len() - 1];
            let parsed = version.strip_prefix("HTTP/").and_then(|v| {
                let (major, minor) = v.split_once('.')?;
                let ok = |s: &str| !s.is_empty() && s.len() <= 10 && s.chars().all(|c| c.is_ascii_digit());
                (ok(major) && ok(minor) && !v[major.len() + 1..].contains('.')).then(|| (major.parse::<u64>().unwrap_or(0), minor.parse::<u64>().unwrap_or(0)))
            });
            let Some(version) = parsed else {
                send_error(stream, 400, Some(&format!("Bad request version ({})", py_repr(version))), false);
                return Ok(false);
            };
            if version >= (1, 1) {
                version_11 = true;
                close = false;
            }
            if version >= (2, 0) {
                send_error(stream, 505, Some(&format!("Invalid HTTP version ({}.{})", version.0, version.1)), false);
                return Ok(false);
            }
        }
        if !(2..=3).contains(&words.len()) {
            send_error(stream, 400, Some(&format!("Bad request syntax ({})", py_repr(line))), false);
            return Ok(false);
        }
        let (method, mut target) = (words[0].to_string(), words[1].to_string());
        if words.len() == 2 {
            close = true;
            http09 = true;
            if method != "GET" {
                send_error(stream, 400, Some(&format!("Bad HTTP/0.9 request type ({})", py_repr(&method))), true);
                return Ok(false);
            }
        }
        if target.starts_with("//") {
            target = format!("/{}", target.trim_start_matches('/'));
        }

        // headers
        let mut headers: Vec<(String, String)> = Vec::new();
        loop {
            let raw = read_line(reader, MAX_LINE + 1)?;
            if raw.len() > MAX_LINE {
                send_error(stream, 431, Some("Line too long"), http09);
                return Ok(false);
            }
            if raw.is_empty() || raw == b"\r\n" || raw == b"\n" {
                break;
            }
            let text: String = raw.iter().map(|&b| b as char).collect();
            let text = text.trim_end_matches(['\r', '\n']);
            if text.starts_with([' ', '\t']) {
                if let Some(last) = headers.last_mut() {
                    last.1.push(' ');
                    last.1.push_str(text.trim());
                }
            } else if let Some((name, value)) = text.split_once(':') {
                headers.push((name.to_string(), value.trim().to_string()));
            }
            if headers.len() > MAX_HEADERS {
                send_error(stream, 431, Some("Too many headers"), http09);
                return Ok(false);
            }
        }
        let header = |name: &str| headers.iter().find(|(k, _)| k.eq_ignore_ascii_case(name)).map(|(_, v)| v.clone());
        match header("Connection").map(|c| c.to_lowercase()) {
            Some(c) if c == "close" => close = true,
            Some(c) if c == "keep-alive" => close = false,
            _ => {}
        }
        if version_11 && header("Expect").is_some_and(|e| e.eq_ignore_ascii_case("100-continue")) {
            stream.write_all(b"HTTP/1.1 100 Continue\r\n\r\n")?;
            stream.flush()?;
        }
        if method != "GET" && method != "POST" {
            send_error(stream, 501, Some(&format!("Unsupported method ({})", py_repr(&method))), http09);
            return Ok(false);
        }

        // body (ConfigServerApp._read_body)
        let body_error = if header("Transfer-Encoding").is_some_and(|t| !t.is_empty()) {
            Some(411)
        } else {
            match header("Content-Length").filter(|s| !s.is_empty()) {
                None => None,
                Some(s) => match crate::config::py_int_from_str(&s) {
                    Some(n) if n < 0 => Some(400),
                    Some(n) if n as u64 > MAX_BODY_SIZE => Some(413),
                    Some(_) => None,
                    // beyond i64 but a number: too large
                    None if s.trim().trim_start_matches('+').chars().all(|c| c.is_ascii_digit() || c == '_') && !s.trim().is_empty() => Some(413),
                    None => Some(400),
                },
            }
        };
        let (path, query) = split_target(&target);
        let mut request = Request { method, path, query, headers, body: Vec::new() };
        if let Some(code) = body_error {
            let mut response = Response { status: code, ..Response::default() };
            response.set_header("Content-Type", "text/html; charset=UTF-8");
            response.write(format!("<html><title>{0}</title><body>{0}</body></html>", code).as_bytes());
            Self::respond(stream, &response, http09)?;
            return Ok(false); // the body was not read: the connection cannot go on
        }
        let length = request.header("Content-Length").and_then(crate::config::py_int_from_str).unwrap_or(0) as usize;
        if length > 0 {
            let mut body = vec![0u8; length];
            if let Err(e) = reader.read_exact(&mut body) {
                log(&format!("ERROR: reading the request body: {}", e));
                return Ok(false);
            }
            request.body = body;
        }
        let response = self.dispatch(&request);
        Self::respond(stream, &response, http09)?;
        Ok(!close)
    }

    // --- browser login ----------------------------------------------------------

    fn launch_file_path(&self, tool_name: &str) -> PathBuf {
        self.localdata_dir.join(format!("launch_{}.html", tool_name))
    }

    /// launch_browser: open the login URL; if that fails, a local page that
    /// POSTs the token (launch_<tool>.html)
    fn launch_browser(&self, port: u16, tool_name: &str) {
        let url = format!("http://127.0.0.1:{}/login/{}?token={}", port, tool_name, self.access_token);
        if startfile(&url).is_ok() {
            return;
        }
        let html = format!(
            "<html>\n    <form id=\"auth\" action=\"http://127.0.0.1:{port}/login/{page}\" method=\"POST\">\n        <input type=\"hidden\" name=\"token\" value=\"{token}\">\n    </form>\n    <script type=\"text/javascript\">\n        document.getElementById(\"auth\").submit();\n    </script>\n    </html>",
            port = port,
            page = tool_name,
            token = self.access_token
        );
        let filename = self.launch_file_path(tool_name);
        let written = std::fs::create_dir_all(&self.localdata_dir)
            .and_then(|_| std::fs::write(&filename, html.replace('\n', "\r\n")));
        if let Err(e) = written {
            log(&format!("ERROR: cannot write {}: {}", filename.display(), e));
            return;
        }
        *self.launch_file.lock().unwrap_or_else(|e| e.into_inner()) = Some(filename.clone());
        let _ = startfile(&filename.to_string_lossy());
    }

    fn exit(&self) -> ! {
        // wait for a request in progress (it may be writing a file)
        let _tool = self.tool.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(file) = self.launch_file.lock().unwrap_or_else(|e| e.into_inner()).take() {
            let _ = std::fs::remove_file(file);
        }
        std::process::exit(0)
    }

    /// ConfigServerApp.run(tool_name): listen, open the browser, serve until idle
    pub fn run(self, tool_name: &str) -> ! {
        let app = Arc::new(self);
        let listener = match listen_exclusive() {
            Ok(l) => l,
            Err(e) => {
                log(&format!("ERROR: cannot listen on 127.0.0.1: {}", e));
                std::process::exit(1);
            }
        };
        let port = listener.local_addr().map(|a| a.port()).unwrap_or(0);
        app.launch_browser(port, tool_name);
        app.reset_timeout(true);
        {
            let app = Arc::clone(&app);
            std::thread::spawn(move || loop {
                std::thread::sleep(Duration::from_millis(100).min(app.timeout / 4));
                let last = *app.activity.lock().unwrap_or_else(|e| e.into_inner());
                if last.is_some_and(|t| t.elapsed() >= app.timeout) {
                    app.exit();
                }
            });
        }
        for stream in listener.incoming() {
            match stream {
                Ok(stream) => {
                    let app = Arc::clone(&app);
                    std::thread::spawn(move || app.serve_connection(stream));
                }
                Err(e) => log(&format!("ERROR: accept: {}", e)),
            }
        }
        app.exit()
    }
}

fn py_repr(s: &str) -> String {
    format!("'{}'", s.replace('\\', "\\\\").replace('\'', "\\'"))
}

/// rfile.readline(limit): up to and including "\n", at most `limit` bytes
fn read_line(reader: &mut impl BufRead, limit: usize) -> std::io::Result<Vec<u8>> {
    let mut line = Vec::new();
    loop {
        let available = match reader.fill_buf() {
            Ok(buf) => buf,
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        };
        if available.is_empty() {
            return Ok(line);
        }
        let room = limit - line.len();
        let take = available.len().min(room);
        match available[..take].iter().position(|&b| b == b'\n') {
            Some(i) => {
                line.extend_from_slice(&available[..=i]);
                reader.consume(i + 1);
                return Ok(line);
            }
            None => {
                line.extend_from_slice(&available[..take]);
                reader.consume(take);
                if line.len() >= limit {
                    return Ok(line);
                }
            }
        }
    }
}

/// os.startfile(target): ShellExecuteW(NULL, NULL, target, ...), an error when
/// it returns <= 32. With WIME_CONFIG_TEST_LAUNCH the target is printed instead.
fn startfile(target: &str) -> Result<(), ()> {
    match std::env::var(TEST_LAUNCH_ENV).ok().as_deref() {
        Some("print") => {
            println!("URL {}", target);
            let _ = std::io::stdout().flush();
            return Ok(());
        }
        Some("fail-url") => {
            if target.starts_with("http:") {
                return Err(());
            }
            println!("URL {}", target);
            let _ = std::io::stdout().flush();
            return Ok(());
        }
        _ => {}
    }
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;
    let wide: Vec<u16> = target.encode_utf16().chain(std::iter::once(0)).collect();
    let result = unsafe {
        ShellExecuteW(std::ptr::null_mut(), std::ptr::null(), wide.as_ptr(), std::ptr::null(), std::ptr::null(), SW_SHOWNORMAL)
    };
    if result as isize > 32 {
        Ok(())
    } else {
        Err(())
    }
}

/// A listening socket on 127.0.0.1, random port, SO_EXCLUSIVEADDRUSE (with
/// SO_REUSEADDR another program could bind the same port and take connections),
/// not inherited by the browser we start.
fn listen_exclusive() -> std::io::Result<TcpListener> {
    use std::os::windows::io::FromRawSocket;
    use windows_sys::Win32::Networking::WinSock::*;
    unsafe {
        let mut data: WSADATA = std::mem::zeroed();
        if WSAStartup(0x0202, &mut data) != 0 {
            return Err(std::io::Error::last_os_error());
        }
        let s = WSASocketW(AF_INET as i32, SOCK_STREAM, IPPROTO_TCP, std::ptr::null(), 0, WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT);
        if s == INVALID_SOCKET {
            return Err(std::io::Error::from_raw_os_error(WSAGetLastError()));
        }
        let fail = |s: SOCKET| {
            let err = std::io::Error::from_raw_os_error(WSAGetLastError());
            closesocket(s);
            Err(err)
        };
        let one: i32 = 1;
        if setsockopt(s, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, &one as *const i32 as *const u8, std::mem::size_of::<i32>() as i32) != 0 {
            return fail(s);
        }
        let mut addr: SOCKADDR_IN = std::mem::zeroed();
        addr.sin_family = AF_INET;
        addr.sin_port = 0;
        addr.sin_addr.S_un.S_addr = u32::from_ne_bytes([127, 0, 0, 1]);
        if bind(s, &addr as *const SOCKADDR_IN as *const SOCKADDR, std::mem::size_of::<SOCKADDR_IN>() as i32) != 0 {
            return fail(s);
        }
        // socketserver.TCPServer.request_queue_size
        if listen(s, 5) != 0 {
            return fail(s);
        }
        Ok(TcpListener::from_raw_socket(s as _))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cookie_parsing_follows_simple_cookie() {
        assert_eq!(get_cookie("a=1; tok=abc", "tok").as_deref(), Some("abc"));
        assert_eq!(get_cookie("tok=abc; tok=def", "tok").as_deref(), Some("def"));
        assert_eq!(get_cookie("tok=\"a\\\"b\"", "tok").as_deref(), Some("a\"b"));
        assert_eq!(get_cookie("tok=abc; Path=/; HttpOnly", "tok").as_deref(), Some("abc"));
        // an invalid cookie string: nothing is applied
        assert_eq!(get_cookie("junk; tok=abc", "tok"), None);
        assert_eq!(get_cookie("Path=/; tok=abc", "tok"), None);
        // parsing stops at an illegal character, keeping what came before
        assert_eq!(get_cookie("tok=abc; x=\u{e9}", "tok").as_deref(), Some("abc"));
        assert_eq!(get_cookie("", "tok"), None);
    }

    #[test]
    fn unquote_and_query_strings() {
        assert_eq!(unquote("a%2Fb%E6%B8%AC"), "a/b測");
        assert_eq!(unquote("%zz%4"), "%zz%4");
        assert_eq!(unquote("%E6%B8"), "\u{fffd}");
        assert_eq!(parse_qsl("token=abc&x&token=&y=1+2"), vec![
            ("token".to_string(), "abc".to_string()),
            ("x".to_string(), String::new()),
            ("token".to_string(), String::new()),
            ("y".to_string(), "1 2".to_string()),
        ]);
        assert_eq!(split_target("/login/config?token=1#x"), ("/login/config".to_string(), "token=1".to_string()));
        assert_eq!(split_target("http://127.0.0.1:5/config?a"), ("/config".to_string(), "a".to_string()));
    }

    #[test]
    fn routes_match_like_the_python_regexes() {
        let html = Route::suffix(r"/(.*\.html)", ".html", Target::Api("x"));
        assert_eq!((html.matcher)("/config.html"), Some(vec!["config.html".to_string()]));
        assert_eq!((html.matcher)("/login/a.html"), Some(vec!["login/a.html".to_string()]));
        assert_eq!((html.matcher)("/config.htm"), None);
        let version = Route::exact_dot(r"/(version.txt)", "version.txt", Target::Api("x"));
        assert!((version.matcher)("/versionXtxt").is_some());
        assert!((version.matcher)("/version.txt2").is_none());
        let dirs = Route::dirs(r"/((css|js)/.*)", &["css", "js"], Target::Api("x"));
        assert_eq!((dirs.matcher)("/css/a.css"), Some(vec!["css/a.css".to_string(), "css".to_string()]));
        assert!((dirs.matcher)("/cssx/a.css").is_none());
        assert!((dirs.matcher)("/css").is_none());
    }

    #[test]
    fn tokens_are_uuid4_hex() {
        let t = new_token();
        assert_eq!(t.len(), 32);
        assert!(t.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
        assert_eq!(&t[12..13], "4");
        assert_ne!(t, new_token());
        assert!(constant_time_eq(&t, &t.clone()));
        assert!(!constant_time_eq(&t, &t[..31]));
        assert!(compare_token("\u{e9}", &t).is_err());
    }

    #[test]
    fn http_date_format() {
        let d = http_date();
        assert!(d.ends_with(" GMT") && d.len() == 29, "{}", d);
    }

    #[test]
    fn extensions_like_splitext() {
        assert_eq!(extension(Path::new(r"C:\a\b.HTML")), ".html");
        assert_eq!(extension(Path::new(r"C:\a\.htaccess")), "");
        assert_eq!(extension(Path::new(r"C:\a\b")), "");
    }
}
