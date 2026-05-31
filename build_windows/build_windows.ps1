# Guitar Tab Player – Windows build script
# Run this on a Windows machine (or in GitHub Actions):
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\build_windows\build_windows.ps1
#
# Requirements:
#   - Python 3.11+ (from python.org, NOT the Microsoft Store version)
#   - pip install pyinstaller PySide6 pyfluidsynth numpy
#   - Inno Setup 6  (https://jrsoftware.org/isdl.php)   – for the installer step
#   - FluidSynth Windows build (see Step 2 below)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

# ── Step 0: venv / dependencies ───────────────────────────────────────────────
Write-Host "==> Installing Python dependencies …" -ForegroundColor Cyan
Push-Location $Root
python -m pip install --upgrade pip
python -m pip install pyinstaller PySide6 pyfluidsynth numpy

# ── Step 1: Collect FluidSynth DLL ────────────────────────────────────────────
Write-Host "==> Locating fluidsynth.dll …" -ForegroundColor Cyan

$FsDll = $null

# Common install paths from the official FluidSynth Windows release
$FsCandidates = @(
    "C:\Program Files\fluidsynth\bin\fluidsynth.dll",
    "C:\Program Files (x86)\fluidsynth\bin\fluidsynth.dll",
    "$env:LOCALAPPDATA\fluidsynth\bin\fluidsynth.dll"
)
foreach ($c in $FsCandidates) {
    if (Test-Path $c) { $FsDll = $c; break }
}

# Fall back: search PATH
if (-not $FsDll) {
    $found = Get-Command fluidsynth.exe -ErrorAction SilentlyContinue
    if ($found) {
        $FsDll = Join-Path (Split-Path $found.Source) "fluidsynth.dll"
    }
}

$BuildDir = Join-Path $Root "build_windows"
if ($FsDll -and (Test-Path $FsDll)) {
    Write-Host "  Found: $FsDll"
    Copy-Item $FsDll $BuildDir -Force
} else {
    Write-Warning @"
fluidsynth.dll not found automatically.
Download the latest FluidSynth Windows release from:
  https://github.com/FluidSynth/fluidsynth/releases
Extract and copy fluidsynth.dll into:
  $BuildDir
Then re-run this script.
"@
    # Don't abort – we can still build, audio just won't work without the DLL.
}

# ── Step 2: Optional – download a small SoundFont ─────────────────────────────
$SfPath = Join-Path $BuildDir "FluidR3_GM.sf2"
if (-not (Test-Path $SfPath)) {
    Write-Host "==> No SoundFont found in build_windows/ – trying to download GeneralUser GS …" -ForegroundColor Cyan
    $GuUrl = "https://github.com/FluidSynth/fluidsynth/releases/download/v2.3.5/GeneralUser_GS_1.471.sf2"
    try {
        Invoke-WebRequest -Uri $GuUrl -OutFile (Join-Path $BuildDir "GeneralUser GS.sf2") -UseBasicParsing
        Write-Host "  SoundFont downloaded."
    } catch {
        Write-Warning "Could not download SoundFont – users will need to load one manually."
    }
}

# ── Step 3: Compile .po → .mo (if msgfmt is available) ────────────────────────
Write-Host "==> Compiling locale files …" -ForegroundColor Cyan
$LocaleDir = Join-Path $Root "tabplayer\locale"
Get-ChildItem "$LocaleDir\*\LC_MESSAGES\tabplayer.po" | ForEach-Object {
    $Mo = $_.FullName -replace '\.po$', '.mo'
    try {
        & msgfmt -o $Mo $_.FullName
        Write-Host "  Compiled: $($_.FullName)"
    } catch {
        Write-Warning "  msgfmt not found – skipping $($_.FullName). Install gettext for Windows."
    }
}

# ── Step 4: PyInstaller ────────────────────────────────────────────────────────
Write-Host "==> Running PyInstaller …" -ForegroundColor Cyan
Set-Location $Root
python -m PyInstaller guitar_tab_player.spec --noconfirm --clean

# ── Step 5: Inno Setup ────────────────────────────────────────────────────────
Write-Host "==> Building installer with Inno Setup …" -ForegroundColor Cyan
$IssScript = Join-Path $BuildDir "installer.iss"

$ISCCPaths = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$ISCC = $ISCCPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($ISCC) {
    & $ISCC $IssScript
    $Output = Join-Path $Root "dist\GuitarTabPlayer-Setup.exe"
    if (Test-Path $Output) {
        Write-Host ""
        Write-Host "==> SUCCESS!  Installer: $Output" -ForegroundColor Green
    }
} else {
    Write-Warning @"
Inno Setup not found. Download from https://jrsoftware.org/isdl.php
After installing, re-run this script or compile manually:
  ISCC.exe "$IssScript"
PyInstaller output is in: dist\GuitarTabPlayer\
"@
}

Pop-Location
