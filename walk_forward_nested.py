#!/usr/bin/env python3
"""
Nested walk-forward research gate.

The existing walk_forward.py is a fixed-parameter OOS stability monitor. This
script adds the missing train -> select -> test loop:

  outer fold: anchored train window, next calendar year test window
  inner loop: choose the best candidate only on the train window
  registry: log every candidate, not just the winner

Example:
  python walk_forward_nested.py --quick
  python walk_forward_nested.py --first-test-year 2021 --last-test-year 2025
"""

import argparse
import math
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta

import pandas as pd

from research.experiment_registry import (
    DEFAULT_REGISTRY_PATH,
    ExperimentRegistry,
    daily_returns_from_equity_csv,
    latest_equity_artifact,
    series_from_daily_returns,
    trial_record,
)
from validation.deflated_sharpe import compute_deflated_sharpe
from validation.pbo_cscv import compute_pbo


DEFAULT_CANDIDATES = [
    ('baseline', ''),
    ('hold=15', '--hold-days 15'),
    ('hold=20', '--hold-days 20'),
    ('hold=25', '--hold-days 25'),
    ('k=5', '--top-k 5'),
    ('k=7', '--top-k 7'),
    ('tp=3.5', '--tp-atr 3.5'),
    ('tp=4.5', '--tp-atr 4.5'),
    ('sl=2.5', '--sl-atr 2.5'),
    ('sl=3.5', '--sl-atr 3.5'),
    ('gap=1.0', '--gap-filter 1.0'),
    ('gap=2.0', '--gap-filter 2.0'),
]

QUICK_CANDIDATES = [
    ('baseline', ''),
    ('hold=15', '--hold-days 15'),
    ('hold=25', '--hold-days 25'),
    ('k=5', '--top-k 5'),
    ('tp=4.5', '--tp-atr 4.5'),
    ('sl=2.5', '--sl-atr 2.5'),
]


FINALIST_CANDIDATES = [
    ('baseline', ''),
    ('gap=1.0', '--gap-filter 1.0'),
    ('hold=20+k=4', '--hold-days 20 --top-k 4'),
    ('tp=3.5+sl=3.0', '--tp-atr 3.5 --sl-atr 3.0'),
]


def run_backtest_range(start_date, end_date, eval_start=None, extra_args=''):
    """Run ai_report.py and return parsed metrics plus daily return payload."""
    cmd = [
        sys.executable,
        'ai_report.py',
        '--start-date', start_date,
        '--end-date', end_date,
    ]
    if eval_start:
        cmd.extend(['--eval-start', eval_start])
    if extra_args:
        cmd.extend(shlex.split(extra_args))

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    out = r.stdout + r.stderr
    if r.returncode != 0:
        raise RuntimeError(
            f"Backtest command failed with exit code {r.returncode}: {' '.join(cmd)}\n"
            f"{out[-2000:]}"
        )

    def get(pattern, label):
        m = re.search(pattern, out)
        if not m:
            raise ValueError(f"Failed to parse {label} from backtest output")
        return float(m.group(1))

    def get_first(patterns, label):
        for pattern in patterns:
            m = re.search(pattern, out)
            if m:
                return float(m.group(1))
        raise ValueError(f"Failed to parse {label} from backtest output")

    metrics = {
        'ann': get(r'年化報酬率:\s+([\+\-\d\.]+)%', 'annual return'),
        'sharpe': get(r'Sharpe Ratio:\s+([\+\-\d\.]+)', 'Sharpe'),
        'sortino': get(r'Sortino Ratio:\s+([\+\-\d\.]+)', 'Sortino'),
        'calmar': get(r'Calmar Ratio:\s+([\+\-\d\.]+)', 'Calmar'),
        'mdd': get(r'最大回撤:\s+([\+\-\d\.]+)%', 'max drawdown'),
        'trades': int(get_first([r'總交易數:\s+(\d+)', r'共 (\d+) 筆交易'], 'trade count')),
        'win_rate': get_first([r'勝率[:：]\s*([\d\.]+)%', r'勝率\s*([\d\.]+)%'], 'win rate'),
        'pf': get(r'Profit Factor:\s+(inf|[\d\.]+)', 'profit factor'),
    }
    equity_path = latest_equity_artifact()
    daily_returns = daily_returns_from_equity_csv(equity_path)
    return metrics, daily_returns, equity_path


