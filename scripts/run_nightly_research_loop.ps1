$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
Set-Location $repo

# Social/video collection is research-only. A provider outage must not stop the
# existing nightly evidence queue or alter any trading task.
try {
    & "$repo\scripts\run_agent_reach_trading_research.ps1"
}
catch {
    Write-Warning "Agent-Reach research intake unavailable: $($_.Exception.Message)"
}

uv run --no-project python scripts\nightly_research_loop.py --print
