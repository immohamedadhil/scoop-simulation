"""Repeatable synthetic or real-topology SCOOP-inspired experiments.

The runner compares attack strategies and a no-attack baseline on the same
network shape, Sybil attachment, and pre-generated honest payment workload.
Every channel balance in a topology loaded from a snapshot is modeled, not observed.
"""
from __future__ import annotations

import argparse
from collections import deque
import json
import math
from pathlib import Path
import statistics
import time
from typing import Callable, Iterable

from scipy.stats import t as student_t

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .attacks import ATTACK_STRATEGIES, run_attack
from .generator import BALANCE_MODELS, synthetic_network
from .honest import DEFAULT_PAYMENTS, MAX_ATTEMPTS, make_workload
from .paths import ROUTE_MODES, add_sybils, find_routes
from .topology import load_topology
from .network import Network

DEFAULT_BUDGETS = (75_000_000, 100_000_000)
DEFAULT_PAYMENT_AMOUNTS = (10_000, 100_000, 1_000_000)


def _shortest_path(graph, source, target, banned: set):
    """Find a fewest-hop route while avoiding previously failed directed edges."""
    if source == target:
        return [source]
    previous = {source: None}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for neighbor in graph.successors(node):
            if neighbor in previous or (node, neighbor) in banned:
                continue
            previous[neighbor] = node
            if neighbor == target:
                path = [target]
                while previous[path[-1]] is not None:
                    path.append(previous[path[-1]])
                return path[::-1]
            queue.append(neighbor)
    return None


