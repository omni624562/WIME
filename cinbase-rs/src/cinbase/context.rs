//! Settings and tables: python/cinbase/__init__.py CB:3615-3940
//! (initCinBaseContext, loadDataFile, customizeCandidateUI, applyConfig,
//! sharedTablesDisagree, checkConfigChange) and the loader threads
//! CB:3951-4123 (LoadPhraseData, LoadCinTable, LoadRCinTable, LoadHCinTable),
//! which run synchronously here.

use super::*;
use crate::candidate_theme::{candidate_colors_for_theme, resolve_candidate_theme};
use crate::config::RCIN_FILE_LIST;
use crate::data;
use crate::pager;
use std::path::Path;

/// CB:3672 loadDataFile(cfg, name, parser, empty): the user's file, else the
/// shipped one, else an empty table.
fn load_data_file<T>(cfg: &CinBaseConfig, name: &str, parse: fn(&str) -> Result<T, String>, empty: &str) -> T {
    let dirs = [cfg.get_config_dir(), cfg.get_data_dir()];
    data::load_data_file(&dirs, name, parse, empty)
}

impl CbTs {
    // CB:3615 initCinBaseContext
    pub fn init_cin_base_context(&mut self) -> Result<(), String> {
        if !self.init_cin_base_state {
            self.lang_mode = if self.cfg.default_english { ENGLISH_MODE } else { CHINESE_MODE };
            self.shape_mode = if self.cfg.default_full_space { FULLSHAPE_MODE } else { HALFSHAPE_MODE };
            self.update_lang_buttons();
        }

        self.sel_cin_type = self.cfg.sel_cin_type;

        self.swkb = None;
        self.symbols = None;
        self.fsymbols = None;
        self.flangs = None;
        self.userphrase = None;
        self.msymbols = None;
        self.extendtable = None;
        self.dsymbols = None;

        self.apply_config();

        // every table gets a value again (an unreadable file falls back)
        self.swkb = Some(load_data_file(&self.cfg, "swkb.dat", Swkb::parse, ""));
        self.symbols = Some(load_data_file(&self.cfg, "symbols.dat", Symbols::parse, ""));
        self.fsymbols = Some(load_data_file(&self.cfg, "fsymbols.dat", FSymbols::parse, ""));
        self.flangs = Some(load_data_file(&self.cfg, "flangs.dat", FLangs::parse, ""));
        self.userphrase = Some(load_data_file(&self.cfg, "userphrase.dat", UserPhrase::parse, ""));
        // phrases the user never wants suggested; same syntax as userphrase
        self.excludephrase = Some(load_data_file(&self.cfg, "excludephrase.dat", UserPhrase::parse, ""));
        self.msymbols = Some(load_data_file(&self.cfg, "msymbols.json", MSymbols::parse, "{}"));
        self.extendtable = Some(load_data_file(&self.cfg, "extendtable.dat", ExtendTable::parse, ""));

        if self.use_dayi_symbols {
            self.dsymbols = Some(load_data_file(&self.cfg, "dsymbols.json", DSymbols::parse, "{}"));
        }

        let (has_phrase, loading) = {
            let p = phrase_data();
            let p = p.borrow();
            (p.phrase.is_some(), p.loading)
        };
        if !has_phrase && !loading {
            self.load_phrase_data();
        }

        self.init_cin_base_state = true;
        Ok(())
    }

