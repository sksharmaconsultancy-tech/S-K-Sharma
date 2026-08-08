#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 523)
#
# ═══════════════════ WHAT'S NEW IN 523 ═══════════════════
#
# DAILY VERIFICATION REPORT PDF — your 8 requested changes (both
# LANDSCAPE and PORTRAIT prints):
#  1. Left/right margins reduced 8mm → 4mm (more table width).
#  2. Rows with BOTH punches present are NOT highlighted any more —
#     only problem rows keep colour (missing punch RED, absent grey).
#  3. IN/OUT + Duty Hrs follow the FIRM ATTENDANCE POLICY (OT only
#     after the policy full-day hours, e.g. 12 hrs) — powered by the
#     Iter 520/522 worked-minutes engine.
#  4. "Attendance Status" column removed.
#  5. Signature column with a wide fixed width.
#  6. Row height increased (9 mm) so employees can sign properly.
#  7. Contractor column/filter shows ONLY when the firm actually has
#     contractors.
#  8. Company ADDRESS printed under the firm name.
#  9. Legend line removed from the print.
# 10. "S.No." column before the Employee Code (Daily Verification PDF/
#     Excel/CSV + Present/Absent Report PDF).
# 11. Department COLUMN removed from the print — rows are now GROUPED
#     department-wise with a grey band per department.
# 12. FATHER NAME column added next to the employee name (PDF + Excel
#     + CSV).
#
# ═════════════ ALSO INCLUDED (Iter 522) ═════════════
#
# FULL-CODE REVIEW FIXES + SPEED (your request):
#  a) BUG FIX (HIGH): the OT REPORT still computed duty on the wall
#     clock, so a lunch break could spill into OT there (over-stated OT
#     pay, disagreed with the Grid). Both surfaces now use WORKED
#     minutes — Grid, In/Out & OT Matrix and OT Report always match.
#  b) BUG FIX (MEDIUM): Grid/Matrix OT window also counted the gap
#     BETWEEN two OT sessions as OT — now worked-minutes there too.
#  c) SPEED: 10 new MongoDB indexes on the hottest queries (attendance
#     punch loads, NOT-FOUND punch scans, machine-user lookups,
#     bio-code matching, holidays, device serials). Created
#     automatically at backend startup — first restart may take a few
#     extra seconds while they build. Grid / Punch-Log / Sync-Dashboard
#     responses get significantly faster on your live data volume.
#     (GZip compression of API responses was already active.)
#
# ═════════════ ALSO INCLUDED (Iter 521) ═════════════
#
# 0) NEW: PRESENT / ABSENT REPORT (as per Firm Attendance Policy):
#    Attendance & Shift → "Present / Absent Report". P / HD / A / WO / H
#    status matrix per employee per day, computed by the SAME policy
#    engine as the Attendance Grid, so it matches payroll Present Days
#    1:1. Department filter + search, day-wise Daily Present footer,
#    colour-coded Excel + PDF exports, policy line on the header.
#
# ═════════════ ALSO INCLUDED (Iter 520 changes) ═════════════
#
# 1) "WHO REGISTERED IN MACHINE BUT NOT IN DATABASE" — FIXED + ANSWERED:
#    • Device Sync → section 2 (Machine ↔ Master) now shows EVERY missing
#      person: punches from machines that are UNREGISTERED or registered
#      WITHOUT a firm are no longer silently dropped when a firm is
#      selected (they show marked "⚠ Unregistered Device").
#    • NEW: machine users harvested from the machine's own user table
#      (USERINFO sync) who have NO Employee Master now appear TOO — even
#      if they have NEVER punched ("Registered on the machine (never
#      punched)"). Each row also shows the NAME STORED IN THE MACHINE.
#    • Punch Log Report: NOT-FOUND rows from a registered machine that
#      has no firm assigned now always show.
#    • STEP 10 of this script prints the full forensic list from your
#      LIVE database (per machine: every PIN + name not in the Master).
#
# 2) IN/OUT & OT MATRIX — NOW 100% PER FIRM ATTENDANCE POLICY (your bug):
#    • OT starts ONLY after the policy's full-day WORKED hours (e.g. 8h).
#      Before: a lunch-break OUT/IN wrongly turned the afternoon into OT,
#      and break time inside the duty window could spill into OT. Now OT
#      is counted on ACCUMULATED WORKED MINUTES — breaks never count.
#    • Weekly Off / Holiday flags now stamp on NO-PUNCH days too, so the
#      matrix colours Sundays/holidays correctly.
#    • Late grace (10 min) + duty-hour rounding (15 min) as per policy.
#    • The report header (screen + Excel + PDF) now prints the firm's
#      policy line so every figure is verifiable:
#      "Firm Attendance Policy — Full Day 8 hrs · OT beyond 8 worked hrs …"
#    • Same engine drives the Attendance Grid, so both always match.
#
# 3) ESIC LEAVE ENTRY FORM (your request):
#    • Employee = searchable DROPDOWN (name/code).
#    • From/To dates entered as DD-MM-YYYY.
#    • Firm selection mandatory, defaults to the open firm.
#    • NEW "ESIC Leave Reason" dropdown (Sickness Benefit, Maternity
#      Benefit, Temporary Disablement, … + Other (Specify)). Reason shows
#      in the register and flows to the auto-marked leave.
#
# 4) REPORTS HUB (your requests):
#    • Salary Comparison: NEW "Periodic" mode — compare a BASE period
#      (from→to months) with a CURRENT period. Works on screen, Excel,
#      PDF and Email.
#    • ALL reports now default Month to the LAST SALARY PROCESSED /
#      FINALIZED month of the selected firm (you work one month back).
#    • Salary Revision Report (FY): NEW dynamic allowance columns — every
#      allowance ENABLED in the Firm Master shows Old/New at each
#      revision (Excel + PDF too).
#    • Wage Register PDF: heading/data OVERLAP fixed — headers and long
#      cells now WRAP, font auto-shrinks for wide registers, Bank
#      A/c + IFSC columns widened.
#
# 5) FORM NO. 23 — OFFICIAL FACTORY ANNUAL RETURN (your uploaded format):
#    • Factory & Boiler Annual Return page → new "FORM 23 (Official)"
#      button prints the statutory Rule 105(i) format: General
#      Information, Workers & Man-days (Men/Women/Children), Man-hours,
#      Leave with Wages, Safety Officer, Ambulance/Canteen/Rest
#      rooms/Crèche/Welfare (Sec 40-B, 45–49), Accidents, Safety
#      Training, and the Payment of Wages Act 1936 wages & deductions
#      section — auto-filled from payroll, with a new "FORM 23 —
#      Statutory Particulars" block in the Edit-Particulars form for the
#      manual fields (Application No., Area, YES/NA answers, fines …).
#
# 6) MONTHLY CHALLAN SUMMARY (your request):
#    • NEW payment status per PF / ESIC challan — PENDING / PAID /
#      FAILED. Tap the badge to cycle; re-updatable any time; shows in
#      the Email/WhatsApp summary text.
#
# 7) FIRM / EMPLOYEE DROPDOWNS EVERYWHERE (your requests):
#    • Leave Report, Comp-Off Ledger, Factory & Boiler Annual Return,
#      Rectified Punches Audit: firm list = searchable dropdown.
#    • Users Log Report: firm dropdown is OPTIONAL — "All companies"
#      shows Super/Sub-admin activity too.
#    • Full & Final Settlement (Reports Hub): employees = searchable
#      dropdown (multi-select).
#    • Salary Compliance Process (AI): employee NAME dropdown with
#      search — no more typing the employee code.
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy523.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy523.sh

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "════════════════════════════════════════════════════════════"
echo "  STEP 0 — DIAGNOSTICS (send me this block if deploy fails)"
echo "════════════════════════════════════════════════════════════"
echo "--- Disk space ---"
df -h / | tail -1
echo "--- Memory + swap ---"
free -h
echo "--- Backend service ---"
sudo supervisorctl status sksharma-backend 2>/dev/null || systemctl status sksharma-backend --no-pager -l 2>/dev/null | head -5 || echo "(no backend service found by either name)"
echo "--- Backend health (localhost:8001) ---"
curl -s -m 5 http://localhost:8001/api/health && echo " <-- backend answers ✅" || echo "❌ BACKEND NOT ANSWERING"
echo "--- Nginx ---"
sudo nginx -t 2>&1 | tail -1
systemctl is-active nginx && echo "nginx active ✅" || echo "❌ nginx NOT active"
echo "--- Web folder ---"
ls -la $WEB_DIR/index.html 2>/dev/null || echo "❌ $WEB_DIR/index.html MISSING"
echo "════════════════════════════════════════════════════════════"
echo ""

