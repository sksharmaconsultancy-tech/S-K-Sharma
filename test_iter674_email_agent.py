"""E2E test — Email Audit Agent Phase 1 (sandbox pipeline, no live mailbox)."""
import asyncio, os, secrets, json, urllib.request
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = "http://localhost:8001/api"

def call(path, tok, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body else None)
    req.add_header("Authorization", f"Bearer {tok}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    sup = await db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}, {"_id": 0, "user_id": 1})
    tok = "testsess_" + secrets.token_hex(16)
    await db.user_sessions.insert_one({
        "session_token": tok, "user_id": sup["user_id"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    comp = await db.companies.find_one({}, {"_id": 0, "company_id": 1, "name": 1})
    print("firm:", comp["name"])

    # 1. settings + sandbox on
    s = call("/email-agent/settings", tok, "POST", {"sandbox": True, "threshold": 80})
    print("1 settings:", {k: s[k] for k in ("enabled", "sandbox", "threshold", "smtp_configured")})

    # 2. register email
    try:
        r = call("/email-agent/registry", tok, "POST", {
            "company_id": comp["company_id"], "email": "hr@kankani-test.com",
            "email_type": "hr", "contact_person": "HR Head"})
        reg_id = r["entry"]["registry_id"]
    except urllib.error.HTTPError as e:
        print("registry add:", e.code, e.read()[:100]); reg_id = None
    print("2 registry added:", bool(reg_id))

    # 3. sandbox ingest — EXACT match + salary email
    r = call("/email-agent/sandbox-ingest", tok, "POST", {
        "sender_email": "hr@kankani-test.com", "sender_name": "HR Head",
        "subject": "August 2026 salary sheet attached",
        "body": ("Dear Sir, please find the August 2026 salary data for our 56 "
                 "employees. Kindly process the salary at the earliest. Employee "
                 "RAM SINGH (code E101) has 2 days LWP this month.")})
    rec = r["record"]
    print("3 exact:", rec["status"], "|", rec["company_match_type"],
          rec["company_match_confidence"], "|", rec["categories"][:3])
    print("   summary:", rec["ai_summary"][:100])
    print("   reco:", rec["ai_recommendation"][:100])
    print("   extracted:", rec["extracted"])
    a1 = rec["audit_id"]

    # 4. sandbox ingest — unknown gmail sender mentioning firm name
    r = call("/email-agent/sandbox-ingest", tok, "POST", {
        "sender_email": "randomperson@gmail.com",
        "subject": "Attendance query",
        "body": f"Hello, this is regarding {comp['name']}. Please share the July attendance summary."})
    rec2 = r["record"]
    print("4 content:", rec2["status"], "|", rec2["company_match_type"],
          "| possible:", rec2["possible_company"], rec2["confidences"].get("company"))
    a2 = rec2["audit_id"]

    # 5. historical email → IGNORED
    r = call("/email-agent/sandbox-ingest", tok, "POST", {
        "sender_email": "hr@kankani-test.com", "subject": "Old mail",
        "body": "old", "received_at": "2026-08-01T05:00:00+00:00"})
    print("5 historical:", r["record"]["status"], "(expect IGNORED_HISTORICAL)")

    # 6. dashboard / list / detail / report / company summary
    d = call("/email-agent/dashboard", tok)
    print("6 dashboard total:", d["total"], "| by_status:", d["by_status"])
    lst = call("/email-agent/emails?limit=10", tok)
    print("   list:", lst["total"])
    det = call(f"/email-agent/emails/{a1}", tok)
    print("   detail timeline steps:", [t["step"] for t in det["timeline"]])
    rep = call("/email-agent/daily-report", tok)
    print("   daily report total:", rep["total"], "| companies:", rep["by_company"][:3])
    cs = call("/email-agent/company-summary", tok)
    print("   company summary:", cs["companies"][:2])

    # 7. manual assign company on the gmail one (if not auto-linked)
    r = call(f"/email-agent/emails/{a2}/assign-company", tok, "POST",
             {"company_id": comp["company_id"]})
    print("7 manual assign:", r)

    # cleanup
    await db.email_audit_records.delete_many({"sandbox": True})
    if reg_id:
        await db.company_email_registry.delete_one({"registry_id": reg_id})
    await db.email_agent_state.update_one({"_singleton": True}, {"$set": {"sandbox": False}})
    await db.user_sessions.delete_one({"session_token": tok})
    print("cleaned. DONE")

asyncio.run(main())
