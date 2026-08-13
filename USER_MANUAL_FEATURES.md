# Software Features & Functionalities
### S.K. Sharma & Co. — Payroll & HR Compliance Software (smartpayrolling.com)
*User Manual Section — documents the software **as developed**. Generated from the live application structure (Server Iter 550).*

---

## 1. Software Feature Overview

The software is a **multi-firm (multi-tenant) Payroll & HR Compliance platform** built as a Web Portal + Mobile PWA. A single Super Admin (consultant) manages many client firms; each firm can also have its own Company Admin login. Employees use the mobile/PWA app for punching and self-service.

**Core pillars:**
1. **Firm & Employee Masters** — multi-company setup, employee lifecycle (onboarding → rejoin → resignation → Full & Final).
2. **Attendance Engine** — biometric machines (ZKTeco/eSSL ADMS), mobile GPS/selfie punch, manual entry; Punch-Sequence based Duty/OT calculation; night-shift & cross-midnight support; Attendance Doctor repair tools.
3. **Payroll** — Compliance Salary Process (statutory) and Actual Salary Process (real pay), OT Salary, Arrear, Bonus, Advances, CTC, Full & Final.
4. **Statutory Compliance** — PF/EPF, ESIC, UAN, PT, LWF, Bonus & Gratuity registers, challans, annual returns, Factory & Boilers, CLRA and Central Wage registers.
5. **Reports & Exports** — every register/report downloadable as Excel and/or PDF, with configurable PDF formats, Report Hub, BI/Power BI data feed.
6. **Automation & AI** — AI Insights, AI Payroll Assistant, AI Universal Import, Compliance Automation Studio, Email/WhatsApp automation.
7. **Administration & Security** — role-based access (Super Admin, Sub Admin, Company Admin/Employer, Employee), approval workflows, audit logs, database backup, user log report.

---

## 2. Complete Module-Wise Feature List

### 2.1 Login & Security
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 1 | Login & Security | Admin Login | Admin PIN Login | Admin signs in with email + PIN; sessions shared across tabs ("All tabs share one login session") | Email, PIN, Forgot PIN | Dashboard access | Super/Sub/Company Admin |
| 2 | Login & Security | Admin Login | Admin Password Login & Set Password | Password-based sign-in; first-time password set/change | Set Password, Change PIN | — | Admin |
| 3 | Login & Security | Employee Login | Employee Code / OTP / PIN Login | Employees sign in with employee code, PIN or OTP | Emp Code Login, OTP Login, PIN Change | Employee app access | Employee |
| 4 | Login & Security | Registration | Company Register / Employee Signup / Join QR | New firm request registration; employee self-signup via firm QR code | Register Choice, Join QR, Get App | Pending approval records | Public → Admin approval |
| 5 | Login & Security | Session | Auto Save & Online Status | Footer shows Online/DB-connected status, auto-save indicator, server iteration badge | — | — | All |

### 2.2 Dashboard
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 6 | Dashboard | Portal Dashboard | Main Dashboard | Firm-wise overview: employee counts, attendance summary, pending approvals, alerts | Selected Company switcher, Refresh | On-screen KPIs | Admin |
| 7 | Dashboard | Labour Cost | Labour Cost Dashboard | Cost analytics per firm/period | Filters | Charts / tables | Admin |
| 8 | Dashboard | Analytics | Labour Statistics & HR Analytics | Headcount, joins/exits and HR statistics | Period filters | Charts | Admin |
| 9 | Dashboard | Present Today | Day-wise Present Count / Present Today | Live present/absent counts for the day | Date picker | Counts | Admin |

### 2.3 Company / Firm Master
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 10 | Firms | Companies (Firm Master) | Firm Master | Create/edit firms: name, code, addresses, PF/ESIC codes, attendance policy link, logo | Add Firm, Edit, Active Firm lock | Firm list | Super Admin |
| 11 | Firms | List of Firms | Firm Directory | Search & browse all client firms | Search, filters | List / Excel | Super Admin |
| 12 | Firms | Firms ID & Password | PF · ESIC Portal Credentials | Store each firm's PF/ESIC/govt portal login credentials securely | Add/Edit credentials | Credential register | Super Admin |
| 13 | Firms | Company Requests | New Firm Requests | Approve/reject self-registered companies | Approve / Reject | — | Super Admin |
| 14 | Firms | Branches | Branch / Location Master | Branch/location records per firm | Add/Edit | List | Admin |
| 15 | Firms | Contractor Master | Contractor Master | Contractors per firm for CLRA/contract labour tracking | Add/Edit | Contractor list | Admin |

