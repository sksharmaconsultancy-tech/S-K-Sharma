"""Unit tests for the Iter 682 night-shift stitcher hardening."""
import sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from server import stitch_cross_day_ot  # noqa: E402

def P(date, kind, hh, mm):
    return {"date": date, "kind": kind, "at": f"{date}T{hh:02d}:{mm:02d}:00"}

# Case 1 — classic night shift, morning OUT at 08:03 (was refused before)
d = {
    "2026-08-21": [P("2026-08-21", "out", 7, 54), P("2026-08-21", "in", 19, 51)],
    "2026-08-22": [P("2026-08-22", "in", 8, 3)],  # mislabelled morning OUT
}
r = stitch_cross_day_ot(d)
c1 = len(r["2026-08-21"]) == 3 and r["2026-08-21"][-1]["kind"] == "out" and not r["2026-08-22"]
print("case1 (08:03 mislabelled morning OUT stitched):", "PASS" if c1 else f"FAIL {r}")

# Case 2 — double-tap tail: IN 19:51 then stray OUT 19:52; next-day OUT 07:58
d = {
    "2026-08-21": [P("2026-08-21", "in", 19, 51), P("2026-08-21", "out", 19, 52),
                   P("2026-08-21", "in", 19, 53)],
    "2026-08-22": [P("2026-08-22", "out", 7, 58)],
}
r = stitch_cross_day_ot(d)
c2 = any(p.get("_cross_day") for p in r["2026-08-21"]) and not r["2026-08-22"]
print("case2 (double-tap tail still stitches):", "PASS" if c2 else f"FAIL {r}")

# Case 3 — regression: normal day-shift must NOT steal next morning punch
d = {
    "2026-08-21": [P("2026-08-21", "in", 8, 2), P("2026-08-21", "out", 19, 58)],
    "2026-08-22": [P("2026-08-22", "in", 8, 1)],
}
r = stitch_cross_day_ot(d)
c3 = len(r["2026-08-21"]) == 2 and len(r["2026-08-22"]) == 1
print("case3 (day shift untouched):", "PASS" if c3 else f"FAIL {r}")

# Case 4 — regression: >16h gap not stitched
d = {
    "2026-08-21": [P("2026-08-21", "in", 10, 0)],
    "2026-08-23": [P("2026-08-23", "out", 9, 0)],
}
r = stitch_cross_day_ot(d)
c4 = len(r["2026-08-21"]) == 1
print("case4 (>16h gap refused):", "PASS" if c4 else f"FAIL {r}")

# Case 5 — mislabelled 'in' at 11:30 next day must NOT be stolen (new cap 11:00)
d = {
    "2026-08-21": [P("2026-08-21", "in", 19, 51)],
    "2026-08-22": [P("2026-08-22", "in", 11, 30)],
}
r = stitch_cross_day_ot(d)
c5 = len(r["2026-08-21"]) == 1 and len(r["2026-08-22"]) == 1
print("case5 (11:30 next-day IN kept):", "PASS" if c5 else f"FAIL {r}")

print("ALL PASS" if all([c1, c2, c3, c4, c5]) else "FAILURES PRESENT")
