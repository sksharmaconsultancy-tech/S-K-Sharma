#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 352)
# Same content as Iter 351 + ROBUST DOWNLOAD (user: "Not Able to Deploy"):
#   the code bundle is ~110 MB; the download now retries up to 5 times,
#   resumes partial downloads, and verifies the tar before extracting.
# Ships on top of 347 (user: "I will manually interlink, then sync again"):
#   • STAFF STRUCTURE SYNC (user: SUVIDHI staff codes/allowances mismatch;
#     verified against shared staf.xls): the old software keeps STAFF in a
#     separate EM_* table (EM_CODE, EM_RATEM, EM_HRA, EM_CONV, EM_TOT).
#     The all-firms sync now auto-discovers that table and syncs staff:
#     Basic=EM_RATEM, HRA + CONVEYANCE allowances, Gross=EM_TOT, UAN/ESI.
#     Match: employee code first, then exact name (covers code mismatches);
#     still-unmatched staff appear in the Unmatched list as "STAFF (EM table)".
#   • EMPLOYEE CODE CORRECTION (user: "Employee Code Is Also Mismatch"):
#     when a staff member is matched by NAME because the portal code differs
#     from the old DB (e.g. SANJAY KUMAR LODHA 380 → 372, DHARMENDRA 781 →
#     772), the portal employee code is auto-corrected to the old-DB code
#     (skipped if another employee already holds that code). The sync result
#     shows a "codes_corrected" counter.
#   • Verified locally against the shared staf.xls: MAN SINGH MALOO now gets
#     Basic 27500 + HRA 2000 + CONVEYANCE 1300 = Gross 30800 (was 51153).
#   • UNMATCHED LIST (user question): the all-firms sync result now shows
#     exactly WHICH employees were unmatched (firm — code — name — status)
#     so you can correct their employee codes and re-sync.
#   • MANUAL HEAD INTERLINKING in the Old DB vs Portal heads viewer:
#     each Old-DB allowance head now has a dropdown of portal allowance
#     labels + "Save" (this firm) or "Save for ALL firms" + "Remove".
#     Interlinked heads show "→ <portal label>".
#   • The ALL-FIRMS structure sync APPLIES the interlinks on its next run:
#     linked heads are renamed to the portal label on every employee's
#     allowance list and the linked label is enabled on the Firm Master
#     (instead of creating a new custom head).
#   → WORKFLOW: Legacy Import → "Show Allowance & Deduction Heads" →
#     interlink the 🟠 heads → press "Sync Salary Structures — ALL Firms".
#     equals Basic + all allowances — a stale gross value can no longer
#     override the heads.
#   • SUVIDHI SALARY STRUCTURE FIX (user bug): legacy import now prefers the
#     old software's CURRENT head-wise structure (EmployeeSalaryStructureDtl:
#     Basic head + allowances) over stale EmployeeMaster.BasicSalary/GrossPay.
#     Gross is derived as Basic + allowances whenever structure rows exist —
#     so the portal's salary structure now MATCHES the old database.
#     → After deploy: re-run Legacy Import (Employees + Salary fields) for
#       SUVIDHI RAYONS; existing employees are updated in place.
#   • AI LAYER (full): new sidebar menu "AI Payroll Assistant"
#     (/ai-payroll-assistant) — Payroll Health & Compliance scores, risk
#     cards, AI Compliance Checker (18+ checks w/ confidence % + Apply Fix +
#     false-positive learning), AI Auditor (PDF/Excel export), Attendance
#     Intelligence, Salary Difference Analysis, Reconciliation, Forecast,
#     Compliance Calendar, Smart Insights, AI notifications, audit log,
#     AI Excel column mapping + templates.
#   • CHATBOT upgrades: "List employees with missing UAN", "Show PF
#     mismatches", "Why is salary of code 50 lower?", compliance rules/news
#     expert answers with official portal links; executes salary process /
#     finalize / downloads / employee updates with Confirm buttons.
#   • Attendance Sheet: "Sort sheet by" option (Code / Name / Department /
#     DOJ) before download (single sheet + all-groups zip).
#   • Salary grids (Compliance + Actual): Excel-style header-wise FILTER
#     boxes under every column (text contains; numbers support >N <N =N).
#   • Shortcuts: sidebar entry, g+i → AI dashboard, Alt+1..6 tabs, R
#     re-analyse, Ctrl+Shift+A AI chat.
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~110 MB, retries enabled)..."
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
  echo "   Open the portal preview URL in a browser once (to wake the server),"
  echo "   wait 30 seconds, then re-run this script."
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
echo -n "   AI layer routes (must be > 0): "
grep -c "ai/analysis" $APP_DIR/backend/routes/ai_layer.py || true
echo -n "   Structure-first legacy mapping (must be > 0): "
grep -c "struct_basic" $APP_DIR/backend/routes/legacy_import.py || true

echo ""
echo -n "   Staff EM-table sync + code correction (must be > 0): "
grep -c "codes_corrected" $APP_DIR/backend/routes/legacy_import.py || true
echo ""
echo "✅ Deploy Iter 352 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   • ALL-FIRMS FIX: open Legacy Import → press"
echo "     'Sync Salary Structures — ALL Firms (from Old DB)'."
echo "     Watch the live counters (employees updated / gross changed)."
echo "   • Then spot-check SUVIDHI STAFF (Attendance Sheet Excel): e.g."
echo "     MAN SINGH MALOO must show Basic 27500 / HRA 2000 / CONV 1300 /"
echo "     Gross 30800, and SANJAY KUMAR LODHA's code becomes 372."
echo "   • Diagnostic (browser): /api/admin/legacy-import/staff-probe?firm_name=SUVIDHI&token=sks-deploy-7391"
echo "   • New menu: AI Payroll Assistant (bottom of sidebar, or press g i)."
echo "   • Salary grids now have Filter… boxes under every column header."
echo "   • Attendance Sheet page has a 'Sort sheet by' option."