### 2.4 Employee Master & Documents
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 16 | Employees | Employee Master | Employee Master | Full employee record: personal, statutory (UAN/ESIC/PF), bank, salary (Compliance rate + simplified Actual Salary input), bio code, photo | Add New Employee, Edit, "Deleted from machine ✓" pill for resigned staff | Employee Master Report | Admin |
| 17 | Employees | Add New Employee | Guided Add | Step-wise creation with validations | Save, KYC upload | New record | Admin |
| 18 | Employees | Bulk Import (Excel) | Employee Bulk Import | Excel template import of employees | Download template, Upload | Import result log | Admin |
| 19 | Employees | Bulk Employee Correction | Mass Update | Correct fields across many employees at once | Field selector, preview | Change log | Super Admin |
| 20 | Employees | Employee Groups | Groups | Group employees (e.g. AIRJET, DORNEAR, STAFF) used across attendance & reports | Add/assign groups | Group filters everywhere | Admin |
| 21 | Employees | KYC & Doc Expiry Tracker | Employee Documents | Store KYC documents; track expiring documents with email alerts | Upload, expiry dates | Expiry tracker list | Admin |
| 22 | Employees | Import UAN / ESIC No | UAN/ESIC Import | Bulk import UAN and ESIC numbers from Excel | Upload | Updated master | Admin |
| 23 | Employees | Employee Rejoin | Rejoin Handling | Re-activate ex-employees with a new joining record | Rejoin action | Updated status | Admin |
| 24 | Employees | Offboarding | Resignation / Offboarded List | Mark resigned/left with dates; resigned staff can be deleted from biometric machines | Offboard, Delete from machine | Offboarded register | Admin |
| 25 | Employees | Pending Employee Approval | Signup Approvals | Approve employee self-signups | Approve/Reject | — | Admin |
| 26 | Employees | Profile Edit Reviews | Profile Change Approval | Review employee-requested profile edits & photos | Approve/Reject | Audit trail | Admin |
| 27 | Employees | ID Card | Employee ID Card | Generate printable ID card | Print/Download | ID card PDF | Admin |
| 28 | Employees | Employee Detail Slip | Detail Slip | One-page employee summary printout | Download | PDF | Admin |

### 2.5 General Masters
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 29 | Masters | Department Master | Departments | Department list used in filters & reports | Add/Edit | — | Admin |
| 30 | Masters | Designation Master | Designations | Designation list | Add/Edit | — | Admin |
| 31 | Masters | Holiday Master | Holidays | Firm-wise holiday calendar consumed by attendance & payroll | Add/Edit per firm/year | Holiday list | Admin |
| 32 | Masters | Shift Master | Shifts | Shift definitions (timings, night shifts); Open Shifts and Roster | Add/Edit, Roster | Shift schedule | Admin |
| 33 | Masters | Allowance & Deduction Heads | Salary Heads | Configurable allowance/deduction heads used in salary structure | Add/Edit heads | — | Admin |

