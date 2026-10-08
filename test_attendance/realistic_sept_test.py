"""
NitoHR — Realistic September 2026 Test
Creates a full month with all features, then validates payroll.
"""
import os, sys, django
sys.path.insert(0, os.path.expanduser('~/Documents/hrms'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hrms.settings')
django.setup()

from core.models import (
    EmployeeProfile, Attendance, LeaveType, LeaveRequest,
    EmployeeSalary, LateComingRule, LateMinuteSlab, LateDeduction,
    CompOffCredit, Holiday,
)
from core.utils import calculate_monthly_payroll, sync_late_deductions
from datetime import date, time, datetime, timedelta
from django.utils import timezone
from decimal import Decimal

EMP = 'TST002'; YEAR = 2026; MONTH = 9
emp = EmployeeProfile.objects.get(employee_id=EMP)
company = emp.company
shift = emp.shift

print('=' * 78)
print(f'REALISTIC SEPTEMBER 2026 TEST — {emp.employee_id} ({emp.full_name})')
print('=' * 78)

# ─── Clean ───
first = date(YEAR, MONTH, 1); last = date(YEAR, MONTH, 30)
Attendance.objects.filter(user=emp.user, date__gte=first, date__lte=last).delete()
LateDeduction.objects.filter(employee=emp, attendance_date__gte=first, attendance_date__lte=last).delete()
LeaveRequest.objects.filter(user=emp.user, start_date__gte=first, start_date__lte=last).delete()
CompOffCredit.objects.filter(employee=emp, earned_on__gte=first, earned_on__lte=last).delete()
print('✓ Cleaned September data')

# ─── Shift ───
shift.start_time = time(9,0); shift.end_time = time(18,0)
shift.break_start = time(13,0); shift.break_end = time(14,0)
shift.grace_period = 10; shift.min_working_hours = 480
shift.overtime_allowed = True
shift.overtime_multiplier = Decimal('1.50'); shift.overtime_limit = 2
shift.min_overtime_minutes = 30
shift.weekend_work_policy = 'overtime'
shift.weekend_ot_multiplier = Decimal('2.00')
shift.mon=shift.tue=shift.wed=shift.thu=shift.fri=True
shift.sat=shift.sun=False
shift.save()
print('✓ Shift configured')

# ─── Salary ───
EmployeeSalary.objects.filter(employee=emp).update(status='inactive')
EmployeeSalary.objects.update_or_create(
    company=company, employee=emp, effective_from=date(2026,1,1),
    defaults={'salary_type':'monthly','basic_salary':Decimal('25000'),
              'hra':Decimal('10000'),'allowance':Decimal('5000'),
              'overtime_rate':Decimal('0'),'status':'active'})
print('✓ Salary ₹40,000')

# ─── Late rule ───
LateComingRule.objects.filter(company=company).delete()
lt_cl = (LeaveType.objects.filter(company=company, name__icontains='casual').first()
         or LeaveType.objects.filter(company=company).first())
rule = LateComingRule.objects.create(
    company=company, is_enabled=True, calculation_method='minutes',
    monthly_allowed_late_marks=3, penalty_type='leave',
    half_day_cutoff_minutes=90, target_leave_type=lt_cl,
    insufficient_balance_action='lop',
    effective_from=date(2026,1,1), effective_to=None, version=1,
    penalty_amount=Decimal('0.25'))
for fm,tm,pd,o in [(1,20,'0.25',0),(21,59,'0.50',1),(60,90,'1.00',2),(91,None,'1.00',3)]:
    LateMinuteSlab.objects.create(rule=rule, from_minutes=fm, to_minutes=tm,
        penalty_days=Decimal(pd), order=o)
print(f'✓ Late rule (3 free, 4 slabs)')

# ─── Attendance ───
tz = timezone.get_current_timezone()
def dt(d,h,m=0): return timezone.make_aware(datetime.combine(d, time(h,m)), tz)

DATA = [
    (1,  'Present',      9,  0, 18,  0, 0),
    (2,  'Present',      9, 15, 18, 15, 0),
    (3,  'Present',      9,  0, 18,  0, 0),
    (4,  'Present',      9, 20, 18, 20, 0),
    (7,  'Present',      9,  0, 18,  0, 0),
    (8,  'Present',      9, 30, 18, 30, 0),
    (9,  'Present',     10, 15, 19, 15, 0),
    (10, 'Present',      9,  0, 18,  0, 0),
    (11, 'Present',      9,  0, 18,  0, 0),
    (14, 'Present',      9,  0, 18,  0, 0),
    (15, 'Half-Day',     9,  0, 13,  0, 0),
    (16, 'Present',      9,  0, 18,  0, 0),
    (17, 'Absent',      None, None, None, None, 0),
    (18, 'Present',      9,  0, 18,  0, 0),
    (22, 'Present',      9, 45, 18, 45, 0),
    (23, 'Present',      9,  0, 18,  0, 0),
    (24, 'Present',      9,  0, 19, 30, 90),
    (25, 'Present',      9, 35, 18, 35, 0),
    (27, 'Weekend Work', 9,  0, 18,  0, 0),
    (28, 'Present',      9,  0, 18,  0, 0),
    (29, 'Present',      9,  0, 18,  0, 0),
    (30, 'Present',      9,  0, 18,  0, 0),
]

for day, status, ih, im, oh, om, ot in DATA:
    d = date(YEAR, MONTH, day)
    if status == 'Absent':
        ci = co = duration = None
    else:
        ci = dt(d, ih, im); co = dt(d, oh, om); duration = co - ci
    Attendance.objects.create(
        user=emp.user, company=company, date=d, shift=shift,
        check_in_time=ci, check_out_time=co,
        state='checked_out' if ci and co else '',
        status=status, total_working_time=duration,
        overtime_minutes=ot, early_out_minutes=0,
        is_half_day=(status == 'Half-Day'))
print(f'✓ Created {len(DATA)} attendance rows')

# ─── Leave (Sep 21) ───
if lt_cl:
    LeaveRequest.objects.create(
        user=emp.user, company=company, leave_type=lt_cl,
        start_date=date(YEAR,MONTH,21), end_date=date(YEAR,MONTH,21),
        status='Approved', reason='Personal')
    print(f'✓ Leave: {lt_cl.name} on Sep 21')

# ─── Run late deduction sync ───
print()
print('=' * 78)
print('STEP A — Late Deduction Sync')
print('=' * 78)
result = sync_late_deductions(emp, YEAR, MONTH)
print(f'sync_late_deductions() returned: {result}')
lds = LateDeduction.objects.filter(employee=emp, attendance_date__year=YEAR, attendance_date__month=MONTH).order_by('attendance_date')
print(f'{"Date":12} {"Penalty":10} {"Source":14} {"Status":16}')
for d in lds:
    print(f'{d.attendance_date} {d.penalty_days:10} {d.source:14} {d.status:16}')
print(f'Total penalty: {sum(d.penalty_days or 0 for d in lds)} days')

# ─── Run payroll ───
print()
print('=' * 78)
print('STEP B — Payroll Calculation')
print('=' * 78)
salary = EmployeeSalary.objects.filter(employee=emp, status='active').first()
r = calculate_monthly_payroll(emp, YEAR, MONTH, salary)

# ─── Compare ───
print()
print('=' * 78)
print('STEP C — Expected vs Actual')
print('=' * 78)

EXPECTED = {
    'working_days':      22,
    'present_days':      Decimal('19.5'),
    'absent_days':       Decimal('1.5'),
    'paid_leave_days':   Decimal('1'),
    'overtime_hours':    Decimal('10.5'),
    'overtime_amount':   Decimal('2876.42'),
    'late_days':         3,
    'late_penalty_days': Decimal('2.00'),
    'late_leave_days':   Decimal('2.00'),
    'late_deduction':    Decimal('0'),
}

print(f'{"Metric":<28} {"Expected":<18} {"Actual":<18} {"Match"}')
print('-' * 78)
for k, exp in EXPECTED.items():
    act = r.get(k, '(missing)')
    try:
        match = '✅' if Decimal(str(act)) == Decimal(str(exp)) else '❌'
    except:
        match = '✅' if act == exp else '❌'
    print(f'{k:<28} {str(exp):<18} {str(act):<18} {match}')

print()
print('All computed values:')
for k in sorted(r.keys()):
    print(f'  {k:<28} {r[k]}')
