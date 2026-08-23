$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$AgentPath = Join-Path $RepoRoot "agent"
$Python = (Get-Command python -ErrorAction Stop).Source
$Code = "import sys; sys.path.insert(0, r'$AgentPath'); import cli; raise SystemExit(cli.main(['serve','--host','127.0.0.1','--port','8899']))"

Set-Location $RepoRoot
& $Python -c $Code
