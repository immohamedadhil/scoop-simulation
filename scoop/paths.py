"""Sybil-pair creation and candidate routes for SCOOP-inspired experiments.

Two route modes are supported:
- ``fixed_pairs``: one sender is connected only to its corresponding receiver.
  This is the historical project model.
- ``sender_to_all_receivers``: each of the N senders has candidate routes to all
  N receivers. All of a sender's route allocations share one budget. This is the
  paper-oriented interpretation used by the experiment runner by default.

The paper does not fully specify its exact path enumeration or attacker-pair
construction. The second mode is therefore an explicit modeling interpretation,
not a claim of exact reproduction. Candidate routes are sampled from exact hop-length buckets between the shortest
path length and the hop cap. This avoids letting dozens of short alternatives crowd
out every longer route.
"""
from __future__ import annotations

from dataclasses import dataclass
import networkx as nx
import numpy as np

from .network import Network

N_PAIRS = 6
PATHS_PER_PAIR = 50
MAX_PATH_LENGTH = 8  # channels, counting the two Sybil-to-honest attachment channels
ATTACHMENTS = ("hubs", "random")
ROUTE_MODES = ("fixed_pairs", "sender_to_all_receivers")
MIN_DEGREE_RANDOM = 5


@dataclass(frozen=True)
class Pair:
    """One Sybil sender and its corresponding Sybil receiver."""

    sender: str
    receiver: str


@dataclass(frozen=True)
class Route:
    """A candidate path and the attacker/budget owner that funds it.

    ``pair`` is retained as the field name for compatibility with the original
    project. In ``sender_to_all_receivers`` mode it identifies the sending
    attacker, not an individual sender-receiver route pair.
    """

    pair: int
    nodes: tuple

    @property
    def length(self) -> int:
        """Number of channels on the route."""
        return len(self.nodes) - 1

    @property
    def budget_owner(self) -> int:
        """Identifier shared by routes that draw from the same budget."""
        return self.pair


def add_sybils(
    net: Network, budget: int, n_pairs: int = N_PAIRS, attachment: str = "hubs", seed: int = 0
) -> list[Pair]:
    """Add N sender/receiver Sybil pairs on distinct honest-node attachments.

    Each sender has ``budget`` satoshi available toward the honest network; each
    receiver has ``budget`` satoshi of inbound liquidity on its attachment.
    The budget is an experiment parameter, not a claim about real-world costs.
    """
    if isinstance(n_pairs, bool) or not isinstance(n_pairs, int) or n_pairs < 1:
        raise ValueError("n_pairs must be a positive integer")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError("budget must be a positive integer")

    honest = list(net.graph.nodes)
    degree = net.graph.out_degree
    if attachment == "hubs":
        # Most channels first; the name breaks ties so the order never changes.
        targets = sorted(honest, key=lambda n: (-degree(n), str(n)))[: 2 * n_pairs]
    elif attachment == "random":
        candidates = sorted((n for n in honest if degree(n) >= MIN_DEGREE_RANDOM), key=str)
        if len(candidates) < 2 * n_pairs:
            raise ValueError("not enough honest nodes with at least 5 channels")
        picks = np.random.default_rng([seed, 2]).choice(len(candidates), 2 * n_pairs, replace=False)
        targets = [candidates[i] for i in picks]
    else:
        raise ValueError(f"unknown attachment {attachment!r}; use one of {ATTACHMENTS}")
    if len(targets) < 2 * n_pairs:
        raise ValueError("not enough honest nodes")

    pairs = []
    for i in range(n_pairs):
        sender, receiver = f"M{i}-sender", f"M{i}-receiver"
        # The sender has outward balance; the receiver-side counterparty has
        # balance toward the receiver, allowing a payment to terminate there.
        net.add_channel(sender, targets[2 * i], capacity=budget, balance_x=budget)
        net.add_channel(targets[2 * i + 1], receiver, capacity=budget, balance_x=budget)
        pairs.append(Pair(sender, receiver))
    return pairs


