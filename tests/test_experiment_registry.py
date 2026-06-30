import sqlite3

from research.experiment_registry import ExperimentRegistry, trial_record


def test_experiment_registry_records_experiment_and_trials(tmp_path):
    db_path = tmp_path / "experiments.sqlite"
    registry = ExperimentRegistry(db_path)

    experiment_id = registry.record_experiment(
        experiment_id="exp_test",
        source="unit_test",
        strategy_version="v-test",
        hypothesis="registry writes structured experiment metadata",
        parameter_space={"x": [1, 2]},
        number_of_trials=1,
        metrics={"sharpe": 1.23},
        sharpe=1.23,
        decision="watchlist",
        trials=[
            trial_record(
                trial_id="trial_1",
                parameters={"x": 1},
                metrics={"sharpe": 1.23, "max_drawdown_pct": -0.1},
                daily_returns=[
                    {"date": "2024-01-02", "return": 0.01},
                    {"date": "2024-01-03", "return": -0.002},
                ],
            )
        ],
        data_paths=[],
    )

    assert experiment_id == "exp_test"

    with sqlite3.connect(db_path) as conn:
        exp_count = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        trial_count = conn.execute("SELECT COUNT(*) FROM experiment_trials").fetchone()[0]
        row = conn.execute(
            "SELECT source, strategy_version, sharpe, decision FROM experiments"
        ).fetchone()

    assert exp_count == 1
    assert trial_count == 1
    assert row == ("unit_test", "v-test", 1.23, "watchlist")

