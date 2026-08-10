## 🧹 MANDATORY POST-TEST CLEANUP (all testing_agent runs)

Any temporary firms, users, attendance rows, salary runs, tickets, etc.
that the testing_agent creates during an iteration **MUST be removed
before the run ends**. Two acceptable strategies:

1. **Preferred — tag & auto-clean.** Prefix any temp doc name/code with
   `Iter{n}-`, `TEST_`, `QA_`, `PYTEST_`, `E2E_`, `__tmp__` **or** set
   `_test_temp: true` on the document, then at the end of the run
   execute:
   ```bash
   python3 /app/scripts/cleanup_test_data.py --apply
   ```
   The script recursively walks every collection and removes anything
   linked by `company_id` / `user_id` / `employee_id` to those tagged
   docs. It is idempotent and safe to run repeatedly.

2. **Explicit deletion.** Track the ids created during the test and call
   the existing delete endpoints (`DELETE /api/companies/{id}`,
   `DELETE /api/admin/employees/{uid}`, ...) inside a `finally` block.

Rules:
- NEVER touch the 6 protected production firms (S.K. Sharma & Co.,
  Sharma Associates, Sharma Services, Sharma Consultancy, Sharma Allied
  Services, Demo Textile Mills Pvt Ltd) or the super_admin
  `sksharmaconsultancy@gmail.com`.
- Test firm names MUST start with `Iter{iteration}-` or `TEST_` so the
  cleanup script can identify them.
- Cleanup script location: `/app/scripts/cleanup_test_data.py`
  (dry-run by default; add `--apply` to actually delete).


# Test Result — Iteration 61

## What's new (this iteration)

### 1) Multi-Company Compliance Salary Batch
- New endpoints (paths renamed away from `/compliance-salary-runs/*` to
  avoid conflict with the `/compliance-salary-runs/{run_id}` wildcard):
  - `POST /api/admin/compliance-batches` — payload
    `{company_ids: [...], month, employee_type?, is_onroll?}`
  - `GET  /api/admin/compliance-batches` — list recent
  - `GET  /api/admin/compliance-batches/{batch_id}` — status
- Background execution via FastAPI `BackgroundTasks`; per-firm status
  (queued / running / done / failed) persisted on
  `compliance_salary_batches.jobs[]`. Each `done` job stores the
  generated `run_id` so the operator can jump to the details.
- Frontend: **Multi-firm mode toggle** at the top of `/compliance-salary-run`
  — when ON, shows a firm multi-select (chips), Select-all/Clear helpers,
  a big "Run batch" button, and a **live-polling** batch status panel
  (3-second interval).

### 2) Employee UAN / ESI IP / PF-No Login
- Backend `POST /api/auth/pin-login` now accepts `uan_no`, `esi_ip_no`,
  or `pf_no` alongside the existing `phone` / (`company_code + employee_code`)
  fields. Only ONE identifier is required plus the 6-digit PIN.
- Reasonable per-identifier validation (UAN must be 10–12 digits, phone
  must be ≥ 8 digits).
- Frontend `/pin-login` (employee sign-in) now has a **4-way tab picker**
  (Mobile / UAN / ESI IP / PF No.) — switching resets the identifier
  field and error state.

### 3) Payslip Auto-Email on Salary Run
- Per-firm toggle stored at `companies.payslip_email_enabled` (default
  false). Only Super Admin can flip it (web-only).
  - `GET  /api/admin/companies/{cid}/payslip-email-config`
  - `PUT  /api/admin/companies/{cid}/payslip-email-config`
- On `POST /api/admin/salary-runs/{run_id}/generate-payslips` the server
  fires an in-process best-effort email hook (`app.state.email_payslips_for_run`).
  It builds a small HTML payslip (Basic / HRA / Bonus / OT / Gross /
  PF / ESIC / TDS / Net) and sends it to `user.email` via Resend.
  Every attempt is logged to `payslip_email_log`.
- Manual trigger + dry-run: `POST /api/admin/salary-runs/{run_id}/email-payslips`
  (payload `{dry_run:false}`).
