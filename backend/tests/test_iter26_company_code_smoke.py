"""Iteration 26 — Phase C follow-up smoke tests.

Focus:
    * POST /api/companies rejects invalid company_code shape (400)
    * POST /api/companies accepts 2-char company_code
    * POST /api/companies returns 409 on duplicate company_code
    * PATCH /api/companies/{id} with company_code="" is a no-op (other fields
      still update)
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
_mc = MongoClient(MONGO_URL)
db = _mc[DB_NAME]

RUN_ID = f"IT26{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def super_admin_token():
    sa = db.users.find_one({"email": "sksharmaconsultancy@gmail.com"})
    assert sa, "super_admin seed missing"
    token = f"testiter26_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": token,
        "user_id": sa["user_id"],
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "created_at": datetime.now(timezone.utc),
        "auth_method": "test_seed",
    })
    yield token
    db.user_sessions.delete_one({"session_token": token})


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    db.companies.delete_many({"name": {"$regex": f"^{RUN_ID}"}})
    db.user_sessions.delete_many({"auth_method": "test_seed"})


def _hdr(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


class TestCompanyCodeValidation:
    def test_invalid_shape_returns_400(self, super_admin_token):
        r = requests.post(f"{API}/companies", headers=_hdr(super_admin_token),
                          json={"name": f"{RUN_ID} InvalidCo",
                                "office_lat": 12.9, "office_lng": 77.6,
                                "company_code": "invalid!"})
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "")
        assert "2" in detail and "8" in detail, f"expected format message, got: {detail!r}"

    def test_two_char_code_accepted(self, super_admin_token):
        # Use a run-unique 2-char code to avoid collision. Use digits + a letter
        # from RUN_ID hash to keep it truly unique per run.
        # Note: RUN_ID is e.g. IT26abcdef; take a couple hex chars.
        code_char = RUN_ID[4].upper()  # a-f -> A-F, a letter
        code_digit = RUN_ID[5]         # hex digit 0-9 or a-f
        code = (code_char + code_digit).upper()[:2]
        # Ensure regex [A-Z0-9]{2,8} — replace any non-alnum with a digit
        code = "".join(c if c.isalnum() else "9" for c in code).upper()
        r = requests.post(f"{API}/companies", headers=_hdr(super_admin_token),
                          json={"name": f"{RUN_ID} TwoCharCo",
                                "office_lat": 12.9, "office_lng": 77.6,
                                "company_code": code})
        # If the 2-char code happens to already exist (409) that's a legit
        # response too — but we specifically want to prove 200 works when free.
        if r.status_code == 409:
            # try another combo
            code = ("Z" + RUN_ID[-1].upper()).replace("!", "9")[:2]
            code = "".join(c if c.isalnum() else "9" for c in code).upper()
            r = requests.post(f"{API}/companies", headers=_hdr(super_admin_token),
                              json={"name": f"{RUN_ID} TwoCharCoB",
                                    "office_lat": 12.9, "office_lng": 77.6,
                                    "company_code": code})
        assert r.status_code == 200, r.text
        assert r.json().get("company_code") == code

    def test_duplicate_code_returns_409(self, super_admin_token):
        dup_code = f"DP{RUN_ID[:2].upper()}"
        dup_code = "".join(c if c.isalnum() else "9" for c in dup_code).upper()

        r = requests.post(f"{API}/companies", headers=_hdr(super_admin_token),
                          json={"name": f"{RUN_ID} DupCoA",
                                "office_lat": 12.9, "office_lng": 77.6,
                                "company_code": dup_code})
        assert r.status_code == 200, r.text

        r = requests.post(f"{API}/companies", headers=_hdr(super_admin_token),
                          json={"name": f"{RUN_ID} DupCoB",
                                "office_lat": 12.9, "office_lng": 77.6,
                                "company_code": dup_code})
        assert r.status_code == 409, r.text
        detail = r.json().get("detail", "")
        assert dup_code in detail, f"expected code in error msg, got: {detail!r}"

    def test_patch_blank_company_code_is_noop(self, super_admin_token):
        # Create with a definite code
        original = f"OG{RUN_ID[:2].upper()}"
        original = "".join(c if c.isalnum() else "9" for c in original).upper()
        r = requests.post(f"{API}/companies", headers=_hdr(super_admin_token),
                          json={"name": f"{RUN_ID} NoopCo",
                                "office_lat": 10.0, "office_lng": 20.0,
                                "company_code": original})
        assert r.status_code == 200, r.text
        cid = r.json()["company_id"]

        # PATCH with blank company_code + updates to other fields
        r = requests.patch(f"{API}/companies/{cid}", headers=_hdr(super_admin_token),
                           json={"company_code": "",
                                 "name": f"{RUN_ID} NoopCo v2",
                                 "address": "New Address"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["company_code"] == original, (
            f"company_code should have been preserved but got {body['company_code']!r}"
        )
        assert body["name"] == f"{RUN_ID} NoopCo v2"
        assert body["address"] == "New Address"
