@echo off
REM 任一步失敗就停下並回傳錯誤碼（CI 靠這個判斷建置是否成功）

REM 產生 cinbase 碼表 json（來源 cin/ 轉 json/，已是最新的會跳過）
python\python3\python.exe python\cinbase\tools\cintojson.py || exit /b 1

cmake . -Bbuild -G "Visual Studio 17 2022" -A Win32 || exit /b 1
cmake --build build --config Release || exit /b 1

cmake . -Bbuild64 -G "Visual Studio 17 2022" -A x64 || exit /b 1
cmake --build build64 --config Release --target PIMETextService || exit /b 1

cmake . -Bbuild_arm64 -G "Visual Studio 17 2022" -A ARM64 || exit /b 1
cmake --build build_arm64 --config Release --target PIMETextService || exit /b 1

REM WIME 只維護 python 後端（大易/酷倉/新酷音）；node（McBopomofo/emojime）與
REM go-backend 已自 repo 移除，需要時可從 git 歷史取回。