- Delivery log: `GET /api/admin/payslip-email/log?company_id=&salary_run_id=`
- Frontend: new **Payslip auto-email** section on the Company Details
  page (Super Admin only, web only) with an ON/OFF toggle.
- Best-effort: failures do NOT block the payslip generation response —
  the API instead returns a summary block (`email_summary`) inside the
  original response so the operator can spot problems.

## Priorities for testing

### Backend (P0)
1. **Compliance batch happy path**: POST `/admin/compliance-batches`
   with `{company_ids:[c1,c2], month:"2026-05"}`. Poll
   `/admin/compliance-batches/{batch_id}` for up to 30 s. Expect
   `status` to reach `completed` (or `completed_with_errors` if a firm
   fails for legitimate reasons). Each `jobs[i].status` should end up in
   `done` or `failed` — never left in `queued`.
2. **Compliance batch validation**: (a) empty `company_ids` → 400.
   (b) One `company_id` that doesn't exist → 404.
3. **Compliance batch RBAC**: `company_admin` calling POST →
   403 (only super_admin/sub_admin allowed).
4. **UAN login**: `POST /auth/pin-login` with `{"uan_no":"999999999999","pin":"000000"}`
   returns 401 (user not found), NOT 400. `{"uan_no":"1234","pin":"000000"}`
   should return 400 (invalid UAN — must be 10–12 digits).
5. **UAN login happy path**: Seed a test employee with `uan_no` set and
   a known PIN. POST with that UAN → 200 with `session_token`.
6. **Similar for ESI IP and PF**: seed users, ensure login succeeds.
7. **Payslip email config**: GET returns `enabled:false` by default,
   PUT with `{enabled:true}` flips it, subsequent GET reflects `true`.
   PUT as `company_admin` must be 403.
8. **Payslip email dry-run**: POST `/admin/salary-runs/{run_id}/email-payslips`
   with `{dry_run:true}` returns `delivered` count > 0 for a run whose firm
   is `enabled=true` and whose employees have emails; nothing is written to
   `payslip_email_log`.
9. **Payslip email disabled short-circuit**: when firm has `enabled=false`,
   POST returns `{delivered:0, note:"payslip_email_enabled=false..."}`.

### Frontend (P1)
- `/pin-login` — 4 tabs render; switching tabs clears the input; only
  the active tab's identifier is sent in the POST body.
- `/compliance-salary-run` — Multi-firm toggle at top; when ON, shows
  the firm chip list and a Run batch button; running a batch shows a
  live-updating status card below the button (poll every 3 s).
- `/company-details/{cid}` — Super Admin sees a new "Payslip auto-email"
  section between "Company status" and "Company admin login" with a
  visible ON/OFF toggle chip.

### Credentials
See `/app/memory/test_credentials.md`. Super admin
`sksharmaconsultancy@gmail.com` via OTP dev mode.
`iter60_features.py` test suite from previous iteration still passes
(15/15).

## Files touched
- Backend:
  - `server.py` — added UAN/ESI/PF fields on `PinLoginRequest` and
    matching lookups in `pin_login`; wired the iter61 module before
    `include_router`; hooked `email_payslips_for_run` into
    `generate_payslips_from_run` (best-effort).
  - `utils/iter61_features.py` — NEW.
- Frontend:
  - `pin-login.tsx` — 4-way identifier picker.
  - `compliance-salary-run.tsx` — multi-firm toggle + batch panel +
    live polling.
  - `company-details.tsx` — `PayslipEmailToggleSection` component
    (super_admin + web only).

## Known caveats
- The multi-firm batch reuses the SAME config parameters (structure %,
  PF cap, ESIC threshold, etc.) across all selected firms. Firm-specific
  overrides still come from `companies.compliance_policy` (iter59).
- Payslip email delivery is best-effort. If Resend rate limits us or a
  particular employee email bounces, we log the failure but do not retry.

