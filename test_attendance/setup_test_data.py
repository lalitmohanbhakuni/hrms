"""
NitoHR — Full Attendance Test Setup
Creates a clean, predictable month of data for TST002.
Run: python setup_test_data.py
"""
import os
import sys
import django

# Add project root to Python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hrms.settings')
django.setup()

from core.models import (
    EmployeeProfile, Shift, Attendance, LeaveType, LeaveRequest,
    EmployeeSalary, LateComingRule, LateMinuteSlab, LateDeduction,
    CompOffCredit, KioskAttendanceLog,
)
from datetime import date, time, datetime, timedelta
from django.utils import timezone
from decimal import Decimal

# ═══════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════
EMP_ID = 'TST002'
YEAR = 2026
MONTH = 10

emp = EmployeeProfile.objects.get(employee_id=EMP_ID)
company = emp.company
shift = emp.shift

print(f'Employee: {emp.employee_id} ({emp.full_name})')
print(f'Company:  {company.name}')
print(f'Shift:    {shift.name}')
print()

# ═══════════════════════════════════════════════════════════
#  1. CLEAN existing test data for Oct 2026
# ═══════════════════════════════════════════════════════════
first = date(YEAR, MONTH, 1)
last  = date(YEAR, MONTH, 30)

Attendancе_qs = Attendance.objects.filter(user=emp.user, date__gte=first, date__lte=last)
n_att = Attendancе_qs.count()
Attendancе_qs.delete()
print(f'Cleaned {n_att} existing attendance rows')

n_ld = LateDeduction.objects.filter(employee=emp, attendance_date__gte=first, attendance_date__lte=last).count()
LateDeduction.objects.filter(employee=emp, attendance_date__gte=first, attendance_date__lte=last).delete()
print(f'Cleaned {n_ld} existing late deductions')

LeaveRequest.objects.filter(user=emp.user, start_date__gte=first, start_date__lte=last).delete()
print(f'Cleaned existing leave requests')
print()

# ═══════════════════════════════════════════════════════════
#  2. CONFIGURE SHIFT
# ═══════════════════════════════════════════════════════════
shift.start_time = time(9, 0)
shift.end_time = time(18, 0)
shift.break_start = time(13, 0)
shift.break_end = time(14, 0)
shift.grace_period = 10
shift.min_working_hours = 480
shift.overtime_allowed = True
shift.overtime_multiplier = Decimal('1.50')
shift.overtime_limit = 2
shift.min_overtime_minutes = 30
shift.weekend_work_policy = 'overtime'
shift.weekend_ot_multiplier = Decimal('2.00')
shift.mon = True; shift.tue = True; shift.wed = True
shift.thu = True; shift.fri = True; shift.sat = False; shift.sun = False
shift.save()
print(f'Shift configured: 09:00-18:00, grace 10min, Mon-Fri')

# ═══════════════════════════════════════════════════════════
#  3. CONFIGURE SALARY
# ═══════════════════════════════════════════════════════════
EmployeeSalary.objects.filter(employee=emp).update(status='inactive')
sal, _ = EmployeeSalary.objects.update_or_create(
    company=company,
    employee=emp,
    effective_from=date(2026, 1, 1),
    defaults={
        'salary_type': 'monthly',
        'basic_salary': Decimal('25000'),
        'hra': Decimal('10000'),
        'allowance': Decimal('5000'),
        'overtime_rate': Decimal('0'),
        'status': 'active',
    }
)   
print(f'Salary: Basic ₹25,000 + HRA ₹10,000 + Allow ₹5,000 = ₹40,000')

# ═══════════════════════════════════════════════════════════
#  4. CONFIGURE LATE RULE
# ═══════════════════════════════════════════════════════════
LateComingRule.objects.filter(company=company).delete()

lt_cl = LeaveType.objects.filter(company=company, name__icontains='casual').first()
if not lt_cl:
    lt_cl = LeaveType.objects.filter(company=company).first()

rule = LateComingRule.objects.create(
    company=company,
    is_enabled=True,
    calculation_method='minutes',
    monthly_allowed_late_marks=3,
    penalty_type='leave',
    half_day_cutoff_minutes=90,
    target_leave_type=lt_cl,
    insufficient_balance_action='lop',
    effective_from=date(2026, 1, 1),
    effective_to=None,
    version=1,
    penalty_amount=Decimal('0.25'),
)

LateMinuteSlab.objects.create(rule=rule, from_minutes=1,  to_minutes=20,   penalty_days=Decimal('0.25'), order=0)
LateMinuteSlab.objects.create(rule=rule, from_minutes=21, to_minutes=59,   penalty_days=Decimal('0.50'), order=1)
LateMinuteSlab.objects.create(rule=rule, from_minutes=60, to_minutes=90,   penalty_days=Decimal('1.00'), order=2)
LateMinuteSlab.objects.create(rule=rule, from_minutes=91, to_minutes=None, penalty_days=Decimal('1.00'), order=3)
print(f'Late rule: minutes mode, free=3, 4 slabs, target leave={lt_cl.name}')

# ═══════════════════════════════════════════════════════════
#  5. CREATE ATTENDANCE RECORDS
# ═══════════════════════════════════════════════════════════
tz = timezone.get_current_timezone()

def make_dt(d, h, m=0):
    return timezone.make_aware(datetime.combine(d, time(h, m)), tz)

