#!/usr/bin/env python3
"""
Paper Trading 自動追蹤器 v8.5

每日收盤後執行，自動模擬 v8.5 策略的實盤績效：
1. 從 stock_report.html 擷取今日信號
2. 追蹤已持倉的 TP/SL/時間到期
3. 累積權益曲線到 paper_equity.json
4. 產出 paper_trading.html 績效網頁

使用方式:
  python paper_tracker.py              # 每日更新（GitHub Actions 自動執行）
  python paper_tracker.py --reset      # 清除所有記錄重新開始
"""

import json
import os
import re
import sys
from datetime import datetime, date, timedelta
import argparse

import paper_common

DATA_FILE = 'paper_equity.json'
HTML_FILE = 'paper_trading.html'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {
        'start_date': date.today().isoformat(),
        'initial_capital': 200_000,
        'capital': 200_000,
        'positions': {},          # {ticker: {entry, tp, sl, entry_date, shares, day_count}}
        'closed_trades': [],      # [{ticker, entry, exit, pnl_pct, reason, entry_date, exit_date}]
        'equity_curve': [],       # [{date, equity, capital, n_positions}]
        'daily_signals': [],      # [{date, tickers: [...]}]
    }

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)

def get_stock_names(tickers):
    """從 TWSE/TPEX open data 取得股票中文名稱，帶本地 JSON 快取（7天有效）。"""
    import csv
    import io
    import urllib.request

    cache_file = os.path.join('data', 'stock_names_cache.json')
    cache = {}
    cache_valid = False

    if os.path.exists(cache_file):
        with open(cache_file, encoding='utf-8') as f:
            cache = json.load(f)
        # 檢查快取是否 7 天內
        updated = cache.get('_updated', '')
        if updated:
            try:
                days = (datetime.now() - datetime.fromisoformat(updated)).days
                if days < 7:
                    cache_valid = True
            except Exception:
                pass

    # 若快取有效且所有 ticker 都有對應名稱，直接回傳
    if cache_valid and all(t in cache for t in tickers):
        return {t: cache.get(t, t) for t in tickers}

    # 重新抓取完整名稱對照
    try:
        # TWSE 上市
        url_twse = 'https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=open_data'
        req = urllib.request.Request(url_twse, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=15)
        text = resp.read().decode('utf-8-sig')
        reader = csv.reader(io.StringIO(text))
        next(reader)  # skip header
        for row in reader:
            if len(row) >= 3:
                code = row[1].strip().strip('"')
                name = row[2].strip().strip('"')
                if code and name:
                    cache[code] = name
    except Exception as e:
        print(f"   ⚠️ TWSE 名稱下載失敗: {e}")

    try:
        # TPEX 上櫃
        url_tpex = 'https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes'
        req = urllib.request.Request(url_tpex, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode('utf-8'))
        for item in data:
            code = item.get('SecuritiesCompanyCode', '').strip()
            name = item.get('CompanyName', '').strip()
            if code and name:
                cache[code] = name
    except Exception as e:
        print(f"   ⚠️ TPEX 名稱下載失敗: {e}")

    # 儲存快取
    cache['_updated'] = datetime.now().isoformat()
    os.makedirs('data', exist_ok=True)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    return {t: cache.get(t, t) for t in tickers}


def get_current_prices(tickers):
    """用 yfinance 取得最新收盤價。"""
    import yfinance as yf
    prices = {}
    if not tickers:
        return prices
    symbols = [f"{t}.TW" for t in tickers]
    try:
        df = yf.download(symbols, period='2d', progress=False)
        close = df['Close'] if 'Close' in df.columns else df[('Close',)]
        if isinstance(close, (int, float)):
            # single ticker
            prices[tickers[0]] = float(close)
        else:
            for t, sym in zip(tickers, symbols):
                if sym in close.columns:
                    val = close[sym].dropna()
                    if len(val) > 0:
                        prices[t] = float(val.iloc[-1])
    except Exception as e:
        print(f"   ⚠️ 價格下載失敗: {e}")
    return prices

def extract_signals_from_report():
    """從 stock_report.html 擷取今日買入信號。

    FIX(4fv): 委派至 paper_common 的單一信號解析器，避免與 paper_trade 各寫
    一份 regex 形成兩套不同步的真相來源。
    """
    return paper_common.extract_signals_from_report()

