import numpy as np
import pandas as pd

from validation.deflated_sharpe import compute_deflated_sharpe
from validation.pbo_cscv import compute_pbo


def test_deflated_sharpe_rewards_persistent_positive_returns():
    returns = np.array([0.010, -0.002] * 160)

    result = compute_deflated_sharpe(returns, n_trials=1)

    assert result.sharpe > 0
    assert result.probability > 0.95


def test_deflated_sharpe_penalizes_multiple_trials():
    returns = np.array([0.004, -0.002] * 160)

    one_trial = compute_deflated_sharpe(returns, n_trials=1)
    many_trials = compute_deflated_sharpe(returns, n_trials=100)

    assert many_trials.expected_max_sharpe > one_trial.expected_max_sharpe
    assert many_trials.probability < one_trial.probability


def test_pbo_cscv_returns_probability_and_split_details():
    idx = pd.date_range("2024-01-01", periods=32, freq="D")
    returns = pd.DataFrame(
        {
            "steady": [0.001, 0.002, -0.001, 0.001] * 8,
            "boom_bust": [0.010] * 16 + [-0.010] * 16,
            "late": [-0.004] * 16 + [0.006] * 16,
            "flat": [0.0, 0.001, 0.0, -0.001] * 8,
        },
        index=idx,
    )

    result = compute_pbo(returns, n_splits=8)

    assert 0 <= result.pbo <= 1
    assert result.n_trials == 4
    assert result.n_observations == 32
    assert result.logits
    assert result.split_results

