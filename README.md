# TW Stocker v9.0 — AI 量化交易系統（雙策略架構）

中期動量 + 板塊輪動的雙策略系統。v8.5 個股動量穩健底倉 + Sector Rotation v2 板塊資金流追蹤。
美股前提（SPY/VIX/SOX）→ 板塊資金流選擇 → 板塊內選股。經 11 段歷史危機壓測 + 00981A 對標驗證。

📊 **線上報表**：https://lemel917.github.io/Eric-Stock/stock_report.html
📈 **Paper Trading**：https://lemel917.github.io/Eric-Stock/paper_trading.html

---

## 雙策略架構總覽

| | v8.5 Momentum | Sector Rotation v2 (NEW) |
|---|:---:|:---:|
| **邏輯** | 個股 cross-sectional ranking | 先選板塊 → 板塊內排名 |
| **Regime** | 台股 0050 vs MA60 | 🌍 **美股 SPY + VIX + SOX** |
| **選股因子** | Mom(20d)×3 + Trend(60MA)×1 | 板塊 flow(10/15/20d) + 板塊內動量 |
| **角色** | 穩健底倉（低 MDD） | 積極追蹤（高報酬） |
| **年化 (7y)** | ~25% | **+36.4%** |
| **Sharpe (7y)** | 1.04 | **1.34** |

---

## Sector Rotation v2 — 板塊輪動策略 (v1.2 beat-00981A)

### 三層架構

```
Layer 1: 美股 Macro Regime（前提門檻）
  SPY trend + VIX level → 整體曝險 (0.0 ~ 1.0)
  SPY + SOX 雙空 → 幾乎停止 (0.1)
  VIX > 28 → 完全停止 (0.0)

Layer 2: 板塊資金流（主體選擇）
  7 大板塊的 10/15/20d 平均報酬加權排名
  取前 3 板塊，板塊均報酬 < -3% → 不進場

Layer 3: 板塊內選股
  momentum(20d) × 2 + trend(close > MA60) × 1
  每板塊 Top-3，合計 6~9 檔

出場: ATR TP/SL 4.0/3.0 + 20 天持倉上限
成本: 買 0.143% + 賣 0.443% + 滑價 10bps
```

### 關鍵設計：美股前提

| 條件 | 曝險 | 說明 |
|------|:---:|------|
| SPY↑ + VIX < 22 | **100%** | 全面多頭 |
| SPY↑ + VIX 22~25 | 70% | 輕微恐慌 |
| SPY↓ + VIX < 25 | 40% | 溫和空頭 |
| SPY↓ + VIX 25~28 + SPY > MA20 | 50% | 復甦允許 |
| SPY↓ + VIX 25~28 | 20% | 中等恐慌 |
| SPY + SOX 雙空 | **10%** | 最危險 |
| VIX > 28 | **0%** | 完全停止 |

### SOX 科技門檻 (v1.1: 影響所有板塊)

| 條件 | 效果 |
|------|------|
| SOX > MA60 | 全面開放 |
| SOX < MA60, mom > -3% | **所有板塊半倉**（不只科技） |
| SOX < MA60, mom < -3% | 科技禁止 + 其他半倉 |

---

## 11 段歷史危機壓測

| 期間 | SR v2 Sharpe | v8.5 Sharpe | 0050 | SR MDD | VIX 均 |
|------|:---:|:---:|:---:|:---:|:---:|
| 💥 金融海嘯 '08-'09 | -1.81 | -0.78 | 0.95 | -40% | 35 |
| 💥 海嘯復甦 '09-'10 | **0.26** | 1.28 | 2.16 | -15% | 28 |
| 🦠 疫情前 '19Q4 | **1.26** | 0.95 | 1.50 | -7% | 14 |
| 🦠 疫情爆發 '20H1 | -0.73 | -0.52 | -0.34 | -14% | 35 |
| 🦠 疫後牛市 '20-'21 | **2.02** | 2.75 | 2.67 | -27% | 24 |
| ⚔️ 烏俄戰爭 '22H1 | -2.53 | -2.22 | -2.21 | -25% | 27 |
| 📉 升息衝擊 '22 | **-1.55** | -1.79 | -2.02 | **-28%** | 26 |
| 🤖 AI 行情 '23-'24 | **2.37** | 2.58 | 2.55 | -15% | 16 |
| 🏛️ 關稅前 '26Q1 | **1.25** | 2.38 | -3.50 | -12% | 26 |
| 🏛️ 關稅衝擊 '26 | **5.12** | 4.02 | 1.22 | -12% | 23 |
| 📊 近期 '26 | **5.12** | 4.02 | 2.12 | -12% | 21 |

### 00981A 對標（共存期 2025-05 至今）

| 期間 | SR v2 | 00981A | 差距 |
|------|:---:|:---:|:---:|
| 🏛️ 關稅前 | +52.5% | -1.0% | ✅ **+54%** |
| 🏛️ 關稅衝擊 | +195.8% | +21.4% | ✅ **+174%** |
| 📊 近期 | +195.8% | +35.0% | ✅ **+161%** |

### v1.0 → v1.2 改善

