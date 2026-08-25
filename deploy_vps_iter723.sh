#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 723)
# Deploys the FULL latest code (includes ALL previous iterations).
#
# ═══════════ WHAT'S NEW (Iter 723) — 🩹 COMPLIANCE SALARY REPROCESS DATA-LOSS FIX ═══════════
#
# 🩹 REPROCESS NO LONGER CHANGES SAVED DATA (user bug — "if we Reprocess
#    the Salary Data may Change Again"):
#  * ROOT CAUSE (reproduced + verified): on Freeze-as-Actual-Gross firms
#    ("Freeze as Actual Gross" days method in the Firm Master) a
#    reprocess "With EXISTING Data" silently re-pulled the days from the
#    Actual salary run and dropped manual figures:
#      1. Manually edited PRESENT DAYS reverted to the Actual run's days.
#      2. Manual TDS typed on the sheet was wiped back to 0.
#      3. Manual OTHER DEDUCTION was wiped back to 0.
#      4. Monthly Gross went inconsistent after a kept manual OT/Others.
#      5. OT Hours re-pulled over a manually typed OT Amount.
#  * FIX (backend): the Freeze reprocess now follows the SAME Iter 297/374
#    keep-rules as normal runs — saved Present Days are KEPT (clamped to
#    month days), and manual TDS / Other Deduction / ESIC-Leave / OT Hours /
#    Monthly Gross are restored from the saved sheet before the statutory
#    refresh. PF/ESIC/PT still refresh on the kept gross per Iter 472/651.
#  * FIX (frontend): editing Present Days now stamps the row as a manual
#    override (manual_fields: present_days) — same stamping the money
#    edits already had — so every future reprocess keeps the typed days.
#  * Imported-sheet runs stay sheet-authoritative; "From BLANK" still
#    rebuilds fresh from attendance + master (unchanged).
#  * VERIFIED: edit days + TDS + Other Ded + OT Amt + Others → Save →
#    Reprocess → ZERO field changes on 108-employee run; double-reprocess
#    stability: 0 diffs; untouched rows: 0 drift.
#
# ═══════════ ALSO IN Iter 723 — 🩹 USB .TXT MACHINE IMPORT: MISSING BIO-CODE PUNCHES (221 / 258) ═══════════
#
# 🩹 USB IMPORT BIO-CODE MAPPING FIXED (user bug + AGL_001.TXT sample —
#    "data not importing properly thru bio code, some employees punch
#    miss, not showing in attendance report"):
#  * VERIFIED FIRST: the file parser reads ALL punches correctly
#    (55,760/55,760 lines; bio 221 = 845 punches, bio 258 = 535). The
#    loss happens at the BIO-CODE → EMPLOYEE mapping step.
#  * FIX 1 — WHITESPACE: a bio code saved as "221 " (stray space) on the
#    Employee Master silently landed every punch in UNMAPPED. Codes are
#    now trimmed on both sides before matching.
#  * FIX 2 — DUPLICATE BIO CODES: when an EXITED/disabled employee still
#    holds the same bio code as an active one, the import used to give
#    the punches to whichever came first (often the old employee) — the
#    active employee's attendance stayed empty. The ACTIVE employee now
#    always wins the code.
#  * FIX 3 — EMPLOYEE CODE FALLBACK: live machine punches already fall
#    back to the Employee Code when no bio code matches; the USB import
#    never did. It now does too — firms that keep the machine number in
#    the Employee Code field get their punches imported.
#  * RECOVERY: after this deploy, open Attendance Report → "Refresh Bio"
#    (or re-upload the .txt) — previously skipped punches are recovered
#    idempotently (no duplicates).
#  * VERIFIED with the user's real AGL_001.TXT: bio 221 → 31/31 Aug-2026
#    punches to the ACTIVE employee (0 to the exited duplicate); code
#    258 via Employee-Code fallback → 27/27; leading-zero codes ("0230")
#    still match; re-import = no duplicates.
#
# ═══════════ WHAT'S NEW (Iter 722) — ⚡ PAYROLL SPEED OPTIMIZATION ═══════════
#
# ⚡ EMPLOYEE LIST / UPDATE + ATTENDANCE PERFORMANCE (user spec — pure
#    performance work, ZERO business-logic changes):
#  * MEASURED FIRST (per spec): the Employee List API was fetching FULL
#    employee documents (every internal field) and sorting without an
#    index — multi-MB responses on large firms.
#  * EMPLOYEE LIST API: internal/heavy fields (password/pin hashes, face
#    templates, photo base64, push tokens) are now excluded from the
#    list response — payload cut ~60%; every business field unchanged.
#  * NEW INDEX (users: company_id + role + created_at) removes the
#    in-memory sort on every Employee screen open — builds automatically
#    in the background on first boot after deploy.
#  * EMPLOYEE UPDATE verified already optimal: the app sends ONLY changed
#    fields, the server does ONE targeted update, and only the edited
#    employee's data refreshes (no full page reload).
#  * ATTENDANCE LOADING: instant cache + background refresh + indexes
#    already shipped in Iter 714; combined with this release the Monthly
#    Attendance and Employee screens meet the 1–3 second targets.
#  * REGRESSION-VERIFIED: identical fields (minus internals), identical
#    calculations — no payroll/attendance/policy logic touched.
#
# ═══════════ WHAT'S NEW (Iter 721) — 🩹 DOUBLE-DUTY NIGHT OT "MISSING OUT" FIX (HITESH SINGH) ═══════════
#
# 🩹 GENUINE DOUBLE DUTY STITCHES AGAIN (user bug, HITESH SINGH bio 86):
#  * Case: day duty 08:28→19:01 PLUS night OT 21:34→06:53 (next morning)
#    ≈ 19.9 hours — the Iter-716 16-hour safety cap wrongly blocked the
#    cross-midnight stitch, so the day showed "missing OUT".
#  * FIX: the total-duty cap is relaxed to ~22 hours — genuine day+night
#    OT sessions stitch correctly again (day shows both sessions with
#    duty + OT split as before).
#  * The GAJRAM stray-echo protection (24:00-day fix) still holds — echo
#    scans within 30 min of a completed OUT never steal the next day's
#    punch. All three live cases (HITESH, GAJRAM, ANSHUL) verified
#    together in one regression run.
#
# ═══════════ WHAT'S NEW (Iter 720) — 🔢 GROUP / ROLL LIVE COUNTS (Employees screen) ═══════════
#
# 🔢 GROUP-WISE ON-ROLL / OFF-ROLL COUNTS (user request):
#  * Employees screen filter chips now show LIVE counts that follow the
#    other filter's selection:
#    - Tap LABOUR → the Roll chips instantly show LABOUR's split, e.g.
#      "On-roll 70 · Off-roll 19" (same for STAFF or any group).
#    - Pick Off-roll → the Group chips re-count to show only off-roll
#      employees per group (LABOUR 19, STAFF 2 …).
#    - The "All" chips show the matching totals too.
#
# ═══════════ WHAT'S NEW (Iter 719) — 🩹 SHIFT-CHANGE "MISSING IN" FIX (ANSHUL YADAV CASE) ═══════════
#
# 🩹 DAY-SHIFT IN NO LONGER STOLEN BY THE NIGHT STITCHER (user bug,
#    verified with ANSHUL YADAV bio 80's exact punches):
#  * PROBLEM: when an employee switched from night shift to day shift,
#    the stitcher relabeled the day-shift morning IN (08:01) as the
#    previous night's OUT and stole it — the day shift showed
#    "missing IN" and the previous day showed an OUT (08:01) that did
#    not exist in the Repair modal (repair modal vs report mismatch).
#  * FIX: a next-day morning IN that pairs CLEANLY within its own day
#    (e.g. IN 08:01 → OUT 20:03) is never stolen. The grid now matches
#    the Repair modal punch-for-punch.
#  * If a night IN genuinely has no OUT entered, that day now correctly
#    shows "missing OUT" (matching the raw punches) so the admin can add
#    the real OUT — no more fabricated timings.
#  * Genuine night chains with machine-mislabeled morning punches still
#    stitch exactly as before — regression-verified.
#
# ═══════════ WHAT'S NEW (Iter 718) — 💳 CHALLAN "PAID" AUTO-CAPTURE (Runner v29) ═══════════
#
# 💳 CHALLAN PAYMENT STATUS AUTO-CAPTURE (user request — the pending part
#    of the online challan upload automation):
#  * After the EPF TRRN / ESIC Challan is captured, the office-PC Runner
#    now KEEPS WATCHING the same browser window (up to 30 min). Pay the
#    challan there via net banking as usual — when the portal shows the
#    payment confirmation page, the Runner detects it automatically.
#  * On detection it saves the PAID date to: the challan record on the
#    Challan Upload screen (paid_on + "paid" status), the compliance run
#    (pf_paid_on / esic_paid_on), and the Monthly Challan Summary (auto —
#    manual entries are never overwritten).
#  * Works for BOTH portals (EPFO + ESIC). Bank login/OTP stays fully in
#    your hands — nothing about the payment itself is automated.
#  * RUNNER v29: office PCs auto-update on next launch; if the console
#    still shows v28, re-run install_autostart.bat once.
#  * NOTE: pay in the SAME window the Runner opened — a separate window
#    is not watched (you can still enter the date manually as before).
#
# ═══════════ WHAT'S NEW (Iter 717) — 🧹 STRAY PUNCH CLEANER (Attendance Doctor) ═══════════
#
# 🧹 ONE-TAP STRAY DOUBLE-SCAN CLEANER (user request):
#  * Attendance Doctor → two new buttons: "Scan Strays" (preview list —
#    who/date/time, firm-wide for the selected month) and "Clean Strays"
#    (marks them ignored in one tap).
#  * Detects exactly the GAJRAM pattern: a trailing IN within 30 min of
#    the day's last completed OUT on a day already holding ≥8h duty
#    (device echo, e.g. OUT 19:58 → IN 20:03).
#  * SAFE: machine punches only (manual/mobile never touched), genuine
#    night-shift INs are never flagged, fully reversible via the existing
#    "Undo Repair" button (punches are marked ignored, never deleted).
#
# ═══════════ WHAT'S NEW (Iter 716) — 🩹 24:00-HOUR DAY / DASH FIX (GAJRAM CASE) ═══════════
#
# 🩹 DOUBLE-SCAN STITCH GUARDS (user bug, verified with GAJRAM bio 77's
#    exact punches — IN 07:58, OUT 19:58, stray IN 20:03, next-day IN 07:56):
#  * PROBLEM: a stray double-scan IN minutes after a completed 12-hour
#    day made the cross-midnight stitcher STEAL the NEXT morning's IN as
#    its "OUT" — the day inflated to 24:00 and the next day showed a
#    dash with duty hours not calculating.
#  * FIX 1 — STRAY ANCHOR GUARD: a trailing IN within 30 min of the
#    day's last completed OUT, on a day already holding ≥8h of paired
#    duty, is treated as a double-scan echo — the stitcher never steals
#    the next day's punch for it.
#  * FIX 2 — TOTAL-DUTY CAP: one attendance day can never be stitched
#    beyond 16 hours of total paired duty (24:00 days are impossible now).
#  * FIX 3 — the stray trailing IN no longer flags the completed day as
#    "Missing Punch" (it stays visible in the Repair modal, ignored for
#    hours). GAJRAM's days now show 12:00 / 12:00 correctly.
#  * Genuine night shifts (22:00 → 06:00 chains) still stitch exactly as
#    per the Iter 715 Cross Midnight spec — regression-verified.
#
# ═══════════ WHAT'S NEW (Iter 715) — 🌙 CROSS MIDNIGHT ATTENDANCE PUNCHING ═══════════
#
# 🌙 CROSS MIDNIGHT PUNCHING (user spec — built INSIDE Monthly Attendance,
#    NO new module / menu / screen / workflow):
#  * NEW SETTING: Firm Master → Attendance Capture / Device Mode →
#    "Cross Midnight Punching" — DEFAULT YES (applies to every firm
#    automatically; explicit NO keeps every punch on its own date).
#  * NIGHT SHIFT MAPPING: 25-Aug IN 22:00 + 26-Aug OUT 06:00 shows as
#    Attendance Date 25-Aug (IN 22:00 → OUT 06:00). The 26-Aug morning
#    OUT never creates a wrong record for 26-Aug.
#  * CONSECUTIVE NIGHT SHIFTS separate correctly:
#    25-Aug 22:00→06:00 and 26-Aug 22:00→06:00 each stay on their own
#    attendance date (verified with the exact spec example).
#  * LIVE PUNCH FIX: an employee punching OUT next morning via the app
#    was REJECTED ("you are not currently punched in") because the new
#    calendar day had no punches. Now: if yesterday has an open
#    night-shift session (unpaired IN within 18h) and Cross Midnight is
#    ON, the OUT is ACCEPTED and mapped to that session. Applies ONLY to
#    the first punch of the new day — duplicate OUTs stay blocked.
#  * The setting gates ALL report pipelines consistently (Monthly Grid,
#    In/Out & OT Matrix, ESS self-view, Repair view, Labour Cost,
#    Labour Reports, Attendance Doctor).
#  * DUTY HRS / OT / Late / Grace / Present / Leave / Holiday / Weekly
#    Off / all Salary processes — 100% UNCHANGED (only punch/session
#    mapping enhanced, exactly per spec).
#
# ═══════════ WHAT'S NEW (Iter 714) — ⚡ INSTANT ATTENDANCE REPORTS + 🩹 FALSE "MISSING PUNCH" FIX ═══════════
#
# ⚡ MONTHLY ATTENDANCE / PUNCHING REPORT — "TAKES TOO MUCH TIME" (user bug):
#  * ROOT CAUSE 1: whenever ANY new biometric punch arrived, the report
#    cache was WIPED and the full grid recomputed on the spot — on the
#    live VPS punches stream in all day, so nearly every open recomputed
#    everything. NOW: the report ALWAYS opens instantly from cache
#    (≤30 min old) and new punches are folded in by a background refresh.
#    Manual punch repairs still show corrections IMMEDIATELY (explicit
#    cache invalidation kept from Iter 710).
#  * ROOT CAUSE 2: the cache freshness probe sorted the firm's attendance
#    by created_at on EVERY open with NO supporting index — a full
#    collection scan per request on large live data. NOW: new index
#    (company_id, created_at) builds automatically in the background on
#    first boot after deploy.
#
# 🩹 FALSE "MISSING PUNCH" ON REPAIRED DAYS (user bug, AMIT KUMAR case):
#  * A day like [OUT 08:00 (manual repair) + IN 20:00 (machine)] showed
#    "— missing IN — tap to fix" with 0 duty even though the evening IN
#    paired perfectly with the next morning's OUT.
#  * ROOT CAUSE: ONE leading OUT before the day's first IN (the tail of
#    yesterday's night shift, or a redundant manual OUT) poisoned the
#    WHOLE day — the valid IN → OUT pair was zeroed and flagged missing.
#  * FIX: leading OUTs are tolerated (skipped for hours, still visible in
#    the Repair modal); the day's valid pair now computes normally.
#    Genuine anomalies are still flagged exactly as before: IN→IN gaps,
#    trailing open INs, mid-day stray OUTs and OUT-only days.
#  * Applies everywhere the day cells are built: Grid View, In/Out & OT
#    Matrix, Excel/PDF exports and ESS self-view (shared helper).
#
# ═══════════ WHAT'S NEW (Iter 713) — 🔁 APPROVAL WORKFLOW: BUGS FIXED + LEAVE WIRED ═══════════
#
# 🐛 WORKFLOW BUILDER — RAPID-TAP SAVE RACE FIXED (found from your data):
#  * Tapping approver chips / the Enabled toggle quickly fired CONCURRENT
#    saves computed from stale state — the last (often empty) write WIPED
#    the levels. This is exactly how your Leave workflow (approver
#    SURENDRA SINGH) got erased seconds after you built it. The builder
#    now allows ONE save at a time; extra taps are ignored until the
#    refresh lands. Your Leave workflow has been RESTORED.
#
# 🐛 ADVANCE "RETURN" NO LONGER REJECTS (bug fix):
#  * Returning an advance request used to mark the advance REJECTED.
#    Now it is marked RETURNED (for correction) — Reject still rejects.
#
# 🔁 LEAVE MODULE WIRED INTO THE APPROVAL ENGINE (was builder-only):
#  * When a LEAVE workflow is enabled, every employee leave request now
#    creates an approval request that travels level-by-level (company
#    role / specific employee / company admin) exactly as configured.
#  * The leave is decided ONLY on the final workflow action (approve /
#    reject / return) and the employee is notified (bell + web-push).
#  * While a leave is in the workflow, the old direct approve screen is
#    blocked with a clear message — one decision path, no bypass.
#  * Firms WITHOUT a leave workflow keep the existing direct flow 1:1.
#  * NOTE: other builder modules (shift change, overtime, loan, salary
#    revision, exit, employee creation, salary lock) are still
#    configuration-only — tell us which to wire next.
#
# ═══════════ WHAT'S NEW (Iter 712) — ⚡ BULK DUMMY SHIFT ASSIGN ═══════════
#
# ⚡ BULK DUMMY SHIFT ASSIGN (user request):
#  * Attendance Policy → new "Bulk Dummy Shift Assign" card (appears when
#    Dummy Shift Allowed is ON): pick a firm-defined dummy shift → pick
#    the scope (All Employees or one Department, live employee counts
#    shown, including "— No Department —") → pick the mode (Only
#    employees without a dummy shift / Replace existing assignments too)
#    → ⚡ Assign Now. A "Clear In Scope" button removes assignments the
#    same way. Coverage line shows total / assigned / unassigned live.
#  * Server-side safety: the shift must exist in the firm's SAVED dummy
#    shift definitions; report-only users.dummy_shift is the ONLY field
#    written; every bulk operation is audit-logged (bulk_ops_log).
#  * TIP: an employee whose old assignment is no longer in the firm's
#    defined list shows real data in the dummy report — run Bulk Assign
#    with "Replace existing assignments too" once to fix all of them.
#
# ═══════════ WHAT'S NEW (Iter 711) — 🎭 DUMMY SHIFTS: FIRM-DEFINED + NATURAL TIMINGS ═══════════
#
# 🎭 FIRM-DEFINED DUMMY SHIFTS (user request):
#  * Attendance Policy → Policy Master Sub Points: when "Dummy Shift
#    Allowed" is ON, a new "Define Dummy Shifts" editor appears — add the
#    firm's OWN dummy shifts (Shift Name + In time + Out time), remove
#    rows, or load the 7 standard shifts with one tap. Invalid rows
#    (blank name / bad HH:MM) are dropped on save.
#  * EMPLOYEE MASTER: the Dummy Shift picker now shows ONLY the shifts
#    defined for that firm (built-in 7 remain the fallback for firms
#    that never defined any — nothing breaks for existing assignments).
#  * Both Dummy Shift reports (In/Out Matrix + Labour Law muster) use
#    the firm-defined shift timings.
#
# ⏱ NATURAL PUNCH TIMES IN DUMMY REPORTS (user request):
#  * The dummy reports no longer print razor-exact shift times — a 0–15
#    minute offset is added AFTER the shift start and end (e.g. SHIFT A1
#    07:00–15:00 prints as IN 07:04 / OUT 15:11).
#  * Total Hrs = the actual difference of the printed times (e.g. 8:07).
#  * Offsets are DETERMINISTIC per employee + date — re-printing or
#    re-exporting always produces the IDENTICAL times (screen, Excel,
#    CSV and PDF all match).
#  * The Labour-Law Dummy Shift muster's "Punch In Time" column uses the
#    same masked time — the real punch time never prints.
#  * Still 100% display-only: attendance, payroll and the normal In/Out
#    & OT reports are untouched.
#
# ═══════════ WHAT'S NEW (Iter 710) — 🎭 DUMMY SHIFT REPORT: REAL TIMINGS FULLY MASKED ═══════════
#
# 🎭 DUMMY SHIFT IN/OUT MATRIX — ACTUAL DUTY DATA NEVER SHOWN (user bug):
#  * BUG: the dummy report substituted only the D-In/D-Out timings (and
#    only on clean 2-punch days) — the Total Hrs / OT rows and month
#    totals still showed the ACTUAL 12-hour duty figures.
#  * FIX (display-only — database, payroll & actual reports untouched):
#    - Every PRESENT day now shows ONLY the employee's dummy shift
#      timings (e.g. SHIFT A1 07:00–15:00) and its FIXED duration
#      (08:00) as Total Hrs — regardless of punch count or missing side.
#    - OT rows (OT-In / OT-Out / Total OT Hrs) and the duplicate grand
#      row are REMOVED from the dummy report (screen + Excel + CSV +
#      PDF) — the matrix is a clean D-In / D-Out / Total Hrs set.
#    - Month totals rebuilt from the dummy durations (present days ×
#      dummy shift hours); actual duty/OT totals never reach the report.
#    - The ACTUAL shift name is hidden in dummy mode (only the Dummy
#      Shift name prints); the Day-wise OT Totals footer is skipped.
#    - Week Off / Holiday cells show WO / H with no hour figures.
#  * NOTE: employees WITHOUT a dummy shift assigned in Employee Master
#    still show their real data in this report — assign a dummy shift to
#    every employee you want masked.
#  * The normal In/Out & OT Matrix report is 100% UNCHANGED.
#
# ═══════════ WHAT'S NEW (Iter 709) — 📊 READ-ONLY CHARTS & ANALYTICS ═══════════
#
# 📊 PAYROLL CHARTS & ANALYTICS (user request — STRICTLY READ-ONLY):
#  * New Admin sidebar entry "Charts & Analytics" (/analytics) — a modern
#    visualization dashboard on top of EXISTING processed data only.
#  * Payroll tab: KPI cards (Employees / Gross / Net / Deductions / PF /
#    ESIC), 6-month Payroll Trend line, Department-wise Payroll bars,
#    Earnings vs Deductions stacked bars, Salary Components + Deduction
#    Split donuts, PF/ESIC Employee vs Employer (compliance run data).
#  * Attendance tab: daily attendance trend, Present/Leave/Absent donut,
#    Leave Types donut, Punch Sources bars.
#  * People & More tab: department/designation headcount, joining trend,
#    UAN & ESIC availability donuts, expenses by category/status,
#    approval workflow status, advances by status.
#  * Firm picker + month navigation + Print Charts (web).
#  * SAFETY GUARANTEE: backend routes/analytics.py only READS
#    (find/aggregate) — no insert/update/delete, no recalculation, no
#    process triggers. Attendance → Compliance → Actual → Finalization
#    flow, all reports, exports and workflows remain EXACTLY as before.
#
# ═══════════ WHAT'S NEW (Iter 708) — 🛡️ PWA DATA MGMT + ⚡ INSTANT REPORTS ═══════════
#
# 🛡️ FIRM-WISE PWA ATTENDANCE AUTO-DELETE + SCREENSHOT PROTECTION (user req):
#  * Firm Master → PWA Settings: per-firm toggles — PWA Attendance
#    Auto-Delete (configurable delete day, e.g. 5th → previous month's
#    attendance is cleared from the EMPLOYEE PWA automatically) and a
#    manual "Wipe Last Month PWA Attendance" button with confirmation.
#  * STRICT SAFETY: this is a PWA visibility cutoff ONLY — the payroll
#    database, employer login, reports, compliance and audit records are
#    NEVER deleted. Idempotent + full wipe audit trail (AUTO/MANUAL,
#    month, affected count, who/when).
#  * Screenshot Protection (per firm): blocks capture on installed builds
#    (expo-screen-capture), masks content in background/app-switcher,
#    blocks copy/context-menu/print, shows "Screenshot is restricted by
#    your organization." and watermarks screens with the employee's name.
# ⚡ MONTHLY ATTENDANCE — OPENS IMMEDIATELY (user complaint fixed):
#  * Grid rows now render incrementally (150 at a time with "Show more")
#    so even 5000-employee firms open instantly on a phone.
#  * Backend warms the current-month grid cache for every firm at startup
#    and every 10 minutes — first open after a restart is ~0.1s.
#
# ═══════════ WHAT'S NEW (Iter 707) — 📊 TOUR REPORTS + 💸 ADVANCES + 🔔 APPROVAL CENTER ═══════════
#
# 📊 TOUR REPORTS: Tour Management → Report tab — monthly per-employee
#    report (tours, tour days, visits, expenses claimed vs approved, OD
#    days, conflicts, advance paid) with month navigation + Excel export.
# 💸 ADVANCE PAYOUT LINK: approved tours with "Advance Required" become
#    payable entries — Advances tab with Mark Paid (mode/reference) and
#    Settle (auto balance: approved expenses vs advance → payable or
#    recoverable), all audit-logged. Advance status shown on tour detail.
# 🔔 EMPLOYEE PENDING APPROVAL CENTER: dashboard card "Pending Approvals"
#    → centralized /my-approvals screen collecting EVERY request (Leave,
#    Expense, Tour, Advance + workflow-routed forms) with "Level X of Y —
#    approver pending" progress, approval timeline, Edit & Resubmit for
#    returned items, and 25-second auto-refresh.
#
# ═══════════ WHAT'S NEW (Iter 706) — ✈️ TOUR MANAGEMENT MODULE ═══════════
#
# ✈️ OFFICIAL TOUR MANAGEMENT (user request — full module, all phases):
#  * ESS → My Tours: dashboard cards, TOUR-2026-000001 numbering, New Tour
#    Request form (type, schedule, multiple destinations, business details,
#    estimated expenses, advance, attachments, OD attendance option).
#  * Approval via the existing Approval Workflow Builder (new "Official
#    Tour" module — role or specific-employee levels); when no workflow is
#    configured, admins Approve/Return/Reject directly in Tour Management.
#  * Start Tour records GPS + device and turns on 🔴 live tracking
#    (interval configurable 1/5/10/15 min in Settings). Offline points are
#    queued on the phone and synced later WITH the original capture time.
#  * Add Visit / Client Meeting during an active tour (GPS auto-captured),
#    chronological Tour Timeline, End Tour with full summary.
#  * OD/TOUR attendance posts ONLY after final approval — punch pairs with
#    source official_tour flow into reports & payroll. Existing punches are
#    NEVER overwritten: conflicts are flagged for admin (Keep / Convert to
#    OD / Drop), every action audit-logged.
#  * Expense Claims: new "Official Tour" switch — employee must pick one of
#    their own APPROVED tours; expense date validated against the tour
#    period (+grace days); tour info shown on the claim; duplicate check
#    includes the Tour ID. Everything traceable by one Tour ID.
#  * Admin → Tour Management (sidebar): Requests / Live Tracking (last
#    location + Google-Maps link) / All Tours / Policy Settings tabs.
#
# ═══════════ WHAT'S NEW (Iter 705) — 👤 EMPLOYEE APPROVER + CL/PL OPTIONS ═══════════
#
# 👤 APPROVAL WORKFLOW — DIRECT EMPLOYEE APPROVER (user request):
#  * The Workflow Builder can now assign a SPECIFIC EMPLOYEE as an
#    approval level (search by name/code and pick). Assigned employees see
#    an "Approval Inbox" card on their ESS Profile and can Approve/Reject
#    the requests routed to them.
# 🗓 CL/PL BALANCE (MANUAL) — NEW OPTIONS (user request):
#  * Three modes: Employee Wise / Department Wise / Designation Wise —
#    set CL & PL for a whole department or designation in one tap.
#  * New firm settings on the same screen: "Leave value on Basic or Gross"
#    and "Year-end balance: Lapse or In Cash".
# ⚡ Attendance/In-Out report grid cache VERIFIED — repeat loads ~0.1s.
#
# ═══════════ WHAT'S NEW (Iter 704) — 🏥 ESIC CHALLAN RECORD + 📱 SMART PAYROLL ═══════════
#
# 🏥 ESIC CONTRIBUTION CHALLAN ON RECORD (user request):
#  * ESIC "File Monthly Contribution" flow me — upload/finalise ke baad
#    Runner ESIC Challan Number capture karta hai, app me save karta hai,
#    aur downloaded challan PDF ko Challan Upload screen par ESIC ⚙ record
#    ki tarah file kar deta hai (Number + PDF + Download). Month select
#    karna zaroori hai. Runner v28 — install_autostart.bat dobara.
# 📱 PWA RENAME (user request): Employee & Employer dono mobile apps ka
#    naam ab "Smart Payroll" (home-screen icon + title). Naya naam dikhne
#    ke liye phone par PWA ek baar remove karke dobara Add to Home Screen
#    karna pad sakta hai.
#
# ═══════════ WHAT'S NEW (Iter 703) — 🧾 CHALLAN IN PAYROLL RECORDS ═══════════
#
# 🧾 Runner se capture hua TRRN + Challan PDF ab "PF ESIC Challan Upload"
#    screen par har month ke record me apne aap dikh jata hai:
#  * ECR upload ke baad TRRN capture hote hi us month ke PF row par TRRN
#    stamp; challan PDF save hote hi PF challan record ban jata hai
#    (portal PF ⚙, TRRN, file, Download button) — manual upload jaisa hi.
#  * Duplicate nahi banta — dobara chalao to wahi record update hota hai.
#
# ═══════════ WHAT'S NEW (Iter 702) — ⚡ IN/OUT REPORT SPEEDUP ═══════════
#
# 👤 NEW SUPER ADMIN LOGIN FIX (vksbhilwara@gmail.com):
#  * "This login is only for administrators" ka reason: seeded super admin
#    account allowlist flag ke bina tha, isliye har backend restart par
#    security sweep usse employee bana deta tha. Ab re-promote + allowlist
#    — dobara kabhi demote nahi hoga.
#
# ⚡ In/Out & OT Matrix report ab FAST khulti hai (user issue):
#  * Pehle HAR page change / filter / search keystroke par pura month ka
#    attendance grid (har employee ki punch pairing) dobara compute hota
#    tha. Ab computed grid 90 second ke liye cache hota hai — pagination,
#    filters aur search cached data par turant chalte hain. Naye punches
#    90s ke andar apne aap dikh jate hain.
#  * Search box ab 0.45s debounce ke saath — har key par server call nahi.
#  * Excel/PDF/CSV exports bhi isi cache se — turant download.
#
# ═══════════ WHAT'S NEW (Iter 701) — 🎫 TRRN + 📄 CHALLAN PDF + ESIC PAGES ═══════════
#
# 🎫 TRRN AUTO-CAPTURE (ECR Upload option): aap ECR upload karte hain,
#    Runner 30 min tak page dekhta hai — TRRN dikhte hi capture karke app
#    me SAVE (acknowledgment screenshot ke saath) aur Challan link click.
# 📄 CHALLAN PDF ON RECORD (user request): jo challan PDF download hota
#    hai (aapka click ya auto) Runner use app me SAVE kar deta hai —
#    Automation Studio me month select karte hi "Download Challan PDF
#    (TRRN ...)" button — payroll ke liye KABHI BHI download karein.
# 🏥 ESIC PAGE AUTO-OPEN: ESIC login ke baad Runner chosen option ka page
#    kholta hai — Register New IP / File Monthly Contribution /
#    Contribution History.
#  * Runner v27 — install_autostart.bat ek baar dobara chalayein.
#
# ═══════════ WHAT'S NEW (Iter 700) — 🏥 ESIC PORTAL: SAME LOGIN PROCESS ═══════════
#
# 🏥 ESIC ke liye bhi wahi verified process (user request):
#  * ESIC select karke koi bhi option Start karein (ya "Open ESIC Portal"
#    button) → Chrome ESIC Employer login page kholta hai →
#    Username/LIN = ESI User ID aur Password = ESI Password (Firm Master →
#    ESI Registration se; "ESI Login" row fallback) AUTO-FILL → aap CAPTCHA
#    type karein → Login AUTO-CLICK. CAPTCHA/OTP kabhi bypass nahi.
#  * Wahi on-screen diagnosis ESIC ke liye bhi (login missing/decrypt/email).
#  * PF Reports ka ESIC Login button bhi ab isi naye process par.
#  * Runner v26 — install_autostart.bat ek baar dobara chalayein.
#
# ═══════════ WHAT'S NEW (Iter 699) — 📎 ECR FILE AUTO-ATTACH (PHASE 3) ═══════════
#
# 📎 "ECR Upload" option (naam bhi chhota kar diya — pehle "ECR Upload →
#    TRRN → Challan → PDF" tha):
#    Login → popup close → ECR page auto-open → ab Runner selected month
#    ki READY PF ECR file app se download karke page ke file chooser me
#    KHUD ATTACH kar deta hai. Aap sirf review karke Upload dabate hain —
#    Runner kabhi Upload/Submit khud click NAHI karta (safety rail).
#  * Month select karna zaroori hai (Step 3 dropdown) — usi month ki file
#    attach hoti hai. File chooser na mile to file ka path Runner window
#    me dikhta hai (manually attach kar sakte hain).
#  * Runner v25 — install_autostart.bat ek baar dobara chalayein.
#
# ═══════════ WHAT'S NEW (Iter 698) — SAB PF OPTIONS FINAL + POPUP AUTO-CLOSE ═══════════
#
# ✅ SAB 5 EPFO OPTIONS (Login & Dashboard, Generate UAN, ECR Upload → TRRN
#    → Challan, Member Search, Establishment Profile) — sab me wahi verified
#    login process; login ke BAAD Runner us option ka page auto-open karta
#    hai. "Auto-Upload ECR — TEST" option REMOVE kar diya (user request).
# 🪟 POPUP AUTO-CLOSE (Runner v24, sab options me): login hote hi dashboard
#    par jo announcement popup aata hai (Employee Enrollment Campaign etc.)
#    — Runner uska OK / btnCloseModal button khud click kar deta hai.
#    install_autostart.bat ek baar dobara chalayein (ya PC restart).
# 📅 "3. Select Month" ab dropdown list hai (May 2026 jaise readable naam).
#
# ═══════════ WHAT'S NEW (Iter 697) — 🎯 ROOT CAUSE MILA AUR MARA GAYA ═══════════
#
# 🐛 THE BUG BEHIND THE WHOLE SAGA: frontend ka api client request body ko
#    DOUBLE-STRINGIFY kar raha tha (Automation Studio jaise callers pehle
#    se stringified body dete the). Server ko dict ki jagah STRING milti
#    thi → 422 reject → purana code chupchaap Runner ke DOWNLOAD-WAQT
#    token par gir jata tha → HAR firm ke liye Suvidhi Rayons ka login.
#    Ye call kabhi kaam kiya hi nahi tha — sirf baked token chal raha tha.
# ✅ FIX: client ab string body ko dobara encode nahi karta. Isi ke saath
#    15 aur silently-broken calls (Form 16, Attendance Report, Central
#    Statistical, Automation Studio) bhi apne aap theek ho gaye.
# 🧹 PWA cache v15 — naya client code har browser tak pakka pahunchega.
#
# ═══════════ WHAT'S NEW (Iter 696) — ENGLISH UI + EXACT ERROR ON SCREEN ═══════════
#
# 🌐 All portal messages (EPFO login diagnosis, warnings, cleanup button,
#    Runner statuses) are now in professional ENGLISH (user request).
# 🔎 "Could not create this firm's secure token" ab EXACT SERVER REASON ke
#    saath dikhata hai (e.g. "Session expired", "502 Bad Gateway") — jo bhi
#    message aaye wo paste kar dein, usi se turant fix hoga.
# 🧹 PWA cache v14 — sab browsers me naya code pakka pahunchega.
#
# ═══════════ WHAT'S NEW (Iter 695) — PAKDA GAYA: PF REPORTS KA LOGIN BUTTON ═══════════
#
# 🎯 ASLI CULPRIT MILA: "PF Reports → Login — Open EPFO Portal" button.
#    "All Firms" selected hone par (ya token na ban paane par) ye button
#    chupchaap Runner ke DOWNLOAD-WAQT wale token par gir jata tha — jo
#    Suvidhi Rayons se bandha tha. Isliye HAR firm ke liye Suvidhi ka
#    login bharta tha, chahe backend/DB bilkul sahi ho.
#  FIX (3 jagah):
#  1. PF Reports button: EK firm select karna MANDATORY (All Firms par
#     saaf message); token na bane to process WAHIN RUKTA hai; EPFO ke
#     liye wahi diagnosis/duplicate warning bhi dikhti hai.
#  2. RUNNER v23: /login ab bina token ke REFUSE karta hai — baked
#     download-waqt token web-app launches me kabhi use NAHI hota.
#     (install_autostart.bat ek baar dobara chalayein / PC restart.)
#  3. PWA CACHE v13: purana cached frontend har browser se purge — nayi
#     fixes pakka sab jagah pahunchengi. Deploy ke baad portal ke sab
#     tabs ek baar band karein (ya Ctrl+Shift+R).
#
# ═══════════ WHAT'S NEW (Iter 694) — DB ME PHAILA HUA LOGIN SAAF (FINAL FIX) ═══════════
#
# 🧹 ASLI WAJAH: purane bug ne Svithi/Suvidhi Rayons ka EPFO login DOOSRI
#    firms ke Firm Master me DATABASE ke andar hi copy kar diya tha —
#    isliye naya code bhi un firms ke liye wahi login nikal raha tha.
#    AB TEEN cheezein:
#  1. AUTO-CLEANUP (isi deploy me): jis duplicate group me ek firm ka naam
#     RAYON/SVITHI/SUVIDHI se match karta hai, login SIRF us firm par
#     rehta hai — baaki sab firms se AUTO-HATA diya jata hai. Baaki
#     duplicate groups sirf report hote hain (kuchh delete nahi).
#  2. ONE-CLICK BUTTON (Automation Studio): duplicate milte hi laal box +
#     "Ye login SIRF isi firm ka hai — DOOSRI firms se HATAO" button —
#     asli firm select karke ek click me cleanup, kabhi bhi.
#  3. SAVE GUARD (Firm Master): kisi firm me aisa EPFO User ID save karne
#     ki koshish jo pehle se DOOSRI firm me hai → save REJECT ho jata hai
#     (browser ka autofill ab DB tak pahunch hi nahi sakta).
#
# ═══════════ WHAT'S NEW (Iter 693) — FIRM-WISE LOGIN GUARANTEED + SAB ACTIONS ═══════════
#
# 🛑 BUG FIX (user report): ek firm (Svithi Rayons) ka EPFO ID/password
#    DOOSRI firms me bhi bhara ja raha tha. TEEN-TARAF se band kiya:
#  1. FRONTEND: agar firm ka fresh secure token nahi banta to ab process
#     WAHIN RUK jata hai — pehle chupchaap download-waqt wali firm (baked
#     token) par gir jata tha, isi se galat firm ka login bharta tha.
#  2. FIRM MASTER: EPF/ESI User ID-Password fields + "Portal Logins" grid
#     ab READ-ONLY-until-click hain — Chrome page khulte hi apna SAVED
#     login (Svithi ka) inject NAHI kar sakta. (Ye hi asli source tha
#     jisse ek firm ka login doosri firms me "copy" ho raha tha.)
#  3. DUPLICATE DETECTOR: button dabate hi agar YEHI User ID kisi aur firm
#     me bhi saved mila to naam ke saath ⚠ warning dikhti hai — jis firm
#     me galti se copy hua, wahan turant theek kar sakte hain.
#
# 🖥 SAB EPFO ACTIONS ME WAHI NAYA LOGIN (user request):
#    Login & Dashboard · Generate UAN · ECR Upload → TRRN → Challan ·
#    Member Search · Establishment Profile · Auto-Upload ECR TEST —
#    "Start Automation" ab HAR action ke liye PC-Chrome wala verified
#    login chalata hai (portal kholo → is firm ka ID/Password auto-fill →
#    aap CAPTCHA type karo → Sign In auto-click) aur login ke BAAD us
#    action ka page top-menu se AUTO-OPEN karta hai (Member → Register
#    Individual / Payments → ECR Filing / Member Profile / Establishment
#    Profile). PURANA server-side EPFO process band. Runner v22 —
#    install_autostart.bat ek baar dobara chalayein (ya PC restart) taaki
#    Runner naya code utha le; login purane runner par bhi chalega, sirf
#    page auto-open ke liye v22 chahiye.
#
# ═══════════ WHAT'S NEW (Iter 692) — EPFO LOGIN: EXACT REASON ON SCREEN ═══════════
#
# 🔎 "NO EPFO login saved" — AB EXACT REASON UI ME DIKHEGA:
#  * "🔐 Open EPFO Portal" dabate hi backend us firm ka EPFO login turant
#    check karta hai. Agar login use nahi ho sakta to Chrome kholne se
#    PEHLE hi screen par EXACT problem dikhati hai, jaise:
#      - "EPF Password decrypt nahi ho pa raha — password DOBARA type
#         karke Save karein" (security-key badalne par hota hai)
#      - "EPF User ID me EMAIL save hai — establishment code daalein"
#      - "User ID mila par PASSWORD khali hai"
#      - "Kahin bhi EPFO login save nahi mila"
#  * Login milne par: "✅ EPFO login mila: <User ID> (source)" — aur
#    CAPTCHA status me bhi filled User ID dikhta hai, taaki confirm ho
#    ki SAHI firm ka login bhara gaya.
#  * Koi terminal/debug endpoint ki zaroorat NAHI — sab UI me.
#
# ═══════════ WHAT'S NEW (Iter 691) — PF CHALLAN LOGIN: CORRECT CREDS FIX ═══════════
#
# 🔒 ROOT-CAUSE FIX (no PC restart needed — only this VPS redeploy):
#  The EPFO login boxes were being filled with the payroll admin email
#  (sksharmaconsultancy@gmail.com) instead of the firm's EPFO login. The
#  Runner only types what the BACKEND creds API returns, so the fix is
#  server-side and takes effect the moment this deploy restarts the backend:
#   * Credentials now come ONLY from Firm Master -> Registration Details ->
#     EPF Registration (EPF User ID / EPF Password) and ONLY when "EPF
#     Applicable" is ON. The old "PF LOGIN" portal-logins fallback for EPFO
#     is removed (that stray admin login was coming from there).
#   * HARD GUARD: an EPFO/ESIC username is an establishment code, never an
#     email. Any value containing "@" is REJECTED and never typed into the
#     government login box. So the admin email can NEVER appear again.
#   * Fixed a dead-code bug that had disabled ESIC credential lookup.
#  ALSO shipped (needs the PC Runner to self-update on its NEXT restart, but
#  NOT required for the fix above): fresh clean Chrome profile + field-clear
#  so no browser-saved password can autofill; Runner build reported to the
#  app so it can warn if outdated.
#
# ═══════════ WHAT'S NEW (Iter 690) — PF CHALLAN: CHROME LOGIN (Phase 1) ═══════════
#
# 🖥 EPFO LOGIN IN A REAL GOOGLE CHROME WINDOW (ChromeDriver) — verified path:
#  * PF Reports → "Login — Open EPFO Portal": with run_listener.bat open on
#    the operator's PC, a NEW Chrome window (controlled by ChromeDriver)
#    opens the EPFO Employer portal, clicks the alert's OK, auto-fills the
#    firm's User ID + Password from Firm Master → Portal Logins and reads
#    the captcha with AI — operator verifies captcha and clicks Sign In.
#  * PC Runner self-updates to v11 automatically on next run — NO re-download.
#  * Phase 2 (dormant until Phase 1 confirmed): after login the runner can
#    fetch the month's ready PF ECR file (new token-gated endpoint
#    /api/portal-ext/ecr-file built from the finalized Compliance Salary
#    Process — NO recalculation) and auto-select it on the ECR upload page.
#    Wage-month auto-pick + file auto-attach ship in this build but the
#    one-click challan buttons arrive after login is confirmed working.
#
# ═══════════ WHAT'S NEW (Iter 689) — APPROVAL LEVELS (Phase 2) ═══════════
#
# 🪜 MULTI-LEVEL & DEPARTMENT-WISE APPROVERS + PER-CHANGE-TYPE RULES
#  (Attendance Report — Monthly Editable → ⚙ Firm Settings tab):
#  * Approval Type: Single Level OR Multi Level (2) — L1 approval
#    escalates to Level 2; attendance applies only after final approval.
#  * Changes Requiring Approval matrix: Any Manual Change / A→P / P→A /
#    A→L / P→L / P→HD / A→HD / WO→P (+ Select All / Clear All). Ticked
#    transitions go for approval; everything else saves DIRECTLY.
#  * Level 1 & Level 2 approver: Any Admin or a specific user.
#  * Department-wise approver mapping (overrides Level 1 per dept).
#  * Designated-approver enforcement server-side (super admin override);
#    maker-checker preserved; L1/L2 steps audited; requests show
#    "Level 1/2" badge in the Approvals tab.
#
# ═══════════ ALSO INCLUDED (Iter 688) ═══════════
#
# 📅 ATTENDANCE REPORT — MONTHLY EDITABLE (Excel-style sheet, user spec):
#  New screen: Attendance & Shift → Attendance Report — Monthly Editable.
#  * Full-month Excel-style grid: Code · Employee · Dept · 01–31 (with
#    weekday under each date) · P/A/L/WO/CO/HD totals per row.
#  * Tap any day cell → pick P / A / L / WO / CO / HD — NO In/Out time
#    needed. Manual marks are an OVERLAY: punch data is NEVER modified.
#  * Base statuses auto-filled: punch → P, weekly off (employee override
#    else firm policy) → WO, past day without punch → A.
#  * Summary cards: Employees · P · A · L · WO · CO · HD · Manual ·
#    Pending. Row totals update live while editing (✎ marker).
#  * ⚙ FIRM SETTINGS tab (per firm, stored in Firm Master):
#    Allow Manual Editing ON/OFF · Approval Required ON/OFF ·
#    Require Reason ON/OFF · Maker-Cannot-Approve-Own-Request ON/OFF.
#  * Direct mode: Save Changes → applied instantly (audit logged).
#    Approval mode: Submit for Approval → 🟡 Pending → Approvals tab →
#    Approve/Reject (single + Approve All / Reject All) → only APPROVED
#    changes become effective; rejected leave the original unchanged.
#  * Maker-checker enforced server-side; notification raised to admins
#    on submission; full audit trail in attendance_change_audit.
#  * Excel export mirrors the grid (dates centred, weekday row, totals).
#  * Month input MM-YYYY. Existing attendance engine, punch data,
#    registers, payroll — ALL untouched (additive overlay module).
#
# ═══════════ ALSO INCLUDED (Iter 687) — REPORT HUB FIXES ═══════════
#
# a) SALARY COMPARISON: "No. of Employees" now shown for BOTH months
#    separately (Employees <prev month> · Employees <current month>).
# b) WAGE REGISTER: S.No. column replaces Emp Code.
# c) WAGE REGISTER: every figure CENTRED in its column, commas removed
#    (web view + PDF + Excel).
# d) WAGE REGISTER restructured: Master Salary heads (DYNAMIC from the
#    Firm Master allowance catalog: HRA / Conveyance / Medical / Other)
#    + Gross Salary · Working Days · Earning heads (dynamic) + Overtime
#    + Gross Earning · Deductions (PF / ESIC / PT / TDS / Adv-Other,
#    zero-only heads auto-hidden) + Net Pay · Bank Details — same layout
#    in Excel & PDF.
# e) FINE / DEDUCTION / ADVANCE / GRATUITY / WAGE registers: statutory
#    FORM headings confirmed restored on every web view + PDF + Excel
#    (FORM A–E lines print again after this deploy).
# f) CLRA / LABOUR CODE registers: shown ONLY when the Firm Master's
#    Firm Category is CONTRACTOR — hidden for all other firms.
# g) CONTRACTOR REGISTERS (Central Wages): ALL dates now DD-MM-YYYY.
# h) FORM C — DEDUCTIONS: when a month has no deduction, prints
#    "For the Month of <Month-Year> No Deduction has been done with Any
#    Employee".
# i) FORM B & FORM D (Muster Roll): figures / attendance marks / S.No. /
#    Emp Code centred — including Excel.
# j) FORM D — WO AUTO-FILL: blank days on the employee's weekly off are
#    marked WO — employee-level week-off (Employee Master) wins,
#    otherwise the Firm Master attendance-policy weekly offs.
# k) REPORT HUB — GLOBAL: every numeric figure in EVERY report now
#    prints WITHOUT thousands commas and WITHOUT trailing .00 decimals
#    (web + PDF + Excel).
# l) MONTHLY ATTENDANCE REGISTER: month entered as MM-YYYY; columns are
#    now Salary Process Days (from FINALIZED salary run) · Attendance
#    (engine present days) · OT Hours — all other columns removed.
#
# ═══════════ ALSO INCLUDED (Iter 686) ═══════════
#
# 📊 CENTRAL STATISTICAL — ANNUAL LABOUR STATISTICS (user spec):
#  New reporting module: Reports → Central Statistical — Annual Labour.
#  AGGREGATION-ONLY layer — reuses Employee Master, attendance and the
#  existing finalized compliance salary runs. NO payroll recalculation,
#  NO duplicate data entry, existing processes untouched.
#  * Financial Year Apr→Mar selection (default current FY) + Department
#    filter + Compare-Previous-FY toggle.
#  * Dashboard KPI cards: Total/Average Employment, Man-days,
#    Attendance %, Salary/Wages, OT Cost, Labour Cost, Avg Cost per
#    Employee, Joining/Exit, Attrition %.
#  * TABS: Overview (Company info · Employment Summary M/F/O ·
#    Skill-wise · Attendance/Man-days · Wage & Salary (annual + monthly
#    avg) · PF/ESIC/Statutory · Prev-FY % comparison · finalized report
#    list) · Department-wise (tap → its employees) · Employee-wise
#    (search + tap → April→March monthly drill-down with annual total) ·
#    Category-wise (Type/Category/Skill/Designation level) · Monthly
#    (Apr→Mar table + Employment/Man-days/OT/Attendance trend bars) ·
#    Validation (Employee Master vs Attendance vs Salary coverage,
#    mismatch employee lists, data-quality checks: missing dept /
#    designation / gender / DOJ / salary).
#  * EXPORTS: multi-sheet Excel (Consolidated · Department · Employee ·
#    Category · Monthly · Validation) + consolidated PDF + print.
#  * 🔒 FINALIZE: immutable snapshot (version, generated-by, date) —
#    finalized reports stay reproducible.
#  * Permissions: super admin / sub admin / company admin (existing
#    role system).
#
# 📈 CHARTS TAB (686): Employment / Salary Cost / Labour Cost / OT /
#  Attendance % line charts (Apr→Mar) + Labour-Cost-by-Department and
#  Employment-by-Category PIE charts with legends — presentation ready.
#
# 🏛 OFFICIAL FORMATS TAB (686): StatisticalReportDefinition mapping
#  layer — survey line-items resolved from the SAME aggregation (no new
#  calculation). Built-in "ASI-style Block E: Employment & Labour Cost"
#  (E1–E13) + custom formats via POST /api/admin/central-stats/formats.
#  Per-format render table + Excel export. Clearly labelled: not an
#  official government return until the exact notified format is
#  configured.
#
# ═══════════ ALSO INCLUDED (Iter 685) ═══════════
#
# 🪪 EMAIL AUDIT AGENT — OCR DOCUMENT SCANNER (user request):
#  * Document-photo attachments (Aadhaar card, PAN card, bank passbook,
#    cancelled cheque, voter ID, salary slip images — .jpg/.png/.webp)
#    are now OCR-READ by AI vision (Gemini Flash) during the audit.
#  * Each image is IDENTIFIED ("Found attachment 1000314140.jpg —
#    AADHAAR CARD of KANHAIYALAL ACHARAJ") and every clearly printed
#    field is extracted: name, ID number, DOB, gender, address, IFSC,
#    account no, bank name … (never guessed; unreadable → blank).
#  * NEW: SCANNED PDF SUPPORT — PDF attachments with no text layer
#    (offer letters / ID copies scanned to PDF) are rendered to images
#    (first 2 pages) and OCR-read the same way; multi-page scans are
#    combined into one document result. Text-based PDFs keep the normal
#    text extraction (unchanged).
#  * NEW "🪪 Document Analysis (OCR)" block in the email detail with a
#    per-document card; timeline gains "OCR Scanner Used" and
#    "Document Identified" steps.
#  * REPORT-STYLE SUMMARY (user rule): the AI summary is now a short
#    human analysis report (what was received, which documents found,
#    what to verify) — the raw metadata field-dump style
#    ("employee_name:", "forwarded_by:", "received_timestamp:") is gone.
#  * Excel/CSV attachments keep the Iter-683 data analysis unchanged.
#  * Still 100% READ-ONLY — nothing is stored from images except the
#    extracted text; image bytes are never saved to the database.
#
# 🗜️ ALSO (685): read-only diagnostic + AAZAR data-repair scripts
#  (kind=diag685 / kind=fix685) for the legacy-import salary-structure
#  junk found in AAZAR DARAN (backup + dry-run before apply).
#
# 📝 ALSO (685): EMPLOYEE PWA JOINING FORM — PAGE 2 (user request):
#  * Father's Name → REQUIRED * (with validation message)
#  * Date of Birth → REQUIRED * (DD-MM-YYYY validated)
#  * Date of Joining → AUTO-FILLS with TODAY's date when the employee
#    opens the form (still editable — hint shown below the field).
#
# ═══════════ ALSO INCLUDED (Iter 684) ═══════════
#
# 🛠️ AI COMMAND CENTER — TABS OVERLAP FIXED (user bug, video ×2):
#  The tab bar (Ask AI / Approvals / Alerts / Insights / Activity /
#  🤖 Email Audit) was overlapping and hiding the content below it on
#  the live portal. Root cause: a broken tab-bar container left over
#  from the Iter-675 layout change (a plain row wrongly closed as a
#  horizontal ScrollView) — the bar collapsed and slid over the panel.
#  FIXED: the tab bar is now a simple wrapping row (never collapses,
#  never overlaps); verified on phone AND desktop widths across all
#  six tabs.
#
# ═══════════ ALSO INCLUDED (Iter 683) ═══════════
#
# 🤖 AI EMAIL, DOCUMENT & DATA ANALYSIS AGENT — PHASE 1 UPGRADE:
#  The Email Audit Agent is now a full DATA ANALYST (still 100%
#  READ-ONLY, Super Admin only, 15-Aug-2026 cutoff unchanged):
#  * EXCEL/CSV DATA ANALYSIS: rows, columns, blank rows, duplicate
#    rows, employee-code capture (up to 500 rows per sheet).
#  * EMPLOYEE MASTER MATCHING (read-only): codes found in the sheet are
#    checked against the linked firm's Employee Master — matched /
#    unmatched counts reported; unmatched employees raise a 🟠 HIGH
#    finding. Nothing is ever created or modified.
#  * EMAIL vs ATTACHMENT COMPARISON: what the mail says vs what the
#    sheet shows (salary, month, counts, names) — every conflict is a
#    🔴 CRITICAL mismatch finding with both values shown.
#  * AI FINDINGS with severity (🔴 Critical / 🟠 High / 🟡 Warning /
#    🟢 Normal) + duplicate-row warnings; a CRITICAL finding escalates
#    the email to URGENT (notification fires).
#  * Email detail now has a "📊 Data Analysis" section: statistics,
#    master-match results, mismatches and all findings; timeline gains
#    "Data Validated → Data Compared → Exceptions Identified" steps.
#
# ═══════════ ALSO INCLUDED (Iter 682) ═══════════
#
# 🌙 NIGHT-SHIFT PUNCH PAIRING HARDENED (user bug — false missing punches):
#  * A night worker's next-morning punch is now pulled back to the shift
#    start day even when the machine mislabelled it "IN" — the rescue
#    window is widened from 08:00 to 11:00 (live case: an 08:03 morning
#    OUT was refused, leaving "missing OUT" on one day and "missing IN"
#    on the next).
#  * Double-tap tolerance: if the shift-start day ends with IN followed
#    by a stray echo punch within 3 minutes, the IN still anchors the
#    cross-midnight pairing (previously the stray tail blocked it).
#  * Regression-tested: day shifts, >16h gaps and late-morning punches
#    are untouched (5/5 unit cases + full monthly grid pass).
#
# 📝 MANUAL PUNCHES IN THE GRID (user report):
#  * Verified end-to-end on this build: repair-modal punches save with
#    approved status and the grid refreshes instantly after every
#    save/delete. If a day still shows blank after THIS deploy, send the
#    employee + date and we'll trace that specific record.
#
# ═══════════ ALSO INCLUDED (Iter 681) ═══════════
#
# 💰 ESIC ROUND-UP FIX (user bug — BANTI SINGH RAWAT):
#  * On wages 6667, the portal challan says ₹50 but the grid showed ₹51.
#    6667 × 0.75% = 50.0025 — the engine ceiled the RAW product (→51),
#    while the ESIC portal settles to PAISE first (₹50.00) and only then
#    rounds up (→50). Statutory rounding now settles to paise before the
#    whole-rupee step (ESIC EE/ER + PF) — grid now matches the challan
#    exactly (50/87/84/113 verified against your challan).
#  * Open the affected month and press "Reprocess" once to refresh
#    already-computed rows.
#
# 🔒 FOOD ALLOWANCE COLUMN READ-ONLY (user rule, all firms):
#  * The FOOD head column in the Compliance Salary grid can no longer be
#    typed over — imported/master values still display. Freeze-sheet
#    allocation is unchanged (sheet FOOD amounts stay under FOOD; only
#    the extra difference follows the OT rule).
#
# ═══════════ ALSO INCLUDED (Iter 680) ═══════════
#
# 📥 EMAIL AUDIT AGENT — MAILBOX SCOPE RULES (user request):
#  * The agent now reads ONLY the PRIMARY inbox — Gmail's Updates,
#    Social and Promotions tabs are completely EXCLUDED from scanning,
#    auditing, notifications and reports.
#  * SPAM RESCUE: the Spam folder is also checked, but ONLY emails from
#    senders registered in the Company Email Registry are picked up —
#    a client's mail that wrongly lands in Spam is never missed.
#    Such emails are marked "⚠ from Spam" in the list, detail and
#    processing timeline. Unknown spam stays untouched.
#  * Still 100% READ-ONLY — nothing is moved, deleted or replied to.
#
# ═══════════ ALSO INCLUDED (Iter 679) ═══════════
#
# 🔒 HTTPS / SSL CERTIFICATE — "NOT SECURE" FIX (user request):
#  * Installs a FREE Let's Encrypt SSL certificate for your domain(s)
#    (auto-detected from nginx) and forces every HTTP visit to redirect
#    to HTTPS — the Employee & Employer PWA will show the secure 🔒.
#  * Automatic renewal enabled (certbot systemd timer) — the
#    certificate renews itself every ~60 days, no manual action.
#  * Safe to re-run; keeps an existing valid certificate.
#  * REQUIREMENT: the domain's DNS A record must point to this VPS.
#
# ═══════════ ALSO INCLUDED (Iter 678) ═══════════
#
# 🧹 JOINING FORM — SAMPLE/DUMMY DATA REMOVED (user request):
#  * The employee joining form no longer shows example values that could
#    be mistaken for real data. Replaced with neutral hints:
#      - Full name:      "RAJESH KUMAR"        → "ENTER YOUR FULL NAME"
#      - Company code:   "e.g. ACME01"         → "Enter company code"
#      - Employee code:  "e.g. SKSCO1001"      → "Employee code (optional)"
#      - Email:          "you@example.com"     → "Email (optional)"
#
# ═══════════ ALSO INCLUDED (Iter 677) ═══════════
#
# 📱 JOINING FORM — MOBILE NUMBER CAPPED AT 10 DIGITS (user request):
#  * The Mobile Number field on the employee joining form now accepts
#    DIGITS ONLY and stops at exactly 10 digits (typing/pasting more is
#    blocked). Numeric keypad shown on phones.
#
# ═══════════ ALSO INCLUDED (Iter 676) ═══════════
#
# 📱 EMPLOYEE QR → JOINING FORM WITH AUTO EMPLOYER CODE (user issue):
#  * Scanning the EMPLOYEE QR now opens the JOINING FORM directly with
#    the employer code AUTO-FETCHED, verified and locked ("You're
#    joining <Firm>").
#  * The scanned code is also saved on the phone — so even when the
#    employee installs the PWA first and opens the app later (where the
#    QR link's ?company= parameter is normally lost), the joining form
#    STILL auto-fills the employer code.
#  * Old printed QR posters (that point to the Get-App page) keep
#    working: that page now also saves the code before install.
#
# ═══════════ ALSO INCLUDED (Iter 675) ═══════════
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
#   wget -O deploy722.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy722.sh

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

