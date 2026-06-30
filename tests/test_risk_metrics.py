"""Unit tests for strategy.risk_metrics.compute_risk_metrics.

These cover the metric formulas with deterministic inputs so a regression in
the calculation (annualization, drawdown, Sharpe, trade stats) is caught.
"""
import numpy as np
import pandas as pd
import pytest

from strategy.risk_metrics import compute_risk_metrics, format_metrics_summary


def _equity(values, start="2020-01-01"):
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.DataFrame({"Equity": values}, index=idx)


def test_flat_equity_has_zero_return_and_drawdown():
    eq = _equity([1_000_000] * 260)
    m = compute_risk_metrics(eq, pd.DataFrame(), initial_capital=1_000_000)
    assert m["total_return"] == pytest.approx(0.0)
    assert m["ann_return"] == pytest.approx(0.0)
    assert m["max_drawdown_pct"] == pytest.approx(0.0)
    # No volatility -> Sharpe guarded to 0, not NaN/inf
    assert m["sharpe"] == 0


def test_total_and_annual_return():
    # Exactly one trading year (252 days) doubling -> ann_return ~= 100%
    vals = np.linspace(1_000_000, 2_000_000, 252)
    m = compute_risk_metrics(_equity(vals), pd.DataFrame(), initial_capital=1_000_000)
    assert m["total_return"] == pytest.approx(1.0, abs=1e-9)
    assert m["ann_return"] == pytest.approx(1.0, rel=0.05)


def test_sharpe_is_arithmetic_daily_return_sharpe():
    # Equity path with genuine variance so geometric != arithmetic Sharpe.
    vals = [1_000_000, 1_010_000, 1_004_950, 1_017_010, 1_013_960,
            1_022_070, 1_015_940, 1_028_130, 1_023_000, 1_035_330]
    eq = _equity(vals)
    m = compute_risk_metrics(eq, pd.DataFrame(), initial_capital=1_000_000)

    dr = eq["Equity"].pct_change().dropna()
    expected = dr.mean() / dr.std() * np.sqrt(252)
    # Primary Sharpe must be the arithmetic daily-return Sharpe (上游一致口徑).
    assert m["sharpe"] == pytest.approx(expected)
    # Geometric Sharpe kept as a reference field and genuinely differs here.
    assert "geometric_sharpe" in m
    assert m["sharpe"] != pytest.approx(m["geometric_sharpe"])


def test_sharpe_respects_risk_free_rate():
    vals = [1_000_000, 1_010_000, 1_004_950, 1_017_010, 1_013_960, 1_022_070]
    eq = _equity(vals)
    m0 = compute_risk_metrics(eq, pd.DataFrame(), risk_free_rate=0.0)
    m_rf = compute_risk_metrics(eq, pd.DataFrame(), risk_free_rate=0.02)
    # A positive risk-free rate lowers the excess-return Sharpe.
    assert m_rf["sharpe"] < m0["sharpe"]


def test_max_drawdown_is_negative_and_uses_cummax():
    # Up to 1.2M, down to 0.9M (peak-to-trough = 0.9/1.2 - 1 = -25%), recover.
    vals = [1_000_000, 1_200_000, 900_000, 1_100_000]
    m = compute_risk_metrics(_equity(vals), pd.DataFrame(), initial_capital=1_000_000)
    assert m["max_drawdown_pct"] == pytest.approx(0.9 / 1.2 - 1)
    assert m["max_drawdown_pct"] < 0


def test_trade_statistics():
    trades = pd.DataFrame({
        "Return_Pct": [0.10, -0.05, 0.20, -0.10],
        "Days_Held": [5, 3, 8, 2],
        "Reason": ["TP", "SL", "TP", "SL"],
    })
    m = compute_risk_metrics(_equity([1_000_000, 1_100_000]), trades,
                             initial_capital=1_000_000)
    assert m["total_trades"] == 4
    assert m["win_rate"] == pytest.approx(0.5)
    # gross profit 0.30, gross loss 0.15 -> PF = 2.0
    assert m["profit_factor"] == pytest.approx(2.0)
    assert m["reason_counts"] == {"TP": 2, "SL": 2}


def test_empty_trades_are_handled():
    m = compute_risk_metrics(_equity([1_000_000, 1_010_000]), pd.DataFrame(),
                             initial_capital=1_000_000)
    assert m["total_trades"] == 0
    assert m["win_rate"] == 0
    assert m["profit_factor"] == 0


def test_format_summary_is_string():
    m = compute_risk_metrics(_equity([1_000_000, 1_050_000]), pd.DataFrame(),
                             initial_capital=1_000_000)
    out = format_metrics_summary(m)
    assert isinstance(out, str)
    assert "風險調整後績效報告" in out
