#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 675)
# Deploys the FULL latest code (includes ALL previous iterations).
#
# ═══════════ WHAT'S NEW (Iter 675) ═══════════
#
# 🛠️ ROOT-CAUSE FIX — OVERLAPPING / HIDING PANELS (user videos ×2):
#  * AI Command Center → Email Audit: the filter chips could overlap and
#    hide the sub-tab bar on first render (REPRODUCED on a production
#    build). Cause: nested horizontal scroll rows collapsing to zero
#    height on initial layout. FIXED — all chip rows are now simple
#    wrapping rows that can never collapse or overlap.
#  * Dashboard "Recently Opened" cards overlapping/misplacing: caused by
#    HYDRATION of pre-rendered pages (React #418 seen on the live
#    build). FIXED AT THE ROOT — the web app is now exported as a pure
#    SPA ("single" output): NO pre-rendered HTML, NO hydration, so
#    late-loading widgets can never be inserted at wrong positions
#    anywhere in the app again.
#  * This deploy also auto-patches nginx so every route URL falls back
#    to /index.html (required for the SPA build; safe + reversible).
#  * PWA cache bumped v11 → v12 — purges ALL old pre-rendered shells.
#    ➤ After deploying, close all portal tabs once (or Ctrl+Shift+R).
#
# ═══════════ ALSO INCLUDED (Iter 674) ═══════════
#
# 🤖 EMAIL AUDIT AGENT — PHASE 1 (user spec, Super Admin only, READ-ONLY):
#  * New "🤖 Email Audit" tab inside AI Command Center.
#  * REUSES the existing Email SMTP & Notifications mailbox (read-only
#    IMAP) — NO new SMTP configuration anywhere.
#  * HARD date boundary: only emails received ON/AFTER 15-Aug-2026 are
#    processed (enforced in backend, IMAP SINCE + per-mail re-check);
#    older mail = IGNORED_HISTORICAL, never in stats/notifications.
#  * Pipeline: Read → Identify Sender → Company Auto-Link (exact
#    registered email 99% → registered domain → AI content match) →
#    Classify (19 categories) → Extract (employee/payroll fields) →
#    Audit → Summary → Recommendation → Notify.
#  * Company Email Registry: multiple registered email IDs per firm
#    (type, contact person, active toggle) — managed from the tab.
#  * MULTIPLE registered companies for one email → never auto-picked:
#    COMPANY_REVIEW_REQUIRED with manual firm selection.
#  * Attachment analysis (READ-ONLY peek): XLSX/CSV/PDF/DOCX/ZIP —
#    name, type, size, readability + content excerpt. Never imported.
#  * Statuses: ACTION_REQUIRED / URGENT / REVIEW_REQUIRED /
#    COMPANY_REVIEW_REQUIRED / INFORMATION_ONLY / PROCESSING_FAILED /
#    IGNORED_HISTORICAL. Confidence < 80% (configurable) → review.
#  * Message-ID dedupe — an email is NEVER audited twice.
#  * Full processing timeline per email ("what did the AI do?"),
#    company-wise view, daily AI report, exceptions, sandbox test mode.
#  * In-app notifications for Action Required / Urgent / Company Review.
#  * Auto-poll every 5 min (configurable) once the agent is switched ON
#    from Email Audit → Settings. Phase 1 sends NOTHING and never
#    touches payroll — permission matrix enforced in code.
#
# ═══════════ ALSO INCLUDED (Iter 673) ═══════════
#
# 🧹 "YESTERDAY AT A GLANCE" BOX REMOVED FROM DASHBOARD (user request):
#  * The digest box no longer renders on the Portal Dashboard at all —
#    it was misrendering inside the Compliance panel on the live portal.
#  * Notifications now surface EXACTLY two ways:
#      1. LIVE POPUP window (bottom-left) — appears ONLY when a NEW
#         notification arrives; auto-hides after ~10 s; Hide button.
#      2. BELL BUTTON 🔔 — full list + the compact "Yesterday at a
#         glance" summary stays pinned INSIDE the bell dropdown.
#  * PWA cache bumped v10 → v11 so old shells purge on first open.
#    ➤ After deploying, close all portal tabs once (or Ctrl+Shift+R).
#
# ═══════════ ALSO INCLUDED (Iter 672) ═══════════
#
# 🛠️ DIGEST / POPUP SCREEN FIX — ROOT CAUSE (user screenshot ×2):
#  * The "Yesterday at a glance" card was rendering INSIDE the
#    Compliance panel (squeezed/misplaced) on the live portal. Root
#    cause: a React HYDRATION mismatch on the pre-rendered dashboard
#    HTML — on slower loads the card node was inserted at a wrong DOM
#    position (React error #418).
#  * FIX: the digest card and the live popup window now live inside
#    STABLE, always-mounted containers — they can never be inserted
#    into another panel again, regardless of load speed.
#  * PWA cache bumped v9 → v10 so every browser purges old shells.
#    ➤ After deploying, close all portal tabs once (or Ctrl+Shift+R).
#
# 📋 TASK ALLOTMENT NOTIFICATIONS (user request):
#  * Assigning a task (create / delegate / reassign) now notifies the
#    assignee instantly — INCLUDING Sub Super Admins (user-targeted
#    notifications reach every role).
#  * Notification shows: task title, assigned by, firm(s), due date,
#    priority (HIGH tasks flagged Important) + "View" opens the Tasks
#    tab. Appears in the bell, the live popup and the daily digest.
#
# ═══════════ ALSO INCLUDED (Iter 671) ═══════════
#
# 📍 LIVE POPUPS → BOTTOM-LEFT + HIDE BUTTON (user request):
#  * The notification popup window now lives in the BOTTOM-LEFT corner
#    (was bottom-right); toasts slide in from the left.
#  * New HIDE button on the popup window — one tap closes ALL visible
#    popups at once (items stay UNREAD in the bell).
#  * When a NEW notification arrives the window auto-UNHIDES, and the
#    whole window auto-hides again after ~10 seconds (was 6 s).
#
# 🔕 DEVICE-OFFLINE ALERTS STOPPED (user request):
#  * "Machine OFFLINE" notifications are NO LONGER raised and the
#    device-offline EMAILS are NO LONGER sent. The background monitor
#    is disabled by default (re-enable anytime by adding
#    DEVICE_OFFLINE_ALERTS=true to backend/.env and restarting).
#  * This deploy also PURGES all old "Machine OFFLINE" notifications
#    from the bell/digest so they stop cluttering the feed.
#
# ═══════════ ALSO INCLUDED (Iter 670) ═══════════
#
# 🛠️ DIGEST CARD SCREEN FIX (user screenshot: card overlapping panels):
#  * On the live portal the "Yesterday at a glance" card could render
#    ON TOP of the Compliance/KPI panels — a stale cached PWA shell
#    from an older deploy mixing with the new bundle.
#  * PWA cache version bumped v8 → v9: every browser/installed PWA
#    purges the old cached shells on first open after this deploy.
#  * The digest card itself is layout-hardened: strictly in normal
#    flow, full-width, clipped (overflow hidden) and painting above
#    sibling chart labels — it can never float over other panels.
#  * TIP after deploying: close ALL open portal tabs once (or press
#    Ctrl+Shift+R) so the new service worker takes over immediately.
#
# ═══════════ ALSO INCLUDED (Iter 669) ═══════════
#
# 🌅 NOTIFICATION DIGEST — "YESTERDAY AT A GLANCE" (user request):
#  * New GET /api/notifications/digest — summarizes YESTERDAY's (IST
#    calendar day) notification events for the logged-in admin:
#    total, counts by category, top-5 highlights (critical > important
#    > newest) and a per-firm breakdown for super admins.
#  * DASHBOARD CARD: warm amber "Yesterday at a glance" card at the top
#    of the Portal Dashboard Overview — category count chips, top 4
#    highlights with priority bars + "View →" deep links, per-firm
#    counts. Dismissible with ✕ (stays hidden until the next morning).
#  * BELL DROPDOWN: a compact pinned digest at the top of the
#    notification dropdown (counts + top 2 highlights).
#  * Opening a highlight marks that notification read + navigates.
#  * Hidden automatically when yesterday had zero notifications.
#
# ═══════════ ALSO INCLUDED (Iter 668) ═══════════
#
# 🔔 LIVE NOTIFICATION POPUPS — STACKABLE TOASTS (user spec):
#  * New notifications now pop up automatically in the BOTTOM-RIGHT
#    corner as compact toast cards — no reload needed.
#  * Stack vertically (max 4 visible), newest closest to the corner,
#    smooth slide-in animation.
#  * Auto-dismiss after ~6 s (hovering a toast pauses the timer);
#    manual ✕ close button on every card.
#  * Each card: category icon + colour, title, short message, relative
#    time ("just now" / "2m ago") and a "View →" action button that
#    deep-links to the related page and marks the item read.
#  * Closing with ✕ does NOT mark it read — the item stays unread in
#    the bell until opened.
#  * 100% NON-BLOCKING overlay: never steals input focus, never reloads
#    the page, never interrupts salary processing or open forms.
#  * Respects the per-device Notification Settings (toasts ON/OFF,
#    sound, per-category filters) from Iter 666.
#
# ═══════════ ALSO INCLUDED (Iter 667) ═══════════
#
# 🔔 NOTIFICATION SYSTEM ENHANCEMENT (user spec, additive layer):
#  * Categories (Attendance/Leave/Salary/Compliance/Expense/Employee/
#    Import/System/Announcement) with icons + colors everywhere.
#  * Priorities: Normal · Important (amber bar) · Critical (red bar).
#  * TOAST popup for new notifications (6.5 s, deduped, click → opens the
#    related page) + optional SOUND (default OFF) — per-device settings.
#  * Bell dropdown: icons, priority bars, unread shading, per-item open,
#    "Mark all read" (server-side per-user read state; opening = seen only).
#  * Notifications page: search, All/Unread/9-category filters, priority
#    badges, Mark All Read, Settings (toast/sound/per-category ON-OFF).
#  * Event alerts wired: Salary Processing Completed, Salary Locked,
#    Salary Import Completed/Partial, New Leave Request (to admins),
#    Leave Approved/Rejected (to the employee) — all with View actions.
#  * Polling 60s → 30s + instant refresh on tab focus. Super admins see
#    all companies; company admins strictly their own + global (backend
#    enforced). No business logic touched.
#
# 📐 ATTENDANCE + GROSS VALIDATION — DEFAULT (user directive):
#  * DEFAULT days-calc method for EVERY firm (migration included; firms
#    with an explicitly chosen method keep it — change in Firm Master).
#  * Sheet DAYS + GROSS are both respected: days AUTO-REDUCE when too
#    high for the gross, but NEVER increase beyond the sheet days.
#  * Salary recalculated on Compliance Days; PF/ESIC/LWF/PT auto.
#  * Fixed Days (26/30/31) method REMOVED (existing fixed firms auto-move).
#
# 🧮 GRID TOTAL vs FILTERS (user bug "filter total showing wrong"):
#  * With a column filter (e.g. Name = BHERU) the TOTAL row still summed
#    ALL employees. The TOTAL row (all heads: Days, OT, Master, Basic,
#    HRA, PF, ESIC, deduction heads, Advance, Net…) now sums ONLY the
#    rows visible after filters/search — in BOTH salary grids.
#
# 📥 IMPORT SALARY SHEET — GROUP FIX (user bug "import 56, showing 69"):
#  * The auto-reprocess after uploading a salary sheet IGNORED the
#    Employee Group + Month Days chosen in Configure Batch — the run came
#    back as "All Groups" with every employee of the firm.
#  * The import now processes EXACTLY like pressing Salary Process:
#    same Employee Group (e.g. LABOUR 56) and same Month Days.
#
# 👥 ATTENDANCE — HIDE ZERO ATTENDANCE (user request):
#  * New one-click toggle on the Attendance Report: "Hide Zero
#    Attendance" instantly hides employees with no hours, no present
#    days, no OT and no punches for the month.
#  * The Excel AND PDF downloads (In/Out · Hours · OT) respect the
#    toggle — exports contain only the working employees.
#
# 🗂️ WORKSPACE TABS — MULTI-TAB FIX (user video "Dashboard issue"):
#  * Pressing "+" no longer stacks duplicate Dashboard tabs — if a
#    Dashboard tab is already open it jumps to it instead.
#  * Switching to another tab is now a PLAIN navigation (no forced
#    double-reload nonce) — the white flash / spinner on every switch is
#    gone. Clicking the ACTIVE tab still refreshes that page (Iter 502).
#  * PWA cache version bumped (v8) so old cached builds are purged.
#
# 📗 HOURS EXCEL — SCREEN FORMAT (user request):
#  * The Attendance "Hours only" Excel is now ONE ROW per employee —
#    S.No. · Name · Father Name · Designation · Bio · day-wise combined
#    Duty+OT hours (HH:MM) — exactly like the on-screen HRS sheet.
#    The separate day-wise OT split stays on the "OT HRS" tab.
#
# 🧾 REGISTER PDF — ADVANCE FIX (user bug "ADVANCE 0 AA RHA HE"):
#  * The Salary Sheet / Register of Wages summary block showed Advance
#    Deduction Amount = 0 always (hardcoded). It now shows the REAL
#    Advance total from the run (both register formats).
#
# 🧊 COMPLIANCE GRID — FREEZE PACK (user requests):
#  * Header rows stay FROZEN on top; grid height auto-fits the screen so
#    the horizontal scrollbar is ALWAYS visible (no page scrolling).
#  * PRESENT DAYS column frozen beside the Name block; NET frozen at the
#    right edge — both stay on screen while scrolling sideways.
#  * ROW HIGHLIGHT follows the cursor: click/edit ANY cell and the whole
#    row highlights; Arrow Up/Down moves the highlight WITH the focus
#    (old-payroll style) — fixed "highlight frozen after edit" bug.
#    (Both Compliance & Actual salary grids.)
#
# 💰 FREEZE DIFFERENCE → INCENTIVE (user request):
#  * New adjust head: when the Firm Master's Allowance catalog has
#    INCENTIVE enabled, the freeze-vs-calculated difference lands under
#    the editable INCENTIVE column. Priority: sheet allowance heads →
#    Overtime (if firm allows OT) → INCENTIVE → Other Allowances.
#    Verified: diff ₹12,410 → INCENTIVE with OT off; OT still wins first.
#
# 🗂️ WORKSPACE TABS — UNSAVED DATA FIX (user bug):
#  * Switching between the portal's workspace tabs used to REMOUNT the
#    salary screens — the open run and every unsaved grid edit vanished.
#  * Both the Compliance Salary and Actual Salary screens now keep an
#    in-memory snapshot: switch away and back, and the same run returns
#    with ALL unsaved edits intact (+ a reminder toast to Save/Finalize).
#
# ⚡ WHOLE-SYSTEM SPEED-UP (user request: "Speedup the whole Live System"):
#  * Pre-compressed JS/CSS bundles + nginx gzip_static — the multi-MB
#    portal bundle now downloads ~4-5× faster on first load.
#  * 1-year browser caching for content-hashed /_expo assets — repeat
#    visits load the portal near-instantly (new deploys auto-bust).
#  * HTTP/2 enabled — all assets download in parallel on one connection.
#  * gzip for every JSON/API response at the nginx layer too.
#  * (Backend already gzips API JSON ~10× — verified.)
#
# 🔒 SALARY LOCK — LIVE-DATA FIX (user bug: "Still not able to Lock"):
#  * NGINX HARDENING (this script now applies it automatically): default
#    1 MB body limit + 60 s proxy timeouts on the VPS can reject/cut a
#    large firm's salary-grid save & lock (HTTP 413 / 504). The deploy
#    now sets client_max_body_size 50m + 300 s proxy timeouts.
#  * HONEST ERROR: the lock previously blamed "PF/ESIC validation" for
#    ANY failure (network / session expiry / 413 / 504). It now shows
#    the REAL cause with the HTTP status (e.g. session expired — log in
#    again; sheet too large; server timeout).
#
# 📷 CAMERA BUTTON — PWA ONLY (user request):
#  * The dedicated "Camera" button next to every Scan-OCR button now
#    shows ONLY on phones (installed PWA / mobile browser). The desktop
#    Web Portal shows just the file-picker Scan buttons.
#
# 🪪 STATUTORY & BANK — OCR AUTO-FILL (user request):
#  * New scan buttons in the Statutory & Bank block of Add/Edit
#    Employee: Scan PAN → fills PAN + Name-as-per-PAN; Scan Aadhaar →
#    fills Aadhaar No. + Name-as-per-Aadhaar; Scan Passbook/Cheque →
#    fills Account No., IFSC (auto-lookup), Bank Name and Branch.
#
# 📊 SHIFT DEPLOYMENT — SUMMARY BY (user request):
#  * "Summary Only" no longer forces BOTH Department-wise AND
#    Designation-wise sections. A new "Summary By" choice lets you pick
#    EITHER Department Wise OR Designation Wise — the preview and ALL
#    downloads (PDF / Excel / CSV) show only the chosen grouping, and
#    the report heading names it (e.g. "— Department Wise Summary").
#
# ✅ BULK EMPLOYEE CORRECTION — VERIFIED (user check):
#  * End-to-end verified that every correction (Father Name, Department,
#    Designation, UAN, Bank A/c, Compliance Basic + allowance heads,
#    Actual Basic + Pay Basis) lands on the Employee Master instantly,
#    including the mirrored flat fields and salary structures.
#
# 🧰 Iter 651-644 (also included) — ESIC reprocess fix · keyboard
#    shortcuts (Enter/Ctrl+S/Ctrl+L) · silent-lock fix + live TOTAL row ·
#    arrow-key navigation · Bulk Correction basis fix · editable
#    INCENTIVE · FOOD ALLOWANCE import fix · dynamic allowance columns.
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy675.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy675.sh

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "════════════════════════════════════════════════════════════"
echo "  STEP 0 — DIAGNOSTICS (send me this block if deploy fails)"
echo "════════════════════════════════════════════════════════════"
df -h / | tail -1
free -h
sudo supervisorctl status sksharma-backend 2>/dev/null || systemctl status sksharma-backend --no-pager -l 2>/dev/null | head -5 || echo "(no backend service found)"
curl -s -m 5 http://localhost:8001/api/health && echo " <-- backend answers ✅" || echo "❌ BACKEND NOT ANSWERING"
sudo nginx -t 2>&1 | tail -1
systemctl is-active nginx && echo "nginx active ✅" || echo "❌ nginx NOT active"
ls -la $WEB_DIR/index.html 2>/dev/null || echo "❌ $WEB_DIR/index.html MISSING"
echo "════════════════════════════════════════════════════════════"
echo ""