## Iter 179 — SaaS Portal Dashboard Phase 2 (2026-06)
- Backend: routes/portal_phase2.py — portal tasks CRUD, tracked documents CRUD (expiry buckets), client health scores, enhanced calendar (+toggle done), alerts/notification center. 24/24 pytest pass (tests/test_iter178_portal_phase2.py).
- Frontend: portal-dashboard.tsx tab strip + bell badge; new src/components/portal/{TasksPanel,DocumentExpiryPanel,ClientHealthPanel,CalendarPanel,AlertsModal}.tsx. Full web E2E by testing agent — all pass, Overview (Phase 1) regression intact.
- Known cosmetic: RN-web shadow*/shorthand CSS console warnings (pre-existing pattern, non-blocking).

## Iter 179b — Recurring Monthly Tasks
- Endpoints: /api/admin/portal-recurring-tasks (CRUD) + /seed-statutory. Lazy idempotent monthly generation on task listing (per-firm expansion for all_firms templates).
- Verified via curl (seed→4 templates→8 auto tasks, idempotent relist) + Playwright (Recurring modal, toggles, custom form).

## Iter 179c — Statutory task Done auto-ticks Compliance Calendar
- Marking a statutory recurring task done ticks that firm's calendar item; all-firms view ticks only when every firm's task is done; reopening un-ticks both. Curl-verified end to end (workspace left neutral).

## Iter 180/181 — Premium UI redesign + payroll punch line + default dashboard
- Testing agent iteration_180: 11/11 backend pytest + full desktop/mobile E2E pass (premium overview, dark mode persist, global search, ESS home, employee tab bar, landing restyle). No regressions.
- Iter 181 self-tested: payslip PDF builds w/ punch line (23KB), punch line visible on Compliance Salary screen, "/" redirects desktop admins to /portal-dashboard, sidebar has single "Dashboard" entry.

## Iter 182 — Salary audit log + premium Employee Master/Salary UX
- 6/6 pytest (tests/test_iter182_salary_audit.py) + 7/7 frontend flows green (iteration_182.json). Auto-save, search, shortcuts, audit modal, stats bar all verified.
- Fixed post-test: "process" audit hook re-added at server.py compliance run creation.

## Iter 183 — Login redesign + grid filter chips
- Testing agent: 2/2 backend pytest (tests/test_iter183_filter_chips.py) + all frontend flows green (iteration_183.json). Employee TEST50/123456 login works on redesigned page; chips filter/clear verified on fresh Kankani 2026-05 compliance run.

## Iter 184 — Login→Dashboard default + dashboard options audit + employee form redesign
- Testing agent iteration_184.json: login redirect PASS, 8/8 KPI cards (after /admin route fix), 8/8 quick actions, 5/5 tabs, bell/refresh/links/firm-chip PASS, employee add+edit premium form PASS, TEST50 employee login regression PASS.
- Known cosmetic: expo-router "REPLACE payload index" dev warning after login redirect (non-blocking).

## Iter 191 — KYC & Doc Expiry Tracker + modularization refactors
- Backend: routes/kyc_tracker.py (GET /api/admin/kyc-tracker), employee_kyc.py +dl_valid_upto/passport_valid_upto; routes/employee_documents.py extracted from server.py (identical behaviour verified).
- Frontend: app/kyc-tracker.tsx (KPI cards/chips/search/Validity modal), AdminWebShell sidebar entries; employee-add.tsx model → src/utils/employeeForm.ts.
- Testing agent: 13/13 pytest (tests/test_iter190_kyc_tracker.py, report /app/test_reports/pytest/iter190.xml) + full web E2E pass (modal save → EXPIRING badge + KPI increment; cleanup done). 2 cosmetic issues fixed post-test (kyc echo fields, testID non-ASCII slug).

## Iter 192 — Employee Advance Management
- Backend: routes/advances.py + salary hooks (compliance create/reprocess, actual process). 25/25 pytest (tests/test_iter192_advances.py). Idempotency, 'both' mirroring, net-cap, all action validations verified.
- Frontend: app/advances.tsx (Dashboard/Ledger/Reports + modals), app/my-advances.tsx (ESS), sidebar + ESS quick card. E2E pass (create ADV-00001, pause->on_hold, delete, reports).
- Test data fully cleaned by testing agent.

