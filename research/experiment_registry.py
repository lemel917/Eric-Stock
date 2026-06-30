"""SQLite-backed audit log for strategy research experiments.

The registry is intentionally small and dependency-light so every research
entry point can write to the same artifact without adopting a larger tracking
system. Metrics are stored as structured JSON, while key gate fields are also
promoted to columns for quick inspection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


DEFAULT_REGISTRY_PATH = "artifacts/experiments.sqlite"


SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_experiment_id(prefix: str = "exp") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def git_info(repo_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Return current git commit and dirty state, tolerating non-git contexts."""
    cwd = Path(repo_root or ".")

    def _run(args: list[str]) -> str | None:
        try:
            return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return None

    commit = _run(["git", "rev-parse", "HEAD"])
    status = _run(["git", "status", "--short"])
    return {
        "git_commit": commit,
        "git_dirty": bool(status),
    }


def data_snapshot_id(paths: Iterable[str | os.PathLike[str]] | None = None) -> str | None:
    """Create a lightweight fingerprint from data file names, sizes, and mtimes."""
    if paths is None:
        paths = [Path("data")]

    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.csv")))
        elif path.exists():
            files.append(path)

    if not files:
        return None

    digest = hashlib.sha256()
    for path in sorted(files):
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(str(path.as_posix()).encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(int(stat.st_mtime)).encode("ascii"))
    return digest.hexdigest()[:16]


def coerce_jsonable(value: Any) -> Any:
    """Convert pandas/numpy/scalar values into JSON-safe structures."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return coerce_jsonable(value.item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(k): coerce_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [coerce_jsonable(v) for v in value]
    return str(value)


def dumps_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(coerce_jsonable(value), ensure_ascii=False, sort_keys=True)


def daily_returns_from_equity(equity_df: pd.DataFrame | pd.Series | None) -> list[dict[str, Any]]:
    """Return a compact date/return JSON payload from an equity curve."""
    if equity_df is None:
        return []
    if isinstance(equity_df, pd.DataFrame):
        if "Equity" not in equity_df.columns:
            return []
        equity = equity_df["Equity"]
    else:
        equity = equity_df
    if equity.empty:
        return []
    equity = equity.copy()
    equity.index = pd.to_datetime(equity.index)
    returns = equity.sort_index().pct_change().dropna()
    return [
        {"date": idx.strftime("%Y-%m-%d"), "return": float(ret)}
        for idx, ret in returns.items()
        if pd.notna(ret) and math.isfinite(float(ret))
    ]


def daily_returns_from_equity_csv(path: str | os.PathLike[str] | None) -> list[dict[str, Any]]:
    if not path:
        return []
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    return daily_returns_from_equity(df)


def series_from_daily_returns(rows: list[dict[str, Any]] | None) -> pd.Series:
    """Convert a registry daily-return payload back into a pandas Series."""
    if not rows:
        return pd.Series(dtype=float)
    dates = [pd.Timestamp(row["date"]) for row in rows if "date" in row]
    values = [float(row["return"]) for row in rows if "return" in row]
    if len(dates) != len(values):
        return pd.Series(dtype=float)
    return pd.Series(values, index=pd.to_datetime(dates)).sort_index()


def latest_equity_artifact(artifact_dir: str | os.PathLike[str] = "artifacts") -> Path | None:
    root = Path(artifact_dir)
    if not root.exists():
        return None
    matches = list(root.glob("equity_*.csv"))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def trial_record(
    trial_id: str,
    parameters: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    daily_returns: list[dict[str, Any]] | None = None,
    decision: str | None = None,
    error: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Build a normalized trial payload for registry insertion."""
    metrics = metrics or {}
    return {
        "trial_id": trial_id,
        "parameters": parameters or {},
        "metrics": metrics,
        "daily_returns": daily_returns or [],
        "sharpe": metrics.get("sharpe"),
        "max_drawdown": metrics.get("max_drawdown_pct", metrics.get("mdd")),
        "ann_return": metrics.get("ann_return", metrics.get("ann")),
        "turnover": metrics.get("turnover"),
        "decision": decision,
        "error": error,
        "notes": notes,
    }