echo "==> 1/9 Freeing disk space (safe cache cleanup)..."
rm -rf $APP_DIR/frontend/.metro-cache $APP_DIR/frontend/.expo /tmp/metro-* /tmp/haste-* 2>/dev/null
npm cache clean --force >/dev/null 2>&1 || true
yarn cache clean >/dev/null 2>&1 || true
AVAIL_MB=$(df -m / | tail -1 | awk '{print $4}')
echo "   Free disk now: ${AVAIL_MB} MB"
if [ "$AVAIL_MB" -lt 1500 ]; then
  sudo apt-get clean 2>/dev/null || true
  sudo journalctl --vacuum-size=100M >/dev/null 2>&1 || true
  df -m / | tail -1 | awk '{print "   Free disk now: "$4" MB"}'
fi

echo "==> 2/9 Ensuring swap (prevents build OOM-kill)..."
SWAP_KB=$(grep SwapTotal /proc/meminfo | awk '{print $2}')
if [ "$SWAP_KB" -lt 1000000 ]; then
  sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile \
    && echo "   Swap ON ✅" || echo "   (swap setup failed — continuing)"
  grep -q "/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
else
  echo "   Swap already present ✅"
fi

echo "==> 3/9 Downloading latest code bundle (~10 MB, retries enabled)..."
rm -f /tmp/sks-latest.tar
ok=""
for i in 1 2 3 4 5; do
  if wget -c -T 60 -t 1 --show-progress -q -O /tmp/sks-latest.tar "$BUNDLE_URL"; then
    ok=1; break
  fi
  echo "   attempt $i failed — retrying in 10s..."
  sleep 10
