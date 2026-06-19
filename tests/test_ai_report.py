"""Tests for the pure helper extracted from ai_report.generate_report.

Importing ai_report also serves as a smoke test that the module (and its
strategy.* imports) loads cleanly after the refactor. matplotlib uses the Agg
backend and main() is guarded by __main__, so import has no side effects.
"""
import numpy as np
import pandas as pd
import pytest

import ai_report


def test_compute_display_atr_with_high_low():
    close = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    high = close + 1
    low = close - 1
    # True range is 2.0 every bar -> ATR(3) of the last bar = 2.0
    atr = ai_report.compute_display_atr(close, high, low, period=3)
    assert atr == pytest.approx(2.0)


def test_compute_display_atr_fallback_without_high_low():
    close = pd.Series(np.linspace(100, 120, 30))
    atr = ai_report.compute_display_atr(close, period=10)
    assert np.isfinite(atr)
    assert atr > 0


def test_compute_display_atr_is_module_level():
    # Regression guard: the helper must remain importable at module scope
    # (it was previously nested inside generate_report).
    assert callable(getattr(ai_report, "compute_display_atr", None))
