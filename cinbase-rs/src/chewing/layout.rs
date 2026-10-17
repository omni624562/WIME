//! Port of python/candidate_layout.py (CL:<line>): how many candidates the
//! candidate window really puts in one row (libIME2 CandidateWindow's column
//! count), measured with GDI and the candidate window's font, like the C++.
//!
//! Test mode (tests/diffharness): fonts and DPI differ between machines, so the
//! harness replaces the measurement on both backends with one model --
//! DPI 96, a code point >= U+1100 one em (MulDiv(fontSize, 96, 72) px) wide,
//! anything else half an em (py_reference_backend.py test_measure_texts).
//! WIME_TEST_GDI=1 keeps the real GDI measurement (at DPI 96) in test mode.

use crate::env;
use std::collections::HashMap;

/// CL:20 FONT_NAME: the candFontName 新酷音 sends
pub const FONT_NAME: &str = "Microsoft JhengHei";
const DEFAULT_GUI_FONT: i32 = 17;
const FW_NORMAL: i32 = 400;

/// Python's a // b (b != 0)
fn floor_div(a: i64, b: i64) -> i64 {
    let q = a / b;
    if (a % b != 0) && ((a < 0) != (b < 0)) {
        q - 1
    } else {
        q
    }
}

/// CL:45 mulDiv()
pub fn mul_div(value: i64, numerator: i64, denominator: i64) -> i64 {
    floor_div(value * numerator + denominator / 2, denominator)
}

fn test_measure() -> bool {
    env::test_mode() && std::env::var("WIME_TEST_GDI").map(|v| v != "1").unwrap_or(true)
}

/// CL:50 systemDpi(): the system DPI, asked with a system-aware thread context
pub fn system_dpi() -> i64 {
    if env::test_mode() {
        return 96;
    }
    use windows_sys::Win32::UI::HiDpi::{GetDpiForSystem, SetThreadDpiAwarenessContext, DPI_AWARENESS_CONTEXT_SYSTEM_AWARE};
    unsafe {
        let old = SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_SYSTEM_AWARE);
        let dpi = GetDpiForSystem();
        if !old.is_null() {
            SetThreadDpiAwarenessContext(old);
        }
        if dpi == 0 {
            96
        } else {
            dpi as i64
        }
    }
}

/// The harness model of measureTexts (see the module comment).
fn model_measure(font_size: i64, dpi: i64, texts: &[String]) -> HashMap<String, i64> {
    let em = mul_div(font_size, dpi, 72);
    texts
        .iter()
        .map(|t| (t.clone(), t.chars().map(|c| if c as u32 >= 0x1100 { em } else { floor_div(em, 2) }).sum()))
        .collect()
}

/// CL:85 measureTexts(): {text: width px}; None on failure
pub fn measure_texts(font_name: &str, font_size: i64, dpi: i64, texts: &[String]) -> Option<HashMap<String, i64>> {
    if test_measure() {
        return Some(model_measure(font_size, dpi, texts));
    }
    use windows_sys::Win32::Foundation::SIZE;
    use windows_sys::Win32::Graphics::Gdi::{
        CreateFontIndirectW, DeleteObject, GetDC, GetObjectW, GetStockObject, GetTextExtentPoint32W, ReleaseDC, SelectObject,
        LOGFONTW,
    };
    unsafe {
        let mut lf: LOGFONTW = std::mem::zeroed();
        if GetObjectW(GetStockObject(DEFAULT_GUI_FONT), std::mem::size_of::<LOGFONTW>() as i32, &mut lf as *mut _ as *mut _) == 0 {
            return None;
        }
        lf.lfHeight = -(mul_div(font_size, dpi, 72) as i32);
        lf.lfWeight = FW_NORMAL;
        // lf.lfFaceName = fontName[:31] (ctypes pads the rest with NULs)
        lf.lfFaceName = [0; 32];
        let face: Vec<u16> = font_name.chars().take(31).collect::<String>().encode_utf16().collect();
        for (i, u) in face.iter().take(31).enumerate() {
            lf.lfFaceName[i] = *u;
        }
        let font = CreateFontIndirectW(&lf);
        if font.is_null() {
            return None;
        }
        let dc = GetDC(std::ptr::null_mut());
        if dc.is_null() {
            DeleteObject(font);
            return None;
        }
        let old = SelectObject(dc, font);
        let mut widths = HashMap::new();
        let mut ok = true;
        for text in texts {
            if widths.contains_key(text) {
                continue;
            }
            let wide: Vec<u16> = text.encode_utf16().collect();
            let mut size = SIZE { cx: 0, cy: 0 };
            if GetTextExtentPoint32W(dc, wide.as_ptr(), wide.len() as i32, &mut size) == 0 {
                ok = false;
                break;
            }
            widths.insert(text.clone(), size.cx as i64);
        }
        SelectObject(dc, old);
        ReleaseDC(std::ptr::null_mut(), dc);
        DeleteObject(font);
        if ok {
            Some(widths)
        } else {
            None
        }
    }
}