def build_yearly_folds(train_start, first_test_year, last_test_year, warmup_days=120):
    folds = []
    for year in range(first_test_year, last_test_year + 1):
        test_start = pd.Timestamp(f'{year}-01-01')
        test_end = pd.Timestamp(f'{year}-12-31')
        train_end = test_start - pd.Timedelta(days=1)
        fetch_start = test_start - pd.Timedelta(days=warmup_days)
        folds.append({
            'fold': len(folds) + 1,
            'train_start': pd.Timestamp(train_start).strftime('%Y-%m-%d'),
            'train_end': train_end.strftime('%Y-%m-%d'),
            'test_fetch_start': fetch_start.strftime('%Y-%m-%d'),
            'test_start': test_start.strftime('%Y-%m-%d'),
            'test_end': test_end.strftime('%Y-%m-%d'),
        })
    return folds


def _pbo_from_trials(trials):
    returns_by_trial = {}
    for trial in trials:
        series = series_from_daily_returns(trial.get('daily_returns'))
        if not series.empty:
            returns_by_trial[trial['trial_id']] = series
    if len(returns_by_trial) < 2:
        return None
    pbo = compute_pbo(returns_by_trial, n_splits=8)
    return pbo.pbo if pbo.pbo == pbo.pbo else None


def _dsr_from_returns(daily_returns, n_trials):
    series = series_from_daily_returns(daily_returns)
    if len(series) < 3:
        return None, None
    dsr = compute_deflated_sharpe(series, n_trials=n_trials)
    return dsr.probability, dsr.deflated_sharpe


