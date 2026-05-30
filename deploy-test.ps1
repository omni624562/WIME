param(
    [ValidateSet("Deploy", "Restore")]
    [string]$Mode = "Deploy",

    [string]$PimeRoot,
    [string]$BackupPath,
    [string]$LogPath,
    [switch]$SkipBuild,
    [switch]$RegisterDll,
    [switch]$ScheduleLockedFiles
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:RepoRoot = if ($PSScriptRoot) {
    $PSScriptRoot
}
else {
    (Get-Location).Path
}
$script:ScheduledReplacement = $false

function Set-Utf8Output {
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [Console]::InputEncoding = $utf8NoBom
    [Console]::OutputEncoding = $utf8NoBom
    $script:OutputEncoding = $utf8NoBom
    if ($null -ne (Get-Variable -Name PSStyle -ErrorAction SilentlyContinue)) {
        $PSStyle.OutputRendering = "PlainText"
    }
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    chcp.com 65001 | Out-Null
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "This script must be run from an elevated PowerShell session."
    }
}

function Resolve-PimeRoot {
    param([string]$ExplicitRoot)

    if ($ExplicitRoot) {
        return (Resolve-Path -LiteralPath $ExplicitRoot).Path
    }

    $reg = Get-ItemProperty -Path "HKLM:\Software\PIME" -ErrorAction SilentlyContinue
    if ($reg -and $reg."(default)") {
        return $reg."(default)"
    }

    $defaultRoot = "C:\Program Files (x86)\PIME"
    if (Test-Path -LiteralPath $defaultRoot) {
        return $defaultRoot
    }

    throw "PIME install folder was not found. Pass -PimeRoot explicitly."
}

function Stop-PimeProcesses {
    param([string]$Root)

    $prefix = $Root.TrimEnd("\") + "\"
    $targets = Get-Process -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                $_.Path -and $_.Path.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
            }
            catch {
                $false
            }
        }

    foreach ($process in $targets) {
        Write-Host "Stopping $($process.ProcessName) ($($process.Id))"
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Milliseconds 500
}

function Test-FileLocked {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }

    try {
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        $stream.Close()
        return $false
    }
    catch {
        return $true
    }
}

function Assert-DllsUnlocked {
    param([string]$Root)

    $dlls = @(
        (Join-Path $Root "x86\PIMETextService.dll"),
        (Join-Path $Root "x64\PIMETextService.dll")
    )

    $locked = @($dlls | Where-Object { Test-FileLocked -Path $_ })
    if ($locked.Count -eq 0) {
        return
    }

    Write-Host "Locked DLL(s):"
    foreach ($dll in $locked) {
        Write-Host "  $dll"
    }

    Write-Host ""
    Write-Host "Processes currently loading PIMETextService.dll:"
    tasklist /m PIMETextService.dll 2>$null

    throw "PIMETextService.dll is still loaded. Close apps using the IME, then run deploy again. No files were changed."
}

function Copy-WithBackup {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,

        [Parameter(Mandatory = $true)]
        [string]$Destination,

        [Parameter(Mandatory = $true)]
        [string]$BackupRoot
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing source: $Source"
    }

    $relative = $Destination.Substring($script:PimeRoot.Length).TrimStart("\")
    $backupFile = Join-Path $BackupRoot $relative
    $backupParent = Split-Path -Parent $backupFile
    $destParent = Split-Path -Parent $Destination

    New-Item -ItemType Directory -Force -Path $backupParent | Out-Null
    New-Item -ItemType Directory -Force -Path $destParent | Out-Null

    if ((Test-Path -LiteralPath $Destination) -and (-not (Test-Path -LiteralPath $backupFile))) {
        Copy-Item -LiteralPath $Destination -Destination $backupFile -Force
    }

    try {
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
        Write-Host "Updated $relative"
    }
    catch {
        if (-not $ScheduleLockedFiles) {
            throw
        }

        $stage = "$Destination.pending-$((Get-Date).ToString('yyyyMMddHHmmss'))"
        Copy-Item -LiteralPath $Source -Destination $stage -Force
        Schedule-ReplacementOnReboot -Source $stage -Destination $Destination
        $script:ScheduledReplacement = $true
        Write-Warning "File is locked; scheduled replacement after reboot: $relative"
    }
}

