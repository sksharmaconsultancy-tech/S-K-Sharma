"""Iter 512 — SDK pull pipeline test: stub adapter → _run_pull → attendance.

Validates: punch ingestion parity with ADMS (bio_code matching, IN/OUT
alternation for kind=both, dedupe), cursor advancement, device stat fields.
Run: cd /app/backend && python3 tests/test_iter512_sdk_pull.py
"""
import asyncio
import sys
from datetime import datetime

sys.path.insert(0, "/app/backend")


class StubAdapter:
    default_port = 4370

    def __init__(self, punches):
        self._punches = punches

    async def test_connection(self, host, port, comm_key=None):
        return {"ok": True, "info": {"serial": "STUB1", "firmware": "test"}}

    async def pull_punches(self, host, port, comm_key=None, since=None):
        out = []
        for p in self._punches:
            if since and p["at"].strftime("%Y-%m-%d %H:%M:%S") <= since:
                continue
            out.append(p)
        return out


async def main():
    from server import db
    import routes.biometric_sdk as sdk_mod

    device = await db.biometric_devices.find_one(
        {"serial_number": "SDKTEST001"}, {"_id": 0})
    assert device, "SDKTEST001 device missing — register it first"

    # employee code 50 → bio 72 (Kankani). Use bio code 72.
    punches = [
        {"device_user_id": "72", "at": datetime(2026, 8, 6, 9, 1, 0), "state": "0", "verify": "fingerprint"},
        {"device_user_id": "72", "at": datetime(2026, 8, 6, 18, 2, 0), "state": "1", "verify": "fingerprint"},
        {"device_user_id": "99999", "at": datetime(2026, 8, 6, 9, 5, 0), "state": "0", "verify": None},  # unmapped
    ]
    stub = StubAdapter(punches)
    orig = sdk_mod.get_adapter
    sdk_mod.get_adapter = lambda v: stub
    try:
        # clean previous runs
        await db.attendance.delete_many({"device_serial": "SDKTEST001"})
        await db.biometric_unmapped.delete_many({"device_serial": "SDKTEST001"})
        await db.biometric_devices.update_one(
            {"serial_number": "SDKTEST001"}, {"$unset": {"sdk_pull_cursor": ""}})
        device.pop("sdk_pull_cursor", None)

        r1 = await sdk_mod._run_pull(device, "test-script")
        print("pull#1:", r1)
        assert r1["fetched"] == 3, r1
        assert r1["inserted"] == 2, r1          # 72 in + 72 out; 99999 unmapped
        assert r1["cursor"] == "2026-08-06 18:02:00", r1

        recs = await db.attendance.find(
            {"device_serial": "SDKTEST001"}, {"_id": 0, "kind": 1, "at": 1, "status": 1, "source": 1}
        ).sort("at", 1).to_list(10)
        print("attendance:", recs)
        assert [x["kind"] for x in recs] == ["in", "out"], recs
        assert all(x["source"] == "zkteco:SDKTEST001" for x in recs), recs

        unmapped = await db.biometric_unmapped.count_documents({"device_serial": "SDKTEST001"})
        assert unmapped == 1, unmapped

        # pull #2 — cursor must skip everything (idempotent)
        dev2 = await db.biometric_devices.find_one({"serial_number": "SDKTEST001"}, {"_id": 0})
        r2 = await sdk_mod._run_pull(dev2, "test-script")
        print("pull#2:", r2)
        assert r2["fetched"] == 0 and r2["inserted"] == 0, r2

        dev3 = await db.biometric_devices.find_one({"serial_number": "SDKTEST001"}, {"_id": 0})
        assert dev3.get("sdk_last_pull_at") and dev3.get("sdk_pull_cursor") == "2026-08-06 18:02:00"
        print("device stats:", {k: dev3.get(k) for k in
                                ("sdk_last_pull_at", "sdk_last_pull_inserted", "sdk_pull_cursor", "sdk_last_error")})
        print("\nALL SDK PULL PIPELINE TESTS PASSED ✅")
    finally:
        sdk_mod.get_adapter = orig
        # cleanup test punches
        await db.attendance.delete_many({"device_serial": "SDKTEST001"})
        await db.biometric_unmapped.delete_many({"device_serial": "SDKTEST001"})


asyncio.run(main())