/// CL:121 _keyMinWidth
fn key_min_width(key_style: &str, text_margin: i64) -> i64 {
    if key_style == "keycap" {
        (text_margin * 3 + 5).max(17)
    } else {
        0
    }
}

/// CL:125 _extraItemWidth
fn extra_item_width(key_style: &str, text_margin: i64) -> i64 {
    let text_gap = if key_style == "keycap" { 1 } else { floor_div(text_margin, 2).max(3) };
    text_margin * 2 + text_gap + floor_div(text_margin, 2).max(2)
}

/// CL:130 candidateColumns()
#[allow(clippy::too_many_arguments)]
pub fn candidate_columns(
    candidates: &[String],
    sel_keys: &str,
    per_row: i64,
    font_size: i64,
    max_width: i64,
    wrap_to_max_width: bool,
    content_margin: i64,
    text_margin: i64,
    key_style: &str,
    font_name: &str,
) -> Result<i64, String> {
    let per_row = per_row.max(1);
    if per_row == 1 || !wrap_to_max_width || max_width <= 0 || candidates.is_empty() {
        return Ok(per_row);
    }
    let dpi = system_dpi();
    let sel: Vec<char> = sel_keys.chars().collect();
    let keys: Vec<String> = (0..candidates.len().min(sel.len())).map(|i| sel[i].to_string()).collect();
    let mut texts = keys.clone();
    texts.extend(candidates.iter().cloned());
    let Some(widths) = measure_texts(font_name, font_size, dpi, &texts) else {
        return Ok(per_row);
    };
    let scale = |v: i64| if dpi == 96 { v } else { mul_div(v, dpi, 96) };
    let margin = scale(content_margin);
    let text_margin = scale(text_margin);
    let col_spacing = (text_margin + 2).max(6);
    let key_width = keys.iter().map(|k| widths[k]).chain(std::iter::once(key_min_width(key_style, text_margin))).max().unwrap_or(0);
    let text_width = candidates.iter().map(|t| widths[t]).max().unwrap_or(0);
    let stride = key_width + text_width + extra_item_width(key_style, text_margin);
    let content_limit = (scale(max_width) - margin * 2).max(1);
    if stride + col_spacing == 0 {
        return Err("ZeroDivisionError: integer division or modulo by zero".into());
    }
    Ok(floor_div(content_limit + col_spacing, stride + col_spacing).min(per_row).max(1))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mul_div_rounds_like_win32() {
        assert_eq!(mul_div(16, 96, 72), 21);
        assert_eq!(mul_div(12, 120, 72), 20);
        assert_eq!(mul_div(6, 144, 96), 9);
    }

    #[test]
    fn real_gdi_measures_wider_text_wider() {
        let texts = vec!["1".to_string(), "測試".to_string(), "測試測試".to_string()];
        if let Some(w) = measure_texts(FONT_NAME, 16, 96, &texts) {
            if !test_measure() {
                assert!(w["測試測試"] > w["測試"] && w["測試"] > w["1"]);
            }
        }
    }
}
