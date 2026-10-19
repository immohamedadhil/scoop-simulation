"""Load the dated Lightning snapshot into SCOOP's directed balance model.

Important modeling choice: Network stores every physical channel in both
routing directions. To avoid routing over a direction that the snapshot says
is unavailable, this loader keeps only channels for which BOTH directional
policies exist and are enabled. Balances are generated randomly; the snapshot
does not reveal actual balances.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np

from .generator import BALANCE_MODELS, split_balance
from .network import Network


_ENDPOINT_PAIRS = (
    ("node1_pub", "node2_pub"),
    ("node1", "node2"),
    ("source", "target"),
    ("src", "dst"),
    ("from", "to"),
    ("u", "v"),
    ("node1_id", "node2_id"),
    ("pubkey1", "pubkey2"),
)
_CAPACITY_FIELDS = ("capacity_sat", "capacity_sats", "capacity", "satoshis", "capacity_msat", "capacity_msat")
_POLICY_PAIRS = (
    ("node1_policy", "node2_policy"),
    ("policy1", "policy2"),
    ("node1_routing_policy", "node2_routing_policy"),
    ("source_policy", "target_policy"),
)


def _maybe_int(value: Any) -> int | None:
    """Convert a non-negative numeric string/value to an integer, if possible."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= 0 else None


def _node_id(value: Any) -> str | None:
    """Normalize endpoint fields that may be identifiers or small objects."""
    if isinstance(value, dict):
        for key in ("pub_key", "pubkey", "id", "public_key", "name"):
            if value.get(key) is not None:
                return str(value[key])
        return None
    if value is None:
        return None
    return str(value)


def _as_records(value: Any) -> list[dict]:
    """Accept a list of records or a mapping from IDs to record dictionaries."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _read_json(path: str | Path) -> dict:
    """Read JSON or Zstandard-compressed JSON with a helpful dependency error."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Topology snapshot not found: {source}")
    raw = source.read_bytes()
    if source.suffix.lower() == ".zst" or raw[:4] == b"\x28\xb5\x2f\xfd":
        try:
            from compression import zstd  # Python 3.14 standard library

            raw = zstd.decompress(raw)
        except ImportError:
            try:
                import zstandard
            except ImportError as exc:
                raise RuntimeError(
                    "This is a .zst snapshot. Use Python 3.14+ (compression.zstd) "
                    "or install the optional reader with: py -m pip install zstandard"
                ) from exc
            raw = zstandard.ZstdDecompressor().decompress(raw)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not parse {source} as JSON after decompression") from exc
    if not isinstance(payload, dict):
        raise ValueError("The topology JSON root must be an object")
    return payload


def _channels_from(payload: dict) -> list[dict]:
    """Find the snapshot's channel list, tolerating common wrapper names."""
    for key in ("channels", "edges", "channel_data", "links"):
        if key in payload:
            records = _as_records(payload[key])
            if records:
                return records
    for wrapper in ("graph", "network", "data", "snapshot"):
        nested = payload.get(wrapper)
        if isinstance(nested, dict):
            found = _channels_from(nested)
            if found:
                return found
    # Some exports map channel IDs directly to records at the root.
    if payload and all(isinstance(value, dict) for value in payload.values()):
        records = list(payload.values())
        if any(any(left in rec and right in rec for left, right in _ENDPOINT_PAIRS) for rec in records):
            return records
    raise ValueError("Could not find a channel list (expected 'channels', 'edges', or 'links')")


def _endpoints(channel: dict) -> tuple[str, str] | None:
    for left, right in _ENDPOINT_PAIRS:
        if left in channel and right in channel:
            a, b = _node_id(channel[left]), _node_id(channel[right])
            if a is not None and b is not None and a != b:
                return a, b
    # A few graph dumps put endpoint IDs in an array.
    endpoints = channel.get("endpoints")
    if isinstance(endpoints, (list, tuple)) and len(endpoints) == 2:
        a, b = _node_id(endpoints[0]), _node_id(endpoints[1])
        if a is not None and b is not None and a != b:
            return a, b
    return None


def _capacity_sat(channel: dict) -> int | None:
    for key in _CAPACITY_FIELDS:
        if key not in channel:
            continue
        value = _maybe_int(channel[key])
        if value is None:
            continue
        if key.endswith("msat"):
            value //= 1000
        return value if value > 0 else None
    return None


def _policy_pair(channel: dict) -> tuple[Any, Any] | None:
    for left, right in _POLICY_PAIRS:
        if left in channel and right in channel:
            return channel[left], channel[right]
    policies = channel.get("policies")
    if isinstance(policies, (list, tuple)) and len(policies) >= 2:
        return policies[0], policies[1]
    if isinstance(policies, dict):
        # Preserve source insertion order if the JSON used a mapping keyed by endpoints.
        values = list(policies.values())
        if len(values) >= 2:
            return values[0], values[1]
    return None


