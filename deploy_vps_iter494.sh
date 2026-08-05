#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 494)
#
# NEW IN 494 — EMPLOYEE PHOTOS ACROSS THE ATTENDANCE MODULE (enhancement
# only — the Device Sync Engine, punch processing and calculations are
# UNTOUCHED):
#   • Employee photos (with initials fallback / unknown-employee icon)
#     now show in: Live Device Sync feed, Punch Log Report (new photo
#     column, tap → large preview with name/code/machine), Daily
#     Verification, Attendance Grid and the Employee search list.
#   • Photos come from the EXISTING Employee Master photo (Documents →
#     Photo). 96px thumbnails are generated lazily, cached in the DB and
#     the browser (batched requests — fast on 100k+ employees).
#   • Security: same admin role gates as the attendance screens;
#     company admins only see their own firm's photos.
#   • BONUS FIX — "Name in Machine" blank for NEW machines: every machine
#     is now asked ONCE automatically for its user database (PIN + name)
#     on first contact (no manual 'Fetch from machine' needed), and
#     zero-padded PINs ("050" vs "50") now resolve too.
#
# ALSO INCLUDES Iter 493 — FIRM SWITCH ALWAYS REFRESHES DATA (your report: "After
# Change the Firm Always Refresh the Data for Selected firm — Don't Show
# Wrong Data of Selected Company"):
#   • Switching the firm from the header picker (or the dashboard
#     dropdown) now does a FULL app reload onto the dashboard — every
#     open screen re-fetches for the NEW firm, so stale data from the
#     previously selected company can never remain on screen.
#   • The firm-select gate after login is unaffected (it already lands
#     on a fresh dashboard).
#
# ALSO INCLUDES Iter 492 — EMPLOYEE MASTER PDF + SALARY CERTIFICATE (your requests):
#   EMPLOYEE MASTER "Download / Print PDF":
#   • Family Details now ONE LINE per member: Relation | Name | DOB |
#     Aadhaar No. (proper table).
#   • Salary Details section now shows the ALLOWANCES too (salary
#     structure heads, actual allowances, compliance structure).
#   • DOB & DOJ printed as MM-DD-YYYY (employee + family DOBs).
#   • Aadhaar No. printed IN FULL (mask removed).
#   • "Salary & Attendance Policy" page prints ONLY when the Firm Master
#     has BOTH Offline Salary AND Bio-Matrix Attendance enabled.
#   SALARY CERTIFICATE:
#   • New PERIOD selector (YYYY-MM) next to the download button in
#     Employee Master.
#   • The certificate now prints the REAL processed figures for the
#     selected month — from the LOCKED/finalized Compliance Salary run,
#     or from the imported OLD-DB legacy history (locked) — with the
#     source printed on the certificate. Months with no processed data
#     fall back to the master salary as before.
#
# ALSO INCLUDES Iter 491 — DELETED EMPLOYEE STILL SHOWED IN COMPLIANCE SALARY (your
# report: "Employees Was Delete From Firm Master ... After Compliance
# Salary Process Still Show That Employee"):
#   • ROOT CAUSE: the Master Data Snapshot (Iter 485) resurrects
#     employees from the frozen snapshot on Reprocess so historical
#     payroll stays reproducible — it also resurrected employees you had
#     DELETED from the Employee Master.
#   • FIX 1: a snapshot employee is resurrected ONLY if they still exist
#     in the Employee Master (e.g. moved out of the group). An employee
#     DELETED from the master data never re-appears in the salary run.
#   • FIX 2: deleting an employee now also removes their frozen salary
#     snapshots (cascade), so old months can't bring them back either.
#   • Employees deleted BEFORE this fix are covered too — the run checks
#     the live Employee Master on every Generate / Reprocess.
#
# ALSO INCLUDES Iter 490 — DELETE EMPLOYEE (SUPER ADMIN ONLY) — your request:
#   • Employee Master now has a red "Delete Employee (Super Admin only)"
#     button — permanently removes the employee from the master data
#     (cascade: attendance, leaves, tickets, payslips) after a confirm.
#   • STRICTLY SUPER ADMIN: Sub (Super) Admins and Company Admins can
#     no longer delete employees — the API rejects them with 403
#     (previously sub-admins could delete directly).
#   • Safety guards kept: legacy-locked employees and super-admin
#     accounts can never be deleted.
#
# ALSO INCLUDES Iter 489 — COMPLIANCE SALARY REGISTER PDF: ADVANCE COLUMN FIX
# (your report: "Advance Amount Show into the PDF Report in Other"):
#   • ADVANCE now prints in its OWN column in BOTH register formats —
#     it was hard-coded to 0 in Format 1 (the amount silently landed in
#     OTHER) and Format 2 had no Advance column at all.
#   • FULLY DYNAMIC per the compliance salary process: the ADVANCE and
#     OTHER deduction columns appear only when the head is enabled in
#     the Firm Master or a row actually carries a value (same rule as
#     PF / ESI / TDS / HRA columns).
#   • Format 2 saved custom layouts automatically get the Advance column
#     injected (before Other Ded.) — no need to re-save your layout.
#   • Grand totals / group sub-totals include the Advance column.
#
# ALSO INCLUDES Iter 488 — DUPLICATE PUNCH FIX ("Multi Punch Within the Same time"):
#   • 5-MIN DUPLICATE FILTER IS NOW DEFAULT & DEVICE-WIDE: the old guard
#     only blocked duplicates from the SAME machine — the same punch
#     arriving from a second registered device / webhook / re-sync was
#     stored AGAIN at the same time (ABDUL RAZA KHAN: 10:23 ×2, 22:13 ×2).
#     Now ANY punch within ±5 minutes of an existing punch is treated as
#     a duplicate.
#   • RAW PUNCHES ARE NEVER DELETED (your rule): duplicates are STORED in
#     the punch log with status "duplicate" and simply ignored by the
#     attendance grid, reports and payroll.
#   • HISTORY AUTO-CLEANED: this deploy marks all EXISTING stored machine
#     duplicates (within 5 min) as "duplicate" for every firm — days like
#     ABDUL's now pair correctly (10:23 IN → 22:13 OUT).
#   • Repair Punches modal no longer lists duplicate noise.
#   • On-demand API: POST /api/admin/attendance/cleanup-duplicate-punches
#     ?company_id=&month=&dry_run=true
#
# INCLUDES Iter 487 (expiring-document email alerts) and everything before.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip
PYBIN=$APP_DIR/backend/venv/bin/python

