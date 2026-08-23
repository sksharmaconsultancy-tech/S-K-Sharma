"""
Iter 691 — SAFE cleanup of browser-autofilled junk in Firm Master portal
credentials.

WHY: Chrome's password manager was autofilling the operator's saved payroll
login (an EMAIL like sksharmaconsultancy@gmail.com + its password) into the
EPF/ESI credential boxes of the Firm Master form. If saved, that junk landed
in the database and was then typed into the EPFO/ESIC login pages.

WHAT THIS DOES:
  * Scans EVERY firm_master.
  * Flags any EPFO/ESIC username that contains "@" (a real EPFO/ESIC login
    is an establishment CODE, never an email) — in the EPF section, the ESI
    section, and the legacy "portal_logins" rows.
  * Prints a REPORT first (read-only) so you can see exactly which firms are
    affected and what the junk value is.
  * Then CLEARS only those junk username+password fields (sets to blank).
    Valid establishment-code logins (no "@") are NEVER touched.

USAGE (on the VPS):
  DB_NAME=<yourdb> python3 fix_epf_autofill_691.py            # report only
  DB_NAME=<yourdb> python3 fix_epf_autofill_691.py --apply    # clean it
"""
import asyncio
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient

APPLY = "--apply" in sys.argv


def _looks_bad(u):
    return bool(u) and "@" in str(u)


async def main():
    mongo = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    dbname = os.environ.get("DB_NAME", "test_database")
    db = AsyncIOMotorClient(mongo)[dbname]

    affected = 0
    cleaned = 0
    print("=" * 70)
    print("SCANNING firm_masters for browser-autofilled junk logins (with '@')")
    print("MODE:", "APPLY (will clean)" if APPLY else "REPORT ONLY (dry run)")
    print("=" * 70)

    async for m in db.firm_masters.find({}):
        cid = m.get("company_id")
        name = m.get("firm_name") or (m.get("header") or {}).get("firm_name") or cid
        changes = {}
        hits = []

        epf = m.get("epf") or {}
        if _looks_bad(epf.get("epf_user_id")):
            hits.append(("EPF User ID", epf.get("epf_user_id")))
            changes["epf.epf_user_id"] = ""
            changes["epf.epf_password"] = ""

        esi = m.get("esi") or {}
        if _looks_bad(esi.get("esi_user_id")):
            hits.append(("ESI User ID", esi.get("esi_user_id")))
            changes["esi.esi_user_id"] = ""
            changes["esi.esi_password"] = ""

        pls = m.get("portal_logins") or []
        new_pls = []
        pl_changed = False
        for row in pls:
            if _looks_bad(row.get("user_name")):
                hits.append((f"portal_logins[{row.get('login_type')}]",
                             row.get("user_name")))
                row = {**row, "user_name": "", "password": ""}
                pl_changed = True
            new_pls.append(row)
        if pl_changed:
            changes["portal_logins"] = new_pls

        if hits:
            affected += 1
            print(f"\nFIRM: {name}  (company_id={cid})")
            for field, val in hits:
                print(f"   ⚠ {field} = {val}   -> will be CLEARED")
            if APPLY:
                await db.firm_masters.update_one(
                    {"_id": m["_id"]}, {"$set": changes})
                cleaned += 1
                print("   ✅ cleared")

    print("\n" + "=" * 70)
    print(f"Firms with junk logins: {affected}")
    if APPLY:
        print(f"Firms cleaned: {cleaned}")
        print("DONE. Now re-enter each firm's REAL EPFO/ESIC login "
              "(establishment code) in Firm Master and Save.")
    else:
        print("This was a DRY RUN. Re-run with --apply to clear them:")
        print("   DB_NAME=<yourdb> python3 fix_epf_autofill_691.py --apply")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
