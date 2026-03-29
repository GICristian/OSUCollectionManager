# Dupa .\build_exe.ps1: compileaza installer\OSC_Setup.iss (Inno Setup 6).
# Cauta ISCC in Program Files; versiunea vine din osc_collector/version.py sau -Version.

param(
  [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$distExe = Join-Path $root "dist\OSC\OSC.exe"
if (-not (Test-Path -LiteralPath $distExe)) {
  Write-Error "Lipseste $distExe. Ruleaza mai intai .\build_exe.ps1"
}

if ($Version.Trim().Length -eq 0) {
  $verPy = Join-Path $root "osc_collector\version.py"
  $raw = Get-Content -Path $verPy -Raw -Encoding utf8
  if ($raw -notmatch '__version__\s*=\s*"([^"]+)"') {
    Write-Error "Nu pot citi __version__ din $verPy"
  }
  $Version = $Matches[1].Trim()
}

$candidates = @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
)
$iscc = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $iscc) {
  Write-Error "Lipseste Inno Setup 6 (ISCC.exe). Instaleaza de la https://jrsoftware.org/isdl.php"
}

New-Item -ItemType Directory -Path "installer\Output" -Force | Out-Null
& $iscc /DMyAppVersion=$Version /Q (Join-Path $root "installer\OSC_Setup.iss")
if (-not $?) {
  Write-Error "ISCC a esuat."
}

$out = Join-Path $root "installer\Output\OSC_${Version}_Setup.exe"
if (-not (Test-Path -LiteralPath $out)) {
  Write-Error "Lipseste $out"
}

Write-Host ""
Write-Host "OK: $out"
Write-Host ""
