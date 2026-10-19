"""Liquidity-based congestion strategies inspired by SCOOP.

Every public strategy takes an untouched starting network and returns an
independent attacked copy. One budget is shared by every route with the same
``Route.budget_owner`` (a fixed pair in the historical mode, or a sender in
``sender_to_all_receivers`` mode). Payments are whole satoshis and are applied
subject to current directed balances, conserving channel money.

For each budget owner, the SPCR-Max LP uses the path bottlenecks available
when that owner acts, after earlier owners' locks. Reported summary metrics still
compare realized payments with the pre-attack bottlenecks. The joint variant
also limits the sum allocated to routes using each directed channel.
"""
from __future__ import annotations

from dataclasses import dataclass
import numbers
from typing import Callable

import numpy as np
from scipy.optimize import linprog

from .metrics import bottlenecks, summarize
from .network import Network
from .paths import Route

ATTACK_STRATEGIES = ("random", "greedy_general", "spcr_max", "joint_spcr_max")


@dataclass(frozen=True)
class AttackResult:
    """The realized outcome of an attack, with amounts aligned to ``routes``."""

    strategy: str
    network: Network
    routes: tuple[Route, ...]
    amounts: tuple[int, ...]
    original_bottlenecks: tuple[int, ...]
    # Legacy field names are retained for compatibility. Keys identify the
    # route budget owner (sender or fixed pair, depending on route mode).
    budget_per_pair: int
    spent_by_pair: dict[int, int]

    @property
    def budget_per_owner(self) -> int:
        """Budget shared by each ``Route.budget_owner`` group."""
        return self.budget_per_pair

    @property
    def spent_by_owner(self) -> dict[int, int]:
        """Total realized payment for each route budget owner."""
        return self.spent_by_pair

    @property
    def locked_payment(self) -> int:
        """Total payment amount locked across all routes, in satoshis."""
        return sum(self.amounts)

    def summary(self) -> dict:
        """Return the SCOOP metrics for this realized attack."""
        return summarize(list(self.routes), list(self.amounts), list(self.original_bottlenecks))