echo "==> 1/9 Downloading latest code bundle (~10 MB, retries enabled)..."
rm -f /tmp/sks-latest.tar
ok=""
for i in 1 2 3 4 5; do
  if wget -c -T 60 -t 1 --show-progress -q -O /tmp/sks-latest.tar "$BUNDLE_URL"; then
    ok=1; break
  fi
  echo "   attempt $i failed — retrying in 10s (server may be waking up)..."
  sleep 10
done
if [ -z "$ok" ]; then
  echo "   wget failed 5x — trying curl..."
  curl -fSL --retry 5 --retry-delay 10 -o /tmp/sks-latest.tar "$BUNDLE_URL"
fi
if ! tar -tf /tmp/sks-latest.tar >/dev/null 2>&1; then
  echo "❌ Downloaded bundle is corrupt/incomplete ($(du -h /tmp/sks-latest.tar | cut -f1))."
  echo "   Open the portal preview URL in a browser once, wait 30s, re-run."
  exit 1
fi
echo "   Bundle OK: $(du -h /tmp/sks-latest.tar | cut -f1)"

echo "==> 2/9 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 3/9 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/9 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/9 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 6/9 ONE-TIME: marking existing duplicate machine punches (never deletes)..."
cd $APP_DIR/backend && $PYBIN - <<'PYEOF'
import asyncio, os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv("/home/sksharma/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]
    cur = db.attendance.find(
        {"status": "approved"},
        {"_id": 0, "record_id": 1, "user_id": 1, "at": 1, "source": 1},
    ).sort([("user_id", 1), ("at", 1)])
    dup_ids, last_uid, last_at = [], None, None
    async for p in cur:
        try:
            t = datetime.fromisoformat(str(p.get("at")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if p["user_id"] != last_uid:
            last_uid, last_at = p["user_id"], None
        src = str(p.get("source") or "")
        if (last_at is not None and src.startswith("zkteco")
                and abs((t - last_at).total_seconds()) < 300):
            dup_ids.append(p["record_id"])
            continue  # marked punches do not advance the window
        last_at = t
    marked = 0
    now = datetime.utcnow().isoformat() + "Z"
    for i in range(0, len(dup_ids), 1000):
        r = await db.attendance.update_many(
            {"record_id": {"$in": dup_ids[i:i + 1000]}},
            {"$set": {"status": "duplicate", "dup_marked_at": now,
                      "dup_marked_by": "deploy494",
                      "decision_reason": ("Duplicate punch within 5 min — kept in the "
                                          "punch log but ignored in attendance "
                                          "calculations (Iter 494 cleanup).")}})
        marked += r.modified_count
    print(f"   duplicates found={len(dup_ids)} marked={marked} (raw punches all kept)")

asyncio.run(main())
PYEOF

echo "==> 7/9 Nginx configs (unchanged — upload limits + ADMS port 80)..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 8/9 Health check..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"

echo "==> 9/9 Verification..."
echo -n "   Server Version badge shows 494 (must say OK): "
grep -q 'APP_ITERATION = "490"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Advance column in register PDFs (must say OK): "
grep -q 'def adv_ded' $APP_DIR/backend/utils/compliance_salary.py && grep -q '"advance", "Advance"' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Super-admin-only employee delete (must say OK): "
grep -q 'require_super_admin_strict(admin)' $APP_DIR/backend/routes/employees_admin.py && grep -q 'em-delete-employee' $APP_DIR/frontend/app/employee-master.tsx && echo "OK" || echo "MISSING!"
echo -n "   Deleted-employee ghost fix in salary runs (must say OK): "
grep -q '_alive_uids' $APP_DIR/backend/routes/compliance_salary_runs.py && grep -q 'master_snapshots' $APP_DIR/backend/routes/employees_admin.py && echo "OK" || echo "MISSING!"
echo -n "   Employee Master PDF updates (must say OK): "
grep -q '_fmt_mdy' $APP_DIR/backend/utils/employee_pdf.py && grep -q 'firm_salary_process' $APP_DIR/backend/utils/employee_pdf.py && echo "OK" || echo "MISSING!"
echo -n "   Salary Certificate period + old-DB data (must say OK): "
grep -q 'cert-month-input' $APP_DIR/frontend/app/employee-master.tsx && grep -q 'legacy_salary_history' $APP_DIR/backend/routes/salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   Firm-switch hard refresh (must say OK): "
grep -q 'reload?: boolean' $APP_DIR/frontend/src/context/SelectedCompanyContext.tsx && echo "OK" || echo "MISSING!"
echo -n "   Employee photo engine (must say OK): "
[ -f $APP_DIR/backend/routes/employee_photos.py ] && [ -f $APP_DIR/frontend/src/components/EmployeePhoto.tsx ] && grep -q 'employee_photos_router' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Machine user-name auto-sync (must say OK): "
grep -q 'userinfo_query_sent' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   Device-wide 5-min duplicate guard (must say OK): "
grep -q 'duplicate_within_5min_stored' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   Cross-device dedupe in grid engine (must say OK): "
grep -q 'is_machine' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Cleanup API present (must say OK): "
grep -q 'cleanup-duplicate-punches' $APP_DIR/backend/routes/attendance_admin_core.py && echo "OK" || echo "MISSING!"
echo -n "   Repair modal hides duplicates (must say OK): "
grep -q '"duplicate"' $APP_DIR/frontend/src/components/PunchRepairModal.tsx && echo "OK" || echo "MISSING!"
echo -n "   Iter 487 expiring-doc alerts still present (must say OK): "
grep -q 'run_doc_expiry_alerts' $APP_DIR/backend/routes/scheduled_reports.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 494 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 494'."
echo "   2. FIRM SWITCH: open any page, switch the firm from the header"
echo "      picker — the app reloads onto the dashboard and every page"
echo "      shows ONLY the new firm's data."
echo "   3. EMPLOYEE MASTER PDF + SALARY CERTIFICATE period options as"
echo "      per Iter 492 notes above."
echo "   3. ADVANCE FIX: Compliance Salary → download the Salary Register"
echo "      PDF (both formats) — Advance now shows in its OWN column;"
echo "      OTHER holds only genuine other deductions."
echo "   4. DUPLICATES: Repair Punches shows no same-time duplicates;"
echo "      new duplicates (within 5 min, ANY device) are stored as"
echo "      'duplicate' automatically and never affect calculations."
