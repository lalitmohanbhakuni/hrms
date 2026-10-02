import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hrms.settings')
django.setup()

from datetime import date, time, timedelta, datetime
from django.utils import timezone
from decimal import Decimal
from core.models import (
    Attendance, EmployeeProfile, LateDeduction,
    EmployeeSalary, LateComingRule
)
from core.utils import sync_late_deductions, calculate_monthly_payroll


# ═══════════════════════════════════════════════════════════
# CONFIG — change these and re-run
# ═══════════════════════════════════════════════════════════
EMPLOYEE_ID = 'TST002'
YEAR, MONTH = 2026, 8       # ← change to test different months
# ═══════════════════════════════════════════════════════════


print(f"\n{'='*60}")
print(f"  TEST RUN — {EMPLOYEE_ID} — {MONTH:02d}/{YEAR}")
print(f"{'='*60}\n")


# ─── 1. Setup ───
p = EmployeeProfile.objects.get(employee_id=EMPLOYEE_ID)
p_user = p.user
p_company = p.company
print(f"Employee : {p.employee_id} — {p.full_name}")
print(f"Shift    : {p.shift.name if p.shift else 'None'}\n")


# ─── 2. Delete old data ───
print("── DELETE OLD DATA ──")
d1 = Attendance.objects.filter(user=p_user, date__year=YEAR, date__month=MONTH).delete()
print(f"  Attendance      : {d1}")
d2 = LateDeduction.objects.filter(employee=p, attendance_date__year=YEAR, attendance_date__month=MONTH).delete()
print(f"  LateDeductions  : {d2}\n")


# ─── 3. Create attendance ───
print("── CREATE ATTENDANCE ──")

def make_att(day, in_h, in_m, status='Present'):
    dt_in = timezone.make_aware(datetime.combine(date(YEAR, MONTH, day), time(in_h, in_m)))
    dt_out = dt_in + timedelta(hours=9)
    total = dt_out - dt_in - timedelta(hours=1)
    if status == 'Half-Day':
        total = dt_out - dt_in

    att = Attendance.objects.create(
        user=p_user, company=p_company, date=date(YEAR, MONTH, day),
        shift=p.shift,
        check_in_time=dt_in, check_out_time=dt_out,
        state='checked_out', status=status,
        total_working_time=total,
    )
    shift_start = timezone.make_aware(datetime.combine(date(YEAR, MONTH, day), p.shift.start_time))
    late = int((dt_in - shift_start).total_seconds() // 60)
    tag = "HALF-DAY" if status == 'Half-Day' else ("LATE" if late > 10 else "")
    print(f"  {att.date} | in={in_h:02d}:{in_m:02d} | late={late:>3}m | {status} {tag}")


# 3 free lates + 3 huge lates >100m
# 3 free lates (30-40m)
make_att(3,  9, 30)      # 30m → free #1
make_att(4,  9, 35)      # 35m → free #2
make_att(5,  9, 40)      # 40m → free #3

# 3 penalized lates (30-40m)
make_att(6,  9, 30)      # 30m → penalty 0.25
make_att(7,  9, 35)      # 35m → penalty 0.25
make_att(10, 9, 40)      # 40m → penalty 0.25

# 2 huge lates (>120m → half-day cutoff)
make_att(11, 11,  5)     # 125m → penalty 0.50
make_att(12, 11, 10)     # 130m → penalty 0.50

# rest normal
for day in [13, 14, 17, 18, 19, 20, 21, 24, 25, 26, 27, 28, 31]:
    make_att(day, 9, 0)
    

total = Attendance.objects.filter(user=p_user, date__year=YEAR, date__month=MONTH).count()
print(f"\n  Total rows: {total}\n")


# ─── 4. Sync late deductions ───
print("── SYNC LATE DEDUCTIONS ──")
result = sync_late_deductions(p, YEAR, MONTH)
print(f"  Created: {result}\n")


# ─── 5. Show LateDeduction rows ───
print("── LATE DEDUCTION ROWS ──")
rows = LateDeduction.objects.filter(
    employee=p, attendance_date__year=YEAR, attendance_date__month=MONTH
).order_by('attendance_date')

if rows.count() == 0:
    print("  ❌ No rows created\n")
else:
    for r in rows:
        print(f"  {r.attendance_date} | type={r.deduction_type:7} | "
              f"penalty={r.penalty_days} | leave={r.leave_days} | "
              f"lop={r.lop_days} | ₹{r.salary_amount} | {r.status}")
    print()


# ─── 6. Run payroll ───
print("── PAYROLL ──")
salary = EmployeeSalary.objects.filter(employee=p).first()
if not salary:
    print("  ❌ No salary config found\n")
else:
    r = calculate_monthly_payroll(p, YEAR, MONTH, salary)
    for k in ('working_days', 'present_days', 'absent_days', 'half_day_units',
              'late_days', 'late_leave_days', 'late_lop_days',
              'late_deduction', 'half_day_deduction',
              'overtime_hours', 'overtime_amount',
              'gross_salary', 'net_payable'):
        print(f"  {k:22} = {r[k]}")

print(f"\n{'='*60}\n")  