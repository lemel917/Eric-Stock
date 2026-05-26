"""
板塊資金流動量傾斜模組 (Sector-Flow Momentum Tilt)

用 10/15/20 天窗口計算各板塊的平均動量，識別資金正在流入的板塊，
動態調整 Top-K 選股的板塊配額，讓策略跟隨資金流方向。

核心概念：
- 計算每個板塊在 universe 內所有股票的平均動量
- 用三個窗口（10d/15d/20d）做加權平均，捕捉不同時間尺度的資金流
- 將 Top-K 的 slot 配額向強勢板塊傾斜
- 當板塊間差異不大時，自動退化為原始純分數排名

v1.0 — 2026-04-09
"""

import pandas as pd
import numpy as np


# =============================================
# 台股板塊分類（中分 ~8 類，based on 代號前兩碼）
# =============================================
# 參考 TWSE 產業分類，合併為實戰可用的 7-8 大板塊
SECTOR_MAP = {
    'semiconductor': {
        'prefixes': ('23', '24'),
        'label': '半導體',
        'description': '晶圓代工、IC設計、封裝測試',
    },
    'electronics': {
        'prefixes': ('25', '30', '33', '34', '35', '36'),
        'label': '電子零組件',
        'description': '被動元件、PCB、連接器、光電',
    },
    'computing': {
        'prefixes': ('37', '49', '61', '63', '64', '65', '66', '67', '68', '69'),
        'label': '資訊/通訊',
        'description': '電腦、伺服器、通訊設備、軟體',
    },
    'finance': {
        'prefixes': ('28', '58'),
        'label': '金融',
        'description': '銀行、壽險、證券、金控',
    },
    'traditional': {
        'prefixes': ('11', '12', '13', '14', '15', '16', '18', '19',
                     '20', '21', '22', '27', '29', '31', '32', '39',
                     '40', '41', '42', '43', '44', '45', '46', '48',
                     '51', '52', '53', '54', '55', '56', '57', '59',
                     '60', '62', '70', '71', '72', '73', '74', '75',
                     '76', '77', '78', '79', '80', '81', '82', '83',
                     '84', '85', '86', '87', '88', '89', '90', '91',
                     '92', '93', '94', '95', '96', '97', '98', '99'),
        'label': '傳產/其他',
        'description': '水泥、塑化、鋼鐵、紡織、食品、營建、觀光等',
    },
    'shipping': {
        'prefixes': ('26',),
        'label': '航運',
        'description': '貨櫃、散裝、航空',
    },
    'biotech': {
        'prefixes': ('17', '47'),
        'label': '生技醫療',
        'description': '新藥、醫材、通路',
    },
}

# 建立快速查表：prefix → sector_name
_PREFIX_TO_SECTOR = {}
for sector_name, info in SECTOR_MAP.items():
    for prefix in info['prefixes']:
        _PREFIX_TO_SECTOR[prefix] = sector_name

# 個股板塊覆寫（prefix 規則不準的股票手動修正）
# 台股 4 碼代號中，60-69 開頭混雜了石化、生技、金融等非科技公司
SECTOR_OVERRIDE = {
    '6505': 'traditional',    # 台塑化 → 石化傳產
    '6446': 'biotech',        # 藥華藥 → 生技
    '6239': 'semiconductor',  # 力成 → 半導體(封測)
    '6116': 'electronics',    # 彩晶 → 電子(面板)
    '6005': 'finance',        # 群益期 → 金融
    '6176': 'electronics',    # 安碁資訊 → 資安/電子
    '4142': 'biotech',        # 國光生 → 生技
    '4743': 'biotech',        # 合一 → 生技
    '1760': 'biotech',        # 寶齡富錦 → 生技
    '1707': 'biotech',        # 葡萄王 → 生技
}


def classify_sector(ticker):
    """
    根據台股代號判斷板塊。優先查個股覆寫表，再用前兩碼規則。

    Parameters
    ----------
    ticker : str
        台股代號，例如 '2330'

    Returns
    -------
    str
        板塊名稱（如 'semiconductor'），若無法分類則回傳 'traditional'
    """
    ticker_str = str(ticker)
    # 優先查覆寫表（修正 prefix 規則不準的個股）
    if ticker_str in SECTOR_OVERRIDE:
        return SECTOR_OVERRIDE[ticker_str]
    # 再用 prefix 規則
    if len(ticker_str) >= 2:
        prefix = ticker_str[:2]
        return _PREFIX_TO_SECTOR.get(prefix, 'traditional')
    return 'traditional'


