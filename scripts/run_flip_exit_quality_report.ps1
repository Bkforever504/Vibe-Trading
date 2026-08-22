$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repo
$env:PYTHONPATH = $repo
python scripts\flip_path_telemetry_completeness.py
if ($LASTEXITCODE -ne 0) {
    throw "Flip path telemetry completeness report failed with exit code $LASTEXITCODE"
}
python scripts\flip_exit_quality_report.py
exit $LASTEXITCODE
