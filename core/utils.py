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


def get_company_filtered(request, queryset, company_field='company'):
    """
    Filter a queryset by the current user's company.

    - Superuser → returns the queryset unchanged (sees all).
    - HR Admin / Manager / Employee → filters by their company.
    - No company → returns empty queryset.
    """
    if not request.user.is_authenticated:
        return queryset.none()

    # Superuser sees everything
    if request.user.is_superuser:
        return queryset

    company = getattr(request, 'user_company', None)
    if company is None:
        return queryset.none()

    # Apply company filter
    return queryset.filter(**{company_field: company})


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

    company = getattr(request, 'user_company', None)
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
    from decimal import Decimal
    from .models import Attendance, LeaveRequest, Holiday

    first_day = date(year, month, 1)
    _, last_day_num = monthrange(year, month)
    last_day = date(year, month, last_day_num)

    # ── Salary components ──
    basic = Decimal(str(salary.basic_salary or 0))
    hra = Decimal(str(salary.hra or 0))
    allowance = Decimal(str(salary.allowance or 0))
    gross = basic + hra + allowance
    ot_rate = Decimal(str(salary.overtime_rate or 0))

    # ✅ `employee` IS the profile — no `.profile`
    company = employee.company
    shift = employee.shift if employee.shift else None
    user = employee.user

    # ── Holidays ──
    holidays = set(
        Holiday.objects.filter(
            company=company,
            date__gte=first_day,
            date__lte=last_day
        ).values_list('date', flat=True)
    )

    # ── Working days ──
    working_days = 0
    for d in (first_day + timedelta(n) for n in range((last_day - first_day).days + 1)):
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

    present_days = attendances.filter(status='Present').count()

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

    # ✅ MOVED OUTSIDE THE LOOP
    # ── Absent days ──
    absent_days = max(
        0,
        working_days - present_days - int(paid_leave_days) - int(unpaid_leave_days)
    )

    # ── Per-day salary ──
    per_day = (gross / Decimal(str(working_days))) if working_days > 0 else Decimal('0')

    # ── Deductions ──
    absent_deduction = (per_day * Decimal(str(absent_days))).quantize(Decimal('0.01'))
    unpaid_leave_deduction = (per_day * unpaid_leave_days).quantize(Decimal('0.01'))
    other_deduction = Decimal('0')

    total_deduction = absent_deduction + unpaid_leave_deduction + other_deduction
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
        'total_deduction': total_deduction,
        'net_payable': net_payable,
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
    

    