### 2.6 Attendance Management
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 34 | Attendance & Shift | Attendance Policy | Policy Master | Per-firm rules: duty hours, grace, late mark, half day, OT rules & rounding, **Rule: Punch Sequence** (first pair = duty, next pairs = OT), weekly off, holiday pay, and **Attendance Punch Policy** (Multiple Punch Allowed, Maximum Punches Per Day, Punch Sequence, Extra Punch Action, Invalid Sequence Action) | Save policy, per-employee override | Policy summary in Firm Master | Admin |
| 35 | Attendance & Shift | Attendance Report | Monthly Attendance Grid | Month × employee grid with view tabs: **IN/OUT (merged sheet: In, Out, Duty HRS, OT In, OT Out, Tot incl OT — intra-pair OT shown as "+OT hh:mm")**, OT IN/OUT, Hours only, Day Salary, IN/OUT + Salary; custom date range; daily basis view; group/sort filters; Hide Days toggle; source badges (B=Biometric, M=Mobile, S=System) | Refresh Bio, Excel, PDF, Daily Excel/PDF, OT Report, Doctor, month stepper ‹ › | Excel + PDF (6-row per employee incl. OT rows), Daily sheets | Admin |
| 36 | Attendance & Shift | Attendance Doctor | Punch Repair | Diagnose problem days (missing IN/OUT, unpaired punches); tap-to-fix from grid; **Repair Punches window** shows the full day incl. next-morning OT OUT (cross-midnight aware); Fix IN + OUT Together (auto-adds OT IN 1 min after duty OUT when only OT Out is given); edit punch time/kind; delete with reason; restore | Auto Repair, per-punch pencil/trash, kind IN↔OUT flip | Repaired attendance | Admin |
| 37 | Attendance & Shift | Daily In/Out & OT Verification | Daily Verification | Day-wise verification sheet of duty & OT with "Rule: Punch Sequence" badge | Date picker, PDF | Verification PDF | Admin |
| 38 | Attendance & Shift | Attendance Master Sheet | Master Sheet | Consolidated attendance master | Filters, export | Excel | Admin |
| 39 | Attendance & Shift | Attendance Sync Dashboard | Sync Health | Machine-sync status per firm/device | Refresh | Status board | Admin |
| 40 | Attendance & Shift | Attendance Review / Approvals | Attendance Approval | Review & approve attendance before payroll | Approve | Approved data | Admin |
| 41 | Attendance & Shift | In/Out & OT Matrix | Matrix Report | In/Out + OT matrix view | Export | Excel | Admin |
| 42 | Attendance & Shift | Comp-Off Ledger | Comp-Off | Compensatory-off credits ledger | Add/consume | Ledger | Admin |
| 43 | Attendance & Shift | GPS Diagnostics / Geofence Monitor | GPS Tools | Live geofence monitor, GPS diagnostics, Location Audit for mobile punches | Map view | Audit list | Admin |
| 44 | Attendance & Shift | Geofence Policy | Geofence Setup | Define geofence radius/locations for mobile punching | Save | — | Admin |

### 2.7 In/Out Punch Management
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 45 | Punch Management | Punch Log Report | Every Punch Log | Every punch — machine, app, import & manual — by date, machine and firm; columns include Name in Machine, Bio, Machine/Source, Status, Punch Photo | Sync from machines, Photo Sync, PDF, PDF + Photos, Download Excel, machine/source & punch-photo filters, search | Excel / PDF (+photos) | Admin |
| 46 | Punch Management | Punch Approvals | Punch Approval | Approve/reject mobile & manual punches; tabs Updated / Auto-Punches / Manual Entries; incomplete-OT filter; audit trail of every edit ("IN 20:00 → 08:00 · reason · by user") | Approve, Reject, Edit | Approval register | Admin |
| 47 | Punch Management | Manual Punch Entry | Manual Punch | Admin adds a punch with time, kind and mandatory reason; idempotent (identical punch never duplicated) | Save | Audit-logged punch | Admin |
| 48 | Punch Management | Back-date Punches | Backdate Entry | Controlled back-dated punch entry | Lookback rules | Audit-logged | Admin |
| 49 | Punch Management | Rectified Punch Audit | Rectification Log | Every repaired/edited punch with old→new values, reason and user | Filters | Audit report | Admin |
| 50 | Punch Management | Flagged Punches | Anomaly Flags | Punches flagged by system rules for review | Review | List | Admin |
| 51 | Punch Management | Contractor Punches | Contractor Punching | Contractor-worker punch capture & log | Filters | Report | Admin |
| 52 | Punch Management | Client Attendance Import | Client Import | Import attendance provided by client (Excel) | Upload | Imported punches | Admin |
| 53 | Punch Management | Import Biometric (.dat) | ZK .dat Import | Import legacy ZKTeco .dat punch files | Upload | Imported punches | Admin |

### 2.8 Multiple Punch Management
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 54 | Multiple Punch | Attendance Punch Policy | Multiple Punch / Max Punch Rules | **Multiple Punch Allowed** (No = one IN→OUT cycle); **Maximum Punches Per Day** (default 4, min 2, configurable 2–20, never hard-coded); **Punch Sequence** IN→OUT→IN→OUT validated; **Extra Punch Action** (Reject / Mark as Exception); **Invalid Sequence Action**. Enforced server-side on mobile/PWA punches (clear real-time messages: "Punch Limit Reached…", "Invalid punch sequence…"); machine punches beyond limit are stored as EXCEPTION (never dropped) | Policy fields, per-employee override | Punch Exception Log | Admin (policy), All (enforcement) |
| 55 | Multiple Punch | Multiple Punch Report | Punch Register + Exceptions | **Punch Register tab**: per employee-day all punches, IN→OUT pairs, Duty/Break/OT hours and "Punches: n / max" pill (red at limit); multi-punch-days-only toggle. **Exceptions tab**: exception type (Max Punch Limit Exceeded, Duplicate IN/OUT, OUT-without-IN, Multiple Punch Not Allowed), reason, policy applied, count, source/device, time | Firm chips, month, search, tabs | On-screen report | Admin |

