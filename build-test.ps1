param(
    [ValidateSet("Win32", "x64", "Both")]
    [string]$Platform = "Both",

    [switch]$SkipTests,
    [switch]$BuildAllTargets
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:RepoRoot = if ($PSScriptRoot) {
    $PSScriptRoot
}
else {
    (Get-Location).Path
}

Push-Location -LiteralPath $script:RepoRoot

function Set-Utf8Output {
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [Console]::InputEncoding = $utf8NoBom
    [Console]::OutputEncoding = $utf8NoBom
    $script:OutputEncoding = $utf8NoBom
    $PSStyle.OutputRendering = "PlainText"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    try {
        chcp.com 65001 | Out-Null
    }
    catch {
        Write-Warning "Unable to switch console code page to 65001: $($_.Exception.Message)"
    }
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Script
    )

    Write-Host ""
    Write-Host "==> $Name"
    & $Script
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$FilePath,

        [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Get-CMakeCommand {
    $cmake = Get-Command cmake -ErrorAction SilentlyContinue
    if ($cmake) {
        return $cmake.Source
    }

    $defaultPath = "C:\Program Files\CMake\bin\cmake.exe"
    if (Test-Path -LiteralPath $defaultPath) {
        return $defaultPath
    }

    throw "CMake was not found on PATH or at $defaultPath"
}

function Add-CargoToPath {
    $cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
    if ((Test-Path -LiteralPath $cargoBin) -and ($env:Path -notlike "*$cargoBin*")) {
        $env:Path = "$cargoBin;$env:Path"
    }
}

function Clear-PythonCache {
    $cacheDirs = @(
        "python\__pycache__",
        "python\cinbase\__pycache__",
        "python\input_methods\chewing\__pycache__",
        "python\opencc\__pycache__",
        "tests\__pycache__"
    )

    $repoRoot = (Resolve-Path .).Path
    foreach ($cacheDir in $cacheDirs) {
        if (-not (Test-Path -LiteralPath $cacheDir)) {
            continue
        }

        $resolved = (Resolve-Path -LiteralPath $cacheDir).Path
        if ($resolved.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}

function Invoke-CMakeBuild {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("Win32", "x64")]
        [string]$Arch,

        [Parameter(Mandatory = $true)]
        [string]$BuildDir
    )

    $targetArgs = @()
    if (-not $BuildAllTargets) {
        $targetArgs = @("--target", "PIMETextService")
    }

    Invoke-Step "Configure $Arch" {
        Invoke-Native -FilePath $script:CMakePath -Arguments @(".", "-B", $BuildDir, "-G", "Visual Studio 17 2022", "-A", $Arch, "-DCMAKE_POLICY_VERSION_MINIMUM=3.5")
    }

    Invoke-Step "Build $Arch" {
        $buildArgs = @("--build", $BuildDir, "--config", "Release") + $targetArgs
        Invoke-Native -FilePath $script:CMakePath -Arguments $buildArgs
    }
}

Set-Utf8Output
Add-CargoToPath
$script:CMakePath = Get-CMakeCommand

Write-Host "PowerShell: $($PSVersionTable.PSVersion)"
Write-Host "CMake: $script:CMakePath"
Write-Host "PYTHONUTF8=$env:PYTHONUTF8; PYTHONIOENCODING=$env:PYTHONIOENCODING"

Invoke-Step "UTF-8 output smoke check" {
    Invoke-Native -FilePath "python" -Arguments @("-c", "print('UTF-8 OK: \u4e2d\u6587\u5019\u9078\u5b57\u6846')")
}

if ($Platform -in @("Win32", "Both")) {
    Invoke-CMakeBuild -Arch "Win32" -BuildDir "build"
}

if ($Platform -in @("x64", "Both")) {
    Invoke-CMakeBuild -Arch "x64" -BuildDir "build64"
}

if (-not $SkipTests) {
    Invoke-Step "Python backend resilience tests" {
        Invoke-Native -FilePath "python" -Arguments @("-m", "unittest", "tests.test_backend_resilience")
    }

    Invoke-Step "Python syntax checks" {
        Invoke-Native -FilePath "python" -Arguments @(
            "-m",
            "py_compile",
            "python\server.py",
            "python\cinbase\cin.py",
            "python\cinbase\config.py",
            "python\cinbase\__init__.py",
            "python\input_methods\chewing\chewing_config.py",
            "python\input_methods\chewing\chewing_ime.py",
            "python\textService.py"
        )
    }

    Invoke-Step "JSON config check" {
        Invoke-Native -FilePath "python" -Arguments @("-m", "json.tool", "python\input_methods\chedayi\config\config.json") | Out-Null
    }
}

Invoke-Step "Clean Python cache" {
    Clear-PythonCache
}

Invoke-Step "Whitespace check" {
    Invoke-Native -FilePath "git" -Arguments @("diff", "--check")
    Invoke-Native -FilePath "git" -Arguments @("-C", "libIME2", "diff", "--check")
}

Write-Host ""
Write-Host "Build and test completed."

Pop-Location