def _disabled(policy: Any) -> bool | None:
    """Return True/False for a parseable policy, or None if policy is missing."""
    if not isinstance(policy, dict):
        return None
    value = policy.get("disabled", policy.get("is_disabled", False))
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no", ""}:
            return False
        return None
    if isinstance(value, (bool, int)):
        return bool(value)
    return None


def load_topology(
    path: str | Path,
    balance_model: str = "uniform",
    seed: int = 0,
) -> tuple[Network, dict[str, int | str]]:
    """Load and preprocess one snapshot; return ``(network, processing_stats)``.

    Processing: numeric capacities are converted to satoshis; channels without
    two available routing policies are excluded; parallel physical channels
    are merged by summing capacity; only the largest strongly connected
    component is retained. Directional balances are modeled with ``balance_model``.

    Args:
        path: JSON snapshot or the provided .json.zst snapshot.
        balance_model: ``uniform``, ``half`` or ``skewed``.
        seed: Fixed seed for reproducible modeled balances.

    Returns:
        Network and counts that should be recorded with experimental results.
    """
    if balance_model not in BALANCE_MODELS:
        raise ValueError(f"unknown balance model {balance_model!r}; use one of {BALANCE_MODELS}")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")

    payload = _read_json(path)
    channels = _channels_from(payload)
    nodes_payload = payload.get("nodes", [])
    raw_nodes = len(nodes_payload) if isinstance(nodes_payload, (list, dict)) else 0
    if raw_nodes == 0:
        raw_nodes = len({endpoint for channel in channels if (pair := _endpoints(channel)) for endpoint in pair})

    # One entry per unordered endpoint pair; store sum capacity and source-channel count.
    parallel: dict[tuple[str, str], dict[str, int]] = {}
    skipped_missing_policy = 0
    skipped_disabled = 0
    skipped_bad_channel = 0

    for channel in channels:
        endpoints = _endpoints(channel)
        capacity = _capacity_sat(channel)
        policies = _policy_pair(channel)
        if endpoints is None or capacity is None:
            skipped_bad_channel += 1
            continue
        if policies is None:
            skipped_missing_policy += 1
            continue
        policy_disabled = (_disabled(policies[0]), _disabled(policies[1]))
        if None in policy_disabled:
            skipped_missing_policy += 1
            continue
        # Current Network/paths modules represent a channel in both directions;
        # therefore a one-way-disabled channel is excluded altogether here.
        global_disabled = _disabled({"disabled": channel.get("disabled", False)})
        if any(policy_disabled) or global_disabled:
            skipped_disabled += 1
            continue

        a, b = sorted(endpoints)
        key = (a, b)
        info = parallel.setdefault(key, {"capacity": 0, "parallel_count": 0})
        info["capacity"] += capacity
        info["parallel_count"] += 1

    if not parallel:
        raise ValueError("No usable channels remained after policy and capacity filtering")

    structure = nx.Graph()
    for a, b in parallel:
        structure.add_edge(a, b)
    component = max(nx.connected_components(structure), key=len)
    component = set(component)
    kept = {edge: info for edge, info in parallel.items() if edge[0] in component and edge[1] in component}

    rng = np.random.default_rng([seed, 17])
    net = Network()
    for (a, b), info in sorted(kept.items()):
        capacity = info["capacity"]
        balance_a = split_balance(capacity, balance_model, rng)
        net.add_channel(a, b, capacity=capacity, balance_x=balance_a)
        # Preserve useful audit information on both directed edge records.
        net.graph[a][b]["parallel_count"] = info["parallel_count"]
        net.graph[b][a]["parallel_count"] = info["parallel_count"]

    if net.graph.number_of_nodes() == 0:
        raise ValueError("No nodes remained in the largest strongly connected component")
    if not net.check_money_conserved():
        raise RuntimeError("topology initialization violated channel money conservation")

    stats: dict[str, int | str] = {
        "snapshot": Path(path).name,
        "balance_model": balance_model,
        "seed": seed,
        "raw_nodes": raw_nodes,
        "raw_channels": len(channels),
        "channels_after_policy_filter": sum(info["parallel_count"] for info in parallel.values()),
        "merged_channel_pairs_before_component": len(parallel),
        "channels_after_largest_component": len(kept),
        "processed_nodes": net.graph.number_of_nodes(),
        "processed_channels": len(kept),
        "processed_directed_edges": net.graph.number_of_edges(),
        "skipped_missing_policy": skipped_missing_policy,
        "skipped_disabled": skipped_disabled,
        "skipped_bad_channel": skipped_bad_channel,
        "balances": "modeled, not observed",
    }
    return net, stats
