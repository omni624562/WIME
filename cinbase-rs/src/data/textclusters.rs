//! textclusters.py: split the contents of a symbol file line into "symbols"
//! (not full grapheme segmentation: variation selectors, skin tones, ZWJ
//! sequences, keycaps, flags and combining marks join the previous symbol).

use super::marks::is_mark;

const ZWJ: u32 = 0x200D;

fn is_extender(ch: char) -> bool {
    let cp = ch as u32;
    (0xFE00..=0xFE0F).contains(&cp)
        || (0xE0100..=0xE01EF).contains(&cp)
        || (0x1F3FB..=0x1F3FF).contains(&cp)
        || (0xE0020..=0xE007F).contains(&cp)
        || is_mark(ch)
}

fn is_regional_indicator(ch: char) -> bool {
    (0x1F1E6..=0x1F1FF).contains(&(ch as u32))
}

/// symbolClusters(text)
pub fn symbol_clusters(text: &str) -> Vec<String> {
    let mut clusters: Vec<String> = Vec::new();
    let mut join_next = false;
    for ch in text.chars() {
        if !clusters.is_empty() && (join_next || ch as u32 == ZWJ || is_extender(ch)) {
            clusters.last_mut().unwrap().push(ch);
            join_next = ch as u32 == ZWJ;
        } else if is_regional_indicator(ch) && clusters.last().is_some_and(|last| {
            let mut it = last.chars();
            matches!((it.next(), it.next()), (Some(c), None) if is_regional_indicator(c))
        }) {
            clusters.last_mut().unwrap().push(ch);
            join_next = false;
        } else {
            clusters.push(ch.to_string());
            join_next = false;
        }
    }
    clusters
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clusters() {
        assert_eq!(symbol_clusters("❤\u{fe0f}a"), vec!["❤\u{fe0f}", "a"]);
        assert_eq!(symbol_clusters("🇹🇼🇯🇵🇺"), vec!["🇹🇼", "🇯🇵", "🇺"]);
        assert_eq!(symbol_clusters("👨\u{200d}👩\u{200d}👧x"), vec!["👨\u{200d}👩\u{200d}👧", "x"]);
        assert_eq!(symbol_clusters("\u{fe0f}1\u{fe0f}\u{20e3}"), vec!["\u{fe0f}", "1\u{fe0f}\u{20e3}"]);
        assert_eq!(symbol_clusters(""), Vec::<String>::new());
    }
}
