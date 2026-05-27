# 持倉表格新增當前股價與目前損益 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在「目前持倉」表格新增「當前股價」與「目前損益 (%)」兩個欄位，顯示各持倉相對進場價的即時損益百分比。

**Architecture:** 方案 A — 在 `update_tracker()` 將 yfinance 抓到的 `current_price` 寫入 `paper_equity.json` 的每個 position；`generate_html()` 讀取後計算百分比並渲染新欄位；同時直接 patch 靜態 `paper_trading.html` 作為立即佔位更新。

**Tech Stack:** Python 3、yfinance、f-string HTML 模板

---

### Task 1: `update_tracker()` — 持久化 current_price 到 positions

**Files:**
- Modify: `paper_tracker.py:269-281` （計算總權益的 for 迴圈之前）

- [ ] **Step 1: 在 `update_tracker()` 的 `# 4. 計算今日總權益` 之前加入 current_price 寫入**

開啟 `paper_tracker.py`，找到第 269 行附近的 `# 4. 計算今日總權益` 註解，在該區塊**之前**插入：

```python
    # 3.5 更新持倉的當前股價（供 generate_html 顯示損益使用）
    for ticker, pos in data['positions'].items():
        if ticker in prices:
            pos['current_price'] = prices[ticker]
```

插入位置在 `for t in to_close:` 迴圈之後、`# 4.` 之前，完整上下文如下：

```python
    for t in to_close:
        del data['positions'][t]

    # 3.5 更新持倉的當前股價（供 generate_html 顯示損益使用）
    for ticker, pos in data['positions'].items():
        if ticker in prices:
            pos['current_price'] = prices[ticker]

    # 3. 記錄今日信號 & 開新倉
```

- [ ] **Step 2: 驗證語法正確**

```powershell
python -c "import ast; ast.parse(open('paper_tracker.py').read()); print('syntax OK')"
```

Expected output: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add paper_tracker.py
git commit -m "feat: persist current_price in positions for P&L display"
```

---

### Task 2: `generate_html()` — 渲染新欄位

**Files:**
- Modify: `paper_tracker.py:354-370` （positions_html 迴圈）、`paper_tracker.py:512` （表頭 tr）、`paper_tracker.py:370` （空持倉 colspan）

- [ ] **Step 1: 修改表頭 `<tr>` — 加入兩個新欄位**

找到 `generate_html()` 中持倉表格表頭（約第 512 行）：

```python
            <tr><th>股票</th><th>名稱</th><th>進場價</th><th>停利</th><th>停損</th><th>進場日</th><th>持有</th></tr>
```

替換為：

```python
            <tr><th>股票</th><th>名稱</th><th>進場價</th><th>當前股價</th><th>目前損益</th><th>停利</th><th>停損</th><th>進場日</th><th>持有</th></tr>
```

- [ ] **Step 2: 修改 positions 迴圈 — 計算並渲染 current_price 與 pnl_pct**

找到 `generate_html()` 中的持倉迴圈（約第 355-367 行）：

```python
    positions_html = ""
    for ticker, pos in data['positions'].items():
        name = stock_names.get(ticker, ticker)
        positions_html += f"""
        <tr>
            <td><b>{ticker}</b></td>
            <td>{name}</td>
            <td>{pos['entry']:.1f}</td>
            <td>{pos['tp']:.1f}</td>
            <td>{pos['sl']:.1f}</td>
            <td>{pos['entry_date']}</td>
            <td>{pos.get('day_count', 0)}天</td>
        </tr>"""
```

替換為：

```python
    positions_html = ""
    for ticker, pos in data['positions'].items():
        name = stock_names.get(ticker, ticker)
        current_price = pos.get('current_price', pos['entry'])
        pnl_pct = (current_price / pos['entry'] - 1) * 100
        pnl_color = '#4ade80' if pnl_pct >= 0 else '#f87171'
        pnl_sign = '+' if pnl_pct >= 0 else ''
        positions_html += f"""
        <tr>
            <td><b>{ticker}</b></td>
            <td>{name}</td>
            <td>{pos['entry']:.1f}</td>
            <td>{current_price:.1f}</td>
            <td style="color:{pnl_color};font-weight:700">{pnl_sign}{pnl_pct:.1f}%</td>
            <td>{pos['tp']:.1f}</td>
            <td>{pos['sl']:.1f}</td>
            <td>{pos['entry_date']}</td>
            <td>{pos.get('day_count', 0)}天</td>
        </tr>"""
```

- [ ] **Step 3: 修改空持倉 fallback — colspan 從 7 改為 9**

找到：

```python
        positions_html = '<tr><td colspan="7" style="text-align:center;color:#888">目前無持倉</td></tr>'
```

替換為：

```python
        positions_html = '<tr><td colspan="9" style="text-align:center;color:#888">目前無持倉</td></tr>'
