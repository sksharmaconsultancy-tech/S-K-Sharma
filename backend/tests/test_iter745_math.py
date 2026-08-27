"""Iter 745 — pure math checks for _lp_penalty_days (run inside server ctx)."""
import server  # noqa: F401  (loads app + routers first, avoids circular import)
from routes.hr_extras import _lp_penalty_days

slabs = {"mode": "slabs", "slabs": [
    {"from": 1, "to": 3, "days": 0.5}, {"from": 4, "to": 6, "days": 1},
    {"from": 7, "to": None, "days": 2}], "max_days": 0}
assert _lp_penalty_days(0, slabs) == 0
assert _lp_penalty_days(2, slabs) == 0.5
assert _lp_penalty_days(5, slabs) == 1
assert _lp_penalty_days(9, slabs) == 2
en = {"mode": "every_n", "every_n": 3, "every_n_days": 0.5, "max_days": 0}
assert _lp_penalty_days(7, en) == 1.0
assert _lp_penalty_days(2, en) == 0.0
cap = {"mode": "every_n", "every_n": 1, "every_n_days": 0.5, "max_days": 1}
assert _lp_penalty_days(10, cap) == 1.0
print("slab/every_n/cap math PASS")
