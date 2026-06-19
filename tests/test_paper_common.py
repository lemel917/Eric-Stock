"""Tests for paper_common shared signal parsing / params (Stock-4fv)."""
import paper_common


# 真實 stock_report.html 信號列格式的最小重現
_BUY_ROW = (
    '<tr><td>2344</td><td>華邦電</td><td>3.97</td><td>218.5</td>'
    '<td><span style="color:#00ff00; font-weight:bold;">🟢 建議買進 #1</span></td>'
    '<td><b>停利:</b> <span style="color:#00ff00">276.0</span> (+26.3%) <br>'
    '<b>停損:</b> <span style="color:#ff4444">182.6</span> (-16.4%) <br>'
    '<b>最晚出場:</b> 2026-07-10</td></tr>'
)
_CANDIDATE_ROW = (
    '<tr style="opacity:0.6"><td>2379</td><td>瑞昱</td><td>3.43</td><td>819.0</td>'
    '<td><span style="color:#ffab00">🟡 候選 (超出 Top-K)</span></td><td>-</td></tr>'
)


def test_extract_parses_buy_signal():
    sigs = paper_common.extract_signals_from_report(_BUY_ROW)
    assert len(sigs) == 1
    s = sigs[0]
    assert s["ticker"] == "2344"
    assert s["entry"] == 218.5   # 進場價 = 今日收盤（第 3 個數字 td）
    assert s["tp"] == 276.0
    assert s["sl"] == 182.6


def test_extract_excludes_candidates():
    # 候選列(非建議買進)不應被當成信號
    sigs = paper_common.extract_signals_from_report(_BUY_ROW + _CANDIDATE_ROW)
    assert [s["ticker"] for s in sigs] == ["2344"]


def test_extract_missing_file_returns_empty():
    assert paper_common.extract_signals_from_report("nonexistent_report.html") == []


def test_shared_params_aligned_with_backtest():
    # max_hold 必須對齊回測的 15（修正原 paper_tracker 的 20）
    assert paper_common.MAX_HOLD_DAYS == 15
    assert paper_common.BUY_COST_RATE == 0.001425
    assert paper_common.SELL_COST_RATE == 0.004425
