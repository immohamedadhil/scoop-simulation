"""Tests for Module 8's experiment runner and honest-impact diagnostics."""

import pandas as pd
import pytest

from scoop.experiments import _workload_diagnostics, run_experiments
from scoop.generator import synthetic_network
from scoop.honest import make_workload, run_workload
from scoop.network import Network


def test_workload_diagnostics_agrees_with_existing_honest_runner():
    network = synthetic_network(n_nodes=35, seed=11, balance_model="half")
    workload = make_workload(network, n=12, seed=4)

    expected = run_workload(network, workload, amount=100)
    actual = _workload_diagnostics(network, workload, amount=100)

    assert actual["honest_success_rate"] == expected["success_rate"]
    assert actual["honest_success_volume"] == expected["success_volume"]
    assert actual["honest_mean_attempts"] == expected["mean_attempts"]
    assert actual["honest_failures_at_locked_channels"] == 0


def test_workload_diagnostics_counts_attacker_locked_edge_failures():
    network = Network()
    network.add_channel("a", "b", capacity=100, balance_x=50)
    network.add_channel("b", "c", capacity=100, balance_x=100)
    network.lock(("a", "b"), 50)
    details = _workload_diagnostics(network, [("a", "c")], amount=10, max_attempts=3)
    assert details["honest_failures"] == 1
    assert details["honest_failures_at_locked_channels"] == 1
    assert details["honest_fraction_failures_at_locked_channels"] == 1.0


def test_run_experiments_creates_csv_plots_and_report(tmp_path):
    def factory(seed):
        return synthetic_network(n_nodes=45, seed=seed, balance_model="half")

    raw = run_experiments(
        factory,
        output_dir=tmp_path,
        seeds=(0,),
        budgets=(100_000,),
        payment_amounts=(100,),
        n_payments=12,
        n_pairs=3,
        k_paths=4,
        max_path_length=8,
        balance_model="half",
        network_label="tiny test network",
    )

    assert set(raw["strategy"]) == {"no_attack", "random", "greedy_general", "spcr_max", "joint_spcr_max"}
    assert raw["delta_success_rate"].notna().all()
    for name in (
        "raw_results.csv", "summary.csv", "paired_differences.csv",
        "locked_payment_by_strategy.png", "honest_success_rate.png",
        "mean_pcr_by_strategy.png", "mean_spcr_by_strategy.png", "summary_report.md",
    ):
        assert (tmp_path / name).is_file(), name
    saved = pd.read_csv(tmp_path / "raw_results.csv")
    assert len(saved) == len(raw)
    assert saved["seed"].nunique() == 1
    assert saved["payment_amount"].nunique() == 1
    assert "gamma_printed_L20" in saved.columns
    assert "path_length_mean" in saved.columns
    assert "budget_per_owner" in saved.columns
    assert set(saved["route_mode"]) == {"sender_to_all_receivers"}
    assert set(saved["budget_scope"]) == {"per sender"}
    config = (tmp_path / "experiment_config.json").read_text(encoding="utf-8")
    assert '"route_mode": "sender_to_all_receivers"' in config
    report = (tmp_path / "summary_report.md").read_text(encoding="utf-8")
    assert "modeled, not observed" in report
    assert "Budget scope: per sender" in report

    repeated = run_experiments(
        factory,
        output_dir=tmp_path / "repeated",
        seeds=(0,),
        budgets=(100_000,),
        payment_amounts=(100,),
        n_payments=12,
        n_pairs=3,
        k_paths=4,
        max_path_length=8,
        balance_model="half",
        network_label="tiny test network",
    )
    pd.testing.assert_frame_equal(
        raw[["strategy", "locked_payment", "honest_success_rate", "delta_success_rate"]],
        repeated[["strategy", "locked_payment", "honest_success_rate", "delta_success_rate"]],
    )


def test_run_experiments_rejects_invalid_settings(tmp_path):
    def factory(seed):
        return synthetic_network(n_nodes=30, seed=seed, balance_model="half")

    with pytest.raises(ValueError, match="seeds must contain"):
        run_experiments(factory, output_dir=tmp_path, seeds=())


def test_workload_diagnostics_rejects_invalid_amount():
    with pytest.raises(ValueError, match="amount must be"):
        _workload_diagnostics(Network(), [], amount=-1)


def test_checkpoint_can_resume_an_interrupted_run_without_duplicate_rows(tmp_path):
    import json

    def factory(seed):
        return synthetic_network(n_nodes=45, seed=seed, balance_model="half")

    settings = dict(
        output_dir=tmp_path,
        seeds=(0,),
        budgets=(100_000,),
        n_payments=8,
        n_pairs=3,
        k_paths=4,
        max_path_length=8,
        balance_model="half",
        network_label="tiny checkpoint test network",
    )

    # Start with one amount, so the runner writes a valid checkpoint.
    partial = run_experiments(factory, payment_amounts=(100,), **settings)
    checkpoint_path = tmp_path / "raw_results_checkpoint.csv"
    config_path = tmp_path / "experiment_config.json"
    assert checkpoint_path.is_file()
    assert len(pd.read_csv(checkpoint_path)) == 5

    # Simulate the originally intended two-amount run being interrupted
    # after its first complete scenario was checkpointed.
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["honest_payment_amounts_satoshi"] = [100, 200]
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    resumed = run_experiments(
        factory,
        payment_amounts=(100, 200),
        resume=True,
        **settings,
    )

    assert len(resumed) == 10
    assert len(pd.read_csv(checkpoint_path)) == 10
    assert not resumed.duplicated(["seed", "budget_per_owner", "payment_amount", "strategy"]).any()
    assert set(resumed["payment_amount"]) == {100, 200}
    assert len(partial) == 5


def test_resume_rejects_changed_settings(tmp_path):
    def factory(seed):
        return synthetic_network(n_nodes=45, seed=seed, balance_model="half")

    common = dict(
        output_dir=tmp_path,
        seeds=(0,),
        budgets=(100_000,),
        payment_amounts=(100,),
        n_payments=8,
        n_pairs=3,
        k_paths=4,
        max_path_length=8,
        balance_model="half",
        network_label="tiny checkpoint test network",
    )
    run_experiments(factory, **common)
    changed = dict(common)
    changed["n_payments"] = 9

    with pytest.raises(ValueError, match="settings differ"):
        run_experiments(factory, resume=True, **changed)