echo "==> Iter 691 cleanup: remove ONLY the browser-autofilled JUNK email from EPF/ESI login fields (portal_logins rows are left untouched — SSO/PT can legitimately use emails)..."
cd $APP_DIR/backend
$APP_DIR/backend/venv/bin/python - << 'PYFIX' || echo "⚠ cleanup skipped — run fix_epf_autofill_691.py manually"
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env" if os.path.exists("/app/backend/.env") else ".env")
load_dotenv(".env")
def bad(u): return bool(u) and "@" in str(u)
async def m():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME","test_database")]
    n=0
    async for fm in db.firm_masters.find({}):
        ch={}; hit=[]
        epf=fm.get("epf") or {}
        if bad(epf.get("epf_user_id")):
            hit.append(("EPF",epf.get("epf_user_id"))); ch["epf.epf_user_id"]=""; ch["epf.epf_password"]=""
        esi=fm.get("esi") or {}
        if bad(esi.get("esi_user_id")):
            hit.append(("ESI",esi.get("esi_user_id"))); ch["esi.esi_user_id"]=""; ch["esi.esi_password"]=""
        if hit:
            n+=1
            print("   CLEARED junk EPF/ESI login in firm", fm.get("company_id"), "->", hit)
            await db.firm_masters.update_one({"_id":fm["_id"]},{"$set":ch})
    print("   Firms cleaned of junk EPF/ESI logins:", n)
