import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hrms.settings')
django.setup()

from datetime import date, time, timedelta, datetime
from django.utils import timezone
from core.models import (
    EmployeeProfile, Attendance, LateDeduction,
    RegularizationRequest, Payroll, LeaveType, EmployeeSalary,
)
from core.utils import sync_late_deductions, calculate_monthly_payroll, get_leave_balance

p = EmployeeProfile.objects.get(employee_id='TST002')
YEAR, MONTH = 2026, 9


def make_att(day, in_h, in_m, status='Present'):
    dt_in = timezone.make_aware(datetime.combine(date(YEAR, MONTH, day), time(in_h, in_m)))
    dt_out = dt_in + timedelta(hours=9)
    total = dt_out - dt_in - timedelta(hours=1)

    Attendance.objects.create(
        user=p.user, company=p.company, date=date(YEAR, MONTH, day),
        shift=p.shift, check_in_time=dt_in, check_out_time=dt_out,
        state='checked_out', status=status,
        total_working_time=total,
    )

    shift_start = timezone.make_aware(datetime.combine(date(YEAR, MONTH, day), p.shift.start_time))
    late = int((dt_in - shift_start).total_seconds() // 60)
    tag = "LATE" if late > 10 else ""
    print(f"  {date(YEAR, MONTH, day)} | in={in_h:02d}:{in_m:02d} | late={late:>3}m | {status} {tag}")


print("=== CLEANING ===")
print("  Attendance   :", Attendance.objects.filter(user=p.user, date__year=YEAR, date__month=MONTH).delete())
print("  LateDeduct   :", LateDeduction.objects.filter(employee=p, attendance_date__year=YEAR, attendance_date__month=MONTH).delete())
print("  RegRequests  :", RegularizationRequest.objects.filter(user=p.user, date__year=YEAR, date__month=MONTH).delete())
print("  Payroll      :", Payroll.objects.filter(employee=p, year=YEAR, month=MONTH).delete())
print()


print("=== 6 LATE ARRIVALS ===")
make_att(1,  9, 15)
make_att(2,  9, 20)
make_att(3,  9, 25)
make_att(4,  9, 45)
make_att(7, 10, 30)
make_att(8, 11,  0)

print("\n=== 16 PRESENT DAYS ===")
for d in [9, 10, 11, 14, 15, 16, 17, 18, 21, 22, 23, 24, 25, 28, 29, 30]:
    make_att(d, 9, 0)

total = Attendance.objects.filter(user=p.user, date__year=YEAR, date__month=MONTH).count()
print(f"\nTotal attendance rows: {total}")


print("\n=== SYNC LATE DEDUCTIONS ===")
result = sync_late_deductions(p, YEAR, MONTH)
print(f"Created: {result}")


print("\n=== LATE DEDUCTION ROWS ===")
rows = LateDeduction.objects.filter(
    employee=p, source='LATE_COMING',
    attendance_date__year=YEAR, attendance_date__month=MONTH,
).order_by('attendance_date')

if rows.count() == 0:
    print("  (no rows)")
else:
    for r in rows:
        print(f"  {r.attendance_date} | {r.deduction_type} | penalty={r.penalty_days} | leave={r.leave_days} | lop={r.lop_days}")


print("\n=== CL BALANCE ===")
lt = LeaveType.objects.get(name='Casual Leave', company=p.company)
print(" ", get_leave_balance(p.user, lt, year=YEAR))


print("\n=== PAYROLL ===")
salary = EmployeeSalary.objects.filter(employee=p).first()
pr = calculate_monthly_payroll(p, YEAR, MONTH, salary)
for k in ('working_days', 'present_days', 'late_days',
          'late_leave_days', 'late_lop_days', 'late_deduction',
          'reg_leave_days', 'reg_deduction', 'reg_marks',
          'total_deduction', 'net_payable'):
    print(f"  {k:20} = {pr.get(k)}")