    // CB:3684 customizeCandidateUI(force=False): send the candidate window
    // look; without force only when it changed since the last time
    pub fn customize_candidate_ui(&mut self, force: bool) {
        let cfg = &self.cfg;
        let mut ui_args = Map::new();
        ui_args.insert("candFontSize".into(), json!(cfg.font_size));
        ui_args.insert("candFontName".into(), json!("Microsoft JhengHei"));
        ui_args.insert("candPerRow".into(), json!(self.cand_per_row));
        ui_args.insert("candUseCursor".into(), json!(cfg.cursor_cand_list));
        ui_args.insert("candidateLayout".into(), json!(cfg.candidate_layout));
        ui_args.insert("candidatePerRow".into(), json!(cfg.candidate_per_row));
        ui_args.insert("candidateEdgeAvoidance".into(), json!(cfg.candidate_edge_avoidance));
        ui_args.insert("candidatePositionMode".into(), json!(cfg.candidate_position_mode));
        ui_args.insert("candidateOpacity".into(), json!(cfg.candidate_opacity));
        ui_args.insert("candidateTheme".into(), json!(resolve_candidate_theme(cfg)));
        ui_args.insert("candidateKeyStyle".into(), json!(cfg.candidate_key_style));
        ui_args.insert("candidateHeaderStyle".into(), json!(cfg.candidate_header_style));
        ui_args.insert("candidateMessageStyle".into(), json!(cfg.candidate_message_style));
        ui_args.insert("candidateColors".into(), Value::Object(candidate_colors_for_theme(cfg)));
        ui_args.insert("candidateStyle".into(), Value::Object(cfg.candidate_style.clone()));
        ui_args.insert("candidateStableWidth".into(), json!(cfg.candidate_stable_width));
        ui_args.insert("candidateMinWidth".into(), json!(cfg.candidate_min_width));
        ui_args.insert("candidateWrapToMaxWidth".into(), json!(cfg.candidate_wrap_to_max_width));
        ui_args.insert("candidateMaxWidth".into(), json!(cfg.candidate_max_width));
        if !force && self.last_candidate_ui_args.as_ref() == Some(&ui_args) {
            return;
        }
        self.last_candidate_ui_args = Some(ui_args.clone());
        self.ts.customize_ui(ui_args);
    }

    // CB:3713 maxCandPerPage(imeDirName)
    pub fn max_cand_per_page(ime_dir_name: &str) -> i64 {
        pager::max_cand_per_page(ime_dir_name)
    }

    // CB:3716 applyConfig
    pub fn apply_config(&mut self) {
        self.config_version = self.cfg.get_version();

        // candidates per row
        if self.cfg.candidate_layout == "vertical" {
            self.cand_per_row = 1;
        } else {
            self.cand_per_row = self.cfg.candidate_per_row;
        }
        if self.client.is_ui_less {
            self.cand_per_row = 1;
        }

        // candidates per page (never more than selection keys)
        self.cand_per_page = self.cfg.cand_per_page;
        if self.cfg.candidate_layout == "horizontal" {
            self.cand_per_page = self.cand_per_row;
        }
        self.cand_per_page = pager::clamp_cand_per_page(self.cand_per_page, &self.ime_dir_name);

        self.customize_candidate_ui(true);

        self.output_small_letter_with_shift = self.cfg.output_small_letter_with_shift;
        self.switch_page_with_space = self.cfg.switch_page_with_space;

        // Shift + Space (not declared before the service is activated)
        self.update_shift_space_key(None);

        self.full_shape_symbols = self.cfg.full_shape_symbols;
        self.direct_out_f_symbols = self.cfg.direct_out_f_symbols;
        self.easy_symbols_with_shift = self.cfg.easy_symbols_with_shift;
        self.show_phrase = self.cfg.show_phrase;
        self.sort_by_phrase = self.cfg.sort_by_phrase;

        self.intelligent_select = self.cfg.intelligent_select;
        self.intelligent_select_recent = self.cfg.intelligent_select_recent;
        self.intelligent_select_context = self.cfg.intelligent_select_context;

        self.hide_composition = self.cfg.hide_composition;
        self.hide_composition_label = self.cfg.hide_composition_label.clone();
        self.ime_display_name = self.cfg.ime_display_name.clone();

        // the mode icon tooltip shows the display name above
        self.update_lang_buttons();

        self.play_sound_when_non_cand = self.cfg.play_sound_when_non_cand;
        self.direct_show_cand = self.cfg.direct_show_cand;
        self.auto_commit_single_candidate = self.cfg.auto_commit_single_candidate;
        self.direct_commit_symbol = self.cfg.direct_commit_symbol;
        self.direct_out_m_symbols = self.cfg.direct_out_m_symbols;
        self.support_wildcard = self.cfg.support_wildcard;
        // only 0 (z) and 1 (*)
        self.sel_wildcard_char = if self.cfg.sel_wildcard_type == 1 { "*".into() } else { "z".into() };
        self.cand_max_items = self.cfg.cand_max_items;
        self.composition_buffer_mode = self.cfg.composition_buffer_mode;
        self.auto_move_cursor_in_brackets = self.cfg.auto_move_cursor_in_brackets;
        self.ime_reverse_lookup = self.cfg.ime_reverse_lookup;
        self.sel_r_cin_type = self.cfg.sel_r_cin_type;
        self.homophone_query = self.cfg.homophone_query;
        self.sel_h_cin_type = self.cfg.sel_h_cin_type;
        self.ignore_private_use_area = self.cfg.ignore_private_use_area;
        self.user_extend_table = self.cfg.user_extend_table;
        self.re_load_table = self.cfg.re_load_table;
        self.priority_extend_table = self.cfg.priority_extend_table;

        if self.ime_dir_name == "chedayi" {
            self.sel_dayi_symbol_char_type = self.cfg.sel_dayi_symbol_char_type;
        }
    }

