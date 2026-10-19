import pytest

from scoop.generator import synthetic_network
from scoop.paths import (
    MAX_PATH_LENGTH,
    MIN_DEGREE_RANDOM,
    N_PAIRS,
    PATHS_PER_PAIR,
    add_sybils,
    find_routes,
)

BUDGET = 75_000_000


def setup(seed=1, attachment="hubs"):
    net = synthetic_network(n_nodes=300, seed=seed)
    honest = set(net.graph.nodes)
    degrees = {n: net.graph.out_degree(n) for n in honest}
    pairs = add_sybils(net, BUDGET, attachment=attachment, seed=seed)
    return net, honest, degrees, pairs


def fake_accounts(pairs):
    return {p.sender for p in pairs} | {p.receiver for p in pairs}


def attached_to(net, pairs):
    return [next(iter(net.graph.successors(a))) for a in fake_accounts(pairs)]


def test_twelve_accounts_each_with_one_channel_to_a_different_honest_node():
    net, honest, _, pairs = setup()
    assert len(pairs) == N_PAIRS
    assert all(net.graph.out_degree(a) == 1 for a in fake_accounts(pairs))
    neighbours = attached_to(net, pairs)
    assert len(set(neighbours)) == 2 * N_PAIRS
    assert set(neighbours) <= honest


def test_hubs_attachment_uses_the_most_connected_nodes():
    net, _, degrees, pairs = setup()
    attached = sorted((degrees[n] for n in attached_to(net, pairs)), reverse=True)
    assert attached == sorted(degrees.values(), reverse=True)[: 2 * N_PAIRS]


def test_random_attachment_uses_nodes_with_enough_channels():
    net, _, degrees, pairs = setup(attachment="random")
    assert all(degrees[n] >= MIN_DEGREE_RANDOM for n in attached_to(net, pairs))


def test_unknown_attachment_is_rejected():
    with pytest.raises(ValueError):
        setup(attachment="magic")


def test_mallorys_channels_hold_the_whole_budget():
    net, _, _, pairs = setup()
    for p in pairs:
        first_hub = next(iter(net.graph.successors(p.sender)))
        last_hub = next(iter(net.graph.predecessors(p.receiver)))
        assert net.balance(p.sender, first_hub) == BUDGET
        assert net.balance(last_hub, p.receiver) == BUDGET
    assert net.check_money_conserved()


def test_routes_are_valid():
    net, _, _, pairs = setup()
    others = fake_accounts(pairs)
    for r in find_routes(net, pairs):
        pair = pairs[r.pair]
        assert (r.nodes[0], r.nodes[-1]) == (pair.sender, pair.receiver)
        assert len(set(r.nodes)) == len(r.nodes)  # nobody visited twice
        assert 3 <= r.length <= MAX_PATH_LENGTH
        assert not set(r.nodes[1:-1]) & others  # never through another fake account
        assert net.bottleneck(r.nodes) > 0


def test_routes_are_bounded_and_sample_multiple_lengths_when_available():
    net, _, _, pairs = setup()
    routes = find_routes(net, pairs, k=PATHS_PER_PAIR, max_length=8)
    for i in range(N_PAIRS):
        lengths = [r.length for r in routes if r.pair == i]
        assert 0 < len(lengths) <= PATHS_PER_PAIR
        assert lengths == sorted(lengths)
        assert min(lengths) >= 3
        assert max(lengths) <= 8
        # In the connected preferential-attachment test network, longer simple
        # alternatives exist; route generation should not discard them just
        # because many shorter routes are available.
        assert len(set(lengths)) >= 2


def test_long_routes_are_dropped():
    net, _, _, pairs = setup()
    assert all(r.length <= 4 for r in find_routes(net, pairs, max_length=4))


def test_same_seed_gives_same_routes():
    net_a, _, _, pairs_a = setup(seed=2)
    net_b, _, _, pairs_b = setup(seed=2)
    assert find_routes(net_a, pairs_a) == find_routes(net_b, pairs_b)


def test_sender_to_all_receivers_mode_shares_one_owner_id_across_destinations():
    from scoop.network import Network

    net = Network()
    # Fully connected small honest core gives each sender a route to every receiver.
    honest_nodes = ["h0", "h1", "h2", "h3"]
    for i, left in enumerate(honest_nodes):
        for right in honest_nodes[i + 1 :]:
            net.add_channel(left, right, capacity=100, balance_x=50)
    pairs = add_sybils(net, budget=100, n_pairs=2, attachment="hubs", seed=7)

    routes = find_routes(net, pairs, k=2, max_length=8, mode="sender_to_all_receivers")
    assert routes
    for owner_id, pair in enumerate(pairs):
        owned = [route for route in routes if route.budget_owner == owner_id]
        # Each of the two senders should have routes to both receivers.
        assert {route.nodes[-1] for route in owned} == {p.receiver for p in pairs}
        assert all(route.nodes[0] == pair.sender for route in owned)
        assert len(owned) >= 2


def test_find_routes_rejects_unknown_route_mode():
    net, _, _, pairs = setup(seed=3)
    with pytest.raises(ValueError, match="unknown route mode"):
        find_routes(net, pairs, mode="all_possible_paths")


def test_route_selection_includes_available_longer_paths():
    from scoop.network import Network
    from scoop.paths import Pair

    net = Network()
    # The direct a-b route is shortest. Three disjoint corridors between a and b
    # provide alternatives of different exact lengths.
    edges = [
        ("s", "a"), ("b", "t"),
        ("a", "b"),
        ("a", "c"), ("c", "d"), ("d", "b"),
        ("a", "e"), ("e", "f"), ("f", "g"), ("g", "b"),
        ("a", "h"), ("h", "i"), ("i", "j"), ("j", "k"), ("k", "b"),
    ]
    for left, right in edges:
        net.add_channel(left, right, capacity=100, balance_x=50)

    routes = find_routes(net, [Pair("s", "t")], k=10, max_length=8)
    lengths = {route.length for route in routes}
    assert {3, 5, 6, 7} <= lengths
    assert max(lengths) <= 8