## Iter 197/198 — Geofence Phase 2 (offline punch queue) + RBAC route protection
- Backend 4/4 pytest (tests/test_iter_geofence_phase2.py): my-geo-policy toggle, offline capture-time honoured (IST), dedupe idempotency, 7-day sanity window. Curl E2E: offline punch with client_punch_at stored with correct at/date/synced_at/pending.
- RBAC: fixed Stack-remount reset in AdminWebShell (stable skeleton) + boot-path restore in index.tsx; staff/sub-admin direct URLs to restricted pages now show Access Denied (route-access-denied) with URL preserved. Page guards in roles/approval-workflows/advances return null on web instead of Redirect.
- iteration_198 429-storm on /attendance/my-geo-policy fixed via TTL cache + AsyncStorage persistence + mount-only effect (offlinePunch.getOfflinePunchEnabled).
- Known env noise: dev LogBox "Failed to fetch" overlay when simulating offline in dev builds (dev-only); Cloudflare security-check challenges under heavy automation.

## Iter 202 — Bulk Operations + Statutory Reports + 8-HR Present Day rule
- Backend: routes/bulk_ops.py (attendance upload status/inout, salary revision select+excel, transfer, resignation, shift assign, history) + routes/statutory_extra_reports.py (PT/LWF/Gratuity/FnF/Advance-Loan/MIS in json/xlsx/pdf) + CLRA form XII-XV .xlsx exports.
- Policy: new policy_master.compliance_present_8hr sub-point → compliance run present days at 8 hrs (utils/salary_run.py _present_day_hours_override) + grid duty/OT split at 8 hrs; "Days" replaced by policy-based "Present Days" (totals.present_days_policy) in grid JSON, XLSX builders and FnF.
- Frontend: app/bulk-operations.tsx, app/statutory-reports.tsx, clra-registers.tsx Excel buttons, attendance-grid "Present Days" labels, AdminWebShell nav entries.
- Testing agent: 32/32 pytest (tests/test_iter202_bulk_ops_reports.py) incl. 8-HR sub-point E2E; fixed advance-loan xlsx sheet-title "/" 500. Frontend bulk-operations page verified; statutory-reports/clra/attendance-grid partially (Playwright session loss, not a user bug). All test data cleaned.

## Iter 299–306 (fork session)
- Salary Register module: tested by testing_agent → /app/test_reports/iteration_299.json — ALL PASS.
- 20-point fix bundle + GPS punch fallback: tested → /app/test_reports/iteration_306.json — 12/12 backend pytest
  (/app/backend/tests/test_iter306_features.py) + frontend flows ALL PASS.
- Known cosmetic-only console warnings (padding shorthand, shadow*, resizeMode) — non-blocking, pre-existing.
- Dev DB: super admin PIN=246810; fresh Kankani compliance run for 2026-05 exists with resolved daily rates.

## Iter 307
- Email register: verified e2e via Playwright (real Resend email with PDF+XLSX attachments delivered).
- Perf: verified /companies excludes logo_base64, /companies/{id}/logo works, gzip content-encoding
  active on register payloads, /auth/me still returns profile_photo_base64, new indexes present.

## Iter 310 — Freeze Salary + Employee Detail Slip
- Backend: 10/10 pytest (/app/backend/tests/test_iter310_freeze_and_slip.py, report /app/test_reports/pytest/iter310.xml):
  freeze happy path (Overtime alloc), OT-off branch (Other Allowances), negative-diff non-destructive,
  snapshot persisted, slip endpoints (list/detail/pdf/xlsx/email 200, bad email 400).
- Frontend E2E pass: /employee-detail-slip (sections, "—" placeholders, FYTD, nav 1/127, exports, email input);
  /compliance-salary-run frozen badge + FREEZE band columns + totals.
- Test data cleaned by testing agent; ot_allowed restored true. No bugs found.

## Iter 311 — PWA speed (code splitting + gzip)
- Static+asyncRoutes production export verified with local SPA server + API proxy: root page,
  deep link /admin-pin-login, password login, /employee-detail-slip and /salary-register lazy
  chunks all load, no console/page errors. Dev preview (Metro) verified after app.json change.

## Iter 313-314
- ESIC Leave: backend curl E2E (settings, cert-required 400, backdate 400, freeze 409,
  compliance auto-import 5 days, register column) + frontend testing agent ALL PASS
  (/app/test_reports/iteration_313.json). Test data cleaned.
