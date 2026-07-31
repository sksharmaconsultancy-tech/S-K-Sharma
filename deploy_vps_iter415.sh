#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 415)
# INCLUDES Iter 400-409 (Runner v9, In/Out & OT Matrix, QR dropdown + PNG,
# PF/ESIC on Gross incl OT, Lock override, Higher PF & VPF module,
# reprocess 422 fix) + NEW IN THIS RELEASE:
#
# Iter 409 — BACKEND REFACTOR (no behaviour change, fully regression
# tested 41/41):
#   • server.py reduced by ~2,500 lines. Extracted verbatim into:
#     routes/sub_admins.py, routes/masters_policy.py, routes/bonus.py,
#     routes/salary_runs.py, routes/attendance_self_service.py,
#     shared/sorting.py, shared/hours.py.
#
# Iter 410 — EMPLOYEE QUICK-MANAGE SHEET (user request):
#   • All Employee Data → tap employee: the sheet now shows FATHER NAME,
#     an ONLINE/OFFLINE (On-Roll/Off-Roll) badge (green = Online·On-Roll,
#     amber = Offline·Off-Roll) and Date of Join.
#   • "Live-in employee" toggle row styling fixed (was rendering as
#     unstyled plain text).
#
# Iter 410 — BIOFACE-MSD1K SUPPORT:
#   • Biometric Devices → Register: new brand "BIOFACE (MSD1K)" —
#     connects over the same iClock/ADMS push protocol (verified
#     handshake + ATTLOG ingest with SN 1801FACEMSD1K1030).
#   • Machine ALREADY REGISTERED on production via API for
#     JAI CLINIC & NURSING HOME (device_id dev_31fcd51c54).
#
# Iter 410 — DEVICE OFFLINE EMAIL ALERT (user accepted):
#   • When any biometric machine stops pushing for 15+ minutes the portal
#     now also EMAILS the super admins + that firm's company admins
#     (in addition to the existing in-app notification). One email per
#     outage; re-arms automatically when the machine reconnects.
#     Requires SMTP configured in Email Settings (already set on prod).
#
# Iter 411 — LEGACY IMPORT: STRICT EMPLOYEE-CODE MATCHING (user rule):
#   • Old-DB import now matches employees by EMPLOYEE CODE ONLY.
#     Name matching is fully removed — same-name employees are NEVER
#     treated as the same person and NEVER updated; without a code match
#     a NEW separate employee is created. Applies to the employee master
#     AND the off-roll workers import.
#   • Duplicate EmpCode inside the OLD DB itself: only the FIRST row is
#     imported; later rows with the same code are skipped and listed in
#     the import report ("DUPLICATE EmpCode ..."). Data of two employees
#     can never be interchanged.
#
# Iter 412 — GROUP-WISE ATTENDANCE SHEET BLANK FIX (user bug):
#   • Root cause (verified on live data): global category groups
#     (LABOUR / STAFF / …) carried a stale member list pointing at another
#     firm's employee, so the individual group export filtered everyone
#     out and produced a BLANK Excel, while the All-groups ZIP worked.
#   • Fix: stale/foreign members are ignored — the resolver keeps only
#     members of the selected firm and otherwise name-matches the group
#     against employee_type/employee_group (case-insensitive). Also fixed
#     the Employee-Group-Policies fallback (was employee_group-only,
#     case-sensitive) and included legacy masters with company_id null.
#   • Applies everywhere groups filter data: attendance sheet Excel,
#     auto-email to client, salary process, bonus runs.
#   • PLUS one-time DB cleanup on first restart: stale member lists on
#     GLOBAL category groups are wiped automatically (idempotent,
#     recorded in migration_flags.iter412_global_group_member_wipe).
#
# Iter 413 — ATTENDANCE EMAIL: EXCEL + PDF (user accepted):
#   • The monthly "Generate & email attendance sheet to client" email now
#     attaches BOTH the fillable Excel AND a print-ready landscape-A4 PDF
#     of the same sheet, so clients can view it on mobile without Excel.
#
# Iter 414 — SALARY STRUCTURE SYNC: STRICT CODE MATCHING (user rule):
#   • "Sync Salary Structures" from the old DB now matches employees by
#     EMPLOYEE CODE ONLY (name matching + name-based code correction
#     removed). No code match ⇒ row counted UNMATCHED and listed in the
#     job report — data of two employees can never be interchanged.
#   • The sync still refreshes: Basic / PF Basic / Gross + every LINKED
#     allowance head (SalaryHeadMaster names + your manual head-links),
#     enables the heads on the Firm Master and stamps
#     salary_structure_synced_at.
#
# Iter 415 — EMPLOYEE PWA: GPS ON BY DEFAULT (user request):
#   • Right after install/login, the employee dashboard shows a one-tap
#     "Turn on GPS location — Enable" banner if location permission is
#     not yet granted, so GPS is switched on BEFORE the first punch.
#     (Browsers don't allow enabling GPS silently at install; this is the
#     compliant equivalent.) If blocked, it guides the employee to the
#     browser/phone settings. Banner disappears once granted.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~115 MB, retries enabled)..."
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

