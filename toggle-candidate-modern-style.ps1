param(
    [Parameter(Mandatory = $true)]
    [bool]$Enabled,

    [string]$ImeName = "chedayi",
    [string]$Theme = "dark",
    [switch]$RestartBackend
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Set-Utf8Output {
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [Console]::InputEncoding = $utf8NoBom
    [Console]::OutputEncoding = $utf8NoBom
    $script:OutputEncoding = $utf8NoBom
    if ($null -ne (Get-Variable -Name "PSStyle" -ErrorAction SilentlyContinue)) {
        $PSStyle.OutputRendering = "PlainText"
    }
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
$config | Add-Member -NotePropertyName "candidateTheme" -NotePropertyValue $Theme -Force

if ($Theme -eq "dark") {
    $candidateColors = [ordered]@{
        panelBackground     = "#1E1E24"
        panelBorder         = "#4B5563" # 調亮灰色邊緣，防止在暗色桌面背景中融合
        textPrimary         = "#F3F4F6"
        textSecondary       = "#8E9AA8"
        highlightBackground = "#3B82F6"
        highlightBorder     = "#3B82F6"
        highlightText       = "#FFFFFF"
    }
    $candidateStyle = [ordered]@{
        contentMargin = 12
        textMargin    = 8
        borderRadius  = 6
    }
} else {
    $candidateColors = [ordered]@{
        panelBackground     = "#F8F9FA"
        panelBorder         = "#E5E7EB"
        textPrimary         = "#2E3440"
        textSecondary       = "#9CA3AF"
        highlightBackground = "#88C0D0"
        highlightBorder     = "#88C0D0"
        highlightText       = "#ECEFF4"
    }
    $candidateStyle = [ordered]@{
        contentMargin = 14
        textMargin    = 10
        borderRadius  = 8
    }
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
