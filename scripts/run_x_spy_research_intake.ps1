$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

# Manual/read-only by default. The Python client enforces one request per day
# and 20 requests per month unless Kenny explicitly changes those caps.
python scripts\x_spy_research_intake.py --max-results 10 --print
