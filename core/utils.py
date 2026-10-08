from django.contrib.auth.models import User
from django.contrib.auth.models import Group
from django.conf import settings
from datetime import date, timedelta, datetime
from calendar import monthrange
from django.utils import timezone


import base64
import hashlib
from cryptography.fernet import Fernet
from django.conf import settings




def get_employee_attendance_for_pdf(employee, year, month, first_day, last_day):
    """
    Returns a dictionary with employee attendance data for PDF generation.
    Uses the HISTORICAL shift stored on each Attendance row (falls back to
    the employee's current profile shift for days with no record).
    """
    from .models import Attendance, LeaveRequest, Holiday, Shift, EmployeeProfile
    from collections import Counter

    profile = employee.profile
    shift = profile.shift if profile else None
    holidays = Holiday.objects.filter(date__gte=first_day, date__lte=last_day).values_list('date', flat=True)
    holidays = set(holidays)

    # Get attendance records (select_related shift for speed)
    attendances = Attendance.objects.filter(
        user=employee,
        date__year=year,
        date__month=month
    ).select_related('shift').order_by('date')

    # ─── Dominant shift for this month (for the PDF header) ───
    _shift_ids = [a.shift_id for a in attendances if a.shift_id]
    if _shift_ids:
        _dom_id = Counter(_shift_ids).most_common(1)[0][0]
        month_shift = Shift.objects.filter(id=_dom_id).first() or shift
    else:
        month_shift = shift

    # Get approved leaves
    leaves = LeaveRequest.objects.filter(
        user=employee,
        status='Approved',
        start_date__lte=last_day,
        end_date__gte=first_day
    )

    # Build daily data
    daily_data = []
    total_present = 0
    total_absent = 0
    total_leave = 0
    total_half = 0
    total_late = 0
    total_overtime_minutes = 0
    total_working_seconds = 0

    for d in (first_day + timedelta(n) for n in range((last_day - first_day).days + 1)):
        day_data = {
            'date': d,
            'day_name': d.strftime('%a'),
            'status': '',
            'check_in': '',
            'check_out': '',
            'working_hours': '--'
        }

        # ─── Fetch attendance early so we can pick the historical shift ───
        att = attendances.filter(date=d).first()
        day_shift = att.shift if (att and att.shift) else shift

        # Check holiday
        if d in holidays:
            day_data['status'] = 'Holiday'
            daily_data.append(day_data)
            continue

        # Check weekly off (only when no record — worked on a weekly off)
        if day_shift and not att:
            day_abbr = d.strftime('%a').lower()[:3]
            if not getattr(day_shift, day_abbr, False):
                day_data['status'] = 'Weekly Off'
                daily_data.append(day_data)
                continue

        # Check leave
        leave_found = False
        for leave in leaves:
            if leave.start_date <= d <= leave.end_date:
                if leave.is_half_day:
                    day_data['status'] = 'Half Day'
                    total_half += 0.5
                else:
                    day_data['status'] = 'Leave'
                    total_leave += 1
                leave_found = True
                break

        if leave_found:
            daily_data.append(day_data)
            continue

        # ─── Attendance record ───
        if att:
            if att.status == 'Present':
                day_data['status'] = 'Present'
                total_present += 1
            elif att.status == 'Absent':
                day_data['status'] = 'Absent'
                total_absent += 1
            elif att.status == 'Half-Day':
                day_data['status'] = 'Half Day'
                total_half += 0.5
                total_present += 0.5     # half-day counts as 0.5 present
            else:
                # Any other status (Under Review, Missing Checkout, etc.)
                day_data['status'] = att.status

            # ── Times (run for every attendance row) ──
            if att.check_in_time:
                local_in = timezone.localtime(att.check_in_time)
                day_data['check_in'] = local_in.strftime('%I:%M %p')
            if att.check_out_time:
                local_out = timezone.localtime(att.check_out_time)
                day_data['check_out'] = local_out.strftime('%I:%M %p')

            # ── Hours / Late / OT ──
            if att.check_in_time and att.check_out_time:
                diff = att.check_out_time - att.check_in_time
                hours = diff.seconds // 3600
                minutes = (diff.seconds % 3600) // 60
                day_data['working_hours'] = f"{hours}h {minutes}m"
                total_working_seconds += diff.seconds

                # Late check (uses shift active on that day)
                if day_shift and att.check_in_time:
                    shift_start = timezone.make_aware(datetime.combine(d, day_shift.start_time))
                    if att.check_in_time > shift_start:
                        total_late += 1

                # Overtime (uses shift active on that day)
                if day_shift and att.check_out_time:
                    shift_end = timezone.make_aware(datetime.combine(d, day_shift.end_time))
                    if att.check_out_time > shift_end:
                        ot = int((att.check_out_time - shift_end).total_seconds() // 60)

                        # Minimum OT threshold
                        _min_ot = int(getattr(day_shift, 'min_overtime_minutes', 0) or 0)
                        if ot < _min_ot:
                            ot = 0

                        # Cap at daily limit
                        if ot > 0 and day_shift.overtime_allowed:
                            if day_shift.overtime_limit:
                                ot = min(ot, int(day_shift.overtime_limit * 60))
                            total_overtime_minutes += ot
        else:
            # No attendance record = Absent (if not leave/holiday/off)
            day_data['status'] = 'Absent'
            total_absent += 1

        daily_data.append(day_data)

    # ─── Summary ───
    total_working_days = len([d for d in daily_data if d['status'] not in ['Weekly Off', 'Holiday']])
    total_absent = max(0, total_working_days - total_present - total_leave)   # ← authoritative absent
    total_hours = total_working_seconds // 3600
    total_minutes = (total_working_seconds % 3600) // 60
    avg_hours = round(total_working_seconds / total_working_days / 3600, 2) if total_working_days > 0 else 0

    return {
        'employee': employee,
        'profile': profile,
        'shift': month_shift,
        'daily_data': daily_data,
        'working_days': total_working_days,
        'present': total_present,
        'absent': total_absent,
        'leave': total_leave,
        'half_day': total_half,
        'late_arrivals': total_late,
        'overtime_minutes': total_overtime_minutes,
        'total_working_hours': f"{total_hours}h {total_minutes}m",
        'avg_working_hours': f"{int(avg_hours)}h {int((avg_hours % 1) * 60)}m" if avg_hours > 0 else "--",
    }
    

def get_approver(employee_user):
    """
    Get the approver for an employee's request.
    
    Returns:
        User: The manager or HR Admin who should approve the request.
    
    Logic:
        - If employee has a manager → return manager
        - If employee has no manager → return HR Admin (superuser or first in ADMIN_ROLES)
    """
    try:
        profile = employee_user.profile
        
        # If employee has a manager
        if profile.manager:
            return profile.manager.user  # Return the manager's User object
        
        # No manager → fallback to HR Admin
        return get_hr_admin()
        
    except Exception:
        return get_hr_admin()


def get_hr_admin():
    """
    Get the HR Admin user (fallback approver).
    
    Returns:
        User: First superuser or first user in HR Admin group.
    """
    # Try to find a superuser first
    superusers = User.objects.filter(is_superuser=True)
    if superusers.exists():
        return superusers.first()
    
    # Then try to find a user in HR Admin group
    try:
        hr_group = Group.objects.get(name='HR Admin')
        hr_admin = hr_group.user_set.first()
        if hr_admin:
            return hr_admin
    except Group.DoesNotExist:
        pass
    
    # Ultimate fallback: any staff user
    staff_users = User.objects.filter(is_staff=True)
    if staff_users.exists():
        return staff_users.first()
    
    # Last resort: first active user
    return User.objects.filter(is_active=True).first()


def can_approve_request(user, request_obj):
    """
    Check if a user can approve/reject a request.
    
    Returns:
        bool: True if user is authorized to approve the request.
    """
    # Superuser and HR Admin can approve anything
    if user.is_superuser or user.groups.filter(name='HR Admin').exists():
        return True
    
    # Get the employee who made the request
    employee_user = request_obj.user
    
    try:
        employee_profile = employee_user.profile
        # If the logged-in user is the manager of the employee
        if employee_profile.manager and employee_profile.manager.user == user:
            return True
    except Exception:
        pass
    
    # If the logged-in user is the employee themselves (cannot approve own request)
    if user == employee_user:
        return False
    
    return False

def get_user_company(request):
    """
    Returns the current user's company.
    Superuser → None (means "all companies").
    """
    if not request.user.is_authenticated:
        return None
    if request.user.is_superuser:
        return None
    return getattr(request, 'user_company', None)


def get_company_filtered(request, queryset, company_field=None):
    """
    Filter a queryset by the current user's company.
    
    - Superuser → returns queryset unchanged.
    - HR Admin / Manager / Employee → filters by their company.
    - No company → returns empty queryset.
    
    Auto-detects the company field:
    - If model has 'company' FK → uses 'company'
    - Otherwise (e.g., User) → uses 'profile__company'
    """
    if not request.user.is_authenticated:
        return queryset.none()

    # Superuser sees everything
    if request.user.is_superuser:
        return queryset

    from .utils import get_user_company
    company = get_user_company(request)
    if company is None:
        return queryset.none()

    # Auto-detect company field
    if company_field is None:
        model = queryset.model
        try:
            # Does the model have a direct 'company' field?
            model._meta.get_field('company')
            company_field = 'company'
        except Exception:
            # Assume User model (company via profile)
            company_field = 'profile__company'

    return queryset.filter(**{company_field: company})

    


def calculate_monthly_payroll(employee, year, month, salary):
    """
    Calculate monthly payroll for one employee by REUSING
    the existing overtime calculation from the Attendance module.

    NOTE: `employee` here IS an EmployeeProfile (not a User).
    """
    from datetime import date, datetime, timedelta
    from calendar import monthrange
    from django.utils import timezone
    from django.db.models import Q, Sum
    from decimal import Decimal
    from collections import Counter
    from .models import Attendance, LeaveRequest, Holiday, LateComingRule, Shift

    first_day = date(year, month, 1)
    _, last_day_num = monthrange(year, month)
    last_day = date(year, month, last_day_num)

    # ── Salary components ──
    basic = Decimal(str(salary.basic_salary or 0))
    hra = Decimal(str(salary.hra or 0))
    allowance = Decimal(str(salary.allowance or 0))
    gross = basic + hra + allowance

    # ✅ `employee` IS the profile — no `.profile`
    company = employee.company
    user = employee.user

    # ── Attendance (fetch early — needed for historical shift detection) ──
    attendances = Attendance.objects.filter(
        user=user,
        company=company,
        date__year=year,
        date__month=month
    ).select_related('shift')

    # ── Detect the dominant shift for THIS month (historical) ──
    # Uses the shift stored on attendance rows. Falls back to current profile shift.
    _shift_ids = [a.shift_id for a in attendances if a.shift_id]
    if _shift_ids:
        _dominant_id = Counter(_shift_ids).most_common(1)[0][0]
        shift = Shift.objects.filter(id=_dominant_id).first() or (employee.shift or None)
    else:
        shift = employee.shift if employee.shift else None

    # ── OT rate: auto-computed from basic × shift multiplier ──
    if shift and shift.overtime_allowed:
        # Hours per day from shift's min_working_hours
        # Field stores MINUTES. Defensive: if value < 24, assume it's hours.
        _mwh = int(shift.min_working_hours or 0)
        if _mwh <= 0:
            _minutes_per_day = 480  # fallback 8 hours
        elif _mwh < 24:
            # Value seems to be in HOURS (e.g., 9) — convert to minutes
            _minutes_per_day = _mwh * 60
        else:
            # Value is in MINUTES (e.g., 540)
            _minutes_per_day = _mwh

        _hours_per_day = Decimal(str(_minutes_per_day)) / Decimal(60)

        # Count working days in this month from the shift flags
        _flags = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        _wd = 0
        for _d in range(1, last_day_num + 1):
            _dd = date(year, month, _d)
            if getattr(shift, _flags[_dd.weekday()], False):
                _wd += 1
        _working_days = Decimal(str(_wd)) if _wd > 0 else Decimal('26')

        _monthly_hours = _working_days * _hours_per_day
        _multiplier = Decimal(str(shift.overtime_multiplier or 1.50))
        ot_rate = (basic / _monthly_hours * _multiplier).quantize(Decimal('0.01'))
    else:
        ot_rate = Decimal('0')
    
    # ── Weekend OT rate (uses weekend_ot_multiplier if set, else falls back) ──
    if shift and shift.overtime_allowed:
        _weekend_mult = Decimal(str(getattr(shift, 'weekend_ot_multiplier', 0) or 0))
        if _weekend_mult > 0:
            weekend_ot_rate = (basic / _monthly_hours * _weekend_mult).quantize(Decimal('0.01'))
        else:
            weekend_ot_rate = ot_rate
    else:
        weekend_ot_rate = Decimal('0')

    # ── Holidays ──
    holidays = set(
        Holiday.objects.filter(
            company=company,
            date__gte=first_day,
            date__lte=last_day
        ).values_list('date', flat=True)
    )

    # ═══════════════════════════════════════════════════════════════
    # FIX #1 — Working days (stop at today for current month,
    #          respect join date)
    # ═══════════════════════════════════════════════════════════════
    _today = date.today()
    _end_day = last_day
    if year == _today.year and month == _today.month:
        _end_day = min(last_day, _today)

    # ── Terminated employees: stop counting at termination date ──
    _terminated_at = getattr(employee, 'terminated_at', None)
    if _terminated_at and _terminated_at < _end_day:
        _end_day = _terminated_at

    _start_day = first_day
    if employee.date_of_joining and employee.date_of_joining > first_day:
        _start_day = employee.date_of_joining

    working_days = 0
    if _start_day <= _end_day:
        for n in range((_end_day - _start_day).days + 1):
            d = _start_day + timedelta(n)
            if d in holidays:
                continue
            if shift:
                day_abbr = d.strftime('%a').lower()[:3]
                if not getattr(shift, day_abbr, False):
                    continue
            working_days += 1

    # ═══════════════════════════════════════════════════════════════
    # FIX #2 — Present days (count all "worked" statuses)
    # ═══════════════════════════════════════════════════════════════
    present_days = Decimal('0')
    for att in attendances:
        if att.status in ('Present', 'Under Review', 'Missing Checkout'):
            present_days += Decimal('1')
        elif att.status == 'Half-Day':
            present_days += Decimal('0.5')

    # ── Late Coming — read from LateDeduction ledger (Phase 4) ──
    from .models import LateDeduction

    # All deduction rows for this month
    all_deductions = LateDeduction.objects.filter(
        employee=employee,
        attendance_date__year=year,
        attendance_date__month=month,
    ).exclude(status='CANCELLED')

    # Split by source
    late_deductions = all_deductions.filter(source='LATE_COMING')
    reg_deductions  = all_deductions.filter(source='REG_OVERAGE')

    late_days = late_deductions.count()
    late_halfday_days  = 0
    total_late_minutes = 0

    # ── Overtime (regular OT + weekend/holiday work) ──
    overtime_minutes = 0
    weekend_overtime_minutes = 0
    for att in attendances:
        day_shift = att.shift if att.shift else shift
        if not (att.check_in_time and att.check_out_time and day_shift):
            continue

        policy = getattr(day_shift, 'weekend_work_policy', 'overtime') or 'overtime'

        # ── Weekend / Holiday work ──
        if att.status in ('Weekend Work', 'Holiday Work'):
            if policy == 'overtime':
                if not day_shift.overtime_allowed:
                    print(
                        f"[payroll] WARNING: {att.date} is {att.status} "
                        f"but shift '{day_shift.name}' has overtime_allowed=False. "
                        f"Hours NOT paid. Set weekend_work_policy='none' to reject."
                    )
                    continue
                full_min = int((att.check_out_time - att.check_in_time).total_seconds() // 60)
                if full_min > 0:
                    weekend_overtime_minutes += full_min
            continue

        # ── Regular working day ──
        if not day_shift.overtime_allowed:
            continue

        shift_end = timezone.make_aware(
            datetime.combine(att.date, day_shift.end_time)
        )

        if att.check_out_time > shift_end:
            ot_min = int((att.check_out_time - shift_end).total_seconds() // 60)

            _min_ot = int(getattr(day_shift, 'min_overtime_minutes', 0) or 0)
            if ot_min < _min_ot:
                ot_min = 0

            if day_shift.overtime_limit and ot_min > 0:
                limit_min = int(day_shift.overtime_limit * 60)
                if ot_min > limit_min:
                    ot_min = limit_min

            overtime_minutes += ot_min

    # ── Split OT into regular + weekend, apply separate rates ──
    _regular_ot_hours = Decimal(str(round(overtime_minutes / 60, 2)))
    _weekend_ot_hours = Decimal(str(round(weekend_overtime_minutes / 60, 2)))
    overtime_hours    = _regular_ot_hours + _weekend_ot_hours

    _regular_ot_amount = (_regular_ot_hours * ot_rate).quantize(Decimal('0.01'))
    _weekend_ot_amount = (_weekend_ot_hours * weekend_ot_rate).quantize(Decimal('0.01'))
    overtime_amount    = _regular_ot_amount + _weekend_ot_amount

    # ── Leaves ──
    leaves = LeaveRequest.objects.filter(
        user=user,
        company=company,
        status='Approved',
        start_date__lte=last_day,
        end_date__gte=first_day
    ).select_related('leave_type')

    paid_leave_days = Decimal('0')
    unpaid_leave_days = Decimal('0')

    for leave in leaves:
        start = max(leave.start_date, first_day)
        end = min(leave.end_date, last_day)
        duration = Decimal(str((end - start).days + 1))
        if leave.is_half_day:
            duration = Decimal('0.5')
        is_paid = getattr(leave.leave_type, 'is_paid', True)
        if is_paid:
            paid_leave_days += duration
        else:
            unpaid_leave_days += duration

    # ═══════════════════════════════════════════════════════════════
    # FIX #3 — Absent days (Decimal-safe)
    # ═══════════════════════════════════════════════════════════════
    # ── Count half-days separately ──
    half_day_count = Decimal('0')
    for att in attendances:
        if att.status == 'Half-Day':
            half_day_count += Decimal('1')

    half_day_units = half_day_count * Decimal('0.5')

    # ── Absent days (in day-units, includes half-day portion) ──
    absent_day_units = max(
        Decimal('0'),
        Decimal(str(working_days)) - present_days - paid_leave_days - unpaid_leave_days
    )

    # ── Split into pure absent + half-day portion ──
    pure_absent_days = max(Decimal('0'), absent_day_units - half_day_units)

    # ── Per-day salary ──
    per_day = (gross / Decimal(str(working_days))) if working_days > 0 else Decimal('0')

    # ── Deductions ──
    pure_absent_deduction = (per_day * pure_absent_days).quantize(Decimal('0.01'))
    half_day_deduction    = (per_day * half_day_units).quantize(Decimal('0.01'))

    # Keep absent_days / absent_deduction as combined total (backwards compat)
    absent_days = absent_day_units
    absent_deduction = pure_absent_deduction + half_day_deduction

    unpaid_leave_deduction = (per_day * unpaid_leave_days).quantize(Decimal('0.01'))
    other_deduction = Decimal('0')

    # ═══════════════════════════════════════════════════════════════
    # LATE PENALTY — split between Leave and LOP
    # ═══════════════════════════════════════════════════════════════
    late_penalty_days      = Decimal('0')
    late_leave_days        = Decimal('0')
    late_lop_days          = Decimal('0')
    late_deduction         = Decimal('0')
    late_halfday_deduction = Decimal('0')

     # ── Late Coming deductions ──
    late_leave_deductions  = late_deductions.filter(deduction_type='LEAVE')
    late_salary_deductions = late_deductions.filter(deduction_type='SALARY')

    late_leave_days = (
        late_leave_deductions.aggregate(s=Sum('leave_days'))['s'] or Decimal('0')
    ).quantize(Decimal('0.01'))
    late_lop_days = (
        (late_salary_deductions.aggregate(s=Sum('penalty_days'))['s'] or Decimal('0'))
        + (late_leave_deductions.aggregate(s=Sum('lop_days'))['s'] or Decimal('0'))
    ).quantize(Decimal('0.01'))
    late_deduction = (
        (late_salary_deductions.aggregate(s=Sum('salary_amount'))['s'] or Decimal('0'))
        + (late_leave_deductions.aggregate(s=Sum('salary_amount'))['s'] or Decimal('0'))
    ).quantize(Decimal('0.01'))

    # ── Regularization over-limit deductions ──
    reg_leave_deductions  = reg_deductions.filter(deduction_type='LEAVE')
    reg_salary_deductions = reg_deductions.filter(deduction_type='SALARY')

    reg_leave_days = (
        reg_leave_deductions.aggregate(s=Sum('leave_days'))['s'] or Decimal('0')
    ).quantize(Decimal('0.01'))
    reg_lop_days = (
        (reg_salary_deductions.aggregate(s=Sum('penalty_days'))['s'] or Decimal('0'))
        + (reg_leave_deductions.aggregate(s=Sum('lop_days'))['s'] or Decimal('0'))
    ).quantize(Decimal('0.01'))
    reg_deduction = (
        (reg_salary_deductions.aggregate(s=Sum('salary_amount'))['s'] or Decimal('0'))
        + (reg_leave_deductions.aggregate(s=Sum('salary_amount'))['s'] or Decimal('0'))
    ).quantize(Decimal('0.01'))
    reg_marks = reg_deductions.count()
    
    late_halfday_deduction = Decimal('0')
    late_penalty_days = late_leave_days + late_lop_days
    total_deduction = (
        absent_deduction
        + unpaid_leave_deduction
        + other_deduction
        + late_deduction
        + reg_deduction
    )
    net_payable = (gross + overtime_amount - total_deduction).quantize(Decimal('0.01'))

    return {
        'basic_salary': basic,
        'hra': hra,
        'allowance': allowance,
        'gross_salary': gross,
        'working_days': working_days,
        'present_days': present_days,
        'absent_days': absent_days,
        'paid_leave_days': paid_leave_days,
        'unpaid_leave_days': unpaid_leave_days,
        'overtime_hours': overtime_hours,
        'overtime_rate': ot_rate,
        'overtime_amount': overtime_amount,
        # ── Split OT (regular vs weekend) ──
        'regular_ot_hours': _regular_ot_hours,
        'weekend_ot_hours': _weekend_ot_hours,
        'regular_ot_amount': _regular_ot_amount,
        'weekend_ot_amount': _weekend_ot_amount,
        'weekend_ot_rate': weekend_ot_rate,

        'absent_deduction': absent_deduction,
        'unpaid_leave_deduction': unpaid_leave_deduction,
        'other_deduction': other_deduction,
        'late_days': late_days,
        'late_halfday_days': late_halfday_days,
        'late_deduction': late_deduction,
        'late_halfday_deduction': late_halfday_deduction,
        'total_deduction': total_deduction,
        'net_payable': net_payable,
        'late_penalty_days': late_penalty_days,
        'late_leave_days': late_leave_days,
        'late_lop_days': late_lop_days,
        'total_late_minutes': total_late_minutes,
        'pure_absent_days': pure_absent_days,
        'pure_absent_deduction': pure_absent_deduction,
        'half_day_days': half_day_count,
        'half_day_units': half_day_units,
        'half_day_deduction': half_day_deduction,
        # ── Regularization over-limit ──
        'reg_leave_days': reg_leave_days,
        'reg_lop_days': reg_lop_days,
        'reg_deduction': reg_deduction,
        'reg_marks': reg_marks,
    }


def number_to_words(n):
    """Convert a number to Indian-style words."""
    n = int(n or 0)
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    if n == 0:
        return 'Zero'

    def two_digit(num):
        if num < 20:
            return ones[num]
        return tens[num // 10] + ('' if num % 10 == 0 else ' ' + ones[num % 10])

    def three_digit(num):
        if num >= 100:
            return ones[num // 100] + ' Hundred' + ('' if num % 100 == 0 else ' ' + two_digit(num % 100))
        return two_digit(num)

    parts = []
    if n >= 10000000:
        parts.append(two_digit(n // 10000000) + ' Crore')
        n %= 10000000
    if n >= 100000:
        parts.append(two_digit(n // 100000) + ' Lakh')
        n %= 100000
    if n >= 1000:
        parts.append(two_digit(n // 1000) + ' Thousand')
        n %= 1000
    if n > 0:
        parts.append(three_digit(n))

    return ' '.join(parts)
    



def get_category_usage(user, company, category, year, month):
    """
    Return {'used': int, 'limit': int, 'remaining': int} for one category
    within the given month, counting Pending + Approved requests only.
    """
    from .models import RegularizationRequest

    used = RegularizationRequest.objects.filter(
        user=user,
        company=company,
        category=category,
        date__year=year,
        date__month=month,
        status__in=['Pending', 'Approved'],
    ).count()

    limit = category.monthly_limit
    return {
        'used':      used,
        'limit':     limit,
        'remaining': max(0, limit - used),
    }
    



def get_leave_balance(user, leave_type, year=None):
    """
    Compute leave balance for one user + leave_type.

    Counts:
      - Total days allowed
      - Days used by approved LeaveRequests
      - Days pending approval
      - Days absorbed by late-arrival penalties (from LateDeduction ledger)

    Returns dict:
        total       — days_allowed
        used        — approved leaves
        pending     — pending leaves
        late_used   — days absorbed by late penalties
        available   — total - used - late_used
    """
    from datetime import date as _date
    from decimal import Decimal
    from django.db.models import Sum
    from .models import LeaveRequest, LateDeduction

    if year is None:
        year = _date.today().year

    total = Decimal(str(leave_type.days_allowed or 0))

    # ── Approved leaves ──
    approved = LeaveRequest.objects.filter(
        user=user, leave_type=leave_type, status='Approved',
    )
    used = sum((Decimal(str(req.get_duration())) for req in approved), Decimal('0'))

    # ── Pending leaves ──
    pending = LeaveRequest.objects.filter(
        user=user, leave_type=leave_type, status='Pending',
    )
    pending_days = sum((Decimal(str(req.get_duration())) for req in pending), Decimal('0'))

    # ── Late penalty absorbed (from LateDeduction ledger) ──
    # Count leave_days from ANY status EXCEPT CANCELLED.
    #   APPLIED          → full leave deduction
    #   PENDING_PAYROLL  → partial leave deduction (remainder going to LOP/salary)
    #   PROCESSED        → permanent
    #   CANCELLED        → reversed, do NOT count
    
    late_used = Decimal('0')
    profile = getattr(user, 'profile', None)
    if profile:
        late_used = (
            LateDeduction.objects
            .filter(
                employee=profile,
                leave_type=leave_type,
                deduction_type='LEAVE',
                attendance_date__year=year,
            )
            .exclude(status='CANCELLED')
            .aggregate(s=Sum('leave_days'))['s']
            or Decimal('0')
        )
        late_used = Decimal(str(late_used)).quantize(Decimal('0.01'))

    available = (total - used - late_used).quantize(Decimal('0.01'))

    return {
        'total':     total,
        'used':      used,
        'pending':   pending_days,
        'late_used': late_used,
        'available': available,
    }


def is_weekend_for_shift(date_obj, shift):
    """
    Return True if the given date is a non-working day for this shift.
    Falls back to Sat/Sun if no shift is provided.
    """
    if not shift:
        return date_obj.weekday() >= 5

    day_attr = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][date_obj.weekday()]
    return not getattr(shift, day_attr, False)
    

def get_late_deduction_history(user, leave_type, year=None):
    """
    Return a list of {month, year, late_days, absorbed_days} for each payroll
    where late penalty was absorbed by this leave type.
    """
    from datetime import date as _date
    from .models import Payroll, LateComingRule

    if year is None:
        year = _date.today().year

    profile = getattr(user, 'profile', None)
    if not profile or not profile.company:
        return []

    rule = LateComingRule.objects.filter(company=profile.company).first()
    if not rule or rule.target_leave_type_id != leave_type.id:
        return []

    rows = (
        Payroll.objects
        .filter(employee=profile, year=year, late_leave_days__gt=0)
        .order_by('-month')
    )
    return [
        {
            'month': r.month,
            'year': r.year,
            'month_name': _date(r.year, r.month, 1).strftime('%b %Y'),
            'late_days': r.late_days,
            'absorbed_days': r.late_leave_days,
        }
        for r in rows
    ]

def get_late_rule_for_date(company, target_date):
    """
    Return the LateComingRule that was effective on `target_date`.
    Picks the most recent rule whose effective_from <= target_date
    and (effective_to is null OR effective_to >= target_date).
    """
    from datetime import date as _date
    from django.db.models import Q
    from .models import LateComingRule

    if not company or not target_date:
        return None

    if hasattr(target_date, 'date'):
        target_date = target_date.date()

    return (
        LateComingRule.objects
        .filter(
            company=company,
            is_enabled=True,
            effective_from__lte=target_date,
        )
        .filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=target_date)
        )
        .order_by('-effective_from', '-version')
        .first()
    )


def get_current_late_rule(company):
    """Return the rule effective today."""
    from datetime import date as _date
    return get_late_rule_for_date(company, _date.today())




def sync_late_deductions(employee, year, month, calc=None):
    """
    Create/refresh LateDeduction transactions for one employee-month.
    Idempotent: deletes existing rows for that month first.
    """
    from datetime import date as _date, datetime, timedelta
    from calendar import monthrange
    from decimal import Decimal
    from django.utils import timezone
    from django.db.models import Q
    from .models import LateDeduction, Attendance, LateComingRule
    from django.db.models import Q

    first = _date(year, month, 1)
    _, last_day_num = monthrange(year, month)
    last = _date(year, month, last_day_num)

    # Idempotency: clear existing rows for this month
    # Idempotency: clear existing rows for this month
    # BUT preserve CANCELLED (HR manually cancelled) and PROCESSED (payroll already ran)
    LateDeduction.objects.filter(
        employee=employee,
        attendance_date__gte=first,
        attendance_date__lte=last,
        source='LATE_COMING',
    ).exclude(status__in=['CANCELLED', 'PROCESSED']).delete()


    # Collect lates with minutes
    lates = []
    for att in Attendance.objects.filter(
        user=employee.user,
        date__gte=first,
        date__lte=last,
    ).select_related('shift'):
        if not (att.check_in_time and att.shift):
            continue

        shift_start = timezone.make_aware(
            datetime.combine(att.date, att.shift.start_time)
        )
        grace = timedelta(minutes=att.shift.grace_period or 0)
        if att.check_in_time <= shift_start + grace:
            continue

        minutes_late = int((att.check_in_time - shift_start).total_seconds() // 60)

        rule = get_late_rule_for_date(employee.company, att.date)
        if not rule or not rule.is_enabled or rule.penalty_type == 'none':
            continue

        lates.append({
            'date': att.date,
            'minutes': minutes_late,
            'rule': rule,
        })

    if not lates:
        return 0

    lates.sort(key=lambda x: x['date'])

    # Free marks from earliest rule
    free_marks = lates[0]['rule'].monthly_allowed_late_marks or 0
    billable = lates[free_marks:]

    if not billable:
        return 0

    # ── Per-day rate for salary mode ──
    # Prefer calc if provided; otherwise compute from EmployeeSalary + shift weekdays.
    per_day = Decimal('0')
    _gross = Decimal('0')
    _wd = 0

    if calc:
        _gross = Decimal(str(calc.get('gross_salary', 0) or 0))
        _wd    = int(calc.get('working_days', 0) or 0)
    else:
        # Look up active salary for this employee
        try:
            from .models import EmployeeSalary
            _sal = EmployeeSalary.objects.filter(
                employee=employee,
                status='active',
            ).order_by('-effective_from').first()
            if _sal:
                _gross = Decimal(str(
                    (_sal.basic_salary or 0)
                    + (_sal.hra or 0)
                    + (_sal.allowance or 0)
                ))
        except Exception:
            _sal = None

        # Working days this month (respecting shift weekdays)
        if employee.shift:
            _flags = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
            for _d in range(1, last_day_num + 1):
                _dd = _date(year, month, _d)
                if getattr(employee.shift, _flags[_dd.weekday()], False):
                    _wd += 1
        else:
            _wd = 26   # fallback

    if _wd > 0 and _gross > 0:
        per_day = (_gross / Decimal(str(_wd))).quantize(Decimal('0.01'))

    created = 0
    
    for late in billable:
        rule = late['rule']

        # ═══════════════════════════════════════════════════════
        # Penalty — depends on calculation_method
        # ═══════════════════════════════════════════════════════
        if rule.calculation_method == 'minutes':
            # Safety: no slabs configured → skip + warn
            if not rule.minute_slabs.exists():
                print(
                    f"[late-deduction] WARNING: Rule v{rule.version} is in "
                    f"'minutes' mode but has NO slabs. Skipping lates for "
                    f"{employee.employee_id} {month:02d}/{year}."
                )
                continue

            # Slab lookup for this day's minutes
            slab = rule.minute_slabs.filter(
                from_minutes__lte=late['minutes']
            ).filter(
                Q(to_minutes__isnull=True) | Q(to_minutes__gte=late['minutes'])
            ).order_by('order', 'from_minutes').first()

            if slab and slab.penalty_days and slab.penalty_days > 0:
                penalty_days = Decimal(str(slab.penalty_days))
            else:
                # Fallback: no slab matched (extreme lateness beyond the
                # highest 'to_minutes'). Never silently skip — use the
                # highest configured slab's penalty instead.
                fallback = (
                    rule.minute_slabs
                    .exclude(to_minutes__isnull=True)
                    .order_by('-to_minutes')
                    .first()
                )
                if fallback and fallback.penalty_days and fallback.penalty_days > 0:
                    penalty_days = Decimal(str(fallback.penalty_days))
                    print(
                        f"[late-deduction] WARNING: No slab for "
                        f"{late['minutes']}m (rule v{rule.version}); "
                        f"using top slab penalty {penalty_days}"
                    )
                else:
                    # Truly no slabs at all — nothing to apply
                    continue
        else:
            # ── Marks mode (existing) ──
            if rule.half_day_cutoff_minutes and late['minutes'] > rule.half_day_cutoff_minutes:
                penalty_days = Decimal('0.5')
            else:
                penalty_days = Decimal(str(rule.penalty_amount or 0))

        if penalty_days <= 0:
            continue


        is_leave = (rule.penalty_type == 'leave')

        # ── Split between LEAVE and LOP ──
        leave_days_value = Decimal('0')
        lop_days_value = Decimal('0')
        salary_amount_value = Decimal('0')
        available_at_creation = None

        if is_leave:
            # Check current available balance for the target leave type
            available = Decimal('0')
            if rule.target_leave_type:
                try:
                    _bal = get_leave_balance(employee.user, rule.target_leave_type, year=year)
                    available = max(Decimal('0'), _bal.get('available', Decimal('0')))
                except Exception:
                    available = Decimal('0')
            available_at_creation = available

            if available >= penalty_days:
                # Full penalty covered by leave
                leave_days_value = penalty_days
            else:
                # Partial leave + remainder handling
                leave_days_value = available
                remainder = penalty_days - available

                if rule.insufficient_balance_action == 'lop':
                    # Remainder becomes salary cut
                    lop_days_value = remainder
                    if per_day > 0:
                        salary_amount_value = (per_day * remainder).quantize(Decimal('0.01'))
                # else: 'skip' → remainder is waived (lop stays 0)
        else:
            # SALARY mode — full salary cut
            if per_day > 0:
                salary_amount_value = (per_day * penalty_days).quantize(Decimal('0.01'))

        # ── Determine status ──
        if is_leave:
            # If any LOP portion exists, it's pending until payroll runs
            status_value = 'PENDING_PAYROLL' if lop_days_value > 0 else 'APPLIED'
        else:
            status_value = 'PENDING_PAYROLL'

        # ── Skip if nothing to record (e.g., skip mode with 0 balance) ──
        if leave_days_value <= 0 and lop_days_value <= 0 and salary_amount_value <= 0:
            continue

        LateDeduction.objects.create(
            employee=employee,
            company=employee.company,
            attendance_date=late['date'],
            deduction_type='LEAVE' if is_leave else 'SALARY',
            penalty_days=penalty_days,
            leave_type=rule.target_leave_type if is_leave else None,
            leave_days=leave_days_value,
            lop_days=lop_days_value,
            salary_amount=salary_amount_value,
            status=status_value,
            policy_snapshot={
                'rule_id': rule.id,
                'version': rule.version,
                'free_marks': rule.monthly_allowed_late_marks,
                'deduction_per_late': str(rule.penalty_amount),
                'half_day_cutoff': rule.half_day_cutoff_minutes,
                'total_lates_in_month': len(lates),
                'billable_lates_in_month': len(billable),
                'minutes_late': late['minutes'],
                'penalty_type': rule.penalty_type,
                'available_at_creation': str(available_at_creation) if available_at_creation is not None else None,
                'insufficient_action': rule.insufficient_balance_action if is_leave else None,
            },
            policy_ref_id=rule.id,
            source='LATE_COMING',
        )
        created += 1

    return created

    

def _get_face_cipher():
    """
    Derive a Fernet key from Django's SECRET_KEY.
    Stable across restarts (same SECRET_KEY → same key).
    """
    key_source = (settings.SECRET_KEY or 'fallback-key').encode('utf-8')
    digest = hashlib.sha256(key_source).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt_face_vector(vector_bytes: bytes) -> bytes:
    """Encrypt a 128-dim face vector (as bytes) for storage."""
    if not vector_bytes:
        return b''
    cipher = _get_face_cipher()
    return cipher.encrypt(vector_bytes)


def decrypt_face_vector(encrypted: bytes) -> bytes:
    """Decrypt a stored face vector."""
    if not encrypted:
        return b''
    cipher = _get_face_cipher()
    return cipher.decrypt(encrypted)


def face_registration_available(company):
    """
    Returns True if the company has face registration enabled.
    Safe even if company is None.
    """
    if not company:
        return False
    return bool(getattr(company, 'face_registration_enabled', False))
    

def get_comp_off_balance(employee):
    from datetime import date as _date
    from decimal import Decimal
    from django.db.models import Sum, Q
    from .models import CompOffCredit

    if employee is None:
        return Decimal('0')

    today = _date.today()
    qs = CompOffCredit.objects.filter(
        employee=employee,
        status='ACTIVE',
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gte=today))
    return qs.aggregate(s=Sum('days_credited'))['s'] or Decimal('0')


def get_active_comp_offs(employee):
    """Return queryset of active, non-expired comp-off credits (for display)."""
    from datetime import date as _date
    from django.db.models import Q
    from .models import CompOffCredit

    if employee is None:
        return CompOffCredit.objects.none()

    today = _date.today()
    return CompOffCredit.objects.filter(
        employee=employee,
        status='ACTIVE',
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=today)
    ).order_by('earned_on')
