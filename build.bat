REM 產生 cinbase 碼表 json（來源 cin/ 轉 json/，已是最新的會跳過）
python\python3\python.exe python\cinbase\tools\cintojson.py

cmake . -Bbuild -G "Visual Studio 17 2022" -A Win32
cmake --build build --config Release

cmake . -Bbuild64 -G "Visual Studio 17 2022" -A x64
cmake --build build64 --config Release --target PIMETextService

cmake . -Bbuild_arm64 -G "Visual Studio 17 2022" -A ARM64
cmake --build build_arm64 --config Release --target PIMETextService

REM WIME 只維護 python 後端（大易/酷倉/新酷音），McBopomofo(node) 不再建置。
REM 需要時手動執行：cd McBopomofoWeb ^&^& npm install ^&^& npm run build:pime
