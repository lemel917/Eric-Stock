"""Tests for survivorship/ffill/value-factor fixes (Stock-vmn / s5r / 81s)."""
import numpy as np
import pandas as pd
import pytest

from strategy.ai_strategy import (
    load_delist_dates,
    apply_delist_mask,
    build_liquid_universe,
)
from strategy.finlab_factors import compute_value_rank


def _dates(n):
    return pd.date_range("2020-01-01", periods=n, freq="B")


# ── Stock-vmn: delist enforcement ──────────────────────────────────────────
def test_apply_delist_mask_excludes_after_delist_date():
    idx = _dates(10)
    mask = pd.DataFrame(True, index=idx, columns=["A", "B"])
    delist = {"B": idx[5]}
    out = apply_delist_mask(mask, delist)
    # B excluded from its delist date onward; A untouched
    assert not out.loc[idx[5]:, "B"].any()
    assert out.loc[: idx[4], "B"].all()
    assert out["A"].all()


def test_apply_delist_mask_noop_when_empty():
    idx = _dates(5)
    mask = pd.DataFrame(True, index=idx, columns=["A"])
    pd.testing.assert_frame_equal(apply_delist_mask(mask, None), mask)


def test_load_delist_dates(tmp_path):
    p = tmp_path / "delisted.csv"
    p.write_text("ticker,delist_date\n1111,2021-03-15\n2222,2022-07-01\n",
                 encoding="utf-8")
    d = load_delist_dates(str(p))
    assert d["1111"] == pd.Timestamp("2021-03-15")
    assert d["2222"] == pd.Timestamp("2022-07-01")


def test_load_delist_dates_missing_file_returns_empty():
    assert load_delist_dates("does_not_exist.csv") == {}


# ── Stock-s5r: zero-volume (halted) days excluded from universe ─────────────
def test_universe_excludes_zero_volume_days():
    idx = _dates(25)
    close = pd.DataFrame(100.0, index=idx, columns=["A", "B"])
    vol = pd.DataFrame(1000.0, index=idx, columns=["A", "B"])
    vol.loc[idx[24], "B"] = 0  # B halted on last day -> no real volume
    mask = build_liquid_universe(close, vol, top_n=50, lookback=20)
    assert mask.loc[idx[24], "A"]
    assert not mask.loc[idx[24], "B"]


# ── Stock-81s: value factor must not leak future financials ────────────────
def test_value_rank_point_in_time_only_latest_row():
    idx = _dates(8)
    close = pd.DataFrame(np.arange(1, 8 * 2 + 1, dtype=float).reshape(8, 2),
                         index=idx, columns=["A", "B"])
    # Simulate point-in-time fetch_value_data output: only the last row is set
    pb = pd.DataFrame(np.nan, index=idx, columns=["A", "B"])
    pe = pd.DataFrame(np.nan, index=idx, columns=["A", "B"])
    pb.loc[idx[-1]] = [1.2, 0.8]
    pe.loc[idx[-1]] = [10.0, 8.0]
    rank = compute_value_rank(close, pb_df=pb, pe_df=pe)
    # Historical rows stay NaN (no look-ahead); only the snapshot day is ranked
    assert rank.iloc[:-1].isna().all().all()
    assert rank.iloc[-1].notna().all()
