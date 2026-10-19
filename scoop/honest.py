"""Honest payment traffic: run many ordinary payments and measure how many succeed.

This is the measurement that answers the research question. It does not depend on
any attacker code: it takes a network in whatever state it is in and reports how
honest users fare. Run it on a clean network for a baseline, and on a depleted
network to see the difference.

Model (following Lu et al. and Beres et al.):
- Sender and receiver are picked uniformly at random from the largest strongly
  connected component (the nodes that can all reach each other).
- The sender does NOT know channel balances (they are private). It routes along the
  fewest-hop path, attempts the payment, and on a hop that lacks balance it bans that
  hop and retries, up to a few times.
- Payments run one after another, and successful ones shift balances, as in reality.
"""
from __future__ import annotations

from collections import deque

import networkx as nx
import numpy as np

from .network import Network

DEFAULT_PAYMENTS = 5000
MAX_ATTEMPTS = 10


def giant_component(net: Network) -> list:
    """Nodes of the largest strongly connected component, in a stable order."""
    component = max(nx.strongly_connected_components(net.graph), key=len)
    return sorted(component, key=str)


def make_workload(net: Network, n: int = DEFAULT_PAYMENTS, seed: int = 0) -> list[tuple]:
    """n random (sender, receiver) pairs. The same seed always gives the same list."""
    nodes = giant_component(net)
    if len(nodes) < 2:
        raise ValueError("need at least two connected nodes to make payments")
    rng = np.random.default_rng([seed, 3])
    pairs = []
    for _ in range(n):
        i, j = rng.choice(len(nodes), size=2, replace=False)
        pairs.append((nodes[i], nodes[j]))
    return pairs


def _shortest_path(graph, source, target, banned: set):
    """Fewest-hop path from source to target, avoiding banned directed edges (BFS)."""
    if source == target:
        return [source]
    prev = {source: None}
    queue = deque([source])
    while queue:
        u = queue.popleft()
        for v in graph.successors(u):
            if v in prev or (u, v) in banned:
                continue
            prev[v] = u
            if v == target:
                path = [target]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])
                return path[::-1]
            queue.append(v)
    return None


def pay_one(net: Network, sender, receiver, amount: int, max_attempts: int = MAX_ATTEMPTS):
    """Try to pay `amount` from sender to receiver. Returns (succeeded, attempts_used)."""
    banned: set = set()
    for attempt in range(1, max_attempts + 1):
        path = _shortest_path(net.graph, sender, receiver, banned)
        if path is None:
            return False, attempt
        hops = list(zip(path, path[1:]))
        short_hop = next(((x, y) for x, y in hops if net.balance(x, y) < amount), None)
        if short_hop is None:
            net.pay(path, amount)
            return True, attempt
        banned.add(short_hop)  # avoid the depleted channel and try again
    return False, max_attempts


def run_workload(net: Network, workload: list[tuple], amount: int, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """Run every payment in order on a copy of the network; report how many succeed."""
    net = net.copy()  # leave the caller's network untouched, so runs are comparable
    successes = attempts_total = volume = 0
    for sender, receiver in workload:
        ok, attempts = pay_one(net, sender, receiver, amount, max_attempts)
        attempts_total += attempts
        if ok:
            successes += 1
            volume += amount
    n = len(workload)
    return {
        "amount": amount,
        "payments": n,
        "successes": successes,
        "success_rate": successes / n if n else 0.0,
        "success_volume": volume,
        "mean_attempts": attempts_total / n if n else 0.0,
    }
