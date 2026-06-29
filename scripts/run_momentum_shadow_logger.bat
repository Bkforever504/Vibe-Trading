@echo off
cd /d "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
"C:\Users\kenne\.local\bin\uv.exe" run --no-project --with alpaca-py --with pandas python scripts\momentum_shadow_logger.py >> "C:\Users\kenne\.vibe-trading\logs\momentum-shadow.log" 2>&1
