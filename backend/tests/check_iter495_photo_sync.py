"""Iter 495 e2e check — ZKTeco SDK user/photo ingest + photo fallback + group filter.

Run: cd /app/backend && python tests/check_iter495_photo_sync.py
"""
import asyncio
import base64
import io
import os
import sys

import httpx

BASE = "http://localhost:8001"
sys.path.append("/app/backend")

TEST_SN = "TEST495SN001"
TEST_PIN = "9495"


def _tiny_jpeg_b64() -> str:
    from PIL import Image
    img = Image.new("RGB", (64, 64), (200, 120, 60))
    out = io.BytesIO()
    img.save(out, format="JPEG")
    return base64.b64encode(out.getvalue()).decode()


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "test_database")]

    ok = True
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as http:
        # ---- login super admin
        r = await http.post("/api/auth/admin-password-login", json={
            "email": "sksharmaconsultancy@gmail.com", "password": "sharma123"})
        assert r.status_code == 200, f"login failed {r.status_code} {r.text[:200]}"
        token = r.json()["session_token"]
        H = {"Authorization": f"Bearer {token}"}
        print("[1] login OK")

        cid = "cmp_527fecdd7c"  # Kankani

        # ---- clean + register a test device
        await db.biometric_devices.delete_many({"serial_number": TEST_SN})
        await db.biometric_machine_users.delete_many({"pin": TEST_PIN})
        await db.users.delete_many({"bio_code": TEST_PIN, "company_id": cid})
        r = await http.post("/api/biometric/devices", headers=H, json={
            "serial_number": TEST_SN, "name": "Iter495 Test Device", "kind": "in",
            "company_id": cid})
        assert r.status_code in (200, 201), f"register device: {r.status_code} {r.text[:300]}"
        print("[2] device registered")

        # ---- getrequest should queue USERINFO + USERPIC/BIOPHOTO queries
        r = await http.get(f"/api/iclock/getrequest?SN={TEST_SN}")
        body = r.text
        assert "DATA QUERY USERINFO" in body, f"USERINFO not queued: {body!r}"
        assert "DATA QUERY USERPIC" in body or "DATA QUERY BIOPHOTO" in body, \
            f"USERPIC not queued: {body!r}"
        print("[3] getrequest auto-queues USERINFO + USERPIC:", body.strip().splitlines())

        # ---- push USER row with table=USERINFO (firmware variant — the fix)
        r = await http.post(
            f"/api/iclock/cdata?SN={TEST_SN}&table=USERINFO",
            content=f"USER PIN={TEST_PIN}\tName=Iter495 Tester\tPri=0\tCard=123",
        )
        assert r.status_code == 200, r.text
        row = await db.biometric_machine_users.find_one({"company_id": cid, "pin": TEST_PIN})
        assert row and row.get("name") == "Iter495 Tester", f"machine user not saved: {row}"
        print("[4] USER row ingested with table=USERINFO (name='%s')" % row["name"])

        # ---- push USERPIC BEFORE the employee exists in master
        jpg = _tiny_jpeg_b64()
        r = await http.post(
            f"/api/iclock/cdata?SN={TEST_SN}&table=USERPIC",
            content=f"USERPIC PIN={TEST_PIN}\tFileName={TEST_PIN}.jpg\tSize=999\tContent={jpg}",
        )
        assert r.status_code == 200
        row = await db.biometric_machine_users.find_one({"company_id": cid, "pin": TEST_PIN})
        assert row and row.get("photo_b64") == jpg, "photo not stored on machine user"
        print("[5] USERPIC ingested + stored on machine-user row")

        # ---- now create the employee AFTER photo arrival (no portal photo)
        import uuid
        uid = f"usr_test495_{uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "user_id": uid, "role": "employee", "company_id": cid,
            "name": "Iter495 Tester", "employee_code": "E495",
            "bio_code": TEST_PIN, "approval_status": "approved"})

        # ---- thumbs endpoint must backfill from machine photo
        r = await http.post("/api/admin/employee-photos/thumbs", headers=H,
                            json={"user_ids": [uid]})
        assert r.status_code == 200, r.text
        thumb = (r.json().get("thumbs") or {}).get(uid)
        assert thumb, "thumb NOT backfilled from machine photo"
        u = await db.users.find_one({"user_id": uid})
        assert u.get("profile_photo_base64") == jpg, "user photo not persisted"
        assert u.get("profile_photo_source") == "machine"
        print("[6] thumbs endpoint backfilled photo from machine (len=%d)" % len(thumb))

        # ---- full endpoint
        r = await http.get(f"/api/admin/employee-photos/{uid}/full", headers=H)
        assert r.status_code == 200 and r.json().get("photo") == jpg
        print("[7] full photo endpoint OK")

        # ---- USERPIC pushed AFTER employee exists → direct sync path
        await db.users.update_one({"user_id": uid},
                                  {"$unset": {"profile_photo_base64": "",
                                              "profile_photo_thumb": ""}})
        r = await http.post(
            f"/api/iclock/cdata?SN={TEST_SN}&table=OPERLOG",
            content=f"USERPIC PIN={TEST_PIN}\tFileName={TEST_PIN}.jpg\tContent={jpg}",
        )
        u = await db.users.find_one({"user_id": uid})
        assert u.get("profile_photo_base64") == jpg, "direct USERPIC→user sync failed"
        print("[8] USERPIC (table=OPERLOG) synced straight to Employee Master")

        # ---- group filter on monthly IN/OUT report
        grp = await db.masters.find_one({"type": "group",
                                         "company_id": {"$in": [cid, "__global__", None]},
                                         "member_user_ids.0": {"$exists": True}})
        month = "2026-05"
        r_all = await http.get(f"/api/admin/attendance/monthly-inout/{cid}/{month}.xlsx",
                               headers=H)
        print(f"[9] monthly-inout no-group: {r_all.status_code} ({len(r_all.content)} bytes)")
        if grp:
            r_grp = await http.get(
                f"/api/admin/attendance/monthly-inout/{cid}/{month}.xlsx"
                f"?group_id={grp['master_id']}", headers=H)
            print(f"[9] monthly-inout group={grp.get('name')}: {r_grp.status_code} "
                  f"({len(r_grp.content)} bytes)")
            assert r_grp.status_code == 200
            assert len(r_grp.content) != len(r_all.content) or r_all.status_code != 200, \
                "group filter produced identical file — check filter"
        else:
            print("[9] no group with members found in masters — skipped diff check")

        # ---- cleanup
        await db.biometric_devices.delete_many({"serial_number": TEST_SN})
        await db.biometric_device_cmds.delete_many({"device_serial": TEST_SN})
        await db.biometric_machine_users.delete_many({"pin": TEST_PIN})
        await db.biometric_operlog.delete_many({"device_serial": TEST_SN})
        await db.users.delete_one({"user_id": uid})
        print("\nALL CHECKS PASSED" if ok else "FAILED")


asyncio.run(main())
