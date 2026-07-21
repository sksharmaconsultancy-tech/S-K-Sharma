"""Iter 224 verification — existing-data protection on .dat import:
A. Day with MANUAL punch → import never touches it.
B. Day with DIFFERENT machine data → skipped (existing_machine_days), needs permission.
C. Re-run with on_existing="replace" → old machine punches replaced, manual kept.
D. Exact re-upload → idempotent (duplicates, no conflict prompt).
"""
import asyncio, os, sys
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

CID = "cmp_527fecdd7c"
D_MAN = "2026-05-11"   # manual-locked day
D_MACH = "2026-05-12"  # machine-conflict day

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    emp = await db.users.find_one(
        {"company_id": CID, "role": "employee", "bio_code": {"$ne": None}, "is_contractual": {"$ne": True}},
        {"_id": 0, "user_id": 1, "bio_code": 1, "name": 1})
    bio, uid = str(emp["bio_code"]), emp["user_id"]
    print("employee:", emp["name"])
    # seed: manual punch on D_MAN, old machine punch on D_MACH
    await db.attendance.insert_many([
        {"record_id": "t224_man", "user_id": uid, "company_id": CID, "date": D_MAN,
         "kind": "in", "at": f"{D_MAN}T09:00:00+00:00", "source": "manual_admin", "status": "approved"},
        {"record_id": "t224_old1", "user_id": uid, "company_id": CID, "date": D_MACH,
         "kind": "in", "at": f"{D_MACH}T07:00:00+00:00", "source": "import:old_batch", "status": "approved"},
    ])
    from utils.zk_dat_import import import_zk_dat_bytes
    IN = f"{bio}\t{D_MAN} 08:00:00\t1\n{bio}\t{D_MACH} 08:00:00\t1\n"
    OUT = f"{bio}\t{D_MAN} 17:00:00\t0\n{bio}\t{D_MACH} 17:00:00\t0\n"
    # A + B: default skip mode
    s = await import_zk_dat_bytes(db, company_id=CID, in_bytes=IN.encode(), out_bytes=OUT.encode(),
                                  source_tag="import:test224")
    print("skip mode:", {k: s[k] for k in ("inserted", "manual_locked_days", "existing_machine_days", "replaced_days")})
    assert s["inserted"] == 0 and s["manual_locked_days"] == 1 and s["existing_machine_days"] == 1
    n_man = await db.attendance.count_documents({"user_id": uid, "date": D_MAN})
    n_mach = await db.attendance.count_documents({"user_id": uid, "date": D_MACH})
    assert n_man == 1 and n_mach == 1, (n_man, n_mach)
    print("A+B ✓ nothing touched without permission")
    # C: replace mode (permission granted)
    s = await import_zk_dat_bytes(db, company_id=CID, in_bytes=IN.encode(), out_bytes=OUT.encode(),
                                  source_tag="import:test224b", on_existing="replace")
    print("replace mode:", {k: s[k] for k in ("inserted", "manual_locked_days", "existing_machine_days", "replaced_days")})
    assert s["manual_locked_days"] == 1  # manual day STILL protected
    assert s["replaced_days"] == 1 and s["inserted"] == 2
    man_doc = await db.attendance.find_one({"user_id": uid, "date": D_MAN})
    assert man_doc["source"] == "manual_admin"  # untouched
    mach = await db.attendance.find({"user_id": uid, "date": D_MACH}, {"_id": 0, "at": 1, "kind": 1, "source": 1}).sort("at", 1).to_list(10)
    assert len(mach) == 2 and all(d["source"] == "import:test224b" for d in mach)
    assert [(d["at"][11:16], d["kind"]) for d in mach] == [("08:00", "in"), ("17:00", "out")]
    print("C ✓ machine day replaced with permission; manual day untouched")
    # D: exact re-upload → idempotent, no conflict
    s = await import_zk_dat_bytes(db, company_id=CID, in_bytes=IN.encode(), out_bytes=OUT.encode(),
                                  source_tag="import:test224c")
    assert s["existing_machine_days"] == 0 and s["inserted"] == 0 and s["duplicate"] == 2, s
    print("D ✓ identical re-upload is silent/idempotent")
    # cleanup
    r = await db.attendance.delete_many({"user_id": uid, "date": {"$in": [D_MAN, D_MACH]},
                                         "$or": [{"record_id": {"$regex": "^t224"}}, {"source": {"$regex": "test224"}}]})
    print("cleaned:", r.deleted_count)
    print("ALL ITER 224 CHECKS PASSED")

asyncio.run(main())
