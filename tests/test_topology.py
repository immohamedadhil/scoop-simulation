"""Tests for Module 7's topology snapshot loader."""
import json

import pytest

from scoop.topology import load_topology


def _policy(disabled=False):
    return {"disabled": disabled, "fee_base_msat": "1000"}


def _channel(a, b, capacity, *, left=True, right=True, channel_id="x"):
    record = {
        "channel_id": channel_id,
        "node1_pub": a,
        "node2_pub": b,
        "capacity": str(capacity),
    }
    if left:
        record["node1_policy"] = _policy()
    if right:
        record["node2_policy"] = _policy()
    return record


def _write_snapshot(path):
    payload = {
        "nodes": [{"pub_key": n} for n in "abcxyz"],
        "channels": [
            _channel("a", "b", 100, channel_id="ab-1"),
            _channel("a", "b", 50, channel_id="ab-2"),
            _channel("b", "c", 200, channel_id="bc"),
            _channel("x", "y", 300, channel_id="xy"),
            _channel("x", "z", 400, right=False, channel_id="xz-no-policy"),
            {
                **_channel("y", "z", 500, channel_id="yz-disabled"),
                "node2_policy": _policy(disabled=True),
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_topology_merges_parallel_channels_and_keeps_largest_component(tmp_path):
    snapshot = tmp_path / "small.json"
    _write_snapshot(snapshot)

    network, stats = load_topology(snapshot, balance_model="half", seed=7)

    assert set(network.graph.nodes) == {"a", "b", "c"}
    assert network.graph["a"]["b"]["capacity"] == 150
    assert network.graph["b"]["a"]["capacity"] == 150
    assert network.graph["a"]["b"]["parallel_count"] == 2
    assert network.check_money_conserved()
    assert stats["raw_channels"] == 6
    assert stats["processed_channels"] == 2
    assert stats["channels_after_policy_filter"] == 4
    assert stats["skipped_missing_policy"] == 1
    assert stats["skipped_disabled"] == 1


def test_load_topology_repeats_balances_with_same_seed(tmp_path):
    snapshot = tmp_path / "small.json"
    _write_snapshot(snapshot)

    first, _ = load_topology(snapshot, balance_model="uniform", seed=123)
    second, _ = load_topology(snapshot, balance_model="uniform", seed=123)
    third, _ = load_topology(snapshot, balance_model="uniform", seed=124)

    assert list(first.graph.edges(data="balance")) == list(second.graph.edges(data="balance"))
    assert first.check_money_conserved()
    assert third.check_money_conserved()


def test_load_topology_rejects_unknown_balance_model(tmp_path):
    snapshot = tmp_path / "small.json"
    _write_snapshot(snapshot)
    with pytest.raises(ValueError, match="unknown balance model"):
        load_topology(snapshot, balance_model="not-a-model")


def test_load_topology_rejects_file_without_usable_channels(tmp_path):
    snapshot = tmp_path / "empty.json"
    snapshot.write_text(json.dumps({"nodes": [], "channels": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="Could not find a channel list"):
        load_topology(snapshot)


def test_load_topology_missing_file_has_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Topology snapshot not found"):
        load_topology(tmp_path / "missing.json")
