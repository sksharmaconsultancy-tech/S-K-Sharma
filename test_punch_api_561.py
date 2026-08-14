"""E2E test — Secure Punching Data Push API (Iter 561)."""
import hashlib
import hmac
import json
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8001"
TOKEN = open("/tmp/tok.txt").read().strip()


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def push(client_id, api_key, secret, body, rid=None, ts=None, sig=None,
         extra_headers=None):
    raw = json.dumps(body).encode()
    ts = ts or str(time.time())
    rid = rid or f"REQ-{time.time_ns()}"
    if sig is None:
        msg = f"{client_id}\n{ts}\n{rid}\n{hashlib.sha256(raw).hexdigest()}"
        sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        BASE + "/api/v1/punching", data=raw, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}",
                 "X-Client-ID": client_id, "X-Timestamp": ts,
                 "X-Request-ID": rid, "X-Signature": sig,
                 **(extra_headers or {})})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, json.load(r), rid
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode()), rid


AUTH = {"Authorization": f"Bearer {TOKEN}"}
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {name}")
    else:
        fail += 1
        print(f"  FAIL {name} — {detail}")


# 1. create client
st, r = call("POST", "/api/admin/punch-api/clients", {
    "name": "Sangam Farms TEST", "company_id": "cmp_527fecdd7c",
    "company_code": "SANGAM001", "machine_codes": ["BIO001"],
    "max_batch": 5, "rate_limit": 30}, AUTH)
check("create client", st == 200 and r.get("ok"), str(r)[:120])
cid = r["credentials"]["client_id"]
key = r["credentials"]["api_key"]
sec = r["credentials"]["secret_key"]
check("secret not in client object", "secret_key" not in r["client"])

# 2. valid push (MAHAVEER employee_code=123)
body = {"company_code": "SANGAM001", "machine_code": "BIO001", "punches": [
    {"employee_code": "123", "employee_name": "MAHAVEER SINGH",
     "punch_date": "2026-08-14", "punch_time": "09:05:22",
     "punch_type": "IN", "machine_transaction_id": "TXN10001"},
    {"employee_code": "123", "employee_name": "MAHAVEER SINGH",
     "punch_date": "2026-08-14", "punch_time": "18:02:14",
     "punch_type": "OUT", "machine_transaction_id": "TXN10002"}]}
st, r, rid1 = push(cid, key, sec, body)
check("valid push accepted 2", st == 200 and r["accepted_count"] == 2
      and r["duplicate_count"] == 0, str(r)[:160])

# 3. duplicate transaction protection (re-send same TXNs, new request id)
st, r, _ = push(cid, key, sec, body)
check("duplicates rejected", st == 200 and r["accepted_count"] == 0
      and r["duplicate_count"] == 2, str(r)[:160])

# 4. replay: reuse the SAME request id
st, r, _ = push(cid, key, sec, body, rid=rid1)
check("replay request-id rejected 401", st == 401 and r["code"] == "AUTH_FAILED", str(r)[:120])

# 5. bad signature
st, r, _ = push(cid, key, sec, body, sig="0" * 64)
check("bad HMAC rejected 401", st == 401, str(r)[:120])

# 6. old timestamp
st, r, _ = push(cid, key, sec, body, ts=str(time.time() - 900))
check("stale timestamp rejected 401", st == 401, str(r)[:120])

# 7. wrong api key
st, r, _ = push(cid, "pk_wrong", sec, body)
check("wrong api key 401", st == 401 and r["code"] == "AUTH_FAILED", str(r)[:120])

# 8. validation errors (bad date/time/type, unknown employee)
bad = {"company_code": "SANGAM001", "machine_code": "BIO001", "punches": [
    {"employee_code": "123", "employee_name": "X", "punch_date": "13-08-2026",
     "punch_time": "09:05:22", "punch_type": "IN", "machine_transaction_id": "T1"},
    {"employee_code": "123", "employee_name": "X", "punch_date": "2026-08-14",
     "punch_time": "9:5", "punch_type": "IN", "machine_transaction_id": "T2"},
    {"employee_code": "123", "employee_name": "X", "punch_date": "2026-08-14",
     "punch_time": "09:05:22", "punch_type": "BREAK", "machine_transaction_id": "T3"},
    {"employee_code": "ZZZ9", "employee_name": "X", "punch_date": "2026-08-14",
     "punch_time": "09:05:22", "punch_type": "IN", "machine_transaction_id": "T4"}]}
