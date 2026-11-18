<#
Full pipeline on the university GPU machine (Windows):
  prepare -> sweep -> train-all -> evaluate -> report -> pack-results
Every step is skipped when already complete, so running this again after a crash or reboot
continues where it stopped. Full log with tracebacks: ml_research\runs\uni_run.log

  powershell -ExecutionPolicy Bypass -File ml_research\scripts\uni_run.ps1 -Raw ml_research\data\raw\kaggle_kebede\archive.zip
  (-Raw takes the zip (recommended) or the extracted folder)
  ... -Foreground          # run in this window instead of a separate minimized window
  ... -MaxTissueThreshold 255  # ablation only: override the protocol's tissue cap (default 40, ADR-0002)
  ... -ExtraArgs "--sweep-epochs","5"   # further options for `oscc-ml uni-run`

The background run opens its own minimized window. Do not close it and do not sign out of
Windows (lock the screen with Win+L instead); Windows is kept awake while it runs.
#>
param(
    [Parameter(Mandatory = $true)][string]$Raw,
    [switch]$Foreground,
    [int]$MaxTissueThreshold = -1,
    [string[]]$ExtraArgs = @()
)
$ML = Split-Path -Parent $PSScriptRoot
$Oscc = Join-Path $ML ".venv\Scripts\oscc-ml.exe"
$Log = Join-Path $ML "runs\uni_run.log"

if (-not (Test-Path $Oscc)) {
    Write-Host "RUN FAILED: ml_research\.venv missing -- FIX: run scripts\uni_setup.ps1 first" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Raw)) {
    Write-Host "RUN FAILED: $Raw not found -- FIX: give the full path to the Kaggle zip or extracted folder" -ForegroundColor Red
    exit 1
}
$RawFull = (Resolve-Path $Raw).Path
New-Item -ItemType Directory -Force (Join-Path $ML "runs") | Out-Null
$env:PYTHONIOENCODING = "utf-8"
$RunArgs = @("uni-run", "--raw", $RawFull) + $ExtraArgs
if ($MaxTissueThreshold -ge 0) { $RunArgs += @("--max-tissue-threshold", "$MaxTissueThreshold") }

if ($Foreground) {
    & $Oscc @RunArgs
    exit $LASTEXITCODE
}

# Quote every argument for the new process (paths may contain spaces).
$Quoted = $RunArgs | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }
$Process = Start-Process -FilePath $Oscc -ArgumentList $Quoted -WindowStyle Minimized -PassThru
Write-Host "Started in a separate minimized window (PID $($Process.Id))." -ForegroundColor Green
Write-Host "  Do not close that window and do not sign out; lock the screen with Win+L."
Write-Host "  Progress log: Get-Content -Wait `"$Log`""