    // CB:3837 sharedTablesDisagree: a loaded shared table differs from this
    // instance's settings (another instance already applied new settings)
    pub fn shared_tables_disagree(&self) -> bool {
        let cfg = &self.cfg;
        {
            let t = self.tables.cin.borrow();
            if t.cur_cin_type.is_some() && !t.loading && !table_load_recently_failed(t.last_load_failure) {
                if t.cur_cin_type != Some(table_index(cfg.sel_cin_type, self.cin_file_list.len()))
                    || t.ignore_private_use_area != Some(cfg.ignore_private_use_area)
                    || t.user_extend_table != Some(cfg.user_extend_table)
                    || (cfg.user_extend_table && t.priority_extend_table != Some(cfg.priority_extend_table))
                {
                    return true;
                }
            }
        }
        {
            let t = self.tables.rcin.borrow();
            if cfg.ime_reverse_lookup
                && t.cur_cin_type.is_some()
                && !t.loading
                && !table_load_recently_failed(t.last_load_failure)
                && t.cur_cin_type != Some(table_index(cfg.sel_r_cin_type, RCIN_FILE_LIST.len()))
            {
                return true;
            }
        }
        {
            let t = self.tables.hcin.borrow();
            if cfg.homophone_query
                && t.cur_cin_type.is_some()
                && !t.loading
                && !table_load_recently_failed(t.last_load_failure)
                && t.cur_cin_type != Some(table_index(cfg.sel_h_cin_type, HCIN_FILE_LIST.len()))
            {
                return true;
            }
        }
        false
    }