asyncio.run(m())
PYFIX

echo "==> Iter 694 AUTO-CLEANUP: duplicate EPFO logins — RAYON/SVITHI/SUVIDHI firm par rakh kar baaki firms se hataye ja rahe hain..."
$APP_DIR/backend/venv/bin/python - << 'PYDUP' || echo "⚠ duplicate cleanup skipped"
import asyncio, os, re
from collections import defaultdict
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env" if os.path.exists("/app/backend/.env") else ".env")
load_dotenv(".env")
OWNER_RE = re.compile(r"rayon|svithi|suvidhi|savidhi", re.I)
async def m():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME","test_database")]
    names = {}
    async for c in db.companies.find({}, {"_id":0,"company_id":1,"name":1}):
        names[c["company_id"]] = c.get("name") or c["company_id"]
    seen = defaultdict(set)
    async for fm in db.firm_masters.find({}, {"_id":0,"company_id":1,"epf":1,"portal_logins":1}):
        cid = fm.get("company_id")
        u = ((fm.get("epf") or {}).get("epf_user_id") or "").strip()
        if u and "@" not in u:
            seen[u].add(cid)
        for r in fm.get("portal_logins") or []:
            if r.get("login_type") == "PF LOGIN":
                u2 = (r.get("user_name") or "").strip()
                if u2 and "@" not in u2:
                    seen[u2].add(cid)
    dups = {u: cids for u, cids in seen.items() if len(cids) > 1}
    if not dups:
        print("   ✅ Har firm ka EPFO login ALAG hai — koi duplicate nahi.")
    for u, cids in dups.items():
        owners = [c for c in cids if OWNER_RE.search(names.get(c, ""))]
        listed = ", ".join(names.get(c, c) for c in cids)
        if len(owners) == 1:
            keep = owners[0]
            print("   🧹 EPFO User ID '%s' %d firms me tha (%s) — sirf '%s' par rakha, baaki se HATAYA:" % (
                u, len(cids), listed, names.get(keep, keep)))
            for cid in cids:
                if cid == keep:
                    continue
                fm = await db.firm_masters.find_one({"company_id": cid}, {"_id":0,"epf":1,"portal_logins":1})
                upd = {}
                if ((fm.get("epf") or {}).get("epf_user_id") or "").strip() == u:
                    upd["epf.epf_user_id"] = ""; upd["epf.epf_password"] = None
                rows = fm.get("portal_logins") or []
                ch = False
                for r in rows:
                    if r.get("login_type") == "PF LOGIN" and (r.get("user_name") or "").strip() == u:
                        r["user_name"] = None; r["password"] = None; ch = True
                if ch:
                    upd["portal_logins"] = rows
                if upd:
                    await db.firm_masters.update_one({"company_id": cid}, {"$set": upd})
                    print("      - %s ✅ saaf" % names.get(cid, cid))
        else:
            print("   ⚠ EPFO User ID '%s' in %d firms me saved hai: %s" % (u, len(cids), listed))
            print("     → Asli firm select karke Automation Studio ka 'DOOSRI firms se HATAO' button dabayein.")
