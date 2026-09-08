param([string]$PythonPath = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$vibeHome = "C:\Users\kenne\.vibe-trading"
$logPath = Join-Path $vibeHome "logs\catalyst-tape-shadow.log"
$secReport = Join-Path $vibeHome "reports\sec-latest-filings-shadow.json"
$tapeReport = Join-Path $vibeHome "reports\catalyst-symbol-tape-shadow.json"
$joinedReport = Join-Path $vibeHome "reports\catalyst-tape-shadow.json"
$radarReport = Join-Path $vibeHome "reports\intraday-opportunity-radar.json"
$issuerSymbols = "AAPL,MSFT,NVDA,AMZN,META,GOOGL,TSLA,AMD,AVGO,NFLX,ADBE,CRM,ORCL,INTC,MU,QCOM,AMAT,LRCX,PLTR,CRWD,PANW,SNOW,COIN,MSTR,HOOD,SHOP,SQ,PYPL,SOFI,UBER,RDDT,RIVN,GME,AMC,BABA,PDD,JPM,BAC,GS,WFC,AXP,CAT,DE,BA,GE,F,GM,NKE,COST,WMT,TGT,HD,LOW,LLY,NVO,UNH,JNJ,MRK,PFE,ABBV,AMGN,GILD,MRNA,BMY,REGN,XOM,CVX,OXY,SLB,FCX,NEM,IREN,APLD,WULF,SNDK"

Set-Location -LiteralPath $repo
if (Test-Path -LiteralPath (Join-Path $repo "KILL_SWITCH")) {
    Write-Warning "KILL_SWITCH present. Catalyst tape shadow skipped."
    exit 0
}

. (Join-Path $repo "scripts\resolve_vibe_python.ps1")
$python = Get-VibePython -PythonPath $PythonPath
$envPath = Join-Path $repo "agent\.env"
if (-not $env:SEC_USER_AGENT -and (Test-Path -LiteralPath $envPath)) {
    $line = Get-Content -LiteralPath $envPath | Where-Object { $_ -match '^SEC_USER_AGENT=' } | Select-Object -First 1
    if ($line) { $env:SEC_USER_AGENT = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'") }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $logPath) | Out-Null
"$(Get-Date -Format o) START shadow_only=true" | Out-File -LiteralPath $logPath -Append -Encoding utf8
$worst = 0

& $python scripts\sec_latest_filings_shadow.py --symbols $issuerSymbols --report $secReport 2>&1 | Out-File -LiteralPath $logPath -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { $worst = $LASTEXITCODE }

& $python scripts\catalyst_symbol_tape_shadow.py --sec-report $secReport --radar-report $radarReport --report $tapeReport --alert 2>&1 | Out-File -LiteralPath $logPath -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { $worst = $LASTEXITCODE }

& $python scripts\catalyst_tape_shadow.py --catalysts $secReport --tape $tapeReport --plans $radarReport --prior-report $joinedReport --out $joinedReport 2>&1 | Out-File -LiteralPath $logPath -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { $worst = $LASTEXITCODE }

& $python scripts\generate_dashboard.py 2>&1 | Out-File -LiteralPath $logPath -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { $worst = $LASTEXITCODE }
"$(Get-Date -Format o) END exit_code=$worst" | Out-File -LiteralPath $logPath -Append -Encoding utf8
exit $worst
