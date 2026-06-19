"""因子層級驗證框架 (Factor Evaluation, OPT-03 / OPT-04)。

回應系統檢查指出的缺口：策略僅有「整體回測」績效，缺乏「單因子」層級的
預測力驗證，因此難以判斷因子是否真的有效、或只是過擬合。

本模組提供標準量化因子分析工具（皆為純函式、可單元測試，不依賴外部資料）：

- zscore_normalize : 橫截面 z-score 標準化（OPT-04）
- forward_returns  : 未來 N 日報酬（作為 label；使用時不得用於同期決策）
- information_coefficient : 每日橫截面 IC（因子 rank 與未來報酬的相關係數）
- ic_summary       : IC 統計（mean IC / ICIR / t-stat / hit-rate）
- quantile_long_short : 分層多空（依因子分 N 層，top - bottom 報酬價差）
- ic_by_horizon    : 不同持有期的 IC（檢視因子衰減；OPT-04）

IC（Information Coefficient）是因子預測力的業界標準：每個截面日計算「因子值排名」
與「未來報酬」的（Spearman）相關，取時間序列平均。ICIR = mean(IC)/std(IC)，
衡量預測力的穩定度。
"""
import numpy as np
import pandas as pd


def zscore_normalize(factor_df, universe_mask=None):
    """橫截面 z-score 標準化：每個日期(列)減均值除標準差。

    Parameters
    ----------
    factor_df : pd.DataFrame  (日期 x 股票) 因子值
    universe_mask : pd.DataFrame(bool), optional  只在 universe 內標準化

    Returns
    -------
    pd.DataFrame  標準化後的因子（均值 0、標準差 1，逐列）
    """
    f = factor_df.where(universe_mask) if universe_mask is not None else factor_df
    mean = f.mean(axis=1)
    std = f.std(axis=1).replace(0, np.nan)
    return f.sub(mean, axis=0).div(std, axis=0)


def forward_returns(close_df, horizon=20):
    """未來 horizon 日報酬 close[t+h]/close[t] - 1。

    注意：此為「label」用途，使用 shift(-horizon) 取未來值。只可用於因子
    *事後評估*（IC/分層），絕不可當成 t 日的可用資訊放進交易決策。
    """
    return close_df.shift(-horizon) / close_df - 1


def information_coefficient(factor_df, close_df, horizon=20, method="spearman",
                            universe_mask=None, min_obs=5):
    """每日橫截面 IC：因子值與未來 horizon 日報酬的相關係數，回傳 Series(index=日期)。

    觀測數不足 min_obs 的日期回傳 NaN。預設 Spearman（rank IC，對極端值穩健）。
    """
    fwd = forward_returns(close_df, horizon)
    f = factor_df
    if universe_mask is not None:
        f = f.where(universe_mask)
        fwd = fwd.where(universe_mask)

    out = {}
    for dt in f.index:
        pair = pd.concat([f.loc[dt], fwd.loc[dt]], axis=1).dropna()
        if len(pair) >= min_obs:
            out[dt] = pair.iloc[:, 0].corr(pair.iloc[:, 1], method=method)
        else:
            out[dt] = np.nan
    return pd.Series(out, name=f"IC_{horizon}d")


def ic_summary(ic_series):
    """彙總 IC 時間序列：mean IC / IC std / ICIR / t-stat / 命中率 / 期數。

    ICIR = mean(IC)/std(IC)；t-stat = ICIR * sqrt(N)；hit_rate = IC>0 的比例。
    """
    ic = ic_series.dropna()
    n = len(ic)
    if n == 0:
        return {"ic_mean": 0.0, "ic_std": 0.0, "icir": 0.0,
                "t_stat": 0.0, "hit_rate": 0.0, "n_periods": 0}
    mean = float(ic.mean())
    std = float(ic.std())
    icir = mean / std if std > 0 else 0.0
    return {
        "ic_mean": mean,
        "ic_std": std,
        "icir": icir,
        "t_stat": icir * np.sqrt(n),
        "hit_rate": float((ic > 0).mean()),
        "n_periods": n,
    }


def quantile_long_short(factor_df, close_df, horizon=20, n_quantiles=5,
                        universe_mask=None):
    """分層多空分析：每日依因子分 n_quantiles 層，計算各層平均未來報酬，
    以及「最高層 - 最低層」的多空價差。

    因子若有效，平均報酬應隨分層單調遞增、long-short 顯著為正。

    Returns
    -------
    dict:
        quantile_returns : list[float]  各層(由低到高)的平均未來報酬
        long_short_mean  : float        多空價差時間序列均值
        long_short_series: pd.Series    每日多空價差
    """
    fwd = forward_returns(close_df, horizon)
    f = factor_df
    if universe_mask is not None:
        f = f.where(universe_mask)
        fwd = fwd.where(universe_mask)

    per_q = {q: [] for q in range(n_quantiles)}
    ls = {}
    for dt in f.index:
        pair = pd.concat([f.loc[dt], fwd.loc[dt]], axis=1).dropna()
        pair.columns = ["factor", "fwd"]
        if len(pair) < n_quantiles:
            continue
        try:
            labels = pd.qcut(pair["factor"], n_quantiles, labels=False,
                             duplicates="drop")
        except ValueError:
            continue
        means = pair["fwd"].groupby(labels).mean()
        for q, m in means.items():
            per_q[int(q)].append(m)
        top, bottom = int(labels.max()), int(labels.min())
        if top != bottom:
            ls[dt] = means.loc[top] - means.loc[bottom]

    quantile_returns = [float(np.mean(per_q[q])) if per_q[q] else float("nan")
                        for q in range(n_quantiles)]
    ls_series = pd.Series(ls, name="long_short")
    return {
        "quantile_returns": quantile_returns,
        "long_short_mean": float(ls_series.mean()) if len(ls_series) else 0.0,
        "long_short_series": ls_series,
    }


def ic_by_horizon(factor_df, close_df, horizons=(1, 5, 10, 20, 60),
                  method="spearman", universe_mask=None):
    """計算多個持有期的 mean IC，用於觀察因子預測力隨期間的衰減。

    Returns
    -------
    dict[int, dict]  {horizon: ic_summary(...)}
    """
    result = {}
    for h in horizons:
        ic = information_coefficient(factor_df, close_df, horizon=h,
                                     method=method, universe_mask=universe_mask)
        result[h] = ic_summary(ic)
    return result