def update_tracker(data):
    """主要更新邏輯：追蹤持倉、結算已平倉、記錄新信號。"""
    today = date.today().isoformat()
    # FIX(4fv): 改用 paper_common 共用參數（max_hold 由 20 修正為 15，對齊回測）
    buy_cost_rate = paper_common.BUY_COST_RATE
    sell_cost_rate = paper_common.SELL_COST_RATE
    slippage = paper_common.SLIPPAGE
    max_hold = paper_common.MAX_HOLD_DAYS
    position_size = paper_common.POSITION_SIZE

    print(f"📊 Paper Tracker 更新 ({today})")
    print(f"   初始資金: {data['initial_capital']:,.0f}")
    print(f"   當前現金: {data['capital']:,.0f}")
    print(f"   持倉檔數: {len(data['positions'])}")

    # 0. 避免重複執行
    if data['equity_curve'] and data['equity_curve'][-1].get('date') == today:
        print(f"   ⚠️ 今日已更新過，跳過")
        return

    # 1. 取得所有相關股票的最新價格
    all_tickers = list(data['positions'].keys())
    signals = extract_signals_from_report()
    signal_tickers = [s['ticker'] for s in signals]
    all_tickers_set = set(all_tickers + signal_tickers)
    prices = get_current_prices(list(all_tickers_set))

    # 2. 追蹤已持倉：檢查 TP/SL/時間到期
    to_close = []
    for ticker, pos in data['positions'].items():
        pos['day_count'] = pos.get('day_count', 0) + 1
        price = prices.get(ticker)
        if price is None:
            continue

        reason = None
        exit_price = price
        if price >= pos['tp']:
            reason = 'TP'
            exit_price = pos['tp']
        elif price <= pos['sl']:
            reason = 'SL'
            exit_price = pos['sl']
        elif pos['day_count'] >= max_hold:
            reason = 'TIME'
            exit_price = price

        if reason:
            # 計算 PnL
            sell_cost = exit_price * pos['shares'] * sell_cost_rate
            slippage_cost = exit_price * pos['shares'] * slippage
            proceeds = exit_price * pos['shares'] - sell_cost - slippage_cost
            cost_basis = pos['entry'] * pos['shares'] * (1 + buy_cost_rate + slippage)
            pnl = proceeds - cost_basis
            pnl_pct = (exit_price / pos['entry'] - 1) * 100

            data['capital'] += proceeds
            data['closed_trades'].append({
                'ticker': ticker,
                'entry': pos['entry'],
                'exit': exit_price,
                'shares': pos['shares'],
                'pnl': round(pnl, 0),
                'pnl_pct': round(pnl_pct, 2),
                'reason': reason,
                'entry_date': pos['entry_date'],
                'exit_date': today,
                'days_held': pos['day_count'],
            })
            to_close.append(ticker)
            emoji = '🟢' if pnl > 0 else '🔴'
            print(f"   {emoji} 平倉 {ticker}: {pos['entry']:.1f}→{exit_price:.1f} ({pnl_pct:+.1f}%) [{reason}] 持{pos['day_count']}天")

    for t in to_close:
        del data['positions'][t]

    # 3.5 更新持倉的當前股價（供 generate_html 顯示損益使用）
    for ticker, pos in data['positions'].items():
        if ticker in prices:
            pos['current_price'] = prices[ticker]

    # 3. 記錄今日信號 & 開新倉
    if signals:
        data['daily_signals'].append({'date': today, 'tickers': signal_tickers})
        max_new = 7 - len(data['positions'])
        opened = 0
        for sig in signals[:max_new]:
            ticker = sig['ticker']
            if ticker in data['positions']:
                continue
            entry_price = sig['entry']
            trade_amount = data['capital'] * position_size
            buy_cost = trade_amount * (buy_cost_rate + slippage)
            if data['capital'] >= trade_amount + buy_cost:
                shares = trade_amount / entry_price
                data['capital'] -= (trade_amount + buy_cost)
                data['positions'][ticker] = {
                    'entry': entry_price,
                    'tp': sig['tp'],
                    'sl': sig['sl'],
                    'entry_date': today,
                    'shares': round(shares, 0),
                    'day_count': 0,
                }
                opened += 1
                print(f"   🆕 開倉 {ticker} @ {entry_price:.1f} (TP {sig['tp']:.1f} / SL {sig['sl']:.1f})")
        if opened:
            print(f"   ✅ 今日開倉 {opened} 檔")
    else:
        print(f"   📋 今日無信號")

    # 4. 計算今日總權益
    total_equity = data['capital']
    for ticker, pos in data['positions'].items():
        price = prices.get(ticker, pos['entry'])
        total_equity += price * pos['shares']

    data['equity_curve'].append({
        'date': today,
        'equity': round(total_equity, 0),
        'capital': round(data['capital'], 0),
        'n_positions': len(data['positions']),
        'n_closed_today': len(to_close),
    })

    total_return = (total_equity / data['initial_capital'] - 1) * 100
    print(f"\n   💰 總權益: {total_equity:,.0f} ({total_return:+.1f}%)")
    print(f"   📈 已完成交易: {len(data['closed_trades'])} 筆")


