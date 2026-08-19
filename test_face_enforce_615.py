"""Iter 615 — E2E tests:
1. Approved-face punch ENFORCEMENT: matching selfie passes, mismatching /
   missing face BLOCKS the punch (403) even without secure-punch policy.
2. Pending self-enrollments AUTO-APPROVE after 2 days.
3. Compliance document acknowledgement endpoints.
"""
import asyncio, base64, os, uuid
from datetime import datetime, timezone, timedelta
import cv2, numpy as np, httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {extra}")


def jb64(img, data_url=True):
    ok, buf = cv2.imencode(".jpg", img)
    b = base64.b64encode(buf.tobytes()).decode()
    return ("data:image/jpeg;base64," + b) if data_url else b


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    su = await db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}, {"user_id": 1})
    emp = await db.users.find_one(
        {"company_id": CID, "role": "employee", "employee_code": "50"}, {"user_id": 1})
    uid = emp["user_id"]
    ts, te = "test_" + uuid.uuid4().hex, "test_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    await db.user_sessions.insert_many([
        {"session_token": ts, "user_id": su["user_id"], "expires_at": now + timedelta(hours=1),
         "created_at": now, "auth_method": "password"},
        {"session_token": te, "user_id": uid, "expires_at": now + timedelta(hours=1),
         "created_at": now, "auth_method": "password"}])
    HA, HE = {"Authorization": f"Bearer {ts}"}, {"Authorization": f"Bearer {te}"}

    # --- face crops from the insightface sample group photo (t1) ------------
    from insightface.data import get_image
    from insightface.app import FaceAnalysis
    eng = FaceAnalysis(name="buffalo_l", allowed_modules=["detection"],
                       providers=["CPUExecutionProvider"])
    eng.prepare(ctx_id=-1, det_size=(640, 640))
    img = get_image("t1")
    faces = sorted(eng.get(img), key=lambda x: -x.det_score)

    def crop(f):
        x1, y1, x2, y2 = [int(v) for v in f.bbox]
        pad = int((x2 - x1) * 0.8)
        return img[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]

    person_a = crop(faces[0])          # the enrolled identity
    person_b = crop(faces[1])          # a DIFFERENT person
    black = np.zeros((400, 400, 3), dtype=np.uint8)  # no face at all
    frames = [jb64(person_a),
              jb64(cv2.convertScaleAbs(person_a, alpha=1.05, beta=3)),
              jb64(cv2.flip(person_a, 1))]

    # snapshot state to restore afterwards
    orig_tpl = await db.face_templates.find_one({"user_id": uid}, {"_id": 0})
    await db.punch_verification_lock.delete_one({"user_id": uid})
    created_att, created_doc = [], None

    async with httpx.AsyncClient(timeout=180) as cli:
        print("\n== 1. AUTO-APPROVE after 2 days ==")
        r = await cli.post(f"{BASE}/face-verification/self-enroll", headers=HE,
                           json={"consent": True, "frames": frames})
        check("self-enroll accepted", r.status_code == 200, r.text)
        check("message mentions 2-day auto-approve",
              "2 days" in r.json().get("message", ""), r.text)
        # backdate the pending request 3 days
        req = await db.face_enrollment_requests.find_one(
            {"user_id": uid, "status": "pending"}, sort=[("submitted_at", -1)])
        await db.face_enrollment_requests.update_one(
            {"enrollment_id": req["enrollment_id"]},
            {"$set": {"submitted_at": (now - timedelta(days=3)).isoformat()}})
        r = await cli.get(f"{BASE}/face-verification/self-status", headers=HE)
        check("self-status triggers auto-approve → approved",
              r.json().get("status") == "approved", r.text)
        tpl = await db.face_templates.find_one({"user_id": uid})
        check("template ACTIVE via auto-approval",
              tpl and tpl.get("status") == "active"
              and tpl.get("registered_via") == "self_enrollment_auto_approved")
        fr = await db.face_enrollment_requests.find_one({"enrollment_id": req["enrollment_id"]})
        check("request marked approved by system_auto_approval",
              fr.get("status") == "approved"
              and fr.get("reviewed_by") == "system_auto_approval"
              and fr.get("sample_previews") == [])
        aud = await db.face_admin_audit.find_one(
            {"action": "self_enroll_auto_approved", "target_user_id": uid})
        check("audit row self_enroll_auto_approved", bool(aud))

        print("\n== 2. PUNCH FACE ENFORCEMENT (approved face = enforced face) ==")
        company = await db.companies.find_one({"company_id": CID}, {"_id": 0, "secure_face_punch_enabled": 1})
        check("firm secure_face_punch_enabled is OFF (tests normal path)",
              not company.get("secure_face_punch_enabled"))

        async def punch(selfie, method="face", kind="in"):
            return await cli.post(f"{BASE}/attendance/punch", headers=HE, json={
                "kind": kind, "biometric_method": method,
                "latitude": None, "longitude": None,
                "selfie_base64": selfie, "device_info": "pytest", "source": "manual",
            })

        # 2a. MISMATCH — different person's face must be BLOCKED
        r = await punch(jb64(person_b))
        check("mismatching face BLOCKED (403)", r.status_code == 403, f"{r.status_code} {r.text[:200]}")
        check("mismatch message mentions face mismatch",
              "does not match" in r.text, r.text[:200])
        await db.punch_verification_lock.delete_one({"user_id": uid})

        # 2b. NO FACE in selfie — blocked
        r = await punch(jb64(black))
        check("no-face selfie BLOCKED (403)", r.status_code == 403, f"{r.status_code} {r.text[:200]}")
        await db.punch_verification_lock.delete_one({"user_id": uid})

        # 2c. face method WITHOUT selfie — blocked
        r = await punch(None)
        check("face punch without selfie BLOCKED (403)", r.status_code == 403,
              f"{r.status_code} {r.text[:200]}")

        # 2d. MATCHING face — must NOT be face-rejected
        r = await punch(jb64(person_a))
        face_rejected = r.status_code == 403 and ("face" in r.text.lower())
        check("matching face NOT face-rejected", not face_rejected,
              f"{r.status_code} {r.text[:200]}")
        if r.status_code == 200:
            rec = await db.attendance.find_one(
                {"user_id": uid, "template_face_match.face_match": "pass"},
                sort=[("at", -1)])
            check("attendance stamped with template_face_match + score",
                  rec is not None and rec.get("face_match_score"))
            if rec:
                created_att.append(rec["record_id"])
        audits = await db.punch_verification_audit.count_documents(
            {"user_id": uid, "stage": "punch_face_match"})
        check("punch_face_match audit rows written", audits >= 3, f"got {audits}")

        # 2e. lockout after repeated mismatches
        await db.punch_verification_lock.delete_one({"user_id": uid})
        for _ in range(3):
            await punch(jb64(person_b))
        r = await punch(jb64(person_a))
        check("lockout kicks in after repeated mismatches (429)",
              r.status_code == 429, f"{r.status_code} {r.text[:150]}")
        await db.punch_verification_lock.delete_one({"user_id": uid})

        # 2f. employee with NO template — punch NOT face-blocked
        other = await db.users.find_one(
            {"company_id": CID, "role": "employee", "user_id": {"$ne": uid},
             "employee_code": "65"}, {"user_id": 1})
        if other and not await db.face_templates.find_one(
                {"user_id": other["user_id"], "status": "active"}):
            to = "test_" + uuid.uuid4().hex
            await db.user_sessions.insert_one(
                {"session_token": to, "user_id": other["user_id"],
                 "expires_at": now + timedelta(hours=1), "created_at": now,
                 "auth_method": "password"})
            r = await cli.post(f"{BASE}/attendance/punch",
                               headers={"Authorization": f"Bearer {to}"},
                               json={"kind": "in", "biometric_method": "face",
                                     "latitude": None, "longitude": None,
                                     "selfie_base64": jb64(person_b),
                                     "device_info": "pytest", "source": "manual"})
            face_block = r.status_code == 403 and "face" in r.text.lower()
            check("un-enrolled employee NOT face-blocked", not face_block,
                  f"{r.status_code} {r.text[:150]}")
            if r.status_code == 200:
                d = await db.attendance.find_one(
                    {"user_id": other["user_id"]}, sort=[("at", -1)])
                if d:
                    created_att.append(d["record_id"])
            await db.user_sessions.delete_one({"session_token": to})

        print("\n== 3. DOCUMENT ACKNOWLEDGEMENT ==")
        r = await cli.post(f"{BASE}/compliance-docs", headers=HA, json={
            "title": "TEST Policy 615", "description": "ack test",
            "category": "policy", "content": "please read"})
        created_doc = r.json().get("doc_id")
        check("admin creates doc", r.status_code == 200 and created_doc, r.text[:150])
        r = await cli.get(f"{BASE}/compliance-docs", headers=HE)
        d = next((x for x in r.json()["docs"] if x["doc_id"] == created_doc), None)
        check("employee list shows acknowledged_by_me=False",
              d is not None and d.get("acknowledged_by_me") is False)
        r = await cli.post(f"{BASE}/compliance-docs/{created_doc}/acknowledge", headers=HE)
        check("employee acknowledges", r.status_code == 200 and r.json().get("ok"), r.text)
        r = await cli.post(f"{BASE}/compliance-docs/{created_doc}/acknowledge", headers=HE)
        check("idempotent re-ack", r.json().get("already") is True, r.text)
        r = await cli.get(f"{BASE}/compliance-docs", headers=HE)
        d = next((x for x in r.json()["docs"] if x["doc_id"] == created_doc), None)
        check("list now acknowledged_by_me=True + ack_count=1",
              d and d.get("acknowledged_by_me") is True and d.get("ack_count") == 1)
        r = await cli.get(f"{BASE}/compliance-docs/does-not-exist/acknowledge", headers=HE)
        # (GET on ack route → 405; POST unknown id → 404)
        r = await cli.post(f"{BASE}/compliance-docs/nope123/acknowledge", headers=HE)
        check("ack unknown doc → 404", r.status_code == 404, r.text[:100])

    # ---- cleanup ------------------------------------------------------
    if orig_tpl:
        await db.face_templates.replace_one({"user_id": uid}, orig_tpl, upsert=True)
    for rid in created_att:
        await db.attendance.delete_one({"record_id": rid})
    if created_doc:
        await db.compliance_docs.delete_one({"doc_id": created_doc})
    await db.face_enrollment_requests.delete_many(
        {"user_id": uid, "reviewed_by": "system_auto_approval"})
    await db.punch_verification_lock.delete_one({"user_id": uid})
    await db.user_sessions.delete_many({"session_token": {"$in": [ts, te]}})
    print(f"\n==== RESULT: {PASS} passed, {FAIL} failed ====")
    raise SystemExit(1 if FAIL else 0)


asyncio.run(main())
