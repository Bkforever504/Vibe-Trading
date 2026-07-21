Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
Set-Location $repo

uv run --no-project --with pyarrow --with pandas --with numpy `
  python research\mes_quote_exhaustion_lab.py

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
