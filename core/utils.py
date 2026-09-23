from django.contrib.auth.models import User
from django.contrib.auth.models import Group
from django.conf import settings
from datetime import date, timedelta, datetime
from calendar import monthrange
from django.utils import timezone


def get_employee_attendance_for_pdf(employee, year, month, first_day, last_day):
    """
    Returns a dictionary with employee attendance data for PDF generation.
    """
    from .models import Attendance, LeaveRequest, Holiday, Shift, EmployeeProfile

    profile = employee.profile
    shift = profile.shift if profile else None
    holidays = Holiday.objects.filter(date__gte=first_day, date__lte=last_day).values_list('date', flat=True)
    holidays = set(holidays)

    # Get attendance records
    attendances = Attendance.objects.filter(
        user=employee,
        date__year=year,
        date__month=month
    ).order_by('date')

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

        # Check holiday
        if d in holidays:
            day_data['status'] = 'Holiday'
            daily_data.append(day_data)
            continue

        # Check weekly off
        if shift:
            day_abbr = d.strftime('%a').lower()[:3]
            if not getattr(shift, day_abbr, False):
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

        # Check attendance record
        att = attendances.filter(date=d).first()
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

            if att.check_in_time:
                local_in = timezone.localtime(att.check_in_time)
                day_data['check_in'] = local_in.strftime('%I:%M %p')
            if att.check_out_time:
                local_out = timezone.localtime(att.check_out_time)
                day_data['check_out'] = local_out.strftime('%I:%M %p')

            # Calculate working hours
            if att.check_in_time and att.check_out_time:
                diff = att.check_out_time - att.check_in_time
                hours = diff.seconds // 3600
                minutes = (diff.seconds % 3600) // 60
                day_data['working_hours'] = f"{hours}h {minutes}m"
                total_working_seconds += diff.seconds

                # Check late
                if shift and att.check_in_time:
                    shift_start = timezone.make_aware(datetime.combine(d, shift.start_time))
                    if att.check_in_time > shift_start:
                        total_late += 1

                # Check overtime
                if shift and att.check_out_time:
                    shift_end = timezone.make_aware(datetime.combine(d, shift.end_time))
                    if att.check_out_time > shift_end:
                        ot = (att.check_out_time - shift_end).total_seconds() // 60
                        if shift.overtime_allowed and shift.overtime_limit:
                            ot = min(ot, shift.overtime_limit * 60)
                        total_overtime_minutes += ot
        else:
            # No attendance record = Absent (if not leave/holiday/off)
            day_data['status'] = 'Absent'
            total_absent += 1

        daily_data.append(day_data)

    # Summary
    total_working_days = len([d for d in daily_data if d['status'] not in ['Weekly Off', 'Holiday']])
    total_hours = total_working_seconds // 3600
    total_minutes = (total_working_seconds % 3600) // 60
    avg_hours = round(total_working_seconds / total_working_days / 3600, 2) if total_working_days > 0 else 0

    return {
        'employee': employee,
        'profile': profile,
        'shift': shift,
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
    from django.db.models import Q
    from decimal import Decimal
    from .models import Attendance, LeaveRequest, Holiday, LateComingRule

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
    shift = employee.shift if employee.shift else None
    user = employee.user

    # ── OT rate: auto-computed from basic × shift multiplier ──
    if shift and shift.overtime_allowed:
        _monthly_hours = Decimal(208)
        _multiplier = Decimal(str(shift.overtime_multiplier or 1.50))
        ot_rate = (basic / _monthly_hours * _multiplier).quantize(Decimal('0.01'))
    else:
        ot_rate = Decimal('0')

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

    _start_day = first_day
    if employee.date_of_joining and employee.date_of_joining > first_day:
        _start_day = employee.date_of_joining

    working_days = 0
    for n in range((_end_day - _start_day).days + 1):
        d = _start_day + timedelta(n)
        if d in holidays:
            continue
        if shift:
            day_abbr = d.strftime('%a').lower()[:3]
            if not getattr(shift, day_abbr, False):
                continue
        working_days += 1

    # ── Attendance ──
    attendances = Attendance.objects.filter(
        user=user,
        company=company,
        date__year=year,
        date__month=month
    )

    # ═══════════════════════════════════════════════════════════════
    # FIX #2 — Present days (count all "worked" statuses)
    # ═══════════════════════════════════════════════════════════════
    present_days = Decimal('0')
    for att in attendances:
        if att.status in ('Present', 'Under Review', 'Missing Checkout',
                          'Weekend Work', 'Holiday Work'):
            present_days += Decimal('1')
        elif att.status == 'Half-Day':
            present_days += Decimal('0.5')

    # ── Late Coming Rule ──
    late_rule, _ = LateComingRule.objects.get_or_create(company=company)

    late_days          = 0
    late_halfday_days  = 0
    total_late_minutes = 0

    if late_rule.is_enabled and shift:
        grace_delta  = timedelta(minutes=shift.grace_period or 0)
        cutoff_delta = timedelta(minutes=late_rule.half_day_cutoff_minutes)

        for att in attendances.filter(check_in_time__isnull=False):
            shift_start = timezone.make_aware(
                datetime.combine(att.date, shift.start_time)
            )
            check_in = att.check_in_time

            if check_in <= shift_start + grace_delta:
                continue

            minutes_late = int((check_in - shift_start).total_seconds() // 60)
            total_late_minutes += minutes_late

            if check_in > shift_start + cutoff_delta:
                late_halfday_days += 1
            else:
                late_days += 1

    # ── Overtime (reuses existing calculation) ──
    overtime_minutes = 0
    for att in attendances:
        if att.check_in_time and att.check_out_time and shift:
            if not shift.overtime_allowed:
                continue
            shift_end = timezone.make_aware(
                datetime.combine(att.date, shift.end_time)
            )
            if att.check_out_time > shift_end:
                ot_min = int((att.check_out_time - shift_end).total_seconds() // 60)
                if shift.overtime_limit:
                    limit_min = int(shift.overtime_limit * 60)
                    if ot_min > limit_min:
                        ot_min = limit_min
                overtime_minutes += ot_min

    overtime_hours = Decimal(str(round(overtime_minutes / 60, 2)))
    overtime_amount = overtime_hours * ot_rate

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

    if late_rule.is_enabled and late_rule.penalty_type != 'none':

        if late_rule.calculation_method == 'marks':
            billable_marks = max(0, late_days - late_rule.monthly_allowed_late_marks)
            marks_penalty  = Decimal(str(billable_marks)) * Decimal(str(late_rule.penalty_amount))
            half_penalty   = Decimal(str(late_halfday_days)) * Decimal('0.5')
            late_penalty_days = marks_penalty + half_penalty

        elif late_rule.calculation_method == 'minutes':
            slab = late_rule.minute_slabs.filter(
                from_minutes__lte=total_late_minutes
            ).filter(
                Q(to_minutes__isnull=True) | Q(to_minutes__gte=total_late_minutes)
            ).first()
            if slab and slab.penalty_days:
                late_penalty_days = slab.penalty_days

        if late_penalty_days > 0:
            can_use_leave = (
                late_rule.penalty_type == 'leave'
                and late_rule.target_leave_type is not None
            )

            if can_use_leave:
                balance   = get_leave_balance(user, late_rule.target_leave_type)
                available = max(Decimal('0'), balance['available'])

                late_leave_days = min(late_penalty_days, available)
                remainder       = late_penalty_days - late_leave_days

                if remainder > 0:
                    if late_rule.insufficient_balance_action == 'lop':
                        late_lop_days = remainder
            else:
                late_lop_days = late_penalty_days

        late_deduction = (per_day * late_lop_days).quantize(Decimal('0.01'))
        late_halfday_deduction = (per_day * late_penalty_days).quantize(Decimal('0.01'))

    total_deduction = (
        absent_deduction
        + unpaid_leave_deduction
        + other_deduction
        + late_deduction
    )
    net_payable = gross + overtime_amount - total_deduction

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
        'pure_absent_days':      pure_absent_days,
        'pure_absent_deduction': pure_absent_deduction,
        'half_day_days':         half_day_count,
        'half_day_units':        half_day_units,
        'half_day_deduction':    half_day_deduction,
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
      - Days absorbed by late-arrival penalties (YTD)

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
    from .models import LeaveRequest, Payroll, LateComingRule

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

    # ── Late penalty absorbed into this leave type ──
    late_used = Decimal('0')
    profile = getattr(user, 'profile', None)
    if profile and getattr(profile, 'company', None):
        rule = LateComingRule.objects.filter(company=profile.company).first()
        if rule and rule.target_leave_type_id == leave_type.id:
            late_used = Payroll.objects.filter(
                employee=profile,
                year=year,
            ).aggregate(s=Sum('late_leave_days'))['s'] or Decimal('0')

    available = total - used - late_used

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
    