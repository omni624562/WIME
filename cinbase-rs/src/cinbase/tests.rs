//! Unit checks of the Python-semantics helpers; behaviour as a whole is
//! checked against the Python backend by tests/diffharness.

use super::*;

fn blank() -> CbTs {
    CbTs::blank(ClientInfo::default(), "chedayi", 4, CHEDAYI_CIN_FILE_LIST, SharedTables::default())
}

#[test]
fn unicode_input_code_point_like_python() {
    assert_eq!(CbTs::unicode_input_code_point("4e00"), Some(0x4e00));
    assert_eq!(CbTs::unicode_input_code_point("0x41"), Some(0x41));
    assert_eq!(CbTs::unicode_input_code_point("1_0000"), Some(0x10000));
    assert_eq!(CbTs::unicode_input_code_point("1F"), None);
    assert_eq!(CbTs::unicode_input_code_point("7F"), None);
    assert_eq!(CbTs::unicode_input_code_point("D800"), None);
    assert_eq!(CbTs::unicode_input_code_point("110000"), None);
    assert_eq!(CbTs::unicode_input_code_point(""), None);
    assert_eq!(CbTs::unicode_input_code_point("xyz"), None);
}

#[test]
fn composition_buffer_insert_and_remove() {
    let mut st = blank();
    st.composition_buffer_string = "abc".into();
    st.composition_buffer_cursor = 1;
    st.buffer_insert_string("X", 0);
    assert_eq!(st.composition_buffer_string, "aXbc");
    assert_eq!(st.composition_buffer_cursor, 2);
    st.composition_buffer_cursor = 4;
    st.buffer_insert_string("大易", 1);
    assert_eq!(st.composition_buffer_string, "aXb大易");
    assert_eq!(st.composition_buffer_cursor, 5);
    st.composition_buffer_cursor = 2;
    st.buffer_remove_string(5, true);
    assert_eq!(st.composition_buffer_string, "b大易");
    assert_eq!(st.composition_buffer_cursor, 0);
    st.buffer_remove_string(1, false);
    assert_eq!(st.composition_buffer_string, "大易");
    assert_eq!(st.ts.current_reply["compositionString"], json!("大易"));
}

#[test]
fn composition_buffer_char_records_shift() {
    let mut st = blank();
    st.buffer_record_char("default", "a", 1);
    st.buffer_record_char("default", "b", 2);
    st.buffer_record_char("english", "x", 1);
    let keys: Vec<i64> = st.composition_buffer_char.keys().copied().collect();
    assert_eq!(keys, vec![2, 1, 0]);
    assert_eq!(st.composition_buffer_char[&0].1, "x");
    assert_eq!(st.composition_buffer_char[&1].1, "a");
    assert_eq!(st.composition_buffer_char[&2].1, "b");
    st.buffer_drop_char_at(0);
    assert_eq!(st.composition_buffer_char[&0].1, "a");
    assert_eq!(st.composition_buffer_char[&1].1, "b");
}

#[test]
fn sel_keys_sent_only_on_change() {
    let mut st = blank();
    st.init_sel_keys();
    assert_eq!(st.ts.current_reply["setSelKeys"], json!("1234567890"));
    st.ts.current_reply.clear();
    assert!(!st.apply_default_sel_keys());
    assert!(st.ts.current_reply.is_empty());
    assert!(st.apply_dayi_sel_keys());
    assert_eq!(st.ts.current_reply["setSelKeys"], json!("␣'[]-\\"));
    assert_eq!(st.sel_keys, "'[]-\\");
    assert!(st.is_sel_keys_changed);
}

#[test]
fn menu_helpers() {
    let mut st = blank();
    assert_eq!(st.menu_header_text(), "選單 功能選單");
    st.menu_push_path("特殊符號");
    st.menu_push_path("箭頭");
    assert_eq!(st.menu_header_text(), "選單 特殊符號 › 箭頭");
    let (labels, attrs) = st.build_toggle_items();
    assert_eq!(attrs.len(), 11);
    assert_eq!(labels[0], "☐ Shift 輸入全形標點");
    assert_eq!(menu::toggle_index(&labels, "☑ Shift 快速輸入符號"), Some(1));
    assert_eq!(menu::main_menu_id("開啟設定視窗…"), Some("settings"));
}
