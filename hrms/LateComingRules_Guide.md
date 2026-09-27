# Late Coming Rules — Complete Guide

**Version:** 1.0
**Last Updated:** 26 September 2026
**Audience:** HR Admin, Superuser, Developers
**Scope:** NitoHR Late Coming & Leave Deduction System

---

## Table of Contents

1. [Overview](#1-overview)
2. [How It Works](#2-how-it-works)
3. [Rule Settings Explained](#3-rule-settings-explained)
4. [HR Setup — First Time](#4-hr-setup--first-time)
5. [HR Monthly Operations](#5-hr-monthly-operations)
6. [Policy Versioning](#6-policy-versioning)
7. [Cancel & Restore](#7-cancel--restore)
8. [Employee Self-Service](#8-employee-self-service)
9. [Common Scenarios](#9-common-scenarios)
10. [What NOT to Do](#10-what-not-to-do)
11. [Technical Reference](#11-technical-reference)
12. [URLs & Models](#12-urls--models)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Overview

The Late Coming Rules system automatically penalizes employees for late arrivals based on configurable company policy.

**Two penalty modes:**
- **Deduct Leave** — reduces leave balance
- **Deduct Salary** — reduces salary in payroll

**Key features:**
- Grace period per shift
- Free marks per month
- Half-day cutoff for extreme lates
- Policy versioning (mid-month changes safe)
- Immutable transaction ledger
- HR cancel/restore
- Employee notifications

---

## 2. How It Works

### High-Level Flow

```
Employee clocks in late
        │
        ▼
System detects lateness (respecting shift grace period)
        │
        ▼
Policy selected by attendance date
        │
        ▼
Two outcomes:
    ├─ Deduct Leave → leave balance reduced
    └─ Deduct Salary → salary cut in payroll
        │
        ▼
Transaction recorded (audit trail)
        │
        ▼
Employee notified + HR can view/cancel
```

### Penalty Calculation

```
Total lates in month:    5
Free marks:              3
Billable lates:          2  (5 - 3)
Penalty per late:        0.25 day
Total penalty:           0.5 day

Then based on mode:
  Leave mode →  0.5 day from Casual Leave
  Salary mode → 0.5 × per-day rate = ₹576.92
```

### Half-Day Cutoff (Per Day)

If any single late exceeds `half_day_cutoff_minutes` (default 120 min):
```
Normal late (≤120 min):  0.25 day penalty
Extreme late (>120 min): 0.5 day penalty
```

### Insufficient Leave Handling (Leave Mode Only)

If available leave < penalty:
```
LOP mode:  Remaining portion cut from salary
Skip mode: Remaining portion waived
```

---

## 3. Rule Settings Explained

| Setting | Purpose | Example |
|---|---|---|
| **Enable Late Policy** | Turn the system on/off | ✓ |
| **Effective From** | Rule applicable from this date | 01 Oct 2026 |
| **Penalty-Free Marks / Month** | Free lates before penalty | 3 |
| **Penalty Type** | What gets deducted | Deduct Leave / Deduct Salary / No Penalty |
| **Deduction per Late** | Days deducted per billable late | 0.25 |
| **Half-Day Cutoff (min)** | Threshold for 0.5 day penalty | 120 |
| **Target Leave Type** | Which leave absorbs (Leave mode) | Casual Leave |
| **If Leave Insufficient** | Behavior when balance low | LOP / Skip |

---

## 4. HR Setup — First Time

### Step 1 — Configure Shift

Navigate: `/setup/` → Shift tab → Create Shift

```
Start time:      09:00 AM
End time:        06:00 PM
Grace period:    10 min
Working days:    Mon–Sat (or per company)
```

**Grace period** = minutes late that still count as "on time".

### Step 2 — Configure Late Coming Rule

Navigate: `/setup/` → Attendance tab → Late Coming Rules

```
Enable:                  ✓
Effective From:          [today's date]
Penalty-Free Marks:      3
Penalty Type:            Deduct Leave
Target Leave Type:       Casual Leave
Deduction per Late:      0.25
Half-Day Cutoff:         120
If Leave Insufficient:   LOP
```

Click **Save as New Policy**.

### Step 3 — Assign Shift to Employees

Navigate: `/assign-shift/`

- Select shift
- Select employees
- Set effective date
- Save

Employees will be notified automatically.

---

## 5. HR Monthly Operations

### Daily / Weekly Checks

Navigate: `/late-deductions/`

**Review:**
- Pending transactions (`PENDING_PAYROLL` status)
- Any anomalies (wrong dates, wrong employees)
- Cancel if needed (see Section 7)

### Monthly Payroll Generation

Navigate: `/payroll/process/`

1. Select Month + Year
2. Click **Generate**

**System performs:**
1. Counts each employee's lates
2. Subtracts free marks
3. Calculates penalties
4. Checks leave balance
5. Creates transactions
6. Sends notifications
7. Updates payroll row

**Terminal shows:**
```
[late-deduction] COM0015 09/2026: 2 transaction(s)
[late-deduction] COM0015 09/2026: 2 marked PROCESSED
```

### Payslip Verification

Navigate: `/payroll/payslips/` → Select employee

**Expected in payslip:**
```
Deductions:
Absent Deduction      ₹1,153.85
Late Penalty          ₹576.92
  2 late marks · 0.50 day
  0.50 day salary cut
Total Deduction       ₹1,730.77
```

---

## 6. Policy Versioning

### Concept

Each rule change creates a **new version**. Old versions stay active for their date range.

### Example Timeline

```
v1: Aug 01 → Aug 20, Leave mode, Casual Leave
v2: Aug 21 → Sep 30, Salary mode
v4: Oct 01 → (active), Leave mode, Casual Leave
```

Late on:
- Aug 15 → v1 applies (leave cut)
- Aug 25 → v2 applies (salary cut)
- Oct 05 → v4 applies (leave cut)

### How to Change Policy

Navigate: `/setup/` → Late Coming Rules

1. Change settings
2. Set **Effective From** (future date)
3. Save

**System auto-closes** the previous rule one day before the new effective date.

### Rules

- **Never set Effective From in the past** (breaks history)
- **Never delete old rules** (breaks audit)
- **Effective From should be a future date** or today

---

## 7. Cancel & Restore

### Cancel a Transaction

Navigate: `/late-deductions/` → Find transaction → Click **X** icon

**Allowed only if:**
- Payroll is Draft or not yet created

**Not allowed if:**
- Payroll is Processed or Paid

**Effect:**
- Status → `CANCELLED`
- Leave balance restored
- Salary cut removed from payslip
- Employee notified

### Restore a Cancelled Transaction

Navigate: `/late-deductions/?tab=cancelled` → Click **↺** icon

**Effect:**
- Status → back to `APPLIED` or `PENDING_PAYROLL`
- Leave balance re-deducted
- Salary cut re-applied

### Audit Trail

Each cancel/restore stores in `policy_snapshot`:
```json
{
  "cancelled_at": "2026-09-26T10:30:00",
  "cancelled_by": "hr_admin",
  "cancel_reason": "Employee was on approved leave",
  "previous_status": "APPLIED"
}
```

---

## 8. Employee Self-Service

### View Late Deductions

URL: `/employee-leaves/?tab=late-deductions`

Employee sees:
- Date, type, penalty, status
- Policy version used

### View Notifications

URL: `/notifications/`

Late penalty notification:
```
Late arrival penalty applied for 09/2026.
2 late marks resulted in 0.65 day(s) salary deduction.
Amount: ₹750.00 will be deducted from your salary.
Additionally, 0.10 day(s) was absorbed from your leave balance.
```

### View Attendance with Late Tags

URL: `/attendance/`

```
25 Sep | 09:02 AM | 06:25 PM | 9h 23m | Present  +2m
24 Sep | 09:18 AM | 06:17 PM | 8h 59m | Present  +18m
```

---

## 9. Common Scenarios

| Scenario | Outcome |
|---|---|
| 5 lates, full balance, Leave mode | 0.5 day leave cut, no salary |
| 5 lates, full balance, Salary mode | ₹576.92 salary cut, leave safe |
| 5 lates, insufficient balance, LOP | Partial leave + partial salary cut |
| 5 lates, insufficient balance, Skip | Leave cut, remainder waived |
| 5 lates, 3 free marks | Only 2 lates penalized |
| One late > 120 min | 0.5 day penalty instead of 0.25 |
| Rule changed mid-month | Old dates use old rule |
| Payroll regenerate | Idempotent — no duplicates |
| HR cancels | Balance + salary restored |
| HR restores | Penalty re-applied |

---

## 10. What NOT to Do

| ❌ Don't | ✅ Do Instead |
|---|---|
| Change rule without effective date | Always set future effective date |
| Cancel transaction on Processed payroll | Adjust next month |
| Delete attendance after payroll | Cancel transaction first |
| Change target leave type mid-month | Use effective date = next month |
| Set effective date in the past | Use today or future |
| Delete old rules | They preserve history |
| Regenerate payroll after finalization | Only regenerate if Draft |

---

## 11. Technical Reference

### Models

**`LateComingRule`**
- Company policy versions
- Fields: `company`, `effective_from`, `effective_to`, `version`, `penalty_type`, `penalty_amount`, `half_day_cutoff_minutes`, `monthly_allowed_late_marks`, `target_leave_type`, `insufficient_balance_action`

**`LateDeduction`** (Transaction Ledger)
- Immutable record of each penalty
- Fields: `employee`, `attendance_date`, `deduction_type`, `penalty_days`, `leave_days`, `lop_days`, `salary_amount`, `status`, `policy_snapshot`, `payroll`

**Status Flow:**
```
APPLIED            (leave-only, done)
PENDING_PAYROLL    (salary cut waiting)
PROCESSED          (payroll ran)
CANCELLED          (HR cancelled)
```

### Key Functions

| Function | File | Purpose |
|---|---|---|
| `sync_late_deductions()` | `core/utils.py` | Creates transactions for a month |
| `get_late_rule_for_date()` | `core/utils.py` | Picks rule by date |
| `get_leave_balance()` | `core/utils.py` | Computes balance from ledger |
| `calculate_monthly_payroll()` | `core/utils.py` | Reads ledger for payroll |

### Data Flow

```
Attendance → sync_late_deductions() → LateDeduction rows
                                            │
                                            ├─→ get_leave_balance()
                                            ├─→ calculate_monthly_payroll()
                                            └─→ HR/Employee pages
```

---

## 12. URLs & Models

### HR URLs

| Page | URL |
|---|---|
| Late Deductions | `/late-deductions/` |
| Cancelled tab | `/late-deductions/?tab=cancelled` |
| Setup | `/setup/` |
| Payroll Generate | `/payroll/process/` |
| Payslips | `/payroll/payslips/` |

### Employee URLs

| Page | URL |
|---|---|
| Late Deductions | `/employee-leaves/?tab=late-deductions` |
| Notifications | `/notifications/` |
| Attendance | `/attendance/` |

---

## 13. Troubleshooting

### Issue: Transactions not created after payroll generate

**Check:**
1. Rule is enabled? `/setup/` → Enable checkbox
2. Attendance rows exist for the month?
3. Late minutes > grace period?
4. Employee has active salary?

### Issue: Notification not received

**Check:**
1. `late_lop_days > 0`? (Notification only when salary is cut)
2. `create_notification` function accessible?
3. Terminal shows `[late-deduction] notify ERROR`?

### Issue: Balance wrong

**Check:**
1. `get_leave_balance` in `core/utils.py`
2. Any `CANCELLED` transactions miscounted? (Should be excluded)
3. `LeaveRequest` (manual leaves) counted separately

### Issue: Policy version conflict

**Check:**
1. `LateComingRule.objects.order_by('effective_from')` — any overlap?
2. `effective_to` of old rule = `effective_from` of new rule - 1 day
3. Use `/setup/` to create new version (auto-close handled)

### Issue: Cannot cancel transaction

**Reason:** Payroll is `Processed` or `Paid`.
**Fix:** Adjust next month, or ask Superuser.

---

## Appendix A — Example Walkthrough

**Scenario: Employee COM0015, October 2026**

**Setup:**
- Rule v4: Leave mode, Casual Leave, 3 free marks, 0.25/late
- Casual Leave balance: 12 days

**Attendance:**
- Oct 1: 09:30 AM (30 min late)
- Oct 2: 09:30 AM (30 min late)
- Oct 3: 09:30 AM (30 min late)
- Oct 4: 09:30 AM (30 min late)
- Oct 5: 09:30 AM (30 min late)

**Payroll Generation:**
1. Lates counted: 5
2. Free marks: 3
3. Billable: 2
4. Penalty: 2 × 0.25 = 0.5 day
5. Leave check: 12 ≥ 0.5 ✓
6. Transaction created:
   - `leave_days = 0.5`, `lop_days = 0`
   - Status: `APPLIED`
7. Balance: 12 → 11.5
8. Notification sent

**Result:**
- Casual Leave: 11.5 days
- Salary: unchanged
- Payslip: Late Penalty = ₹0.00

---

## Appendix B — Model Relationships

```
Company
  └── LateComingRule (1:N, multiple versions)
  └── LateDeduction (1:N)
        └── EmployeeProfile (N:1)
              └── LeaveType (N:1, target)
              └── Payroll (N:1, when processed)
```

---

## Appendix C — Migration Notes

If upgrading from a system where late penalties were stored directly on `Payroll`:

1. Backup DB
2. Run migrations
3. Backfill `LateDeduction` rows from historical `Payroll.late_leave_days`
4. Verify balance calculations match

---

**End of Document**

*For technical questions: contact development team*
*For policy questions: contact HR Admin*