### 2.9 Leave, Holiday & Shift Change
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 56 | Leave | Leaves | Leave Requests | Employee applies for leave; admin approves | Apply, Approve/Reject | Leave Report | Employee + Admin |
| 57 | Leave | Leave Balance Config | Balances | Configure leave balances | Save | — | Admin |
| 58 | Leave | ESIC Leave | ESIC Sickness Leave | ESIC leave entry — **auto-approved on submission** | Submit | ESIC leave record | Admin |
| 59 | Leave | Leave Report | Leave Register | Leave usage report | Export | Excel | Admin |
| 60 | Shift | Shift Change Requests | Shift Change | Employee requests shift change; approval workflow | Request, Approve | Change log | Employee + Admin |

### 2.10 Overtime Management
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 61 | Overtime | OT Report | OT Register | Standalone OT report from grid data | Month/range | Excel/PDF | Admin |
| 62 | Overtime | OT Salary | OT Salary Run | OT payout processing separate from base payroll | Run, finalize | OT salary sheets | Admin |
| 63 | Overtime | Policy | OT Calculation Rules | Punch-Sequence OT (2nd pair onward), intra-pair OT beyond duty quota, OT rounding slabs (0/30/60 min), OT caps, cross-midnight OT stitching — all automatic | Policy Master | Reflected in all reports | Automatic |

### 2.11 Payroll Processing
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 64 | Payroll | Salary Process (Payroll Run) | Monthly Payroll | Select firm + month → compute attendance-linked salary → review → finalize | Run, Finalize, month stepper | Salary Register | Admin |
| 65 | Payroll | Compliance Salary | Compliance Salary Process | Statutory (books) salary run: PF/ESIC/PT/LWF computed on compliance rates | Run, review, finalize | Compliance registers, challan data | Admin |
| 66 | Payroll | Actual Salary | Actual Salary Process | Real-pay run using the simplified Actual Salary amount from Employee Master | Run, finalize | Actual Salary Report | Admin |
| 67 | Payroll | Salary Compliance Process (AI) | AI Salary Compliance | AI-assisted compliance salary preparation | Review AI output | Draft run | Admin |
| 68 | Payroll | Arrear Salary | Arrears | Arrear salary run for a past period | Run | Arrear sheets | Admin |
| 69 | Payroll | Past Salary Runs | Run History | Browse/reopen previous runs | Open | Historical registers | Admin |
| 70 | Payroll | Monthly Payroll Report | Consolidated Monthly Report | Optimized monthly payroll report; defaults to the last finalized month; ‹ › month stepper | Excel/PDF | Report | Admin |
| 71 | Payroll | Day-wise Salary Sheet | Daily Salary | Per-day salary sheet | Export | Excel | Admin |
| 72 | Payroll | CTC Management | CTC | CTC structure per employee | Edit | CTC report | Admin |
| 73 | Payroll | Advance Management | Advance / Loan | Give advances, auto-deduct in payroll, employee can view "My Advances" | Add advance, EMI | Advance ledger | Admin + Employee |
| 74 | Payroll | Full & Final Settlement | F&F | Settlement computation for exits (dues, gratuity, leave encash) | Compute, finalize | F&F statement | Admin |
| 75 | Payroll | Salary Slip | Payslips | Payslip per employee per month; Send Salary Slips via WhatsApp | Download, WhatsApp send | Payslip PDF | Admin + Employee |
| 76 | Payroll | Salary Register | Register | Full salary register per run | Excel/PDF | Register | Admin |
| 77 | Payroll | Yearly Payroll Register | Annual Register | Year-wise payroll register | Export | Excel | Admin |
| 78 | Payroll | Bank Transfer Files | Bank Sheet | Bank-format salary transfer files; configurable Bank Sheet Format | Generate | Bank file (Excel) | Admin |