def main():
    parser = argparse.ArgumentParser(description='Nested walk-forward research gate')
    parser.add_argument('--train-start', type=str, default='2019-01-01',
                        help='Anchored train start date')
    parser.add_argument('--first-test-year', type=int, default=2021)
    parser.add_argument('--last-test-year', type=int, default=None,
                        help='Defaults to the last completed calendar year')
    parser.add_argument('--warmup-days', type=int, default=120)
    parser.add_argument('--quick', action='store_true',
                        help='Use a smaller candidate space')
    parser.add_argument('--candidate-set', choices=['default', 'quick', 'finalists'],
                        default='default',
                        help='Candidate universe to test')
    parser.add_argument('--test-all-candidates', action='store_true',
                        help='Also run every candidate on each OOS fold for finalist diagnostics')
    parser.add_argument('--select-metric', choices=['sharpe', 'calmar', 'ann'],
                        default='sharpe')
    parser.add_argument('--registry', type=str, default=DEFAULT_REGISTRY_PATH,
                        help='Experiment registry SQLite path')
    parser.add_argument('--no-registry', action='store_true',
                        help='Do not write to experiment registry')
    args = parser.parse_args()

    today = datetime.today()
    last_full_year = today.year - 1
    last_test_year = args.last_test_year or last_full_year
    if args.quick:
        candidates = QUICK_CANDIDATES
    elif args.candidate_set == 'quick':
        candidates = QUICK_CANDIDATES
    elif args.candidate_set == 'finalists':
        candidates = FINALIST_CANDIDATES
    else:
        candidates = DEFAULT_CANDIDATES
    folds = build_yearly_folds(
        args.train_start,
        args.first_test_year,
        last_test_year,
        warmup_days=args.warmup_days,
    )

    print(f"{'='*78}")
    print(f"Nested Walk-Forward Research Gate - {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*78}")
    print(f"Train anchor: {args.train_start}")
    print(f"Test years: {args.first_test_year}-{last_test_year}")
    print(f"Candidates per fold: {len(candidates)}")
    print(f"Selection metric: {args.select_metric}")
    print()

    all_trials = []
    fold_rows = []
    candidate_oos_rows = []

    for fold in folds:
        print(f"\nFold {fold['fold']}: train {fold['train_start']} -> {fold['train_end']}; "
              f"test {fold['test_start']} -> {fold['test_end']}")
        train_trials = []
        train_results = []

        for idx, (name, extra_args) in enumerate(candidates, 1):
            sys.stderr.write(f"[fold {fold['fold']} train {idx}/{len(candidates)}] {name}\n")
            sys.stderr.flush()
            trial_id = f"fold{fold['fold']}_train_{name}"
            try:
                metrics, daily_returns, equity_path = run_backtest_range(
                    fold['train_start'],
                    fold['train_end'],
                    extra_args=extra_args,
                )
                metrics['name'] = name
                metrics['args'] = extra_args
                train_results.append(metrics)
                trial = trial_record(
                    trial_id=trial_id,
                    parameters={
                        'fold': fold['fold'],
                        'phase': 'inner_train',
                        'candidate': name,
                        'args': extra_args,
                        'period': f"{fold['train_start']}->{fold['train_end']}",
                    },
                    metrics=metrics,
                    daily_returns=daily_returns,
                    decision='candidate',
                    notes=f'equity_artifact={equity_path}' if equity_path else None,
                )
            except Exception as exc:
                trial = trial_record(
                    trial_id=trial_id,
                    parameters={
                        'fold': fold['fold'],
                        'phase': 'inner_train',
                        'candidate': name,
                        'args': extra_args,
                    },
                    error=str(exc),
                    decision='reject',
                )
                print(f"  train {name}: FAILED - {exc}")
            train_trials.append(trial)
            all_trials.append(trial)

        if not train_results:
            print(f"  Fold {fold['fold']} skipped: no successful train candidates")
            continue

        selected = max(train_results, key=lambda x: x.get(args.select_metric, float('-inf')))
        selected_name = selected['name']
        selected_args = selected['args']
        fold_pbo = _pbo_from_trials(train_trials)

        print(f"  selected: {selected_name} "
              f"train {args.select_metric}={selected.get(args.select_metric):.3f}")

        test_candidates = candidates if args.test_all_candidates else [(selected_name, selected_args)]
        for test_name, test_args in test_candidates:
            test_trial_id = f"fold{fold['fold']}_test_{test_name}"
            is_selected = test_name == selected_name
            try:
                test_metrics, test_daily_returns, equity_path = run_backtest_range(
                    fold['test_fetch_start'],
                    fold['test_end'],
                    eval_start=fold['test_start'],
                    extra_args=test_args,
                )
                test_metrics['name'] = test_name
                test_metrics['args'] = test_args
                dsr_probability, dsr_z = _dsr_from_returns(test_daily_returns, len(candidates))
                test_metrics['dsr_probability'] = dsr_probability
                test_metrics['dsr_z'] = dsr_z
                test_metrics['fold_pbo'] = fold_pbo
                test_metrics['selected_by_train'] = is_selected

                test_trial = trial_record(
                    trial_id=test_trial_id,
                    parameters={
                        'fold': fold['fold'],
                        'phase': 'outer_test',
                        'candidate': test_name,
                        'args': test_args,
                        'selected_by_train': is_selected,
                        'train_period': f"{fold['train_start']}->{fold['train_end']}",
                        'test_period': f"{fold['test_start']}->{fold['test_end']}",
                    },
                    metrics=test_metrics,
                    daily_returns=test_daily_returns,
                    decision='watchlist',
                    notes=f'equity_artifact={equity_path}' if equity_path else None,
                )
                all_trials.append(test_trial)

                train_metric = selected.get(args.select_metric) if is_selected else None
                test_metric = test_metrics.get(args.select_metric)
                decay = test_metric / train_metric if train_metric and train_metric > 0 else None
                row = {
                    **fold,
                    'selected': selected_name,
                    'candidate': test_name,
                    'selected_by_train': is_selected,
                    'train_metric': train_metric,
                    'test_metric': test_metric,
                    'test_sharpe': test_metrics.get('sharpe'),
                    'test_mdd': test_metrics.get('mdd'),
                    'test_trades': test_metrics.get('trades'),
                    'decay': decay,
                    'dsr_probability': dsr_probability,
                    'pbo': fold_pbo,
                    'daily_returns': test_daily_returns,
                }
                candidate_oos_rows.append(row)
                if is_selected:
                    fold_rows.append({k: v for k, v in row.items() if k != 'daily_returns'})

                if is_selected:
                    decay_str = f"{decay:.2f}" if decay is not None else "NA"
                    dsr_str = f"{dsr_probability:.2f}" if dsr_probability is not None else "NA"
                    pbo_str = f"{fold_pbo:.2f}" if fold_pbo is not None else "NA"
                    print(f"  selected test Sharpe={test_metrics['sharpe']:.3f} "
                          f"MDD={test_metrics['mdd']:.1f}% decay={decay_str} "
                          f"DSR={dsr_str} PBO={pbo_str}")
                elif args.test_all_candidates:
                    print(f"  diagnostic {test_name}: Sharpe={test_metrics['sharpe']:.3f} "
                          f"MDD={test_metrics['mdd']:.1f}%")
            except Exception as exc:
                all_trials.append(trial_record(
                    trial_id=test_trial_id,
                    parameters={
                        'fold': fold['fold'],
                        'phase': 'outer_test',
                        'candidate': test_name,
                        'args': test_args,
                        'selected_by_train': is_selected,
                    },
                    error=str(exc),
                    decision='reject',
                ))
                print(f"  test {test_name}: FAILED - {exc}")

    if not fold_rows:
        print("\nNo successful folds.")
        return 1

    print(f"\n{'='*78}")
    print("Nested OOS Summary")
    print(f"{'='*78}")
    header = (f"{'Fold':<5s} | {'Test':<9s} | {'Selected':<10s} | "
              f"{'Train':>7s} | {'Test':>7s} | {'Decay':>6s} | "
              f"{'Sharpe':>7s} | {'MDD':>7s} | {'DSR':>5s} | {'PBO':>5s}")
    print(header)
    print('-' * len(header))
    for row in fold_rows:
        decay = row['decay']
        dsr = row['dsr_probability']
        pbo = row['pbo']
        print(f"{row['fold']:<5d} | {row['test_start'][:4]:<9s} | {row['selected']:<10s} | "
              f"{row['train_metric']:>7.3f} | {row['test_metric']:>7.3f} | "
              f"{decay if decay is not None else float('nan'):>6.2f} | "
              f"{row['test_sharpe']:>7.3f} | {row['test_mdd']:>6.1f}% | "
              f"{dsr if dsr is not None else float('nan'):>5.2f} | "
              f"{pbo if pbo is not None else float('nan'):>5.2f}")

    avg_test_sharpe = sum(row['test_sharpe'] for row in fold_rows) / len(fold_rows)
    min_test_sharpe = min(row['test_sharpe'] for row in fold_rows)
    valid_decays = [row['decay'] for row in fold_rows if row['decay'] is not None and math.isfinite(row['decay'])]
    avg_decay = sum(valid_decays) / len(valid_decays) if valid_decays else None
    pbo_values = [row['pbo'] for row in fold_rows if row['pbo'] is not None]
    max_pbo = max(pbo_values) if pbo_values else None

    print('-' * len(header))
    print(f"Average test Sharpe: {avg_test_sharpe:.3f}")
    print(f"Minimum test Sharpe: {min_test_sharpe:.3f}")
    if avg_decay is not None:
        print(f"Average OOS decay: {avg_decay:.2f}")
    if max_pbo is not None:
        print(f"Max fold PBO: {max_pbo:.2f}")

    candidate_summary = []
    candidate_pbo = None
    if args.test_all_candidates and candidate_oos_rows:
        print(f"\n{'='*78}")
        print("Finalist OOS Diagnostics")
        print(f"{'='*78}")

        returns_by_candidate = {}
        for name, _ in candidates:
            rows = [row for row in candidate_oos_rows if row['candidate'] == name]
            if not rows:
                continue
            sharpes = [row['test_sharpe'] for row in rows if row['test_sharpe'] is not None]
            mdds = [row['test_mdd'] for row in rows if row['test_mdd'] is not None]
            trades = [row['test_trades'] for row in rows if row['test_trades'] is not None]
            daily_returns = []
            for row in rows:
                daily_returns.extend(row.get('daily_returns') or [])
            series = series_from_daily_returns(daily_returns)
            if not series.empty:
                returns_by_candidate[name] = series
            candidate_summary.append({
                'candidate': name,
                'avg_oos_sharpe': sum(sharpes) / len(sharpes) if sharpes else None,
                'min_oos_sharpe': min(sharpes) if sharpes else None,
                'avg_oos_mdd': sum(mdds) / len(mdds) if mdds else None,
                'worst_oos_mdd': min(mdds) if mdds else None,
                'avg_trades': sum(trades) / len(trades) if trades else None,
                'selected_folds': sum(1 for row in rows if row['selected_by_train']),
                'n_folds': len(rows),
            })

        if len(returns_by_candidate) >= 2:
            pbo = compute_pbo(returns_by_candidate, n_splits=8)
            if pbo.pbo == pbo.pbo:
                candidate_pbo = pbo.pbo

        candidate_summary.sort(
            key=lambda row: (
                row['avg_oos_sharpe'] if row['avg_oos_sharpe'] is not None else float('-inf'),
                row['worst_oos_mdd'] if row['worst_oos_mdd'] is not None else float('-inf'),
            ),
            reverse=True,
        )
        header = (f"{'Candidate':<18s} | {'Avg Sh':>7s} | {'Min Sh':>7s} | "
                  f"{'Avg MDD':>8s} | {'Worst MDD':>9s} | {'Sel':>5s} | {'Folds':>5s}")
        print(header)
        print('-' * len(header))
        for row in candidate_summary:
            print(f"{row['candidate']:<18s} | {row['avg_oos_sharpe']:>7.3f} | "
                  f"{row['min_oos_sharpe']:>7.3f} | {row['avg_oos_mdd']:>7.1f}% | "
                  f"{row['worst_oos_mdd']:>8.1f}% | {row['selected_folds']:>5d} | "
                  f"{row['n_folds']:>5d}")
        if candidate_pbo is not None:
            print(f"Candidate-set PBO: {candidate_pbo:.2f}")

    decision = 'accept'
    pbo_gate = candidate_pbo if candidate_pbo is not None else max_pbo
    if min_test_sharpe < 0 or (pbo_gate is not None and pbo_gate > 0.5):
        decision = 'reject'
    elif avg_decay is not None and avg_decay < 0.7:
        decision = 'watchlist'

    if not args.no_registry:
        registry = ExperimentRegistry(args.registry)
        experiment_id = registry.record_experiment(
            source='walk_forward_nested.py',
            strategy_version='v8.5',
            hypothesis='Parameter selection should survive anchored nested OOS testing.',
            parameter_space=[{'name': name, 'args': extra_args} for name, extra_args in candidates],
            number_of_trials=len(all_trials),
            in_sample_period=f"{args.train_start}->{folds[-1]['train_end']}",
            out_of_sample_period=f"{folds[0]['test_start']}->{folds[-1]['test_end']}",
            metrics={
                'folds': fold_rows,
                'candidate_summary': candidate_summary,
                'avg_test_sharpe': avg_test_sharpe,
                'min_test_sharpe': min_test_sharpe,
                'avg_oos_decay': avg_decay,
                'max_pbo': max_pbo,
                'candidate_pbo': candidate_pbo,
            },
            sharpe=avg_test_sharpe,
            pbo=pbo_gate,
            decision=decision,
            command=' '.join(sys.argv),
            trials=all_trials,
        )
        print(f"\nExperiment registry: {args.registry} ({experiment_id})")

    print(f"Decision: {decision}")
    return 0 if decision != 'reject' else 1


if __name__ == '__main__':
    sys.exit(main())
