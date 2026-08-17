"""Iter 602 — Secure face-punch verification flow tests."""
import asyncio, base64, os, sys, uuid
from datetime import datetime, timezone, timedelta

import cv2
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"


def jb64(img):
    ok, buf = cv2.imencode(".jpg", img)
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]
    su = await db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}, {"user_id": 1})
    emp = await db.users.find_one({"company_id": CID, "role": "employee",
                                   "employee_code": "50"}, {"user_id": 1, "name": 1})
    ts, te = "test_" + uuid.uuid4().hex, "test_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    await db.user_sessions.insert_many([
        {"session_token": ts, "user_id": su["user_id"], "expires_at": now + timedelta(hours=1),
         "created_at": now, "auth_method": "password"},
        {"session_token": te, "user_id": emp["user_id"], "expires_at": now + timedelta(hours=1),
         "created_at": now, "auth_method": "password"}])
    HA = {"Authorization": f"Bearer {ts}"}
    HE = {"Authorization": f"Bearer {te}"}
    ok = True

    from insightface.data import get_image
    from insightface.app import FaceAnalysis
    eng = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"],
                       providers=["CPUExecutionProvider"])
    eng.prepare(ctx_id=-1, det_size=(640, 640))
    img = get_image("t1")
    faces = sorted(eng.get(img), key=lambda f: -f.det_score)[:2]
    crops = []
    for f in faces:
        x1, y1, x2, y2 = [int(v) for v in f.bbox]
        pad = int((x2 - x1) * 0.8)
        crops.append(img[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad])
    A, B = crops
    A2 = cv2.convertScaleAbs(A, alpha=1.05, beta=3)
    A3 = cv2.flip(A, 1)

    # policy: liveness OFF for lab test (static crops can't turn heads),
    # anti-spoof ON, secure punch ON.
    orig = await db.companies.find_one({"company_id": CID},
        {"_id": 0, "secure_face_punch_enabled": 1, "secure_punch_liveness": 1})
    await db.companies.update_one({"company_id": CID},
        {"$set": {"secure_face_punch_enabled": True, "secure_punch_liveness": False,
                  "secure_punch_anti_spoof": True}})

    async with httpx.AsyncClient(timeout=180) as c:
        # enroll person A
        r = await c.post(f"{BASE}/admin/face-verification/enroll", headers=HA,
                         json={"user_id": emp["user_id"],
                               "frames": [jb64(A), jb64(A2), jb64(A3)]})
        print("1. enroll A:", r.status_code); ok &= r.status_code == 200

        r = await c.get(f"{BASE}/attendance/face-verify/policy", headers=HE)
        print("2. policy:", r.json()); ok &= r.json()["face_registered"] is True and r.json()["secure_punch_enabled"] is True

        # start (no device registered → allowed, device_auth skipped)
        r = await c.post(f"{BASE}/attendance/face-verify/start", headers=HE, json={})
        j = r.json(); steps = [s["step"] for s in j.get("steps", [])]
        print("3. start:", r.status_code, steps); ok &= r.status_code == 200 and steps[0] == "CENTER" and len(steps) == 3

        # complete with SAME person A frames → SUCCESS
        variants = [A, A2, A3]
        frames = [{"step": s, "frame": jb64(variants[i])} for i, s in enumerate(steps)]
        r = await c.post(f"{BASE}/attendance/face-verify/complete", headers=HE,
                         json={"verification_session_id": j["verification_session_id"], "frames": frames})
        print("4. genuine verify:", r.status_code, r.json() if r.status_code == 200 else r.json().get("detail", "")[:60])
        ok &= r.status_code == 200 and r.json()["face_match_score"] >= 72
        vsid = j["verification_session_id"]

        # WRONG PERSON (B) vs A's template → REJECTED
        r = await c.post(f"{BASE}/attendance/face-verify/start", headers=HE, json={})
        j2 = r.json(); steps2 = [s["step"] for s in j2["steps"]]
        Bv = [B, cv2.convertScaleAbs(B, alpha=1.05, beta=3), cv2.flip(B, 1)]
        frames2 = [{"step": s, "frame": jb64(Bv[i])} for i, s in enumerate(steps2)]
        r = await c.post(f"{BASE}/attendance/face-verify/complete", headers=HE,
                         json={"verification_session_id": j2["verification_session_id"], "frames": frames2})
        print("5. wrong person -> expect 403:", r.status_code, r.json().get("detail", "")[:60])
        ok &= r.status_code == 403

        # punch WITHOUT verification session → 403 gate
        r = await c.post(f"{BASE}/attendance/punch", headers=HE,
                         json={"kind": "in", "biometric_method": "face",
                               "latitude": 26.9, "longitude": 75.8})
        print("6. punch w/o session -> expect 403:", r.status_code, r.json().get("detail", "")[:50])
        ok &= r.status_code == 403 and "Secure verification" in r.json().get("detail", "")

        # audit rows exist
        r = await c.get(f"{BASE}/admin/attendance/punch-verification-audit?company_id={CID}", headers=HA)
        logs = r.json()["logs"]
        print("7. audit rows:", len(logs), [(l["result"], l.get("face_match_score")) for l in logs[:2]])
        ok &= len(logs) >= 2 and logs[0]["result"] == "REJECTED"

        # lockout after 3 fails (1 fail so far) → 2 more wrong attempts then 429
        for _ in range(2):
            r = await c.post(f"{BASE}/attendance/face-verify/start", headers=HE, json={})
            js = r.json()
            if r.status_code != 200:
                break
            st = [s["step"] for s in js["steps"]]
            fr = [{"step": s, "frame": jb64(Bv[i])} for i, s in enumerate(st)]
            await c.post(f"{BASE}/attendance/face-verify/complete", headers=HE,
                         json={"verification_session_id": js["verification_session_id"], "frames": fr})
        r = await c.post(f"{BASE}/attendance/face-verify/start", headers=HE, json={})
        print("8. lockout -> expect 429:", r.status_code); ok &= r.status_code == 429

    # restore
    unset = {k: 1 for k in ["secure_face_punch_enabled", "secure_punch_liveness",
                            "secure_punch_anti_spoof"] if k not in (orig or {})}
    if unset:
        await db.companies.update_one({"company_id": CID}, {"$unset": unset})
    if orig:
        await db.companies.update_one({"company_id": CID}, {"$set": orig})
    await db.face_templates.delete_many({"user_id": emp["user_id"]})
    await db.face_templates_history.delete_many({"user_id": emp["user_id"]})
    await db.punch_verification_lock.delete_many({"user_id": emp["user_id"]})
    await db.punch_verification_sessions.delete_many({"user_id": emp["user_id"]})
    await db.user_sessions.delete_many({"session_token": {"$in": [ts, te]}})
    print("RESULT:", "PASS ✅" if ok else "FAIL ❌")
    sys.exit(0 if ok else 1)


asyncio.run(main())