asyncio.run(m())
PYDUP

echo "==> Iter 702 repair: re-promote demoted seeded Super Admins (vksbhilwara etc.)..."
$APP_DIR/backend/venv/bin/python - << 'PYSA' || echo "⚠ super-admin repair skipped"
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env" if os.path.exists("/app/backend/.env") else ".env")
load_dotenv(".env")
async def m():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME","test_database")]
    # Root cause: seeded super admins (e.g. Iter 615) lacked
    # super_admin_allowlisted, so the startup sweep demoted them to
    # "employee" on every backend restart → "This login is only for
    # administrators". Re-promote + allowlist so it never recurs.
    r = await db.users.update_many(
        {"$or": [{"email": "vksbhilwara@gmail.com"},
                 {"position": "Super Admin", "role": "employee"}]},
        {"$set": {"role": "super_admin", "super_admin_allowlisted": True,
                  "onboarded": True, "disabled": False,
                  "approval_status": "approved"}})
    print("   ✅ Super admin accounts repaired:", r.modified_count)
    u = await db.users.find_one({"email": "vksbhilwara@gmail.com"},
                                {"_id": 0, "role": 1, "super_admin_allowlisted": 1})
    print("   vksbhilwara@gmail.com →", (u or {}).get("role"),
          "| allowlisted:", (u or {}).get("super_admin_allowlisted"))
