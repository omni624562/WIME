cmake_minimum_required(VERSION 3.10)

project(PIMETextService)

# http://www.utf8everywhere.org/
add_definitions(/D_UNICODE=1 /DUNICODE=1)
set(CMAKE_CXX_STANDARD 14)

# generate the resource file containing version info
configure_file("PIMETextService.rc.in" "PIMETextService.rc" @ONLY)

include_directories(
    ${CMAKE_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/json/single_include
    ${CMAKE_CURRENT_SOURCE_DIR}
)

add_library(PIMETextService SHARED
    # core IME implementation
    PIMEImeModule.cpp
    PIMEImeModule.h
    PIMETextService.cpp
    PIMETextService.def
    PIMETextService.h
    PIMEClient.cpp
    PIMEClient.h
    PIMELangBarButton.cpp
    PIMELangBarButton.h
    DllEntry.cpp
    # resources
    ${CMAKE_CURRENT_BINARY_DIR}/PIMETextService.rc
)

target_link_libraries(PIMETextService
    libIME2_static
)

if(MSVC)
    # /guard:cf 只在編譯時加（cmake/*_flag_overrides.cmake）不夠：連結器也要 /GUARD:CF
    # 才會寫入 CFG 表並設定 DLL 的 GuardCF 特性，否則 x86/x64 的 DLL 實際上沒有 CFG
    # （dumpbin /headers 看不到 "Guard"、/loadconfig 的 Guard CF function count 為 0）。
    # ARM64 的連結器預設就開。用 target 選項而不是 CMAKE_SHARED_LINKER_FLAGS_INIT：
    # 已存在的 build 目錄的快取不會重新套用 _INIT
    target_link_options(PIMETextService PRIVATE /GUARD:CF)
endif()
