# app/strategy.py
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from app.config import settings
from app.logger import logger


@dataclass
class Edge:
    source: str
    target: str
    rate: float


@dataclass
class QuoteSnapshot:
    spot_price: float
    futures_price: float
    slippage_bp: float = settings.slippage_bp
    loan_fee_rate: float = 0.0


@dataclass
class TradePlan:
    execute: bool
    qty_mwh: float = 0.0
    spread: float = 0.0
    expected_profit: float = 0.0
    path: list[str] | None = None
    block_reason: str | None = None


def kelly_size(spread: float, stdev: float = 35, bank: float = 50_000) -> float:
    """Return a crude Kelly position size in MWh."""

    f_star = spread / (stdev**2)
    size_fraction = min(max(f_star, 0), 0.10)
    return size_fraction * bank / spread


def _build_edges(quotes: QuoteSnapshot) -> list[Edge]:
    if quotes.spot_price <= 0 or quotes.futures_price <= 0:
        raise ValueError("Quotes must be positive")

    slip = max(quotes.slippage_bp, 0) / 10_000
    buy_price = quotes.spot_price * (1 + slip)
    sell_price = quotes.futures_price * (1 - slip)
    loan_multiplier = max(0.0, 1 - quotes.loan_fee_rate)

    edges = [
        Edge("GBP", "MWH", rate=1 / buy_price),
        Edge("MWH", "GBP", rate=sell_price),
        Edge("GBP", "GBP", rate=loan_multiplier),
    ]
    return edges


def _bellman_ford(nodes: Sequence[str], edges: Sequence[Edge], source: str) -> list[str] | None:
    dist = {node: math.inf for node in nodes}
    pred: dict[str, str | None] = {node: None for node in nodes}
    dist[source] = 0

    weights = {(edge.source, edge.target): -math.log(edge.rate) for edge in edges}

    for _ in range(len(nodes) - 1):
        updated = False
        for edge in edges:
            weight = weights[(edge.source, edge.target)]
            if dist[edge.source] + weight < dist[edge.target]:
                dist[edge.target] = dist[edge.source] + weight
                pred[edge.target] = edge.source
                updated = True
        if not updated:
            break

    for edge in edges:
        weight = weights[(edge.source, edge.target)]
        if dist[edge.source] + weight < dist[edge.target]:
            cycle_start = edge.target
            for _ in range(len(nodes)):
                cycle_start = pred.get(cycle_start) or cycle_start
            cycle = [cycle_start]
            node = pred.get(cycle_start)
            while node is not None and node not in cycle:
                cycle.append(node)
                node = pred.get(node)
            cycle.append(cycle[0])
            cycle.reverse()
            return cycle

    return None


def _cycle_rate(path: Iterable[str], edges: Sequence[Edge]) -> float:
    edge_map = {(edge.source, edge.target): edge for edge in edges}
    nodes = list(path)
    if len(nodes) < 2:
        return 1.0

    rate = 1.0
    for left, right in zip(nodes, nodes[1:]):
        edge = edge_map.get((left, right))
        if edge is None:
            return 0.0
        rate *= edge.rate
    return rate


def select_route(quotes: QuoteSnapshot) -> TradePlan:
    edges = _build_edges(quotes)
    nodes = sorted({edge.source for edge in edges} | {edge.target for edge in edges})

    spread = quotes.futures_price - quotes.spot_price
    cycle = _bellman_ford(nodes, edges, source="GBP")
    if not cycle:
        logger.debug("No negative cycle detected")
        return TradePlan(False, 0.0, spread, 0.0, [], None)

    cycle_rate = _cycle_rate(cycle, edges)
    slip = max(quotes.slippage_bp, 0) / 10_000
    buy_price = quotes.spot_price * (1 + slip)
    sell_price = quotes.futures_price * (1 - slip)
    loan_multiplier = max(0.0, 1 - quotes.loan_fee_rate)

    profit_per_mwh = sell_price * loan_multiplier - buy_price
    if cycle_rate <= 1 or profit_per_mwh <= 0:
        logger.debug(
            "Cycle rejected: rate=%.6f profit/mwh=%.4f path=%s",
            cycle_rate,
            profit_per_mwh,
            cycle,
        )
        return TradePlan(False, 0.0, spread, 0.0, cycle, None)

    qty = kelly_size(profit_per_mwh, bank=settings.kelly_bank_gbp)
    max_notional = min(settings.max_notional_per_trade, settings.loan_limit_gbp)
    notional = qty * buy_price

    if notional > max_notional:
        logger.debug(
            "Notional %.2f above cap %.2f; skipping trade", notional, max_notional
        )
        return TradePlan(False, 0.0, spread, 0.0, cycle, "notional")

    if qty <= 0:
        logger.debug("Zero position after risk caps; skipping")
        return TradePlan(False, 0.0, spread, 0.0, cycle, None)

    expected_profit = qty * profit_per_mwh
    return TradePlan(True, qty, profit_per_mwh, expected_profit, list(cycle), None)
