"""Iter 601 — Phase 1: FACE VERIFICATION — Enrollment (user spec).

Self-hosted stack (no external API, biometric data stays on the VPS):
  * InsightFace / ArcFace (buffalo_l) — face detection + 512-d embeddings.
  * Server-side quality gates — exactly ONE face, blur (Laplacian),
    brightness, minimum face size.
  * Cross-sample consistency — the 2-3 enrollment samples must be the SAME
    person (pairwise cosine similarity) before a template is stored.
  * Templates are AES-encrypted at rest via utils.secrets_vault and are
    NEVER exposed through employee-facing APIs.
  * Every admin action on biometric records is audit-logged
    (face_admin_audit collection).

HR/Admin-ONLY enrollment (user decision 3a): employees cannot register or
replace their own face. Re-registration replaces + archives the old
template; disable keeps history.

The heavy model loads lazily in a worker thread — server start stays fast.
"""
import asyncio
import base64
import json
import threading
import uuid
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    logger,
)
from utils.secrets_vault import decrypt_secret, encrypt_secret  # noqa: E402

router = APIRouter(prefix="/api", tags=["face-verification"])

FACE_MODEL_PACK = "buffalo_l"
MIN_FACE_PX = 90            # face box must be at least this many pixels wide
MIN_BRIGHTNESS = 40         # mean gray value — reject very dark frames
MAX_BRIGHTNESS = 235        # reject blown-out frames
MIN_BLUR_VAR = 28.0         # Laplacian variance — reject heavy blur
MIN_DET_SCORE = 0.60        # detector confidence
SAMPLE_CONSISTENCY = 0.55   # min cosine sim between enrollment samples

_engine = None
_engine_lock = threading.Lock()
_engine_error: Optional[str] = None


def _get_engine():
    """Lazy-load InsightFace once per process (thread-safe)."""
    global _engine, _engine_error
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        try:
            from insightface.app import FaceAnalysis
            eng = FaceAnalysis(
                name=FACE_MODEL_PACK,
                allowed_modules=["detection", "recognition"],
                providers=["CPUExecutionProvider"],
            )
            eng.prepare(ctx_id=-1, det_size=(640, 640))
            _engine = eng
            logger.info("[face] InsightFace %s ready", FACE_MODEL_PACK)
        except Exception as e:  # model missing / download failed
            _engine_error = str(e)
            logger.exception("[face] engine load failed")
            raise HTTPException(
                status_code=503,
                detail="Face engine not ready on the server — models are "
                       "still downloading or missing. Try again in a minute.")
    return _engine


def _decode_frame(b64: str) -> np.ndarray:
    """base64 (data-url tolerated) → BGR image array."""
    import cv2
    if "," in b64[:80]:
        b64 = b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(b64)
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        img = None
    if img is None:
        raise HTTPException(status_code=400, detail="Unreadable image frame")
    # Cap huge frames to keep CPU inference fast.
    h, w = img.shape[:2]
    if max(h, w) > 1280:
        scale = 1280.0 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
    return img


def _quality_gate(img: np.ndarray, face) -> Optional[str]:
    """Returns a human reason when the frame fails quality checks."""
    import cv2
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
    if (x2 - x1) < MIN_FACE_PX:
        return "Face is too far from the camera — move closer"
    crop = gray[y1:y2, x1:x2]
    if crop.size == 0:
        return "Face is outside the frame — center your face"
    mean_b = float(crop.mean())
    if mean_b < MIN_BRIGHTNESS:
        return "Image too dark — move to a well-lit area"
    if mean_b > MAX_BRIGHTNESS:
        return "Image over-exposed — avoid direct bright light"
    blur = float(cv2.Laplacian(crop, cv2.CV_64F).var())
    if blur < MIN_BLUR_VAR:
        return "Face is blurred — hold the camera steady"
    return None


