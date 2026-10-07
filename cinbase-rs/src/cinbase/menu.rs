//! Port of python/cinbase/menu.py: the ``` function menu tree and its
//! navigation path (menupathlist, shown as the "選單 路徑 › 子頁" header).

use super::CbTs;

pub const BACK_ITEM: &str = "↩ 返回";

pub const MAIN_MENU: &[(&str, &str)] = &[
    ("symbols", "特殊符號"),
    ("emoji", "表情符號"),
    ("bopomofo", "注音符號"),
    ("flangs", "外語文字"),
    ("toggles", "功能開關"),
    ("settings", "開啟設定視窗…"),
];

pub const TOGGLES_PAGE_TITLE: &str = "功能開關（暫時，只影響這個程式）";

/// attribute -> label
pub const TOGGLE_DEFS: &[(&str, &str)] = &[
    ("fullShapeSymbols", "Shift 輸入全形標點"),
    ("easySymbolsWithShift", "Shift 快速輸入符號"),
    ("playSoundWhenNonCand", "拆錯字碼時發出警告嗶聲提示"),
    ("showPhrase", "輸出字串後顯示聯想字詞"),
    ("sortByPhrase", "優先以聯想字詞排序候選清單"),
    ("intelligentSelect", "智慧選字（依前一字排序）"),
    ("intelligentSelectRecent", "智慧選字：前一字相同時近期優先"),
    ("intelligentSelectContext", "智慧選字：參考前一字"),
    ("supportWildcard", "萬用字元查詢"),
    ("imeReverseLookup", "反查輸入字根"),
    ("homophoneQuery", "同音字查詢"),
];

const DEFAULT_TOGGLES: &[&str] =
    &["fullShapeSymbols", "easySymbolsWithShift", "playSoundWhenNonCand", "showPhrase", "sortByPhrase", "supportWildcard", "imeReverseLookup", "homophoneQuery"];

pub fn main_menu_labels() -> Vec<String> {
    MAIN_MENU.iter().map(|(_, label)| label.to_string()).collect()
}

/// mainMenuId(label): None for an unknown label
pub fn main_menu_id(label: &str) -> Option<&'static str> {
    MAIN_MENU.iter().find(|(_, l)| *l == label).map(|(id, _)| *id)
}

/// toggleAttrsFor(imeDirName)
pub fn toggle_attrs_for(ime_dir_name: &str) -> Vec<String> {
    let list: Vec<&str> = match ime_dir_name {
        "chephonetic" => vec!["fullShapeSymbols", "easySymbolsWithShift", "playSoundWhenNonCand", "showPhrase", "sortByPhrase", "imeReverseLookup", "homophoneQuery"],
        "cheez" => vec!["playSoundWhenNonCand", "showPhrase", "sortByPhrase", "supportWildcard", "imeReverseLookup"],
        "chearray" | "chedayi" => TOGGLE_DEFS.iter().map(|(a, _)| *a).collect(),
        _ => DEFAULT_TOGGLES.to_vec(),
    };
    list.into_iter().map(String::from).collect()
}

fn toggle_label(attr: &str) -> &'static str {
    TOGGLE_DEFS.iter().find(|(a, _)| *a == attr).map(|(_, l)| *l).unwrap_or("")
}

/// toggleIndex(labels, itemName): compare the text after the ☑/☐ mark.
pub fn toggle_index(labels: &[String], item_name: &str) -> Option<usize> {
    let name: String = item_name.chars().skip(2).collect();
    labels.iter().position(|l| l.chars().skip(2).collect::<String>() == name)
}

/// withBack(items): sub pages start with "↩ 返回".
pub fn with_back(items: &[String]) -> Vec<String> {
    let mut out = vec![BACK_ITEM.to_string()];
    out.extend(items.iter().cloned());
    out
}

impl CbTs {
    /// getattr(cbTS, attr, False) for the function-menu toggles
    pub fn toggle_value(&self, attr: &str) -> bool {
        match attr {
            "fullShapeSymbols" => self.full_shape_symbols,
            "easySymbolsWithShift" => self.easy_symbols_with_shift,
            "playSoundWhenNonCand" => self.play_sound_when_non_cand,
            "showPhrase" => self.show_phrase,
            "sortByPhrase" => self.sort_by_phrase,
            "intelligentSelect" => self.intelligent_select,
            "intelligentSelectRecent" => self.intelligent_select_recent,
            "intelligentSelectContext" => self.intelligent_select_context,
            "supportWildcard" => self.support_wildcard,
            "imeReverseLookup" => self.ime_reverse_lookup,
            "homophoneQuery" => self.homophone_query,
            _ => false,
        }
    }

    /// homophoneKeyIsRoot: ` is a root of the current table (大易三碼's 巷)
    pub fn homophone_key_is_root(&self) -> bool {
        match &self.cin {
            Some(cin) => cin.borrow().is_in_key_name("`"),
            None => false,
        }
    }

    /// buildToggleItems: (labels with ☑/☐, attributes)
    pub fn build_toggle_items(&self) -> (Vec<String>, Vec<String>) {
        let mut attrs = toggle_attrs_for(&self.ime_dir_name);
        if attrs.iter().any(|a| a == "homophoneQuery") && self.homophone_key_is_root() {
            if let Some(pos) = attrs.iter().position(|a| a == "homophoneQuery") {
                attrs.remove(pos);
            }
        }
        let labels = attrs
            .iter()
            .map(|attr| format!("{} {}", if self.toggle_value(attr) { "☑" } else { "☐" }, toggle_label(attr)))
            .collect();
        (labels, attrs)
    }

    /// menu.resetPath
    pub fn menu_reset_path(&mut self) {
        self.menupathlist = Vec::new();
    }

    /// menu.pushPath
    pub fn menu_push_path(&mut self, name: &str) {
        self.menupathlist.push(name.to_string());
    }

    /// menu.popPath
    pub fn menu_pop_path(&mut self) {
        self.menupathlist.pop();
    }

    /// menu.headerText
    pub fn menu_header_text(&self) -> String {
        let path = if self.menupathlist.is_empty() { "功能選單".to_string() } else { self.menupathlist.join(" › ") };
        format!("選單 {}", path)
    }
}
