"""Iter 223 verification — IN.dat/OUT.dat import rules:
1. IN.dat → all punches IN (status byte ignored)
2. OUT.dat → all punches OUT
3. Same-day same-kind punches within 15 min → ignored (first kept)
4. Evening IN with morning IN → lands as 3rd punch → OT IN
5. Both files → shift-anchored reclassify only when sequence dirty
"""
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
import sys
sys.path.insert(0, "/app/backend")

CID = "cmp_527fecdd7c"
DATE = "2026-05-04"  # empty month locally

IN_DAT = f"""
{{BIO}}\t{DATE} 08:00:00\t1
{{BIO}}\t{DATE} 08:07:00\t1
{{BIO}}\t{DATE} 19:00:00\t1
"""
OUT_DAT = f"""
{{BIO}}\t{DATE} 17:00:00\t0
{{BIO}}\t{DATE} 17:10:00\t0
{{BIO}}\t{DATE} 23:00:00\t0
"""

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    emp = await db.users.find_one(
        {"company_id": CID, "role": "employee", "bio_code": {"$ne": None}, "is_contractual": {"$ne": True}},
        {"_id": 0, "user_id": 1, "bio_code": 1, "name": 1})
    bio = str(emp["bio_code"])
    print("employee:", emp["name"], "bio:", bio)
    from utils.zk_dat_import import import_zk_dat_bytes
    stats = await import_zk_dat_bytes(
        db, company_id=CID,
        in_bytes=IN_DAT.replace("{BIO}", bio).encode(),
        out_bytes=OUT_DAT.replace("{BIO}", bio).encode(),
        source_tag="import:test_iter223")
    print("stats:", {k: stats[k] for k in ("total_lines", "inserted", "near_duplicate", "duplicate", "unmapped")})
    assert stats["inserted"] == 4, stats
    assert stats["near_duplicate"] == 2, stats  # 08:07 in + 17:10 out ignored
    docs = await db.attendance.find(
        {"user_id": emp["user_id"], "date": DATE, "source": "import:test_iter223"},
        {"_id": 0, "at": 1, "kind": 1}).sort("at", 1).to_list(10)
    seq = [(d["at"][11:16], d["kind"]) for d in docs]
    print("punch sequence:", seq)
    assert seq == [("08:00", "in"), ("17:00", "out"), ("19:00", "in"), ("23:00", "out")], seq
    print("→ 08:00 IN (morning), 17:00 OUT, 19:00 IN = 3rd punch → OT IN, 23:00 OUT = OT OUT ✓")

    # idempotency: re-import — nothing new
    stats2 = await import_zk_dat_bytes(
        db, company_id=CID,
        in_bytes=IN_DAT.replace("{BIO}", bio).encode(),
        out_bytes=OUT_DAT.replace("{BIO}", bio).encode(),
        source_tag="import:test_iter223b")
    assert stats2["inserted"] == 0 and stats2["duplicate"] == 4, stats2
    print("re-import idempotent ✓")

    # cleanup
    r = await db.attendance.delete_many({"user_id": emp["user_id"], "date": DATE, "source": {"$regex": "test_iter223"}})
    print("cleaned:", r.deleted_count)
    print("ALL ITER 223 CHECKS PASSED")

asyncio.run(main())
