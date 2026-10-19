import math

import pytest

from scoop.metrics import bottlenecks, ccr, pcr, spcr, summarize
from scoop.network import Network
from scoop.paths import Route


def route(length):
    """A route with the given number of channels (node names do not matter here)."""
    return Route(0, tuple(range(length + 1)))


def test_ccr_three_out_of_four():
    assert ccr(3, 4) == 0.75
    assert ccr(4, 4) == 1.0


def test_pcr_uses_the_weakest_channel():
    # balances 10, 3, 7: the bottleneck is 3
    assert pcr(3, 3) == 1.0
    assert pcr(2, 3) == pytest.approx(2 / 3)


def test_check_question_example():
    # 5 channels, smallest balance 4, Mallory sends 2
    assert pcr(2, 4) == 0.5
    assert spcr(2, 4, length=5, l_max=20) == pytest.approx(0.125)


def test_scores_never_go_above_one():
    assert pcr(5, 4) == 1.0
    assert spcr(8, 8, length=8, l_max=8) == 1.0
    assert spcr(4, 4, length=8, l_max=20) == pytest.approx(0.4)  # why L_max = 20 caps SPCR at 0.4


def test_printed_gamma_ignores_the_amount():
    # amount / SPCR = L_max * bottleneck / length, whatever the amount
    one_coin = summarize([route(5)], [1], [4])["gamma_printed_L20"]
    all_coins = summarize([route(5)], [4], [4])["gamma_printed_L20"]
    assert one_coin == pytest.approx(all_coins) == pytest.approx(20 * 4 / 5)


def test_hand_made_attack():
    row = summarize([route(3), route(5)], amounts=[4, 0], original_bottlenecks=[4, 10])
    assert row["locked_payment"] == 4
    assert (row["routes_total"], row["routes_attacked"]) == (2, 1)
    assert row["mean_pcr"] == pytest.approx(0.5)  # (1 + 0) / 2
    assert row["mean_spcr_L20"] == pytest.approx(3 / 20 / 2)
    assert row["mean_spcr_L8"] == pytest.approx(3 / 8 / 2)
    assert row["honest_coins_stuck"] == 4  # 4 coins x 1 honest channel
    assert row["gamma_ratio"] == pytest.approx(8)  # 4 / 0.5
    assert row["gamma_printed_L20"] == pytest.approx(4 / (3 / 20))


def test_honest_coins_stuck_counts_every_honest_channel():
    assert summarize([route(6)], [2], [5])["honest_coins_stuck"] == 2 * 4


def test_no_attack_does_not_crash():
    row = summarize([route(3), route(4)], [0, 0], [4, 4])
    assert (row["locked_payment"], row["routes_attacked"], row["mean_pcr"]) == (0, 0, 0.0)
    assert math.isnan(row["gamma_ratio"]) and math.isnan(row["gamma_printed_L20"])


def test_no_routes_does_not_crash():
    row = summarize([], [], [])
    assert row["routes_total"] == 0 and math.isnan(row["gamma_ratio"])


@pytest.mark.parametrize("amounts, bottlenecks_", [([5], [4]), ([-1], [4]), ([1, 1], [4])])
def test_rejects_bad_input(amounts, bottlenecks_):
    with pytest.raises(ValueError):
        summarize([route(3)], amounts, bottlenecks_)


def test_bottlenecks_reads_the_network():
    net = Network()
    net.add_channel("sender", "a", capacity=100, balance_x=100)
    net.add_channel("a", "b", capacity=10, balance_x=6)
    net.add_channel("b", "receiver", capacity=100, balance_x=100)
    assert bottlenecks(net, [Route(0, ("sender", "a", "b", "receiver"))]) == [6]