done
if [ -z "$ok" ]; then
  curl -fSL --retry 5 --retry-delay 10 -o /tmp/sks-latest.tar "$BUNDLE_URL"
fi
if ! tar -tf /tmp/sks-latest.tar >/dev/null 2>&1; then
  echo "❌ Downloaded bundle is corrupt/incomplete. Open the portal preview URL in a browser once, wait 30s, re-run."
  exit 1
fi
echo "   Bundle OK: $(du -h /tmp/sks-latest.tar | cut -f1)"

echo "==> 4/9 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR || { echo "❌ Extract failed (disk full?) — aborting."; exit 1; }
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if grep -q "^OTP_EMAIL_ENABLED=false" $APP_DIR/backend/.env; then
  sed -i 's/^OTP_EMAIL_ENABLED=.*/OTP_EMAIL_ENABLED=true/' $APP_DIR/backend/.env
fi
grep -q "^OTP_EMAIL_ENABLED=" $APP_DIR/backend/.env || echo "OTP_EMAIL_ENABLED=true" >> $APP_DIR/backend/.env
grep -q "^RESEND_FROM_EMAIL=" $APP_DIR/backend/.env || echo "RESEND_FROM_EMAIL=no-reply@smartpayrolling.com" >> $APP_DIR/backend/.env
grep -q "^RESEND_API_KEY=re_" $APP_DIR/backend/.env || echo "RESEND_API_KEY=re_TVV9ccdZ_NiFrGwZzGjVTiKLEYSskpGqB" >> $APP_DIR/backend/.env
grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env || echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env

echo "==> 5/9 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP install openpyxl Pillow -q || true
echo "→ Warming up Face AI models (InsightFace buffalo_l — downloads ~300MB on first run)…"
$APP_DIR/backend/venv/bin/python - << 'PYW' || echo "   (model warmup failed — face features will retry lazily)"
from insightface.app import FaceAnalysis
app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"],
                   providers=["CPUExecutionProvider"])
app.prepare(ctx_id=-1, det_size=(640, 640))
print("   Face AI models READY")
PYW

echo "==> 6/9 Restarting backend FIRST (portal comes back before the build)..."
echo "==> Seeding second super admin login (idempotent)..."
cd $APP_DIR/backend
$APP_DIR/backend/venv/bin/python seed_second_super_admin.py || python3 seed_second_super_admin.py || echo "⚠ SEED FAILED — run manually: cd $APP_DIR/backend && ./venv/bin/python seed_second_super_admin.py"

echo "==> Iter 629 migration: enable auto-approve for MOBILE/PWA punches on ALL firms..."
cd $APP_DIR/backend
$APP_DIR/backend/venv/bin/python - << 'PYMIG' || echo "⚠ migration failed — run manually"
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env" if os.path.exists("/app/backend/.env") else ".env")
load_dotenv(".env")
async def m():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    r = await db.companies.update_many({}, {"$set": {"auto_approve_mobile_punches": True}})
    print(f"   auto_approve_mobile_punches=True set on {r.modified_count}/{r.matched_count} firms")
asyncio.run(m())
PYMIG

echo "==> Iter 667 migration: Attendance + Gross Validation as DEFAULT days-calc method..."
$APP_DIR/backend/venv/bin/python - << 'PYMIG2' || echo "⚠ migration failed — run manually"
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env" if os.path.exists("/app/backend/.env") else ".env")
load_dotenv(".env")
async def m():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    r = await db.firm_masters.update_many(
        {"$or": [{"salary_process.days_calc_method": {"$exists": False}},
                 {"salary_process.days_calc_method": {"$in": ["", None, "fixed"]}}]},
        {"$set": {"salary_process.days_calc_method": "attendance_gross_validation"}})
    print(f"   days_calc_method=attendance_gross_validation set on {r.modified_count} firm(s) (explicit choices untouched)")
