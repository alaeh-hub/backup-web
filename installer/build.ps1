# Builds the Windows installer: frontend -> AlaEhBackup.exe (PyInstaller) -> AlaEhBackup-Setup.exe (Inno Setup).
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
param([string]$Version = "1.2.0")
$ErrorActionPreference = "Stop"
$Version = $Version.TrimStart("v")
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host "[1/3] Building the frontend"
Push-Location frontend; npm install; npm run build; Pop-Location

Write-Host "[2/3] Packaging the app (PyInstaller)"
python -m pip install -q -r backend/requirements.txt -r backend/requirements-desktop.txt pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all py7zr --name AlaEhBackup `
  --paths backend --add-data "$root\frontend\dist;frontend_dist" `
  --distpath installer/out --workpath installer/work --specpath installer/work `
  backend/desktop.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "[3/3] Building the installer (Inno Setup)"
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw "Inno Setup not found. Install it with: winget install JRSoftware.InnoSetup" }
& $iscc "/DAppVersion=$Version" installer/setup.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Done: installer/out/AlaEhBackup-Setup.exe"