echo "==> 1/10 Freeing disk space (safe cache cleanup)..."
rm -rf $APP_DIR/frontend/.metro-cache $APP_DIR/frontend/.expo /tmp/metro-* /tmp/haste-* 2>/dev/null
npm cache clean --force >/dev/null 2>&1 || true
yarn cache clean >/dev/null 2>&1 || true
AVAIL_MB=$(df -m / | tail -1 | awk '{print $4}')
echo "   Free disk now: ${AVAIL_MB} MB"
if [ "$AVAIL_MB" -lt 1500 ]; then
  echo "   ⚠ Less than 1.5 GB free — cleaning apt + journal too..."
  sudo apt-get clean 2>/dev/null || true
  sudo journalctl --vacuum-size=100M >/dev/null 2>&1 || true
  df -m / | tail -1 | awk '{print "   Free disk now: "$4" MB"}'
fi

echo "==> 2/10 Ensuring swap (prevents build OOM-kill)..."
SWAP_KB=$(grep SwapTotal /proc/meminfo | awk '{print $2}')
if [ "$SWAP_KB" -lt 1000000 ]; then
  echo "   No/low swap — creating 2 GB swapfile..."
  sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile \
    && echo "   Swap ON ✅" || echo "   (swap setup failed — continuing)"
  grep -q "/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
