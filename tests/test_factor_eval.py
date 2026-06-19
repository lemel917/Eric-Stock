"""Tests for strategy.factor_eval (OPT-03 / OPT-04).

Uses deterministic constructions: a factor equal to the forward return must
have IC == 1 (perfect predictor); its negation must have IC == -1. This pins
the IC / quantile-spread math without relying on noisy randomness.
"""
import numpy as np
import pandas as pd
import pytest

from strategy.factor_eval import (
    zscore_normalize,
    forward_returns,
    information_coefficient,
    ic_summary,
    quantile_long_short,
    ic_by_horizon,
)


def _close_panel(n_days=60, n_tickers=10, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n_days, freq="B")
    cols = [f"S{i}" for i in range(n_tickers)]
    steps = rng.normal(0.0005, 0.02, size=(n_days, n_tickers))
    close = 100 * np.exp(np.cumsum(steps, axis=0))
    return pd.DataFrame(close, index=idx, columns=cols)


def test_zscore_normalize_row_stats():
    df = pd.DataFrame([[1.0, 2, 3, 4, 5], [10, 20, 30, 40, 50]])
    z = zscore_normalize(df)
    assert np.isclose(z.iloc[0].mean(), 0, atol=1e-9)
    assert np.isclose(z.iloc[0].std(ddof=1), 1, atol=1e-9)
    assert np.isclose(z.iloc[1].mean(), 0, atol=1e-9)


def test_forward_returns():
    close = pd.DataFrame({"A": [10.0, 11.0, 12.0, 13.0, 14.0]})
    fwd = forward_returns(close, horizon=2)
    assert fwd["A"].iloc[0] == pytest.approx(12 / 10 - 1)
    assert fwd["A"].iloc[1] == pytest.approx(13 / 11 - 1)
    assert pd.isna(fwd["A"].iloc[3])  # last `horizon` rows undefined


def test_perfect_factor_has_ic_one():
    close = _close_panel()
    factor = forward_returns(close, horizon=5)  # factor == the label
    ic = information_coefficient(factor, close, horizon=5)
    summ = ic_summary(ic)
    assert summ["ic_mean"] == pytest.approx(1.0, abs=1e-9)
    assert summ["hit_rate"] == pytest.approx(1.0)
    assert summ["n_periods"] > 0


def test_inverse_factor_has_ic_negative_one():
    close = _close_panel()
    factor = -forward_returns(close, horizon=5)
    summ = ic_summary(information_coefficient(factor, close, horizon=5))
    assert summ["ic_mean"] == pytest.approx(-1.0, abs=1e-9)


def test_quantile_long_short_positive_and_monotonic_for_good_factor():
    close = _close_panel()
    factor = forward_returns(close, horizon=5)
    res = quantile_long_short(factor, close, horizon=5, n_quantiles=5)
    q = res["quantile_returns"]
    assert res["long_short_mean"] > 0          # top beats bottom
    assert q[-1] > q[0]                          # high-factor quantile earns more


def test_ic_by_horizon_keys_and_shape():
    close = _close_panel()
    factor = forward_returns(close, horizon=5)
    out = ic_by_horizon(factor, close, horizons=(1, 5, 20))
    assert set(out.keys()) == {1, 5, 20}
    assert {"ic_mean", "icir", "t_stat", "hit_rate"} <= set(out[5].keys())


def test_ic_summary_empty_is_safe():
    summ = ic_summary(pd.Series(dtype=float))
    assert summ["n_periods"] == 0
    assert summ["icir"] == 0.0
