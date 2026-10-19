"""Scores for one attack: SCOOP's metrics, plus coins stuck on honest channels.

Choices SCOOP does not state (also to be listed in the README):
- Every score compares against the balances BEFORE the attack started (the "original
  bottleneck" of each route). This is the same for every attacker and never divides
  by zero, because routes with an empty channel were already dropped.
- SPCR is reported for L_max = 20 (the paper's stated value) and L_max = 8 (what the
  paper's plotted results suggest).
- gamma is reported two ways: the printed formula, and LockedPayment / mean PCR,
  which matches the paper's figures.
"""
from __future__ import annotations

import math

from .network import Network
from .paths import Route

L_MAX_VALUES = (20, 8)


def ccr(amount: int, balance: int) -> float:
    """Channel congestion ratio: share of one channel's balance that is locked (max 1)."""
    return min(1.0, amount / balance)


def pcr(amount: int, bottleneck: int) -> float:
    """Path congestion ratio: share of the route's weakest channel that is locked (max 1)."""
    return min(1.0, amount / bottleneck)


def spcr(amount: int, bottleneck: int, length: int, l_max: int) -> float:
    """Scaled PCR: PCR weighted by route length, so longer routes count more."""
    return length / l_max * pcr(amount, bottleneck)


def bottlenecks(net: Network, routes: list[Route]) -> list[int]:
    """Bottleneck of every route. Call this before the attack to get the originals."""
    return [net.bottleneck(r.nodes) for r in routes]


def summarize(routes: list[Route], amounts: list[int], original_bottlenecks: list[int]) -> dict:
    """Overall scores for one attack, as one row for the results CSV."""
    if not len(routes) == len(amounts) == len(original_bottlenecks):
        raise ValueError("routes, amounts and bottlenecks must have the same length")
    for a, b in zip(amounts, original_bottlenecks):
        if not 0 <= a <= b:
            raise ValueError("each amount must be between 0 and its route's bottleneck")

    n = len(routes)
    pcrs = [pcr(a, b) for a, b in zip(amounts, original_bottlenecks)]
    attacked = [i for i, a in enumerate(amounts) if a > 0]
    locked = sum(amounts)
    mean_pcr = sum(pcrs) / n if n else 0.0
    row = {
        "locked_payment": locked,
        "routes_total": n,
        "routes_attacked": len(attacked),
        "mean_pcr": mean_pcr,
        # Mallory's own first and last channels are not honest, so length - 2
        # This is a satoshi-hop aggregate over route interiors, not a count of
        # distinct coins; overlapping routes can count the same channel more than once.
        "honest_coins_stuck": sum(a * (r.length - 2) for r, a in zip(routes, amounts)),
        "gamma_ratio": locked / mean_pcr if mean_pcr > 0 else math.nan,
    }
    for l_max in L_MAX_VALUES:
        spcrs = [spcr(a, b, r.length, l_max) for r, a, b in zip(routes, amounts, original_bottlenecks)]
        row[f"mean_spcr_L{l_max}"] = sum(spcrs) / n if n else 0.0
        # Printed formula: average of amount / SPCR over the attacked routes
        row[f"gamma_printed_L{l_max}"] = (
            sum(amounts[i] / spcrs[i] for i in attacked) / len(attacked) if attacked else math.nan
        )
    return row
