$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repo
uv run --no-project python scripts\flip_path_telemetry_completeness.py --print
