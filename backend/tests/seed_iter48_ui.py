"""Iter-48 seed for UI tests: create a fresh company + a couple of decided
punches so both super_admin and company_admin can see History content."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import requests

BASE = None
for line in Path("/app/frontend/.env").read_text().splitlines():
    if line.startswith("EXPO_PUBLIC_BACKEND_URL"):
        BASE = line.split("=", 1)[1].strip().strip('"').strip("'").rstrip("/")
        break
assert BASE

SA_EMAIL = "sksharmaconsultancy@gmail.com"
api = requests.Session()
api.headers.update({"Content-Type": "application/json"})


def _otp_login(identifier, channel="email"):
    r = api.post(f"{BASE}/api/auth/otp/request",
                 json={"identifier": identifier, "channel": channel})
    r.raise_for_status()
    code = r.json().get("dev_code") or r.json().get("code")
    r = api.post(f"{BASE}/api/auth/otp/verify",
                 json={"identifier": identifier, "channel": channel, "code": code})
    r.raise_for_status()
    return r.json()


# 1. Super-admin token
sa_body = _otp_login(SA_EMAIL)
sa_token = sa_body["session_token"]
sa_h = {"Authorization": f"Bearer {sa_token}"}

# 2. Create a fresh company
suffix = uuid.uuid4().hex[:6]
phone = f"+91777{uuid.uuid4().int % 10_000_000:07d}"
r = api.post(f"{BASE}/api/companies", json={
    "name": f"TEST_Iter48UI {suffix}",
    "address": "1 UI Test Rd",
    "office_lat": 12.9,
    "office_lng": 77.5,
    "geofence_radius_m": 500,
    "compliance_enabled": True,
    "business_category": "industry",
    "business_subcategory": "Textile",
    "admin_phone": phone,
    "admin_name": "QA Admin",
}, headers=sa_h)
r.raise_for_status()
body = r.json()
cid = body["company_id"]
temp_pin = body["admin"]["temp_pin"]

# 3. Log in as company admin via PIN
rl = api.post(f"{BASE}/api/auth/admin-pin-login",
              json={"identifier": phone, "pin": temp_pin})
rl.raise_for_status()
ca_body = rl.json()
ca_token = ca_body["session_token"]
ca_h = {"Authorization": f"Bearer {ca_token}"}

# handle possible forced PIN change
if ca_body.get("pin_must_change"):
    # set a new PIN
    api.post(f"{BASE}/api/auth/set-pin",
             json={"new_pin": "246810"}, headers=ca_h)

# 4. Create pending punches as the admin, then approve one, reject one
def punch(kind, source, headers):
    return api.post(f"{BASE}/api/attendance/punch", json={
        "kind": kind, "latitude": 12.9, "longitude": 77.5,
        "biometric_method": "fingerprint", "source": source,
    }, headers=headers)

r1 = punch("in", "geofence-auto", ca_h)
r1.raise_for_status()
rid1 = r1.json()["record_id"]
# Approve via super_admin
api.post(f"{BASE}/api/attendance/punches/{rid1}/decision",
         json={"action": "approve"}, headers=sa_h).raise_for_status()

# Age the previous punch so debounce doesn't block the next one
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
from datetime import datetime, timedelta, timezone

async def _age():
    m = AsyncIOMotorClient([ln.split("=",1)[1].strip().strip('"') for ln in Path("/app/backend/.env").read_text().splitlines() if ln.startswith("MONGO_URL=")][0])
    db = m[[ln.split("=",1)[1].strip().strip('"') for ln in Path("/app/backend/.env").read_text().splitlines() if ln.startswith("DB_NAME=")][0]]
    new_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    await db.attendance.update_one({"record_id": rid1}, {"$set": {"at": new_iso, "original_at": new_iso}})
    m.close()
asyncio.run(_age())

r2 = punch("out", "geofence-auto", ca_h)
r2.raise_for_status()
rid2 = r2.json()["record_id"]
# Reject via super_admin
api.post(f"{BASE}/api/attendance/punches/{rid2}/decision",
         json={"action": "reject", "reason": "Test rejection"}, headers=sa_h).raise_for_status()

# Third: leave one pending
rid3 = None  # skip: last non-rejected was IN so we can't create another IN today

seed = {
    "company_id": cid,
    "admin_phone": phone,
    "admin_pin": "246810" if ca_body.get("pin_must_change") else temp_pin,
    "sa_token": sa_token,
    "ca_token": ca_token,
    "rid_approved": rid1,
    "rid_rejected": rid2,
    "rid_pending": rid3,
    "base_url": BASE,
}
Path("/app/test_reports/iter48_ui_seed.json").write_text(json.dumps(seed, indent=2))
print(json.dumps(seed, indent=2))
