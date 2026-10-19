"""Payment channel network: balances, honest payments, and locked (stuck) payments.

Every channel x-y is stored as two directed edges, x->y and y->x. Each edge holds:
  balance   coins x can still send to y
  locked    coins x has locked toward y in payments that never finish
  capacity  total coins in the channel (same value on both edges)

Money is conserved on every channel:
  balance_xy + balance_yx + locked_xy + locked_yx == capacity

All amounts are whole satoshi (integers).
"""
from __future__ import annotations

import numbers

import networkx as nx


class Network:
    def __init__(self) -> None:
        self.graph = nx.DiGraph()

    def add_channel(self, x, y, capacity: int, balance_x: int) -> None:
        """Open a channel; x holds balance_x and y holds the rest of the capacity."""
        if x == y:
            raise ValueError("a channel needs two different nodes")
        if self.graph.has_edge(x, y):
            raise ValueError(f"channel {x}-{y} already exists")
        if not 0 <= balance_x <= capacity:
            raise ValueError("balance_x must be between 0 and capacity")
        self.graph.add_edge(x, y, capacity=capacity, balance=balance_x, locked=0)
        self.graph.add_edge(y, x, capacity=capacity, balance=capacity - balance_x, locked=0)

    def balance(self, x, y) -> int:
        return self.graph[x][y]["balance"]

    def locked(self, x, y) -> int:
        return self.graph[x][y]["locked"]

    def bottleneck(self, path) -> int:
        """Smallest balance along the path: the most that can be sent through it."""
        return min(self.graph[x][y]["balance"] for x, y in self._hops(path))

    def pay(self, path, amount: int) -> None:
        """Honest payment: on every hop the coins move to the other side."""
        amount = self._checked(path, amount)
        for x, y in self._hops(path):
            self.graph[x][y]["balance"] -= amount
            self.graph[y][x]["balance"] += amount

    def lock(self, path, amount: int) -> None:
        """Attacker payment that never finishes: on every hop the coins get stuck."""
        amount = self._checked(path, amount)
        for x, y in self._hops(path):
            self.graph[x][y]["balance"] -= amount
            self.graph[x][y]["locked"] += amount

    def copy(self) -> Network:
        """Independent copy, so every attacker starts from the identical network."""
        new = Network()
        new.graph = self.graph.copy()
        return new

    def check_money_conserved(self) -> bool:
        for x, y, edge in self.graph.edges(data=True):
            back = self.graph[y][x]
            total = edge["balance"] + back["balance"] + edge["locked"] + back["locked"]
            if total != edge["capacity"]:
                return False
        return True

    def _hops(self, path):
        if len(path) < 2:
            raise ValueError("a path needs at least two nodes")
        if len(set(path)) != len(path):
            raise ValueError("a path must not visit a node twice")
        hops = list(zip(path, path[1:]))
        for x, y in hops:
            if not self.graph.has_edge(x, y):
                raise ValueError(f"no channel between {x} and {y}")
        return hops

    def _checked(self, path, amount) -> int:
        """Validate an amount for this path, before anything is changed."""
        if isinstance(amount, bool) or not isinstance(amount, numbers.Integral):
            raise TypeError("amounts must be whole satoshi (integers)")
        if amount < 0:
            raise ValueError("amount cannot be negative")
        if amount > self.bottleneck(path):
            raise ValueError("amount exceeds the path bottleneck")
        return int(amount)
