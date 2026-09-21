<#
  AutoCAD AI Automation : repair environment and start the server.

  Finds a usable Python on this machine, then either
    (a) repoints the existing venv at it, keeping all installed packages, or
    (b) builds a fresh venv and installs requirements.txt,
  then starts uvicorn and opens the chat page.

  Run from anywhere:
    powershell -ExecutionPolicy Bypass -File C:\RC-Projects\autocad-ai\autocad-ai\setup-and-start.ps1
#>

$ErrorActionPreference = 'Continue'

$Proj   = 'C:\RC-Projects\autocad-ai\autocad-ai'
$VenvPy = Join-Path $Proj 'venv\Scripts\python.exe'
$Cfg    = Join-Path $Proj 'venv\pyvenv.cfg'
$Deps   = "import fastapi, uvicorn, ezdxf, jsonschema, openai, win32com.client; print('deps ok')"

function Say([string]$m) { Write-Host "  $m" }
function Head([string]$m) { Write-Host ""; Write-Host "  $m" -ForegroundColor Cyan }

Head 'AutoCAD AI Automation : environment check'

if (-not (Test-Path $Proj)) { Say "Project folder not found: $Proj"; Read-Host 'Enter to exit'; exit 1 }
Set-Location $Proj
Say "Project : $Proj"

# ---------------------------------------------------------------- find pythons
Head 'Looking for a Python interpreter'

$cand = New-Object System.Collections.Generic.List[string]

try {
  $pyList = & py -0p 2>$null
  if ($pyList) {
    foreach ($line in $pyList) {
      $m = [regex]::Match([string]$line, '[A-Za-z]:\\[^\r\n]*?python\.exe')
      if ($m.Success) { $cand.Add($m.Value) }
    }
  }
} catch { }

try {
  $w = & where.exe python 2>$null
  if ($w) { foreach ($p in $w) { $cand.Add([string]$p) } }
} catch { }

$globs = @(
  "$env:LOCALAPPDATA\Python\pythoncore-*\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
  "$env:ProgramFiles\Python3*\python.exe",
  "C:\Python3*\python.exe"
)
foreach ($g in $globs) {
  Get-ChildItem -Path $g -ErrorAction SilentlyContinue | ForEach-Object { $cand.Add($_.FullName) }
}

$found = @()
foreach ($p in ($cand | Select-Object -Unique)) {
  if ([string]::IsNullOrWhiteSpace($p)) { continue }
  if ($p -like '*WindowsApps*') { continue }          # Store alias stub, not a real interpreter
  if ($p -like "$Proj*") { continue }                 # skip the broken venv itself
  if (-not (Test-Path $p)) { continue }
  $v = & $p -c "import sys;print('%d.%d.%d' % sys.version_info[:3])" 2>$null
  if ($LASTEXITCODE -eq 0 -and $v) {
    $ver = [version]([string]$v).Trim()
    $found += [pscustomobject]@{ Exe = $p; Ver = $ver }
    Say ("{0}  ->  {1}" -f $ver, $p)
  }
}

if ($found.Count -eq 0) {
  Head 'No Python found'
  Say 'Install Python 3.14 (or 3.12/3.13) from python.org or the Microsoft Store,'
  Say 'tick "Add python.exe to PATH", then run this script again.'
  Read-Host '  Enter to exit'
  exit 1
}

# ------------------------------------------------------------- fast path: 3.14
$match314 = $found | Where-Object { $_.Ver.Major -eq 3 -and $_.Ver.Minor -eq 14 } |
            Sort-Object Ver -Descending | Select-Object -First 1

$ready = $false