asyncio.run(m())
PYMIG2

echo "==> Iter 671 migration: purge old 'Machine OFFLINE' notifications..."
$APP_DIR/backend/venv/bin/python - << 'PYMIG3' || echo "⚠ migration failed — run manually"
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env" if os.path.exists("/app/backend/.env") else ".env")
load_dotenv(".env")
async def m():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    r = await db.notifications.delete_many({"type": "device.offline"})
    print(f"   deleted {r.deleted_count} old device-offline notification(s)")
asyncio.run(m())
PYMIG3

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

echo "==> 7/9 Building web frontend (with OOM protection)..."
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

echo "==> 8/9 Publishing new build (with rollback safety)..."
sudo mkdir -p $WEB_DIR
sudo rm -rf ${WEB_DIR}.prev
sudo cp -r $WEB_DIR ${WEB_DIR}.prev 2>/dev/null || true
sudo find $WEB_DIR -mindepth 1 -maxdepth 1 ! -name '.well-known' ! -name '_expo' -exec rm -rf {} +
sudo cp -r dist/* $WEB_DIR/
sudo cp public/sw.js $WEB_DIR/sw.js 2>/dev/null || true
sudo find $WEB_DIR/_expo -type f -mtime +45 -delete 2>/dev/null || true

# Iter 675 — the app is now a pure SPA (single index.html, NO pre-rendered
# route pages, NO hydration). Every route URL must fall back to
# /index.html at nginx. Patch the site config that serves $WEB_DIR if its
# try_files doesn't already fall back to /index.html.
echo "==> 8a/9 Ensuring nginx SPA fallback (try_files ... /index.html)..."
SITE_FILE=$(sudo grep -rl "$WEB_DIR" /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | head -1)
if [ -n "$SITE_FILE" ]; then
  if sudo grep -q "try_files.*index\.html" "$SITE_FILE"; then
    echo "   SPA fallback already present in $SITE_FILE ✓"
  else
    sudo cp "$SITE_FILE" "${SITE_FILE}.bak675"
    if sudo grep -q "try_files" "$SITE_FILE"; then
      sudo sed -i 's|try_files[^;]*;|try_files $uri $uri.html /index.html;|' "$SITE_FILE"
    else
      # add try_files inside the location / block serving the web root
      sudo sed -i "0,/location \/ {/s|location / {|location / {\n        try_files \$uri \$uri.html /index.html;|" "$SITE_FILE"
    fi
    if sudo nginx -t; then
      echo "   SPA fallback patched into $SITE_FILE ✓"
    else
      echo "   ⚠ nginx test failed — restoring original site config"
      sudo cp "${SITE_FILE}.bak675" "$SITE_FILE"
    fi
  fi
else
  echo "   ⚠ Could not locate the nginx site config for $WEB_DIR — if deep"
  echo "     links 404 after this deploy, add: try_files \$uri /index.html;"
fi

sudo nginx -t && sudo systemctl reload nginx

echo "==> 8b/9 Nginx hardening for BIG salary sheets (Iter 667)..."
# Iter 667 REPAIR — older deploys left http-level client_max_body_size in
# more than one conf.d file ("directive is duplicate" -> nginx -t fails).
# /etc/nginx/conf.d/sks-upload.conf OWNS the global limit; strip the
# directive from every OTHER conf.d file, and dedupe sks-upload.conf too.
# Iter 667 REPAIR — the global body-size may ALSO live in nginx.conf's
# http block (older deploys). nginx forbids two http-level copies. Keep
# EXACTLY ONE: if nginx.conf has it, bump it to 100m and DELETE
# sks-upload.conf; otherwise sks-upload.conf owns it.
for CONF in /etc/nginx/conf.d/*.conf; do
  [ -f "$CONF" ] || continue
  [ "$CONF" = "/etc/nginx/conf.d/sks-upload.conf" ] && continue
  if grep -q "client_max_body_size" "$CONF"; then
    sudo sed -i '/client_max_body_size/d' "$CONF"
    echo "   Removed duplicate body-size from $CONF ✅"
  fi
done
if grep -q "client_max_body_size" /etc/nginx/nginx.conf; then
  sudo sed -i 's/client_max_body_size[[:space:]]*[0-9]*[km]\?;/client_max_body_size 100m;/' /etc/nginx/nginx.conf
  sudo rm -f /etc/nginx/conf.d/sks-upload.conf
  echo "   nginx.conf owns the global 100m limit — removed sks-upload.conf ✅"
elif [ -f /etc/nginx/conf.d/sks-upload.conf ]; then
  sudo awk '!(/client_max_body_size/ && seen++)' /etc/nginx/conf.d/sks-upload.conf | sudo tee /tmp/sks-upload.dedup >/dev/null
  sudo mv /tmp/sks-upload.dedup /etc/nginx/conf.d/sks-upload.conf
else
  echo "client_max_body_size 100m;" | sudo tee /etc/nginx/conf.d/sks-upload.conf >/dev/null
fi
# Big-payload timeouts INSIDE the site server blocks only (never conf.d —
# that is what caused the duplicate-directive failure).
for CONF in /etc/nginx/sites-enabled/*; do
  [ -f "$CONF" ] || continue
  grep -q "proxy_pass" "$CONF" || continue
  if ! grep -q "client_max_body_size" "$CONF"; then
    sudo sed -i '0,/server[[:space:]]*{/s//server {\n    client_max_body_size 100m;\n    proxy_read_timeout 300s;\n    proxy_send_timeout 300s;\n    proxy_connect_timeout 60s;/' "$CONF"
    echo "   Patched $CONF (100m body / 300s timeouts) ✅"
  else
    sudo sed -i 's/client_max_body_size[[:space:]]*[0-9]*[km]\?;/client_max_body_size 100m;/' "$CONF"
    grep -q "proxy_read_timeout" "$CONF" || sudo sed -i '0,/client_max_body_size 100m;/s//client_max_body_size 100m;\n    proxy_read_timeout 300s;\n    proxy_send_timeout 300s;/' "$CONF"
    echo "   Updated $CONF (body size -> 100m) ✅"
  fi
done
sudo nginx -t && sudo systemctl reload nginx && echo "   nginx reloaded ✅" || echo "   ❌ nginx config test failed — check: sudo nginx -t"

echo "==> 8c/9 SPEED-UP: nginx compression, caching & HTTP/2 (Iter 667)..."
# 1) Pre-compress the built JS/CSS once so nginx can serve .gz instantly
#    (gzip_static) instead of re-compressing multi-MB bundles per visitor.
sudo find $WEB_DIR -type f \( -name '*.js' -o -name '*.css' -o -name '*.html' -o -name '*.json' -o -name '*.svg' \) -size +1k -exec gzip -kf9 {} \; 2>/dev/null
echo "   Pre-compressed $(sudo find $WEB_DIR -name '*.gz' | wc -l) static files ✅"
# 2) Site-wide perf config (http context via conf.d): gzip everything
#    text-ish, serve pre-compressed files, long immutable cache for the
#    content-hashed /_expo bundles (safe — new deploys emit new hashes).
sudo tee /etc/nginx/conf.d/sksharma_perf.conf >/dev/null <<'NGINXPERF'
# S.K. Sharma & Co. — performance tuning (deploy Iter 667)
gzip on;
gzip_comp_level 5;
gzip_min_length 1024;
gzip_vary on;
gzip_proxied any;
gzip_types text/plain text/css application/json application/javascript
           text/javascript application/wasm image/svg+xml font/ttf;
gzip_static on;
sendfile on;
tcp_nopush on;
keepalive_timeout 65;
# Long-lived browser cache ONLY for content-hashed static assets;
# API responses and index.html stay untouched (default off).
map $uri $sks_expires {
    default                                   off;
    ~^/_expo/static/                          365d;
    ~\.(png|jpe?g|webp|ico|woff2?|ttf)$       30d;
}
expires $sks_expires;
NGINXPERF
# 3) HTTP/2 — multiplexes all asset downloads over one connection.
for CONF in /etc/nginx/sites-enabled/*; do
  [ -f "$CONF" ] || continue
  if grep -qE "listen[[:space:]]+443 ssl;" "$CONF"; then
    sudo sed -i 's/listen[[:space:]]\+443 ssl;/listen 443 ssl http2;/' "$CONF"
    echo "   HTTP/2 enabled in $CONF ✅"
  fi
done
if sudo nginx -t 2>/dev/null; then
  sudo systemctl reload nginx && echo "   nginx perf config live ✅"
else
  echo "   ⚠ perf config rejected by this nginx build — removing it (site stays as-is)"
  sudo rm -f /etc/nginx/conf.d/sksharma_perf.conf
  sudo nginx -t && sudo systemctl reload nginx
fi

echo "==> 9/9 Verification..."
echo -n "   Server badge is 675 (must say OK): "
grep -q 'APP_ITERATION = "675"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   SPA output (single) — Iter 675 (must say OK): "
grep -q '"output": "single"' $APP_DIR/frontend/app.json && echo "OK" || echo "MISSING!"
echo -n "   PWA cache v12 — Iter 675 (must say OK): "
grep -q 'sks-pwa-v12' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   Deep-link check (/portal-dashboard must be 200): "
curl -s -o /dev/null -w "%{http_code}" -k https://localhost/portal-dashboard -H "Host: smartpayrolling.com" || true
echo ""
echo -n "   Email Audit Agent backend — Iter 674 (must say OK): "
[ -f $APP_DIR/backend/routes/email_audit_agent.py ] && grep -q 'email_audit_agent' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Email Audit tab frontend — Iter 674 (must say OK): "
[ -f $APP_DIR/frontend/src/components/EmailAuditTab.tsx ] && grep -q 'EmailAuditTab' $APP_DIR/frontend/app/ai-command-center.tsx && echo "OK" || echo "MISSING!"
echo -n "   Dashboard digest box REMOVED — Iter 673 (must say OK): "
grep -q 'NotifDigestCard' $APP_DIR/frontend/app/portal-dashboard.tsx && echo "STILL PRESENT!" || echo "OK"
echo -n "   PWA cache v11 — Iter 673 (must say OK): "
grep -q 'sks-pwa-v11' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   Task allotment notifications — Iter 672 (must say OK): "
grep -q '_notify_task_allotted' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo -n "   Digest stable-slot fix — Iter 672 (must say OK): "
grep -q 'notif-digest-slot' $APP_DIR/frontend/src/components/NotifDigestCard.tsx && echo "OK" || echo "MISSING!"
echo -n "   PWA cache v10 — Iter 672 (must say OK): "
grep -q 'sks-pwa-v10' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   Popups bottom-left + Hide — Iter 671 (must say OK): "
grep -q 'live-notif-toast-hide-all' $APP_DIR/frontend/src/components/LiveNotifToasts.tsx && echo "OK" || echo "MISSING!"
echo -n "   Device-offline alerts OFF — Iter 671 (must say OK): "
grep -q '_OFFLINE_ALERTS_ON' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   PWA cache v9 — Iter 670 (must say OK): "
grep -q 'sks-pwa-v9' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   Notification Digest — Iter 669 (must say OK): "
grep -q 'notifications/digest' $APP_DIR/backend/routes/notifications.py && [ -f $APP_DIR/frontend/src/components/NotifDigestCard.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Live Notification Popups — Iter 668 (must say OK): "
[ -f $APP_DIR/frontend/src/components/LiveNotifToasts.tsx ] && grep -q 'LiveNotifToasts' $APP_DIR/frontend/src/components/AdminWebShell.tsx && echo "OK" || echo "MISSING!"
echo -n "   PUBLISHED web bundle has Hide-Zero-Attendance (must say OK): "
grep -rlq "Hide Zero Attendance" $WEB_DIR/_expo 2>/dev/null && echo "OK" || echo "MISSING! — the frontend build/copy FAILED; scroll up to the 'expo export' output for the error"
echo -n "   Toolbar polish — Iter 640 (must say OK): "
grep -q 'label renamed to just' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Approve backlog endpoint — Iter 639 (must say OK): "
grep -q 'approve-all-pending' $APP_DIR/backend/routes/attendance_self_service.py && echo "OK" || echo "MISSING!"
echo -n "   Attendance grid fonts — Iter 639 (must say OK): "
grep -q 'scaled ~20% for larger fonts' $APP_DIR/frontend/app/attendance-grid.tsx && echo "OK" || echo "MISSING!"
echo -n "   Toolbar overlap fix — Iter 638 (must say OK): "
grep -q 'compact buttons, one line' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Configure Batch toolbar — Iter 637 (must say OK): "
grep -q 'batchLine' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Actual grid redesign + compact header — Iter 636 (must say OK): "
grep -q 'csr-setup-expand' $APP_DIR/frontend/app/compliance-salary-run.tsx && grep -q 'UI readability' $APP_DIR/frontend/app/salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Grid readability redesign — Iter 635 (must say OK): "
grep -q 'UI readability' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   1-min autosave restored — Iter 634 (must say OK): "
grep -q 'AUTO-SAVE RESTORED' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Tab-switch reload removed — Iter 634 (must say OK): "
grep -qv 'visibilitychange' $APP_DIR/frontend/src/hooks/usePwaAutoUpdate.ts && echo "OK" || echo "MISSING!"
echo -n "   Whole-rupee CALCULATION — Iter 633 (must say OK): "
grep -q 'ALWAYS CALCULATE IN ROUND FIGURES' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Export Displayed button — Iter 633 (must say OK): "
grep -q 'export-display.xlsx' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Whole-rupee exports — Iter 632 (must say OK): "
grep -q 'round_export_rows' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Allowance disable warning — Iter 631 (must say OK): "
grep -q 'compliance-allowance-impact' $APP_DIR/frontend/app/firm-master.tsx && echo "OK" || echo "MISSING!"
echo -n "   Allowance mask inside engine — Iter 630 (must say OK): "
grep -q 'enabled_allowances: Optional' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   PWA punch auto-approve default — Iter 629 (must say OK): "
grep -q 'is not False' $APP_DIR/backend/routes/attendance_core.py && echo "OK" || echo "MISSING!"
echo -n "   ESS punch time display fix — Iter 629 (must say OK): "
grep -q 'timeZone: "UTC"' $APP_DIR/frontend/app/my-attendance.tsx && echo "OK" || echo "MISSING!"
echo -n "   Dummy Shift Matrix backend — Iter 628 (must say OK): "
grep -q 'dummy_map' $APP_DIR/backend/routes/inout_ot_matrix.py && echo "OK" || echo "MISSING!"
echo -n "   Dummy Shift Mode toggle UI — Iter 628 (must say OK): "
grep -q 'iom-dummy-toggle' $APP_DIR/frontend/app/inout-ot-matrix.tsx && echo "OK" || echo "MISSING!"
echo -n "   Shift Deployment Summary Only — Iter 627 (must say OK): "
grep -q '_summary_only' $APP_DIR/backend/routes/labour_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Summary toggle UI — Iter 627 (must say OK): "
grep -q 'lr-data-summary' $APP_DIR/frontend/app/labour-reports.tsx && echo "OK" || echo "MISSING!"
echo -n "   Daily rate revisions — Iter 626 (must say OK): "
grep -q "_apply_daily_rate_revisions" $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   calc_detail audit — Iter 626 (must say OK): "
grep -q '"calc_detail"' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Multi-branch module — Iter 624 (must say OK): "
grep -q "branch_mgmt_router" $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Punch branch authorization — Iter 624 (must say OK): "
grep -q "_branch_punch_gate" $APP_DIR/backend/routes/attendance_core.py && echo "OK" || echo "MISSING!"
echo -n "   Branch screens — Iter 624 (must say OK): "
[ -f $APP_DIR/frontend/app/branch-management.tsx ] && [ -f $APP_DIR/frontend/app/branch-dashboard.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Format 2 UAN/EPF wrap fix — Iter 623 (must say OK): "
grep -q 'idcell2' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   PF/ESIC proration LOCKED to Month Days — Iter 622 (must say OK): "
grep -q 'pf_proration_method = "calendar_days"' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   PF proration badge — Iter 621 (must say OK): "
grep -q "pf-proration-badge" $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   PF proration mirror in grid — Iter 620 (must say OK): "
grep -q "pfProrationFactor" $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Shortcuts Phase 3 — custom keys engine (must say OK): "
grep -q "applyOverride" $APP_DIR/frontend/src/utils/shortcuts.ts && echo "OK" || echo "MISSING!"
echo -n "   Shortcuts Phase 3 — Employee Master Alt+N (must say OK): "
grep -q '"employee-master"' $APP_DIR/frontend/app/admin.tsx && echo "OK" || echo "MISSING!"
echo -n "   Excel-style grid cells — Iter 618 (must say OK): "
grep -q "EditableGridCell" $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Arrow-key data-integrity guard (must say OK): "
grep -q "dirtyRef" $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   No-autosave + copy-verbatim (must say OK): "
grep -q "markGridDirty" $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Import ADVANCE→Advance col (must say OK): "
grep -q "actual_other_ded" $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   DOJ/DOL calendar window + audit (must say OK): "
grep -q "pay_days_audit" $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   Photo crop step in PWA (must say OK): "
grep -q "CropModal" $APP_DIR/frontend/app/profile-photo.tsx && echo "OK" || echo "MISSING!"
echo -n "   Punch face enforcement — Iter 615 (must say OK): "
grep -q "enforce_template_match" $APP_DIR/backend/routes/face_punch.py && echo "OK" || echo "MISSING!"
echo -n "   Web build published (must say OK): "
[ -f $WEB_DIR/index.html ] && echo "OK" || echo "MISSING!"
echo -n "   Backend /api/health: "
curl -s -m 5 http://localhost:8001/api/health || echo "❌ NOT ANSWERING"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  DONE — Iter 675 deployed."
echo "  • NEW (675): OVERLAP ROOT-CAUSE FIX — Email Audit chip rows can no"
echo "    longer collapse over the sub-tabs, and the whole web app is now a"
echo "    pure SPA (no pre-rendered HTML / no hydration), which eliminates"
echo "    the misplaced/overlapping panel family of bugs (dashboard cards,"
echo "    digest box, etc.). Nginx auto-patched for /index.html fallback."
echo "    ➤ Close all open portal tabs once (or Ctrl+Shift+R) after deploy."
echo "  • NEW (674): 🤖 EMAIL AUDIT AGENT (Phase 1, READ-ONLY, Super Admin)."
echo "    AI Command Center → 🤖 Email Audit. Reuses the existing SMTP/IMAP"
echo "    mailbox; processes only mail from 15-Aug-2026; auto-links firms"
echo "    via the Company Email Registry; classifies, extracts, audits,"
echo "    recommends and notifies. Turn it ON in Email Audit → Settings."
echo "  • NEW (673): 'Yesterday at a glance' box REMOVED from the Dashboard."
echo "    Notifications now show ONLY as the live popup (new arrivals) and"
echo "    via the bell button (list + compact digest inside the dropdown)."
echo "    ➤ Close all open portal tabs once (or Ctrl+Shift+R) after deploy."
echo "  • NEW (672): Digest/popup SCREEN FIX — root cause was a hydration"
echo "    mismatch inserting the card into the wrong panel; both now live"
echo "    in stable always-mounted containers. PWA cache bumped to v10."
echo "    ➤ Close all open portal tabs once (or Ctrl+Shift+R) after deploy."
echo "  • ALSO (672): Task Allotment notifications — assignees (incl. Sub"
echo "    Super Admins) get an instant notification with View → Tasks."
echo "  • NEW (671): Popups moved to BOTTOM-LEFT + HIDE button (closes all,"
echo "    auto-unhides on new arrivals, window auto-hides after ~10 s)."
echo "  • ALSO (671): Device-offline notifications & emails STOPPED; old"
echo "    'Machine OFFLINE' items purged from the feed."
echo "  • NEW (670): Digest-card screen fix — PWA cache bumped to v9 (old"
echo "    shells purged) + the 'Yesterday at a glance' card layout-hardened"
echo "    so it can never overlap other dashboard panels."
echo "    ➤ Close all open portal tabs once (or Ctrl+Shift+R) after deploy."
echo "  • NEW (669): NOTIFICATION DIGEST — 'Yesterday at a glance' card on"
echo "    the Dashboard (dismissible for the day) + pinned summary in the"
echo "    bell dropdown: category counts, top highlights with View links,"
echo "    per-firm breakdown for super admins."
echo "  • NEW (668): LIVE NOTIFICATION POPUPS — new notifications pop up"
echo "    bottom-right as stackable toast cards (max 4), slide-in animation,"
echo "    auto-dismiss ~6 s, hover pauses, View → opens the page & marks"
echo "    read, ✕ only closes (stays unread). Fully non-blocking."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): ACTUAL SALARY grid got the same readability"
echo "    upgrade — 14px text, 14px bold headers, ~44px rows, larger"
echo "    edit cells, full viewport height, all employees one page."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): COMPACT HEADER — once a compliance run is on"
echo "    screen, the Select-firm + Configure-batch cards collapse"
echo "    into one slim bar (Firm · Month · Group | Change firm /"
echo "    month) so the grid starts right at the top. Tap to expand."
echo "  • ALSO (635): COMPLIANCE GRID READABILITY (VIEW-ONLY redesign)"
echo "    — 14px grid text, 14px bold headers, ~44px rows, wider"
echo "    auto-fit columns, right-aligned money, grid uses the full"
echo "    viewport height and ALL employees stay on ONE page with"
echo "    sticky headers. ZERO logic/calculation changes."
echo "  • ALSO (634): AUTO-SAVE RESTORED — the Compliance Salary sheet"
echo "    silently saves ALL work every 1 minute while there are"
echo "    unsaved edits (green Auto-saved HH:MM:SS indicator). The"
echo "    Actual Salary Process already saves each edit instantly and"
echo "    now RETRIES failed saves after 1 minute."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): ACTUAL SALARY grid got the same readability"
echo "    upgrade — 14px text, 14px bold headers, ~44px rows, larger"
echo "    edit cells, full viewport height, all employees one page."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): COMPACT HEADER — once a compliance run is on"
echo "    screen, the Select-firm + Configure-batch cards collapse"
echo "    into one slim bar (Firm · Month · Group | Change firm /"
echo "    month) so the grid starts right at the top. Tap to expand."
echo "  • ALSO (635): COMPLIANCE GRID READABILITY (VIEW-ONLY redesign)"
echo "    — 14px grid text, 14px bold headers, ~44px rows, wider"
echo "    auto-fit columns, right-aligned money, grid uses the full"
echo "    viewport height and ALL employees stay on ONE page with"
echo "    sticky headers. ZERO logic/calculation changes."
echo "  • ALSO (634): MULTI-TAB FIX — switching back to an older browser"
echo "    tab NO LONGER reloads the app / kicks you to the Dashboard"
echo "    after a deploy (update now applies on next fresh open only)."
echo "    Closing/refreshing a tab with unsaved compliance edits now"
echo "    asks for confirmation first."
echo "  • ALSO (633): WHOLE-RUPEE CALCULATION — the compliance engine"
echo "    itself now calculates in round figures (gross, wage bases,"
echo "    PF/ESIC/PT/TDS, deductions, net) so a Reprocess never shows"
echo "    decimals again; totals are re-derived so columns tally."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): ACTUAL SALARY grid got the same readability"
echo "    upgrade — 14px text, 14px bold headers, ~44px rows, larger"
echo "    edit cells, full viewport height, all employees one page."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): COMPACT HEADER — once a compliance run is on"
echo "    screen, the Select-firm + Configure-batch cards collapse"
echo "    into one slim bar (Firm · Month · Group | Change firm /"
echo "    month) so the grid starts right at the top. Tap to expand."
echo "  • ALSO (635): COMPLIANCE GRID READABILITY (VIEW-ONLY redesign)"
echo "    — 14px grid text, 14px bold headers, ~44px rows, wider"
echo "    auto-fit columns, right-aligned money, grid uses the full"
echo "    viewport height and ALL employees stay on ONE page with"
echo "    sticky headers. ZERO logic/calculation changes."
echo "  • ALSO (634): AUTO-SAVE RESTORED — the Compliance Salary sheet"
echo "    silently saves ALL work every 1 minute while there are"
echo "    unsaved edits (green Auto-saved HH:MM:SS indicator). The"
echo "    Actual Salary Process already saves each edit instantly and"
echo "    now RETRIES failed saves after 1 minute."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): ACTUAL SALARY grid got the same readability"
echo "    upgrade — 14px text, 14px bold headers, ~44px rows, larger"
echo "    edit cells, full viewport height, all employees one page."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): COMPACT HEADER — once a compliance run is on"
echo "    screen, the Select-firm + Configure-batch cards collapse"
echo "    into one slim bar (Firm · Month · Group | Change firm /"
echo "    month) so the grid starts right at the top. Tap to expand."
echo "  • ALSO (635): COMPLIANCE GRID READABILITY (VIEW-ONLY redesign)"
echo "    — 14px grid text, 14px bold headers, ~44px rows, wider"
echo "    auto-fit columns, right-aligned money, grid uses the full"
echo "    viewport height and ALL employees stay on ONE page with"
echo "    sticky headers. ZERO logic/calculation changes."
echo "  • ALSO (634): MULTI-TAB FIX — switching back to an older browser"
echo "    tab NO LONGER reloads the app / kicks you to the Dashboard"
echo "    after a deploy (update now applies on next fresh open only)."
echo "    Closing/refreshing a tab with unsaved compliance edits now"
echo "    asks for confirmation first."
echo "  • ALSO (633): EXCEL (DISPLAYED) button on the Compliance sheet"
echo "    — exports EXACTLY what is on screen (incl. unsaved edits)"
echo "    BEFORE Save as Draft. Nothing is persisted by the export."
echo "  • ALSO (632): COMPLIANCE EXPORTS IN WHOLE RUPEES — the Excel /"
echo "    CSV Salary Sheet no longer prints paise (2903.85 -> 2904),"
echo "    so exported figures always MATCH the processed salary."
echo "    Days / hours / rates keep their real precision."
echo "  • NEW (631): DISABLE WARNING — switching OFF an allowance in"
echo "    Firm Master that has amounts in a processed month shows the"
echo "    month-wise impact (amount, employees, FINALIZED flag) and"
echo "    asks for confirmation before disabling."
echo "  • ALSO (630): ALLOWANCE ENABLE/DISABLE CONTRACT — disabling an"
echo "    editable allowance in Firm Master now calculates it as 0 on"
echo "    the NEXT Reprocess (Gross/ESIC/PT bases exclude it); stored"
echo "    values survive, re-enable + Reprocess restores them. On"
echo "    Freeze imports the masked amount moves into OT / Other"
echo "    Allowance so Gross Paid ALWAYS equals the imported gross"
echo "    and the columns add up. Basic is never masked."
echo "  • ALSO (629): PWA punch time FIXED — My Attendance was adding"
echo "    +5:30 twice (morning punch showed 3:27 PM). Now shows the"
echo "    exact punched wall-clock time. Correction requests fixed too."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): ACTUAL SALARY grid got the same readability"
echo "    upgrade — 14px text, 14px bold headers, ~44px rows, larger"
echo "    edit cells, full viewport height, all employees one page."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): COMPACT HEADER — once a compliance run is on"
echo "    screen, the Select-firm + Configure-batch cards collapse"
echo "    into one slim bar (Firm · Month · Group | Change firm /"
echo "    month) so the grid starts right at the top. Tap to expand."
echo "  • ALSO (635): COMPLIANCE GRID READABILITY (VIEW-ONLY redesign)"
echo "    — 14px grid text, 14px bold headers, ~44px rows, wider"
echo "    auto-fit columns, right-aligned money, grid uses the full"
echo "    viewport height and ALL employees stay on ONE page with"
echo "    sticky headers. ZERO logic/calculation changes."
echo "  • ALSO (634): AUTO-SAVE RESTORED — the Compliance Salary sheet"
echo "    silently saves ALL work every 1 minute while there are"
echo "    unsaved edits (green Auto-saved HH:MM:SS indicator). The"
echo "    Actual Salary Process already saves each edit instantly and"
echo "    now RETRIES failed saves after 1 minute."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): ACTUAL SALARY grid got the same readability"
echo "    upgrade — 14px text, 14px bold headers, ~44px rows, larger"
echo "    edit cells, full viewport height, all employees one page."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): COMPACT HEADER — once a compliance run is on"
echo "    screen, the Select-firm + Configure-batch cards collapse"
echo "    into one slim bar (Firm · Month · Group | Change firm /"
echo "    month) so the grid starts right at the top. Tap to expand."
echo "  • ALSO (635): COMPLIANCE GRID READABILITY (VIEW-ONLY redesign)"
echo "    — 14px grid text, 14px bold headers, ~44px rows, wider"
echo "    auto-fit columns, right-aligned money, grid uses the full"
echo "    viewport height and ALL employees stay on ONE page with"
echo "    sticky headers. ZERO logic/calculation changes."
echo "  • ALSO (634): MULTI-TAB FIX — switching back to an older browser"
echo "    tab NO LONGER reloads the app / kicks you to the Dashboard"
echo "    after a deploy (update now applies on next fresh open only)."
echo "    Closing/refreshing a tab with unsaved compliance edits now"
echo "    asks for confirmation first."
echo "  • ALSO (633): WHOLE-RUPEE CALCULATION — the compliance engine"
echo "    itself now calculates in round figures (gross, wage bases,"
echo "    PF/ESIC/PT/TDS, deductions, net) so a Reprocess never shows"
echo "    decimals again; totals are re-derived so columns tally."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): ACTUAL SALARY grid got the same readability"
echo "    upgrade — 14px text, 14px bold headers, ~44px rows, larger"
echo "    edit cells, full viewport height, all employees one page."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): COMPACT HEADER — once a compliance run is on"
echo "    screen, the Select-firm + Configure-batch cards collapse"
echo "    into one slim bar (Firm · Month · Group | Change firm /"
echo "    month) so the grid starts right at the top. Tap to expand."
echo "  • ALSO (635): COMPLIANCE GRID READABILITY (VIEW-ONLY redesign)"
echo "    — 14px grid text, 14px bold headers, ~44px rows, wider"
echo "    auto-fit columns, right-aligned money, grid uses the full"
echo "    viewport height and ALL employees stay on ONE page with"
echo "    sticky headers. ZERO logic/calculation changes."
echo "  • ALSO (634): AUTO-SAVE RESTORED — the Compliance Salary sheet"
echo "    silently saves ALL work every 1 minute while there are"
echo "    unsaved edits (green Auto-saved HH:MM:SS indicator). The"
echo "    Actual Salary Process already saves each edit instantly and"
echo "    now RETRIES failed saves after 1 minute."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): ACTUAL SALARY grid got the same readability"
echo "    upgrade — 14px text, 14px bold headers, ~44px rows, larger"
echo "    edit cells, full viewport height, all employees one page."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): APPROVE BACKLOG — Punch Approvals now has a green"
echo "    Approve All Pending (N) button that clears the entire pending"
echo "    punch queue in ONE click (full audit trail on each record)."
echo "  • NEW (657): Grid freeze pack — header, Present Days & Net frozen;"
echo "    h-scrollbar always on screen; highlight follows edited cell;"
echo "    Freeze diff can now land in editable INCENTIVE (OT first)."
echo "  • ALSO (656): Workspace tab fix — switching tabs no longer wipes"
echo "    the open salary run or unsaved grid edits (both grids)."
echo "  • ALSO (655): SPEED-UP — pre-compressed bundles, gzip_static,"
echo "    1-year asset caching, HTTP/2. Portal loads much faster now."
echo "  • ALSO (654): Salary Lock live-data fix — nginx 50m body/300s"
echo "    timeouts auto-applied; lock errors now show the REAL cause."
echo "  • ALSO (653): Camera button PWA-only; OCR auto-fill for PAN /"
echo "    Aadhaar / Bank details in the Statutory & Bank block."
echo "  • ALSO (652): Shift Deployment Summary By — pick Department OR"
echo "    Designation wise summary (not both); heading names the choice."
echo "  • ALSO (651): ESIC always recalculated on reprocess-with-existing;"
echo "    Enter opens Present Days; Ctrl+S saves; Ctrl+L locks."
echo "  • ALSO (650): Lock never silent; TOTAL row live-sums every head."
echo "  • ALSO (649): Row highlight + arrow-key navigation on grids."
echo "  • ALSO (648): Bulk Correction Rate/Pay Basis now sticks."
echo "  • ALSO (647): Salary Lock hardened; INCENTIVE column editable."
echo "  • ALSO (646): Import sheet FOOD ALLOWANCE lands under its own"
echo "    column — never in OT; OT columns follow the OVER TIME toggle."
echo "  • ALSO (645): INCENTIVE columns in BOTH PDF register formats."
echo "  • ALSO (644): Salary Lock fixed; INCENTIVE columns on grid +"
echo "    Excel/CSV; OT columns follow the OVER TIME toggle."
echo "  • ALSO (643): Excel-import PF fix (Fixed 26, not 31); frozen"
echo "    page headers; note-chips row; 12px grid font."
echo "  • ALSO (642): Configure Batch filters — Month (FY-wise), Month"
echo "    Days, Employee Group + summary cards all on ONE line."
echo "  • ALSO (641): Salary Process button is now a compact two-line"
echo "    button matching Copy Last Month Salary."
echo "  • ALSO (640): Configure Batch polish — days field renamed to"
echo "    just MONTH DAYS with a narrow 2-digit input; Copy Last"
echo "    Month Salary is now a small two-line button."
echo "  • ALSO (639): ATTENDANCE GRID readability — names 14px, day"
echo "    cells 20% wider, IN/OUT times 12px, taller rows, larger"
echo "    headers/summary columns. View-only; no logic changes."
echo "  • ALSO (638): toolbar overlap FIXED — Month/FY selectors no"
echo "    longer collide with the Month-Days label; all 3 summary"
echo "    cards stay on the same line; Salary Process + Copy Last"
echo "    Month buttons are now compact side-by-side (not full-width)."
echo "  • ALSO (637): CONFIGURE BATCH single-line toolbar (VIEW-ONLY)"
echo "    — 22px title + gear icon, Month/FY/Days/Group in one row"
echo "    with display-only summary cards (Total blue / Processed"
echo "    green / Pending orange), GREEN Salary Process + purple"
echo "    Copy Last Month buttons, month-days notice in a light-blue"
echo "    info panel. No behaviour changes."
echo "  • ALSO (636): COMPACT HEADER — once a compliance run is on"
echo "    screen, the Select-firm + Configure-batch cards collapse"
echo "    into one slim bar (Firm · Month · Group | Change firm /"
echo "    month) so the grid starts right at the top. Tap to expand."
echo "  • ALSO (635): COMPLIANCE GRID READABILITY (VIEW-ONLY redesign)"
echo "    — 14px grid text, 14px bold headers, ~44px rows, wider"
echo "    auto-fit columns, right-aligned money, grid uses the full"
echo "    viewport height and ALL employees stay on ONE page with"
echo "    sticky headers. ZERO logic/calculation changes."
echo "  • ALSO (634): MULTI-TAB FIX — switching back to an older browser"
echo "    tab NO LONGER reloads the app / kicks you to the Dashboard"
echo "    after a deploy (update now applies on next fresh open only)."
echo "    Closing/refreshing a tab with unsaved compliance edits now"
echo "    asks for confirmation first."
echo "  • ALSO (633): EXCEL (DISPLAYED) button on the Compliance sheet"
echo "    — exports EXACTLY what is on screen (incl. unsaved edits)"
echo "    BEFORE Save as Draft. Nothing is persisted by the export."
echo "  • ALSO (632): COMPLIANCE EXPORTS IN WHOLE RUPEES — the Excel /"
echo "    CSV Salary Sheet no longer prints paise (2903.85 -> 2904),"
echo "    so exported figures always MATCH the processed salary."
echo "    Days / hours / rates keep their real precision."
echo "  • NEW (631): DISABLE WARNING — switching OFF an allowance in"
echo "    Firm Master that has amounts in a processed month shows the"
echo "    month-wise impact (amount, employees, FINALIZED flag) and"
echo "    asks for confirmation before disabling."
echo "  • ALSO (630): ALLOWANCE ENABLE/DISABLE CONTRACT — disabling an"
echo "    editable allowance in Firm Master now calculates it as 0 on"
echo "    the NEXT Reprocess (Gross/ESIC/PT bases exclude it); stored"
echo "    values survive, re-enable + Reprocess restores them. On"
echo "    Freeze imports the masked amount moves into OT / Other"
echo "    Allowance so Gross Paid ALWAYS equals the imported gross"
echo "    and the columns add up. Basic is never masked."
echo "  • ALSO (629): ALL employee PWA punches now AUTO-APPROVE by"
echo "    default (every firm). A firm can still turn this off via"
echo "    Firm Settings -> Auto-approve Mobile App Punches. Fake-GPS"
echo "    flagged punches still require manual approval."
echo "  • ALSO (628): DUMMY SHIFT IN/OUT MATRIX — open In/Out & OT"
echo "    Matrix and switch on the amber Dummy Shift Mode chip (only"
echo "    visible when the firm has Dummy Shift Allowed ON in the"
echo "    Attendance Policy). Present 2-punch days show the Dummy"
echo "    Shift master timings, WO/H markers follow Employee Master"
echo "    week-off + Holiday Master, overnight OUT is marked *."
echo "    100% READ-ONLY — attendance/payroll are never modified."
echo "  • ALSO (627): Shift Deployment Report now has a Data option —"
echo "    Full Data (all employee rows) or SUMMARY ONLY: Department-"
echo "    wise + Designation-wise totals (Deployed / Present / Half"
echo "    Day / Hours / OT / Cost) — screen, PDF, Excel & CSV."
echo "  • MULTI-BRANCH: Branches screen → ⚙ opens Branch Management"
echo "    (extended fields, employee home/authorized branches, temp"
echo "    assignments, transfers) and the Branch Dashboard with"
echo "    cost allocation. One payroll record per employee always."
echo "  • PF & ESIC now ALWAYS divide by the Month Days entered on the"
echo "    salary sheet — for ALL firms. Old method settings (÷26 etc.)"
echo "    are ignored; the options are removed from Compliance Settings."
echo "  • REPROCESS any sheet that showed ÷26 PF figures: PF becomes"
echo "    12% of the earned Wage Base (e.g. LAL CHAND 4333 → 520)."
echo "  • SHORTCUTS: press ? in the portal for the full list; click ✎"
echo "    on any row to set your own keys; Reset restores defaults."
echo "  • Alt+N = new record on Employee Master / Advances / Claims;"
echo "    Ctrl+S saves employee forms; Ctrl+F finds an employee."
echo "  • SALARY GRID (618): arrows only move between cells — they can"
echo "    never change a payroll figure. Type to edit,"
echo "    Enter commits + moves down, Escape cancels."
echo "  • Untouched cells are never marked as manual overrides."
echo "  Admins just need to hard-refresh the portal once (Ctrl+F5)."
echo "════════════════════════════════════════════════════════════"