### 2.12 Statutory Compliance (PF / ESIC / PT / LWF / Bonus / Gratuity)
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 79 | Compliance | PF Reports | PF / EPF | PF contribution reports, PF-ESIC audit, PF Contribution Report, ECR-oriented outputs | Month/firm | Excel/PDF | Admin |
| 80 | Compliance | ESIC Reports | ESIC | ESIC contribution reports & records | Month/firm | Excel/PDF | Admin |
| 81 | Compliance | UAN | UAN Management | UAN stored per employee; bulk Import UAN/ESIC numbers | Import | Master data | Admin |
| 82 | Compliance | PF & ESIC Claims | Claims Management | Track PF/ESIC claims for employees | Add/track | Claims register | Admin |
| 83 | Compliance | Monthly Challan Summary | Statutory Challans | Challan summary (PF/ESIC/PT) per month | Export | Challan sheets | Admin |
| 84 | Compliance | Contribution Sheets | Contribution Sheets | PF/ESIC contribution sheets | Export | Excel | Admin |
| 85 | Compliance | PT / LWF / Gratuity / MIS | Other Statutory | Professional Tax, Labour Welfare Fund, Gratuity & MIS reports | Export | Reports | Admin |
| 86 | Compliance | Bonus Process | Bonus Run | Yearly bonus computation; Bonus Registers (A, B, D); Bonus Yearly Summary; Bonus Reports | Run, export | Registers | Admin |
| 87 | Compliance | Annual Returns | Annual Returns | Statutory annual returns incl. Factory & Boiler Annual Return | Generate | Return PDFs | Admin |
| 88 | Compliance | CLRA / Central Wage Registers | Labour Registers | CLRA registers, Central Wage registers, Labour Reports | Generate | Registers | Admin |
| 89 | Compliance | Compliance Policy / Settings | Compliance Setup | PF/ESIC settings, compliance policy per firm | Save | — | Admin |
| 90 | Compliance | Compliance Automation Studio | Automation | Rules-based compliance automation | Configure | Automated outputs | Super Admin |
| 91 | Compliance | Statutory Reports / Compliance Reports | Report Pack | Consolidated compliance report hub | Export | Excel/PDF | Admin |

### 2.13 Biometric Devices & Integration
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 92 | Devices | Biometric Devices (ZKTeco) | Device Manager | Register ZKTeco/eSSL machines (ADMS/iClock push); live device status; per-device punch counters | Add device, Device Sync | Device board | Admin |
| 93 | Devices | Device Sync | Machine User Sync | Push employees to machines, update names, **delete employees from machines** (resigned staff), sync commands queue | Sync from machines | Sync log | Admin |
| 94 | Devices | Photo Sync / Reconciliation | Punch Photos | Capture punch photos from machines (`/iclock/fdata` ingest), photo reconciliation, photo diagnostics on device card | Photo Sync | PDF + Photos | Admin |
| 95 | Devices | Sync Engine | Background Sync | Continuous ingest of machine punches with duplicate window (5 min), bounce merge, re-kind normalisation and punch-policy enforcement | Automatic | — | System |

### 2.14 Reports Hub & Exports
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 96 | Reports | Report Hub / Reports Center | All Reports | Central hub for every report | Search | — | Admin |
| 97 | Reports | Attendance Reports | Attendance Pack | Monthly grid Excel/PDF, Daily sheets, Present/Absent Report, Day-wise Present Count, Daily Verification, In/Out & OT Matrix, Multiple Punch Report, User Log Report | Filters | Excel/PDF | Admin |
| 98 | Reports | Payroll Reports | Payroll Pack | Salary Register, Monthly Payroll Report, Yearly Register, Day-wise Salary, Actual Salary Report, MIS | Filters | Excel/PDF | Admin |
| 99 | Reports | Employee Reports Hub | Employee Pack | Employee Master Report, Detail Slip, All Employee Data, Master Data Report | Filters | Excel/PDF | Admin |
| 100 | Reports | PDF Report Formats | Format Designer | Configure PDF formats (paper size, orientation, titles) per report type | Save formats | Applied to PDFs | Super Admin |
| 101 | Reports | BI & Data Feed | Power BI / Excel Feed | Data feed endpoints for BI tools | Copy link | Live data feed | Super Admin |
| 102 | Reports | OCR Sheet Verification | Sheet Verify | OCR-based verification of printed sheets against system data | Upload | Match report | Admin |
| 103 | Reports | Split View Compare / Legacy vs Current | Comparisons | Compare legacy records vs current system | Select runs | Diff view | Super Admin |

### 2.15 Import / Export & Legacy
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 104 | Import/Export | AI Universal Import | AI Import | AI-assisted import of arbitrary Excel formats | Upload, map | Imported data | Super Admin |
| 105 | Import/Export | Legacy Import Wizard | Legacy Migration | Import legacy payroll data; Legacy SQL Explorer; Legacy Salary Records | Wizard steps | Migrated data | Super Admin |
| 106 | Import/Export | Bulk Operations | Bulk Tools | Bulk data operations across firms | Select operation | Change log | Super Admin |