| 指標 | v1.0 | v1.2 | 改善 |
|------|:---:|:---:|:---:|
| 升息衝擊 MDD | -44.8% | **-27.8%** | ✅ +17.0% |
| 烏俄戰爭 MDD | -31.7% | **-25.0%** | ✅ +6.7% |
| 關稅衝擊 Sharpe | 4.83 | **5.12** | ✅ +6% |
| 海嘯復甦 Sharpe | -0.08 | **+0.26** | ✅ 翻正 |
| 近期 vs 00981A | +152.9% | **+160.9%** | ✅ 差距擴大 |

---

## v8.5 Momentum 策略（保留）

### 績效總覽

| 指標 | 值 | 說明 |
|------|:---:|------|
| **Sharpe** | **2.47** | 四波 32 組消融驗證最佳配置 |
| **年化報酬** | **+62.5%** | 包含交易成本 + 滑價 |
| **MDD** | **-14.2%** | Breadth Regime 精準捕捉中小型股市況 |
| **Calmar** | **4.40** | 年化報酬/MDD |
| **Profit Factor** | **1.74** | 總獲利/總虧損 |

### 策略公式

```
每日訊號:
  1. Universe = 過去 20 日平均成交額 Top-60
  2. 綜合評分 = rank_momentum(20d) × 3 + rank_trend(60MA) × 1
  3. 進場: score ≥ 2.0 AND close > 60MA AND 大盤 regime ≥ 40%
  4. 跳空 > 1.5×ATR 的進場日跳過
  5. Top-7 選股（相關性 > 0.8 的替換為不相關候選）

出場 (gap-aware): ATR TP 4.0 / SL 3.0 + 20 天持倉
成本: 買 0.1425% + 賣 0.4425% + 滑價 10bps
```

---

## 快速開始

```bash
pip install -r requirements.txt

# ── v8.5 Momentum ──
python ai_report.py --show-inst

# ── Sector Rotation v2 ──
python sector_rotation_report.py                          # 預設 1200 天
python sector_rotation_report.py --start-date 2019-01-01  # 7 年回測
python sector_rotation_report.py --compare                # vs 0050

# ── 深度危機壓測 (11 段) ──
python deep_crisis_test.py

# ── 驗證工具 ──
python walk_forward.py                                    # OOS 穩定性
python monte_carlo.py --runs 2000 --block-size 5          # Block Bootstrap
python crisis_test.py                                     # 基礎危機壓測

# ── Paper Trading ──
python paper_trade.py signals --enrich
python paper_trade.py hardstop
```

## 專案結構

```
tw_stocker/
├── ai_report.py                  # v8.5 主程式 + CLI + HTML 報表
├── sector_rotation_report.py     # 🆕 板塊輪動 v2 回測 + 報告
├── deep_crisis_test.py           # 🆕 11 段歷史危機壓測 + 00981A
├── crisis_test.py                # 基礎危機壓力測試
├── walk_forward.py               # Anchored OOS 穩定性驗證 (v2)
├── monte_carlo.py                # Equity-Curve Block Bootstrap (v3)
├── sweep.py                      # 季度參數校準 + Telegram 警報
├── paper_trade.py                # Paper Trading v8 + 月報
├── strategy/
│   ├── ai_strategy.py            # 因子工程 (Mom×3 + Trend×1)
│   ├── event_backtest.py         # v8.5 事件驅動回測引擎
│   ├── us_market.py              # 🆕 美股信號 (SPY/VIX/SOX)
│   ├── sector_rotation_backtest.py # 🆕 板塊輪動回測引擎
│   ├── sector_flow.py            # 板塊資金流分析
│   ├── institutional_flow.py     # 三大法人籌碼因子
│   ├── news_sentiment.py         # 新聞情緒因子
│   ├── risk_metrics.py           # 風險指標計算
│   └── benchmark.py              # Benchmark (0050 / EW)
├── artifacts/                    # 每日 CSV + 月報
├── .github/workflows/
│   └── update_ai_report.yml      # 每日自動執行
└── stock_report.html             # 完整交易報表
```

## 壓力測試方法論

> ⚠️ **Monte Carlo** (`monte_carlo.py`) 對每日組合報酬率做 equity-curve block bootstrap，
> 保留了多檔同持、regime 縮放、gap sizing 等組合效應。但 bootstrap 仍假設日報酬的
> 時序結構可以被隨機重排——在極端 regime 轉換時這不成立。結果應視為
> **分布估計的參考**，不能直接當作實盤安全邊際。
>
> **OOS 穩定性** (`walk_forward.py`) 是固定參數的分段 OOS 測試（非 nested walk-forward）。
>
> **歷史危機壓測** (`deep_crisis_test.py`) 在 11 段歷史危機做完整回測，
> 含金融海嘯、COVID、烏俄戰爭、升息、關稅衝擊，同時比較 v8.5 / SR v2 / 0050 / 00981A。

## 免責聲明

本系統由 AI 量化模型自動產出，僅供學術研究與技術交流之用，不構成任何投資建議。歷史回測績效不代表未來實際報酬，投資有風險，決策請自行負責。