def generate_html(data):
    """產出 paper trading 績效網頁。"""
    today = date.today().isoformat()
    initial = data['initial_capital']
    equity_curve = data['equity_curve']

    if not equity_curve:
        return

    latest_equity = equity_curve[-1]['equity']
    total_return = (latest_equity / initial - 1) * 100

    # 計算統計
    trades = data['closed_trades']
    n_trades = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    win_rate = len(wins) / n_trades * 100 if n_trades > 0 else 0
    avg_pnl = sum(t['pnl_pct'] for t in trades) / n_trades if n_trades else 0
    total_profit = sum(t['pnl'] for t in wins) if wins else 0
    total_loss = abs(sum(t['pnl'] for t in losses)) if losses else 1
    pf = total_profit / total_loss if total_loss > 0 else 0

    # MDD
    peak = initial
    mdd = 0
    for pt in equity_curve:
        if pt['equity'] > peak:
            peak = pt['equity']
        dd = (pt['equity'] - peak) / peak * 100
        if dd < mdd:
            mdd = dd

    # 年化 (簡化)
    n_days = len(equity_curve)
    ann_return = total_return * (252 / max(n_days, 1))

    # 權益曲線 JSON
    dates_json = json.dumps([p['date'] for p in equity_curve])
    equity_json = json.dumps([p['equity'] for p in equity_curve])
    benchmark_json = json.dumps([initial] * len(equity_curve))

    # 交易清單 (最近 30 筆)
    recent_trades = trades[-30:][::-1]

    # 取得所有相關股票名稱
    all_name_tickers = list(data['positions'].keys()) + [t['ticker'] for t in recent_trades]
    stock_names = get_stock_names(list(set(all_name_tickers)))

    trades_html = ""
    for t in recent_trades:
        color = '#2f7d4f' if t['pnl'] > 0 else '#b4452f'
        emoji = '🟢' if t['pnl'] > 0 else '🔴'
        name = stock_names.get(t['ticker'], t['ticker'])
        trades_html += f"""
        <tr>
            <td>{t['exit_date']}</td>
            <td><b>{t['ticker']}</b></td>
            <td>{name}</td>
            <td>{t['entry']:.1f}</td>
            <td>{t['exit']:.1f}</td>
            <td style="color:{color};font-weight:700">{t['pnl_pct']:+.1f}%</td>
            <td>{t['reason']}</td>
            <td>{t['days_held']}天</td>
        </tr>"""

    # 持倉
    positions_html = ""
    for ticker, pos in data['positions'].items():
        name = stock_names.get(ticker, ticker)
        current_price = pos.get('current_price', pos['entry'])
        pnl_pct = (current_price / pos['entry'] - 1) * 100
        pnl_color = '#2f7d4f' if pnl_pct >= 0 else '#b4452f'
        pnl_sign = '+' if pnl_pct >= 0 else ''
        positions_html += f"""
        <tr>
            <td><b>{ticker}</b></td>
            <td>{name}</td>
            <td>{int(pos.get('shares', 0)):,}</td>
            <td>{pos['entry']:.1f}</td>
            <td>{current_price:.1f}</td>
            <td style="color:{pnl_color};font-weight:700">{pnl_sign}{pnl_pct:.1f}%</td>
            <td>{pos['tp']:.1f}</td>
            <td>{pos['sl']:.1f}</td>
            <td>{pos['entry_date']}</td>
            <td>{pos.get('day_count', 0)}天</td>
        </tr>"""

    if not positions_html:
        positions_html = '<tr><td colspan="10" style="text-align:center;color:#7a6a52">目前無持倉</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Paper Trading v8.5 — {today}</title>
    <meta name="description" content="TW Stocker v8.5 Paper Trading 實時績效追蹤">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        :root {{
            --bg: #f0e4cc;
            --surface: #faf4e6;
            --surface-2: #f3e8d0;
            --surface-hover: #f6edd8;
            --border: rgba(120,88,46,0.18);
            --border-strong: rgba(120,88,46,0.34);
            --text: #3a2c1d;
            --text-dim: #7a6a52;
            --accent: #9c6b3f;
            --accent-2: #5f3c20;
            --gain: #2f7d4f;
            --loss: #b4452f;
            --warn: #b5852a;
            --radius: 16px;
            --shadow: 0 1px 2px rgba(80,52,24,0.10), 0 12px 30px rgba(80,52,24,0.13);
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html {{ -webkit-text-size-adjust: 100%; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans TC', sans-serif;
            background:
                repeating-linear-gradient(91deg, rgba(120,82,40,0.022) 0 1px, transparent 1px 9px),
                radial-gradient(1100px 520px at 50% -8%, rgba(156,107,63,0.16), transparent 60%),
                linear-gradient(165deg, #f4ead7 0%, #e7d6b6 100%);
            background-attachment: fixed;
            color: var(--text);
            min-height: 100vh;
            padding: 28px 20px 64px;
            font-variant-numeric: tabular-nums;
            font-feature-settings: "tnum" 1;
            -webkit-font-smoothing: antialiased;
        }}
        .container {{ max-width: 1040px; margin: 0 auto; }}
        h1 {{
            font-size: clamp(1.55rem, 5vw, 2rem);
            font-weight: 800;
            letter-spacing: -0.02em;
            background: linear-gradient(95deg, var(--accent), var(--accent-2));
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }}
        .subtitle {{
            color: var(--text-dim); margin-bottom: 26px; font-size: 0.9rem;
            display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
        }}
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin-bottom: 24px;
        }}
        .metric {{
            background: linear-gradient(160deg, var(--surface), var(--surface-2));
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 16px 18px;
            position: relative;
            overflow: hidden;
            transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
        }}
        .metric::before {{
            content: ""; position: absolute; left: 0; top: 0; bottom: 0;
            width: 3px; background: var(--accent);
        }}
        .metric:hover {{
            transform: translateY(-2px);
            border-color: var(--border-strong);
            box-shadow: var(--shadow);
        }}
        .metric .label {{
            color: var(--text-dim); font-size: 0.72rem;
            text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600;
        }}
        .metric .value {{ font-size: 1.5rem; font-weight: 700; margin-top: 4px; letter-spacing: -0.01em; }}
        .metric .value.green {{ color: var(--gain); }}
        .metric .value.red {{ color: var(--loss); }}
        .metric .value.blue {{ color: var(--accent); }}
        .chart-box {{
            background: linear-gradient(160deg, var(--surface), var(--surface-2));
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            margin-bottom: 24px;
        }}
        .chart-box h2 {{
            font-size: 1.05rem; margin-bottom: 14px; color: var(--text); font-weight: 700;
            padding-left: 12px; position: relative;
        }}
        .chart-box h2::before {{
            content: ""; position: absolute; left: 0; top: 0.15em; bottom: 0.15em;
            width: 4px; border-radius: 4px;
            background: linear-gradient(180deg, var(--accent), var(--accent-2));
        }}
        table {{ width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.85rem; }}
        th {{
            text-align: left; padding: 10px 12px;
            border-bottom: 2px solid var(--border-strong);
            color: var(--text-dim); font-weight: 600;
            font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.4px;
            white-space: nowrap;
        }}
        td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
        tbody tr {{ transition: background .12s ease; }}
        tr:hover {{ background: var(--surface-hover); }}
        td b {{ color: var(--text); font-weight: 600; }}
        .badge {{
            display: inline-flex; align-items: center;
            padding: 3px 10px; border-radius: 999px;
            font-size: 0.7rem; font-weight: 700;
        }}
        .badge-live {{
            background: rgba(47,125,79,0.14); color: var(--gain);
            border: 1px solid rgba(47,125,79,0.35);
        }}
        .disclaimer {{
            margin-top: 28px; padding: 16px;
            background: rgba(181,133,42,0.10);
            border: 1px solid var(--border);
            border-left: 4px solid var(--warn);
            border-radius: 12px;
            font-size: 0.78rem; color: var(--text-dim);
        }}
        @media (max-width: 720px) {{
            body {{ padding: 18px 12px 48px; }}
            .chart-box {{ padding: 16px 14px; }}
            table {{ display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
            .metric .value {{ font-size: 1.35rem; }}
        }}
    </style>
</head>
<body>
<div class="container">
    <h1>📈 Paper Trading v8.5</h1>
    <p class="subtitle">
        <span class="badge badge-live">● LIVE</span>
        起始日 {data['start_date']} | 更新 {today} | 初始資金 {initial:,.0f}
    </p>

    <div class="metrics">
        <div class="metric">
            <div class="label">總權益</div>
            <div class="value {'green' if total_return > 0 else 'red'}">{latest_equity:,.0f}</div>
        </div>
        <div class="metric">
            <div class="label">總報酬</div>
            <div class="value {'green' if total_return > 0 else 'red'}">{total_return:+.1f}%</div>
        </div>
        <div class="metric">
            <div class="label">年化報酬</div>
            <div class="value {'green' if ann_return > 0 else 'red'}">{ann_return:+.1f}%</div>
        </div>
        <div class="metric">
            <div class="label">最大回撤</div>
            <div class="value red">{mdd:.1f}%</div>
        </div>
        <div class="metric">
            <div class="label">勝率</div>
            <div class="value blue">{win_rate:.0f}%</div>
        </div>
        <div class="metric">
            <div class="label">交易數</div>
            <div class="value blue">{n_trades}</div>
        </div>
        <div class="metric">
            <div class="label">Profit Factor</div>
            <div class="value {'green' if pf > 1 else 'red'}">{pf:.2f}</div>
        </div>
        <div class="metric">
            <div class="label">持倉數</div>
            <div class="value blue">{len(data['positions'])}</div>
        </div>
    </div>

    <div class="chart-box">
        <h2>權益曲線</h2>
        <canvas id="equityChart" height="80"></canvas>
    </div>

    <div class="chart-box">
        <h2>🔓 目前持倉</h2>
        <table>
            <tr><th>股票</th><th>名稱</th><th>股數</th><th>進場價</th><th>當前股價</th><th>目前損益</th><th>停利</th><th>停損</th><th>進場日</th><th>持有</th></tr>
            {positions_html}
        </table>
    </div>

    <div class="chart-box">
        <h2>📋 近期交易（最近 30 筆）</h2>
        <table>
            <tr><th>日期</th><th>股票</th><th>名稱</th><th>進場</th><th>出場</th><th>損益</th><th>原因</th><th>持有</th></tr>
            {trades_html}
        </table>
    </div>

    <div class="disclaimer">
        ⚠️ <b>免責聲明：</b>此為 Paper Trading 模擬績效，非真實交易。歷史模擬不代表未來報酬。
        策略版本 v8.5 (Ablation-Proven)，含成本 0.58%/筆 + 10bps 滑價。投資有風險，決策請自行負責。
    </div>
</div>

<script>
const ctx = document.getElementById('equityChart').getContext('2d');
new Chart(ctx, {{
    type: 'line',
    data: {{
        labels: {dates_json},
        datasets: [{{
            label: 'Paper Trading 權益',
            data: {equity_json},
            borderColor: '#9c6b3f',
            backgroundColor: 'rgba(156, 107, 63, 0.16)',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
            borderWidth: 2,
        }}, {{
            label: '初始資金',
            data: {benchmark_json},
            borderColor: '#b9a07c',
            borderDash: [5, 5],
            fill: false,
            pointRadius: 0,
            borderWidth: 1,
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{ labels: {{ color: '#5a4a36' }} }},
        }},
        scales: {{
            x: {{ ticks: {{ color: '#7a6a52', maxTicksLimit: 10 }}, grid: {{ color: 'rgba(120,90,50,0.15)' }} }},
            y: {{ ticks: {{ color: '#7a6a52', callback: v => (v/1000).toFixed(0)+'K' }}, grid: {{ color: 'rgba(120,90,50,0.15)' }} }},
        }}
    }}
}});
</script>
</body>
</html>"""

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"   🌐 績效網頁已更新: {HTML_FILE}")


def main():
    parser = argparse.ArgumentParser(description='Paper Trading 自動追蹤器 v8.5')
    parser.add_argument('--reset', action='store_true', help='清除所有記錄重新開始')
    args = parser.parse_args()

    if args.reset:
        for f in [DATA_FILE, HTML_FILE]:
            if os.path.exists(f):
                os.remove(f)
        print("🔄 已清除所有 paper trading 記錄")
        return

    data = load_data()
    update_tracker(data)
    save_data(data)
    generate_html(data)
    print("✅ Paper Tracker 完成")


if __name__ == '__main__':
    main()
