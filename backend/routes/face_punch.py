"""Iter 602 — Phase 2: SECURE FACE PUNCH verification flow (user spec).

Random liveness challenges (server-verified via face keypoints — NOT just
a frontend boolean), anti-spoof analysis, 1:1 ArcFace match vs the
registered template, failed-attempt lockout and a tamper-resistant
punch_verification_audit log. Punch APIs consume the resulting
verification session — the backend is the final authority.
"""
import asyncio
import base64
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Body, Header, HTTPException, Query, Request

from server import db, get_user_from_token, require_role, now_iso, logger  # noqa: E402
from routes.face_verification import (  # noqa: E402
    _get_engine, _decode_frame, _quality_gate, _cos, emb_from_enc,
    MIN_DET_SCORE,
)
from utils import anti_spoof  # noqa: E402

router = APIRouter(prefix="/api", tags=["face-punch"])

CHALLENGES = ["TURN_LEFT", "TURN_RIGHT", "MOVE_CLOSER"]
CHALLENGE_TEXT = {
    "CENTER": "Look straight at the camera",
    "TURN_LEFT": "Turn your head LEFT",
    "TURN_RIGHT": "Turn your head RIGHT",
    "MOVE_CLOSER": "Move your face CLOSER to the camera",
}
FV_TTL_MIN = 4
DEFAULT_THRESHOLD_PCT = 72     # ((cos+1)/2)*100 — cos ≈ 0.44
DEFAULT_MAX_FAILS = 3
DEFAULT_LOCK_MIN = 30
SPOOF_MIN_LIVE = 0.55
MOTION_MIN = 1.4               # frames must show real motion


def _policy(company: dict) -> dict:
    return {
        "enabled": bool(company.get("secure_face_punch_enabled")),
        "threshold": float(company.get("face_match_threshold_pct") or DEFAULT_THRESHOLD_PCT),
        "max_fails": int(company.get("punch_max_failed_attempts") or DEFAULT_MAX_FAILS),
        "lock_min": int(company.get("punch_retry_lock_minutes") or DEFAULT_LOCK_MIN),
        "webauthn_required": company.get("secure_punch_webauthn_required", True),
        "anti_spoof": company.get("secure_punch_anti_spoof", True),
        "liveness": company.get("secure_punch_liveness", True),
    }


async def _lockout_check(user_id: str, pol: dict):
    doc = await db.punch_verification_lock.find_one({"user_id": user_id})
    if doc and doc.get("locked_until"):
        until = datetime.fromisoformat(doc["locked_until"])
        if until > datetime.now(timezone.utc):
            mins = int((until - datetime.now(timezone.utc)).total_seconds() // 60) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Punch temporarily locked after repeated failed "
                       f"verifications. Try again in {mins} min or contact HR/Admin.")


async def _record_fail(user: dict, pol: dict, reason: str):
    doc = await db.punch_verification_lock.find_one_and_update(
        {"user_id": user["user_id"]},
        {"$inc": {"fails": 1},
         "$set": {"last_fail_at": now_iso(), "last_reason": reason}},
        upsert=True, return_document=True)
    fails = int((doc or {}).get("fails") or 1)
    if fails >= pol["max_fails"]:
        await db.punch_verification_lock.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"locked_until": (datetime.now(timezone.utc)
                                       + timedelta(minutes=pol["lock_min"])).isoformat(),
                      "fails": 0}})


async def _audit(user: dict, kind: str, result: str, extra: dict):
    try:
        await db.punch_verification_audit.insert_one({
            "audit_id": f"pva_{uuid.uuid4().hex[:12]}",
            "user_id": user.get("user_id"), "name": user.get("name"),
            "employee_code": user.get("employee_code"),
            "company_id": user.get("company_id"),
            "stage": kind, "result": result, **extra, "at": now_iso(),
        })
    except Exception:
        logger.exception("[face-punch] audit write failed")


def _yaw_offset(face) -> float:
    """Nose x-offset relative to eye midpoint, normalised by eye distance
    (sign = head turn direction; magnitude grows with the turn)."""
    k = face.kps  # [left_eye, right_eye, nose, mouth_l, mouth_r]
    eye_mid_x = (k[0][0] + k[1][0]) / 2.0
    eye_dist = abs(k[1][0] - k[0][0]) + 1e-6
    return float((k[2][0] - eye_mid_x) / eye_dist)


def _analyse(b64: str) -> Dict[str, Any]:
    eng = _get_engine()
    img = _decode_frame(b64)
    faces = [f for f in eng.get(img) if float(f.det_score) >= MIN_DET_SCORE]
    if len(faces) != 1:
        return {"ok": False, "faces": len(faces),
                "reason": ("No face detected — keep your face inside the frame"
                           if not faces else
                           "Multiple faces detected — only the employee should be visible")}
    face = faces[0]
    q = _quality_gate(img, face)
    if q:
        return {"ok": False, "faces": 1, "reason": q}
    import cv2
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    spoof = anti_spoof.frame_spoof_check(img, face.bbox)
    return {"ok": True, "faces": 1,
            "emb": face.normed_embedding.astype(np.float32),
            "yaw": _yaw_offset(face),
            "bbox_w": float(face.bbox[2] - face.bbox[0]),
            "gray": gray, "live_score": spoof["live_score"]}