    // CB:3856 checkConfigChange: before every request while activated
    pub fn check_config_change(&mut self) -> Result<(), String> {
        // re-read config.json without the 3 second throttle when the shared
        // tables disagree with this copy
        if self.shared_tables_disagree() {
            self.cfg.last_update_time = 0.0;
        }
        self.cfg.update();
        let mut re_load_cin_table = false;
        let mut update_extend_table = false;
        let sel_cin_type = table_index(self.cfg.sel_cin_type, self.cin_file_list.len());
        let sel_r_cin_type = table_index(self.cfg.sel_r_cin_type, RCIN_FILE_LIST.len());
        let sel_h_cin_type = table_index(self.cfg.sel_h_cin_type, HCIN_FILE_LIST.len());

        if let Some(cin) = &self.cin {
            cin.borrow_mut().save_count_file(false)?;
        }

        // a changed table setting reloads the table (not right after a failure)
        let (cin_loading, cin_failed) = {
            let t = self.tables.cin.borrow();
            (t.loading, table_load_recently_failed(t.last_load_failure))
        };
        if !cin_loading && !cin_failed {
            let (cur, ipua, uet, pet) = {
                let t = self.tables.cin.borrow();
                (t.cur_cin_type, t.ignore_private_use_area, t.user_extend_table, t.priority_extend_table)
            };
            if cur != Some(sel_cin_type) {
                re_load_cin_table = true;
            }
            if ipua != Some(self.cfg.ignore_private_use_area) {
                re_load_cin_table = true;
            }
            if self.cfg.re_load_table {
                update_extend_table = true;
                re_load_cin_table = true;
                self.cfg.re_load_table = false;
                self.cfg.save();
            }
            if uet != Some(self.cfg.user_extend_table) {
                update_extend_table = true;
                re_load_cin_table = true;
            }
            if pet != Some(self.cfg.priority_extend_table) && self.cfg.user_extend_table {
                re_load_cin_table = true;
            }
        }

        if self.cfg.ime_reverse_lookup || self.ime_reverse_lookup {
            let (r_loading, r_failed, r_cur, r_none) = {
                let t = self.tables.rcin.borrow();
                (t.loading, table_load_recently_failed(t.last_load_failure), t.cur_cin_type, t.cin.is_none())
            };
            let c_loading = self.tables.cin.borrow().loading;
            if !r_loading && !c_loading && !r_failed && (r_cur != Some(sel_r_cin_type) || r_none) {
                self.load_r_cin_table();
            }
        }

        if self.cfg.homophone_query || self.homophone_query {
            let (h_loading, h_failed, h_cur, h_none) = {
                let t = self.tables.hcin.borrow();
                (t.loading, table_load_recently_failed(t.last_load_failure), t.cur_cin_type, t.cin.is_none())
            };
            let c_loading = self.tables.cin.borrow().loading;
            if !h_loading && !c_loading && !h_failed && (h_cur != Some(sel_h_cin_type) || h_none) {
                self.load_h_cin_table();
            }
        }

        // compare our version with the files' version
        let version = self.config_version;
        if self.cfg.is_full_reload_needed(&version) {
            // data files changed: rebuild the context
            self.init_cin_base_context()?;
        } else if self.cfg.is_config_changed(&version) {
            self.apply_config();
        }

        if re_load_cin_table || update_extend_table {
            if update_extend_table {
                self.extendtable = Some(load_data_file(&self.cfg, "extendtable.dat", ExtendTable::parse, ""));
            }
            if re_load_cin_table {
                self.re_load_cin_table = true;
            }
            self.load_cin_table();
        } else {
            let shared = self.tables.cin.borrow().cin.clone();
            let same = match (&self.cin, &shared) {
                (Some(a), Some(b)) => Rc::ptr_eq(a, b),
                (None, None) => true,
                _ => false,
            };
            if !same {
                self.cin = shared;
            }
        }
        Ok(())
    }

    // CB:3951 LoadPhraseData.run (synchronous)
    pub fn load_phrase_data(&mut self) {
        let data = phrase_data();
        data.borrow_mut().loading = true;
        let datadirs = [self.cfg.get_config_dir(), self.cfg.get_data_dir()];
        data.borrow_mut().phrase = None;
        let phrase = Phrase::load(&datadirs);
        let mut d = data.borrow_mut();
        d.phrase = phrase;
        d.loading = false;
    }

