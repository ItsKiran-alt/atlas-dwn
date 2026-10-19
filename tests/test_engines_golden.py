"""The PRODUCTION engines checked against every golden scenario (tier, flags, message routing, goal status, forbidden trades)."""
import pytest

from dwn.engines.pipeline import analyse
from loader import scenarios

CASES = list(scenarios())


@pytest.mark.parametrize("s,profile,event", CASES, ids=[c[0]["id"] for c in CASES])
def test_production_engine_matches_golden(s, profile, event):
    a = analyse(profile, event)
    e = s["expected"]
    assert a.tier == str(e["tier"]), f'{s["id"]}: tier {a.tier} != {e["tier"]} ({a.flags})'
    assert sorted(a.flags) == sorted(e["flags"]), f'{s["id"]}: flags {a.flags} != {e["flags"]}'
    assert a.message == e["client_message"], f'{s["id"]}: message {a.message} != {e["client_message"]}'
    if e["goal_status_after"]:
        assert a.goal_after.status == e["goal_status_after"]
    mnt = s["must_not_trade_classes"]
    if mnt not in ("-", "all classes"):
        assert mnt in a.must_not_trade, f'{s["id"]}: {mnt} must be protected from trading, got {a.must_not_trade}'
    if mnt == "all classes":
        assert a.tier == "Paused"
    if a.tier == "Paused":
        assert a.adjustment is None


def test_engine_is_deterministic():
    s, p, ev = CASES[0]
    assert analyse(p, ev).model_dump() == analyse(p, ev).model_dump()


def test_no_adjustment_ever_touches_a_protected_class():
    for s, p, ev in CASES:
        a = analyse(p, ev)
        if a.adjustment:
            for cls in a.must_not_trade:
                if cls in p.restrictions.untradable:
                    assert abs(a.adjustment[cls]) < 0.05, (s["id"], cls, a.adjustment)
            if p.restrictions.no_new_alts:
                assert a.adjustment["AL"] <= 0.05, (s["id"], a.adjustment)
