"""離線整合測試：build_liquid_universe -> engineer_features -> 回測 全鏈路。

用合成 OHLCV 直接串起資料管線（繞過 yfinance），刻意注入「停牌(NaN/零量)」與
「下市」情境，驗證 Stock-s5r / Stock-vmn 的修正在 *完整管線* 下不會讓
engineer_features 或回測引擎崩潰——這條路徑單元測試原本沒覆蓋到。
"""
import numpy as np
import pandas as pd
import pytest

from strategy.ai_strategy import build_liquid_universe, engineer_features
from strategy.event_backtest import EventDrivenBacktester


@pytest.fixture
def panel():
    n_days = 150
    rng = np.random.default_rng(123)
    idx = pd.date_range("2020-01-01", periods=n_days, freq="B")
    cols = [f"S{i}" for i in range(10)] + ["HALT", "DEAD"]

    drift = np.linspace(0.0008, 0.0018, len(cols))
    noise = rng.normal(0, 0.012, size=(n_days, len(cols)))
    close = pd.DataFrame(100 * np.exp(np.cumsum(drift + noise, axis=0)),
                         index=idx, columns=cols)

    vol = pd.DataFrame(rng.uniform(2_000, 8_000, size=(n_days, len(cols))),
                       index=idx, columns=cols)

    # 停牌：HALT 在 day80~90 無報價（模擬 ffill(limit=5) 後殘留 NaN）+ 零成交量
    close.iloc[80:91, close.columns.get_loc("HALT")] = np.nan
    vol.iloc[80:91, vol.columns.get_loc("HALT")] = 0

    # 下市：DEAD 自 day100 起下市
    delist_date = idx[100]
    close.iloc[101:, close.columns.get_loc("DEAD")] = np.nan
    vol.iloc[101:, vol.columns.get_loc("DEAD")] = 0

    open_ = close.shift(1)
    open_.iloc[0] = close.iloc[0]
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99

    return dict(close=close, open=open_, high=high, low=low, vol=vol,
                idx=idx, delist={"DEAD": delist_date})


def test_universe_excludes_halt_and_delisted(panel):
    uni = build_liquid_universe(panel["close"], panel["vol"], top_n=8,
                                delist_dates=panel["delist"])
    # 下市股自下市日起不得在 universe
    assert not uni.loc[panel["delist"]["DEAD"]:, "DEAD"].any()
    # 停牌期間(零量/NaN)不得入選
    assert not uni.loc[panel["idx"][85], "HALT"]


def test_engineer_features_survives_nan(panel):
    uni = build_liquid_universe(panel["close"], panel["vol"], top_n=8,
                                delist_dates=panel["delist"])
    total_score, ma_long, atr_df, short_ma = engineer_features(
        panel["close"], panel["vol"], universe_mask=uni)
    # 不論有 NaN，輸出形狀需對齊且為 DataFrame
    assert total_score.shape == panel["close"].shape
    assert ma_long.shape == panel["close"].shape
    # 至少在後段(指標穩定後)存在有效分數
    assert total_score.iloc[70:].notna().any().any()


def _run(panel, uni, score, ma_long, atr_df):
    bt = EventDrivenBacktester(initial_capital=1_000_000, position_size=0.20)
    return bt.run(score, panel["close"], panel["open"], panel["high"],
                  panel["low"], ma_long, top_k=3, threshold=1.0,
                  atr_df=atr_df, vol_df=panel["vol"], universe_mask=uni)


def test_full_pipeline_runs_and_is_deterministic(panel):
    uni = build_liquid_universe(panel["close"], panel["vol"], top_n=8,
                                delist_dates=panel["delist"])
    score, ma_long, atr_df, _ = engineer_features(
        panel["close"], panel["vol"], universe_mask=uni)

    trades1, eq1 = _run(panel, uni, score, ma_long, atr_df)
    trades2, eq2 = _run(panel, uni, score, ma_long, atr_df)

    # 即使資料含停牌/下市 NaN，引擎也不應崩潰，且權益有限為正
    assert len(eq1) > 0
    assert np.isfinite(eq1["Equity"].to_numpy()).all()
    assert (eq1["Equity"] > 0).all()
    # 相同輸入 -> 完全可重現
    pd.testing.assert_frame_equal(eq1, eq2)
    pd.testing.assert_frame_equal(trades1, trades2)