def compute_sector_flow(close_df, universe_mask=None, windows=None,
                        weights=None):
    """
    計算各板塊在多個時間窗口的動量分數。

    每個板塊的動量 = universe 內該板塊所有股票的平均 return (close[t] / close[t-w] - 1)。
    多窗口加權平均後，做橫向排名產出板塊相對強度。

    Parameters
    ----------
    close_df : pd.DataFrame
        收盤價矩陣 (日期 × 股票代號)
    universe_mask : pd.DataFrame (bool), optional
        動態 Universe 遮罩
    windows : list[int], optional
        動量計算窗口（預設 [10, 15, 20]）
    weights : list[float], optional
        各窗口權重（預設 [0.3, 0.4, 0.3]）

    Returns
    -------
    sector_flow_df : pd.DataFrame
        (日期 × 板塊) 的動量分數矩陣
    sector_composition : dict
        {sector_name: [tickers]} 各板塊的股票組成
    """
    if windows is None:
        windows = [10, 15, 20]
    if weights is None:
        weights = [0.3, 0.4, 0.3]

    assert len(windows) == len(weights), "windows 和 weights 長度必須相同"

    # 1. 分類所有股票到板塊
    sector_tickers = {}
    for ticker in close_df.columns:
        sector = classify_sector(ticker)
        if sector not in sector_tickers:
            sector_tickers[sector] = []
        sector_tickers[sector].append(ticker)

    # 2. 計算每個窗口、每個板塊的平均動量
    sector_names = sorted(sector_tickers.keys())
    dates = close_df.index

    # 預計算各窗口的回報率矩陣
    window_returns = {}
    for w in windows:
        window_returns[w] = close_df / close_df.shift(w) - 1

    # 初始化結果矩陣
    sector_flow_data = {s: np.full(len(dates), np.nan) for s in sector_names}

    for i in range(max(windows), len(dates)):
        for sector, tickers in sector_tickers.items():
            # 取得 universe 內的股票
            if universe_mask is not None:
                valid_tickers = [t for t in tickers
                                 if t in universe_mask.columns
                                 and universe_mask[t].iloc[i]]
            else:
                valid_tickers = tickers

            if not valid_tickers:
                continue

            # 加權平均各窗口的板塊動量
            weighted_flow = 0.0
            total_weight = 0.0
            for w, wt in zip(windows, weights):
                rets = window_returns[w][valid_tickers].iloc[i]
                valid_rets = rets.dropna()
                if len(valid_rets) > 0:
                    weighted_flow += valid_rets.mean() * wt
                    total_weight += wt

            if total_weight > 0:
                sector_flow_data[sector][i] = weighted_flow / total_weight

    sector_flow_df = pd.DataFrame(sector_flow_data, index=dates)

    return sector_flow_df, sector_tickers


def get_sector_slots(sector_scores, top_k=7, tilt_strength=1.0,
                     min_dispersion=0.005):
    """
    根據板塊動量分數分配 Top-K 的 slot 配額。

    Parameters
    ----------
    sector_scores : pd.Series
        當日各板塊的動量分數（index=板塊名）
    top_k : int
        總 slot 數
    tilt_strength : float
        傾斜力度 (0.0=均分, 1.0=全力傾斜)
    min_dispersion : float
        板塊分數標準差低於此值時，退化為均分（無明顯方向）

    Returns
    -------
    dict
        {sector_name: slot_count} 每個板塊的建議 slot 數
    """
    valid_scores = sector_scores.dropna()
    if len(valid_scores) == 0:
        return {}

    # 檢查板塊間是否有明顯差異
    score_std = valid_scores.std()
    if score_std < min_dispersion:
        # 差異太小，退化為不限制（回傳空 dict 讓 caller 用原始邏輯）
        return {}

    # 混合策略：tilt_strength 控制傾斜比例
    # 1. 計算排名（越高越好）
    ranks = valid_scores.rank(ascending=True)  # 1=最差, N=最好
    n_sectors = len(ranks)

    # 2. 將排名轉為權重
    # softmax-like: 讓排名差異轉為 slot 分配
    rank_weights = ranks / ranks.sum()

    # 3. 均分權重
    uniform_weights = pd.Series(1.0 / n_sectors, index=valid_scores.index)

    # 4. 混合
    blended = tilt_strength * rank_weights + (1 - tilt_strength) * uniform_weights
    blended = blended / blended.sum()  # 歸一化

    # 5. 分配 slot（按權重比例分配，取 floor 後把剩餘給最強板塊）
    raw_slots = blended * top_k
    floor_slots = raw_slots.apply(np.floor).astype(int)

    # 確保至少分配完所有 slot
    remaining = top_k - floor_slots.sum()
    if remaining > 0:
        # 按小數部分大小分配剩餘 slot
        fractional = raw_slots - floor_slots
        top_frac = fractional.nlargest(int(remaining))
        for sector in top_frac.index:
            floor_slots[sector] += 1

    return floor_slots.to_dict()


def select_with_sector_tilt(candidates, sector_slots, top_k, slots_available):
    """
    按板塊配額從候選股中選股。

    Parameters
    ----------
    candidates : list[tuple]
        已按分數排序的候選股 [(ticker, score, entry_price), ...]
    sector_slots : dict
        {sector_name: max_slots} 板塊配額
    top_k : int
        目標選股數
    slots_available : int
        實際可用 slot（扣除已持倉）

    Returns
    -------
    list[tuple]
        選中的候選股列表
    """
    effective_k = min(top_k, slots_available)

    if not sector_slots:
        # 無傾斜，退化為原始行為
        return candidates[:effective_k]

    selected = []
    sector_used = {}  # 追蹤各板塊已用 slot

    for ticker, score, entry_price in candidates:
        if len(selected) >= effective_k:
            break

        sector = classify_sector(ticker)
        used = sector_used.get(sector, 0)
        max_allowed = sector_slots.get(sector, 1)  # 未在 map 中的板塊給 1 slot

        if used < max_allowed:
            selected.append((ticker, score, entry_price))
            sector_used[sector] = used + 1

    # 如果因為配額限制導致 slot 沒填滿，用剩餘最高分候選補上
    if len(selected) < effective_k:
        selected_tickers = {s[0] for s in selected}
        for ticker, score, entry_price in candidates:
            if len(selected) >= effective_k:
                break
            if ticker not in selected_tickers:
                selected.append((ticker, score, entry_price))
                selected_tickers.add(ticker)

    return selected
