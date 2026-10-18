//! wime-config.exe: the WIME settings tools (大易/酷倉 and 新酷音), see
//! wime::configtool. A Windows-subsystem program: no console window opens.

#![windows_subsystem = "windows"]

fn main() {
    let args: Vec<String> = std::env::args().collect();
    std::process::exit(wime::configtool::main(&args));
}
