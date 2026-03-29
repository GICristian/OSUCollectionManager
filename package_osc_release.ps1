# Arhivează dist\OSC pentru distribuire (prietenul extrage zip → folder OSC → OSC.exe).
# Rulează după .\build_exe.ps1. Ieșire: OSC_<versiune>_portable.zip în rădăcina repo-ului.
#
# Parametru opțional -ZipVersion (ex. același număr ca tag-ul Git v0.4.2 → "0.4.2") pentru CI.

param(
  [string]$ZipVersion = ""
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$distOsc = Join-Path $root "dist\OSC"
$mainExe = Join-Path $distOsc "OSC.exe"
if (-not (Test-Path $mainExe)) {
  Write-Error "Lipsește $mainExe. Rulează mai întâi .\build_exe.ps1"
}

$verPy = Join-Path $root "osc_collector\version.py"
if ($ZipVersion.Trim().Length -gt 0) {
  $ver = $ZipVersion.Trim()
} else {
  $raw = Get-Content -Path $verPy -Raw -Encoding utf8
  if ($raw -notmatch '__version__\s*=\s*"([^"]+)"') {
    Write-Error "Nu pot citi __version__ din $verPy"
  }
  $ver = $Matches[1]
}
$zipName = "OSC_${ver}_portable.zip"
$zipPath = Join-Path $root $zipName

if (Test-Path $zipPath) {
  Remove-Item -LiteralPath $zipPath -Force
}

Compress-Archive -Path $distOsc -DestinationPath $zipPath -CompressionLevel Optimal
Write-Host ""
Write-Host "OK: $zipName (conține folderul OSC — extrage tot, apoi OSC\OSC.exe)."
Write-Host ""
