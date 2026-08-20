"""Iter 624 — unit test for the multi-branch punch authorization gate.
Run: cd /app/backend && python -m pytest tests/test_iter624_punch_gate.py -q
"""
import asyncio
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, "/app/backend")

CID = "cmp_test_gate624"
TODAY = "2026-08-20"


@pytest.fixture(scope="module")
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_punch_gate(loop):
    from server import db
    from routes.attendance_core import _branch_punch_gate

    async def run():
        await db.branch_temp_assignments.delete_many({"company_id": CID})
        emp = {"user_id": "u_gate", "company_id": CID,
               "home_branch_id": "brA", "authorized_branch_ids": ["brA", "brB"]}
        legacy = {"user_id": "u_legacy", "company_id": CID}

        # 1. no branch config → always allowed (legacy behaviour)
        assert await _branch_punch_gate(legacy, "brZ", "Z", TODAY) is None
        # 2. home / authorized branch → allowed
        assert await _branch_punch_gate(emp, "brA", "A", TODAY) is None
        assert await _branch_punch_gate(emp, "brB", "B", TODAY) is None
        # 3. main office is never blocked
        assert await _branch_punch_gate(emp, "main", "Main", TODAY) is None
        # 4. unauthorised branch, no temp assignment → 403
        try:
            await _branch_punch_gate(emp, "brC", "C", TODAY)
            raise AssertionError("expected 403")
        except HTTPException as e:
            assert e.status_code == 403 and "not authorised" in e.detail
        # 5. approved temp assignment covering today → allowed + id returned
        await db.branch_temp_assignments.insert_one({
            "assign_id": "bta_gate1", "company_id": CID, "user_id": "u_gate",
            "branch_id": "brC", "status": "approved",
            "from_date": "2026-08-19", "to_date": "2026-08-21"})
        assert await _branch_punch_gate(emp, "brC", "C", TODAY) == "bta_gate1"
        # 6. assignment window over → 403 again
        assert await _branch_punch_gate(emp, "brC", "C", "2026-08-25") is not None \
            if False else True
        try:
            await _branch_punch_gate(emp, "brC", "C", "2026-08-25")
            raise AssertionError("expected 403 after window")
        except HTTPException as e:
            assert e.status_code == 403
        # 7. cancelled assignment → 403
        await db.branch_temp_assignments.update_one(
            {"assign_id": "bta_gate1"}, {"$set": {"status": "cancelled"}})
        try:
            await _branch_punch_gate(emp, "brC", "C", TODAY)
            raise AssertionError("expected 403 after cancel")
        except HTTPException as e:
            assert e.status_code == 403
        await db.branch_temp_assignments.delete_many({"company_id": CID})
    loop.run_until_complete(run())
