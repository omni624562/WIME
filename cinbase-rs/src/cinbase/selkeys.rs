//! Port of python/cinbase/selkeys.py: the only owner of the selection-key
//! state. "The last selection keys sent" is per client (cand_sel_keys).

use super::CbTs;

pub const DEFAULT_SELKEYS: &str = "1234567890";
/// 大易: Space picks the 1st candidate, '[]-\ the 2nd..6th
pub const DAYI_DISPLAY_SELKEYS: &str = "'[]-\\";
pub const DAYI_CAND_SELKEYS: &str = "␣'[]-\\";

impl CbTs {
    /// initSelKeys: when the client is created, set the cache and send the
    /// default selection keys.
    pub fn init_sel_keys(&mut self) {
        self.cand_sel_keys = DEFAULT_SELKEYS.to_string();
        let keys = self.cand_sel_keys.clone();
        self.ts.set_sel_keys(&keys);
    }

    /// applySelKeys: switch the keys; setSelKeys only when they change.
    /// Returns whether setSelKeys was sent.
    pub fn apply_sel_keys(&mut self, display_keys: &str, cand_sel_keys: &str) -> bool {
        self.sel_keys = display_keys.to_string();
        if self.cand_sel_keys == cand_sel_keys {
            return false;
        }
        self.cand_sel_keys = cand_sel_keys.to_string();
        self.ts.set_sel_keys(cand_sel_keys);
        self.is_sel_keys_changed = true;
        true
    }

    pub fn apply_default_sel_keys(&mut self) -> bool {
        self.apply_sel_keys(DEFAULT_SELKEYS, DEFAULT_SELKEYS)
    }

    pub fn apply_dayi_sel_keys(&mut self) -> bool {
        self.apply_sel_keys(DAYI_DISPLAY_SELKEYS, DAYI_CAND_SELKEYS)
    }
}