### 2.16 Communication & Automation
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 107 | Communication | WhatsApp Center | WhatsApp Alerts | WhatsApp Configuration, Templates, Linking, Alerts, Send Salary Slips (WhatsApp) *(requires Meta API credentials)* | Configure, send | Message log | Admin |
| 108 | Communication | Email SMTP & Notifications | Email Automation | SMTP settings, automated emails (e.g. expiring documents), Attendance Email | Configure | Sent mail log | Admin |
| 109 | Communication | Mailbox / Messages / Tickets | Internal Comms | Internal mailbox, messages and support tickets | Compose | Threads | Admin + Employee |
| 110 | Communication | Notification Center | Notifications | In-app notification center | Mark read | — | All |
| 111 | Communication | AI Insights / AI Payroll Assistant | AI Tools | AI-generated insights & payroll Q&A assistant (Emergent Universal LLM key) | Ask | Answers/summaries | Admin |
| 112 | Communication | Sales · Proposals | Proposals | Client proposal records | Add | List | Super Admin |

### 2.17 Employee Self Service (Mobile / PWA)
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 113 | ESS | Punch | Mobile GPS/Selfie Punch | Punch IN/OUT from the PWA with GPS geofence and selfie; punch-policy enforced with real-time messages; offline aware | Punch button | Attendance record | Employee |
| 114 | ESS | History | My Attendance & History | Employee sees own punches & attendance | Month view | — | Employee |
| 115 | ESS | Payslip | My Payslips | View/download payslips | Download | PDF | Employee |
| 116 | ESS | Leaves | Apply Leave | Apply & track leaves | Apply | Status | Employee |
| 117 | ESS | My Advances | Advances | View advance/loan balance | — | Ledger | Employee |
| 118 | ESS | Shift Change | Request Shift Change | Raise shift change request | Request | Status | Employee |
| 119 | ESS | Profile | Profile Edit + Photo | Request profile edits & upload photo (admin approval) | Submit | Approved changes | Employee |
| 120 | ESS | Onboarding | Self Signup / Join QR | Join firm via QR, complete onboarding, pending-approval screen | Signup | New employee record | Employee |

### 2.18 Administration, Security & System
| Sr. | Module | Sub-Module | Feature | Detailed Functionality | Key Options | Output / Report | User Role |
|---|---|---|---|---|---|---|---|
| 121 | Administration | User Master (Sub Admins) | Sub Admin Management | Create sub-admins with firm scopes | Add, scope firms | User list | Super Admin |
| 122 | Administration | User Rights (Roles) / Access Management | Permissions | Role & rights configuration; Employer Access Rights; Super Admin Rights | Toggle rights | — | Super Admin |
| 123 | Administration | Approval Inbox / Workflow Builder | Approval Workflow | Central approval inbox; configurable workflows (attendance, shift, deletion, employee approvals) | Approve/Reject | Workflow log | Admin |
| 124 | Administration | Deletion Approval | Two-step Deletes | Sensitive deletions require approval | Approve | Audit | Super Admin |
| 125 | Administration | User Log Report | Audit Trail | Login/action logs of users | Filters | Excel | Super Admin |
| 126 | Administration | Database Backup / Backup Center | Backups | On-demand DB backups & backup center | Backup now | Backup files | Super Admin |
| 127 | Administration | Database Viewer / Editor | DB Tools | Direct data viewer/editor (advanced) | Query | — | Super Admin |
| 128 | Administration | Appearance / Theme | Theming | Portal theme customisation & preview | Save theme | — | Admin |
| 129 | Administration | User Manual (PDF) | Documentation | Downloadable user manual PDF generated from the system | Download | Manual PDF | All Admin |
| 130 | Administration | Portal Automation / Test Portal | Automation Tools | Portal automation utilities and test screens | Run | — | Super Admin |

---

## 3. Detailed Feature Description (Major Features)

### 3.1 Attendance Policy — Policy Master
- **Purpose:** Single source of truth for how a firm's attendance is calculated.
- **Functionality:** Duty hours/quota, grace time, late mark, half-day rules, weekly off & holiday handling, OT rounding slabs (0/30/60 min), **Punch Sequence rule** (first IN→OUT pair = Duty, following pairs = OT), and the **Attendance Punch Policy** block (Multiple Punch Allowed, Maximum Punches Per Day 2–20 with default 4, Extra Punch Action Reject/Exception, Invalid Sequence Action).
- **Inputs:** numeric hour fields, Yes/No switches, choice chips.
- **Calculation:** automatic — every attendance grid, verification sheet, payroll run and export consumes this policy. Per-employee overrides supported.
- **Notes:** Firms that never saved the punch-limit fields remain unlimited (legacy behaviour); historical attendance is never recalculated automatically.

