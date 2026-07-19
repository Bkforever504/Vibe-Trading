from __future__ import annotations

import numpy as np
import pandas as pd

from research.momentum_rotation_forward_extension import evaluate_forward


def test_forward_extension_reports_metrics_and_holdings() -> None:
    index = pd.date_range("2023-01-02", periods=900, freq="B")
    universe = pd.DataFrame(
        {
            "UP": 100.0 * np.cumprod(np.full(len(index), 1.001)),
            "SLOW": 100.0 * np.cumprod(np.full(len(index), 1.0002)),
            "DOWN": 100.0 * np.cumprod(np.full(len(index), 0.9995)),
        },
        index=index,
    )
    result = evaluate_forward(universe)
    assert result["metrics"]["total_return_pct"] > 0
    assert result["latest_holdings"] == ["UP", "SLOW"]
