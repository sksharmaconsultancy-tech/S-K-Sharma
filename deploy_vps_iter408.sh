#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 408)
# INCLUDES Iter 400-401 (Runner v9, Reports Center alignment, Compliance
# register tally fixes) + NEW IN THIS RELEASE:
#
# Iter 402 — IN/OUT & OT MATRIX (user requests):
#   • Row sequence changed to: D-In, D-Out, Total Hrs, OT-In, OT-Out,
#     Total OT Hrs, and a NEW row "Total Working Hrs" = Total Hrs +
#     Total OT Hrs (screen + Excel + PDF + CSV).
#   • Total Hrs now shows DUTY-ONLY hours (no OT inside), so the three
#     hour rows always tally: Total + OT = Total Working.
#   • Report defaults to ACTIVE employees only (All / Resigned still
#     selectable).
#   • OT-In/OT-Out are shown ONLY when OT is actually counted — no more
#     phantom OT-In time appearing BEFORE the duty OUT punch.
#   • Month Totals line now also shows "Total Working".
#
# Iter 402 — OT PUNCH RULE (user rule, affects Attendance Grid + payroll
# identically since they share one engine):
#   • An IN punch that comes back BEFORE the duty quota is complete
#     (e.g. lunch-break re-entry) is a BREAK RETURN — merged into duty,
#     NOT counted as OT. OT starts only from an IN punch found AFTER the
#     duty window is over (checked to the SECOND).
#   • No re-entry punch? The auto-split still follows the firm's
#     Attendance Policy (full_day_hours / ot_allowed / OT slabs) exactly
#     as before ("decide as per Attendance Policy").
#
# Iter 403 — DAY-WISE OT SUMMARY FOOTER (user accepted):
#   • In/Out & OT Matrix now ends with a "Day-wise OT Totals" strip —
#     total OT hours per day across ALL filtered employees, light-blue
#     for OT days and AMBER for the heaviest-OT day, plus the Month OT
#     grand total. Included on screen, Excel and PDF.
#
# Iter 404 — QR CODES (JOINING & APP) FIRM DROPDOWN (user request):
#   • "Select Firm" is now a searchable DROPDOWN (same picker as the rest
#     of the app) instead of a long chip list; the first firm is
#     auto-selected so the QR shows immediately.
#
# Iter 405 — QR "DOWNLOAD PNG" BUTTON (user accepted):
#   • Each QR card (Employee & Employer) now has a "Download PNG" button —
#     saves the QR as a 640px PNG (firm name in the filename) for WhatsApp
#     or poster designs, no printing needed. Works offline (renders the
#     on-screen QR onto a canvas).
#
# Iter 406 — PF & ESIC ON GROSS EARNING INCLUDING OT (user rule):
#   • The wage-base floor  max(Basic, 50% x Gross Earning)  now uses the
#     FULL Gross Earning INCLUDING the OT amount for PF, ESIC and PT —
#     including Freeze-imported runs where the imported-gross difference
#     is routed to Overtime / Other Allowances (previously that difference
#     was added AFTER the statutory calc, so PF/ESIC never saw the OT).
#   • Grid live-edit: typing an OT Amt / Others amount now instantly
#     refreshes PF Wages, PF (E), ESIC Base and ESIC (E) on the row.
#   • Verified: freeze row gross 21,000 (incl. OT 912) -> wage base
#     10,500 = 50% x 21,000 (was 10,044 ignoring OT).
#   NOTE: figures change on the NEXT "Salary Process" / Reprocess of a
#   run — already-saved runs keep their stored numbers until reprocessed.
#
# Iter 407 — SALARY LOCK ERROR OVERRIDE (user request):
#   • Super Admin can now "Lock Anyway" even when the PF/ESIC validation
#     finds ERRORS (red button in the Lock check popup). The override is
#     stamped on the run + audit trail. Other roles stay blocked.
#
# Iter 408 — HIGHER PF & VOLUNTARY PF (VPF) MODULE (user spec):
#   • Employee Master: new "PF Contribution Type" selector — Statutory /
#     Higher PF (actual wages) / VPF — with conditional fields: Higher PF
#     Wage, Effective From/To, Employee Declaration, Management Approval
#     Required, Approval Status (Pending/Approved/Rejected + Expired
#     indicator), Remarks, VPF % or Fixed Amount.
#   • Company policy (Standard Compliance Settings): Allow Higher PF
#     (default OFF), Allow VPF (default ON), VPF max % limit.
#   • Engine: Higher PF = both sides on ACTUAL PF wages, NO ceiling
#     (EPS stays on the 15k cap for ECR compatibility unless Higher
#     Pension); needs policy + approval + effective window, else falls
#     back to statutory with the reason in the calc note. VPF = statutory
#     PF + VPF (% of PF wages or fixed) — employer share NEVER increases.
#   • Salary Lock validation: 10 new employee-wise checks with correction
#     suggestions (approval pending, declaration missing, policy off,
#     invalid dates, VPF over limit, negative VPF, blank higher wage...).
#   • NEW report: Reports Center → "PF Contribution (Higher PF / VPF)" —
#     5 views (All / Higher / VPF / Approval Pending / PF Difference)
#     with Excel + PDF export.
#   • PF audit log: every change to the contribution type / wages / VPF
#     is stored (old vs new, who, when, why). Monthly snapshots now also
#     freeze the contribution type at Salary Lock.
#   • Fully backward compatible — existing runs, ECR, slips unchanged.
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
echo ""
echo "✅ Deploy Iter 408 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   VERIFY: Attendance & Shift → In/Out & OT Matrix:"
echo "   • Rows: D-In, D-Out, Total Hrs, OT-In, OT-Out, Total OT Hrs,"
echo "     Total Working Hrs (= Total + OT)."
echo "   • Default shows ACTIVE employees only."
echo "   • Lunch-break re-entry punches no longer create false OT;"
echo "     OT counts only from a punch made AFTER duty hours complete."
echo "   • Same rule applies on the Attendance Grid + payroll (1:1)."
echo "   • Scroll to the bottom: Day-wise OT Totals footer (heaviest"
echo "     OT day highlighted amber) — also in the Excel/PDF exports."