st, r, _ = push(cid, key, sec, bad)
check("field validation (4 failed)", st == 200 and r["failed_count"] == 4
      and len(r.get("errors", [])) == 4, str(r)[:200])

# 9. wrong machine code
st, r, _ = push(cid, key, sec, {**body, "machine_code": "BIO999"})
check("unknown machine 422", st == 422 and r["code"] == "VALIDATION_ERROR", str(r)[:120])

# 10. wrong company code
st, r, _ = push(cid, key, sec, {**body, "company_code": "OTHER01"})
check("company mismatch 422", st == 422, str(r)[:120])

# 11. batch limit (max 5 configured)
big = {"company_code": "SANGAM001", "machine_code": "BIO001", "punches": [
    {"employee_code": "123", "employee_name": "M", "punch_date": "2026-08-14",
     "punch_time": "09:00:00", "punch_type": "IN",
     "machine_transaction_id": f"B{i}"} for i in range(6)]}
st, r, _ = push(cid, key, sec, big)
check("batch limit 422", st == 422, str(r)[:120])

# 12. IP whitelist — restrict to an IP we don't have
st, r = call("PATCH", f"/api/admin/punch-api/clients/{cid}",
             {"allowed_ips": ["203.0.113.99"]}, AUTH)
st, r, _ = push(cid, key, sec, body)
check("IP not allowed 403", st == 403 and r["code"] == "IP_NOT_ALLOWED", str(r)[:120])
call("PATCH", f"/api/admin/punch-api/clients/{cid}", {"allowed_ips": []}, AUTH)

# 13. block client
call("PATCH", f"/api/admin/punch-api/clients/{cid}", {"blocked": True}, AUTH)
st, r, _ = push(cid, key, sec, body)
check("blocked client 401", st == 401, str(r)[:120])
call("PATCH", f"/api/admin/punch-api/clients/{cid}", {"blocked": False}, AUTH)

# 14. rotate key — old key stops working
st, r = call("POST", f"/api/admin/punch-api/clients/{cid}/rotate", {"what": "key"}, AUTH)
newkey = r["credentials"]["api_key"]
st, r, _ = push(cid, key, sec, body)
check("old key rejected after rotate", st == 401, str(r)[:120])
st, r, _ = push(cid, newkey, sec, {**body, "punches": [
    {"employee_code": "123", "employee_name": "M", "punch_date": "2026-08-14",
     "punch_time": "19:00:00", "punch_type": "IN",
     "machine_transaction_id": "TXN10003"}]})
check("new key works", st == 200 and r["accepted_count"] == 1, str(r)[:160])

# 15. punches actually stored in attendance
import subprocess
out = subprocess.run(["python3", "-c", """
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
async def m():
    db = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ.get('DB_NAME','test_database')]
    n = await db.attendance.count_documents({'source':'vendor_api','date':'2026-08-14'})
    print(n)
asyncio.run(m())"""], capture_output=True, text=True)
check("punches stored in attendance (3)", out.stdout.strip() == "3", out.stdout + out.stderr)

# 16. logs recorded with filters
st, r = call("GET", f"/api/admin/punch-api/logs?client_id={cid}&status=failed", None, AUTH)
check("failed logs recorded", st == 200 and len(r["logs"]) >= 5, str(len(r.get('logs', []))))
st, r = call("GET", f"/api/admin/punch-api/logs?client_id={cid}&status=success", None, AUTH)
check("success logs recorded", st == 200 and len(r["logs"]) >= 2, str(len(r.get('logs', []))))

# 17. docs endpoint
st, r = call("GET", "/api/admin/punch-api/docs", None, AUTH)
check("vendor docs", st == 200 and "HMAC" in r["markdown"])

# cleanup
st, r = call("DELETE", f"/api/admin/punch-api/clients/{cid}", None, AUTH)
check("delete client", st == 200)
subprocess.run(["python3", "-c", """
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
async def m():
    db = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ.get('DB_NAME','test_database')]
    r1 = await db.attendance.delete_many({'source':'vendor_api'})
    r2 = await db.api_punch_txns.delete_many({})
    print('cleanup', r1.deleted_count, r2.deleted_count)
asyncio.run(m())"""])

print(f"\nRESULT: {ok} passed, {fail} failed")
