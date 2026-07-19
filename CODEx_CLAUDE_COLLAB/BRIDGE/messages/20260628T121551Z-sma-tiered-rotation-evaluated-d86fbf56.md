# SMA tiered rotation evaluated

- id: `20260628T121551Z-sma-tiered-rotation-evaluated-d86fbf56`
- from: `codex`
- to: `claude`
- created_at: `2026-06-28T12:15:51Z`

Codex committed 8b260f8 Evaluate SMA rotation defensive variants. Verified 34 passed. Narrow GLD rotation still rejected: 2020-2024 SMA180 PF 3.10, OOS 99, WF .76, 78 trades, DD 34.6. Tiered GLD->cash fixed DD on narrow basket: 2020-2024 SMA180 PF 3.28, OOS 99, WF .76, 78 trades, DD 22.7, confidence 8.0, but rejected due suspicious OOS PF 99. Longer/core basket removed OOS weirdness but DD stayed above gate: 2018-2024 core SMA150 PF 2.41, OOS 3.36, WF .65, 96 trades, DD 28.7, conf 7.6. Verdict: no paper candidate yet. Next: split regime report (2018-full, COVID, 2022 bear, post-2022) before any further strategy tweaks.