class ExperimentRegistry:
    """Persistence facade for the shared experiment SQLite database."""

    def __init__(self, db_path: str | os.PathLike[str] = DEFAULT_REGISTRY_PATH):
        self.db_path = Path(db_path)
        if self.db_path.parent:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    source TEXT,
                    git_commit TEXT,
                    git_dirty INTEGER NOT NULL DEFAULT 0,
                    data_snapshot_id TEXT,
                    strategy_version TEXT,
                    hypothesis TEXT,
                    parameter_space TEXT,
                    number_of_trials INTEGER,
                    in_sample_period TEXT,
                    out_of_sample_period TEXT,
                    daily_returns_json TEXT,
                    turnover REAL,
                    max_drawdown REAL,
                    sharpe REAL,
                    deflated_sharpe REAL,
                    pbo REAL,
                    crisis_score REAL,
                    paper_trading_status TEXT,
                    decision TEXT,
                    metrics_json TEXT,
                    command TEXT,
                    notes TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experiment_trials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL,
                    trial_id TEXT NOT NULL,
                    parameters_json TEXT,
                    metrics_json TEXT,
                    daily_returns_json TEXT,
                    sharpe REAL,
                    max_drawdown REAL,
                    ann_return REAL,
                    turnover REAL,
                    decision TEXT,
                    error TEXT,
                    notes TEXT,
                    UNIQUE(experiment_id, trial_id),
                    FOREIGN KEY(experiment_id)
                        REFERENCES experiments(experiment_id)
                        ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_experiments_created
                ON experiments(created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trials_experiment
                ON experiment_trials(experiment_id)
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    def record_experiment(
        self,
        *,
        experiment_id: str | None = None,
        source: str | None = None,
        strategy_version: str | None = None,
        hypothesis: str | None = None,
        parameter_space: dict[str, Any] | list[Any] | None = None,
        number_of_trials: int | None = None,
        in_sample_period: str | None = None,
        out_of_sample_period: str | None = None,
        metrics: dict[str, Any] | None = None,
        daily_returns: list[dict[str, Any]] | None = None,
        turnover: float | None = None,
        max_drawdown: float | None = None,
        sharpe: float | None = None,
        deflated_sharpe: float | None = None,
        pbo: float | None = None,
        crisis_score: float | None = None,
        paper_trading_status: str | None = None,
        decision: str | None = None,
        command: str | None = None,
        notes: str | None = None,
        trials: list[dict[str, Any]] | None = None,
        repo_root: str | os.PathLike[str] | None = None,
        data_paths: Iterable[str | os.PathLike[str]] | None = None,
    ) -> str:
        experiment_id = experiment_id or make_experiment_id()
        metrics = metrics or {}
        git = git_info(repo_root)

        if number_of_trials is None and trials is not None:
            number_of_trials = len(trials)

        if sharpe is None:
            sharpe = metrics.get("sharpe")
        if max_drawdown is None:
            max_drawdown = metrics.get("max_drawdown_pct", metrics.get("mdd"))
        if turnover is None:
            turnover = metrics.get("turnover")

        row = {
            "experiment_id": experiment_id,
            "created_at": utc_now_iso(),
            "source": source,
            "git_commit": git["git_commit"],
            "git_dirty": int(git["git_dirty"]),
            "data_snapshot_id": data_snapshot_id(data_paths),
            "strategy_version": strategy_version,
            "hypothesis": hypothesis,
            "parameter_space": dumps_json(parameter_space),
            "number_of_trials": number_of_trials,
            "in_sample_period": in_sample_period,
            "out_of_sample_period": out_of_sample_period,
            "daily_returns_json": dumps_json(daily_returns),
            "turnover": turnover,
            "max_drawdown": max_drawdown,
            "sharpe": sharpe,
            "deflated_sharpe": deflated_sharpe,
            "pbo": pbo,
            "crisis_score": crisis_score,
            "paper_trading_status": paper_trading_status,
            "decision": decision,
            "metrics_json": dumps_json(metrics),
            "command": command,
            "notes": notes,
        }

        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{col}=excluded.{col}" for col in columns if col != "experiment_id")

        with self.connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                f"""
                INSERT INTO experiments ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(experiment_id) DO UPDATE SET {updates}
                """,
                [row[col] for col in columns],
            )

            for trial in trials or []:
                conn.execute(
                    """
                    INSERT INTO experiment_trials (
                        experiment_id, trial_id, parameters_json, metrics_json,
                        daily_returns_json, sharpe, max_drawdown, ann_return,
                        turnover, decision, error, notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(experiment_id, trial_id) DO UPDATE SET
                        parameters_json=excluded.parameters_json,
                        metrics_json=excluded.metrics_json,
                        daily_returns_json=excluded.daily_returns_json,
                        sharpe=excluded.sharpe,
                        max_drawdown=excluded.max_drawdown,
                        ann_return=excluded.ann_return,
                        turnover=excluded.turnover,
                        decision=excluded.decision,
                        error=excluded.error,
                        notes=excluded.notes
                    """,
                    (
                        experiment_id,
                        trial["trial_id"],
                        dumps_json(trial.get("parameters")),
                        dumps_json(trial.get("metrics")),
                        dumps_json(trial.get("daily_returns")),
                        trial.get("sharpe"),
                        trial.get("max_drawdown"),
                        trial.get("ann_return"),
                        trial.get("turnover"),
                        trial.get("decision"),
                        trial.get("error"),
                        trial.get("notes"),
                    ),
                )
        return experiment_id

    def latest(self, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT experiment_id, created_at, source, strategy_version,
                           number_of_trials, sharpe, deflated_sharpe, pbo,
                           decision, hypothesis
                    FROM experiments
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )


def _format_row(row: sqlite3.Row) -> str:
    values = []
    for key in row.keys():
        val = row[key]
        if isinstance(val, float):
            val = f"{val:.4f}"
        values.append("" if val is None else str(val))
    return " | ".join(values)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the experiment registry")
    parser.add_argument("--db", default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--latest", type=int, default=10)
    args = parser.parse_args()

    registry = ExperimentRegistry(args.db)
    rows = registry.latest(args.latest)
    if not rows:
        print(f"No experiments found in {args.db}")
        return 0

    print(" | ".join(rows[0].keys()))
    print("-" * 120)
    for row in rows:
        print(_format_row(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
