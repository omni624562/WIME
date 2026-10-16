<#
.SYNOPSIS
    重新建置內附的新酷音引擎：python\libchewing\chewing.dll 與 data\ 下的詞庫。

.DESCRIPTION
    來源是 libchewing 子模組（https://codeberg.org/chewing/libchewing.git，tag v0.13.1）
    與它的 data 子模組（libchewing-data）。不經過上游的 CMake：它會從 GitHub 下載
    Corrosion，這裡直接用 cargo。

    1. chewing.dll：chewing_capi 以 cdylib 建成 32 位元（i686-pc-windows-msvc），
       靜態連結 C 執行階段（+crt-static，不需要 VC++ 可轉散發套件），並內建 SQLite
       （sqlite-bundled：升級時把舊版的 chewing.sqlite3 使用者詞庫轉成 chewing.dat、
       設定工具匯入舊詞庫都要用到）。匯出的函式與上游 capi\src\symbols-msvc.def 相同。
    2. 詞庫：用同一份原始碼建出的 chewing-cli，把 data\dict\chewing\{tsi,word}.csv
       轉成 tsi.dat / word.dat；symbols.dat / swkb.dat 直接複製。結果是可重現的
       （同一份 CSV 每次建出的 .dat 位元組相同）。
    3. 用內嵌的 32 位元 Python 載入新的 DLL，確認 chewing_version() 是預期的版本。

    建出的檔案仍然提交到 repo（安裝程式直接打包 python\libchewing）；
    tests\test_libchewing_build.py 檢查提交的 DLL 版本與詞庫檔案組合。

    cargo 會因為 sqlite-bundled 在子模組的 Cargo.lock 多加一行相依（cc），建完後還原，
    子模組保持乾淨。

.PARAMETER SkipDll
    只重建詞庫。

.PARAMETER SkipData
    只重建 DLL。
#>
param(
    [switch]$SkipDll,
    [switch]$SkipData
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ExpectedVersion = "0.13.1"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $RepoRoot "libchewing"
$DataSource = Join-Path $Source "data"
$OutDir = Join-Path $RepoRoot "python\libchewing"
$OutData = Join-Path $OutDir "data"
$TargetDir = Join-Path $RepoRoot "build\libchewing-target"
$Python = Join-Path $RepoRoot "python\python3\python.exe"

function Invoke-Checked([string]$what, [scriptblock]$block) {
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

# 子模組要在正確的版本，data 子模組要已經取回
if (-not (Test-Path (Join-Path $Source "Cargo.toml"))) {
    throw "libchewing submodule is missing: git submodule update --init libchewing"
}
$described = (& git -C $Source describe --tags --exact-match 2>$null)
if ($described -ne "v$ExpectedVersion") {
    throw "libchewing submodule is at '$described', expected v$ExpectedVersion (git -C libchewing checkout v$ExpectedVersion)"
}
if (-not (Test-Path (Join-Path $DataSource "dict\chewing\tsi.csv"))) {
    Invoke-Checked "git submodule update (libchewing-data)" { git -C $Source submodule update --init data }
}

$env:CARGO_TARGET_DIR = $TargetDir
$lockFile = Join-Path $Source "Cargo.lock"
Push-Location $Source
try {
    if (-not $SkipDll) {
        $savedRustflags = $env:RUSTFLAGS
        $env:RUSTFLAGS = "-C target-feature=+crt-static"
        try {
            Invoke-Checked "cargo rustc chewing_capi" {
                cargo rustc --release -p chewing_capi --features sqlite-bundled `
                    --target i686-pc-windows-msvc --crate-type cdylib
            }
        }
        finally {
            $env:RUSTFLAGS = $savedRustflags
        }
        Copy-Item (Join-Path $TargetDir "i686-pc-windows-msvc\release\chewing_capi.dll") `
            (Join-Path $OutDir "chewing.dll") -Force
    }

    if (-not $SkipData) {
        # 詞庫轉換工具只在建置時用，建成本機架構即可
        Invoke-Checked "cargo build chewing-cli" { cargo build --release -p chewing-cli }
        $cli = Join-Path $TargetDir "release\chewing-cli.exe"
        New-Item -ItemType Directory -Force $OutData | Out-Null
        foreach ($name in "tsi", "word") {
            $csv = Join-Path $DataSource "dict\chewing\$name.csv"
            $dat = Join-Path $OutData "$name.dat"
            Invoke-Checked "chewing-cli init $name" { & $cli init --csv $csv $dat }
        }
        foreach ($name in "symbols.dat", "swkb.dat") {
            Copy-Item (Join-Path $DataSource "misc\$name") (Join-Path $OutData $name) -Force
        }
        # 舊的 C 版 libchewing 的資料檔，新版不會讀
        foreach ($name in "dictionary.dat", "index_tree.dat", "pinyin.tab") {
            $old = Join-Path $OutData $name
            if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old }
        }
    }
}
finally {
    Pop-Location
    # sqlite-bundled 讓 cargo 在 Cargo.lock 補上 cc 相依；還原，子模組保持乾淨
    & git -C $Source checkout -- Cargo.lock 2>$null
}

# 確認內嵌的 32 位元 Python 載得起來、版本正確
$check = "import ctypes,sys; d=ctypes.CDLL(sys.argv[1]); d.chewing_version.restype=ctypes.c_char_p; print(d.chewing_version().decode())"
$version = (& $Python -c $check (Join-Path $OutDir "chewing.dll"))
if ($LASTEXITCODE -ne 0 -or $version -ne $ExpectedVersion) {
    throw "chewing.dll reports version '$version', expected $ExpectedVersion"
}

Get-ChildItem $OutDir\chewing.dll, $OutData\* | ForEach-Object {
    "{0,-12} {1,10:N0}  {2}" -f $_.Name, $_.Length, (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
}
"libchewing $version OK"