function Schedule-ReplacementOnReboot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,

        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    if (-not ("PendingFileRename.NativeMethods" -as [type])) {
        Add-Type -TypeDefinition @"
namespace PendingFileRename {
    using System;
    using System.Runtime.InteropServices;

    public static class NativeMethods {
        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool MoveFileEx(string lpExistingFileName, string lpNewFileName, int dwFlags);
    }
}
"@
    }

    $MOVEFILE_REPLACE_EXISTING = 0x1
    $MOVEFILE_DELAY_UNTIL_REBOOT = 0x4

    $ok = [PendingFileRename.NativeMethods]::MoveFileEx($Source, $Destination, $MOVEFILE_REPLACE_EXISTING -bor $MOVEFILE_DELAY_UNTIL_REBOOT)
    if (-not $ok) {
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        throw "Unable to schedule replacement on reboot. Win32 error: $errorCode"
    }
}

function Restore-Backup {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,

        [Parameter(Mandatory = $true)]
        [string]$BackupRoot
    )

    if (-not (Test-Path -LiteralPath $BackupRoot)) {
        throw "Backup folder was not found: $BackupRoot"
    }

    Stop-PimeProcesses -Root $Root
    Clear-PendingPimeReplacements -Root $Root

    Get-ChildItem -LiteralPath $BackupRoot -File -Recurse | ForEach-Object {
        $relative = $_.FullName.Substring($BackupRoot.Length).TrimStart("\")
        $destination = Join-Path $Root $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        try {
            Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
            Write-Host "Restored $relative"
        }
        catch {
            if (-not $ScheduleLockedFiles) {
                throw
            }

            $stage = "$destination.restore-$((Get-Date).ToString('yyyyMMddHHmmss'))"
            Copy-Item -LiteralPath $_.FullName -Destination $stage -Force
            Schedule-ReplacementOnReboot -Source $stage -Destination $destination
            $script:ScheduledReplacement = $true
            Write-Warning "File is locked; scheduled restore after reboot: $relative"
        }
    }

    if ($script:ScheduledReplacement) {
        Write-Warning "One or more files are scheduled for restore after reboot. PIMELauncher was not restarted; reboot before testing."
    }
    else {
        Start-PimeLauncher -Root $Root
    }
}

function Clear-PendingPimeReplacements {
    param([string]$Root)

    $sessionManager = "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager"
    $propertyName = "PendingFileRenameOperations"
    $property = Get-ItemProperty -Path $sessionManager -Name $propertyName -ErrorAction SilentlyContinue
    if (-not $property) {
        return
    }

    $values = @($property.$propertyName)
    if ($values.Count -eq 0) {
        return
    }

    $rootNeedle = "\??\$($Root.TrimEnd("\"))"
    $filtered = New-Object System.Collections.Generic.List[string]
    $removed = 0

    for ($i = 0; $i -lt $values.Count; $i += 2) {
        $source = $values[$i]
        $destination = if ($i + 1 -lt $values.Count) { $values[$i + 1] } else { "" }
        $touchesPime = (
            ($source -like "*$rootNeedle*") -or
            ($destination -like "*$rootNeedle*")
        )

        if ($touchesPime) {
            $removed++
            continue
        }

        $filtered.Add($source)
        if ($i + 1 -lt $values.Count) {
            $filtered.Add($destination)
        }
    }

    if ($removed -gt 0) {
        if ($filtered.Count -gt 0) {
            Set-ItemProperty -Path $sessionManager -Name $propertyName -Value ([string[]]$filtered)
        }
        else {
            Remove-ItemProperty -Path $sessionManager -Name $propertyName -ErrorAction SilentlyContinue
        }
        Write-Host "Cleared $removed pending PIME replacement operation(s)."
    }
}

function Start-PimeLauncher {
    param([string]$Root)

    $launcher = Join-Path $Root "PIMELauncher.exe"
    if (Test-Path -LiteralPath $launcher) {
        Start-Process -FilePath $launcher -WorkingDirectory $Root -WindowStyle Hidden
        Write-Host "Started PIMELauncher.exe"
    }
}

