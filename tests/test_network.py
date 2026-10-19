import random

import pytest

from scoop.network import Network


def two_people():
    """Channel A-B with capacity 10, A holds 6 (the example from the design)."""
    net = Network()
    net.add_channel("A", "B", capacity=10, balance_x=6)
    return net


def three_people():
    """A - B - C: A-B capacity 10 (A holds 6), B-C capacity 8 (B holds 5)."""
    net = two_people()
    net.add_channel("B", "C", capacity=8, balance_x=5)
    return net


def all_balances(net):
    return {(x, y): d["balance"] for x, y, d in net.graph.edges(data=True)}


def test_add_channel_sets_both_sides():
    net = two_people()
    assert net.balance("A", "B") == 6
    assert net.balance("B", "A") == 4
    assert net.check_money_conserved()


@pytest.mark.parametrize("x, y, capacity, balance_x", [
    ("A", "A", 10, 5),   # same node twice
    ("A", "B", 10, 11),  # more than capacity
    ("A", "B", 10, -1),  # negative
])
def test_add_channel_rejects_bad_input(x, y, capacity, balance_x):
    with pytest.raises(ValueError):
        Network().add_channel(x, y, capacity, balance_x)


def test_add_channel_rejects_duplicate():
    net = two_people()
    with pytest.raises(ValueError):
        net.add_channel("A", "B", 10, 5)


def test_pay_moves_coins_to_other_side():
    net = two_people()
    net.pay(["A", "B"], 2)
    assert (net.balance("A", "B"), net.balance("B", "A")) == (4, 6)
    assert net.locked("A", "B") == 0
    assert net.check_money_conserved()


def test_lock_makes_coins_stuck():
    net = two_people()
    net.pay(["A", "B"], 2)
    net.lock(["A", "B"], 3)
    assert (net.balance("A", "B"), net.balance("B", "A")) == (1, 6)
    assert net.locked("A", "B") == 3
    assert net.check_money_conserved()


def test_bottleneck_is_smallest_balance():
    net = three_people()
    assert net.bottleneck(["A", "B", "C"]) == 5  # min(6, 5)
    assert net.bottleneck(["C", "B", "A"]) == 3  # min(3, 4)


def test_multi_hop_pay_and_lock():
    net = three_people()
    net.pay(["A", "B", "C"], 2)
    assert (net.balance("A", "B"), net.balance("B", "C")) == (4, 3)
    assert (net.balance("B", "A"), net.balance("C", "B")) == (6, 5)
    net.lock(["A", "B", "C"], 3)
    assert (net.balance("A", "B"), net.balance("B", "C")) == (1, 0)
    assert (net.locked("A", "B"), net.locked("B", "C")) == (3, 3)
    assert net.check_money_conserved()


@pytest.mark.parametrize("action", ["pay", "lock"])
def test_refuses_amount_above_bottleneck_and_changes_nothing(action):
    net = three_people()
    before = all_balances(net)
    with pytest.raises(ValueError):
        getattr(net, action)(["A", "B", "C"], 6)  # bottleneck is 5
    assert all_balances(net) == before


@pytest.mark.parametrize("amount, error", [(-1, ValueError), (1.5, TypeError), (True, TypeError)])
def test_rejects_bad_amounts(amount, error):
    with pytest.raises(error):
        two_people().lock(["A", "B"], amount)


@pytest.mark.parametrize("path", [["A"], ["A", "C"], ["A", "B", "A"]])
def test_rejects_bad_paths(path):
    with pytest.raises(ValueError):
        three_people().pay(path, 1)


def test_no_balance_goes_negative_and_money_is_conserved():
    rng = random.Random(0)
    net = three_people()
    paths = [["A", "B"], ["B", "A"], ["B", "C"], ["C", "B"], ["A", "B", "C"], ["C", "B", "A"]]
    for _ in range(500):
        path = rng.choice(paths)
        amount = rng.randint(0, net.bottleneck(path))
        getattr(net, rng.choice(["pay", "lock"]))(path, amount)
        assert min(all_balances(net).values()) >= 0
        assert net.check_money_conserved()


def test_copy_is_independent():
    net = two_people()
    clone = net.copy()
    clone.lock(["A", "B"], 6)
    assert net.balance("A", "B") == 6
    assert net.locked("A", "B") == 0