if ($match314 -and (Test-Path $Cfg)) {
  Head 'Found Python 3.14 : repointing the existing venv (keeps installed packages)'
  $exe  = $match314.Exe
  $home = Split-Path $exe -Parent
  Copy-Item $Cfg "$Cfg.bak" -Force -ErrorAction SilentlyContinue
  @(
    "home = $home",
    'include-system-site-packages = false',
    ("version = " + $match314.Ver.ToString()),
    "executable = $exe"
  ) | Set-Content -Path $Cfg -Encoding ASCII
  Say "pyvenv.cfg now points at $exe"

  $probe = & $VenvPy -c $Deps 2>&1
  if ($LASTEXITCODE -eq 0) { Say 'Existing packages import cleanly.'; $ready = $true }
  else { Say 'Packages did not import, falling back to a rebuild.'; Say ([string]$probe) }
}

# ------------------------------------------------------------------- rebuild
if (-not $ready) {
  $pick = $found | Where-Object { $_.Ver -ge [version]'3.11.0' } |
          Sort-Object Ver -Descending | Select-Object -First 1
  if (-not $pick) { Head 'Python 3.11 or newer is required'; Read-Host '  Enter to exit'; exit 1 }

  Head ("Rebuilding the virtual environment with Python " + $pick.Ver)
  if (Test-Path (Join-Path $Proj 'venv')) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Rename-Item (Join-Path $Proj 'venv') "venv-broken-$stamp"
    Say "Old venv renamed to venv-broken-$stamp (delete it whenever you like)"
  }

  & $pick.Exe -m venv (Join-Path $Proj 'venv')
  if (-not (Test-Path $VenvPy)) { Say 'venv creation failed.'; Read-Host '  Enter to exit'; exit 1 }

  Say 'Upgrading pip'
  & $VenvPy -m pip install --upgrade pip --quiet

  Say 'Installing requirements.txt (numpy and scipy take a few minutes)'
  & $VenvPy -m pip install -r (Join-Path $Proj 'requirements.txt')
  if ($LASTEXITCODE -ne 0) {
    Head 'Install failed'
    Say 'Most likely a pinned version has no wheel for this Python and pip tried to compile.'
    Say 'Send the last 20 lines above to Claude and it will relax the pins that need it.'
    Read-Host '  Enter to exit'
    exit 1
  }

  $probe = & $VenvPy -c $Deps 2>&1
  if ($LASTEXITCODE -ne 0) { Head 'Dependencies still not importing'; Say ([string]$probe); Read-Host '  Enter to exit'; exit 1 }
  Say 'Dependencies installed.'
}

# ------------------------------------------------------------------ env check
Head 'Checking configuration'
$envFile = Join-Path $Proj '.env'
if (-not (Test-Path $envFile)) {
  Say 'WARNING: no .env file. AI planning will fail. Needs AI_PROVIDER and DEEPSEEK_API_KEY.'
} else {
  $envText = Get-Content $envFile -Raw
  if ($envText -notmatch 'DEEPSEEK_API_KEY\s*=\s*\S' -or $envText -match 'your_api_key_here') {
    Say 'WARNING: DEEPSEEK_API_KEY looks unset. Sketch prompts will error and'
    Say 'P&ID / 3D prompts will silently fall back to built-in templates.'
  } else {
    Say '.env has an API key set.'
  }
}

$app = & $VenvPy -c "from src.api.main import app; print('api import OK')" 2>&1
if ($LASTEXITCODE -ne 0) { Head 'The app itself failed to import'; Say ([string]$app); Read-Host '  Enter to exit'; exit 1 }
Say ([string]$app)

# --------------------------------------------------------------------- serve
Head 'Starting the server'
Say 'Chat UI   : http://127.0.0.1:8000/sketch.html'
Say 'COM check : http://127.0.0.1:8000/api/autocad-status'
Say 'Open AutoCAD with a drawing before you press Build in AutoCAD.'
Say 'Leave this window open. Ctrl+C stops the server.'
Write-Host ""

Start-Job -ScriptBlock {
  Start-Sleep -Seconds 6
  Start-Process 'http://127.0.0.1:8000/sketch.html'
} | Out-Null

& $VenvPy -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000

Write-Host ""
Say 'Server stopped.'
Read-Host '  Enter to exit'