### 3.2 Monthly Attendance Grid (Attendance Report)
- **Purpose:** The daily working screen for attendance verification.
- **Functionality:** Month × employee matrix; merged IN/OUT sheet shows per day: In, Out, Total Duty HRS, OT In, OT Out, Tot (incl. OT); intra-pair OT (worked beyond quota with no separate OT punches) shows as `+OT hh:mm`; problem days show "missing IN/OUT — tap to fix"; source badges (Biometric/Mobile/System); group, sort, search and custom date range filters; Daily Summary strip (Present/Absent/Weekly Off/Holiday/Missing per day).
- **Outputs:** Excel (6 rows per employee: D-In, D-Out, T-Hrs, OT-In, OT-Out, Tot-Hrs + monthly Duty/OT/Present totals + OT HRS sheet), landscape-legal PDF with the same 6-line day cells, Daily Excel/PDF.
- **Access:** Super Admin, Sub Admin (scoped), Company Admin (own firm).

### 3.3 Attendance Doctor & Punch Repair
- **Purpose:** Fix wrong or missing punches safely with a full audit trail.
- **Functionality:** Month diagnosis per employee (ok / missing_out / missing_in / unpaired); Repair Punches window lists every punch of the day **plus the next morning's punch for cross-midnight OT**; Fix IN + OUT Together form (IN, OUT, OT In, OT Out with automatic next-day handling; OT In auto-added 1 minute after duty OUT when only OT Out is entered); per-punch edit (time & IN/OUT kind), delete with reason, restore; machine punches are only normalised, never destroyed.
- **Rules:** every change stores old→new values, reason and the acting admin (see Rectified Punch Audit).

### 3.4 Multiple Punch & Punch Exception Management
- **Purpose:** Control how many times an employee may punch per day and keep the punch stream clean.
- **Functionality:** enforcement happens in the backend for app punches (rejected with clear messages and logged) and machine punches (stored as non-counted EXCEPTION rows); the **Multiple Punch Report** gives a per-day punch register (pairs, Duty/Break/OT, `Punches: n / max`) and a full **Exception Log** (type, reason, policy applied, existing count, source/device).
- **Use case:** detect employees punching more than allowed, machine double-punching, missing-pair days.

### 3.5 Payroll Runs (Compliance / Actual / OT / Arrear / Bonus / F&F)
- **Purpose:** Complete pay processing on two parallel tracks — **Compliance Salary** (statutory books: PF/ESIC/PT/LWF on compliance rates) and **Actual Salary** (real payout from the simplified Actual Salary field).
- **Functionality:** select firm + month → attendance-linked auto computation → on-screen review → finalize; separate OT Salary and Arrear runs; annual Bonus process with Registers A/B/D; Full & Final settlement for exits; Advance/loan auto-deduction; CTC management.
- **Outputs:** Salary Register, payslips (PDF + WhatsApp send), bank transfer files, challan summaries, contribution sheets, monthly/yearly payroll registers.
- **Automatic calculations:** duty/OT hours → wages, PF/ESIC/PT/LWF amounts, bonus, gratuity (F&F), advance EMIs.

### 3.6 Biometric Device Integration (ZKTeco / eSSL ADMS)
- **Purpose:** Fully automatic punch collection from fingerprint/face machines.
- **Functionality:** machines push punches over ADMS/iClock (`/iclock/cdata`) and punch photos (`/iclock/fdata`); device manager shows live status and counters; user sync pushes employees to machines, updates names and **deletes resigned employees from machines** ("Deleted from machine ✓" pill in Employee Master); Punch Log Report shows the machine's own user name ("Name in Machine") and Bio ID per punch for mapping verification; 5-minute duplicate window and normalisation keep the stream clean.
- **Notes:** each employee's **Bio Code must be unique per firm** — the Punch Log's "Name in Machine" column exposes any mismatch instantly.

### 3.7 Employee Self-Service (Mobile / PWA)
- **Purpose:** Employee app without any app-store install (installable PWA).
- **Functionality:** GPS + selfie punch with geofence validation and punch-policy messages; my attendance; payslips; leave application; advances; shift-change requests; profile edit/photo (admin approved); onboarding via firm QR code.
- **Access:** Employee role only; admins approve everything sensitive.

