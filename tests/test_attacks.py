import pytest

from scoop.attacks import (
    ATTACK_STRATEGIES,
    greedy_attack,
    joint_spcr_max_attack,
    random_attack,
    run_attack,
    spcr_max_attack,
)
from scoop.network import Network
from scoop.paths import Route


def disjoint_network_and_routes():
    """Two channel-disjoint routes for testing the fractional-knapsack LP."""
    net = Network()
    net.add_channel("s", "a", capacity=10, balance_x=10)
    net.add_channel("a", "t", capacity=8, balance_x=8)
    net.add_channel("s", "b", capacity=6, balance_x=6)
    net.add_channel("b", "t", capacity=9, balance_x=9)
    routes = [Route(0, ("s", "a", "t")), Route(0, ("s", "b", "t"))]
    return net, routes


def overlapping_network_and_routes():
    net = Network()
    net.add_channel("s", "a", capacity=10, balance_x=10)
    net.add_channel("a", "t", capacity=8, balance_x=8)
    net.add_channel("a", "b", capacity=8, balance_x=8)
    net.add_channel("b", "t", capacity=9, balance_x=9)
    routes = [Route(0, ("s", "a", "t")), Route(0, ("s", "a", "b", "t"))]
    return net, routes


def directed_balances(net):
    return {(u, v): data["balance"] for u, v, data in net.graph.edges(data=True)}


def assert_network_invariants(net):
    assert all(data["balance"] >= 0 and data["locked"] >= 0 for _, _, data in net.graph.edges(data=True))
    assert net.check_money_conserved()


@pytest.mark.parametrize(
    "strategy",
    [random_attack, greedy_attack, spcr_max_attack, joint_spcr_max_attack],
)
def test_each_strategy_respects_budget_and_conserves_money(strategy):
    net, routes = disjoint_network_and_routes()
    before = directed_balances(net)

    result = strategy(net, routes, budget=12, seed=17)

    assert directed_balances(net) == before  # input network is not mutated
    assert len(result.amounts) == len(routes)
    assert all(0 <= amount <= net.bottleneck(route.nodes) for route, amount in zip(routes, result.amounts))
    assert all(spent <= 12 for spent in result.spent_by_pair.values())
    assert result.locked_payment == sum(result.amounts)
    assert result.summary()["locked_payment"] == result.locked_payment
    assert_network_invariants(result.network)


def test_random_attack_repeats_for_the_same_seed():
    net, routes = disjoint_network_and_routes()
    first = random_attack(net, routes, budget=12, seed=23)
    second = random_attack(net, routes, budget=12, seed=23)
    assert first.amounts == second.amounts
    assert directed_balances(first.network) == directed_balances(second.network)


def test_greedy_takes_the_largest_current_bottleneck_first():
    net, routes = disjoint_network_and_routes()
    result = greedy_attack(net, routes, budget=6)
    assert result.amounts == (6, 0)


def test_spcr_max_matches_fractional_knapsack_when_routes_do_not_share_channels():
    net, routes = disjoint_network_and_routes()
    result = spcr_max_attack(net, routes, budget=12)
    # Route 2 has better SPCR per satoshi (2/6 > 2/8); fund it fully, then route 1.
    assert result.amounts == (6, 6)
    joint = joint_spcr_max_attack(net, routes, budget=12)
    assert joint.amounts == result.amounts


def test_joint_optimizer_respects_shared_directed_channel_limits():
    net, routes = overlapping_network_and_routes()
    result = joint_spcr_max_attack(net, routes, budget=12)

    # Both routes use s->a, whose starting balance is 10, so allocations total <= 10.
    shared_use = sum(amount for route, amount in zip(routes, result.amounts) if ("s", "a") in set(zip(route.nodes, route.nodes[1:])))
    assert shared_use <= net.balance("s", "a")
    assert result.amounts == (2, 8)
    assert_network_invariants(result.network)


def test_ordinary_optimizer_clips_overlapping_lp_allocations_before_locking():
    net, routes = overlapping_network_and_routes()
    result = spcr_max_attack(net, routes, budget=12)
    # The uncoupled LP requests 4 and 8, but the shared 10-sat channel caps realized use.
    assert result.amounts == (4, 6)
    assert sum(result.amounts) <= 12
    assert_network_invariants(result.network)


def test_joint_allocations_never_overspend_any_starting_directed_balance():
    net, routes = overlapping_network_and_routes()
    starting = directed_balances(net)
    result = joint_spcr_max_attack(net, routes, budget=12)

    use = {}
    for route, amount in zip(routes, result.amounts):
        for edge in zip(route.nodes, route.nodes[1:]):
            use[edge] = use.get(edge, 0) + amount
    assert all(amount <= starting[edge] for edge, amount in use.items())


def test_run_attack_exposes_common_strategy_names():
    net, routes = disjoint_network_and_routes()
    assert set(ATTACK_STRATEGIES) == {"random", "greedy_general", "spcr_max", "joint_spcr_max"}
    result = run_attack("joint_spcr_max", net, routes, budget=12)
    assert result.strategy == "joint_spcr_max"


def test_unknown_strategy_is_rejected():
    net, routes = disjoint_network_and_routes()
    with pytest.raises(ValueError, match="unknown attack strategy"):
        run_attack("magic", net, routes, budget=12)


@pytest.mark.parametrize("budget, error", [(-1, ValueError), (1.5, TypeError), (True, TypeError)])
def test_invalid_budgets_are_rejected(budget, error):
    net, routes = disjoint_network_and_routes()
    with pytest.raises(error):
        random_attack(net, routes, budget=budget)


def test_zero_bottleneck_candidate_is_rejected():
    net, routes = disjoint_network_and_routes()
    net.lock(routes[0].nodes, net.bottleneck(routes[0].nodes))
    with pytest.raises(ValueError, match="positive original bottleneck"):
        random_attack(net, routes, budget=12)


def test_empty_route_list_is_valid():
    net, _ = disjoint_network_and_routes()
    result = joint_spcr_max_attack(net, [], budget=12)
    assert result.amounts == ()
    assert result.locked_payment == 0
    assert result.summary()["routes_total"] == 0


def test_sender_to_multiple_receivers_shares_budget_across_all_owned_routes():
    from scoop.paths import add_sybils, find_routes
    from scoop.generator import synthetic_network

    net = synthetic_network(n_nodes=70, seed=101, balance_model="half")
    budget = 10_000
    pairs = add_sybils(net, budget=budget, n_pairs=3, attachment="hubs", seed=101)
    routes = find_routes(net, pairs, k=4, max_length=8, mode="sender_to_all_receivers")
    assert routes
    result = joint_spcr_max_attack(net, routes, budget=budget, seed=101)
    assert all(total <= budget for total in result.spent_by_owner.values())
    assert len(result.spent_by_owner) <= len(pairs)
    assert result.budget_per_owner == budget
    assert_network_invariants(result.network)


def test_later_budget_owner_handles_routes_exhausted_by_earlier_owner():
    net = Network()
    net.add_channel("s", "a", capacity=10, balance_x=10)
    net.add_channel("a", "t", capacity=10, balance_x=10)
    # Two different budget owners deliberately use the same physical path.
    routes = [Route(0, ("s", "a", "t")), Route(1, ("s", "a", "t"))]
    result = joint_spcr_max_attack(net, routes, budget=10)
    assert result.amounts == (10, 0)
    assert result.spent_by_owner == {0: 10, 1: 0}
    assert_network_invariants(result.network)
