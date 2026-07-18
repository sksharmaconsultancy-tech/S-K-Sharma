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
