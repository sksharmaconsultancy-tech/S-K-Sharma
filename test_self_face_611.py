"""Iter 611 — self face enrollment full E2E with a REAL face image."""
import asyncio, base64, os, sys, uuid
from datetime import datetime, timezone, timedelta
import cv2, httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"


def jb64(img):
    ok, buf = cv2.imencode(".jpg", img)
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    su = await db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}, {"user_id": 1})
    emp = await db.users.find_one({"company_id": CID, "role": "employee", "employee_code": "50"},
                                  {"user_id": 1})
    ts, te = "test_" + uuid.uuid4().hex, "test_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    await db.user_sessions.insert_many([
        {"session_token": ts, "user_id": su["user_id"], "expires_at": now + timedelta(hours=1),
         "created_at": now, "auth_method": "password"},
        {"session_token": te, "user_id": emp["user_id"], "expires_at": now + timedelta(hours=1),
         "created_at": now, "auth_method": "password"}])
    HA, HE = {"Authorization": f"Bearer {ts}"}, {"Authorization": f"Bearer {te}"}

    from insightface.data import get_image
    from insightface.app import FaceAnalysis
    eng = FaceAnalysis(name="buffalo_l", allowed_modules=["detection"],
                       providers=["CPUExecutionProvider"])
    eng.prepare(ctx_id=-1, det_size=(640, 640))
    img = get_image("t1")
    f = sorted(eng.get(img), key=lambda x: -x.det_score)[0]
    x1, y1, x2, y2 = [int(v) for v in f.bbox]
    pad = int((x2 - x1) * 0.8)
    A = img[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
    frames = [jb64(A),
              jb64(cv2.convertScaleAbs(A, alpha=1.05, beta=3)),
              jb64(cv2.flip(A, 1))]

    had_template = await db.face_templates.find_one({"user_id": emp["user_id"]})
    async with httpx.AsyncClient(timeout=120) as cli:
        r = await cli.post(f"{BASE}/face-verification/self-enroll", headers=HE,
                           json={"consent": True, "frames": frames})
        print("self-enroll:", r.status_code, r.json())
        assert r.status_code == 200
        r = await cli.get(f"{BASE}/face-verification/self-status", headers=HE)
        assert r.json()["status"] == "pending", r.text
        print("status pending ✅")
        r = await cli.get(f"{BASE}/admin/face-verification/pending?company_id={CID}", headers=HA)
        pend = r.json()["pending"]
        eid = next(p["enrollment_id"] for p in pend if p["user_id"] == emp["user_id"])
        assert pend[0].get("sample_previews") is not None
        print("admin sees pending w/ previews ✅")
        # employee cannot decide
        r = await cli.post(f"{BASE}/admin/face-verification/pending/{eid}/decide",
                           headers=HE, json={"action": "approve"})
        assert r.status_code == 403
        print("employee cannot approve own face ✅")
        r = await cli.post(f"{BASE}/admin/face-verification/pending/{eid}/decide",
                           headers=HA, json={"action": "approve"})
        print("approve:", r.status_code, r.json())
        assert r.status_code == 200
        t = await db.face_templates.find_one({"user_id": emp["user_id"]})
        assert t and t["status"] == "active" and t["registered_via"] == "self_enrollment_approved"
        print("template ACTIVE via self_enrollment_approved ✅")
        req = await db.face_enrollment_requests.find_one({"enrollment_id": eid})
        assert req["status"] == "approved" and req["sample_previews"] == []
        print("previews purged after decision ✅")
        r = await cli.get(f"{BASE}/face-verification/self-status", headers=HE)
        assert r.json()["status"] == "approved"
        print("employee status approved ✅")
        n = await db.notifications.find_one({"target_user_id": emp["user_id"],
                                             "title": {"$regex": "Face Registration"}})
        assert n, "notification missing"
        print("employee notified ✅")

    # cleanup
    if not had_template:
        await db.face_templates.delete_many({"user_id": emp["user_id"]})
    await db.face_enrollment_requests.delete_many({"user_id": emp["user_id"]})
    await db.notifications.delete_many({"target_user_id": emp["user_id"],
                                        "title": {"$regex": "Face Registration"}})
    await db.user_sessions.delete_many({"session_token": {"$in": [ts, te]}})
    print("\nALL PASS (cleaned up)")

asyncio.run(main())
