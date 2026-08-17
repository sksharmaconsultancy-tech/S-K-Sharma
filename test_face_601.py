"""Iter 601 — Face enrollment + WebAuthn device backend tests."""
import asyncio, base64, os, sys, uuid
from datetime import datetime, timezone, timedelta

import cv2
import httpx
import numpy as np
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
BASE = "http://localhost:8001/api"


def jpg_b64(img) -> str:
    ok, buf = cv2.imencode(".jpg", img)
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]
    su = await db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}, {"user_id": 1})
    emp = await db.users.find_one({"company_id": "cmp_527fecdd7c", "role": "employee",
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

    # Build face samples from insightface's bundled group photo (crop 2 people).
    from insightface.data import get_image
    img = get_image("t1")  # group photo with multiple faces
    from insightface.app import FaceAnalysis
    eng = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"],
                       providers=["CPUExecutionProvider"])
    eng.prepare(ctx_id=-1, det_size=(640, 640))
    faces = sorted(eng.get(img), key=lambda f: -f.det_score)[:2]
    crops = []
    for f in faces:
        x1, y1, x2, y2 = [int(v) for v in f.bbox]
        pad = int((x2 - x1) * 0.8)
        crop = img[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
        crops.append(crop)
    p1, p2 = crops[0], crops[1]
    p1b = cv2.convertScaleAbs(p1, alpha=1.06, beta=4)   # same person, varied
    p1c = cv2.flip(p1, 1)

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(f"{BASE}/admin/face-verification/engine-status", headers=HA)
        print("1. engine:", r.json()); ok &= r.json().get("ready") is True

        blank = np.full((480, 480, 3), 128, np.uint8)
        r = await c.post(f"{BASE}/admin/face-verification/check-frame", headers=HA,
                         json={"frame": jpg_b64(blank)})
        print("2. blank frame:", r.json()["ok"], r.json().get("reason", "")[:40]); ok &= r.json()["ok"] is False

        r = await c.post(f"{BASE}/admin/face-verification/enroll", headers=HA,
                         json={"user_id": emp["user_id"],
                               "frames": [jpg_b64(p1), jpg_b64(p1b), jpg_b64(p1c)]})
        print("3. enroll same person:", r.status_code, str(r.json())[:90]); ok &= r.status_code == 200

        r = await c.post(f"{BASE}/admin/face-verification/enroll", headers=HA,
                         json={"user_id": emp["user_id"],
                               "frames": [jpg_b64(p1), jpg_b64(p2)]})
        print("4. mixed persons -> expect 422:", r.status_code, r.json().get("detail", "")[:60])
        ok &= r.status_code == 422

        r = await c.get(f"{BASE}/admin/face-verification/status?user_id={emp['user_id']}", headers=HA)
        print("5. status:", r.json()["face"]["status"], "samples:", r.json()["face"].get("samples"))
        ok &= r.json()["face"]["status"] == "active"

        # employee CANNOT touch enrollment APIs
        r = await c.post(f"{BASE}/admin/face-verification/enroll", headers=HE,
                         json={"user_id": emp["user_id"], "frames": [jpg_b64(p1), jpg_b64(p1b)]})
        print("6. employee enroll -> expect 403:", r.status_code); ok &= r.status_code == 403

        r = await c.post(f"{BASE}/admin/face-verification/disable", headers=HA,
                         json={"user_id": emp["user_id"]})
        print("7. disable:", r.status_code); ok &= r.status_code == 200

        # template must be encrypted at rest
        t = await db.face_templates.find_one({"user_id": emp["user_id"]}, {"_id": 0, "template_enc": 1})
        print("8. template encrypted:", str(t["template_enc"])[:8]); ok &= str(t["template_enc"]).startswith("enc::")

        # ── WebAuthn ──
        r = await c.post(f"{BASE}/attendance/device/register-options", headers=HE,
                         json={}, follow_redirects=True)
        j = r.json()
        print("9. register-options:", r.status_code, "rp:", j.get("options", {}).get("rp", {}).get("id"))
        ok &= r.status_code == 200 and bool(j.get("challenge_id"))

        r = await c.post(f"{BASE}/attendance/device/register-verify", headers=HE,
                         json={"challenge_id": j["challenge_id"],
                               "credential": {"id": "fake", "rawId": "ZmFrZQ", "type": "public-key",
                                              "response": {"clientDataJSON": "e30", "attestationObject": "e30"}}})
        print("10. garbage attestation -> expect 400:", r.status_code); ok &= r.status_code == 400

        r = await c.post(f"{BASE}/attendance/device/auth-options", headers=HE, json={})
        print("11. auth-options w/o device -> expect 404:", r.status_code); ok &= r.status_code == 404

        r = await c.get(f"{BASE}/attendance/device/status", headers=HE)
        print("12. device status:", r.status_code, r.json()); ok &= r.status_code == 200

    # cleanup
    await db.face_templates.delete_many({"user_id": emp["user_id"]})
    await db.face_templates_history.delete_many({"user_id": emp["user_id"]})
    await db.user_sessions.delete_many({"session_token": {"$in": [ts, te]}})
    print("RESULT:", "PASS ✅" if ok else "FAIL ❌")
    sys.exit(0 if ok else 1)


asyncio.run(main())