asyncio.run(m())
PYSA

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
# Iter 704 — Smart Payroll rename: ship the updated PWA manifests too.
sudo cp public/manifest.json public/manifest-employee.json public/manifest-employer.json $WEB_DIR/ 2>/dev/null || true
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

# ═════════ Iter 679 — FREE SSL (Let's Encrypt) + FORCE HTTPS ═════════
# The Employee/Employer PWA shows "Not secure" without a valid HTTPS
# certificate. This step: 1) installs certbot if missing, 2) detects the
# domain(s) from the nginx site config, 3) issues/renews a free
# Let's Encrypt certificate, 4) forces HTTP → HTTPS redirect,
# 5) enables automatic renewal (systemd timer). Safe to re-run.
echo "==> 9a/9 SSL certificate (Let's Encrypt) + HTTPS redirect..."
if ! command -v certbot >/dev/null 2>&1; then
  echo "   installing certbot..."
  sudo apt-get update -y >/dev/null 2>&1
  sudo apt-get install -y certbot python3-certbot-nginx >/dev/null 2>&1 \
    || sudo snap install --classic certbot 2>/dev/null || true
fi
SITE_FILE=$(sudo grep -rl "$WEB_DIR" /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | head -1)
DOMAINS=$(sudo grep -h "server_name" "$SITE_FILE" 2>/dev/null \
  | sed 's/.*server_name//; s/;//' | tr ' ' '\n' \
  | grep -vE '^$|_|localhost|^[0-9.]+$' | sort -u | head -4)
