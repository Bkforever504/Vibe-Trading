import numpy as np
import pytest

from agent.analytics.paired_bootstrap import paired_diff_ci


def test_paired_diff_excludes_zero_flag():
    baseline = np.arange(20.0)
    result = paired_diff_ci(baseline, baseline - 10.0)
    assert result["diff_mean"] == -10.0
    assert result["excludes_zero"] is True


def test_paired_diff_includes_zero_flag():
    values = np.sin(np.arange(20.0))
    result = paired_diff_ci(values, values)
    assert result["excludes_zero"] is False


def test_length_mismatch_raises():
    with pytest.raises(ValueError, match="equal length"):
        paired_diff_ci([1, 2], [1])

