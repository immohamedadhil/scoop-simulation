import pytest

from scoop.generator import synthetic_network
from scoop.honest import giant_component, make_workload, pay_one, run_workload
from scoop.network import Network


def diamond():
    """A -> C two ways: A-B-C and A-D-C, so one route can fail and the other work."""
    net = Network()
    net.add_channel("A", "B", capacity=100, balance_x=100)
    net.add_channel("B", "C", capacity=100, balance_x=100)
    net.add_channel("A", "D", capacity=100, balance_x=100)
    net.add_channel("D", "C", capacity=100, balance_x=100)
    return net


def test_make_workload_is_deterministic():
    net = synthetic_network(n_nodes=200, seed=1)
    assert make_workload(net, n=50, seed=7) == make_workload(net, n=50, seed=7)


def test_workload_pairs_are_distinct_and_connected():
    net = synthetic_network(n_nodes=200, seed=1)
    nodes = set(giant_component(net))
    for sender, receiver in make_workload(net, n=100, seed=1):
        assert sender != receiver
        assert sender in nodes and receiver in nodes


def test_simple_payment_succeeds_and_moves_coins():
    net = diamond()
    ok, attempts = pay_one(net, "A", "C", 40)
    assert ok and attempts == 1
    assert net.balance("A", "B") == 60  # coins moved along A-B-C
    assert net.balance("B", "C") == 60


def test_payment_retries_around_a_depleted_channel():
    net = diamond()
    net.lock(["B", "C"], 100)  # empty B->C, so the first route cannot carry anything
    ok, attempts = pay_one(net, "A", "C", 40)
    assert ok and attempts == 2  # second try uses A-D-C
    assert net.balance("A", "D") == 60


def test_payment_fails_when_no_route_has_enough():
    net = diamond()
    net.lock(["B", "C"], 100)
    net.lock(["D", "C"], 100)  # both ways into C are empty
    ok, attempts = pay_one(net, "A", "C", 40)
    assert not ok  # fails once both routes are exhausted


def test_payment_fails_when_disconnected():
    net = Network()
    net.add_channel("A", "B", capacity=100, balance_x=100)
    net.add_channel("C", "D", capacity=100, balance_x=100)
    assert pay_one(net, "A", "D", 10) == (False, 1)


def test_run_workload_reports_sensible_numbers():
    net = synthetic_network(n_nodes=300, seed=2)
    workload = make_workload(net, n=200, seed=2)
    result = run_workload(net, workload, amount=10_000)
    assert result["payments"] == 200
    assert 0 <= result["successes"] <= 200
    assert 0.0 <= result["success_rate"] <= 1.0
    assert result["success_volume"] == result["successes"] * 10_000
    assert result["mean_attempts"] >= 1.0


def test_run_workload_does_not_change_the_input_network():
    net = synthetic_network(n_nodes=200, seed=1)
    before = sorted((x, y, d["balance"]) for x, y, d in net.graph.edges(data=True))
    run_workload(net, make_workload(net, n=100, seed=1), amount=50_000)
    after = sorted((x, y, d["balance"]) for x, y, d in net.graph.edges(data=True))
    assert before == after


def test_bigger_payments_are_harder():
    net = synthetic_network(n_nodes=400, seed=3)
    workload = make_workload(net, n=400, seed=3)
    small = run_workload(net, workload, amount=10_000)["success_rate"]
    big = run_workload(net, workload, amount=5_000_000)["success_rate"]
    assert small >= big


def test_depleting_liquidity_lowers_success():
    """Measurement is sensitive: emptying channels makes fewer honest payments work."""
    net = synthetic_network(n_nodes=400, seed=4)
    workload = make_workload(net, n=400, seed=4)
    clean = run_workload(net, workload, amount=500_000)["success_rate"]

    depleted = net.copy()
    hubs = sorted(depleted.graph.nodes, key=lambda n: depleted.graph.out_degree(n), reverse=True)[:10]
    for h in hubs:
        for nbr in list(depleted.graph.successors(h)):
            depleted.lock([h, nbr], depleted.balance(h, nbr))  # empty the hub's outgoing channels
    hurt = run_workload(depleted, workload, amount=500_000)["success_rate"]
    assert hurt < clean


@pytest.mark.parametrize("n", [0, 1])
def test_edge_case_sizes(n):
    net = synthetic_network(n_nodes=200, seed=1)
    result = run_workload(net, make_workload(net, n=n, seed=1) if n else [], amount=10_000)
    assert result["payments"] == n
