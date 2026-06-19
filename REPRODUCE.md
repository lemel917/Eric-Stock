# 績效數字重現指南 (Reproducibility, Stock-899)

本檔案是所有對外宣稱績效數字的**單一真相來源**。README 等文件引用的數字，
都應能由下列指令重新產生。任何宣稱若無法由此重現，視為待驗證。

> 背景：審查發現 README 同時存在多組互相矛盾的數字（例如 v8.5 年化
> 62.5%/Sharpe 2.47 vs `factor_search_results.csv` 52.85%/2.308 vs
> `ablation_results.csv` 21.56%/1.18），且部分壓測列疑似重複/區間重疊。
> 此外，產生這些數字的程式當時帶有 trailing intrabar、ffill survivorship、
> 價值因子前視等偏差（已修正），故**舊數字可能高估**，需重跑。

## 環境

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pytest            # 先確認測試通過（CI gate）
```

## 重現各項數字

| 宣稱數字 | 重現指令 | 輸出 |
|---------|---------|------|
| v8.5 主回測（年化/Sharpe/MDD/Calmar/PF） | `python ai_report.py --regime-filter --regime-graduated --breadth-regime --regime-floor 0.10 --trailing --trailing-atr 2.5 --tp-atr 4.0 --sl-atr 2.5 --hold-days 15 --top-k 7 --gap-filter 1.5 --days 1200` | `stock_report.html` 內績效區 |
| 因子消融 (ablation) | `python ablation_study.py` | `ablation_results.csv` + `ablation_chart.png` |
| 因子網格搜尋 | `python factor_grid_search.py` | `factor_search_results.csv` + `factor_search_chart.png` |
| Sector Rotation v2（年化 36.4%/Sharpe 1.34） | `python sector_rotation_report.py` | stdout / 報表 |
| 11 段歷史危機壓測 | `python crisis_test.py` 與 `python deep_crisis_test.py` | stdout（各段 Sharpe/MDD）|
| 00981A 對標 | `python sector_rotation_report.py`（含共存期對標） | stdout |
| Walk-Forward OOS | `python walk_forward.py` | stdout |
| Monte Carlo（**固定種子可重現**） | `python monte_carlo.py --runs 2000 --block-size 5 --seed 42` | stdout 信賴區間 |

## 更新流程（待辦）

1. 以**修正後**程式重跑上表所有指令（修正後參數：SL 2.5×ATR、持倉 15 天、
   trailing 2.5×ATR、價值因子 point-in-time、universe 含下市排除）。
2. 把每個對外數字連同**精確日期區間**與來源指令，集中記錄於本檔或單一 CSV。
3. 移除 README 中無法重現/重複的列（壓測表中標 ⚠️ 者），以重跑結果取代。
4. Sharpe > 3 的宣稱需附容量/衝擊成本壓力測試，否則下修。

## 注意事項

- `ai_report.py` / `sector_rotation_report.py` 透過 `yfinance` 即時下載資料，
  不同日期執行因資料更新可能略有差異；重現時請記錄執行日期。
- Monte Carlo 已支援 `--seed`，相同種子+相同輸入 → 完全可重現。
- 其餘回測為確定性計算（無隨機），相同輸入資料下結果固定。
