$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
uv run --no-project --with pandas --with pyarrow python research\options_nbbo_curriculum.py @args
