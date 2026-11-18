<#
Readiness check on the university GPU machine (Windows): Python, GPU name and VRAM, free disk,
write access, pretrained-weight downloads, then a ~2-minute GPU smoke run of all four models.
Output is also saved to ml_research\runs\uni_check.log (send that file if something fails).

  powershell -ExecutionPolicy Bypass -File ml_research\scripts\uni_check.ps1
  ... -AllowCpu -SkipDownload -MinFreeGb 1 -BudgetSeconds 30 -BatchSize 4    # CI only
#>
param(
    [switch]$AllowCpu,
    [switch]$SkipDownload,
    [double]$MinFreeGb = 40,
    [double]$BudgetSeconds = 120,
    [int]$BatchSize = 0
)
$ML = Split-Path -Parent $PSScriptRoot
$Oscc = Join-Path $ML ".venv\Scripts\oscc-ml.exe"
if (-not (Test-Path $Oscc)) {
    Write-Host "CHECK FAILED: ml_research\.venv is missing or incomplete -- FIX: run ml_research\scripts\uni_setup.ps1 first" -ForegroundColor Red
    exit 1
}
New-Item -ItemType Directory -Force (Join-Path $ML "runs") | Out-Null
$CheckArgs = @("check", "--min-free-gb", $MinFreeGb, "--budget-seconds", $BudgetSeconds)
if ($AllowCpu) { $CheckArgs += "--allow-cpu" }
if ($SkipDownload) { $CheckArgs += "--skip-download" }
if ($BatchSize -gt 0) { $CheckArgs += @("--batch-size", $BatchSize) }

$env:PYTHONIOENCODING = "utf-8"
& $Oscc @CheckArgs 2>&1 | Tee-Object -FilePath (Join-Path $ML "runs\uni_check.log")
exit $LASTEXITCODE
