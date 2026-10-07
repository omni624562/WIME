//! Port of python/cinbase/compositionbuffer.py (compositionBufferMode).
//!
//! State: composition_buffer_string, composition_buffer_cursor and
//! composition_buffer_char ({string index: (type, original keys)}, used by
//! VK_DOWN to re-select). Python slicing semantics (negative bounds) are kept.

use super::pyutil::{py_len, py_slice};
use super::CbTs;

impl CbTs {
    /// insertString(text, removeStringLength): insert at the cursor after
    /// replacing the removeStringLength chars before it.
    pub fn buffer_insert_string(&mut self, text: &str, remove_string_length: i64) {
        let buf = self.composition_buffer_string.clone();
        let comp_pos1 = self.composition_buffer_cursor - remove_string_length;
        let comp_pos2 = self.composition_buffer_cursor - py_len(&buf);
        if comp_pos2 < 0 {
            self.composition_buffer_string = py_slice(&buf, None, Some(comp_pos1)) + text + &py_slice(&buf, Some(comp_pos2), None);
        } else {
            self.composition_buffer_string = py_slice(&buf, None, Some(comp_pos1)) + text;
        }
        self.composition_buffer_cursor += py_len(text) - remove_string_length;
        let s = self.composition_buffer_string.clone();
        self.ts.set_composition_string(&s);
        self.ts.set_composition_cursor(self.composition_buffer_cursor);
    }

    /// removeString(removeStringLength, removeBefore)
    pub fn buffer_remove_string(&mut self, remove_string_length: i64, remove_before: bool) {
        let buf = self.composition_buffer_string.clone();
        let len = py_len(&buf);
        let cursor = self.composition_buffer_cursor;
        let n = if remove_before {
            0.max(remove_string_length.min(cursor))
        } else {
            0.max(remove_string_length.min(len - cursor))
        };
        if remove_before {
            let comp_pos1 = cursor - n;
            let comp_pos2 = cursor - len;
            if comp_pos2 < 0 {
                self.composition_buffer_string = py_slice(&buf, None, Some(comp_pos1)) + &py_slice(&buf, Some(comp_pos2), None);
            } else {
                self.composition_buffer_string = py_slice(&buf, None, Some(comp_pos1));
            }
            self.composition_buffer_cursor -= n;
        } else {
            let comp_pos1 = cursor;
            let comp_pos2 = cursor - len + n;
            if comp_pos2 < 0 {
                self.composition_buffer_string = py_slice(&buf, None, Some(comp_pos1)) + &py_slice(&buf, Some(comp_pos2), None);
            } else {
                self.composition_buffer_string = py_slice(&buf, None, Some(comp_pos1));
            }
        }
        let s = self.composition_buffer_string.clone();
        self.ts.set_composition_string(&s);
        self.ts.set_composition_cursor(self.composition_buffer_cursor);
    }

    /// recordChar(type, keys, cursor): record the char just inserted; records
    /// at or after the insertion point move right by one.
    pub fn buffer_record_char(&mut self, composition_type: &str, composition_char: &str, composition_cursor: i64) {
        let map = &mut self.composition_buffer_char;
        if map.contains_key(&(composition_cursor - 1)) {
            let mut keys: Vec<i64> = map.keys().copied().collect();
            keys.sort_unstable_by(|a, b| b.cmp(a));
            for key in keys {
                if key >= composition_cursor - 1 {
                    let v = map.shift_remove(&key).unwrap();
                    map.insert(key + 1, v);
                }
            }
        }
        map.insert(composition_cursor - 1, (composition_type.to_string(), composition_char.to_string()));
    }

    /// dropCharAt(index): delete the record at index; later records move left.
    pub fn buffer_drop_char_at(&mut self, index: i64) {
        let map = &mut self.composition_buffer_char;
        map.shift_remove(&index);
        let mut keys: Vec<i64> = map.keys().copied().collect();
        keys.sort_unstable();
        for key in keys {
            if key > index {
                let v = map.shift_remove(&key).unwrap();
                map.insert(key - 1, v);
            }
        }
    }
}
