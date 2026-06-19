"""Unit tests for strategy.finlab_factors pure factor functions.

Covers RSI bounds/direction, breakout ratio, and cross-sectional rank outputs
(all expected to be in [0, 1] and shape-preserving).
"""
import numpy as np
import pandas as pd
import pytest

from strategy.finlab_factors import (
    compute_rsi,
    compute_rsi_rank,
    compute_breakout,
    compute_breakout_rank,
    compute_revenue_momentum,
)


def _panel(n_days=120, n_tickers=5, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n_days, freq="B")
    cols = [f"S{i}" for i in range(n_tickers)]
    # Geometric random walk, strictly positive prices
    steps = rng.normal(0.0005, 0.02, size=(n_days, n_tickers))
    prices = 100 * np.exp(np.cumsum(steps, axis=0))
    return pd.DataFrame(prices, index=idx, columns=cols)


def test_rsi_within_bounds():
    rsi = compute_rsi(_panel(), period=20)
    valid = rsi.dropna(how="all")
    assert ((valid.stack() >= 0) & (valid.stack() <= 100)).all()


def test_rsi_monotonic_series_direction():
    idx = pd.date_range("2020-01-01", periods=60, freq="B")
    up = pd.DataFrame({"A": np.linspace(10, 50, 60)}, index=idx)
    down = pd.DataFrame({"A": np.linspace(50, 10, 60)}, index=idx)
    rsi_up = compute_rsi(up, period=14).iloc[-1, 0]
    rsi_down = compute_rsi(down, period=14).iloc[-1, 0]
    assert rsi_up > 95   # all gains -> RSI near 100
    assert rsi_down < 5   # all losses -> RSI near 0


def test_breakout_at_new_high_is_one():
    idx = pd.date_range("2020-01-01", periods=200, freq="B")
    rising = pd.DataFrame({"A": np.linspace(10, 100, 200)}, index=idx)
    bo = compute_breakout(rising, window=50)
    # Last bar is the all-time high -> ratio ~1.0
    assert bo.iloc[-1, 0] == pytest.approx(1.0, abs=1e-6)
    # Ratio never materially exceeds 1
    assert bo.dropna().to_numpy().max() <= 1.0 + 1e-6


@pytest.mark.parametrize("fn", [compute_rsi_rank, compute_breakout_rank,
                                compute_revenue_momentum])
def test_rank_outputs_in_unit_interval(fn):
    df = _panel()
    ranked = fn(df)
    vals = ranked.stack()
    assert ranked.shape == df.shape
    assert ((vals >= 0) & (vals <= 1)).all()


def test_universe_mask_excludes_tickers():
    df = _panel()
    mask = pd.DataFrame(True, index=df.index, columns=df.columns)
    mask["S0"] = False
    ranked = compute_rsi_rank(df, universe_mask=mask)
    # Masked ticker must be NaN everywhere it was excluded
    assert ranked["S0"].isna().all()
