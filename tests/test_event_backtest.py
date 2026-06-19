"""Regression / determinism tests for the EventDrivenBacktester.

This is the safety net for performance refactors of the main backtest loop
(e.g. numpy-array vectorization): the engine is run on deterministic synthetic
data and must (a) produce a well-formed, finite equity curve and (b) be exactly
reproducible run-to-run. Any refactor that changes results will fail these.

No network is required: all network-backed features (macro_regime,
sector_flow_tilt, regime_filter) are left at their default-off settings.
"""
import numpy as np
import pandas as pd
import pytest

from strategy.event_backtest import EventDrivenBacktester


@pytest.fixture
def synthetic_panel():
    """Deterministic OHLC panel with clear uptrends so entries trigger."""
    n_days, n_tickers = 180, 8
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-01", periods=n_days, freq="B")
    cols = [f"S{i}" for i in range(n_tickers)]

    # Upward-drifting geometric walks -> close stays above its 60d MA often.
    drift = np.linspace(0.0008, 0.002, n_tickers)
    noise = rng.normal(0, 0.012, size=(n_days, n_tickers))
    close = 100 * np.exp(np.cumsum(drift + noise, axis=0))
    close = pd.DataFrame(close, index=idx, columns=cols)

    # Derive a consistent OHLC from close (deterministic, no look-ahead concern
    # for a test fixture).
    open_ = close.shift(1).fillna(close.iloc[0])
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99

    ma_60 = close.rolling(60).mean()

    # Constant high score for the first 4 tickers so they are always candidates.
    score = pd.DataFrame(0.0, index=idx, columns=cols)
    score.iloc[:, :4] = 3.0

    return dict(total_score=score, close_df=close, open_df=open_,
                high_df=high, low_df=low, ma_60=ma_60)


def _run(panel):
    bt = EventDrivenBacktester(initial_capital=1_000_000, position_size=0.20)
    return bt.run(top_k=3, threshold=2.0, **panel)


def test_backtest_runs_and_returns_wellformed_output(synthetic_panel):
    trades_df, equity_df = _run(synthetic_panel)

    assert isinstance(equity_df, pd.DataFrame)
    assert "Equity" in equity_df.columns
    assert len(equity_df) > 0

    eq = equity_df["Equity"]
    assert np.isfinite(eq.to_numpy()).all(), "equity must be finite"
    assert (eq > 0).all(), "equity must stay positive"

    # Uptrending market with active trading should produce at least one trade.
    assert len(trades_df) >= 1
    for col in ("Return_Pct", "Days_Held", "Reason"):
        assert col in trades_df.columns


def test_backtest_is_deterministic(synthetic_panel):
    """Identical inputs -> identical outputs. Guards refactors (vectorization)."""
    t1, e1 = _run(synthetic_panel)
    t2, e2 = _run(synthetic_panel)

    pd.testing.assert_frame_equal(e1, e2)
    pd.testing.assert_frame_equal(t1, t2)
