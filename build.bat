@echo off
REM Stop at the first failing step and return its error code (CI relies on it).
REM Keep this file ASCII-only with CRLF line endings: cmd.exe parses batch files
REM in the console code page, and non-ASCII text or LF-only lines break it.
REM No -G: CMake picks the newest installed Visual Studio (2022 locally; CI images
REM may only have a newer one). Existing build dirs keep their cached generator.

REM Generate the cinbase table JSON cache (cin/ -> json/; up-to-date files are skipped).
REM The repo's embedded Python is only a build and test tool: the installer ships
REM the generated tables (python\cinbase\json) under data\, and no Python at all.
python\python3\python.exe python\cinbase\tools\cintojson.py || exit /b 1

cmake . -Bbuild -A Win32 || exit /b 1
cmake --build build --config Release || exit /b 1

REM Rust backend and settings tool (cinbase-rs: wime-cinbase.exe, wime-config.exe): 32-bit, static CRT (see cinbase-rs\.cargo\config.toml)
REM cargo reads .cargo\config.toml from the current directory, not from --manifest-path
pushd cinbase-rs
cargo build --release || (popd & exit /b 1)
popd

cmake . -Bbuild64 -A x64 || exit /b 1
cmake --build build64 --config Release --target PIMETextService || exit /b 1

cmake . -Bbuild_arm64 -A ARM64 || exit /b 1
cmake --build build_arm64 --config Release --target PIMETextService || exit /b 1

REM Native ARM64 builds of the launcher, the backend and the settings tool (the
REM installer uses them on ARM64 Windows instead of the 32-bit x86 ones, which would
REM run emulated): <crate>\target\aarch64-pc-windows-msvc\release\*.exe
pushd PIMELauncher
cargo build --release --target aarch64-pc-windows-msvc || (popd & exit /b 1)
popd
pushd cinbase-rs
cargo build --release --target aarch64-pc-windows-msvc || (popd & exit /b 1)
popd

REM WIME only maintains Dayi / Cangjie / Chewing (Rust, cinbase-rs; the python
REM sources stay as the tests' reference). The node (McBopomofo, emojime) and
REM go-backend sources were removed; see git history.
