"""Paper trading 共用模組 (Stock-4fv)。

過去 paper_tracker.py 與 paper_trade.py 各自寫一份 HTML regex 解析同一個
stock_report.html，且交易參數(成本/持倉天數)各自硬編碼且彼此不一致
(tracker max_hold=20 vs 回測 15)。本模組提供單一信號來源與共用參數常數，
兩支程式皆委派至此，避免兩套平行真相來源。
"""
import os
import re

# === 共用交易參數（與 event_backtest 預設對齊）===
BUY_COST_RATE = 0.001425    # 買入手續費
SELL_COST_RATE = 0.004425   # 賣出手續費 + 證交稅
SLIPPAGE = 0.001            # 滑價 10bps
MAX_HOLD_DAYS = 15          # 持倉上限（對齊回測，原 tracker 誤用 20）
POSITION_SIZE = 0.10        # 單筆部位比例

REPORT_PATH = "stock_report.html"

# 實際 stock_report.html 的信號列格式（已對照真實輸出驗證）：
#   <td>代號</td><td>名稱</td><td>分數</td><td>今日收盤</td>
#   <td>...🟢 建議買進 #N...</td>
#   <td><b>停利:</b> <span>TP</span> ... <b>停損:</b> <span>SL</span> ...</td>
# 進場價 = 今日收盤（第 3 個純數字 td：代號、分數、收盤）。
# 採用此「標籤式」解析（原 paper_tracker 的正確版本）；原 paper_trade 的
# 位置式 regex 在此格式下匹配不到，已一併修正為委派至本函式。
_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
_TICKER_RE = re.compile(r"<td>(\d{4})</td>")
_NUM_TD_RE = re.compile(r"<td[^>]*>([\d\.]+)</td>")
_TP_RE = re.compile(r"停利.*?>([\d\.]+)<")
_SL_RE = re.compile(r"停損.*?>([\d\.]+)<")


def extract_signals_from_report(source=REPORT_PATH):
    """從 stock_report.html 擷取今日「建議買進」信號，回傳 list[dict]。

    Parameters
    ----------
    source : str
        HTML 檔路徑，或直接傳入 HTML 字串內容。

    Returns
    -------
    list[dict]：每筆 {'ticker', 'entry', 'tp', 'sl'}（價格為 float）。
        檔案不存在或無信號時回傳空 list。
    """
    if source and "<" not in source and os.path.exists(source):
        with open(source, encoding="utf-8") as f:
            html = f.read()
    elif source and "<" in source:
        html = source
    else:
        return []

    signals = []
    for row in _ROW_RE.findall(html):
        if "建議買進" not in row:
            continue
        ticker_m = _TICKER_RE.search(row)
        nums = _NUM_TD_RE.findall(row)   # [代號, 分數, 收盤(=進場), ...]
        tp_m = _TP_RE.search(row)
        sl_m = _SL_RE.search(row)
        if ticker_m and len(nums) >= 3 and tp_m and sl_m:
            signals.append({
                "ticker": ticker_m.group(1),
                "entry": float(nums[2]),
                "tp": float(tp_m.group(1)),
                "sl": float(sl_m.group(1)),
            })
    return signals
