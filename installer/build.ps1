# Builds the Windows installer: frontend -> AlaEhBackup.exe (PyInstaller) -> AlaEhBackup-Setup.exe (Inno Setup).
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
param([string]$Version = "1.6.0")
$ErrorActionPreference = "Stop"
$Version = $Version.TrimStart("v")
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host "[1/3] Building the frontend"
Push-Location frontend
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue      # never package a stale frontend if the build fails
npm install
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install failed" }
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Frontend build failed" }
Pop-Location

Write-Host "[2/3] Packaging the app (PyInstaller)"
# The exe needs to know its own version to compare it with the latest release (see backend/updater.py).
Set-Content -Path backend/_version.py -Value "VERSION = `"$Version`"" -Encoding ascii
python -m pip install -q -r backend/requirements.txt -r backend/requirements-desktop.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AlaEhBackup --icon "$root\installer\app.ico" --add-data "$root\installer\app.ico;." `
  --paths backend --collect-all cryptography --hidden-import cryptography.hazmat.bindings._rust --add-data "$root\frontend\dist;frontend_dist" `
  --distpath installer/out --workpath installer/work --specpath installer/work `
  backend/desktop.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "      self-test of the packaged app"
$selftest = Join-Path ([IO.Path]::GetTempPath()) "aeb-selftest.txt"
Remove-Item $selftest -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "installer/out/AlaEhBackup.exe" -ArgumentList "--selftest", "`"$selftest`"" -Wait -PassThru
$result = if (Test-Path $selftest) { (Get-Content $selftest -Raw).Trim() } else { "the app did not run at all (exit code $($p.ExitCode))" }
if ($p.ExitCode -ne 0 -or $result -ne "ok") { throw "The packaged app failed its self-test, so no installer was built:`n$result" }

Write-Host "[3/3] Building the installer (Inno Setup)"
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw "Inno Setup not found. Install it with: winget install JRSoftware.InnoSetup" }
& $iscc "/DAppVersion=$Version" installer/setup.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Done: installer/out/AlaEhBackup-Setup.exe"
