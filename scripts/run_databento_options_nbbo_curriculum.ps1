$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$fetchOutput = uv run --no-project --with databento --with pandas --with pyarrow --with tzdata `
    python scripts\fetch_databento_options_nbbo.py @args 2>&1
$fetchExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
$fetchOutput | Write-Output
if ($fetchExitCode -ne 0) {
    exit $fetchExitCode
}

if ($args -contains "--download") {
    python research\options_nbbo_curriculum.py `
        --quotes data\databento\options_nbbo_candidate_quotes.jsonl
    $curriculumExitCode = $LASTEXITCODE
    if ($curriculumExitCode -ne 0) {
        exit $curriculumExitCode
    }
    python scripts\options_edge_attribution_report.py
    exit $LASTEXITCODE
}