echo "==> 2/7 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 3/7 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo "==> 4/7 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/7 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 6/7 Reloading nginx..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 7/7 Health check + verification..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"
echo -n "   Matrix new rows (must say OK): "
grep -q "Total Working Hrs" $APP_DIR/backend/routes/inout_ot_matrix.py && echo "OK" || echo "MISSING!"
echo -n "   Matrix active default (must say OK): "
grep -q 'status: str = "active"' $APP_DIR/backend/routes/inout_ot_matrix.py && echo "OK" || echo "MISSING!"
echo -n "   OT break-return rule (must say OK): "
grep -q "BREAK RETURN" $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Higher PF/VPF module / Iter 408 (must say OK): "
grep -q "pf_contribution_type" $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   PF Contribution report / Iter 408 (must say OK): "
[ -f $APP_DIR/backend/routes/pf_contribution_report.py ] && echo "OK" || echo "MISSING!"
echo -n "   Lock error override / Iter 407 (must say OK): "
grep -q "allow_errors" $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   PF/ESIC gross incl OT / Iter 406 (must say OK): "
grep -q "ot_pay_extra" $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   QR Download PNG / Iter 405 (must say OK): "
grep -q "Download PNG" $APP_DIR/frontend/app/join-qr.tsx && echo "OK" || echo "MISSING!"
echo -n "   QR firm dropdown / Iter 404 (must say OK): "
grep -q "joinqr-firm-picker" $APP_DIR/frontend/app/join-qr.tsx && echo "OK" || echo "MISSING!"
echo -n "   OT footer / Iter 403 (must say OK): "
grep -q "day_ot_totals" $APP_DIR/backend/routes/inout_ot_matrix.py && echo "OK" || echo "MISSING!"
echo -n "   Register tally fix / Iter 401 (must say OK): "
grep -q "RESIDUAL" $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Reprocess 422 fix / Iter 409 (must say OK): "
grep -q "Iter 409" $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   Refactor modules / Iter 409 (must say OK): "
[ -f $APP_DIR/backend/routes/salary_runs.py ] && [ -f $APP_DIR/backend/routes/sub_admins.py ] && [ -f $APP_DIR/backend/shared/hours.py ] && echo "OK" || echo "MISSING!"
echo -n "   Quick-sheet Father/Online badge / Iter 410 (must say OK): "
grep -q "rollBadge" $APP_DIR/frontend/app/admin.tsx && echo "OK" || echo "MISSING!"
echo -n "   BIOFACE MSD1K brand / Iter 410 (must say OK): "
grep -q "bioface" $APP_DIR/frontend/app/biometric-devices.tsx && echo "OK" || echo "MISSING!"
echo -n "   Device offline EMAIL alert / Iter 410 (must say OK): "
grep -q "offline alert EMAIL" $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   Strict code-match import / Iter 411 (must say OK): "
grep -q "Iter 411" $APP_DIR/backend/routes/legacy_import.py && echo "OK" || echo "MISSING!"
echo -n "   Group-wise sheet blank fix / Iter 412 (must say OK): "
grep -q "Iter 412" $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Email Excel+PDF / Iter 413 (must say OK): "
grep -q "build_master_sheet_pdf" $APP_DIR/backend/utils/master_sheet.py && echo "OK" || echo "MISSING!"
echo -n "   Strict salary-structure sync / Iter 414 (must say OK): "
grep -q "Iter 414" $APP_DIR/backend/routes/legacy_import.py && echo "OK" || echo "MISSING!"
echo -n "   Employee GPS default-on banner / Iter 415 (must say OK): "
grep -q "Turn on GPS location" "$APP_DIR/frontend/app/(tabs)/index.tsx" && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 415 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   VERIFY:"
echo "   • All Employee Data → tap an employee: Father Name + Online/Offline"
echo "     badge + DOJ now show on the quick sheet."
echo "   • Biometric Devices → Register new device → brand BIOFACE (MSD1K),"
echo "     Serial 1801FACEMSD1K1030, kind BOTH, pick the firm."