# (day, status, check_in, check_out, notes)
events = [
    (1,  'Present', make_dt(date(YEAR,MONTH,1), 9, 0),  make_dt(date(YEAR,MONTH,1), 18, 0), 'on time'),
    (2,  'Present', make_dt(date(YEAR,MONTH,2), 9, 0),  make_dt(date(YEAR,MONTH,2), 18, 0), 'on time'),
    (5,  'Present', make_dt(date(YEAR,MONTH,5), 9, 15), make_dt(date(YEAR,MONTH,5), 18, 0), 'late 15'),
    (6,  'Present', make_dt(date(YEAR,MONTH,6), 9, 25), make_dt(date(YEAR,MONTH,6), 18, 0), 'late 25'),
    (7,  'Present', make_dt(date(YEAR,MONTH,7), 10, 15),make_dt(date(YEAR,MONTH,7), 18, 0), 'late 75'),
    (8,  'Present', make_dt(date(YEAR,MONTH,8), 9, 20), make_dt(date(YEAR,MONTH,8), 18, 0), 'late 20'),
    (9,  'Present', make_dt(date(YEAR,MONTH,9), 9, 15), make_dt(date(YEAR,MONTH,9), 18, 0), 'late 15'),
    (12, 'Half-Day', make_dt(date(YEAR,MONTH,12),9, 0), make_dt(date(YEAR,MONTH,12),13, 0), '4h half day'),
    (13, 'Present', make_dt(date(YEAR,MONTH,13),9, 30), make_dt(date(YEAR,MONTH,13),18, 0), 'late 30'),
    (14, 'Absent',  None, None, 'absent'),
    (15, 'Present', make_dt(date(YEAR,MONTH,15),9, 0),  make_dt(date(YEAR,MONTH,15),19, 30),'1.5h OT'),
    (16, 'Present', make_dt(date(YEAR,MONTH,16),9, 0),  make_dt(date(YEAR,MONTH,16),18, 0), 'on time'),
    (20, 'Present', make_dt(date(YEAR,MONTH,20),9, 0),  make_dt(date(YEAR,MONTH,20),18, 0), 'on time'),
    (21, 'Present', make_dt(date(YEAR,MONTH,21),9, 0),  make_dt(date(YEAR,MONTH,21),18, 0), 'on time'),
    (22, 'Present', make_dt(date(YEAR,MONTH,22),9, 0),  make_dt(date(YEAR,MONTH,22),18, 0), 'on time'),
    (23, 'Present', make_dt(date(YEAR,MONTH,23),9, 0),  make_dt(date(YEAR,MONTH,23),18, 0), 'on time'),
    (26, 'Present', make_dt(date(YEAR,MONTH,26),9, 0),  make_dt(date(YEAR,MONTH,26),18, 0), 'on time'),
    (27, 'Present', make_dt(date(YEAR,MONTH,27),9, 0),  make_dt(date(YEAR,MONTH,27),18, 0), 'on time'),
    (28, 'Present', make_dt(date(YEAR,MONTH,28),9, 0),  make_dt(date(YEAR,MONTH,28),18, 0), 'on time'),
    (29, 'Present', make_dt(date(YEAR,MONTH,29),9, 0),  make_dt(date(YEAR,MONTH,29),18, 0), 'on time'),
    (30, 'Present', make_dt(date(YEAR,MONTH,30),9, 0),  make_dt(date(YEAR,MONTH,30),18, 0), 'on time'),
]

created = 0
for day, status, ci, co, notes in events:
    d = date(YEAR, MONTH, day)
    duration = (co - ci) if (ci and co) else None

    # Overtime calc for Oct 15
    ot_min = 0
    if day == 15:
        ot_min = 90
    elif day == 12:
        ot_min = 0

    is_half = (status == 'Half-Day')

    Attendance.objects.create(
        user=emp.user,
        company=company,
        date=d,
        shift=shift,
        check_in_time=ci,
        check_out_time=co,
        state='checked_out' if ci and co else '',
        status=status,
        total_working_time=duration,
        overtime_minutes=ot_min,
        early_out_minutes=0,
        is_half_day=is_half,
    )
    created += 1

print(f'Created {created} attendance rows')

# ═══════════════════════════════════════════════════════════
#  6. CREATE PAID LEAVE (Oct 19)
# ═══════════════════════════════════════════════════════════
if lt_cl:
    lr = LeaveRequest.objects.create(
        user=emp.user,
        company=company,
        leave_type=lt_cl,
        start_date=date(YEAR,MONTH,19),
        end_date=date(YEAR,MONTH,19),
        status='Approved',
        reason='Test paid leave',
    )
    print(f'Created approved leave: {lt_cl.name} on Oct 19')

# ═══════════════════════════════════════════════════════════
#  SUMMARY
# ═══════════════════════════════════════════════════════════
print()
print('=' * 60)
print('SETUP COMPLETE')
print('=' * 60)
print(f'Attendance rows: {Attendance.objects.filter(user=emp.user, date__gte=first, date__lte=last).count()}')
print(f'Leaves:          {LeaveRequest.objects.filter(user=emp.user, start_date__gte=first, start_date__lte=last).count()}')
print(f'Late rule:       {LateComingRule.objects.filter(company=company).count()}')
print(f'Slabs:           {LateMinuteSlab.objects.filter(rule=rule).count()}')
