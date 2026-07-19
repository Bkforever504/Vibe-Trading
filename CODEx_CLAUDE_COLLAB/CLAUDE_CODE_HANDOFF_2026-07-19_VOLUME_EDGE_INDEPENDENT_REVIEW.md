# Claude Code Handoff: Volume Edge Independent Review

Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Objective

Independently audit Codex's volume-indicator research. Do not optimize additional parameters against the same holdout and do not enable execution.

## Read First

1. `research/VOLUME_INDICATOR_EDGE_RESEARCH_2026-07-19.md`
2. `research/volume_overlay_lab.py`
3. `research/spy_orb_volume_lab.py`
4. `research/volume_candidate_validation.py`
5. `research/shadow_volume_coverage.py`
6. `scripts/rsi2_shadow_logger.py`

Reports:

- `~/.vibe-trading/reports/volume-overlay-lab.json`
- `~/.vibe-trading/reports/spy-orb-volume-lab.json`
- `~/.vibe-trading/reports/volume-candidate-validation.json`
- `~/.vibe-trading/reports/shadow-volume-coverage.json`

## Codex Result

- 396 configurations tested.
- QQQ RSI2 plus RVOL, volume z-score, volume oscillator, or MAVD is the only promising daily family.
- The family was negative in 2022 and 2023 and has only 15 to 27 holdout trades per filter.
- SPY 15-minute ORB plus aligned CMF produced 0.0806R holdout expectancy over 140 trades, but bootstrap CI crosses zero and doubled costs reduce it to 0.0039R.
- No candidate is high-confidence ready or forward-promotion ready.
- RSI2 logger now records candidate flags as telemetry only. Signal behavior is unchanged.

## Tasks

1. Audit for lookahead, timestamp alignment, split leakage, survivorship, and incorrect cost application.
2. Recompute the leading QQQ results with a stationary or moving-block bootstrap rather than IID trade bootstrap.
3. Apply a multiple-testing correction or White Reality Check style assessment across the full tested family.
4. Verify the 2022 and 2023 failure regimes and propose one preregistered regime hypothesis only if supported before rerunning.
5. Review every row in the shadow coverage report and identify any logger that can be fairly replayed without inventing exits.
6. Add tests for any confirmed bug. Do not broaden strategy parameters merely to improve the score.

## Acceptance Standard

- No live or paper order authority added.
- Conclusions separate stock-return replay from option-fill feasibility.
- Any surviving candidate must state sample size, uncertainty interval, costs, negative regimes, and remaining forward gate.
- Write findings to `CODEx_CLAUDE_COLLAB/CLAUDE_REVIEW_2026-07-19_VOLUME_EDGE.md`.
