# Creează repo-ul OSUCollectionManager pe GitHub (dacă lipsește) și face push pe main.
# O singură dată, înainte: deschide PowerShell și rulează:
#   gh auth login -h github.com -p https -w
# (se deschide browserul; acceptă permisiunile GitHub CLI.)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
  [System.Environment]::GetEnvironmentVariable("Path", "User")
$ghCmd = Get-Command gh -ErrorAction SilentlyContinue
$gh = if ($ghCmd) { $ghCmd.Source } else { $null }
if (-not $gh -or -not (Test-Path -LiteralPath $gh)) {
  $gh = "C:\Program Files\GitHub CLI\gh.exe"
}
if (-not (Test-Path -LiteralPath $gh)) {
  Write-Error "Lipsește GitHub CLI. Rulează: winget install --id GitHub.cli -e"
}

$tmpAuthErr = [System.IO.Path]::GetTempFileName()
$p = Start-Process -FilePath $gh -ArgumentList @("auth", "status") -Wait -PassThru -NoNewWindow `
  -RedirectStandardError $tmpAuthErr
Remove-Item -LiteralPath $tmpAuthErr -Force -ErrorAction SilentlyContinue
if ($p.ExitCode -ne 0) {
  Write-Host ""
  Write-Host "Nu esti logat in gh. Ruleaza in acest terminal, apoi executa din nou acest script:"
  Write-Host "  gh auth login -h github.com -p https -w"
  Write-Host ""
  exit 1
}

$tmpUser = [System.IO.Path]::GetTempFileName()
$pApi = Start-Process -FilePath $gh -ArgumentList @("api", "user", "-q", ".login") `
  -Wait -NoNewWindow -PassThru -RedirectStandardOutput $tmpUser
if ($pApi.ExitCode -ne 0) {
  Remove-Item -LiteralPath $tmpUser -Force -ErrorAction SilentlyContinue
  Write-Error "gh api user a esuat (reia gh auth login)."
}
$user = (Get-Content -LiteralPath $tmpUser -Raw).Trim()
Remove-Item -LiteralPath $tmpUser -Force -ErrorAction SilentlyContinue
if (-not $user) {
  Write-Error "Utilizator GitHub gol."
}

$repo = "OSUCollectionManager"
$full = "${user}/${repo}"
$url = "https://github.com/${user}/${repo}.git"

$tmpViewErr = [System.IO.Path]::GetTempFileName()
$pView = Start-Process -FilePath $gh -ArgumentList @("repo", "view", $full) `
  -Wait -NoNewWindow -PassThru -RedirectStandardError $tmpViewErr
Remove-Item -LiteralPath $tmpViewErr -Force -ErrorAction SilentlyContinue
if ($pView.ExitCode -ne 0) {
  Write-Host "Creez repo public $full ..."
  $desc = "OSC: osu!Collector collections manager (lazer + stable)"
  $pCreate = Start-Process -FilePath $gh `
    -ArgumentList @("repo", "create", $repo, "--public", "-d", $desc) `
    -Wait -NoNewWindow -PassThru
  if ($pCreate.ExitCode -ne 0) {
    Write-Error "gh repo create a esuat."
  }
} else {
  Write-Host "Repo $full exista deja."
}

git remote remove origin 2>$null | Out-Null
git remote add origin $url

Write-Host "Push origin main -> $url"
git push -u origin main
if ($LASTEXITCODE -ne 0) {
  Write-Error "git push a eșuat."
}

Write-Host ""
Write-Host "Gata: https://github.com/$full"
Write-Host "GitHub: Settings / Actions / General - Workflow permissions: Read and write (release zip)."
Write-Host ""