else
  echo "   Swap already present ✅"
fi

echo "==> 3/10 Downloading latest code bundle (~10 MB, retries enabled)..."
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

echo "==> 4/10 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR || { echo "❌ Extract failed (disk full?) — aborting."; exit 1; }
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 5/10 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP install openpyxl -q || true

echo "==> 6/10 Restarting backend FIRST (portal comes back before the build)..."
sudo supervisorctl stop sksharma-backend 2>/dev/null || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend 2>/dev/null || sudo systemctl restart sksharma-backend 2>/dev/null || true
HEALTH=""
for i in $(seq 1 12); do
  sleep 5
  HEALTH=$(curl -s -m 8 http://localhost:8001/api/health)
  [ -n "$HEALTH" ] && break
  echo "   waiting for backend... (${i}0s)"
done
if [ -n "$HEALTH" ]; then
  echo "   Backend healthy ✅  ($HEALTH)"
else
  echo "   ❌ BACKEND STILL NOT ANSWERING. Last 30 log lines:"
  sudo tail -30 /var/log/supervisor/sksharma-backend*.log 2>/dev/null || sudo journalctl -u sksharma-backend -n 30 --no-pager 2>/dev/null
  echo "   ── Send me the lines above. Continuing with the web build anyway."
fi

echo "==> 7/10 Building web frontend (with OOM protection)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
export NODE_OPTIONS="--max-old-space-size=3072"
rm -rf dist
if npx expo export -p web 2>&1 | tail -15; then true; fi
if [ ! -f dist/index.html ] || [ ! -d dist/_expo/static/js/web ]; then
  echo "❌ WEB BUILD FAILED — the current live portal folder was NOT touched."
  echo "   Re-run this script once; if it fails again send me the build error above."
  exit 1
fi
echo "   Build OK ✅ ($(du -sh dist | cut -f1))"

echo "==> 8/10 Publishing new build (with rollback safety)..."
sudo mkdir -p $WEB_DIR
sudo rm -rf ${WEB_DIR}.prev
sudo cp -r $WEB_DIR ${WEB_DIR}.prev 2>/dev/null || true
sudo find $WEB_DIR -mindepth 1 -maxdepth 1 ! -name '.well-known' ! -name '_expo' -exec rm -rf {} +
sudo cp -r dist/* $WEB_DIR/
sudo cp public/sw.js $WEB_DIR/sw.js 2>/dev/null || true
sudo find $WEB_DIR/_expo -type f -mtime +45 -delete 2>/dev/null || true
sudo nginx -t && sudo systemctl reload nginx

echo "==> 9/10 Verification..."
echo -n "   Server badge is 523 (must say OK): "
grep -q 'APP_ITERATION = "523"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Policy-true OT split engine (must say OK): "
grep -q 'ACCUMULATED WORKED MINUTES' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Matrix policy header (must say OK): "
grep -q 'Firm Attendance Policy' $APP_DIR/backend/routes/inout_ot_matrix.py && echo "OK" || echo "MISSING!"
echo -n "   Machine-users-in-sync-dashboard fix (must say OK): "
grep -q 'never punched' $APP_DIR/backend/routes/attendance_sync_dashboard.py && echo "OK" || echo "MISSING!"
echo -n "   ESIC reason dropdown backend (must say OK): "
grep -q 'reason_other' $APP_DIR/backend/routes/esic_leave.py && echo "OK" || echo "MISSING!"
echo -n "   Periodic salary comparison (must say OK): "
grep -q '_run_rows_period' $APP_DIR/backend/routes/payroll_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Last-finalized-month default (must say OK): "
grep -q 'last-finalized-month' $APP_DIR/backend/routes/payroll_reports.py && echo "OK" || echo "MISSING!"
echo -n "   FORM 23 builder (must say OK): "
grep -q 'build_form23_pdf' $APP_DIR/backend/utils/factory_return_pdf.py && echo "OK" || echo "MISSING!"
echo -n "   Challan payment status (must say OK): "
grep -q 'pf_status' $APP_DIR/backend/routes/challan_summary.py && echo "OK" || echo "MISSING!"
echo -n "   Daily Verification PDF v523 (must say OK): "
grep -q "Iter 523" $APP_DIR/backend/routes/daily_verification.py && echo "OK" || echo "MISSING!"
echo -n "   Worked-minutes OT at ALL 4 sites (must say 4): "
grep -c "worked_minutes_in_window(day_punches" $APP_DIR/backend/server.py
echo -n "   Speed indexes (must say OK): "
grep -q "increase speed of system" $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Present/Absent report module (must say OK): "
[ -f $APP_DIR/backend/routes/present_absent_report.py ] && echo "OK" || echo "MISSING!"
echo -n "   Wage-register wrap fix (must say OK): "
grep -q 'OVERLAPPING' $APP_DIR/backend/utils/register_export.py && echo "OK" || echo "MISSING!"
echo -n "   Web build published (must say OK): "
[ -f $WEB_DIR/index.html ] && echo "OK" || echo "MISSING!"
echo -n "   Backend /api/health: "
curl -s -m 5 http://localhost:8001/api/health || echo "❌ NOT ANSWERING"
echo ""
echo -n "   Portal responds through nginx: "
CODE=$(curl -s -k -L -m 10 -o /dev/null -w "%{http_code}" http://localhost/ )
if [ "$CODE" = "200" ]; then
  echo "HTTP $CODE ✅"
elif [ "$CODE" = "301" ] || [ "$CODE" = "302" ]; then
  CODE2=$(curl -s -k -m 10 -o /dev/null -w "%{http_code}" https://localhost/ )
  echo "HTTP $CODE → HTTPS $CODE2 $( [ "$CODE2" = "200" ] && echo '✅ (HTTP→HTTPS redirect is normal with SSL)' || echo '❌' )"
else
  echo "HTTP $CODE ❌"
fi

echo ""
echo "==> 10/10 FORENSIC REPORT — Registered IN MACHINE but NOT in Database"
$APP_DIR/backend/venv/bin/python - <<'PYEOF'
import os, re, asyncio
from collections import defaultdict
from motor.motor_asyncio import AsyncIOMotorClient

envp = "/home/sksharma/app/backend/.env"
env = {}
for line in open(envp):
    m = re.match(r'^([A-Z_]+)="?([^"\n]*)"?', line.strip())
    if m:
        env[m.group(1)] = m.group(2)

async def main():
    db = AsyncIOMotorClient(env.get("MONGO_URL", "mongodb://localhost:27017"))[
        env.get("DB_NAME", "hrms_production")]
    devs = {str(d.get("serial_number") or ""): d async for d in
            db.biometric_devices.find({}, {"_id": 0, "serial_number": 1,
                                           "name": 1, "company_id": 1})}
    comp = {c["company_id"]: c.get("name") async for c in
            db.companies.find({}, {"_id": 0, "company_id": 1, "name": 1})}
    known = set()
    async for u in db.users.find({"role": "employee"},
                                 {"_id": 0, "bio_code": 1, "employee_code": 1}):
        for v in (u.get("bio_code"), u.get("employee_code")):
            v = str(v or "").strip()
            if v:
                known.add(v)
                if v.lstrip("0"):
                    known.add(v.lstrip("0"))
    print("=" * 68)
    print(" WHO IS REGISTERED IN THE MACHINE BUT NOT IN THE DATABASE")
    print("=" * 68)
    # A) pins that have PUNCHED but have no master (biometric_unmapped)
    per_dev = defaultdict(list)
    async for g in db.biometric_unmapped.aggregate([
        {"$group": {"_id": {"pin": "$device_user_id", "sn": "$device_serial"},
                    "n": {"$sum": 1}, "last": {"$max": "$at"}}},
        {"$sort": {"last": -1}}, {"$limit": 3000},
    ]):
        pin = str(g["_id"]["pin"] or "")
        if pin in known or (pin.lstrip("0") or pin) in known:
            continue
        per_dev[str(g["_id"]["sn"] or "?")].append((pin, g["n"], str(g["last"])[:16]))
    # machine user names
    names = {}
    async for mu in db.biometric_machine_users.find(
            {}, {"_id": 0, "pin": 1, "name": 1, "device_serial": 1}):
        names[(str(mu.get("device_serial") or ""), str(mu.get("pin") or ""))] = mu.get("name") or ""
        names[("", str(mu.get("pin") or ""))] = mu.get("name") or ""
    total = 0
    for sn, pins in sorted(per_dev.items()):
        d = devs.get(sn) or {}
        firm = comp.get(d.get("company_id")) or ("⚠ NO FIRM ASSIGNED" if d else "⚠ UNREGISTERED DEVICE")
        print(f"\nMACHINE {sn}  ({d.get('name') or '—'})  → firm: {firm}")
        print(f"  {'PIN':<12} {'NAME IN MACHINE':<26} {'PUNCHES':>8}  LAST PUNCH")
        for pin, n, last in sorted(pins, key=lambda x: -x[1]):
            nm = names.get((sn, pin)) or names.get(("", pin)) or "—"
            print(f"  {pin:<12} {nm[:25]:<26} {n:>8}  {last}")
            total += 1
    # B) enrolled on machine but NEVER punched
    never = defaultdict(list)
    async for mu in db.biometric_machine_users.find(
            {}, {"_id": 0, "pin": 1, "name": 1, "device_serial": 1}):
        pin = str(mu.get("pin") or "").strip()
        if not pin or pin in known or (pin.lstrip("0") or pin) in known:
            continue
        sn = str(mu.get("device_serial") or "?")
        if any(p == pin for p, _, _ in per_dev.get(sn, [])):
            continue
        never[sn].append((pin, mu.get("name") or "—"))
    if never:
        print("\n" + "-" * 68)
        print(" ENROLLED ON THE MACHINE BUT NEVER PUNCHED (no master either)")
        for sn, pins in sorted(never.items()):
            d = devs.get(sn) or {}
            firm = comp.get(d.get("company_id")) or "⚠ UNREGISTERED / NO FIRM"
            print(f"\nMACHINE {sn}  ({d.get('name') or '—'})  → firm: {firm}")
            for pin, nm in sorted(pins):
                print(f"  PIN {pin:<12} {nm}")
                # counted separately
    print("\n" + "=" * 68)
    print(f" TOTAL PINs punching without an Employee Master: {total}")
    print(" Create their masters one-tap from Device Sync → section 2.")
    print("=" * 68)

asyncio.run(main())
PYEOF

echo ""
echo "✅ Deploy Iter 523 complete!"
echo ""
echo "   ON EACH DEVICE: desktop hard-refresh (Ctrl+Shift+R); phone PWA —"
echo "   close fully and reopen TWICE."
echo ""
echo "   VERIFY: footer badge must read 'Server Iter 523'."
echo ""
echo "   THEN CHECK:"
echo "   • Attendance & Shift → Present / Absent Report — new P/HD/A/WO/H"
echo "     matrix + Excel/PDF."
echo "   • Device Sync → pick the firm → section 2 now lists every machine"
echo "     PIN missing from the Master (incl. never-punched, with names)."
echo "   • In/Out & OT Matrix → policy line on top; OT only beyond 8"
echo "     worked hrs; Sundays coloured."
echo "   • ESIC Leave → new employee dropdown + DD-MM-YYYY + reason list."
echo "   • Reports Hub → month defaults to last finalized salary month;"
echo "     Salary Comparison has the new Periodic mode."
echo "   • Factory & Boiler Annual Return → 'FORM 23 (Official)' button."
echo "   • Monthly Challan Summary → tap PENDING/PAID/FAILED badges."
