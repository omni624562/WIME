@echo off
REM Stop at the first failing step and return its error code (CI relies on it).
REM Keep this file ASCII-only with CRLF line endings: cmd.exe parses batch files
REM in the console code page, and non-ASCII text or LF-only lines break it.

REM Generate the cinbase table JSON cache (cin/ -> json/; up-to-date files are skipped)
python\python3\python.exe python\cinbase\tools\cintojson.py || exit /b 1

cmake . -Bbuild -G "Visual Studio 17 2022" -A Win32 || exit /b 1
cmake --build build --config Release || exit /b 1

cmake . -Bbuild64 -G "Visual Studio 17 2022" -A x64 || exit /b 1
cmake --build build64 --config Release --target PIMETextService || exit /b 1

cmake . -Bbuild_arm64 -G "Visual Studio 17 2022" -A ARM64 || exit /b 1
cmake --build build_arm64 --config Release --target PIMETextService || exit /b 1

REM WIME only maintains the python backend (Dayi / Cangjie / Chewing). The node
REM (McBopomofo, emojime) and go-backend sources were removed; see git history.
