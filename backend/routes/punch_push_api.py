"""Iter 561 (user spec) — SECURE PUNCHING DATA PUSH API (B2B).

Vendor-facing endpoint:
  * POST /api/v1/punching — external company systems push machine punches
    (JSON). Protected by: HTTPS check, per-client IP whitelist, Bearer
    API-key auth, HMAC-SHA256 request signing, timestamp window (replay
    protection), unique Request-ID check, per-client rate limiting,
    configurable batch limits, strict field validation and duplicate
    machine_transaction_id protection. Full audit logging.

Admin module (Super Admin only):
  * /api/admin/punch-api/clients        — API Integration Master CRUD.
  * /api/admin/punch-api/logs           — API request logs with filters.
  * /api/admin/punch-api/docs           — vendor integration document.

Security: this module NEVER exposes salary/PF/PAN/bank or any read
access — the vendor can only POST punches. Secrets are shown ONCE at
generation; only SHA-256 hashes of the API key are stored for auth and
the HMAC secret is kept server-side, never returned again.
"""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import re
import secrets as pysecrets
import time as time_mod
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from server import db, get_user_from_token, now_iso, require_role  # noqa: E402

router = APIRouter(tags=["punch-push-api"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")
_TS_WINDOW_SEC = 300          # ±5 minutes
_DEFAULT_BATCH = 1000
_DEFAULT_RATE = 60            # requests / minute
_rate_mem: Dict[str, List[float]] = {}   # client_id -> request epochs
_idx_ready = False


async def _ensure_indexes() -> None:
    global _idx_ready
    if _idx_ready:
        return
    await db.api_punch_txns.create_index(
        [("company_code", 1), ("machine_code", 1),
         ("machine_transaction_id", 1)], unique=True)
    await db.api_request_ids.create_index("request_id", unique=True)
    await db.api_request_ids.create_index("created_epoch",
                                          expireAfterSeconds=86400)
    await db.api_request_logs.create_index([("at", -1)])
    _idx_ready = True


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _err(status: int, code: str, message: str,
         errors: Optional[list] = None) -> JSONResponse:
    body: Dict[str, Any] = {"status": "error", "code": code,
                            "message": message}
    if errors:
        body["errors"] = errors
    return JSONResponse(status_code=status, content=body)


def _client_ip(request: Request) -> str:
    xf = request.headers.get("x-forwarded-for") or ""
    if xf:
        return xf.split(",")[0].strip()
    return request.client.host if request.client else ""


async def _log(client: Optional[dict], request: Request, request_id: str,
               received: int, accepted: int, duplicate: int, failed: int,
               http_status: int, ms: float, error: str = "",
               sec_fail: str = "") -> None:
    try:
        await db.api_request_logs.insert_one({
            "log_id": f"apl_{uuid.uuid4().hex[:10]}",
            "at": now_iso(),
            "client_id": (client or {}).get("client_id") or
                         request.headers.get("x-client-id") or "",
            "company_code": (client or {}).get("company_code") or "",
            "company_id": (client or {}).get("company_id") or "",
            "request_id": request_id,
            "source_ip": _client_ip(request),
            "endpoint": "/api/v1/punching",
            "method": "POST",
            "received": received, "accepted": accepted,
            "duplicate": duplicate, "failed": failed,
            "http_status": http_status,
            "processing_ms": round(ms, 1),
            "error": error,
            "security_failure": sec_fail,
        })
        upd = {"last_request_at": now_iso()}
        if http_status == 200:
            upd["last_success_at"] = now_iso()
        else:
            upd["last_failed_at"] = now_iso()
        if client:
            await db.api_clients.update_one(
                {"client_id": client["client_id"]}, {"$set": upd})
        if sec_fail:
            await _maybe_security_alert(client, request, sec_fail)
    except Exception:
        pass


_ALERT_THRESHOLD = 5          # failures within window → alert
_ALERT_WINDOW_MIN = 15
_ALERT_COOLDOWN_MIN = 60      # max 1 email per client per hour


async def _maybe_security_alert(client: Optional[dict], request: Request,
                                sec_fail: str) -> None:
    """Iter 563 (user-accepted improvement) — email the super admin when
    a client (or unknown caller) accumulates repeated security failures
    (bad signature, blocked IP, wrong key…) so intrusion attempts are
    flagged immediately. Max one alert per client per hour."""
    try:
        cid = (client or {}).get("client_id") or \
            request.headers.get("x-client-id") or "UNKNOWN"
        window_start = datetime.now(timezone.utc)
        from datetime import timedelta as _td
        since = (window_start - _td(minutes=_ALERT_WINDOW_MIN)).isoformat()
        n = await db.api_request_logs.count_documents({
            "client_id": cid, "security_failure": {"$nin": ["", None]},
            "at": {"$gte": since}})
        n += 1  # current failure not yet inserted
        threshold = int((client or {}).get("alert_threshold") or _ALERT_THRESHOLD)
        if n < threshold:
            return
        last = await db.api_security_alerts.find_one(
            {"client_id": cid}, sort=[("at", -1)])
        if last and last.get("at", "") > \
                (window_start - _td(minutes=_ALERT_COOLDOWN_MIN)).isoformat():
            return
        to_email = str((client or {}).get("alert_email") or "").strip() or \
            next(iter(__import__("server").SUPER_ADMIN_EMAILS), "")
        ip = _client_ip(request)
        subject = f"⚠ Punching API security alert — {cid} ({n} failures in {_ALERT_WINDOW_MIN} min)"
        text = (f"Punching Data Push API — repeated security failures detected.\n\n"
                f"Client: {cid} ({(client or {}).get('name') or 'unknown'})\n"
                f"Latest failure: {sec_fail}\n"
                f"Failures in last {_ALERT_WINDOW_MIN} min: {n}\n"
                f"Latest source IP: {ip}\n"
                f"Time: {now_iso()}\n\n"
                f"Review: Administration → API Integration → API Logs.\n"
                f"You can Block the client or rotate its credentials from the same screen.")
        from server import _send_email_with_attachments
        res = await _send_email_with_attachments(
            to_email=to_email, subject=subject, text=text,
            html=f"<pre>{text}</pre>", attachments=[])
        await db.api_security_alerts.insert_one({
            "client_id": cid, "at": now_iso(), "failures": n,
            "latest_failure": sec_fail, "source_ip": ip,
            "emailed_to": to_email, "delivered": bool(res.get("delivered")),
            "email_error": res.get("error")})
    except Exception:
        pass


# ────────────────────────────────────────────────────────────────────
#  VENDOR ENDPOINT — POST /api/v1/punching
# ────────────────────────────────────────────────────────────────────
@router.post("/api/v1/punching")
async def push_punching(request: Request):
    t0 = time_mod.time()
    await _ensure_indexes()
    rid = request.headers.get("x-request-id") or ""

    # ── HTTPS only (behind nginx/WAF the proto arrives in this header)
    proto = (request.headers.get("x-forwarded-proto") or "").lower()
    if proto == "http":
        await _log(None, request, rid, 0, 0, 0, 0, 403,
                   (time_mod.time() - t0) * 1000, sec_fail="HTTP_NOT_ALLOWED")
        return _err(403, "HTTPS_REQUIRED", "API is available over HTTPS only")

    # ── Client authentication (Bearer API key + X-Client-ID)
    client_id = (request.headers.get("x-client-id") or "").strip()
    auth = request.headers.get("authorization") or ""
    api_key = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not client_id or not api_key:
        await _log(None, request, rid, 0, 0, 0, 0, 401,
                   (time_mod.time() - t0) * 1000, sec_fail="MISSING_CREDENTIALS")
        return _err(401, "AUTH_FAILED", "Unauthorized API request")
    client = await db.api_clients.find_one({"client_id": client_id})
    if (not client or client.get("status") != "active"
            or client.get("blocked")
            or _sha256(api_key) != client.get("api_key_hash")):
        await _log(client, request, rid, 0, 0, 0, 0, 401,
                   (time_mod.time() - t0) * 1000, sec_fail="AUTH_FAILED")
        return _err(401, "AUTH_FAILED", "Unauthorized API request")
    if client.get("expiry_date"):
        try:
            if datetime.now(timezone.utc).date().isoformat() > str(client["expiry_date"]):
                await _log(client, request, rid, 0, 0, 0, 0, 401,
                           (time_mod.time() - t0) * 1000, sec_fail="EXPIRED")
                return _err(401, "AUTH_FAILED", "API credentials expired")
        except Exception:
            pass

    # ── IP whitelist
    ip = _client_ip(request)
    allowed = [str(x).strip() for x in (client.get("allowed_ips") or []) if str(x).strip()]
    if allowed and ip not in allowed:
        await _log(client, request, rid, 0, 0, 0, 0, 403,
                   (time_mod.time() - t0) * 1000, sec_fail=f"IP_NOT_ALLOWED:{ip}")
        return _err(403, "IP_NOT_ALLOWED", "Request IP is not authorized")

    # ── Rate limiting (per client, per minute)
    limit = int(client.get("rate_limit") or _DEFAULT_RATE)
    now = time_mod.time()
    hits = [t for t in _rate_mem.get(client_id, []) if now - t < 60]
    if len(hits) >= limit:
        _rate_mem[client_id] = hits
        await _log(client, request, rid, 0, 0, 0, 0, 429,
                   (time_mod.time() - t0) * 1000, sec_fail="RATE_LIMIT")
        return _err(429, "RATE_LIMIT_EXCEEDED", "Too many API requests")
    hits.append(now)
    _rate_mem[client_id] = hits

    # ── Timestamp window + HMAC signature + replay protection
    ts_raw = (request.headers.get("x-timestamp") or "").strip()
    sig = (request.headers.get("x-signature") or "").strip().lower()
    if not ts_raw or not rid or not sig:
        await _log(client, request, rid, 0, 0, 0, 0, 401,
                   (time_mod.time() - t0) * 1000, sec_fail="MISSING_SIGNATURE_HEADERS")
        return _err(401, "AUTH_FAILED",
                    "X-Timestamp, X-Request-ID and X-Signature headers required")
    try:
        ts = float(ts_raw)
    except ValueError:
        await _log(client, request, rid, 0, 0, 0, 0, 401,
                   (time_mod.time() - t0) * 1000, sec_fail="BAD_TIMESTAMP")
        return _err(401, "AUTH_FAILED", "Invalid X-Timestamp (unix epoch seconds)")
    if abs(now - ts) > _TS_WINDOW_SEC:
        await _log(client, request, rid, 0, 0, 0, 0, 401,
                   (time_mod.time() - t0) * 1000, sec_fail="TIMESTAMP_EXPIRED")
        return _err(401, "AUTH_FAILED", "Request timestamp outside allowed window")
    body_bytes = await request.body()
    if len(body_bytes) > int(client.get("max_request_bytes") or 2_000_000):
        await _log(client, request, rid, 0, 0, 0, 0, 413,
                   (time_mod.time() - t0) * 1000, sec_fail="BODY_TOO_LARGE")
        return _err(413, "REQUEST_TOO_LARGE", "Request body exceeds allowed size")
    expect = hmac_mod.new(
        str(client.get("secret_key") or "").encode(),
        f"{client_id}\n{ts_raw}\n{rid}\n{hashlib.sha256(body_bytes).hexdigest()}".encode(),
        hashlib.sha256).hexdigest()
    if not hmac_mod.compare_digest(expect, sig):
        await _log(client, request, rid, 0, 0, 0, 0, 401,
                   (time_mod.time() - t0) * 1000, sec_fail="BAD_SIGNATURE")
        return _err(401, "AUTH_FAILED", "Invalid HMAC signature")
    try:  # replay protection — request_id must be unique (24 h TTL)
        await db.api_request_ids.insert_one({
            "request_id": rid, "client_id": client_id,
            "created_epoch": datetime.now(timezone.utc)})
    except Exception:
        await _log(client, request, rid, 0, 0, 0, 0, 401,
                   (time_mod.time() - t0) * 1000, sec_fail="REPLAY_REQUEST_ID")
        return _err(401, "AUTH_FAILED", "Duplicate X-Request-ID (replay rejected)")

    # ── JSON parse
    import json as json_mod
    try:
        payload = json_mod.loads(body_bytes.decode("utf-8"))
        assert isinstance(payload, dict)
    except Exception:
        await _log(client, request, rid, 0, 0, 0, 0, 400,
                   (time_mod.time() - t0) * 1000, error="INVALID_JSON")
        return _err(400, "INVALID_JSON", "Invalid JSON request format")

    # ── Company / machine validation
    if str(payload.get("company_code") or "").strip() != client.get("company_code"):
        await _log(client, request, rid, 0, 0, 0, 0, 422,
                   (time_mod.time() - t0) * 1000, error="COMPANY_MISMATCH")
        return _err(422, "VALIDATION_ERROR", "Invalid punching data", [
            {"field": "company_code",
             "message": "company_code does not match this API client"}])
    machine_code = str(payload.get("machine_code") or "").strip()
    allowed_machines = [str(m).strip() for m in
                        (client.get("machine_codes") or []) if str(m).strip()]
    if not machine_code or (allowed_machines and machine_code not in allowed_machines):
        await _log(client, request, rid, 0, 0, 0, 0, 422,
                   (time_mod.time() - t0) * 1000, error="MACHINE_INVALID")
        return _err(422, "VALIDATION_ERROR", "Invalid punching data", [
            {"field": "machine_code",
             "message": "machine_code missing or not registered for this company"}])

    punches = payload.get("punches")
    if not isinstance(punches, list) or not punches:
        await _log(client, request, rid, 0, 0, 0, 0, 422,
                   (time_mod.time() - t0) * 1000, error="NO_PUNCHES")
        return _err(422, "VALIDATION_ERROR", "Invalid punching data", [
            {"field": "punches", "message": "punches must be a non-empty array"}])
    max_batch = int(client.get("max_batch") or _DEFAULT_BATCH)
    if len(punches) > max_batch:
        await _log(client, request, rid, len(punches), 0, 0, len(punches), 422,
                   (time_mod.time() - t0) * 1000, error="BATCH_TOO_LARGE")
        return _err(422, "VALIDATION_ERROR", "Invalid punching data", [
            {"field": "punches",
             "message": f"Batch exceeds the configured maximum of {max_batch}"}])

    # ── Employee master of the mapped firm (match by employee_code/bio)
    company_id = client.get("company_id") or ""
    emps = await db.users.find(
        {"company_id": company_id, "role": "employee"},
        {"_id": 0, "user_id": 1, "employee_code": 1, "bio_code": 1, "name": 1},
    ).to_list(5000)

    def _norm(v: Any) -> str:
        s = str(v if v is not None else "").strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s.lstrip("0") or ("0" if s else "")
    by_code = {_norm(e.get("employee_code")): e for e in emps
               if _norm(e.get("employee_code"))}
    by_bio = {_norm(e.get("bio_code")): e for e in emps
              if _norm(e.get("bio_code"))}

    accepted, duplicate, failed = 0, 0, 0
    errors: List[dict] = []
    att_rows: List[dict] = []
    txn_rows: List[dict] = []
    for i, p in enumerate(punches):
        if not isinstance(p, dict):
            failed += 1
            errors.append({"field": f"punches[{i}]", "message": "Not an object"})
            continue
        ecode = str(p.get("employee_code") or "").strip()
        ename = str(p.get("employee_name") or "").strip()
        pdate = str(p.get("punch_date") or "").strip()
        ptime = str(p.get("punch_time") or "").strip()
        ptype = str(p.get("punch_type") or "").strip().upper()
        txn = str(p.get("machine_transaction_id") or "").strip()
        row_err = None
        if not ecode or not ename:
            row_err = ("employee_code/employee_name", "Required")
        elif not _DATE_RE.match(pdate):
            row_err = ("punch_date", "Invalid date format (YYYY-MM-DD)")
        elif not _TIME_RE.match(ptime):
            row_err = ("punch_time", "Invalid time format (HH:mm:ss)")
        elif ptype not in ("IN", "OUT"):
            row_err = ("punch_type", "Must be IN or OUT")
        elif not txn:
            row_err = ("machine_transaction_id", "Required")
        if row_err is None:
            try:
                datetime.strptime(f"{pdate} {ptime[:8]}",
                                  "%Y-%m-%d %H:%M:%S" if len(ptime) >= 8
                                  else "%Y-%m-%d %H:%M")
            except ValueError:
                row_err = ("punch_date/punch_time", "Invalid date or time value")
        emp = by_code.get(_norm(ecode)) or by_bio.get(_norm(ecode))
        if row_err is None and not emp:
            row_err = ("employee_code",
                       f"Employee {ecode} not found in this company")
        if row_err:
            failed += 1
            errors.append({"field": f"punches[{i}].{row_err[0]}",
                           "message": row_err[1]})
            continue
        hhmm = ptime[:5]
        txn_rows.append({
            "company_code": client["company_code"],
            "machine_code": machine_code,
            "machine_transaction_id": txn,
            "_att": {
                "record_id": f"att_{uuid.uuid4().hex[:12]}",
                "user_id": emp["user_id"],
                "company_id": company_id,
                "date": pdate,
                "kind": "in" if ptype == "IN" else "out",
                "at": f"{pdate}T{hhmm}:00Z",
                "source": "vendor_api",
                "status": "approved",
                "device_serial": machine_code,
                "machine_transaction_id": txn,
                "api_client_id": client_id,
                "api_request_id": rid,
                "api_source_ip": ip,
                "api_employee_name": ename,
                "received_at": now_iso(),
                "created_at": now_iso(),
            },
        })

    # ── Duplicate machine_transaction_id protection (unique index)
    # Iter 583 — plus configurable time-window duplicate detection: a punch
    # within the firm's dedup window of an existing punch is stored but
    # marked "duplicate" (never counted, raw kept).
    try:
        _co_pol = await db.companies.find_one(
            {"company_id": company_id},
            {"_id": 0, "attendance_policy.dedup_window_minutes": 1}) or {}
        _dedup_min = int((_co_pol.get("attendance_policy") or {}).get("dedup_window_minutes", 5))
    except (TypeError, ValueError):
        _dedup_min = 5
    for t in txn_rows:
        att = t.pop("_att")
        try:
            await db.api_punch_txns.insert_one({
                **t, "record_id": att["record_id"], "client_id": client_id,
                "created_at": now_iso()})
        except Exception:
            duplicate += 1
            continue
        if _dedup_min > 0:
            try:
                _at_dt = datetime.strptime(att["at"], "%Y-%m-%dT%H:%M:%SZ")
                _dup = await db.attendance.find_one({
                    "user_id": att["user_id"],
                    "at": {"$gte": (_at_dt - timedelta(minutes=_dedup_min)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "$lte": (_at_dt + timedelta(minutes=_dedup_min)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                    "status": {"$in": ["approved", "pending", "held", "blocked"]},
                }, {"_id": 1})
                if _dup:
                    att["status"] = "duplicate"
                    att["duplicate_reason"] = f"within_{_dedup_min}min"
                    duplicate += 1
            except Exception:
                pass
        att_rows.append(att)
        accepted += 1
    if att_rows:
        # Iter 581 — central onboarding eligibility engine (HELD/BLOCKED).
        try:
            from shared.attendance_eligibility import bulk_apply as _elig_bulk
            await _elig_bulk(db, company_id, att_rows)
        except Exception:
            pass
        await db.attendance.insert_many(att_rows)

    resp = {
        "status": "success",
        "message": "Punching data received successfully",
        "company_code": client["company_code"],
        "request_id": rid,
        "received_count": len(punches),
        "accepted_count": accepted,
        "duplicate_count": duplicate,
        "failed_count": failed,
    }
    if errors:
        resp["errors"] = errors[:50]
    await _log(client, request, rid, len(punches), accepted, duplicate,
               failed, 200, (time_mod.time() - t0) * 1000,
               error="; ".join(f"{e['field']}: {e['message']}"
                               for e in errors[:5]))
    return resp


# ────────────────────────────────────────────────────────────────────
#  ADMIN — API INTEGRATION MASTER (Super Admin only)
# ────────────────────────────────────────────────────────────────────
async def _admin(authorization: Optional[str]):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    return admin


def _pub(c: dict) -> dict:
    """Public view — NEVER return secret_key / api_key hash."""
    return {k: v for k, v in c.items()
            if k not in ("_id", "secret_key", "api_key_hash")}


@router.get("/api/admin/punch-api/clients")
async def list_clients(authorization: Optional[str] = Header(None)):
    await _admin(authorization)
    docs = await db.api_clients.find({}).sort("created_at", -1).to_list(200)
    return {"clients": [_pub(c) for c in docs]}


@router.post("/api/admin/punch-api/clients")
async def create_client(payload: Dict[str, Any] = Body(...),
                        authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    company_id = str(payload.get("company_id") or "").strip()
    company_code = str(payload.get("company_code") or "").strip().upper()
    name = str(payload.get("name") or "").strip()
    if not company_id or not company_code or not name:
        raise HTTPException(status_code=400,
                            detail="company_id, company_code and name required")
    if await db.api_clients.find_one({"company_code": company_code}):
        raise HTTPException(status_code=400,
                            detail="An API client with this Company Code already exists")
    api_key = f"pk_{pysecrets.token_hex(24)}"
    secret = f"sk_{pysecrets.token_hex(32)}"
    client = {
        "client_id": f"CL{pysecrets.token_hex(4).upper()}",
        "name": name,
        "company_id": company_id,
        "company_code": company_code,
        "integration_type": "punching_push",
        "environment": str(payload.get("environment") or "production"),
        "api_version": "v1",
        "api_key_hash": _sha256(api_key),
        "secret_key": secret,
        "allowed_ips": [str(x).strip() for x in
                        (payload.get("allowed_ips") or []) if str(x).strip()],
        "machine_codes": [str(x).strip() for x in
                          (payload.get("machine_codes") or []) if str(x).strip()],
        "max_batch": int(payload.get("max_batch") or _DEFAULT_BATCH),
        "rate_limit": int(payload.get("rate_limit") or _DEFAULT_RATE),
        "status": "active",
        "blocked": False,
        "created_at": now_iso(),
        "created_by": admin.get("user_id"),
        "expiry_date": str(payload.get("expiry_date") or "") or None,
    }
    await db.api_clients.insert_one(dict(client))
    # Credentials returned ONCE — never retrievable again.
    return {"ok": True, "client": _pub(client),
            "credentials": {"client_id": client["client_id"],
                            "api_key": api_key, "secret_key": secret}}


@router.patch("/api/admin/punch-api/clients/{client_id}")
async def update_client(client_id: str, payload: Dict[str, Any] = Body(...),
                        authorization: Optional[str] = Header(None)):
    await _admin(authorization)
    c = await db.api_clients.find_one({"client_id": client_id})
    if not c:
        raise HTTPException(status_code=404, detail="API client not found")
    upd: Dict[str, Any] = {}
    for k in ("name", "status", "blocked", "expiry_date", "environment",
              "alert_email"):
        if k in payload:
            upd[k] = payload[k]
    for k in ("max_batch", "rate_limit"):
        if k in payload:
            upd[k] = int(payload[k] or 0) or (
                _DEFAULT_BATCH if k == "max_batch" else _DEFAULT_RATE)
    if "alert_threshold" in payload:
        upd["alert_threshold"] = max(int(payload["alert_threshold"] or 0), 0) \
            or _ALERT_THRESHOLD
    for k in ("allowed_ips", "machine_codes"):
        if k in payload and isinstance(payload[k], list):
            upd[k] = [str(x).strip() for x in payload[k] if str(x).strip()]
    if not upd:
        raise HTTPException(status_code=400, detail="Nothing to update")
    upd["updated_at"] = now_iso()
    await db.api_clients.update_one({"client_id": client_id}, {"$set": upd})
    c.update(upd)
    return {"ok": True, "client": _pub(c)}


@router.post("/api/admin/punch-api/clients/{client_id}/rotate")
async def rotate_credentials(client_id: str,
                             payload: Dict[str, Any] = Body(default={}),
                             authorization: Optional[str] = Header(None)):
    """Regenerate API key and/or secret (what={key|secret|both})."""
    await _admin(authorization)
    c = await db.api_clients.find_one({"client_id": client_id})
    if not c:
        raise HTTPException(status_code=404, detail="API client not found")
    what = str(payload.get("what") or "both")
    out: Dict[str, str] = {"client_id": client_id}
    upd: Dict[str, Any] = {"rotated_at": now_iso()}
    if what in ("key", "both"):
        api_key = f"pk_{pysecrets.token_hex(24)}"
        upd["api_key_hash"] = _sha256(api_key)
        out["api_key"] = api_key
    if what in ("secret", "both"):
        secret = f"sk_{pysecrets.token_hex(32)}"
        upd["secret_key"] = secret
        out["secret_key"] = secret
    await db.api_clients.update_one({"client_id": client_id}, {"$set": upd})
    return {"ok": True, "credentials": out}


@router.delete("/api/admin/punch-api/clients/{client_id}")
async def delete_client(client_id: str,
                        authorization: Optional[str] = Header(None)):
    await _admin(authorization)
    r = await db.api_clients.delete_one({"client_id": client_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="API client not found")
    return {"ok": True}


@router.get("/api/admin/punch-api/logs")
async def api_logs(company_code: Optional[str] = Query(None),
                   client_id: Optional[str] = Query(None),
                   from_date: Optional[str] = Query(None),
                   to_date: Optional[str] = Query(None),
                   status: Optional[str] = Query(None),
                   ip: Optional[str] = Query(None),
                   request_id: Optional[str] = Query(None),
                   limit: int = Query(200, ge=1, le=1000),
                   authorization: Optional[str] = Header(None)):
    await _admin(authorization)
    q: Dict[str, Any] = {}
    if company_code:
        q["company_code"] = company_code
    if client_id:
        q["client_id"] = client_id
    if ip:
        q["source_ip"] = ip
    if request_id:
        q["request_id"] = request_id
    if status == "success":
        q["http_status"] = 200
    elif status == "failed":
        q["http_status"] = {"$ne": 200}
    if from_date:
        q["at"] = {"$gte": from_date}
    if to_date:
        q.setdefault("at", {})
        q["at"]["$lte"] = to_date + "T23:59:59"
    docs = await db.api_request_logs.find(q, {"_id": 0}) \
        .sort("at", -1).to_list(limit)
    return {"logs": docs}


@router.post("/api/admin/punch-api/clients/{client_id}/test-console")
async def test_console(client_id: str, payload: Dict[str, Any] = Body(...),
                       authorization: Optional[str] = Header(None)):
    """Iter 562 (user-accepted improvement) — generate a READY-SIGNED
    sample request (curl + Python) with the client's real credentials,
    and optionally fire it live against /api/v1/punching (send_now)."""
    await _admin(authorization)
    c = await db.api_clients.find_one({"client_id": client_id})
    if not c:
        raise HTTPException(status_code=404, detail="API client not found")
    api_key = str(payload.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400,
                            detail="Paste the client's API Key (you saved it at generation)")
    if _sha256(api_key) != c.get("api_key_hash"):
        raise HTTPException(status_code=400,
                            detail="This API Key does not match the client (was it rotated?)")
    import json as json_mod
    body = {
        "company_code": c["company_code"],
        "machine_code": str(payload.get("machine_code") or
                            (c.get("machine_codes") or ["BIO001"])[0]),
        "punches": [{
            "employee_code": str(payload.get("employee_code") or "EMP001"),
            "employee_name": str(payload.get("employee_name") or "Test Employee"),
            "punch_date": str(payload.get("punch_date") or
                              datetime.now(timezone.utc).date().isoformat()),
            "punch_time": str(payload.get("punch_time") or "09:05:22"),
            "punch_type": str(payload.get("punch_type") or "IN").upper(),
            "machine_transaction_id": str(payload.get("machine_transaction_id")
                                          or f"TXN{int(time_mod.time())}"),
        }],
    }
    raw = json_mod.dumps(body, separators=(",", ":")).encode()
    ts = str(int(time_mod.time()))
    rid = f"REQ-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{pysecrets.token_hex(3).upper()}"
    msg = f"{client_id}\n{ts}\n{rid}\n{hashlib.sha256(raw).hexdigest()}"
    sig = hmac_mod.new(str(c.get("secret_key") or "").encode(), msg.encode(),
                       hashlib.sha256).hexdigest()
    url = str(payload.get("base_url") or "https://<your-domain>") + "/api/v1/punching"
    body_str = raw.decode()
    curl = (f"curl -X POST '{url}' \\\n"
            f"  -H 'Content-Type: application/json' \\\n"
            f"  -H 'Authorization: Bearer {api_key}' \\\n"
            f"  -H 'X-Client-ID: {client_id}' \\\n"
            f"  -H 'X-Timestamp: {ts}' \\\n"
            f"  -H 'X-Request-ID: {rid}' \\\n"
            f"  -H 'X-Signature: {sig}' \\\n"
            f"  -d '{body_str}'")
    python_code = f'''import hashlib, hmac, json, time, uuid, requests

CLIENT_ID = "{client_id}"
API_KEY = "{api_key}"
SECRET_KEY = "<your secret key>"
URL = "{url}"

body = {json_mod.dumps(body, indent=2)}
raw = json.dumps(body, separators=(",", ":")).encode()
ts = str(int(time.time()))
rid = f"REQ-{{uuid.uuid4().hex[:12].upper()}}"
msg = f"{{CLIENT_ID}}\\n{{ts}}\\n{{rid}}\\n{{hashlib.sha256(raw).hexdigest()}}"
sig = hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()
r = requests.post(URL, data=raw, headers={{
    "Content-Type": "application/json",
    "Authorization": f"Bearer {{API_KEY}}",
    "X-Client-ID": CLIENT_ID, "X-Timestamp": ts,
    "X-Request-ID": rid, "X-Signature": sig}})
print(r.status_code, r.json())'''
    out: Dict[str, Any] = {
        "ok": True, "curl": curl, "python": python_code,
        "note": ("The signed curl is valid for ±5 minutes only "
                 "(timestamp window). The Python snippet signs fresh "
                 "requests — insert the Secret Key you saved."),
    }
    if payload.get("send_now"):
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as cli:
                r = await cli.post(
                    "http://localhost:8001/api/v1/punching", content=raw,
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {api_key}",
                             "X-Client-ID": client_id, "X-Timestamp": ts,
                             "X-Request-ID": rid, "X-Signature": sig})
                out["live_status"] = r.status_code
                out["live_response"] = r.json()
        except Exception as e:
            out["live_status"] = 0
            out["live_response"] = {"error": str(e)}
    return out


@router.get("/api/admin/punch-api/docs")
async def vendor_docs(request: Request,
                      base_url: Optional[str] = Query(None),
                      authorization: Optional[str] = Header(None)):
    """Vendor integration document (markdown) — share with the client.
    Iter 564 (user request) — includes the REAL portal URL so the vendor
    gets the exact endpoint, derived from the request host."""
    await _admin(authorization)
    base = (base_url or "").strip().rstrip("/")
    if not base:
        host = request.headers.get("x-forwarded-host") or \
            request.headers.get("host") or "<your-domain>"
        proto = request.headers.get("x-forwarded-proto") or "https"
        base = f"{proto}://{host}"
    endpoint = f"{base}/api/v1/punching"
    md = f"""# Punching Data Push API — Integration Guide (v1)

## Endpoint
`POST {endpoint}`   (HTTPS only)
UAT: use the UAT credentials/domain issued to you — UAT and Production
credentials, IP whitelists and data are completely separate.

## Required Headers
| Header | Value |
|---|---|
| Content-Type | application/json |
| Authorization | Bearer <API_KEY> |
| X-Client-ID | Your Client ID (e.g. CL1A2B3C4D) |
| X-Timestamp | Unix epoch seconds (must be within ±5 min of server time) |
| X-Request-ID | Unique ID per request (e.g. REQ-20260813-00001). Reuse is rejected (replay protection). |
| X-Signature | HMAC-SHA256 signature (see below) |

## HMAC Signature
```
string_to_sign = CLIENT_ID + "\\n" + X_TIMESTAMP + "\\n" + X_REQUEST_ID
               + "\\n" + SHA256_HEX(raw_request_body)
X-Signature   = HMAC_SHA256_HEX(SECRET_KEY, string_to_sign)
```

## Request Body
```json
{{
  "company_code": "SANGAM001",
  "machine_code": "BIO001",
  "punches": [
    {{
      "employee_code": "EMP001",
      "employee_name": "Rahul Sharma",
      "punch_date": "2026-08-13",
      "punch_time": "09:05:22",
      "punch_type": "IN",
      "machine_transaction_id": "TXN10001"
    }}
  ]
}}
```
All fields are required. `punch_date` = YYYY-MM-DD, `punch_time` =
HH:mm:ss (24-hour), `punch_type` = IN | OUT.
`machine_transaction_id` must be UNIQUE per machine — the same
transaction sent again is counted as duplicate, never inserted twice.
Max punches per request: as configured for your client (default {_DEFAULT_BATCH}).
Rate limit: as configured (default {_DEFAULT_RATE} requests/minute).

## Success Response (HTTP 200)
```json
{{
  "status": "success",
  "message": "Punching data received successfully",
  "company_code": "SANGAM001",
  "request_id": "REQ-20260813-00001",
  "received_count": 2,
  "accepted_count": 2,
  "duplicate_count": 0,
  "failed_count": 0
}}
```

## Error Responses
| HTTP | code | Meaning |
|---|---|---|
| 401 | AUTH_FAILED | Bad/missing credentials, signature, timestamp or reused Request-ID |
| 403 | IP_NOT_ALLOWED | Request IP not whitelisted |
| 403 | HTTPS_REQUIRED | Plain HTTP rejected |
| 400 | INVALID_JSON | Body is not valid JSON |
| 413 | REQUEST_TOO_LARGE | Body exceeds size limit |
| 422 | VALIDATION_ERROR | Field errors (per-field list in `errors`) |
| 429 | RATE_LIMIT_EXCEEDED | Too many requests |

## Security Notes
- Keep the SECRET KEY private; it is never sent over the wire.
- The API accepts punch data POST only — no read access of any kind.
- All requests are logged (IP, request-id, counts, failures).
"""
    return {"markdown": md, "endpoint": endpoint}