    // CB:3977 LoadCinTable.run (synchronous; every exception is swallowed)
    pub fn load_cin_table(&mut self) {
        let table = self.tables.cin.clone();
        table.borrow_mut().loading = true;
        let _ = (|| -> Result<(), String> {
            self.cfg.sel_cin_type = table_index(self.cfg.sel_cin_type, self.cin_file_list.len());
            let sel_cin_file = self.cin_file_list[self.cfg.sel_cin_type as usize].clone();
            let json_path = self.jsondir.join(&sel_cin_file);

            let current = self.cin.clone();
            if self.re_load_cin_table || current.is_none() {
                self.re_load_cin_table = false;
                // parse the new table first; replace the old one only on success
                let new_cin = match Cin::load(&json_path, &self.ime_dir_name, self.ignore_private_use_area, Cin::default_count_dir(&self.ime_dir_name)) {
                    Ok(c) => c,
                    Err(e) => {
                        let mut t = table.borrow_mut();
                        t.last_load_failure = env::time();
                        t.load_failed = true;
                        if current.is_none() {
                            self.cin = t.cin.clone();
                        }
                        return Err(e);
                    }
                };
                // the instance's and the shared table are usually the same object: close once
                let shared = table.borrow().cin.clone();
                let mut olds: Vec<Rc<RefCell<Cin>>> = Vec::new();
                for t in [current, shared].into_iter().flatten() {
                    if !olds.iter().any(|o| Rc::ptr_eq(o, &t)) {
                        olds.push(t);
                    }
                }
                for old in olds {
                    old.borrow_mut().close();
                }
                let new_cin = Rc::new(RefCell::new(new_cin));
                self.cin = Some(new_cin.clone());
                let mut t = table.borrow_mut();
                t.cin = Some(new_cin);
                t.cur_cin_type = Some(self.cfg.sel_cin_type);
                t.last_load_failure = 0.0;
                t.load_failed = false;
            }

            if self.extendtable.is_none() {
                self.extendtable = Some(load_data_file(&self.cfg, "extendtable.dat", ExtendTable::parse, ""));
            }
            {
                let extend = self.extendtable.as_ref().unwrap();
                self.cin_mut()?.update_cin_table(
                    self.cfg.user_extend_table,
                    self.cfg.priority_extend_table,
                    &extend.chardefs,
                    self.cfg.ignore_private_use_area,
                );
            }
            let mut t = table.borrow_mut();
            t.user_extend_table = Some(self.cfg.user_extend_table);
            t.priority_extend_table = Some(self.cfg.priority_extend_table);
            t.ignore_private_use_area = Some(self.cfg.ignore_private_use_area);
            Ok(())
        })();
        table.borrow_mut().loading = false;
    }

    // CB:4039 LoadRCinTable.run (synchronous)
    pub fn load_r_cin_table(&mut self) {
        let table = self.tables.rcin.clone();
        table.borrow_mut().loading = true;
        let _ = (|| -> Result<(), String> {
            self.cfg.sel_r_cin_type = table_index(self.cfg.sel_r_cin_type, RCIN_FILE_LIST.len());
            let sel_cin_file = RCIN_FILE_LIST[self.cfg.sel_r_cin_type as usize];
            let json_path = self.jsondir.join(sel_cin_file);
            let mut t = table.borrow_mut();
            if let Some(old) = t.cin.as_mut() {
                old.close();
            }
            t.cin = None;
            let not_exist = !json_path.exists();
            t.file_not_exist = Some(not_exist);
            if not_exist {
                // only the 大易 / 倉頡 tables ship by default
                t.last_load_failure = env::time();
            } else {
                match RCin::load(&json_path, &self.ime_dir_name) {
                    Ok(c) => t.cin = Some(c),
                    Err(e) => {
                        t.last_load_failure = env::time();
                        return Err(e);
                    }
                }
            }
            t.cur_cin_type = Some(self.cfg.sel_r_cin_type);
            Ok(())
        })();
        let mut t = table.borrow_mut();
        self.r_cin_file_not_exist = t.file_not_exist.unwrap_or(false);
        t.loading = false;
    }

    // CB:4086 LoadHCinTable.run (synchronous)
    pub fn load_h_cin_table(&mut self) {
        let table = self.tables.hcin.clone();
        let mut t = table.borrow_mut();
        t.loading = true;
        self.cfg.sel_h_cin_type = table_index(self.cfg.sel_h_cin_type, HCIN_FILE_LIST.len());
        let sel_cin_file = HCIN_FILE_LIST[self.cfg.sel_h_cin_type as usize];
        let json_path = self.jsondir.join(sel_cin_file);
        if let Some(old) = t.cin.as_mut() {
            old.close();
        }
        t.cin = None;
        t.file_not_exist = Some(!Path::new(&json_path).exists());
        match HCin::load(&json_path, &self.ime_dir_name) {
            Ok(c) => t.cin = Some(c),
            // missing or broken: retried by checkConfigChange after a while
            Err(_) => t.last_load_failure = env::time(),
        }
        t.cur_cin_type = Some(self.cfg.sel_h_cin_type);
        t.loading = false;
    }
}