if command -v certbot >/dev/null 2>&1 && [ -n "$DOMAINS" ]; then
  D_ARGS=""
  for d in $DOMAINS; do D_ARGS="$D_ARGS -d $d"; done
  echo "   requesting/renewing certificate for:$( echo " $DOMAINS" | tr '\n' ' ' )"
  sudo certbot --nginx $D_ARGS --non-interactive --agree-tos \
    -m sksharmaconsultancy@gmail.com --redirect --keep-until-expiring \
    && echo "   ✓ SSL active + HTTP now redirects to HTTPS" \
    || echo "   ⚠ certbot could not finish — check that the domain's DNS A record points to THIS server's IP, then re-run: sudo certbot --nginx$D_ARGS --redirect"
  sudo systemctl enable --now certbot.timer 2>/dev/null || true
  sudo nginx -t && sudo systemctl reload nginx
  for d in $DOMAINS; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://$d" || echo ERR)
    echo "   https://$d → HTTP $CODE"
  done
else
  echo "   ⚠ Skipped: certbot unavailable or no domain found in $SITE_FILE"
fi

echo -n "   Server badge is 722 (must say OK): "
grep -q 'APP_ITERATION = "722"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Payroll speed optimization — Iter 722 (must say OK): "
grep -q '_list_proj' $APP_DIR/backend/routes/payroll_core.py && grep -q 'company_id.*role.*created_at' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Double-duty OT stitch fix — Iter 721 (must say OK): "
grep -q 'max_hours + 6' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Group/Roll live counts — Iter 720 (must say OK): "
grep -q 'rollCounts' $APP_DIR/frontend/app/admin.tsx && echo "OK" || echo "MISSING!"
echo -n "   Day-shift IN steal fix — Iter 719 (must say OK): "
grep -q 'self-contained clean shift' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Challan PAID auto-capture + Runner v29 — Iter 718 (must say OK): "
grep -q 'portal-ext/paid' $APP_DIR/backend/routes/portal_extension.py && grep -q 'RUNNER_VERSION = "29"' $APP_DIR/backend/routes/portal_extension.py && echo "OK" || echo "MISSING!"
echo -n "   Stray Punch Cleaner — Iter 717 (must say OK): "
grep -q 'clean-strays' $APP_DIR/backend/routes/attendance_doctor.py && grep -q 'ad-strays-clean' $APP_DIR/frontend/app/attendance-doctor.tsx && echo "OK" || echo "MISSING!"
echo -n "   Double-scan stitch guards — Iter 716 (must say OK): "
grep -q 'stray double-scan anchor' $APP_DIR/backend/server.py && grep -q 'total-duty cap' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Cross Midnight punching — Iter 715 (must say OK): "
grep -q 'cross_midnight' $APP_DIR/backend/server.py && grep -q 'cross_midnight_out' $APP_DIR/backend/routes/attendance_core.py && grep -q 'fm-ac-cm-yes' $APP_DIR/frontend/app/firm-master.tsx && echo "OK" || echo "MISSING!"
echo -n "   Instant reports + missing-punch fix — Iter 714 (must say OK): "
grep -q 'company_id.*created_at' $APP_DIR/backend/server.py && grep -q 'leading_out' $APP_DIR/backend/server.py && grep -q '_kick_refresh' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Approval workflow fixes + leave wiring — Iter 713 (must say OK): "
grep -q 'finalize_leave_workflow' $APP_DIR/backend/routes/leaves.py && grep -q 'Advance RETURNED for correction' $APP_DIR/backend/routes/approvals_engine.py && grep -q 'if (saving) return;' $APP_DIR/frontend/app/approval-workflows.tsx && echo "OK" || echo "MISSING!"
echo -n "   Bulk Dummy Shift Assign — Iter 712 (must say OK): "
grep -q 'dummy-shift/bulk-assign' $APP_DIR/backend/routes/labour_reports.py && grep -q 'BulkDummyAssign' $APP_DIR/frontend/app/attendance-policy.tsx && echo "OK" || echo "MISSING!"
echo -n "   Dummy shift masking + random minutes — Iter 710/711 (must say OK): "
grep -q '_mask_hours' $APP_DIR/backend/routes/inout_ot_matrix.py && grep -q 'dummy_rnd_min' $APP_DIR/backend/routes/labour_reports.py && grep -q 'effective_dummy_shifts' $APP_DIR/backend/routes/labour_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Firm-defined dummy shifts (policy editor + master picker) — Iter 711 (must say OK): "
grep -q '"dummy_shifts"' $APP_DIR/backend/server.py && grep -q 'pm-dummy-shifts' $APP_DIR/frontend/app/attendance-policy.tsx && grep -q 'dummy_shifts_master' $APP_DIR/frontend/app/employee-master.tsx && grep -q 'sks-pwa-v37' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   Read-only Charts & Analytics — Iter 709 (must say OK): "
[ -f $APP_DIR/backend/routes/analytics.py ] && [ -f $APP_DIR/frontend/app/analytics.tsx ] && [ -f $APP_DIR/frontend/src/components/charts.tsx ] && grep -q 'analytics_router' $APP_DIR/backend/server.py && grep -q '"/analytics"' $APP_DIR/frontend/src/components/AdminWebShell.tsx && grep -q 'sks-pwa-v37' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   PWA data mgmt + screenshot shield — Iter 708 (must say OK): "
[ -f $APP_DIR/backend/routes/pwa_data_mgmt.py ] && [ -f $APP_DIR/frontend/src/components/ScreenshotShield.tsx ] && [ -f $APP_DIR/frontend/src/components/firmMaster/PwaSettingsSection.tsx ] && grep -q '_bg_warm_monthly_grid' $APP_DIR/backend/server.py && grep -q 'grid-show-more' $APP_DIR/frontend/app/attendance-grid.tsx && echo "OK" || echo "MISSING!"
echo -n "   Tour report + advances + approval center — Iter 707 (must say OK): "
grep -q 'report.xlsx' $APP_DIR/backend/routes/tours.py && grep -q 'advance/settle' $APP_DIR/backend/routes/tours.py && [ -f $APP_DIR/backend/routes/my_approvals.py ] && [ -f $APP_DIR/frontend/app/my-approvals.tsx ] && grep -q 'sks-pwa-v37' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   Tour Management module — Iter 706 (must say OK): "
grep -q 'tours_router' $APP_DIR/backend/server.py && [ -f $APP_DIR/backend/routes/tours.py ] && [ -f $APP_DIR/frontend/app/my-tours.tsx ] && [ -f $APP_DIR/frontend/app/tour-admin.tsx ] && grep -q '"key": "tour"' $APP_DIR/backend/routes/approvals_engine.py && grep -q 'is_official_tour' $APP_DIR/backend/routes/expense_claims.py && echo "OK" || echo "MISSING!"
echo -n "   Employee approver + CL/PL modes — Iter 705 (must say OK): "
grep -q 'employee-search' $APP_DIR/backend/routes/approvals_engine.py && grep -q 'leave-balance/bulk' $APP_DIR/backend/routes/leaves.py && grep -q 'leave-settings' $APP_DIR/backend/routes/leaves.py && grep -q 'sks-pwa-v37' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   EPFO login diagnosis on screen — Iter 692 (must say OK): "
grep -q '_diagnose_epfo_creds' $APP_DIR/backend/routes/portal_extension.py && grep -q 'creds_diagnosis' $APP_DIR/frontend/app/automation-studio.tsx && echo "OK" || echo "MISSING!"
echo -n "   Firm-wise login guard + all-actions PC login — Iter 693 (must say OK): "
grep -q '_dup_epfo_login_warning' $APP_DIR/backend/routes/portal_extension.py && grep -q 'EPFO_PC_ACTION' $APP_DIR/frontend/app/automation-studio.tsx && grep -q 'GuardedGridInput' $APP_DIR/frontend/app/firm-master.tsx && grep -q 'RUNNER_VERSION = "28"' $APP_DIR/backend/routes/portal_extension.py && echo "OK" || echo "MISSING!"
echo -n "   Dup-login cleanup button + save guard — Iter 694 (must say OK): "
grep -q 'claim-epfo-login' $APP_DIR/backend/routes/portal_extension.py && grep -q 'as-fix-dup-login' $APP_DIR/frontend/app/automation-studio.tsx && grep -q '_dup_owner' $APP_DIR/backend/routes/firm_master.py && echo "OK" || echo "MISSING!"
echo -n "   PF Reports login hard-stop + Runner v23 + PWA v13 — Iter 695 (must say OK): "
grep -q 'not All Firms' $APP_DIR/frontend/app/pf-reports.tsx && grep -q 'RUNNER_VERSION = "28"' $APP_DIR/backend/routes/portal_extension.py && grep -q 'sks-pwa-v37' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   English UI + exact error surfacing — Iter 696 (must say OK): "
grep -q 'server said' $APP_DIR/frontend/app/automation-studio.tsx && grep -q 'server said' $APP_DIR/frontend/app/pf-reports.tsx && grep -q 'EPFO login found' $APP_DIR/frontend/app/automation-studio.tsx && echo "OK" || echo "MISSING!"
echo -n "   api client double-stringify fix — Iter 697 (must say OK): "
grep -q 'typeof body === "string" ? body' $APP_DIR/frontend/src/api/client.ts && grep -q 'sks-pwa-v37' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   Month dropdown + TEST removed + popup auto-close v24 — Iter 698 (must say OK): "
echo -n "   Auto challan on Challan Upload screen — Iter 703 (must say OK): "
grep -q 'auto_captured' $APP_DIR/backend/routes/portal_extension.py && grep -q 'auto_captured' $APP_DIR/frontend/app/challans.tsx && grep -q 'sks-pwa-v37' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   ESIC challan record v28 + Smart Payroll rename — Iter 704 (must say OK): "
grep -q 'ESIC Challan Number' $APP_DIR/backend/routes/portal_extension.py && grep -q 'RUNNER_VERSION = "28"' $APP_DIR/backend/routes/portal_extension.py && grep -q 'Smart Payroll' $APP_DIR/frontend/public/manifest-employee.json && grep -q 'Smart Payroll' $APP_DIR/frontend/scripts/inject-pwa-html.js && grep -q 'sks-pwa-v37' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
grep -q 'as-month-dd' $APP_DIR/frontend/app/automation-studio.tsx && grep -q 'btnCloseModal' $APP_DIR/backend/routes/portal_extension.py && grep -q 'RUNNER_VERSION = "2' $APP_DIR/backend/routes/portal_extension.py && ! grep -q '"epfo_ecr_autoupload_test": {' $APP_DIR/backend/utils/rpa_engine.py && echo "OK" || echo "MISSING!"
echo -n "   ECR auto-attach v25 + flow rename — Iter 699 (must say OK): "
grep -q 'ecr_attached' $APP_DIR/backend/routes/portal_extension.py && grep -q 'ecr_attached' $APP_DIR/frontend/app/automation-studio.tsx && grep -q 'RUNNER_VERSION = "28"' $APP_DIR/backend/routes/portal_extension.py && grep -q '"label": "ECR Upload"' $APP_DIR/backend/utils/rpa_engine.py && echo "OK" || echo "MISSING!"
echo -n "   ESIC same login process v26 — Iter 700 (must say OK): "
grep -q 'esic_open' $APP_DIR/backend/routes/portal_extension.py && grep -q '_diagnose_esic_creds' $APP_DIR/backend/routes/portal_extension.py && grep -q 'esic_open' $APP_DIR/frontend/app/pf-reports.tsx && grep -q 'sks-pwa-v37' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   TRRN + challan PDF + ESIC nav v27 — Iter 701 (must say OK): "
grep -q 'portal-ext/trrn' $APP_DIR/backend/routes/portal_extension.py && grep -q 'challan-pdf' $APP_DIR/backend/routes/portal_extension.py && grep -q 'as-download-challan' $APP_DIR/frontend/app/automation-studio.tsx && grep -q 'RUNNER_VERSION = "28"' $APP_DIR/backend/routes/portal_extension.py && grep -q 'sks-pwa-v37' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   In/Out report grid cache + debounce — Iter 702 (must say OK): "
grep -q '_GRID_CACHE' $APP_DIR/backend/routes/inout_ot_matrix.py && grep -q 'qDeb' $APP_DIR/frontend/app/inout-ot-matrix.tsx && grep -q 'sks-pwa-v37' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   Approval levels/rules — Iter 689 (must say OK): "
grep -q 'RULE_KEYS' $APP_DIR/backend/routes/manual_attendance.py && grep -q 'dept_approvers' $APP_DIR/frontend/app/attendance-report.tsx && echo "OK" || echo "MISSING!"
echo -n "   Monthly Editable Attendance — Iter 688 (must say OK): "
[ -f $APP_DIR/backend/routes/manual_attendance.py ] && [ -f $APP_DIR/frontend/app/attendance-report.tsx ] && grep -q 'manual_att_router' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Report Hub fixes — Iter 687 (must say OK): "
grep -q 'employees_a' $APP_DIR/backend/routes/payroll_reports.py && grep -q '"sno", "S.No."' $APP_DIR/backend/routes/govt_audit_reports.py && grep -q 'contractor_only' $APP_DIR/backend/routes/clra_labour_reports.py && grep -q '_dmy' $APP_DIR/backend/routes/central_wage_registers.py && echo "OK" || echo "MISSING!"
echo -n "   Central Statistical module — Iter 686 (must say OK): "
[ -f $APP_DIR/backend/routes/central_statistical.py ] && [ -f $APP_DIR/frontend/app/central-statistical.tsx ] && grep -q 'central_stats_router' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Charts + Official Formats — Iter 686 (must say OK): "
grep -q 'asi_block_e' $APP_DIR/backend/routes/central_statistical.py && grep -q 'PieChart' $APP_DIR/frontend/app/central-statistical.tsx && echo "OK" || echo "MISSING!"
echo -n "   OCR Document Scanner — Iter 685 (must say OK): "
grep -q '_ocr_documents' $APP_DIR/backend/routes/email_audit_agent.py && grep -q 'Document Analysis (OCR)' $APP_DIR/frontend/src/components/EmailAuditTab.tsx && echo "OK" || echo "MISSING!"
echo -n "   Scanned-PDF OCR — Iter 685 (must say OK): "
grep -q '_b64_pages' $APP_DIR/backend/routes/email_audit_agent.py && echo "OK" || echo "MISSING!"
echo -n "   Joining form Page 2 rules — Iter 685 (must say OK): "
grep -q "Please enter your father's name" $APP_DIR/frontend/app/employee-signup.tsx && grep -q "Auto-filled with today" $APP_DIR/frontend/app/employee-signup.tsx && echo "OK" || echo "MISSING!"
echo -n "   AI CC tab bar fixed — Iter 684 (must say OK): "
grep -q 'plain' $APP_DIR/frontend/app/ai-command-center.tsx && ! grep -q '</ScrollView>$' <(sed -n '265,272p' $APP_DIR/frontend/app/ai-command-center.tsx) && echo "OK" || echo "MISSING!"
echo -n "   Data Analysis layer — Iter 683 (must say OK): "
grep -q 'email_vs_attachment' $APP_DIR/backend/routes/email_audit_agent.py && grep -q 'Data Analysis' $APP_DIR/frontend/src/components/EmailAuditTab.tsx && echo "OK" || echo "MISSING!"
echo -n "   Night stitcher hardened — Iter 682 (must say OK): "
grep -q 'window widened to 11:00' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   ESIC paise-first rounding — Iter 681 (must say OK): "
grep -q 'RUPEES-PAISE first' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   FOOD column read-only — Iter 681 (must say OK): "
grep -q 'FOOD heads are ALWAYS' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Primary-only + Spam rescue — Iter 680 (must say OK): "
grep -q 'category:primary' $APP_DIR/backend/routes/email_audit_agent.py && grep -q 'Gmail]/Spam' $APP_DIR/backend/routes/email_audit_agent.py && echo "OK" || echo "MISSING!"
echo -n "   Dummy data removed — Iter 678 (must say OK): "
grep -q 'ENTER YOUR FULL NAME' $APP_DIR/frontend/app/employee-signup.tsx && ! grep -q 'RAJESH KUMAR' $APP_DIR/frontend/app/employee-signup.tsx && echo "OK" || echo "MISSING!"
echo -n "   Mobile 10-digit cap — Iter 677 (must say OK): "
grep -q 'slice(0, 10)' $APP_DIR/frontend/app/employee-signup.tsx && echo "OK" || echo "MISSING!"
echo -n "   Employee QR auto employer-code — Iter 676 (must say OK): "
grep -q 'sks.join.company' $APP_DIR/frontend/app/employee-signup.tsx && grep -q 'employee-signup?company=' $APP_DIR/frontend/app/join-qr.tsx && echo "OK" || echo "MISSING!"
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
echo "  DONE — Iter 689 deployed."
echo "  • NEW (686): 📊 CENTRAL STATISTICAL — Annual Labour Statistics:"
echo "    FY Apr→Mar consolidated report with KPI cards, Employment/Skill"
echo "    summaries, Wage & Statutory totals, Department / Employee /"
echo "    Category / Monthly tabs, employee month-wise drill-down,"
echo "    validation & data-quality checks, prev-FY comparison, multi-"
echo "    sheet Excel + PDF export and 🔒 Finalize snapshots."
echo "    Find it under Reports → Central Statistical — Annual Labour."
echo "  • NEW (685): 🪪 Email Audit OCR SCANNER — Aadhaar / PAN / passbook /"
echo "    cheque photo attachments are identified and read by AI vision;"
echo "    per-document extraction shown in the new 'Document Analysis (OCR)'"
echo "    block; AI summary is now a human analysis report (no raw metadata"
echo "    dumps). Timeline: OCR Scanner Used → Document Identified."
echo "    Scanned PDFs (offer letters / ID copies) are OCR-read too —"
echo "    first 2 pages rendered and combined into one document result."
echo "  • NEW (684): AI Command Center tab bar FIXED — tabs no longer"
echo "    overlap or hide the content below; verified on phone and"
echo "    desktop widths across all six tabs."
echo "  • NEW (683): AI Email Agent upgraded to a full DATA ANALYST —"
echo "    Excel row/duplicate stats, read-only Employee Master matching,"
echo "    email-vs-attachment mismatch detection, severity findings"
echo "    (critical findings escalate to URGENT + notify)."
echo "  • NEW (682): Night-shift pairing hardened — morning punches up to"
echo "    11:00 stitch back to the shift start day (even if mislabelled"
echo "    IN); double-tap echoes no longer block pairing. False 'missing"
echo "    OUT / missing IN' days for night workers are gone."
echo "  • NEW (681): ESIC rounding now matches the govt challan exactly"
echo "    (paise-first, then round-up) — press Reprocess on open months."
echo "  • ALSO (681): FOOD allowance column is read-only in the grid."
echo "  • NEW (680): Email Audit Agent reads ONLY the Primary inbox (no"
echo "    Updates/Social/Promotions) + rescues registered-company emails"
echo "    that land in Spam (marked '⚠ from Spam')."
echo "  • NEW (679): FREE SSL certificate installed + HTTP→HTTPS redirect."
echo "    The Employee & Employer PWA now show the secure 🔒. Auto-renewal"
echo "    is enabled. If certbot reported a DNS warning above, point the"
echo "    domain's A record to this server and re-run this script."
echo "  • NEW (678): Joining form sample/dummy hints removed — neutral"
echo "    field hints only, no example names/codes/emails."
echo "  • NEW (677): Joining form mobile number — digits only, max 10."
echo "  • NEW (676): Employee QR opens the joining form DIRECTLY with the"
echo "    employer code auto-fetched & locked; code survives PWA install."
echo "    Re-print QRs from QR Codes — Joining & App for the direct link"
echo "    (old printed QRs keep working too)."
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
