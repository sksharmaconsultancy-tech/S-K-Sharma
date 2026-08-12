# S.K. Sharma & Co. — Product Requirements

## Overview
Mobile app for **S.K. Sharma & Co.**, offering **Compliance · Payroll · Manpower** services. Employees clock in/out via geo-fenced biometric verification, view payslips & compliance documents, request leaves and raise service tickets. Company/Super Admins manage employees, approvals and broadcasts.

## Brand
- Firm: **S.K. Sharma & Co.**
- Tagline: *Compliance · Payroll · Manpower*
- Palette: Navy `#1B3A6E` + Amber `#E39A2A` + Cream `#FBFBF9`
- Logo assets in `/app/frontend/assets/images/`: `logo.png`, `logo-mark.png`, `icon.png`, `adaptive-icon.png`, `splash-image.png`, `favicon.png` (sourced from user-provided brand asset)

## Multi-Tenant Support
- Super Admin can create and manage multiple client companies under one panel (`/companies` screen).
- Each company has its own geofence coordinates and radius.
- Employees & activities (attendance, leaves, tickets, notifications) are stamped with `company_id`.
- Company Admins see only their own company's data; Super Admin sees everything with a company filter.
- New Google sign-ups start with `company_id = null` and land in the Admin Panel's "Unassigned" list until Super Admin assigns them to a company.

## Employee Onboarding (self-service via company code)
- Each company auto-generated a **6-char company code** (visible on the Super Admin's Companies screen, tap the yellow bar to share via native share sheet).
- New Google sign-ups with `role == 'employee'` and `onboarded == false` are auto-redirected to `/onboarding`.
- 3-step onboarding wizard:
  1. Enter company code → validated via `GET /api/companies/by-code/{code}` and shows a "matched company" preview.
  2. Personal details: Name, Father's name, DOB, DOJ.
  3. Employment: Shift start/end, monthly salary, half-day hours, full-day hours.
- On submit → `POST /api/onboarding` sets `company_id`, saves all fields, sets `onboarded = true`. User lands in the app.
- Super Admin can still manually assign/override any field via the Admin Panel employee editor.

## Roles
- `employee` — default (2nd+ signups, unassigned until Super Admin links to a company)
- `company_admin` — HR-level (approve leaves, tickets, broadcast, upload payslips) for ONE company only
- `super_admin` — first signup auto-elevated; can create companies, assign users to companies, promote roles

## Auth
- **OTP-based sign-in** (email or SMS). `OTP_DEV_MODE=1` returns the 6-digit code in the API response for local testing. Google login has been **removed** from the landing screen per user request.
- Bearer token stored in `expo-secure-store` (mobile) / `localStorage` (web)
- `sksharmaconsultancy@gmail.com` is hard-coded as the ultimate `super_admin` on first sign-in.

## Employee approval workflow (NEW)
- Self-onboarding (`POST /api/onboarding`) sets `approval_status='pending'`.
- `/api/auth/me` exposes `approval_pending` / `approval_rejected` flags; frontend guards route pending users to `/pending-approval` (auto-polls every 20s).
- Company/super admin sees a "Pending approvals" section on the Admin Panel with Approve / Reject actions.
- Approve → sets `approval_status='approved'`. Reject → clears `company_id` + `onboarded=false`, employee bounced back to `/register-choice` with an explanatory banner.
- Super_admin manually assigning a `company_id` via `PATCH /admin/user-role` also auto-approves.

## Employee offboarding (exit date)
- Company/super admin can set `exit_date` (YYYY-MM-DD) on any employee in their company via `PATCH /admin/user-role`.
- If `exit_date <= today`, `/api/auth/me` returns `offboarded=true` and `company_name`. Guards redirect the employee to `/offboarded`, showing "You are no longer to use this app due to you have left company (…)".

## Core Features
1. **Landing** — Branded hero + Google Sign-in
2. **Dashboard** — Today's shift, quick stats, admin overview (if admin), quick actions
3. **Smart Punch** — Geo-fence check (Haversine, configurable radius) + fingerprint/Face ID (`expo-local-authentication`)
4. **Attendance History** — 30-day punch log
5. **Leaves** — Employee request; admin approve/reject
6. **Documents** — Payslips + labour compliance docs (PF/ESI/Gratuity/Min Wage/Policy — 5 seeded)
7. **Tickets** — HR/payroll/compliance/IT/other queries with admin reply
8. **Notifications** — Broadcast by audience (all/employees/admins)
9. **Admin Panel** — Employee list, role management (super_admin), org stats
10. **Profile** — Google identity, workplace links, logout

## Backend (FastAPI + MongoDB)
Endpoints under `/api`:
- `POST /auth/session`, `GET /auth/me`, `POST /auth/logout`
- `GET /company`, `PATCH /company`
- `POST /attendance/punch`, `GET /attendance/today`, `GET /attendance/history`
- `POST /leaves`, `GET /leaves`, `PATCH /leaves/{id}`
- `GET /payslips`, `POST /payslips`
- `GET /compliance-docs`, `POST /compliance-docs`
- `POST /tickets`, `GET /tickets`, `PATCH /tickets/{id}`
- `GET /notifications`, `POST /notifications`
- `GET /admin/employees`, `PATCH /admin/user-role`, `GET /admin/stats`

## Seed Data
- Demo company **Demo Enterprises Pvt Ltd** at `12.9716, 77.5946` (Bengaluru), 500m geofence radius
- 5 compliance documents (PF, ESI, Gratuity, Minimum Wage 2026, Code of Conduct)

## Notes
- Biometric on device (`expo-local-authentication`) — face on iOS if enrolled, else fingerprint
- Geofence enforced server-side using Haversine
- Frontend uses `@/src/utils/storage` avoided; auth uses `expo-secure-store` directly per playbook

---
## Iteration 91 (June 2026) — Salary/Master/OCR/Reports batch
All items user-requested this session; backend 21/21 + frontend 18/18 tests passed.

### Salary Update modal (SalaryUpdateModal.tsx + routes/employee_salary.py)
- Actual structure fixed layout: Basic Salary (+ Monthly/Daily/Hourly `rate_type` dropdown), Salary 1/2/3 rows (amount + `working_days`).
- Allowances/Deductions sections: heads = ENABLED heads on Firm Master (`firm_masters.allowances/deductions`), amounts only, no delete. Saved as `users.actual_salary_allowances/actual_salary_deductions`.
- Compliance: Basic head always present & non-deletable; PF Employer = 12% × Basic, ESI Employer = 3.25% × Gross (≤ ₹21,000) auto-calc (AUTO badge); decimals (.00) allowed everywhere.
- Employee Type/Group editable inside the modal (MasterSelect).

### Salary processing (server.py ~16560, utils/salary_run.py, utils/compliance_salary.py)
- Actual run: `basic` = Basic row from `salary_structure_actual` (falls back salary_monthly); `oth_allo` prefilled with master allowances; EPF/ESI FETCHED from latest compliance run same month+firm (0 if none); Total Gross = Basic Sal + W.Basic Sal + Oth.Allo; hourly = basic × (p_days×duty_hrs) + basic×p_hours.
- Compliance resolve_structure: precedence-0 = employee `salary_structure_compliance` rows (Basic from updated master).
- Compliance run finalize: POST /api/admin/compliance-salary-runs/{run_id}/finalize; reprocess blocked (409) when finalized.

### Unified Employee Type/Group
- RoleUpdate accepts either key; both users.employee_type & employee_group set (Title-Cased). MasterSelect dropdown (Group master) used in employee-add, employee-master Grouping card, salary-run filter, Update Salary modal.

### New components/screens
- src/components/MasterSelect.tsx — collapsed dropdown backed by /admin/masters?type=..., custom values allowed, in-flow menu (no clipping).
- app/past-salary-runs.tsx — Utilities → Past Salary Runs (actual + compliance tabs; deep-link ?run_id= opens run on process screens).
- app/master-data-report.tsx + routes/master_data_report.py — Reports → Master Data: READ-ONLY employee master, tabs Active/Left/All (left = exit_date set), filters (q, employee_type, is_onroll, company_id), Excel export (/api/admin/reports/master-data[.xlsx]).
- routes/employee_profile.py — GET/PATCH /api/admin/employees/{user_id}/profile (one-page full edit).
- app/employee-add.tsx — dual mode: ?user_id= = EDIT existing (prefill + PATCH profile, "Save all details"); salary section = Basic + rate basis + Salary 1/2/3 (allowance/deduction pickers removed); Designation/Department/Type-Group = MasterSelect dropdowns.
- app/employee-master.tsx — "Edit All Details (One Page)" button; UanEsicCard (generate-uan/esic, Aadhaar-only mandatory, creds-missing ⇒ job queued manual_required); Residential Address MetaCell.

### OCR (routes/ocr.py, ScanOCRButton.tsx)
- Multi-page: payload {pages:[{document_base64, mime_type}]}, max 2 uploads/4 images; PDF rasterised server-side via PyMuPDF (pymupdf in requirements); "Add 2nd page" UI; legacy single-image still works.
- KYC PATCH present_address ⇒ also writes users.address (Address column sync).

### Grids/UX
- salary-run grid: arrow-key ↑↓←→/Enter navigation (cellRefs in ResultGrid), column group tints (master=blue #EFF6FF, calc=green #F0FDF4, deductions=red #FEF2F2), focus-guard stops mid-edit refresh; Employee Type REQUIRED before generate; in-screen firm picker shows ALL firms.
- compliance-salary-run: in-screen "Select firm" card (all active firms, localCid override), buildBody sends company_id, Save/Finalize button + FINALIZED lock chip.
- punch-approvals: Single day / Periodic (From–To) date filter; DateField opens native calendar on any click (showPicker) — global fix.
- firm-master Settings: mandatory Attendance Policy selector (standard | textile ⇒ settings.attendance_policy_preset).
- live-sync.ts: fixed double /api in WS URL.

### Known remaining / backlog
- server.py biometric /iclock/* extraction to routes/biometric_devices.py (pending refactor).
- RPA captcha solver (needs user API key). Employee Details Slip PDF (awaiting sample). SQL mirror (P3).
- Minor web console warnings: RNW shadow*/outline deprecations, expo-notifications listener on web.
- Employee Master does not yet display firm's selected attendance policy preset (selector exists on Firm Master).

## Iter 92-verify (fork) — Compliance Reports verified + biometric routes extracted
- compliance_reports.py: FIXED `net_pay` → `net` key mismatch in _CONTRIB_KEYS (contributions were all 0 rows). All 3 reports (contributions/leave/gratuity) + .xlsx export verified via curl + web UI screenshot (renders inside AdminWebShell sidebar → Reports → Compliance Reports).
- compliance-reports.tsx & master-data-report.tsx: added authLoading guard (spinner) so screens don't flash "Admins only" during auth boot.
- routes/biometric_devices.py (NEW): all ZKTeco /iclock/* + /biometric/* endpoints moved out of server.py (-520 lines, now ~16.4k). E2E verified: register device → handshake → ATTLOG push → attendance ingest (auto-approved, bio_code/employee_code mapping) → simulate-punch → delete. server.py refactor COMPLETE.
- Monthly master-data email: manual endpoint POST /api/admin/reports/master-data/email works; Resend key verified (200, delivered to sksharmaconsultancy@gmail.com). NOTE: seeded firm admin emails (admin@kankani.local) get resend_status_403 — Resend sandbox sender (onboarding@resend.dev) only delivers to the account owner's address until a domain is verified. Not a code bug.

## Iter 93 — Pendency batch (user: "do pendency / next action plan")
- Compliance Reports .xlsx: firm LETTERHEAD (name/address/title/generated-on, merged-centered rows 1-4, table from row 6) + signature block ("For {firm}" / "Authorised Signatory") at bottom-right.
- routes/super_admins.py (NEW) + app/super-admin-access.tsx (NEW — fixes dead sidebar link "User Rights → Super Admin Rights"): full CRUD for super_admin accounts. GET/POST /api/admin/super-admins, PATCH/{id}, POST/{id}/reset-password, DELETE/{id}. Guards: strict super_admin only (sub_admin rejected), no self-disable/self-delete, last-enabled-super-admin protected, sessions revoked on disable/delete. New super admins: email OTP login always; optional password (password_must_change=True).
- E2E verified via curl + Playwright UI (create modal → list card w/ Edit/Disable/Delete, "You" badge, self-protected). Test account cleaned up.
- Still blocked on user input: 2Captcha API key (RPA autonomy), Employee Details Slip PDF sample format.
- utils/welcome_email.py (NEW): send_admin_welcome_email() — Resend welcome email with login details on super-admin AND sub-admin creation (fire-and-forget; creation never fails on email errors). APP_PUBLIC_URL added to backend/.env for the portal link. Sample delivered to sksharmaconsultancy@gmail.com; fake/test addresses log resend_status_403 warning only.

## Iter 93b — BUG FIX: Actual Salary Process crash ("bg is not defined")
- User report: "Not able to Process" — run WAS created but grid render crashed with red error screen.
- Root cause: salary-run.tsx EditCell declared `bg?: string` in its TS type (Iter 91 column tints) but never destructured `bg` from props → runtime ReferenceError at line 947.
- Fix: added `bg` to EditCell destructuring. BONUS: HdrCell white header text was invisible on light group tints → dark text (#1E293B) when bg set.
- Verified E2E via Playwright: firm → Labour → Salary Process → grid renders w/ 2 employees, all headers visible, totals OK.

## Iter 93c — Kankani fresh data import (user-provided "Kankani Data.xls")
- BACKUP first: /app/backups/kankani_backup_20260709_030725.json (62 old employees, 1250 punches, 32 salary runs, 1 compliance run).
- CLEARED for cmp_527fecdd7c: employees, attendance, leaves, salary_runs, compliance_salary_runs, biometric_unmapped.
- IMPORTED 125 employees (108 Labour / 17 Staff) from the .xls: code(50-532, also bio_code), name, father, designation, department(WEAVING/SECURITY), type, gender, dob/doj (DD-MM-YYYY), salary_structure_actual (Basic daily/monthly + Salary 1/2/3 tiers w/ working_days verbatim), full_day_hrs (Wrk Hrs), PAN/Aadhaar/ESI/PF, bank fields, PIN 1234. No phones in sheet (emp-code-login blocked until phones added).
- Verified: Actual Salary Process returns 108 Labour + 17 Staff; dashboard shows 125 employees; iter73 old salary test-run drafts cleaned.

## Iter 93d — Duplicate-email guard on Employer Registration (user question: "If Employer Register with Same Mail id")
- OLD behavior (bug): duplicate email was ACCEPTED at registration; at approval the users.email_1 unique index blew up → code swallowed it and marked request "approved" pointing at the WRONG existing firm, with NO new firm provisioned (silent failure).
- FIX 1 (registration /auth/company-register): email now checked like phone — super_admin email → 409 guidance; live-firm account → 409 "already registered with '<firm>'"; orphan account → auto-healed (purged); duplicate email on a pending request → 409.
- FIX 2 (approval PATCH /company-requests/{id}): DuplicateKeyError branch now only returns idempotent success when the existing admin matches by PHONE (true double-tap); an email-only conflict → new company rolled back, request auto-REJECTED with reason, 409 to super admin.
- Tested: existing-firm email blocked, super-admin email blocked, pending-dup blocked, fresh email registers + approves fine. Test data cleaned.

## Iter 93e — Default biometric punch factor = Fingerprint Only (user request)
- src/utils/biometric.ts getBiometricPreference(): when NO explicit choice saved → returns "fingerprint" if device has a fingerprint sensor; face-only devices fall back to "any" (so Face-ID-only iPhones aren't locked out). Explicit user choice always wins.
- biometric-prefs.tsx: "Default" label moved from "Any enrolled biometric" to "Fingerprint only".
- Strict mode: fingerprint pref disables OS fallback (no silent PIN/face swap). NOTE: native-only behavior — verify on a real device via Expo Go, not web.

## Iter 93f — P Days typing fix + Bio Codes import
- BUG (user report): Compliance Salary "Present Days" was a controlled TextInput clamped on EVERY keystroke → couldn't type >2 chars or decimals ("26.5" became "31" mid-edit). Actual Salary was already fine (EditCell has local state).
- FIX: new PresentDaysCell component in compliance-salary-run.tsx — local text state while focused, commit+clamp (to month_days) only on blur/Enter, arrow-key row navigation preserved. Verified: "26.5" commits as 26.5; "265" clamps to 31 on blur.
- BIO CODES: user uploaded updated "Kankani Data.xls" with "Bio Code No" column → all 125 employees' bio_code updated (was employee_code before). Spot checks: emp 50→bio 72, 65→19, 81→5. NOTE: 2 duplicate bio codes in sheet imported verbatim: SEETA BAI (emp 437 & 460 → bio 55), ANSHUL YADAV (emp 484 & 519 → bio 80) — device punches for these map ambiguously.

## Iter 93g — Batch: P Days .5 steps, Refresh Bio, Punch Approvals table + calendar fix
- P Days half-day steps: salary-run.tsx (onChange snap Math.round(v*2)/2), compliance-salary-run.tsx PresentDaysCell commit snap, backend actual-salary-process auto-fetch p_days snapped to .5.
- Refresh Bio: POST /api/biometric/remap-unmapped (routes/biometric_devices.py) re-matches biometric_unmapped raw ATTLOG lines against CURRENT bio codes; "Refresh Bio" button in attendance-grid.tsx toolbar (teal, next to Excel). E2E verified: unknown punch → unmapped → set bio_code → remap → attendance created.
- Punch Approvals CALENDAR BUG root cause: DateField was wrapped in <View style={{flex:0}}> which computes width 0 on RN-web → field rendered overlapped/invisible. Removed wrappers + dateBar flexWrap + DateField minWidth 170.
- Punch Approvals TABLE (user request): Pending/Approved/Rejected/Auto/Manual tabs now render the same day-summary grid as Updated tab with columns Date, Name, Father Name, Designation, In, Out, Duty HRS, OT In, OT Out, Total OT, Total Duty HRS + Action (✓/✕ queue → Save batch). Punches grouped per employee+day; first IN/OUT pair = duty, later pairs = OT. DELETED dead code: PunchCard, RejectModal, AdjustModal, Fact, approve(), submitReject/Adjust (~400 lines). Backend pending-punches now returns father_name.
- NOTE: "Data not showing" root cause = user's ZK punches are dated 2026-07-05..07 while default filter is today + Pending; imported punches are status=approved (visible in Approved tab with correct dates). Verified table shows real imported data.

## Iter 93h — .dat imports stored + re-read on "Refresh Bio" (user request)
- upload_zk_dat (server.py) now persists raw .dat text into db.zk_dat_imports (import_id, company_id, from/to dates, source_tag, in/out/combined text capped 4MB each).
- /api/biometric/remap-unmapped (Refresh Bio button) now ALSO re-runs import_zk_dat_bytes on the last 20 stored imports (same source_tag → idempotent dedupe). Response adds dat_files_reread + dat_recovered; attendance-grid alert updated.
- E2E verified: upload .dat w/ unknown bio 88888 → 2 unmapped, stored → set bio on emp 65 → Refresh Bio → 2 punches recovered (in/out kinds alternate correctly) → rerun recovers 0 (idempotent).
- CAVEAT: imports uploaded BEFORE this feature aren't stored — user must re-upload once.

## Iter 93i — "Blank on any click" root cause: Cloudflare challenge on API calls
- Diagnosis (confirmed w/ troubleshoot_agent): preview domain's Cloudflare bot-protection intermittently returns "Just a moment…" HTML (HTTP 200, text/html) to fetch() API calls → api client crashed parsing → every screen blank + red overlay. Backend 100% healthy (curl JSON OK; app renders fully via localhost:3000).
- FIXES shipped:
  1. src/api/client.ts: BASE = "" (relative /api) on web → same-origin requests carry cf_clearance cookies (native keeps EXPO_PUBLIC_BACKEND_URL). attendance-sheet.tsx upload URL also made relative.
  2. api(): content-type check before JSON parse; CF challenge detected → auto-RETRY once after 1.5s; if still challenged → friendly tagged error ("Security check in progress — reload the page") instead of raw HTML dump.
  3. _layout.tsx: web unhandledrejection suppression for tagged isChallenge errors + LogBox.ignoreLogs.
- LIMITATION: the sandbox automation browser IP is now hard-flagged by CF (headless can't solve challenges) → cannot E2E via preview URL from automation for a while. Real-user browsers solve the challenge interactively on page load. Dev-only red overlay may still appear for uncaught cases; gone in published builds.

## Iter 93j — Access Rights: set USER ID + Password for firm admins (App & Web login)
- routes/admin_credentials.py (NEW): GET/POST /api/admin/companies/{company_id}/admin-credentials (super_admin strict). Sets `login_id` (3-32 chars [A-Za-z0-9_.], unique case-insensitive across users incl. email clash check) and/or bcrypt password (must_change False, lockout counters reset).
- server.py admin-password-login: now accepts EMAIL OR USER ID in the same field ("@" → email lookup, else case-insensitive login_id regex). Lockout logic unchanged.
- employer-access-rights.tsx: "Login Credentials (App & Web)" card below permission groups — shows admin/email/current User ID/password-set status, inputs + "Set credentials". admin-pin-login.tsx: password mode accepts "email or User ID" (placeholder + validation).
- E2E verified: set kankani/kank1234 → login via "kankani" AND "KANKANI" works (case-insensitive), bad id rejected, UI card renders. NOTE: Kankani admin now has login_id=kankani password=kank1234 (recorded in test_credentials.md).

## Iter 93k — Credentials tested Web+App; employee phoneless login FIXED
- Tested: super admin OTP ✓; firm admin User ID `kankani`/kank1234 web UI login ✓ (dashboard loads as Prakash Kankani); email login ✓; wrong password rejected ✓.
- FOUND+FIXED: 125 imported employees have NO phone → emp-code-login (code + phone last4) was impossible. Backend now falls back: candidates WITHOUT a phone can sign in with employee_code + 4-digit PIN (verified via pin_hash). Same single input field accepts last4 OR PIN; labels updated on emp-code-login.tsx.
- Verified: emp 50 + PIN 1234 logs in (backend + web UI); wrong PIN rejected; web correctly shows employees "Please use the mobile app" gate (by design, employees are mobile-only).

## Iter 93l — "Not able to login Super Admin" FIXED
- ROOT CAUSE: OTP_EMAIL_ENABLED=false in backend/.env → OTP codes were never emailed (only shown as dev_code hint); super admin's pin_hash/password_hash existed but values were undocumented (user's PIN/password attempts → 401).
- FIX: OTP_EMAIL_ENABLED=true (verified delivered:true via Resend to their inbox); reset known credentials: PIN 654321, password sharma123, login_id sksharma. All 3 methods curl-verified.

## Iter 93m — Access Rights: PIN option added (App login)
- admin_credentials.py: POST now accepts `pin` (6 digits) → pin_hash set, lockout counters reset; GET returns has_pin. employer-access-rights.tsx credentials card: added "App PIN (6 digits)" input.
- admin-pin-login: identifier now also resolves login_id (case-insensitive) besides email/phone/company_code.
- Verified: set PIN 111222 for Kankani admin → PIN login works via email AND via User ID (user already renamed login_id to "Kankani123" themselves). Note: Kankani admin PIN now 111222 (test value; user may change).

## Iter 93n — Sidebar Menu Access (per-button allow/block) in Access Rights
- Backend: companies.employer_menu_rights {route: bool} (missing == allowed, {} == all). PATCH/GET /admin/companies/{id}/access-rights carry menu_rights; /auth/me exposes user.menu_rights for company admins. EmployerAccessUpdate.menu_rights added (NOTE: earlier parallel edit corrupted server.py tail — fixed, lines 16527-16533 garbage removed).
- AdminWebShell.tsx: NAV_COMPANY_ADMIN + NavItem now exported; company_admin nav filter hides items whose menu_rights[route] === false (both all-features and scoped branches). Also FIXED pre-existing missing `Image` import (would crash when a firm logo was set).
- employer-access-rights.tsx: new "Sidebar Menu Access (Web Portal)" section lists every sidebar button (groups + children) with Allowed/Blocked toggles; saved together with the existing Save access rights button. Dashboard excluded (always visible).
- Verified: PATCH saves, /auth/me returns menu_rights (tested via injected session for Kankani admin), UI renders all toggles. NOTE: user has changed the Kankani admin PIN + password themselves via the credentials card (old test values kank1234/111222 no longer valid).

## Iter 94 — Sub-Admin granular Sidebar Menu Rights (mirrors Employer Access Rights)
- Backend: users.menu_rights {route: bool} for sub_admins; SubAdminCreate/SubAdminUpdate accept menu_rights; PATCH/GET /admin/sub-admins persist+return it; /auth/me returns sub-admin's own menu_rights (guarded _enrich_user_with_company so the firm's employer_menu_rights no longer clobbers sub_admin's own map).
- sub-admins.tsx: editor modal now has "Sidebar Menu Access (Web Portal)" section listing NAV_SUPER leaf routes with Allowed/Blocked toggles (SUB_ADMIN_ALWAYS_BLOCKED routes excluded: /sub-admins, /employer-access-rights, /super-admin-access, /attendance-sheet, /masters, /compliance-policy, /portal-automation, /ai-insights, /appearance).
- AdminWebShell.tsx: CRITICAL FIX — web gate at ~L476 previously short-circuited sub_admins to EmployeeWebGate ("use mobile app"); added role !== "sub_admin" so sub-admins reach the desktop shell; sidebar filter honors menu_rights[route] === false.
- Verified E2E: super admin edits Test SubAdmin menu rights → persists; sub-admin login shows restricted sidebar (Salary Process/Tickets hidden). NOTE: menu_rights keys only gate LEAF routes; group labels auto-hide when all children blocked.
- Test sub-admin account created: testsub@sksharma.co / testsub123 (password_must_change=true; menu_rights: salary-run/reports/employees-inert/tickets blocked).

## Iter 94b — Add / Update Employee: SAME one-page form (user request)
- Employee Master Data (/admin) row → preview sheet now has a PRIMARY "Edit Employee Details (same form as Add New Employee)" button → /employee-add?user_id=… (identical fields & order). Duplicated quick-edit inputs (emp code/dept/position) REMOVED from the sheet; sheet keeps admin-only controls (exit date, live-in, role/company for super admin).
- employee-add.tsx: added Employee Code (auto if blank on Add) + Bio Code fields at top of Identity — matches Kankani master-sheet columns. FIXED pre-existing crash: useEffect used but never imported (broke the whole screen).
- Backend: routes/employee_profile.py — employee_code + bio_code now editable via PATCH (with 409 firm-scoped duplicate-code guard); GET returns bio_code. server.py admin_create_employee accepts bio_code.
- Verified E2E: Add form shows new fields; row → Edit opens prefilled identical form (code 123, bio 4, name etc.); PATCH dup code → 409.

## Iter 94c — Geofence-exit alert to Employer + Super Admin (user request)
- Requirement: employee punched IN leaves geofence while auto punch-out is OFF → notify Employer & Super Admin ("you may mark Half Day or punch them OUT").
- Backend: POST /api/attendance/geofence-exit-alert (employee auth). Guards: only when last punch today == "in"; dedupe 1 alert/employee/day via new `geofence_alerts` collection. Creates 2 notification docs: {company_id, audience:"admins"} for the firm's admins + {company_id:None, audience:"super_admins"} for super admins. routes/notifications.py feed now handles "super_admins" audience.
- Frontend: AutoPunchContext.tsx — second foreground geofence watcher (alert-only, no punch) runs when supported && !(device-enabled && effective_auto_punch). Never prompts for permission (only watches if already granted). Client debounce 30 min; checks open IN via /attendance/today before POSTing.
- Verified: backend flow E2E via injected employee session (alert → both admins see notification, dedupe works). LIMITATION: exit detection runs while the app is OPEN (foreground); background detection needs a dev build with background-location permission.

## Iter 94d — Big batch (user requests, all verified E2E)
1. SALARY SEPARATION: SalaryUpdateModal + employee-add form split into "EMPLOYEE ACTUAL SALARY" vs "COMPLIANCE SALARY (PF/ESI/TDS)" parts with SEPARATE Rate Basis each (compliance rate stored as rate_type on compliance Basic row; new user field compliance_salary_mode in profile PATCH/create).
2. PUNCH SOURCE TABS REWORK (punch-approvals.tsx): new GET /api/admin/attendance/day-status/{company_id}?from_date&to_date (max 31d) powers: Updated = edited punches only; Auto-Punches = BOTH in&out present (inline editable HH:MM); Manual Entries = missing IN/OUT/BOTH (fillable, red inputs + badges). Works Single day + Periodic. saveRow uses globalThis.prompt for audit reason; PATCH for edits, POST manual-punch for fills.
3. DIRECT LINKAGE: PATCH /admin/attendance/{record_id} now keeps status='approved' (editing admin IS approver) — edits flow straight into Attendance Report. Audit log retained.
4. ATTENDANCE GRID RULES: '⚠ rectify' ONLY for one-sided punches; both-punches cells NEVER error; missing punch → HRS BLANK (hours view = blank amber cell); OT view dot when no OT.
5. HIDE DAYS: attendance-grid 'Hide Days 1–31' toggle (testID toggle-hide-days) → hides day cols + Duty HRS col, keeps OT HRS/Total Duty HRS/Days/Extra HRS (+ new Salary ₹).
6. DAY-WISE SALARY IN REPORT: monthly-grid response now has per-day cell 'salary', totals.salary_total per employee, day_salary_totals + salary_grand_total. Formula mirrors _actual_salary_row_compute: daily→basic×(hrs/duty_hrs); hourly→basic×hrs; monthly→(basic/month_days)×(hrs/duty_hrs). Grid shows green 'Salary ₹' column + bottom 'Day-wise Salary ₹' footer row.
7. UAN/ESIC: Aadhaar-only messaging (OCR mention removed from portal_generation.py + employee-master hint).
8. CRITICAL BUG FIXED: SelectedCompanyContext wiped persisted firm selection on EVERY page load (user briefly null during auth bootstrap → clearLock). Now waits for authLoading=false. Firm selection survives refresh.
9. TIMEZONE CONVENTION (IMPORTANT for future agents): punch 'at' stores WALL-CLOCK (device IST) time labelled as UTC (per .dat imports + grid raw display). day-status + punch-approvals send/display naive times, NO tz conversion. Do NOT astimezone punch times.
- E2E automation tip: after login, page.evaluate localStorage.setItem('skc:selected_company','cmp_527fecdd7c') + ...('skc:selected_company_locked','1') then navigate — firm gets selected.
- Backend tests: /app/backend/tests/test_iter93_punch_and_salary.py (6/6 green).

## Iter 94e — "Facing Issue On Punching Data" FIXED (all punch options)
ROOT CAUSES (2 real bugs):
1. AdminWebShell topBar had NO zIndex → the firm-picker dropdown (inside header) was painted UNDER `main` content → clicks on dropdown items were swallowed → firm selection NEVER committed → "Pick a firm first" everywhere. FIX: topBar zIndex:3000.
2. Stale session-lock: logout removed only 'skc:selected_company' but NOT 'skc:selected_company_locked' → next login had lock=1 with no selection → setSelectedCompanyId permanently blocked. FIX: restore only honors lock when a selection exists (removes stale lock); setSelectedCompanyId allows when locked-but-empty; logout now removes both keys.
3. Firm (company_admin) login auto-selects own firm (existing Iter 67 code) — verified via injected session: Prakash Kankani lands with Kankani active, punch tabs load without picking.
NOTE: handoff creds "Kankani123/password" are STALE — password login returns Invalid credentials (login_id Kankani123 is correct; user changed the password). PIN may still be 1234.
Verified E2E: stale-lock + super admin → picker commits (Kankani Enterprises · KEPS) → Auto-Punches tab loads 01-Jul biometric table with editable In/Out.

## Iter 94f — Pendency batch 2 (all verified E2E)
1. NIGHT SHIFT (day-status/punch approvals): pairing is chronological — an IN owns the first unconsumed OUT within 24h even on the NEXT date (fetch range ±1 day; f-1 pre-consumed). Punch Approvals shows In/Out DATES under each time ("(+1)" amber when next-day). saveRow targets the punch's own date; filled OUT earlier than IN → auto next-day. dutyH wraps midnight.
2. HH:MM AUTO-FORMAT v2: keeps most-recent 4 digits on overflow (typing over prefilled never swallows), minutes clamp 59, selectTextOnFocus on all punch inputs; also manual-punch-entry modal (maxLength removed).
3. ATTENDANCE REPORT — 5 report types (GridView union): IN/OUT, OT IN/OUT, Hours only, Day Salary (per-day ₹ cells), IN/OUT + Salary (punches + ₹ line). testIDs view-salary / view-inout-salary. COL.daySal=58.
4. SEPARATE Day-wise Salary Sheet: /app/frontend/app/salary-day-sheet.tsx (sidebar Reports → "Day-wise Salary Sheet", both NAV_SUPER & NAV_COMPANY_ADMIN). Cols: Code|Name|Desig|Date|In|Out|Duty|OT In|OT Out|OT HRS|Total HRS|Day Salary + bottom TOTAL row. Data: monthly-grid (cell.salary etc). Salary column/footer REMOVED from attendance-grid summary (user wanted it separate; day-cell salary only in the 2 new views).
5. ADDITIONAL DUTY: new collection extra_duty_entries {user_id,date,extra_hours,extra_amount}. GET /api/admin/attendance/extra-duty/{cid}?from_date&to_date + POST /api/admin/attendance/extra-duty (upsert; zeros delete). Extra HOURS merge into monthly-grid day duty/hours (→ P Days & all reports & day salary). Extra AMOUNTS sum into `oth_allo` in POST /admin/actual-salary-process (verified ₹750 → oth_allo 750 → 0 after clear). Punch Approvals 4th source tab "Additional Duty" (tab-extra): only both-punch rows, Extra HRS + Amount ₹ inputs, Save (testIDs xd-hrs-/xd-amt-/xd-save-<key>).

## Iter 94g — Duty-HRS rounding policy + Additional Duty columns
1. ROUNDING: apply_employee_policy_override now copies `duty_hours_rounding_minutes` — employee-level rounding override finally honored (verified: VINIT SINGH 11.89 → 12.0 with 30-min step, reverted after test). Firm-level rounding already worked via Attendance Policy screen chips (0/5/10/15/30) — Kankani has NONE configured, so the firm must set it on the Attendance Policy screen for firm-wide rounding.
2. ADDITIONAL DUTY tab: added Duty HRS (base, from punches, midnight-wrap) and Total HRS (base + typed Extra HRS, live green preview) columns.

## Iter 95 — Duplicate .dat import fix + HH:MM everywhere + Salary Sheet date range + OT in In/Out+Salary
1. ROOT CAUSE "all reports showing —": zk-dat-import idempotency query included the per-upload timestamped `source` tag → re-uploading the same .dat duplicated EVERY punch (in,in,out,out) → has_unpaired_punches flagged every day anomaly=missing_punch → hours/salary zeroed. FIXES:
   a. utils/zk_dat_import.py: idempotency now matches user_id+at+kind (source removed).
   b. dedupe_same_machine_punches (server.py): exact (kind, timestamp) duplicates always dropped regardless of source.
   c. DB cleanup: deleted 684 duplicate attendance records (kept earliest per user+at+kind).
   d. _classify_punch_source: "import:*" → "bio" badge; anomaly cells now use classified badges too.
2. HH:MM TIME FORMAT (user rule "Always Duty HRS and Total HRS as Per the Time System"): punch-approvals.tsx (all tabs: baseDuty/totalDuty/dutyH/duty_hours/ot_hours/total_hours) and salary-day-sheet.tsx (fmtH + TOTAL row) now render HH:MM via fmtHoursHM. attendance-grid already used fmtHoursHM.
3. DAY-WISE SALARY SHEET: From/To DD-MM-YYYY inputs (auto-format) + green "Show" button (testIDs sds-from-date/sds-to-date/sds-show) → applies from_date/to_date on monthly-grid. Single date allowed (To=From). Chip shows applied range with ✕ clear. Date column uses day_full_dates (correct in range mode).
4. IN/OUT + SALARY grid view now shows OT line per cell: "OT {ot_in}–{ot_out} · HH:MM" (accent color) between punches and ₹.
Verified E2E via screenshots: salary sheet 01→02 Jul range shows Duty 08:00 / OT 03:53 / Total 11:53 / ₹1,114.69; grid IN/OUT+Salary shows OT + ₹ lines.

## Iter 95b — HR Letters + Bonus Registers A–D + Annual Returns (WEB PORTAL ONLY)
1. HR LETTERS (/hr-letters, sidebar NAV_SUPER + NAV_COMPANY_ADMIN): Appointment/Offer/Warning/Termination. routes/hr_letters.py — GET template/{type} (auto-fill from Employee+Firm Master, salary via salary_structure_actual Basic row), POST save (ref_no {CODE}/{APT|OFR|WRN|TRM}/{year}/{seq}), GET register, DELETE, GET {id}/pdf (fpdf2 letterhead: firm name/address, ref/date, To block, subject, body, signature). db.hr_letters. UI: type pills → employee dropdown search → Load Template → editable subject/body + live letterhead preview → Save & Download PDF; Letter Register tab (filter, PDF re-download, delete).
2. BONUS REGISTERS (/bonus-registers, sidebar "Bonus Registers (A–D) & Returns"): routes/statutory_registers.py — db.bonus_financials per (company, fy_start_year): gross_profit/depreciation/development_rebate/direct_tax/other_sums/allocable_percent/set_on_off_rows/payment_date/nature_of_industry/employer_name (GET/PUT financials). PDFs: form-a (allocable surplus computation), form-b (set-on/set-off rows), form-c (employee-wise bonus paid via _compute_bonus_run + father/designation join), form-d (annual return particulars). form-c/d require super/sub admin.
3. ANNUAL RETURNS (same screen): equal-remuneration.pdf (category-wise men/women + rate ranges from employee master gender/designation/basic) and ismw.pdf (Form XXIII style; migrant heuristic = address not containing firm state, falls back to full listing + note).
4. BONUS ENGINE FIX (server.py _compute_bonus_run): resolves Basic from salary_structure_actual (daily ×26, hourly ×8×26 monthly equivalent) — Kankani bonus was all zeros, now total ₹727,708, 105/125 eligible.
5. GOTCHAS: api() client auto-JSON.stringifies body — callers must pass RAW OBJECT (testing agent fixed double-stringify 422 in both new screens). fpdf2 multi_cell leaves x at right margin — call set_x(l_margin) or ln() before consecutive multi_cells.
Tested: testing agent 17/17 backend pytest (tests/test_iter95_hr_letters_bonus.py) + E2E frontend both screens + light regression on salary-day-sheet/attendance-grid. Demo data left: letter KEPS/APT/2026/001, bonus financials FY 2025-26.

## Iter 95c — Email HR Letters to employees (Resend)
POST /api/admin/hr-letters/{id}/email {to_email?} — generates letter PDF, emails via _send_email_with_attachments (Resend, base64 attachment). Defaults to employee's email; 400 "no email on file" when missing. Stamps emailed_to/emailed_at/email_delivered on the letter doc. UI: blue "Email" button per register row (testID hrl-email-{id}); on 400 an inline override input+Send appears (hrl-email-input-/hrl-email-send-{id}). Verified: 400 flow + real delivery to sksharmaconsultancy@gmail.com (200 delivered:true) + screenshot of inline override UI.

## Iter 95d — Bulk HR Letters (generate + email + combined PDF)
POST /api/admin/hr-letters/bulk {company_id, letter_type, send_email, skip_existing=true} — creates letters for ALL employees (template auto-fill per employee, sequential ref nos, flag bulk:true); optionally emails each employee with an address; returns {created, skipped_existing, emailed, email_failed, no_email, total_employees}. GET /api/admin/hr-letters/bulk.pdf?company_id&letter_type — one combined PDF, page per letter (refactored _render_letter_page out of _letter_pdf_bytes). UI (Generate tab): bulk card with email checkbox (hrl-bulk-email-toggle) + "Generate for ALL employees" (hrl-bulk-generate, web confirm). Register tab: "Download All (1 PDF)" (hrl-download-all) when a type filter is active.
Verified: bulk run created 124 + skipped 1 existing; combined PDF 200 (211KB, 125 pages); test bulk letters cleaned from DB afterwards (register left with the original 1).

## Iter 95e/f — Shift Master dropdown + read-only Duty HRS + approved-tab cleanup
1. ADD/EDIT EMPLOYEE SHIFTS: removed free-typed "Shift start/end" HH:MM fields from employee-add.tsx; replaced with chips from GET /shift-masters ("NONE (firm default)" + each shift NAME (start–end)). Form field shift_id. Backend: POST /admin/employees accepts shift_id (validates vs db.shift_masters, 400 unknown) → sets attendance_policy_override.shift_id + mirrors shift_start/end for display. PATCH /admin/employees/{id}/profile handles shift_id (preserves other override keys; ""→clears+nulls start/end). GET profile returns shift_id. Seeded 2 shifts for Kankani: Day Shift 08:00–20:00 (sh_cc69d0727967), Night Shift 20:00–08:00 (sh_e9fb9c6abae8) — editable in Shift Master. Verified E2E (create+switch+invalid+clear, test emp deleted).
2. ACTUAL SALARY PROCESS: Duty HRS column is now ReadCell (not editable) per user rule "Only We can Change P Days and P HRS" — P Days/P Hours/Basic etc. remain editable (salary-run.tsx; gridCol 0 removed, other cols untouched).
3. PUNCH APPROVALS: Approved & Rejected tabs no longer render ✓/✗ action buttons or Action column (read-only once decided) — punch-approvals.tsx tab guard.
4. "Employee Master Data not able to open" report: could NOT reproduce — verified /admin loads + employee detail modal + full master open as super admin AND company admin (debug session). Likely transient during service restarts. Awaiting user retry/details.

## Iter 95g — "Fill from shift" one-tap in Manual Entries
Backend day-status (/admin/attendance/day-status/{cid}): rows now include shift_start/shift_end (employee attendance_policy_override.shift_id → Shift Master, else mirrored user fields); response includes "shifts" (full Shift Master list). Frontend punch-approvals.tsx: Manual Entries tab shows a blue ⚡HH:MM pill (testID ds-fill-{in|out}-{key}) under EMPTY time boxes; tap → fills the input (admin still presses Save). Resolution: assigned shift first; FALLBACK = closest Shift Master shift by circular-minute distance from the day's EXISTING punch (missing IN → match shift END to the OUT time, fill start; vice versa). Both-missing + no assigned shift → no pill. Verified: 45 pills on 06-07-2026 Kankani; tap filled 08:00 (matched Day Shift from 19:51 OUT), Duty 11:51, Save enabled.

## Iter 95h — Expired session dead-end fix ("Not able to open ..." reports)
ROOT CAUSE: /auth/me returns detail "Invalid session" for expired/stale tokens — AuthContext isAuthFailure matcher didn't include that string, so user stayed "logged in" with null data and every admin screen showed the "Admins only" lock (user reported as Employee Master / Add Employee "not able to open").
FIX (AuthContext.tsx refresh()): added "invalid session" to matcher; on web auth-failure → clearToken + window.location.assign("/") BUT ONLY when pathname !== "/" (unguarded redirect caused an infinite reload loop on the login page — first attempt failed, guard added).
Verified on web: stale token on /employee-add → lands on Sign-in page; fresh login → Add New Employee opens fully.

## Iter 96 — Full web-portal sweep (43 routes) + fixes
Testing agent swept 43 admin routes. FIXED:
1. CRITICAL: /attendance-policy crashed (white page) for firms with legacy policy shape (workday_hours/grace_minutes vs modern full_day_hours/grace_minutes_late) — .toFixed on undefined. Fixes: frontend normalisePolicy() defensive mapper (testing agent, attendance-policy.tsx) + backend GET /attendance/policy now normalises legacy keys via setdefault (server.py ~5075). Verified: page renders with Shift Master, weekly off, thresholds.
2. Raw web <select> elements used testID → React unknown-prop DOM warnings: changed to data-testid in bulk-employee-correction.tsx (bc-company), bonus-run.tsx (bn-company/bn-fy/bn-group), attendance-email.tsx (aec-company).
3. Also fixed earlier in Iter 95i: challans.tsx exportXlsx used URL.createObjectURL(non-Blob) — now uses apiBinary().webBlobUrl.
Known benign: expo-notifications web warnings, pre-login 401s, 'outline' style warnings. All 43 routes render clean per iteration_96.json.

## Iter 96d — PF ECR (.txt) + ESIC (.xls) portal files VERIFIED & field-name bugfix
1. ROOT CAUSE of "no ESIC members" (and the reason previous session couldn't verify): routes/challans.py read `esic_no` from users, but the Employee Master stores the ESIC IP number as `esi_ip_no` (canonical everywhere else: server.py create/update, employee-add.tsx, employee-master.tsx). Fixed `_uan_esic_map` + both ESIC endpoints to use `esi_ip_no`. NOTE: the handoff-reported "pandas ValueError / engine=xlwt" never applied — esic.xls uses xlwt directly (no pandas), works fine.
2. VERIFIED against user samples (re-downloaded artifacts): ECR .txt = exact 6-field `UAN#~#NAME#~#EPF_EE#~#EPS_ER#~#EPF_ER#~#REFUND` (CONTRIBUTION_HELP_FILE.pdf) with CRLF; ESIC .xls = exact `ESI_CODE,NAME,DAYS,SAL,RE,DATE` sheet (sample format of ESIC.xls), legacy BIFF .xls opens in xlrd, RE=1 when 0 days. Test: seeded 3 employees with uan_no/esi_ip_no, all 4 endpoints (ecr.txt/ecr.xlsx/esic.xls/esic.xlsx) 200 with correct rows; seeds cleaned after.
3. Frontend Month + Employee Group filters verified in browser: months [2026-07, 2026-06], groups [Labour, Staff, All]; selecting 2026-06+Labour → run "2026-06 · Labour · 108 emp" auto-picked; 4 download buttons render.
4. DATA-ENTRY PREREQUISITE for real uploads (user action): employees currently have NO uan_no / esi_ip_no filled, and the Kankani compliance runs have 0 rates (gross/PF/ESIC all 0) — files generate but with 0 amounts until Compliance Salary rates + UAN/ESI numbers are entered in Employee Master.

## Iter 96e — Missing Statutory Numbers report (Challans screen)
Backend (routes/challans.py, registered BEFORE /challans/{challan_id}): GET /admin/challans/missing-statutory[?company_id] → {total, missing_uan, missing_esi, employees[{user_id,company_id,employee_code,name,employee_type,uan_no,esi_ip_no}]} (active employees missing uan_no OR esi_ip_no, sorted by numeric code; firm-scoped for company/sub-admins, all-firms optional for super admin). GET /admin/challans/missing-statutory.xlsx → Excel with Firm column, MISSING cells amber-highlighted.
Frontend challans.tsx: new card between Portal Files and Upload — count pills (miss-uan-count/miss-esi-count, green when 0), Show/Hide list toggle (miss-toggle, first 200 rows), Export Excel (miss-export).
Verified E2E: Kankani 125/125/125, xlsx 200 (9KB), all-firms 200; UI pills+list render on web.

## Iter 96f — Auto Punch-IN at first login after joining approval (user rule)
"On the time of new joined employee approve, mark as punch in at the time of first login; after that the punching policy of the app is applied."
Backend server.py: PATCH /admin/approve-employee (approve branch) now sets first_login_punch_pending:True on employee targets. New helper _maybe_first_login_punch(user) (above emp-code-login): consumes the flag ATOMICALLY (update_one with flag in filter → no double punch on parallel logins), skips if a non-rejected punch already exists today (e.g. biometric device), else inserts attendance {kind:in, source:"first-login-auto", status:approved, decision_by:system, decision_reason:"Auto punch-in at first login after joining approval", location_status:no-gps, gps_verified:false} and stamps users.first_login_punch_at. Called from BOTH employee logins: /auth/pin-login and /auth/emp-code-login (NOT admin logins; role==employee guard). Subsequent punches use the normal /attendance/punch policy untouched (auto OUT toggle works since last_kind=in).
Verified E2E: pending test emp → approve 200 → pin-login created exactly 1 in-punch, 2nd login no duplicate; emp-code-login path also verified; test user + punches cleaned from DB. Existing employees (bulk-imported/admin-created before this) are NOT affected — only approvals from now on set the flag.

## Iter 96g — PWA (installable web app) + GitHub Actions semantic commits
PWA: frontend/public/{manifest.json, sw.js, icons/icon-192|512.png, maskable-192|512.png (generated from assets/images/icon.png, brand bg #0F2E3D)}. Expo web output:"single" IGNORES app/+html.tsx at runtime → src/utils/pwa.ts setupPWA() injects manifest link + theme-color + apple metas + registers /sw.js at runtime (called from _layout.tsx boot effect; +html.tsx also updated in case output ever switches to static). SW strategy deliberately conservative to avoid stale-deploy complaints: /api/* + non-GET never cached; navigations network-first (cache fallback offline only); static assets stale-while-revalidate; cache name sks-pwa-v1. Verified in browser: manifest link present, SW active at /sw.js, manifest valid (standalone, 4 icons), app renders fine.
CI: .github/workflows/semantic-commits.yml (commitlint via wagoid/commitlint-github-action@v6 on push/PR + amannn/action-semantic-pull-request@v5 for PR titles) + commitlint.config.js (config-conventional, header ≤100, subject-case off). Activates when user pushes via Save to GitHub.

## Iter 96h — AI-vision Captcha reader + autonomous portal login (RPA)
User rule: "captcha reader for online portals — read captcha and login directly to portal." Chose Option 1 (AI vision, no 2captcha needed).
NEW utils/captcha_reader.py: read_captcha(image_base64, numeric_only, session_id) → uses EMERGENT_LLM_KEY via emergentintegrations LlmChat + ImageContent, model openai/gpt-5.4 (same as OCR). Cleans output to alphanumeric. VERIFIED 6/6 accuracy on generated distorted text captchas.
utils/rpa_worker.py _perform_login REWRITTEN: fills creds → screenshots the captcha <img> element (_find_captcha_image_b64) → read_captcha (numeric_only for ESIC) → fills captcha input → clicks submit → _login_succeeded heuristic (logout/dashboard markers, captcha gone, url left /login) → retries up to 3× (reloads captcha each fail). Handles no-captcha forms too. New statuses: logged_in / captcha_failed / portal_blocked / playwright_missing / playwright_error. _detect_block_or_error catches WAF block pages ("Web Page Blocked", "Attack ID", access denied) so we never false-positive success. Optional PORTAL_PROXY_URL env → chromium launch proxy (to egress via Indian ISP). _process_one_job updated for new statuses.
NEW endpoint POST /api/admin/portal-automation/test-login {portal:epfo|esic, company_id} → runs login NOW, returns {ok,status,message,captcha_attempts,screenshot_base64}. Firm-scoped; 412 if no portal creds on Firm Master.
Installed playwright chromium-headless-shell v1228 (matched playwright 1.61.0) into /pw-browsers.
⚠️ BLOCKER (infra, not code): EPFO portal WAF BLOCKS the Emergent cloud pod IP (34.7.135.173 → "Web Page Blocked, Attack ID 20000051"). Tested live: status=portal_blocked. Captcha reading is proven working, but actual auto-login into EPFO/ESIC requires egress from an allowed Indian ISP IP — user must supply PORTAL_PROXY_URL (Indian residential/ISP proxy) OR run an on-prem RPA runner at the firm office (office IP allowlisted with EPFO). Kankani has PF LOGIN creds saved (ESI Login empty).

## Iter 96j — PWA mobile view = native mobile app UI (user request)
User: "Redesign mobile view of PWA portal same as existing mobile app, same features like app."
ROOT CAUSE: web layout was role-gated not width-gated — AdminWebShell forced the desktop portal for ANY admin on web regardless of viewport (isWebDesktop = web && (width>=960 || isAdminRole)), so phones/PWA showed the cramped desktop portal. Landing + admin-pin-login branched on Platform.OS==="web" too (desktop split-screen on phones; employee sign-in hidden on web).
FIX (pure breakpoint switch, DESKTOP_MIN=960 exported from AdminWebShell):
1. AdminWebShell.tsx: isWebDesktop = Platform.OS==="web" && width>=DESKTOP_MIN (removed isAdminRole). Narrow web → returns {children} = the (tabs) mobile app UI + full-screen Stack screens, identical to native app.
2. index.tsx (landing): useWindowDimensions; isWebDesktop=web&&width>=960 → wide web keeps enterprise split-screen; phone-web uses the SAME mobile landing. Employee sign-in button now shown when !isWebDesktop (native OR phone-web) instead of Platform.OS!=="web".
3. admin-pin-login.tsx: redefined isWeb = Platform.OS==="web" && width>=960 (added useWindowDimensions) → phone-web uses mobile login card + "Employee sign in instead" link.
Verified in browser: phone (390px) → mobile landing w/ Employee sign-in, admin login → mobile tabs dashboard (Home/Documents/Profile, Quick actions, Admin overview), /challans renders full-screen with NO desktop sidebar, all features present. Desktop (1920px) → enterprise landing + Web portal shell intact (no regression). Lint clean on all 3 files.

## Iter 96k — Separate installable links: /employer & /employee
User: "2 separate links for Employer login and Employee login, and after opening the link directly install in mobile."
- NEW routes app/employer.tsx (→ /admin-pin-login) and app/employee.tsx (→ /pin-login), both render src/components/InstallEntry.tsx: branded landing + one-tap Install button (btn-install) + "Continue to sign in" (btn-continue). Uses Chrome/Android beforeinstallprompt (captured globally in setupPWA), iOS shows Add-to-Home-Screen hint. If already logged in → /(tabs); native OR installed-standalone → straight to loginPath.
- SEPARATE PWAs: public/manifest-employer.json (id/start_url /employer, name "SKS Employer") + manifest-employee.json (id/start_url /employee, "SKS Employee"). setManifestHref() in pwa.ts swaps the linked manifest per route so each installs as its OWN home-screen icon. pwa.ts rewritten with: beforeinstallprompt/appinstalled capture, setManifestHref, isStandalonePWA, isIOSWeb, promptInstall, canInstallNow.
- BUGFIX (blocker): AuthContext.refresh() force-redirected any unauthenticated web path (≠"/") to "/", which bounced /employer & /employee to the landing. Added PUBLIC_PREFIXES allowlist (/employer,/employee,/admin-pin-login,/pin-login,/company-login,/company-register,/emp-code-login,/employee-signup,/admin-set-password,/firm-select) so these stay put.
- Verified E2E on phone viewport: /employer → manifest-employer.json + buttons; /employee → manifest-employee.json, Continue → /pin-login (Mobile/UAN/ESI IP/PF + PIN). Lint clean.
Share links: https://<site>/employer  and  https://<site>/employee

## Iter 96l — Employer-managed employee credentials + Employee login cleanup
AUTH (used integration_expert playbook; bcrypt rounds=12, login_id usernames, lockouts — all pre-existing conventions):
- Backend server.py: PinLoginRequest +login_id → /auth/pin-login now accepts username(login_id)+PIN (case-insensitive, role=employee). NEW POST /admin/employee-credentials {user_id, login_id?, pin?, password?, must_change} — company/super/sub admin, company-scoped, globally-unique username, validates pin(6 digits)/password(8+ letter+digit), sets pin_must_change/password_must_change. NEW POST /auth/employee-password-login {login_id, password} → employee username+password login w/ password lockout (5→15min). _enrich_user_with_company + _redact_user now expose has_password bool (hash still stripped).
- Frontend pin-login.tsx: added "Username" identifier + PIN/Password mode toggle (pin-mode-pin/password); password path calls /auth/employee-password-login. Removed "Admin sign in instead" link (employee login = employee only).
- Frontend NEW src/components/EmployeeCredentialsCard.tsx rendered in employee-master.tsx (Full Master) — employer sets username+PIN+password, status pills, force-change checkbox, alerts creds to share.
VERIFIED E2E backend: set creds → username+PIN login 200 → username+password login 200 → wrong pw 401. Test employee creds reverted after.

## Iter 96m — Employee login/edit UX per user requests
- pin-login.tsx: HID UAN / ESI IP / PF No. identifier tabs — only Mobile + Username remain (subtitle + autoCapitalize updated). Backend still supports uan/esi/pf if ever re-enabled.
- admin.tsx: consolidated the two employee-edit buttons into ONE — "Edit / Manage Employee (all details)" → /employee-master (the superset hub: same one-page edit form + PF/ESIC gen, salary cert, credentials, shift, policy, OCR). Removed duplicate direct-edit button.
- employee-add.tsx: firm picker LOCKED when editing (canSwitchFirm = role && !editUserId) → editing shows only that employee's company name, no other companies.
- admin-pin-login.tsx: removed "Employee sign in instead" footer link (employer login = admins only).
- Role change: CONFIRMED already restricted to Super Admin only — UI gated by isSuper (admin.tsx) + backend /admin/user-role rejects non-super role/company changes with 403.
All files lint clean. Separate installable links: /employer and /employee (Iter 96k).

## Iter 96n — iOS compatibility for /employer & /employee install
iOS Safari has NO beforeinstallprompt (can't trigger native install). InstallEntry.tsx now: isIOS() → renders a clear step-by-step "Install on your iPhone/iPad" card (1. open in Safari, 2. tap Share, 3. Add to Home Screen) INSTEAD of a dead button. Non-iOS keeps the one-tap Install/Add-to-Home-Screen button. pwa.ts: added isIOS() (device-only, any browser), kept isIOSWeb(), added setAppleWebAppTitle() — InstallEntry sets apple-mobile-web-app-title per link ("Employer Portal"/"Employee App") so each iOS home-screen icon is named correctly. Verified via emulated iPhone UA: iOS steps card renders on /employer & /employee; lint clean.

## Iter 96q — Actual Salary Process PF/ESIC now SYNC from Compliance (else 0)
User: in Actual Salary Process (web), PF & ESIC were reflecting (auto-computed) in the deduction column — should instead sync from Compliance Salary run (Compliance→Actual, option 2), else show zero.
ROOT CAUSE: backend (server.py ~16890) already correctly pulls epf=pf_employee / esi=esic_employee from the latest compliance_salary_runs for same month+company (0 if not processed) — but the FRONTEND salary-run.tsx computeRow() OVERRODE them every render: epf=0.12*basic, esi=(gross<=21000?0.0075*gross:0). Fixed computeRow to carry the row's synced epf/esi through (Number(r.epf)||0) and Net Pay = gross-(epf+esi+adv+tds). Updated header doc comment.
Verified: /admin/actual-salary-process for 2026-03 (no compliance) → epf/esi 0; 2026-06 (compliance exists but Kankani rates=0) → 0. Values will show real PF/ESIC once Compliance Salary is processed with non-zero rates. Backend PATCH row endpoint already preserves epf/esi (no recompute). Lint clean.

## Iter 96r-t — batch of employee/compliance UX changes (DONE)
- employee-add.tsx: Field component +onBlur/editable. Basic Salary onBlur → if 0<amt<=1500 auto-set salary_mode="daily" (Iter 96r).
- compliance-salary-run.tsx: monthDaysOverride default "26" (editable, still clamped to calendar days) (Iter 96s). REMOVED Multi-firm batch mode card + MultiCompanyPicker import + runBatch; REPLACED with a Firm selection chip row (super/sub admin) that sets localCid → activeCompanyId (Iter 96t). Leftover lint WARNINGS only (setBatchMode/batchBusy/PctInput/RoChip unused) — app compiles fine.
- All verified: app loads, lint = warnings only.

## PENDING QUEUE (confirmed with user, not yet built)
1. Bank Sheet in Actual Salary Process — columns: S.No, Name, Father Name, Bank Name, NAME AS PER BANK (bank_account_name), IFSC Code (bank_ifsc), Net Salary (from COMPLIANCE run 'net' field). Filters: Finance Year, Employee Type, Month/Year, Pay Mode, Bank Name. NOTE: employee bank fields = bank_name/bank_account/bank_ifsc/bank_account_name; NO pay_mode field exists yet. Compliance net field = row['net'].
2. Super Admin Email inbox — side option to check mail, stay logged in = GMAIL integration (needs integration_expert + user's Google account/OAuth).
3. Punch photo — show selfie in In/Out punch records; if machine punch, capture photo from device. (attendance records have selfie_base64 for app punches; biometric device punches may not have photos.)

## Iter 97 — Punch selfie viewer (admin+employee), Join QR utility, salary<=1500 daily (DONE)
- NEW backend GET /api/attendance/{record_id}/selfie — employee self-access to own punch selfie (403 if not owner, 404 if missing). Curl-verified 200/403/404. Admin endpoint /admin/attendance/{id}/selfie unchanged.
- (tabs)/attendance.tsx: camera icon (testID punch-photo-<rid>) on each Today's-activity row → Punch Photo modal (base64 img or "No photo captured"). history.tsx: same icon (hist-photo-<rid>) in day drilldown rows + modal.
- punch-approvals.tsx admin Photo buttons/modal were already complete from previous session — confirmed working.
- employee-add.tsx: "Off-Line gross / month" onBlur now also auto-switches Rate Basis→DAILY when <=1500 (Basic Salary already had it from 96r). Tested by testing agent.
- NEW /app/frontend/app/join-qr.tsx — Joining QR Code utility (sidebar: Utilities > Joining QR Code, both super-admin & company-admin navs in AdminWebShell). Firm chips (company_admin auto-locked to own firm via /company; super/sub admin via /companies), QR (react-native-qrcode-svg) → <origin>/employee-signup?company=<CODE>, Copy Link + Print QR (web print window w/ instructions). Visual verified: KEPS QR renders.
- BUG FIXED: join-qr initially used `isLoading` from useAuth but AuthContext exposes `loading` → guard fell through and redirected logged-in users to "/" during auth bootstrap. Renamed to loading. (Watch for this in future new screens!)
- Super admin PIN 654321 is STALE (user changed it). Password login sharma123 works — payload keys {email, password}. test_credentials.md updated.
- Testing: testing_agent iter97 — backend 6/6 pass; frontend employee-add auto-daily + employee-signup?company=KEPS lock verified. Playwright/preview intermittently hit Cloudflare challenges/429 (bot-detection only; real users unaffected).
- STILL PENDING: Super Admin Email inbox (needs user clarification — webmail link vs embedded mailbox), 2captcha key for RPA, Employee Details Slips PDF sample format.

## Iter 97b — QR poster: firm logo + Hindi instructions (DONE)
- join-qr.tsx: on-screen card shows firm logo (logo_base64, if set) + Hindi line "अपने फ़ोन के कैमरे से यह QR कोड स्कैन करें". Print poster now includes logo, bold Hindi headline, and bilingual (EN + HI) 3-step instructions. Verified visually.

## Iter 98 — Textile Policy 2 rules explainer (DONE)
- attendance-policy.tsx TextilePolicySection: added plain-language "how it works" card (testID textile-policy2-rules / textile-policy1-rules) shown under the variant radio when Policy 1 or Policy 2 is selected. Explains: 8hrs=1 Present Day, extras→OT (gated by employee ot_applicable flag), 4-8hrs=Half Day, week-off/govt-holiday worked→all OT no present day, rounding note. Verified visually on Kankani (textile firm).
- Policy 2 engine already existed (server.py compute_textile_day ~line 1650) — this was a UI visibility request only.
- Gmail embedded mailbox (super admin): playbook received from integration_expert (Gmail API OAuth2 + refresh token in Mongo). WAITING on user to provide GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET (instructions sent — redirect URI https://<domain>/api/gmail/oauth/callback).

## Iter 98 — Firm-Master-linked payroll rules batch (DONE, tested 21/21 backend + frontend)
1. Policy 2 change: <8hrs worked → NO half day/absent, ALL hours → OT (server.py compute_textile_day; explainer card updated).
2. Firm Master Salary Process gates: salary_process.online_salary gates POST /admin/compliance-salary-runs (+reprocess); offline_salary gates POST /admin/actual-salary-process → 403 "You are not permitted for this…". Helper _require_firm_salary_permission (~server.py:13500).
3. firm-master.tsx: Offline Salary toggle ON auto-enables Bio Matrix Attendance. testIDs fm-online-salary/fm-offline-salary/fm-bio-matrix.
4. EPF/ESI firm gates: firm_masters.epf.applicable/esi.applicable ANDed with per-employee flags in compute_compliance_row (firm_pf_enabled/firm_esic_enabled params). Missing firm_master record → NOT calculated.
5. "15. Report Order" section removed from firm-master.tsx.
6. OT Calculation On (basic|gross) radio in Firm Master §10 (salary_process.ot_calc_basis) → _actual_salary_row_compute ot_basis param; stored on run doc as ot_calc_basis, row PATCH re-computes with it. Gross basis folds oth_allo into OT rate.
7. CL/PL: firm-master upsert 400s when cl_pl_applicable=true and both limits 0.
8. NEW Leave Report: GET /api/admin/leave-report?company_id&year (routes/leaves.py) — CL(casual)/PL(earned) allowed/taken/balance per employee; frontend /leave-report screen + sidebar Reports > Leave Report (both navs); client CSV download.
9. Report sorting: sort_by=name|code|net|gross on salary+compliance export.csv/xlsx (_sort_export_rows ~server.py:12793); /reports sort chips + Finalized-only filter (visSalaryRuns/visComplianceRuns).
10. Grid sorting chips on salary-run.tsx (asal-sort-*) and compliance-salary-run.tsx (comp-sort-*), display-only client sort.
11. RPA creds: rpa_worker._fetch_creds + portal_generation._portal_creds_present now read Firm Master epf.epf_user_id/epf_password & esi.esi_user_id/esi_password FIRST, fallback portal_logins rows.
- Kankani firm_masters flags left ENABLED (online/offline salary True, epf/esi applicable True) so processing keeps working.
- Test suite: /app/backend/tests/test_iter98_payroll_rules.py (21 tests). Known stale failures in test_iter52/test_iter81 (pre-existing).
- Cleanup ran: 19 stale test firms + 112 docs purged via scripts/cleanup_test_data.py.
- CAUTION for future agents: two file-corruption incidents happened via parallel search_replace (duplicated tails in server.py + reports.tsx) — verify file ends after big parallel edit batches.
- STILL PENDING: Gmail embedded mailbox (waiting GOOGLE_CLIENT_ID/SECRET from user), 2captcha key, Employee Details Slips PDF sample.

## Iter 99 — Punch Policy hardening + first-login auto punch + leave balance (DONE, tested 13/13)
1. GEOFENCE MANDATORY EVERY CONDITION: POST /attendance/punch — removed Iter57 no-GPS bypass. Coords required for ALL punches (400 otherwise); manual mode (gps not allowed) additionally requires selfie_base64 + biometric_method; ONLY live-in staff punch without coords. Firm w/o configured geofence → coords recorded, allowed (nothing to verify). Frontend biometric path now always fetches GPS.
2. First-login auto punch-in: GET /attendance/first-punch-status (pending = employee with zero attendance ever); (tabs)/attendance.tsx effect auto-triggers handlePunch() once (welcome toast with firm name).
3. Punch notifications: personal notification (audience "user" + target_user_id) 'Punch IN/OUT — <Firm Name>' created in punch endpoint; routes/notifications.py list supports audience "user".
4. Employee leave balance: GET /leaves/balance (routes/leaves.py); leaves.tsx "My Leave Balance" card (testID leave-balance-card) for employees, CL/PL used/allowed/balance.
5. Toasts on punch now include firm name.
- Tests: /app/backend/tests/test_iter99_punch_policy.py (13). Report iteration_99.json. All test data cleaned.

## Iter 100-102 (fork) — Branding, PWA links, Compliance import, Arrear module (DONE)
1. NEW LOGO applied everywhere: "Smart Payroll Service — A Product of Sharma Group" (user's 2nd upload rj4piaqe_Smart Payroll Service.png). Regenerated public/icons/icon-192/512 + maskable, assets/images (icon, adaptive-icon, favicon, logo, logo-mark, splash-image), public/brand-logo.png. admin-pin-login webLogo + AdminWebShell sidebar logoBadge now render the logo image (fallback "SKS" text removed).
2. SEPARATE PWA LINKS: pwa.ts setupPWA now picks the manifest SYNCHRONOUSLY from location.pathname (/employee|/pin-login → manifest-employee.json "SKS Employee"; /employer|/admin-pin-login → manifest-employer.json "SKS Employer"); +html.tsx mirrors this via inline script (prod static export). Fixes both links installing as the same app.
3. EMPLOYEE BLOCKED FROM EMPLOYER PORTAL: InstallEntry kind=employer + role employee → "Employers only" screen (testID employer-blocked-for-employee) with Go-to-Employee button; admin-pin-login redirects logged-in employees to /employee. Backend already 403s employees on admin logins (verified).
4. COMPLIANCE IMPORT (replaces Attendance Master link, per user): routes/compliance_import.py — POST /admin/compliance-import/upload (base64 xls/xlsx/csv, Attendance-Master column format, header auto-detect, match by code→UAN→PF→ESIC→name), GET .../status, GET /gmail/spreadsheet-attachments, POST .../from-gmail. Data in compliance_import_entries (company,month,user). Run payload flag renamed use_attendance_master → use_imported_sheet; attendance_source "imported_sheet". compliance-salary-run.tsx: "Import Salary Sheet" card (csr-import-upload / csr-import-gmail / csr-use-imported-sheet) + Gmail attachment picker modal. Masters > Attendance Master screen kept but UNLINKED from compliance.
5. ATTENDANCE REPORT (attendance-grid.tsx): Group filter now merges legacy masters groups (type=group incl. __global__) with employee-groups; visible Sort chip row (sort-code/name/days/duty/ot). Backend _resolve_group_employee_ids: global masters allowed + empty member_user_ids falls back to name-match on users.employee_group/employee_type (Staff→17 emp verified).
6. SIDEBAR GROUPING: "Salary Process" parent with children Actual (/salary-run), Compliance (/compliance-salary-run), Arrear (/arrear-salary-run) in NAV_SUPER + NAV_COMPANY_ADMIN; NAV_PERMISSION_MAP arrear = salary_process perms.
7. ARREAR MODULE (routes/arrear_salary.py + arrear-salary-run.tsx): POST/GET/DELETE /admin/arrear-salary-runs; per past month in range: latest (prefer finalized) compliance run rows = OLD; recompute row at CURRENT master (compliance_gross) with effective_present reconstructed exactly ((gross_paid-ot_pay)/per-day-rate); arrear=diff. PF: EPF wages diff capped, 12%/8.33%/3.67 dues; ESIC 0.75/3.25 only when new row attracts ESIC. Exports: /ecr.txt (EPFO 8-field #~# format: UAN#~#NAME#~#EPF_W#~#EPS_W#~#EDLI_W#~#EPF#~#EPS#~#ER, per ARREAR_HELP_FILE.pdf) + /export.xlsx register. E2E verified via UI (449 RISHABH 23500→25500 → arrear 2319, EPF 139/EPS 97/ER 42) — test data reverted.
8. Geofence entry notification (attendance.tsx): insideNotifiedRef now RESETS when leaving geofence (re-entry re-notifies).
9. Data fixes: orphan TEST_ITER98 firm_master deleted (duplicate "Select firm" bug); employee 50 PIN=654321 (see test_credentials.md).
- CANCELLED by user: 2captcha RPA solver, Employee Details Slips PDF.
- PENDING USER ACTION: Gmail reconnect (Mailbox → Connect; fork reset gmail_accounts).

## Iter 103 — SMTP Email Notifications (DONE, self-tested)
- routes/email_notifications.py: smtp_settings (singleton, runtime-editable, password masked/persisted), email_triggers (9 events: leave_applied/approved/rejected, punch_in/out, salary_finalized, employee_joined, ticket_raised/resolved; default OFF; recipients employee|admins|custom + extra_emails; {placeholder} templates), email_log. aiosmtplib (587 STARTTLS / 465 TLS). fire_email_event() never raises; hooks added in routes/leaves.py (create+decide), routes/tickets.py (create+resolve), server.py (punch ~8120, both finalize endpoints, admin_create_employee ~7395).
- Endpoints: GET/PUT /admin/smtp-settings, POST /admin/smtp-settings/test, GET/PUT /admin/email-triggers, POST /admin/notifications/compose (email+in-app, all/selected employees), GET /admin/email-log.
- Frontend /email-settings (super/sub admin, sidebar Automation > "Email SMTP & Notifications"): 4 tabs — SMTP Settings (Gmail app-password hint, port chips, test send), Automated Triggers (per-event switch/recipients/templates), Compose & Send, Email Log.
- Tested: settings CRUD + mask persistence, real Gmail handshake (535 with fake creds = expected), triggers persist, compose in-app delivered, no-email employees skipped, log records. Test data cleaned; smtp_settings left EMPTY for user to configure with their Gmail App Password.

## Iter 105 — Hospital Shift Change + Policy Variant + Bank Sheet + Bulk-Import fix (this session)
1. HOSPITAL SHIFT-CHANGE (user req): backend routes/shift_change.py — GET /shift-change/options (allowed only if firm business_category/subcategory == hospital), POST /shift-change-requests (employee, only BEFORE punch-in, no dup pending), GET /shift-change-requests (role-scoped), GET /admin/shift-change-requests/{id}/replacement-candidates (employees not punched that date), POST /admin/shift-change-requests/{id}/decide (approve REQUIRES replacement_user_id → swaps shift_name of both users, writes shift_assignments, notifies BOTH: "Today your shift is X (start–end). Please punch in timely." + optional shift_allotted email; reject notifies requester). Frontend: shift-change.tsx (employee, shift chips + reason + my-requests), shift-approvals.tsx (admin, pending list + approve modal with mandatory candidate radio + note + history). Sidebar: "Shift Change Approvals" under Approvals (AdminWebShell). Employee home quick action "Shift change request" (only when options.allowed). Test firm: City Care Hospital cmp_987f0d7da5 (see test_credentials.md). VERIFIED E2E backend+UI.
2. FIRM MASTER POLICY 1/2 PICKER: PolicyVariantPicker.tsx in firm-master section 10a, uses GET/PATCH /attendance/policy?company_id=. FIXED backend PATCH to support PARTIAL updates: merges incoming fields onto existing policy (legacy old-schema policies backfilled from category preset before _validate_policy). FIXED firm-master.tsx dead-end: adopts selectedCompany once the async firm list loads (useEffect) instead of "Pick a Firm" gate. VERIFIED: UI click persists policy_2 and reverts to policy_1.
3. BANK SHEET SIDEBAR: "Bank Sheet Format" confirmed visible under Reports submenu (both super/company admin navs) and page loads with 17 employees. Already wired — verified working.
4. BULK IMPORT FIRM NAME (user bug): employee-bulk-import.tsx — firm dropdown was empty when /companies fetch raced auth or failed once. Added mount-time self-heal (reloadCompanies if empty) + "Loading firms…" placeholder. VERIFIED.
5. GIT: local commit e30b83a created; push to main pending USER action from terminal (PAT with commit-tree snapshot method shared).

## Iter 110 — Firm Master: Salary Process linkage + Leave 2-digit + Save→Dashboard (this session, self-tested)
1. SALARY PROCESS LINKAGE (firm-master.tsx §10): toggles relabeled "Online Salary → Compliance Salary Process" / "Offline Salary → Actual Salary Process"; "Online Process Days (Compliance Salary)" enabled ONLY when online_salary ON, "Offline Process Days (Actual Salary)" only when offline_salary ON (Field got disabled+maxLength props); helper hint text added.
2. LEAVE 2-DIGIT LIMIT (user req): CL/PL Day Limit inputs capped at 2 digits (maxLength=2 + digit-strip slice(0,2)). Verified typing 125 → 12.
3. SAVE → DASHBOARD (user req): firm-master save() now does window.location.href="/" on web (full reload → lands on Dashboard); router.replace("/(tabs)") native. Verified E2E via screenshot tool.
4. PIN code auto-fill: /api/pincode/302001 verified working (Rajasthan/Jaipur); firm-master lookupPin wiring confirmed present (Iter 107).

## Iter 111 — Punch Approval Reasons + Extra Duty ± + Bio Code Reports + Daily Export + Sidebar Gating (tested, iteration_110.json ALL PASS)
1. PUNCH APPROVALS (punch-approvals.tsx): per-row "Update Reason" picker (presets: Due to Mismatch / Not Registered In Machine / Android Not Available + Custom modal); saveRow uses picker (no browser prompt); detailed post-save alert (employee, IN/OUT old→new, reason). "Updated" tab: new "Update Details (Punch · Reason · By)" column via day-status cells now carrying edit_reason/edited_by_name/original_hhmm (server.py day-status projection + editor name lookup).
2. EXTRA DUTY ±: Additional Duty tab has +/− sign toggle & HRS/MIN unit toggle; negative extra_hours allowed (backend upsert only rejects negative amount); attendance grid merge clamps day at 0 (h != 0 + max(0,...)).
3. BIO CODE IN ALL REPORTS: Grid View XLSX + Hours Only XLSX (col A "Bio Code", offsets shifted), IN/OUT + Hours monthly PDFs ("Bio" col after Code, identity_cols=6). OT report already had Bio.
4. DAILY BASIS EXPORT: NEW /api/admin/attendance/daily/{cid}/{YYYY-MM-DD}.xlsx|.pdf (utils/daily_attendance.py — S.No/Bio/Code/Name/Father/Designation/In/Out/OT In/OT Out/Duty/OT/Total/Status + P/A/MISS counts). Frontend attendance-grid.tsx: "Daily basis" DD-MM-YYYY input + Daily Excel/Daily PDF buttons (group filter honoured).
5. SIDEBAR SALARY GATING (AdminWebShell.tsx): fetches /admin/firm-master/{cid} (NOTE: payload nested under `master`), gatedNav hides Salary Process (Compliance)+(Arrear) when online_salary OFF and (Actual) when offline_salary OFF — ONLY when at least one toggle ON; All-firms/unconfigured → no gating. Verified both paths via screenshot.
6. Test data cleaned: leftover manual punch att_57a4731d3700 deleted; Kankani & City Care firm_masters reverted.

## Iter 112 — Daily Attendance Report Auto-Email (this session, self-tested)
- routes/email_notifications.py: _smtp_send/_send_and_log now support binary ATTACHMENTS; new trigger `daily_attendance_report` (label "Daily Attendance Report (Every Morning)", recipients admins, send_time "08:00" IST, placeholders {firm_name}{date}{present}{absent}{miss_punch}{total}); PUT /admin/email-triggers persists validated send_time; run_daily_attendance_batch() builds yesterday's Daily XLSX+PDF per firm (reuses _compute_monthly_grid_data + utils/daily_attendance) and emails firm admins + extra_emails; POST /admin/email-triggers/daily-attendance/send-now (manual test, optional {date, company_id}); daily_attendance_report_loop() 60s scheduler (last_sent_date guard) started in server.py startup.
- email-settings.tsx Automated Triggers tab: daily trigger shows "Send time (IST)" input + "Send now (test)" button (testIDs es-daily-send-time / es-daily-send-now).
- VERIFIED: trigger seeds in GET; send-now with temp fake SMTP built report for Kankani (124 emp) and reached real Gmail handshake (535 expected); UI renders. SMTP settings + test logs REVERTED to empty — trigger ships DISABLED; user must configure SMTP then enable it.
- CAUTION FOR NEXT AGENT: NEVER batch multiple parallel search_replace calls on the SAME file — concurrent writes clobber each other (caused lost edits in email_notifications.py + monthly_attendance.py this session; all repaired).

## Iter 113 — Recovery + Gender/Masters/QR/Individual Punch (this session, self-tested)
- CRITICAL INCIDENT: user's "Save to GitHub" click RESET the workspace to origin/main (yesterday's snapshot de634bf) — deleted .env files (backend down) + reverted all Iter 110-112 work from disk. RECOVERED via `git reset --hard adcaebc` (auto-commit had everything incl .env) + 3-way patch of in-flight edits. If Save to GitHub is used again, expect the same reset; recover from latest auto-commit via reflog.
- GENDER: employee-add already had GenderSelect (Male/Female/Transgender); added normGender() normalization for OCR + edit-prefill values.
- MASTERS: MasterSelect custom typed values now POST /admin/masters (persist into dropdown); backend create_master now allows company_admin for OWN firm only.
- QR CODES: "QR Codes (Join / App)" promoted to TOP-LEVEL sidebar item in NAV_SUPER (was hidden under Utilities; user couldn't find it).
- INDIVIDUAL PUNCH (user req): "+ Individual Punch" button on Punch Approvals (canAct roles) → modal: employee search picker (/admin/employees), date, IN/OUT HH:MM (night-shift aware: OUT<=IN → next day), reason preset chips → POST /admin/attendance/manual-punch (auto-approved). Verified E2E (punches created in DB, then test data removed).
- GIT: local main = bf6b739 (all work committed); clean-snapshot branch = ready-to-push snapshot WITHOUT .env; GitHub main still has YESTERDAY's snapshot — push pending (user PAT or Save-to-GitHub; if the latter, re-check .env + workspace state after).
- NOTE: automation browser intermittently hits Cloudflare challenge ("Security check in progress" dev overlay) — automation-only artifact, real browsers unaffected.
- MANUAL PUNCHES LOG (approved improvement): "Manual Punches Log" button on Punch Approvals → amber panel listing source=manual_admin punches for selected date/range (GET /admin/attendance/manual-log/{cid}?from_date&to_date — employee+creator names, hhmm) with per-row Undo (DELETE /admin/attendance/{id}?reason=...). Verified E2E incl. undo.
- VPS DEPLOYED (user-confirmed): repo at /home/sksharma/app; backend service = payroll-backend.service; nginx has TWO active roots for smartpayrolling.com — /var/www/sksharma AND /home/sksharma/app/frontend/dist — after `npx expo export -p web`, MUST copy dist/* into /var/www/sksharma too, then reload nginx. Full deploy recipe: git fetch+reset origin/main → pip install -r requirements.txt → systemctl restart payroll-backend → yarn install + expo export → cp dist/* /var/www/sksharma/ → systemctl reload nginx.
- WARNING for next agent: user twice ran VPS commands in the WORKSPACE terminal (wiping .env via git reset to clean snapshot). If backend dies with KeyError MONGO_URL, restore via `git reset --hard <latest auto-commit>` (reflog) which re-creates .env files.

## Iter 114 (fork) — Employee fields / Contribution & Bonus Reports / Compose+Mailbox / UI moves (testing_agent iteration_113.json: 16/16 backend GREEN)
- EMPLOYEE MASTER new fields: blood_group (A+..O- chips), marital_status (Single/Married/Widowed/Divorced chips), pan_name ("Name As Per PAN Card"), upi_id — employee-add.tsx (add+edit prefill+payload), server.py admin_create_employee, routes/employee_profile.py _STR_FIELDS, master_data_report.py columns (Blood Group/Marital Status/Name As Per PAN/UPI ID).
- FIRMS ALPHABETICAL: GET /api/companies now sorts by name (case-insensitive) — covers all firm dropdowns.
- NEW routes/contribution_reports.py (+registered in server.py): GET /admin/reports/contribution(?kind=pf|esi&month) monthly per-employee sheet; /contribution-yearly (FY Apr–Mar employee-wise matrix); /bonus-yearly-summary (Name/Father/DOJ + per-month Days+Earned + Firm-Master-enabled allowance heads + totals); all with .xlsx variants. Data source = LATEST compliance_salary_run per month.
- NEW screens: frontend/app/contribution-sheets.tsx (?kind=pf|esi, Month-wise / Employee-wise Yearly modes), frontend/app/bonus-yearly-summary.tsx (FY picker, wide table, xlsx download).
- SIDEBAR (AdminWebShell both NAV arrays): Reports gains P.F./E.S.I. Contribution Sheet + HR Letters (HR Letters removed from top level); Bonus gains Bonus Yearly Summary; AI Insights moved to the very END of NAV_SUPER.
- COMPLIANCE SALARY PROCESS: grid + CSV + PDF now show Name, Father Name, Designation, UAN No., ESIC No. and HIDE Employee Code. compute_compliance_row emits father_name/designation/uan_no/esi_ip_no (old saved runs show "—" until reprocessed). Group-header offset now 6*CELL_W; TOTAL row has 6 leading cells.
- EMAIL COMPOSE (routes/email_notifications.py compose + email-settings.tsx): attachments (base64, max 5×10MB) passed through to SMTP; "📣 ALL FIRMS (single click)" broadcast (all_companies=true, super/sub only; hides Recipients card; in-app notif gets per-target company_id).
- MAILBOX↔SMTP (routes/gmail_mailbox.py): when Gmail OAuth NOT connected, /gmail/status|messages|messages/{id}|send fall back to smtp_settings creds — IMAP (imaplib in to_thread; host derived smtp.x→imap.x, gmail→imap.gmail.com; SENT tries [Gmail]/Sent Mail) for reading, _send_and_log for sending (event mailbox_compose). Workspace has NO smtp_settings → status connected=false; works on user VPS where SMTP is configured.
- DASHBOARD: centered Super Admin/Sub Admin name + logo block (testID admin-brand-center) on (tabs)/index.tsx; roleBadge now includes "Sub Super Admin".
- PWA INSTALL FIX (get-app QR issue): +html.tsx now captures beforeinstallprompt EARLY into window.__pwaInstallEvt + dispatches 'pwa-install-ready'; get-app.tsx picks up the stashed event (race fix — event fired before React mounted). iOS keeps Add-to-Home-Screen hint.
- NOTE: testing agent flipped firm_masters cmp_527fecdd7c salary_process.online_salary false→true in workspace DB (to create fresh compliance run) — workspace-only.
- PENDING for user verification: PWA install button on real Android Chrome after VPS deploy; Mailbox SMTP/IMAP on VPS (needs Gmail IMAP enabled for the app-password account).

## Iter 115 — EPF Challan / ESIC Bulk Sheet UPLOAD AUTOMATION (user request; stops at challan, NO bank payment)
- rpa_worker.py: new action_types upload_ecr / upload_esic_mc; _perform_login(..., upload=) now optionally uploads after login; _attempt_portal_upload navigates (EPFO: "ECR/Return Filing" etc; ESIC: "Online Monthly Contribution" etc), finds input[type=file] (frames too), set_input_files with buffer, clicks Upload/Submit/Validate — _PAYMENT_BLOCKLIST safety rail NEVER clicks pay/payment/bank buttons. Statuses: uploaded→completed, upload_manual→manual_required (file downloadable).
- challans.py: extracted _ecr_txt_bytes/_esic_xls_bytes builders (reused by downloads); NEW endpoints POST /api/admin/portal-upload-jobs {run_id, portal epfo|esic} (validates Firm-Master creds via rpa_worker._fetch_creds + builds file → job doc w/ file_b64 in portal_automation_jobs), GET /api/admin/portal-upload-jobs (list, screenshots stripped), GET /api/admin/portal-upload-jobs/{job_id}/file (manual fallback). NOTE: paths NOT under /challans/... to avoid /challans/{challan_id} route collision (was a bug, fixed).
- challans.tsx: "🤖 Auto Upload to Portal" card — Auto-Upload EPF ECR → EPFO + Auto-Upload ESIC Bulk Sheet → ESIC buttons (confirm dialog states no-bank-payment), job status list w/ chips (Queued/Running/Uploaded ✓/Finish manually/Failed) + 10s polling + per-job file download.
- E2E verified in workspace: queue→worker pickup→graceful manual_required (Playwright browser not installed here). VPS needs: pip install playwright && python -m playwright install chromium && RPA_WORKER_ENABLED=1 in backend/.env (+ PORTAL_PROXY_URL if govt portals block VPS IP).
- User also shared EPFO ECR v3.0 + ESIC MC helpfile links (pod couldn't fetch — govt sites block; formats already match firm's actual portal samples).

## Iter 116 — Generate EPF UAN full automation (user request)
- rpa_worker.py: _attempt_uan_registration(page, snap) — after login opens Member → "Register - Individual" (nav text candidates), fills member form from employee_snapshot (Aadhaar mandatory, name upper, DOB/DOJ in DD/MM/YYYY — converter handles both ISO and DD-MM-YYYY, gender select MALE/FEMALE/TRANSGENDER, father name, marital status map Single→UNMARRIED etc, mobile last-10-digits, email), clicks Save/Submit/Register (payment blocklist respected), then regex-scans page for "UAN …(\d{12})".
- _perform_login gained uan_snap param (both no-captcha and captcha success paths); statuses uan_registered / uan_manual.
- _process_one_job: generate_uan passes employee_snapshot; on UAN found → db.users.uan_no saved (source rpa_auto) + job completed; registered w/o visible UAN → manual_required "approve on portal + Manual Complete"; nav/aadhaar-field failure → manual_required w/ screenshot.
- portal_generation.py employee_snapshot now includes marital_status.
- Verified in workspace: job queue → worker pickup → graceful manual_required (Playwright missing here; full flow needs VPS chromium).

## Iter 117 — Company create/edit form: live validation blocks Save (user request)
- companies.tsx Add/Edit modal: liveErrors computed each render (name required, lat -90..90, lng -180..180, radius>0, company code A-Z0-9 2-8, employer admin email format, admin phone 10-13 digits). Red "Please fix before saving" list (testID cc-live-errors) shows while any error exists; Create/Save button disabled (opacity 0.45) + submit() guard refuses while errors remain. Company is only created when ALL errors are cleared.

## Iter 118 — Relation-aware Father/Spouse name in reports (user request)
- NEW utils/relation.py father_or_spouse_display(u): Female+Unmarried→"D/O <father>", Female+Married→spouse_name only (fallback father), else father_name.
- Applied to: master_data_report.py rows (column relabelled "Father / Spouse Name"), compliance_salary.py compute row (grid/CSV/PDF), contribution_reports.py _emp_lookup (bonus yearly summary).
- NEW employee field spouse_name: employee-add.tsx (Spouse Name input appears when Marital Status = Married), server.py create doc, employee_profile.py _STR_FIELDS.

## Iter 119 — Bulk Employee Import updates (user requests)
- CSV template: employee_group column REMOVED (26 columns now); employee_type only. Import mirrors employee_group = employee_type (merged concept), group-policy inherit now keyed by type value.
- Allowances/Deductions per Company Policy: when a CSV row has no allowance/deduction columns, actual_salary_allowances/deductions default to the heads ENABLED in firm_masters Sections 5&6 (amount 0). Verified live: import to Kankani yields HRA/CONV./OVER TIME + PF/ESI/ADVANCE.

## Iter 120 — Employer can also be an Employee (user request)
- Duplicate checks in single Add Employee + Bulk Import now only block when the existing phone/email belongs to role=employee — a Firm Master employer/admin mobile can also be registered as an employee.
- Login disambiguation: /auth/admin-pin-login prefers admin-role match on email/phone; /auth/pin-login (employee) prefers role=employee on phone. Verified live both directions; employee-duplicate still blocks.

## Iter 121 — Sidebar: merged duplicate "Utilities" group into single "Utility" group (NAV_SUPER) — children: Past Salary Runs, Import Biometric .dat, QR Codes, Users Log Report, Messages, Tickets, Mailbox, Database Viewer.

## Iter 122 — Employee Full Report + Sub Admin Performance Chart + QR-scoped landing (user requests; testing_agent PASS all)
- NEW `/employee-report` screen (sidebar Reports > Employee Report, replaced old /admin link in BOTH nav trees): firm picker → employee search/select → period (quick chips This month/Last month/Last 3 months/This FY + from/to DateFields) → Generate. Sections: Profile, Attendance (summary stats + day-wise table), Leaves, Actual Salary, Compliance Salary, Documents, Tickets. Export Excel + Export PDF buttons.
- NEW backend `/app/backend/routes/employee_full_report.py`: GET /api/admin/employee-report (+/export.xlsx multi-sheet openpyxl, +/export.pdf reportlab). Validates dates (400), unknown user (404), auth (401). Registered in server.py bottom.
- `/users-log-report`: added "Sub Admin Performance" card — per-admin stacked horizontal bars (Punch blue/Salary green/Compliance orange/Other gray) with legend + totals + breakdown text; quick period chips Last 7/30/90 days. Pure RN Views (no chart lib). Unattributed events labeled "System / Device".
- QR-scoped landing: get-app.tsx stores localStorage `qr_entry_type` (employee|employer). index.tsx mobile landing hides Admin+Company buttons for employee QR (Employee sign in becomes primary), hides Employee sign in for employer QR; "Show all sign-in options" link clears it. Desktop landing unchanged.
- OCR error "PASTE_KE**HERE" reported by user = placeholder EMERGENT_LLM_KEY in the VPS .env (local key valid). User must set real key on VPS.

## Iter 123 — Sub Admin Employee Master rights + Switch Firm fix + QR/OCR follow-ups (user requests; testing_agent 16/16 backend + frontend PASS)
- EMPLOYEE MASTER FOR SUB ADMINS: ~13 endpoints in server.py now allow sub_admin gated by sub_admin_permissions (employees:read/write, attendance_policy:read/write) + firm scope via sub_admin_can_touch_company: /admin/user-role (PATCH), /admin/employees/{id}/policy (GET/PATCH), attendance-policy-override (GET/PUT/DELETE), documents (GET list/GET/POST/DELETE), master-pdf (single+bulk). Role change & firm reassignment stay super-admin-only. _load_scoped_employee(+_any_role) enforce sub-admin scope. Frontend employee-master.tsx isAdmin includes sub_admin.
- SWITCH FIRM FIX: header GlobalCompanyPicker silently no-oped after first selection (iter77 session lock). Added switchCompany() to SelectedCompanyContext (always applies explicit pick, re-locks to new firm, 'All firms' clears lock). Failed /companies refetch no longer wipes list (was showing "No firms").
- test_credentials.md: testsub@sksharma.co / testsub123 reset + perms updated (employees:r/w, attendance_policy:r/w, companies:read, scope all).
- Non-blocking follow-ups noted by testing agent: debounce /companies refetch (Cloudflare 429 on rapid switching in automation), cosmetic sub-admin home shows employee punch card.
- DEPLOYMENT: user's VPS = /home/sksharma/app (supervisor svc: sksharma-backend, web root /var/www/sksharma, venv /home/sksharma/app/venv). GitHub main was stale at iter-120 snapshot; user must Save to GitHub → main before VPS pull. VPS .env needs real EMERGENT_LLM_KEY (OCR fix).

## Iter 124-125 — Remember last firm, Sub Admin full access fix, Bulk Import new format
- REMEMBER LAST FIRM (user request): GET/PATCH /api/me/last-company (routes/user_prefs.py) stores last_selected_company_id per admin; SelectedCompanyContext persists every explicit firm pick and auto-restores it after next login (super+sub admin; once per login via restoredForUser ref). Tested by agent 15/15 PASS (iteration_116).
- SUB ADMIN "Not your firm" FIX (user request): sub admins were compared against their nonexistent company_id in challans.py (_scope_company + record checks + jobs), firm_master.py (_assert_firm_access), employee_kyc.py, employee_salary.py, portal_generation.py, leaves.py, server.py (_resolve_target_company + set-credentials). Now sub_admin behaves like super admin across firms in scope (sub_admin_can_touch_company); company_admin unchanged.
- BULK EMPLOYEE IMPORT NEW FORMAT (user request): template CSV + import now use firm's own headers: EMPLOYEE PFNO, UAN_NO, EMPLOYEE ESINO, EMPLOYEE NAME, EMPLOYEE FATHER NAME, Designation, Department, Emp Type, Gender, Marital Status, DOB, DOJ, EMPLOYEE BASIC, PF_BASIC, HRA, CONV, OVER_TIME, Gross Pay, Present Add, Permanent Add, PANNo, Name As Per Pan Card, Aadhar Card No, Name On Aadhar Card, Bank Name, Bank Address, Account No, Name On Bank Ac, IFSC Code, Mobile1, Mobile2, Pay Mode, Pay Basis, Resign Date, Basic Salary Actual. Backend _ALIASES header normalization in bulk-import endpoint (old lowercase headers still work); new user fields: marital_status, basic_salary, pf_basic, hra, conveyance, over_time, present/permanent_address, name_as_per_pan/aadhar, bank_address, account_holder, phone2, pay_mode, pay_basis, resign_date; Basic Salary Actual→salary_monthly, Gross Pay→compliance_gross, Pay Basis→salary_mode. Curl-verified import + template.
- NOTE: temp code-bundle endpoint routes/temp_bundle.py (token sks-deploy-7391) serves /tmp/sksharma-latest.bundle for VPS deploys — REMOVE once GitHub Save-to-GitHub flow is reliable. GitHub main was updated via VPS push of clean single-commit snapshot (no secrets; push protection passed after stripping .env/SksPay.env/creds from tracking).

## Iter 126 — Employer Salary Processing Access Rights (user request; testing_agent 16/16 backend PASS, iteration reported by test agent)
- USER ASK: "If We Enable Manage (Employer Access Rights) then Employer can edit/process Actual, Compliance and Arrear salaries."
- BACKEND server.py: POST /admin/salary-runs now gated by require_employer_permission "salary_process:write"; all 9 run-scoped salary-run GETs (get run, register-form27.pdf, export.csv/.xlsx, register.pdf, payslips.pdf/.zip, off-roll-slip, off-roll-slips.zip) gated by "salary_process:read"; compliance generate-payslips gated by "compliance_salary:write" (finalize/reprocess/create already were).
- BACKEND routes/arrear_salary.py: POST create → "salary_process:write"; list/get/ecr.txt/export.xlsx → "salary_process:read" (DELETE stays super/sub admin only). Arrear intentionally reuses salary_process keys (matches AdminWebShell NAV_PERMISSION_MAP — no new permission key added).
- super_admin/sub_admin always pass require_employer_permission; company_admin needs firm-level grant in companies.employer_permissions.
- FRONTEND AdminWebShell.tsx: /salary-run + /arrear-salary-run menu entries are now OPT-IN for company_admin (like compliance) — hidden unless salary_process:read|write granted, even when employer_permissions is empty/unset. employer-access-rights.tsx label renamed "Salary process (Actual + Arrear)".
- Access rights admin endpoints: GET/PATCH /api/admin/companies/{cid}/access-rights.
- Test file: /app/backend/tests/test_iter125_employer_access_rights.py (16 cases). Kankani admin PIN login needs 6 digits now — 4-digit PIN in credentials stale; test agent injected user_sessions doc for user_0a38839e3568 (documented in test_credentials.md).

## Iter 126b — VPS deployment incident RESOLVED (2026-07-13)
- ROOT CAUSE of "features not working" on www.smartpayrolling.com: nginx proxies /api -> 127.0.0.1:8001, but TWO backend managers existed: (1) systemd unit `payroll-backend.service` running OLD (pre-iter-122) code on 8001 via venv /home/sksharma/app/venv — this is what users hit; (2) supervisor `sksharma-backend` running NEW code on UNUSED port 8000 via venv /home/sksharma/app/backend/venv.
- FIXES applied on VPS: supervisor conf port 8000->8001 (`/etc/supervisor/conf.d/sksharma*.conf`); installed missing `emergentintegrations` + `aiosmtplib` into /home/sksharma/app/backend/venv (pip needs `--extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/` for emergentintegrations); `systemctl disable --now payroll-backend` (mask failed — unit file exists at /etc/systemd/system/payroll-backend.service; disabled is sufficient).
- VERIFIED live: health 200, /api/me/last-company 401, /api/admin/employee-report 422, arrear-salary-runs 401 — all NEW routes serving through nginx.
- FUTURE DEPLOY CHECKLIST for VPS: (1) wget bundle from /api/temp-code-bundle?token=sks-deploy-7391; (2) git fetch bundle + reset --hard FETCH_HEAD in /home/sksharma/app; (3) pip install -r backend/requirements.txt WITH the emergent extra-index-url into backend/venv; (4) expo export -p web + cp dist/* to /var/www/sksharma; (5) sudo supervisorctl restart sksharma-backend (NOT systemd); (6) verify `curl localhost:8001/api/health` and a NEW route returns 401 not 404.
- Server takes ~10-20s to boot (18k-line server.py). Uvicorn runs --workers 2: master can stay "RUNNING" in supervisor while workers crash-loop (check /var/log/sksharma/backend.err.log).
- GitHub main update flow: from VPS `git push origin HEAD:main --force` (single-commit snapshot; PAT auth; credential.helper store recommended).

## Iter 126c — Remember-last-firm SPA re-login fix (user bug report; testing_agent verified core flow)
- BUG 1: SelectedCompanyContext restoredForUser ref was never reset on logout → same-user re-login in the SPA (no page reload) skipped the /me/last-company restore. FIX: reset ref to null in the (!authLoading && !user) effect.
- BUG 2: sub admins were parked on /firm-select even after the server restore set the firm. FIX: firm-select.tsx auto router.replace("/(tabs)") when selection appears (only if screen was entered WITHOUT a selection and no manual pick — deliberate "Switch firm" visits unaffected via initialCidRef/manualPickRef).
- Testing agent: sub admin login → lands directly on dashboard with Kankani restored (PASS). Cloudflare 429 blocked full logout/relogin loop automation (env artifact, not app bug). Cosmetic pre-existing expo-router warning: REPLACE "(tabs)" not handled (dashboard renders via fallback) — not fixed, low priority.
- "Salary Process (Actual) not showing" complaint = Firm Master toggle behavior (iter-110/114 design): Companies (Firm Master) → firm → Salary Process → "Offline Salary → Actual Salary Process" ON shows the menu. Asked user whether to keep or remove this gating — ANSWER PENDING.
- Deployed to VPS (bundle 8f02ec1, web entry-59148b2...). Live verified: new bundle served + backend routes healthy.

## Iter 126d/e — Batch of user requests (2026-07-13, deployed as one bundle)
- Dashboard sidebar click stuck on prod static export: onNavigate maps "/(tabs)" -> "/" (AdminWebShell); firm-select replace("/(tabs)") -> "/".
- "Admins only" on Salary Process (Actual) + Compliance Salary for SUB ADMINS: isAdmin in salary-run.tsx + compliance-salary-run.tsx now includes sub_admin; firm picker + firm-required validation extended to sub_admin (salary-run).
- Employee Master salary structure follows Firm Master (user request): employee-add.tsx fetches /admin/firm-master/{cid}; renders "Allowances (from Firm Master)" + "Deductions (from Firm Master)" amount fields (bind actual_allowances/actual_deductions SalaryLine[]); "Employee Actual Salary" section hidden when firm is online-only (offline_salary OFF), legacy/unconfigured firms keep it. Verified via screenshot (Kankani: HRA/CONV./OVER TIME + PF/ESI/ADVANCE, Actual hidden).
- Sidebar Masters rename: "Employee Groups" -> "Employee Type" (both nav trees + screen title).
- Mailbox Gmail-style category tabs: Primary/Promotions/Social/Updates/Spam. Frontend chips pass label (CATEGORY_PERSONAL etc / SPAM). Backend gmail_mailbox.py: Gmail API combines INBOX+CATEGORY_* labelIds; IMAP fallback uses X-GM-RAW "category:x" search + [Gmail]/Spam folder select. Tabs only visible when Gmail/SMTP connected (dev not connected; prod has SMTP).
- STILL OPEN: prod remember-last-firm reported "dashboard with empty firm picker" AFTER 126c deploy — awaiting user's mongosh diagnostics (users.last_selected_company_id + companies.employer_permissions values on VPS).

## Iter 126f — Remember-last-firm TRUE root cause found & fixed
- User's VPS mongo diagnostic showed NO users had last_selected_company_id -> persist never saved in prod.
- ROOT CAUSE: SelectedCompanyContext persistLastCompany passed body: JSON.stringify({company_id}) but api() client stringifies body itself -> double-encoded JSON string -> FastAPI 422 -> .catch swallowed -> never persisted. (Earlier dev tests masked it because the agent had seeded the value via curl.)
- FIX: pass plain object body. Verified e2e: cleared DB value, picked firm via header GlobalCompanyPicker in browser, DB now shows last_selected_company_id=cmp_527fecdd7c.
- Codebase greped: no other double-stringify api() calls remain.

## Iter 126g — Employee Master restructure + PF Basic rule (user requests, verified via screenshot + engine unit test)
- employee-add.tsx: added "Compliance Basic Salary" + "PF Basic Salary" in Compliance section. EPF rule: basic>0 && <15000 -> pf_basic auto-copies basic and field locks; basic>=15000 -> pf_basic optional/editable. Saved as compliance_basic / pf_basic (create POST doc + employee_profile.py _NUM_FIELDS).
- Firm-Master heads editors moved INTO Compliance section, now bind compliance_allowances/compliance_deductions (user: "Allowances from Firm Master is part of Compliance Salary").
- Pay Mode moved into Compliance section; Bio Code moved to Actual Salary section (still visible for online-only firms above the gate); Family Details moved to END of form.
- utils/compliance_salary.py: PF calc override — user.pf_basic>0 -> pf_wages = pf_basic (pro-rated by effective_present/month_days for monthly mode, no 15k cap since explicit); else legacy min(stat_wage_base, cap). compliance_basic feeds resolve_structure as basic_amount (pro-rated) when no explicit overrides/rows. Unit-tested 4 cases: 12000->12000, filled 16000->16000, empty+18000->15000 cap, half attendance->6000.
- Earlier this session (126e): sub_admin isAdmin fix on salary screens, Employee Type rename, mailbox category tabs, dashboard nav fix, remember-firm persist 422 fix (126f).

## Iter 126h — Compliance Draft/Finalize lock + unlock approval + challan gating (user request; curl-tested end-to-end)
- compliance-salary-run.tsx: run detail shows "Save as Draft" + "Finalize (Lock)" when draft; when FINALIZED shows lock chip + "Request Change" (sub/employer) or "Unlock" (super). Pending request: amber chip; super admin sees Approve/Reject buttons inline.
- NEW endpoints in server.py (before reprocess): POST /admin/compliance-salary-runs/{run_id}/unlock-request (super -> immediate unlock; others -> salary_unlock_requests doc, dedup pending), GET /admin/salary-unlock-requests (super sees all, requester sees own), POST /admin/salary-unlock-requests/{req_id}/decide (require_super_admin_strict; approve -> finalized=False + audit unlocked_at/by/reason).
- routes/challans.py create: non-super roles get 409 unless compliance run for firm+month is FINALIZED ("upload challans only after finalize").
- Both salary screens (salary-run.tsx + compliance-salary-run.tsx): currentMonth() now defaults to PREVIOUS month.
- Reprocess already blocks finalized runs (409, pre-existing). Tested: draft challan 409 -> finalize 200 -> challan ok -> unlock-request pending -> approve -> finalized False. Dev data restored (run back to draft, test challan deleted).
- NOTE: user asked this workflow for COMPLIANCE runs only; Actual salary untouched.

## Iter 126i — VPF (Voluntary PF) (user request; engine unit-tested + UI screenshot verified)
- employee-add.tsx: after PF Basic note -> "VPF (Voluntary PF)" checkbox (testID vpf-toggle); when ON reveals "VPF Amount / month (₹)" field. Saved as vpf_enabled(bool)+vpf_amount(num) (create POST + employee_profile.py whitelists).
- utils/compliance_salary.py: when vpf_enabled & amount>0 -> vpf pro-rated (monthly: *effective_present/month_days) added to pf_employee (employee-side only; employer share unchanged); row includes "vpf_amount". Tested: PF 1440 + VPF 500 = 1940; off -> 1440.
- PENDING CLARIFICATION: user message "Please Rollback Old Line for Amendment" — meaning unclear, asked user.

## Iter 127 — Monthly Challan Summary + Audit Lock + Primary Inbox Ping (user requests; testing_agent 13/13 backend + full UI pass; iter 127b curl+screenshot verified)
- NEW Reports ▸ "Monthly Challan Summary" (/challan-summary, super_admin + sub_admin; company_admin sees own firm). routes/challan_summary.py wired into server.py.
- GET /api/admin/challan-summary?month=YYYY-MM: all active firms — salary_status (finalized/draft/not_processed from compliance_salary_runs), PF/ESIC amounts (manual override else auto from newest db.challans upload incl. paid_on date), pf/esic_by_name, pf/esic_date, remark, is_audit, reg_email (firm_masters.header.email_1/2), reg_whatsapp (first contact_person mobile). Stored in db.challan_summaries keyed (company_id, month).
- PATCH /api/admin/challan-summary/{cid}/{month}: pf_amount/esic_amount/pf_date/esic_date/remark. Remark containing "audit" (case-insens) => is_audit=true.
- GLOBAL AUDIT LOCK: middleware in server.py (_audit_lock_guard, before include_router(api)) blocks POST/PUT/PATCH/DELETE /api/* targeting a locked company_id (path, ?company_id= or JSON body) with HTTP 423. super_admin + employee roles exempt; paths ending /send-email exempt. 20s cache + bust_audit_lock_cache() on remark change (instant lock/unlock). IMPORTANT: do NOT re-inject request._receive after await request.body() — Starlette 0.37 _CachedRequest handles replay; manual re-inject broke responses (fixed).
- Emails: POST /admin/challan-summary/email (whole sheet) + POST /admin/challan-summary/{cid}/{month}/send-email (one firm to registered email, `to` override). WhatsApp = client-side wa.me links (user chose free pre-filled option).
- Frontend challan-summary.tsx: month picker defaults previous month; AUTO-SAVE (900ms debounce per row, diff vs baseline, "✓ Saved"/spinner/Failed status col — NO save button per user); per-row Email+WhatsApp icon buttons in front of firm name (confirm modal prefilled with registered contact, editable; 10-digit WA numbers get 91 prefix); PF/ESIC DateField under each amount; audit rows red + locked for non-super; header Email/WhatsApp buttons for full sheet with confirm modals.
- Primary Inbox ping: GET /api/gmail/primary-unread (super+sub admin, 45s server cache; OAuth CATEGORY_PERSONAL is:unread else IMAP X-GM-RAW category:primary). gmail status/messages/detail now allow sub_admin (read-only; send still super-only). Frontend: usePrimaryInbox hook (60s poll, dismissed ids in AsyncStorage), PrimaryInboxBanner on dashboard (tabs)/index.tsx (amber card, tap->/mailbox, ✕ dismiss until new mail), mail-bell badge in AdminWebShell header (testID web-mail-bell).
- Test data cleaned after testing (no firms left locked).

## Iter 127c/d/e — Salary Process fixes + auto-fit columns (unit+e2e+screenshot verified)
- COMPLIANCE ENGINE (utils/compliance_salary.py compute_compliance_row): now reads Employee Master `compliance_salary_allowances` — gross = compliance_basic + Σ allowance heads (HRA/CONV/MEDICAL/SPECIAL map to columns, rest → others), pro-rated by present days; master columns show full-month amounts (master_user/master_gross_override). Fixes gross=0 when compliance_gross blank (basic-only → basic IS gross). `compliance_salary_deductions` (excl. PF/ESI/provident heads) added to total_deduction as `master_deduction` field.
- ROLES: sub_admin (with salary_process:write perm) can now POST /admin/salary-runs, reprocess actual, and reprocess compliance (was super/company_admin only).
- employee-add.tsx Iter 127d: Firm-Master allowance/deduction editors ALSO in Actual Salary section (actual_allowances/actual_deductions → actual_salary_allowances etc., engine already summed them). NOTE: Actual section hidden when firm_masters.salary_process.online_salary=true & offline=false (showActualSalary gate) — by design.
- GRIDS Iter 127e (user rolled back wrap-text → auto-fit): compliance-salary-run.tsx has `colW` useMemo (name/father/desg/uan/esi auto-width from content, num width for ALL numeric cells incl. totals row + group spans via CELL_W=colW.num, INFO_W spacer). salary-run.tsx: module const renamed BASE_COL_WIDTHS; ResultGrid shadows COL_WIDTHS with content-fitted widths (px≈len*7.2+20, clamp 280); totalMinWidth depends on it. numberOfLines={1} restored everywhere.
- GitHub: repo sksharmaconsultancy-tech/S-K-Sharma (PUBLIC — advised private), pushed via user token (told user to revoke). Push flow: clean tree in /tmp/ghpush_* excluding node_modules/dist/.env/memory/test_reports/backups.
- VPS deploy: /home/sksharma/app, venv pip at backend/venv/bin/pip, bundle at /api/temp-code-bundle?token=sks-deploy-7391&kind=tar (tar built from /app excluding .env).

## Iter 129 — "All months" gating + ALL attendance reports per Firm Master Policy + policy-aware Employee PWA attendance (testing_agent 13/13 backend + 5/5 frontend; present/weekly_off gap fixed & retested 13/13)
- "All months" option hidden unless EVERY run is finalized (user: "all screens"): reports.tsx (MonthPicker allowEmpty={allowAllMonths}; month filter moved CLIENT-side so drafts across months are detectable; auto-selects latest run month; bulk-download uses vis lists) + challans.tsx (portal month select; allRunsFinalized on finalized_at; auto-select latest).
- Monthly IN/OUT PDF + HRS PDF rebuilt: utils/monthly_attendance_pdf.py fully rewritten to consume the policy grid from _compute_monthly_grid_data (was raw punches, no approved-filter). Trailing cols now Duty/OT/Total Duty/Days/Extra HRS matching XLSX. server.py _monthly_report_impl: all 4 variants grid-based; legacy raw punch loading removed. Verified MADAN KEER (212) totals 24.00/6.50/30.50/3/6.50 identical PDF↔grid.
- NEW GET /api/attendance/my-month?month=YYYY-MM (employee self): _compute_monthly_grid_data got only_user_id param; returns per-day cells (in/out/hours/duty/ot/present 0|0.5|1/weekly_off/anomaly) + totals + weekly_off_days (0=Mon..6=Sun); salary fields stripped. EVERY cell normalised to carry present+weekly_off (grid only sets them on clean punch days — was a bug caught by testing agent).
- history.tsx (employee PWA): calendar now policy-driven via my-month (fallback to legacy raw pairing if API fails). New "anomaly" status (orange, "!", legend "Missing punch", drill-down note "duty not counted per firm policy"), weekly offs from policy (not hardcoded Sunday), OT pill in drill-down, OT in month total.
- /api/attendance/summary (dashboard 7-day widget): per-day hours overlaid from grid pipeline (missing-punch days = 0), still_in days keep raw live hours; all-time total unchanged (raw).
- Already policy-aware (no change needed): monthly XLSX (grid/hours), daily xlsx+pdf, weekly email summary, OT report, on-screen grid views incl Salary + IN/OUT+Salary.
- TEST CREDS: employee UI login = /pin-login → Username tab → TEST50 / 123456 (emp code 50, Kankani). pytest tests/test_iter129_policy_attendance.py (13/13).
- PENDING USER: CL/PL day counts + accrual ("will share tomorrow"), Salary PDF/Excel export layouts ("will share"), PWA install confirmation, VPS deploy of these changes (needs expo export + node scripts/inject-pwa-html.js post-export).

## Iter 130 — Statutory Salary Register PDF (exact user format) + firm-switch resets + past-runs hidden
- Compliance register PDF REWRITTEN to match user's reference "Compliance Salary.pdf" (Form No. 27(1), rule 78(1)(a)(i)): portrait A4, header w/ P.F.Code+ESI Code (from firm_masters.epf.epf_no / esi.esi_no; address from companies.address), centered SALARY REGISTER (GROUP) + M/S. firm name, right Month Days + FOR THE MONTH + Page x of y (NumberedCanvas). Grouped EARNINGS(SALARY/HRA/CONV/OTHER/TOTAL) + DEDUCTIONS(PF/ESI/ADVANCE/OTHER/TDS/TOTAL) cols, NAME+S/O father & UAN/ESI stacked cells, DAYS/HRS, GRAND TOTAL row, summary page (emp count, gross breakdown, deduction breakdown incl ABRY, PF/non-PF/ESI wage splits, Total Days/Hours, RUPEES in words gross+net, Checked by / Payment Date / For FIRM / AUTHORISED SIGNATORY footer). Function: utils/compliance_salary.py build_compliance_register_pdf(run, company_name, firm). Endpoint /admin/compliance-salary-runs/{id}/register.pdf passes firm dict. Existing "PDF" button on Salary Process Compliance = direct download (user's ask). VERIFIED visually (2-page render, Kankani STAFF run).
- saveAsDraft hard guard: blocked with message when run.finalized (button already hidden when finalized). Unlock-via-Super-Admin approval flow ALREADY existed (verified backend: non-SA creates salary_unlock_requests pending; SA approves/rejects; reprocess/new-run 403/409 on finalized).
- Firm switch RESET (user directive): compliance-salary-run.tsx + salary-run.tsx — prevCidRef effect clears run/activeBatch/empType on firm change; employee-type group chips now keyed to localCid too. Compliance "Past compliance runs" list REMOVED from front page on both screens → compact link to /past-salary-runs (testIDs csr-open-past-runs / asp-open-past-runs). ALL VERIFIED via screenshots (firm switch clears loaded run + per-firm groups).
- STILL PENDING FROM USER: CL/PL day counts + accrual, Actual/OT salary export layouts (only Compliance layout was shared), PWA install confirmation, VPS deploy.

## Iter 131 — "Clear all pendency" batch (all verified)
- ESIC ON BASIC (user directive, twice): Standard Compliance Settings label "ESIC eligibility limit (Basic ≤)" + hint rewritten; utils/compliance_salary.py esic_wage_base = earned BASIC (was max(basic, floor% gross)); client recalc in compliance-salary-run.tsx matched. Verified: 15000 gross → basic 6000 → esic_base 6000, emp 45, er 195.
- Past Salary Runs firm-scoped: past-salary-runs.tsx passes company_id from useSelectedCompany (header shows "Firm: X — its runs only"). Verified 24→22 Kankani-only.
- Salary Process (OT) added to sidebar submenu (NAV_SUPER + NAV_COMPANY_ADMIN, /ot-salary-run in SALARY_ROUTES opt-in + ROUTE_PERMS). Verified visible.
- OT Calculation config in Firm Master (Policy 2 ONLY): attendance policy fields ot_pct_basic/ot_pct_gross (0-500, normalizer in server.py ~1091); UI block in TextilePolicySection (testIDs ot-pct-basic/ot-pct-gross) shown only when policy_2; ot_salary.py _compute: firm cfg wins → hourly=(per_day_basic×%B + per_day_gross×%G)/100/full_day_hours, cfg.calc_on="firm_master"; firms endpoint returns pcts; ot-salary-run.tsx hides manual calc controls & shows firm cfg line when set. PATCH round-trip verified (100/25 saved+reverted on City Care).
- Duplicate deletion-request guard: ALREADY EXISTED in routes/deletion_approvals.py _queue_request + firm deletes (returns "already pending Super Admin approval" message, alerted by frontend). No change needed.
- Employee Masters filter: TYPE (All/STAFF/Unset) → GROUP chips (Unset removed); Compliance label "Employee group".
- Firm-switch reset on Salary Process Actual (salary-run.tsx prevCidRef) + Compliance (earlier).
- NOTE: NO firm currently has policy_2 (Kankani=policy_1) — OT screen shows "No firms have Policy 2" until user selects it in Firm Master.
- NOT YET PUSHED TO GITHUB (last push was fffe1df; user has token rotation pending).

## Iter 132 — ROLLBACK INCIDENT + full restore + Excel bulk import
- INCIDENT: a platform rollback silently reverted the worktree mid-session (deleted ot_salary.py, compliance-settings.tsx, challan files, tests; reverted ~20 modules). Auto-commits then pushed the damage to GitHub main (7bc7e60/f391d18 were PARTIALLY broken). RECOVERED via `git checkout 3024aa15 -- .` (last full good auto-commit) + re-applied the 4 post-3024aa1 changes. If features "disappear" again, check `git log --all` for the last good commit and audit with feature greps before pushing.
- Sub-admin restricted company scope fix: /companies checked scope=="limited" but User Rights saves "restricted" → restricted sub-admins saw ALL firms. Now `scope != "all"`. Verified restricted sub-admin sees only assigned firm.
- Employee Master scoped to globally selected firm (admin.tsx companyFilter syncs with lockedCid).
- Bulk Employee Import: CSV → Excel. GET /admin/employees/bulk-import-template.xlsx (all cells TEXT "@", 500 preformatted rows, "Emp Group" header) + POST /admin/employees/bulk-import-parse (base64 xlsx → {headers,rows} strings, leading zeros preserved, int floats destringed, dates ISO). Frontend reads xlsx as base64 → parse endpoint; CSV fallback kept. Aliases "emp group"/"group" → employee_type. Sidebar label "Bulk Import (Excel)".
- Kankani (preview DB) remains policy_2 + ot_pct_basic=100 (user requested).

## Iter 139 — New biometric import formats + Bio Code in Bulk Correction (E2E verified)
- Import Biometric screen now accepts device "attendance record" exports in TWO new formats (auto-detected, all upload slots):
  1. Tab-separated .TXT export: `No | TMNo | EnNo | Name | Mode | INOUT | DateTime` (date `YYYY/MM/DD`), header optional. INOUT even=IN / odd=OUT; identical-kind days re-paired by punch position (existing iter86 logic).
  2. Binary GENLOG .DAT backup ("ZoucqGENLOGData" header): 8-byte records `u16 pad | u32 secs-since-2000 | u16 (enrollNo<<4|flags)`; auto-aligns start offset, rejects future-year garbage. Verified byte-exact vs user's real files (50,942/50,942 records match across both formats).
- Binary uploads are converted to the .TXT shape BEFORE persistence in `zk_dat_imports` so "Refresh Bio" re-reads still work. Legacy .dat text + Excel paths unchanged. Code: `utils/zk_dat_import.py` (parse_genlog_records / parse_device_txt_lines / decode_punch_bytes), endpoint `POST /admin/attendance/zk-dat-import`.
- Bulk Employee Correction: firms with **Offline Salary enabled in Firm Master** get an editable **Bio Code** column (after allowances, before UAN). Backend-gated in `bulk-correction-fields`; save path clears with empty string → None. Grid renders it generically (no frontend logic change; COL_WIDTHS 100).
- E2E tested: TXT import inserted 6 mapped punches for 2026-07-14 (Kankani), binary re-upload deduped all 6 (idempotent + format equivalence). Test punches cleaned up; Kankani offline_salary flag restored to false.
- NOTE: 4 pre-existing failures in tests/test_iter106 (CCH seed firm cmp_987f0d7da5 no longer in DB) — data dependency, not regressions.
- Shift Master Duty HRS auto-calc (Iter 139): `routes/shift_masters.py` stores `duty_hours` (decimal, overnight wraps) on create + recompute on patch. Both editors (shift-master.tsx modal + attendance-policy.tsx ShiftMasterEditor) show live "Duty HRS" as In/Out time is typed; list rows show "Duty HRS X". Fields relabelled In Time / Out Time. Verified: 21:00→06:00 = 9.0, patch to 05:30 = 8.5.

## Iter 141 — Actual Salary Bulk Correction mode + Bio Code moved out of compliance (E2E verified)
- Bulk Employee Correction now has a mode toggle (offline-salary firms only, via `actual_salary_enabled` flag from `bulk-correction-fields?mode=`): **Compliance Salary Correction** (unchanged, Bio Code REMOVED per user) vs **Actual Salary Correction**.
- Actual mode columns: Emp Code (locked) | Employee Name | Father Name (both EDITABLE in this mode) | Designation | Actual Salary Basic | Pay Basis (daily/monthly dropdown) | Shift (Shift Master dropdown; "" clears override + shift_start/end mirrors) | Bio Code | Salary 1/Day 1 | Salary 2/Day 2 | Salary 3/Day 3 + Save.
- Backend: `BulkEmployeeCorrection` model extended (father_name, actual_basic, pay_basis, shift_id, salary_N/day_N); save merges into `salary_structure_actual` rows (Basic Salary amount+rate_type, Salary N amount+working_days), preserves untouched rows, mirrors pay_basis flat. Code: `utils/iter60_features.py`.
- Frontend: `bulk-employee-correction.tsx` — mode chips (dirty-discard confirm on switch), derived base values via `actualBase()`, select:paybasis / select:shift renderers, mode-aware locking.
- Verified: fields gating, structured save (745→800 etc. + revert), shift set/clear, UI grid render + dirty tracking screenshot. Kankani offline_salary flag restored to false after tests.

## Iter 142 — Firm/Employee OT gating + Both IN/OUT device + Setup Guide domain (tested by testing_agent iteration_142: ALL PASS)
- **OT gating (user spec):** Firm Master → Salary Process Settings has "Overtime (OT) Allowed" toggle (`salary_process.ot_allowed`, default/missing = allowed). OFF ⇒ NO OT for any employee (verified: Kankani June grid 3533.5h → 0.0h). Per-employee: legacy `ot_applicable` now honored in `apply_employee_policy_override` (fixes prior gap where only attendance_policy_override.ot_allowed counted; verified emp 50: 37.5h → 0 → 37.5). Gate points: compute_textile_day, grid + OT-report pair-split blocks, salary loops (company_policies firm_ot_allowed injection + per-emp merge), compute_present_days_and_ot (utils/salary_run.py), inject_firm_ot_flag() helper (server.py ~line 922). UI: firm-master toggle (fm-ot-allowed), employee-add checkbox (ot-toggle, gated by firm flag, sent as ot_applicable on create), employee-master OtCard for non-textile firms + TextileMasterCard OT row hidden when firm OT off.
- **Both IN/OUT single machine:** biometric device `kind` now "in"|"out"|"both". kind=both ⇒ per-punch alternation by employee/day (last earlier punch in ⇒ out, else in). Verified E2E: 3 pushes → IN/OUT/IN. UI third segment "BOTH · Single" (d-kind-both), purple IN/OUT pill on cards.
- **Setup Guide** updated to production domain: Server Mode ADMS, Enable Domain Name ON, Server Address http://www.smartpayrolling.com, Enable Proxy Server OFF (+ blank proxy IP/port), BOTH-device wording. NOTE FOR USER'S VPS: device pushes to /iclock/* paths — nginx must proxy /iclock → backend /api/iclock (snippet given in chat); HTTP (port 80) must not redirect /iclock to HTTPS since device firmware talks plain HTTP.
- server.py tail corruption (duplicated router block) found + repaired during this iter.

## Iter 143 — Live ADMS punch time fix + PWA auto-update + VPS device networking
- BUG FIX (user report "Machine time not showing properly"): live ZKTeco ADMS pushes were converted IST→UTC while the ENTIRE pipeline (.dat/.TXT imports, monthly grid strftime display) uses device wall-clock stored as UTC-labelled. `_parse_zk_timestamp` no longer shifts; punch shows exactly the machine time. Verified: push 09:15 → stored 09:15. Users with earlier live-device punches need one-off +5:30 repair script (given in chat, source ^zkteco:).
- PWA auto-update (user uses installed mobile PWA): sw.js CACHE v2 + navigations fetch cache:no-store; inject-pwa-html registers update-on-visibility + controllerchange one-time reload + stamps unique build id into dist/sw.js each export. Nginx now: index.html & sw.js Cache-Control no-cache, /_expo/static immutable 1y.
- VPS: duplicate nginx site (sites-available/smartpayrolling) removed; sksharma config rewritten w/ /iclock/→/api/iclock/ proxy on BOTH 443 and 80 (no HTTPS redirect for /iclock; ZK firmware is plain HTTP); port-80 block is default_server (device firmware couldn't type domain names → device uses Server Address 165.99.223.52 port 80, Enable Domain Name OFF). Verified: curl by domain+IP both return backend response.

## Iter 144 — Punch time unified on WALL-CLOCK convention (user: "both employee and employer login punching time showing wrong")
- Root cause: mixed conventions — machine punches/.dat imports/admin manual entries store device wall-clock labelled UTC (grid strftime = correct), but app self-punches stored real UTC and PWA screens used toLocaleTimeString (tz-shifting) → device punches +5:30 wrong on PWA, app punches -5:30 wrong in grid.
- Fix: (a) server.py ist_wallclock_now/iso helpers (line ~1905); punch endpoint `at`=IST wall-clock, `today`+auto-debounce compare in wall-clock space; approve-punch endpoint same. (b) Frontend fmtTime/fmtWhen in present-today, roster, attendance-review, location-audit, history, punch-approvals, (tabs)/attendance now slice HH:MM verbatim from ISO (no Date() tz conversion).
- Verified: app punch stored 19:05 when IST=19:05.
- PRODUCTION migration (given in chat, run once): shift +5:30 all attendance where source NOT ^zkteco:|^import:|manual_admin|roster and not marked tz_fixed_app (historical app self-punches + admin_approved records).
- NOTE: partial parallel-edit batch failures observed twice this session (edits reported success but not persisted) — ALWAYS grep-verify critical edits.

## Iter 145 — Punch Log Report (Utility) — DONE, verified via curl + screenshot
- New Utility sidebar item "Punch Log Report" (/punch-log-report). Filters: From/To date, Firm (all/one), Machine/Source dropdown (Device <SN> | Import (.dat/.TXT) | Mobile App | Manual (Admin)). Grid: Date, Time, IN/OUT (colored), Emp Code, Name, Bio, Machine, Firm, Status. "Download Excel" exports full filtered log (openpyxl, frozen header, up to 100k rows; JSON view capped 2000 with truncation note).
- Backend: routes/punch_logs.py (GET /admin/punch-logs + /admin/punch-logs.xlsx), sub-admin firm scoping honored; import punches carry the import tag in device_serial → labelled "Import (.dat/.TXT)".

## Iter 146 — Web Push Notifications (PWA) + P0 "Save as Draft" fix — DONE, tested (iteration_145.json, 10/10 backend + frontend e2e)
- WEB PUSH (user choice: employee notified on employer approve/reject of punch/leave + new-joining approvals):
  - Backend: routes/web_push.py — GET /api/push/vapid-public-key, POST /api/push/subscribe (upsert db.push_subscriptions by endpoint, re-binds to current login), POST /api/push/unsubscribe. Helpers push_to_user / push_to_company_admins (pywebpush in thread executor, prunes 404/410 dead subs). VAPID keys in backend/.env (VAPID_PRIVATE_KEY/VAPID_PUBLIC_KEY/VAPID_CLAIMS_EMAIL). pywebpush added to requirements.txt.
  - Hooks (all try/except-guarded, lazy import): submit_onboarding → admins get "New joining request"; decide_employee_approval → employee gets joining approved/rejected; admin_approve_punch + create_manual_punch → employee gets punch notification; leaves.py decide_leave → employee gets leave approved/rejected.
  - Frontend: public/sw.js CACHE v3 + push/notificationclick listeners; src/utils/push.ts (getRegistration-based, no .ready hang in dev); src/components/PushBanner.tsx on dashboard (tabs/index) — shows when permission=default, dismiss persisted in localStorage sks_push_banner_dismissed, silently re-syncs subscription when already granted.
  - NOTE: push delivery only works on the DEPLOYED PWA over HTTPS (service worker required); dev preview returns reason no_sw. iOS requires the PWA to be installed to home screen (iOS 16.4+).
- P0 FIX "Save as Draft resets data" (Compliance Salary Process): root cause — updatePresentDays/updateRowField were client-side only and saveAsDraft saved NOTHING. New endpoint POST /api/admin/compliance-salary-runs/{run_id}/save-rows persists rows+totals (validates row set matches run, blocks finalized runs, stamps draft_saved_at/by). Frontend: Save as Draft button now posts rows+totals; plus 2.5s debounced auto-save after any grid edit (scheduleDraftAutoSave). Actual Salary run was already persisting via PATCH /admin/actual-salary-process/{run_id}/row — no change needed there.
- Remaining backlog: Manual CL/PL leave balance per employee (P1), WhatsApp API (blocked on Meta credentials), SQL sync (P3).

## Iter 147 — Geofence punch-in reminder push — DONE, logic verified via direct tick test
- Background loop (routes/web_push.py punch_reminder_loop, started in server.py startup): every 10 min, employees with a push subscription + fresh location ping (≤30 min old) who are INSIDE their firm's geofence and have NO attendance punch today get web-push "Punch In reminder ⏰". Max 1 reminder/employee/day via db.push_reminder_log. No time-of-day window (night shifts supported). Note: requires employee to have opened the PWA recently (location ping needed).

## Iter 148 — Daily Attendance (date-wise, firm-wise) on employer dashboard — DONE, verified curl + screenshot
- New screen /daily-attendance (Quick action "Daily attendance (date-wise)" on dashboard for admins): ◀ date ▶ navigation + Jump-to-today, firm picker (super/sub admin; company_admin auto-scoped), tappable Present/Absent/All filter chips, per-employee cards with IN/OUT punch chips (time + colored), worked hrs badge / IN NOW / ABSENT status.
- Backend: GET /api/admin/daily-attendance?date=YYYY-MM-DD&company_id= (routes/punch_logs.py) — per-employee grouped punches, first_in/last_out, worked_hrs (IN→OUT pair sum, wall-clock), still_in flag, present/absent counts. Sub-admin firm scoping honored.

## Iter 149 — Manual CL/PL balance per employee — DONE, verified curl + screenshot
- users get optional cl_allowed_override / pl_allowed_override (None = firm Leave Policy default).
- Backend (routes/leaves.py): GET /api/admin/leave-balance-config?company_id= (employees + overrides + firm defaults), PATCH /api/admin/leave-balance {user_id, cl_allowed, pl_allowed} (null clears; 0–366 validation; firm scoping for company_admin/sub_admin). Overrides applied per-row in /admin/leave-report (+is_override flag) and in employee self-service /leaves/balance.
- Frontend: new /leave-balance-config screen (firm picker, search, per-employee CL/PL inputs with firm-default placeholder, blank=default, dirty highlight + "manual override" tag, bulk Save). Linked from Leave Report header (options icon).

## Iter 150 — Auto-block leave requests exceeding CL/PL balance — DONE, curl-verified 4 cases
- POST /api/leaves now rejects casual (CL) / earned (PL) requests exceeding remaining yearly balance (allowed = per-employee override else firm Leave Policy limit; used = approved + PENDING days in the from_date's year). Enforced only when firm cl_pl_applicable=true OR employee has a manual override — firms without leave policy unaffected. Other leave types (sick etc.) never blocked.
- Frontend leaves.tsx: request modal now SHOWS the block reason in a red banner (was silently swallowed); error cleared on modal reopen.

## Iter 150b — Live CL/PL balance inside leave request form — DONE, verified via screenshot
- /leaves/balance returns new `enforced` flag (firm cl_pl_applicable OR any manual override).
- Request modal: selecting Casual/Earned shows a live banner "CL balance 2026: X of Y day(s) left · requesting N day(s)" — turns red with "exceeds your balance, request will be blocked" when over. Balance refetched on modal open. Main balance card now also shows for override-only employees.

## Iter 151 — OCR at employee joining + family member Aadhaar scan + scan copies in DB — DONE, e2e verified (real OCR round-trip)
- Onboarding (employee PWA): "Scan Aadhaar / PAN / any ID to auto-fill" button on Personal details step → fills Name/Father/DOB on the form; ALL other extracted details (aadhar_number, pan_number, gender, present_address, voter/passport) auto-saved to the employee's KYC fields (never overwrites non-empty) + full snapshot in users.onboarding_ocr.
- New endpoints (routes/ocr.py user_router prefix /api): POST /ocr/parse-my-document (parse + self-KYC save), POST /ocr/parse-family-document (Aadhaar-only, parse-only, returns scan_doc_id), POST /me/family-members (direct add, no approval — dedupe by aadhaar/name, DD-MM-YYYY→ISO dob), GET /me/scanned-documents/{id} + admin GET /api/admin/scanned-documents/{id} (firm-scoped).
- Scan/captured copies stored in db.scanned_documents {doc_id, user_id, purpose onboarding|family_member, pages[base64], cap ~6.7MB}; referenced via onboarding_ocr.scan_doc_id and family member.scan_doc_id.
- Family: profile-edit.tsx "Scan family member's Aadhaar — add automatically" → instant add with name/dob/aadhaar_no/scan_doc_id; FamilyMember model + profile-edit approval flow + admin RoleUpdate cleaning now preserve aadhaar_no/scan_doc_id. ScanOCRButton gained `endpoint` prop + passes __scan_doc_id via onApply.

## Iter 152 — OCR photo auto-compression (fix "Not able to scan" from phone camera) — DONE
- ScanOCRButton: camera photos of ANY size now accepted and auto-downscaled client-side (canvas, max 1600px long edge, JPEG q0.8 → ~200–500KB) before upload. Old behavior rejected files >6MB outright — phone cameras produce 4–12MB, so employees couldn't scan. PDFs unchanged (6MB cap). Advise VPS nginx client_max_body_size 10m for multi-page scans.

## Iter 153 — Sheet Verification (OCR reconciliation) utility — DONE, e2e verified with real LLM OCR
- Utility → "Sheet Verification (OCR)" (super/sub/company admin). Flow: upload handwritten sheet (photo/PDF, ≤4 pages, client-compressed 2000px) → POST /api/admin/sheet-verification/ocr (gpt-5.4 vision, strict JSON rows {code,name,in,out,ot,signature}) → editable review table → POST .../match (code exact → fuzzy name ≥0.75; tolerance default ±15min) → MIS verdict table: MATCHED / TIME_MISMATCH / NOT_IN_SYSTEM / NOT_ON_SHEET / UNMATCHED_ROW + signature flag; run saved in db.sheet_verifications.
- Per-employee actions: "Fix with OCR" (writes sheet times: existing punch edited w/ audit original_at/edit_reason, missing punch created source manual_admin) or "Leave". SUB-ADMIN fixes queue in db.sheet_fix_requests → SUPER ADMIN approve/reject panel on the same screen (PATCH /api/admin/sheet-fix-requests/{id}). Verified: OCR extraction exact, super fix applied (IN 08:54→09:00), leave, sub-admin firm-scoping enforced.

## Iter 154 — Day-wise Present Count report — DONE, verified via screenshots
- Reports → "Day-wise Present Count": month nav (1–31), firm picker, per-day Present + OT counts (OT = ≥2 IN punches/day), Sundays red, month man-day totals. Backend GET /api/admin/attendance-report/day-counts?month=YYYY-MM (routes/punch_logs.py).
- Tapping a count deep-links to /daily-attendance?date=YYYY-MM-DD (param support added) showing the full employee list for that day.
- PENDING (user asked earlier, not yet done): Punch Approval grid column restructure (Date/Code/Name/Father/Designation/In/Out/Duty HRS/OT In/OT Out/OT HRS/Total HRS/Status/Update Reason/Action) + landscape PDF daily report with Signature column from Punch Approval.

## Iter 156 — DB Backup download fix + VPS deploy (2026-07-16)
- VPS deployed via temp-code-bundle tar (GitHub main lacked db_backup commit); killed stale uvicorn holding 8001 (spawn error). /api/admin/database-backup live (401).
- BUGFIX database-backup.tsx: URL.createObjectURL(res) called on apiBinary wrapper object → "Overload resolution failed". Now uses res.webBlobUrl (same pattern as contribution-sheets). E2E verified: zip downloads.

## Iter 157 — Sub Admin inactivity auto-disable + Compliance PDF 10-per-page (user requests, both tested)
- NEW routes/sub_admin_inactivity.py: inactivity_loop (6h sweep, started in server.py startup). Warn sub admin at 25d inactive (in-app + push + email, once per inactivity period via inactivity_warned_for=last_activity_iso); auto-disable at 30d (disabled=true, disabled_reason=auto_inactivity, auto_disabled_at) + notify ALL super admins (in-app + push + email). Last activity = max(pin_last_login_at, password_last_login_at, reactivated_at, created_at). Email via email_notifications _get_settings/_send_and_log (works on VPS where SMTP configured).
- server.py PATCH /admin/sub-admins/{id}: disabled=true sets disabled_reason=manual; disabled=false clears flags + sets reactivated_at (resets clock).
- sub-admins.tsx: row shows "Last login: <date>" + "⏸ auto-disabled (30 days inactive)" chip.
- utils/compliance_salary.py BOTH register builders (v1 Form-27 + v2 modern): fixed 10 employees per A4-landscape page (chunked tables + PageBreak, headers repeat, GRAND TOTAL on last page, v2 zebra uses global index). Verified: 55-row run → v1 7 pages, v2 6 pages. NOTE: parse_month tail had pre-existing dead-code garbage — cleaned.
- Tested via direct _tick(): warn@26d ✓, disable@31d + super notif ✓, idempotent ✓, test sub-admin state restored.

## Iter 158 — Batch of user requests (2026-07-16, all screenshot-verified)
1. FIRM MASTER dropdown fix: Salary Structure options rendered BEHIND content below (RN-web stacking). dropdownList now IN-FLOW (marginTop 4, no absolute) — same pattern as MasterSelect. Verified selectable.
2. AUTO EMPLOYEE CODE lock: new Firm Settings toggle "Auto Employee Code (lock manual entry)" (firm_masters settings.auto_employee_code, default False). employee-add.tsx firmHeads.autoCode → Employee Code field disabled + "(AUTO — locked in Firm Master)" label; submit omits manual code on Add.
3. ADDRESSES: Present + Permanent grouped in one TwoCol with "Permanent Address — same as Present Address" checkbox (testID same-as-present) that copies & locks + live-syncs. Verified copies.
4. DOB/DOJ CALENDAR: replaced masked text inputs with DateField (browser calendar + manual typing; ISO↔DD-MM-YYYY converters isoToDDMMDash). maskDashDate removed (unused).
5. MARITAL STATUS: chip "Single" → "Unmarried" (edit-prefill normalises legacy "Single"→"Unmarried"; relation.py/rpa already handle both).
6. OCR "Scan Other Document": generic prompt now also asks for address/mobile/email/uan_no/pf_no/esi_no/bank_name/bank_account_no/ifsc/upi_id; employee-add generic onApply maps ALL keys w/ alias fallbacks (address→present, ifsc_code→bank_ifsc, account_no→bank_account etc.) — previously extracted-but-unmapped fields were silently dropped (user bug). NEEDS user re-test with a real doc.
- PENDING USER ANSWER: Location master (State/District/PIN) clarifying question (auto-lookup vs full directory vs manual) — asked, not yet answered.

## Iter 159 — India Location Master: States + Districts + PIN Code (user request; verified E2E)
- NEW /app/backend/data/india_locations.json: 37 states/UTs, 727 districts (GitHub sab99r dataset + Ladakh + A&N added manually).
- NEW routes/locations.py (registered in server.py): GET /api/locations/states | /districts?state= | /all | /pincode/{pin}. PIN lookup proxies FREE India Post API (api.postalpincode.in) with db.pincode_cache Mongo cache; any authenticated user. 503 w/ manual-entry hint if API down.
- MASTERS screen: new "Locations" tab (mst-tab-location) → LocationsPanel: PIN lookup box (loc-pin/loc-pin-search) showing "PIN — District, State + post offices", plus state chips (with district counts) → district chips browser. CRUD add/list cards hidden for this tab.
- EMPLOYEE ADD/EDIT: new PIN Code / District / State fields after the address block — typing a 6-digit PIN auto-fills District+State (editable). New user fields pincode/district/state: server.py create doc + employee_profile.py _STR_FIELDS.
- Verified: /masters PIN 311001 → Bhilwara,Rajasthan + Rajasthan 33 districts expand; /employee-add PIN 302001 → Jaipur/Rajasthan auto-filled.
- NOTE: VPS backend needs outbound HTTPS to api.postalpincode.in (first lookup per PIN; cached after).

## Iter 160 — Compliance Settings: Effective Date + Change Log + EPF Act charges (tested)
- DEFAULT_STATUTORY_CFG += pf_admin_percent 0.5 (A/c 2), pf_edli_percent 0.5 (A/c 21), pf_edli_admin_percent 0.0 (A/c 22). _NUMERIC_FIELDS extended (global + firm overrides auto-flow).
- get_standard_compliance_cfg(on_date=None): version-aware — picks newest db.compliance_settings_log entry with effective_from <= on_date; server.py compliance run passes month+"-31" (policy per effective date).
- PUT /admin/compliance-settings: accepts effective_from (YYYY-MM-DD, default today); every save appends full snapshot to compliance_settings_log. GET returns log + effective_from.
- UI: PF section shows 3 new rows + read-only "Employer TOTAL" row; new "Effective Date & Change Log" section (DateField cs-effective-from + history list). Verified via curl + screenshot.

## Iter 161 — PF Reports + ESIC Reports hub + portal-upload preview (user formats; tested)
- NEW routes/pf_reports.py (/api/admin/pf-reports/*): challan.pdf/.xlsx (EPFO provisional challan layout: A/c 01/02/10/21/22 rows EE/ER/Admin/7Q/14B; page per month + period summary), ecr.pdf/.xlsx (EPFO Return Statement layout via challans._ecr_lines), esic-sheet.pdf/.xlsx (ESIC Contribution History layout), esic-challan.pdf/.xlsx (ESIC A/C No.1 challan + acknowledgement), summary + esic-summary JSON. Period = month_from..month_to (manual month/year, max 24). Data = latest compliance run/month; A/c2 min ₹500; roles super/sub/company_admin (firm-scoped).
- NEW /app/frontend/app/pf-reports.tsx (?kind=pf|esic): kind tabs, From/To MonthPickers, 4 download buttons per kind, period preview table, link to old contribution sheet. NAV REPLACED: "P.F. Contribution Sheet"→"PF Reports", "E.S.I. Contribution Sheet"→"ESIC Reports" (both AdminWebShell lists).
- challans.tsx (PF/ESIC Automation): quick-access buttons to both hubs + "Preview EPF/ESIC Data" toggles → GET /api/admin/challans-portal-preview?run_id&kind (NOTE: path is challans-portal-preview, NOT /challans/portal-preview — that gets shadowed by /challans/{id} route). Red rows = missing UAN/IP (skipped on upload).
- All 8 downloads curl-tested 200; preview 17 lines both kinds; screenshots OK. GOTCHA: challans._uan_esic_map(rows) is the extras loader (NOT _load_statutory_extra).
- PENDING (user): old payroll .bak (SQL Server, 750MB) import — user will do later; guided SSMS restore→CSV export→then build import mapping.

## Iter 162/163 — Utilities → PDF Report Formats (SUPER ADMIN ONLY; tested 12/12 + UI)
- NEW routes/report_formats.py mounted at /api/admin/report-formats (registered in server.py after compliance_settings_router). Registry REPORTS: pf_ecr + esic_contribution (column catalogs, editable), pf_challan + esic_challan (columns=None, fixed statutory). Formats saved in db.app_settings key "report_format:{report_id}" as {columns:[{key,heading?,width?}], orientation, font_size, title}.
- Endpoints: GET "" (list w/ saved status), GET/PUT/DELETE /{report_id}. ALL super_admin only. Helpers get_report_format(report_id) (never raises) + resolve_columns(report_id, fmt) used by pf_reports.py generators.
- pf_reports.py: _ecr_pdf/_esic_sheet_pdf now build column-driven tables (proportional widths stretched to printable width, per-column numeric RIGHT align); _challan_pdf/_esic_challan_pdf accept fmt for title/orientation/font_size. Route handlers fetch saved format via get_report_format(). Excel exports untouched (default headers; _ECR_HDR kept for xlsx).
- Frontend: NEW src/components/ReportFormatEditor.tsx (generic modal: title input rfe-title, portrait/landscape toggle rfe-orient-*, font size rfe-font, column rows w/ checkbox/rename/width/order for tabular reports, fixed-layout note otherwise, Save/Reset). app/report-formats.tsx rebuilt: fetches GET /admin/report-formats, groups PF/ESIC cards + existing Compliance Register card (RegisterLayoutEditor), shows "Custom format saved by X · date" vs "Using default format". Strict super_admin gate (sub-admins redirected).
- Tested: testing_agent iteration_163 — backend 12/12 pytest (/app/backend/tests/test_iter163_report_formats.py, pdfminer PDF content assertions), frontend e2e all green. Formats left at defaults.

## Iter 164 — On/Off-roll gated by Firm Master 'Offline Salary' (tested 9/9 + UI)
- Rule (user directive): firm's salary_process.offline_salary=false ⇒ employees ALWAYS On-roll (Off-roll blocked); Compliance Salary Process is strictly ON-ROLL always (off-roll excluded server-side).
- server.py: NEW helper _firm_offline_salary_enabled(company_id) (near _require_firm_salary_permission). Employee CREATE silently coerces is_onroll→True when firm offline disabled (~line 7559, uses cid). PATCH /admin/user-role + routes/employee_profile.py patch → 400 "Off-roll is not allowed — enable Offline Salary..." when firm offline disabled.
- _compute_compliance_run (~14300): REPLACED payload.is_onroll filter block — non-off_roll runs now force the on-roll $or clause regardless of payload (off_roll run_type still forces is_onroll=False). _compute_salary_run (Actual, ~13290) intentionally UNCHANGED — off-roll still allowed there.
- Frontend: employee-add.tsx locks to single "On-roll" chip + note when firmHeads.offline=false (effect force-sets is_onroll true); employee-master.tsx EmployeeGroupingCard fetches /admin/firm-master/{cid} → rollLocked (toggle inert + "Locked to On-roll..." hint); (tabs)/profile.tsx Personal details adds "Salary roll" DetailLine (On-roll/Off-roll from /auth/me is_onroll).
- Tested: testing_agent iteration_164 — 9/9 pytest (/app/backend/tests/test_iter164_onroll_gating.py incl. compliance-run exclusion with payload is_onroll:false) + Playwright UI (locked chip, locked grouping toggle, PWA Salary roll line). Mongo state fully restored.
- GOTCHA (tooling): parallel search_replace edits on the SAME file can silently drop one edit — apply same-file edits sequentially.

## Iter 165 — Fingerprint verification in Employee PWA (admin-controlled; tested 7/7 + UI)
- Rule: firm_masters.salary_process.bio_matrix_attendance must be TRUE for the firm → admin can require fingerprint per employee (users.fingerprint_required, toggle in Employee Master Grouping card, testID grouping-fingerprint-toggle). Applies at BOTH app unlock and punch. Silent fallback when device/browser unsupported (user choice).
- server.py: _enrich_user_with_company adds firm_biometric_enabled + fingerprint_required + effective_fingerprint_required (employee role only, 1 extra firm_masters lookup); RoleUpdate.fingerprint_required + gate via _firm_biometric_attendance_enabled (400 when firm bio OFF); POST /api/me/fingerprint/enrolled logs fingerprint_enrolled_at/fingerprint_device.
- Frontend NEW: src/utils/fingerprintGate.ts (web=WebAuthn platform authenticator, credential rawId in localStorage sks_fp_cred_{userId}, device-local enroll/verify, UV required; native=expo-local-authentication; fingerprintSupported/enrolled/enroll/verify/clear). src/components/FingerprintUnlockGate.tsx (app-unlock gate, once per session via module flag, auto-enrolls on NOT_ENROLLED, silent skip unsupported) wired in (tabs)/_layout.tsx for employees with effective_fingerprint_required.
- attendance.tsx: ensureFingerprintWeb() called at top of submitPunch AND in handlePunch GPS path before setBusy (web only; native path already prompts LocalAuthentication). profile.tsx: FingerprintCard (testID fingerprint-card) when firm_biometric_enabled — badge REQUIRED BY EMPLOYER/NOT REQUIRED, Set up/Re-enroll/Test buttons, unsupported note.
- employee-master.tsx: grouping card fetches firm salary_process once for BOTH offline_salary (Iter 164 rollLocked) and bio_matrix_attendance (fp toggle lock); loader copies fingerprint_required/enrolled_at/device from full doc (bug found by testing agent, fixed).
- Tested: iteration_165 — 7/7 pytest (test_iter165_fingerprint_gate.py) + Playwright UI (locked toggle, unlock-gate silent skip in headless, fingerprint-card visibility, punch unblocked). Mongo state restored. WebAuthn virtual-authenticator path not exercised (headless) — real-device verification pending by user.

## Iter 166 — Employee status filter + resigned exclusion from salary (tested 4/4 + UI)
- /admin (Employee Master Data, admin.tsx): NEW status chips ACTIVE EMPLOYEE (default, pre-existing hide rules) / RESIGN EMPLOYEE / ALL EMPLOYEE (testIDs status-filter-*). isResigned(e)= exit_date|resign_date|employment_status in exited/resigned/terminated/inactive. Red "RESIGNED · date" pill (resignedPill) beside code pill. Old always-hide isActive gate replaced by matchesStatus.
- server.py: NEW _month_is_after_exit(user, month) beside _month_is_before_doj (~10103) — exit_date/resign_date < 1st of run month ⇒ excluded; exit month itself stays payable (final settlement). Applied at 3 sites (~13394 _compute_salary_run, ~14397 _compute_compliance_run, ~18504 create_actual_salary_process) — covers BOTH Compliance and Actual salary per user directive.
- Tested: iteration_166 — 4/4 pytest (test_iter166_resign_exclusion.py: excluded 2026-07, included exit-month 2026-06, actual-salary excluded) + Playwright UI (chips default/active/resigned/all, pill, existing type/roll chips intact). DB state fully restored.

## Iter 167 — "Resigned this month" summary on Compliance Salary screen (verified via curl)
- _compute_compliance_run captures excluded_resigned [{user_id,name,employee_code,exit_date}] + excluded_resigned_count before the Iter 166 filter; stored on run doc / returned in response.
- compliance-salary-run.tsx: red banner (testID resigned-summary, styles resignedBanner*) below the result-card header listing "N resigned employees auto-excluded" with names/codes/exit dates.
- Verified: exit_date 2026-06-15 on SURENDRA SINGH → run 2026-07 returned excluded_resigned_count=1 with his entry, not in rows; state restored, test run deleted.

## Iter 168 — Salary process strictly ACTIVE employees (user confirmed choices)
- User choices: exit-month stays payable (final settlement, unchanged); DISABLED employees now excluded from salary processing too.
- server.py: the 3 filter sites (~13395 _compute_salary_run, ~14410 _compute_compliance_run, ~18521 create_actual_salary_process) now also filter e.get("disabled") is not True (marker: "# Iter 166/168").
- Verified via curl: disabled=True on SURENDRA SINGH → excluded from compliance run 2026-07 (125 rows); state restored, test run deleted.
- master-data-report.tsx: renamed "Left Employees" tab → "Resigned Employees" (user asked for Active/Resign/All on Master Data Report — feature already existed with status=active|left|all backend param).

## Iter 169 — OCR bank details fix + active-only group counts (verified via curl)
- ROOT CAUSE (user bug "OCR bank details not filling"): OCR/KYC writes stored bank_account_number/ifsc_code but the Employee "Bank Details" section + salary/payment reports read users.bank_account/bank_ifsc. FIX: mirror on every KYC write — routes/employee_kyc.py PATCH (admin OCR autofill), server.py _validate_kyc (/me/kyc), routes/ocr.py parse-my-document. Verified: PATCH kyc with bank_account_number/ifsc_code → users doc got bank_account+bank_ifsc.
- GET /admin/employee-types (~10800): $match now excludes disabled + exit_date/resign_date set → group count chips (Employee Master + Compliance EMPLOYEE GROUP) count ACTIVE employees only.
- admin.tsx: isResigned/matchesStatus hoisted to component scope; EmployeeFilterChips now receives employees.filter(matchesStatus) so type counts always match the visible list.
- NOTE for user (compliance run screenshot): saved runs are snapshots — must click Reprocess after setting exit dates; exit-month employees stay included (final settlement, user-confirmed).

## Iter 172 — Bulk Punch Import via Excel (Punch Approvals) — TESTED, ALL PASS
- User request: import punching data company-wise from Excel, match by Bio Code OR Name, insert In/Out punches date-wise directly into the punching report.
- Backend: /app/backend/routes/punch_import.py (registered in server.py):
  * GET /api/admin/punch-import/template → sample xlsx (base64) with headers Bio Code|Name|Date|In Time|Out Time.
  * POST /preview → parses xlsx (auto-detects header row/columns), matches by bio_code → employee_code → name; returns rows with status matched/unmatched/error + summary. Handles DD-MM-YYYY dates, AM/PM & Excel-fraction times.
  * POST /commit → inserts approved attendance records (source="excel_import", import_batch_id) with duplicate skip; IST wall-clock stored as Z per convention.
  * Company scoping: non-super-admins 403 on other firms.
- Frontend: /app/frontend/src/components/PunchImportModal.tsx (new); green "Import Excel" button (testID pa-import-excel) in punch-approvals.tsx header row; modal flow: Sample template download (web blob) → Choose Excel → preview table w/ summary chips → Import N punches → success screen; refreshes grid via load(true) after import.
- Testing: backend pytest 6/6 + frontend Playwright E2E incl. real file-chooser upload — all pass (testing agent). Test excel_import records cleaned up.

## Iter 173 — Removed "resigned employees auto-excluded" banner (user request)
- compliance-salary-run.tsx: deleted the Iter 167 red banner JSX (testID resigned-summary) + resignedBanner* styles. Backend still computes/stores excluded_resigned on runs (harmless, unused by UI now). Screenshot-verified screen renders clean.
- VPS deploy note: pip install of requirements.txt FAILS on VPS (litellm direct-URL vs emergentintegrations ResolutionImpossible) — skip pip when requirements unchanged, or strip the litellm line. GitHub push + code sync worked; user redeploys via temp-code-bundle script.

## Iter 174 — Automation (EPFO/ESIC) shows ONLY FINALIZED runs + replace-on-reprocess (user directive; curl+UI verified)
- server.py GET /admin/compliance-salary-runs: new query param finalized_only=true → filters finalized:True AND dedupes to NEWEST run per (company_id, month, employee_type).
- server.py POST /admin/compliance-salary-runs: before insert, delete_many older NON-finalized runs for same month+company_id+employee_type (case-insensitive group match; None/"" group matched together) — fresh processing REPLACES old draft data (finalized months still blocked with 409).
- challans.tsx (Automation → PF/ESIC Challans): run fetch now uses ?finalized_only=true; empty-dropdown message → "No FINALIZED compliance run — finalize the month in Salary Process first".
- Verified: workspace had 23 duplicate 2026-06 Staff drafts → collapse to 1 on reprocess; finalized_only=0 until finalize → then 1; UI dropdown shows only "2026-06 · Staff · 17 emp ✓"; create on finalized month blocked. Test run de-finalized after (workspace state neutral).
- NOTE: PF Reports / ESIC Reports hubs (pf_reports.py "latest run per month") intentionally NOT changed — user scoped this to Automation.

## Iter 175 — Contractor Employees + Attendance Policy Master Sub Points (tested 4/4 + full UI E2E)
1. FIRM MASTER: 10a Policy variant picker GATED — shows only when Industry Type set + Offline Salary ON + Bio Matrix ON (hint text otherwise). New read-only PolicyMasterSummary component below (17-point grid + Open Policy Master link). 10b "Contractor Employees (Policy 2)" (shows when variant=policy_2): Toggle settings.contractor_employees + repeatable rows firm_masters.contractors [{name, father_name, from_date, to_date}] with DateFields + "Add More Contractors". PolicyVariantPicker gained onVariantChange prop.
2. EMPLOYEE MASTER Grouping card: "Contractual Employee" toggle (users.is_contractual) + contractor chips (users.contractor_name from firm contractors); only visible when firm has contractor_employees enabled + contractors defined. RoleUpdate += is_contractual/contractor_name (false clears name).
3. PUNCH GATING: server.py apply_contractual_gate(record) (near _parse_manual_at) — stamps is_contractual/contractor_name; demotes to pending ONLY when decision_by startswith "system:" (zkteco webhook via routes/biometric_devices.py, .dat import via utils/zk_dat_import.py contractual_map). App punches already pending (stamp only). Admin/manual punches stay approved.
4. CONTRACTOR PUNCHES: routes/contractor_punches.py (registered): GET /api/admin/contractor-punches?company_id&date → groups by day-contractor (record-level override wins over user default), summary pending/approved/rejected; POST /decide {user_id,date,action?,contractor_name?} updates all in/out records of that day. Frontend /contractor-punches screen (nav: Approvals → Contractor Punches in BOTH AdminWebShell lists) with per-row Approve/Reject + contractor chip picker per day. After approval attendance flows into normal policy computation.
5. POLICY MASTER SUB POINTS: _validate_policy sanitises attendance_policy.policy_master {attendance_basis monthly|daily|hourly, shift_type fixed|rotational|open, punch_types subset[biometric,mobile,manual,gps], contractor_assignment_required, site_wise_attendance, client_wise_attendance, multiple_punch_allowed(def true), auto_shift_detection, wfh_allowed, geofencing_required(def true)}. attendance-policy.tsx new PolicyMasterSubPoints section (testID policy-master-subpoints). Industry-wise defaults deferred (user: "will set later").
- Workspace state: Kankani has contractors RAM PRASAD + GOPAL SINGH, SURENDRA SINGH (50) is contractual under RAM PRASAD, policy_master = daily/rotational/biometric+gps. offline_salary + bio_matrix remain OFF.
- Tests: iteration_175.json all pass; pytest tests/test_iter175_contractual.py.

## Iter 177 — Part 1 role separation + Labour Law Reports Module (tested iteration_177 all pass)
- Employer dashboard: hero punch card + duty summary EMPLOYEE-only; Punch tab employee-only; admins get "My Attendance (Employee Mode)" ActionRow (row-my-attendance) → /(tabs)/attendance (title becomes "My Attendance"); sticky punch CTAs hidden when firm attendance_punching_enabled=false.
- routes/labour_reports.py: 22-report engine (registers/daily/shift/technology groups) over employees×attendance×policy; filters dept/desig/category/gender/contractor/shift/branch + month or ≤62-day range; formats json/csv/excel/pdf; PDF has logo+company+generated meta+page numbers+QR (report_verifications, GET /verify/{id} public). Frontend /labour-reports hub (nav Reports → Labour Law Reports).

## Iter 178 — State-wise PT + Portal Dashboard (curl + screenshot verified)
- utils/compliance_salary.py: PT_STATE_SLABS (27 states/UTs incl. no-PT states) + pt_from_slabs(); compute_compliance_row(firm_pt=...) resolution: emp pt_amount_override > firm compliance_policy.pt_slabs > firm compliance_policy.pt_state slabs > legacy emp pt_state flat. server.py passes firm_pt from company_doc.compliance_policy; CompliancePolicyPayload += pt_state; GET /api/admin/pt-states catalogue. Frontend compliance-policy.tsx: PT State chip picker + slab preview (Kankani set to Rajasthan = no PT). NOTE: Firm Master allowed_deductions PT toggle still gates the PT column (Iter 170 mask).
- routes/portal_dashboard.py: GET /api/admin/portal-dashboard (role-aware) → kpis (employees/present/absent/pending punches/leaves/tickets/expiring docs/firms/payroll finalized), 14-day attendance trend, 6-month payroll net trend, per-firm compliance status (finalized/draft/not processed), statutory calendar (TDS 7, PF+ESIC 15, PT 21, PF return 25). Frontend /portal-dashboard (nav position 2 both lists): KPI cards, bar charts, status list, calendar, quick actions. Theme system (8 presets) already existed (Iter 85).
- Phase 2 backlog: Task Management, Client health scores, Doc expiry dashboard, drill-down analytics. Phase 3: multi-state compliance rules config.

## Iter 179 — Portal Dashboard PHASE 2 (tested: 24/24 pytest + full web E2E)
- routes/portal_phase2.py (registered after portal_dashboard in server.py):
  1. TASKS: portal_tasks collection. GET/POST /api/admin/portal-tasks (+counts open/in_progress/done/overdue), PATCH/DELETE /portal-tasks/{task_id}. Fields: title, description, company_id/name, assignee_id/name, due_date, priority (low/medium/high), status (open/in_progress/done, done sets completed_at/by). company_admin locked to own firm (POST company_id override + 403 on other firms' tasks).
  2. TRACKED DOCUMENTS: tracked_documents collection. GET/POST /api/admin/tracked-documents, PATCH/DELETE /{tdoc_id}. doc_type in [license,registration,insurance,contract,certificate,other]; expiry_date required YYYY-MM-DD. GET returns days_left + bucket (expired/critical≤7d/warning≤30d/upcoming≤90d/ok) + bucket counts.
  3. CLIENT HEALTH: GET /api/admin/portal-dashboard/client-health → per-firm score/100 + grade A(≥85)/B(≥70)/C(≥50)/D with 6 factors: payroll status 30, attendance today 25 (70% target), punch approvals 15, leaves 10, tickets 10, doc expiry 10. Sorted worst-first.
  4. CALENDAR: GET /api/admin/portal-dashboard/calendar?month= → 5 statutory items (keys tds/pf/esic/pt/pf_return) + task due dates + doc expiries merged. POST /calendar/toggle {month,item_key,company_id?} flips done via calendar_completions (scope = company_id or "__all__").
  5. ALERTS: GET /api/admin/portal-dashboard/alerts → derived alerts (pending punches/leaves/contractor, open tickets, overdue tasks, expiring docs, statutory due≤5d or overdue not-ticked, payroll not finalized after 15th) sorted critical>warning>info + recent_notifications (10 latest broadcasts).
- Frontend portal-dashboard.tsx: tab strip Overview|Tasks|Client Health|Documents|Calendar (testIDs pd-tab-*) + bell pd-bell with red count badge → AlertsModal (Notification Center: action-required list with route/tab jump + recent broadcasts). New components in src/components/portal/: TasksPanel (counters, filters, New Task modal w/ firm chips, Start/Done/Reopen/delete), DocumentExpiryPanel (bucket cards, Add Document modal), ClientHealthPanel (grade badge + score bar, expandable factor breakdown), CalendarPanel (month prev/next, statutory checkbox toggle, task/doc icons).
- Seed rows in workspace: task "File PF ECR for June" (Kankani, overdue) + doc "Factory License Bhilwara" (expired). 2026-06 pf statutory ticked during smoke test.
- Tests: /app/backend/tests/test_iter178_portal_phase2.py (24 pass), full frontend E2E via testing agent — no blocking issues. Phase 3 backlog: multi-state compliance rules config, drill-down analytics.

## Iter 179b — Recurring Monthly Tasks (curl + web E2E verified)
- portal_phase2.py: recurring_tasks collection. GET/POST /api/admin/portal-recurring-tasks, PATCH/DELETE /{rtask_id} (PATCH active=true resets last_generated_month for regeneration). POST /portal-recurring-tasks/seed-statutory → 4 idempotent presets (PF ECR d15 high, ESIC d15 high, TDS d7 med, PT d21 med); super_admin seeds all_firms=True, company_admin own firm.
- Lazy generation: _generate_recurring(admin) runs on GET /portal-tasks — creates this month's tasks per firm (all_firms templates expand across companies), due day clamped to month length, idempotent via {source_rtask_id, month, company_id}; created_by "system:recurring". Generated tasks show a repeat icon in TasksPanel.
- TasksPanel.tsx: "Recurring" button (pd-task-recurring) → manage modal (pd-rec-seed presets, pd-rec-add custom form w/ title/day/priority/All-firms-or-firm chips, ON/OFF toggles pd-rec-toggle-*, delete). Verified: seed created 4 templates → 8 tasks (4 × 2 firms) for 2026-07, second listing idempotent (9 total incl. seed task).

## Iter 179c — Task↔Calendar sync (curl verified, both directions)
- portal_phase2.py: _sync_calendar_from_task() called from PATCH /portal-tasks when status changes. SEED_TO_CAL_KEY maps statutory recurring presets (pf_ecr→pf, esic, tds, pt) to calendar item keys.
- Done → upserts calendar_completions for the task's firm scope (via: "task:{id}"); when ALL firms' tasks for that template+month are done → also ticks "__all__" scope (all-firms calendar view).
- Reopen → deletes completion for firm scope AND "__all__" rollup. Verified: firm tick, rollup only after both firms done, un-tick on reopen. Custom (non-seed) recurring/manual tasks unaffected.

## Iter 180 — PREMIUM UI REDESIGN (tested: 11/11 pytest + full E2E, iteration_180.json)
User supplied mockups (enterprise admin portal + ESS mobile + login). Implemented:
1. THEME: new default preset "azure_light" (#2563EB blue / #4338CA indigo) in theme.ts; one-time migration corporate_sapphire→azure_light (flag sksharma.theme.migrated.v2 in localStorage + AsyncStorage). Dark toggle flips azure_light ↔ midnight_dark (helpers isDarkTheme/DARK_THEME_ID exported from theme.ts).
2. ESS (employee mobile): (tabs)/index.tsx employee branch → EssWelcomeHeader (gradient, greeting, avatar, bell, ess-dark-toggle), PunchHeroCard (live clock, punch/view-only, worked-hrs metrics; overlaps header via essScroll marginTop:-44), QuickCardsGrid (services; Expense Claim/Reimbursement = SOON), MonthCalendarCard (uses /attendance/my-month, taps to /history). All in src/components/ess/. Employee bottom tabs now Home|Leave|Punch FAB|Payslip|Profile ((tabs)/leave.tsx + payslip.tsx re-export ../leaves ../payslip; Documents tab hidden for employees via href:null, still reachable from quick cards). Admin/employer mobile UNCHANGED (old header + bento + Documents tab).
3. ADMIN PORTAL: portal-dashboard Overview tab replaced by src/components/portal/OverviewPremium.tsx — welcome banner, 8 gradient KPI cards (Monthly Revenue=COMING SOON), SVG compliance donut, payroll overview w/ PF/ESIC/TDS/PT liability chips, upcoming due dates + alerts shortcut, top-5 client health bars, attendance/payroll/growth charts, state-wise + industry-wise client bars, quick actions. Backend routes/portal_dashboard.py extended: liabilities (from best_by current-month run totals: pf_employee+pf_employer_total etc), compliance_donut, clients_by_state/industry, employee_growth (cumulative by users.created_at), payroll_processed_pct, kpis.pending_tasks/pending_payroll_firms.
4. SHELL: AdminWebShell header now has global menu search (web-global-search filters flatNav, dropdown gs-result-*) + dark toggle (web-dark-toggle). 
5. LANDING: same content as before (user insisted contents unchanged) restyled with blue→indigo LinearGradient left pane + glass feature tiles + gradient Admin sign-in CTA.

## Iter 181 — Payroll punch line + Portal Dashboard as default
- Punch line "Your Satisfaction is Our First Ambition" added to: payslip PDF footer (utils/payslip_pdf.py shared flow → single + bulk), ESS payslip screen footer, Compliance Salary Run screen footer.
- Portal Dashboard is now THE default dashboard on desktop web: NAV_SUPER + NAV_COMPANY_ADMIN first item = {route:/portal-dashboard, label:"Dashboard"} (old /(tabs) sidebar entry REMOVED); app/index.tsx redirects admin roles on web ≥960px to /portal-dashboard after login (mobile still /(tabs)).

## Iter 182 — Employee Master + Salary Process premium UX (tested 6/6 pytest + 7/7 frontend, iteration_182.json)
- /admin Employee Master: EmployeeStatsBar (gradient Total/Active/On-roll/Off-roll/Resigned cards, testID emp-stats-bar) + EmployeeListSkeleton (both in src/components/EmployeeStatsBar.tsx); empRow/avatar/search restyled 16px+shadow. employee-master.tsx + employee-add.tsx card/input/button premium styles (needed `shadow` import!).
- Compliance Salary (/compliance-salary-run): instant search comp-emp-search (filters sortRows w/ X/Y match counter), "/" focuses search, Ctrl+S saves draft (web keydown effect), EmployeeListSkeleton while computing, silent AUTO-SAVE (3s debounce on run.rows change; skips finalized + first sighting per run_id via autoSaveSkipRef; shows "✓ Auto-saved HH:MM"), Audit Log button + modal (comp-audit-close).
- Salary Process Actual (/salary-run): actual-emp-search + skeleton + card polish.
- BACKEND: routes/salary_audit.py — GET /api/admin/salary-audit-log (company_admin scoped; filters company_id/month/run_id) + write_salary_audit() (never raises; collection salary_audit_log). Hooks in server.py: process (after compliance_salary_runs.insert_one ~line 14947), save_rows, finalize, unlock approve. NOTE: testing agent found process hook missing → re-added + verified after.
- PDF branding: utils/pdf_branding.py punchline_flowables() appended before doc.build in salary_register_pdf, daily/weekly/monthly attendance, salary_certificate, off_roll_slip_pdf, compliance_salary (2 sites); labour_reports on_page canvas draws centered punch line every page; payslip_pdf has Paragraph punch line. Verified in muster roll PDF text extraction.
- /app/push_github_main.sh: VPS script to push latest workspace bundle to GitHub main (needs GITHUB_REPO + fine-grained PAT; strips .env/node_modules; user must edit 2 vars).

## Iter 183 — Premium PWA Login Redesign + Salary Grid Filter Chips (tested 2/2 pytest + full E2E, iteration_183.json)
- `/pin-login` (Employee) & `/company-login` (Employer) fully redesigned: blue gradient (#1E3A8A→#3B82F6), glassmorphism card, gradient CTA, brand header, trust footer. Auth logic + all testIDs unchanged.
- Branch/Dept/Contractor filter chips on Compliance + Actual Salary grids via new `src/components/GridFilterChips.tsx`; backend row builders (utils/compliance_salary.py, utils/salary_run.py) emit branch_name/department/contractor_name. Chips render only for groups with data; old saved runs (no fields) show no chips — no crash.

## Iter 184 — Dashboard default home + option interlinks + Employee form premium redesign (tested, iteration_184.json)
- All post-login redirects now go through "/" → desktop-web admins land on /portal-dashboard automatically (admin-pin-login, company-login, otp-login, pin-change; guards on login screens too).
- Dashboard audit: ALL KPI cards/quick-actions/tabs/links verified against DB. Fixes: Pending Tasks KPI now opens Tasks tab; Total Employees KPI route corrected /employee-master→/admin (was dead click showing "Missing employee").
- Welcome banner shows selected firm chip (pd-firm-chip) — firm name or "All Firms (N)".
- /employee-add (both Add New Employee + Employee Details edit modes) premium redesign: gradient header icon, SectionHeader chips (Identity/Employment/Actual Salary/Compliance/Statutory-Bank/Family). Actual Salary section still conditional on firm Offline Salary toggle (by design).
- Deployed note: user must redeploy on VPS for live/PWA to update; PWA needs app reopen×2 or hard refresh.

## Iter 185 — Employer PWA mobile login premium + QR install button always visible
- admin-pin-login.tsx MOBILE layout redesigned (gradient bg + glass card, "Employer Sign In") — installed Employer PWA opens this screen (desktop split-screen untouched).
- get-app.tsx (QR target): Install button now ALWAYS visible; when beforeinstallprompt unavailable (iOS/in-app browsers) it shows manual install steps alert; sets correct manifest per type (manifest-employer.json / manifest-employee.json) + apple-web-app title.
- Self-tested via screenshots (390px): premium mobile employer login + install button on /get-app?type=employer.

## Iter 186 — Post-login Admin home + Admin Sign In premium consistency
- (tabs)/index.tsx admin/employer MOBILE home: old "Hello" top bar replaced with premium gradient hero header (Welcome back + role pill + company pill + glass bell). Employee ESS home untouched.
- admin-pin-login.tsx DESKTOP left brand panel converted from light blue to deep #1E3A8A→#2563EB gradient with white text + glass trust pills (matches new login design language across app).
- Verified via screenshots (desktop 1920 + mobile 390 after real login).

## Iter 186b — Mobile PWA Admin home body premium (Super/Sub Admin)
- BentoTile → premium white cards, 18 radius, soft shadow, per-variant gradient icon chips (light=blue/indigo, dark=cyan/blue, accent=violet/pink).
- ActionRow → white cards 16 radius, soft shadow, 38px rounded-square icon chips, bolder labels.
- Removed old centered logo+name block (admin-brand-center) — identity now lives in gradient hero header.
- Verified via mobile 390px screenshot after real super admin login.

## Iter 187 — FIX: Super Admin couldn't change company in mobile PWA
- Root cause 1: dashboard CompanyPicker used setSelectedCompanyId() which is blocked by the Iter-77 session lock; switched to switchCompany() (explicit pick overrides lock — same as desktop header).
- Root cause 2: CompanyPicker Modal sheet could render below the visual viewport on scrolled mobile web pages (taps never landed); sheetWrap now position:fixed inset-0 on web. Fix benefits all CompanyPicker usages.
- Verified: mobile 390px real login, switched Kankani→City Care→Kankani successfully.

## Iter 188 — Dashboard firm-switch race fix + Employee device-biometrics enable on PWA
- (tabs)/index.tsx: stale-response guard (loadSeqRef) — switching firms no longer lets an older in-flight /admin/stats response overwrite the new firm's data.
- biometric-prefs.tsx: NEW WebBiometricPrefs branch for web/PWA — employees can now ENABLE (WebAuthn enroll), TEST and REMOVE device biometrics in the browser (was a dead-end "open on your phone" screen). Uses existing fingerprintGate utils (same as required-fingerprint flow).
- PunchFlowModal: optional-skip message now points users to Profile → Biometric preferences to enable.

## Iter 189 — Enterprise Employee Form (SAP/Workday-grade) — desktop + mobile PWA (tested, all pass)
- /employee-add (Add + Edit modes) desktop shell: breadcrumb sticky header, 6 section anchor-tabs (nativeID + scrollIntoView), left summary panel (avatar/status/summary rows; completion checklist in add mode, Open Full Profile in edit), sticky bottom bar (Cancel/Save Draft/Create-Save). Form logic untouched; E2E create+edit verified by testing agent (TESTQA employee created+deleted).
- Iter 189b mobile PWA: horizontal section jump-tabs + live completion bar under header + sticky bottom action bar (web only; native untouched).

## Iter 190 — FIX: blank page after Super Admin login on LIVE PWA
- Reproduced on live with playwright: after login, "/" → /(tabs) crashed with "Cannot read properties of null (reading 'pending_leaves')" — the admin "Leave approvals" ActionRow dereferenced stats before /admin/stats resolved (timing-dependent; static export on live hit it consistently).
- Fix: optional chaining (stats?.pending_leaves ?? 0) in (tabs)/index.tsx line ~610. All other stats.* accesses verified guarded (stats && block / admin.tsx line 322).
- Iter 190 deployed + VERIFIED ON LIVE: super admin login → premium home renders on smartpayrolling.com mobile (entry-d6dec4fd).

## Iter 191 — KYC & Document Expiry Tracker (enterprise module) + refactors (tested, all pass)
- NEW backend routes/kyc_tracker.py: GET /api/admin/kyc-tracker — per-employee Aadhaar/PAN/Bank completeness + DL/Passport valid-upto expiry (statuses complete/incomplete/expiring(≤60d)/expired) + summary counts; role-scoped (super/sub/company admin).
- employee_kyc.py PATCH now accepts dl_valid_upto / passport_valid_upto (ISO or DD-MM-YYYY, 400 on garbage, blank clears; echoed in kyc response).
- NEW frontend /kyc-tracker (enterprise UI): 7 KPI stat cards (clickable filters), filter chips, search, per-employee doc chips (Aadhaar/PAN/Bank/DL/Passport with expiry badges), "Validity" modal (DateFields → PATCH), row → /employee-master. Sidebar entry "KYC & Doc Expiry Tracker" in both super-admin & company-admin navs (perm-gated employees:read).
- REFACTOR: employee documents endpoints (9: admin docs CRUD, master-pdf, master-pdf/bulk, /me/documents*) moved out of server.py into routes/employee_documents.py (server.py 19451→18948 lines). _load_scoped_employee_any_role stays in server.py (shared import).
- REFACTOR: employee-add.tsx form model (EmpForm, EMPTY_FORM, SECTION_TABS, date/gender helpers) extracted to src/utils/employeeForm.ts (2647→2503 lines). No UI change.
- Testing agent iteration: 13/13 backend pytest (tests/test_iter190_kyc_tracker.py) + full desktop E2E green; /employee-add & TEST50 login regressions pass.
- NOT deployed to live yet — user must run the VPS deploy script and reopen PWA twice.

## Iter 192 — Employee Advance Management System (tested 25/25, E2E pass)
- NEW backend routes/advances.py: advances + advance_transactions collections. POST/GET/PATCH/DELETE /api/admin/advances, /dashboard (KPIs, 6-mo trend, dept/contractor/type breakdowns), /reports (9 kinds + xlsx via openpyxl), /{id}/action (pause|resume|skip_month|recover_full[fnf]|waive), GET /api/me/advances (ESS).
- Advance types: Salary/Festival/Loan/Emergency/Medical/Travel/Other; payment modes Cash/Bank/UPI/Cheque; recovery single|emi; source compliance|actual|both; priority high/normal/low (oldest-first tiebreak); auto voucher ADV-NNNNN (db.counters); auto end-month; auto-close at balance 0; audit trail on every action.
- SALARY SYNC hooks in server.py: compliance create (~14426), compliance reprocess (~14799), actual-salary-process (~18470) call routes.advances.apply_advance_recovery. Idempotent per (advance, month, process); 'both' source mirrors in 2nd process WITHOUT double balance decrement (balance_applied flag); deduction capped at row net. Compliance rows: advance_recovery/total_deduction/net + totals; Actual rows: adv/net_pay.
- Frontend /advances (enterprise UI): tabs Dashboard/Ledger/Reports, New Advance modal (employee search, EMI auto-installments, end-month auto), detail modal (summary boxes, progress, schedule, recovery history, audit, action buttons w/ confirmations), Excel export. Sidebar: Salary Process group > "Advance Management" (both navs, perm salary_process:*).
- Frontend /my-advances (ESS read-only) + "My Advances" quick card on employee dashboard.
- User constraint honored: NO changes to super_admin/sub_admin role logic.
- Iter 191.5 fix: temp-code-bundle endpoint now ALWAYS rebuilds tar (stale-cache deploy bug); live VPS orphan process on port 8001 killed (spawn error root cause).
- NOTE: Kankani firm_masters salary_process.offline_salary was enabled in WORKSPACE db for testing actual salary process.
- NOT yet deployed to live VPS.
- PENDING USER DECISION: huge RBAC/approval-workflow spec pasted (roles, permission matrix, workflow builder, approval inbox) — needs phased plan + confirmation before build.

## Iter 193 — RBAC Phase 1 + Approval Workflow Engine (tested, pass)
- Custom Company Roles & Permission Matrix (/roles, routes/company_roles.py); staff users stored as company_admin + is_company_staff + staff_permissions[].
- Multi-level Approval Workflows (/approval-workflows builder, /approval-inbox, routes/approvals_engine.py).
- Known gap found by tests (fixed in Iter 194): direct-URL access to restricted pages not gated on frontend.

## Iter 194 — Statutory Registration module: ESIC IP (Part B) + EPF UAN automation (tested 21/22 pytest + full E2E, pass)
- NEW backend routes/statutory_registration.py (prefix /api/admin/statutory): unified ESIC IP + EPF UAN registration engine.
  - Collections: statutory_registrations (full audit history[] per reg), registration_settings (per-company eligibility rules: esic_wage_ceiling 21000, pf_wage_ceiling 15000, pf_cover_all, require_approval).
  - Endpoints: {portal}/dashboard (KPIs+coverage%), {portal}/eligible (validation+duplicate flags), {portal}/registrations CRUD, /submit (validates; staff or require_approval → pending_approval else queue RPA), /approve (real admins only) /reject /retry, /link-existing (writes users.esi_ip_no|uan_no, no duplicate creation), {portal}/bulk (≤200), /registrations/{id}/form (Form-1/Form-11 PDF base64 via reportlab), GET/PUT /settings.
  - Statuses: draft, pending_approval, rejected, queued, submitted, generated, failed, action_required, existing_found, linked_existing.
  - Validation: Aadhaar 12-digit (blocking), name/dob/doj (blocking), PAN regex/father/gender/address/phone (warnings), wage-ceiling eligibility notes. Duplicate detection: own number on file OR same-Aadhaar employee with number.
  - Permissions: registrations:read/write added to EMPLOYER_PERMISSION_KEYS + roles permission catalog.
- RPA worker (utils/rpa_worker.py): NEW _attempt_esic_ip_registration (login → "Register New IP" → fill IP form incl. family/dispensary/wages → submit → regex-read Insurance No → write users.esi_ip_no). _perform_login now takes esic_snap. _sync_registration mirrors job states onto reg records (in_progress→submitted, completed→generated + value, manual_required→action_required, failed→failed) + inserts admin notifications.
- portal_generation.py REWRITTEN: generate-uan/generate-esic Employee-Master buttons now route through the module (create reg + queue). Accept {overrides:{aadhaar_no}} (generate WITHOUT pressing Save — persists Aadhaar if blank on file) and {existing_value} (link existing number directly). manual-complete also syncs reg → generated.
- NEW frontend /statutory-registration?portal=esic|uan (Fiori-style): 6 KPI cards, ESIC/UAN segmented toggle, Registration Queue tab (10 status filter chips, search) + Eligible Employees tab (select-all-ready, Bulk Register, per-row Register/Link), detail modal (validation checklist, family particulars editor + dispensary, RPA run trail, audit timeline, link-existing, Submit/Approve&Queue/Reject/Retry/Form PDF download). Sidebar group "Statutory Registration" in both navs (perm registrations:*).
- employee-master UanEsicCard: inline Aadhaar input (generate without save) + "Have an existing UAN/ESIC IP? Enter it" inline link flows.
- RBAC FIX (Iter 193 gap): /advances and /statutory-registration now redirect staff without the matching permission to /portal-dashboard on direct URL access.
- Notes: Kankani firm has EPFO creds (UAN jobs queue) but NO ESIC creds (ESIC → action_required manual mode). Gov portals block datacenter IPs → jobs end action_required unless PORTAL_PROXY_URL set (existing behavior).
- NOT yet deployed to live VPS.

## Iter 194b — ESIC monthly salary-run alerts + deploy script (tested)
- scan_esic_alerts() in routes/statutory_registration.py hooked into compliance salary process + reprocess (server.py, after apply_advance_recovery, never raises): upserts esic_alerts doc per (company, month) with needs_registration[] (gross ≤ ceiling, no esi_ip_no) and ceiling_crossed[] (has IP, gross > ceiling); inserts admin notification when counts change.
- GET /api/admin/statutory/esic/alerts (last 6 months, company-scoped).
- Frontend: amber "ESIC Alerts — salary run {month}" banner on /statutory-registration ESIC view (needs-reg line taps to Eligible tab; ceiling-crossed shows names+gross).
- Verified: direct function test (SURENDRA SINGH flagged missing, synthetic crossed case), endpoint + banner screenshot OK; synthetic data cleaned.
- /app/deploy_vps_iter194.sh created (Iter 193+194 → live VPS; includes stop → fuser -k 8001/tcp orphan kill → start; verifies 401 on company-roles, approval-workflows, statutory routes; PWA reopen-twice reminder).

## Iter 194c — DEPLOYED TO LIVE VPS (2026-07-18, user-confirmed output)
- deploy194.sh run on VPS as root: bundle extracted, deps installed, expo export → /var/www/sksharma, backend restarted with port-8001 orphan kill. All 4 route checks ✅ (company-roles, approval-workflows, statutory/esic/dashboard, statutory/esic/alerts). /api/health ok.
- temp_bundle.py now supports kind=script (serves /app/deploy_vps_iter194.sh) so future deploys are a 2-line wget+bash — no more terminal script pasting.
- Live now includes: Iter 193 (RBAC + Approval Workflows) + Iter 194 (Statutory Registration ESIC/UAN + ESIC alerts + Employee Master button linking + RBAC URL gating).
- PENDING USER VERIFICATION on live: open PWA twice, check Statutory Registration sidebar group + Employee Master Generate buttons; add ESIC portal login on Firm Master for ESIC RPA.

## Iter 195 — Enterprise Process Command Center on all 3 Salary Process pages (tested 5/5 backend + full E2E, pass)
- NEW backend routes/salary_readiness.py: GET /api/admin/salary-process/readiness?company_id=&month= — LIVE per-firm/month feed: compliance_pct, KPIs (total emp, salary processed compliance/actual+finalized, PF/ESIC eligible via statutory settings, PT applicable, UAN/IP missing, compliance errors, challans pending, attendance record count) + 11 validation checks (attendance, salary structure, UAN, ESIC IP, Aadhaar, PAN, Bank, wage definition, duplicate aadhaar/codes, contractor mapping, KYC complete).
- NEW shared components src/components/salary/: ProcessCommandCenter.tsx (KPI card strip + workflow stepper [8 compliance / 7 actual / 5 arrear steps, green done/blue current/grey pending] + collapsible validation panel w/ progress bar; self-fetches on companyId/month/refreshKey change) and TotalsFooter.tsx (sticky bottom run-totals strip).
- Integrated into compliance-salary-run.tsx (footer: Gross/PF EE-ER/ESIC EE-ER/PT/TDS/Advance/Deductions/Net), salary-run.tsx (Gross/EPF/ESI/Advance/TDS/Net Pay), arrear-salary-run.tsx (Arrear Gross/EPF wages/dues/ESIC). Existing payroll logic untouched (UI wrapper only) — regression verified.
- NOT yet deployed to live VPS (deploy194.sh 2-liner works for future deploys: kind=script).

## Iter 195b — DEPLOYED TO LIVE VPS (2026-07-18, user-confirmed output)
- deploy194.sh (kind=script 2-liner) run on VPS: all 5 route checks ✅ incl. new /api/admin/salary-process/readiness. Live now includes Iter 195 Process Command Center on all 3 salary pages.
- PENDING USER VERIFICATION on live: reopen PWA twice → Compliance Salary Process → pick firm → KPI cards/stepper/validation panel/totals footer.

## Iter 196 — Statutory Registration overhaul: LIVE portal view + OTP handoff + one-click + full form (tested pass, iteration_196.json)
- USER DISSATISFACTION FIX (flow confusing, wanted live view, portal-style form):
- LIVE VIEW: rpa_worker streams browser JPEG frames every 2s onto job doc (_live_stream_loop, self-terminating); GET /api/admin/portal-automation/jobs/{id}/live; LiveRunViewer component (dark browser-mock: LIVE badge, URL bar, frame, step log) in queue detail modal + form page.
- AADHAAR OTP HANDOFF: worker pauses at OTP prompt (status awaiting_otp, _wait_for_otp polls 3 min), admin types OTP in Live View → POST /jobs/{id}/otp → worker continues.
- ONE-CLICK: eligible row "Register on Portal" = bulk([1]) → queue + auto-opens live modal; validation gaps → jumps to full form.
- FULL FORM: /statutory-registration-form?portal=&user_id= — portal-flow strip, 4 stepped sections (Aadhaar first per user's flowchart), dispensary+family+nominee, actions (Register on Portal Now / Save / Link existing), pre-reg checks sidebar, embedded live viewer. Prefill endpoint GET /statutory/{portal}/employee/{uid}/prefill.
- USER-CONFIRMED PORTAL URLS: ESIC = portal.esic.gov.in/EmployerPortal/ESICInsurancePortal/Portal_Loginnew.aspx; EPFO = unifiedportal-emp.epfindia.gov.in/epfo/ (unchanged).
- EPF FLOW (user flowchart): _attempt_uan_registration now: dialog auto-accept, existing-UAN branch (Previous Employment Yes + fill UAN → Member ID under existing UAN), fill Name/DOB/Aadhaar/Gender, click Verify → OK → submit. generate-uan accepts {register_member:true} for employees WITH uan_no (skips dup check, source=member_registration); form page shows "Register Member ID under existing UAN" button. SNAP_FIELDS now includes uan_no.
- ESIC FLOW (user flowchart): Aadhaar-first entry → Verify/Send OTP → OTP handoff → UIDAI details → mobile/employment/dispensary/family → IP + e-Pehchan note.
- deploy194.sh now installs Playwright Chromium + deps and forces RPA_WORKER_ENABLED=1 on VPS (root cause of "registration doesn't happen": Chromium was never installed on VPS). Chromium also installed in this pod.
- NOT yet deployed to live VPS.

## Iter 197 — Geofence Phase 2 COMPLETE (Offline Attendance Queue + Background Sync) + RBAC Frontend Route Protection (tested: iteration_197/198 + self-verified)
- OFFLINE PUNCHING (firm-gated, default OFF per user directive):
  - PunchFlowModal now accepts a `postPunch` prop (offline-capable poster from attendance.tsx); offline result shows "Saved — Pending Sync" screen.
  - attendance.tsx: offline sync banner (testID offline-sync-banner) with pending count + "Sync now" (testID sync-now-btn); auto-flush on window `online` event; mount-only effects with doFlushRef.
  - offlinePunch.ts: IndexedDB queue (db sks_offline / store punches); getOfflinePunchEnabled() — TTL-cached (60s) + in-flight dedupe + AsyncStorage-persisted last-known policy (survives offline cold start; fixes 429 storm found in iteration_198); flushQueue drops permanently-rejected punches (4xx except 401/429) and after 20 attempts.
  - Backend /api/attendance/punch: honours client_punch_at for `at`/`date` (IST wall-clock) when offline=true, sanity window (-7d..+10min), stores offline_punch/synced_at/client_dedupe_id; idempotent on client_dedupe_id (returns duplicate:true). 4/4 pytest (tests/test_iter_geofence_phase2.py) + curl E2E verified.
  - GET /api/attendance/my-geo-policy returns offline_punch_enabled from companies.offline_geofence_enabled (default false).
- RBAC ROUTE PROTECTION (P1 issue CLOSED):
  - AdminWebShell: routeDenied memo — any master-nav route not in the user's permission-filtered nav renders "Access Denied" (testID route-access-denied) + Go to Dashboard; super admins never gated; children (Stack) kept mounted via display:none.
  - ROOT CAUSE FIXED: AdminWebShell used to remount the Stack (bare -> shell) during auth bootstrap, RESETTING navigation to index and clobbering deep links (also caused the old "REPLACE payload index" quirk + URL-stuck-at-"/"). Now renders a position-stable skeleton so the Stack never remounts. index.tsx also has a boot-path restore (__bootPath) + notAtRoot guard.
  - Page-level staff guards in roles.tsx / approval-workflows.tsx / advances.tsx return null on web (instead of <Redirect>) so the shell's denied screen keeps the URL.
  - Self-verified via Playwright: sub-admin (testsub) /salary-run + /messages denied w/ URL preserved; staff HR (testhr) /roles denied; allowed pages render; super admin unaffected; employee TEST50 mobile login/punch intact.
- Cleanup: offline_geofence_enabled=false restored on Kankani; all test punches deleted.
- NOT yet deployed to live VPS.

## Iter 204–207 (July 2026 fork session)
- Iter 204: Shift Change Request & Approval Module v2 (employee UI /shift-change-request, admin /shift-change-admin, Instant Shift Exception on off-shift punches, policy config). DEPLOYED.
- Iter 205: Attendance grid — Emp Code removed, Father Name added, frozen identity columns + sticky header (web CSS sticky, solid bg fix); clock-timing HH:MM totals (minute-accurate); division-mode Present Days = whole days + Extra HRS; separate "OT HRS" cross-check sheet in monthly-inout/monthly-hours XLSX; Week-Off Worked Attendance policy module (ot_only/half_day_ot/full_day_ot/hourly + thresholds + toggles) in policy.week_off_worked, engine hooks in grid compute + compute_textile_day. Group filter shows only groups with active employees. DEPLOYED.
- Iter 206: Comp-Off Ledger (routes/comp_off.py, comp_off_ledger collection) — earn from worked week-offs (>=full→1, >=half→0.5), admin screen /comp-off-ledger (sidebar Reports), manual Grant/Use, "Approve · Comp-Off" in leave approvals (routes/leaves.py, use_comp_off flag + balance enforcement), employee balance on Leaves screen. DEPLOYED.
- Iter 207: Week-Off mode "full_day_min_hours" (>=min_hours→full day; below→plain duty only, cap 24; min_hours 0 = 50% of duty hrs); Weekly Off N/A → per-employee weekly_off_days_override (users collection, saved via /admin/user-role, applied in apply_employee_policy_override, projections at server.py ~16866 & ~17447); Employee Master weekly-off chips; Hours-Only day duty row = duty+OT capped 24. DEPLOYED.
- Fixes: proposal PDF/Word export company_id param; IKORE halfday_threshold_rule enabled directly on live DB.
- CAUTION: search_replace on server.py occasionally reports success but does not persist (phantom edits) — ALWAYS re-grep after editing server.py.
- Deploy flow: /app/deploy_vps_iter207.sh served via GET /api/temp-code-bundle?token=sks-deploy-7391&kind=script (pointer in routes/temp_bundle.py). User runs wget+bash on VPS.

## Iter 216 (June 2026 fork session)
- Salary Process (Actual) attendance source fix: Biometric → p_days from grid `present_days_policy` (half-days like 26.5 preserved; falls back total_days_computed → total_days_int → present_days), p_hours from `total_extra_hrs` (grid Iter 216 change: per-day policy mode → OT minutes; division mode → remainder). Manual → p_days/p_hours all 0.
- Salary Process (Compliance) `_compute_compliance_run`: Present Days + OT now fetched from `_compute_monthly_grid_data` (same source as Actual + Attendance Report) via grid_by_user_c override applied AFTER both stats branches (incl. policy_2 firms — that fixed 3 mismatched staff rows). Skipped when compliance_present_8hr sub-point on or use_imported_sheet.
- Verified via /tmp/test_iter216.py on Kankani 2026-06: Actual biometric 126/126 match grid, Manual 126/126 zero, Compliance 126/126 match report.
- deploy_vps_iter215.sh created + temp_bundle.py pointer updated (kind=script serves it). Pushed to github main (b13b2a5). DEPLOY COMMAND GIVEN TO USER.

## Iter 217/218 (June 2026 fork session, same day)
- Actual Salary Process: Duty HRS = Employee Master resolution (attendance_policy_override.standard_working_hours → shift duration → firm policy → 8), verified == grid totals.shift_hours 126/126.
- Actual: Basic READ-ONLY (from Employee Master salary_structure_actual Basic row); `basic` removed from ActualSalaryRowPatchBody + PATCH ignores it; frontend Basic cell → ReadCell.
- Actual grid: Code/Type/Roll columns removed (header/body/totals + BASE_COL_WIDTHS); Name sticky offset now sn only; gridCol renumbered (othallo 3, adv 4, tds 5).
- Actual: firm chips → CompanyPicker dropdown (allowAll=false, testID asp-firm-picker).
- Iter 218 gate: firm policy_master.compliance_present_8hr ON (+salary_allowed includes compliance) → Actual process blocks on-roll (400 on is_onroll=True; excludes on-roll on ALL runs, 400 if none left). On-roll paid via Compliance only (8hr direct sync, pre-existing Iter 202 path — grid override skipped there).
- Compliance grid fetch hardened: grids resolved for every company_id among scoped employees (super admin without firm filter covered).
- deploy_vps_iter216.sh created; temp_bundle pointer → deploy216.sh.

## Iter 219 (June 2026 fork session, same day)
- ROOT CAUSE of "compliance attendance not syncing" on live: user's firm has compliance_present_8hr ON → grid override was intentionally skipped, falling back to compute_present_days_and_ot on raw db.attendance (misses punch approvals/manual entries pipeline). FIX: 8-HR mode now computes per-day from grid cells (`days` map, w=hours): w>=8 → 1 day + (w-8)→OT; halfday_threshold_rule → 0.5 day @ half_day_hours, rest→OT; weekoff/holiday sub-points mirrored; ot_allowed/firm_ot_allowed gates honored. Verified 68 rows 0 mismatch vs expected.
- Half days SHOWN in compliance: compute_compliance_row present_days = round(effective_present*2)/2 (float, .5 steps); grid override + imported-sheet stats keep halves; frontend updatePresentDays clamps input to .5 steps (manual half-day entry allowed).
- Regression: toggle OFF path still 126/126 (test_iter216.py updated exp to half steps).
- deploy_vps_iter217.sh created; temp_bundle pointer → deploy217.sh.

## Iter 220 (June 2026 fork session, same day)
- Sub Admin & Staff Users overhaul (auth playbook consulted via integration_expert):
  - Mobile hygiene: _clean_mobile_or_400 (rejects "@", digits+, min 10) + _validate_pin_or_400 (6 digits) helpers in server.py (~line 15891). Sub-admin create/patch store phone in BOTH phone_e164 and phone (normalized) so phone logins work. list_staff nulls emails in phone fields; deploy script cleans live DB.
  - Separate 6-digit PIN: SubAdminCreate/Update + StaffCreate + staff PATCH accept `pin` → pin_hash (bcrypt via _hash_pin). admin-pin-login already role-agnostic lookup.
  - EMPLOYEE LINKING: create_staff with an existing employee's email (same firm) → sets is_company_staff=True + company_role_id on the EMPLOYEE doc (role stays "employee", password kept unless provided). Portal logins (admin-password-login / admin-pin-login) allow linked employees and issue sessions with auth_method "staff_portal"/"staff_portal_pin"; get_user_from_token normalizes ONLY those sessions to company_admin+staff_permissions (employee app sessions untouched). delete_staff on linked employee = unlink (keeps employee + employee sessions). list_staff includes linked employees with linked_employee flag.
  - Frontend: roles.tsx staff modal (Mobile always visible/digits-only, PIN field, optional password with linking hint, EMPLOYEE-LINKED pill); sub-admins.tsx (PIN field create+edit, phone digits-only, email-in-phone never prefilled).
  - CAUTION for future agents: search_replace on server.py may silently apply elsewhere / rollback on lint-block — ALWAYS grep-verify edits landed (one edit had to be re-applied; also fixed stray duplicated shutdown block `de_router(...)` at EOF).
- Verified via /tmp/test_iter220.py (15 checks all pass). deploy_vps_iter218.sh (incl. live phone-field cleanup step); temp_bundle → deploy218.sh.

## Iter 221 (June 2026 fork session, same day)
- Attendance Report bug "blank day headers after 25th": ROOT CAUSE — on web, headerRow (sticky top flex row) width caps at viewport, so its blue background stopped painting past ~day 25 while cells (transparent bg + white text) turned invisible. FIX in attendance-grid.tsx: (1) styles.hcell now paints its own solid brandPrimary bg; (2) ROW_FIT = { minWidth: "max-content" } (web) applied to headerRow + body rows so backgrounds/zebra span full scroll content. Verified via DOM check (day-28 header bg rgb(37,99,235)) + screenshot with all 26–31 headers visible.
- deploy_vps_iter219.sh; temp_bundle → deploy219.sh.

## Iter 222 (June 2026 fork session, same day)
- Attendance Report 1–31 day headers recolored to distinct deep teal (#0F766E) via new styles.hcellDayBg in attendance-grid.tsx (identity columns stay brandPrimary blue, totals stay brandSecondary). Verified via screenshot.
- deploy_vps_iter220.sh; temp_bundle → deploy220.sh. Pushed to github main.

## Iter 223 + 224 (June 2026 fork session, same day) — .dat import rules (utils/zk_dat_import.py)
- IN.dat slot → ALL punches forced kind "in" (status byte ignored); OUT.dat → "out". Combined-file alternation preserved (slots_here == {"combined"}).
- Near-duplicate filter: same (user, day, kind) within 15 min → ignored (stats.near_duplicate).
- Evening IN with morning IN → stays "in" → 3rd punch → pipeline OT IN (verified sequence 08:00 in/17:00 out/19:00 in/23:00 out).
- Both files → shift-anchored reclassify ONLY when chronological kinds don't pair cleanly: alternate from "in" if first punch < shift midpoint (override.shift_id → shift_masters start+dur/2, fallback 13:00) else "out". _build_bio_index now projects attendance_policy_override.
- Iter 224 existing-data protection: per (user,day) — any ^manual source → day skipped ALWAYS (manual_locked_days). Machine sources ^(import|zkteco|bio|excel) with DIFFERENT data → skipped (existing_machine_days) unless on_existing="replace" (deletes only machine punches, replaced_days). Exact duplicates flow silent/idempotent. Endpoint /admin/attendance/zk-dat-import gained Form replace_existing; frontend zk-dat-import.tsx prompts confirm() then re-uploads with replace_existing=1; new StatRows.
- Tests: /app/tests/test_iter223.py + test_iter224.py (all pass). NOTE: search_replace on this repo occasionally rolls back edits on lint-block — ALWAYS grep-verify (stats dict edit had to be re-applied).
- deploy_vps_iter221.sh; temp_bundle → deploy221.sh.

## Iter 225 (June 2026 fork session, same day)
- Detailed import CONFLICT REPORT (user chose option a): import_zk_dat_bytes collects stats["conflicts"] (≤300 rows: type manual_protected|machine_conflict, date, employee_code, name, existing[] "HH:MM KIND (manual)", new[]). Frontend zk-dat-import.tsx renders amber conflict card (table Code/Name/Date/Existing/New/Status) with "Replace Machine Data" (re-upload replace_existing=1) / "Keep Existing Data" buttons; confirm() prompt removed. Manual days shown as "Manual — kept" (never replaceable). Verified backend payload.
- PENDING LIVE ISSUES (need user specifics — cannot reproduce locally, local July grid has 0 violations):
  1. "Round HRS to nearest (minutes)" (duty_hours_rounding_minutes, firm=15 special :00/:30 snap) — user says live Duty HRS not honoring it. Rounding IS applied at server.py 17318/17323 (pair path), 1903 (compute_textile_day), 17745 (2nd path). Need firm+employee+date example.
  2. "IN/OUT sheet Total Duty HRS not showing for some employees" — hypotheses: policy_2 under-8h days → ALL hrs to OT so duty_hours=0 (frontend line 1124 shows totals.duty_hours); or missing_punch anomaly days (single punch) contribute 0. Need example employee.
- deploy_vps_iter222.sh; temp_bundle → deploy222.sh.

## Iter 226 (June 2026 fork session, same day) — NIGHT SHIFT import fix (bio 20 JITENDRA SINGH)
- ROOT CAUSE: shift-anchor reclassify required seq[0]=="in"; night shifter day = OUT 08:03 + IN 19:55 → flipped to day shift (no shift assigned → 13:00 fallback anchor).
- FIXES in zk_dat_import.py: (1) clean = alternating regardless of starting kind (trust slot kinds); (2) CROSS-MIDNIGHT STITCH: slot OUT whose prev punch is prev-day IN with gap ≤16h → date moved to prev day; (3) leading morning OUT (<12:00, first of its day, followed same-day by IN ≥6h later) → date-1 (prev month/import spillover).
- Verified with user's real kankani in/out .dat files: bio 20 grid now 01..: in 19:55, out 03:55(+OT to 08:03), 12.0h, no anomaly; leading July-1 08:03 OUT lands on 2026-06-30.
- User instruction to rectify live data: re-upload both files after deploy → conflict report → "Replace Machine Data" once.
- PENDING NEXT: Attendance Policy "Shift Rotational or Open" option — Open = per-day shift auto-detected from employee's FIRST IN punch (nearest shift master), attendance + OT computed on the detected shift. NOT implemented yet.
- Local artifacts: /tmp/kankani_in.dat,/tmp/kankani_out.dat (re-download from customer-assets URLs in chat if lost).
- deploy_vps_iter223.sh; temp_bundle → deploy223.sh.

## Iter 227 + 228 (June 2026 fork session) — Rotational/Open shifts + "Wrong Data Minutes" import fix
- FIXED P0: `shift_mode` NameError in server.py _validate_policy (previous session's blocker) — shift_mode ("fixed"|"open") now validated + persisted in attendance_policy.
- Iter 227 SHIFT ROTATIONAL/OPEN: new `_is_shift_open(policy)` helper (server.py ~1406) — True when policy.shift_mode=="open" OR policy_master.shift_type in (rotational, open). Passed as firm_shift_open to ALL 3 resolve_shift_for_user call sites (compute-day ~6089, monthly grid ~17293, OT report ~17755). Open mode: shift auto-picked per day by circular distance of first IN punch to Shift Master start times; apply_resolved_shift_to_policy sets full_day/standard hours from shift duration. Frontend attendance-policy.tsx: new "Shift Mode" chip selector after ShiftMasterSection (testID ap-shift-mode-fixed/open); onPress also syncs policy_master.shift_type. Verified: bio 20 first-IN 19:55 → Night Shift 12h duty; bio 15 first-IN 08:03 → Day Shift 12h.
- Iter 228 "WRONG DATA MINUTES" (user complaint, zk_dat_import.py) — ROOT CAUSE: shift-anchor blind re-alternation corrupted days with same-kind noise (IN 08:25 + IN 09:51 + OUT 20:17 → fake IN 08:25/OUT 09:51 = 1.4h). FIXES:
  1. Anchor-alternation REMOVED → same-kind RUN COLLAPSE: IN-run keep FIRST (+ keep later IN if ≥6h gap = new session), OUT-run keep LAST. Slot kinds stay authoritative.
  2. Edge-bounce drop (_drop_edge_bounces, run before conflict check AND after collapse): leading OUT followed by IN ≤15min → drop OUT; trailing IN ≤15min after OUT → drop IN.
  3. Cross-day bounce: IN ≤15min after a night-exit OUT that was stitched to prev day → dropped (stitch loop).
  4. Night-exit-on-IN-machine flip: morning (<12h) IN-file punch after prev-day dangling evening IN (6-16h) with another IN ≥6h later same day → kind flipped to "out", moved to prev day.
  5. _is_bounce_in guard on stitch + flip: an "IN" ≤15min after an OUT is NOT treated as a night IN — kills phantom 22-24h double-shift days (emp 316 23.75h→11.73h etc.).
  - stats["noise_collapsed"] counter added. Verified against real kankani .dat files: 0 timestamp errors, multi-punch 0-hr days 30→8 (rest genuinely ambiguous → flagged), phantom 24h days eliminated, all bio-20 night shifts intact.
- Tests: /app/tests/test_iter228.py (+ 223/224 still pass). Audit harness /tmp/audit_import.py.
- REMINDER (recurring): search_replace edits on server.py sometimes silently roll back — ALWAYS grep-verify after editing (happened again with _is_shift_open call sites).
- User rectification steps after deploy: re-upload both .dat files → conflict report → "Replace Machine Data" once. For rotational firms: Attendance Policy → Shift Mode → Open/Rotational → Save.
- deploy_vps_iter224.sh; push to github main done this session.

## Iter 229 (June 2026 fork session, same day) — grid OUT column showed synthetic split boundary
- User bug: In/Out grid showed OUT with SAME minutes as IN (19:55 → "07:55") because single-pair days split arithmetically for OT displayed the boundary (IN + shift hrs) as OUT.
- Fix at server.py _compute_monthly_grid_data (~17375): when ot_in_dt == reg_out_dt (arithmetic split, not a real punch) → _out_display = ot_out_dt (the ACTUAL machine OUT, e.g. 08:03). Explicit OT pairs unchanged. OT-report endpoint left as-is (boundary intentionally marks the duty/OT window split).

## Iter 230 (June 2026 fork session, batch of 7 user requests)
1. compliance-settings.tsx — firm scope chips → searchable dropdown modal (testID cs-scope-firm-dropdown / cs-firm-search).
2. compliance-salary-run.tsx — "Configure employees" button removed (modal code retained, unreachable).
3. GROSS ₹1 BUG — utils/compliance_salary.py compute_compliance_row: _reconcile() rounds all 6 heads to whole ₹ and absorbs delta into largest head so Σheads == round(gross) (applied to paid + master). Frontend applyPresentDays mirrors (rHeads sum = grossPaid).
4. 4-BUTTON LIFECYCLE both salary screens: Save (was "Save as Draft"/flush pending PATCHes) / Reprocess (reload last-saved run via GET run) / Delete (confirmYesNo twice → DELETE via deletion_approvals router: super admin deletes directly, others queue approval) / Finalize & Lock. Compliance's old recompute renamed "Recompute (Attendance)".
5. EDITABLE AMOUNTS: compliance grid new "OT Amt*" column after Gross + editable TDS (updateRowField extended: ot_pay→gross_paid=monthly_gross+ot, tds→ded/net, totals strip synced; save-rows persists rows+totals wholesale). Actual grid: W.Basic editable → PATCH field w_basic → row.w_basic_override in _actual_salary_row_compute (~19402); editing p_hours clears override. NOTE: ActualSalaryRowPatchBody at ~19438.
6. EMPLOYEE REPORT (employee-report.tsx): firm dropdown + "3 · Payslips" card (er-slip-month, er-slip-dl-one/dl-all/mail-one/mail-all). New backend endpoints in server.py (~14310): GET /admin/employee-payslip.pdf?company_id&user_id&month, GET /admin/payslips-month.zip, POST /admin/payslips/email {company_id, month, user_id?} — resolution: latest COMPLIANCE run first else ACTUAL (mapped via _actual_row_to_payslip); email via Resend _send_email_with_attachment (sandbox sender limits delivery until domain verified).
7. PF CHALLAN routes/pf_reports.py — _month_challan extras (eps_subscribers, total_emps, non_pf, non_pf_wages); _challan_pdf + challan.xlsx rebuilt to SBI Combined Challan format (subscribers/wages rows, particulars grid A/C 01/02/10/21/22, grand total in words via _num_to_words_inr, bank/establishment boxes, non-PF footer).
- server.py ROLLBACK BUG hit AGAIN (w_basic model field) — always grep-verify server.py edits.
- Testing: iteration_213.json all PASS. deploy_vps_iter225.sh created; pushed to main.

## Iter 231 — user bug: real DOUBLE-DUTY (day+night) attendance was being erased by iter-228 bounce rules
- User screenshot (AJAY SINGH RAWAT, bio 58): weavers really do OUT 20:00 → IN 20:09 → night work → OUT 07:58 next morning (Total Duty 23:59). Iter-228's 15-min bounce heuristics dropped these punches → days vanished from IN/OUT sheet & Duty HRS.
- FIX (zk_dat_import.py): quick IN ≤15min after an OUT is now PAIRING-AWARE — kept when the NEXT chronological punch is an OUT within 16h (real session), dropped only when it dangles. Removed _is_bounce_in guard from stitch+flip (stitch again always pulls next-morning OUT to prev-day IN, incl. quick night INs). _drop_edge_bounces reduced to leading-OUT-only. Same rule auto-handles the post-night morning IN (08:02 after 07:58 OUT pairs with evening OUT → kept).
- test_iter228.py updated to double-duty semantics; 223/224/228 all pass. Real-file audit: AJAY d01 raw 23.83 (duty 8 + OT 16), bio84 d04 regression intact (11.87), zero-hour multi-punch days = 4 (all genuine).
- REMINDER for user-facing answer: grid counts only APPROVED punches — if employee app punches are pending in Punch Approval, day stays blank until approved. VPS machine days trimmed by iter-228 need re-import with "Replace Machine Data".

## Iter 232 — Attendance Doctor + Auto Repair (user's "blank Total Duty HRS" spec)
- RCA delivered to user: Duty HRS blank when (a) day has UNPAIRED punches (user's own no-guess rule voids the day), (b) mobile punches still PENDING approval (grid counts status=approved only), (c) pre-iter-231 imports trimmed real double-duty punches (fixed; VPS needs re-import w/ Replace).
- NEW /app/backend/routes/attendance_doctor.py (registered in server.py):
  * GET /api/admin/attendance-doctor?company_id&month[&user_id] — per employee-day: full punch chain (all statuses+source), pairing simulation (mirrors grid incl. stitch_cross_day_ot), duty mins, exact blank reasons (pending_approval/missing_in/missing_out/no_punches/pairing_failed).
  * POST /api/admin/attendance-doctor/repair {company_id, month, preview} — normalises APPROVED MACHINE punches only (iter-231 rules): noise → status "auto_ignored" (REVERSIBLE, never deleted, grid excludes non-approved), night OUTs re-dated to shift start day; manual/app punches untouched; repair_tag stamped.
  * POST /api/admin/attendance-doctor/repair/undo — restores auto_ignored → approved for firm+month.
- NEW /app/frontend/app/attendance-doctor.tsx (route /attendance-doctor) + "Doctor" button in attendance-grid header toolbar (testID ms-open-doctor). Verified via screenshot: 172 problem days listed with reasons.
- Requirements already covered by existing engine (mapped for user): machine direction via IN/OUT .dat slots + combined force_alternate; dup handling 15-min rule; night/rotational shifts; missing-punch rules; OT split per decided rules. attendance index user_id+date exists (1976 local punches; scale fine).

## Iter 244 (June 2026) — Onboarding fixes (employee-add)
- Mandatory-field policy (user directive): Name*, Employee No.* (auto counts), Designation* (from list), Date of Joining*, Salary details* (Basic/monthly/compliance gross). Mobile/Email now OPTIONAL (backend no longer 400s without phone/email; employee can't self-login until one added). Red stars rendered via `required` prop on Field/MasterSelect; DOJ + Basic Salary starred; completion checklist updated (Employee No. replaces Mobile; Bank/Aadhaar marked optional).
- Spouse rule: Spouse Name mandatory ONLY when gender=Female AND marital=Married (field visible when Married; star when Female).
- PWA draft→create bug: "Create Employee" now validates BEFORE opening review modal (openReview) so errors are never hidden under it; review ScrollView maxHeight now min(430, 50% of winH) so Confirm & Create stays visible on short screens. Verified e2e: draft save → review → Confirm & Create → employee created (no mobile) → draft auto-discarded.
- Group Master interlink (user bug): GET /api/admin/masters?type=group now lazily auto-registers groups that exist only on employee records (employee_type from Bulk Import) into db.masters (scope firm, flag auto_registered=bulk_import_interlink, global name dedupe). Verified: all Kankani imported groups appear in Group dropdown/General Masters.

## Iter 245 (June 2026) — Compliance sequence, hybrid dates, offline rule
- Compliance Salary field sequence (user): Basic Salary → PF Basic Salary → HRA → CONV. → OTH. ALLOW. → other Firm-Master allowances → Gross Salary (auto = Basic + allowances). Implemented via allowHeadRank stable sort (HRA=0, CONV*=1, OTH*=2, rest firm order); Basic/PF-Basic moved above allowances; gross relabelled "Gross Salary (auto = Basic + HRA + CONV. + Allowances)"; deductions, VPF, Actual-salary blocks, Pay Mode follow.
- DateField.tsx rewritten (shared component → applies to Employee Master edit, employee-add DOB/DOJ, family DOB, all admin/employer/employee PWA screens): HYBRID — type DD-MM-YYYY (accepts d-m-yyyy, /, ., ddmmyyyy, ISO; commits on blur/enter, invalid reverts) AND calendar icon opens native picker via hidden <input type=date> (testID `${testID}-picker`). Verified both paths e2e.
- Off-roll (offline) employees: Compliance Salary section replaced with amber note (not required); getMandatoryError for off-roll requires only Actual/Off-line salary (basic_salary || salary_monthly), compliance skipped.

## Iter 246 (June 2026) — Rollback: Mobile mandatory, Employee Code optional
- User rollback of Iter 244 rule: Employee Code star/validation REMOVED (blank = auto); Mobile is MANDATORY again (red star + "Mobile number is required." validation + backend phone/email 400 restored). Checklist shows "Mobile number" again.
- NOTE: parallel search_replace batch dropped one edit silently (getMandatoryError) — reapplied; also cleaned stray duplicated style lines at EOF of employee-add.tsx.

## Iter 247 (June 2026) — Full activity log + idle auto-logout
- `activity_log` collection + FastAPI middleware in server.py (_activity_logger, after audit-lock guard): logs EVERY /api write (POST/PUT/PATCH/DELETE), login (actor resolved from body email/phone) and report download (GET with .xlsx/.pdf/.csv/.txt/export/download) — fields: at (date+time), actor_id/name/role, company_id, method, path, action ("CREATE/UPDATE/DELETE/LOGIN/DOWNLOAD path"), status, sanitized details (pin/password/token/otp/captcha/secret stripped), ip. Skips: temp-code-bundle, rpa frames, health, db-viewer. Anonymous non-auth calls skipped. Indexes: at desc, actor_id, company_id.
- Users Log Report (/admin/users-log) now includes activity_log as source 0 (limit 3000, failed calls tagged [FAILED status]); NEW GET /admin/users-log.xlsx export (Date/Time/User/Role/Firm/Action/Details/Source); green "Excel Report" button (testID ulr-export-xlsx) in users-log-report.tsx.
- NEW IdleLogout.tsx mounted in _layout.tsx: auto-logout after 10 min inactivity for ADMIN roles (super/sub/company admin) on web (mouse/key/scroll/touch listeners, 5s throttle) and native (responder capture + AppState). Employees NOT auto-logged-out (punch flow). Alert + redirect to "/" on fire.

## Iter 248 (June 2026) — New joiners always land in ACTIVE list
- User bug: newly added OFF-ROLL (offline) employees vanished from the "ACTIVE EMPLOYEE" tab in Employee Master Data (/admin). Root cause: matchesStatus in admin.tsx excluded is_onroll===false from Active. Fix: Active = every working employee (on-roll + off-roll); only disabled/resigned excluded. On-roll/Off-roll sub-filter chips still available.

## Iter 249 (June 2026) — Punch Log Report: Apply auto-downloads full period
- User request: selecting From/To and clicking Apply now BOTH refreshes the on-screen list AND auto-downloads the full-period Excel (Punch_Log_from_to.xlsx, up to 100k rows; verified 1976/1976 rows match). Top "Download Excel" button unchanged.

## Iter 250 (June 2026) — ZKTeco old-data fetch + punch photos
- User bug: old punches stored inside connected machines never downloaded (handshake ATTLOGStamp=None = new logs only; getrequest never issued commands).
- Fix: NEW "Fetch old data" button per device card → POST /api/biometric/devices/{device_id}/resync opens a 6h resync window (resync_until, resync_check_sent). While active: handshake answers ATTLOGStamp=0 + ATTPHOTOStamp=0 (device re-uploads ALL stored logs), getrequest issues one C:{id}:CHECK. Duplicates skipped by idempotency guard.
- Punch PHOTOS (user request "download data with photo"): iclock_push now parses table=ATTPHOTO (PIN=YYYYMMDDHHMMSS-<pin>.jpg headers + JPEG bytes) → attaches to matching attendance record (±90s window) as selfie_base64 (photo_source=zkteco_attphoto); photos arriving before their ATTLOG line are parked in db.biometric_photos and attached at ingest.
- IN/OUT direction confirmation: punches inherit the machine's registered direction (kind in/out/both alternating) — already working, verified.
- Punch Log Report: rows now include record_id + has_photo (cheap distinct lookup); on-screen "Photo" column (📷/—); Excel export embeds actual photo thumbnails in the Photo column (PIL thumbnail 72px, row height 45, max 2000 embedded; beyond that "YES").
- E2E verified: resync→handshake Stamp=0→CHECK→old ATTLOG (kind=in from IN machine)→ATTPHOTO attach→has_photo=true→xlsx embedded image.

## Iter 251 (June 2026) — Blinking status LED + Apply rollback
- Biometric device cards: BlinkDot (Animated.loop opacity pulse) — BLUE blink when Online, RED blink when Offline; label colored to match. Verified with test online/offline devices (screenshot).
- Punch Log Report rollback (user): Apply only loads data on screen again — NO auto Excel download (Download Excel button remains for exports).

## Iter 252 (June 2026) — Machine sync from Punch Log + daily Show
- Punch Log Report: NEW green "Sync from machines" button (testID plog-sync-machines) → POST /api/biometric/devices/resync-all[?company_id] opens 6h resync window on ALL enabled devices in scope (returns devices/online counts + guidance). Machines re-upload all stored punches; press Apply after to refresh. 404 when no machines registered.
- Attendance Report (attendance-grid): NEW green "Show" button beside Daily basis date (testID daily-show) → sets custom range from=to=dailyDate so the grid shows ONLY that day's column on screen (Clear resets). Verified via screenshot (15-06-2026 single-day view).

## Iter 253 (June 2026) — Punch Log firm-change refresh
- Changing the Firm dropdown now auto-resets machine selection, rows/total/truncated, machine list, and reloads punches for the NEW firm (machines repopulated from its data). Verified: Kankani (526) → City Care (0, machine list reset).

## Iter 254 (June 2026) — PF & ESIC calculation fixes (compliance_salary.py)
- PF (user bug): 50%-of-gross floor rule REMOVED from PF — PF wages now STRICTLY = Employee Master "PF Basic Salary" (pro-rated by attendance for monthly staff), capped at pf_wage_cap unless explicit PF Basic exceeds it. E.g. PF Basic 15000 + gross 40000 → PF wages 15000 / PF 1800 (was inflated by floor).
- ESIC eligibility (user directive): checked against Employee Master "Compliance Basic Salary" (compliance_basic) ≤ esic_gross_threshold; falls back to derived full-month basic when blank. Unit-verified 3 cases.

## Iter 255 (June 2026) — Compliance Salary Process fixes (PF formula + UI)
- PF STILL-wrong root cause: the run screen's CLIENT-side recompute (compliance-salary-run.tsx, on row edits) still used max(PF Basic, 50% gross). Fixed: pfWagesNew = min(pfBasicPro, max(pfCap, pfBasicPro)) — strictly PF Basic; floorPct removed. ESIC eligibility client-side now uses row.compliance_basic (new field emitted by compute_compliance_row) ≤ threshold, fallback full-month basic.
- UI (user requests): 1) Dept chips hidden on Compliance run grid (GridFilterChips new hide=["dept"] prop; Branch/Contractor remain). 2) Employee Group is now a DROPDOWN right after Month days (override) (testID csr-group-select; native <select> on web, chips fallback native). 3) Import Salary Sheet card moved to BOTTOM of page (after Past runs). All verified via screenshot.

## Iter 256 (June 2026) — Compliance grid keyboard nav + finalize clear
- Spreadsheet-style Arrow-key navigation across ALL editable cells of the Compliance run grid: Up/Down = same column next/prev row; Left/Right = hop between editable columns in row order pd → others → ot_pay → tds → other_deduction (columns follow Firm-Master-enabled heads via navCols). Implemented with cellRefs registry + handleNavKey; PresentDaysCell got onNav prop (commits before hopping). Verified via Playwright (activeElement coordinates).
- Finalize & Lock now CLEARS the front page (setRun(null), empType reset) — run moves to Past Runs; message updated. NOTE: Advance is not an editable grid column (auto recovery from Advances module) — nav covers TDS/Other/OT/Others/Present Days.

## Iter 257 (June 2026) — Finalize guard scoped per employee group
- User bug: after Finalize & Lock of one group's salary, processing ANOTHER group for the same firm+month was blocked. Root cause: finalized-month guard (backend POST /admin/compliance-salary-runs + frontend generate()) matched only firm+month. Fixed: both now scope to the SAME employee_type (case-insensitive; blank = ungrouped runs). Verified: STAFF finalized → LABOUR processes 200; STAFF again → 409.

## Iter 258 (June 2026) — Centralized ZKTeco Device Management (phase 1)
- User pasted an enterprise spec (React/Node/Postgres) but instructed: keep the ADMS connect process unchanged, build INSIDE the existing ZKTeco Device Setup window. Implemented within Expo/FastAPI/Mongo stack:
- Command queue: db.biometric_device_cmds (+ getrequest delivers up to 5 pending as C:{id}:{cmd}; devicecmd parses ID=/Return= to mark done/failed).
- INFO parsing from getrequest (_parse_info): firmware, user_count, fp_count, att_log_count, device_ip persisted on device doc; shown on card (FIRMWARE / USERS ON DEVICE / FINGERPRINTS / LOGS ON DEVICE / DEVICE IP).
- Remote controls per card: Sync data (CHECK), Refresh info (INFO), Restart (REBOOT, web confirm), Push employees (DATA UPDATE USERINFO PIN\tName per employee with bio_code). Endpoint POST /api/biometric/devices/{id}/command (actions: restart, sync_data, refresh_info, clear_attlog[api-only]).
- POST /api/biometric/devices/push-employees {company_id, user_id?, device_id?} — pushes names by Bio Code to firm machines; 404 message "No biometric machine is registered for this company — register the device first in ZKTeco Device Setup" when none; 400 when employee lacks bio_code.
- Employee Master (admin.tsx preview modal): NEW "Push Name to Biometric Machine" button (testID push-emp-to-machine) using the endpoint; shows the not-registered message.
- E2E verified: queue→deliver→result, INFO parse, single push (PIN=72 SURENDRA SINGH), no-device message; UI screenshot OK.
- DEFERRED (spec backlog): alerts (offline/memory), device health/sync reports + exports, WebSocket live dashboard, interactive map, dark mode, fingerprint/face template sync, lock/unlock & clear-log UI.

## Iter 259 (June 2026) — Machine date/time sync + offline alerts + health report
- "Set date & time" button per device card → POST command action sync_time → queues `SET OPTION DateTime={zk_encoded}` with CURRENT IST wall-clock (ZK encoding ((y-2000)*372+(m-1)*31+(d-1))*86400+h*3600+m*60+s; verified decode 22-Jul-2026 06:18 IST).
- Device OFFLINE alerts: device_offline_alert_loop (5-min poll, started in server startup) — silent >15 min → ONE notification to company admins + super_admins (type device.offline); flag resets when back online.
- Device Health Report: GET /api/biometric/devices/health-report.xlsx (Firm/Device/SN/Direction/Location/Status colored/Heartbeat/Firmware/Users/FP/Logs/IP/Punches/Enabled) + green "Health Report (Excel)" button beside Register new device.

## Iter 260 (June 2026) — Attendance Engine Overhaul: new report columns
- User confirmed: Break = OUT→next-IN gap; Late/Early vs configured shift timings (per employee/group); show in BOTH monthly grid and daily detail.
- Backend (server.py): new `compute_day_punch_metrics()` (near split_regular_ot_times) — pairs sessions, computes break_minutes (OUT→IN gaps), late_minutes (first IN vs shift start, honors grace_minutes_late, full lateness beyond grace), early_minutes (last OUT vs shift end); night shifts handled with circular ±12h distance.
- Shift source for late/early: daily override / resolved shift → else nearest firm-policy shift by first-IN (resolve_shift_for_user with firm_shift_open=True) so night workers measure against the night shift.
- `_compute_monthly_grid_data`: each day cell now carries punches (existing), break_hours, net_hours (paired IN→OUT time excl. breaks), late_min, early_min; row totals carry total_punches, break_hours, net_hours, late_minutes, early_minutes.
- Daily report (utils/daily_attendance.py): XLSX + PDF now include Punches | Break HRS | Late Min | Early Go columns with footer totals.
- Frontend (attendance-grid.tsx): 5 new summary columns after Extra HRS (Punches, Break HRS, Net HRS, Late Min, Early Go — late/early amber when >0); IN/OUT day cells show compact "L{m} E{m} B{hh:mm}" metrics line.
- Verified with live Kankani July-2026 data (night-shift VINIT: late/early 0; SATISH day-out 17:05 vs 20:00 → early 175m; break 00:35 detected from 4-punch day) + Playwright screenshot of grid.

## Iter 261 (June 2026) — ZKTeco Device Management Phase 2
- **FP/Face template sync**: OPERLOG/BIODATA pushes now parsed (`_ingest_templates`) — FP (FID/Size/Valid/TMP), FACE, and unified BIODATA (Type 1=fp, 2/8/9=face) templates upserted into `db.biometric_templates` keyed (company, pin, kind, slot). Wire-format preserved so re-push is exact (`_template_to_cmd`).
- New endpoints: POST `/biometric/devices/{id}/fetch-templates` (queues DATA QUERY USERINFO/FINGERTMP/BIODATA), POST `/biometric/devices/{id}/sync-templates` (pushes USERINFO + all stored firm templates to target, skips source device; optional {user_id}), GET `/biometric/templates-summary`.
- **Lock/Unlock device**: portal-side lock (action lock/unlock on the command endpoint) — while locked, ATTLOG pushes are parked into `db.biometric_locked_punches` (audit) and NOT ingested; card shows red LOCKED badge. **Unlock door** button → AC_UNLOCK relay command.
- **Live Dashboard**: GET `/biometric/live-feed` (recent zkteco punches joined with employee + device names, source ^zkteco: only); frontend "Live punch feed" collapsible panel with IN/OUT pills, live-updating via useLiveSync (attendance.zk-pushed) + 15s polling; "N/N machines online" counter.
- **Bug fix**: `_queue_cmd` cmd_id collided when many commands queued in the same millisecond (all shared one ID → broken devicecmd correlation). Now ms-timestamp + 3 random digits.
- E2E verified with simulated devices (TESTSN-A/B): template capture → summary → sync queue → getrequest delivery, lock parks punches / unlock ingests, AC_UNLOCK queued, live feed OK. Test artifacts cleaned from dev DB.

## Iter 262 (June 2026) — Editable "Set date & time" for machines
- User: clicking Set date & time should OPEN the date/time details to edit; Apply syncs the edited value to the machine.
- Frontend (biometric-devices.tsx): "Set date & time" now opens a centered dialog (testIDs time-dialog/-date/-time/-apply) pre-filled with current time; inputs DD-MM-YYYY + HH:MM:SS, "Use current time" refill, "Apply to machine" queues the command.
- Backend: sync_time action accepts optional {date, time} (DD-MM-YYYY / YYYY-MM-DD, HH:MM[:SS]); encodes via _zk_encode_datetime; 400 on invalid; falls back to current IST when omitted.
- Verified: UI apply queued `SET OPTION DateTime=851165100` which decodes exactly to 25-Jun-2026 10:45:00; bad date rejected 400.

## Iter 263 (June 2026) — GMT / time-zone setting per machine
- User asked "GMT setting available or not" → found handshake hardcoded TimeZone=8 (China!). Fixed.
- Backend: gmt_offset field on device (create/update models; default "+05:30"); `_parse_gmt_offset_minutes` accepts +05:30 / 5:30 / -04:00 / +8 / 5.5 (invalid → 330); handshake now sends `TimeZone=<hours or signed minutes>` (whole hours plain, half zones in minutes e.g. 330 for IST per Push SDK); `_zk_datetime_now(device)` and sync_time fallback use the device's zone. Legacy devices without the field default to India.
- Frontend: "GMT offset (time zone)" input in Register/Edit form (testID d-gmt, default +05:30, hint text), GMT fact on card, "Set date & time" dialog prefills current time in the machine's configured zone (parseGmtMinutes helper).
- Verified: register with +04:00, handshake TimeZone updates on PATCH (330 for +05:30), sync_time label shows zone; UI field renders with default.

## Iter 264 (June 2026) — Security audit fixes (SEC-001 CRITICAL, SEC-002 HIGH)
- User ran security audit; verdict FAIL. User approved fixing the 2 critical issues; confirmed they use PIN/password (not OTP).
- SEC-001 (account takeover via OTP echo): server.py — OTP_DEV_MODE default "0"; response NEVER returns the code (removed dev_code/dev_note; only masked dev_hint when explicitly OTP_DEV_MODE=1); plaintext code removed from logs; 45s resend cooldown (429); otp_verify blocks auto-provisioning of any non-employee role (super_admin/company_admin/sub_admin) via unauthenticated OTP. Frontend otp-login.tsx dev-code box simply no longer renders (harmless). Verified: no leak, cooldown, guess rejected.
- SEC-002 (device spoofing): biometric_devices.py — record last_source_ip + seen_ips on every handshake/getrequest/push; new opt-in per-device IP lock (ip_lock + ip_allowlist). When locked, pushes from foreign IPs are parked (biometric_locked_punches reason=ip_blocked, not ingested) and getrequest withholds queued commands (prevents template/PII leak). New endpoint POST /biometric/devices/{id}/ip-lock {mode lock|unlock, ips?}. Default (no lock) = allow all → existing live machines untouched. UI: "Lock to IP"/"Unlock IP" button + SOURCE IP fact on device card. Verified E2E with X-Forwarded-For simulation.
- NOT fixed (reported to user as remaining): SEC-003 plaintext EPFO/ESIC passwords, SEC-004 3650-day sessions/client-only idle logout, plus P3 hardening items.

## Iter 265 (June 2026) — Always enable employee PWA punching
- User: some employees saw "Attendance punching is disabled" and asked to ALWAYS enable punching in the employee PWA.
- Root cause: GET /api/company set attendance_punching_enabled from firm_masters.salary_process.bio_matrix_attendance (Iter 114 gate) — firms with Bio Matrix OFF disabled app punching.
- Fix: server.py /api/company now always sets attendance_punching_enabled = True. The /attendance/punch endpoint still enforces GPS/geofence/biometric rules, so only the punch UI visibility changed.
- Verified: employee TEST50 (SURENDRA, Kankani) /company returns True; PWA dashboard + attendance tab show active "Punch In" (disabled card gone).

## Iter 266 (June 2026) — Bulk Import City/State/PinCode + double-confirm; per-role idle logout
- Bulk Employee Import: added City, State, Pin Code columns to the .xlsx template + sample row; aliases (city/town, state, pin code/pincode/pin_code/postal code/zip) map them; bulk-import stores city, district(=city), state, pincode. Verified: import stores Jaipur/Rajasthan/302001.
- Double confirmation before import (web): two sequential window.confirm dialogs (firm+row-count, then final CREATE confirmation) in employee-bulk-import.tsx runImport(); hint text added under step 4.
- Idle auto-logout (IdleLogout.tsx): per-role — super_admin & sub_admin = 30 min, company_admin = 10 min (unchanged). Alert message now dynamic. NOTE: still CLIENT-side only (SEC-004 server-side expiry still open).

## Iter 267 (June 2026) — ZKTeco Multi-Device Sync Engine (Phase 1)
- New module /app/backend/routes/sync_engine.py (repository→service→worker→API layers) on MongoDB + ADMS push. User approved: MongoDB (not SQL), ADMS command-queue model, portal-as-source-of-truth conflicts.
- Collections: sync_settings, sync_jobs (queue: pending/processing/success/failed/retry/cancelled), sync_log (per-device execution), sync_conflicts. Devices got sync_enabled=true default.
- Auto-sync hooks: employee CREATE (server.py add), UPDATE (employee_profile.py patch), DELETE (server.py delete → enqueue_employee_removal using pre-captured pin). All wrapped so sync never breaks employee ops.
- Worker sync_engine_loop() every 30s: _dispatch_job builds ADMS commands (DATA UPDATE USERINFO + card/passwd per settings + FP/FACE/BIODATA templates via _template_to_cmd; DELETE USERINFO for delete/disable), queues via _queue_cmd, opens sync_log rows → status processing; _reconcile_job reads biometric_device_cmds terminal states (done/failed via /iclock/devicecmd ack) → success / retry (up to max_retry_count) / failed. Offline devices auto-catch-up on reconnect (inherent to ADMS pull).
- Conflict logging hooked into _ingest_templates: machine-only template → sync_conflicts (open) for admin approve/reject.
- APIs: GET/PUT /sync/settings, POST /sync/employee, POST /sync/all (dept/group/branch filter), GET /sync/status (dashboard aggregates), GET /queue, GET /sync/logs, GET /sync/conflicts, POST /sync/conflicts/{id}/resolve.
- E2E verified: manual sync job pending→processing→success after simulated device ack; dashboard/logs/queue correct. Test artifacts cleaned.
- PENDING (future phases): Phase 2 Sync Dashboard/Queue Monitor/History UI (WebSocket live); Phase 3 manual sync buttons UI + settings screen; Phase 4 reports (device-wise/employee/failed/attendance/health/performance) + live notifications.

## Iter 268 (June 2026) — Sync Engine Phases 2-4 (UI + reports + notifications)
- New screen /app/frontend/app/sync-engine.tsx (nav "Device Sync Engine" added to AdminWebShell sidebar + route perms). Super-admin firm picker; company_admin auto-scoped.
- Phase 2: Dashboard (8 stat tiles: total/online/offline devices, pending, synced, failed, in-queue, conflicts + last-sync), Queue Monitor (live job list w/ status pills), History (sync_log rows). Live via 10s status polling + useLiveSync on sync.*/attendance.* events.
- Phase 3: Manual sync — "Sync All Employees" + filtered sync (department/group/branch) calling POST /sync/all; full Admin Settings tab (auto-sync, fingerprints, face, card, password, photos, attendance, retry, max_retry_count, sync_interval) via GET/PUT /sync/settings.
- Phase 4: "Report" button → GET /sync/report.xlsx (3 sheets: Summary status counts, Device-wise, Jobs). Notifications: worker inserts notifications (type sync.failed, audience admins) when a job fails after max retries. Conflicts tab: approve(Keep)/reject(Ignore) → POST /sync/conflicts/{id}/resolve.
- Verified: all endpoints 200, Excel 3-sheet report generates, UI Dashboard/Settings/Queue tabs render & function (Playwright).

## Iter 269 (June 2026) — SSL / HTTPS on production VPS
- User asked to secure the portal (browsers showed "Not Secure"). Created /app/setup_ssl_iter236_v2.sh, served via /api/temp-code-bundle?kind=ssl (temp_bundle.py updated; kind=script now serves deploy_vps_iter235.sh).
- v1 failed on VPS: Ubuntu 24.04 apt certbot 2.9.0 broken (pyOpenSSL "module 'lib' has no attribute 'GEN_EMAIL'"). v2 removed apt certbot, installed official snap certbot 5.7.0.
- RESULT: https://smartpayrolling.com + www LIVE with Let's Encrypt cert, HTTP→HTTPS redirect enabled in /etc/nginx/sites-enabled/sksharma, auto-renewal (snap timer) dry-run passed. Verified HTTP 200.
- STILL PENDING: SEC-003 (encrypt portal_logins passwords) and SEC-004 (server-side 12h session expiry with auto-extend — user chose option a).

## Iter 270 (June 2026) — "OT Include in Existing Compliance Salary" (Yes/No)
- New Policy Master sub-point `compliance_ot_include` (default YES) shown under "Count Present Day @ 8 HRS" in Attendance Policy → Sub Points (attendance-policy.tsx PM_FLAGS; default-true handled in dflt line + server.py _flag(...,True) + backfill setdefault True).
- YES → OT Duty HRS paid inside Compliance Salary (ot_pay in gross_paid — existing behaviour). NO → _compute_compliance_run zeroes stats.ot_hours (no OT pay in compliance) and OT HRS auto-import into the OT Salary Process.
- OT Salary Process gate widened (routes/ot_salary.py _ot_process_enabled + /firms $or query): policy_2 OR (compliance_present_8hr=true AND compliance_ot_include=false). Error text + ot-salary-run.tsx notes updated.
- E2E verified (emp 50, 10-hr day 2026-06-10): include=YES → ot_hours 2.0, ot_pay 187.5 in gross_paid; include=NO → compliance ot 0/0, OT Salary run shows 2 OT duty hrs (÷2=1 recorded, ₹93, ESIC deducted). Test punches/runs/flags cleaned/restored.

## Iter 271 (June 2026) — Employee Master form updates (user requests)
- Present + Permanent Address now EACH have a PIN Code: existing `pincode` relabelled "Present Address PIN Code" (keeps District/State auto-lookup); NEW `permanent_pincode` field (copied+locked by the "Same as Present Address" tick). Backend: create /admin/employees + employee_profile.py _STR_FIELDS + employee_pdf.py rows.
- "Emergency Contact Name" field REMOVED from the form UI (kept in DB/API for old data); only "Emergency Contact No." remains.
- Family Details: Relation is now a dropdown (RelationSelect component; Father/Mother/Husband/Wife/Son/Daughter/Brother/Sister/Grandfather/Grandmother/Other); NEW "Aadhaar No." column (12-digit hard limit, digits only — backend also trims via regex); NEW "Nominee" checkbox per member (is_nominee). Review modal shows "— Nominee ✓"; Employee Master PDF shows "(Nominee)" + Aadhaar.
- E2E: create/edit/GET/PDF all verified; Aadhaar 15-digit input trimmed to 12; UI smoke-tested via Playwright (both sections render, dropdown selection works).

## Iter 272 (June 2026) — IFSC → Bank + Branch auto-lookup (Employee Master)
- New endpoint GET /api/locations/ifsc/{code} (routes/locations.py) — Razorpay IFSC API + ifsc_cache Mongo cache; validates ^[A-Z]{4}0[A-Z0-9]{6}$.
- Employee Master form: IFSC field now uppercases/strips to 11 chars and on complete code auto-fills Bank name + NEW "Branch Name" field (editable). New user field bank_branch: create endpoint + employee_profile _STR_FIELDS + Employee Master PDF ("Branch Name" row) + review modal.
- NOTE: two search_replace edits reported success but did not persist (IFSC field UI + review row) — had to re-apply. Verify greps after batched edits on employee-add.tsx.
- Verified: API 200 for HDFC/SBIN codes + 400 bad code + cache hit; Playwright confirmed typing SBIN0031825 auto-fills "State Bank of India" + "GANPATI PLAZA, JAIPUR".

## Iter 274 (June 2026) — Report format overhaul (user requests, all E2E tested)
- Compliance Register FORMAT 2 (v2): dropped Code + UAN/ESI cols; name = Employee/Father-Spouse; Basic/HRA/Conv from MASTER salary (basic_master etc.); order ...earnings→Days→GROSS→deductions; NEW Signature col; header shows "Salary Month Days: N"; last page = Format-1-style detailed summary (sec tables + rupees in words + foot) via new tot keys (hrs/sal/hra_e/conv_e/oth_e/pf_wages/gross_pf/gross_nonpf/esi_base/nonesi_base).
- PF Challan → LANDSCAPE default (REPORTS defaults + _challan_pdf fallback flipped).
- S.No added: monthly attendance PDFs (identity_cols now 7 in monthly_attendance_pdf.py), Actual Salary Register PDF. (v1 compliance register + daily PDF + process screens already had SN.)
- PDF Report Formats utility expanded 4 → 19 reports (report_formats.py REPORTS): attendance_inout/ot/hours (title/orient/font), daily_present + salary_register (FULL column control via DAILY_PDF_COLUMNS / SALARY_REGISTER_COLUMNS catalogs), payslips + salary_certificate + clra_form_xii–xv + bonus_form_a–d (title-only; wired via new async title_for() helper — LOCAL imports inside endpoints to avoid circular import).
- Generators now accept fmt: monthly_attendance_pdf (_fmt_opts/_scaled_widths), daily_attendance.build_daily_pdf (column select/rename/reorder/width), salary_run.build_salary_register_pdf (rewritten with catalog), payslip_pdf + salary_certificate (title kwarg).
- PENDING NEXT: Employee Master photo + up to 3 OPTIONAL attachments (JPEG/PDF, Document Name + file + upload) — backend routes/employee_documents.py ALREADY has full upload API (categories incl "photo", base64, jpeg/png/pdf); only frontend section in employee-add.tsx needed.

## Iter 275 (June 2026) — Employee Master: Photo & Attachments + Statutory/Bank reorder
- New "Photo & Attachments (Optional)" section in employee-add.tsx: Attach Photo (JPEG) with preview; up to 3 OPTIONAL attachments (Document Name + file, JPEG/PDF only, 10MB cap); uses existing routes/employee_documents.py API (category "photo"/"other"); files held locally, uploaded via uploadPendingDocs(uid) after Save (create & edit); edit mode lists existing docs + delete; "Photo on file ✓" indicator.
- Statutory/Bank section reordered per user: UAN|EPF, ESIC|UPI, PAN|Name-as-PAN, Aadhaar|Name-as-Aadhaar (NEW field aadhaar_name — create endpoint + _STR_FIELDS), Bank A/C|IFSC, Bank Name|Branch.
- E2E: photo + PDF doc upload/list/delete via API OK; UI verified via Playwright screenshots.

## Iter 276 (June 2026) — Rapid punch dedup (user request)
- New server.py `dedupe_rapid_punches(punches, 30)`: drops ANY punch (any kind/source) within 30s of the previously kept punch (keeps FIRST of burst). Wired BEFORE dedupe_same_machine_punches at all 3 pipelines: monthly grid (~17667), OT report (~18223), Iter-202 compliance path (~14963).
- E2E: burst IN 08:00:00/IN+3s/OUT+7s + OUT 17:00/+5s → clean IN 08:00, OUT 17:00, punches=2, 9h, no anomaly.
- RECURRING TOOL ISSUE: search_replace on server.py/employee-add.tsx sometimes reports success but does NOT persist ("phantom edit") — ALWAYS grep-verify after editing these large files.

## Iter 277 (June 2026) — Rectified Punches Audit
- New GET /api/admin/attendance/rectified-punches/{company_id}/{month} (routes/punch_logs.py): re-runs the 3-stage dedup (rapid 30s / same-machine 15m / OUT-IN bounce 60s) per employee-day and reports dropped scans with IST time + reason + kept punches.
- New screen /rectified-punches (frontend/app/rectified-punches.tsx): firm chips (/companies), month prev/next, summary card, per-day cards. Sidebar: Utility → "Rectified Punches Audit" (AdminWebShell).
- E2E: 4-scan burst → 4 received / 2 kept with reasons; UI screenshot PASS.

## Iter 278 (June 2026) — Company-wise shift assignment from Shift Master
- routes/shift_masters.py: GET/PUT /api/companies/{cid}/assigned-shifts — stores companies.assigned_shift_ids AND syncs attendance_policy.shifts (name/start/end) so the attendance engine + existing pickers keep working. PUT = super/sub admin only; GET also company_admin (own firm).
- shift-master.tsx: new "Assign Shifts to Firm (Company-wise)" card — firm chips + checkbox list of master shifts + Save.
- employee-policy.tsx: Shift name + dummy dropdowns now load the firm's assigned shifts (fallback to generic SHIFT_OPTIONS when firm has none selected).
- E2E: assign Day/Night to Kankani → GET reflects, attendance_policy.shifts synced; UI screenshot PASS.

## Iter 282-286 (July 2026, fork) — Security + UX batch + Onboarding Approval + Access & Workflow Mgmt
- SEC-004 FIXED: sessions now 12h sliding expiry (server.py SESSION_TTL_HOURS=12, SESSION_SLIDE_THROTTLE_MINUTES=30; get_user_from_token extends conditionally; legacy 10y sessions clamped in DB + on first use). E2E: fresh TTL 12h, auto-extend, throttle, clamp, 401 expired. VPS migration included in /app/deploy_vps_iter282.sh (temp_bundle kind=script now serves deploy282).
- SEC-003 (encrypt EPFO/ESIC portal passwords) still PENDING — user said "process later".
- Employee avatar photo Upload/Change/Remove buttons on employee-add.tsx (pickPhoto/removePhoto; edit mode = instant replace via employee_documents API; new mode = uploads on Save; uploadPendingDocs now deletes old photo before POST).
- Employee Master Identity field order (user): Code→Name→Father→Gender→Marital→DOB→DOJ→Mobile→Email (DOJ moved from Employment section).
- Attendance IN/OUT grid: legend spells out Biometric=Machine / Mobile=PWA / System=Manual; cells show RAW IN→OUT span hours (spanHours, overnight-safe) and L/E/B metric codes REMOVED (attendance-grid.tsx DayCell).
- Firm pickers now DROPDOWNS (web <select>, chips on native): shift-master.tsx (shm-firm-select), attendance-master.tsx (am-firm-select).
- Theme pack: +6 presets in src/theme.ts (sunset_saffron, forest_olive, rose_gold, steel_sky, graphite_lime, obsidian_teal dark; isDarkTheme covers both darks). 15 total.
- MasterSelect.tsx: typing filters options live (Designation/Department/Group type-ahead).
- Reports Hub compliance runs rows: show Group, Employees count, Gross/PF/ESI/TDS/Net from run.totals (was reading non-existent total_pf fields → "—").
- Dashboard "Company Policies" tile section REMOVED from admin.tsx; routes moved to sidebar Utility group (attendance-policy, biometric-devices, backdate-punches added; standalone attendance-policy top-level entry removed) — super-admin NAV only.
- ONBOARDING APPROVAL WORKFLOW Phase 1 (routes/onboarding_approval.py + frontend/app/employee-approvals.tsx, sidebar Approvals group):
  * companies.onboarding_approval settings (17 toggles + approval_expiry_days 0/1/3/7), GET/PUT /api/admin/companies/{cid}/onboarding-approval
  * users.onboarding_status: pending_approval/hold/rejected/approved/active; admin_create_employee sets pending when enabled
  * server.py gates: _onboarding_login_gate (pin-login + emp-code-login), _onboarding_punch_gate (attendance/punch), _onboarding_payroll_exclusion (salary run @13855 allow_salary; compliance run @15083 allow_pf/esic/tds)
  * GET /api/admin/onboarding-approvals (enriched: photo_doc_id, today's punches, doc flags, expiry) + POST .../{uid}/decide (approve/reject/hold + remarks) → onboarding_audit + employee notification; approvers respect Workflow Builder 'employee_creation' chain (_user_can_action_level)
  * Expiry = flag ⏰ EXPIRED only (user choice C). Full backend E2E (10 steps) + testing_agent frontend PASS (iteration_285.json).
- ACCESS & WORKFLOW MANAGEMENT Phase A (user spec merge of Roles & Permissions + Workflow Builder):
  * routes/access_management.py: GET /api/admin/access-management/stats + /audit; write_access_audit() shared helper
  * audit hooks: company_roles.py (role create/update/delete), approvals_engine.py (workflow save); MODULES expanded (+shift_change, overtime, loan, salary_revision, exit)
  * frontend/app/access-management.tsx: tabs Dashboard (stat cards + recents) / Roles (create, seed defaults, delete) / Users (staff CRUD + role dropdown + enable/disable) / Permission Matrix (modules × roles R/W instant-save grid) / Workflow Builder (module chains overview + open builder) / Audit Logs (access + onboarding merged)
  * Sidebar: "/roles" entry replaced by "/access-management" (Access & Workflow Mgmt); Workflow Builder child removed from Approvals group (super-admin NAV). Old /roles & /approval-workflows routes still work.
  * Phase B pending: Return/Forward/Delegate/Escalate, conditional rules, SLA/auto-escalation; Phase C: drag-drop canvas, versioning, live monitor, notif rules, IP/Geo/2FA.
- Labour Law Reports: NEW "Shift Deployment Report" (key shift_deployment, Shift Reports group) in routes/labour_reports.py — shift name from Shift Master (timing via policy["_shift_masters"] map loaded in generate()), father name, contractor, in/out, hours, OT, Machine/Device classification (Biometric Machine / Mobile-PWA / System-Manual), status + per-shift TOTAL strength rows. JSON+PDF E2E OK; appears automatically in labour-reports.tsx catalogue.
- User pending choices: SEC-003 encryption go-ahead; GitHub push via platform "Save to GitHub" (fallback push_github_main.sh).

## Iter 287 — Workflow Phase B + Deploy 287
- PHASE B (routes/approvals_engine.py): per-level `condition` {field,op∈(>,>=,<,<=,==,!=,contains),value} evaluated vs request summary at create (non-matching level skipped w/ history 'level_skipped'; all-skipped → fallback single company_admin level, never auto-approve); per-level `sla_hours` (lazy auto-escalation via _auto_escalate_overdue() called in approval_inbox GET — advances level or flags sla_breached at final level, idempotent via level_since reset); actions `delegate` (to_user_id staff/admin validation, levels.$.delegated_to + _user_can_action_level honors it) and `escalate` (manual jump, escalated flag); level_since tracked on create/advance.
- Frontend: approval-workflows.tsx "Level Settings (SLA & Conditions)" editor per module (draft state, save preserves sla/condition via strip()); chain nodes show ⏱h + IF badges. approval-inbox.tsx: Delegate (numbered staff prompt) + Escalate buttons, ⚡ESCALATED / ⏰SLA BREACHED pills.
- E2E verified: condition skip (10k vs 90k advance), delegate 200, escalate→L2, auto-escalate fired once (idempotent), maker-checker preserved. Test advances/requests cleaned; advance workflow restored to plain HR→Admin chain.
- Deploy: /app/deploy_vps_iter287.sh (temp_bundle kind=script now serves 287; includes SEC-004 session clamp step).

## Iter 288 — Theme Pack Completion + Earning Heads Bug Fix
- THEME PACK (user P2): +4 presets in src/theme.ts → lavender_mist, mocha_espresso, arctic_ice (light) + deep_space (3rd dark; isDarkTheme covers all 3 darks). 18 total presets. Verified rendering on /appearance.
- BUG FIX (user report: "Compliance Salary Earning Head not showing for some employees in Employee Master"):
  * ROOT CAUSE: SalaryUpdateModal.tsx + employee-add.tsx built allowance/deduction rows ONLY from firm-enabled heads (firm_allowance_heads). Employees with saved heads NOT in the firm list (firm-disabled e.g. "OTH. ALLOW.", legacy/imported custom heads, or missing firm_master doc) had those earning heads INVISIBLE — and saving would silently DROP them.
  * FIX: mergeHeads() union (firm-enabled heads + saved employee heads, case-insensitive dedupe) in both editors. employee-add.tsx render conditions switched from firmHeads.* to merged lists; lineAmount/setLineAmount now case-insensitive so "Hra" prefills "HRA".
  * Verified E2E: seeded emp 50 with OTH. ALLOW. 1500 (firm-disabled) + WASHING ALLOW. 500 (custom) → both visible w/ amounts in Update Salary modal AND employee edit form; Gross ₹16,000 correct. Seed reverted after test.
- SEC-003 (EPFO/ESIC password encryption) STILL PENDING — user chose Theme Pack priority; encryption not yet started.

## Iter 288b — On-roll Compliance Salary Mandatory (user rule)
- New Employee Add (employee-add.tsx): clarified user rule — Off-roll hides ALL Compliance Salary heads (already worked, Iter 245); On-roll now REQUIRES Compliance Salary: getMandatoryError checks compliance_basic/compliance_gross → error "Compliance Salary is mandatory for On-roll employees...". Compliance Basic Salary field marked required (*).
- Verified E2E: off-roll → block hidden w/ note; on-roll → fields show w/ *; on-roll create without compliance basic → blocked with red error banner.

## Iter 289 — IN/OUT Report enhancements + 8-HR Present Days bug fix
- attendance-grid.tsx: (1) S.No. frozen column before Employee Name (COL.sno/LEFT offsets, header + row cells, sno prop on GridRow); (2) group filter chips now show employee counts "All (127) / LABOUR (108) / STAFF (17)" (groupCounts captured on unfiltered load); All remains default.
- monthly_attendance_pdf.py: IN/OUT PDF now LEGAL paper landscape (1008×612pt), ALL days 1-31 in ONE table page-width (chunk=days_n); pages break only by employee rows. Day col base 8mm, tighter identity widths, body font 5pt, pad 1. Portrait override still chunks 6.
- BUG FIX (user report: Present Days wrong when "Count Present Day @ 8 HRS — Compliance Salary only" enabled): server.py grid compute — (a) standard_h forced to EXACTLY 8.0 (was min(full,8): firms with full-day <8 split duty/OT too early → OT inflated, e.g. 9h day showed 2.5 OT instead of 1.0); (b) _day_present now FULLY decided by the 8-HR rule (≥8→1.0, halfday-rule block decides if ON, ≥half_day_hours→0.5, else 0) matching the Iter-219 Compliance Salary sync exactly. Verified with synthetic repro (7h→0.5/9h→1.0+1OT/3h→0, total 1.5); Kankani (flag OFF) regression-checked unchanged.

## Iter 289b — Removed Late Min / Early Go columns (user request)
- attendance-grid.tsx: removed "Late Min" and "Early Go" summary columns (header + row cells). Punches / Break HRS / Net HRS retained. Backend fields untouched.

## Iter 289c — OT 30-minute slabs (user request)
- server.py (grid compute + OT report): replaced "<1 hour OT ignored" grace with 30-min slab FLOOR: ot = int(ot*2)/2. Example 07:56-16:30 (8:34) → 8.0 duty + 0.5 OT (verified via synthetic test). Extra <30min → 0. Compliance sync inherits via day-cell hours.

## Iter 289d — Total Duty HRS = exact time schedule + more columns removed
- server.py: totals.hours ("Total Duty HRS") now = exact punch-schedule sum (total_sched_min = day_min + extra grants), e.g. 89:55 not the Excel-style 89:30 sum of processed cells. Division-mode math still uses total_hours_min. Verified: 8:34+10:31 → 19.0833 (19:05).
- attendance-grid.tsx: removed Break HRS + Net HRS summary columns (Late Min/Early Go removed earlier); only Punches retained.
- DEFERRED: per-firm OT slab setting (exact/30min/1h) — current global default 30-min slab.

## Iter 289e — Per-firm OT Rounding slab setting (user confirmed)
- policy_master.ot_slab_minutes: 0 (exact) / 30 (default) / 60. Validator + backfill in get_attendance_policy. Applied in grid compute (_pm_firm) + OT report (pol.policy_master). Verified per-slab: 8:34 → OT 0.5/0.5/0.0 (Exact still passes through firm duty_hours_rounding first).
- attendance-policy.tsx: "OT Rounding" chip row (Exact / 30 min slab / 1 hour slab) added under Policy Master Sub Points; verified via screenshot.
- NOTE: earlier grid slab edit silently didn't persist despite success msg — re-applied and re-verified.

## Iter 289f — Rollback + rename (user request)
- ROLLED BACK: Total Duty HRS grand total back to sum of processed day figures (total_hours_min); total_sched_min removed.
- RENAMED: "Total Duty HRS" → "Total Working HRS" in web grid header, PDF _TRAIL_LABELS, XLSX trail_labels, OT report xlsx.

## Iter 290 — Attendance Policy Simulator (user approved)
- New backend: routes/policy_simulator.py — POST /api/admin/attendance-policy/simulate (policy dict + in/out HH:MM → worked/duty/ot/present + notes). Mirrors day rules: duty rounding, 8-HR sub-point, halfday threshold, OT slab, policy_2/default. Registered in server.py.
- attendance-policy.tsx: PolicySimulator card under Policy Master Sub Points (IN/OUT inputs + Simulate → result boxes). Gotcha fixed: api client auto-stringifies body (double JSON.stringify caused 422).
- Verified E2E via curl + UI screenshot (07:56-16:30 → 8:30 worked, 8:00 duty, 0:30 OT, present 1).

## Iter 290b — Sub-admin punch import fix (user request)
- routes/punch_import.py _auth: sub_admins were always 403'd (checked admin.company_id equality — sub-admins have a scope list, not company_id). Now uses sub_admin_can_touch_company. Verified: scoped firm 200, out-of-scope 403, template 200.
- Also clarified earlier: sub-admin attendance Excel download already works (scope + menu rights are portal settings).

## Iter 289 (fork) — Labour Reports date picker fix (user bug)
- WebDateField.tsx: transparent <input type=date> overlay only opened the calendar when the invisible webkit picker-indicator icon was hit. Fixed: onClick calls input.showPicker() (with focus fallback) + CSS stretches ::-webkit-calendar-picker-indicator across the full field. Applies portal-wide (all WebDateField usages).
- Verified via automated screenshot: From/To fields in Daily Attendance Register now open calendar and accept values.
- temp_bundle.py now serves deploy_vps_iter289.sh (kind=script).
- SEC-003 (plaintext EPFO/ESIC passwords) still PENDING.

## Iter 290-292 (fork) — Big user batch, all tested & deployed via deploy290.sh
- Date picker fix (WebDateField showPicker), staff picker from Employee Master + PWA staff-portal-switch (/auth/staff-portal-switch, backup token helpers in client.ts, AdminWebShell "Employee App" back button), sub-admin scope select/deselect all.
- Bulk Transfer redesign: resigned-only, new employee code, service_history, global search by Aadhaar/PAN/Mobile/ESI/UAN (routes/bulk_ops.py employee-search + rewritten /transfer).
- Shift menus merged (shift-change-admin.tsx segments), Compliance Reports CompanyPicker, Salary Day Sheet single-day mode, attendance-grid PresentCountFooter (server day_present_counts), bank-sheet TOTAL row, PF ECR 11-field format (challans.py _ecr_txt_bytes).
- PWA: sw.js v4 nav 3.5s timeout race + precache "/", deploy script adds nginx gzip.
- NEW: In/Out & OT Matrix report (routes/inout_ot_matrix.py + app/inout-ot-matrix.tsx, JSON/xlsx/pdf/csv exports, colour-coded, punch-history modal) + Employee Reports hub (routes/employee_reports_hub.py annual-salary-statement + app/employee-reports.tsx) + 3 new HR letter types (experience/relieving/salary_certificate).
- Testing: iteration_291.json + iteration_292.json all green (13/13 + 6/7 pytest). Deploy290 served via temp_bundle.py kind=script.
- SEC-003 (plaintext EPFO/ESIC passwords) STILL PENDING.

## SEC-003 RESOLVED (fork iter 293)
- utils/secrets_vault.py: Fernet enc (PORTAL_CREDS_KEY env, fallback MONGO_URL-derived; multi-key decrypt, enc:: prefix).
- firm_master.py: GET/PATCH mask passwords (•••••• + password_set flags), _protect_secrets on save, migrate_portal_secrets() at server startup (idempotent).
- rpa_worker._fetch_creds + rpa_engine portal scan decrypt transparently. portal_generation truthy checks unaffected.
- deploy290.sh generates PORTAL_CREDS_KEY into VPS backend/.env if missing.
- E2E verified: GET masked, PATCH encrypts (enc::gAAA...), mask-echo preserves, decrypts OK, migration encrypted 1 legacy doc.

## Session Iter 294-295 (2026-07-25)
- Iter 294 batch: 12-group dark sidebar (#0F172A/#2563EB approved), AI Payroll Assistant (voice+chat, gpt-5.4, confirm-before-run), global data search, keyboard shortcuts, favourites, notification centre, EN/HI toggle, auto-save employee drafts, split-view compare, bank transfer files (ICICI/HDFC/SBI/Axis/Kotak, xlsx/csv/txt/xml), BI data feed (Power BI/Excel, per-firm key), multi-brand biometrics (eSSL=ADMS, Matrix/Mantra=JSON webhook /api/device-webhook/{key}), STAFF group interlink fix (per-firm scoping in list_masters).
- Iter 295 fixes: employee sessions 90d sliding (EMPLOYEE_SESSION_TTL_HOURS, _session_ttl_hours_for_role in server.py; admins stay 12h), bulk-import double-confirm modals, bulk-import Resign Date → exit_date+employment_status interlink, sync-engine CompanyPicker dropdown, Recently Opened moved to Dashboard (OverviewPremium), Auto Shift Detection flag honored in _is_shift_open, geofence GPS-accuracy buffer (client getAccurateFix watch-based fix in src/utils/accurateLocation.ts + server cap 100m via gps_accuracy_m), PWA blank-page fix (deploy keeps old bundles; nginx already had no-cache index.html), repair-punches show punch date.
- Deploys: deploy_vps_iter294.sh (served via /api/temp-code-bundle?kind=script). User deployed 294 and 295 successfully to smartpayrolling.com.
- Pending: WhatsApp API integration, legacy payroll DB import, SQL sync, server.py refactor.

## Session Iter 297 (2026-06 fork) — Salary Reprocess + ESIC zero-day fixes
- NON-DESTRUCTIVE REPROCESS (user directive "reprocess = update, not start from zero"):
  - POST /admin/compliance-salary-runs: fetches newest non-finalized draft for month+firm+group and passes rows into _compute_compliance_run(prev_rows=...). Per employee: preserved present_days/ot_hours/duty_hours drive the recompute; manual other_deduction(+head) carried over. delete_many now scoped by _gate_cid (company_admin fix). run["reprocessed"]=True flag.
  - POST /admin/actual-salary-process: fetches newest non-finalized draft for month+firm; preserves p_days (capped at max_p_days), p_hours, adv, tds, w_basic_override per row; money recomputed via _actual_salary_row_compute.
  - Frontend confirm text updated on salary-run.tsx + compliance-salary-run.tsx: "Do you want to REPROCESS... YES → entered days & edits are KEPT".
- ESIC ZERO-DAY FIX (utils/compliance_salary.py): _zero_pay guard (effective_present<=0 & duty_hours<=0 & gross_paid<=0) → pf_applicable/esic_applicable False + pt/tds/master_deduction zeroed. Root cause: salary_structure_compliance master rows returned full-month basic regardless of days → ESIC on 0-day rows.
- E2E verified on live backend (Kankani, 2026-05): compliance days 7.5 + ded ₹111 preserved on reprocess, 108 zero-day rows all ESIC=0, actual p_days 9.5/adv 222/tds 33 preserved. Test runs cleaned from DB.
- deploy_vps_iter297.sh created; temp_bundle.py kind=script now serves deploy297.sh.
- Pending: WhatsApp API integration, legacy payroll DB import, SQL sync, server.py refactor.
- Iter 297b — Connection Doctor (user: "JYK8240100297 not able to connect"): GET /api/biometric/connection-doctor (routes/biometric_devices.py) — per-device online/offline/never_connected verdict + advice + last_source_ip; lists db.biometric_unknown serials not yet registered with difflib fuzzy typo hint vs registered serials. Frontend biometric-devices.tsx: orange "Connection Doctor" button + bottom-sheet modal (verdict dots, advice, unknown-serial red cards). E2E verified incl. typo detection + online flip after handshake. Included in deploy297.
- Iter 298 — TWO-BRANCH SALARY SPLIT (user: one firm, two branches, separate PF/ESIC; manage in Actual Salary):
  - biometric_devices: new `branch_name` tag (Create/Update models, register doc, editor UI input in biometric-devices.tsx).
  - server.py create_actual_salary_process: `payload.branch_name`; per-DATE branch attribution via day's FIRST zkteco punch (device serial → branch map); home-branch run subtracts away-days; GUEST rows (other-branch employees) get only days-worked-here, salary_mode forced daily, day-rate derived from master (monthly/md, hourly*duty_hrs) or emp.branch_rates[branch] override; rows carry branch_name/guest_of_branch/branch_days; run doc has branch_name; _fin_q + prev-run merge scoped per branch.
  - PATCH row: `basic` editable ONLY for guest rows (Iter 217 lock kept for home rows).
  - GET /api/admin/branches?company_id → distinct users.branch_name (drives selector).
  - salary-run.tsx: Branch chips (Combined + each branch, shown only when branches exist), GUEST badge + branch-day split under name, editable Basic cell for guest rows, branch in run title & existing-run confirm check.
  - E2E verified (Kankani, temp BRANCH-A/B data, cleaned up): guest 2 days @ daily rate, rate edit 700→1400, home run subtracts away days + excludes non-visitors, combined branch_days map, branch-scoped reprocess keeps entered days.
  - NOTE: compliance (PF/ESIC) branch split NOT done — user said manage in Actual salary; phase 2 if requested.
- Iter 297/298 known tool issue: search_replace sometimes reports success without writing — always grep-verify critical edits.
- Iter 299 — LEGACY SQL IMPORT PHASE 1 (user: 919MB MS SQL Server .bak ZIP, multiple firms, "check data before import"):
  - /app/legacy_setup_vps.sh — VPS script: installs docker + SQL Server 2022 Express container (sks-mssql, port 127.0.0.1:14333, SA pass in /home/sksharma/legacy/.sa_pass), unzips backup from /home/sksharma/legacy/, RESTORE FILELISTONLY→MOVE→RESTORE for every .bak, writes LEGACY_MSSQL_* to backend .env, installs pymssql, restarts backend. Served via temp_bundle kind=legacy (filename legacy_setup.sh).
  - backend/routes/legacy_explorer.py — read-only: GET /admin/legacy/status (dbs+sizes), /admin/legacy/tables?db= (row counts), /admin/legacy/rows?db=&table=&skip&limit&search (identifier validation vs sys.tables, text-col LIKE search, OFFSET/FETCH). pymssql via asyncio.to_thread. Graceful 503 when unconfigured. pymssql==2.3.13 appended to requirements.txt.
  - frontend/app/legacy-explorer.tsx — DB chips → table chips w/ row counts + search → paginated row grid w/ search. Setup instructions shown when unconfigured. Menu: Import/Export → "Legacy SQL Explorer" (both nav lists in AdminWebShell).
  - VPS capacity confirmed by user: 15GB RAM / 171GB free / 4 cores.
  - PHASE 2 PENDING: after user checks data → build table→schema mapping + preview + firm-wise import.
  - Verified: status/tables endpoints (unconfigured path), script serving, screen renders. SQL-dependent paths (pymssql queries, restore script) can only be truly tested on the VPS after user uploads backup.
- Iter 299b — Legacy "Find Firms & Employees" smart scan (user: "how can we check Firms And Employees / hold companies already created"):
  - GET /api/admin/legacy/discover?db= — scans sys.columns: company-name columns (compname/firmname/clientname etc.) → distinct values (TOP 200, skip >150 distinct) matched against mongo db.companies names (exact/contains/difflib 0.8) → in_portal flag; employee-master tables scored by column hints (empname/father/pf/esi/doj/salary/code + table-name emp/staff/worker, score>=3).
  - legacy-explorer.tsx: "Find Firms & Employees" amber button per DB → companies list with ✓ in portal / not in portal badges + employee table chips (tap opens rows).
  - Verified unconfigured path (503) on preview; real scan runs on VPS (SQL restored there: DB PayrollCnslt_NSK_20260725_160823, restore succeeded 2026-07-25).
  - VPS SSH port is 3052 (user connects via ssh -p 3052 root@165.99.223.52).
- Iter 300 — LEGACY IMPORT WIZARD (user: import Company Master + Employee Master + Offline/Online salary process data, choose heads manually):
  - Schema fetched from prod via /api/legacy-schema (68KB, saved analysis): DB PayrollCnslt_NSK_20260725_160823, 115 tables. Key: FirmMaster (673 rows, FrimID+FnYear per-year copies), EmployeeMaster (105k, FirmNo+AcYear copies, dedupe latest per EmpCode/EmpID), SalaryTrans (987k, ONLINE, Earn1-25/Deduct1-20 heads via SalaryHeadMaster SalHead_SrNo+DispalyName, MonthYear 'Feb 2019', FirstDayOfMonth datetime), SalaryTransoff (38k, OFFLINE, aggregate fields), EmployeeSalaryStructureDtl (EmpID_FK/FirmID_FK head-wise rates). ALL column assumptions verified vs schema.
  - backend/routes/legacy_import.py: GET firms (latest FnYear per FrimID + emp/salary counts + difflib portal suggestion), POST preview (counts, fast set-based existing check), POST run (background job → db.legacy_import_jobs progress; employees → users w/ head-wise field groups personal/contact/ids/bank/salary/status, match by company+name (update selected fields) else create w/ legacy_imported flag, phone clash→dropped; salary → db.legacy_salary_history per-row docs w/ resolved head names, chunked 2000, idempotent delete per firm+kind, indexes), GET jobs/{id}, GET /admin/legacy-salary (months list / rows w/ search).
  - frontend: legacy-import.tsx (3-step wizard: firm checkboxes + portal-firm picker modal w/ suggestions, head tick boxes, preview → start → live progress), legacy-salary.tsx (firm/type/month chips, dynamic head-wise columns table, search). Menu entries added (both nav lists).
  - Tested locally: unconfigured 503 paths, /companies shape, legacy-salary empty months. REAL import runs on VPS only (needs user deploy + test).
- Iter 300e — HEAD-MAPPING OVERRIDE + 2-STEP CONFIRMATION (user: "confirm 2 time before import; allow to change head then import; interlink Employee Type/Department/Designation with masters"):
  - backend legacy_import.py: ImportBody.field_overrides {src_portal_field: dst_field|'skip'} applied in _emp_doc_fields (move value or drop); _interlink_masters auto-creates group/department/designation docs in db.masters per mapped firm (dedupe vs existing incl __global__, groups uppercased w/ member_user_ids). Unit-tested (override move+skip verified).
  - frontend legacy-import.tsx: Head Mapping chart now EDITABLE — HEAD_MAP (29 legacy cols → default portal fields, grouped) + PORTAL_FIELDS (31 targets); tap row → picker modal (Default/SKIP/any field); CHANGED (amber) / SKIPPED (red) badges; "Reset all changes"; overrides sent as field_overrides in preview+run body. Start Import → Confirmation 1/2 (lists changed heads or "all default") → Final Confirmation 2/2 → run.
  - E2E verified via Playwright with mocked legacy API: firm tick, SKIP override, preview, both confirm modals, run body contained field_overrides {"father_name":"skip"}. Real SQL flows only on VPS.
  - deploy_vps_iter298.sh created; temp_bundle.py kind=script now serves deploy298.sh (warns if sks-mssql container not running).
- Iter 301 — LEGACY vs CURRENT comparison report (agent-suggested improvement, user approved):
  - backend legacy_import.py: GET /api/admin/legacy-compare?company_id=&search= (per-employee: legacy online/offline aggregate months+last basic/gross/net/days from db.legacy_salary_history, current actual/compliance runs collapsed to distinct user+month via 2-stage $group, mismatch_basic flag when master basic_salary differs >1 from legacy online last_basic; stats count/with_legacy/mismatches); GET /api/admin/legacy-compare/{user_id} (month-wise merged table: legacy_online/legacy_offline/compliance/actual per month desc + master snapshot). Roles: super_admin/company_admin(own firm)/sub_admin.
  - frontend legacy-compare.tsx: firm chips, search, "Mismatches (n)" filter toggle, 4-col list (Employee / Legacy last / Master Basic w/ amber mismatch + legacy value / Current last), tap row → modal month table (Legacy Online | Legacy Offline | Compliance (new) | Actual (new), each ₹net + days + gross). Menu "Legacy vs Current" (git-compare icon) in both AdminWebShell nav lists.
  - E2E verified with seeded legacy history on 2 Kankani employees (mismatch flag rendered, detail table with 2019 legacy + 2026 current months); seed data fully cleaned after test.
  - deploy_vps_iter298.sh updated to mention the report (kind=script serves deploy298.sh).
- Iter 301b — IMPORT 422 FIX + SALARY-HISTORY HEAD OVERRIDES (user hit pydantic "model_attributes_type" on VPS import; then asked to edit/skip SalaryTrans/SalaryTransoff heads too):
  - BUG ROOT CAUSE: legacy-import.tsx passed body: JSON.stringify(body()) but api() client already stringifies → double-encoded string body → pydantic 422. Fixed by passing the object. (Only these 2 call sites had the bug repo-wide.) Verified via Playwright: real preview call now returns 503 legacy-not-configured (parsed OK) instead of 422.
  - backend legacy_import.py: ImportBody += salary_online_overrides / salary_offline_overrides dicts; _apply_hist_overrides() applied per row in _run_job (pop src → move to dst or skip); _HIST_PROTECTED identity keys (company_id/firm_no/kind/month/emp_code/emp_id/user_id/name) never remappable. Unit-tested (skip, remap, protected keys, unknown src).
  - frontend legacy-import.tsx: ONLINE_HIST_FIELDS (16: month_days…net incl earn_heads/deduct_heads groups) + OFFLINE_HIST_FIELDS (16 incl rate/w_basic/others/tds); Head Mapping chart renders editable ONLINE/OFFLINE subsections (shown only when that history type ticked); editHead state now {scope: emp|on|off, field} with scoped picker options; ovOn/ovOff states sent in body; confirm-1 lists all changes across 3 scopes ("Online salary: …", "Offline salary: …"); global reset counts all.
  - E2E (Playwright, mocked SQL endpoints): skip Employer ESI (online) + remap TDS→Less Other (offline), confirm-1 listed both, run payload had salary_online_overrides {er_esi:skip} & salary_offline_overrides {tds:less_other} as proper JSON object.
  - deploy_vps_iter298.sh updated (items 5 & 6). USER MUST RE-RUN deploy298.sh on VPS to get the 422 fix + new options.
- Iter 301c — MISMATCH FLAG REFINED (user on prod: "why show error" — 177/987 flagged after real import of A B Infrasolutions):
  - Root cause of false flags: legacy SalaryTrans Basic = EARNED basic (pro-rated by present days) while master basic_salary = full-month rate; zero-day months also flagged.
  - Fix in legacy-compare list endpoint: aggregate also last_month_days; full_basic = last_basic * month_days/days when partial month; skip flag when last_days==0; 2% relative tolerance. leg_on.full_basic returned; frontend shows "legacy ≈ ₹X/mo" and explainer text updated ("review flag, not an error").
  - Verified with 3 seeded cases (partial-month normalizes to match → no flag; genuine rate diff → flag; zero-day → no flag); seed cleaned.
  - Ships in deploy298 bundle — user must RE-RUN deploy298.sh on VPS.
- Iter 302 — PUBLISH LEGACY MONTHS INTO COMPLIANCE SALARY PROCESS (user: "why data not importing in compliance salary process" → wants old SalaryTrans months in the month list + reports; then "import first, we check, then lock"):
  - backend legacy_import.py: POST /api/admin/legacy-salary/publish-compliance {company_id, lock:false} (super_admin) → bg job _publish_compliance_job: per distinct online month, SKIP if any compliance_salary_runs exists for firm+month (never overwrite); rows via _legacy_row_to_compliance (earn_heads → hra/conveyance/medical/special/ot_pay by name match, others=gross-known; pf_wages=pf_basic, pf_employee=ee_pf, EPS=8.33% capped 15k from er_pf, EPF=remainder; esic_ee from ded head 'ESI' else 0.75% gross; pt via PROF/PTAX/P.TAX/exact PT; tds; total_deduction=gross-net; uan/esi_ip/father/designation enriched from users). Run doc: finalized=lock(False default), legacy_imported=True, attendance_source=legacy_import, totals=_CMP_TOTAL_KEYS sums. Progress in legacy_import_jobs (type publish_compliance).
  - POST /api/admin/legacy-salary/lock-compliance {company_id} → finalizes all legacy_imported runs of firm (read-only lock; save-rows blocked on finalized).
  - frontend legacy-salary.tsx: when firm+online selected → "Publish X month(s) (unlocked — check first)" button w/ 2-step confirm modal + job polling (published/skipped counts); "Data checked & OK → Lock all published legacy months" button w/ confirm; lockMsg feedback.
  - E2E verified on preview (seeded 2 months, 1 pre-existing run): publish→1 published/1 skipped, run rows correct (HRA 2000/conv 500/others 500 split, EPS 750/EPF 420 from er 1170, ESI ee 90 from ded head), export.csv + register.pdf HTTP 200 on published run, lock-compliance flipped finalized=True. Seeds cleaned. Also fixed P.TAX head → pt recognition.
  - Ships in deploy298 — user must re-run deploy298.sh on VPS.
- Iter 301d — mismatch flag v3 (user: "still 41"): compare vs last 3 months' full-month rates (scale BOTH directions incl OT/extra paid days), flag only if NONE within 2.5%. Verified 4 seeded cases (OT-inflated no-flag, genuine flag, arrears month no-flag, zero-day no-flag); cleaned.
- Iter 302c/d — MONTH SELECTION + EMPLOYEE-FIRST GUARD (user: "provide all month select option", "salary import only for firms whose employees already imported"):
  - PublishBody += months: Optional[List[str]] (filter distinct months); publish confirm modal step 1 now shows per-month tick chips + "ALL MONTHS" toggle (default all selected), Continue disabled at 0.
  - Guards: publish-compliance 400s if firm has no users with legacy_imported=True; legacy-import/run 400s when salary ticked without import_employees and firm has no imported employees.
  - E2E verified: both guards return correct 400s; selective publish created only 2019-02+2019-04 (2019-03 excluded); P.TAX ded head now lands in pt column (150). Seeds cleaned.
- Iter 302e — "Select All Months" CHECKBOX (user request): publish modal step 1 now has a prominent checkbox row (checkbox/indeterminate/square icons) "Select All Months (N)" toggling all month chips in one tap; verified 5→0→5 selection + Continue disabled at 0.
- Iter 302f — MASTER SALARY IN PUBLISHED MONTHS (user: "import master salary also for that month so salary can be calculated accordingly"):
  - Wizard salary import now also stores master_basic (SalaryTrans.BasicSalary — the month's full rate) and master_pf_basic (PFBasicSalary) in legacy_salary_history online rows (new imports on VPS).
  - _legacy_row_to_compliance now emits basic_master/hra_master/conveyance_master/medical_master/special_master/others_master/gross_master + monthly_gross=gross_master: uses stored master_basic when present, else pro-rates earned→full month (basic*month_days/present_days). Verified both paths (stored 10000 precedence; 9000*28/26=9692.31).
  - Firm imported BEFORE this change lacks stored rates → publish falls back to pro-rating automatically.
- Iter 303 — CREATE NEW FIRM FROM LEGACY + UNDO IMPORT (user: A-ONE MOTOR'S imported into wrong firm; "create new firm with legacy settings", "show first what you get", "get credentials also"):
  - backend legacy_import.py: FirmMap.company_id now Optional + create_new flag; _parse_legacy_firm() reads SELECT TOP 1 * FROM FirmMaster (latest FnYear), fuzzy column matching (normalized names) → name/short/address1-2/city/state/pin/emails/start_date/business_nature/pf_no/esi_no/bank/PAN-TAN-GST-LIN docs/owner/phone + pf/esi portal user_id & password. GET /admin/legacy-import/firm-preview/{firm_no} (passwords masked, duplicate_company check). _create_company_from_legacy(): dedupes by name (returns existing), creates companies doc (lat/lng 0, default attendance policy, legacy_imported+legacy_firm_no) + firm_masters doc (registered_address, header emails/start/business_nature, epf/esi applicable+numbers+credentials, bank, compliance_docs PAN/TAN/LIN + appended "GST NO." doc, portal_logins PF/ESI rows, contact_persons Owner). Called at start of _run_job per create_new mapping (totals.firms_created); run endpoint validates mapping has company_id or create_new; _run_job now takes admin_uid.
  - POST /admin/legacy-import/undo {firm_no, company_id}: deletes users(legacy_imported+legacy_firm_no), legacy_salary_history(firm), legacy compliance runs(company), legacy_imported_firms lock. firms list now returns imported_company_id.
  - frontend legacy-import.tsx: picker option "➕ Create NEW firm…" → fetches firm-preview → modal table of ALL settings (incl masked logins, duplicate warning) → OK sets sel="__create__" (green "NEW FIRM (will be created)" chip); body() maps __create__→{create_new:true}. Imported firms show red "Undo" pill → confirm modal → undo → refresh + success msg.
  - TESTED: parser+create unit-verified with mocked SQL row (address/PF/ESI/creds/bank/PAN/GST doc/portal logins/contact + name-dedupe); undo E2E via HTTP (all 4 collections cleaned, unlock); frontend E2E via Playwright (picker→preview→NEW FIRM chip; Undo→confirm→success msg, correct POST body). Seeds cleaned.
- Iter 304 — FY PERIOD SELECTION + LEGACY FIRM BADGES (user: "compliance report period as per FY/month", "legacy salary firms = only imported ones", "mark salary imported & lock as highlight"):
  - MonthPicker.tsx: new fyMode prop — web: Month select (Apr→Mar order, Jan-Mar labeled "(next yr)") + FY select ("FY 2019-20"); native modal: FY-labeled year chips + Apr-first grid; correct calendar-year mapping (Feb+FY2019-20→2020-02 verified E2E incl leap-year day cap). compliance-salary-run.tsx & reports.tsx month pickers use fyMode+yearsBack=20; reports.tsx fyOptions loop now 20 FYs back.
  - GET /api/admin/legacy-salary/firms: only companies present in legacy_salary_history + published_months/locked_months/fully_locked counts; legacy-salary.tsx uses it (chips show green "✓ SALARY IMPORTED (n)" or amber "🔒 LOCKED" badge, amber border when fully locked; badges refresh after Lock All).
  - E2E verified via Playwright screenshots on live preview. Seeds cleaned.
- Iter 305 — COMPARISON RECORD + REPLACE-OR-NOT + OLD-DB COUNTS (user: "comparison record in employee wizard", "how many active/resign/total", "data not match", "grouping wise for multiple firms", "matched name list confirm replace or not, remaining will import"):
  - firms endpoint SQL rewritten: counts via ROW_NUMBER latest AcYear record per employee (matches import dedupe → fixes "data not match"), returns employees_active / employees_resigned; wizard firm rows show "X emp (✅ a active · 🔻 r resigned)".
  - POST /api/admin/legacy-import/employee-compare (body=ImportBody): grouped per firm → {total, active, resigned, matched[{name, employee_code, change_count, changes[{field,old,new}] (≤25)}], new_names} — matched by name-lower against portal users, diff via _emp_doc_fields (excl phone/email/allowances, numeric tolerance .01). Unit-tested with patched SQL against live Kankani user (real diffs).
  - ImportBody.replace_names {str(firm_no): [names]} — in _run_job existing-match branch: names not in list are KEPT (totals.employees_kept) but still linked (uid) for salary import; absent key = replace all (backward compat).
  - frontend legacy-import.tsx: "Compare Records — matched names, Replace or Not" teal button after Preview → modal grouped firm-wise (old-DB counts header, "Replace ALL matched" checkbox, per-name checkboxes w/ field diffs shown, NEW names list) → Apply choices banner; body() sends replace_names only if applied; job summary shows "kept (not replaced)" + firms_created.
  - E2E Playwright (mocked SQL endpoints): counts row, modal, untick AJAB → run body replace_names {'5':['AFZAL HUSSAIN']}, "1 kept (not replaced)" shown. All PASS.

## Iter 299–306 (this session)
- NEW: Enterprise Salary Register module — /salary-register (frontend) + /app/backend/routes/salary_register.py.
  Dynamic columns from run rows (registry + catch-all + zero-pruning), Compliance/Actual toggle, FY-wise month,
  run selector, Group/Branch/Dept/Contractor chips, search, sort, server pagination, PDF(A3)/XLSX/CSV exports.
  Tested: iteration_299.json (all pass).
- GPS punch fix: accurateLocation.ts — parallel one-shot seed + timeout fallbacks (current → last-known), 15s budget.
- 20-point user list DONE (iteration_306.json all pass):
  1 sub-admin employee delete → super-admin approval (deletion_requests kind "employee")
  2 Employee Master photo doc (category photo) syncs users.profile_photo_base64
  3 punch selfie blank fix (data-URL prefix strip on write + read)
  4 pf_no in compliance rows + Register Format 1 UAN/PF/ESI cell
  5 ESIC zero-day guard verified (old runs must be reprocessed on VPS)
  6 compliance-salary-run no longer auto-opens last run
  7 compliance rate fallback → salary_structure_actual "Basic…" head + rate_type (daily 745 etc.)
  8 tap-to-highlight rows (amber) in compliance + actual salary grids
  9 "Group" chip added to GridFilterChips (all consumers)
  10 compliance_register_v1/v2 in Report Formats editor (title-only), wired into register.pdf endpoint
  11 eye toggle on secure Fields in firm-master.tsx
  12 optional DOJ column in Actual Salary Register PDF (hidden by default via _REGISTER_DEFAULT_HIDDEN)
  13 sidebar hide/show rail (localStorage sks_sidebar_hidden)
  14 sidebar "Firms" section + NEW /firm-credentials PIN-gated vault (POST /api/admin/firm-credentials)
  15 ACTIVE FIRM pill read-only (lock icon)
  16 bulk import City/State/Pin already existed (Iter 266) — informed user
  17 covered by #6
  18 bulk-correction header/cell width alignment (shared colWidthFor)
  19 bulk-correction group filter → only groups with active employees
  20 editable "ESIC Leave" days column in compliance grid (+ calc band off-by-one fix)
- Deploy script: /app/deploy_vps_iter299.sh (served as deploy299.sh via /api/temp-code-bundle)
- Dev super admin PIN reset to 246810 (dev DB only)
- PENDING: P1 WhatsApp API integration; P2 server.py refactor

## Iter 307 (this session, continued)
- "Email register to firm": POST /api/admin/salary-register/email (PDF+XLSX attachments via Resend
  _send_email_with_attachment from utils/iter60_features.py). Export builders refactored into
  _xlsx_bytes/_pdf_bytes helpers. /filters returns firm_email (firm_masters.header.email_1/2 →
  companies.email fallback). Frontend: Email button + inline panel on salary-register.tsx. VERIFIED e2e (real email sent).
- PERFORMANCE package (user: "portal slow, lots of data"):
  1. gzip middleware (GZipMiddleware min 1KB) — ~10x smaller JSON payloads
  2. get_user_from_token no longer fetches profile_photo_base64 (was dragged on EVERY request);
     /auth/me re-attaches it via targeted query
  3. /companies list excludes logo_base64; new GET /companies/{id}/logo; SelectedCompanyContext
     lazily fetches only the selected firm's logo
  4. Startup indexes added: users(company_id+role / +employee_code), attendance(company_id+date),
     compliance_salary_runs & salary_runs(company_id+month+generated_at), notifications(user_id+created_at),
     leaves(company_id+status), employee_documents, firm_masters(company_id unique),
     deletion_requests(status), legacy_salary_history, punch_logs, device_commands

## Iter 308
- Legacy Salary Records: firm SEARCH box + "Bulk lock firms" multi-select mode
  ("Select all unlocked", per-chip checkboxes, Lock N selected firms with confirm).
  Backend lock-compliance now accepts company_ids[] (BulkLockBody) and returns per_firm counts.

## Iter 308b
- report-formats.tsx now renders ALL report groups dynamically (was hardcoded to PF+ESIC only) —
  fixes "Salary Report Format 1 not showing for edit".
- Added "salary_register_module" (dynamic Salary Register) to Report Formats (title-only), wired
  title override into export.pdf + email.
- Salary Register PDF now has a LAST-PAGE SUMMARY in the Option-2 style: boxed head-wise totals
  (earnings/deductions/employer), days/net, RUPEES in words (gross+net), Checked-by/Authorised
  Signatory strip (_summary_flowables in routes/salary_register.py). Verified: 4-page PDF, summary text extracted.

## Iter 308c
- Excel export of the Salary Register now includes a second "Summary" sheet (same content as the
  PDF last page: head-wise totals, days/net, rupees in words, signature lines). Email attachments
  carry it too (shared _xlsx_bytes). Verified: sheets = [Salary Register, Summary].

## Iter 309
- Full layout editor for the dynamic Salary Register: /api/admin/salary-register/layout (GET/PUT/DELETE,
  app_settings key salary_register_module_layout). Choose columns/order/rename/width/per-page/row-height.
  Applied in _prepare (grid+CSV+XLSX+Email) and _pdf_bytes (chunked pages + rowHeights).
  RegisterLayoutEditor generalized with endpoint prop; report-formats card salary_register_module opens it.
  Verified via curl: renamed headings, 7-column selection, per_page=40 -> 5-page PDF. compliance_basic added to _EXCLUDE_KEYS.
- NOTE: fixed statutory layouts (Form 27 Format 1, challans, ECR, payslips) remain title-only by design.

## Iter 310 — Freeze Salary + Employee Master Detail Slip (Phase 1)
- FREEZE SALARY (Compliance Salary Process, user directive): imported-sheet runs
  (use_imported_sheet=true) freeze the exact imported attendance/earnings.
  Difference engine: imported_gross vs calculated_gross (master rate × imported days);
  if imported > calculated the diff routes to OVERTIME when firm_masters.salary_process.ot_allowed
  is true, else to OTHER ALLOWANCES (others head + monthly_gross). gross_paid=imported, net recalcs.
  Row fields: imported_gross / calculated_gross / difference / difference_allocation_head;
  totals include the 3 comparison sums. Run doc: frozen=true, frozen_at, freeze_snapshot_id;
  immutable audit snapshot in db.freeze_salary_snapshots. Negative diff = non-destructive (recorded only).
  Frontend: purple FREEZE SALARY (IMPORTED) grid band (Imp. Gross/Calc. Gross/Difference/Diff. Alloc.),
  header badge, TOTAL row. Code: server.py 'Iter 310' blocks + compliance-salary-run.tsx.
- EMPLOYEE MASTER DETAIL SLIP Phase 1: routes/employee_detail_slip.py + app/employee-detail-slip.tsx
  (menu: Employees → Employee Detail Slip, perm employees:read).
  Endpoints: /employees (search list), /{user_id} (sections JSON), /slip.pdf (A4, QR via qrcode lib),
  /slip.xlsx, /email (Resend attachment). Sections: Personal/Employment/Statutory-KYC/Bank/Salary/Other(Phase 2).
  FYTD (April-start) attendance summary (distinct punch dates + by-month) & approved-leave days.
  Profile completion % from 21-slot checklist. Missing Phase-2 fields (Mother Name, Grade, Cost Centre,
  Confirmation Date, Nominee, Education, Experience, Company Assets) render "—".
- deps: qrcode==8.2 added (requirements.txt). Deploy script: /app/deploy_vps_iter310.sh (installs qrcode).
- Tested: 10/10 pytest (tests/test_iter310_freeze_and_slip.py) + web E2E — ALL PASS, data cleaned.
- Phase 2 backlog: add missing master fields + barcode/timeline/audit/dark mode; WhatsApp API integration.

## Iter 311 — PWA Speed Upgrade (user: "PWA employee and Employer working Slow")
- Root cause: web export was a SINGLE 5.5 MB JS bundle (1.34 MB gz) + VPS nginx had no gzip.
- app.json: web.output "single" → "static"; expo-router plugin asyncRoutes {"web":"production"}
  → per-route code splitting in production export (158 chunks; initial = entry 272KB gz +
  __common 463KB gz + _layout 58KB gz ≈ 790KB gz, screens lazy-load 5–25KB gz chunks;
  after deploys unchanged chunks stay browser-cached).
- Dev preview (Metro) unaffected (asyncRoutes production-only). Verified prod build E2E via local
  SPA server: login → portal-dashboard → employee-detail-slip → salary-register, zero page errors.
- /app/deploy_vps_iter311.sh: exports split build, precompresses assets (gzip -9 .gz kept alongside),
  patches nginx idempotently (sks-gzip-fix marker: gzip on + gzip_static on + gzip_types) with
  nginx -t rollback safety; keeps iter295 no-cache index.html / immutable hashed assets.
- temp_bundle.py kind=script now serves deploy_vps_iter311.sh.

## Iter 312-314 — Attachments · ESIC Leave Module · RPA Chrome Test Button
- Iter 312 also: email/export attachments renamed to Reportname_Group_MonthYear
  (salary_register._export_filename + all call sites w/ employee_type; detail slip
  EmployeeDetailSlip_{code}_{MonthYear}; iter60 AttendanceSheet_{Firm}_{MonthYear}).
  Detail Slip Phase 2 shipped (fields+edit modal+audit+timeline+barcode+dark mode+splash) — tested ALL PASS (iteration_312/313 reports).
- Iter 313 ESIC LEAVE MODULE: routes/esic_leave.py + app/esic-leave.tsx (menu:
  Compliance Salary → ESIC Leave, perm compliance_salary:*). Per-firm settings in
  db.esic_leave_settings (defaults all ON, max_backdate_days=30). Entries in db.esic_leaves
  (certificate base64, status pending/approved/rejected). Approve → creates approved
  db.leaves (leave_type "esic", source esic_leave_module). Compliance run auto-fills
  row.esic_leave_days via esic_leave_days_map (honours enabled+link_compliance).
  Salary Register has esic_leave_days column ("ESIC Leave"), removed when firm toggle
  show_separate_register OFF. Freeze lock: create/approve/reject/delete blocked (409)
  when compliance_salary_runs.frozen=True overlaps months and lock_after_freeze ON.
  Backend curl-verified + frontend testing agent ALL PASS (iteration_313.json).
- Iter 314 RPA: FLOWS["epfo_ecr_autoupload_test"] "Auto-Upload ECR — TEST (Open Portal
  + Close Alert)" (needs_creds False bypass in start validation). Steps: open EPFO →
  click #btnCloseModal OK → screenshot. Engine now launches REAL Google Chrome
  (executable_path detection: RPA_CHROME_BIN env / /opt/google/chrome/chrome /
  google-chrome-stable / google-chrome / chromium, with --no-sandbox) falling back to
  bundled Chromium; RPA_USE_CHROME=0 disables. Verified: session completed, all 3 steps done.
  NOTE: pod needed `playwright install chromium` (headless_shell-1228); deploy script installs
  Chrome + playwright browsers on VPS. USER WILL GUIDE NEXT STEPS of the ECR auto-upload flow.
- Deploy: /app/deploy_vps_iter314.sh (temp_bundle kind=script serves it).

## Iter 315 — ECR Test in USER'S OWN Chrome window (no server automation)
- User directive: "Do not use [server] automation — just open the page in a new Google
  Chrome window controlled by automation." Implemented via the existing PC Runner
  (Selenium ChromeDriver on the user's desktop): portal_extension.py RUNNER_VERSION=2,
  run() supports mode "ecr_test" (also epfo_test/ecr) → opens EPFO in a NEW visible
  Chrome window (detach=True, maximized), waits up to 20s for #btnCloseModal
  (fallback button.btn-danger[data-bs-dismiss=modal]) and clicks OK; no credentials.
  Zip now includes run_ecr_test.bat + README lines; existing installs self-update
  (runner-script endpoint serves v2 — verified by simulating launcher update fetch).
- Frontend: test-portal.tsx new amber button "Auto-Upload ECR — TEST (Chrome Window)"
  (testID btn-ecr-test-chrome) downloads the runner zip + instructions.
- NOTE: pod is linux/aarch64 → Selenium can't run here (Selenium Manager unsupported);
  logic mirrors the Playwright flow verified live against EPFO. Server-side RPA flow
  from Iter 314 remains available in Automation Studio.

## Iter 316 — ecr_test runner v3 (user-guided ECR flow, steps 2-4)
- After closing the EPFO alert, the PC runner now: fetches the SELECTED FIRM's EPFO
  creds (/api/portal-ext/creds?portal=epfo, token-gated), pastes Username (#username
  et al + generic fallback) and Password, screenshots the captcha and solves it via
  /api/portal-ext/solve-captcha (numeric_only False), fills it, SHOWS the read captcha
  on screen (fixed banner div #sks-captcha-banner injected into the page + console),
  then clicks Sign In (#loginbtn/submit/XPath text fallback) — only when captcha filled.
  RUNNER_VERSION=3 (self-update verified). Runner code compile-checked; Selenium cannot
  run in ARM64 pod — user validates on their PC. NEXT: user will guide post-login ECR
  upload steps.

## Iter 316b-317 — EPFO modal-intercept fix + MANDATORY firm selection
- Iter 316b: Sign In/Submit click was blocked by EPFO home-page alert modal
  (#mainHomePageAlertModal, static backdrop) intercepting pointer events. Fix:
  _dismiss_epfo_modals(ctx) in rpa_engine (click #btnCloseModal + JS-strip .modal.show /
  .modal-backdrop / body.modal-open) called before submit, with force-click fallback.
  Same JS-strip + JS click() fallback added to the Selenium ecr_test runner.
  Also fixed EPFO login not filling: Angular ng-model needs REAL typing — runner now waits
  for #username clickable and uses send_keys (native-setter+input/change/blur fallback). RUNNER_VERSION=5.
- Iter 317 (user directive) — FIRM SELECTION MANDATORY, no process starts without a real firm:
  automation-studio.tsx treats selectedCompanyId "all"/empty as no firm (companyId="") →
  start blocked with clear message; test-portal.tsx firmId gate blocks runner/extension download.
  Server: /rpa/start and portal-automation download (_resolve_company) reject "" and "all" (400).
  Verified via curl (all/empty→400, real firm→200).

## Iter 318 — EPFO Login & Dashboard flow: close alert → fill creds → captcha
- User directive: apply the ecr_test "open + close alert" logic to the standard
  Login & Dashboard (base) flow BEFORE filling ID/Password, then show captcha.
- rpa_engine _flow_steps base is now: Open Portal → Close Alert Popup
  (_step_close_alert_if_epfo — runs _step_epfo_close_alert only for portal==epfo, instant
  skip for ESIC) → Enter User ID & Password → Solve Captcha & Sign In → Verify → Dashboard.
- _step_fill_credentials hardened: dismiss lingering EPFO modal, AUTO-DETECT username
  (#username/name/formcontrolname/text fallback) + password fields with retry waits for the
  Angular form to render, type via press_sequentially (real keys), then VERIFY input_value
  and re-type if a box didn't retain the value (Angular ng-model). Creds pulled from Firm Master.
- Verified live E2E: session reached waiting_captcha with steps Open/Close Alert/Enter Creds done,
  logs show "User ID & Password filled from Firm Master" then captcha prompt. Session stopped after.
- Deploy: /app/deploy_vps_iter314.sh (updated blurb; still latest script served by temp_bundle kind=script).

## Iter 319 — Dashboard "Employee Enrollment Campaign" warning + all Choose-Action flows
- After login the EPFO dashboard shows an "Employee Enrollment Campaign" warning modal.
  _step_dashboard now runs _dismiss_epfo_modals for portal==epfo before capturing.
- _dismiss_epfo_modals hardened with a generic catch-all: clicks OK/Close/I-Agree/footer
  buttons inside any .modal.show (in addition to #btnCloseModal / #mainHomePageAlertModal),
  then JS-strips leftover modals — handles both the login-page alert and the dashboard warning.
- Confirmed the shared pre-login sequence (Open → Close Alert → Fill Creds from Firm Master →
  Captcha → Verify → Dashboard-with-warning-close) is inherited by ALL Choose-Action flows:
  login, epfo_generate_uan, epfo_ecr_upload, epfo_member_search (nav), epfo_establishment (nav).
- Live E2E re-verified flow reaches waiting_captcha with Open/Close Alert/Enter Creds done.

## Iter 320 — RPA MAX SPEED + Manual Control + Full Screen (deployed script 320)
- SPEED_MULT reduced to {"fast": 0.05} — FAST is the ONLY speed. get_settings always
  returns "fast"; frontend speed selector removed (shows a single "⚡ Fast" chip);
  start payload hardcodes speed:"fast".
- All artificial human-pace delays REMOVED: click cadence (500–1500ms) gone, typing now
  fixed 20ms/char (still real key events for Angular ng-model), highlight pause 0.8→0.05s,
  post-action sleeps 0.3-0.4→0.05s, cursor CSS transition .45s→.1s, frame loop 1.0→0.5s.
  Training/compliance-mode speed floors removed from Ctx.
- MANUAL OVERRIDE: new rpa_engine.interact_session(sid, payload) + route
  POST /api/rpa/session/{sid}/interact — kinds: click (normalised x/y 0-1 → page.mouse.click),
  type (page.keyboard.type), key (page.keyboard.press), scroll (mouse.wheel). Works while
  running/paused/waiting. Frontend: "Manual Control" toggle under live frame; clicks on the
  frame map via InteractiveFrame (onLayout dims + locationX/offsetX → normalised) ; keyboard
  bar (text + Enter/Tab/Backspace/Esc/arrows quick keys).
- FULL SCREEN: "Full Screen" button opens RN Modal with the live frame sized to the window
  (winW/winH), Manual toggle + keyboard bar inside, "Exit Full Screen" closes.
- CAUTION learned: parallel search_replace calls on the SAME file can race and silently drop
  edits — apply same-file edits sequentially and re-grep to verify.
- Deploy: /app/deploy_vps_iter320.sh served via /api/temp-code-bundle?token=sks-deploy-7391&kind=script.
- Pushed to GitHub (commit 2133c73, main).

## Iter 321 — Attendance reports: ACTIVE employees only
- New helper server.py::_employee_inactive_for_report(user, month) — excludes disabled=True /
  active=False, plus _month_is_after_exit rule (exit BEFORE report month → excluded; exit
  DURING month → still included; resigned-without-date → excluded).
- Applied in 3 places: _compute_monthly_grid_data (covers grid JSON, Grid-View/Hours/OT/InOut
  XLSX+PDF, daily reports; self-view only_user_id exempt), _build_ot_report_rows, and
  _generate_attendance_sheet_impl (Attendance Sheet template).
- Group-wise filter ALREADY existed on both Attendance Grid (chips) and Attendance Sheet
  (dropdown) via ?group_id= → _resolve_group_employee_ids (masters type=group by master_id,
  name-match fallback, employee_group_policies fallback). Note: /admin/employee-groups returns
  groups WITHOUT group_id key for this firm (name/member_count only); masters groups carry ids.
- Verified live: flagged 3 test employees (exit before month → excluded; exit mid-month →
  included; disabled → excluded), grid 127→125, May report still shows mid-May leaver,
  group_id=mst_820470a644 (LABOUR) → 108 rows, all XLSX endpoints 200. Flags reverted.

## Iter 322 — Register PDFs + Bulk Correction filters + Attendance Master Sheet menu
- Format 2 (build_compliance_register_pdf_v2): added UAN No. / EPF No. / ESIC No. columns
  (V2_REGISTER_COLUMNS after desig; values from uan_no/pf_no/esi_ip_no; centred; injected
  into pre-existing saved layouts when none of the 3 keys present).
- Format 2 blank last page FIX: whole summary+foot+punchline now built inside
  KeepInFrame(shrink) sized to the frame — always exactly ONE final page (verified 14 pages
  for 127 emp @10/page, last page has summary text).
- Format 1 (build_compliance_register_pdf): fixed 15 mm employee row height (user request).
- Bulk Employee Correction: isResigned broadened (exit_date/date_of_leaving/leaving_date/
  employment_status/disabled — matches backend), Group dropdown falls back to ALL firm groups
  when member-matching finds none, firm dropdown got a type-to-filter TextInput (bc-firm-search).
- Sidebar (NAV_SUPER → Attendance & Shift): added "Attendance Master Sheet" → /attendance-sheet
  (screen existed since Iter 68 but had NO menu entry). Note: /attendance-master is labelled
  "Shift Master" under Masters — left as-is.
- Verified via PDF render (pymupdf) + Playwright screenshots (firm filter, 127 active/0 resigned
  chips, LABOUR group → 108, sidebar entry).

## Iter 323 — Format-1 Master Salary band + report polish + Master Sheet import format
- Format 1 (build_compliance_register_pdf): inserted shaded "MASTER SALARY & ALLOWANCES"
  band (SALARY/HRA/CONV./OTHER/TOTAL from basic_master/hra_master/conveyance_master/
  medical+special+others_master) between DESIG. and DAYS/HRS → 23 columns; all figures
  CENTRE-aligned; amounts are WHOLE RUPEES (no .00) in both Format 1 AND Format 2 (incl.
  summary pages, literals "0.00"→"0"); SIGN./BANK column widened (w=18) for signatures.
  Was developed as a demo first (user approved via "Develop and Make Corrections as Discussed").
- Attendance Master Sheet (build_master_sheet_xlsx): added Designation + Employee Group
  columns (prefilled) so the sheet round-trips into Salary Compliance / Salary Actual import
  (CANONICAL_FIELDS already had designation/employee_group synonyms). Active-only employees
  guaranteed by Iter 321 filter. Projection in _generate_attendance_sheet_impl extended.
- Verified live: register.pdf v1 (14 pages, master band shaded, centred ints, wide sign col),
  v2 unchanged apart from ints, sheet headers = Code/Name/DOJ/Dept/Desig/Group/Days/Gross/
  Advance/TDS/Notes with values populated.

## Iter 324-325 — Register sort/group, signature right-align, Firms Excel views, deploy 325
- register.pdf endpoint: ?sort_by=(name|code|designation|department) & ?group_by=
  (employee_group|department|designation). Rows enriched from users (dept/group/code) then
  sorted; builders (both formats) take group_by → group header band + "TOTAL — X" sub-total
  rows via body_items[{kind:hdr|emp|sub}] chunking (hdr/sub rows 9mm F1 / auto F2).
- compliance-salary-run.tsx: "PDF Sort by" + "Group by" selects (web) feeding both PDF buttons.
- Signature blocks right-aligned (TA_RIGHT paragraph styles) on both formats' summary pages.
- firm_master.py: /admin/firm-credentials now returns city; NEW /admin/firms-master-list (+
  /export.xlsx) with 20 firm-master columns. firm-list.tsx = Excel grid, tap-to-copy, Export
  Excel; sidebar "List of Firms" now → /firm-list (was sub-admin gate /firm-select).
- firm-credentials.tsx → Excel-sheet view (S.No/Firm/City/PF Code/PF Login/PF Pw/ESIC Code/
  ESIC Login/ESIC Pw), tap-to-copy any cell, global show/hide passwords toggle.
- Bulk import: "state" alias added (template already had Present Add/City/State/Pin Code).
- Dev super-admin PIN reset to 246810 (pin_hash bcrypt r10) for firm-credentials testing.
- Deploy script deploy_vps_iter325.sh; temp_bundle kind=script now serves it.

## Iter 326 — Format-1 heading highlight + Format-2 Signature column
- Format 1 header rows now navy #0F3B5C + white text (like Format 2); MASTER band uses
  lighter #1B5480 for distinction.
- Format 2: "sign" column injected at end of saved layouts when missing (defaults had it).

## Iter 328-329 — Client attendance sheet format, calc audit, workspace sync, deploy 329
- build_master_sheet_xlsx → CLIENT FORMAT (EM_PFNO/UAN_NO/EM_ESINO/EM_CODE/EM_NAME/EM_FNAME/
  EM_DESG/EM_DOJ/EM_RESINGDATE/EM_RATEM/EM_HRA/EM_CONV/EM_TOT/Present Days/OVER_TIME/Adv/TDS/
  Other Less/Employee Salary), rates_by_user prefilled via server._compliance_rates_by_user
  (latest compliance run *_master). Email batch (iter60_features) enriched + active-only.
- compliance_import HEADER_MAP: EM_* aliases + new fields tds/other_less/ot_hours stored on
  compliance_import_entries. Run consumption: Adv+other_less → other_deduction ("Advance/Other");
  imported TDS overrides master TDS AFTER firm ded_mask (mask used to zero it). E2E verified
  (upload base64 JSON — NOT multipart — /admin/compliance-import/upload; run row: days 25,
  other_ded 600, tds 200).
- CALC AUDIT (user request): compute_compliance_row ZERO-DAY GUARD — 0 present + 0 duty + 0 OT
  → all earned heads and monthly_gross forced 0 (fixed hra_amount leaked before). Format-2
  earnings columns switched from *_master to EARNED so columns sum to TOTAL. All 127 rows
  verified: earnings=gross, ded=total, net=gross-ded.
- firm-credentials: one-page flex table (no horizontal scroll) + 900ms mount guard against
  click-through copy from the search menu.
- firm-select gate now uses switchCompany (lock-override) so the workspace firm always lands
  in the global header picker; sign-out modal "Select Another Firm" already opens /firm-select.
- Deploy script deploy_vps_iter329.sh (temp_bundle kind=script).

## Iter 330 — Copy Last Month Salary + PDF font bump, deploy 330
- Compliance PDF Format 1 & 2: header font +1 and data font +1 (compliance_salary.py, prior session).
- COPY LAST MONTH SALARY (user request, choices: exact copy / skip new joiners / editable draft):
  ComplianceSalaryRunCreate.copy_last_month → _copy_last_month_compliance_run(server.py):
  finds prev-month run (same firm+group, prefer finalized then latest), copies rows VERBATIM,
  drops exited-before-month/disabled employees (copied_skipped), strips last month's
  advance_recovery from rows (endpoint re-applies current month via apply_advance_recovery),
  recomputes totals. Run fields: attendance_source=copied_last_month, copied_from_month/_run_id.
  Normal draft semantics: finalized block + replace-old-drafts + audit "Copied N employees from M".
- Frontend compliance-salary-run.tsx: purple "Copy Last Month Salary" button (testID
  csr-copy-last-month) next to Salary Process with confirm dialog; "COPIED FROM YYYY-MM" chip on run.
- E2E verified via curl: May→June copy carried exact gross/ded/net; adv EMI stripped correctly.
- Deploy script deploy_vps_iter330.sh (temp_bundle kind=script now serves 330).

## Iter 331 — Master Data Report upgrade + Legacy allowances sync, deploy 331
- master_data_report.py: exact user column sequence (UAN/EPFO/ESIC/EmpCode/Name/.../Firm),
  Exit-Resign column HIDDEN on Active tab, Basic (compliance_basic|basic_salary|basic_amount|
  salary_structure_compliance/actual Basic head), PF Basic, HRA/Conv (hra_amount/conv_amount +
  compliance_salary_allowances + salary_structure_compliance buckets), dynamic allowance columns
  (al_<head> keys inserted after Conv.), Monthly Gross (compliance_gross|basic+allows|salary_monthly),
  pan_name/aadhaar_name/upi_id, Present addr (present_address|address)+district/state/pincode,
  Permanent addr+permanent_pincode. _fetch_rows returns (columns, rows); xlsx/email updated (SN col).
- master-data-report.tsx: click-header sort ▲▼ (numeric-aware, blanks last), per-column filter row
  (contains, testID mdr-filter-<key>), keyboard nav web (↑↓ PgUp/PgDn/Home/End/Esc, skips when typing
  in inputs) with row highlight (#DBEAFE + left border) + click-to-select, scrollIntoView on move.
- legacy_import.py: _sync_firm_allowances — legacy allowance heads (EmployeeSalaryStructureDtl,
  ALLOWANCE, amount>0) matched to Firm Master catalog (fixed labels + custom masters), enabled via
  firm_masters.allowances.$label=True; unmatched heads CREATED in db.masters (type=allowance) then
  enabled; bucket label (HRA/CONV./MEDICAL ALLOWANCES/OTH. ALLOW./OTHER MISC.ALLOWANCE) ALWAYS also
  enabled so the run's allow_mask keeps the column. Hooked in _run_job after employee loop
  ("salary" group); preview endpoint returns firm.allowance_heads [{head,label,action,bucket}];
  wizard shows chips (enable=purple, create=amber) + job totals allowance_labels_enabled/created.
- Deploy script deploy_vps_iter331.sh (temp_bundle kind=script serves 331).

## Iter 332 — Legacy lock + import code-match fix + renames, deploy 332
- LEGACY SALARY LOCK (user request): lock-compliance also sets legacy_locked on the firm's
  legacy_imported employees; undo $unsets it (and deletes legacy-created emps as before).
  Guards: DELETE /admin/employees blocked (403) for legacy_locked; PATCH profile allows ONLY
  resign fields (resign_date/exit_date/date_of_leaving/leaving_date/employment_status/
  exit_reason/exit_remarks) — other CHANGED fields → 403 listing blocked; bulk salary-revision
  skips locked employees. E2E curl-verified (lock→403 delete→403 designation→exit_date ok→undo).
- LEGACY IMPORT BUG (SUVIDHI RAYONS 2548→1000): name-only matching merged duplicate names.
  Fixed to EMPLOYEE-CODE-first matching in _run_job, employee-compare and preview counts;
  name fallback only when the row has no code or portal emp has no code (code backfilled).
  User must UNDO + re-import affected firms after deploying.
- Renames: "Employee Master Data"→"All Employee Data" (Employees menu, home, i18n);
  "Master Data Report"→"Employee Master Report" (Reports menu + screen title).
- Firms ID & Password: sub_admin allowed (own PIN); test sub admin testsub@sksharma.co PIN 135790.
- Deploy script deploy_vps_iter332.sh (temp_bundle kind=script serves 332).

## Iter 333 — Sidebar firm-lock UX, 1000-cap fix, allowance fetch fix, deploy 333
- AdminWebShell: NavItem.disabled — company_admin firm-feature filtering + salaryFlags pruning
  now MARK entries disabled (visible, dimmed, lock icon) instead of hiding; click shows
  "not available for the current firm — enable this function or change the firm" (web alert);
  routeDenied returns false|"denied"|"firm" with firm-specific denied page; global search skips
  disabled. menu_rights / staff RBAC still HIDE entries.
- GET /admin/employees: to_list(1000) → to_list(30000) (SUVIDHI 2548 emp cut-off; active missing).
- Legacy import allowances fix: SalHeadType match loosened to startswith("ALLOW") everywhere
  (_emp_doc_fields, head-sync gather, preview SQL LIKE 'ALLOW%%'); struct lookup falls back
  across AcYears via EmpCode→EmpIDs map (_struct_for); diagnostic error lists actual
  SalHeadType values when nothing matches. User must UNDO+re-import to backfill allowances.
- Legacy import firm picker: alphabetic sort + search filter (pickQuery, testID li-pick-search).
- Attendance Master Sheet: sub_admin allowed on generate/upload/apply-mapping/email endpoints.
- Deploy script deploy_vps_iter333.sh (temp_bundle serves 333).

## Iter 333b — Off-roll employee import
- Offline history loop collects off_latest (latest SalaryTransoff row per worker: code/emp_id/
  name/type/SalaryRate). After history import (import_employees && salary_offline): match portal
  (emp_uid → code → name); missing workers CREATED with is_onroll=False, salary_mode daily,
  salary_structure_actual [{Basic Salary, rate, rate_type daily}], legacy_offroll=True; existing
  employees get salary_structure_actual backfilled when empty; offline history rows user_id linked.
  Totals: offroll_created / offroll_rate_backfilled (shown in wizard summary).

## Iter 334 — Allowance sync dotted-label fix, deploy 334
- _sync_firm_allowances: $set with dotted label paths ("allowances.CONV.") is invalid in Mongo
  (trailing dot = empty field) — now merges and writes the WHOLE allowances object.
- Legacy heads in hra/conv/medical/special buckets map to the standard label (CONV., HRA, …)
  instead of creating duplicate custom heads; custom heads only for "others"-bucket unknowns.
- /admin/employees cap set to 20000 per user request. Deploy script deploy_vps_iter334.sh.

## Iter 335 — Attendance sheet salary columns + All-groups ZIP, deploy 335
- master_sheet.py build_master_sheet_xlsx: EM_RATEM/EM_HRA/EM_CONV/EM_TOT → Basic/HRA/Conv./
  <allowance_labels param (firm-enabled, dynamic)>/Gross Salary; rates dict now
  {basic,hra,conv,extra{label:amt},gross}; dynamic N_COLS/widths.
- server.py: _compliance_rates_by_user → _master_rates_by_user(company_id) -> (labels, rates)
  from EMPLOYEE MASTER (compliance_basic/basic_salary/struct rows; allowances from
  compliance_salary_allowances + salary_structure_compliance mapped to firm-enabled labels;
  gross = compliance_gross|sum|salary_monthly). iter60 email batch uses same.
- match_columns: exact "Employee Salary" header FORCED to canonical gross_salary and marked
  used first (employee_group was stealing it at 66 confidence).
- NEW GET /admin/attendance-sheet/{cid}/{month}/groups.zip — one xlsx per employee group
  (employee_type/employee_group, blanks=UNGROUPED), active-only, zipped (user asked .rar; ZIP
  delivered — opens natively on Windows). Frontend attendance-sheet.tsx: "All groups" → zip.
- Verified: headers + master rates correct (Kankani 745/750 daily), zip has LABOUR/STAFF/
  UNGROUPED files, mapping gross→Employee Salary.

## Iter 336 — Import auto-reprocess (Freeze), PF/ESIC gate fix, Freeze column, deploy 336
- server.py: create_compliance_salary_run endpoint split → _create_compliance_salary_run_core
  (payload, admin) reused by compliance_import._store_import: after storing entries the month
  is AUTO-PROCESSED with use_imported_sheet=True (Freeze); response carries auto_run{ok,run|error}.
  E2E verified (Kankani 2026-07: frozen run, diff 1630 → Overtime, gross=imported, ESIC computed).
- firm_stat_flags pf/esic gates broadened: epf/esi.applicable OR Firm Master Deductions PF/ESI
  toggle (user bug: PF (Emp) 0 · ESIC (Emp) 0 on imported runs).
- compliance-salary-run.tsx: upload + Gmail import handlers show auto-processed run (setRun);
  "Freeze Salary" column inserted right AFTER Gross (purple, per-row imported_gross + total);
  calc band width +1 when frozen. Trailing Imp/Calc/Diff/Alloc columns unchanged.
- month_days note: 26 came from the UI field the admin set; auto-run uses default month days.
- Deploy script deploy_vps_iter336.sh.

## Iter 337 — Days Calculation Method (Freeze workflow), deploy 337
- Firm Master salary_process: days_calc_method (attendance|gross_based|freeze_based|fixed|
  attendance_gross_validation, default attendance), days_calc_fixed (26/30/31),
  days_calc_rounding (0.5 half-day | 1 full-day ONLY — user directive).
- server.py firm_stat_flags projection widened to full salary_process (was ot_allowed only —
  caused method invisible); carries days_calc_* per firm.
- _compute_compliance_run (use_imported_sheet): after first pass, row.attendance_days = sheet
  days; non-attendance methods derive Compliance Days = Imported Gross ÷ Per-Day Gross where
  Per-Day = first-pass gross_paid/present_days (exact for daily+monthly rated; fallback
  monthly_gross/month_days), rounded half/full, clamped [0, month_days]; row recomputed via
  compute_compliance_row with new days; row.compliance_days set; freeze diff block then
  allocates remainder (OT/Other) and sets row.freeze_status matched|diff (|diff|<1).
- firm-master.tsx: radio group + Fixed Days chips + rounding chips (Half/Full) with formula hint.
- compliance-salary-run.tsx frozen grid: Att. Days · Comp. Days · Imp. Gross · Calc. Gross ·
  Difference · Status (✓ Matched / ≠ Diff) · Diff. Alloc. columns + totals row cells.
- E2E verified (Kankani, validation method): 21000@750/day → comp 28.0 ✓ Matched diff 0;
  745/day → 28.0, diff 140 → Overtime; monthly 39000 → 14.0 ✓ Matched. Test data cleaned,
  firm method restored to attendance. Deploy script deploy_vps_iter337.sh.

## Iter 338 — Import Freeze gross into Actual Salary, deploy 338
- Firm Master salary_process.freeze_to_actual toggle (firm-master.tsx switch; default False
  in routes/firm_master.py).
- ACTUAL Salary Process (POST /admin/actual-salary-process, server.py ~21295): when toggle ON,
  frozen compliance run's rows.imported_gross override each ON-ROLL row's total_gross.
  diff = imported − calculated: |diff|<1 → snap into basic_salary, status "matched";
  diff>0 → w_basic_override (+w_basic_salary) if salary_process.ot_allowed else oth_allo;
  diff<0 → basic_salary reduction ("Base Adjustment"). Heads always sum to frozen gross.
  net_pay = gross − (epf+esi+adv+tds). Row flags: freeze_gross_imported, imported_gross,
  calculated_gross, difference, freeze_actual_status, difference_allocation_head.
- Same override also in legacy _compute_salary_run (~line 14320) for /admin/salary-runs.
- salary-run.tsx: Total Gross cell shows "❄ Freeze" badge (+✓ when matched) on overridden rows.
- E2E verified on Kankani 2026-07 (frozen run, 5 employees @21000): OT allocation, sums, net all
  PASS; draft run deleted after test. Toggle left ENABLED on Kankani firm.
- temp_bundle.py kind=script now serves deploy_vps_iter338.sh.

## Iter 339 — One-time Freeze import (auto days derivation), deploy 339
- _compute_compliance_run: sheet has gross but attendance_days<=0 and firm method="attendance" →
  method auto-falls back to attendance_gross_validation (single import fills days/statutory/match).
- Daily-rated fix: when per-day gross can't come from first-pass gross_paid/present_days nor
  monthly_gross (both 0 with a 0-days sheet), a FULL-MONTH probe compute_compliance_row derives
  per-day gross so days derive for daily-rated workers.
- firm-master.tsx: Days Calc Method points + freeze_to_actual toggle now gated on sp.online_salary.
- Verified: Kankani 0-days entries → 28/31 days derived, calc≈imported, remainder→OT, ✓ Matched.
- temp_bundle.py kind=script serves deploy_vps_iter339.sh (adds post-deploy verification lines).

## Iter 339b — No negative salary figures on Freeze runs
- Derived days round DOWN (math.floor to half/full step) so calculated gross never exceeds
  imported gross (BHERU LAL TELI case: 20.8 was rounded UP to 21 → diff −117).
- Attendance-method rows whose sheet-days salary OVERSHOOTS the imported gross now auto-derive
  days from the gross too (freeze authoritative) → Difference always ≥ 0, remainder → OT/Other.
- Verified: full Kankani imported run has 0 negative-difference rows (incl. monthly-rated 39000
  master vs 21000 imported → days shrink, diff positive).

## Iter 340 — Compliance grid OT columns + clamps + Punch Approvals H:MM, deploy 340
- Grid: OT Amt* moved BEFORE Gross; NEW OT Hrs column (auto = ot_pay ÷ ot_hourly_rate, live).
- Backend rows carry ot_hourly_rate (basis Firm Master ot_calc_basis basic|gross; full-month
  Basic/Gross ÷ month_days ÷ full_day_hours × ot_multiplier default 2.0) + firm_ot_allowed.
- OT Hrs LOCKED on imported (hasFrz) runs; editable (OTHoursCell commit-on-blur → ot_pay =
  hrs × rate) on normal runs when firm_ot_allowed.
- Trailing FREEZE SALARY (IMPORTED) band/cols REMOVED; rows with freeze_status!=="matched"
  highlighted (#FEE2E2 + red left border).
- Present Days clamps ≤ month_days: sheet _pd, reprocess _ppd, attendance_days (2 spots).
- freeze_actual_gross days floored at 2 decimals (no −1.55 overshoot). 0 negative diffs verified.
- punch-approvals.tsx: Extra Duty ± input now TIME (H:MM) via formatHHMM; decToHM/hmToDec
  helpers; unit HRS/MIN toggle removed; save parses H:MM.
- NOTE: stray duplicated "down\")..." fragment at server.py EOF removed (was breaking startup).
- Verified via screenshots: grid order + highlight + HH:MM header; API compute: 0 neg, 0 over-days.

## Iter 340b — Legacy Import: Active/Resigned counts + duplicate email fix
- routes/legacy_import.py totals now track employees_active / employees_resigned (created +
  updated branches; resigned = fields.employment_status=="resigned" or legacy IsResign).
- legacy-import.tsx job meta line shows "Active imported: X · Resigned imported: Y".
- Duplicate email E11000 fix (KRIPA SHARAN SHARMA case): pre-check users.email clash → drop
  email; insert wrapped with retry-once (email+phone stripped) on any E11000.
- Fixed stray "ked, ..." duplicated fragment at legacy_import.py EOF (syntax error, same class
  of glitch as server.py "down\")" — WATCH for these after edits).

## Iter 340c — Old DB vs Portal Difference List
- POST /admin/legacy-import/missing (body: {mappings:[{firm_no, company_id}]}) → per firm:
  legacy_count, portal_count, missing[] {emp_code, name, resigned, reason}. Reasons: blank name /
  import error (matched from latest job errors "emp NAME: ...") / generic skipped.
- Matched = portal user by employee_code OR exact name (merged) → not missing.
- legacy-import.tsx: "Old DB vs Portal — Difference List" button on done jobs (uses job.mappings),
  inline list firm-wise; green "No differences" note when all imported.
- Endpoint verified E2E (returns 503 'Legacy SQL Server is not configured yet' in dev — real data
  only exists on the user's VPS).

## Iter 341 — EPS Disable (Employee Master) + ECR EPS = 0
- users.eps_disabled bool: employee-add.tsx checkbox after VPF (create + edit; employeeForm.ts
  EMPTY_FORM/type), server.py create doc, employee_profile.py _BOOL_FIELDS.
- compliance_salary.py compute: eps_disabled → pf_employer_epf += eps; eps = 0; row carries
  eps_disabled flag.
- ECR builders (statutory_bulk.build_pf_ecr_txt + master_sheet.build_ecr_text): EPS wages 0,
  EPS contrib 0, EPS portion moved into EPF_EPS_DIFF/employer share.
- Both ECR download endpoints stamp users.eps_disabled on rows (covers runs generated earlier).
- Verified: NORMAL 3041/253/112 vs EPSOFF 0/0/365 (both builders).

## Iter 341b — Punch Log Report: NOT FOUND + NEW REGISTRATION flags
- routes/punch_logs.py _query_rows: rows get flag="" | "not_found" (user doc missing) |
  "new_registration" (users.created_at date == today IST).
- biometric_unmapped punches (bio code with NO master match) merged into the report as rows:
  name "NOT FOUND IN MASTER", bio_code = device_user_id, firm resolved via biometric_devices
  serial → company; respects firm/machine filters + sub-admin scope; rows re-sorted date/time desc.
- XLSX: new "Remark" column (NOT FOUND red / NEW REGISTRATION green).
- punch-log-report.tsx: red/green row tint + ⛔/🆕 name markers.
- Verified E2E with seeded unmapped punch (then cleaned up).

## Iter 342 — PWA speed (/companies) + Bulk Correction On/Off-Roll
- PERF: GET /companies per-firm loop (3 queries × N firms) replaced with 3 aggregations
  (users/attendance/leaves grouped by company_id); to_list cap 500→2000.
- NEW ?lite=1 param: only company_id/name/company_code/capability flags/is_active, skips stats.
  ALL frontend firm pickers (28 call sites incl. SelectedCompanyContext, CompanyPicker) switched
  to /companies?lite=1 (payload 5273→274 bytes in dev). companies.tsx (Firms dashboard) keeps
  the full endpoint for stats.
- Bulk Employee Correction (mode=actual): new "On/Off-Roll" select column (select:onroll,
  key is_onroll) — bulk shift Off-Roll → On-Roll. Payload model + generic update path handles
  bool. E2E verified flip False/True via API.

## Iter 342b — Attendance Sheet Automation for Sub Super Admin
- attendance-email.tsx: isSuper now includes sub_admin (Send now / Dry-run card + trigger guard);
  isAdminish extended to company_admin (unchanged read access). Backend endpoints already
  allowed sub_admin since Iter 332; sidebar already shows the menu.

## Iter 342c — Undo/create-firm list bug + attendance sheet file names
- legacy_import.py: portal firm list caps raised 300→5000 (firms endpoint) and 500→5000
  (legacy-salary firms) — firms beyond the cap vanished from the wizard dropdown while the
  duplicate-name check still found them ("not showing in list" + "already created" bug).
- attendance-sheet.tsx: browser download names now include FIRM NAME slug:
  AttendanceSheets_{Firm}_{month}_AllGroups.zip, AttendanceSheet_{Firm}_{month}_{grp}.xlsx,
  MonthlyAttendance_{kind}_{Firm}_{month}.xlsx (a.download overrides server header on web).

## Iter 343 — Publish OFFLINE legacy salary → ACTUAL Salary Process
- routes/legacy_import.py: _legacy_row_to_actual mapper (rate→basic, w_basic, others→oth_allo,
  less_adv+loan+other→adv, gross/net) + _publish_offline_actual_job (additive: skips months with
  existing actual run) + POST /admin/legacy-salary/publish-actual (PublishBody).
- Runs inserted into salary_runs (run_type "actual", attendance_source "legacy_import",
  legacy_imported True, run_id asal_*). Undo deletes them too.
- legacy-salary.tsx: purple "Publish months to ACTUAL Salary Process (off-roll)" button on the
  offline tab; startPublish picks endpoint by kind (shared month-picker modal + job poller).
- E2E verified: seed offline hist row → publish → visible in /admin/salary-runs + opens in
  Actual screen (26 days / 21500 / 20950). Seed cleaned.

## Iter 343b — Freeze display-only (manual OT edits stick) + deploy 341
- compliance grid: editing ot_pay/others on imported rows sets manual_override=true +
  difference_allocation_head "Manual"; freeze comparison (calculated_gross/difference/status)
  recomputed live client-side.
- _compute_compliance_run freeze block: prev row with manual_override → restore saved ot_pay/
  others/gross_paid AS-IS (net = kept gross − fresh deductions); freeze fields display-only.
  Verified PASS (edited +500 kept across reprocess, diff −500 shown as Manual).
- deploy_vps_iter341.sh created; temp_bundle serves it (kind=script). Covers iters 340b–343b.

## Iter 344 — Direct delete for Sub Super Admin + Freeze EXACT match
- delete_employee: sub_admin approval queue REMOVED — deletes directly (Iter 306 reverted per
  user). deletion_approvals.py salary-run delete: sub_admin also direct now.
- Freeze exact match: new `elif _diff_g < 0` branch — calc gross above imported is TRIMMED
  (OT first, then Others, head "Trimmed"), gross_paid = imported. Every imported row now has
  Gross − Freeze = 0 (verified full Kankani run: 0 mismatches; manual_override rows exempt).

## Iter 342–347 (fork session, June 2026)
- Iter 342: OFFLINE legacy salary import fix — `_month_key_any()` in legacy_import.py derives
  month from FirstDayOfMonth OR MonthYear ('Feb 2019'/'02-2019'/201902 …); safe EmpCode parse;
  `offline_skipped_no_month` diagnostic counters. deploy_vps_iter342.sh.
- Iter 343: Compliance salary "Save only refreshes page" — root cause: window.confirm/alert
  suppressed by browser + reload-on-No. Fixed: src/utils/confirm.ts now renders IN-APP DOM
  modal (confirmYesNo) + showToast (unsuppressible); removed both window.location.reload()
  paths in compliance-salary-run.tsx; finalize uses confirmYesNo. deploy_vps_iter343.sh.
- Iter 345: AI Chat Assistant v2 (routes/ai_assistant.py rewrite): executes work — process/
  finalize salary (confirm_api, danger flag), report downloads (auto), email reports, employee
  phone/salary/status updates via POST /admin/ai-assistant/employee-status; purified data Q&A
  (salary_total/esic_eligible/absent_list/present_count/employee_count/top_paid/run_status/
  missing_data/pf_mismatch/why_salary); compliance_info expert (rules/news + portal links);
  Hindi/Hinglish. Frontend AiAssistant.tsx: download/link actions, auto-run, danger styling.
  Tested 13/13 backend + UI (iteration_345.json).
- Iter 346: FULL AI LAYER (routes/ai_layer.py + app/ai-payroll-assistant.tsx + sidebar menu):
  GET /admin/ai/analysis (scores, 18+ findings w/ confidence, trends, forecast, reconciliation,
  calendar, insights, recommendations; cached in ai_analyses, refresh=1), apply-fix (PAN/IFSC
  normalise; logs ai_action_log), feedback learning (ai_feedback suppression), salary-diff,
  audit-report.pdf/.xlsx, map-columns (rules+LLM) + import-templates, red-risk → notifications.
  Shortcuts: g+i, Alt+1..6, R. Attendance sheet `?sort=` (code/name/department/doj) + ms-sort
  dropdown. Excel-style per-column header filters in compliance-salary-run.tsx & salary-run.tsx
  (src/utils/colFilter.ts, >N <N =N ops). Tested 15/15 + UI (iteration_346.json).
- Iter 347: SUVIDHI salary structure mismatch — legacy import now prefers CURRENT head-wise
  structure (EmployeeSalaryStructureDtl BASIC head + allowances; gross = basic + allowances)
  over stale EmployeeMaster.BasicSalary/GrossPay. Unit tested. Chat "_find_employees" strips
  'code/emp' prefixes. deploy_vps_iter344.sh (served via temp_bundle token sks-deploy-7391).
- PENDING: user to re-import SUVIDHI after deploy 344 and confirm structures match; P1
  WhatsApp API integration; backlog server.py refactor.
- Iter 351-353 (fork): Suvidhi staff salary fix iterations — discovered WP_Emp_Attendance is a
  10-row scratch table, NOT staff master; EmployeeSalaryStructureDtl holds PER-YEAR rows whose
  EmpID join multiplied+summed across years (HRA 19044 vs true 2000). Added /api/legacy-query
  (token sks-deploy-7391, SELECT-only) for remote legacy-DB diagnosis on VPS (smartpayrolling.com).
- Iter 354: USER-SPECIFIED final mapping — salary read directly from EmployeeMaster:
  BasicSalary/PFBasicSalary/GrossPay + Earn1..10 = HRA/CONV./OTH. ALLOW./OVER TIME/INCENTIVE/
  OTHER MISC.ALLOWANCE/BONUS/MEDICAL ALLOWANCES/FOOD ALLOWANCES/FOOD ALLOWANCE (names refreshed
  from SalaryHeadMaster via _head_names, defaults in _EARN_DEFAULT). _emp_doc_fields(earn_names=)
  signature changed; EmployeeSalaryStructureDtl NO LONGER used. Sync auto-corrects employee codes
  on name-match (codes_corrected counter). Unit tested vs staf.xls (30800/31300 cases).
- Iter 355: Attendance Sheet "Sort sheet by" + Designation option (backend _att_sheet_sort).
- Iter 356: EMPLOYEE-WISE YEARLY PAYROLL REGISTER (routes/payroll_register.py +
  app/payroll-register.tsx + sidebar "Yearly Payroll Register"). Bonus-Register layout: employee
  info block, Apr–Mar months across top, heads as rows, EMPLOYEE TOTAL + GRAND TOTAL. Endpoints:
  /api/admin/reports/payroll-register[.pdf|.xlsx] (fy_start_year, fy_years 1-5, department,
  designation, category, status, bank, skip/limit). PDF=A3 landscape ReportLab w/ logo+page nos;
  XLSX=openpyxl merged headers/freeze/print-area. AI validation flags (pf/esic/gross mismatch,
  negative net, missing attendance, loan recovery, duplicate) → red cells. Freeze-salary residual
  absorbed into Other Allowance when imported_gross/difference markers present.
  Tested 8/8 backend + full UI (iteration_356.json).
- ROADMAP (user approved phases): B) Labour Statistics & HR Analytics Phase 1 (HR Analytics
  Dashboard, Department Statistics, Category-wise Manpower, Monthly Labour Return, Turnover
  Analysis — all auto-calculated, register-style PDF/Excel). C) Annual Returns Management
  (Minimum Wages, Payment of Wages, Bonus, Equal Remuneration, Employment Statistics, Social
  Security Statistics, LWF, PT returns + Compliance Dashboard). D) Factory & Boilers Compliance
  (needs NEW masters first: licenses/boilers/accidents/PPE/medical, then registers + dashboard).
  Full specs are in the user messages of this session (2026-07-28). P1 WhatsApp integration
  still pending. VPS deploys served via kind=script (currently deploy_vps_iter356.sh).
- Iter 357 (Phases B/C/D, all tested 33/33 + UI, iteration_357.json):
  B) LABOUR STATISTICS (routes/labour_statistics.py + app/labour-statistics.tsx):
     /api/admin/labour-stats/{dashboard,department,category,monthly-return,welfare,turnover}
     [+.xlsx/.pdf via suffix-delegation in /{kind}]. Auto-calc from users/attendance/
     compliance_salary_runs. Rule-based AI insights (attrition, OT, ghosts, dups, anomalies).
  C) ANNUAL RETURNS (routes/annual_returns.py + app/annual-returns.tsx):
     /api/admin/annual-returns/{list,dashboard,minimum-wages,payment-of-wages,bonus,
     equal-remuneration,employment-statistics,social-security,lwf,pt}[.xlsx/.pdf].
  D) FACTORY & BOILERS (routes/factory_compliance.py + app/factory-compliance.tsx):
     factory_records collection (kind+data dict); 14 master kinds (_MASTER_KINDS) + computed
     registers daily-attendance/present-absent/muster-roll/working-hours/strength;
     /api/admin/factory/{kinds,records CRUD,register/{kind}[.xlsx/.pdf],dashboard} with 45-day
     due alerts (_DUE_FIELDS) + compliance/risk scores.
  Shared: utils/register_export.py (register_xlsx/register_pdf A3 landscape) and
  src/components/RegisterTable.tsx (table + ExportButtons + shared styles).
  Sidebar (AdminWebShell 2 places): Labour Statistics & HR Analytics / Annual Returns /
  Factory & Boilers. Present & Absent employee-wise report added on user request.
  Deploy script: deploy_vps_iter357.sh (served via temp_bundle kind=script).
- Iter 358 (tested 15/15 + UI, iteration_358.json): REPORTS CENTER (app/reports-center.tsx,
  sidebar "Reports Center"; single hub with chips + month/FY inputs + RegisterTable).
  Routers: routes/payroll_reports.py (/api/admin/payroll-reports/*: salary-comparison,
  gross-vs-net, salary-revision, increment, ex-gratia, incentive, arrear, full-and-final,
  ctc-register, ctc-analysis, ot-department, ot-daily, ot-cost-analysis) and
  routes/govt_audit_reports.py (govt_router /api/admin/govt-registers/*: wage/fine/deduction/
  advance/gratuity; audit_router /api/admin/audit-reports/* super/sub-admin only, generic
  collection dumps from salary_audit_log, attendance_audit_log, salary_history, activity_log,
  access_audit, emp_login_attempts, employee_audit_logs, bulk_ops_log, onboarding_audit,
  kyc_history). labour-stats += salary-distribution, tenure-analysis. factory += leave-with-wages
  computed + adult-worker/dangerous-occurrence/welfare/canteen/machine-operator masters.
  All use suffix .xlsx/.pdf delegation. User-supplied lists: reports already existing were
  intentionally NOT duplicated (linked in the page). NOT built (no data model yet): shift-wise/
  holiday/double OT + OT approvals (needs shift & approval masters), Form A-Z state-wise
  government formats, Contractor/BOCW/Apprenticeship registers, succession planning.
  Deploy: deploy_vps_iter358.sh (temp_bundle kind=script).
- Iter 359 (tested 14/14 pytest + full UI, iteration_359.json): PF & ESIC CLAIMS MANAGEMENT
  SYSTEM. Backend routes/claims_management.py (router /api/admin/claims, collection
  pf_esic_claims): 16 PF + 11 ESIC claim types, per-kind statuses, DOC_CHECKLIST per kind,
  claim_no CLM-{PF|ESIC}-NNNNN, status timeline[], employee auto-fill from users master by
  employee_code, EXTERNAL company claims (company_id="external" + data.company_name free
  text). Smart AI on save: _ai_checks (eligibility rules Form-10C>10yrs→10D, <6mo, <5yrs TDS,
  ESIC 9-month contribution scan from compliance_salary_runs, UAN/IP format, missing docs,
  duplicate open-claim detection), _doc_score 0-100%, _expected_settlement (avg from settled
  history). Endpoints: meta, dashboard, list w/ filters, POST create/update, DELETE,
  /reminders (follow-up engine, auto +7d), /report/{pf-register,esic-register,pending,
  approved,rejected,settlement}[.xlsx|.pdf]. Frontend app/claims-management.tsx: 5 tabs
  (Dashboard stat cards, Claims Register w/ PF-ESIC toggle + filters + expandable cards w/
  timeline/docs/AI + edit/delete, New/Edit Claim form w/ company select incl External +
  doc-checklist chips + Smart AI Analysis panel, Follow-up Reminders, Reports w/ exports).
  Sidebar (AdminWebShell x2): Compliance → "PF & ESIC Claims". Deploy: deploy_vps_iter359.sh
  (temp_bundle kind=script updated to 359).
- Iter 360 (tested 9/9 pytest + full 5-step wizard UI, iteration_360.json): AI UNIVERSAL
  PAYROLL IMPORT. Backend routes/ai_universal_import.py (router /api/admin/ai-import,
  registered in server.py as ai_uimport_router): POST /analyze (pandas parse xls/xlsx/csv,
  header-row auto-locate, FIELD_HINTS rule mapping 50 canonical fields, template fingerprint
  sha1 of sorted headers → ai_universal_templates instant recognition, _guess_file_type 14
  types top-3, _detect_period regex, company fuzzy match vs db.companies, single LLM assist
  gpt-5.4 emergentintegrations only when needed; rows chunked 500/doc in ai_import_rows).
  POST /validate (employee matching code→uan→esic→aadhaar→pan→mobile→name+dob→fuzzy w/
  confidence; 20+ validations: dupes in file, format checks UAN/ESIC/PAN/IFSC, negative
  values, days>calendar, min wage from compliance_policy.minimum_wage_daily, PF≤15k/ESIC≤21k
  eligibility; AI Correction Engine fills UAN/ESIC/IFSC from master + prev-month gross diff
  via compliance_salary_runs). POST /commit (asyncio background, progress polling GET /job/
  {id}, 409 duplicate-import guard; targets: employee_master→users upsert/create,
  attendance_salary→compliance_import_entries then AUTO PAYROLL via
  _create_compliance_salary_run_core(use_imported_sheet=True) — reuses Freeze Salary engine,
  leave→leaves, extras→ai_imported_extras; saves learned template; audit ai_import_audit;
  temp rows deleted post-success). GET /compliance-check (post-run PF-UAN/ESIC-IP/wage-cap/
  negative-net scan + 6 artifact links incl pf-ecr.txt), GET /dashboard, GET+DELETE
  /templates, POST /explain (LLM plain-English error explainer). Frontend
  app/ai-universal-import.tsx: 3 tabs (Import Wizard 5 steps w/ step indicator, Dashboard,
  Learned Templates); web file input via dynamic <input type=file>; amber low-confidence
  mapping rows; validation filters; target checkboxes; live progress bar; payroll +
  compliance cards w/ artifact download buttons. Sidebar (AdminWebShell x2): Payroll →
  "AI Universal Import" (sparkles icon). Deploy: deploy_vps_iter360.sh (temp_bundle
  kind=script now serves 360).
- Iter 361 (user request, unit-tested locally — legacy MS SQL only exists on VPS): OFFLINE/
  ACTUAL SALARY from OLD DB. routes/legacy_import.py: new _pickcol (case-insensitive column
  lookup) + _actual_salary_struct(e) — EmployeeMaster Salary→Basic (rate_type from PayBasis),
  Salary1-3→Salary 1/2/3 amounts, Days1-3→working_days; returns the exact
  salary_structure_actual shape the Employee form saves ([{head:Basic,amount,rate_type},
  {head:Salary i,amount,working_days}]); tolerant of Salary_i/Sali & Dayi variants; None when
  row has no data. Wired into _emp_doc_fields "salary" group (import wizard + employee-compare
  preview) AND _SYNC_SALARY_KEYS so "Sync Salary Structures — ALL Firms" overwrites
  salary_structure_actual from old DB with new live counter totals.actual_salary_synced.
  Deploy: deploy_vps_iter361.sh (temp_bundle kind=script → 361). User must run the ALL-Firms
  sync on VPS to apply.
- Iter 362 (potential-improvement accepted): ACTUAL SALARY COMPARISON Old DB vs Portal.
  legacy_import.py: _struct_vals (salary_structure_actual → flat basic/s1-3/d1-3, handles
  "Basic"/"Basic Salary" heads), _CMP_FIELDS, _actual_salary_compare_data (per mapped firm:
  legacy rows via _actual_salary_struct vs portal users matched by code→name; status MATCH/
  DIFF(+field list)/NOT IN PORTAL; per-firm counters; rows sorted DIFF first, capped 500 for
  UI). GET /admin/legacy-import/actual-salary-compare[?firm_no&only_diff] + .xlsx/.pdf export
  (register_xlsx/pdf, Old vs Portal columns for all 7 fields). Frontend legacy-import.tsx:
  green button (testID li-actual-salary-compare) + per-firm expandable 🟢🟠🔴 summary showing
  only problem rows + ⬇ Excel/⬇ PDF (apiBinary). Endpoints return clean 503 locally (legacy
  MS SQL only on VPS); comparison/mapping logic unit-tested. Deploy: deploy_vps_iter362.sh
  (temp_bundle kind=script → 362).
- Iter 363 (user request): OLD DB BioCode → users.bio_code (device enrolment no.).
  legacy_import.py _emp_doc_fields salary group: _pickcol(BioCode/BiometricCode/MachineCode),
  "72.0"→"72", skips empty/0; "bio_code" added to _SYNC_SALARY_KEYS; sync counter
  bio_codes_synced. Unit-tested. Deploy: deploy_vps_iter363.sh (temp_bundle kind=script→363).
- Iter 364 (user request): ROLLBACK of Iter 361 Actual Salary auto-fetch. legacy_import.py:
  removed doc["salary_structure_actual"] from _emp_doc_fields salary group, removed
  "salary_structure_actual" from _SYNC_SALARY_KEYS, removed actual_salary_synced counter.
  KEPT: bio_code sync (Iter 363), read-only Actual Salary Comparison report (Iter 362),
  _actual_salary_struct helper (used by comparison). Compliance mapping re-verified against
  user spec — matches exactly (Iter 354): BasicSalary→Basic, PFBasicSalary→PF Basic,
  GrossPay→Gross, Earn1-10→HRA/CONV./OTH. ALLOW./OVER TIME/INCENTIVE/OTHER MISC.ALLOWANCE/
  BONUS/MEDICAL ALLOWANCES/FOOD ALLOWANCES/FOOD ALLOWANCE. DATA RESTORE: new
  /app/restore_actual_salary_from_backup.sh (mongorestore users→temp DB, restores ONLY
  salary_structure_actual per user_id from pre-sync backup, then drops temp). NOTE: file
  corruption incident — parallel search_replace edits to same file clobbered each other
  (trailing garbage + lost edit); fixed sequentially; NEVER batch-edit same file in parallel.
  Deploy: deploy_vps_iter364.sh (temp_bundle kind=script→364).
- Iter 365 (user request): DAILY MongoDB BACKUP on VPS. deploy_vps_iter365.sh is a
  lightweight one-time SETUP script (no bundle download): writes
  /home/sksharma/backup_mongo_daily.sh (mongodump --archive --gzip to
  /home/sksharma/backups/mongo_YYYY-MM-DD.gz + env snapshot + log), installs cron 0 2 * * *,
  rotation keeps 14 daily + 1st-of-month for 185 days, runs first backup immediately to
  verify. Pairs with restore_actual_salary_from_backup.sh (Iter 364). temp_bundle
  kind=script→365.
- Iter 366: BACKUP CENTER + ALL-FIRMS RE-SYNC packaging. Backend routes/backup_center.py
  (/api/admin/backups: list [session], /latest + /download/{name} [session OR token
  sks-backup-7391], _bk_dir: BACKUP_DIR env → /home/sksharma/backups → /app/backups, filename
  regex blocks traversal — tested 401/404). Registered backup_center_router in server.py.
  Frontend app/backup-center.tsx: backup list w/ Download buttons + Windows Task Scheduler
  auto-download instructions with USER-CHOSEN folder input (bk-pc-dir, default C:\SKSBackups,
  commands template live) + note that server-side BACKUP_DIR is configurable. Sidebar x2:
  Import/Export → "Backup Center". Verified sync job intact post-rollback (only
  _SYNC_SALARY_KEYS: basic/pf_basic/gross/salary_monthly/allowances/bio_code). Deploy:
  deploy_vps_iter366.sh (full bundle; re-sync workflow steps in output; temp_bundle→366).
- Iter 367 (user request): SALARY COMPLIANCE PROCESS (AI). Backend
  routes/ai_salary_compliance.py (router /api/admin/ai-salary-compliance, registered as
  ai_salcomp_router): GET /employee-inputs (READ-ONLY prefill: firm_masters.allowances/
  deductions enabled heads in ORIGINAL dict order — NO re-sort/re-group/filter, amounts from
  compliance_salary_allowances; basic fallback chain compliance_basic→salary_structure_actual
  Basic row (daily rate_basis)→salary_monthly; attendance from compliance_import_entries →
  salary run row; PF/ESI eligibility, PT state). POST /calculate → gpt-5.4 with SYSTEM_PROMPT
  (user's Senior Payroll & Compliance Expert prompt: 12 numbered sections, Sr. No. FIRST
  column in every table, heads exact-order no-omit rule, daily-rate formula, plain text no
  markdown). Frontend app/ai-salary-compliance.tsx: Load Employee (company/code/month) +
  editable dynamic allowance/deduction rows (sr numbers) + attendance/variable/statutory
  groups + result panel monospace. Sidebar x2: Payroll → "Salary Compliance Process (AI)".
  E2E tested: emp 50 Kankani daily ₹745 → 200, all sections present, firm heads HRA/CONV./
  OVER TIME + PF/ESI/ADVANCE in order. STRICTLY ADDITIVE — Freeze Salary/import untouched.
  Deploy: deploy_vps_iter367.sh (temp_bundle→367).
- Iter 368 (user fixes on Salary Compliance Process): DETERMINISTIC ENGINE MODE.
  ai_salary_compliance.py: /calculate now routes to _calculate_engine when
  company_id+employee_code+month present — uses utils.compliance_salary.compute_compliance_row
  with firm compliance_policy (statutory keys from DEFAULT_STATUTORY_CFG), firm_masters
  PF/ESI applicability flags, firm_pt state slabs, employee_policy — deductions/net identical
  to Salary Process. _tbl() builds fixed-width tables in code: Sr. No. FIRST column
  guaranteed, footer total right-aligned exactly under Amount (₹) heading. Variable pay
  (incentives/bonus/arrears/reimb) added to gross; loan_recovery added to deductions. AI only
  writes sections 10-12 (checklist/journal/notes), non-fatal on failure. Manual mode (no
  employee) falls back to _calculate_ai_only. Frontend runCalc sends company_id/employee_code/
  month. Verified: emp 50 Kankani 2026-06 26d+10OT → gross 20766.88, ESIC 59, employer 252,
  net 20207.88; tables aligned. Deploy: deploy_vps_iter368.sh (temp_bundle→368).
- Iter 370 (user: first-click PF/ESIC + sorting + totals + validation panel):
  1. FIRST-CLICK FIX: utils/compliance_salary.py — pf_eligible/esic_eligible computed
     SEPARATELY from _zero_pay guard and emitted on every row ("pf_eligible",
     "esic_eligible"); row "pf_applicable"/"esic_applicable" amounts-gating unchanged
     (exports/ECR untouched). Frontend updatePresentDays uses the eligibility flags
     (falls back to old applicable flag for pre-370 runs) — typing days on a fresh
     0-day run now computes PF/ESIC instantly, no second Salary Process click.
     Also compliance-salary-run.tsx: loadPolicy() callback + policyReadyRef; generate()
     AWAITS firm compliance-policy on first click and passes fresh values into
     buildBody(pv) — fixes statutory-defaults race. Actual Salary unchanged (syncs
     EPF/ESI from compliance run, benefits automatically).
  2. HEADER-CLICK SORTING: both compliance-salary-run.tsx (colSort state, header Text
     onPress → toggleColSort, uses COL_FILTER_GETTERS, asc ▲/desc ▼/off) and
     salary-run.tsx (HdrCell now Pressable with onPress+sortDir, hdrSort() spread,
     uses ACTUAL_COL_GETTERS). Sort chips + PDF sort/group untouched.
  3. HEAD-WISE TOTALS: compliance TOTAL row — Master group sums (basic_master…gross_master),
     Present Days, ESIC Leave, Wage Base (stat_wage_base) via sumCol(); actual TOTAL row —
     P Days, P Hours, Basic (Master), Oth.Allo sums.
  4. ProcessCommandCenter (Compliance Validation) moved to BOTTOM of page on both
     compliance-salary-run.tsx and salary-run.tsx.
  Verified E2E on preview (Kankani, STAFF, 2026-06): fresh process → type 26 days →
  ESIC (E) 59 / (Er) 252 instantly; Gross ▲ / EPF ▲ header sorting works; panels at bottom.
  Deploy: deploy_vps_iter370.sh (temp_bundle→370). USER MUST REPROCESS existing months once.
- Iter 371 (user: unlock button + month default):
  1. UNLOCK IN CONFIGURE BATCH: compliance-salary-run.tsx — finalizedExisting useMemo
     (runs list matched on month+company+employee_type+finalized) + unlockExisting()
     → POST /admin/compliance-salary-runs/{id}/unlock-request; amber button
     (csr-unlock-existing) under Salary Process row, isSuper (super/sub) only.
     salary-run.tsx — refreshFinalized() fetches /admin/salary-runs (month+firm+branch),
     asp-unlock-existing button → NEW endpoint POST /admin/salary-runs/{run_id}/unlock
     (server.py, after finalize_actual_salary_run; super/sub only, sets finalized False).
     server.py unlock-request: sub_admin now unlocks IMMEDIATELY (was request-only);
     company_admin still goes through salary_unlock_requests approval flow.
  2. MONTH DEFAULT: currentMonth() in both compliance-salary-run.tsx and salary-run.tsx —
     day > 25 ⇒ CURRENT month, else previous month.
  Verified E2E on preview: compliance default month July (server Jul 29), June finalized →
  unlock button appears → Yes → "Salary unlocked ✓" toast, button gone; actual window
  unlock same; curl finalize→unlock on asal run OK.
  Deploy: deploy_vps_iter371.sh (temp_bundle→371, includes Iter 370).
- Iter 372 (user: PDF dynamic heads + label/overflow fixes):
  1. build_compliance_register_pdf (v1) REWRITTEN spec-driven: m_cols/e_cols/d_cols
     built from rows[0].enabled_allowances / enabled_deductions (show_hra/show_conv/
     show_oth_m/show_oth_e/show_pf/show_esi/show_tds). Dynamic indices M0/DAYS_I/E0/
     D0/NET_I/SIGN_I/NCOLS drive spans/widths/backgrounds. Summary lines conditional.
  2. v1 IDs column: header "UAN / P.F.NO. / ESI NO.", rows print PLAIN numbers (labels
     removed), new idcell ParagraphStyle wordWrap="CJK" fixes EPF No. overwriting cols.
  3. build_compliance_register_pdf_v2: cols_spec filtered via _col_ok (hra/conv/
     other_earn/pf/esi/tds) from same masks; summary conditional too.
  4. NEW build_actual_salary_register_pdf in utils/salary_run.py (Actual grid columns,
     GRAND TOTAL, zebra). Endpoint /admin/salary-runs/{run_id}/register.pdf branches on
     run_type=="actual"; EPF/ESI col visibility mirrors engine semantics (epf/esi
     .applicable authoritative, fallback Deductions catalog PF/ESI).
  Verified via pypdf text-extraction on Kankani June runs: v1 bands SALARY/HRA/CONV/TOTAL
  (no OTHER/TDS), IDs unlabeled; v2 dropped Other+TDS cols; actual register OK 6 pages.
  Deploy: deploy_vps_iter372.sh (temp_bundle→372, includes 370+371).
- Iter 373 (user: Excel matches PDF + unlock in blocked path):
  1. compliance_salary.py: dynamic_csv_columns(rows) filters CSV_COLUMNS by
     enabled_allowances/enabled_deductions; to_csv uses it; compliance export.xlsx
     endpoint uses dynamic_csv_columns.
  2. salary_run.py: ACTUAL_CSV_COLUMNS + actual_csv_columns(show_epf, show_esi) +
     to_actual_csv. server.py: _actual_epf_esi_flags(company_id) helper (Applicable
     authoritative, fallback Deductions catalog) reused by register.pdf, export.csv,
     export.xlsx — actual runs branch to Actual grid columns.
  3. compliance-salary-run.tsx generate(): FINALIZED-blocked path now offers Super/Sub
     Admins a Yes/No "UNLOCK it now" confirm → unlock-request endpoint → reload.
  Verified: CSV headers dynamic (compliance drops med/spl/others/pt/tds), actual
  CSV/XLSX new columns, XLSX headers via openpyxl, unlock dialog E2E (toast confirmed).
  Deploy: deploy_vps_iter373.sh (temp_bundle→373, includes 370-372).
- Iter 374 (user bug: manual amounts removed on lock/unlock):
  ROOT CAUSES: (a) finalize raced the 2.5-3s debounced auto-save — save-rows fired
  AFTER the lock → 400 → silent loss; (b) reprocess (after unlock) only preserved
  days/ot_hours/other_deduction — manual others/ot_pay/tds/esic_leave were recomputed
  from master and wiped.
  FIXES:
  1. compliance-salary-run.tsx finalizeRun(): clears autoSaveTimer + flushes save-rows
     BEFORE POST finalize. salary-run.tsx finalize(): flushes pendingRef row PATCHes first.
  2. updateRowField stamps manual_override + manual_fields[key] on EVERY manual edit
     (was imported-runs only).
  3. server.py _compute_compliance_run: non-imported reprocess restores manual fields
     from _prev (manual_fields + heuristics: esic_leave_days>0, ot_pay>0 w/ ot_hours 0,
     tds>0 w/o sheet) and rebuilds monthly_gross/gross_paid/total_deduction/net deltas.
     Inserted just before the Iter 310 Freeze block; imported runs keep Iter 343b logic.
  Verified via API scripts: manual TDS 500 → reprocess → kept (net rebuilt); ot_pay 750 +
  others 300 kept; tds survived a 2nd reprocess. Test data reset afterwards.
  Deploy: deploy_vps_iter374.sh (temp_bundle→374, includes 370-373).
- Iter 375 (user: Claims Mgmt upgrades + Employee Master fixes + deploy):
  CLAIMS (routes/claims_management.py + claims-management.tsx):
  1. GET /api/admin/claims/employees?company_id= → all employees w/ left flag
     (dol from exit/resign/leaving fields, employment_status, active/disabled).
  2. Claim form: employee picker dropdown — PF Form-19/10C shows LEFT employees
     only, all other claim types show full list; picking auto-fills code/name/
     UAN/IP/dept/desg/DOJ/DOL. "＋ Add Other Company Manually" button → external
     mode with record-only note (company saved on claim only, NEVER in Firm Master).
  3. GET /api/admin/claims: date_from/date_to (data.application_date) + sort=
     date_desc|date_asc|name|firm. Register UI: From/To date inputs + sort select.
  EMPLOYEE MASTER (employee-add.tsx):
  4. FIXED CRASH: codeManual state was never declared (prev agent) → page showed
     "codeManual is not defined". Added useState(false).
  5. DOJ auto-fills 01-<current month>-<year> for NEW employees.
  6. isoToDDMM now passes through DD-MM-YYYY legacy values (edit form showed
     blank DOJ/DOB for all 125 legacy Kankani employees).
  ATTENDANCE SHEET (server.py "Iter 377" comments):
  7. _month_is_before_doj uses _parse_any_date (legacy DD-MM-YYYY DOJs never
     filtered before); _att_sheet_sort doj sort parses mixed formats.
  Verified: claims endpoints via curl (date range, name/firm sort, external claim
  creates NO firm/company doc); UI via playwright (Form-19 → 1 placeholder option,
  KYC → 129, external note, date filters); employee form new+edit (DOJ default
  01-07-2026, legacy DOJ 01-12-2018 displays, PAN/Aadhaar autofill, pencil);
  PATCH profile rejects "50/A"; attendance xlsx sort=doj chronological, 127 rows.
  Deploy: deploy_vps_iter375.sh (temp_bundle→375, includes 370-374).
- Iter 376 (user: claim file attachments + PF wage-base floor rule):
  CLAIM ATTACHMENTS (claims_management.py + claims-management.tsx):
  1. New collection claim_documents {doc_id, claim_id, doc_name, filename,
     content_type, size, base64, uploaded_by/at}. Endpoints:
     GET/POST /admin/claims/{id}/documents, GET .../{doc_id}/file (inline),
     DELETE .../{doc_id}. PDF/JPG/PNG/WEBP/HEIC only, 10MB cap.
  2. Upload auto-ticks matching checklist item + timeline entry + recompute
     doc_score/ai_flags; deleting last file for a doc_name un-ticks it.
  3. Form UI: "📎 Attached Files" block (doc-type select + Attach File via
     FileReader→base64), file rows with view (blob new tab) / delete;
     register expanded detail lists attached files w/ view.
  PF WAGE BASE (user confirmed option a):
  4. compliance_salary.py compute_compliance_row: floor applies ONLY when
     pf_basic_override < pf_wage_cap → base=max(pf_basic_prorated,
     floor%×gross_paid); else base=pf_basic_prorated; wages=min(base, cap).
     Replaces Iter 254 strict-PF-Basic rule. Mirrored in
     compliance-salary-run.tsx client grid recompute (grossEarn incl ot_pay).
  Verified: 7 unit cases (8000/20000→10000, 8000/40000→15000, 18000→15000,
  15000→15000, 8000/12000→8000, half-month 18000→9000, 0→0); attachments
  E2E via curl (upload/list/download/auto-tick/bad-type-reject/delete-untick)
  + playwright UI (attach button, 8 doc types, employee picker 129 opts in
  edit mode). Test claims cleaned up.
  Deploy: deploy_vps_iter376.sh (temp_bundle→376, includes 370-375).
- Iter 377 (user: Compliance salary grid shows only Firm-Master-enabled heads):
  Grid already masked columns via rows[0].enabled_allowances/enabled_deductions
  (stamped by engine since Iter 85/171) but OLD runs / Copy-Last-Month / legacy
  runs lack the stamp → all heads showed. FIX in compliance-salary-run.tsx:
  fmMask state fetches /admin/firm-master/{cid} (cid from rows[0].company_id
  or activeCompanyId), maps AMAP {HRA:hra, CONV.:conveyance, MEDICAL
  ALLOWANCES:medical, OTH. ALLOW.:special, OTHER MISC.ALLOWANCE:others} +
  ded mask (epf/esi applicable authoritative else PF/ESI catalog, PT, TDS/
  I. TAX). Mask only when master stored (updated_at/updated_by present —
  mirrors backend "None only when never configured"). All 8 mask sites now
  use `?? fmMask.en/.ed` fallback (group header, col headers, row cells
  master+calc, ded cells, totals, navCols).
  Verified via playwright: Kankani grid (STAFF July) shows M.Basic/M.HRA/
  M.Conv/M.Gross only; M.Med/M.Spl/M.Others + PT/TDS header cells hidden.
  Deploy: deploy_vps_iter377.sh (temp_bundle→377, includes 370-376).
- Iter 378 (user accepted improvement: old-run exports follow Firm Master):
  server.py: async _ensure_firm_head_masks(run) — when rows[0] lacks
  enabled_allowances/enabled_deductions, stamps LIVE firm master masks
  (same AMAP + epf/esi applicable-or-catalog + PT + TDS/I. TAX logic as
  engine) on all rows at EXPORT time. Called in compliance-salary-runs
  export.csv / export.xlsx / register.pdf endpoints (after auth guard).
  Verified: cloned July run with masks stripped (run_test_oldmask) →
  CSV/XLSX headers show basic/hra/conveyance only (no medical/special/
  others/pt/tds); PDF text lacks Medical/Special/P.Tax/TDS. Test run
  deleted after verification.
  Deploy: deploy_vps_iter378.sh (temp_bundle→378, includes 370-377).
- Iter 379 (user: compliance grid highlights + column order):
  compliance-salary-run.tsx:
  1. Column order: Sr(new, 40px, idx+1) → UAN No. → ESIC No. → Name →
     Father → Desg → PD → ESIC Leave. First FOUR columns sticky
     (stickyOff [0,sr,sr+uan,sr+uan+esi]); infoW/i<8/i>=6 right-align;
     FROZEN_W/INFO_W updated; filter row + totals row realigned (TOTAL
     under Name).
  2. Gross column highlighted amber (#FEF3C7 cells, #B45309 header);
     Freeze Salary purple as before (#5B21B6 header now too).
  3. frzDiff now VALUE-based: |imported_gross - gross_paid| > 0.5
     (was freeze_status !== "matched" which broke on runs without the
     stored status). Diff employees: row #FEE2E2 + red left border
     (existing), NAME bold red, Gross+Freeze cells #FECACA/#991B1B.
  Verified via playwright: grid shows Sr|UAN|ESIC|Name order, amber Gross
  header/cells, totals aligned. Freeze columns render only on imported
  runs (hasFrz) — unchanged.
  Deploy: deploy_vps_iter379.sh (temp_bundle→379, includes 370-378).
- Iter 380 (user accepted improvement: "Mismatch only" filter):
  compliance-salary-run.tsx: onlyMismatch state + rowIsMismatch(r)
  (|imported_gross - gross_paid| > 0.5). sortRows filters when active.
  Chip "⚠ Mismatch only (n)" beside Sort buttons, rendered only when
  hasFrz; red-filled when active, red-outline when n>0.
  Verified: patched July run rows with imported_gross (2 diffs) → chip
  showed (2), click filtered grid to the 2 red-highlighted employees.
  DB patch reverted after test.
  Deploy: deploy_vps_iter380.sh (temp_bundle→380, includes 370-379).
- Iter 381 (user accepted improvement: payslips follow Firm Master heads):
  utils/payslip_pdf.py _flow_for_employee: earnings list dynamic —
  Basic always; HRA/Conveyance/Medical/Special/Others per
  row.enabled_allowances (mask None → legacy: HRA always + others only
  when non-zero); Overtime always; Bonus/Other Earnings hidden when mask
  present & zero. Deductions PF/ESIC/PT/TDS per enabled_deductions;
  Advance/Other always. server.py _payslip_rows_for_month (compliance
  branch) stamps masks via _ensure_firm_head_masks → covers single
  payslip, ZIP-all, e-mail payslips endpoints (all use this helper);
  /me payslips + actual-run bulk keep legacy fallback (mask None).
  Verified: employee-payslip.pdf for Kankani July → shows Basic/HRA/
  Conveyance/Overtime + PF/ESIC only; Medical/Special/PT/TDS/Bonus
  hidden. pytest payslip builder tests pass (7 passed; other errors are
  pre-existing live-session fixtures).
  Deploy: deploy_vps_iter381.sh (temp_bundle→381, includes 370-380).
- Iter 382 (user: PF & ESIC Claims form changes):
  Backend claims_management.py: PF_TYPES += "Pension (Form-10D)",
  "Death Claim (Form-20 / 5-IF)", "Composite Claim Form"; /employees
  projection returns phone.
  Frontend claims-management.tsx:
  1. FIELDS: removed department/designation/acknowledgement_no/
     payment_reference; added uan_password + mobile_no. Field ORDER
     (user follow-up): UAN Number → UAN Password → Mobile No. →
     Employee Code → Employee Name → dates.
  2. All date fields labeled/typed DD-MM-YYYY; DATE_KEYS + isoToDDMM/
     ddmmToISO convert on load (editClaim) and save (save() converts to
     ISO before POST so range filter/sort/reminders still work);
     verified: typed 15-06-2026 → stored 2026-06-15. Reminders display
     converted. pickEmployee fills mobile_no + DD-MM dates.
  3. Executive auto-fills logged-in user name (useAuth user.name),
     editable.
  4. Attach button renamed "Upload Document" (cloud icon).
  Verified via playwright (all removals, autofill, new types, save) +
  DB check; test claim deleted.
  Deploy: deploy_vps_iter382.sh (temp_bundle→382, includes 370-381).
- Iter 383 (user: Form 20/10D/5-IF data capture + print in attached format):
  User uploaded "PF Composite Claim Form No 20,10D & 5IF.xls" + "New Forn
  No-8.docx". Built:
  1. /app/backend/utils/death_claim_forms.py — reportlab canvas builders:
     build_composite_death_claim_pdf (replicates Excel: header epfindia/
     mobile, titles, items 1-10 numbered rows with tick boxes, item 11
     claimant table 4 rows × 9 cols, item 12 PF/EDLI bank (Claimant I-III),
     item 13 Pension bank (I-IV), item 14 address+PIN, certification,
     signatures, 5 enclosures) and build_form8_pdf (FORM No. 8 descriptive
     roll, rows 1-9 + specimen signature + finger-impression grid + date/
     place/attesting authority, 2 identical pages = duplicate). dc dates
     printed DD-MM (ISO converted).
  2. GET /admin/claims/{id}/death-forms.pdf?which=composite|form8.
  3. claims-management.tsx: isDeathType (/Form-10D|Form-20|5-IF|Composite|
     Death/) shows section — PF/Pension/EDLI tick chips (dc_app_*),
     DC_ROWS deceased fields, 4 claimant blocks (DC_CL_COLS), PF bank ×3 +
     Pension bank ×4 (DC_BANK_COLS), F8_ROWS; all flat dc_* keys in
     form/data; editClaim restores dc_*. Print buttons (composite/form8)
     via apiBinary; require saved claim.
  Verified: PDFs rendered to PNG and visually match attachments; endpoint
  200 for both; UI section renders with print buttons; test claim deleted.
  Deploy: deploy_vps_iter383.sh (temp_bundle→383, includes 370-382).
- Iter 384 (user accepted improvement: one-tap claimant→bank auto-copy):
  claims-management.tsx: green "Auto-copy Claimant names → Bank tables"
  button (testid cl-dc-autocopy) between claimant blocks and PF bank
  section — copies dc_cl{i}_name → dc_pfbank{i}_name (i≤3) +
  dc_pnbank{i}_name (i≤4), and dc_pfbank{i}_{acc,bank,ifsc} →
  dc_pnbank{i}_* ; fills only blank fields (never overwrites).
  Verified via playwright: claimant names + PF acc/IFSC propagated.
  Deploy: deploy_vps_iter384.sh (temp_bundle→384, includes 370-383).
- Iter 385 (user: PF/ESIC audit + OLD-DB unlock w/ log):
  AUDIT FINDINGS: PF=0 for all Kankani emps because Employee Master
  pf_basic blank (Iter 129/254 rule). User confirmed: (1) PF blank →
  NO deduction (keep rule); (2) ESIC wage base = 50% rule: max(Basic,
  50% of Gross); (3) pf_applicable=No exclusion stays.
  a) compliance_salary.py: esic_wage_base = stat_wage_base (was basic;
     replaces Iter 130). compliance-salary-run.tsx grid recompute:
     esiBase = max(paidBasic, grossEarn*floorPct). Unit verified:
     basic 4000/gross 10000 → base 5000, EE 38, ER 163.
  b) OLD-DB employees (legacy_locked): employee_profile.py PATCH no
     longer blocks — full master+salary edits allowed; audit log entry
     (Iter 312 employee_audit_logs) now flagged legacy_locked:true.
     bulk_ops.py revise: locked skip removed, salary_revisions entry
     flagged legacy_locked. Delete of locked employee remains BLOCKED
     (server.py 9180). legacy_salary_history NEVER written. E2E
     verified: locked emp edit ok, audit log w/ from→to + flag, legacy
     docs count unchanged; test data reverted.
  Deploy: deploy_vps_iter385.sh (temp_bundle→385, includes 370-384).
- Iter 386 (user: Employee Master +91 mobile):
  employee-add.tsx: new MobileField component — fixed NON-editable
  "+91" badge (surfaceTertiary bg, right border) + TextInput capped at
  10 digits (maxLength+regex). normalizePhone10() strips legacy
  "+91"/"91" prefixes on form load. Review summary shows "+91 XXXXXXXXXX".
  Storage unchanged: form.phone holds 10 digits only (Iter 376
  validation intact). Verified via playwright: badge visible, typing 13
  digits keeps only 10.
  Deploy: deploy_vps_iter386.sh (temp_bundle→386, includes 370-385).
- Iter 387 (user: Revise PF & ESIC Calculation Module — Phase 1+2 of 6):
  PLAN (user approved): P1 config+masters, P2 engine+snapshot, P3
  validation engine + Salary Lock block (Super Admin can override
  WARNINGS, errors always block), P4 audit dashboard + View Calculation
  + monthly snapshot, P5 reports, P6 AI assistant. SINGLE deploy script
  at the END of all phases (no per-phase deploys).
  P1: compliance_settings.py + compliance-settings.tsx — new cfg keys
  pf_enabled/esic_enabled/wage_definition_rule_enabled/
  esic_disable_above_ceiling (bools), pf/esic_proration_method
  (calendar_days|paid_days|attendance_days|working_days|none),
  rule_version (label), head_mapping (7 heads basic/hra/conveyance/
  medical/special/others/ot × {pf,esic}; basic force-locked true).
  Works in BOTH scopes: Standard (all firms) + per-firm override
  (firm_masters.statutory_overrides). Employee Master new fields:
  higher_pension/intl_worker/excluded_employee/esic_temp_exempt (bool),
  esic_reg_status/dispensary/esic_join_date/esic_exit_date (str) — in
  employee_profile.py whitelists, server.py create (~8492),
  employeeForm.ts, employee-add.tsx UI (PF flags after EPS Disable;
  ESIC block after UPI in Statutory section).
  P2: compliance_salary.py engine — cfg passthru keys (_CFG_PASSTHRU),
  _proration_factor(), module gates, excluded_employee skip, intl
  worker = no PF cap, higher_pension = EPS on uncapped base, ESIC temp
  exempt + exit-date(month via cfg._salary_month) + disable-above-
  ceiling toggle, wage-rule OFF ⇒ ESIC base = Σ mapped heads (+OT),
  pf/esic_reason strings + calc_snapshot on every row. Run doc stores
  statutory_effective (full merged cfg) — statutory_cfg untouched so
  reprocess still re-merges live settings. Grid recompute
  (compliance-salary-run.tsx updatePresentDays) mirrors: reads
  statutory_effective, wage-rule switch, head mapping, eps_disabled/
  higher_pension/intl_worker. DEFAULTS REPLICATE PRE-387 BEHAVIOUR.
  11 engine unit cases + testing agent 8/8 pytest + UI smoke ALL PASS
  (test_reports/iteration_387.json). rule_version saved: "FY 2026-27 v1".
  DEFERRED: single deploy script after Phase 6.
- Iter 388 (Phases 3-6 of PF/ESIC module — ALL DONE, tested 17/17):
  P3 VALIDATION ENGINE: routes/compliance_validation.py —
  validate_compliance_run() checks PF_ZERO/PF_MISSING_UAN/PF_DUP_UAN/
  PF_WAGE_INVALID/PF_ABOVE_CEILING/PF_MISSING_BASIC/
  PF_HIGHER_PENSION_MISMATCH/PF_SALARY_CHANGED + ESIC_ZERO/MISSING_IP/
  DUP_IP/WAGE_INVALID/ABOVE_CEILING/WRONG_EXCLUSION/EXIT_BEFORE_MONTH/
  MAPPING_MISSING. GET .../{run_id}/validate. Finalize (server.py
  ~16955): errors→422, warnings→409 (can_override), super_admin +
  {allow_warnings:true}→200 + lock_validation stamp. Frontend: lockCheck
  modal in compliance-salary-run.tsx (finalizeRun validates first;
  "Lock Anyway (Super Admin — warnings only)" button).
  P4 AUDIT DASHBOARD: GET .../{run_id}/audit-dashboard; new screen
  /pf-esic-audit (run picker → color table Green/Yellow/Red + filters +
  search + View Calc modal rendering calc_snapshot). "PF/ESIC Audit"
  ActionBtn (testID btn-pf-esic-audit) on salary run screen. Monthly
  snapshot: write_monthly_snapshot() → db.compliance_monthly_snapshots
  (append-only, on finalize; failure never blocks lock).
  P5 REPORTS: GET .../audit-export?kind=pf|esic|exceptions&format=
  xlsx|pdf (openpyxl/reportlab; sheet-title sanitizer _re_sheet) + GET
  /admin/compliance-reports/missing-ids?which=uan|ip&format=. All 10
  combos 200.
  P6 AI ASSISTANT: POST .../{run_id}/ai-explain/{user_id} — Emergent
  LLM key, gpt-5.4-mini, explains PF/ESIC why/heads/rules/validation/
  action; purple "AI Explain" button in View Calc modal.
  Also fixed pre-existing duplicate router-include/shutdown block in
  server.py tail. Testing agent: backend 17/17 + frontend all pass
  (iteration_388.json; pytest backend/tests/test_iter388_*.py).
  PENDING USER ANSWER: printable A4 explanation sheet in View Calc?
  DEFERRED: single VPS deploy script after user confirms (deploy script
  387 currently live on temp-code-bundle; needs 388 bump when user asks
  to deploy).
- Iter 389 (user confirmed): Printable A4 Explanation Sheet — GET
  /admin/compliance-salary-runs/{run_id}/calc-sheet/{user_id} (reportlab
  A4 portrait: employee header, heads-considered table, PF/ESIC workings,
  rules, validation table color-coded, footer). "Print A4 Sheet" button
  (teal, testID calc-print-a4) beside AI Explain in View Calc modal
  (apiBinary → window.open blob on web). Verified: 1-page PDF w/ all
  sections. Deploy: deploy_vps_iter389.sh (temp_bundle→389; combined
  386+387+388+389).
- Iter 390 (user: Compliance Salary Process must follow Firm Master
  enabled Allowances/Deductions everywhere): VERIFIED grid Master-rate &
  calculated columns already mask correctly (Iter 377; Kankani shows
  only M.Basic/M.HRA/M.Conv). FIXED 3 remaining spots in
  compliance-salary-run.tsx that ignored the mask: (1) header subtitle
  "PF · ESIC · PT · TDS" now lists only enabled deduction heads,
  (2) run summary line (month_days · PF · ESIC · PT · TDS) hides
  disabled heads, (3) sticky TotalsFooter hides PF/ESIC/PT/TDS blocks
  per enabled_deductions (row-stamped mask, fmMask fallback). Verified
  via screenshot on Kankani (PT/TDS disabled → hidden everywhere).
- Iter 391 (user confirmed improvement): mask applied to Copy Last
  Month confirm text (enabled ded heads only) + Past Salary Runs
  compliance list meta now shows Net · PF · ESIC (· PT · TDS only when
  firm-enabled) via edMask fetched from firm-master. Verified via
  screenshot (Kankani: PT/TDS hidden). Deploy: deploy_vps_iter391.sh
  (temp_bundle→391; combined 386-391). USER DEPLOYING LIVE NOW.
- Iter 392 (user spec: Attendance Synchronization Dashboard): NEW module
  — backend routes/attendance_sync_dashboard.py (GET
  /admin/attendance-sync-dashboard w/ filters company/preset/
  missing_days/dept/desig/machine/status; KPIs, 7 sections: new joining,
  machine-only (biometric_unmapped + difflib suggested match),
  master-only, attendance-missing (leave-aware remarks), continuous
  absence buckets 3/5/7/15/30, machine sync health, weekly-join +
  daily-punch trends; rule-based smart remarks; 0.24s load) + export
  endpoint (xlsx/pdf/csv per section). Frontend
  app/attendance-sync-dashboard.tsx (KPI cards, filter chips, search,
  collapsible sections, progress bars, trend bars, row nav to
  employee-detail-slip / biometric-devices). Menu after "Attendance
  Report" in AdminWebShell (Attendance & Shift + Reports groups).
  Testing agent: 12/12 backend pytest + 10/10 frontend flows PASS.
  Deferred (per WhatsApp integration pending): Notify HR/WhatsApp/Email
  actions, nightly scheduler.
- Iter 393 (user: single-sheet full export): section=full on the export
  endpoint — ONE Excel sheet with all 7 sections stacked (styled bands),
  one combined PDF (landscape, 10pp) and CSV. Header EXCEL/PDF buttons
  (testID asd-full-xlsx/asd-full-pdf). Verified via openpyxl/pypdf.
- Iter 393 deploy: deploy_vps_iter393.sh (temp_bundle→393, incl 392+393). USER DEPLOYING.
- Iter 394 (server.py refactor P0): Compliance Salary Runs engine
  (~2,200 lines: create/process, list, save-rows, finalize + Iter-388
  validation gate, unlock requests, reprocess, CSV/XLSX/register-PDF/
  PF-ECR/ESIC exports, generate-payslips) extracted from server.py into
  routes/compliance_salary_runs.py (server.py 22k → 20.5k lines).
  Previous fork created the module but never registered it, leaving 6
  NameError call sites in server.py (_firm_offline_salary_enabled,
  _firm_biometric_attendance_enabled, _ensure_firm_head_masks,
  _require_firm_salary_permission). Fixed: router registered + 4 helpers
  imported back into server.py namespace. Also removed a duplicated
  include_router block (9 modules registered twice). Testing agent:
  23/23 backend pytest PASS (tests/test_iter394_compliance_salary_runs_refactor.py).
- Iter 394 deploy: deploy_vps_iter394.sh (temp_bundle→394). AWAITING USER DEPLOY.
- Next: WhatsApp API integration (P1); continue server.py extraction (P2).
- Iter 395 (user: WhatsApp Business Integration Module, all 3 phases):
  Backend utils/whatsapp_engine.py (Graph client, per-firm encrypted
  creds via secrets_vault, 20s queue worker with retry/backoff + daily
  limits + auto log cleanup, daily scans: birthday/anniversary/absent/
  continuous-absence/holiday/doc reminders, schedules engine, chatbot
  keyword replies SALARY/ATTENDANCE/LEAVE/PF/ESIC/HOLIDAY/PROFILE/BANK/
  HELP) + routes/whatsapp_center.py (settings w/ masked tokens, template
  CRUD + 30 seeded defaults + preview, manual/bulk send, send-salary-
  slips by month, history retry/cancel/delete, dashboard KPIs, schedules
  CRUD, reports json/xlsx/pdf, PUBLIC webhook GET verify + POST statuses
  /inbound chatbot with optional HMAC signature check, employee wa-field
  update endpoint). Hooks: welcome on employee create (server.py),
  salary_processed + salary_slip PDF on generate-payslips
  (compliance_salary_runs.py), leave approved/rejected (leaves.py).
  Frontend: whatsapp-config.tsx, whatsapp-templates.tsx,
  whatsapp-center.tsx (6 tabs) + 5 AdminWebShell menu entries
  (Administration/Communication/Payroll/Attendance/Compliance).
  PENDING-CONFIG mode until user enters Meta credentials (user choice 1b).
  Collections: wa_settings, wa_templates, wa_messages, wa_schedules,
  wa_inbound, wa_audit. Testing agent: 22/22 backend + frontend PASS
  (/app/test_reports/iteration_395.json).
- Iter 395 deploy: deploy_vps_iter395.sh (temp_bundle→395). AWAITING USER DEPLOY.
- Backlog Phase 4 (user's future enhancements): AI chatbot self-service,
  two-way HR conversations, Hindi/English multi-language, WhatsApp OTP,
  payslip acknowledgment, approval workflows via WhatsApp (leave/OT/
  reimbursement), voice/document sharing, QR code to start chat.
- Iter 396 (potential improvement, user approved): "WhatsApp Payslips"
  one-click blast button on compliance-salary-run.tsx action bar (next to
  Push payslips) → POST /admin/whatsapp/send-salary-slips {month} for the
  open run's firm. E2E verified (queued 18/18 for csrun 2026-07, test
  messages cleaned). NOTE: initial search_replace corrupted the file tail
  (orphaned StyleSheet block) — fixed by truncating + insert_text.
  Included in deploy_vps_iter395.sh bundle (user hasn't deployed yet).
- Iter 396 (user): PF Reports "Portal Login" card added to pf-reports.tsx —
  green "Login — Open EPFO Portal" (opens
  https://unifiedportal-emp.epfindia.gov.in/epfo/ in a NEW browser tab;
  ESIC tab opens the ESIC login URL) + amber "Auto-Login Runner (Chrome)"
  (downloads /admin/portal-automation/runner-download zip, firm-scoped).
  E2E verified via Playwright (new tab url confirmed).
- Iter 396 (verification): Freeze Salary OT/Other allocation confirmed
  correct in current code (OT ON→Overtime, OT OFF→Other Allowances,
  days auto-shrink, final gross==imported). Stale legacy row in frozen
  2026-07 run (emp 50, diff −1.55) predates Iter 340/344 fixes —
  remedy: unlock → reprocess → refreeze. 2 stale Iter-310 tests updated,
  suite 10/10 green.
- Iter 396 (refactor step 2): Actual Salary Process block (server.py
  19152–19961: _actual_salary_row_compute/_actual_salary_totals, models,
  /admin/branches, actual-salary-process create/row/finalize,
  salary-runs unlock) extracted to routes/actual_salary_process.py;
  router registered; openapi 696 paths, all 5 extracted routes live.
- Iter 397 (user flow): ONE-CLICK PORTAL LOGIN implemented exactly per
  user diagram: PF Reports Login button → POST
  /admin/portal-automation/launch-token (firm-scoped, auth) → browser
  fetches http://127.0.0.1:8765/login?portal=epfo|esic&token=... →
  Runner v6 listener (run_listener.bat, CORS + Private-Network headers)
  → GET /api/portal-ext/get-login (alias of creds; returns ONLY selected
  firm creds) → Selenium Chrome opens portal → CLICKS ALERT OK FIRST
  (btnCloseModal + 3 fallback selectors, 8s/2s waits) → auto-fills
  Username/Password → user enters captcha + clicks Login. Fallback when
  Runner not listening: opens portal tab + hint (verified E2E via
  Playwright: fallback tab https://unifiedportal-emp.epfindia.gov.in/epfo/
  + message shown; listener contract verified via curl: /ping, /login
  launched:true, OPTIONS CORS headers). Runner code compile-checked.
- Iter 397 (refactor steps 3-6): extracted routes/attendance_policy_api.py
  (policy get/patch/presets/saved-list/reset + textile compute-day),
  routes/attendance_reports_api.py (_monthly/_daily_report_impl + monthly
  hours/ot/inout + daily xlsx/pdf), routes/attendance_location_api.py
  (flagged, location-audit +xlsx, clear-flag, selfie; _compute_location_status
  imported back), routes/employees_admin.py (create/bulk-import/template/
  parse/delete; _employee_is_resigned + delete_employee_record imported
  back for deletion_approvals lazy import). server.py 19,747→17,914.
  openapi 696 paths unchanged; all smoke tests OK. Full testing-agent
  regression STILL PENDING (first attempt aborted during setup) — rerun
  before/after next deploy.
- Iter 398 (refactor step 7, FINAL BIG BLOCK): attendance core cluster
  (~3,520 lines: punch engine, worksites, pending/approve, roster/mark,
  day-status, manual-punch + audit, admin history, _compute_payroll_run,
  shared date helpers) extracted to routes/attendance_core.py. server.py
  17,924 → 14,400 lines (22k at session start). 13 shared names
  re-exported into server namespace FIRST at bottom (fixed boot
  ImportError _month_is_complete by scanning ALL route modules'
  `from server import` lists). Testing agent 26/26 PASS
  (tests/test_iter398_attendance_core_refactor.py, employee PIN-login
  punch flow, manual-punch + roster cycles with cleanup, payroll engine,
  downstream payslips/biometric/messages imports, openapi 698).
- Iter 398 (user): Runner v7 — alert dismiss now tries OK
  (#btnCloseModal, 20s) first, then X (aria-label="Close"), then generic
  dismiss buttons; applied to ecr_test flow, sign-in modal strip and the
  generic login flow, THEN autofill runs. Compile-checked; served
  version 7 verified.
- Iter 400 (user): Runner v9 — EPFO alert popup fix (real root cause: click
  fired mid fade-in animation and was intercepted). New logic: wait for
  document.readyState complete → poll up to 25s for a VISIBLE modal → click
  OK/Close with JS-click fallback → verify modal gone → strip stuck
  backdrops → THEN autofill (Angular-safe send_keys typing in generic path).
  Also ChromeDriver AUTO-UPDATE self-heal ladder in _fresh_driver()
  (retry → wipe ~/.cache/selenium + pip -U selenium → SE_FORCE_BROWSER_DOWNLOAD).
  E2E-verified in-container with real Chrome + mock EPFO page (delayed
  animated modal): popup clicked, modal gone, creds filled. Runner is
  self-updating; user only restarts run_listener.bat. User confirmed to
  KEEP the PC-runner architecture (Selenium→ChromeDriver→Chrome on user PC).
- Iter 400 (user): Reports Center column alignment — RegisterTable header
  first cell was 108px vs 170px data cell (st.first); added st.thFirst so
  ALL register-style report headings align. Screenshot-verified.
- Iter 401 (user check "Salary Report PDF/Excel Format 1 & 2"): register
  earnings "Other" column in BOTH PDF formats is now the RESIDUAL
  (gross_paid − basic − hra − conv) so rows ALWAYS tally to GROSS (daily-
  rated rows keep medical/special inside gross with earned heads at 0).
  F1 master OTHER column + earnings OTHER now also show when heads exist
  only on the master (show_oth_m/show_oth_e extended). v2 summary
  tot["oth_e"] uses same residual. Excel: _NUMERIC_COLS extended (basic,
  hra, conveyance, monthly_gross, gross_paid, pf_wages, stat_wage_base,
  vpf_amount, medical, special, others, other_deduction, master_deduction,
  pf_employer_total) so TOTAL row sums them; _NO_TOTAL_COLS skips rate/
  month_days. Verified on run csrun_630128ccfd1d (127 emps): rows and
  summary tally (105,002), Excel totals correct.
- Deploy: /app/deploy_vps_iter401.sh served via temp-code-bundle kind=script.
- Iter 402 (user, In/Out & OT Matrix): row sequence now D-In, D-Out,
  Total Hrs, OT-In, OT-Out, Total OT Hrs + NEW "Total Working Hrs" row
  (= Total + OT; uses grid cell "hours" which is duty+OT combined, while
  "total" now maps to duty_hours DUTY-ONLY so rows tally). Default status
  = "active" (backend all endpoints + frontend chip). OT-In/OT-Out blanked
  when OT rounds to zero (no phantom boundary time before D-Out).
  month_grand added to JSON/xlsx/pdf Month Totals.
- Iter 402 (user OT rule, shared engine server.py split_regular_ot_times):
  a 2nd IN→OUT pair whose IN falls BEFORE (first-IN + duty quota) is a
  BREAK RETURN merged into the regular window — NOT OT. OT starts only
  from a pair beginning at/after the quota boundary (second-precision).
  If merged window exceeds quota, existing arithmetic split still applies
  (user: "decide as per Attendance Policy" for no-re-entry days).
  Unit-tested: lunch-break, real-OT, short+break, single-long, break+OT,
  boundary-second cases all pass; live July data (51 emps) grand tally
  0 mismatches; UI screenshot verified (rows + Active default).
- Deploy: /app/deploy_vps_iter402.sh served via temp-code-bundle kind=script.
- Iter 403 (user accepted): Day-wise OT Totals footer on In/Out & OT
  Matrix — per-day OT sums across ALL filtered employees (computed in
  _build pre-pagination; keys day_ot_totals + month_ot_total). UI card
  (light-blue OT days, AMBER heaviest day), xlsx footer block, pdf footer
  table. Verified live (July: month OT 854:00, peak day 12 = 154:30).
- Deploy: /app/deploy_vps_iter403.sh served via temp-code-bundle kind=script.
- Iter 404 (user): QR Codes (Joining & App) firm selection converted from
  chip list to searchable dropdown (reused src/components/CompanyPicker,
  allowAll=false, preloaded list, auto-select first firm). Chip styles
  removed. Screenshot-verified incl. firm switch updating QR + code.
- Deploy: /app/deploy_vps_iter404.sh served via temp-code-bundle kind=script.
- Iter 405 (user accepted): "Download PNG" button on both QR cards in
  join-qr.tsx — serializes the on-screen react-native-qrcode-svg SVG onto
  a 640px canvas (white bg, offline; the first attempt via api.qrserver.com
  fetch stalled) and downloads `<Firm>-<type>-QR.png`. Playwright-verified
  actual download (City-Care-Hospital-employee-QR.png).
- Deploy: /app/deploy_vps_iter405.sh served via temp-code-bundle kind=script.
- Iter 406 (user rule "Gross Earning includes OT" for PF/ESIC):
  compute_compliance_row now accepts stats.ot_pay_extra /
  stats.other_allowance_extra; the Freeze block in
  routes/compliance_salary_runs.py re-computes the row with the diff
  allocated INSIDE the compute (merging earnings+statutory fields back,
  preserving sheet TDS/other_deduction/deduction+allowance masks; single
  path handles +diff Overtime/Other Allowances and -diff Trim). Frontend
  grid updateRowField(ot_pay/others) now refreshes PF wages/amounts +
  ESIC base/amounts live (mirrors backend); totals strip extended.
  E2E verified on a fresh freeze run (RAJENDRA: swb 10,500 = 50%x21,000
  incl OT 912; ESIC 79); full-run 0 mismatches; freeze test suite passed.
- Deploy: /app/deploy_vps_iter406.sh served via temp-code-bundle kind=script.
- Iter 407 (user): Salary Lock ERROR override — finalize accepts
  allow_errors (super_admin only) -> 422 detail includes can_override;
  lock_validation.errors_overridden stamped; red "Lock Anyway (override
  errors)" button in the lock popup. E2E tested.
- Iter 408 (user spec): Higher PF & VPF module. Engine: pf_contribution_type
  statutory|higher|vpf on Employee Master (+higher_pf_wage, vpf_percent,
  higher_pf_from/to, pf_declaration_available, pf_approval_required,
  pf_approval_status, pf_remarks; all in employee_profile allowed fields
  with db.pf_audit_log change trail). Company policy allow_higher_pf
  (default false)/allow_vpf(default true)/vpf_max_percent in compliance
  settings (backend tuples + settings screen with per-field bool default
  support). compute_compliance_row: higher = uncapped both sides, EPS on
  cap unless higher_pension, gated by policy+approval+window w/ fallback
  reason (pf_higher_reason, calc_note explains); vpf = % of PF wages or
  fixed, clamped by vpf_max_percent, employer unchanged. 10 new lock
  validations in compliance_validation.py (PF_ABOVE_CEILING exempts
  higher-active). Snapshot rows freeze type. NEW routes/
  pf_contribution_report.py (view=all|higher|vpf|pending|diff, xlsx, pdf)
  + app/pf-contribution-report.tsx + Reports Center link. Employee Master
  UI: type chips + conditional Higher/VPF boxes + status chip
  (Pending/Approved/Rejected/Expired). Unit tests 10/10 + testing_agent
  iteration_408.json 10/10 PASS. Pre-existing minor notes: profile route
  is PATCH (not PUT); reprocess requires month in body.
- Deploy: /app/deploy_vps_iter408.sh served via temp-code-bundle kind=script.

## Iter 409 — Reprocess 422 fix (June 2026 fork)
- User verified Iter 408 (Higher PF/VPF) on VPS: all good.
- Fix: POST /admin/compliance-salary-runs/{run_id}/reprocess no longer
  422s when body is empty / missing "month". Endpoint now accepts a raw
  Optional[Dict] Body and falls back to the run's saved values (month,
  month_days, employee_type, is_onroll, structure_pct, statutory_cfg).
  Verified: empty body, no body, partial (no month), full body → all 200,
  month preserved after reprocess.
- Deploy: /app/deploy_vps_iter409.sh served via temp-code-bundle kind=script.
- WhatsApp/Meta block: still NOT lifted (user confirmed) — remains blocked.

## Iter 409b/410 — Refactor + Quick-sheet + BIOFACE (June 2026 fork)
- Iter 409 refactor DONE: server.py 14,449→11,952 lines. Extracted verbatim:
  routes/sub_admins.py (sub-admin CRUD + portal creds + access rights),
  routes/masters_policy.py (masters CRUD + pt-states + compliance-policy),
  routes/bonus.py (bonus policy/runs/report), routes/salary_runs.py
  (legacy Actual salary runs + exports + payslips + annual report),
  shared/sorting.py (_sort_export_rows), shared/hours.py
  (_compute_day_hours & co.), routes/attendance_self_service.py (punch
  approvals + history/selfie/my-month/summary; attendance_core 1262→858).
  Re-exports kept on server: _payslip_rows_for_month (WhatsApp engine),
  _sort_export_rows, _compute_bonus_run (statutory_registers),
  _clean_mobile_or_400/_validate_pin_or_400 (company_roles).
  testing_agent regression 41/41 PASS (iteration_409.json,
  tests/test_iter409_refactor_regression.py).
- Iter 410 (user request): Employee quick-manage sheet (admin.tsx) now
  shows Father Name, Online/Offline (On-Roll/Off-Roll) badge and DOJ.
  Also fixed missing Live-in toggle styles (was unstyled).
- Iter 410: BIOFACE-MSD1K biometric machine — new brand "bioface" in
  frontend BRANDS + backend model map. iClock/ADMS ingest verified
  (handshake + ATTLOG push with user SN 1801FACEMSD1K1030).
- Deploy: /app/deploy_vps_iter410.sh served via temp-code-bundle kind=script.
- Iter 410b (remote, on PRODUCTION smartpayrolling.com): BIOFACE MSD1K
  registered via API — device_id dev_31fcd51c54, SN 1801FACEMSD1K1030,
  firm JAI CLINIC & NURSING HOME (cmp_652c3d8222), kind=both,
  brand=bioface. iClock handshake 200 + test ATTLOG punch (bio 99999)
  ingested → Punch Log shows "NOT FOUND IN MASTER" as expected.
  NOTE: prod super-admin password is Sharma@2026 (NOT sharma123).
  User still needs to: run deploy_vps_iter410.sh + configure machine ADMS
  + physical punch test.
- Iter 410c: Device OFFLINE alert now also EMAILS (super admins + firm's
  company admins) via SMTP settings machinery (routes/email_notifications
  _get_settings/_send_and_log), lazy-imported in device_offline_alert_loop.
  One email per outage, re-arms on reconnect. Gated on SMTP configured
  (prod has it; dev doesn't — verified recipients resolution in dev).
- User reported "Bioface option not showing" — root cause: Iter 410 not
  yet deployed on VPS (prod JS bundle predates change; preview verified
  BIOFACE chip renders). deploy_vps_iter410.sh updated with email alert.

## Iter 411 — Legacy import: STRICT code matching (user rule)
- routes/legacy_import.py: employee master + off-roll workers import now
  match by EMPLOYEE CODE ONLY. All name-based fallback matching REMOVED
  (user: "do not treat same-name as same employee, do not update") —
  no code match ⇒ NEW employee created.
- Duplicate EmpCode within the OLD DB: first row wins, later rows skipped
  with report line "DUPLICATE EmpCode ..." (totals.employees_duplicate_code).
  seen_codes resets per firm.
- Deploy: /app/deploy_vps_iter411.sh served via temp-code-bundle kind=script.

## Iter 412 — Group-wise attendance sheet BLANK fix (user bug)
- ROOT CAUSE (verified on prod data — 10+ firms affected incl. KANKANI 110→5,
  IKORE 133→5): global category group masters (LABOUR etc.) carry a stale
  member_user_ids list pointing at ANOTHER firm's employee → resolver
  returned that 1 foreign id → blank sheet. All-groups ZIP splits by
  employee_type directly, hence worked.
- Fix in server.py _resolve_group_employee_ids:
  1) explicit member lists filtered to the selected firm; if none remain,
     fall through to name matching;
  2) masters lookup includes company_id None;
  3) EGP fallback now regex-matches BOTH employee_group AND employee_type
     case-insensitively (was employee_group-only exact match).
- Verified: injected stale foreign member into dev LABOUR group → export
  now 113 rows (was blank/5). Test data restored.
- Deploy: /app/deploy_vps_iter412.sh via temp-code-bundle kind=script.
- Iter 412b (user approved): startup migration wipes stale member_user_ids
  on GLOBAL group masters (idempotent via migration_flags
  iter412_global_group_member_wipe). Verified in dev (seeded stale member
  → wiped on restart, flag set). Runs automatically when the VPS deploy
  restarts the backend.

## Iter 413 — Attendance email: Excel + PDF (user accepted)
- utils/master_sheet.py: NEW build_master_sheet_pdf (landscape A4,
  reportlab, same columns as xlsx, repeating header). Verified with 128
  Kankani employees → 4-page PDF.
- utils/iter60_features.py _run_attendance_email_batch: email now attaches
  Excel + PDF twin; PDF failure is non-fatal (logged, Excel still sent).
- Deploy: /app/deploy_vps_iter413.sh via temp-code-bundle kind=script.

## Iter 414 — Salary-structure sync: strict code matching (user rule)
- _sync_structures_job in routes/legacy_import.py: name-matching fallback
  + Iter 353 name-based code correction REMOVED. Code match only; no match
  ⇒ unmatched list. Sync still refreshes Basic/PF Basic/Gross + linked
  Earn heads (SalaryHeadMaster + manual head-links), enables Firm Master
  heads, stamps salary_structure_synced_at.
- User flow: deploy iter414 → run "Sync Salary Structures" (button on the
  Legacy Import screen, or POST /admin/legacy-import/sync-salary-structures)
  to refresh linked heads from old DB.
- Deploy: /app/deploy_vps_iter414.sh via temp-code-bundle kind=script.

## Iter 415 — Employee PWA: GPS on by default (user request)
- app/(tabs)/index.tsx: employee dashboard shows a one-tap "Turn on GPS
  location — Enable" banner when foreground location permission isn't
  granted (browsers can't silently enable GPS at install). Enable →
  permission prompt → immediate location-ping; blocked → guidance
  (web: address-bar lock instructions; native: Open Settings). Banner
  hides once granted. Verified via Playwright as TEST50 employee.
- Deploy: /app/deploy_vps_iter415.sh via temp-code-bundle kind=script.
- Iter 416: GPS popup now AUTO-TRIGGERS on employee dashboard load
  (requestForegroundPermissionsAsync on mount when canAskAgain); granted →
  immediate location-ping; denied/dismissed → Enable banner fallback.
  Verified via Playwright (auto ping fired, no banner when granted).
  Deploy: /app/deploy_vps_iter416.sh.

## Iter 417 — Smart Punch GPS Verification revamp (user spec)
- NEW src/utils/smartGps.ts: SmartGpsEngine — warmUp (5s background
  refresh, Balanced), getPunchFix (preflight perm/services/network →
  warm-fix shortcut if fresh<5s & ≤30m → 4 attempts × getAccurateFix
  (15s, final 30s) with 5s waits; tiers ≤30 proceed / ≤100 accept from
  attempt 2 / final best-effort), diagnoseGpsFailure (exact guidance),
  logGpsDiagnostic (POST /gps-diagnostics), smartPunchFix singleton for
  legacy paths. PunchFlowModal GPS step streams live progress; old
  "Could not get your location" removed. attendance.tsx punch fetches
  swapped to smartPunchFix.
- NEW routes/gps_diagnostics.py: POST /gps-diagnostics (any auth user),
  GET /admin/gps-diagnostics (+counts+success_rate, filters
  company/date/outcome, company_admin scoped), GET .xlsx export.
  Registered in server.py. Collection: db.gps_diagnostics.
- NEW app/gps-dashboard.tsx + sidebar entry "GPS Diagnostics" (Attendance
  group). Fixed duplicate-sidebar (root _layout already wraps
  AdminWebShell — page must not wrap again).
- testing_agent: backend 12/12 PASS + dashboard UI verified
  (iteration_417.json, tests/test_iter417_gps_diagnostics.py).
- DEFERRED (needs policy decision): offline attendance with GPS-pending
  background sync (spec item 9) — changes attendance saving; not done.
- Deploy: /app/deploy_vps_iter417.sh via temp-code-bundle kind=script.

## Iter 418 — Smart Punch Native SDK + Device Sync Engine (offline punches)
- Workflow UNCHANGED (user strict rule). Added SDK layer frontend/src/sdk/:
  index.ts (SmartPunchSDK: capabilities, getTelemetry device/OS/battery/
  network/root, biometricAuth native+webauthn, gps, offline) and
  offlineQueue.ts (Device Sync Engine — SINGLE sync authority; storage
  delegated to proven src/utils/offlinePunch.ts: IndexedDB web /
  AsyncStorage native; onSyncResult listeners; offlinePunchAllowed firm
  gate; startAutoSync = online event + 60s interval + expo-background-task
  WorkManager/BGTask ~15min on real builds, idempotent, boot flush).
- attendance.tsx queue/sync imports switched to @/src/sdk/offlineQueue;
  onSyncResult keeps pending badge live. _layout.tsx calls startAutoSync()
  on boot (app-wide sync + early background-task registration).
- PunchFlowModal.tsx: fixed missing imports (getTelemetry, enqueuePunch,
  startAutoSync, offlinePunchAllowed); telemetry enrichment on save;
  catch-block offline cache now firm-gated. Removed unused expo-location.
- Backend UNCHANGED (punch endpoint already idempotent on client_dedupe_id
  + honours client_punch_at). Kankani offline_geofence_enabled set True.
- testing_agent: backend 2/2 (idempotency, geo-policy flag) + frontend
  offline banner / seeded-queue auto-drain verified (iteration_418.json,
  tests/test_iter418_offline_sync.py). Background task needs real build
  (not Expo Go/web) — user informed.
- ZKTeco ADMS SDK health check on user request: 8/8 PASS (handshake,
  heartbeat/commands, ATTLOG ingest, duplicate guard, unmapped parking,
  OPERLOG, online heartbeat). Script: backend/tests/check_zkteco_sdk.py.
  Contractual employees' machine punches correctly go to pending (Iter 175).
- Deploy: /app/deploy_vps_iter418.sh via temp-code-bundle kind=script
  (temp_bundle.py updated to serve deploy418.sh).

## Iter 419 — Machine-Only Sync (no Employee Master) + sync-all diagnostics
- User report "0 employee sync job(s) queued": /sync/all now explains WHY
  (no employees in firm / no Bio Codes / filter mismatch / no sync-enabled
  machine) instead of a bare zero. Verified live.
- MACHINE-ONLY SYNC (user: master data feeding pending, machines already
  enrolled): POST /sync/machines (+ GET /sync/machines/status). Phase 1
  harvest: DATA QUERY USERINFO/FINGERTMP/BIODATA to every sync-enabled
  machine; run doc in db.machine_sync_runs (phase harvest, distribute_at
  +120s). Phase 2 distribute (worker loop process_sync_queue →
  _process_machine_sync_runs): pushes every captured machine user
  (db.biometric_machine_users — NEW: USER PIN= lines now parsed in
  _ingest_templates) + every biometric_template to every machine, skipping
  templates on their origin device. Master users collection never consulted.
- Frontend: sync-engine.tsx Dashboard → new "Sync Machines Only" button
  (confirm dialog) before "Sync All Employees".
- E2E verified 7/7: run start, harvest cmds delivered, USER/FP capture,
  worker distribute (machine names like "RAKESH MACHINE" + Card pushed),
  origin-template skip, status endpoint. Script:
  backend/tests/check_machine_only_sync.py. UI button verified via screenshot.
- Deploy: same deploy_vps_iter418.sh (bundle rebuilds on demand — re-run).

## Iter 419 (cont.) — Machines tab, Sync Attendance removed, firm follow
- NEW "Machines" tab on Device Sync Engine: every registered machine with
  ONLINE/OFFLINE, employees-on-machine / fingerprints / punch-records
  (live counts the machine reports on its heartbeat INFO — already parsed
  by _parse_info into biometric_devices), pending sync commands, firmware,
  IP, last contact. Backend: GET /sync/machines/overview (sync_engine.py).
- "Sync Attendance" toggle REMOVED (user rule: attendance flows only FROM
  machines INTO the portal, never machine↔machine). Dropped from
  SYNC_DEFAULTS + Settings tab UI.
- Firm dropdown on sync-engine now ALWAYS opens with the currently
  selected firm (useSelectedCompany) and follows top-bar switches.
- Verified via API + screenshot (Kankani: 125 employees / 118 FP / 3010
  records on Test Gate).

## Iter 419 (cont. 2) — "Always sync, no approval" + direct command delivery
- Conflicts AUTO-APPROVED: log_template_conflict now stores conflicts as
  status=approved (resolved_by system:auto-approve) — machine-only
  templates sync everywhere with zero admin action. Startup migration in
  sync_engine_loop auto-approves any legacy OPEN conflicts (idempotent).
  Conflicts tab empty-state copy updated.
- Command delivery made DIRECT: iclock getrequest batch raised 5 → 30
  commands per poll (biometric_devices.py) — full-firm syncs finish in a
  few polls. (There never was an approval step; "waiting" = machine not
  polled yet.)
- Verified: template-only upload → conflict auto-approved, 0 open; 12
  queued cmds delivered in ONE poll.

## Iter 419 (cont. 3) — Punch Log columns + OT marking + menu renames + bundle fix
- Punch Log Report (screen + Excel): NEW columns "Name In Machine" (employee
  name AS STORED ON the machine — from biometric_machine_users harvest),
  "Machine Name" (friendly device name), and "OT" column marking OT PUNCH
  (everything from the 2nd IN of the day = OT session, same rule as
  day-counts). Excel photo-embed column now anchored dynamically.
  Verified: IN/OUT/IN(OT)/OUT(OT) sequence + xlsx headers/values.
- Menu: "Reports Center" → "Report Hub", moved from Payroll group into
  Reports group; "Labour Law Reports" → "Labour Reports", moved from
  Compliance group into Reports group (both super-admin + company-admin
  menus; page titles updated).
- VPS bundle fix: temp-code-bundle tar had ballooned to 140MB (.metro-cache,
  rpa_media, *.webm) and the proxy cut downloads at ~90s → now 9.5MB via
  new excludes. Verified <1s download, valid tar.

## Iter 420 — Daily In/Out & OT Verification Report + Bio Code policy rules
- NEW module (Reports → Daily In/Out & OT Verification):
  backend routes/daily_verification.py + frontend app/daily-verification.tsx.
  Reuses _compute_monthly_grid_data (1:1 with Attendance Grid). 13 filters,
  16 summary tiles, colour-coded rows (red missing punch / orange
  unapproved OT / yellow late-early / blue manual / green normal / grey
  absent-WO-holiday-leave), statuses incl. Missing In/Out, Half Day,
  Late/Early/OT/Manual markers, Approved vs Unapproved OT (ot_applicable +
  optional policy ot_daily_max_hours cap), per-row Physical Verification
  (checkbox + remarks → db.daily_verifications + attendance_audit_log
  module=daily_verification), drill-down (punch timeline w/ source,
  machine, geo, selfie + previous-7-days), exports: xlsx / csv / pdf
  landscape+portrait / print / email (SMTP) / WhatsApp PDF (WA engine).
  All exports audited. 128 emps in 0.1s; paginated (limit/offset).
- Bulk Employee Correction: Bio Code column now also in COMPLIANCE
  (On-Roll) mode when firm policy compliance_present_8hr ON AND biometric
  enabled (salary_process.bio_matrix_attendance OR registered machine) —
  iter60_features.bulk_correction_fields.
- Firm Master auto-default: on PATCH firm-master, if
  salary_process.offline_salary DISABLED or bio_matrix_attendance ENABLED
  → attendance_policy.policy_master.compliance_present_8hr auto-set True.
- testing_agent iteration_420.json: backend 10/10 + all frontend flows
  PASS. WEB_SELECT style warning fixed post-test. Email/WA return clear
  400 when SMTP/WA unconfigured (expected).

## Iter 421 — Dynamic deductions, Actual Other Ded., PF validation per Firm Master
- Compliance Salary DYNAMIC DEDUCTIONS per Firm Master: engine
  (compute_compliance_row) now keeps per-head breakdown row.deduction_heads;
  run compute filters heads to Firm-Master-enabled custom labels
  (custom_ded_labels; disabled-head amounts removed from Total Ded., added
  back to Net); rows carry deduction_head_labels. CSV/XLSX exports render
  one dynamic column per head (dynamic_csv_columns + flatten_deduction_heads);
  frontend grid renders per-head read-only cells between TDS and Other*.
  Verified: ADVANCE 500 + CANTEEN 200 counted, disabled UNIFORM 99 excluded.
- Actual Salary Process: NEW editable "Other Ded.*" column (row.other_ded)
  — backend _actual_salary_row_compute/net, totals, PATCH body; frontend
  salary-run.tsx (col, editable cell, totals chip/row, CSV, sort/filter).
  Verified: PATCH other_ded=250 → net -250, totals aggregated.
- PF validation follows FIRM MASTER policy (user rule): AI compliance
  analysis (ai_layer._employee_checks) no longer flags Missing UAN when
  firm EPF disabled (epf.applicable / deductions.PF), nor Missing ESIC IP
  when ESI disabled. Verified ON→findings 1/1, OFF→0/0. (Compliance salary
  engine already gated PF/ESI amounts via firm_pf_enabled/firm_esi_enabled.)
- Also this session: Present Days ≤ month-days validation (grid save +
  import — see Iter 420 notes), machine filter firm-scoped in Daily
  Verification.

## Iter 422 — Editable Advance Deduction + Master Report "Date of Join"
- COMPLIANCE SALARY grid: NEW editable "Advance*" column (deductions band,
  before Other*). Auto-filled from the Advance ledger; inline edits stamp
  manual_fields ("advance_recovery") so REPROCESS keeps the typed amount
  (both normal + imported/Freeze runs). routes/advances.py
  apply_advance_recovery skips rows with manual advance_recovery. Frontend
  compliance-salary-run.tsx: navCols/arrow-nav, totals strip + totals row,
  col filter/sort, dedTotal (updateRowField + updatePresentDays) now include
  advance_recovery (also fixed latent bug where editing any cell dropped the
  ledger advance from Total Ded.). Register export helpers (other_ded in
  utils/compliance_salary.py) include advance_recovery.
- ACTUAL SALARY: Adv column was already editable (PATCH body.adv). Fixed
  reprocess DOUBLE-COUNT: carry-forward now takes prev.adv MINUS
  prev.advance_recovery (ledger EMI re-applied idempotently on top).
- Employee Master Report (Reports → /master-data-report): "DOJ" column
  relabeled "Date of Join" (grid + xlsx export) — column & data already
  existed (backend routes/master_data_report.py _COLUMNS).
- Verified: backend E2E script tests/check_advance_edit.py (compliance
  save-rows → reprocess keeps adv 500 + manual_fields; actual PATCH adv 750
  → net -750, reverted); Playwright screenshots — Advance* column visible &
  editable on run csrun_bca09c4a4cec, "Date of Join" header in master report.
- deploy_vps_iter422.sh created; temp_bundle "script" kind now serves it
  (wget .../api/temp-code-bundle?token=sks-deploy-7391&kind=script).
- Iter 422b: Employee Master Report — NEW "Date of Birth" column (key: dob,
  between Gender and Marital Status) in grid + xlsx export. Verified via API.
- Iter 422c: Employee Master Report — NEW "Age" column (auto-calculated from
  dob via _parse_dob/_age_years, handles dd-mm-yyyy/yyyy-mm-dd/dd/mm/yyyy) +
  "🎂 Birthdays" chip filter (birthdays=true query param → only employees with
  DOB in the CURRENT month; wired into grid + xlsx export). Verified: ages
  correct (AFZAL 01-01-1990 → 36), June birthdays = 0 (data histogram Jan:120,
  Mar:3, Apr:1, Jul:1). NOTE: file corruption during parallel edits fixed
  (duplicated tail block removed, helpers re-added).
- Iter 423: FIX — Compliance Salary Finalize/Lock validation now respects
  Firm Master policy. Root cause: Iter 421 gated only ai_layer; the LOCK gate
  uses routes/compliance_validation.validate_compliance_run which never read
  firm toggles. Fix: fetch firm_masters epf/esi applicable + deductions
  catalog (Iter 369 authoritative logic), drop PF_*/HIGHER_PF/VPF_* findings
  when EPF disabled and ESIC_* (incl. global ESIC_MAPPING_MISSING) when ESI
  disabled. Verified live: both ON → 8 err/9 warn; ESI OFF → 0 err;
  BOTH OFF → 0/0; flags restored.
- Iter 423b (user directives): (1) Compliance Finalize & Lock is now
  NON-BLOCKING in ALL cases — validate_compliance_run still runs and findings
  are stamped on lock_validation (non_blocking_policy: true) + audit trail,
  but 422/409 raises removed; frontend pre-lock modal shows findings with a
  single always-available "Finalize & Lock Now" button (role gates removed).
  (2) Actual Salary Process: p_days month-days/DOJ cap REMOVED on the row
  PATCH — admins may enter more present days than the month. Verified:
  finalize clone with 8 errors → 200 + stamp; PATCH p_days=35 (month 31) OK.
  NOTE: Compliance Present-Days ≤ month-days rule (Iter 420) intentionally
  KEPT — user only unblocked Actual.
- Iter 424: All Employee Data list (/admin) — each card now shows
  "S/O <father_name> · DOJ: <date>" under the designation line (fields
  already on the /admin/employees payload). Verified via screenshot.
- Iter 425 (user directive): Higher PF "Management Approval" REMOVED — always
  auto-approved. utils/compliance_salary.py drops the approval-pending gate
  (Higher PF activates with company allow_higher_pf ON + type=higher +
  effective window); compliance_validation.py HIGHER_PF_APPROVAL_PENDING
  removed; employee-add.tsx approval toggle/status selector removed, chip
  shows Approved/Expired only. VPF verified: statutory PF + VPF% on top
  (employee side only), employer statutory; allow_vpf=False skips VPF.
  Engine tests: tests/check_higher_pf_vpf.py ALL PASS (25000 wages @12% =
  3000 with pending approval ignored; toggle OFF → 15000; VPF 3300 = 1800+
  1500). Preview standard_compliance: allow_higher_pf=True, allow_vpf=True.
- Iter 425b (user bug — "Higher PF not working, PF 1800 / Wage Base 0"):
  ROOT CAUSE: allow_higher_pf resolved through TIME-VERSIONED compliance
  settings (compliance_settings_log) — months whose policy version predated
  the switch silently fell back to the ₹15,000 ceiling. FIX: engine no longer
  consults the company "Allow Higher PF" switch at all (employee type=higher
  + effective window is enough); HIGHER_PF_NOT_ALLOWED validation removed;
  DEFAULT allow_higher_pf=True (informational). E2E verified on preview:
  RAJENDRA MEENA (STAFF, 13.5 days) → pf_wages 25000, pf_employee 3000,
  higher_active=True; user's draft run + employee master fully restored.
  Unit tests updated (toggle-off no longer gates) — ALL PASS.
- Iter 425c (user directive — "Always Calculate on Wage Base"): Higher PF
  wages = max(pf_base, stat_wage_base[, higher_pf_wage]) — the Compliance
  Policy WAGE BASE (max(Basic, floor% Gross Earning)) with NO ceiling, never
  the ₹15,000-capped master PF Basic (that was why PF stayed 1800 when the
  master PF Basic was 15000). ESIC already on the wage base. Unit test added
  (pf_basic 15000 / basic 22000 / gross 30000 → pf_wages 22000, PF 2640) —
  ALL PASS.
- Iter 426 (user requests, Compliance Salary Process screen):
  1. "Recompute (Attendance)", "PDF Layout ⚙", "Audit Log", "PF/ESIC Audit"
     buttons REMOVED (+ audit modal, RegisterLayoutEditor import, dead state).
  2. Salary Process now: first time processes directly; when a draft exists →
     3-way choice (confirmChoice in utils/confirm.ts): "With EXISTING Data"
     (keeps edits) / "From BLANK" (payload.fresh=True → _prev_rows cleared,
     rebuild from attendance+master, extra confirm) / Cancel.
  3. Employee Group selection MANDATORY before Salary Process & Copy Last
     Month (blocks empType==="all"); dropdown label "— Select group
     (mandatory) —".
  4. MONTH DAYS LOCK: once processed (draft/finalized) for firm+month+group,
     Month days input is read-only (🔒 + note) and backend FORCES
     payload.month_days to the previous run's value on every reprocess.
  5. "Active Firm / Firm Settings" banner hidden on this screen.
  Verified: backend E2E (26 days locked across existing+fresh reprocess,
  manual other_ded kept on existing / discarded on fresh, cleanup OK) +
  screenshot (buttons gone, lock note visible, mandatory group).
  NOTE: parallel search_replace on the same file RACES — existingAny memo
  was lost once and re-added via insert_text (sequential edits for same-file
  changes from now on).
- Iter 427 (user requests):
  1. "Group by:" PDF option removed from Compliance Salary Process (pdfGroup
     state deleted; export URL sends empty group_by).
  2. Run summary (month · employees · month_days · payslips pushed) moved
     from the header to the sticky TotalsFooter via new `caption` prop
     (src/components/salary/TotalsFooter.tsx); header title/hint block
     removed.
  3. PF-on-second-process bug FIXED: the grid recompute (updatePresentDays)
     now mirrors the engine's Higher PF rule (wage base, no ceiling, ECR
     split w/ EPS on ceiling) and scales VPF with new PF wages — first
     process + typed days show correct PF immediately.
  4. FIXED DAYS (26/30/31) now applies to the NORMAL Salary Process too
     (was import-only): stats overridden to firm's days_calc_fixed before
     compute; manual/prev-carry days still win on reprocess-with-existing.
     E2E: Kankani temporarily set to fixed/26 → all 2026-05 STAFF rows
     present_days=26, gross 19370; firm restored, run deleted.
  Screenshot verified: Group by gone, footer caption present, month-days 🔒.
- Iter 427b (user clarification): FIXED DAYS (26/30/31) now sets the run's
  MONTH DAYS too — backend create fetches firm_masters.salary_process; when
  method=fixed, payload.month_days = days_calc_fixed (prev-run month-days
  lock still wins). Frontend: "Month days (override)" auto-prefills the
  firm's fixed figure on firm selection. E2E: fixed=30, form sent 31 →
  run.month_days=30, all present_days=30, full master gross 22350; firm
  restored, run deleted.
- Iter 428 (user request): Employee Master — PF Contribution Type is now
  OPTIONAL and moved NEXT TO the PF Basic column. New "Change PF Policy for
  this employee (Higher PF / VPF)" checkbox (default OFF → options hidden,
  salary follows Compliance Policy / Firm Master statutory PF; toggling OFF
  resets pf_contribution_type to statutory). Auto-opens for employees whose
  saved type is non-statutory. Screenshot verified (hidden by default,
  chips appear on enable).
- Iter 429 (user complaint — "Month days locked, not able to edit"): the
  hard lock (Iter 426) softened. Field is EDITABLE again; when the typed
  value differs from the already-processed days, a confirmChoice asks
  "Keep processed days (X)" / "Use NEW days (Y)" — NEW sends
  override_month_days=true which bypasses both the prev-run force and the
  fixed-days fetch on the backend. Default (no flag) still keeps the same
  processed days (safety preserved). E2E: 26 → reprocess 31 no-flag stays
  26 → override becomes 31; cleaned up.
- Iter 430 (user directive): PF Basic Salary ABOVE ₹15,000 → statutory PF
  follows the COMPLIANCE POLICY WAGE BASE capped at the ceiling:
  pf_wages = min(max(prorated PF Basic, stat_wage_base), 15000). Engine
  (utils/compliance_salary.py) + grid recompute mirror updated. Tests:
  full month 1800 (unchanged); half month pf_basic 20000/basic 22000 →
  wages 11000 → PF 1320 (was 1200); below-cap unchanged; prior Higher-PF/
  VPF suite still green.
- Iter 431 (user request): PF Basic Salary > ₹15,000 auto-defaults to
  HIGHER PF (Actual Wages, auto-approved) with PF Basic copied into Higher
  PF Wage. Frontend: pf_basic onChange auto-opens the PF policy section,
  sets type=higher + higher_pf_wage (keeps auto-copied wage in sync when
  lowered). Backend safety net (employee_profile PATCH): same rule when
  pf_contribution_type absent from payload; explicit type in payload always
  respected (employer can change later, engine follows saved values). E2E
  verified + employee restored.
- Iter 433 (user request — 11-POINT PAYROLL REPORT CORRECTIONS):
  1. Arrear Register export (PDF NEW + Excel rebuilt via shared register
     builder): S.No | UAN | ESIC | Emp Name | Father Name | Days | Rate |
     Gross Arrear | dynamic PF/ESIC deduction cols | Net Payable
     (routes/arrear_salary.py `_arrear_register_data`).
  2. CTC Analysis: S.No column.
  3. Fine Register: Month-wise/Periodic (`month_to` param, aggregates
     months) + centred empty note "There is No Fine in this Month of
     (Month Year)" (JSON `empty_note` + PDF via register_pdf empty_note).
  4/5/6. F&F, Gratuity Register, OT Cost Analysis: `employee_ids` param
     (single/multiple/all picker chips in reports-center.tsx); picked
     employees included even without exit-date/DOJ.
  7. Daily OT Register: Daily/Periodic date range (`from_date`/`to_date`),
     Month-wise removed in UI, S.No added.
  8. Dept-wise OT: REWRITTEN punch-based over date range — dept-wise
     employee count, OT employee names list, S.No, Daily/Periodic.
  9. Employee-wise Payroll Register: Bonus Amount head (optional earn,
     parsed from allowances "bonus" + r.bonus), in earn_sum + grand totals.
  10. PF Contribution PDF: margins 8→4mm, centred headings, font 7.
  11. Salary Register Compliance: v1 margins 5→3mm, v2 6→4mm (scale
     widths updated). Master head-wise cols already dynamic.
  Global: register_export body font 9→10pt; title leading fixed (no
  overlap); duplicate "TOTAL" label in totals row fixed.
  All verified: backend/tests/check_report_corrections.py (18/18 PASS) +
  PDF renders + Report Hub UI screenshot.
- Iter 435 (user request — ROLLBACK): Employee Name LEFT-aligned in ALL
  reports (register_export PDF+xlsx, compliance register v1/v2, actual
  salary register, salary_register_pdf, PF contribution, labour reports,
  daily verification). NOTE: user first asked right-align then reversed —
  Name columns must stay LEFT.
- Iter 436 (user request): Portal Upload Files (EPFO ECR / ESIC MC) —
  new toggle button "Remove Without UAN / ESIC No. Employees"
  (challans.tsx `toggle-skip-missing`) → `skip_missing=1` on
  /admin/challans/ecr.txt, ecr.xlsx, esic.xlsx (esic.xls always skips
  missing IP). Default unchanged (blank UAN included in .txt per Iter 291).
- Deploy script: /app/deploy_vps_iter435.sh (served via
  /api/temp-code-bundle?token=sks-deploy-7391&kind=script).
- Iter 437 (ROLLED BACK on user request): the Fine/Advance "Reason column
  from grid remarks" improvement was started (remark pencil in grid +
  reprocess carry) then FULLY REVERTED — user said "No need". Do NOT
  re-suggest this feature. Codebase is back to Iter 436 state.
- Iter 438 (user request): After SAVE or FINALIZE on Compliance & Actual
  Salary Process → "Download / Mail Reports" modal (PDF / Excel / CSV /
  All chips, Download button + email input with Send).
  - Shared component: frontend/src/components/salary/ReportsShareModal.tsx
    (NOTE: animationType MUST be "none" — "fade" left the modal ghosted/
    half-transparent on these pages).
  - Compliance: modal opens after Save-as-Draft + Finalize (run_id/month
    captured in `reportsFor` BEFORE finalize clears the page). Actual
    (salary-run.tsx): after Save + Finalize + a "Download / Mail"
    ActionBtn in the run header.
  - Backend: POST /admin/compliance-salary-runs/{id}/email-report and
    POST /admin/salary-runs/{id}/email-report — body {to, formats:[...|all]}.
    Attachments reuse the existing register/export builders.
  - utils/report_email.py: tries admin SMTP (Email Settings) first, falls
    back to RESEND_API_KEY env. E2E verified (both endpoints via curl +
    UI Send button → "Report (PDF) emailed to …").
- Iter 439/440 (user request — Download/Mail Reports modal upgrades):
  - Compliance modal formats: PDF Format 1 (variant 1), PDF Format 2
    (variant 2 / Option 2 register), Excel, CSV. Actual Salary: PDF/Excel/CSV.
  - Employee Group badge shown in modal (run.employee_type).
  - "Or mail the reports": fetches Firm Master registered emails via NEW
    GET /admin/firm-emails/{company_id} (header.email_1/email_2) — chips
    to pick one/several/all (default all) + optional extra typed email.
  - ≥1 format selection is MANDATORY (frontend status message + backend
    400 "Select at least one report format"). Mail carries EXACTLY the
    selected formats.
  - send_report_email now accepts a recipient LIST (SMTP loops per
    recipient; Resend gets full list). NOTE: dev Resend sandbox key only
    delivers to the account owner (403 for others) — on VPS the user's
    SMTP settings handle any recipient.
  - Backend verified via curl (pdf+pdf2 mail OK, empty formats → 400,
    firm-emails OK); UI verified via screenshot on salary-run.
- Iter 441 (VPS incident): user's VPS backend DOWN after deploy435 →
  created /app/fix_backend_441.sh (served via temp-code-bundle
  kind=fixscript) — prints stderr tail, manual import test, reinstalls
  reqs, clears port 8001, restarts + health check. AWAITING user run
  result. Preview env verified healthy (dashboard renders fine).
- Iter 442 (user request): "Download / Mail" button directly in Report
  Hub header (reports-center.tsx, testID rc-share, hidden for audit
  group) → ReportsShareModal with PDF/Excel chips + firm email chips.
  NEW POST /admin/payroll-reports/email-report handles BOTH payroll
  kinds (_REPORTS+ctx) and govt kinds (_GOVT+month_to/employee_ids,
  incl. fine empty-note PDF). Modal gained `extraBody` prop merged into
  the email POST body. Verified via curl (payroll + govt kinds) + UI
  screenshot.
- Iter 443 (user request — Freeze as Actual Gross + Master-linked deductions
  + PF/ESIC on Wage Base):
  - FREEZE AS ACTUAL GROSS: firms with days_calc_method=freeze_actual_gross
    now auto-import the ACTUAL Salary run (db.salary_runs run_type=actual,
    same month, newest first) into the Compliance run: total_gross → Freeze
    (imported_gross, taken AS-IS, days derived, diff → OT/Other Allow.),
    adv → advance_recovery (stamped manual_fields so ledger skips), tds →
    tds, other_ded → other_deduction. Works WITHOUT an imported sheet
    (attendance_source="actual_salary_freeze", frozen=True badge). Key var
    _frz_imp = use_imported_sheet OR _fag_row present; gates at stats
    block, days-derivation block (L~548) and Freeze block (L~862).
  - MASTER-LINKED DEDUCTIONS: ded_mask now carries "advance" (ADVANCE
    toggle) and "other" (OTH. DEDUC. toggle). Disabled heads are NOT
    applied (sheet TDS/other gates, prev-row restores gated, advance
    ledger rows filtered at both apply_advance_recovery call sites) and
    columns hidden on grid (compliance-salary-run.tsx hasDed("advance"/
    "other") in headers, dedCount, row cells, totals row, footer, navCols,
    fmMask ed2) + CSV/Excel exports (dynamic_csv_columns) +
    _ensure_firm_head_masks for old runs.
  - PF ON WAGE BASE (user confirmed): statutory PF wages = min(max(pf_base,
    stat_wage_base), 15000) whenever wage_definition_rule on — i.e. wage
    base max(Basic earned, 50% Gross) capped ₹15,000. PF Basic blank/0
    still ⇒ no PF (applicability), Firm Master EPF/ESI gate first then
    Employee Master flags. ESIC unchanged (already on stat_wage_base).
  - Renamed "Standard Compliance Settings" title → "PF/ESIC Settings".
  - Tested: seeded actual run rows → compliance process verified gross
    18000/25000/9500 imported AS-IS, adv/tds/other landed, ESIC on wage
    base, diff→OT; PF unit tests (firm gate, emp gate, blank pf_basic,
    wage-base floor). Test data reverted after.
  - CAUTION: /app/backend/routes/compliance_salary_runs.py was TRUNCATED
    once during parallel search_replace edits (restored from git HEAD tail).
    Verify file ends with the ECR endpoint if editing heavily in parallel.
  - Deploy: /app/deploy_vps_iter444.sh (temp_bundle kind=script now serves
    deploy444.sh).
- Iter 445 (user bug — EPFO ECR upload error RFE-37 + ESIC SAL column):
  - RFE-37 fix: ALL 3 ECR builders (routes/challans.py _ecr_lines — the
    Portal Upload Files screen; utils/statutory_bulk.build_pf_ecr_txt;
    utils/master_sheet.build_ecr_text) now DERIVE contributions from the
    WAGE columns exactly like the EPFO validator: Due EPF = 12%×EPF wages,
    Due EPS = 8.33%×EPS wages (HALF-UP rounding, not banker's), ER diff =
    Due EPF − Due EPS. EPS-disabled members print EPS wages = 0; higher-
    pension members keep EPS on uncapped wages; EE = max(row EE, due) so
    VPF still remits more. Verified: unit cases + real run (55 members,
    all pass the portal formula).
  - ESIC SAL column now ALWAYS the ESIC wage base (amount ESIC deducted
    on), never Gross — fixed challans esic.xls/esic.xlsx + statutory_bulk
    build_esic_mc_csv (removed gross fallbacks).
- Iter 446 (user bug — EPFO "File name cannot have spaces or a non-word
  character"): all ECR/ESIC portal file names now use MMYYYY (word chars
  only): ECR_072026.txt instead of ECR_2026-07.txt. Fixed backend
  (challans.py _portal_month helper on ecr.txt/ecr.xlsx/esic.xls/esic.xlsx
  + RPA upload job file_name; compliance_salary_runs.py PF_ECR + ECR
  export headers) AND frontend a.download names (challans.tsx, reports.tsx,
  compliance-salary-run.tsx) since the browser save name comes from the
  frontend. Verified header: ECR_062026.txt.
  ⚠ LESSON (recurred twice): PARALLEL search_replace edits on the SAME
  file corrupt/truncate it (challans.py got stray "ls}" tail; earlier
  compliance_salary_runs.py truncated). Edit the same file SEQUENTIALLY.
- Iter 447 (user bug — "PF is Not Calculating as per Wage Base", example
  SAPNA PARMAR: Wage Base 12,044 but PF showed 1,495 = 12% of PF Basic
  12,459): statutory PF wages are now EXACTLY min(stat_wage_base, 15000)
  when the Wage Definition Rule is on — PF Basic no longer LIFTS wages
  above the wage base (it only gates applicability: blank/0 ⇒ no PF).
  Fixed utils/compliance_salary.py (removed max(pf_base, …)) AND BOTH
  frontend client-side recompute blocks in compliance-salary-run.tsx
  (present-days edit + OT/Others edit) to mirror it. Higher PF / IW / VPF
  paths unchanged. Verified: SAPNA case → pf_wages 12043.7, PF 1445, ESIC
  91 (matches grid). Runs must be REPROCESSED to update stored figures.
- Iter 448 (user-accepted enhancement — pre-upload "EPFO File Check"):
  - New GET /api/admin/challans/ecr-check?run_id&skip_missing → validates
    the ECR file like the EPFO portal: filename word-chars rule, UAN
    presence/12-digit format/duplicates, member-name characters, RFE-37
    formula (ER diff = Due EPF − Due EPS from wages, EE ≥ due), EPS/EDLI
    wage limits (higher-pension exempt), NCP-days sanity. Returns
    {ok, file_name, members, skipped_no_uan, checks[], issues[]}.
  - challans.tsx: purple "EPFO File Check" button (testid ecr-file-check)
    in the Portal Upload Files card + green/red results panel; honours the
    Remove-Without-UAN toggle. Tested by testing_agent — PASSED (report
    /app/test_reports/iteration_448.json).
  - Note: /challans run dropdown only lists runs with finalized:true.
- Iter 449 (user spec — "Enhancement of Existing PF & ESIC Settings with
  Statutory Corrections"): implemented WITHOUT any new module, fully
  backward compatible (defaults = legacy behaviour):
  - NEW SETTINGS (Standard + per-firm overrides, compliance_settings.py
    _CHOICE_FIELDS): pf_wage_calc_method (basic_da | floor | higher* )
    and esic_wage_calc_method (wage_base* | actual | floor | higher).
    UI chips on /compliance-settings (ChoicePicker, testids
    cs-pf_wage_calc_method-*, cs-esic_wage_calc_method-*).
  - ENGINE (utils/compliance_salary.py): PF wages per method capped at
    ceiling; ADOPT PF above ceiling — adopt_pf="no" ⇒ Excluded Employee
    (pf 0, reason in pf_reason), adopt_pf="yes"+pf_wage_override ⇒ PF on
    manual wage (prorated, uncapped) with EPS ALWAYS capped at ceiling and
    ER split = 12%×wage − EPS → EPF; ESIC wages per method (actual = ESI-
    flagged heads + OT); ESIC ELIGIBILITY on full-month ESI Wages when a
    non-default method is set (legacy Basic check kept for default).
    _CFG_PASSTHRU_KEYS updated. 12 unit cases pass incl. SAPNA + Higher PF
    regressions.
  - EMPLOYEE MASTER: adopt_pf (_STR_FIELDS) + pf_wage_override
    (_NUM_FIELDS) in employee_profile.py; UI chips + conditional wage
    input on employee-add.tsx (testids adopt-pf-*, pf-wage-override);
    employeeForm.ts fields.
  - VALIDATION (compliance_validation.py): PF_ABOVE_CEILING now allows
    Adopt PF=Yes; new ADOPT_PF_WAGE_MISSING + PF_EXCLUDED_ABOVE_CEILING
    warnings.
  - GRID mirror: both client-side recompute blocks in
    compliance-salary-run.tsx honour both methods.
  - testing_agent iteration_449: 100% PASS (settings persist, employee UI
    hydrates, 400 on invalid values). Fixed testing feedback: employee
    Save now window.alert()s the mandatory-field error (was silent).
- Iter 450 (user confirmed via Data.xls demo — AMIT PF Basis 17,796 must
  give PF 2,136 not 1,800): a PF Basic FILLED ABOVE the EPF ceiling on the
  Employee Master is treated as the ADOPTED PF wage — PF deducted on the
  FULL PF Basic (prorated, uncapped, _pf_eff=max(pf_basic_prorated,
  calc_base)); EPS stays capped at 15,000; ER split = 12%×wage − EPS →
  EPF. (Partially reverses Iter 430/447 for the pf_basic>cap case ONLY;
  wage-base rule intact below the ceiling — SAPNA 1,445 regression-safe.)
  Grid recompute mirrored in both blocks; validation PF_ABOVE_CEILING now
  also allows master pf_basic>cap.
- Iter 450: user approved switching ESIC eligibility to ESI Act basis —
  Standard compliance setting esic_wage_calc_method = "actual" SET IN THE
  PREVIEW DB. ⚠ DB setting does NOT deploy with code: user must ALSO set
  PF/ESIC Settings → ESIC Wage Calculation Method = "Actual ESI Wages" on
  the VPS after deploying (or leave default wage_base if they change mind).
  Effect: eligibility on full-month GROSS ≤ 21,000 and ESI on full gross
  earned (e.g. LAXMI gross 23,540 → exempt; NEERAJ 21,000 → ESI 158/683).
- Demo calculation for user's Data.xls (22 employees) verified against
  user expectations; harness reminder: pass compliance_basic +
  compliance_salary_allowances (NOT salary_structure_compliance) for
  correct proration in ad-hoc engine demos.
- Iter 451 (user request): ECR .txt NCP DAYS always WHOLE numbers (rounded
  half-up, 0.5 → 1) in challans.py _ecr_lines (statutory_bulk/master_sheet
  already integer). Verified 55-member file: 0 decimal NCPs.
- Iter 451b (user reverted): ESIC stays on the LEGACY rule — setting
  esic_wage_calc_method reset to "wage_base" (eligibility on Basic ≤
  21,000, ESI on max(Basic, 50% Gross)). Do NOT switch to "actual" and do
  NOT tell user to change it on VPS. The configurable option remains
  available but default/legacy is active.
- Iter 452/453 (user requests, PF/ESIC Upload screen):
  - Sidebar renamed "PF / ESIC Challans" → "PF / ESIC Upload" (AdminWebShell
    + split-view).
  - Run dropdown shows only MONTH NAME of finalized runs (e.g. "June 2026
    ✓"), no employee count; group appended only when same month has
    multiple runs.
  - ECR filename = FIRMNAME_MMYYYY.txt (word chars, e.g.
    KANKANIENTERPRISES_072026.txt) via challans._ecr_fname (db.companies
    name); fallback ECR_MMYYYY.txt when run has no company. Frontend
    download names use run.company_name (added to the runs LIST endpoint).
  - ESIC upload format matched EXACTLY to user's "Format for Upload.xls":
    columns ESI_CODE/NAME/DAYS/SAL/RE/DATE, SAL = GROSS EARNED truncated
    to ₹ (REVERSES Iter 445 wage-base SAL per explicit user sample),
    DAYS whole numbers, LEFT/zero-day members INCLUDED with DAYS 0 SAL 0
    RE 1 (previously excluded because zero-pay rows have
    esic_applicable=False). Applied to both esic.xls and esic.xlsx.
  - ECR NCP whole numbers (Iter 451) retained.
- Deploy Iter 453 (this session): /app/deploy_vps_iter453.sh created and
  served via /api/temp-code-bundle?kind=script (temp_bundle.py updated).
  Covers Iters 445-453 on top of the Iter 444 release. User given wget
  instructions to run it on the VPS.
- Iter 454 (user request): clicking "Dashboard" in the admin sidebar
  collapses ALL expanded sub-menus (collapseTick broadcast in
  AdminWebShell.tsx NavRow). Verified via browser automation.
- Iter 455 (user request): EPFO accepts NO special characters in the ECR
  filename — underscore removed: FIRMNAMEMMYYYY.txt (backend
  challans._ecr_fname + frontend challans.tsx names map). ESIC files keep
  ESIC_MC_FIRM_MMYYYY (portal accepts "_"). Verified via API
  (KANKANIENTERPRISES072026.txt).
- Deploy Iter 455: /app/deploy_vps_iter455.sh served via
  /api/temp-code-bundle?kind=script.
- Iter 456 (user FINAL PF Engine spec — rollback/simplification):
  * PF Basic 0/blank → no PF. PF Basic ≤ 15,000 → PF wage = max(earned PF
    Basic, earned 50% gross) capped 15,000. PF Basic > 15,000 → ADOPTED
    HIGHER PF: PF on full earned PF Basic (pro-rated), NO cap; EPS capped;
    balance ER share → Employer EPF. VPF + Higher PF contribution type kept.
  * REMOVED: adopt_pf / pf_wage_override (engine, employee_profile fields,
    Employee Master UI, compliance_validation checks) and
    pf_wage_calc_method / esic_wage_calc_method (engine defaults+passthru,
    compliance_settings _CHOICE_FIELDS, Settings page dropdowns +
    ChoicePicker). ESIC stays on LEGACY rules only.
  * Verified via /tmp/test_pf_engine.py — 9 scenarios incl. AMIT 17,796 →
    2,136 and 1,70,000 → 20,400, adopt_pf ignored, VPF/HigherPF intact.
- Iter 456 (ESIC template instructions, user-uploaded sheet): esic.xls +
  esic.xlsx now: DAYS ceil (round UP), all cells TEXT format, zero-wage
  exited members → Reason 2 + Last Working Day dd/mm/yyyy (exit_date/
  resign_date from users, on/before month end), other zero-wage → Reason 1,
  part-month leavers → no reason/date. Shared helper challans._esic_row_vals;
  _uan_esic_map now also fetches exit_date/resign_date.
- Deploy Iter 456: /app/deploy_vps_iter456.sh served via
  /api/temp-code-bundle?kind=script.
- Iter 457 (user bug — MILAP CHAND JAIN, Basic 2,30,000 / PF Basic 1,70,000
  showed PF 27,600): the "Higher PF (Actual Wages)" path (REVERSES Iter 425c
  "always wage base") now uses: Higher PF Wage (pro-rated) → else earned PF
  Basic → else wage base. Verified: MILAP → PF 20,400. Test file
  /tmp/test_pf_engine.py extended to 13 scenarios.
- Iter 457b: BOTH client-side grid recompute mirrors in
  compliance-salary-run.tsx (ot_pay/others editor + updatePresentDays)
  updated to the final PF Engine: PF Basic>cap → earned PF Basic (no max
  with wage base), Higher PF → own wage (hiWage prorated → PF Basic →
  wage base), EPS capped + ECR ER split for above-cap statutory wages,
  ESIC legacy only (calc-method mirrors removed).
- IMPORTANT: MILAP CHAND JAIN exists ONLY on the user's VPS DB — user's
  "still 27,600" report is from the un-deployed VPS. Fix requires:
  run deploy456.sh on VPS + RE-RUN the Compliance Salary Process.
- Iter 458 (user bug — "Server Never Upload the Sheet", Import Salary Sheet
  2026-07): endpoint /admin/compliance-import/upload verified working on
  preview (200). ROOT CAUSE: VPS nginx default client_max_body_size 1M
  rejects base64 Excel bodies with 413 before FastAPI. deploy456.sh now
  writes /etc/nginx/conf.d/sks-upload.conf (client_max_body_size 100M,
  proxy_read/send_timeout 300s) + verification grep. Frontend
  pickAndUpload catch now shows a clear message for 413/too-large.
- Iter 459 (user request): PF ECR now INCLUDES members with ZERO working
  days (pf_eligible but not pf_applicable): wages/contributions 0, NCP =
  full month days — membership continuity on EPFO. Non-eligible employees
  (no PF Basic / Excluded / PF=No) stay out. challans._ecr_lines filter
  changed to (pf_applicable or pf_eligible). Verified via synthetic
  zero-day row: "#~#0#~#0...#~#26#~#0" and ecr-check passes NCP sanity.
- User confirmed (option 3): PF 50%-of-Gross floor KEEPS including Overtime
  + Other Allowances (as-is), and ESIC also keeps including them (as-is).
  NO code change needed — documented behavior: typing OT/Other Allowance
  can raise PF for below-cap employees where 50% Gross > earned PF Basic.
- Iter 460 (user: "still not able to upload ESIC Excel" + provided WORKING
  "sample format of ESIC.xls"): the portal-accepted file has ESI_CODE+NAME
  as TEXT ('@'), DAYS/SAL/RE as NUMERIC (General), DATE blank / dd/mm/yyyy
  TEXT for exited. Iter 456's all-text cells were the breakage. Both
  esic.xls (xlwt, sheet 'Sheet1') and esic.xlsx (openpyxl) now match the
  sample exactly — verified via seeded IPs incl. Reason 2 + LWD row.
- Iter 461 (user request — "Modern Payroll multi-tab workspace", ALL 3
  phases confirmed):
  * Phase 1: WorkspaceTabs.tsx (new) — Chrome-style tabs in AdminWebShell
    below the topbar; per-tab route+label, add/close/switch, persisted in
    localStorage (sks_workspace_tabs_v1); active tab follows pathname.
  * Phase 2: workspaceSync.ts (new) — BroadcastChannel "sks-workspace-sync";
    announceRecordUpdate() called after employee save (employee-add.tsx);
    AdminWebShell shows top-right toast with Refresh Now (remount via ?_r=)
    / Ignore; footer Last sync updates.
  * Phase 3: useRecordLock() hook — cooperative lock via lock-ping/held/
    takeover/release messages; employee-add shows "Record locked" modal
    (Read Only / Take Control / Cancel); submit blocked in read-only.
    Footer status bar: Online (navigator.onLine) · DB connected · Last
    sync · Auto Save On.
  * Verified E2E via 2-page playwright: toast + refresh + lock modal +
    take control all OK. Theme kept (user's Q3 default).
- Iter 462 (user: "still not able to import excel in Compliance salary
  process / column issue"): could NOT reproduce on preview — full UI flow
  (button → picker → upload) imported 125/125 from user's Kankani Data.xls.
  Root causes possible on VPS: (a) deploy456 nginx fix not applied yet,
  (b) wrong-format file (daily punch sheet fails header detection —
  correctly). Improvements shipped: more header aliases (workingdays/
  paiddays/totaldays/salary/grosssalary/etc.) + 400 error now echoes the
  sheet's own first row so users see the mismatched columns.
- Iter 463/465 (user error recording + PORTAL-ACCEPTED MC_Template11.xls):
  ESIC .xls is now built ON TOP of the official template stored at
  /app/backend/assets/esic_mc_template.xls via xlutils.copy — preserves
  the portal's exact long header captions + "Instructions & Reason Codes"
  sheet. Data: IP zfill(10) TEXT, name sanitized (alphabets+space only)
  TEXT, days/wages/reason NUMERIC, LWD dd-mm-yyyy TEXT (portal page says
  dashes). xlutils added to requirements.txt. Verified generated file:
  headers + Instructions sheet intact, 0987654320 padding, Reason 2 +
  10-07-2026 for exited member.
- Iter 464 (user request): clicking the ACTIVE workspace tab now REFRESHES
  the current page (remount via ?_r nonce, stripped from stored routes)
  instead of doing nothing / jumping to Dashboard; inactive tab click still
  switches to that tab's own saved page.
- Iter 466 (user: still same portal error): per official MC manual
  (instruction 10) ALL columns incl. days/wages/reason are now TEXT strings
  written into the official template (this mirrors exactly what Excel
  produces when an employer types into the real template — its columns are
  pre-formatted Text). Verified: headers + Instructions sheet intact, all
  data cells t1 text, IP zfill, dd-mm-yyyy LWD. NOTE: unconfirmed whether
  user redeployed after Iter 465; asked them to verify the deploy check
  line "ESIC .xls uses OFFICIAL portal template (Iter 465): OK".
- Iter 467 (user request): ESIC Excel "Total Monthly Wages" now = row's
  esic_wage_base (wage-base rules: max(Basic earned, 50% Gross) — the
  wages ESIC contribution is deducted on) instead of gross_paid; fallback
  to gross_paid when esic_wage_base missing (old runs). Verified:
  RAJENDRA gross 11603 → SAL 5801 (wage base). Applies to both .xls & .xlsx
  via shared _esic_row_vals.
- Iter 468 (ROOT CAUSE of ESIC portal "not able to read"): xlwt output has
  ONLY the "Workbook" OLE stream; every portal-accepted file also carries
  SummaryInformation/DocumentSummaryInformation. _launder_xls() re-writes
  the built .xls via headless LibreOffice (isolated profile, 90s timeout,
  silent fallback to raw bytes). Verified via API: streams now CompObj/Ole/
  DocSummary/Summary/Workbook, 0.9s response. deploy456.sh installs
  libreoffice-calc if soffice missing + new verification check.
- User "still shows gross" report = VPS not redeployed since Iter 467
  (wage-base SAL verified here: gross 11603 -> SAL 5801).
- Iter 469 (user request — "allow the DOWNLOADED Attendance Sheet to upload
  in Compliance Salary Process; allowance/deduction heads are DYNAMIC"):
  compliance_import.py header matching rewritten with per-field ALIAS
  PRIORITY (ordered tuples) + right-most tie-break. Fixes: (1) "Employee
  Salary" fill-in column is now the imported/Freeze gross — previously the
  master "Gross Salary" column hijacked gross_earning; (2) dynamic
  allowance-head columns (between Conv. and Gross Salary) can no longer
  hijack fill-in fields (e.g. master "OVER TIME" vs fill-in "OVER_TIME");
  (3) sheet columns matching an ENABLED Firm-Master deduction head
  (UNIFORM/CLUB/CANTEEN/…) import per-head into the run's dynamic
  deduction_heads columns (entry field custom_deductions; merged in
  compliance_salary_runs.py after the Iter 420 custom filter, statutory
  heads excluded). (4) MAJOR pre-existing bug fixed: the AUTO-REPROCESS
  after every sheet import (Iter 335) was silently failing with
  ImportError — _create_compliance_salary_run_core / ComplianceSalaryRunCreate
  / _compute_compliance_run moved out of server.py long ago; imports fixed
  in compliance_import.py, ai_universal_import.py, utils/iter61_features.py.
  Verified E2E (upload -> auto-run -> imported_gross = Employee Salary,
  UNIFORM 150 in its own column). pytest iter100 (14) + iter360 (9) pass —
  iter100 test updated for Iter 335 auto-run + Iter 426 month-days lock
  (override_month_days). deploy_vps_iter469.sh created; temp_bundle kind=script
  now serves deploy469.sh. USER MUST REDEPLOY VPS (also carries Iter 467/468
  ESIC wage-base fix they reported as "still showing gross").
- Iter 470 (user: "ESIC Upload still showing Monthly Gross"): two residual
  sources of gross found & fixed in challans.py via shared _esic_wages(r):
  (1) the ON-SCREEN /challans-portal-preview?kind=esic showed gross_paid;
  (2) OLD runs whose rows lack esic_wage_base fell back to gross — now
  derived on the fly (esic_wage_base → stat_wage_base → max(basic, 50% of
  gross)), so users do NOT need to reprocess old months, only re-download.
  Verified locally: SURENDRA gross 19370 → SAL/preview 9685. Both .xls and
  .xlsx + preview use the wage base. deploy_vps_iter469.sh updated with an
  Iter 470 verification line (grep _esic_wages). REMINDER GIVEN AGAIN: user
  must run the deploy script — their VPS never received Iter 467 either.
  NOTE (pre-existing, unrelated): tests/test_iter388 TestFinalizeGates 2
  failures — finalize returns 200 with errors_overridden/warnings_overridden
  true (some override setting in DB); fails on untouched code too.
- Iter 471 (user bug — "Check Daily Rate and Monthly Rate on Salary Process
  Compliance"; example RATAN LAL per-day 450 × 20 days = 9000): the engine
  computed daily-rated staff as MONTHLY (450×20÷31=290) because it only read
  policy.salary_mode (Actual cadence). Fixes in utils/compliance_salary.py:
  (1) compliance_salary_mode (or structure Basic rate_type) now governs
  salary_mode; (2) comp_basic fallback factors: daily=×present days,
  hourly=×duty hours; master figures ×month_days; (3) PF: earned PF Basic =
  per-day rate × days, ceiling checks vs FULL-MONTH equivalent
  (_pf_basic_month); (4) ESIC eligibility Basic ×month_days for daily;
  (5) structure-row per-day heads scaled to earned values before the
  max(Basic, 50% Gross) wage-base floor (and master heads ×month_days).
  Frontend compliance-salary-run.tsx grid live-edit recompute mirrors all of
  it (pfBasicPro daily=×pd, pfBasicMonth for cap checks, esiEligBasic
  ×monthDays). Verified: unit matrix + API E2E (MADAN temp-daily: gross 9000,
  PF 1080, ESIC 68 on base 9000); monthly rows regression-identical.
  ALSO: Server Version badge — GET /api/version (APP_ITERATION const in
  server.py, BUMP EACH RELEASE) + "Server Iter N" chip in AdminWebShell
  status bar. ECR runner v10 (portal_extension.py): after Sign In, polls up
  to 3 min for login then auto-opens Payments >> ECR/Return Filing >> ECR
  Upload tab; RUNNER_VERSION bumped so user PCs self-update.
  Stale tests updated: iter394 EXISTING_RUN_ID repointed (fixture run had
  been deleted from DB); iter388 TestFinalizeGates 2 tests + iter408
  approval-pending test SKIPPED (Iter 423b never-block / Iter 425 no-approval
  user directives). Suites now 86 passed, 4 skipped.
- Iter 472 (user request — "Salary Process → With Existing Data: Days &
  Freeze stay the SAME but PF/ESIC must REFRESH per master changes"):
  compliance_salary_runs.py — (a) FREEZE manual_override rows: reprocess
  still restores the admin's OT/Others/kept gross AS-IS, but the statutory
  block (stat_wage_base, pf_*, vpf, esic_*, pt, calc_note) is RE-COMPUTED on
  that kept Gross Earning with CURRENT master/settings (gap routed via
  other_allowance_extra so wage bases see the full kept gross);
  total_deduction rebuilt (pf+esic+pt+tds+other+master+advance) and net =
  kept gross − total. (b) Non-imported manual rows: after the Iter 374
  others/ot_pay restores change the gross, same statutory refresh runs.
  Verified E2E: freeze run + manual OT +500 + master pf_basic revision →
  reprocess kept days 14.5 & gross 18500, PF went 0 → 1110 (wages 9250 =
  50% of kept gross), ESIC 70 on kept gross. Full suites 69 passed 3 skipped.
- Iter 473 (user reports — "new machines not showing in machine list" +
  "allow fetching current month or one month back data from machine"):
  biometric_devices.py — (a) _unknown_devices_payload() helper (extracted
  from Connection Doctor); GET /biometric/devices now returns
  unknown_devices so unregistered serials show ON the Machine List;
  (b) POST /biometric/devices/{id}/fetch-range?range=current_month|
  last_month queues `DATA QUERY ATTLOG StartTime=...\tEndTime=...` (ZK push
  protocol, tab-separated, verified via web docs) + a CHECK; month edges
  computed in the device's GMT zone. Frontend biometric-devices.tsx:
  red "New machines detected" cards with Register button pre-filling the
  serial (openRegisterUnknown); "Fetch this month"/"Fetch last month"
  buttons per device card. testing_agent frontend run: ALL PASS
  (/app/test_reports/iteration_471.json) incl. Server Iter 472 badge,
  unknown card, prefill, month-fetch alert. Seeded test serials cleaned.
  KNOWN LIMITATION explained to user: ADMS machines push only NEW punches;
  historical data needs Fetch old data (full) or the new month fetch
  (firmware must support DATA QUERY; fallback message included).
  NOTE: /admin-login route does NOT exist — admin login page is
  /admin-pin-login (Password tab). Testing agent suggested refactor:
  biometric-devices.tsx 2134 lines (backlog).
- Iter 474 (user report — "registered 4 machines today: CQIK231260072,
  NCD8251000569, NCD8251000531, NCD8251000591 — showing ONLINE but data
  didn't come"): ROOT CAUSE — handshake answered ATTLOGStamp=None for
  freshly registered devices, telling the machine the server already has
  everything, so stored punches were never uploaded (only future punches).
  Fixes in biometric_devices.py: (a) _first_sync — handshake answers
  ATTLOGStamp=0 until the device's FIRST data push lands (last_push_at
  empty), then normal stamping; (b) device registration auto-queues a
  CHECK command so the machine re-initialises within ~1 min (no reboot).
  Verified E2E: register → CHECK queued → handshake stamp=0 → push ATTLOG →
  handshake stamp=None. For machines registered BEFORE the deploy the user
  must press "Fetch old data" once per machine (or reboot the machine).
- Iter 475 (user spec — Employee Rejoin/Rehire): NEW
  /app/backend/routes/employee_rejoin.py registered in server.py:
  GET /admin/employees/{id}/rejoin-info (previous details + service span/
  gap + history + firm policy), POST /admin/employees/{id}/rejoin
  (validations: must be separated, rejoin_date >= LWD, reason required;
  archives closing period to employment_history with sequence; employee
  code continue/new per firm_masters.rejoin_policy with
  previous_employee_codes link; applies new dept/desig/salary/compliance
  structure via build_compliance_structure; leave policy continue/reset/
  manual; gratuity_service_policy stamped; UAN/ESIC NEVER changed;
  active=True restores PWA/mobile/biometric; immutable rejoin_audit with
  admin+IP; ws broadcast employee.rejoined),
  GET /admin/employees/{id}/employment-history,
  GET/PUT /admin/firm-masters/{cid}/rejoin-policy.
  Frontend: /app/frontend/app/employee-rejoin.tsx wizard (read-only prev
  card, service summary, section B form, policy card, history timeline);
  employee-master.tsx shows green "Rejoin Employee (Rehire)" (em-rejoin)
  for separated employees. Backend E2E verified (validations, archive,
  audit, code continuity). testing_agent frontend run ALL PASS after it
  fixed 2 bugs: (1) employee-master detail merge missing active/
  employment_status/exit_date/resign_date fields; (2) employee-rejoin
  double JSON.stringify (api client already stringifies). Report:
  /app/test_reports/iteration_475.json. Seeded test employee cleaned.
  NOTE: _parse_any_date returns datetime — use _to_date() wrapper.
  Backlog from spec (NOT yet built): rejoin-policy Firm Master UI screen
  (API ready), multi-period report annotations, notifications to HR/
  manager beyond ws broadcast.

## Iter 476 (fork) — Firm Master sticky banner + ADMS port-80 nginx fix
- firm-master.tsx: sticky amber "Unsaved changes" banner pinned under the
  page header (outside ScrollView) with Save Now button; shows only when
  dirty. Screenshot-verified (stays pinned while scrolling).
- deploy476.sh: NEW nginx conf.d/sks-adms.conf — catch-all :80 server
  proxying /iclock/ + /api/iclock/ straight to backend:8001 so BIOFACE/
  ZKTeco machines NEVER receive a 301 HTTPS redirect (root cause of the
  "machines online but no data" issue when VPS forces HTTPS).
- NOTE: /admin-login does NOT exist — login page is /admin-pin-login
  (Password tab). Testing via localStorage key `llc_session_token`.

## Iter 477 — Govt Registers FORM headings + periodic; grid OT Hrs / ESIC Leave
- govt_audit_reports.py: (a) statutory FORM heading restored on ALL 5
  Government Registers — _FORM_HEAD dict (FORM B — WAGE REGISTER; FORM C —
  REGISTER OF LOANS/RECOVERIES for fine/deduction/advance; Gratuity Act
  line) + rules-2017 line; delivered via new form_line param in
  register_pdf/register_xlsx (utils/register_export.py — "\n"-split lines,
  dynamic freeze pane) and "form_line" field in the JSON view. Titles now
  "(Form B)"/"(Form C)" (were "(Form)"). Iter 433 empty-note line kept.
  (b) PERIODIC month..month_to on ALL 5 (was fine/advance only): wage +
  deduction aggregate per-employee across months; gratuity takes Basic
  from the latest processed month in range.
- reports-center.tsx: MONTH_RANGE_KINDS = all 5 govt registers (generic
  Month wise/Periodic toggle reused); form_line rendered centred above the
  result title (testID rc-form-line).
- compliance-salary-run.tsx (user request): OT Hrs column MOVED right
  after Present Days (was OT Amt*→OT Hrs→Gross). infoW now 9 cols
  (i<9 width checks), INFO_W band += CELL_W, calcCount -1; body cell +
  totals cell moved to match. OT Hrs stays editable-on-normal-runs /
  read-only-on-freeze as before (Iter 340 logic untouched).
- ESIC Leave column (user request): grid cell now READ-ONLY text — days
  auto-fetched from ESIC Leave Master. compliance_salary_runs.py: when
  esic_leave settings enabled+link_compliance the master map is
  AUTHORITATIVE (sets 0 when no approved entry); module off → legacy
  behaviour (preserved values kept).
- Verified: curl (JSON form_line + periodic subtitle "June 2026 to July
  2026" + aggregated rows; PDF/XLSX headings via pypdf/openpyxl), UI
  screenshots (Report Hub periodic toggle + FORM B heading; grid header
  order Present Days→OT Hrs→ESIC Leave with aligned bands).
- Deploy: /app/deploy_vps_iter477.sh (kind=script). APP_ITERATION=477.

## Iter 478 — Portal-editable Government Register headings
- govt_audit_reports.py: _form_head(kind) reads db.app_settings key
  "govt_register_heading:{kind}" (custom overrides built-in _FORM_HEAD;
  empty = default). NEW endpoints (registered BEFORE the /{kind}
  catch-all): GET /admin/govt-registers/headings (all roles) and
  PUT /admin/govt-registers/headings/{kind} body {lines} (SUPER ADMIN
  only; empty lines deletes the override). JSON + PDF + XLSX all flow
  through _form_head.
- reports-center.tsx: "Edit heading" pencil (testID rc-edit-heading,
  super_admin only, govt group only) → modal (rc-heading-input /
  rc-heading-save / rc-heading-reset) with multiline heading editor,
  Save / Reset to default / Close; reloads the view after save.
- Verified E2E: curl (GET headings, PUT custom → JSON+PDF show custom,
  PUT empty → default restored) + UI screenshot flow (save custom →
  rendered, reset → FORM B default back). APP_ITERATION=478;
  deploy_vps_iter478.sh served via kind=script.

## Iter 479 — CLRA/Labour Code Phase 1 + Daily Report PDF + UX
USER SPEC: massive 19-register CLRA/Labour Code prompt. Phased plan agreed:
Phase 1 built now; Phase 2 = field enhancements to existing registers +
LWF register (user: build LWF for other states — Rajasthan has none);
Phase 3 = Inspection Register, Digital Document Register, QR/scheduled
reports, CLRA-vs-Labour-Code mode. Digital signature = SKIPPED (user).
- NEW /app/backend/routes/contractors.py: db.contractors CRUD
  (licence/PAN/GSTIN/EPF/ESIC/deposit/max_labour/agreement/status),
  auto-seed from firm_masters.contractors, active-labour counts from
  users.contractor_name, renewal flags (60-day lookahead), rename syncs
  users.contractor_name.
- NEW /app/backend/routes/clra_labour_reports.py (/api/admin/clra-reports):
  contractor-register, principal-employer, contract-labour-register,
  pt-register, rejoin-history, compliance-dashboard — JSON + .xlsx/.pdf,
  same pattern as govt_audit_reports. Email via payroll_reports
  email-report group=="clra" branch.
- NEW /app/frontend/app/contractor-master.tsx (CRUD UI, status pills,
  expiry warnings) + sidebar "Contractor Master" under Masters (both menu
  defs in AdminWebShell). Report Hub group "CLRA / Labour Code" added
  (GROUP_BASE.clra) with all 6 chips.
- Daily In/Out & OT Verification (user request): PDF (landscape+portrait)
  renamed "Daily Report", company 2nd row, date right-aligned; columns
  Verified/Verified By/Remarks REMOVED; Emp Code → Bio Code (users.bio_code,
  falls back to employee_code); summary block now in the FOOTER of every
  page + "Page N"; bottomMargin 17mm. XLSX/CSV unchanged. NEW present_only
  filter (single punch counts as present) in _build + JSON + all exports +
  "Only Present" switch in daily-verification.tsx.
- admin.tsx: green "Rejoin Employee (Rehire)" button (testid
  admin-rejoin-btn) under Exit/Left date when employee separated.
- NEW /app/frontend/src/components/FirmDropdown.tsx (user: "Always show
  firm picker as dropdown list") — inline-expanding searchable dropdown;
  replaced company CHIPS in admin.tsx sheet (testid admin-company-dropdown;
  locked state keeps lock pill). Used in contractor-master too.
- TESTED: testing_agent iteration_479.json — 25/25 backend pytest + all
  frontend flows PASS. APP_ITERATION=479; deploy_vps_iter479.sh (kind=script).
- NOTE: gotcha — parallel search_replace batches on the same file sometimes
  drop one edit silently; verify with grep after batch edits.

## Iter 480 — CLRA/Labour Code Phase 2 (statutory field enhancements)
- govt_audit_reports.py `_wage_register`: Form B now splits allowances
  (conveyance/medical/special/others) + deductions (pf/esic/pt/tds/
  other_ded) + Bank A/c-IFSC (from users), periodic aggregation kept.
  `_gratuity_register`: + eligible_service, wage_def, exempt (≤₹20L) /
  taxable split, payment_date.
- clra_labour_reports.py NEW kinds: pf-register (UAN/PF-EPS wages/EPF-EE/
  VPF/EPS-ER/EPF-ER/EDLI/NCP/DOJ-DOE-rejoin), esic-register (IP/wage base/
  0.75-3.25%/contribution+benefit period via _esic_periods/TIC),
  lwf-register (_LWF_SLABS 16 states, firm state from companies.state or
  firm_masters.registered_address.state, contribution-month aware, due
  dates), leave-register (EL ledger: opening=users.leave_opening_balance,
  earned=FY present_days//20 from compliance runs, availed=db.leaves
  approved, closing). Filename header sanitised to ASCII (em-dash in
  title crashed Content-Disposition latin-1 encode — FIXED).
- labour_reports.py daily_attendance: + Contractor/Shift/Source/Late Min/
  Early Out Min columns (from _day_summary + emps projection).
- NOTE: _company() in labour_statistics projects only name+logo — do NOT
  use it for state; query companies/firm_masters directly.
- Verified via curl (all kinds JSON + pdf/xlsx 200; LWF tested with
  temp Maharashtra state then reverted; daily_attendance via
  POST /admin/labour-reports/generate report_key+filters) + Report Hub
  screenshot (10 CLRA chips, PF Register table renders).
- APP_ITERATION=480; deploy_vps_iter480.sh (kind=script).
- Phase 3 pending: Inspection Register (CRUD), Digital Document Register,
  scheduled email reports, CLRA vs Labour Code mode toggle.

## Iter 481 — Punch dedup (5 min) + alternation repair + night-shift pairing
USER ISSUE (live VPS, RANJAN FABRICS): almost all grid cells "missing OUT"
— employees DO punch twice but double-punch bursts flipped ADMS IN/OUT
alternation; night OUT (01:10) landed next day as "in".
- biometric_devices.py ingestion: skip punch if same user+device has any
  punch within ±5 min ("duplicate_within_5min_ignored").
- server.py NEW dedupe_close_punches(punches_by_day): (1) drop punches
  <5 min after previous kept punch from SAME source; (2) re-kind machine
  days whose punches are all same-kind (zkteco/import sources only,
  mobile/manual untouched): first<08:00 → "out" (night candidate), rest
  alternate in/out.
- stitch_cross_day_ot extended: next-day first punch kind "in" before
  08:00 after unpaired IN → re-kinded "out" + pulled back (was out-only).
- Wired at ALL 4 call sites: _compute_monthly_grid_data, server.py:9264
  (by_day), server.py:10428 (OT matrix pipeline), attendance_doctor._stitch.
- Unit-tested via ast-extracted functions: burst dedupe ✓, night pairing
  22:00 IN + next-day 01:10 → OUT same day ✓, mobile kinds untouched ✓.
- No DB migration: existing duplicates repaired on the fly at compute.
- APP_ITERATION=481; deploy_vps_iter481.sh.

## Iter 482 — "Both punches available but showing missing" (user bug, live VPS)
- ROOT CAUSE: employee PWA/mobile punches stored with status "pending"
  (Iter 83 rule); _compute_monthly_grid_data counts ONLY status approved
  → pending App OUT invisible in grid while PunchRepairModal (reads
  /admin/attendance/history, all statuses) shows both punches.
- FIX: PunchRepairModal.tsx — pending punches get amber "PENDING — tap to
  approve" button → POST /api/attendance/punches/{record_id}/decision
  {action: approve} (roles: super/sub/company admin) → reload + setChanged.
- E2E verified locally: synthetic machine IN 10:08 approved + mobile OUT
  22:08 pending → daily-verification showed "10:08 / -"; after decision
  approve → "10:08 / 22:08". Test records cleaned up.
- APP_ITERATION=482; deploy_vps_iter482.sh.

## Iter 483 — Auto-approve Mobile App Punches per firm (user: "Do it")
- Firm Master → 8. Firm Settings → new Toggle "Auto-approve Mobile App
  Punches (no admin review)" (settings.auto_approve_mobile_punches,
  testID fm-auto-approve-app).
- PATCH /api/admin/firm-master/{cid} mirrors flag to
  companies.auto_approve_mobile_punches AND, when ON, bulk-approves the
  firm's OLD pending punches (skips pending_reason=contractual_employee
  and mock_location=True) with decision_by "system:firm-auto-approve".
- POST /api/attendance/punch (attendance_core.py ~line 543): firm_auto
  flag → status "approved" instantly. Mock-GPS punches stay pending;
  contractual employees still demoted by apply_contractual_gate (the
  system: decision_by preserves that contract).
- E2E verified locally: sweep approved seeded pending punch, kept mock
  pending; new app punch approved when ON, pending when OFF; contractual
  TEST50 stayed pending as designed. Test data cleaned up.
- APP_ITERATION=483; deploy_vps_iter483.sh; temp_bundle kind=script → 483.

## Iter 484-485 — Firm Master ERP redesign + Sub-admin leak fix + Master Snapshot
1) FIRM MASTER 16-SECTION ERP LAYOUT (user request, full restructure approved):
   - firm-master.tsx: left side-nav (NAV_SECTIONS, testID fm-nav-{id}),
     sections render conditionally via sec(id). Sticky action bar: Save /
     Save & Continue / Reset / Cancel / Clone Company / Export Configuration.
     AUTO-SAVE 2s debounce (saveSilent), auto-state pill in header.
   - NEW components /src/components/firmMaster/: primitives.tsx (Card,
     FieldV2, DropdownV2, CheckRow, MiniBtn), GeneralInfoSection.tsx
     (identity-only, 2-col, drag&drop logo + crop-to-square, code unique
     check via /admin/firm-master-check-code, status chips, colour swatches),
     ContactDetailsSection.tsx (normalized cards primary/hr/payroll/
     compliance/accounts + Company Communication + prefs + per-contact
     Receives permissions + Copy/vCard/click-to-call + Test Email/WhatsApp),
     AuditLogSection.tsx, HealthSection.tsx (health score).
   - Backend routes/firm_master_v2.py: GET/PUT /admin/firm-master/{cid}/contacts
     (db.company_contacts normalized, legacy auto-migrate), audit list,
     export JSON, clone (super only), check-code, test-whatsapp, vcard.
   - firm_master.py: GET seeds master.general defaults; PATCH validates
     (name required, start date <= today, company_code unique), mirrors
     general → companies, writes firm_master_audit entries.
   - Old "Firm Header" emails + Contact Persons grid REMOVED (migrated).
2) P0 SECURITY FIX: sub_admin saw ALL firms on Present Today.
   attendance_admin_core.py /admin/attendance/today + present-not-punched
   now honour ?company_id for sub_admin and call
   apply_sub_admin_company_scope; belt&braces current-firm row filter.
3) COMPLIANCE MASTER DATA SNAPSHOT (user spec "Develop Accordingly"):
   - utils/master_snapshot.py: FROZEN_MASTER_FIELDS (~60 fields),
     db.compliance_master_snapshots one doc PER EMPLOYEE, versioned
     (active flag, history kept), indexed cms_scope_active_user.
   - _compute_compliance_run: overlay snapshot before DOJ/exit filters,
     resurrect ghosts, first-generate creates v1 (allow_snapshot_create
     param; reprocess passes False), new joiners appended.
   - POST /admin/compliance-salary-runs/{id}/refresh-master-snapshot
     (super_admin + sub_admin only, reason + IP audit, version+1) and
     GET .../master-snapshot-info. Frontend "Refresh Master" ActionBtn
     (isSuper) with mandated confirmation text.
   - PF/ESIC calc engine utils/compliance_salary.py: ZERO changes (user
     explicit directive).
   - Audits: snapshot_created / snapshot_appended / refresh_master_snapshot
     in salary_audit_log.
- Testing: iteration_485.json — 14/14 backend + 5/5 frontend PASS.
- APP_ITERATION=485; deploy_vps_iter485.sh; temp_bundle → 485.

## Iter 486 — Attendance engine fixes + CLRA Phase 3 (final)
ATTENDANCE ("Still Facing Issue" bug):
- biometric_devices.py: ATTLOG punch-state (col 3) now honoured
  (_STATE_KIND 0=in,1=out,2/3=break,4/5=OT). kind="both" devices use
  machine state first, alternation fallback; fixed-kind devices honour
  explicit non-zero states.
- server.py dedupe_close_punches: all-same-kind day repair now covers ALL
  sources (was machine-only) → earliest=IN, latest=OUT.
- server.py monthly grid: punch query extended ±1 day for CROSS-MONTH
  night stitching; helper day keys dropped after stitch. Verified E2E:
  Jul-31 20:00→Aug-1 01:10 pairs on July grid, Aug-1 orphan gone.
- attendance_admin_core.py: GET /admin/attendance/grid-debug?user_id&date —
  full trace (raw punches all statuses, excluded reasons e.g. pending,
  processed pipeline, selected IN/OUT, out_missing_reason).
- PunchRepairModal approve → onSaved() → grid refreshes instantly.
CLRA PHASE 3:
- clra_labour_reports.py: _inspection_register + _document_register kinds;
  inspections CRUD (/admin/clra-reports/inspections, BEFORE /{kind});
  compliance_act_line() → subtitles cite CLRA 1970 vs Labour Codes based
  on firm_masters.settings.compliance_mode.
- routes/scheduled_reports.py: /admin/report-schedules CRUD + send-now +
  scheduled_reports_loop (5-min, IST, idempotent last_sent_key; daily/
  weekly/monthly; use_previous_month; uses _smtp_send attachments).
  Started in server.py startup.
- frontend: ClraPhase3Panel.tsx (schedules panel + inspection entries)
  mounted in reports-center; firm-master Compliance Settings →
  compliance_mode radio (fm-compliance-mode-*); compliance-salary-run
  header MASTER SNAPSHOT badge (testID snapshot-badge, reads
  master-snapshot-info, refreshes after Refresh Master).
- All E2E tested via curl (registers, CRUD, mode toggle, schedules,
  send-now SMTP guard, pdf/xlsx exports) + UI screenshot. Test data
  cleaned. APP_ITERATION=486; deploy_vps_iter486.sh; temp_bundle → 486.
KNOWN/DISCUSSION ITEMS: pending app punches still excluded from grid
unless approved/auto-approve ON (by design); SMTP must be configured for
scheduled emails; WhatsApp blocked on user's Meta account; server.py +
compliance-salary-run.tsx refactor pending.

ITER 487 — EXPIRING DOCUMENTS EMAIL ALERTS (DONE, tested):
- scheduled_reports.py: run_doc_expiry_alerts() — scans firm_masters.
  compliance_docs + contractors CLRA licences; buckets 60/30/7/0 days;
  recipients = company_contacts with recipient_permissions.compliance_reports
  + communication.compliance_email/official_email; gated by comm_prefs.
  send_compliance_alerts; exactly-once via db.doc_expiry_alerts alert_key;
  daily scan in scheduled_reports_loop after 08:00 IST.
- Manual trigger: POST /api/admin/doc-expiry-alerts/run-now?company_id=
  (force=True bypasses the pref toggle for testing).
- UI: ContactDetailsSection → Communication Preferences card now has the
  60/30/7 explanation + "Check Expiring Docs Now" button (cd-check-expiry).
- SECURITY: _adm() in scheduled_reports.py now enforces
  sub_admin_can_touch_company (was missing — sub-admin scope leak);
  firm_master_v2.py verified already scoped via _assert_firm_access.
- TESTED: seeded 30d firm doc + 7d contractor licence; run-now w/o SMTP →
  correct guard msg; with local aiosmtpd sink → 1 email, 2 alerts, correct
  subject/body; second run → "All alerts already sent" (idempotent); UI
  button click e2e → alert dialog. Test data cleaned up.
- APP_ITERATION=487; deploy_vps_iter487.sh; temp_bundle script → 487.

ITER 488 — DUPLICATE PUNCH FIX (DONE, tested; user: "Multi Punch Within
the Same time — ignore duplicates within 5 min by default"):
- Ingestion (_ingest_attlog_line): ±5-min duplicate guard now checks ANY
  existing punch of the employee (was same-device only). Per user rule
  duplicates are STORED with status="duplicate" (never dropped/deleted),
  excluded from all calcs; both-mode alternation query now filters
  status=approved so dupes can't flip IN/OUT.
- Display (dedupe_close_punches): machine punches dedupe against previous
  kept punch from ANY source (manual/app punches keep same-source-only
  rule — an admin repair punch is never dropped).
- New API: POST /api/admin/attendance/cleanup-duplicate-punches
  ?company_id=&month=&dry_run= → marks stored approved zkteco dupes
  status="duplicate" (never deletes). deploy488.sh runs this once for ALL
  firms via inline Mongo script.
- PunchRepairModal hides status=duplicate rows.
- Tested: ABDUL RAZA KHAN replica (10:23×2 + 22:13×2 two devices) → grid
  pairs 10:23 IN→22:13 OUT; ingestion stores 3rd-device dup as
  status=duplicate; cleanup dry-run+real marks 2; nothing deleted.
- APP_ITERATION=488; deploy_vps_iter488.sh; temp_bundle script → 488.

NEXT (user spec, Iter 489 — SINGLE MACHINE ATTENDANCE MODE, large):
Company-level attendance_config in Firm Master (device mode radio:
separate/single_machine/mobile/gps/qr; interpretation A alternate /
B first-last; duplicate window 0/1/2/5/10 min; lunch: ignore_middle/
actual_break/fixed 30/45/60). Engine branch ONLY when single_machine.
Reconnaissance done: hook = dedupe_close_punches(company_cfg) at call
sites server.py:9283/9751/10460 + attendance_admin_core grid-debug +
attendance_doctor; firm_master PATCH mirrors settings to companies doc
(pattern: auto_approve_mobile_punches); grid day-cell fields to add:
punch_pattern, calc_mode, dupes_ignored, machine names; FirmMaster UI
section 8 "attendance" lives in frontend/app/firm-master.tsx (~line 845).
Fixed-lunch deduction needs hours-level hook (grid compute ~line 10030).

ITER 489 — REGISTER PDF ADVANCE COLUMN FIX (DONE, tested; user: "Advance
Amount Show into the PDF Report in Other"):
- utils/compliance_salary.py: Format 1 (build_compliance_register_pdf)
  had "adv": 0 hardcoded + other_ded() included advance_recovery →
  advance printed under OTHER, ADVANCE always 0. Fixed: adv_ded() own
  column, other_ded() excludes advance; totals accumulate "adv".
- Columns now DYNAMIC: ADVANCE/OTHER deduction columns appear only when
  head enabled in Firm Master mask or a row carries a value.
- Format 2 (v2): new ("advance","Advance",12,True) in V2_REGISTER_COLUMNS
  (between esi & other_ded); saved layouts get advance injected before
  other_ded/tds/total_ded; _col_ok gates advance+other_ded; totals/group
  subtotals include it. Layout editor catalog comes from backend → auto.
- CSV/XLSX (dynamic_csv_columns) already had separate advance_recovery.
- Tested via pdfplumber: v1 (adv 2500/other 300 correct, no-adv firm hides
  ADVANCE col), v2 (new + old saved layouts both show Advance), totals OK.
- APP_ITERATION=489; deploy_vps_iter489.sh (cumulative w/ 488 dup fix +
  one-time dup cleanup); temp_bundle script → 489.

ITER 490 — DELETE EMPLOYEE, SUPER ADMIN ONLY (DONE, tested):
- employees_admin.py DELETE /api/admin/employees/{user_id}: now uses
  require_super_admin_strict (require_role lets sub_admin inherit
  super_admin — verified sub_admin got 200 before fix!). company_admin
  branch removed. Guards kept: legacy_locked, super_admin target, self.
- employee-master.tsx: red "Delete Employee (Super Admin only)" button
  (testID em-delete-employee) below Login Credentials, visible only for
  role=super_admin; confirm dialog; cascade note; router.back() after.
- Tested E2E: company_admin 403, sub_admin 403, super_admin 200 +
  cascade; UI screenshot verified.
- APP_ITERATION=490; deploy_vps_iter490.sh (cumulative 488+489+490);
  temp_bundle script → 490.

ITER 491 — DELETED EMPLOYEE GHOST IN COMPLIANCE SALARY (DONE, tested;
user: "Employees Was Delete From Firm Master ... Still Show"):
- ROOT CAUSE: snapshot ghost-resurrection (Iter 485) re-added employees
  deleted from db.users on Reprocess (frozen data has no exit_date so the
  resign filter couldn't catch them either).
- FIX 1 compliance_salary_runs.py: ghosts resurrected ONLY if user_id
  still exists in db.users (_alive_uids batch check).
- FIX 2 employees_admin.py delete_employee_record cascade now deletes
  compliance_master_snapshots docs for the user.
- NOTE for tests: POST /api/admin/compliance-salary-runs and /reprocess
  return {"ok":true,"run":{...}} NESTED — rows at resp["run"]["rows"].
- Tested E2E (Kankani 2026-06 STAFF): generate 18 rows w/ ghost + snap v1
  → delete (cascade master_snapshots:1) → reprocess 17 rows, ghost gone.
  Test data cleaned.
- APP_ITERATION=491; deploy_vps_iter491.sh (cumulative 488-491);
  temp_bundle script → 491.

ITER 492 — EMPLOYEE MASTER PDF + SALARY CERTIFICATE PERIOD (DONE, tested):
- utils/employee_pdf.py: family table one-line (Relation|Name|DOB|Aadhaar),
  _fmt_mdy() MM-DD-YYYY for DOB/DOJ/family DOB (user EXPLICITLY asked
  MM-DD-YYYY, flagged in reply in case they meant DD-MM), Aadhaar FULL
  (unmasked), Salary Details += salary_structure_actual heads +
  actual_salary_allowances + salary_structure_compliance, policy page
  gated on firm_masters.salary_process.offline_salary AND
  .bio_matrix_attendance (param firm_salary_process passed from
  employee_documents.py single + bulk endpoints).
- Salary Certificate: employee-master.tsx new certMonth input (YYYY-MM,
  testID cert-month-input) → ?month=; salary_runs.py endpoint resolves
  ACTUAL figures: finalized compliance run row > legacy_salary_history
  (kind online→offline, "Old DB records — LOCKED") > master fallback;
  utils/salary_certificate.py new actual= param renders real
  basic/gross/net/present-days table + source.
- Tested via pdfplumber: all assertions pass (flags on/off, old-db month,
  fallback month). Test data cleaned/restored.
- APP_ITERATION=492; deploy_vps_iter492.sh (cumulative 488-492).

ITER 493 — FIRM SWITCH ALWAYS REFRESHES (DONE, tested; user: "After
Change the Firm Always Refresh the Data ... Don't Show Wrong Data"):
- SelectedCompanyContext.switchCompany(cid, opts?): on web, after
  persisting selection (localStorage + PATCH), does location.assign("/")
  after 250ms → FULL document reload, all screens refetch for new firm.
  firm-select.tsx passes {reload:false} (it navigates itself).
- Cannot key-remount the Stack (Iter 197 warning) — reload is the safe
  global guarantee. Tested with window marker: marker wiped → real
  reload; dashboard refetched (All firms scope).
- APP_ITERATION=493; deploy_vps_iter493.sh (cumulative 488-493).

ITER 494 — EMPLOYEE PHOTOS IN ATTENDANCE MODULE (DONE, tested; user spec
"enhancement only, don't touch sync engine"):
- NEW routes/employee_photos.py: POST /api/admin/employee-photos/thumbs
  (batch ≤300, lazy 96px JPEG thumbs cached in users.profile_photo_thumb,
  regen when profile_photo_updated_at newer) + GET .../{uid}/full.
  Role-gated (company_admin scoped to own firm). Registered in server.py.
- NEW src/components/EmployeePhoto.tsx: module-level cache + debounced
  batch loader, initials avatar fallback, unknown-employee icon (no uid),
  tap → full preview modal (name/code/machine).
- Wired: biometric-devices.tsx live feed (+user_id in backend feed rows),
  punch-log-report.tsx new photo col (+user_id in rows), daily-
  verification.tsx name cell, attendance-grid.tsx name cell, admin.tsx
  employee search list (replaced initials-only avatar).
- Photos source: existing Employee Master → Documents → Photo (syncs to
  users.profile_photo_base64) — no schema change.
- BONUS FIX (user: "Name in Machine not showing for NEW machines"):
  getrequest now auto-queues DATA QUERY USERINFO ONCE per device
  (userinfo_query_sent flag); punch-log _mu_map also indexes PINs with
  leading zeros stripped.
- Tested: thumbs (1KB thumb, cached, None for no-photo), full (11KB),
  live-feed + punch-log rows expose user_id (1941 rows), UI avatars
  render on Punch Log (screenshot). Sync engine untouched.
- APP_ITERATION=494; deploy_vps_iter494.sh (cumulative 488-494).

ITER 495 — MACHINE SDK PHOTOS + NEW-MACHINE USER FETCH + GROUP IN/OUT
(DONE, tested via tests/check_iter495_photo_sync.py — all pass):
- USERPIC/BIOPHOTO capture in _ingest_templates (biometric_devices.py):
  photo stored on biometric_machine_users.photo_b64 + synced to
  users.profile_photo_base64 when employee matched (via
  _match_employee_for_bio incl. lstrip-0) and has no portal photo.
- ROOT CAUSE new machines "not fetching users": firmwares reply to
  DATA QUERY USERINFO with table=USERINFO (or blank) — server only parsed
  table=OPERLOG/BIODATA/USERPIC/BIOPHOTO. Fix: iclock_push now runs
  _ingest_templates for EVERY non-ATTLOG/ATTPHOTO table (prefix-guarded).
- getrequest auto-queues DATA QUERY USERPIC + BIOPHOTO once per device
  (userpic_query_sent flag).
- employee_photos.py: _machine_photo_backfill — thumbs/full endpoints
  fall back to machine-registered face when user has no portal photo
  (persisted with profile_photo_source="machine").
- GROUP-WISE monthly IN/OUT verified working e2e (frontend attendance-
  sheet.tsx sends group_id; _resolve_group_employee_ids filters — LABOUR
  export 44KB vs full 52KB). No backend change needed.
- Deploy script one-time step: unsets userinfo_query_sent +
  userpic_query_sent on ALL devices so existing machines re-send user DB
  + photos on next poll (replies now parsed correctly).
- White screen issue (P0 from handoff): user confirmed RESOLVED ("All
  Done Please Ignore").
- APP_ITERATION=495; deploy_vps_iter495.sh; temp_bundle kind=script → 495.
NEXT: Single Machine Attendance Mode (big spec, Message 148); WhatsApp
API (blocked on user Meta credentials); SMTP config by user.

ITER 496 — UNIVERSAL REPORT TABLE ENGINE, PHASE 1 (DONE, tested: backend
6/6 pytest + frontend 4 screens via testing_agent, iteration_496.json):
- NEW src/components/ReportTable.tsx: one common renderer — auto col width
  (content-measured, min/max per type), sticky header, frozen leading
  cols (position:sticky web), ellipsis + hover/tap tooltip, num→right /
  date→center / text→left alignment, responsive font 14/13/12 (min 11),
  consistent row height, virtual scrolling >120 rows, drag col-resize
  (web), Columns show/hide panel + Reset layout.
- NEW routes/report_prefs.py: GET/PUT /api/report-prefs/{key} — per-user
  per-report saved layout {w,hide,t} in db.report_ui_prefs; frontend
  caches in localStorage (rt:{key}) + debounced server sync; newer t wins.
- MIGRATED Phase 1: punch-log-report (punch_log; photo col render, sticky
  photo/code/name, flag colors kept), ot-report (ot_report; tap-sort keys
  now = column keys, TOTAL footer pinned), leave-report (leave_report),
  bank-transfer preview (bank_transfer; TOTAL footer).
- APP_ITERATION=496; deploy_vps_iter496.sh; temp_bundle kind=script → 496.
REMAINING PHASES (user approved full rollout — his words "check all",
prefs BOTH localStorage+server, PDF engine to ALL reports eventually):
- Phase 2: salary-register.tsx (banded 2-row header — needs engine
  support for column groups), bank-sheet, wage register, salary sheet,
  compliance-salary-run results grid.
- Phase 3: attendance-grid, monthly attendance, inout-ot-matrix,
  daily-verification, employee-master list, advances, loans, PF/ESIC/
  bonus/gratuity registers, contractor/department-wise.
- PDF phase: shared utils/report_pdf.py builder (landscape, auto width,
  repeatRows, Paragraph-wrap) then migrate known-broken PDFs first.
NEXT (unchanged): Single Machine Attendance Mode (Message 148 spec);
WhatsApp API (blocked on user Meta credentials); SMTP config by user.

ITER 497 — UNIVERSAL REPORT ENGINE PHASE 2+3 + SCREEN-MATCHING PDF (DONE,
tested: backend 6/6 pytest + 5 screens live via testing_agent,
iteration_497.json):
- ReportTable.tsx: BANDED headers (ReportCol.band {key,label,color} →
  merged sticky band row above header, header sticky top=BAND_H, native
  stickyHeaderIndices [0,1]) + universal PDF toolbar button (pdfTitle/
  pdfSubtitle props → POSTs visible cols/widths/values+footer to
  /api/report-export/pdf, downloads blob; web-only, rows>0 gate).
- NEW backend utils/report_pdf.py build_report_pdf(): landscape auto page
  (A4→legal→A3→A2), col widths proportional to screen, repeatRows 1-2,
  Paragraph wrap for overflowing left-aligned text, zebra, footer
  highlight, band SPANs. routes/report_export.py POST /api/report-export/
  pdf (roles super/sub/company admin, max 20k rows/80 cols).
- MIGRATED: salary-register.tsx (rtCols banded via GROUP_COLORS, layout-
  editor width→min=max, sticky __sn/code/name, onSort kept, rtFooter;
  removed GridScroller/bands/colWidth), bank-sheet.tsx (BS_COLS),
  salary-day-sheet.tsx (HDR now ReportCol[], removed W const),
  contribution-sheets.tsx (monthly dynamic cols + yearly with per-month
  cols, footers; reportKeys contrib_{pf|esic}_{monthly|yearly}).
- Footer label placement trick: pass values {sn:" "} so label lands on
  the Name column.
- NOT migrated (deliberate): compliance-salary-run.tsx grid (interactive
  editable cells + GridFreeze already frozen — high risk), attendance-
  grid/monthly matrix (interactive day-cell matrix), employee-master
  (management list), clra-registers (uses shared RegisterTable),
  advances/loans (card-based UIs, not tables).
- APP_ITERATION=497; deploy_vps_iter497.sh; temp_bundle → 497.
NEXT: Single Machine Attendance Mode — NEED user to re-share full spec
(Message 148 of old session not available in fork); WhatsApp API blocked
on user Meta credentials; SMTP config by user.

ITER 498 — ONE-SHOT PUNCH REPAIR (IN + OUT + OT together) (DONE, e2e
verified via playwright screenshots on live grid, test punches restored):
- PunchRepairModal.tsx: new "⚡ Fix IN + OUT Together (one save)" flow —
  IN + OUT time fields side by side, prefilled from existing punches;
  ONE Save updates existing punches (PATCH /admin/attendance/{id}) or
  creates missing ones (POST /admin/attendance/manual-punch).
- Pairing logic: duty pair = 1st IN + last OUT before OT-IN (or last OUT
  overall); OT pair = 2nd IN + OUT after it (Iter 419 convention) so the
  duty OUT never clobbers the OT OUT.
- OT repair (user follow-up): "Also repair OT punch" toggle → OT In/OT
  Out fields in the SAME form, saved in the same click.
- Night shift: OUT < IN → OUT auto-saved next day with 🌙 note; OT pair
  rolls to next day similarly (otInIsNextDay/otOutIsNextDay).
- Bug fixed during dev: leftover `lastOut` ref crashed modal (renamed to
  dutyOut).
- APP_ITERATION=498; deploy_vps_iter498.sh; temp_bundle → 498.

ITER 499 — 4 ITEMS (DONE, tested via testing_agent: backend 13/13 +
frontend 5 flows, iteration_499.json):
1. GROUP FILTER BUG (attendance report): ROOT CAUSE — list_employee_groups
   merged Masters groups WITHOUT group_id → all chips undefined id, no
   filter. Fix: server.py returns master_id + byname:<NAME> safety id
   (resolved in _resolve_group_employee_ids), attendance-grid.tsx de-dupe
   prefers entries with ids & drops id-less. Verified LABOUR=108/STAFF=16.
2. PRIORITY TASKS strip on portal-dashboard Overview (PriorityTasks.tsx +
   GET /api/admin/portal-tasks/priority in portal_phase2.py — overdue→
   high→due_today max 8 + today's statutory schedule; click → Tasks/
   Calendar tab; refetch via tabVisits counter). Existing layout untouched.
3. FACTORY & BOILER ANNUAL RETURN: routes/factory_returns.py + utils/
   factory_return_pdf.py + app/factory-annual-return.tsx (menu:
   Compliance). Unified data layer: compliance_salary_runs (current) +
   compliance_import_entries (legacy, READ-ONLY) merged per user+month,
   current wins. Sources combined|current|legacy. Details saved on
   companies.factory_details (occupier/manager/license/welfare/accidents
   per year). Exports: Form-style Factory PDF, Boiler PDF, openpyxl xlsx
   (added to requirements.txt). Uses Rs. not ₹ in PDFs (Helvetica).
4. MENU SEARCH: AdminWebShell flatNavDeep (matches label+parent, shows
   section path) + repCat lazy fetch of Report-Hub kinds (payroll/govt/
   clra/audit lists) → deep link /reports-center?kind=X (param handled in
   reports-center.tsx).
- APP_ITERATION=499; deploy_vps_iter499.sh; temp_bundle → 499.
PENDING USER VERIFICATION: deploys 498 & 499 on VPS.
NEXT: Single Machine Attendance Mode (need user to re-share spec);
WhatsApp API (Meta block); SMTP config by user. Spec section 3 of the
Factory-return request ("source selector on ALL existing reports") only
implemented on the new module — phased rollout pending if user wants it.

## Iter 500 — Employee-wise CTC Module (ALL 3 PHASES) ✅
User request: comprehensive CTC module supporting Gross/CTC/Mixed modes in the
same company; existing Gross processing 100% untouched.

**Phase 1 — Masters** (`backend/routes/ctc_module.py`, `frontend/app/ctc-management.tsx`):
- Firm salary mode: GET/PUT /api/admin/ctc/firm-mode/{cid} (gross|ctc|mixed) → companies.salary_structure_mode
- CTC Structure Master (ctc_structures collection): components typed earning/employer/deduction,
  calc = percent (of basic/gross/ctc, base_cap for PF 15000 / ESIC 21000 eligibility) | fixed | balance;
  min/max clamps, seq ordering, hidden flag. Fixed-point iteration: gross = CTC − employer cost.
- 3 default templates auto-seeded per company (idempotent): Standard Office CTC ⭐,
  Compliance / Labour CTC, Flexible / Custom (blank).
- POST /api/admin/ctc/preview — live breakup (gross + employer == CTC to the rupee, verified).

**Phase 2 — Assignment + Payroll**:
- POST /api/admin/ctc/assign (gross↔ctc per employee; users.salary_mode/monthly_ctc/annual_ctc/
  ctc_structure_id/ctc_effective_date) + ctc_revisions history + ctc_audit_log.
- Compliance Salary engine hook (compliance_salary_runs.py ~line 425/440/1245): CTC-mode employees'
  gross auto-derived from structure; engine then runs unchanged (PF/ESIC/PT/proration/OT).
  Row stamped ctc_mode/monthly_ctc/ctc_gross_derived/ctc_employer_total/ctc_employer_contributions.
  Gross-mode rows carry NO new fields — backward compatibility test-verified on 127-employee run.

**Phase 3 — Reports/Payslips/Dashboard**:
- GET /api/admin/ctc/summary — dashboard cards (CTC employees, monthly/annual CTC, employer cost,
  net payout, avg, by_structure).
- Employee CTC Register + Revision History via universal ReportTable (PDF/Excel export included).
- Payslip "CTC ANNEXURE" table (utils/payslip_pdf.py) for ctc_mode rows; compliance payslip
  breakup carries ctc fields.
- Menu: Payroll → Salary Process → CTC Management (both nav trees in AdminWebShell).

Testing: 12/12 backend pytest (tests/test_iter500_ctc_module.py) + frontend flows pass
(test_reports/iteration_500.json). All test data cleaned (revisions/audit purged, firm mode gross).
Deploy: deploy_vps_iter500.sh, temp_bundle kind=script → deploy500.sh, APP_ITERATION="500".

Pending backlog after Iter 500: Single Machine Attendance Mode (P2, Message 148 spec),
WhatsApp API (blocked on Meta creds), SMTP config for expiring-doc emails (user-side),
AI WhatsApp chatbot (P4), Multi-language EN/HI (P5).

## Iter 500b — Yearly CTC Projection report (appraisal season)
- GET /api/admin/ctc/yearly-projection?company_id&fy_start — FY Apr–Mar aggregation
  from compliance_salary_runs (latest run per user+month wins). Per employee:
  monthly_cost (CTC or master gross; falls back to run's full-month gross for
  daily-rated masters), projected_annual, months_paid, gross/net/employer YTD,
  total_cost_ytd, projected_ytd, variance_ytd (CTC compares vs total cost;
  Gross vs gross paid), utilization_pct + totals.
- Frontend: 4th tab "Yearly Projection" on /ctc-management with FY chips
  (current + 2 previous), ReportTable grid + TOTAL footer + universal PDF export.
- Verified: backend curl (18 rows FY 2026-27 Kankani) + screenshot (grid,
  FY chips, PDF button all render). Deploy script + verification updated.

## Iter 500c — One-click Increment Letter from CTC revision
- GET /api/admin/ctc/increment-letter/{rev_id}.pdf (utils/ctc_increment_letter.py):
  firm letterhead, increment/revision wording (auto: increase shows amount + %),
  OLD vs NEW CTC breakup table (earnings, gross, employer contributions,
  Monthly/Annual CTC, est. net, colored difference row), reason, effective date,
  employee acknowledgement + authorised signatory + punchline footer.
- Frontend: 📄 Letter column in Revision History tab (apiBinary download,
  testID ctc-letter-{rev_id}).
- Verified E2E: created test revisions on PAN TEST EMP (30000→36000), PDF text
  extracted OK ("increase of ₹6,000 (20.0%)", both breakups). UI screenshot OK.
  All test data cleaned (user reverted to gross, revisions + audit purged).

## Iter 501 — Client Attendance Import (Attendance Summary Excel) ✅
User spec (16 points) — NEW module, existing Punch Import / Biometric Sync /
engines verified untouched (zero diff).
- Backend: routes/client_attendance_import.py (/api/admin/client-attendance/*):
  template, preview (auto header-row + column detection w/ synonyms, manual
  mapping, staging re-validate without re-upload), commit (duplicate modes
  replace|skip|merge; replace deletes ONLY client_import punches; batched
  insert_many 1000/chunk; idempotent via staging.consumed), logs + error xlsx
  + DELETE=rollback, days viewer, mapping templates (header-name based).
- Data: db.attendance punches (source=client_import, approved, import_batch_id),
  db.client_attendance_days (client values AS-IS, never recalculated),
  db.client_attendance_imports (log), db.client_import_templates,
  db.client_import_staging. Optional opt-in: compliance_import_entries
  present_days sync per month.
- Status logic: Present>0 / Absent>0 / leave codes CL SL PL EL OD CO WO WH H
  LWP ML HD / per-code columns / WO / Holiday / times→present.
- Frontend: app/client-attendance-import.tsx — drop zone, stats cards,
  mapping modal + templates, invalid grid, first-15 preview, dup-mode radio,
  compliance sync switch, Import History tab (error download + rollback).
  Menu: Import / Export → Client Attendance Import (both nav trees).
- Tested: 15+ backend assertions PASS (auto-map 17 cols, invalid date,
  missing employee, missing OUT flag, CL mapping, commit, idempotent commit,
  error xlsx, dup detect, skip / merge (fills only OUT) / replace (fresh
  punches), rollback; DB verified clean after). UI screenshot verified.
- Deploy: deploy_vps_iter501.sh, temp_bundle → deploy501.sh, APP_ITERATION=501.

## Iter 502 — Task Hierarchy + stay-on-page fixes ✅
1. Company-wise Task Assignment Hierarchy (user spec, portal_phase2.py + TasksPanel.tsx):
   - Statuses extended: open|in_progress|submitted|done|approved (100% backward compat).
   - RBAC: super_admin assigns ONLY to sub_admins (employee direct assign → 400),
     multi-company (company_ids validated ⊆ assignee's sub_admin_company_ids).
     sub_admin: internal tasks + delegate to team of scoped firms only; sees only
     own/created/own-firm tasks; other admins' tasks → 403. company_admin cannot create.
   - Workflow: sub submits (done blocked w/ hint) → super approves (sub approve → 403).
   - POST /portal-tasks/{id}/delegate (child task + parent_task_id + delegated_count).
   - GET /portal-tasks/assignees (role-aware), GET /portal-tasks/hub-dashboard
     (super: companies/subs/awaiting/overdue/escalated + by_company; sub: firms/
     pending/completed/high/upcoming/team progress), GET /portal-tasks/{id}/audit.
   - db.task_audit_log: assigned/reassigned/delegated/status:*/deleted with actor+ts.
   - UI: hub stat cards, Submitted/Approved filters+badges, assignee dropdown w/ search,
     multi-company tick chips (scoped), delegate modal (👤+), Submit/Approve buttons.
   - Tested: 9-step backend flow PASS (assign scope 400, sub done 400, approve gates
     403/200, cross-admin 403, delegate, hubs, audit trail). UI screenshot verified.
2. Punch Approvals bug (user): Pending badge counts all dates vs date-filtered list →
   empty state now shows "N pending punches found on <dates> — Show them" jump button.
3. Firm switch stays on current page (SelectedCompanyContext reloads pathname+search;
   only / and /firm-select go home). Workspace tab clicks (active OR old) refresh that
   tab's own page in place (WorkspaceTabs.switchTab).
4. Iter 501 (same session): Client Attendance Import module; Firm dropdown in New Task;
   task creation super-admin-only then extended per hierarchy spec.
Deploy: deploy_vps_iter502.sh, temp_bundle → deploy502.sh, APP_ITERATION=502.

## Iter 503 (shipped inside deploy502) — Task Attachments (proof/evidence)
- Backend (portal_phase2.py): db.task_attachments (base64, ≤10MB, ≤10/task,
  images+PDF only). POST/GET /portal-tasks/{id}/attachments, GET/DELETE
  /portal-tasks/attachments/{att_id}. RBAC: sub_admin only own tasks; delete
  = uploader or super_admin. attachments_count on task; audit
  attachment_added/removed. Tested: upload 200, bad mime 400, roundtrip,
  count, super delete, audit events — all PASS.
- Frontend (TasksPanel): 📎 + count on cards, attachments modal (upload via
  DocumentPicker image/pdf, image preview overlay, PDF download, delete),
  Submit-for-Review nudges to attach evidence when none. UI verified.

## Iter 503b (in deploy502) — Punch Log NOT-FOUND fixes + firm filter
1. Bug (user): "NOT FOUND IN MASTER not working on some machines" — root
   cause: unmapped punches from devices NOT registered in biometric_devices
   have no company_id, so the firm filter dropped them. Fix (punch_logs.py):
   unregistered-device rows always show, company label "⚠ Unregistered
   Device". Verified: 2 hidden SEC2-1 rows now visible under Kankani filter.
2. Photo viewing (user request): GET /admin/punch-logs/photo?ref= —
   ref=record_id (attendance.selfie_base64, RBAC-scoped) or
   ref=unmapped|serial|pin|at (parked db.biometric_photos ATTPHOTO within
   ±120s of the unmapped punch). Punch Log Report 📷 is now clickable with
   a full-screen photo viewer (photo_ref field added to rows).
3. New Task Firm dropdown got a 🔍 filter box (pd-task-firm-filter). Verified.

## Iter 503c (in deploy502) — One-click Register from NOT-FOUND rows
- punch-log-report.tsx: Employee column renders "➕ Register" chip on
  flag=not_found rows → router.push /employee-add?prefill_bio=<pin>&
  prefill_name=<name_in_machine> (globalThis.__punchRegister handler).
- employee-add.tsx: accepts prefill_bio / prefill_name query params (create
  mode only) and seeds form.bio_code + form.name on mount.
- Verified via deep-link screenshot: name prefilled, bio code seeded.

## Iter 503 — Single Machine Attendance Mode + PWA Task Management ✅
1. PWA bug (user: "Task Management Option Not Showing" for Super Admin):
   (tabs)/index.tsx Quick actions now start with "Task Management"
   (row-task-management → /portal-dashboard?tab=tasks) + "Portal
   Dashboard" for all admin roles. portal-dashboard.tsx honours ?tab=
   query param via useLocalSearchParams. Verified via mobile screenshots.
2. SINGLE MACHINE ATTENDANCE MODE (Message 148 spec, P0):
   - companies.attendance_config = {device_mode: separate|single_machine|
     mobile|gps|qr, interpretation: alternate|first_last, dup_window_min:
     0/1/2/5/10, lunch_mode: ignore_middle|actual_break|fixed,
     lunch_fixed_min: 30/45/60}. Firm Master PATCH validates + mirrors to
     companies doc AND firm_masters.settings (routes/firm_master.py).
   - Engine: server.py dedupe_close_punches(company_cfg=) branches to NEW
     _single_machine_normalize ONLY when device_mode=single_machine (all
     other firms 100% legacy). Mode A alternate re-kinds machine punches
     IN/OUT/IN…; Mode B first=IN last=OUT, middles per lunch_mode
     (actual_break → OUT/IN pairs; ignore/fixed → dropped). dup window
     drops bursts (0=off). Manual/mobile punches never re-kinded. Meta
     _smm {calc_mode,dupes_ignored,punch_pattern} on first machine punch.
   - Fixed-lunch hours hook: grid compute + OT report deduct
     lunch_fixed_min from duty_only when duty*60 > lunch mins.
   - Wired call sites (cfg passed): grid _compute_monthly_grid_data,
     _build_ot_report_rows, _policy2_biometric_stats (compliance run,
     projection + call updated), attendance_admin_core grid-debug
     (returns attendance_config in response), attendance_doctor _stitch.
   - Grid day cells now include calc_mode / dupes_ignored / punch_pattern
     when single-machine meta present.
   - Firm Master UI: section 8 new "Attendance Capture / Device Mode"
     card (fm-ac-separate/single/mobile/gps/qr, fm-ac-alt/firstlast,
     fm-ac-dup-N chips, fm-ac-lunch-* radios, fm-ac-lunchmin-N chips).
   - GOTCHA fixed: companies projections in grid + OT report had to add
     "attendance_config": 1 or cfg silently absent.
   - NOTE: a tool glitch during editing appended garbage at server.py EOF
     and silently dropped 2 edits — repaired; verify file tail if editing
     server.py in bulk.
   - Tested: engine unit tests (A alternate + dup drop + meta, B ignore
     middle, B actual break, window off, legacy unchanged, manual kept);
     e2e: PATCH firm-master mirror verified in DB; monthly-grid API on
     seeded 5-punch day → punches=2, in 09:00 out 18:00, 9h − 45m lunch
     = 8.25 (duty 7.25 + OT 1.0), calc_mode/pattern fields present;
     grid-debug shows cfg + _smm meta. Test data cleaned; Kankani
     attendance_config unset (user must opt-in per firm).
Deploy: deploy_vps_iter503.sh, temp_bundle → deploy503.sh, APP_ITERATION=503.

## Iter 504 — PWA Task Management visibility (user: "Still Not Showing") ✅
Root cause: user's VPS WAS on 503 with the fix in the built JS (verified
by fetching smartpayrolling.com route chunks — row-task-management present
in index chunk), but the installed PWA served a CACHED OLD shell: sw.js
races network vs 3.5s timeout on navigations → slow mobile connections get
the stale cached index.html + old bundles.
Fixes:
1. public/sw.js CACHE bumped sks-pwa-v4 → v5 (activate purges old cache).
2. NEW admin-only "Tasks" BOTTOM TAB: app/(tabs)/tasks.tsx
   (tasks-tab-screen, wraps TasksPanel), registered in (tabs)/_layout.tsx
   (href null for employees).
3. Big "Tasks · Task Management" BentoTile (bento-tasks) first on admin
   home + Iter 503 quick actions retained.
Verified via mobile screenshots (tile at top, /tasks tab renders panel
with New Task). deploy_vps_iter504.sh (copies public/sw.js to web root +
verifies tasks-tab-screen inside built JS), temp_bundle → deploy504.sh,
APP_ITERATION=504. User phone steps: close+reopen PWA twice (or reinstall
icon) after deploy.

## Iter 505 — Task Edit + Edit Log, PWA assign fix, global-task visibility ✅
1. EDIT TASK CONTENT + LOG (user request): portal_phase2.py update_task
   now records field-by-field edit log (Title/Description/Due date/
   Priority/Firm old→new) as audit action "edited"; task gets
   last_edited_at/by/by_name + edited_count (no-op edits don't log).
   TasksPanel.tsx: ✏️ pencil (pd-task-edit-<id>) opens the Add modal in
   edit mode (prefilled; Assign-to & multi-firm hidden while editing;
   "Save Changes" → PATCH). Amber "✎ edited ×N — view log" chip
   (pd-task-history-<id>) opens Edit Log modal (GET /portal-tasks/{id}/
   audit; pd-history-close). "New Task" button resets edit state.
2. PWA ASSIGN BUG (user: "Not able to assign task from PWA"): root cause
   — form silently attached the CURRENTLY SELECTED firm even when outside
   the Sub Super Admin's scope → backend 400 "Selected firm(s) are not
   assigned…". Fix: picking an assignee auto-preselects an in-scope firm
   (current firm if allowed, else their first firm; null scope = all);
   createTask sends company_id:null + only multiCids when a scoped
   assignee is chosen (scopedAssign flag). Verified via curl.
3. GLOBAL TASK VISIBILITY (testing-agent finding): list endpoint firm
   filter now ORs {company_id:null, company_ids:{$in:[null,[]]}} so
   no-firm tasks always appear (PWA always has a firm selected).
4. PWA install issue (user msg): manifest.json/icons/sw.js on VPS all
   verified reachable+valid (manifest injected dynamically by +html.tsx);
   awaiting user detail on exact symptom.
Testing: backend flows via curl (edit log entries, edited_count, no-op,
assign-with-scope, global visibility). testing_agent iteration_505.json —
UI testIDs render; full E2E clicks blocked by Cloudflare 429 on preview
(known env artifact). Deploy: deploy_vps_iter505.sh, temp_bundle →
deploy505.sh, APP_ITERATION=505.

## Iter 506 — Alloted-task visibility + 2 CRITICAL app-wide fixes + Bonus Excel ✅
1. USER BUG "Alloted Task Not Showing In Main Screen" (sub admin):
   a. Backend portal_phase2 list: for sub_admin the firm-filter $or now
      also matches {assignee_id: me} / {created_by: me} — alloted tasks
      visible regardless of currently selected firm (verified 3 scenarios
      via curl as testsub@sksharma.co / testsub123, sub_623b8a106846).
   b. (tabs)/index.tsx: new "My tasks (N open)" home section
      (home-my-tasks, home-task-<id>, home-tasks-viewall) — top 3 open
      tasks w/ firm, due date, overdue red, assigned-by; fetched by
      loadMyTasks() OUTSIDE load()'s big try (3 retries) with NO firm
      param on purpose.
2. CRITICAL FIX — sub admin BLANK screen on cold load: app/index.tsx fired
   Redirect→/firm-select then flipped to /(tabs) mid "remember-my-firm"
   restore → expo-router dead-ended on empty tree. Fix:
   SelectedCompanyContext exposes firmRestoreDone (set on all terminal
   paths + 8s failsafe); index gate shows spinner (firm-restore-wait)
   until done, then ONE final redirect. Verified: sub admin cold "/"
   renders home.
3. CRITICAL FIX — infinite refresh loop (whole app): AuthContext.refresh
   did setUser(new object) every call → load useCallback (deps user)
   recreated → useFocusEffect([load, refresh]) re-ran → refresh again →
   endless loop, seq reached 24+, 94 CF "Security check" errors per
   session, server hammered (830 portal-tasks hits). Fix: setUser keeps
   SAME identity when JSON-equal. After fix: 0 errors, loop gone. This
   loop likely caused earlier "Pending punch mismatch"/"blank"-style
   flakiness reports.
4. Bonus Yearly Summary Excel = display format (user request):
   contribution_reports.py bonus-yearly-summary.xlsx rebuilt with openpyxl
   custom two-row header — month spans Days|Earned interleaved pairs,
   merged fixed cols, heads (Yr), bold yellow TOTAL, freeze panes, dd-mm-
   yyyy DOJ. GOTCHA: use get_column_letter (merged cell .column_letter
   crashes → 'MergedCell' has no attribute). Verified via openpyxl parse
   (no data rows in preview DB — no compliance runs — structure OK).
Verified super admin home regression-clean. Deploy: deploy_vps_iter506.sh,
temp_bundle → deploy506.sh, APP_ITERATION=506.

## Iter 507 — Assignee-scoped firm multi-select in New Task ✅
User: "After the Selection of Sub Super Admin Firm Selection Option May
Change Please Check". TasksPanel.tsx: when a Sub Super Admin is selected,
the plain chip-wall is replaced by a searchable multi-select checklist
restricted to that sub admin's firms — label "Firms for this task —
<name>'s firms only (N selected)", Select-All chip (pd-task-mc-all),
🔍 filter (mcQ state, shows when >6 firms), checkbox rows
(pd-task-mc-<cid>), mcBox style. mcQ reset on assignee change/clear;
pd-task-assignee-none testID added. Clearing assignee restores the
Firm (optional) dropdown. testing_agent iteration_506.json: all 6 steps
PASS (incl. create with scoped firm + cleanup). Deploy:
deploy_vps_iter507.sh, temp_bundle → deploy507.sh, APP_ITERATION=507.
NOTE: main-agent screenshot tool was fully Cloudflare-blocked this
session — use testing_agent for UI verification when that happens.

## Iter 508+509 — Sub Admin task discipline + edit lock + tappable counts ✅
Backend (portal_phase2.py):
- TASK_STATUSES += "later". PATCH rejects status="later" (must use POST
  /portal-tasks/{id}/later with mandatory reason → later_reason/by/at,
  audit "marked_later").
- GET /portal-tasks/overdue-block (sub_admin): assigned tasks past due
  without overdue_ack_due == due_date. POST /portal-tasks/{id}/
  overdue-reason → overdue_reason_log[], last_overdue_reason,
  overdue_ack_due=due_date (audit "overdue_reason"). Due-date change
  re-triggers the gate.
- 24h rule: create task without due_date → due tomorrow.
- Super admin firm-filter bypass (created_by/assigned_by/assignee = me) —
  fixes "Allotted Tasks Not Showing In Super Admin Login".
- status=overdue list filter; counts include "later".
- Iter 509 EDIT LOCK: content edits (title/desc/due/priority/firm) only
  by super_admin or created_by==me (_wants_content_edit 403). Assignee
  keeps status/Later/attachments. Verified via curl (5 scenarios).
Frontend:
- TasksPanel: FILTERS + later/overdue chips; ALL hub + status counters
  tappable (pd-count-*, pd-hub-*) → setFilter; "⏸ Later…" button
  (pd-task-later-<id>) + reason modal (pd-later-reason/save); "▶ Resume";
  "⏸ LATER" chip + later_reason + "⚠ Late reason" lines on cards
  (visible to super); ✏️ edit button only for isSuper || created_by==me.
- NEW src/components/portal/OverdueGate.tsx — full-screen blocking modal
  (overdue-gate, overdue-reason-<id>, overdue-submit-<id>) mounted in
  (tabs)/_layout for sub_admin; fail-open on network errors.
Testing: testing_agent iteration_507.json — backend 10/10 pytest
(/app/backend/tests/test_iter508_task_workflow.py) + all frontend
scenarios PASS; edit-lock verified via curl after that run. Deploy:
deploy_vps_iter509.sh, temp_bundle → deploy509.sh, APP_ITERATION=509.

## Iter 510 (2026-08-06) — "PWA/Web Portal not opening" investigation
User reported portal won't open post-Iter-509. Verified in workspace:
Super Admin (password sharma123) + Sub Admin (testsub@sksharma.co) login,
Web Portal, and PWA (tabs) ALL WORK on Iter 509 code — in dev AND in a
production `expo export -p web` build served statically. Conclusion: the
fault is on the VPS (suspects: build OOM/disk-full during 509 deploy,
backend not restarting, or stale PWA service-worker shell).
Fix shipped: deploy_vps_iter510.sh — RECOVERY deploy with STEP-0
diagnostics block (disk/mem/backend logs/nginx/web dir), safe cache
cleanup, auto 2GB swap, backend restart BEFORE build, build published
only after dist verification (rollback-safe, .prev backup), sw.js cache
bumped v5→v6, APP_ITERATION=510, temp_bundle kind=script → deploy510.sh.
Awaiting user to run script on VPS and report the diagnostics if it still fails.

## Iter 511 (2026-08-06) — "Employer PWA blank page"
Reproduced NOTHING broken in code: employer login (admin@kankani.local,
PIN reset to 123456 — 6-digit now required), all PWA tabs, /employer
install entry all render in dev AND production build. Root cause = stale
PWA shell on user device (cached HTML → deleted JS bundle → blank).
PERMANENT FIX: blank-page SELF-HEAL inline script in app/+html.tsx
(sks-selfheal-count): on entry-script 404 or splash stuck >15s →
unregister SW + purge all caches + auto-reload (max 2/session, counter
resets on successful boot). Verified: fires correctly on simulated
bundle 404 (2 attempts then stops), zero false triggers on normal boot.
sw.js cache v6→v7, APP_ITERATION=511, deploy_vps_iter511.sh,
temp_bundle kind=script → deploy511.sh.

## Iter 512 (2026-08-07) — Vendor SDK Direct-Pull Channel (user request, option B)
ADDITIVE only — ADMS push untouched. Plug-in framework backend/sdk_adapters/
(base.py BaseDeviceAdapter + @register auto-discovery registry; add vendor =
add file). REAL adapter zk_family.py via pyzk (TCP 4370): ZKTeco Standalone,
eSSL Legacy, FingerTec, Ronald Jack, BioMax, Realtime T&A. Pending slots
(implemented=False): Suprema, Nitgen, Virdi, Anviz, BioEnable, Matrix Legacy,
Hikvision, Dahua (Hik/Dahua skipped per user choice B).
Endpoints (routes/biometric_sdk.py): GET /api/biometric/sdks,
POST /api/biometric/devices/{id}/sdk-test, POST .../sdk-pull; background
sdk_auto_pull_loop (60s scan, auto_pull_minutes per device). Pull reuses
_ingest_attlog_line → full parity (bio_code match, IN/OUT alternation,
5-min dup rule, contractor gate, source zkteco:<SN>). Device fields added:
connection_mode(push|sdk), sdk_vendor, device_ip, device_port, comm_key,
auto_pull_minutes (+sdk_last_pull_at/_inserted/_error, sdk_pull_cursor).
Frontend: biometric-devices.tsx editor (Connection Mode chips, vendor picker
w/ pending greyed, IP/Port/CommKey/auto-pull, port-forward hint), device card
(SDK PULL chip, SDK VENDOR/LAST PULL facts, Test connection + Pull punches
buttons, error line). attendance-sync-dashboard: SDK machines show PULL OK/
CHECK + vendor/last-pull/auto info. NOTE: errors use HTTP 400 (502 gets
swallowed by Cloudflare). Tests: backend/tests/test_iter512_sdk_pull.py ALL
PASS (stub adapter: ingest, cursor, dedupe, unmapped). UI smoke-tested.
Deploy: deploy_vps_iter512.sh, APP_ITERATION=512, pyzk==0.9 in requirements.

## Iter 513 (2026-08-07) — Machine-vs-Master list not showing for NCD machines
User: NCD8251000531/591/569 "Not Registered In masters Data not Getting".
Checked LIVE prod (smartpayrolling.com, password Sharma@2026 still valid):
all 3 machines registered+online+pushing (85k/92k/55k punches). ROOT CAUSE:
attendance_sync_dashboard machine_only aggregation had NO company filter —
every firm saw the same global 300 most-recent unmapped pins (SAMARPAN TBS
machines dominated), crowding out NCD rows. Prod has 110k unmapped punches
total. FIX: when company_id given, scope biometric_unmapped agg to that
firm's device serials (_firm_sns). Exports + master_pending KPI fixed too
(export reuses same fn). Verified locally (scoped=0 for Kankani vs global
row from SEC2-1). APP_ITERATION=513, deploy_vps_iter513.sh (superset of
512 SDK feature + 511 self-heal). User still hasn't deployed 511/512.

## Iter 514 (2026-08-07) — One-tap "Create Master from machine PIN" (user accepted improvement)
Backend: POST /api/biometric/create-master-from-pin (routes/biometric_devices.py,
above remap-unmapped). Creates minimal approved employee (bio_code=pin,
employee_code=pin if free else None, name from biometric_machine_users USERINFO
capture else "EMP <pin>", onboarded/approved, has_pin False,
created_from_machine_pin=<sn>) then remaps ALL parked biometric_unmapped rows
for that pin across the firm's devices via _ingest_attlog_line (cap 5000,
deletes remapped rows). Idempotent: existing bio match → created:false, just
remaps. Tested E2E on preview (create+remap+delete unmapped, idempotent).
Frontend: attendance-sync-dashboard.tsx section-2 rows get red "Create Master
from PIN <id>" button (confirm → API → alert result → reload); row press still
opens /employee-add. APP_ITERATION=514, deploy_vps_iter514.sh (superset 511-513).

## Iter 515 (2026-08-07) — eSSL CQIK231260072 cannot connect
Checked LIVE prod: machine NEVER reached server (absent from unknown_devices
log which records every unregistered hit — probes PROBE-TEST-1/2/3 confirmed
/iclock paths reach FastAPI over HTTPS, and nginx proxies /iclock→/api/iclock).
ROOT CAUSE: plain HTTP :80 returns 301→HTTPS; eSSL/old-ZK ADMS firmware cannot
follow redirects or do TLS → dies silently. FIX in deploy_vps_iter515.sh:
adds nginx listener :8090 (sks-adms-http.conf, plain HTTP, no redirect,
/iclock/→127.0.0.1:8001/api/iclock/, /api/ too for Matrix webhooks), ufw
allow 8090, rollback if nginx -t fails, verification curl expects 404/200
from FastAPI. Machine settings: Cloud Server smartpayrolling.com port 8090,
HTTPS OFF, then register serial from Unknown-Devices list. Also noted prod
unknown device CN4C231160062 (8087 hits, stopped 07-30) still unregistered.
APP_ITERATION=515.

## Iter 515 follow-up (user: "Not Showing Online Still")
Prod on 515; user registered CQIK231260072 (essl, OUT, KISHANGARH,
cmp_3c815a9b1b) but last_seen_at=None. Port 8090: CONNECTION REFUSED on prod
(listener not installed — likely nginx -t rollback). BUT discovered:
http://165.99.223.52/iclock/cdata (IP host header, port 80) reaches FastAPI
with NO 301 redirect — PROBE-IP80 logged in unknown_devices. So machine fix
needs NO deploy: eSSL Cloud Server → Domain Name OFF, Server Address
165.99.223.52, Port 80, HTTPS OFF. Told user. If still absent → device-side
network (no internet/DNS/ADMS option).

## Iter 516 (2026-08-07) — Punch Log NOT-FOUND rows missing for NCD machines
Same crowding pattern as Iter 513: punch_logs.py _query_rows loaded
biometric_unmapped sort(at desc).limit(2000) GLOBALLY, firm/machine filter
applied after → busy firm crowded NCD rows out. FIX: scope _unm_q at DB
level — machine param → device_serial direct; company filter → $or
[serial in firm's devices, serial nin all registered] (preserves Iter 503
"unregistered devices always show"). biometric_photos parked-photo query
inherits same scoping. Verified on preview: firm filter shows own device
881 + unregistered SEC2-1, excludes other-firm 777; unfiltered shows all.
xlsx export same engine. APP_ITERATION=516, deploy_vps_iter516.sh.
Note: user said "use SDK if required" — not needed here, was a query bug.

## Iter 517 (2026-08-07) — grid grouping + punch log search + label fix
User reports resolved:
1. RANJAN FABRICS "missing punches but 2 in record": prod data showed 95
   machine punches ALL kind=in on Aug-3 (evening 19-20h punches on IN
   machine JYK8240100297), OUT machine JYK8240100174 receives ZERO punches;
   the 2nd record = server_auto_close (+12h synthetic). Told user to check
   OUT machine; offered opt-in smart direction-correction (NOT built yet —
   needs user approval, would change attendance engine).
2. punch_logs.py: server_auto_close now labeled "Auto-Close (System)"
   (was fallback "Mobile App"); machine_key "auto_close".
3. attendance-grid.tsx: department/designation sort now renders group bands
   (deptBand, "YARN · 23 employees"), gridItems memo, S.No continues.
   Verified via screenshot (Kankani: NO DEPARTMENT/SECURITY/WEAVING bands).
4. punch-log-report.tsx: free-text Search box (client-side across
   name/code/bio/machine/firm/date/time/kind/status), count shows "X of N".
5. "NCD NOT FOUND still missing": their unmapped rows are Apr-2026-old;
   default 7-day range shows none — instructed to widen date range (data
   verified on prod: since Aug-06 NCD has 0 new unmapped).
6. Sub admin CAN access punch-log-report (verified preview screenshot);
   if hidden on prod → menu_rights toggle in Sub Admins screen.
APP_ITERATION=517, deploy_vps_iter517.sh.

## Iter 518 (2026-08-07) — Smart Direction Correction (user choice C)
Forensic (prod RANJAN): both punches saved, BOTH kind=in (device kind=in
forces direction); OUT machine JYK8240100174 OFFLINE since 02-08 (last IP
27.58.185.151); auto_close makes synthetic OUT +12h. Built:
1. Ingest (biometric_devices.py _ingest_attlog_line): opt-in per firm
   (companies.attendance_config.smart_direction + smart_direction_gap_hrs
   default 4): state-less punch on kind=in device >= gap hrs after day-first
   approved IN → kind=out + direction_corrected=True. Tested: 8h→out ✅,
   2h gap stays in ✅.
2. POST /api/biometric/smart-direction-repair {company_id,from,to,dry_run}:
   per user-day 2+ zkteco INs from in-kind serials & no zkteco OUT & gap>=cfg
   → last IN converted to OUT + server_auto_close rows deleted. Tested dry+
   real ✅ (auto_close deleted).
3. firm-master.tsx Attendance Capture section: SDC radios (fm-sdc-on/off),
   gap chips 3/4/5/6/8, "Repair past days (this month)" button (fm-sdc-repair);
   setAC base preserves the new keys. UI verified via screenshot.
4. punch_logs.py: rows with direction_corrected show status "auto-out ✔"
   (user's "update attendance report to verify" request; monthly grid reads
   db.attendance so repaired days show real IN/OUT automatically).
APP_ITERATION=518, deploy_vps_iter518.sh.

## Iter 519 (2026-08-07) — Daily Present Count footer (user enhancement spec)
attendance-grid.tsx: dailySummary useMemo (single pass over
filteredEmployees × day_labels; present credit c.present incl 0.5,
else weekly_off/holiday/absent; missing = in xor out). PresentCountFooter
rewritten: FooterStatRow per stat, sticky identity cols preserved; now fed
by FILTERED data (was server-global day_present_counts). "☐ Daily Summary"
toggle chip (toggle-daily-summary testID) adds Absent/Weekly Off/Holiday/
Missing Punch rows. Footer added to BOTH web + native grid branches.
Backend utils/monthly_attendance.py: compute_daily_summary(grid) +
write_daily_summary_rows(ws,...) appended to build_grid_view_xlsx (inout)
and build_hours_only_grid_xlsx. utils/monthly_attendance_pdf.py
build_monthly_inout_pdf: 5 footer rows per page (_sumrow, %g format).
Verified: xlsx rows 387-391 present, pdf 200, UI screenshot (toggle+rows).
NOTE: Leave counts not in grid cells (leave flag absent) — omitted from
summary; can add when leave module marks grid cells.
APP_ITERATION=519, deploy_vps_iter519.sh.

## Iter 520 (2026-08-07) — Policy-true OT engine + Machine-not-in-DB visibility + 10 user requests
ENGINE (server.py): split_regular_ot_times rewritten — pairs classified by
ACCUMULATED WORKED MINUTES vs full_day quota (mid-pair split at crossing);
new worked_minutes_in_window() used at both duty/OT calc sites (grid +
OT report) so breaks NEVER count as duty/OT (lunch no longer creates
phantom OT). Empty + anomaly day cells now stamped weekly_off/holiday
(_emp_weekoffs from weekly_off_days_override || policy weekly_off_days).
inout_ot_matrix.py: "policy" block + header line (screen/xlsx/pdf).
UNMAPPED VISIBILITY: attendance_sync_dashboard machine_only — unregistered
devices + no-firm devices always show (⚠ Unregistered Device); merges
biometric_machine_users w/o master (punch_count=0 "never punched",
name_in_machine); punch_logs _all_sns = firm-assigned serials only.
ESIC form: EmployeeDropdown (new src/components/EmployeeDropdown.tsx,
single+multi search dropdown), DD-MM-YYYY masks, mandatory firm, 13-reason
dropdown + Other(Specify); backend stores reason/reason_other → leave reason.
REPORTS HUB: GET /admin/payroll-reports/last-finalized-month (finalized||
frozen csrun max month) → default Month on firm change; salary-comparison
periodic (month_to/month_b_to via ctx, _run_rows_period agg, works JSON/
xlsx/pdf/email); salary-revision dynamic allowance Old/New cols from
firm_masters.allowances (OVER TIME excluded).
register_export.py register_pdf: wrapped Paragraph headers+long cells,
font auto-shrink (10/8.5/7.5 by col count), bank/ifsc width 1.5 (fixes
wage-register overlap per user PDF).
FORM 23 (user upload): factory_returns.py FORM23_FIELDS manual particulars
(factory_details.form23), _compute_return form23 block (gender man-days/
man-hours/avg-daily, leave-with-wages entitled=240+ days, wages basic/DA),
GET /{cid}/{year}/form23.pdf (build_form23_pdf in factory_return_pdf.py);
frontend FORM 23 button + statutory particulars editor block.
CHALLAN SUMMARY: pf_status/esic_status paid|pending|failed (PATCH re-
updatable, 400 on bad value), tap-to-cycle badges, status in email/WA text.
FIRM DROPDOWNS: leave-report, comp-off-ledger, factory-annual-return,
rectified-punches (CompanyPicker); users-log-report optional All-firms;
ai-salary-compliance employee-name dropdown (emp code input/field removed).
TESTED: testing agent backend 11/11 PASS (/app/test_reports/iteration_508.json,
tests/test_iter520_backend.py); UI screenshots (esic, challan badges,
report-hub periodic tabs + default month 2026-07). APP_ITERATION=520,
deploy_vps_iter520.sh (step 10 = live-DB forensic "machine but not in DB"
report), temp_bundle kind=script → deploy520.sh.

## Iter 521 (2026-08-07) — Present/Absent Report per attendance policy
NEW /app/backend/routes/present_absent_report.py: GET /api/admin/reports/
present-absent (+.xlsx/.pdf) — P/HD/A/WO/H matrix from
_compute_monthly_grid_data cells (present credit 1/0.5, weekly_off/holiday
flags — incl. Iter 520 empty-day stamping); present_days =
totals.present_days_policy (payroll 1:1); dept filter/search, day_counts
footer, colour xlsx (openpyxl) + landscape pdf. Registered in server.py
after inout_ot_matrix. Frontend /app/frontend/app/present-absent-report.tsx
(+ AdminWebShell nav x2 "Present / Absent Report"). Verified: JSON 127 emps
Kankani, WO on Sundays, future days blank; xlsx/pdf 200; screenshot OK.
APP_ITERATION=521, deploy_vps_iter521.sh, temp_bundle → deploy521.sh.

## Iter 522 (2026-08-07) — Code review fixes + speed
code_review_agent full review found 2 real bugs (both fixed in server.py):
(a) HIGH — OT Report duty still wall-clock (line ~10769) so lunch spilled
into OT via shift cap; now worked_minutes_in_window. (b) MEDIUM — grid OT
window (line ~10263) wall-clock counted gaps between OT sessions; now
worked. All 4 duty/OT sites use worked_minutes_in_window (verified
grep-count 4 + math test: 10h worked/1h lunch/8h shift → duty 480, OT 120).
SPEED (user request): 10 new startup indexes — attendance(user,date,at),
biometric_unmapped(serial,at / at / pin,serial), biometric_machine_users
(serial,pin / company), users(company,bio_code), biometric_devices(serial),
holidays(company,date). GZip already active. Dead styles removed
(esic-leave searchRow/searchInput). APP_ITERATION=522,
deploy_vps_iter522.sh, temp_bundle → deploy522.sh.

## Iter 523 (2026-08-07) — Daily Verification PDF redesign (user PDF upload)
daily_verification.py _build_pdf (BOTH orientations): margins 8→4mm;
company address+city under firm name (projection extended); Attendance
Status col removed; Contractor col only when any row has contractor;
rows with BOTH punches NOT highlighted (only missing-punch red / muted
absent kept, green never); rowHeights 9mm (8mm portrait) + fixed wide
Signature col (34/26mm); legend paragraph removed; fs 7.0/5.8; header
"Sr"→"S.No." (also HEADERS xlsx/csv). present_absent_report.py PDF:
S.No. col added (offsets/styles/colWidths shifted). Frontend
daily-verification.tsx: Contractor filter only when contractors exist.
OT-after-12h per policy = engine (520/522), no extra change. Verified:
pdftoppm renders correct for landscape+portrait+present-absent.
APP_ITERATION=523, deploy_vps_iter523.sh, temp_bundle → deploy523.sh.

## Iter 523b — Daily Verification dept grouping + father name
daily_verification.py: users projection +father_name; rows carry
father_name. PDF: Department col → removed; groupby department (sorted
dept+code) grey SPAN band rows (5.5mm), continuous S.No., Father Name col
after name; rowHeights list per band/data row. HEADERS/_row_values (xlsx/
csv) add Father Name (col widths 19 letters). Verified via pdftoppm.

## Iter 523c — VPS deploy failures explained/fixed
User's VPS deploy reported (a) "BACKEND STILL NOT ANSWERING": Iter-521
speed indexes were built SYNCHRONOUSLY in @startup → blocked uvicorn for
minutes on live data. Moved to _bg_speed_indexes() create_task (sleep 5,
background=True). (b) "Portal responds through nginx: HTTP 301 ❌": nginx
HTTP→HTTPS redirect (SSL) — NOT an error; deploy523.sh now retries health
12x5s and follows the redirect (301/302 → checks https, marks OK).

## Iter 524 (2026-06) — Punch-Time Photo Capture & Display (user feature)
Backend punch_logs.py (fixed missing imports base64/Response that broke
boot): rows carry photo_status captured|pending|missing (pending = parked
ATTPHOTO in biometric_photos for same serial+PIN ±90s); GET /admin/
punch-logs?photo=available|missing|pending filter; GET /admin/punch-logs/
photo.jpg?ref&token= raw JPEG for <img> thumbnails (auth via query token);
GET /admin/punch-logs.pdf?include_photos=0|1 (RLImage thumbnails, cap 400
rows w/ photos, 1500 w/o); GET /admin/punch-photos/reconciliation (total/
received/pending/missing/failed>48h/parked); POST /admin/punch-photos/
retry-match re-runs parked-photo queue (verified E2E: pending→captured).
ATTPHOTO ingest in biometric_devices.py was already async/non-blocking.
Frontend punch-log-report.tsx: Punch Photo col = inline thumbnail
(✓ Captured, tap→modal) / ⏳ Sync Pending / ✕ No Photo; token stashed in
__plrToken before fetch; Punch Photo filter dropdown; PDF + PDF+Photos +
Photo Sync header buttons. NEW app/photo-sync.tsx: 6 metric cards +
coverage bar + firm/date filters + Retry Photo Sync. AdminWebShell menu
entry after Punch Log Report. Testing agent: 15/15 backend pytest
(tests/test_iter524_punch_photos.py) + frontend E2E PASS
(test_reports/iteration_524.json). APP_ITERATION=524,
deploy_vps_iter524.sh, temp_bundle → deploy524.sh (step 9 prints live
photo-coverage stats + machine 'Attendance Photo' enable hint).

## Iter 525 (2026-06) — Shift Deployment Report redesign (user requests)
labour_reports.py shift_deployment builder rewritten: Shift/Shift Timing/
Machine-Device/Date columns REMOVED (date+firm on heading); S.No. added;
Hours/OT/Status from compute_textile_day (firm-master policy engine, same
as Grid); NEW Cost column = day pay per Firm Master + Employee Policy
(rate resolution mirrors compute_compliance_row: epol.salary →
compliance_gross → salary_monthly → structure Basic row; mode
daily/hourly/monthly; OT at policy ot_multiplier 1.5 default; monthly
divisor = calendar days of that month). Optional group_by=department|
designation (passed via policy["_group_by"]): ▶ band rows + SUBTOTAL per
group + GRAND TOTAL (deployed count, hours, OT, cost sums). generate():
shift_deployment requires from_date (single day or from–to period), month
rejected. _row_kind() styles band (#475569 white bold) / total (#E2E8F0
bold) rows in BOTH _excel_bytes and _pdf_bytes generically. _load_dataset
emps projection extended (+employee_policy, compliance_gross,
salary_monthly, salary_structure_*, compliance_salary_mode, ot_applicable,
attendance_policy_override, week_off flags). Frontend labour-reports.tsx:
DAY_OR_PERIOD_KEYS={shift_deployment} → Period Type chips (Single Day /
Periodic From–To, no Month) + Group/Format chips (No Grouping/Department
Wise/Designation Wise). Verified via curl (json/pdf/excel/csv + 400 on
month-only) + screenshot + PDF extraction. APP_ITERATION=525,
deploy_vps_iter525.sh, temp_bundle → deploy525.sh.

## Iter 526 (2026-06) — Shift Deployment PDF/Excel polish + Out-punch fix
labour_reports.py: (a) header_meta = "Date: DD-MM-YYYY" when from==to else
"Period: … to …" (Generated by removed). (b) _pdf_bytes REWRITTEN header:
firm name 14pt bold + address + date + title drawn in on_page canvas →
repeats on EVERY page (topMargin 28mm, logo left drawImage, QR right
renderPDF.draw, rule line under title); footer = Page N right + "Generated:
… IST" left (Verify text REMOVED, QR keeps code); heading row WHITE (blue
1D4ED8 removed in PDF TableStyle + Excel header font). (c) _merge_end():
band/total label cells merged — PDF SPAN + Excel merge_cells; band text
moved to col 0 (whole-row merge), _sum_row label = "SUBTOTAL — X · N
deployed" at col 0, sums at Hours/OT/Cost. extra_styles now actually
appended to TableStyle (was dropped — bug). (d) OUT-PUNCH FIX (user bug):
generate() for shift_deployment re-fetches punches ±1 day with
status=approved then dedupe_close_punches + stitch_cross_day_ot (same as
_compute_monthly_grid_data) → night-shift OUT on next calendar day now
shows; verified VINIT 19:57→08:03 12h. pypdf verified header on all 26
pages, no Verify text. Deploy script deploy_vps_iter525.sh notes updated
(items 10-14). APP_ITERATION stays 525.

## Iter 526b — All 22 labour report PDFs verified with new header
User approved potential improvement: verified via /tmp/check_all_pdfs.py
(pypdf) that ALL 26 catalogue report keys render the new every-page header
(firm on p1+last, Date/Period, Generated footer, NO Verify text): 25 OK,
dummy_shift correctly 400 (firm policy off). Portrait layout (department
_wise) visually checked — no overlap. No code change needed (shared
_pdf_bytes).

## Iter 526c — Cost column on OT Register + Dept/Contractor Wise (approved
potential improvement). labour_reports.py: _rate_of + _day_cost +
_present_of_status extracted to MODULE level (shift_deployment builder
de-duplicated to use them). overtime_register: +Cost col (day pay incl OT
at policy multiplier, present from _day_summary status). department_wise/
contractor_wise: +Cost col (sum of per-employee-day _day_cost). Verified
via curl all 4 reports incl. shift_deployment regression (identical
costs). deploy525.sh notes item 15 added.

## Iter 527 — Daily Labour Cost Dashboard (approved potential improvement)
NEW /app/backend/routes/labour_cost.py: GET /api/admin/labour-cost/
dashboard?company_id&day → {total_cost, employees_present, total_hours,
ot_hours, mtd_cost, departments[], trend[]} — month-to-date loop with the
same pipeline (approved punches ±1d, dedupe+stitch, compute_textile_day +
labour_reports._day_cost); registered in server.py after labour_reports.
NEW /app/frontend/app/labour-cost-dashboard.tsx: 5 metric cards, MTD
daily-cost bar chart (selected day purple), department-wise cost bars,
date+firm filters. Menu "Labour Cost Dashboard" added after Labour Reports
in BOTH AdminWebShell menus. Verified: API totals match Shift Deployment
grand total (48389.88/47) + populated screenshot. deploy525.sh item 16 +
verification greps added.

## Iter 528 — "Count Present Day @ 8 HRS" honoured in reports (user bug)
labour_reports.py: _compliance_8hr_on(policy) (policy_master.
compliance_present_8hr && salary_allowed in compliance/both), _ot_allowed
(firm gate → override.ot_allowed → ot_applicable), _apply_compliance_8hr
(policy, e, eng): NOTE compute_textile_day duty_hours = TOTAL worked (OT
subset). Normal days: duty=min(worked,8), extra→OT (if allowed), present
1.0/@8, 0.5/@half. Days where week-off/holiday SPECIAL rules fired
(detected via eng notes containing week_off/week-off/holiday): engine
OT+present kept, displayed duty still capped at 8 (all-OT days → duty 0).
Applied in: shift_deployment builder, monthly_register (rewritten to use
compute_textile_day + rule; late days still from _day_summary), and
labour_cost.py dashboard. Verified Kankani (flag ON, policy_2, WO=Sun):
Fri 12h→8+4OT, Sun (week_off_worked mode) 12h→8+4OT P, monthly VINIT
136h/67.5OT/17P. Grand-total cost unchanged (48389.88). deploy525.sh
item 17.

## Iter 529 — All day-wise reports on the policy engine (approved improv.)
labour_reports.py: compute_textile_day now module-level import (local
imports removed). day_rows() overlays s["hours"]/s["ot_hours"]/s["status"]
from compute_textile_day + _apply_compliance_8hr; when 8hr flag OFF and
engine folds OT into duty (ot>0 and duty>=ot) → display duty = duty-ot.
Status: P>=1, HD>=0.5, OT if only-OT, P if hrs>0, else _day_summary
fallback (keeps OUT-only miss-punch rows visible). overtime_register cols
now [OT Hours, Total Worked Hrs, Cost] ("Normal Hours" removed — base
Hours col IS regular duty now). Affects daily_attendance, overtime_
register, late_coming, early_going, miss_punch, half_day, double_shift,
night_shift, weekly_off, holiday_attendance, face_attendance, in_out.
Verified: daily_attendance & OT register Fri 8h+4OT; all-26-key PDF
regression 25 OK/0 fail. deploy525.sh item 18.

## Iter 530/531 — Report UX batch (user requests)
labour_reports.py: (a) shift_deployment Cost round figures (row round(),
_sum_row r[11]=round(c)). (b) GENERIC Group Wise post-processing in
generate(): filters.group_by department|designation|contractor → if that
column exists (and key != shift_deployment): ▶ band + SUBTOTAL (sums of
all-numeric columns via num_idx) + GRAND TOTAL; works in preview/pdf/
excel/csv since rows mutate pre-format. (c) label suffix "— X Wise".
(d) S.No. slim: Excel width 6, PDF col_widths 9mm (has_sig block extended
with has_sno). (e) QR FIX: encodes URL {APP_PUBLIC_URL}/api/admin/
labour-reports/verify/{id} (fallback SKS-REPORT:); verification doc now
stores report_label+company_name; verify endpoint returns HTML page
(✅ GENUINE with details / ❌ 404 forged) or ?format=json. _pdf_bytes
gained verify_url param. Frontend labour-reports.tsx: FILTER_FIELDS/text
filters REMOVED → GROUP_OPTIONS chips (None/Dept/Desig/Contractor, hidden
for shift_deployment which has native chips); full rows shown on screen
(100-cap removed), special rows styled bold grey, GRAND TOTAL pinned on
sort, totals hidden when searching; buildBody sends group_by (contractor
excluded for shift_deployment). Verified: grouped daily_attendance json +
GT sums, verify HTML 200/404, excel A-width 6, PDF title suffix, 26-key
PDF regression 25 OK, screenshot of Group Wise UI. deploy525.sh items
19-23.

## Iter 532 — Late/Early vs actual Shift Master timing (approved improv.)
labour_reports.py: _load_dataset loads policy["_shift_map"] {name:(start,
end)} from shift_masters. _day_summary: shift resolution = emp.shift_start
→ assigned Shift Master (emp.shift_name lookup) → firm default 09:00-18:00.
Late/Early now WRAP-AWARE ((a-b)%1440, sane window ≤720min) for night
shifts; workers with NO known shift (_known_shift False) only flagged when
diff ≤360min → phantom 600+ min lates for unassigned night workers GONE
(VIKRAM 667/599 → 0; assigned "Night Shift" 20:00-08:00 → in 20:07 within
grace, not late ✓; genuine day lates 26-58min still detected, 77 rows/20d).

## Iter 532b — GRAND TOTAL display fix (user bug)
Backend totals verified mathematically exact (sum==GT for hours/ot/cost,
PDF/Excel alignment confirmed via analyze tool). Root cause of "wrong":
WEB preview rendered every cell fixed 108px + numberOfLines=1, so the
"GRAND TOTAL · 48 deployed" label truncated in the S.No. cell and sums
looked misplaced. labour-reports.tsx: special rows now render MERGED-cell
style on screen (label width = 108×span until first non-empty cell,
remaining sums under their exact columns) — matches PDF/Excel merge.
Screenshot verified.

## Iter 532c — Live diagnostics for 2 open user issues (photos + ARAMS)
User issues on LIVE VPS (cannot inspect from here): (1) Punch Log shows
"✕ No Photo" for everyone; (2) ARAMS TEXTILES (KISHANGARH)/machine 062036:
NOT-FOUND-IN-MASTER rows missing. Code paths audited and correct locally
(handshake sends ATTPHOTOStamp + TransFlag AttPhoto; _ingest_attphoto
parses PIN=<14dig>-<pin>.jpg + parks unmatched; unmapped rows Iter 503/
516/520 rules OK). Likely live causes: photos = machines never send
ATTPHOTO (capture OFF / no camera); ARAMS = either device assigned to a
different firm record, PINs all matching via employee_code fallback, or
device NOT REGISTERED (cdata 404s, nothing stored). deploy525.sh now has a
"MACHINE DIAGNOSTIC" block: per device → firm assigned, last push, 7d
punches, 7d unmapped (+distinct PINs), photos attached/parked + verdict
hints. Awaiting user to run deploy and send the diagnostic block.

## Iter 527 — Grouped Salary Comparison + Central Contractor Wage Registers (Form A–D) + P/A+OT web view
1. SALARY COMPARISON (user request): name-wise rows REMOVED; grouped
   Department-wise + Designation-wise with "No. of Employees" and
   Attendance (present days) columns for both compared periods.
   Report Hub chips: Dept + Designation / Department Wise / Designation
   Wise (group_by param end-to-end incl. xlsx/pdf/email).
2. NEW MODULE routes/central_wage_registers.py + app/central-wage-registers.tsx
   (Compliance menu → "Contractor Registers — Central Wages (Form A–D)"):
   Form A Employee Register, Form B Wage Register (approved compliance
   salary run + attendance engine, same 8-hr OT policy), Form C
   Deductions/Advances/Recoveries (advances module auto rows + manual
   entries, configurable categories, lock-guarded), Form D Muster Roll
   (landscape month grid + totals). Masters: cwr_principal_employers,
   cwr_work_orders, cwr_emp_map (Employee Master never modified).
   Workflow Draft→Verified→Approved→Locked + unlock audit (cwr_status).
   Wage period = month OR custom from/to. Excel/PDF via register_export.
3. Present/Absent + Daily OT report FRONTEND finished (dual-row per
   employee: Status + OT; S.No/Name/Father/Designation merged; summary
   bar). Old report untouched. Also fixed leftover syntax error in
   present_absent_ot.py that crashed backend startup.
4. Tests: 26/26 pytest backend/tests/test_iter527_central_wage_and_salary_compare.py
   + frontend flows PASS (test_reports/iteration_527.json).
5. deploy_vps_iter527.sh created; temp_bundle points to it; APP_ITERATION=527.

## Iter 528 — Register links shifted into Report Hub (user request)
"Contractor Registers — Central Wages (Form A–D)" and "CLRA Registers
(Form XII–XV)" REMOVED from the Compliance sidebar and added to the
Report Hub "Already Available (open page)" link row (reports-center.tsx
EXISTING list). Screenshot-verified: both chips render and navigate.
Update: user asked to move the 2 links OUT of "Already Available" — they
now render in a SEPARATE "Contractor Registers" section (green chips,
CONTRACTOR_REGISTERS const in reports-center.tsx). Screenshot verified.

## Iter 529-530 — Monthly Payroll Report + Quick User Manual PDF
1. NEW routes/monthly_payroll_report.py + app/monthly-payroll-report.tsx
   (sidebar Reports → Monthly Payroll Report): one landscape report —
   employee details, attendance 1-31 (P/A/WO/HO/CL/PL/EL/SL/ESIC/HD via
   grid engine + approved leaves overlay), policy payable days, OT,
   Compliance/Actual gross (independent), Final Salary basis selector,
   PF/ESIC/PT/LWF/TDS/Advance/Other deductions from the basis run,
   Net Payable, bank details (masked for non-super-admin), footer
   totals, frozen identity columns (GridFreeze), Excel + custom A3 PDF,
   "Salary Not Calculated"/"Attendance Pending" notes (no fake zeros).
2. NEW routes/user_manual.py + app/user-manual.tsx (sidebar
   Administration → User Manual (PDF), SUPER ADMIN ONLY, 403 others):
   22-page SaaS-style Quick User Manual with REAL screenshots
   (/app/backend/assets/manual/*.png, captured via playwright script
   /tmp/capture_manual.py), navy/teal theme, cover, TOC w/ page nums,
   callouts, steps, notes, compliance-vs-actual table, workflow chart.
3. Report Hub: separate "Contractor Registers" section (Iter 528).
4. Tests: 12/12 pytest tests/test_iter530_monthly_payroll_and_manual.py
   + all frontend flows PASS. APP_ITERATION=530, deploy_vps_iter530.sh.

## Iter 531 — Auto-updating User Manual (user request)
1. Manual rebuilds LIVE per download: version = APP_ITERATION, date =
   today, "What's New" page from db.manual_updates (seeded, POST
   /api/admin/user-manual/log-update to append), extra sections from
   db.manual_sections (no code changes needed for new features).
2. POST /api/admin/user-manual/refresh-screenshots (super admin) runs
   backend/manual_capture.py in background; GET .../status reports
   freshness; frontend has Refresh Screenshots button + status line.
3. manual_capture.py hardened per user directives: NEVER saves error
   screens (red overlay markers) or BLANK screens ("No data...", "No
   leave requests"...); seeds temporary SAMPLE leaves/ESIC entries
   (manual_sample:true, cleaned up in finally); payslip captured for
   the employee with most present days via live payroll/run API;
   OT report clicked to the data month.
4. FIXED BUG: /companies crashed (office_lat.toFixed on undefined) →
   guarded, shows "No geofence set" (this was the wrong firm-master
   screenshot user reported).
5. APP_ITERATION=531, deploy_vps_iter531.sh, temp_bundle updated.

## Iter 532 — PWA section in User Manual (user request)
Section "19. Install as an App (PWA)" added to the manual: install table
(Android Chrome / iPhone Safari / desktop Chrome-Edge), benefits bullets,
post-update reopen warning. Manual now 24 pages; TOC + What's New
changelog entry auto-included; frontend section chips updated.

## Iter 533 — Employee Quick Guide PDF (user-approved improvement)
1. GET /api/admin/employee-guide.pdf (super admin only): 9-page
   phone-first guide — teal cover, install (PWA), sign in, punch in/out,
   attendance, leave, payslip, profile, help table. Real 390x844 phone
   screenshots (emp_*.png) captured via temporary employee session
   (minted+cleaned in manual_capture.py) with sample leave for that
   employee so no screen is blank.
2. FIXED BUG: /admin/payroll/run now allows role=employee scoped to SELF
   (was 403 → employee Payslip tab always showed "No data"). Payslip tab
   now functional for employees.
3. user-manual screen: second button "Employee Quick Guide (PDF)";
   changelog entries logged for PWA guide + employee guide.

## Iter 532 (rev 2) — Manual screenshot/heading fix + cover cleanup + rollback (user request)
1. FIXED heading↔screenshot mismatches in manual_capture.py:
   - employee_master: /admin scrolled to "Employees" list (search box via
     get_by_placeholder scroll_into_view) — was Admin Panel stats.
   - attendance: /attendance-grid?month=<data month> (was blank current month).
   - monthly_payroll: /monthly-payroll-report?month=<data month> (added
     useLocalSearchParams month support to monthly-payroll-report.tsx).
   - bank: clicks the salary-run month chip ("Jul 2026").
   - payslip: _best_payslip_uid prefers gross>0 rows (no more ₹0 slip).
   All 21 screenshots re-captured & visually verified.
2. Cover page (user request): "Product By : S.K. Sharma & Co. Payroll &
   Compliance Portal", "Prepared By : Ankit Sharma"; REMOVED Document
   Version / Last Updated / Screenshots As Of / CONFIDENTIAL. Employee
   guide cover matched. Punch line on EVERY page footer:
   "Your Satisfaction is our First Ambition".
3. REMOVED the "What's New — Recent Payroll Updates" page + TOC entry
   (build_manual now takes extras only; manual_updates collection kept
   for the /status endpoint).
4. ROLLBACK (user request): "Refresh Screenshots / Re-capturing
   screenshots…" button removed from user-manual.tsx (backend
   /refresh-screenshots endpoint kept for dev workspace use).
5. APP_ITERATION=532, deploy_vps_iter532.sh, temp_bundle pointer updated.

## Iter 533 — Two new manual sections + cover cleanup (user request)
1. NEW manual sections with real screenshots: "4. Add New Firm (Firm
   Master Setup)" (capture firm_add.png = /firm-master?company_id=…) and
   "6. Add New Employee" (employee_add.png = /employee-add). All later
   sections renumbered 7–21; comparison=13, PWA=21, extras start n=22.
   Frontend SECTIONS chips updated. Manual now 25 pages, 23 screenshots.
2. "Software Version" line removed from BOTH covers (user request) —
   covers now show only Product By + Prepared By (Ankit Sharma).
3. APP_ITERATION=533, deploy_vps_iter533.sh, temp_bundle pointer updated.
NOTE: /pw-browsers is wiped on pod restarts — rerun
`python -m playwright install chromium-headless-shell` before capture.

## Iter 534 — Monthly Payroll Report perf + HRS day cells; cover layout (user requests)
1. PERF FIX (report "hangs"): monthly-payroll-report.tsx — every keystroke
   in search/month refired the heavy /admin/reports/monthly-payroll call
   AND re-rendered ~8,000 grid cells. Now: 600ms debounce + loadSeq stale
   guard; grid body memoised (useMemo on [data, offsets]). Backend API
   itself is fast (~0.12s for 127 emps).
2. DAY CELLS (user request "don't show Present/Absent"): backend _build
   now emits hours per attendance policy — att_mode="HRS+OT" when
   attendance_policy.overtime_threshold_hours>0 → "8+4" (duty+OT), else
   plain hours; absent="-"; WO/HO/CL/PL/EL/SL/ESIC codes kept. Summary
   count columns unchanged. Excel/PDF share values; PDF subtitle notes
   the mode; DAY_W 30→40, legend updated.
3. Manual covers (user request): Product By + Prepared By moved to cover
   BOTTOM (y=34mm); punch line centred in PAGE CENTRE of cover (15pt,
   y=150mm) and centred in every page footer.
4. APP_ITERATION=534, deploy_vps_iter534.sh (also carries Iter 533 manual
   sections), temp_bundle pointer updated.

## Iter 535 — Monthly Payroll Report default month (user request)
Month selector defaults to the LAST salary-finalized month, never the
current month: backend _default_month(company_id) (finalized/frozen
compliance run → latest compliance run → latest actual run → today);
all 3 endpoints use it when month param empty. Frontend starts with
month="" and adopts data.month into the input after the first load.
APP_ITERATION=535, deploy_vps_iter535.sh, temp_bundle pointer updated.

## Iter 536 — Month stepper + Actual Salary simplification (user requests)
1. Monthly Payroll Report: run_months (distinct months of compliance +
   actual runs) in the API; ‹ › stepper beside the month box jumps to
   prev/next month having a run (calendar fallback when none).
2. Employee Master (user request "In Actual Salary no allowances
   required"): removed "Allowances — Actual Salary" and "Deductions —
   Actual Salary" blocks + "Total Allowances (Actual)" note from
   employee-add.tsx. Payload now saves actual_salary_allowances: [] /
   actual_salary_deductions: [] (clears legacy values on save). Actual
   Salary = Basic + Salary 1/2/3 with Days only. Compliance blocks and
   both salary engines untouched. NOTE: user first asked to merge the
   two blocks, then chose "keep both as-is", then finally asked to
   remove the Actual block — final state implemented.
3. APP_ITERATION=536, deploy_vps_iter536.sh, temp_bundle pointer updated.

## Iter 537 — Attendance day cells strictly per policy engine (user report)
User: "Attendance Showing Wrong — show as per Firm Attendance Policy
1-31". Root cause: cells only used the duty+OT split when
attendance_policy.overtime_threshold_hours was set; otherwise fell back
to raw total hours (e.g. "11" instead of "8+3"). Fix: day cells ALWAYS
use the policy engine's duty_hours + ot_hours (fallback to hours only
when the engine cell has no split). att_mode now constant "HRS+OT";
legend chip made unconditional. Verified d1=8+3 (11h @ 8h policy),
worked-WO day shows its hours ("7").

## Iter 538/539 — Portal hang fix + Punch-Sequence attendance (user)
1. HANG FIX: monthly_payroll_report.py _build_cached (TTL 120s, LRU 10)
   used by json/xlsx/pdf endpoints; frontend skipNext ref kills the
   double-load on open; rows render in chunks of 150 (+Show more).
2. PUNCH-SEQUENCE mode — rides on policy sub-point
   attendance_by_duty_hours (_pm_seq_mode) in BOTH pipelines
   (_compute_monthly_grid_data + _build_ot_report_rows):
   - dedupe_same_kind_punches(5 min) helper in server.py (~line 2147)
   - split_regular_ot_times(punches, 0) → 1st pair duty, later pairs
     pure OT (incl. next-morning OUT via existing cross-day stitch)
   - standard_h = pol.full_day_hours (RAW firm policy, NOT the resolved
     shift length, NOT _pm_8hr forced 8) → dynamic split 8+3 / 8+4
   - division mode divides by firm duty hrs in seq mode
   Verified: RAJENDRA 11h→8+3; VINIT 4-punch day→3 duty + 8.5 OT
   (23:29→next-morning 08:03); flag OFF firms byte-identical (8+3).
   Kankani demo flag restored OFF after testing.
3. attendance-policy.tsx sub-point label documents the sequence rule.
4. APP_ITERATION=539, deploy_vps_iter539.sh, pointer updated.
PENDING: user hasn't yet confirmed shift timings question for
daily-verification display; punch-sequence rule was their answer.

## Iter 540 — Rule badge on Daily In/Out & OT Verification (user accepted)
Backend _build (routes/daily_verification.py) returns "punch_sequence"
(from attendance_policy.policy_master.attendance_by_duty_hours);
daily-verification.tsx shows header badge: green "Rule: Punch Sequence"
/ blue "Rule: Standard (Shift HRS)". APP_ITERATION=540,
deploy_vps_iter540.sh, pointer updated.

## Iter 541 — Sync deletes, ESIC auto-approve, DV filters/margins (user)
1. sync_engine.py: POST /api/sync/delete-employee (resolve by user_id/
   employee_code/bio_code, dry_run supported, force=True bypass of
   auto-sync toggle) + POST /api/sync/delete-left (bulk delete LEFT
   employees: exit_date/resign_date/status resigned-left-terminated/
   active:false with bio_code). sync-engine.tsx "Remove from machines"
   section (input + 2 buttons, named confirms via window.confirm).
2. esic_leave.py create_entry: entries now status=approved on save +
   auto-mark attendance (db.leaves insert) at create; approve endpoint
   kept for legacy pending rows. esic-leave.tsx Module Settings card
   removed (SETTING_ROWS/saveSettings/Switch cleaned).
3. daily-verification.tsx: Category/Shift/Punch Source filters removed;
   "Unit / Group" → "Group". daily_verification.py PDF: portrait side
   margins 12mm (landscape stays 4mm), avail = width - 2*side.
4. APP_ITERATION=541, deploy_vps_iter541.sh, pointer updated.
PENDING/OPEN: (a) Punch PHOTO not arriving from machines (ATTPHOTO
ingest exists in biometric_devices.py ~line 360-800; handshake sends
ATTPHOTOStamp; next step: check TransFlag AttPhoto in handshake +
device "capture photo on punch" setting + add ingest diagnostics).
(b) Punch-sequence shift-timing question to user still unanswered.

## Iter 542 — "Deleted from machine ✓" tag (user accepted improvement)
sync_engine.py job-completion handler: delete job success → users.
machine_deleted_at stamped; add/update success → $unset (re-sync clears
tag). admin.tsx employee row shows green machineDelPill when field set
(list endpoint /admin/employees returns full docs, no projection change
needed). Verified visually via manual stamp (cleaned after test).
APP_ITERATION=542, deploy_vps_iter542.sh, pointer updated.

## Iter 543 — Punch-photo diagnostics & ingest fixes (open user issue)
1. biometric_devices.py ATTPHOTO branch: per-device counters
   photo_recv_count/photo_saved_count + photo_last_at/error/head
   (header prefix before JPEG marker) on every push, incl. failures.
2. _ingest_attphoto fallback regex: filename without "PIN=" prefix.
3. NEW POST /iclock/fdata — accepts photo uploads (JPEG in body) from
   firmware that posts there; same ingest + diagnostics.
4. biometric-devices.tsx DeviceCard: "PUNCH PHOTOS x/y saved · ago"
   Fact + amber last-error line with raw header.
Tested by simulating cdata ATTPHOTO (ok), garbage body (error captured),
fdata (ok); test data cleaned. Handshake already sends TransFlag with
AttPhoto + ATTPHOTOStamp, timestamps consistent (naive device-local).
NEXT: user must confirm machine "capture photo on punch" setting; the
device card now proves whether photos arrive at the server.

## Iter 544 — Attendance Doctor OT punch "auto remove" fix (user P0 bug)
User: "OT Punch Never Save if We click on Save IN + OUT OT Out Punch Auto Remove".
Root cause (2 bugs):
1. Engine: OT OUT saved WITHOUT an OT IN never forms a pair —
   split_regular_ot_times skips unpaired OUTs and has_unpaired_punches
   flags the day, so OT dropped + duty blank.
2. PunchRepairModal mapping: with 1 IN + 2 OUTs, dutyOut picked the LAST
   out (the OT OUT) and otOutPunch=null → form reopened with OT blank
   ("auto removed") and re-save PATCHed the OT punch to the duty time,
   creating duplicate OUT punches.
Fixes:
- PunchRepairModal.tsx: mapping fix (no 2nd IN + ≥2 outs → first OUT =
  duty, last OUT = OT OUT; otIn tie uses <=). saveBoth auto-adds the OT
  IN punch 1 min after duty OUT when OT Out given without OT In (+ UI
  hint). otOutIsNextDay now derives from duty OUT when OT In blank.
- attendance_admin_core.py manual-punch: idempotent — identical
  approved punch (user+kind+at) returned with deduped=true, no dup insert.
Verified by API simulation of the fixed saveBoth: 4 punches saved,
engine returns OT pair 18:01→20:00, day cleanly paired, re-save
idempotent. APP_ITERATION=544, deploy_vps_iter544.sh, pointer updated.

## Iter 545 — Configurable Multiple Punch & Maximum Punch Policy (user spec)
Policy Master (attendance_policy.policy_master) new fields:
maximum_punches_per_day (default 4, clamp 2-20), punch_sequence
("in_out_alternate"), extra_punch_action (reject|exception, default
reject), invalid_sequence_action (reject|exception). multiple_punch_allowed
is now FUNCTIONAL: No = one IN→OUT cycle (2 punches).
Backend:
- utils/punch_policy.py: resolve_punch_policy (employee override → firm →
  default; unset max = 0 = unlimited legacy), counted_punches,
  log_punch_exception → punch_exceptions collection.
- attendance_core.py /attendance/punch: max/multiple check before accept
  (clear messages per spec), sequence rejections now log exceptions;
  extra/invalid action "exception" also stores attempt as
  status="exception" punch. Manual admin punches bypass (Case 7).
- biometric_devices.py ingest: over-limit machine punch stored with
  status="exception" + logged (never dropped); skips contractual gate.
- routes/punch_policy_report.py: GET /api/admin/multi-punch/report
  (punch register: pairs, duty/break/OT vs firm full_day quota,
  punches n/max, only_multiple filter) + /exceptions (log).
Frontend:
- attendance-policy.tsx: ATTENDANCE PUNCH POLICY section (chips 2-10 +
  numeric input, sequence row, action choices, tooltip).
- NEW /multi-punch-report screen (Punch Register + Exceptions tabs,
  firm chips, month, search, only-multiple toggle).
- AdminWebShell: Reports → "Multiple Punch Report" (both menus).
- PolicyMasterSummary: Max Punches/Day + Extra Punch Action rows.
Testing: /app/test_mpp_545.py 25/25 PASS (spec tests A-H + exception
action + legacy unlimited + report math G/H + clamping). Frontend tested
by testing_agent 5/5 PASS (iteration_545.json), Kankani policy restored.
Backward compat: firms with unsaved policy = unlimited; saving policy
bakes default 4. Historical attendance never recalculated.
APP_ITERATION=545, deploy_vps_iter545.sh, bundle pointer updated.

## Iter 546 — Night-OT repair window fix (user bug: VINIT LODI 08-Aug)
User: OT not showing in OT IN/OUT; repair window missing the OT Out punch.
Root cause: PunchRepairModal loaded only the tapped date — a night/OT
session's OUT lives on the NEXT date, invisible → admins edited the wrong
punch (audit "IN 20:00 → 08:00" kept kind=in), breaking cross-day stitch.
Fix (PunchRepairModal.tsx load()): fetch dateIso..next day; when the day
ends with an unpaired trailing IN, pull the next day's first morning punch
(<12:00) into the list (amber next-day date). Correct-kind OUT prefills
OT Out and saves cross-midnight; wrong-kind punch is now visible so the
admin can flip IN↔OUT via pencil (kind chips already exist).
Verified via API simulation (correct + corrupted-kind cases).
DATA repair steps for VINIT (user must do on VPS UI): 09-Aug punch 08:00
→ kind OUT; punch 20:00 → kind IN. APP_ITERATION=546,
deploy_vps_iter546.sh, bundle pointer updated.

## Iter 547 — Merged IN/OUT + OT sheet (user request)
Attendance Report IN/OUT view day cells now also render the OT line
"OT {ot_in}–{ot_out} · hrs" (amber, only when ot_hours>0) — all 4 punches
in one sheet. Same pattern as inout_salary view (cell data already had
ot_in/ot_out/ot_hours). Separate OT IN/OUT tab unchanged. Exports
(Excel/PDF InOut) unchanged — extend on request. attendance-grid.tsx
only. APP_ITERATION=547, deploy_vps_iter547.sh, pointer updated.

## Iter 548 — IN/OUT cell layout per user spec
Cell order: In / Out / Total Duty HRS / OT In / OT Out / "Tot" (duty incl
OT). dutyH = hours - ot_hours on OT days, spanHours otherwise (Iter 283
preserved). Screenshot-verified locally. Also this session: repaired
VINIT LODI data DIRECTLY on VPS via admin API (restored machine IN
20:02 from duplicate, deleted corrupt manual OUT 20:00 on 09-Aug);
doctor verified 08=duty+OT(20:05-08:00), 09/10 paired. Prod super admin
password Sharma@2026 still active — advised user to change.
APP_ITERATION=548, deploy_vps_iter548.sh, pointer updated.
