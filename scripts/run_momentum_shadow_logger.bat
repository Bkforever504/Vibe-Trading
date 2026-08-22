@echo off
cd /d "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
"C:\Users\kenne\.local\bin\uv.exe" run --no-project --with alpaca-py --with pandas --with yfinance python scripts\momentum_shadow_logger.py >> "C:\Users\kenne\.vibe-trading\logs\momentum-shadow.log" 2>&1
if errorlevel 1 exit /b %errorlevel%
"C:\Users\kenne\.local\bin\uv.exe" run --no-project --with pandas --with yfinance python scripts\momentum_edge_ensemble_shadow.py >> "C:\Users\kenne\.vibe-trading\logs\momentum-shadow.log" 2>&1
