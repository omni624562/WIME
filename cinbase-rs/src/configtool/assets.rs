//! Where the settings tools find their web pages and shipped data. The layout
//! itself is in paths.rs (the data root: `<PIME>\data` installed, the repo's
//! `python` folder in development); this only binds it to one data root.
//!
//! | what                                   | under the data root                     |
//! |----------------------------------------|-----------------------------------------|
//! | 大易/酷倉 page, config.js               | input_methods\<ime>\config              |
//! | 大易/酷倉 icon.ico                      | input_methods\<ime>                     |
//! | shared pages (*.htm), css/fonts/js     | cinbase\config                          |
//! | data/*.json the pages load             | cinbase (data\)                         |
//! | default symbols.dat, swkb.dat, ...     | cinbase\data                            |
//! | tables (cincount, rcinAvailable)       | cinbase\json                            |
//! | 新酷音 pages, css/images/js/fonts       | input_methods\chewing                   |
//! | libchewing dictionaries, symbols.dat   | libchewing\data                         |
//! | version.txt                            | the data root's parent (<PIME>)         |

use crate::paths;
use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct Assets {
    data_root: PathBuf,
}

impl Assets {
    pub fn from_env() -> Assets {
        Assets { data_root: paths::data_root().clone() }
    }

    /// version.txt's folder (python/cinbase/../../, python/input_methods/chewing/../../../)
    pub fn version_dir(&self) -> PathBuf {
        paths::version_dir_in(&self.data_root)
    }

    // -- 大易 / 酷倉 (python/cinbase/configtool.py) --------------------------------

    /// cinbase (configtool.current_dir)
    pub fn cinbase_dir(&self) -> PathBuf {
        paths::cinbase_dir_in(&self.data_root)
    }

    /// cinbase/config: the shared pages, css, fonts, images, js
    pub fn cinbase_pages_dir(&self) -> PathBuf {
        paths::cinbase_pages_dir_in(&self.data_root)
    }

    /// cinbase/data: the default data files
    pub fn cinbase_data_dir(&self) -> PathBuf {
        paths::data_dir_in(&self.data_root)
    }

    /// cinbase/json: the tables
    pub fn cinbase_json_dir(&self) -> PathBuf {
        paths::json_dir_in(&self.data_root)
    }

    /// input_methods/<ime>/config: the IME's page and config.js
    pub fn ime_config_dir(&self, ime: &str) -> PathBuf {
        paths::default_config_dir_in(&self.data_root, ime)
    }

    /// input_methods/<ime>: icon.ico
    pub fn ime_dir(&self, ime: &str) -> PathBuf {
        paths::ime_dir_in(&self.data_root, ime)
    }

    // -- 新酷音 (python/input_methods/chewing/config_tool.py) -------------------------

    /// input_methods/chewing: the pages, css, images, js, fonts
    pub fn chewing_pages_dir(&self) -> PathBuf {
        self.ime_dir("chewing")
    }

    /// libchewing/data (libchewing.CHEWING_DATA_DIR)
    pub fn chewing_data_dir(&self) -> PathBuf {
        paths::chewing_data_dir_in(&self.data_root)
    }
}