def _workload_diagnostics(
    network: Network,
    workload: list[tuple],
    amount: int,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict[str, int | float]:
    """Run honest traffic and report success metrics plus failures at locked edges.

    The routing and payment rules intentionally mirror ``honest.run_workload``.
    ``locked`` is not increased by successful honest payments, so a positive
    value identifies an edge on which attacker funds remain stuck.
    """
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ValueError("amount must be a non-negative integer")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")

    working = network.copy()
    successes = total_attempts = volume = 0
    failures_at_locked = 0
    n = len(workload)
    for sender, receiver in workload:
        banned: set = set()
        used_locked_edge = False
        success = False
        attempts_used = 0
        for attempt in range(1, max_attempts + 1):
            attempts_used = attempt
            path = _shortest_path(working.graph, sender, receiver, banned)
            if path is None:
                break
            hops = list(zip(path, path[1:]))
            insufficient = next(((x, y) for x, y in hops if working.balance(x, y) < amount), None)
            if insufficient is None:
                working.pay(path, amount)
                success = True
                break
            x, y = insufficient
            if working.locked(x, y) > 0:
                used_locked_edge = True
            banned.add((x, y))
        total_attempts += attempts_used
        if success:
            successes += 1
            volume += amount
        else:
            if used_locked_edge:
                failures_at_locked += 1
    failures = n - successes
    exhausted = sum(1 for _, _, data in network.graph.edges(data=True)
                    if data.get("locked", 0) > 0 and data.get("balance", 0) == 0)
    return {
        "honest_amount": amount,
        "honest_payments": n,
        "honest_successes": successes,
        "honest_failures": failures,
        "honest_success_rate": successes / n if n else 0.0,
        "honest_success_volume": volume,
        "honest_mean_attempts": total_attempts / n if n else 0.0,
        "honest_failures_at_locked_channels": failures_at_locked,
        "honest_fraction_failures_at_locked_channels": failures_at_locked / failures if failures else 0.0,
        "attacker_locked_directions_exhausted": exhausted,
    }


def _confidence_interval(values: Iterable[float]) -> tuple[float, float, float, int]:
    """Return mean, low CI, high CI and sample count using a 95% t interval."""
    numbers = [float(value) for value in values if pd.notna(value)]
    if not numbers:
        return math.nan, math.nan, math.nan, 0
    mean = statistics.fmean(numbers)
    if len(numbers) < 2:
        return mean, math.nan, math.nan, len(numbers)
    critical = float(student_t.ppf(0.975, df=len(numbers) - 1))
    margin = critical * statistics.stdev(numbers) / math.sqrt(len(numbers))
    return mean, mean - margin, mean + margin, len(numbers)


def _summaries(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate raw metric summaries and paired attack-minus-baseline effects."""
    summary_rows: list[dict] = []
    metric_columns = [
        "locked_payment", "mean_pcr", "mean_spcr_L20", "mean_spcr_L8",
        "gamma_ratio", "gamma_printed_L20", "gamma_printed_L8",
        "honest_success_rate", "honest_success_volume", "honest_mean_attempts",
        "honest_fraction_failures_at_locked_channels",
    ]
    grouping = ["balance_model", "route_mode", "strategy", "budget_per_owner", "payment_amount"]
    for keys, group in raw.groupby(grouping, dropna=False, sort=True):
        row = dict(zip(grouping, keys))
        for metric in metric_columns:
            mean, low, high, n = _confidence_interval(group[metric].dropna().tolist())
            row[f"{metric}_mean"] = mean
            row[f"{metric}_ci95_low"] = low
            row[f"{metric}_ci95_high"] = high
            row[f"{metric}_n"] = n
        summary_rows.append(row)

    # Deltas are already paired inside each seed/budget/payment setting.
    paired_rows: list[dict] = []
    delta_columns = ["delta_success_rate", "delta_success_volume", "delta_mean_attempts"]
    non_baseline = raw[raw["strategy"] != "no_attack"]
    paired_grouping = ["balance_model", "route_mode", "strategy", "budget_per_owner", "payment_amount"]
    for keys, group in non_baseline.groupby(paired_grouping, dropna=False, sort=True):
        row = dict(zip(paired_grouping, keys))
        for metric in delta_columns:
            mean, low, high, n = _confidence_interval(group[metric].dropna().tolist())
            row[f"{metric}_mean"] = mean
            row[f"{metric}_ci95_low"] = low
            row[f"{metric}_ci95_high"] = high
            row[f"{metric}_n"] = n
        paired_rows.append(row)
    return pd.DataFrame(summary_rows), pd.DataFrame(paired_rows)


def _write_plots(raw: pd.DataFrame, output_dir: Path) -> list[Path]:
    """Write two simple plots and return their paths."""
    created: list[Path] = []
    if raw.empty:
        return created

    attack_rows = raw.drop_duplicates(subset=["seed", "route_mode", "budget_per_owner", "strategy"])
    means = attack_rows.groupby(["budget_per_owner", "strategy"], dropna=False)["locked_payment"].mean().reset_index()
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for budget, group in means.groupby("budget_per_owner", sort=True):
        ax.plot(group["strategy"], group["locked_payment"] / 1_000_000, marker="o", label=f"B={budget:,} sat/owner")
    ax.set_title("Attacker locked payment by strategy")
    ax.set_xlabel("Strategy")
    ax.set_ylabel("Locked payment (million satoshi)")
    ax.tick_params(axis="x", rotation=20)
    ax.legend()
    fig.tight_layout()
    path = output_dir / "locked_payment_by_strategy.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(path)

    means = raw.groupby(["strategy", "payment_amount"], dropna=False)["honest_success_rate"].mean().reset_index()
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for amount, group in means.groupby("payment_amount", sort=True):
        ax.plot(group["strategy"], group["honest_success_rate"], marker="o", label=f"payment={amount:,} sat")
    ax.set_title("Honest payment success rate")
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Success rate")
    ax.set_ylim(0, 1.02)
    ax.tick_params(axis="x", rotation=20)
    ax.legend()
    fig.tight_layout()
    path = output_dir / "honest_success_rate.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(path)

    # Paper-aligned attack-side metrics, calculated once per seed/strategy/budget
    # rather than repeatedly across the honest-payment amount sweep.
    attack_rows = raw.drop_duplicates(subset=["seed", "route_mode", "budget_per_owner", "strategy"])
    for metric, title, ylabel, filename in (
        ("mean_pcr", "Mean path congestion ratio by strategy", "Mean PCR", "mean_pcr_by_strategy.png"),
        ("mean_spcr_L8", "Mean scaled path congestion ratio (L_max=8)", "Mean SPCR (L_max=8)", "mean_spcr_by_strategy.png"),
    ):
        means = attack_rows.groupby(["budget_per_owner", "strategy"], dropna=False)[metric].mean().reset_index()
        fig, ax = plt.subplots(figsize=(10, 5.5))
        for budget, group in means.groupby("budget_per_owner", sort=True):
            ax.plot(group["strategy"], group[metric], marker="o", label=f"B={budget:,} sat/owner")
        ax.set_title(title)
        ax.set_xlabel("Strategy")
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", rotation=20)
        ax.legend()
        fig.tight_layout()
        path = output_dir / filename
        fig.savefig(path, dpi=160)
        plt.close(fig)
        created.append(path)
    return created


def _write_report(raw: pd.DataFrame, summary: pd.DataFrame, output_dir: Path, network_label: str) -> Path:
    """Write a compact Markdown summary with the modeling limitations."""
    path = output_dir / "summary_report.md"
    if raw.empty:
        path.write_text("# SCOOP-inspired experiment report\n\nNo results were produced.\n", encoding="utf-8")
        return path
    seeds = sorted(int(value) for value in raw["seed"].unique())
    budgets = sorted(int(value) for value in raw["budget_per_owner"].unique())
    amounts = sorted(int(value) for value in raw["payment_amount"].unique())
    strategy_means = (
        raw.groupby("strategy", dropna=False)["honest_success_rate"].mean()
        .sort_values(ascending=False).to_dict()
    )
    table_lines = ["| Scenario | Mean honest success rate |", "|---|---:|"]
    table_lines.extend(f"| {name} | {value:.4f} |" for name, value in strategy_means.items())
    content = f"""# SCOOP-inspired simulation report

## Setup

- Network input: {network_label}
- Balance model: {', '.join(sorted(set(raw['balance_model'].astype(str))))}; balances are **modeled, not observed**.
- Seeds: {', '.join(map(str, seeds))}
- Route mode: {raw['route_mode'].iloc[0]}
- Budget scope: {raw['budget_scope'].iloc[0]}
- Budget per owner (satoshi): {', '.join(f'{value:,}' for value in budgets)}
- Honest payment amounts (satoshi): {', '.join(f'{value:,}' for value in amounts)}
- Strategies: {', '.join(sorted(raw['strategy'].astype(str).unique()))}

## Observed results

Mean honest payment success rate across the completed rows:

{chr(10).join(table_lines)}

See `raw_results.csv` for the individual seed results, `summary.csv` for means and 95% confidence intervals, and `paired_differences.csv` for attack-minus-no-attack effects paired by seed.

## Modeling choices and limitations

This is a simulation on a static topology inspired by SCOOP; it is not a reproduction of SCOOP and does not interact with a live Lightning node. Channel balances are generated because the real balances are private. The `sender_to_all_receivers` mode models six sender Sybils and six receiver Sybils; each sender shares one budget across routes to all receivers. The paper's exact route enumeration and balance split are not fully specified, so `fixed_pairs` remains available as a sensitivity baseline. The topology loader excludes a physical channel if either directional policy is missing or disabled. Honest payments use shortest-hop routing with retries that exclude a failed directed hop. Fees, HTLC slot limits, and timeouts are not modeled, and attacker locks remain in place during honest workload measurements. Each strategy uses the same pre-generated honest workload and a matching no-attack baseline for its seed, budget, and payment amount.

Attack-side PCR and SPCR are reported separately from honest-payment success. `honest_coin_hops_stuck` is an aggregate over route interiors, not a count of unique coins, because overlapping routes can count the same channel more than once. Do not tune parameters to match the paper's numbers. Treat differences between strategies and between congestion metrics and honest payment failures as empirical findings.
"""
    path.write_text(content, encoding="utf-8")
    return path


def run_experiments(
    network_factory: Callable[[int], Network | tuple[Network, dict]],
    output_dir: str | Path = "results",
    *,
    seeds: Iterable[int] = range(20),
    budgets: Iterable[int] = DEFAULT_BUDGETS,
    payment_amounts: Iterable[int] = DEFAULT_PAYMENT_AMOUNTS,
    n_payments: int = DEFAULT_PAYMENTS,
    n_pairs: int = 6,
    k_paths: int = 50,
    max_path_length: int = 8,
    attachment: str = "hubs",
    route_mode: str = "sender_to_all_receivers",
    balance_model: str = "uniform",
    network_label: str = "provided network factory",
    resume: bool = False,
) -> pd.DataFrame:
    """Run all attacks and save raw CSV, summaries, plots, and a report.

    A fresh network is produced for each seed. For each budget, the no-attack
    baseline and every strategy share the same Sybil-augmented topology and the
    exact same honest workload. By default, each of the N senders has candidate
    routes to all N receivers; each sender shares one budget across its routes.
    Use ``route_mode="fixed_pairs"`` to recreate the older one-destination model.
    ``network_factory(seed)`` may return a Network,
    or ``(Network, metadata_dict)`` when the loader has preprocessing counts.
    Reusing a seed must recreate the same topology and balance assignment.
    """
    seed_list = tuple(seeds)
    budget_list = tuple(budgets)
    amount_list = tuple(payment_amounts)
    if not seed_list or any(isinstance(s, bool) or not isinstance(s, int) or s < 0 for s in seed_list):
        raise ValueError("seeds must contain non-negative integers")
    if not budget_list or any(isinstance(b, bool) or not isinstance(b, int) or b < 1 for b in budget_list):
        raise ValueError("budgets must contain positive integers")
    if not amount_list or any(isinstance(a, bool) or not isinstance(a, int) or a < 1 for a in amount_list):
        raise ValueError("payment_amounts must contain positive integers")
    if isinstance(n_payments, bool) or not isinstance(n_payments, int) or n_payments < 1:
        raise ValueError("n_payments must be a positive integer")
    if isinstance(n_pairs, bool) or not isinstance(n_pairs, int) or n_pairs < 1:
        raise ValueError("n_pairs must be a positive integer")
    if isinstance(k_paths, bool) or not isinstance(k_paths, int) or k_paths < 1:
        raise ValueError("k_paths must be a positive integer")
    if isinstance(max_path_length, bool) or not isinstance(max_path_length, int) or max_path_length < 1:
        raise ValueError("max_path_length must be a positive integer")
    if route_mode not in ROUTE_MODES:
        raise ValueError(f"route_mode must be one of {ROUTE_MODES}")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output / "raw_results_checkpoint.csv"
    config_path = output / "experiment_config.json"
    rows: list[dict] = []
    budget_scope = "per sender" if route_mode == "sender_to_all_receivers" else "per fixed sender-receiver pair"
    config = {
        "seeds": list(seed_list),
        "budgets_per_owner_satoshi": list(budget_list),
        "legacy_budgets_per_pair_satoshi": list(budget_list),
        "honest_payment_amounts_satoshi": list(amount_list),
        "n_payments": n_payments,
        "n_pairs": n_pairs,
        "k_paths": k_paths,
        "max_path_length_channels": max_path_length,
        "attachment": attachment,
        "route_mode": route_mode,
        "budget_scope": budget_scope,
        "balance_model": balance_model,
        "network_label": network_label,
        "strategies": ["no_attack", *ATTACK_STRATEGIES],
        "balance_note": "modeled, not observed",
    }
    run_started = time.monotonic()
    total_scenarios = len(seed_list) * len(budget_list) * len(amount_list)
    if resume:
        if not checkpoint_path.is_file():
            raise FileNotFoundError(
                f"Cannot resume: {checkpoint_path} does not exist. Start a new run without --resume."
            )
        if not config_path.is_file():
            raise FileNotFoundError(
                f"Cannot resume safely: {config_path} is missing. Keep the original experiment configuration."
            )
        saved_config = json.loads(config_path.read_text(encoding="utf-8"))
        if saved_config != config:
            raise ValueError(
                "Cannot resume because the current settings differ from experiment_config.json. "
                "Use the original settings or choose a new output directory."
            )
        checkpoint = pd.read_csv(checkpoint_path)
        required = {"seed", "budget_per_owner", "payment_amount", "strategy"}
        if not required.issubset(checkpoint.columns):
            raise ValueError(f"Checkpoint is missing required columns: {sorted(required - set(checkpoint.columns))}")
        expected_strategies = {"no_attack", *ATTACK_STRATEGIES}
        completed: set[tuple[int, int, int]] = set()
        for keys, group in checkpoint.groupby(["seed", "budget_per_owner", "payment_amount"], dropna=False):
            seed_key, budget_key, amount_key = (int(v) for v in keys)
            if set(group["strategy"].astype(str)) != expected_strategies or len(group) != len(expected_strategies):
                raise ValueError(
                    f"Checkpoint has an incomplete or duplicated scenario for seed={seed_key}, "
                    f"budget={budget_key}, amount={amount_key}. Do not edit checkpoint CSV manually."
                )
            completed.add((seed_key, budget_key, amount_key))
        rows = checkpoint.to_dict("records")
        print(
            f"Resuming from {len(completed)}/{total_scenarios} completed seed/budget/amount scenarios "
            f"({len(rows)} rows already saved; {total_scenarios - len(completed)} scenarios remain).",
            flush=True,
        )
    else:
        if checkpoint_path.exists():
            raise FileExistsError(
                f"{checkpoint_path} already exists. Use --resume to continue that run, "
                "or choose a new --output directory."
            )
        completed = set()
        config_tmp = config_path.with_suffix(".json.tmp")
        config_tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
        config_tmp.replace(config_path)

    for seed in seed_list:
        seed_pending = [
            (budget, amount)
            for budget in budget_list
            for amount in amount_list
            if (seed, budget, amount) not in completed
        ]
        if not seed_pending:
            print(f"Skipping seed={seed}: every scenario is already checkpointed.", flush=True)
            continue
        print(f"Starting seed={seed}; {len(seed_pending)} scenarios remain for this seed.", flush=True)
        built = network_factory(seed)
        if isinstance(built, tuple):
            honest_network, topology_stats = built
            if not isinstance(honest_network, Network) or not isinstance(topology_stats, dict):
                raise TypeError("network_factory tuple must be (Network, metadata dict)")
        else:
            honest_network, topology_stats = built, {}
            if not isinstance(honest_network, Network):
                raise TypeError("network_factory must return a Network or (Network, metadata dict)")
        topology_columns = {
            "topology_raw_nodes": topology_stats.get("raw_nodes", math.nan),
            "topology_raw_channels": topology_stats.get("raw_channels", math.nan),
            "topology_processed_nodes": topology_stats.get("processed_nodes", math.nan),
            "topology_processed_channels": topology_stats.get("processed_channels", math.nan),
            "topology_skipped_disabled": topology_stats.get("skipped_disabled", math.nan),
            "topology_skipped_missing_policy": topology_stats.get("skipped_missing_policy", math.nan),
        }
        workload = make_workload(honest_network, n=n_payments, seed=seed)
        for budget in budget_list:
            pending_amounts = [
                amount for amount in amount_list if (seed, budget, amount) not in completed
            ]
            if not pending_amounts:
                print(f"Skipping seed={seed}, budget={budget}: already checkpointed.", flush=True)
                continue
            # Include Sybil links in BOTH attacked and no-attack cases so only
            # the attack locks, rather than an added topology, differ in comparison.
            comparison_net = honest_network.copy()
            pairs = add_sybils(comparison_net, budget=budget, n_pairs=n_pairs, attachment=attachment, seed=seed)
            routes = find_routes(
                comparison_net, pairs, k=k_paths, max_length=max_path_length, mode=route_mode
            )
            if not routes:
                raise ValueError(
                    f"No candidate routes for seed={seed}, budget={budget}; "
                    "check network connectivity, balance model, and path limits"
                )

            # Attack allocations do not depend on the honest payment amount.
            # Compute each strategy exactly once for this seed and budget.
            attack_results = {
                strategy: run_attack(strategy, comparison_net, routes, budget=budget, seed=seed)
                for strategy in ATTACK_STRATEGIES
            }

            for amount in amount_list:
                if (seed, budget, amount) in completed:
                    print(
                        f"Skipping seed={seed}, budget={budget}, amount={amount}: already checkpointed.",
                        flush=True,
                    )
                    continue
                baseline = _workload_diagnostics(comparison_net, workload, amount)
                common_row = {
                    "seed": seed,
                    "balance_model": balance_model,
                    "route_mode": route_mode,
                    "budget_scope": budget_scope,
                    "budget_per_owner": budget,
                    # Backwards-compatible alias; semantics depend on route_mode.
                    "budget_per_pair": budget,
                    "payment_amount": amount,
                    "n_payments": n_payments,
                    "n_pairs": n_pairs,
                    "k_paths": k_paths,
                    "max_path_length": max_path_length,
                    "attachment": attachment,
                    "network_label": network_label,
                    **topology_columns,
                    "path_length_min": min(route.length for route in routes),
                    "path_length_mean": statistics.fmean(route.length for route in routes),
                    "path_length_max": max(route.length for route in routes),
                }
                base_row = {
                    **common_row,
                    "strategy": "no_attack",
                    "locked_payment": 0,
                    "routes_total": len(routes),
                    "routes_attacked": 0,
                    "mean_pcr": 0.0,
                    "mean_spcr_L20": 0.0,
                    "mean_spcr_L8": 0.0,
                    "honest_coins_stuck": 0,
                    "honest_coin_hops_stuck": 0,
                    "gamma_ratio": math.nan,
                    "gamma_printed_L20": math.nan,
                    "gamma_printed_L8": math.nan,
                    "honest_success_rate": baseline["honest_success_rate"],
                    "honest_success_volume": baseline["honest_success_volume"],
                    "honest_mean_attempts": baseline["honest_mean_attempts"],
                    "honest_failures_at_locked_channels": baseline["honest_failures_at_locked_channels"],
                    "honest_fraction_failures_at_locked_channels": baseline["honest_fraction_failures_at_locked_channels"],
                    "attacker_locked_directions_exhausted": baseline["attacker_locked_directions_exhausted"],
                    "honest_successes": baseline["honest_successes"],
                    "honest_failures": baseline["honest_failures"],
                    "delta_success_rate": 0.0,
                    "delta_success_volume": 0.0,
                    "delta_mean_attempts": 0.0,
                }
                rows.append(base_row)

                for strategy, result in attack_results.items():
                    attack_scores = result.summary()
                    honest_scores = _workload_diagnostics(result.network, workload, amount)
                    rows.append({
                        **common_row,
                        "strategy": strategy,
                        "locked_payment": result.locked_payment,
                        "routes_total": attack_scores["routes_total"],
                        "routes_attacked": attack_scores["routes_attacked"],
                        "mean_pcr": attack_scores["mean_pcr"],
                        "mean_spcr_L20": attack_scores["mean_spcr_L20"],
                        "mean_spcr_L8": attack_scores["mean_spcr_L8"],
                        "honest_coins_stuck": attack_scores["honest_coins_stuck"],
                        # This is an aggregate satoshi-hop score, not unique coins.
                        "honest_coin_hops_stuck": attack_scores["honest_coins_stuck"],
                        "gamma_ratio": attack_scores["gamma_ratio"],
                        "gamma_printed_L20": attack_scores["gamma_printed_L20"],
                        "gamma_printed_L8": attack_scores["gamma_printed_L8"],
                        "honest_success_rate": honest_scores["honest_success_rate"],
                        "honest_success_volume": honest_scores["honest_success_volume"],
                        "honest_mean_attempts": honest_scores["honest_mean_attempts"],
                        "honest_failures_at_locked_channels": honest_scores["honest_failures_at_locked_channels"],
                        "honest_fraction_failures_at_locked_channels": honest_scores["honest_fraction_failures_at_locked_channels"],
                        "attacker_locked_directions_exhausted": honest_scores["attacker_locked_directions_exhausted"],
                        "honest_successes": honest_scores["honest_successes"],
                        "honest_failures": honest_scores["honest_failures"],
                        "delta_success_rate": honest_scores["honest_success_rate"] - baseline["honest_success_rate"],
                        "delta_success_volume": honest_scores["honest_success_volume"] - baseline["honest_success_volume"],
                        "delta_mean_attempts": honest_scores["honest_mean_attempts"] - baseline["honest_mean_attempts"],
                    })

                # Atomically persist after each complete payment-size scenario.
                # If the process or EC2 session dies, at most the currently running
                # scenario must be repeated; prior scenarios can be resumed.
                checkpoint_tmp = checkpoint_path.with_suffix(".csv.tmp")
                pd.DataFrame(rows).to_csv(checkpoint_tmp, index=False)
                checkpoint_tmp.replace(checkpoint_path)
                completed.add((seed, budget, amount))
                elapsed_seconds = time.monotonic() - run_started
                print(
                    f"Checkpoint saved: {len(completed)}/{total_scenarios} scenarios complete; "
                    f"seed={seed}, budget={budget}, amount={amount}; {len(rows)} rows persisted; "
                    f"elapsed={elapsed_seconds / 60:.1f} min.",
                    flush=True,
                )

    raw = pd.DataFrame(rows)
    raw.to_csv(output / "raw_results.csv", index=False)
    summary, paired = _summaries(raw)
    summary.to_csv(output / "summary.csv", index=False)
    paired.to_csv(output / "paired_differences.csv", index=False)
    _write_plots(raw, output)
    _write_report(raw, summary, output, network_label)
    return raw


def main(argv: list[str] | None = None) -> int:
    """Command-line runner; uses a synthetic network unless --snapshot is provided."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", help="Path to lngraph_2021_11_27__00_00.json.zst or unpacked JSON")
    parser.add_argument("--balance-model", choices=BALANCE_MODELS, default="uniform")
    parser.add_argument("--nodes", type=int, default=300, help="Synthetic node count (ignored with --snapshot)")
    parser.add_argument("--output", default="results", help="Output directory")
    parser.add_argument("--seeds", type=int, default=20, help="Number of seeds, starting at zero")
    parser.add_argument("--payments", type=int, default=DEFAULT_PAYMENTS, help="Honest payments per run")
    parser.add_argument("--budgets", type=int, nargs="+", default=list(DEFAULT_BUDGETS))
    parser.add_argument("--amounts", type=int, nargs="+", default=list(DEFAULT_PAYMENT_AMOUNTS))
    parser.add_argument("--k-paths", type=int, default=50)
    parser.add_argument("--max-path-length", type=int, default=8)
    parser.add_argument("--route-mode", choices=ROUTE_MODES, default="sender_to_all_receivers",
                        help="candidate routes: N fixed pairs (legacy), or each sender to all N receivers")
    parser.add_argument("--quick", action="store_true", help="Small smoke run: 2 seeds, 100 payments, one budget and amount")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from raw_results_checkpoint.csv using the exact saved settings")
    args = parser.parse_args(argv)

    if args.seeds < 1 or args.nodes < 20:
        parser.error("--seeds must be >= 1 and --nodes must be >= 20")
    if args.quick:
        seeds = (0, 1)
        payments = 100
        budgets = (75_000_000,) if args.snapshot else (2_000_000,)
        amounts = (10_000,)
    else:
        seeds = tuple(range(args.seeds))
        payments = args.payments
        budgets = tuple(args.budgets)
        amounts = tuple(args.amounts)

    if args.snapshot:
        snapshot_path = Path(args.snapshot)
        def factory(seed: int) -> tuple[Network, dict]:
            return load_topology(snapshot_path, balance_model=args.balance_model, seed=seed)
        network_label = str(snapshot_path)
    else:
        def factory(seed: int) -> Network:
            return synthetic_network(n_nodes=args.nodes, seed=seed, balance_model=args.balance_model)
        network_label = f"synthetic Barabasi-Albert graph ({args.nodes} nodes)"

    try:
        raw = run_experiments(
            factory, output_dir=args.output, seeds=seeds, budgets=budgets,
            payment_amounts=amounts, n_payments=payments, k_paths=args.k_paths,
            max_path_length=args.max_path_length, route_mode=args.route_mode,
            balance_model=args.balance_model,
            network_label=network_label,
            resume=args.resume,
        )
    except KeyboardInterrupt:
        checkpoint = Path(args.output) / "raw_results_checkpoint.csv"
        print(
            "\nRun interrupted. Completed scenarios remain saved in "
            f"{checkpoint.resolve() if checkpoint.exists() else checkpoint}.\n"
            "To continue, rerun the exact same command and add --resume.\n"
            "Do not delete the checkpoint or change the experiment settings.",
            flush=True,
        )
        return 130
    print(f"Completed {len(raw)} rows. Results saved to: {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a module by users
    raise SystemExit(main())