def _sample_simple_paths_at_length(
    net: Network,
    source,
    target,
    length: int,
    count: int,
    rng: np.random.Generator,
    distance_to_target: dict,
    forbidden_internal: set,
) -> list[tuple]:
    """Sample up to ``count`` usable simple paths of exactly ``length`` hops.

    The bounded depth-first search only follows nodes that can still reach the
    destination within the remaining hop allowance. A per-length expansion
    budget prevents pathological searches on large graphs. Randomized neighbor
    order makes the selected paths varied while the supplied RNG keeps runs
    repeatable.
    """
    if count <= 0:
        return []

    graph = net.graph
    paths: list[tuple] = []
    seen: set[tuple] = set()
    # Bound search effort independently for each hop-length bucket. Most viable
    # Lightning routes are found in very few expansions; this cap mainly protects
    # against lengths that cannot be realized in a particular graph.
    expansion_budget = max(5_000, count * 800)
    expansions = 0

    while len(paths) < count and expansions < expansion_budget:
        current_path = [source]
        visited = {source}

        def search(current, remaining: int):
            nonlocal expansions
            if expansions >= expansion_budget:
                return None
            expansions += 1

            if remaining == 0:
                candidate = tuple(current_path)
                if current == target and candidate not in seen:
                    # The source/destination nodes are included in the path; all
                    # channels must have positive available balance initially.
                    if net.bottleneck(candidate) > 0:
                        return candidate
                return None

            candidates = []
            for neighbor in graph.successors(current):
                if neighbor in visited:
                    continue
                if neighbor in forbidden_internal and neighbor != target:
                    continue
                if neighbor == target:
                    # A simple path may only arrive at its destination on the
                    # final hop of the requested exact length.
                    if remaining == 1:
                        candidates.append(neighbor)
                    continue
                distance = distance_to_target.get(neighbor)
                if distance is None or distance > remaining - 1:
                    continue
                candidates.append(neighbor)

            rng.shuffle(candidates)
            for neighbor in candidates:
                current_path.append(neighbor)
                visited.add(neighbor)
                result = search(neighbor, remaining - 1)
                visited.remove(neighbor)
                current_path.pop()
                if result is not None:
                    return result
                if expansions >= expansion_budget:
                    break
            return None

        result = search(source, length)
        if result is None:
            # Either this exact length has no usable simple path, or its search
            # budget was exhausted. Retrying the same bucket would add little
            # value and could make real-topology runs unexpectedly expensive.
            break
        seen.add(result)
        paths.append(result)

    return paths


def _length_quotas(min_length: int, max_length: int, k: int) -> list[tuple[int, int]]:
    """Distribute a maximum of ``k`` routes across hop lengths fairly.

    When k is smaller than the number of available lengths, choose lengths spaced
    across the whole interval rather than filling only its shortest end.
    """
    all_lengths = list(range(min_length, max_length + 1))
    if not all_lengths:
        return []
    if k < len(all_lengths):
        positions = np.linspace(0, len(all_lengths) - 1, num=k)
        indices = sorted({int(round(position)) for position in positions})
        lengths = [all_lengths[index] for index in indices]
    else:
        lengths = all_lengths

    base, extra = divmod(k, len(lengths))
    return [(length, base + (1 if index < extra else 0))
            for index, length in enumerate(lengths)]


def find_routes(
    net: Network,
    pairs: list[Pair],
    k: int = PATHS_PER_PAIR,
    max_length: int = MAX_PATH_LENGTH,
    mode: str = "fixed_pairs",
) -> list[Route]:
    """Find up to ``k`` viable simple paths per sender/destination job.

    Instead of taking only the first k shortest paths, candidate routes are
    sampled across exact hop lengths from the shortest distance through
    ``max_length``. This preserves short routes while allowing longer candidates
    to be represented when the graph supports them. A route's budget owner is
    the sender index; in sender-to-all-receivers mode all of a sender's routes
    share that sender's budget.
    """
    if mode not in ROUTE_MODES:
        raise ValueError(f"unknown route mode {mode!r}; use one of {ROUTE_MODES}")
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")
    if isinstance(max_length, bool) or not isinstance(max_length, int) or max_length < 1:
        raise ValueError("max_length must be a positive integer")

    if mode == "fixed_pairs":
        jobs = [(i, pair.sender, pair.receiver) for i, pair in enumerate(pairs)]
    else:
        jobs = [
            (sender_index, sender_pair.sender, receiver_pair.receiver)
            for sender_index, sender_pair in enumerate(pairs)
            for receiver_pair in pairs
        ]

    all_sybil_nodes = {node for pair in pairs for node in (pair.sender, pair.receiver)}
    reverse_graph = net.graph.reverse(copy=False)
    distance_cache: dict[object, dict] = {}
    routes: list[Route] = []

    for job_index, (owner_id, source, target) in enumerate(jobs):
        if source == target:
            continue
        distances = distance_cache.get(target)
        if distances is None:
            distances = dict(nx.single_source_shortest_path_length(
                reverse_graph, target, cutoff=max_length
            ))
            distance_cache[target] = distances
        min_length = distances.get(source)
        if min_length is None or min_length > max_length:
            continue

        quotas = _length_quotas(min_length, max_length, k)
        forbidden_internal = all_sybil_nodes - {source, target}
        job_routes: list[tuple] = []
        for length, quota in quotas:
            rng = np.random.default_rng([job_index, length, k, max_length])
            sampled = _sample_simple_paths_at_length(
                net, source, target, length, quota, rng, distances,
                forbidden_internal,
            )
            job_routes.extend(sampled)

        # Keep each sender/destination job ordered by length for readable CSVs
        # and reproducible tests, without claiming paths are shortest-first only.
        job_routes.sort(key=lambda path: (len(path), tuple(map(str, path))))
        routes.extend(Route(owner_id, path) for path in job_routes)

    return routes
