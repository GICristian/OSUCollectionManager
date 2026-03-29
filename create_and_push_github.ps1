# Creează repo-ul OSUCollectionManager pe GitHub (dacă lipsește) și face push pe main.
# O data, inainte: gh auth login -h github.com -p https -w
# (ASCII-only strings: evita erori de parsare in Windows PowerShell 5.1)

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
  Write-Error "Lipseste GitHub CLI. Ruleaza: winget install --id GitHub.cli -e"
}

$ghDataDir = Join-Path $env:APPDATA "GitHub CLI"
$hasGhConfig = Test-Path -LiteralPath $ghDataDir

$skipAuthStatus = -not [string]::IsNullOrWhiteSpace($env:GH_TOKEN)
if (-not $skipAuthStatus) {
  $tmpAuthErr = [System.IO.Path]::GetTempFileName()
  $p = Start-Process -FilePath $gh -ArgumentList @("auth", "status") -Wait -PassThru -NoNewWindow `
    -RedirectStandardError $tmpAuthErr
  Remove-Item -LiteralPath $tmpAuthErr -Force -ErrorAction SilentlyContinue
  if ($p.ExitCode -ne 0) {
    Write-Host ""
    Write-Host "=== GitHub CLI (gh) nu este autentificat pe acest profil Windows ==="
    Write-Host ""
    Write-Host "Contul din Cursor / github.com NU este acelasi lucru cu gh CLI."
    Write-Host "Ruleaza login-ul pentru gh in acelasi terminal unde rulezi acest script."
    Write-Host ""
    Write-Host "Folosesc gh de la:"
    Write-Host "  $gh"
    Write-Host ""
    if (-not $hasGhConfig) {
      Write-Host "Lipseste folderul: $ghDataDir"
      Write-Host "(inca nu s-a terminat niciun gh auth login aici.)"
      Write-Host ""
    }
    Write-Host "Ruleaza (se deschide browserul):"
    Write-Host ('  & "' + $gh + '" auth login -h github.com -p https -w')
    Write-Host ""
    Write-Host "Verificare:"
    Write-Host ('  & "' + $gh + '" auth status')
    Write-Host ""
    Write-Host "Alternativa: variabila de mediu GH_TOKEN (PAT cu scope repo)."
    Write-Host ""
    exit 1
  }
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
  # Start-Process -ArgumentList poate sparge gresit flag-urile pentru gh; folosim apel direct.
  $desc = "OSC osu Collector manager (lazer and stable)"
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $createOut = & $gh @("repo", "create", $repo, "--public", "--description", $desc) 2>&1
  $createOk = $?
  $ErrorActionPreference = $prevEap
  if ($null -ne $createOut) {
    $createOut | ForEach-Object { Write-Host $_ }
  }
  if (-not $createOk) {
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
  Write-Error "git push a esuat."
}

Write-Host ""
Write-Host "Gata: https://github.com/$full"
Write-Host "GitHub: Settings / Actions / General - Workflow permissions Read and write (release zip)."
Write-Host ""