def _check_integer(value, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise TypeError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return int(value)


def _prepare(
    net: Network, routes: list[Route] | tuple[Route, ...], budget: int, seed: int
) -> tuple[Network, tuple[Route, ...], tuple[int, ...], dict[int, list[int]]]:
    budget = _check_integer(budget, "budget")
    seed = _check_integer(seed, "seed")
    route_list = tuple(routes)
    # A zero original bottleneck is not a usable candidate and would make PCR undefined.
    original = tuple(bottlenecks(net, list(route_list)))
    if any(value <= 0 for value in original):
        raise ValueError("all candidate routes must have a positive original bottleneck")

    grouped: dict[int, list[int]] = {}
    for index, route in enumerate(route_list):
        grouped.setdefault(route.budget_owner, []).append(index)
    return net.copy(), route_list, original, grouped


def _finish(
    strategy: str,
    attacked: Network,
    routes: tuple[Route, ...],
    amounts: list[int],
    original: tuple[int, ...],
    budget: int,
) -> AttackResult:
    spent: dict[int, int] = {}
    for route, amount in zip(routes, amounts):
        spent[route.budget_owner] = spent.get(route.budget_owner, 0) + amount

    # Catch invariant violations close to where an attack is applied.
    if any(data["balance"] < 0 or data["locked"] < 0 for _, _, data in attacked.graph.edges(data=True)):
        raise RuntimeError("attack produced a negative balance or locked amount")
    if not attacked.check_money_conserved():
        raise RuntimeError("attack did not conserve channel money")
    if any(spent_owner > budget for spent_owner in spent.values()):
        raise RuntimeError("attack exceeded a route budget owner's budget")
    if any(amount < 0 or amount > original[i] for i, amount in enumerate(amounts)):
        raise RuntimeError("attack assigned an invalid path payment")

    return AttackResult(
        strategy=strategy,
        network=attacked,
        routes=routes,
        amounts=tuple(amounts),
        original_bottlenecks=original,
        budget_per_pair=budget,
        spent_by_pair=spent,
    )


def _current_bottleneck(net: Network, route: Route) -> int:
    return net.bottleneck(route.nodes)


def _apply_targets(
    attacked: Network,
    routes: tuple[Route, ...],
    indices: list[int],
    targets: dict[int, int],
    amounts: list[int],
    budget: int,
) -> int:
    """Apply proposed payments in stable route order, enforcing live balances."""
    remaining = budget
    spent = 0
    for index in indices:
        if remaining == 0:
            break
        route = routes[index]
        current = _current_bottleneck(attacked, route)
        amount = min(targets.get(index, 0), current, remaining)
        if amount > 0:
            attacked.lock(route.nodes, amount)
            amounts[index] = amount
            remaining -= amount
            spent += amount
    return spent


def random_attack(
    net: Network,
    routes: list[Route] | tuple[Route, ...],
    budget: int,
    seed: int = 0,
) -> AttackResult:
    """Spend a seeded random amount, split among routes with random weights.

    The sampled spend is uniform over the inclusive range [0, budget]. Each
    proposed route amount is capped by its current bottleneck when applied. Any
    unused amount caused by a cap is not redistributed to other routes.
    """
    attacked, route_list, original, grouped = _prepare(net, routes, budget, seed)
    amounts = [0] * len(route_list)
    rng = np.random.default_rng([seed, 4])

    for owner_id in sorted(grouped):
        indices = grouped[owner_id]
        if not indices or budget == 0:
            continue
        target_spend = int(rng.integers(0, budget + 1))
        weights = rng.random(len(indices))
        if float(weights.sum()) == 0.0:
            weights = np.ones(len(indices))
        shares = weights / weights.sum()
        allocations = rng.multinomial(target_spend, shares)
        targets = {index: int(amount) for index, amount in zip(indices, allocations)}
        _apply_targets(attacked, route_list, indices, targets, amounts, budget)

    return _finish("random", attacked, route_list, amounts, original, budget)


def greedy_attack(
    net: Network,
    routes: list[Route] | tuple[Route, ...],
    budget: int,
    seed: int = 0,
) -> AttackResult:
    """Greedy General baseline: consume the largest current bottlenecks first."""
    attacked, route_list, original, grouped = _prepare(net, routes, budget, seed)
    amounts = [0] * len(route_list)

    for owner_id in sorted(grouped):
        indices = grouped[owner_id]
        if budget == 0:
            continue
        # Rank with the balances available at the start of this attacker's turn.
        ranked = sorted(indices, key=lambda i: (-_current_bottleneck(attacked, route_list[i]), i))
        remaining = budget
        for index in ranked:
            if remaining == 0:
                break
            route = route_list[index]
            amount = min(_current_bottleneck(attacked, route), remaining)
            if amount > 0:
                attacked.lock(route.nodes, amount)
                amounts[index] = amount
                remaining -= amount

    return _finish("greedy_general", attacked, route_list, amounts, original, budget)


def _solve_lp(
    attacked: Network,
    routes: tuple[Route, ...],
    indices: list[int],
    budget: int,
    *,
    joint: bool,
) -> dict[int, int]:
    """Solve SPCR-Max for one budget owner and return whole-satoshi amounts."""
    if not indices or budget == 0:
        return {index: 0 for index in indices}

    current_caps = {index: _current_bottleneck(attacked, routes[index]) for index in indices}
    # Earlier senders may have consumed channels on these paths. Optimize using
    # the bottlenecks available when this sender acts, and hold those coefficients
    # fixed within this LP so the objective remains linear.
    active_indices = [index for index in indices if current_caps[index] > 0]
    if not active_indices:
        return {index: 0 for index in indices}
    route_caps = [current_caps[index] for index in active_indices]
    values = [routes[index].length / current_caps[index] for index in active_indices]
    c = -np.asarray(values, dtype=float)

    constraints: list[list[float]] = [[1.0] * len(active_indices)]
    limits: list[float] = [float(budget)]
    edge_rows: dict[tuple, list[int]] = {}

    if joint:
        route_edges: list[set[tuple]] = []
        for index in active_indices:
            route = routes[index]
            edges = set(zip(route.nodes, route.nodes[1:]))
            route_edges.append(edges)
            for edge in edges:
                edge_rows.setdefault(edge, [])
        for edge in edge_rows:
            for column, edges in enumerate(route_edges):
                if edge in edges:
                    edge_rows[edge].append(column)
            row = [0.0] * len(active_indices)
            for column in edge_rows[edge]:
                row[column] = 1.0
            constraints.append(row)
            limits.append(float(attacked.balance(*edge)))

    result = linprog(
        c,
        A_ub=np.asarray(constraints, dtype=float),
        b_ub=np.asarray(limits, dtype=float),
        bounds=[(0.0, float(cap)) for cap in route_caps],
        method="highs",
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"SPCR-Max optimization failed: {result.message}")

    # Rounding down preserves every LP upper bound, budget limit, and shared-edge
    # constraint. The resulting loss is less than one satoshi per route.
    allocations = {index: 0 for index in indices}
    allocations.update({
        index: max(0, int(np.floor(float(value))))
        for index, value in zip(active_indices, result.x)
    })
    return allocations


def spcr_max_attack(
    net: Network,
    routes: list[Route] | tuple[Route, ...],
    budget: int,
    seed: int = 0,
) -> AttackResult:
    """SPCR-Max LP with per-route caps and sequential shared-channel clipping.

    Each sender's LP uses the path bottlenecks available when that sender acts.
    The LP itself does not couple paths that share a channel; proposed amounts
    are applied in input order and capped against live balances. Use
    ``joint_spcr_max_attack`` to constrain shared channels inside the LP.
    """
    attacked, route_list, original, grouped = _prepare(net, routes, budget, seed)
    amounts = [0] * len(route_list)

    for owner_id in sorted(grouped):
        indices = grouped[owner_id]
        targets = _solve_lp(attacked, route_list, indices, budget, joint=False)
        _apply_targets(attacked, route_list, indices, targets, amounts, budget)

    return _finish("spcr_max", attacked, route_list, amounts, original, budget)


def joint_spcr_max_attack(
    net: Network,
    routes: list[Route] | tuple[Route, ...],
    budget: int,
    seed: int = 0,
) -> AttackResult:
    """SPCR-Max LP with shared directed-channel balance constraints.

    For each budget owner, the sum allocated to routes using a directed edge
    may not exceed that edge's currently available balance.
    """
    attacked, route_list, original, grouped = _prepare(net, routes, budget, seed)
    amounts = [0] * len(route_list)

    for owner_id in sorted(grouped):
        indices = grouped[owner_id]
        targets = _solve_lp(attacked, route_list, indices, budget, joint=True)
        # The LP constraints make this stable order feasible; applying paths in
        # input order still keeps Network's own payment validation as a guard.
        for index in indices:
            amount = targets[index]
            if amount > 0:
                attacked.lock(route_list[index].nodes, amount)
                amounts[index] = amount

    return _finish("joint_spcr_max", attacked, route_list, amounts, original, budget)


_ATTACKER_FUNCTIONS: dict[str, Callable[..., AttackResult]] = {
    "random": random_attack,
    "greedy_general": greedy_attack,
    "spcr_max": spcr_max_attack,
    "joint_spcr_max": joint_spcr_max_attack,
}


def run_attack(
    strategy: str,
    net: Network,
    routes: list[Route] | tuple[Route, ...],
    budget: int,
    seed: int = 0,
) -> AttackResult:
    """Run one named strategy using the common interface needed by experiments."""
    try:
        function = _ATTACKER_FUNCTIONS[strategy]
    except KeyError as exc:
        raise ValueError(f"unknown attack strategy {strategy!r}; use one of {ATTACK_STRATEGIES}") from exc
    return function(net, routes, budget, seed)