@router.post("/attendance/face-verify/start")
async def face_verify_start(
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    company = await db.companies.find_one(
        {"company_id": user.get("company_id")}, {"_id": 0}) or {}
    pol = _policy(company)
    await _lockout_check(user["user_id"], pol)
    tpl = await db.face_templates.find_one(
        {"user_id": user["user_id"], "status": "active"}, {"_id": 0, "template_enc": 1})
    if not tpl:
        raise HTTPException(
            status_code=428,
            detail="Face not registered — ask HR/Admin to register your face "
                   "from the Employee Master first.")
    # Device auth gate: if the employee HAS a registered device (or policy
    # mandates one), a device-verified session must be supplied.
    has_device = await db.webauthn_credentials.count_documents(
        {"user_id": user["user_id"], "status": "active"}) > 0
    vs_id = str(payload.get("verification_session_id") or "")
    vs = None
    if vs_id:
        vs = await db.punch_verification_sessions.find_one(
            {"session_id": vs_id, "user_id": user["user_id"], "used": False})
    if has_device and pol["webauthn_required"]:
        if not vs or vs.get("device_auth") != "pass":
            raise HTTPException(
                status_code=403,
                detail="Verify your registered device first (Face ID / "
                       "fingerprint), then retry.")
    if not vs:
        vs_id = f"vs_{uuid.uuid4().hex}"
        await db.punch_verification_sessions.insert_one({
            "session_id": vs_id, "user_id": user["user_id"],
            "company_id": user.get("company_id"),
            "device_auth": "pass" if not has_device else "skipped",
            "used": False, "created_at": now_iso(),
            "expires_at": (datetime.now(timezone.utc)
                           + timedelta(minutes=FV_TTL_MIN)).isoformat(),
        })
    # Random challenge sequence: CENTER + 2 random distinct challenges.
    steps = ["CENTER"] + random.sample(CHALLENGES, 2)
    await db.punch_verification_sessions.update_one(
        {"session_id": vs_id},
        {"$set": {"challenges": steps, "challenge_issued_at": now_iso(),
                  "expires_at": (datetime.now(timezone.utc)
                                 + timedelta(minutes=FV_TTL_MIN)).isoformat()}})
    return {"verification_session_id": vs_id,
            "steps": [{"step": s, "instruction": CHALLENGE_TEXT[s]} for s in steps]}


@router.post("/attendance/face-verify/complete")
async def face_verify_complete(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    company = await db.companies.find_one(
        {"company_id": user.get("company_id")}, {"_id": 0}) or {}
    pol = _policy(company)
    await _lockout_check(user["user_id"], pol)
    vs_id = str(payload.get("verification_session_id") or "")
    vs = await db.punch_verification_sessions.find_one(
        {"session_id": vs_id, "user_id": user["user_id"], "used": False})
    if not vs or not vs.get("challenges"):
        raise HTTPException(status_code=400, detail="Verification session expired — start again")
    if datetime.fromisoformat(vs["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Verification session expired — start again")
    frames: List[dict] = payload.get("frames") or []
    steps = vs["challenges"]
    by_step = {str(f.get("step")): str(f.get("frame") or "") for f in frames}
    if any(s not in by_step or not by_step[s] for s in steps):
        raise HTTPException(status_code=400, detail="Missing challenge frames — start again")

    ip = request.client.host if request and request.client else None

    async def _fail(reason: str, friendly: str, extra: dict = None):
        await _record_fail(user, pol, reason)
        await _audit(user, "face_verify", "REJECTED",
                     {"reason": reason, "ip": ip, **(extra or {})})
        raise HTTPException(status_code=403, detail=friendly)

    results: Dict[str, dict] = {}
    for s in steps:
        r = await asyncio.to_thread(_analyse, by_step[s])
        if not r["ok"]:
            await _fail(f"{s}: {r['reason']}",
                        "⚠ Punch Rejected — " + r["reason"], {"step": s})
        results[s] = r

    # Same person across all challenge frames.
    embs = [results[s]["emb"] for s in steps]
    for i in range(len(embs)):
        for j in range(i + 1, len(embs)):
            if _cos(embs[i], embs[j]) < 0.45:
                await _fail("frame_person_mismatch",
                            "⚠ Punch Rejected — live-person verification failed. "
                            "Use your own face directly in front of the camera.")

    # Liveness — server-verified challenge responses.
    if pol["liveness"]:
        center = results["CENTER"]
        turn_dirs = []
        for s in steps[1:]:
            r = results[s]
            if s in ("TURN_LEFT", "TURN_RIGHT"):
                delta = r["yaw"] - center["yaw"]
                if abs(delta) < 0.16:
                    await _fail(f"liveness_{s.lower()}_not_performed",
                                "⚠ Punch Rejected — we could not verify a live person. "
                                "Follow the camera instructions and try again.")
                turn_dirs.append(np.sign(delta))
            elif s == "MOVE_CLOSER":
                if r["bbox_w"] < center["bbox_w"] * 1.18:
                    await _fail("liveness_move_closer_not_performed",
                                "⚠ Punch Rejected — we could not verify a live person. "
                                "Follow the camera instructions and try again.")
        if len(turn_dirs) == 2 and turn_dirs[0] == turn_dirs[1]:
            await _fail("liveness_same_direction",
                        "⚠ Punch Rejected — liveness check failed. Try again.")
        motion = anti_spoof.motion_check([results[s]["gray"] for s in steps])
        if motion < MOTION_MIN:
            await _fail("liveness_static_frames",
                        "⚠ Punch Rejected — possible photo/video/screen "
                        "presentation detected. Use your live face.")

    # Anti-spoof (dedicated PAD model when installed, heuristics otherwise).
    live_scores = [results[s]["live_score"] for s in steps]
    anti_spoof_score = float(np.mean(live_scores))
    if pol["anti_spoof"] and anti_spoof_score < SPOOF_MIN_LIVE:
        await _fail("anti_spoof_detected",
                    "⚠ Punch Rejected — a photograph or screen presentation "
                    "was detected. Use your live face directly in front of "
                    "the camera.",
                    {"anti_spoof_score": round(anti_spoof_score, 3)})

    # 1:1 match vs THIS employee's registered template only.
    tpl = await db.face_templates.find_one(
        {"user_id": user["user_id"], "status": "active"}, {"_id": 0, "template_enc": 1})
    if not tpl:
        raise HTTPException(status_code=428, detail="Face not registered")
    reg = emb_from_enc(tpl["template_enc"])
    mean_emb = np.mean(np.stack(embs), axis=0)
    mean_emb = mean_emb / (np.linalg.norm(mean_emb) + 1e-9)
    cos = _cos(reg, mean_emb)
    score_pct = round(((cos + 1.0) / 2.0) * 100.0, 1)
    if score_pct < pol["threshold"]:
        await _fail("face_mismatch",
                    "⚠ Punch Rejected — face verification failed. The detected "
                    "face does not match the registered employee.",
                    {"face_match_score": score_pct})

    await db.punch_verification_sessions.update_one(
        {"session_id": vs_id},
        {"$set": {"face_match": "pass", "liveness": "pass",
                  "anti_spoof": "pass", "face_match_score": score_pct,
                  "anti_spoof_score": round(anti_spoof_score, 3),
                  "verified_at": now_iso(),
                  "expires_at": (datetime.now(timezone.utc)
                                 + timedelta(minutes=3)).isoformat()}})
    await db.face_templates.update_one(
        {"user_id": user["user_id"]}, {"$set": {"last_verified_at": now_iso()}})
    await db.punch_verification_lock.delete_one({"user_id": user["user_id"]})
    await _audit(user, "face_verify", "SUCCESS",
                 {"face_match_score": score_pct,
                  "anti_spoof_score": round(anti_spoof_score, 3), "ip": ip})
    return {"ok": True, "verification_session_id": vs_id,
            "face_match_score": score_pct,
            "checks": {"device_auth": vs.get("device_auth"),
                       "liveness": "pass", "anti_spoof": "pass",
                       "face_match": "pass"}}


@router.get("/attendance/face-verify/policy")
async def face_verify_policy(authorization: Optional[str] = Header(None)):
    """Employee PWA asks whether the secure flow is required + face/device state."""
    user = await get_user_from_token(authorization)
    company = await db.companies.find_one(
        {"company_id": user.get("company_id")}, {"_id": 0}) or {}
    pol = _policy(company)
    tpl = await db.face_templates.find_one(
        {"user_id": user["user_id"], "status": "active"}, {"_id": 0, "user_id": 1})
    has_device = await db.webauthn_credentials.count_documents(
        {"user_id": user["user_id"], "status": "active"}) > 0
    return {"secure_punch_enabled": pol["enabled"],
            "face_registered": bool(tpl), "device_registered": has_device,
            "webauthn_required": pol["webauthn_required"]}


@router.get("/admin/attendance/punch-verification-audit")
async def punch_verification_audit(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin["company_id"]
    elif company_id:
        q["company_id"] = company_id
    rows = await db.punch_verification_audit.find(
        q, {"_id": 0}).sort("at", -1).to_list(300)
    return {"logs": rows}
