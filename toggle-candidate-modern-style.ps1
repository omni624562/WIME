param(
    [Parameter(Mandatory = $true)]
    [bool]$Enabled,

    [string]$ImeName = "chedayi",
    [switch]$RestartBackend
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Set-Utf8Output {
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [Console]::InputEncoding = $utf8NoBom
    [Console]::OutputEncoding = $utf8NoBom
    $script:OutputEncoding = $utf8NoBom
    $PSStyle.OutputRendering = "PlainText"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    chcp.com 65001 | Out-Null
}

function Stop-PimeBackend {
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                $_.Path -and $_.Path.StartsWith("C:\Program Files (x86)\PIME\", [System.StringComparison]::OrdinalIgnoreCase)
            }
            catch {
                $false
            }
        } |
        ForEach-Object {
            Write-Host "Stopping $($_.ProcessName) ($($_.Id))"
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
}

function Start-PimeLauncher {
    $launcher = "C:\Program Files (x86)\PIME\PIMELauncher.exe"
    if (Test-Path -LiteralPath $launcher) {
        Start-Process -FilePath $launcher -WorkingDirectory (Split-Path -Parent $launcher) -WindowStyle Hidden
        Write-Host "Started PIMELauncher.exe"
    }
}

Set-Utf8Output

$configDir = Join-Path $env:APPDATA "PIME\$ImeName"
$configPath = Join-Path $configDir "config.json"
if (-not (Test-Path -LiteralPath $configPath)) {
    throw "Config file was not found: $configPath"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $env:LOCALAPPDATA "PIME\TestBackups\config-$ImeName-$timestamp"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$backupPath = Join-Path $backupDir "config.json"
Copy-Item -LiteralPath $configPath -Destination $backupPath -Force

$jsonText = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
$config = $jsonText | ConvertFrom-Json
$config | Add-Member -NotePropertyName "candidateModernStyle" -NotePropertyValue $Enabled -Force

$config | Add-Member -NotePropertyName "candidateLayout" -NotePropertyValue "horizontal" -Force
$config | Add-Member -NotePropertyName "candidatePerRow" -NotePropertyValue 10 -Force
$config | Add-Member -NotePropertyName "candidateEdgeAvoidance" -NotePropertyValue $true -Force
$config | Add-Member -NotePropertyName "candidateTheme" -NotePropertyValue "light" -Force

$candidateColors = [ordered]@{
    panelBackground = "#FFFFFF"
    panelBorder = "#DADDE3"
    textPrimary = "#20242A"
    textSecondary = "#6B7280"
    highlightBackground = "#DCEBFF"
    highlightBorder = "#9CC7FF"
    highlightText = "#0B3A75"
}
$candidateStyle = [ordered]@{
    contentMargin = 8
    textMargin = 6
    borderRadius = 8
}
$config | Add-Member -NotePropertyName "candidateColors" -NotePropertyValue $candidateColors -Force
$config | Add-Member -NotePropertyName "candidateStyle" -NotePropertyValue $candidateStyle -Force

$config |
    ConvertTo-Json -Depth 20 |
    Set-Content -LiteralPath $configPath -Encoding UTF8

Write-Host "Updated $configPath"
Write-Host "candidateModernStyle=$Enabled"
Write-Host "Backup: $backupPath"

if ($RestartBackend) {
    Stop-PimeBackend
    Start-Sleep -Milliseconds 500
    Start-PimeLauncher
}
