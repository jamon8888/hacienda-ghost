# install.ps1 — piighost one-command installer for Windows
# Usage: irm https://piighost.dev/install.ps1 | iex
$ErrorActionPreference = 'Stop'

$EXTRAS = "mcp,index,gliner2"

# 1. Ensure uv is present
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    irm https://astral.sh/uv/install.ps1 | iex
    # Refresh PATH so uv is visible
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
}

# 2. Install piighost
Write-Host "Installing piighost[$EXTRAS]..."
uv tool install "piighost[$EXTRAS]" --python 3.12

# 3. Run the Python installer
Write-Host "Running piighost install --full ..."
piighost install --full
