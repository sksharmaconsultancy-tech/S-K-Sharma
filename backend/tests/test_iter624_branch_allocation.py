"""Iter 624 — Multi-branch acceptance test (user spec §19 'Rahul').

Rahul: Home Branch A, authorized A+B, monthly ₹30,000, 30 payable days.
Attendance: 01–10 Branch A, 11 Branch B, 12–30 Branch A.
Expected: ONE payroll record; Branch A cost ₹29,000; Branch B ₹1,000
(guest day); no duplicate PF/ESIC (allocation is proportional shares of the
single employer liability).
Run:  cd /app/backend && python -m pytest tests/test_iter624_branch_allocation.py -q
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, "/app/backend")

CID = "cmp_test_branch624"
MONTH = "2026-07"


@pytest.fixture(scope="module")
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _seed(db):
    async def run():
        for c in ("users", "branches", "attendance", "compliance_salary_runs",
                  "branch_temp_assignments"):
            await db[c].delete_many({"company_id": CID})
        await db.branches.insert_many([
            {"branch_id": "brA", "company_id": CID, "name": "Branch A", "active": True},
            {"branch_id": "brB", "company_id": CID, "name": "Branch B", "active": True},
        ])
        await db.users.insert_one({
            "user_id": "u_rahul", "company_id": CID, "role": "employee",
            "name": "Rahul", "home_branch_id": "brA",
            "authorized_branch_ids": ["brA", "brB"], "status": "active",
        })
        punches = []
        for d in range(1, 31):
            date = f"{MONTH}-{d:02d}"
            bid = "brB" if d == 11 else "brA"
            punches.append({"record_id": f"att_{d}", "user_id": "u_rahul",
                            "company_id": CID, "date": date, "kind": "in",
                            "at": f"{date}T09:00:00", "branch_id": bid,
                            "home_branch_id": "brA"})
        await db.attendance.insert_many(punches)
        await db.compliance_salary_runs.insert_one({
            "run_id": "csrun_test624", "company_id": CID, "month": MONTH,
            "month_days": 30, "rows": [{
                "user_id": "u_rahul", "name": "Rahul", "company_id": CID,
                "present_days": 30, "gross_paid": 30000, "net_payable": 30000,
                "pf_employer_total": 1800, "esic_employer": 0,
            }],
        })
    return run


def test_rahul_allocation(loop):
    from server import db
    from routes.branch_management import _allocation
    loop.run_until_complete(_seed(db)())
    data = loop.run_until_complete(_allocation(CID, MONTH))

    # ONE payroll record only
    assert len(data["employees"]) == 1
    e = data["employees"][0]
    assert e["home_branch_id"] == "brA"
    assert e["gross"] == 30000
    assert e["cross_branch"] is True

    by_bid = {b["branch_id"]: b for b in data["branches"]}
    assert by_bid["brA"]["gross"] == 29000, by_bid
    assert by_bid["brB"]["gross"] == 1000, by_bid
    assert by_bid["brA"]["days"] == 29 and by_bid["brB"]["days"] == 1
    # guest day recognised on Branch B
    assert by_bid["brB"]["guest_days"] == 1
    # employer PF liability allocated proportionally — totals stay 1800 (no duplication)
    assert round(by_bid["brA"]["pf_employer"] + by_bid["brB"]["pf_employer"]) == 1800
    # totals reconcile to the single consolidated salary
    assert round(sum(b["gross"] for b in data["branches"])) == 30000


def test_no_punch_days_fall_to_home_branch(loop):
    from server import db
    from routes.branch_management import _allocation

    async def tweak():
        # remove ALL punches → allocation must fall back to home branch
        await db.attendance.delete_many({"company_id": CID})
    loop.run_until_complete(tweak())
    data = loop.run_until_complete(_allocation(CID, MONTH))
    by_bid = {b["branch_id"]: b for b in data["branches"]}
    assert by_bid["brA"]["gross"] == 30000 and "brB" not in by_bid


def test_cleanup(loop):
    from server import db

    async def clean():
        for c in ("users", "branches", "attendance", "compliance_salary_runs",
                  "branch_temp_assignments"):
            await db[c].delete_many({"company_id": CID})
    loop.run_until_complete(clean())
