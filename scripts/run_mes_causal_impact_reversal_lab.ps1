param(
    [switch]$ForceCache
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = "python"

$Arguments = @(
    (Join-Path $RepoRoot "research\mes_causal_impact_reversal_lab.py")
)
if ($ForceCache) {
    $Arguments += "--force-cache"
}

& $Python @Arguments
exit $LASTEXITCODE