function Register-PimeDlls {
    param([string]$Root)

    $x86Dll = Join-Path $Root "x86\PIMETextService.dll"
    $x64Dll = Join-Path $Root "x64\PIMETextService.dll"
    $regsvr32x86 = Join-Path $env:WINDIR "SysWOW64\regsvr32.exe"
    $regsvr32x64 = Join-Path $env:WINDIR "System32\regsvr32.exe"

    if (Test-Path -LiteralPath $x86Dll) {
        & $regsvr32x86 /s $x86Dll
        Write-Host "Registered x86 PIMETextService.dll"
    }

    if (Test-Path -LiteralPath $x64Dll) {
        & $regsvr32x64 /s $x64Dll
        Write-Host "Registered x64 PIMETextService.dll"
    }
}

Set-Utf8Output
Assert-Administrator

if (-not $LogPath) {
    $LogPath = Join-Path $env:LOCALAPPDATA "PIME\Logs\deploy-test.log"
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
Start-Transcript -Path $LogPath -Append | Out-Null

Push-Location -LiteralPath $script:RepoRoot

try {
    $script:PimeRoot = Resolve-PimeRoot -ExplicitRoot $PimeRoot
    Write-Host "PIME root: $script:PimeRoot"

    if ($Mode -eq "Restore") {
        if (-not $BackupPath) {
            throw "Restore mode requires -BackupPath."
        }
        Restore-Backup -Root $script:PimeRoot -BackupRoot (Resolve-Path -LiteralPath $BackupPath).Path
        Write-Host "Restore completed."
        return
    }

    if (-not $SkipBuild) {
        & (Join-Path $script:RepoRoot "build-test.ps1") -SkipTests
    }

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    if (-not $BackupPath) {
        $BackupPath = Join-Path $env:LOCALAPPDATA "PIME\TestBackups\$timestamp"
    }
    New-Item -ItemType Directory -Force -Path $BackupPath | Out-Null
    Write-Host "Backup path: $BackupPath"

    Stop-PimeProcesses -Root $script:PimeRoot
    Clear-PendingPimeReplacements -Root $script:PimeRoot
    if (-not $ScheduleLockedFiles) {
        Assert-DllsUnlocked -Root $script:PimeRoot
    }

    Copy-WithBackup `
        -Source (Join-Path $script:RepoRoot "build\PIMETextService\Release\PIMETextService.dll") `
        -Destination (Join-Path $script:PimeRoot "x86\PIMETextService.dll") `
        -BackupRoot $BackupPath

    Copy-WithBackup `
        -Source (Join-Path $script:RepoRoot "build64\PIMETextService\Release\PIMETextService.dll") `
        -Destination (Join-Path $script:PimeRoot "x64\PIMETextService.dll") `
        -BackupRoot $BackupPath

    $pythonFiles = @(
        "server.py",
        "textService.py",
        "cinbase\__init__.py",
        "cinbase\cin.py",
        "cinbase\config.py",
        "cinbase\config\config.htm",
        "cinbase\config\css\config.css",
        "cinbase\config\js\config.js",
        "input_methods\checj\config\config.json",
        "input_methods\chedayi\config\config.json",
        "input_methods\cheliu\config\config.json",
        "input_methods\chewing\config_tool.py",
        "input_methods\chewing\config_tool.html",
        "input_methods\chewing\css\config.css",
        "input_methods\chewing\chewing_config.py",
        "input_methods\chewing\chewing_ime.py",
        "input_methods\chewing\js\config.js"
    )

    foreach ($file in $pythonFiles) {
        Copy-WithBackup `
            -Source (Join-Path $script:RepoRoot "python\$file") `
            -Destination (Join-Path $script:PimeRoot "python\$file") `
            -BackupRoot $BackupPath
    }

    if ($RegisterDll) {
        Register-PimeDlls -Root $script:PimeRoot
    }

    if ($script:ScheduledReplacement) {
        Write-Warning "One or more files are scheduled for replacement after reboot. PIMELauncher was not restarted; reboot before testing."
    }
    else {
        Start-PimeLauncher -Root $script:PimeRoot
    }

    Write-Host ""
    Write-Host "Deploy completed."
    Write-Host "Restore command:"
    Write-Host "  pwsh -ExecutionPolicy Bypass -File `"$script:RepoRoot\deploy-test.ps1`" -Mode Restore -BackupPath `"$BackupPath`""
}
finally {
    Pop-Location
    Stop-Transcript | Out-Null
}
