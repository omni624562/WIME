@echo off
REM Stop at the first failing step and return its error code (CI relies on it).
REM Keep this file ASCII-only with CRLF line endings: cmd.exe parses batch files
REM in the console code page, and non-ASCII text or LF-only lines break it.
REM No -G: CMake picks the newest installed Visual Studio (2022 locally; CI images
REM may only have a newer one). Existing build dirs keep their cached generator.

REM Generate the cinbase table JSON cache (cin/ -> json/; up-to-date files are skipped)
python\python3\python.exe python\cinbase\tools\cintojson.py || exit /b 1

REM Trimmed copy of the Python standard library zip for the installer (build\python312.zip)
python\python3\python.exe installer\trim_python_zip.py || exit /b 1

cmake . -Bbuild -A Win32 || exit /b 1
cmake --build build --config Release || exit /b 1

REM Rust Dayi backend (cinbase-rs): 32-bit, static CRT (see cinbase-rs\.cargo\config.toml)
REM cargo reads .cargo\config.toml from the current directory, not from --manifest-path
pushd cinbase-rs
cargo build --release || (popd & exit /b 1)
popd

cmake . -Bbuild64 -A x64 || exit /b 1
cmake --build build64 --config Release --target PIMETextService || exit /b 1

cmake . -Bbuild_arm64 -A ARM64 || exit /b 1
cmake --build build_arm64 --config Release --target PIMETextService || exit /b 1

REM WIME only maintains the python backend (Dayi / Cangjie / Chewing). The node
REM (McBopomofo, emojime) and go-backend sources were removed; see git history.
