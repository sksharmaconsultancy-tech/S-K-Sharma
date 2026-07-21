"""Iter 228 verification — "Wrong Data Minutes" import fixes:
1. Dirty same-kind runs are COLLAPSED (first-IN / last-OUT), NOT blindly
   re-alternated (old bug: IN 08:25 + IN 09:51 + OUT 20:17 became a fake
   1.4 h day).
2. Cross-machine bounce: leading OUT followed by IN within 15 min → OUT
   dropped; trailing IN within 15 min after OUT → IN dropped.
3. Night-exit on the wrong machine: a morning IN-file punch directly after
   the previous day's dangling evening IN (6-16 h) with another IN later
   the same day → re-classified as the night shift's OUT on the prev day.
"""
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
import sys
sys.path.insert(0, "/app/backend")

CID = "cmp_527fecdd7c"
D1 = "2026-04-06"  # empty month locally
D2 = "2026-04-07"
D3 = "2026-04-08"

# Case 1 (D1): in 08:25 + stray in 09:51 (>15min, <6h) + out 20:17
#              + trailing bounce in 20:20 (≤15 min after OUT → dropped)
# Case 2 (D2): leading out 08:00 + in 08:04 (bounce) + out 20:00
#              + night IN 20:30 (>15 min after OUT → kept)
# Case 3 (D2 night → D3): morning IN-file punch 08:05 on D3 directly after
#              D2's dangling evening IN → flipped to OUT on D2; evening IN
#              20:10 on D3 stays (dangling until next file).
IN_DAT = f"""
{{BIO}}\t{D1} 08:25:00\t1
{{BIO}}\t{D1} 09:51:00\t1
{{BIO}}\t{D1} 20:20:00\t1
{{BIO}}\t{D2} 08:04:00\t1
{{BIO}}\t{D2} 20:30:00\t1
{{BIO}}\t{D3} 08:05:00\t1
{{BIO}}\t{D3} 20:10:00\t1
"""
OUT_DAT = f"""
{{BIO}}\t{D1} 20:17:00\t0
{{BIO}}\t{D2} 08:00:00\t0
{{BIO}}\t{D2} 20:00:00\t0
"""

TAG = "import:test_iter228"


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    emp = await db.users.find_one(
        {"company_id": CID, "role": "employee", "bio_code": {"$ne": None}, "is_contractual": {"$ne": True}},
        {"_id": 0, "user_id": 1, "bio_code": 1, "name": 1})
    bio = str(emp["bio_code"])
    uid = emp["user_id"]
    print("employee:", emp["name"], "bio:", bio)
    await db.attendance.delete_many({"user_id": uid, "date": {"$in": [D1, D2, D3]}})

    from utils.zk_dat_import import import_zk_dat_bytes
    stats = await import_zk_dat_bytes(
        db, company_id=CID,
        in_bytes=IN_DAT.replace("{BIO}", bio).encode(),
        out_bytes=OUT_DAT.replace("{BIO}", bio).encode(),
        source_tag=TAG)
    print("stats:", {k: stats[k] for k in ("total_lines", "inserted", "near_duplicate", "noise_collapsed")})

    async def day(d):
        docs = await db.attendance.find(
            {"user_id": uid, "date": d, "source": TAG},
            {"_id": 0, "at": 1, "kind": 1}).sort("at", 1).to_list(20)
        return [(x["at"][:16].replace("T", " ")[5:], x["kind"]) for x in docs]

    s1, s2, s3 = await day(D1), await day(D2), await day(D3)
    print("D1:", s1)
    print("D2:", s2)
    print("D3:", s3)

    # Case 1 — stray 09:51 IN collapsed + trailing 20:20 bounce dropped;
    # day pairs 08:25 → 20:17.
    assert s1 == [("04-06 08:25", "in"), ("04-06 20:17", "out")], s1
    print("case 1 ✓ run-collapse + trailing bounce (no fake 1.4h day)")

    # Case 2 — leading OUT 08:00 dropped (bounce); night IN 20:30 kept and
    # its OUT is the flipped D3-morning 08:05 punch (case 3).
    assert s2 == [("04-07 08:04", "in"), ("04-07 20:00", "out"),
                  ("04-07 20:30", "in"), ("04-08 08:05", "out")], s2
    print("case 2+3 ✓ bounces dropped; night exit on IN machine flipped to OUT on prev day")

    # Case 3 — D3 keeps only the real evening IN (dangling until next file).
    assert s3 == [("04-08 20:10", "in")], s3
    print("case 3 ✓ D3 evening IN preserved")

    # cleanup
    n = await db.attendance.delete_many({"user_id": uid, "source": TAG})
    print("cleaned:", n.deleted_count)
    print("ALL ITER 228 CHECKS PASSED")


asyncio.run(main())