- RPA test flow: 2 live runs completed (bundled Chromium + system Chrome via executable_path);
  EPFO portal opened, #btnCloseModal clicked, screenshot captured.

## Iter 315
- Runner zip verified: contains run_ecr_test.bat; embedded runner code compiles; runner-script
  self-update endpoint serves version 2 with ecr_test. Selenium cannot execute in this ARM64 pod —
  final click validated earlier via Playwright against live EPFO (#btnCloseModal).

## Iter 316b-317
- Firm-mandatory guards curl-verified: /rpa/start + runner-download reject "all"/empty (400),
  accept real firm (200). EPFO modal-dismiss + Angular send_keys typing + runner v5 compile-checked.

## Iter 318
- EPFO Login & Dashboard flow live E2E: Open Portal → Close Alert → Enter User ID & Password
  (from Firm Master, auto-detected) all done; flow paused at captcha prompt as designed.

## Iter 394 — server.py refactor: Compliance Salary Runs extraction
- routes/compliance_salary_runs.py registered in server.py; 4 shared helpers imported back
  (they are still called at server.py lines ~8441/13858/15032/19307). De-duplicated 9
  double-registered routers. flake8 F821 clean on both files.
- Testing agent 23/23 pytest PASS (tests/test_iter394_compliance_salary_runs_refactor.py,
  report /app/test_reports/iteration_394.json): CRUD on test run 2026-08, finalize gate,
  unlock flow, all 7 exports on existing run csrun_bca09c4a4cec (unmodified), legacy
  helper-dependent endpoints (POST /admin/employees, actual-salary-process, payslips.zip),
  de-dup sanity, no NameError in logs. Test data cleaned.
- Pre-existing unrelated 500s noted in logs: audit-export xlsx, biometric/connection-doctor,
  rpa interact, compliance-import upload (env/data-related, NOT from this refactor).

## Iter 395 — WhatsApp Business Integration Module
- Backend 22/22 pytest PASS (tests/test_iter395_whatsapp.py, report
  /app/test_reports/iteration_395.json): settings masked-token round-trip, test-connection
  graceful fail, template CRUD/seed/preview, queue → worker → failed(not_configured) in
  pending-config mode, retry/cancel/delete, send-salary-slips, dashboard, reports
  json/xlsx/pdf, schedules CRUD, webhook verify 403/challenge-echo, status callback,
  chatbot HELP reply, employee-create regression.
- Frontend verified: whatsapp-config (firm dd, creds, automation switches, PENDING CONFIG
  badge), whatsapp-templates (30 seeded, edit/preview modals), whatsapp-center all 6 tabs.
- NOTE: Meta Graph API not mocked — unconfigured by design until user enters credentials
  on the VPS. All test data cleaned; Kankani wa_settings reset to disabled.

## Iter 397 — server.py refactor (steps 3-6) + one-click portal login
- 35/35 backend regression PASS (tests/test_iter397_refactor_regression.py, report
  /app/test_reports/iteration_397.json). Extracted: attendance_policy_api,
  attendance_reports_api, attendance_location_api, employees_admin (+ earlier
  actual_salary_process). server.py 19,747 → 17,914. openapi 698 paths (2 new
  portal-login endpoints added).
- One-click portal login: launch-token (auth) + get-login alias + Runner v6 listener
  (127.0.0.1:8765, CORS + Private-Network) + alert-OK click before autofill. Listener
  contract verified via curl; frontend fallback (tab + hint) verified via Playwright.
- Employee create→delete cycle functionally verified post-extraction (no 500 with
  WhatsApp unconfigured).

## Iter 398 — attendance_core extraction + Runner v7 alert handling
- 26/26 backend regression PASS (report /app/test_reports/iteration_398.json). server.py
  now 14,400 lines. Boot ImportError fixed by re-exporting 13 shared names before other
  route-module imports.
- Runner v7: OK (#btnCloseModal) → X (aria-label=Close) → generic dismiss, then autofill.

## Iter 422
- Editable Advance Deduction: backend E2E (tests/check_advance_edit.py) —
  compliance run 2026-05 save-rows with advance_recovery=500 + manual_fields,
  reprocess → adv preserved (500), td/net adjusted; test run deleted after.
  Actual run asal_dedbdccd233e PATCH adv=750 → net -750 (200 OK), reverted.
- Frontend Playwright: Advance* editable column + ADVANCE totals chip visible
  on compliance grid (run csrun_bca09c4a4cec); "Date of Join" header visible
  in /master-data-report; xlsx export 200.

## Iter 423
- Salary Lock validation firm-policy gate: toggled Kankani epf/esi.applicable
  live against run csrun_bca09c4a4cec — BOTH ON (8e/9w: ESIC_MISSING_IP,
  PF_MISSING_BASIC), ESI OFF (0e/9w), BOTH OFF (0/0), restored to ON.

## Iter 423b
- Non-blocking finalize: cloned csrun_bca09c4a4cec → finalize with 8e/9w →
  200 OK, lock_validation stamped with non_blocking_policy; clone deleted.
- Actual p_days uncapped: PATCH p_days=35 on asal_dedbdccd233e (month_days
  31) → accepted; reverted to original.

## Iter 425
- Higher PF auto-approve + VPF: tests/check_higher_pf_vpf.py — 6 assertions
  PASS (higher wages uncapped, approval ignored, toggle-off fallback, VPF on
  top employee-side, VPF disallowed skip).

## Iter 426
- Backend: 2026-05 STAFF run created @26 days; reprocess w/ 31 → stays 26 &
  keeps manual other_ded 111; fresh=True → stays 26, edits discarded; deleted.
- Screenshot: 4 buttons removed, firm banner gone, month-days 🔒 note, group
  mandatory dropdown; grid renders fine (run csrun_bca09c4a4cec).

## Iter 485
- Firm Master 16-section ERP + Contact Details + auto-save: backend 14/14
  pytest PASS (tests/test_iter485_firm_master_and_snapshot.py), frontend 5/5
  Playwright flows PASS (report /app/test_reports/iteration_485.json).
- Master snapshot lifecycle E2E: generate→v1 freeze, master edit, reprocess
  frozen, delete+generate frozen, refresh-master→v2 + audit w/ IP; cleanup done.
- Sub-admin present-today scope: restricted sub_admin blocked from
  non-allowed firm (with and without ?company_id).
- PF/ESIC calc engine untouched (git diff clean on utils/compliance_salary.py).

ITER 487 (doc-expiry alerts):
- Backend curl E2E: run-now found=2 (60/30/7 buckets), SMTP guard msg OK,
  real send via local SMTP sink OK (1 email/2 alerts), idempotency OK.
- Sub-admin scope guard added to scheduled_reports._adm (unit-verified).
- UI: "Check Expiring Docs Now" button works e2e (screenshot verified,
  Server Iter 487 badge visible). Test data cleaned.

## Iter 520
- Backend testing agent: 11/11 PASS (test_reports/iteration_508.json;
  backend/tests/test_iter520_backend.py). Engine OT policy cases: 8h worked
  +1h lunch → OT 0 (was 1h phantom); 9h → duty 8/OT 1; Sunday no-punch
  weekly_off=true. Sync dashboard shows unregistered-device + never-punched
  machine users. Challan pf_status persists, 400 on invalid. ESIC reason
  stored. FORM 23 PDF 200. Periodic salary comparison subtitle/cols correct
  incl. xlsx/pdf. /api/version=520.
- UI screenshots: ESIC form (dropdown/DD-MM-YYYY/reason), Challan PENDING▾
  badges, Report Hub Month-wise|Periodic tabs + default month from
  last-finalized-month. Server Iter 520 badge visible.

## Iter 527
- Backend: 26/26 pytest PASS (tests/test_iter527_central_wage_and_salary_compare.py):
  grouped salary comparison (both/department/designation + totals + xlsx/pdf),
  central wage registers Form A-D JSON/xlsx/pdf, workflow transitions + audit,
  Form C 409 when locked, masters CRUD + employee-map reflected in Form A,
  Form D custom period slices to exact day columns.
- Frontend: /central-wage-registers tabs + Setup render; Report Hub group-by
  chips (rc-cmpgroup-*) switch correctly; /present-absent-report OT format
  dual-row table renders, old format unchanged. (test_reports/iteration_527.json)

## Iter 530
- 12/12 pytest PASS (tests/test_iter530_monthly_payroll_and_manual.py):
  monthly payroll report JSON/xlsx/pdf + filters + null-note behaviour +
  bank masking (super vs sub admin), user-manual.pdf 200/401/403.
- Frontend: Report Hub separate Contractor Registers section placement,
  monthly payroll grid + basis toggle, user manual screen — ALL PASS.

## Iter 531
- Auto-update manual verified: 23-page PDF with What's New page + live
  version/screenshot dates; refresh-screenshots endpoint captured 15/15
  with sample-data seeding + cleanup (0 leftovers), blank/error screens
  rejected; /companies crash fixed and re-captured correctly.

## Iter 533
- Employee Quick Guide: 9-page PDF verified (cover + punch page rendered),
  200 super admin / 401 unauth. manual_capture now 21/21 good captures
  incl. 6 employee phone shots; temp employee session + samples cleaned.
- payroll/run employee self-scope fix verified via emp_payslip capture
  showing real data (20 present days).

## Iter 532 (rev 2)
- manual_capture re-run: 21/21 ok. Visually verified employee_master
  (employee list), attendance 2026-07 (real punches), monthly_payroll
  2026-07 (P/A codes, finalized run), bank Jul 2026 chip, payslip
  ₹22,100 (MADAN KEER).
- user-manual.pdf: 23 pages, cover has Product By/Prepared By Ankit
  Sharma only, no CONFIDENTIAL, footer punch line on every page, no
  What's New page/TOC entry. employee-guide.pdf 9 pages OK.
- Frontend /user-manual: refresh button gone, download buttons + status
  line work (screenshot verified). Playwright chromium-headless-shell
  reinstalled after fork (browsers wiped).

## Iter 533 (manual sections)
- capture re-run 23/23 ok; firm_add.png (Firm Master 16-step editor,
  General Information) and employee_add.png (Add New Employee form with
  OCR buttons) visually verified.
- user-manual.pdf: 25 pages; TOC + body have "4. Add New Firm" (page 6)
  and "6. Add New Employee" (page 8); no Software Version on either
  cover; employee-guide.pdf cover verified too.

## Iter 534
- API /admin/reports/monthly-payroll: 127 rows in 0.12s; att_mode=HRS+OT;
  day cells "8+4.5"/"8+4"/"-"/WO verified; xlsx+pdf 200.
- UI: grid rendered ~5s full load, typing in search 0.1s responsive
  (was hanging); legend shows "8+4 = Duty HRS + OT HRS"; screenshot OK.
- Manual cover: punch line centred mid-page, Product By/Prepared By at
  bottom, footer punch line centred (pypdf text-order verified).

## Iter 535
- API without month param returns month=2026-07 (finalized) while current
  month is 2026-08; UI month input auto-fills 2026-07, grid loads.

## Iter 536
- Stepper: start 2026-07 → prev 2026-06 → next 2026-07 (run months
  2026-03/06/07/08) verified via playwright.
- /employee-add: Actual allowance/deduction blocks + (Actual) total gone,
  Compliance blocks intact, lint clean, screenshot verified.

## Iter 537
- RAJENDRA 2026-07: d1 8+3, d3 8+2.5, d5 7 (worked WO), d10 8+1.5 —
  matches _compute_monthly_grid_data duty/ot split exactly. UI verified.

## Iter 538/539
- Cache: 1st call 0.104s, 2nd 0.028s. Legacy (flag OFF) unchanged 8+3.
- Seq mode ON test: full-duty split at firm hrs, explicit OT pair pure OT,
  next-morning OT OUT stitched. Grid/OT-report/daily-verification all via
  same engine. UI screenshot OK (Show more hidden under 150 rows).

## Iter 540
- API punch_sequence=False for demo firm; badge renders in header
  (screenshot verified, testID dv-rule-badge).