### 3.8 Approvals, Audit & Security
- **Purpose:** Compliance-grade control.
- **Functionality:** Approval Inbox aggregates punch, attendance, shift, profile, employee and deletion approvals; Workflow Builder configures flows; every punch edit/rejection is audit-logged (who, when, old→new, reason); User Log Report tracks logins/actions; Database Backup and Backup Center; role-based menus (Super Admin / Sub Admin with firm scope / Company Admin / Employee).

---

## 4. Role-Wise Feature Availability

| Feature Area | Super Admin | Sub Admin (scoped firms) | Company Admin (Employer) | Employee |
|---|---|---|---|---|
| Firm Master / Firm credentials | ✔ | view (scope) | own firm view | — |
| Employee Master & documents | ✔ | ✔ (scope) | ✔ (own firm) | own profile (request) |
| Attendance Policy / Punch Policy | ✔ | ✔ (scope) | ✔ (own firm) | — |
| Attendance Grid, Doctor, Punch Logs | ✔ | ✔ (scope) | ✔ (own firm) | own history |
| Payroll & Salary runs | ✔ | ✔ (scope) | ✔ (own firm) | own payslips |
| Compliance (PF/ESIC/PT/LWF/Bonus) | ✔ | ✔ (scope) | ✔ (own firm) | — |
| Biometric device management | ✔ | ✔ (scope) | ✔ (own firm) | — |
| Reports & Exports | ✔ | ✔ (scope) | ✔ (own firm) | — |
| Sub-admin / roles / rights | ✔ | — | — | — |
| DB backup / viewer / legacy tools | ✔ | — | — | — |
| Mobile punch, leave, advances, shift change | — | — | — | ✔ |

---

## 5. Compliance Feature List
1. **PF/EPF** — contribution reports, PF-ESIC audit, monthly challan summary, contribution sheets, UAN master + bulk import.
2. **ESIC** — contribution reports, ESIC leave (auto-approve), claims tracking, ESIC number import.
3. **Professional Tax & LWF** — computation in compliance runs + PT/LWF reports.
4. **Bonus** — annual bonus process, Registers A/B/D, yearly summary.
5. **Gratuity** — Full & Final settlement computation + gratuity reporting (PT/LWF/Gratuity/MIS pack).
6. **Labour law registers** — CLRA registers, Central Wage registers, Factory & Boiler annual return, annual returns pack, labour reports.
7. **Compliance Salary Process** — dedicated statutory salary track, kept separate from Actual Salary; AI-assisted variant available.
8. **Compliance Automation Studio** — rules-driven automation of recurring compliance outputs.

## 6. Reporting & Export Feature List
- **Excel:** monthly attendance grid (6-row), daily sheets, master sheet, punch log, salary register, payroll registers (monthly/yearly), bank transfer file, contribution sheets, challans, employee master, leave report, user log.
- **PDF:** monthly IN/OUT (6-line day cells), daily verification, punch log (with photos option), payslips, ID card, detail slip, registers, annual returns, user manual; formats configurable in **PDF Report Formats**.
- **Other:** Power BI / Excel BI data feed, OCR sheet verification, split-view compare, WhatsApp payslip delivery.

## 7. Employee Portal / Mobile (PWA) Feature List
GPS + selfie punch with geofence & punch-policy enforcement · my attendance/history · payslip download · leave apply & status · my advances · shift-change request · profile edit + photo (approval based) · notifications · QR-code joining & onboarding · installable PWA ("Install" from browser) · works across devices with one login session per browser profile.

## 8. System Administration & Security Features
Role-based access (4 roles) · sub-admin firm scoping · rights/permissions editor · approval workflows + approval inbox · deletion approvals · full punch-edit audit trail (Rectified Punch Audit) · user login/action log · database backup + backup center · database viewer (super admin) · SMTP/WhatsApp configuration · PDF format governance · theme/appearance · server iteration badge for version verification.

## 9. Feature Summary
| Category | Count (approx.) |
|---|---|
| Major modules | 18 |
| Documented features | 130 |
| Reports with Excel/PDF export | 35+ |
| Statutory compliance outputs | 15+ |
| Roles supported | 4 (Super Admin, Sub Admin, Company Admin, Employee) |
| Punch sources | 4 (Biometric machine, Mobile/PWA GPS+selfie, Manual admin, Import) |

*This document reflects the software as deployed (Server Iter 550) and should be re-generated after major feature additions.*
