"""Practice (synthetic) networks for Phase 1, and the balance models.

Choices SCOOP does not state (also to be listed in the README):
- Shape: preferential attachment (Barabasi-Albert): each new node opens 2 channels,
  usually with nodes that already have many. 1,000 nodes by default.
- Channel size: lognormal with median 1M sat and mean 4M sat, at least 20,000 sat.
  The real Nov 2021 snapshot has median 1.0M and mean 4.05M; SCOOP states mean 4M.
- A fresh network for every seed; the same seed always gives the same network.
"""
from __future__ import annotations

import math

import networkx as nx
import numpy as np

from .network import Network

MEDIAN_CAPACITY = 1_000_000
MEAN_CAPACITY = 4_000_000
MIN_CAPACITY = 20_000

BALANCE_MODELS = ("uniform", "half", "skewed")
SKEWED_SHARE = 0.3  # Pickhardt et al. 2021: ~30% of probed channels had nearly all coins on one side
SKEWED_EDGE = 0.05  # "nearly all" = at least 95% on one side

# Lognormal: median = exp(mu), mean = exp(mu + sigma^2 / 2)
_MU = math.log(MEDIAN_CAPACITY)
_SIGMA = math.sqrt(2 * math.log(MEAN_CAPACITY / MEDIAN_CAPACITY))


def random_capacity(rng: np.random.Generator) -> int:
    """One channel size: most are small, a few are huge."""
    return max(MIN_CAPACITY, int(rng.lognormal(_MU, _SIGMA)))


def split_balance(capacity: int, model: str, rng: np.random.Generator) -> int:
    """How many of the channel's coins the first node holds."""
    if model == "half":
        return capacity // 2
    if model == "uniform":
        share = rng.uniform(0, 1)
    elif model == "skewed":
        if rng.uniform(0, 1) < SKEWED_SHARE:
            share = rng.uniform(0, SKEWED_EDGE)
            if rng.uniform(0, 1) < 0.5:  # either side can be the full one
                share = 1 - share
        else:
            share = rng.uniform(0, 1)
    else:
        raise ValueError(f"unknown balance model {model!r}; use one of {BALANCE_MODELS}")
    return int(round(share * capacity))


def synthetic_network(
    n_nodes: int = 1000, seed: int = 0, balance_model: str = "uniform", links_per_node: int = 2
) -> Network:
    """A practice network. The same seed always gives the same network."""
    shape = nx.barabasi_albert_graph(n_nodes, links_per_node, seed=seed)
    # Separate random streams, so every balance model gets the same channel sizes
    capacity_rng = np.random.default_rng([seed, 0])
    balance_rng = np.random.default_rng([seed, 1])
    net = Network()
    for x, y in sorted(shape.edges()):
        capacity = random_capacity(capacity_rng)
        net.add_channel(x, y, capacity, split_balance(capacity, balance_model, balance_rng))
    return net
