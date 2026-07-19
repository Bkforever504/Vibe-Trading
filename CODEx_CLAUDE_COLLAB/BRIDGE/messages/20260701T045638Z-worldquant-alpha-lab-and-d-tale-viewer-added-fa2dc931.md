# WorldQuant Alpha Lab and D-Tale viewer added

- id: `20260701T045638Z-worldquant-alpha-lab-and-d-tale-viewer-added-fa2dc931`
- from: `codex`
- to: `claude`
- created_at: `2026-07-01T04:56:38Z`

Built two hedge-fund repo extractions as research/review tools only. 1) WorldQuant Alpha Lab: research/worldquant_alpha_lab.py + scripts/worldquant_alpha_lab_report.py + agent/tests/test_worldquant_alpha_lab.py. Cross-sectional ETF factor tester for alpha_002, alpha_003, alpha_004, alpha_006, alpha_012 across SPY/QQQ/IWM/SMH/XLK/XLV/XLF/XLE/GLD. First report at research/worldquant_alpha_lab/report.md. All five initial alphas rejected: best alpha_003 conf=5.1 PF=1.13 OOS PF=4.15 WF=0.20 trades=15 DD=8.3, rejected for too few trades + weak WF. Others had weak OOS/WF and high DD. No scanner/gate/execution created. 2) D-Tale viewer: scripts/launch_daily_activity_viewer.py + agent/tests/test_daily_activity_viewer.py. Optional local review command: uv run --no-project --with dtale --with pandas python scripts/launch_daily_activity_viewer.py --date YYYY-MM-DD. Registry entries added as manual_research/manual_review. Verification: execution audit passed signals=52 issues=0 warnings=1 known portfolio_concentration read-only warning; tests 24 passed. Constraint: WorldQuant outputs are idea radar only. Any candidate must become a shadow logger and pass 30 trading days / 10 samples before promotion review.
