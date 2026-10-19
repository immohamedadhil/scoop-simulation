import networkx as nx
import numpy as np
import pytest

from scoop.generator import (
    BALANCE_MODELS,
    MIN_CAPACITY,
    random_capacity,
    split_balance,
    synthetic_network,
)


def channels(net):
    return sorted((x, y, d["balance"], d["capacity"]) for x, y, d in net.graph.edges(data=True))


def capacities(net):
    return sorted((x, y, d["capacity"]) for x, y, d in net.graph.edges(data=True))


def shares(model, n=20_000):
    """Fraction of coins on the first side, for many channels of 1M sat."""
    rng = np.random.default_rng(5)
    return np.array([split_balance(1_000_000, model, rng) / 1_000_000 for _ in range(n)])


def lopsided(s):
    """Fraction of channels with at least 95% of the coins on one side."""
    return ((s <= 0.05) | (s >= 0.95)).mean()


def test_same_seed_gives_same_network():
    assert channels(synthetic_network(seed=1)) == channels(synthetic_network(seed=1))


def test_different_seeds_give_different_networks():
    assert channels(synthetic_network(seed=1)) != channels(synthetic_network(seed=2))


def test_size_and_everyone_connected():
    g = synthetic_network(n_nodes=1000, seed=3).graph
    assert g.number_of_nodes() == 1000
    assert g.number_of_edges() == 2 * 1996  # 2 starting channels + 997 new nodes x 2, both directions
    assert nx.is_strongly_connected(g)


@pytest.mark.parametrize("model", BALANCE_MODELS)
def test_every_channel_is_valid(model):
    net = synthetic_network(n_nodes=300, seed=4, balance_model=model)
    for _, _, d in net.graph.edges(data=True):
        assert 0 <= d["balance"] <= d["capacity"]
        assert d["capacity"] >= MIN_CAPACITY
        assert type(d["balance"]) is int and type(d["capacity"]) is int
    assert net.check_money_conserved()


def test_balance_models_use_the_same_channels():
    nets = [synthetic_network(n_nodes=300, seed=4, balance_model=m) for m in BALANCE_MODELS]
    assert capacities(nets[0]) == capacities(nets[1]) == capacities(nets[2])


def test_half_gives_exactly_half():
    rng = np.random.default_rng(0)
    assert split_balance(100, "half", rng) == 50
    assert split_balance(101, "half", rng) == 50


def test_uniform_is_about_half_on_average():
    s = shares("uniform")
    assert abs(s.mean() - 0.5) < 0.01
    assert abs(lopsided(s) - 0.10) < 0.01  # 10% are lopsided just by chance


def test_skewed_has_more_lopsided_channels_on_both_sides():
    s = shares("skewed")
    assert abs(lopsided(s) - 0.37) < 0.015  # 30% forced + 70% x 10% by chance
    assert (s <= 0.05).mean() > 0.15 and (s >= 0.95).mean() > 0.15


def test_unknown_model_is_rejected():
    with pytest.raises(ValueError):
        split_balance(100, "magic", np.random.default_rng(0))


def test_channel_sizes_match_real_lightning():
    rng = np.random.default_rng(6)
    caps = np.array([random_capacity(rng) for _ in range(200_000)])
    assert abs(np.median(caps) / 1_000_000 - 1) < 0.02
    assert abs(caps.mean() / 4_000_000 - 1) < 0.05
    assert caps.min() >= MIN_CAPACITY
