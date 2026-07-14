"""Iteration 18 — Company / Employer persona (Path A self-register +
Path B super-admin allot) backend tests.

Covers:
  - POST /api/auth/company-register  (public)
  - PATCH /api/company-requests/{id}  (approval + provisioning)
  - POST /api/companies               (Path B — allot + temp PIN)
  - POST /api/auth/admin-pin-login    (for both provisioned admins)

The tests seed a THROWAWAY super_admin doc via pymongo so we never
touch the real super admin's PIN. Everything created during the run is
cleaned up in a fixture teardown.
"""

import os
import uuid

import bcrypt
import pytest
import requests
from pymongo import MongoClient


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL not set in frontend/.env")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

# Unique test tag to make cleanup + email identification trivial
TAG = f"ITER18_{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def throwaway_super_admin(mongo, http):
    """Seed a fresh super_admin (NOT the real one) with a known PIN and
    return {'headers': {...}, 'user_id': ...}. Cleaned up after tests."""
    from datetime import datetime, timezone
    pin = "778899"
    pin_hash = bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()
    uid = f"user_{TAG}_sa"
    email = f"throwaway_sa_{TAG.lower()}@example.com"
    mongo.users.insert_one({
        "user_id": uid,
        "email": email,
        "phone": f"+9199{TAG[-6:].replace('_', '0').rjust(8, '9')[:8]}",
        "name": f"Throwaway SA {TAG}",
        "role": "super_admin",
        "has_pin": True,
        "pin_hash": pin_hash,
        "pin_must_change": False,
        "pin_fail_count": 0,
        "pin_locked_until": None,
        "onboarded": True,
        "approval_status": "approved",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Log in
    r = http.post(f"{API}/auth/admin-pin-login", json={"identifier": email, "pin": pin})
    assert r.status_code == 200, f"seed super-admin login failed: {r.status_code} {r.text}"
    token = r.json()["session_token"]
    yield {
        "user_id": uid,
        "email": email,
        "headers": {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    }
    # ---- Global teardown ----
    # Remove throwaway super admin + all sessions
    mongo.user_sessions.delete_many({"user_id": uid})
    mongo.users.delete_one({"user_id": uid})
    # Delete all data created with our TAG
    mongo.company_requests.delete_many({"$or": [
        {"company_name": {"$regex": TAG}},
        {"contact_email": {"$regex": TAG.lower()}},
    ]})
    # Companies + users provisioned during tests
    cos = list(mongo.companies.find({"name": {"$regex": TAG}}, {"company_id": 1}))
    cids = [c["company_id"] for c in cos]
    if cids:
        mongo.companies.delete_many({"company_id": {"$in": cids}})
        mongo.users.delete_many({"company_id": {"$in": cids}})
    # Users by phone/email tag
    mongo.users.delete_many({"$or": [
        {"email": {"$regex": TAG.lower()}},
        {"name": {"$regex": TAG}},
    ]})


def _tagged_phone(idx: int) -> str:
    # Unique deterministic-ish phone under TAG
    return f"+9198{str(abs(hash(TAG + str(idx))))[-8:]}"


# ---------------------------------------------------------------------------
# PATH A — self-register
# ---------------------------------------------------------------------------
class TestPathASelfRegister:
    def _valid_payload(self, idx=1):
        return {
            "company_name": f"{TAG} Firm A{idx}",
            "address": "Plot 12 Sector 5",
            "city": "Noida",
            "state": "Uttar Pradesh",
            "contact_name": f"Owner {TAG} {idx}",
            "contact_mobile": _tagged_phone(idx),
            "contact_email": f"owner_{TAG.lower()}_{idx}@example.com",
            "nature_of_business": "Manufacturing",
            "pin": "482913",
        }

    def test_valid_registration(self, http, mongo):
        p = self._valid_payload(1)
        r = http.post(f"{API}/auth/company-register", json=p)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert isinstance(data.get("request_id"), str) and data["request_id"]
        assert "message" in data

        doc = mongo.company_requests.find_one({"request_id": data["request_id"]})
        assert doc is not None
        assert doc["kind"] == "self_register"
        assert doc["status"] == "pending"
        assert doc.get("admin_pin_hash")
        # bcrypt verify
        assert bcrypt.checkpw(p["pin"].encode(), doc["admin_pin_hash"].encode())

    @pytest.mark.parametrize("field", ["company_name", "address", "city", "state", "contact_name", "nature_of_business"])
    def test_missing_required_field(self, http, field):
        p = self._valid_payload(2)
        p[field] = ""
        p["contact_mobile"] = _tagged_phone(20 + hash(field) % 100)
        r = http.post(f"{API}/auth/company-register", json=p)
        assert r.status_code == 400, f"{field}: expected 400 got {r.status_code} {r.text}"

    def test_invalid_email(self, http):
        p = self._valid_payload(3)
        p["contact_email"] = "not-an-email"
        p["contact_mobile"] = _tagged_phone(3)
        r = http.post(f"{API}/auth/company-register", json=p)
        assert r.status_code == 400
        assert "email" in r.json().get("detail", "").lower()

    @pytest.mark.parametrize("bad_pin", ["12345", "1234567", "abcdef", "111111", "123456", "000000"])
    def test_invalid_pin(self, http, bad_pin):
        p = self._valid_payload(4)
        p["pin"] = bad_pin
        p["contact_mobile"] = _tagged_phone(40 + hash(bad_pin) % 100)
        r = http.post(f"{API}/auth/company-register", json=p)
        assert r.status_code == 400, f"pin={bad_pin} got {r.status_code}"

    def test_duplicate_mobile_pending_request(self, http):
        p = self._valid_payload(5)
        r1 = http.post(f"{API}/auth/company-register", json=p)
        assert r1.status_code == 200, r1.text
        # 2nd call same phone → 409
        r2 = http.post(f"{API}/auth/company-register", json=p)
        assert r2.status_code == 409, f"expected 409 got {r2.status_code} {r2.text}"

    def test_duplicate_mobile_existing_user(self, http, mongo):
        # Insert a user with a known phone, then attempt to register
        phone = _tagged_phone(6)
        mongo.users.insert_one({
            "user_id": f"user_{TAG}_pre",
            "email": f"pre_{TAG.lower()}@example.com",
            "phone": phone,
            "name": f"Pre {TAG}",
            "role": "employee",
            "created_at": "2024-01-01T00:00:00+00:00",
        })
        p = self._valid_payload(6)
        p["contact_mobile"] = phone
        r = http.post(f"{API}/auth/company-register", json=p)
        assert r.status_code == 409, r.text


# ---------------------------------------------------------------------------
# PATH A — approval / provisioning
# ---------------------------------------------------------------------------
class TestPathAApproval:
    def _submit(self, http, idx):
        p = {
            "company_name": f"{TAG} ApproveCo {idx}",
            "address": "Approval Rd",
            "city": "Pune",
            "state": "Maharashtra",
            "contact_name": f"ApprOwner {TAG} {idx}",
            "contact_mobile": _tagged_phone(200 + idx),
            "contact_email": f"appr_{TAG.lower()}_{idx}@example.com",
            "nature_of_business": "Services",
            "pin": "593827",
        }
        r = http.post(f"{API}/auth/company-register", json=p)
        assert r.status_code == 200, r.text
        return p, r.json()["request_id"]

    def test_approve_provisions_company_and_admin(self, http, mongo, throwaway_super_admin):
        p, req_id = self._submit(http, 1)
        r = http.patch(
            f"{API}/company-requests/{req_id}",
            json={"status": "approved"},
            headers=throwaway_super_admin["headers"],
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "company_id" in data
        assert "company_code" in data
        assert "admin_user_id" in data
        # company_code = 6-char uppercase hex
        cc = data["company_code"]
        assert len(cc) == 6 and cc == cc.upper() and all(ch in "0123456789ABCDEF" for ch in cc)

        co = mongo.companies.find_one({"company_id": data["company_id"]})
        assert co is not None
        assert co["name"] == p["company_name"]

        u = mongo.users.find_one({"user_id": data["admin_user_id"]})
        assert u is not None
        assert u["role"] == "company_admin"
        assert u["phone"] == p["contact_mobile"]
        assert bcrypt.checkpw(p["pin"].encode(), u["pin_hash"].encode())
        assert u.get("pin_must_change") is False

        # Login test
        lr = http.post(f"{API}/auth/admin-pin-login",
                       json={"identifier": p["contact_mobile"], "pin": p["pin"]})
        assert lr.status_code == 200, lr.text
        ld = lr.json()
        assert "session_token" in ld and ld["session_token"]
        assert ld.get("pin_must_change") is False

    def test_reject_leaves_db_clean(self, http, mongo, throwaway_super_admin):
        p, req_id = self._submit(http, 2)
        r = http.patch(
            f"{API}/company-requests/{req_id}",
            json={"status": "rejected"},
            headers=throwaway_super_admin["headers"],
        )
        assert r.status_code == 200, r.text
        assert mongo.companies.find_one({"name": p["company_name"]}) is None
        assert mongo.users.find_one({"phone": p["contact_mobile"]}) is None


# ---------------------------------------------------------------------------
# PATH B — super admin allots credentials
# ---------------------------------------------------------------------------
class TestPathBAllotCredentials:
    def test_create_company_with_admin_returns_temp_pin(self, http, mongo, throwaway_super_admin):
        phone = _tagged_phone(300)
        payload = {
            "name": f"{TAG} PathB Co",
            "address": "Path B Ave",
            "office_lat": 28.6,
            "office_lng": 77.2,
            "admin_phone": phone,
            "admin_name": f"PathB Admin {TAG}",
            "admin_email": f"pathb_{TAG.lower()}@example.com",
        }
        r = http.post(f"{API}/companies", json=payload, headers=throwaway_super_admin["headers"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "admin" in data
        temp_pin = data["admin"].get("temp_pin")
        assert isinstance(temp_pin, str) and len(temp_pin) == 6 and temp_pin.isdigit()

        u = mongo.users.find_one({"phone": phone})
        assert u is not None
        assert u["role"] == "company_admin"
        assert u.get("pin_must_change") is True

        # Log in with temp PIN
        lr = http.post(f"{API}/auth/admin-pin-login",
                       json={"identifier": phone, "pin": temp_pin})
        assert lr.status_code == 200, lr.text
        ld = lr.json()
        assert ld.get("pin_must_change") is True
        assert "session_token" in ld

    def test_duplicate_admin_phone_409(self, http, throwaway_super_admin):
        phone = _tagged_phone(301)
        p = {
            "name": f"{TAG} DupCo 1",
            "address": "Dup Ave",
            "office_lat": 28.6,
            "office_lng": 77.2,
            "admin_phone": phone,
            "admin_name": f"Dup Admin {TAG}",
            "admin_email": f"dup1_{TAG.lower()}@example.com",
        }
        r1 = http.post(f"{API}/companies", json=p, headers=throwaway_super_admin["headers"])
        assert r1.status_code == 200, r1.text
        p2 = dict(p, name=f"{TAG} DupCo 2", admin_email=f"dup2_{TAG.lower()}@example.com")
        r2 = http.post(f"{API}/companies", json=p2, headers=throwaway_super_admin["headers"])
        assert r2.status_code == 409, f"expected 409, got {r2.status_code} {r2.text}"

    def test_create_company_without_admin_phone_no_admin(self, http, mongo, throwaway_super_admin):
        p = {
            "name": f"{TAG} NoAdminCo",
            "address": "NoAdmin Ave",
            "office_lat": 28.6,
            "office_lng": 77.2,
        }
        r = http.post(f"{API}/companies", json=p, headers=throwaway_super_admin["headers"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "admin" not in data
        assert data.get("company_id")
        # No company_admin user should exist for this company
        u = mongo.users.find_one({"company_id": data["company_id"], "role": "company_admin"})
        assert u is None