```

- [ ] **Step 4: 驗證語法正確**

```powershell
python -c "import ast; ast.parse(open('paper_tracker.py').read()); print('syntax OK')"
```

Expected output: `syntax OK`

- [ ] **Step 5: Commit**

```bash
git add paper_tracker.py
git commit -m "feat: add current price and P&L% columns to positions table"
```

---

### Task 3: 直接 patch `paper_trading.html` — 立即視覺更新

**Files:**
- Modify: `paper_trading.html:141` （表頭 tr）、`paper_trading.html:143-205` （各 position row）

這個 task 讓目前已部署的靜態 HTML 立即反映新欄位結構。由於 `paper_equity.json` 尚未有 `current_price`，當前股價佔位值使用進場價（損益顯示 `+0.0%`）。

- [ ] **Step 1: 修改表頭 — 加入「當前股價」與「目前損益」**

找到 `paper_trading.html` 第 141 行：

```html
            <tr><th>股票</th><th>名稱</th><th>進場價</th><th>停利</th><th>停損</th><th>進場日</th><th>持有</th></tr>
```

替換為：

```html
            <tr><th>股票</th><th>名稱</th><th>進場價</th><th>當前股價</th><th>目前損益</th><th>停利</th><th>停損</th><th>進場日</th><th>持有</th></tr>
```

- [ ] **Step 2: 修改每個持倉列 — 插入佔位欄位**

對每一個 `<tr>` 持倉列，在 `<td>{entry}</td>` 之後、`<td>{tp}</td>` 之前插入：

```html
            <td>{entry}</td>
            <td style="color:#4ade80;font-weight:700">+0.0%</td>
```

7 支持倉分別為（進場價如下）：
- 2327 國巨*：進場 629.0
- 3481 群創：進場 44.7
- 2454 聯發科：進場 3860.0
- 2303 聯電：進場 114.0
- 6415 矽力*-KY：進場 562.0
- 2408 南亞科：進場 310.5
- 6285 啟碁：進場 296.0

- [ ] **Step 3: 驗證 HTML 結構正確**

```powershell
python -c "
from html.parser import HTMLParser
class V(HTMLParser):
    def __init__(self): super().__init__(); self.th=0; self.td=0
    def handle_starttag(self,t,a):
        if t=='th': self.th+=1
        if t=='td': self.td+=1
v=V(); v.feed(open('paper_trading.html',encoding='utf-8').read())
print(f'th={v.th} td={v.td}')
"
```

Expected: `th` 包含 9 個 positions 表頭欄位（加上 transactions 表的 8 個），`td` 數量增加 14（7 列 × 2 新欄）。

- [ ] **Step 4: Commit**

```bash
git add paper_trading.html
git commit -m "fix: patch static HTML positions table with new columns (placeholder values)"
```

---

### Task 4: 端對端驗證

- [ ] **Step 1: 確認 `paper_equity.json` 目前結構（無 current_price 為預期）**

```powershell
python -c "
import json
data = json.load(open('paper_equity.json'))
pos = list(data['positions'].values())[0]
print('keys:', list(pos.keys()))
print('has current_price:', 'current_price' in pos)
"
```

Expected: `has current_price: False`（尚未執行 update_tracker）

- [ ] **Step 2: 用小型 smoke test 驗證 generate_html fallback 正確**

```powershell
python -c "
import json, sys
sys.argv = ['paper_tracker.py']
import paper_tracker
data = paper_tracker.load_data()
# 確認 fallback: 若無 current_price，損益應為 0%
pos = list(data['positions'].values())[0]
cp = pos.get('current_price', pos['entry'])
pnl = (cp / pos['entry'] - 1) * 100
print(f'fallback pnl: {pnl:+.1f}%')
assert abs(pnl) < 0.001, 'fallback should be 0%'
print('fallback OK')
"
```

Expected:
```
fallback pnl: +0.0%
fallback OK
```

- [ ] **Step 3: 推送到 GitHub，觸發 GitHub Actions 部署**

```bash
git push
```

確認 Actions 執行後，`paper_trading.html` 上的持倉表格顯示 9 欄，且損益為真實數值（非 +0.0%）。

---

## Self-Review 結果

| Spec 需求 | 對應 Task |
|---|---|
| `update_tracker()` 寫入 `current_price` | Task 1 |
| `generate_html()` 表頭加兩欄 | Task 2 Step 1 |
| `generate_html()` 每列加 current_price + pnl_pct | Task 2 Step 2 |
| `colspan` 7 → 9 | Task 2 Step 3 |
| 靜態 HTML 立即更新 | Task 3 |
| Fallback 為進場價 / +0.0% | Task 2 Step 2 + Task 4 Step 2 |
| 正值綠色 `#4ade80`，負值紅色 `#f87171` | Task 2 Step 2 |
