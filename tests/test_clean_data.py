"""Tests for tools.clean_data.clean_ohlc (Stock-5xz)."""
import pandas as pd
import pytest

from tools.clean_data import clean_ohlc


def test_removes_duplicate_timestamps():
    df = pd.DataFrame({
        "Datetime": ["2024-04-15 09:00:00+08:00",
                     "2024-04-15 09:00:00+08:00",   # exact duplicate
                     "2024-04-16 09:00:00+08:00"],
        "Close": [10.0, 10.0, 11.0],
    })
    out, stats = clean_ohlc(df)
    assert stats["duplicates_removed"] == 1
    assert len(out) == 2


def test_unifies_mixed_timezones():
    # 09:00+08:00 and 01:00+00:00 are the SAME instant -> one row after dedup
    df = pd.DataFrame({
        "Datetime": ["2024-04-18 09:00:00+08:00",
                     "2024-04-18 01:00:00+00:00"],
        "Close": [12.0, 12.0],
    })
    out, stats = clean_ohlc(df, tz="Asia/Taipei")
    assert len(out) == 1
    # All timestamps normalized to the same (Asia/Taipei) offset
    offsets = out["Datetime"].apply(lambda t: t.utcoffset())
    assert offsets.nunique() == 1


def test_sorts_by_time():
    df = pd.DataFrame({
        "Datetime": ["2024-04-16 09:00:00+08:00",
                     "2024-04-15 09:00:00+08:00"],
        "Close": [11.0, 10.0],
    })
    out, _ = clean_ohlc(df)
    assert list(out["Close"]) == [10.0, 11.0]


def test_empty_dataframe_is_safe():
    out, stats = clean_ohlc(pd.DataFrame({"Datetime": [], "Close": []}))
    assert stats["rows_out"] == 0