def _analyse_frame(b64: str) -> Dict[str, Any]:
    """Detect faces + quality on ONE frame. Runs in a worker thread."""
    eng = _get_engine()
    img = _decode_frame(b64)
    faces = [f for f in eng.get(img) if float(f.det_score) >= MIN_DET_SCORE]
    if len(faces) == 0:
        return {"ok": False, "reason": "No face detected — keep your face inside the frame", "faces": 0}
    if len(faces) > 1:
        return {"ok": False, "reason": "Multiple faces detected — only one person should be visible", "faces": len(faces)}
    face = faces[0]
    q = _quality_gate(img, face)
    if q:
        return {"ok": False, "reason": q, "faces": 1}
    emb = face.normed_embedding.astype(np.float32)
    return {"ok": True, "faces": 1, "embedding": emb,
            "det_score": float(face.det_score)}


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _emb_to_enc(emb: np.ndarray) -> str:
    return encrypt_secret(base64.b64encode(emb.astype(np.float32).tobytes()).decode())


def emb_from_enc(enc: str) -> np.ndarray:
    raw = base64.b64decode(decrypt_secret(enc))
    return np.frombuffer(raw, dtype=np.float32)


async def _face_admin_audit(admin: dict, action: str, target_user_id: str,
                            detail: str = "") -> None:
    try:
        await db.face_admin_audit.insert_one({
            "log_id": f"faa_{uuid.uuid4().hex[:12]}",
            "admin_id": admin.get("user_id"),
            "admin_name": admin.get("name"),
            "admin_role": admin.get("role"),
            "action": action,
            "target_user_id": target_user_id,
            "detail": detail,
            "at": now_iso(),
        })
    except Exception:
        logger.exception("[face] audit write failed")


def _require_face_admin(admin: dict) -> None:
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])


async def _target_employee_or_404(admin: dict, user_id: str) -> dict:
    emp = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "user_id": 1, "name": 1, "company_id": 1,
         "employee_code": 1, "disabled": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Employee not in your company")
    return emp


def _status_row(t: Optional[dict]) -> Dict[str, Any]:
    if not t:
        return {"status": "not_registered"}
    return {
        "status": t.get("status") or "active",
        "registered_at": t.get("registered_at"),
        "registered_by_name": t.get("registered_by_name"),
        "samples": t.get("samples"),
        "model": t.get("model"),
        "last_verified_at": t.get("last_verified_at"),
        "disabled_at": t.get("disabled_at"),
    }


@router.get("/admin/face-verification/engine-status")
async def face_engine_status(authorization: Optional[str] = Header(None)):
    """Is the AI engine loaded / loadable? (Admin diagnostics.)"""
    admin = await get_user_from_token(authorization)
    _require_face_admin(admin)
    if _engine is not None:
        return {"ready": True, "model": FACE_MODEL_PACK}
    try:
        await asyncio.to_thread(_get_engine)
        return {"ready": True, "model": FACE_MODEL_PACK}
    except HTTPException as e:
        return {"ready": False, "model": FACE_MODEL_PACK, "error": e.detail,
                "last_error": _engine_error}


