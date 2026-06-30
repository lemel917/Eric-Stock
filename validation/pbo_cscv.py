"""Probability of Backtest Overfitting via CSCV.

CSCV (Combinatorially Symmetric Cross Validation) splits the time axis into
equal blocks, evaluates every train/test block combination, picks the best
configuration in train, and measures where that selected configuration ranks
out of sample. PBO is the fraction of splits where the selected configuration
lands in the lower half out of sample.
"""

from __future__ import annotations

import argparse
import itertools
import math
import sys
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from validation.deflated_sharpe import annualized_sharpe


@dataclass(frozen=True)
class PBOResult:
    pbo: float
    n_splits: int
    n_trials: int
    n_observations: int
    logits: list[float]
    selected_trials: list[str]
    split_results: list[dict[str, float | int | str]]


def _prepare_returns(returns_by_trial: dict[str, pd.Series] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(returns_by_trial, pd.DataFrame):
        df = returns_by_trial.copy()
    else:
        df = pd.DataFrame({name: pd.Series(series) for name, series in returns_by_trial.items()})
    df = df.replace([np.inf, -np.inf], np.nan).dropna(how="all")
    df = df.dropna(axis=1, how="all")
    df.columns = [str(col) for col in df.columns]
    return df


def sharpe_metric(values: pd.Series | np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 2:
        return float("-inf")
    return annualized_sharpe(arr)


def compute_pbo(
    returns_by_trial: dict[str, pd.Series] | pd.DataFrame,
    *,
    n_splits: int = 8,
    metric_func: Callable[[pd.Series], float] = sharpe_metric,
) -> PBOResult:
    """Compute PBO using CSCV over trial return series."""
    df = _prepare_returns(returns_by_trial)
    trial_names = [str(c) for c in df.columns]
    n_trials = len(trial_names)
    n_obs = len(df)

    if n_trials < 2 or n_obs < n_splits or n_splits < 2:
        return PBOResult(
            pbo=float("nan"),
            n_splits=n_splits,
            n_trials=n_trials,
            n_observations=n_obs,
            logits=[],
            selected_trials=[],
            split_results=[],
        )
    if n_splits % 2 != 0:
        raise ValueError("n_splits must be even for CSCV")

    split_indices = np.array_split(np.arange(n_obs), n_splits)
    all_combos = list(itertools.combinations(range(n_splits), n_splits // 2))
    # CSCV combinations are symmetric. Keep exactly one side of each
    # complement pair so train/test reversals are not double-counted.
    combos = []
    seen_pairs = set()
    all_split_set = set(range(n_splits))
    for combo in all_combos:
        complement = tuple(sorted(all_split_set - set(combo)))
        pair_key = tuple(sorted((combo, complement)))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        combos.append(combo)

    logits: list[float] = []
    selected_trials: list[str] = []
    split_results: list[dict[str, float | int | str]] = []

    for combo in combos:
        train_blocks = set(combo)
        test_blocks = all_split_set - train_blocks
        train_idx = np.concatenate([split_indices[i] for i in sorted(train_blocks)])
        test_idx = np.concatenate([split_indices[i] for i in sorted(test_blocks)])

        train_scores = df.iloc[train_idx].apply(metric_func, axis=0)
        test_scores = df.iloc[test_idx].apply(metric_func, axis=0)
        train_scores = train_scores.replace([np.inf, -np.inf], np.nan)
        test_scores = test_scores.replace([np.inf, -np.inf], np.nan)

        if train_scores.dropna().empty or test_scores.dropna().empty:
            continue

        selected = str(train_scores.idxmax())
        selected_test_score = float(test_scores[selected])
        valid_test_scores = test_scores.dropna()
        if not math.isfinite(selected_test_score) or valid_test_scores.empty:
            continue

        percentile = float((valid_test_scores <= selected_test_score).sum() / len(valid_test_scores))
        percentile = min(max(percentile, 1e-12), 1 - 1e-12)
        logit = math.log(percentile / (1.0 - percentile))

        logits.append(logit)
        selected_trials.append(selected)
        split_results.append({
            "train_blocks": ",".join(map(str, sorted(train_blocks))),
            "test_blocks": ",".join(map(str, sorted(test_blocks))),
            "selected_trial": selected,
            "train_metric": float(train_scores[selected]),
            "test_metric": selected_test_score,
            "test_percentile": percentile,
            "logit": logit,
        })

    pbo = float(np.mean([logit <= 0 for logit in logits])) if logits else float("nan")
    return PBOResult(
        pbo=pbo,
        n_splits=n_splits,
        n_trials=n_trials,
        n_observations=n_obs,
        logits=logits,
        selected_trials=selected_trials,
        split_results=split_results,
    )


def returns_from_csvs(paths: list[str]) -> pd.DataFrame:
    series = {}
    for path in paths:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if "Equity" not in df.columns:
            raise ValueError(f"{path} is missing an Equity column")
        series[path] = df["Equity"].pct_change().dropna()
    return pd.DataFrame(series)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute PBO using CSCV from equity CSV files")
    parser.add_argument("--equity", nargs="+", required=True, help="Equity CSV files, one per trial")
    parser.add_argument("--splits", type=int, default=8, help="Even number of CSCV time slices")
    args = parser.parse_args()

    df = returns_from_csvs(args.equity)
    result = compute_pbo(df, n_splits=args.splits)
    print(f"PBO: {result.pbo:.4f}")
    print(f"Trials: {result.n_trials}")
    print(f"Observations: {result.n_observations}")
    print(f"CSCV splits evaluated: {len(result.logits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
