"""Estimated performance and drift analytics for the charts. Deterministic, no LLM, no invented numbers.

The portfolio's real return history is not available in this prototype. What we CAN say honestly is how the portfolio's
CURRENT mix would have behaved, using weekly closes of low-cost market proxies (SPY = equities, AGG = bonds, VNQ = alternatives,
cash = 0%). Every chart that uses this says so. If history is missing, the result is `available=False` and the UI shows
"not available yet" rather than a number."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

PROXY = {"EQ": "SPY", "FI": "AGG", "AL": "VNQ"}          # cash earns 0 in this estimate
BENCH = {"SPY": 0.60, "AGG": 0.40}
SYMBOLS = ["SPY", "AGG", "VNQ"]
WEEKS = {"1Y": 52, "3Y": 156, "5Y": 260}
MIN_WEEKS = 20


@dataclass
class Perf:
    available: bool = False
    reason: str = ""
    dates: list = field(default_factory=list)
    portfolio: list = field(default_factory=list)     # index, starts at 100
    benchmark: list = field(default_factory=list)
    returns: dict = field(default_factory=dict)       # {"1Y": 8.2, ...} only for windows the history covers
    bench_returns: dict = field(default_factory=dict)
    asof: date | None = None


def _weekly_returns(bars: list[tuple]) -> dict[date, float]:
    out = {}
    for (d0, c0), (d1, c1) in zip(bars, bars[1:]):
        if c0 and c0 > 0:
            out[d1] = c1 / c0 - 1.0
    return out


def _compound(rets: dict[date, float], weights: dict[str, float], days: list[date]) -> list[float]:
    idx, out = 100.0, [100.0]
    for d in days[1:]:
        r = sum(w * rets[s].get(d, 0.0) for s, w in weights.items())
        idx *= 1.0 + r
        out.append(idx)
    return out


def estimate(weights: dict[str, float], history: dict[str, list[tuple]], years: int = 5) -> Perf:
    """`weights` are percentages by class (EQ/FI/AL/CA). Weekly rebalanced to constant weights."""
    need = [s for s in SYMBOLS if len(history.get(s) or []) >= MIN_WEEKS]
    if len(need) < len(SYMBOLS):
        return Perf(reason="Market history has not been loaded yet. Use Research & Market > Refresh to load it.")
    rets = {s: _weekly_returns(history[s]) for s in SYMBOLS}
    common = sorted(set.intersection(*(set(r) for r in rets.values())))
    common = common[-WEEKS["5Y" if years >= 5 else "3Y"]:]
    if len(common) < MIN_WEEKS:
        return Perf(reason="Not enough overlapping history to draw a chart.")
    days = [common[0]] + common            # a base point one step before the first return
    port_w = {PROXY[k]: weights.get(k, 0) / 100.0 for k in PROXY}
    p = _compound(rets, port_w, days)
    b = _compound(rets, BENCH, days)
    res = Perf(available=True, dates=days, portfolio=p, benchmark=b, asof=days[-1])
    for label, wk in WEEKS.items():
        if len(days) > wk:
            res.returns[label] = round((p[-1] / p[-1 - wk] - 1.0) * 100.0, 1)
            res.bench_returns[label] = round((b[-1] / b[-1 - wk] - 1.0) * 100.0, 1)
    return res


def drift_rows(weights: dict[str, float], plan: dict[str, float], band: float) -> list[dict]:
    """Per class gap from the target plan and whether it is outside the drift range (band, in points)."""
    rows = []
    for k, label in (("EQ", "Equities"), ("FI", "Bonds"), ("AL", "Alternatives"), ("CA", "Cash")):
        cur, tgt = float(weights.get(k, 0)), float(plan.get(k, 0))
        rows.append(dict(key=k, label=label, current=cur, target=tgt, gap=round(cur - tgt, 1), outside=abs(cur - tgt) > band))
    return rows
