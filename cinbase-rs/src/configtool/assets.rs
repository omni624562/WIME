//! Where the settings tools find their web pages and shipped data -- the ONE
//! place that knows the layout, so moving the pages out of the `python`
//! folder (phase 3) only changes this file.
//!
//! For now everything is where the Python tools serve it from, under the PIME
//! `python` folder (paths::python_dir(): WIME_PY_DIR, else `<exe dir>\..\python`):
//!
//! | what                                   | folder                                  |
//! |----------------------------------------|-----------------------------------------|
//! | 大易/酷倉 page, config.js               | python\input_methods\<ime>\config       |
//! | 大易/酷倉 icon.ico                      | python\input_methods\<ime>              |
//! | shared pages (*.htm), css/fonts/js     | python\cinbase\config                   |
//! | data/*.json the pages load             | python\cinbase (data\)                  |
//! | default symbols.dat, swkb.dat, ...     | python\cinbase\data                     |
//! | tables (cincount, rcinAvailable)       | python\cinbase\json                     |
//! | 新酷音 pages, css/images/js/fonts       | python\input_methods\chewing            |
//! | libchewing dictionaries, symbols.dat   | python\libchewing\data                  |
//! | version.txt                            | the PIME folder (python\..)             |

use crate::paths;
use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct Assets {
    python_dir: PathBuf,
}

impl Assets {
    pub fn from_env() -> Assets {
        Assets { python_dir: paths::python_dir().clone() }
    }

    /// version.txt's folder (python/cinbase/../../, python/input_methods/chewing/../../../)
    pub fn version_dir(&self) -> PathBuf {
        self.python_dir.join("..")
    }

    // -- 大易 / 酷倉 (python/cinbase/configtool.py) --------------------------------

    /// python/cinbase (configtool.current_dir)
    pub fn cinbase_dir(&self) -> PathBuf {
        self.python_dir.join("cinbase")
    }

    /// python/cinbase/config: the shared pages, css, fonts, images, js
    pub fn cinbase_pages_dir(&self) -> PathBuf {
        self.cinbase_dir().join("config")
    }

    /// python/cinbase/data: the default data files
    pub fn cinbase_data_dir(&self) -> PathBuf {
        self.cinbase_dir().join("data")
    }

    /// python/cinbase/json: the tables
    pub fn cinbase_json_dir(&self) -> PathBuf {
        self.cinbase_dir().join("json")
    }

    /// python/input_methods/<ime>/config: the IME's page and config.js
    pub fn ime_config_dir(&self, ime: &str) -> PathBuf {
        self.python_dir.join("input_methods").join(ime).join("config")
    }

    /// python/input_methods/<ime>: icon.ico
    pub fn ime_dir(&self, ime: &str) -> PathBuf {
        self.python_dir.join("input_methods").join(ime)
    }

    // -- 新酷音 (python/input_methods/chewing/config_tool.py) -------------------------

    /// python/input_methods/chewing: the pages, css, images, js, fonts
    pub fn chewing_pages_dir(&self) -> PathBuf {
        self.ime_dir("chewing")
    }

    /// python/libchewing/data (libchewing.CHEWING_DATA_DIR)
    pub fn chewing_data_dir(&self) -> PathBuf {
        self.python_dir.join("libchewing").join("data")
    }
}
