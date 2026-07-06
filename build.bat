cmake . -Bbuild -G "Visual Studio 17 2022" -A Win32cmake --build build --config Release

cmake . -Bbuild64 -G "Visual Studio 17 2022"  -A x64cmake --build build64 --config Release --target PIMETextService

cmake . -Bbuild_arm64 -G "Visual Studio 17 2022"  -A ARM64cmake --build build_arm64 --config Release --target PIMETextService

REM WIME 只維護 python 後端（大易/酷倉/新酷音），McBopomofo(node) 不再建置。
REM 需要時手動執行：cd McBopomofoWeb ^&^& npm install ^&^& npm run build:pime