@router.get("/admin/face-verification/status")
async def face_status(
    user_id: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    _require_face_admin(admin)
    await _target_employee_or_404(admin, user_id)
    t = await db.face_templates.find_one(
        {"user_id": user_id}, {"_id": 0, "template_enc": 0})
    return {"face": _status_row(t)}


@router.get("/admin/face-verification/list")
async def face_list(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Registration status per employee of a firm (for master columns)."""
    admin = await get_user_from_token(authorization)
    _require_face_admin(admin)
    cid = admin["company_id"] if admin["role"] == "company_admin" else company_id
    q: dict = {}
    if cid:
        q["company_id"] = cid
    rows = {}
    async for t in db.face_templates.find(q, {"_id": 0, "template_enc": 0}):
        rows[t["user_id"]] = _status_row(t)
    return {"faces": rows}


@router.post("/admin/face-verification/check-frame")
async def face_check_frame(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Live guidance during enrollment: analyse ONE camera frame and tell
    the operator what to fix (no face / multiple faces / dark / blur)."""
    admin = await get_user_from_token(authorization)
    _require_face_admin(admin)
    frame = str(payload.get("frame") or "")
    if not frame:
        raise HTTPException(status_code=400, detail="frame required")
    res = await asyncio.to_thread(_analyse_frame, frame)
    return {"ok": res["ok"], "faces": res["faces"],
            "reason": res.get("reason")}


@router.post("/admin/face-verification/enroll")
async def face_enroll(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Register (or RE-register) an employee's face from 2-3 LIVE camera
    samples. Gallery uploads are refused by the frontend; the backend
    additionally requires multi-sample consistency so a single photo can't
    be replayed into different samples verbatim."""
    admin = await get_user_from_token(authorization)
    _require_face_admin(admin)
    user_id = str(payload.get("user_id") or "")
    frames: List[str] = [f for f in (payload.get("frames") or []) if f]
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if len(frames) < 2 or len(frames) > 5:
        raise HTTPException(status_code=400,
                            detail="Provide 2-5 live camera samples")
    emp = await _target_employee_or_404(admin, user_id)

    embs: List[np.ndarray] = []
    for i, f in enumerate(frames):
        res = await asyncio.to_thread(_analyse_frame, f)
        if not res["ok"]:
            raise HTTPException(
                status_code=422,
                detail=f"Sample {i + 1}: {res['reason']}")
        embs.append(res["embedding"])

    # Same-person consistency across samples.
    for i in range(len(embs)):
        for j in range(i + 1, len(embs)):
            if _cos(embs[i], embs[j]) < SAMPLE_CONSISTENCY:
                raise HTTPException(
                    status_code=422,
                    detail="Samples do not match each other — all samples "
                           "must be the SAME person, captured live. Retake.")
    # Identical frames (replayed single photo) are suspicious.
    import hashlib
    if len({hashlib.md5(f.encode()).hexdigest() for f in frames}) < len(frames):
        raise HTTPException(status_code=422,
                            detail="Duplicate frames detected — capture "
                                   "distinct live samples, not copies.")

    mean_emb = np.mean(np.stack(embs), axis=0)
    mean_emb = mean_emb / (np.linalg.norm(mean_emb) + 1e-9)

    old = await db.face_templates.find_one({"user_id": user_id}, {"_id": 0})
    if old:
        await db.face_templates_history.insert_one(
            {**old, "archived_at": now_iso(), "archived_by": admin["user_id"]})
    doc = {
        "user_id": user_id,
        "company_id": emp.get("company_id"),
        "employee_code": emp.get("employee_code"),
        "template_enc": _emb_to_enc(mean_emb),
        "samples": len(frames),
        "model": FACE_MODEL_PACK,
        "status": "active",
        "registered_at": now_iso(),
        "registered_by": admin["user_id"],
        "registered_by_name": admin.get("name"),
        "last_verified_at": None,
        "disabled_at": None,
    }
    await db.face_templates.update_one(
        {"user_id": user_id}, {"$set": doc}, upsert=True)
    await _face_admin_audit(
        admin, "re_enroll" if old else "enroll", user_id,
        f"{len(frames)} live samples, model {FACE_MODEL_PACK}")
    return {"ok": True, "face": _status_row(doc),
            "message": f"Face registered for {emp.get('name')} "
                       f"({len(frames)} live samples) ✓"}


@router.post("/admin/face-verification/disable")
async def face_disable(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    _require_face_admin(admin)
    user_id = str(payload.get("user_id") or "")
    await _target_employee_or_404(admin, user_id)
    r = await db.face_templates.update_one(
        {"user_id": user_id},
        {"$set": {"status": "disabled", "disabled_at": now_iso(),
                  "disabled_by": admin["user_id"]}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="No registered face")
    await _face_admin_audit(admin, "disable", user_id)
    return {"ok": True}


@router.post("/admin/face-verification/enable")
async def face_enable(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    _require_face_admin(admin)
    user_id = str(payload.get("user_id") or "")
    await _target_employee_or_404(admin, user_id)
    r = await db.face_templates.update_one(
        {"user_id": user_id},
        {"$set": {"status": "active", "disabled_at": None}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="No registered face")
    await _face_admin_audit(admin, "enable", user_id)
    return {"ok": True}


# ═════════ Iter 611 — EMPLOYEE SELF-ENROLLMENT with HR APPROVAL ═════════
# Employees capture their own live samples; nothing becomes an ACTIVE
# punch credential until HR/Admin approves. Statuses: pending / approved /
# rejected / recapture_required. Pending previews auto-expire (7 days).

SELF_RETENTION_DAYS = 7


async def _cleanup_pending():
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=SELF_RETENTION_DAYS)).isoformat()
    await db.face_enrollment_requests.update_many(
        {"status": "pending", "submitted_at": {"$lt": cutoff}},
        {"$set": {"status": "expired", "sample_previews": []}})


@router.post("/face-verification/self-check-frame")
async def self_check_frame(payload: Dict[str, Any] = Body(...),
                           authorization: Optional[str] = Header(None)):
    """Employee-side per-frame quality gate (same engine as HR flow)."""
    await get_user_from_token(authorization)
    res = await asyncio.to_thread(_analyse_frame, str(payload.get("frame") or ""))
    return {"ok": res["ok"], "reason": res.get("reason")}


@router.post("/face-verification/self-enroll")
async def self_enroll(payload: Dict[str, Any] = Body(...),
                      authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    if not payload.get("consent"):
        raise HTTPException(status_code=400,
                            detail="Consent is required before enrollment")
    frames: List[str] = [f for f in (payload.get("frames") or []) if f]
    if len(frames) < 3 or len(frames) > 5:
        raise HTTPException(status_code=400, detail="Provide 3-5 live samples")
    embs: List[np.ndarray] = []
    for i, f in enumerate(frames):
        res = await asyncio.to_thread(_analyse_frame, f)
        if not res["ok"]:
            raise HTTPException(status_code=422,
                                detail=f"Sample {i + 1}: {res['reason']}")
        embs.append(res["embedding"])
    for i in range(len(embs)):
        for j in range(i + 1, len(embs)):
            if _cos(embs[i], embs[j]) < SAMPLE_CONSISTENCY:
                raise HTTPException(
                    status_code=422,
                    detail="Face samples could not be verified as belonging "
                           "to the same person. Please recapture.")
    import hashlib as _h
    if len({_h.md5(f.encode()).hexdigest() for f in frames}) < len(frames):
        raise HTTPException(status_code=422,
                            detail="Duplicate frames detected — capture "
                                   "distinct live samples.")
    mean_emb = np.mean(np.stack(embs), axis=0)
    mean_emb = mean_emb / (np.linalg.norm(mean_emb) + 1e-9)
    u = await db.users.find_one(
        {"user_id": user["user_id"]},
        {"_id": 0, "name": 1, "employee_code": 1, "company_id": 1,
         "designation": 1, "department": 1}) or {}
    # Supersede any earlier open request from this employee.
    await db.face_enrollment_requests.update_many(
        {"user_id": user["user_id"], "status": "pending"},
        {"$set": {"status": "superseded", "sample_previews": []}})
    doc = {
        "enrollment_id": f"fen_{uuid.uuid4().hex[:10]}",
        "user_id": user["user_id"], "company_id": u.get("company_id"),
        "employee_code": u.get("employee_code"), "name": u.get("name"),
        "designation": u.get("designation"), "department": u.get("department"),
        "status": "pending", "samples": len(frames),
        "template_enc": _emb_to_enc(mean_emb),
        # First + last frame kept as HR review previews (auto-deleted on
        # decision / after retention days). NOT usable for punching.
        "sample_previews": [frames[0], frames[-1]],
        "consent": True, "submitted_at": now_iso(),
        "is_reenrollment": bool(await db.face_templates.find_one(
            {"user_id": user["user_id"], "status": "active"}, {"_id": 1})),
    }
    await db.face_enrollment_requests.insert_one({**doc})
    await db.face_admin_audit.insert_one({
        "audit_id": f"faud_{uuid.uuid4().hex[:8]}", "action": "self_enroll_submitted",
        "target_user_id": user["user_id"], "by": user["user_id"],
        "detail": f"{len(frames)} live samples (self-service)", "at": now_iso()})
    return {"ok": True, "status": "pending",
            "message": "Face samples submitted — pending HR approval."}


@router.get("/face-verification/self-status")
async def self_status(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    active = await db.face_templates.find_one(
        {"user_id": user["user_id"]}, {"_id": 0, "template_enc": 0})
    req = await db.face_enrollment_requests.find_one(
        {"user_id": user["user_id"],
         "status": {"$in": ["pending", "rejected", "recapture_required"]}},
        {"_id": 0, "template_enc": 0, "sample_previews": 0},
        sort=[("submitted_at", -1)])
    if req and req["status"] == "pending":
        status = "pending"
    elif active and active.get("status") == "active":
        status = "approved"
    elif req:
        status = req["status"]
    else:
        status = "not_registered"
    return {"status": status,
            "active_template": bool(active and active.get("status") == "active"),
            "registered_at": (active or {}).get("registered_at"),
            "request": req}


@router.get("/admin/face-verification/pending")
async def pending_enrollments(company_id: Optional[str] = Query(None),
                              authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    _require_face_admin(admin)
    await _cleanup_pending()
    q: dict = {"status": "pending"}
    cid = admin.get("company_id") or company_id
    if admin.get("role") in ("super_admin", "sub_admin") and company_id:
        cid = company_id
    if cid:
        q["company_id"] = cid
    rows = await db.face_enrollment_requests.find(
        q, {"_id": 0, "template_enc": 0}).sort("submitted_at", -1).to_list(200)
    return {"pending": rows}


@router.post("/admin/face-verification/pending/{enrollment_id}/decide")
async def decide_enrollment(enrollment_id: str,
                            payload: Dict[str, Any] = Body(...),
                            authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    _require_face_admin(admin)
    action = str(payload.get("action") or "")
    if action not in ("approve", "reject", "recapture"):
        raise HTTPException(status_code=400, detail="Invalid action")
    reason = str(payload.get("reason") or "")[:300]
    req = await db.face_enrollment_requests.find_one(
        {"enrollment_id": enrollment_id, "status": "pending"})
    if not req:
        raise HTTPException(status_code=404, detail="Pending enrollment not found")
    if action == "approve":
        old = await db.face_templates.find_one({"user_id": req["user_id"]}, {"_id": 0})
        if old:
            await db.face_templates_history.insert_one(
                {**old, "archived_at": now_iso(), "archived_by": admin["user_id"],
                 "archived_reason": "replaced_by_self_enrollment"})
        await db.face_templates.update_one(
            {"user_id": req["user_id"]},
            {"$set": {
                "user_id": req["user_id"], "company_id": req.get("company_id"),
                "employee_code": req.get("employee_code"),
                "template_enc": req["template_enc"], "samples": req["samples"],
                "model": FACE_MODEL_PACK, "status": "active",
                "registered_at": now_iso(), "registered_by": admin["user_id"],
                "registered_by_name": admin.get("name"),
                "registered_via": "self_enrollment_approved",
                "last_verified_at": None, "disabled_at": None}},
            upsert=True)
    new_status = {"approve": "approved", "reject": "rejected",
                  "recapture": "recapture_required"}[action]
    await db.face_enrollment_requests.update_one(
        {"enrollment_id": enrollment_id},
        {"$set": {"status": new_status, "reviewed_at": now_iso(),
                  "reviewed_by": admin.get("email") or admin["user_id"],
                  "reason": reason, "sample_previews": []}})
    await _face_admin_audit(
        admin, f"self_enroll_{new_status}", req["user_id"],
        reason or f"{req['samples']} samples")
    from routes.ess import _notify  # noqa: E402 — reuse ESS notifier (+SMS)
    emp = await db.users.find_one({"user_id": req["user_id"]},
                                  {"_id": 0, "mobile": 1}) or {}
    msgs = {
        "approved": "Face Registration Approved ✓ — secure punch is now enabled for you.",
        "rejected": f"Face Registration Rejected.{(' Reason: ' + reason) if reason else ''} You may register again.",
        "recapture_required": f"Please register your face again.{(' Reason: ' + reason) if reason else ''}",
    }
    await _notify(req["user_id"], req.get("company_id"),
                  f"Face Registration {new_status.replace('_', ' ').title()}",
                  msgs[new_status], sms_type="onboarding", mobile=emp.get("mobile"))
    return {"ok": True, "status": new_status}
