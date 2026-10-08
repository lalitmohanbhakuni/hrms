import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hrms.settings')
django.setup()

from core.models import EmployeeProfile, Attendance, EmployeeSalary
from datetime import date, time, datetime
from django.utils import timezone
from core.utils import calculate_monthly_payroll
from decimal import Decimal

emp = EmployeeProfile.objects.get(employee_id='TST002')
shift = emp.shift
sunday = date(2026, 10, 4)

# Get salary object
salary = EmployeeSalary.objects.filter(
    employee=emp, status='active'
).order_by('-effective_from').first()
if not salary:
    print('❌ No active salary found for', emp.employee_id)
    exit(1)
print(f'Salary: basic={salary.basic_salary} hra={salary.hra} allowance={salary.allowance}')

# Clean up
Attendance.objects.filter(user=emp.user, date=sunday).delete()

tz = timezone.get_current_timezone()
ci = timezone.make_aware(datetime.combine(sunday, time(9, 0)), tz)
co = timezone.make_aware(datetime.combine(sunday, time(18, 0)), tz)

# Configure shift
shift.overtime_allowed = True
shift.overtime_multiplier = Decimal('1.50')
shift.weekend_work_policy = 'overtime'
shift.weekend_ot_multiplier = Decimal('2.00')
shift.save()

print(f'Shift: {shift.name}')
print(f'  weekday OT mult: {shift.overtime_multiplier}')
print(f'  weekend OT mult: {shift.weekend_ot_multiplier}')
print(f'  policy: {shift.weekend_work_policy}')
print()

# ── Scenario A: Sunday as Weekend Work ──
att = Attendance.objects.create(
    user=emp.user, company=emp.company, date=sunday, shift=shift,
    check_in_time=ci, check_out_time=co,
    state='checked_out', status='Weekend Work',
    total_working_time=co - ci,
)
r = calculate_monthly_payroll(emp, 2026, 10, salary)
print('=== A: Sunday as Weekend Work (9 hours) ===')
print(f'  present_days    = {r.get("present_days")}')
print(f'  working_days    = {r.get("working_days")}')
print(f'  absent_days     = {r.get("absent_days")}')
print(f'  overtime_hours  = {r.get("overtime_hours")}')
print(f'  overtime_amount = {r.get("overtime_amount")}')

# ── Scenario B: Same Sunday but Present (control) ──
att.status = 'Present'
att.save()
r2 = calculate_monthly_payroll(emp, 2026, 10, salary)
print()
print('=== B: Sunday as Present (control) ===')
print(f'  present_days    = {r2.get("present_days")}')
print(f'  overtime_hours  = {r2.get("overtime_hours")}')

# ── Scenario C: Present + 2h OT past shift end ──
co_late = timezone.make_aware(datetime.combine(sunday, time(20, 0)), tz)
att.check_out_time = co_late
att.total_working_time = co_late - ci
att.save()
r3 = calculate_monthly_payroll(emp, 2026, 10, salary)
print()
print('=== C: Present + 2h OT past shift end ===')
print(f'  overtime_hours  = {r3.get("overtime_hours")}')
print(f'  overtime_amount = {r3.get("overtime_amount")}')

# Clean up
Attendance.objects.filter(user=emp.user, date=sunday).delete()
print()
print('Cleaned up')