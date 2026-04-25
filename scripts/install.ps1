# install.ps1 — piighost one-command installer for Windows
# Usage: irm https://raw.githubusercontent.com/jamon8888/hacienda-ghost/master/scripts/install.ps1 | iex
#
# Options (set before running):
#   $env:PIIGHOST_MODE   = "strict" (default) | "local"
#   $env:PIIGHOST_EXTRAS = "proxy,gliner2,mcp,index,cache" (default)
#   $env:PIIGHOST_SOURCE = PyPI package name or git URL (default: GitHub)

$ErrorActionPreference = 'Stop'

$MODE    = if ($env:PIIGHOST_MODE)   { $env:PIIGHOST_MODE }   else { "strict" }
$EXTRAS  = if ($env:PIIGHOST_EXTRAS) { $env:PIIGHOST_EXTRAS } else { "proxy,gliner2,mcp,index,cache" }
$SOURCE  = if ($env:PIIGHOST_SOURCE) { $env:PIIGHOST_SOURCE } else { "git+https://github.com/jamon8888/hacienda-ghost.git" }

Write-Host ""
Write-Host "piighost installer" -ForegroundColor Cyan
Write-Host "  mode   : $MODE"
Write-Host "  extras : $EXTRAS"
Write-Host "  source : $SOURCE"
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Ensure uv is present
# ---------------------------------------------------------------------------
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[1/4] Installing uv..." -ForegroundColor Yellow
    irm https://astral.sh/uv/install.ps1 | iex
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
} else {
    Write-Host "[1/4] uv already installed" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 2. Stop any running piighost service before (re)install
# ---------------------------------------------------------------------------
Write-Host "[2/4] Stopping existing piighost service (if any)..." -ForegroundColor Yellow
schtasks /end /tn "piighost-proxy" 2>$null | Out-Null
Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*uvicorn*piighost*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue

# ---------------------------------------------------------------------------
# 3. Install piighost with all requested extras
# ---------------------------------------------------------------------------
Write-Host "[3/4] Installing piighost[$EXTRAS]..." -ForegroundColor Yellow
$pkg = "piighost[$EXTRAS] @ $SOURCE"
uv tool install --reinstall $pkg --python 3.12

# Refresh PATH so piighost binary is available
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("PATH","User")

# ---------------------------------------------------------------------------
# 4. Run the system installer
# ---------------------------------------------------------------------------
Write-Host "[4/4] Running: piighost install --mode=$MODE ..." -ForegroundColor Yellow
piighost install --mode=$MODE

Write-Host ""
Write-Host "Done! piighost is installed in $MODE mode." -ForegroundColor Green
Write-Host "Run 'piighost doctor' to verify everything is working." -ForegroundColor Cyan
