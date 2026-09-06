<#
Unsigned Windows build for NeuroEdit.

Mirrors scripts/build_alpha_macos.sh: creates a build venv, installs the app
with its packaging extra, runs PyInstaller against the shared NeuroEdit.spec,
then wraps the result in an Inno Setup installer.

Usage (from the desktop/ folder, on a Windows machine):
    .\scripts\build_alpha_windows.ps1 -Version alpha-001

Requires: Python 3.12 on PATH, and Inno Setup 6 (ISCC.exe) installed or on PATH.
Produces: release\NeuroEdit-<version>-Windows-Setup.exe
#>
param(
    [string]$Version = "0.5.12"
)

$ErrorActionPreference = "Stop"

# Resolve the desktop/ root (parent of this scripts/ folder) and work from there.
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$ReleaseDir = Join-Path $Root "release"
$AppDir = Join-Path $Root "dist\NeuroEdit"
$AppExe = Join-Path $AppDir "NeuroEdit.exe"

# 1. Build virtual environment.
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -c requirements-release.txt -e ".[package]"

# 2. Clean previous build output (leave release/ in place; we add to it).
Remove-Item -Recurse -Force "build", "dist" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

# 3. PyInstaller -> dist\NeuroEdit\NeuroEdit.exe
$env:NEUROEDIT_VERSION = $Version.TrimStart('v')
& ".\.venv\Scripts\pyinstaller.exe" --clean --noconfirm NeuroEdit.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed (exit $LASTEXITCODE)."
}
if (-not (Test-Path $AppExe)) {
    throw "Build failed: $AppExe was not created."
}

# 4. Locate the Inno Setup compiler (ISCC.exe).
$Iscc = $null
$candidate = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($candidate) {
    $Iscc = $candidate.Source
} else {
    foreach ($p in @(
        "${Env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${Env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )) {
        if (Test-Path $p) { $Iscc = $p; break }
    }
}
if (-not $Iscc) {
    throw "Inno Setup compiler (ISCC.exe) not found. Install Inno Setup 6 from https://jrsoftware.org/isdl.php"
}

# 5. Compile the installer.
& $Iscc "/DMyAppVersion=$Version" "installer\NeuroEdit.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compile failed (exit $LASTEXITCODE)."
}

$Setup = Join-Path $ReleaseDir "NeuroEdit-$Version-Windows-Setup.exe"
Write-Host ""
Write-Host "Unsigned Windows build complete."
Write-Host "Installer: $Setup"
Write-Host ""
Write-Host "Because this build is unsigned, Windows SmartScreen may warn testers."
Write-Host "Tell them to click 'More info' then 'Run anyway' on first launch."
