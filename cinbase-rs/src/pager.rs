//! Port of python/cinbase/pager.py, the only owner of candidate pagination.
//!
//! Invariant: a page never holds more candidates than there are selection
//! keys (6 for 大易, 10 otherwise).

/// maxCandPerPage(imeDirName)
pub fn max_cand_per_page(ime_dir_name: &str) -> i64 {
    if ime_dir_name == "chedayi" {
        6
    } else {
        10
    }
}

/// clampCandPerPage(candPerPage, imeDirName)
pub fn clamp_cand_per_page(cand_per_page: i64, ime_dir_name: &str) -> i64 {
    1.max(cand_per_page.min(max_cand_per_page(ime_dir_name)))
}

/// paginate(candidates, perPage): pages of at most perPage (at least 1) items.
pub fn paginate<T: Clone>(candidates: &[T], per_page: i64) -> Vec<Vec<T>> {
    let per_page = per_page.max(1) as usize;
    candidates.chunks(per_page).map(|c| c.to_vec()).collect()
}

/// pageCount(total, perPage): math.ceil(total / perPage); 0 for no candidates.
pub fn page_count(total: usize, per_page: i64) -> usize {
    let per_page = per_page.max(1) as usize;
    total.div_ceil(per_page)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    /// Expected values from python/cinbase/pager.py (tests/fixtures/pager_cases.json).
    #[test]
    fn matches_python() {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/pager_cases.json");
        let cases: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        for c in cases["max"].as_array().unwrap() {
            assert_eq!(max_cand_per_page(c[0].as_str().unwrap()), c[1].as_i64().unwrap());
        }
        for c in cases["clamp"].as_array().unwrap() {
            assert_eq!(clamp_cand_per_page(c[0].as_i64().unwrap(), c[1].as_str().unwrap()), c[2].as_i64().unwrap(), "{}", c);
        }
        for c in cases["paginate"].as_array().unwrap() {
            let items: Vec<String> = c[0].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_string()).collect();
            let got = paginate(&items, c[1].as_i64().unwrap());
            assert_eq!(serde_json::to_value(&got).unwrap(), c[2], "{}", c);
        }
        for c in cases["count"].as_array().unwrap() {
            assert_eq!(page_count(c[0].as_u64().unwrap() as usize, c[1].as_i64().unwrap()) as u64, c[2].as_u64().unwrap(), "{}", c);
        }
    }
}
