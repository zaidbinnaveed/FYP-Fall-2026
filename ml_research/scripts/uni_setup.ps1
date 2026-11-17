<#
One-time setup on the university GPU machine (Windows). No admin rights needed.

  powershell -ExecutionPolicy Bypass -File ml_research\scripts\uni_setup.ps1
  powershell -ExecutionPolicy Bypass -File ml_research\scripts\uni_setup.ps1 -Cpu      # testing only
  ... -CudaTag cu132                                   # force a CUDA build
  ... -TorchVersion X -TorchvisionVersion Y -CudaTag cuNNN   # old driver; see docs/UNI_RUNBOOK.md

Installs uv for this user (if missing), Python 3.11 (managed by uv), a virtual environment in
ml_research\.venv, the locked dependencies with CUDA torch, and the oscc_ml package.
#>
param(
    [switch]$Cpu,
    [string]$CudaTag = "auto",
    [string]$TorchVersion = "",
    [string]$TorchvisionVersion = ""
)
$ErrorActionPreference = "Stop"
$ML = Split-Path -Parent $PSScriptRoot

function Fail([string]$What, [string]$Fix) {
    Write-Host "SETUP FAILED: $What -- FIX: $Fix" -ForegroundColor Red
    exit 1
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv for this user (no admin rights needed)..."
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Fail "could not download uv ($($_.Exception.Message))" "check the internet connection or proxy (HTTPS_PROXY)"
    }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail "uv is not on PATH" "open a new PowerShell window and run this script again"
}

uv python install 3.11
if ($LASTEXITCODE -ne 0) { Fail "could not install Python 3.11 with uv" "check the internet connection" }
$Py = Join-Path $ML ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    uv venv --python 3.11 (Join-Path $ML ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "could not create $ML\.venv" "check write access to $ML" }
}

$InstallArgs = @((Join-Path $ML "scripts\install_pinned.py"), "--python", $Py, "--extra", "train")
if ($Cpu) { $InstallArgs += @("--torch", "cpu") } else { $InstallArgs += @("--torch", "cuda", "--cuda-tag", $CudaTag) }
if ($TorchVersion) { $InstallArgs += @("--torch-version", $TorchVersion) }
if ($TorchvisionVersion) { $InstallArgs += @("--torchvision-version", $TorchvisionVersion) }

& $Py @InstallArgs
if ($LASTEXITCODE -ne 0) {
    Fail "dependency installation failed (see the lines above)" "fix the reported problem and run uni_setup again; it is safe to re-run"
}

if (-not $Cpu) {
    & $Py -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"
    if ($LASTEXITCODE -ne 0) { Fail "torch is installed but cannot see the GPU" "run nvidia-smi; update the NVIDIA driver if it fails" }
}

Write-Host ""
Write-Host "SETUP COMPLETE. Next: powershell -ExecutionPolicy Bypass -File ml_research\scripts\uni_check.ps1" -ForegroundColor Green
