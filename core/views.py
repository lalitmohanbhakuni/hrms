from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User, Group
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse, JsonResponse, FileResponse
from django.db import transaction
from django.db.models import Q, Sum, Count
from django.views.decorators.http import require_http_methods
from datetime import date, timedelta, datetime
from decimal import Decimal
from calendar import monthrange
from io import BytesIO
from math import radians, sin, cos, sqrt, atan2
import csv
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User


from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm

from django_ratelimit.decorators import ratelimit

from .models import (
    Attendance, LeaveType, Holiday, LeaveRequest, Notification,
    RegularizationRequest, EmployeeProfile, Shift, Company,
    OfficeLocation, EmployeeSalary, Payroll,
    PasswordResetRequest,
)
from .forms import (
    EmployeeForm,
    ForgotPasswordForm,
    SetNewPasswordForm,
)
from .decorators import (
    admin_or_hr_required, hr_admin_required,
    company_required, payroll_required
)
from .utils import (
    get_approver, get_hr_admin, can_approve_request,
    get_company_filtered, get_user_company
)






def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c


def create_notification(user, message, notification_type='info', related_object=None):
    Notification.objects.create(
        user=user,
        message=message,
        notification_type=notification_type,
        related_object_id=related_object.id if related_object else None,
        related_object_type=related_object._meta.model_name if related_object else None,
    )


def notify_admins(message, notification_type='info', related_object=None):
    for admin in User.objects.filter(is_superuser=True):
        create_notification(admin, message, notification_type, related_object)


@ratelimit(key='ip', rate='5/m', method='POST', block=False)
def login_view(request):
    if request.method == 'POST':
        if getattr(request, 'limited', False):
            messages.error(request, 'Too many login attempts. Please try again after 1 minute.')
            return render(request, 'login.html')

        login_input = request.POST.get('username', '').strip()
        password    = request.POST.get('password', '')

        if not login_input or not password:
            messages.error(request, 'Please enter both username and password.')
            return render(request, 'login.html')

        user = None

        # 1) Username
        user = authenticate(request, username=login_input, password=password)

        # 2) Employee ID (case-insensitive, unique)
        if user is None:
            from .models import EmployeeProfile
            matches = EmployeeProfile.objects.filter(employee_id__iexact=login_input)
            if matches.count() == 1:
                profile = matches.first()
                if profile.user.is_active:
                    user = authenticate(
                        request,
                        username=profile.user.username,
                        password=password,
                    )

        # 3) Email (unique)
        if user is None:
            from django.contrib.auth.models import User
            matches = User.objects.filter(email__iexact=login_input, is_active=True)
            if matches.count() == 1:
                u = matches.first()
                user = authenticate(request, username=u.username, password=password)

        if user is not None:
            if not user.is_active:
                messages.error(request, 'Your account is inactive. Contact your HR admin.')
                return render(request, 'login.html')
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, 'Invalid credentials. Please try again.')

    return render(request, 'login.html')


# ✅ ADD THIS RIGHT HERE
def logout_view(request):
    logout(request)
    return redirect('login')




# ---------- Dashboard ----------
@login_required
def dashboard(request):
    from .utils import get_company_filtered, get_user_company
    
    user = request.user
    today = date.today()
    current_company = get_user_company(request)

    month_str = request.GET.get('month', '')
    year_str = request.GET.get('year', '')
    admin_month_str = request.GET.get('admin_month', '')
    admin_year_str = request.GET.get('admin_year', '')

    month = int(month_str) if month_str and month_str.isdigit() else today.month
    year = int(year_str) if year_str and year_str.isdigit() else today.year
    admin_month = int(admin_month_str) if admin_month_str and admin_month_str.isdigit() else today.month
    admin_year = int(admin_year_str) if admin_year_str and admin_year_str.isdigit() else today.year

    if month < 1 or month > 12:
        month = today.month
    if year < 2000 or year > 2100:
        year = today.year
    if admin_month < 1 or admin_month > 12:
        admin_month = today.month
    if admin_year < 2000 or admin_year > 2100:
        admin_year = today.year

    selected_date = date(year, month, 1)

    today_attendance = Attendance.objects.filter(user=user, date=today).first()
    monthly_history = Attendance.objects.filter(
        user=user,
        date__year=year,
        date__month=month
    ).order_by('-date')


    # ---------- Employee Shift ----------
    employee_shift = None
    if hasattr(user, 'profile') and user.profile and user.profile.shift:
        employee_shift = user.profile.shift

    
    # ---------- Late minutes ----------
    late_minutes = 0
    if today_attendance and today_attendance.state == 'checked_in':
        if employee_shift:
            shift_start = datetime.combine(today, employee_shift.start_time)
            shift_start = timezone.make_aware(shift_start)
            check_in = today_attendance.check_in_time
            if check_in > shift_start:
                late_minutes = int((check_in - shift_start).total_seconds() // 60)
                
        

    # ---------- Attendance Calendar (role-aware) ----------
    first_day = date(year, month, 1)
    _, num_days = monthrange(year, month)
    last_day = date(year, month, num_days)

    # Determine scope + mode
    is_admin_or_owner = (
        user.is_superuser
        or user.groups.filter(name='HR Admin').exists()
    )
    is_manager = (
        not is_admin_or_owner
        and hasattr(user, 'profile')
        and user.profile
        and user.profile.role == 'manager'
    )

    if is_admin_or_owner:
        scope_user_ids = list(
            User.objects.filter(
                is_superuser=False,
                profile__is_active=True,
                profile__company=current_company,
            ).values_list('id', flat=True)
        )
        calendar_mode = 'team'
    elif is_manager:
        scope_user_ids = list(
            EmployeeProfile.objects.filter(
                manager=user.profile,
                is_active=True,
            ).values_list('user_id', flat=True)
        )
        calendar_mode = 'team'
    else:
        scope_user_ids = [user.id]
        calendar_mode = 'self'

    # Per-day attendance aggregates within scope
    month_attendance = Attendance.objects.filter(
        date__year=year,
        date__month=month,
        user_id__in=scope_user_ids,
    ).values('date', 'user_id', 'status')
    
    attendance_by_day = {}   # day -> {'Present': n, 'Absent': n, 'Half-Day': n}
    for row in month_attendance:
        d = row['date'].day
        st = row['status'] or 'Absent'
        attendance_by_day.setdefault(d, {}).setdefault(st, 0)
        attendance_by_day[d][st] += 1

    # Per-day leave counts within scope
    month_leaves = LeaveRequest.objects.filter(
        status='Approved',
        start_date__lte=last_day,
        end_date__gte=first_day,
        user_id__in=scope_user_ids,
    ).values('user_id', 'start_date', 'end_date')

    leave_by_day = {}
    for lv in month_leaves:
        s = max(lv['start_date'], first_day)
        e = min(lv['end_date'], last_day)
        for i in range((e - s).days + 1):
            d = (s + timedelta(days=i)).day
            leave_by_day[d] = leave_by_day.get(d, 0) + 1

    # Per-day holidays
    month_holidays = {
        h.date.day: h.name
        for h in Holiday.objects.filter(
            company=current_company,
            date__gte=first_day,
            date__lte=last_day,
        )
    }
    calendar_data = []
    for day in range(1, num_days + 1):
        current_date = date(year, month, day)
        is_weekend = current_date.weekday() >= 5

        holiday_name = month_holidays.get(day)
        counts = attendance_by_day.get(day, {})
        on_leave = leave_by_day.get(day, 0)

        present_count = counts.get('Present', 0)
        half_count    = counts.get('Half-Day', 0)

        # ── Compute absent dynamically (team mode only) ──
                # ── Compute absent dynamically (team mode only) ──
        absent_count = 0
        if calendar_mode == 'team' and current_date <= today and not is_weekend and not holiday_name:
            # Only count employees who had already joined by this date
            employees_joined_by_date = EmployeeProfile.objects.filter(
                user_id__in=scope_user_ids,
                is_active=True,
                date_of_joining__lte=current_date,
            ).count()

            expected = max(0, employees_joined_by_date - on_leave)
            absent_count = max(0, expected - present_count - half_count)

        row = {
            'day': day,
            'date': current_date,
            'is_weekend': is_weekend,
            'is_holiday': bool(holiday_name),
            'holiday_name': holiday_name,
            'mode': calendar_mode,
            'counts': {
                'present': present_count,
                'absent':  absent_count,           # ✅ computed for team
                'half':    half_count,
                'leave':   on_leave,
            },
            'employees': [],
        }

        # ── Build per-employee list for team mode ──
        if calendar_mode == 'team':
            day_attendance = Attendance.objects.filter(
                date=current_date,
                user_id__in=scope_user_ids,
            ).select_related('user', 'user__profile')

            att_by_user = {a.user_id: a for a in day_attendance}

            day_leaves = LeaveRequest.objects.filter(
                status='Approved',
                start_date__lte=current_date,
                end_date__gte=current_date,
                user_id__in=scope_user_ids,
            ).values_list('user_id', flat=True)
            leave_user_ids = set(day_leaves)

            emps = EmployeeProfile.objects.filter(
                user_id__in=scope_user_ids,
                is_active=True,
            ).select_related('user')

            for emp in emps:
                att = att_by_user.get(emp.user_id)

                if emp.user_id in leave_user_ids:
                    status = 'Leave'
                elif att:
                    status = att.status or 'Absent'
                elif current_date > today:
                    status = 'Future'
                else:
                    status = 'Absent'

                row['employees'].append({
                    'name':         emp.full_name or emp.user.username,
                    'employee_id':  emp.employee_id,
                    'designation':  emp.designation or '—',
                    'department':   emp.department or '—',
                    'status':       status,
                    'check_in':     att.check_in_time.strftime('%I:%M %p') if att and att.check_in_time else '--:--',
                    'check_out':    att.check_out_time.strftime('%I:%M %p') if att and att.check_out_time else '--:--',
                })

        # Self mode → own status
        if calendar_mode == 'self':
            if holiday_name:
                row['self_status'] = 'holiday'
            elif is_weekend:
                row['self_status'] = 'weekend'
            elif on_leave:
                row['self_status'] = 'leave'
            elif counts.get('Present'):
                row['self_status'] = 'present'
            elif counts.get('Half-Day'):
                row['self_status'] = 'halfday'
            elif counts.get('Absent'):
                row['self_status'] = 'absent'
            elif current_date > today:
                row['self_status'] = 'future'
            else:
                row['self_status'] = 'none'
        else:
            row['self_status'] = None

        calendar_data.append(row)

    # ✅ OUTSIDE the loop — builds once, after all rows are in
    calendar_employees_json = {
        str(r['day']): r['employees']
        for r in calendar_data
        if r['mode'] == 'team'
    }
        

    first_weekday = first_day.weekday()

    pending_leaves = LeaveRequest.objects.filter(user=user, status='Pending').count()

    # ---------- Leave Balance ----------
    leave_types = get_company_filtered(request, LeaveType.objects.filter(is_active=True))
    leave_balance = []
    total_available = 0
    total_used = 0
    total_pending = 0
    for lt in leave_types:
        approved = LeaveRequest.objects.filter(user=user, leave_type=lt, status='Approved')
        used = sum(req.get_duration() for req in approved)
        pending = LeaveRequest.objects.filter(user=user, leave_type=lt, status='Pending')
        pending_days = sum(req.get_duration() for req in pending)
        available = lt.days_allowed - used
        total_available += available
        total_used += used
        total_pending += pending_days
        leave_balance.append({
            'leave_type': lt,
            'total': lt.days_allowed,
            'used': used,
            'pending': pending_days,
            'available': available,
        })

    selected_employee = user
    employee_id = request.GET.get('employee_id')
    if user.is_superuser and employee_id:
        try:
            selected_employee = User.objects.get(id=employee_id)
        except User.DoesNotExist:
            pass

    # ---------- Pending Actions Count & List (Team-based) ----------
    if user.is_superuser or user.groups.filter(name='HR Admin').exists():
        admin_requests = get_company_filtered(
            request,
            LeaveRequest.objects.filter(
                status='Pending',
                user__profile__manager__isnull=True
            )
        )
        pending_actions_count = admin_requests.count()
        pending_leave_requests = admin_requests.order_by('-applied_on')[:10]

        if user.is_superuser:
            all_today_attendance = Attendance.objects.filter(date=today).select_related('user')
            all_employees = User.objects.all().order_by('username')
            all_employees_attendance = Attendance.objects.filter(
                date__year=admin_year,
                date__month=admin_month
            ).select_related('user').order_by('user__username', 'date')
        else:
            all_today_attendance = get_company_filtered(
                request, Attendance.objects.filter(date=today)
            ).select_related('user')
            all_employees = User.objects.filter(
                is_superuser=False, profile__company=current_company
            ).order_by('username')
            all_employees_attendance = get_company_filtered(
                request,
                Attendance.objects.filter(
                    date__year=admin_year,
                    date__month=admin_month
                )
            ).select_related('user').order_by('user__username', 'date')

    elif user.groups.filter(name='Manager').exists():
        try:
            profile = user.profile
            team_members = EmployeeProfile.objects.filter(manager=profile).values_list('user_id', flat=True)
            manager_requests = LeaveRequest.objects.filter(
                status='Pending',
                user_id__in=team_members
            )
            pending_actions_count = manager_requests.count()
            pending_leave_requests = manager_requests.order_by('-applied_on')[:10]
        except EmployeeProfile.DoesNotExist:
            pending_actions_count = 0
            pending_leave_requests = LeaveRequest.objects.none()
        all_today_attendance = None
        all_employees = None
        all_employees_attendance = None
    else:
        pending_actions_count = LeaveRequest.objects.filter(user=user, status='Pending').count()
        pending_leave_requests = LeaveRequest.objects.filter(user=user, status='Pending').order_by('-applied_on')[:10]
        all_today_attendance = None
        all_employees = None
        all_employees_attendance = None

    pending_actions = pending_leave_requests

    # ---------- Manager-specific Stats ----------
    team_count = 0
    team_present_today = 0
    team_on_leave_today = 0
    team_pending_actions_count = 0
    team_absent_today = 0
    team_attendance_rate = 0

    if user.groups.filter(name='Manager').exists():
        try:
            profile = user.profile
            team_members = EmployeeProfile.objects.filter(
                manager=profile,
                is_active=True,
            ).values_list('user_id', flat=True)
            team_count = team_members.count()

            team_present_today = Attendance.objects.filter(
                date=today,
                status='Present',
                user_id__in=team_members
            ).values('user').distinct().count()

            team_on_leave_today = LeaveRequest.objects.filter(
                status='Approved',
                start_date__lte=today,
                end_date__gte=today,
                user_id__in=team_members
            ).values('user').distinct().count()

            team_pending_actions_count = LeaveRequest.objects.filter(
                status='Pending',
                user_id__in=team_members
            ).count()

            # ✅ Team Attendance Rate
            team_expected = max(0, team_count - team_on_leave_today)
            if team_expected > 0:
                team_attendance_rate = round((team_present_today / team_expected) * 100)
            else:
                team_attendance_rate = 0
            team_attendance_rate = max(0, min(100, team_attendance_rate))

            # ✅ Absent = expected − present (never negative)
            team_absent_today = max(0, team_expected - team_present_today)

        except EmployeeProfile.DoesNotExist:
            pass

    # ---------- Monthly Chart Data ----------
    attendance_chart_labels = []
    attendance_chart_present = []
    attendance_chart_absent = []
    attendance_chart_half = []

    if user.is_superuser or user.groups.filter(name='HR Admin').exists():
        year_attendances = get_company_filtered(
            request,
            Attendance.objects.filter(date__year=today.year)
        )
        for month_num in range(1, 13):
            month_attendances = year_attendances.filter(date__month=month_num)
            month_name = date(today.year, month_num, 1).strftime('%b')
            attendance_chart_labels.append(month_name)
            attendance_chart_present.append(month_attendances.filter(status='Present').count())
            attendance_chart_absent.append(month_attendances.filter(status='Absent').count())
            attendance_chart_half.append(month_attendances.filter(status='Half-Day').count())

    # ---------- Weekly Bar Chart Data ----------
    start_of_week = today - timedelta(days=today.weekday())
    week_start = start_of_week
    week_end = start_of_week + timedelta(days=6)

    weekly_days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    weekly_day_present = [0, 0, 0, 0, 0, 0, 0]
    weekly_day_absent = [0, 0, 0, 0, 0, 0, 0]
    weekly_day_half = [0, 0, 0, 0, 0, 0, 0]
    weekly_day_onleave = [0, 0, 0, 0, 0, 0, 0]

    manager_weekly_days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    manager_weekly_day_present = [0, 0, 0, 0, 0, 0, 0]
    manager_weekly_day_absent = [0, 0, 0, 0, 0, 0, 0]
    manager_weekly_day_half = [0, 0, 0, 0, 0, 0, 0]
    manager_weekly_day_onleave = [0, 0, 0, 0, 0, 0, 0]

    # ---------- ADMIN CHART (Superuser / HR Admin) ----------
    if user.is_superuser or user.groups.filter(name='HR Admin').exists():
        total_employees = get_company_filtered(
            request,
            User.objects.filter(
                is_superuser=False,
                profile__is_active=True,
            )
        ).count()
        weekly_days = []
        weekly_day_present = []
        weekly_day_absent = []
        weekly_day_half = []
        weekly_day_onleave = []

        for i in range(7):
            day = start_of_week + timedelta(days=i)
            if day <= today:
                present = get_company_filtered(
                    request,
                    Attendance.objects.filter(
                        date=day,
                        status='Present',
                        user__is_superuser=False,
                        user__profile__is_active=True,
                    )
                ).values('user').distinct().count()
                half = get_company_filtered(
                    request,
                    Attendance.objects.filter(
                        date=day,
                        status='Half-Day',
                        user__is_superuser=False,
                        user__profile__is_active=True,
                    )
                ).values('user').distinct().count()
                on_leave = get_company_filtered(
                    request,
                    LeaveRequest.objects.filter(
                        status='Approved',
                        start_date__lte=day,
                        end_date__gte=day,
                        user__is_superuser=False,
                        user__profile__is_active=True,
                    )
                ).values('user').distinct().count()
                absent = max(0, total_employees - present - on_leave)
            else:
                present = 0
                absent = 0
                half = 0
                on_leave = 0
            weekly_days.append(day.strftime('%a'))
            weekly_day_present.append(present)
            weekly_day_absent.append(absent)
            weekly_day_half.append(half)
            weekly_day_onleave.append(on_leave)

        week_start = start_of_week
        week_end = start_of_week + timedelta(days=6)

    # ---------- MANAGER CHART (Manager only) ----------
    elif user.groups.filter(name='Manager').exists():
        try:
            profile = user.profile
            team_members = EmployeeProfile.objects.filter(
                manager=profile,
                is_active=True,
            ).values_list('user_id', flat=True)
            team_count = team_members.count()
            manager_weekly_days = []
            manager_weekly_day_present = []
            manager_weekly_day_absent = []
            manager_weekly_day_half = []
            manager_weekly_day_onleave = []

            for i in range(7):
                day = start_of_week + timedelta(days=i)
                if day <= today:
                    present = Attendance.objects.filter(
                        date=day,
                        status='Present',
                        user_id__in=team_members
                    ).values('user').distinct().count()
                    half = Attendance.objects.filter(
                        date=day,
                        status='Half-Day',
                        user_id__in=team_members
                    ).values('user').distinct().count()
                    on_leave = LeaveRequest.objects.filter(
                        status='Approved',
                        start_date__lte=day,
                        end_date__gte=day,
                        user_id__in=team_members
                    ).values('user').distinct().count()
                    absent = max(0, team_count - present - on_leave)
                else:
                    present = 0
                    absent = 0
                    half = 0
                    on_leave = 0
                manager_weekly_days.append(day.strftime('%a'))
                manager_weekly_day_present.append(present)
                manager_weekly_day_absent.append(absent)
                manager_weekly_day_half.append(half)
                manager_weekly_day_onleave.append(on_leave)
        except EmployeeProfile.DoesNotExist:
            pass

    # ---------- TOTAL EMPLOYEES (for non-superuser) ----------
    if not user.is_superuser:
        total_employees = get_company_filtered(
            request,
            User.objects.filter(
                is_superuser=False,
                profile__is_active=True,
            )
        ).count()

    # ---- Month navigation ----
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    next_disabled = (year == today.year and month == today.month)
    admin_prev_month = admin_month - 1 if admin_month > 1 else 12
    admin_prev_year = admin_year if admin_month > 1 else admin_year - 1
    admin_next_month = admin_month + 1 if admin_month < 12 else 1
    admin_next_year = admin_year if admin_month < 12 else admin_year + 1
    admin_next_disabled = (admin_year == today.year and admin_month == today.month)

    base_params = f"month={month}&year={year}"
    if employee_id:
        base_params += f"&employee_id={employee_id}"
    admin_base_params = f"admin_month={admin_month}&admin_year={admin_year}"

    # ---------- Dashboard Stats ----------
    present_today = get_company_filtered(
        request,
        Attendance.objects.filter(
            date=today,
            status='Present',
            user__is_superuser=False,
            user__profile__is_active=True,
        )
    ).values('user').distinct().count()

    on_leave_today = get_company_filtered(
        request,
        LeaveRequest.objects.filter(
            status='Approved',
            start_date__lte=today,
            end_date__gte=today,
            user__profile__is_active=True,
        )
    ).values('user').distinct().count()

    # ✅ Absent = active − present − on leave (never negative)
    absent_today = max(0, total_employees - present_today - on_leave_today)

    # ✅ Attendance Rate (for HR Admin / Owner only)
    attendance_rate = 0
    if user.is_superuser or user.groups.filter(name='HR Admin').exists():
        expected = max(0, total_employees - on_leave_today)
        if expected > 0:
            attendance_rate = round((present_today / expected) * 100)
        attendance_rate = max(0, min(100, attendance_rate))

    next_holiday = get_company_filtered(
        request,
        Holiday.objects.filter(date__gte=today)
    ).order_by('date').first()

    today_total_seconds = 0
    if today_attendance and today_attendance.total_working_time:
        today_total_seconds = int(today_attendance.total_working_time.total_seconds())


    # ---------- Admin: Employee Data for Dashboard (expandable table) ----------
    employee_data = []

    if user.is_superuser or user.groups.filter(name='HR Admin').exists():
        employees = get_company_filtered(
            request,
            User.objects.filter(
                is_superuser=False,
                profile__is_active=True,
            )
        ).order_by('username')
        
        attendances = get_company_filtered(
            request,
            Attendance.objects.filter(
                date__year=admin_year,
                date__month=admin_month
            )
        ).select_related('user')
        
        for emp in employees:
            emp_records = [att for att in attendances if att.user == emp]
            total_days = len(emp_records)
            present = len([r for r in emp_records if r.status == 'Present'])
            absent = len([r for r in emp_records if r.status == 'Absent'])
            half_day = len([r for r in emp_records if r.status == 'Half-Day'])
            percentage = int((present / total_days) * 100) if total_days > 0 else 0
            
            profile = getattr(emp, 'profile', None)
            shift_name = profile.shift.name if profile and profile.shift else '—'
            shift_timing = ''
            if profile and profile.shift:
                start = profile.shift.start_time.strftime('%I:%M %p')
                end = profile.shift.end_time.strftime('%I:%M %p')
                shift_timing = f"{start} – {end}"
            
            records = []
            for att in emp_records:
                records.append({
                    'date': att.date,
                    'in_time': att.check_in_time.strftime('%I:%M %p') if att.check_in_time else '--:--',
                    'out_time': att.check_out_time.strftime('%I:%M %p') if att.check_out_time else '--:--',
                    'status': att.status,
                })
            
            employee_data.append({
                'employee': emp,
                'records': records,
                'total_days': total_days,
                'present': present,
                'absent': absent,
                'half_day': half_day,
                'percentage': percentage,
                'shift_name': shift_name,
                'shift_timing': shift_timing,
            })
    else:
        employee_data = []

    context = {
        'user': user,
        'selected_employee': selected_employee,
        'today_attendance': today_attendance,
        'monthly_history': monthly_history,
        'today': today,
        'pending_leaves': pending_leaves,
        'all_employees_attendance': all_employees_attendance,
        'all_employees': all_employees,
        'selected_month_name': selected_date.strftime('%B %Y'),
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
        'next_disabled': next_disabled,
        'base_params': base_params,
        'employee_id': employee_id,
        'admin_selected_month_name': date(admin_year, admin_month, 1).strftime('%B %Y'),
        'admin_prev_month': admin_prev_month,
        'admin_prev_year': admin_prev_year,
        'admin_next_month': admin_next_month,
        'admin_next_year': admin_next_year,
        'admin_next_disabled': admin_next_disabled,
        'admin_base_params': admin_base_params,
        'leave_balance': leave_balance,
        'total_available': total_available,
        'total_used': total_used,
        'total_pending': total_pending,
        'pending_leave_requests': pending_leave_requests,
        'pending_actions': pending_actions,
        'attendance_chart_labels': attendance_chart_labels,
        'attendance_chart_present': attendance_chart_present,
        'attendance_chart_absent': attendance_chart_absent,
        'attendance_chart_half': attendance_chart_half,
        'weekly_days': weekly_days,
        'weekly_day_present': weekly_day_present,
        'weekly_day_absent': weekly_day_absent,
        'weekly_day_half': weekly_day_half,
        'weekly_day_onleave': weekly_day_onleave,
        'week_start': week_start,
        'week_end': week_end,
        'total_employees': total_employees,
        'present_today': present_today,
        'absent_today': absent_today,
        'pending_actions_count': pending_actions_count,
        'next_holiday': next_holiday,
        'today_total_seconds': today_total_seconds,
        'calendar_data': calendar_data,
        'first_weekday': first_weekday,
        'month': month,
        'year': year,
        'on_leave_today': on_leave_today,
        'employee_shift': employee_shift,
        'late_minutes': late_minutes,
        'team_count': team_count,
        'team_present_today': team_present_today,
        'team_on_leave_today': team_on_leave_today,
        'team_pending_actions_count': team_pending_actions_count,
        'team_attendance_rate': team_attendance_rate,
        'team_absent_today': team_absent_today,
        'manager_weekly_days': manager_weekly_days,
        'manager_weekly_day_present': manager_weekly_day_present,
        'manager_weekly_day_absent': manager_weekly_day_absent,
        'manager_weekly_day_half': manager_weekly_day_half,
        'manager_weekly_day_onleave': manager_weekly_day_onleave,
        'employee_data': employee_data,
        'attendance_rate': attendance_rate,
        'calendar_employees_json': calendar_employees_json,
    }
    return render(request, 'dashboard.html', context)


# ---------- Attendance ----------
@login_required
def clock_in(request):
    from datetime import timedelta

    if request.method != 'POST':
        return redirect('dashboard')

    user = request.user
    today = date.today()

    # Already checked in?
    attendance = Attendance.objects.filter(user=user, date=today).first()
    if attendance and attendance.state == 'checked_in':
        messages.warning(request, 'You are already checked in.')
        return redirect('dashboard')

    profile = getattr(user, 'profile', None)
    if not profile:
        messages.error(request, 'Employee profile not found.')
        return redirect('dashboard')

    company = profile.company
    attendance_type = profile.attendance_type
    check_in_lat = None
    check_in_lng = None
    check_in_dist = None

    if attendance_type == 'office':
        office = profile.office_location
        if not office:
            messages.error(request, 'No office location assigned. Please contact HR.')
            return redirect('dashboard')

        # Get real client IP (works behind proxies/Render)
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        client_ip = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')

        # ─────────────────────────────────────────────
        # Path 1: Office WiFi IP match (from OfficeLocation)
        # ─────────────────────────────────────────────
        ip_allowed = office.matches_ip(client_ip)

        # DEBUG
        print(f'[CLOCK-IN] client_ip={client_ip!r}')
        print(f'[CLOCK-IN] office.allowed_ip_prefix={office.allowed_ip_prefix!r}')
        print(f'[CLOCK-IN] ip_allowed={ip_allowed}')
        

        if ip_allowed:
            # ✅ On office WiFi — allow check-in without GPS
            lat = request.POST.get('latitude')
            lng = request.POST.get('longitude')
            if lat and lng:
                try:
                    check_in_lat = float(lat)
                    check_in_lng = float(lng)
                    check_in_dist = int(haversine(
                        check_in_lat, check_in_lng,
                        float(office.latitude), float(office.longitude)
                    ))
                except (ValueError, TypeError):
                    pass
        else:
            # ─────────────────────────────────────────
            # Path 2: GPS fallback
            # ─────────────────────────────────────────
            lat = request.POST.get('latitude')
            lng = request.POST.get('longitude')
            accuracy = request.POST.get('accuracy')

            if not lat or not lng:
                messages.error(
                    request,
                    'Please connect to office WiFi, or enable GPS on your mobile device.'
                )
                return redirect('dashboard')

            try:
                lat = float(lat)
                lng = float(lng)
                accuracy = float(accuracy) if accuracy else 0
            except ValueError:
                messages.error(request, 'Invalid location data.')
                return redirect('dashboard')

            if accuracy > 500:
                messages.error(
                    request,
                    f'GPS signal too weak (±{accuracy:.0f}m). '
                    'Please connect to office WiFi or use a mobile phone.'
                )
                return redirect('dashboard')

            distance = haversine(lat, lng, float(office.latitude), float(office.longitude))
            if distance > office.allowed_radius:
                messages.error(
                    request,
                    f'You are not in the office location. '
                    f'(Distance: {distance:.0f}m, Allowed: {office.allowed_radius}m)'
                )
                return redirect('dashboard')

            check_in_lat = lat
            check_in_lng = lng
            check_in_dist = int(distance)
    else:
        # Remote / Flexible — capture location if provided
        lat = request.POST.get('latitude')
        lng = request.POST.get('longitude')
        if lat and lng:
            try:
                check_in_lat = float(lat)
                check_in_lng = float(lng)
            except ValueError:
                pass

    # ─────────────────────────────────────────────
    # Save attendance
    # ─────────────────────────────────────────────
    if attendance and attendance.state == 'checked_out':
        attendance.check_in_time = timezone.now()
        attendance.check_out_time = None
        attendance.total_working_time = timedelta(0)
        attendance.state = 'checked_in'
        attendance.company = company
        attendance.check_in_latitude = check_in_lat
        attendance.check_in_longitude = check_in_lng
        attendance.check_in_distance = check_in_dist
        attendance.save()
    else:
        attendance = Attendance.objects.create(
            user=user,
            company=company,
            check_in_time=timezone.now(),
            state='checked_in',
            total_working_time=timedelta(0),
            check_in_latitude=check_in_lat,
            check_in_longitude=check_in_lng,
            check_in_distance=check_in_dist,
        )

    local_time = timezone.localtime(attendance.check_in_time)
    messages.success(request, f'Clocked in at {local_time.strftime("%I:%M:%S %p")}')
    return redirect('dashboard')

@login_required
def clock_out(request):
    from datetime import timedelta

    today = date.today()
    attendance = Attendance.objects.filter(
        user=request.user, date=today, state='checked_in'
    ).first()

    if not attendance:
        messages.warning(request, 'You are not checked in.')
        return redirect('dashboard')

    profile = getattr(request.user, 'profile', None)
    if not profile:
        messages.error(request, 'Employee profile not found.')
        return redirect('dashboard')

    company = profile.company
    attendance_type = profile.attendance_type
    check_out_lat = None
    check_out_lng = None

    # ─── Location validation for Office employees ───
    if attendance_type == 'office':
        office = profile.office_location
        if not office:
            messages.error(request, 'No office location assigned. Contact HR.')
            return redirect('dashboard')

        # Get client IP
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        client_ip = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')

        # Path 1: Office WiFi (from OfficeLocation)
        ip_allowed = office.matches_ip(client_ip)

        if ip_allowed:
            lat = request.POST.get('latitude')
            lng = request.POST.get('longitude')
            if lat and lng:
                try:
                    check_out_lat = float(lat)
                    check_out_lng = float(lng)
                except (ValueError, TypeError):
                    pass
        else:
            # Path 2: GPS fallback
            lat = request.POST.get('latitude')
            lng = request.POST.get('longitude')
            accuracy = request.POST.get('accuracy')

            if not lat or not lng:
                messages.error(
                    request,
                    'Please connect to office WiFi, or enable GPS to check out.'
                )
                return redirect('dashboard')

            try:
                lat = float(lat)
                lng = float(lng)
                accuracy = float(accuracy) if accuracy else 0
            except ValueError:
                messages.error(request, 'Invalid location data.')
                return redirect('dashboard')

            if accuracy > 500:
                messages.error(
                    request,
                    f'GPS signal too weak (±{accuracy:.0f}m). '
                    'Please connect to office WiFi or use a mobile phone.'
                )
                return redirect('dashboard')

            distance = haversine(lat, lng, float(office.latitude), float(office.longitude))
            if distance > office.allowed_radius:
                messages.error(
                    request,
                    f'You are not in the office location. '
                    f'(Distance: {distance:.0f}m, Allowed: {office.allowed_radius}m)'
                )
                return redirect('dashboard')

            check_out_lat = lat
            check_out_lng = lng
    else:
        # Remote / Flexible
        lat = request.POST.get('latitude')
        lng = request.POST.get('longitude')
        if lat and lng:
            try:
                check_out_lat = float(lat)
                check_out_lng = float(lng)
            except ValueError:
                pass

    # ─── Save check-out ───
    interval = timezone.now() - attendance.check_in_time
    if attendance.total_working_time:
        attendance.total_working_time += interval
    else:
        attendance.total_working_time = interval

    attendance.check_out_time = timezone.now()
    attendance.state = 'checked_out'
    attendance.check_out_latitude = check_out_lat
    attendance.check_out_longitude = check_out_lng
    attendance.save()

    local_out = timezone.localtime(attendance.check_out_time)
    messages.success(
        request,
        f'Clocked out at {local_out.strftime("%I:%M:%S %p")}. '
        f'Total worked today: {attendance.total_working_time}'
    )
    return redirect('dashboard')



# ---------- Helper ----------
def is_admin(user):
    return user.is_superuser


# ---------- Employee Management ----------

@login_required
@hr_admin_required
@company_required
def employee_list(request):
    employees = get_company_filtered(
        request,
        User.objects.filter(
            is_superuser=False,
            profile__is_active=True,          # ← ADD THIS
        )
    ).order_by('username')
    return render(request, 'employee_list.html', {'employees': employees})





@login_required
@hr_admin_required
@company_required
def employee_create(request):
    from .utils import get_user_company
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    # ✅ FIX #1 — fetch company BEFORE creating the form
    company = get_user_company(request)

    if request.method == 'POST':
        # ✅ FIX #2 — pass company so office_location/manager querysets are populated
        form = EmployeeForm(request.POST, company=company)
        if form.is_valid():
            username  = form.cleaned_data['username']
            email     = form.cleaned_data['email']
            password  = form.cleaned_data['password1']
            password2 = form.cleaned_data.get('password2', '')

            # ✅ ═══════════════════════════════════════════════════
            # ✅ PASSWORD VALIDATION
            # ✅ Rejects weak passwords using Django's built-in validators:
            # ✅   - Minimum 8 characters
            # ✅   - Not entirely numeric
            # ✅   - Not a common password
            # ✅   - Not too similar to username/email
            # ✅ ═══════════════════════════════════════════════════
            password_errors = []

            if not password:
                password_errors.append("Password is required.")

            if password and password2 and password != password2:
                password_errors.append("Passwords do not match.")

            if password:
                temp_user = User(username=username, email=email)
                try:
                    validate_password(password, user=temp_user)
                except ValidationError as exc:
                    password_errors.extend(exc.messages)

            if password_errors:
                for err in password_errors:
                    form.add_error('password1', err)
                    # messages.error(request, err)
                # Skip creation — render form with errors below
            else:
                # ✅ Password is valid → proceed with normal creation
                user = User.objects.create_user(
                    username=username, email=email, password=password
                )

                # ✅ Company already fetched at top — reuse it
                if not company and request.user.is_superuser:
                    # Superuser must pick a company from form
                    company_id = request.POST.get('company')
                    if company_id:
                        from .models import Company
                        company = Company.objects.filter(id=company_id).first()

                profile = EmployeeProfile(
                    user=user,
                    company=company,
                    full_name=form.cleaned_data['full_name'],
                    date_of_birth=form.cleaned_data.get('date_of_birth'),
                    date_of_joining=form.cleaned_data.get('date_of_joining'),
                    designation=form.cleaned_data.get('designation', ''),
                    department=form.cleaned_data.get('department', ''),
                    phone=form.cleaned_data.get('phone', ''),
                    address=form.cleaned_data.get('address', ''),
                    attendance_type=form.cleaned_data['attendance_type'],
                    office_location=form.cleaned_data.get('office_location'),
                    role=form.cleaned_data.get('role', 'employee'),
                )

                # Auto-generate employee_id within the company
                if company:
                    prefix = company.code_prefix
                    existing_ids = EmployeeProfile.objects.filter(
                        company=company, employee_id__startswith=prefix
                    ).values_list('employee_id', flat=True)
                    max_num = 0
                    for emp_id in existing_ids:
                        try:
                            num = int(emp_id[len(prefix):])
                            if num > max_num:
                                max_num = num
                        except ValueError:
                            continue
                    profile.employee_id = f"{prefix}{max_num + 1:04d}"
                else:
                    profile.employee_id = f"EMP{EmployeeProfile.objects.count() + 1:04d}"

                profile.save()

                # Manager assignment
                manager_id = request.POST.get('manager')
                if manager_id:
                    profile.manager_id = manager_id
                    profile.save(update_fields=['manager_id'])

                # Shift assignment
                shift_id = request.POST.get('shift')
                if shift_id:
                    profile.shift_id = shift_id
                    profile.save(update_fields=['shift_id'])

                # Role → group
                from django.contrib.auth.models import Group
                role = request.POST.get('role', 'employee')
                if role == 'manager':
                    grp, _ = Group.objects.get_or_create(name='Manager')
                    user.groups.add(grp)
                elif role == 'hr_admin':
                    grp, _ = Group.objects.get_or_create(name='HR Admin')
                    user.groups.add(grp)
                else:
                    user.groups.clear()

                messages.success(
                    request,
                    f'Employee {profile.full_name} created. ID: {profile.employee_id}'
                )
                return redirect('employee_list')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        # ✅ FIX #3 — GET form also needs company
        form = EmployeeForm(company=company)

    # Filter dropdowns by company
    from .utils import get_company_filtered
    shifts = get_company_filtered(request, Shift.objects.all()).order_by('name')
    offices = get_company_filtered(request, OfficeLocation.objects.all()).filter(is_active=True)
    all_managers = get_company_filtered(
        request,
        EmployeeProfile.objects.filter(
            role__in=['manager', 'hr_admin'],
            is_active=True,                    # ← ADD
        )
    ).order_by('full_name')

    context = {
        'form': form,
        'action': 'Create',
        'shifts': shifts,
        'offices': offices,
        'all_managers': all_managers,
    }
    return render(request, 'employee_form.html', context)

    

@login_required
@hr_admin_required
@company_required
def employee_edit(request, user_id):
    from .utils import get_user_company, get_company_filtered

    # ─── Cache company once ───
    company = None if request.user.is_superuser else get_user_company(request)

    # ─── Security: ownership check ───
    if request.user.is_superuser:
        user = get_object_or_404(User, id=user_id)
    else:
        user = get_object_or_404(User, id=user_id, profile__company=company)

    try:
        profile = EmployeeProfile.objects.get(user=user)
    except EmployeeProfile.DoesNotExist:
        # Determine company for new profile
        fallback_company = company
        if request.user.is_superuser:
            # For superuser, infer from the user's existing group/context if possible
            fallback_company = None   # superuser must pick company below
        profile = EmployeeProfile.objects.create(
            user=user,
            employee_id=f"EMP{user.id:04d}",
            full_name=user.username,
            company=fallback_company,
        )
        messages.info(request, f'Profile was missing – created a default profile for {user.username}.')

    if request.method == 'POST':
        user.username = request.POST.get('username')
        user.email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')
        if password1 or password2:
            if password1 == password2:
                user.set_password(password1)
            else:
                messages.error(request, 'Passwords do not match.')
                return redirect('employee_edit', user_id=user.id)
        user.save()

        profile.full_name = request.POST.get('full_name')
        profile.date_of_birth = request.POST.get('date_of_birth') or None
        profile.date_of_joining = request.POST.get('date_of_joining') or None
        profile.designation = request.POST.get('designation', '')
        profile.department = request.POST.get('department', '')
        profile.phone = request.POST.get('phone', '')
        profile.address = request.POST.get('address', '')
        profile.attendance_type = request.POST.get('attendance_type')
        profile.role = request.POST.get('role', 'employee')

        # ─── Security: validate office_location belongs to same company ───
        office_id = request.POST.get('office_location')
        if office_id:
            if request.user.is_superuser:
                office_ok = OfficeLocation.objects.filter(id=office_id).exists()
            else:
                office_ok = OfficeLocation.objects.filter(
                    id=office_id, company=company
                ).exists()
            profile.office_location_id = office_id if office_ok else None
        else:
            profile.office_location_id = None

        # ─── Security: validate manager belongs to same company ───
        manager_id = request.POST.get('manager')
        if manager_id:
            if request.user.is_superuser:
                manager_ok = EmployeeProfile.objects.filter(id=manager_id).exists()
            else:
                manager_ok = EmployeeProfile.objects.filter(
                    id=manager_id, company=company
                ).exists()
            profile.manager_id = manager_id if manager_ok else None
        else:
            profile.manager_id = None

        # ─── Security: validate shift belongs to same company ───
        shift_id = request.POST.get('shift')
        if shift_id:
            if request.user.is_superuser:
                shift_ok = Shift.objects.filter(id=shift_id).exists()
            else:
                shift_ok = Shift.objects.filter(
                    id=shift_id, company=company
                ).exists()
            profile.shift_id = shift_id if shift_ok else None
        else:
            profile.shift_id = None                # ← was `profile.shift = None`

        profile.save()

        # ─── Role → Group sync ───
        from django.contrib.auth.models import Group
        role = request.POST.get('role', 'employee')
        user.groups.clear()   # clean slate
        if role == 'manager':
            grp, _ = Group.objects.get_or_create(name='Manager')
            user.groups.add(grp)
        elif role == 'hr_admin':
            grp, _ = Group.objects.get_or_create(name='HR Admin')
            user.groups.add(grp)

        messages.success(request, f'Employee {profile.full_name} updated successfully.')
        return redirect('employee_list')

    # ─── Company-scoped dropdown data ───
    shifts = get_company_filtered(request, Shift.objects.all()).order_by('name')
    offices = get_company_filtered(
        request, OfficeLocation.objects.all()
    ).filter(is_active=True)

    # Only managers from the SAME company can be assigned
    all_managers = get_company_filtered(
        request,
        EmployeeProfile.objects.filter(
            role__in=['manager', 'hr_admin'],
            is_active=True,                    # ← ADD
        )
    ).order_by('full_name')

    context = {
        'employee_user': user,
        'profile': profile,
        'action': 'Edit',
        'shifts': shifts,
        'offices': offices,
        'all_managers': all_managers,
    }
    return render(request, 'employee_form.html', context)

        


@login_required
@hr_admin_required
@company_required
def employee_delete(request, user_id):
    from .utils import get_user_company
    from django.utils import timezone

    # ─── Security: ownership check ───
    if request.user.is_superuser:
        employee = get_object_or_404(User, id=user_id)
    else:
        company = get_user_company(request)
        employee = get_object_or_404(User, id=user_id, profile__company=company)

    if request.method == 'POST':
        if request.user == employee:
            messages.error(request, 'You cannot delete your own account!')
        else:
            # ─── SOFT DELETE (never hard-delete) ───
            profile = getattr(employee, 'profile', None)
            if profile:
                profile.is_active = False
                profile.terminated_at = timezone.localdate()
                profile.save(update_fields=['is_active', 'terminated_at'])

            employee.is_active = False
            employee.save(update_fields=['is_active'])

            emp_id = profile.employee_id if profile else employee.username
            messages.success(
                request,
                f'Employee {emp_id} deactivated. Their ID is retired and will not be reused.'
            )
        return redirect('employee_list')

    return render(request, 'employee_confirm_delete.html', {'employee': employee})


# ---------- Employee Detail ----------
@login_required
@hr_admin_required
@company_required
def employee_detail(request, user_id):
    from .utils import get_user_company
    
    if request.user.is_superuser:
        employee_user = get_object_or_404(User, id=user_id)
    else:
        company = get_user_company(request)
        employee_user = get_object_or_404(User, id=user_id, profile__company=company)
    
    profile = get_object_or_404(EmployeeProfile, user=employee_user)
    
    today = date.today()
    attendances = Attendance.objects.filter(
        user=employee_user,
        date__year=today.year,
        date__month=today.month
    )
    total_days = attendances.count()
    present = attendances.filter(status='Present').count()
    absent = attendances.filter(status='Absent').count()
    half_day = attendances.filter(status='Half-Day').count()
    
    leave_types = LeaveType.objects.filter(is_active=True, company=profile.company)
    leave_balance = []
    for lt in leave_types:
        approved = LeaveRequest.objects.filter(user=employee_user, leave_type=lt, status='Approved')
        used = sum(req.get_duration() for req in approved)
        pending = LeaveRequest.objects.filter(user=employee_user, leave_type=lt, status='Pending')
        pending_days = sum(req.get_duration() for req in pending)
        leave_balance.append({
            'leave_type': lt,
            'total': lt.days_allowed,
            'used': used,
            'pending': pending_days,
            'available': lt.days_allowed - used,
        })
    
    context = {
        'employee_user': employee_user,
        'profile': profile,
        'total_days': total_days,
        'present': present,
        'absent': absent,
        'half_day': half_day,
        'leave_balance': leave_balance,
        'month_name': today.strftime('%B %Y'),
    }
    return render(request, 'employee_detail.html', context)


# ---------- Leave Types ----------



@login_required
@hr_admin_required
@company_required
def leave_type_list(request):
    from .utils import get_company_filtered
    
    types = get_company_filtered(
        request,
        LeaveType.objects.all()
    ).order_by('name')
    
    return render(request, 'leave_type_list.html', {'leave_types': types})
        
    


@login_required
@hr_admin_required
@company_required
def leave_type_create(request):
    from .utils import get_user_company
    
    if request.method == 'POST':
        name = request.POST.get('name')
        days = request.POST.get('days_allowed')
        
        if name and days:
            # Get the current user's company
            company = get_user_company(request)
            
            # Superuser must select a company explicitly
            if request.user.is_superuser and not company:
                company_id = request.POST.get('company')
                if company_id:
                    from .models import Company
                    company = Company.objects.filter(id=company_id).first()
            
            LeaveType.objects.create(
                name=name,
                days_allowed=days,
                company=company,   # ✅ Auto-assign company
            )
            messages.success(request, 'Leave type created.')
            return redirect('leave_type_list')
        else:
            messages.error(request, 'All fields required.')
    
    # For superuser, pass the company list so they can choose
    context = {'action': 'Create'}
    if request.user.is_superuser:
        from .models import Company
        context['companies'] = Company.objects.all()
    
    return render(request, 'leave_type_form.html', context)


@login_required
@hr_admin_required
@company_required
def leave_type_edit(request, pk):
    from .utils import get_company_filtered
    
    leave_type = get_object_or_404(LeaveType, id=pk)
    
    # Security: verify ownership
    if not request.user.is_superuser:
        if leave_type.company != request.user_company:
            messages.error(request, 'You do not have permission to edit this leave type.')
            return redirect('leave_type_list')
    
    if request.method == 'POST':
        leave_type.name = request.POST.get('name')
        leave_type.days_allowed = request.POST.get('days_allowed')
        leave_type.is_active = 'is_active' in request.POST
        leave_type.save()
        messages.success(request, 'Leave type updated.')
        return redirect('leave_type_list')
    return render(request, 'leave_type_form.html', {'action': 'Edit', 'leave_type': leave_type})


@login_required
@hr_admin_required
@company_required
def leave_type_delete(request, pk):
    from .utils import get_user_company
    
    # Ownership check
    if request.user.is_superuser:
        leave_type = get_object_or_404(LeaveType, id=pk)
    else:
        leave_type = get_object_or_404(
            LeaveType, id=pk, company=get_user_company(request)
        )
    
    if request.method == 'POST':
        leave_type.delete()
        messages.success(request, 'Leave type deleted.')
        return redirect('leave_type_list')
    return render(request, 'leave_type_confirm_delete.html', {'leave_type': leave_type})


# ---------- Holidays ----------
@login_required
@hr_admin_required
@company_required
def holiday_list(request):
    from .utils import get_company_filtered
    from .models import Holiday
    
    holidays = get_company_filtered(
        request, 
        Holiday.objects.all()
    ).order_by('date')
    
    return render(request, 'holiday_list.html', {'holidays': holidays})


@login_required
@hr_admin_required
@company_required
def holiday_create(request):
    from .utils import get_user_company
    
    if request.method == 'POST':
        name = request.POST.get('name')
        date_str = request.POST.get('date')
        if name and date_str:
            Holiday.objects.create(
                name=name, 
                date=date_str,
                company=get_user_company(request)   # <-- auto-assign
            )
            messages.success(request, 'Holiday added.')
            return redirect('holiday_list')
        else:
            messages.error(request, 'All fields required.')
    return render(request, 'holiday_form.html', {'action': 'Add'})


@login_required
@admin_or_hr_required
@company_required
def holiday_edit(request, pk):
    holiday = get_object_or_404(Holiday, id=pk)
    
    # Security: verify the holiday belongs to the user's company
    if not request.user.is_superuser:
        if holiday.company != request.user_company:
            messages.error(request, 'You do not have permission to edit this holiday.')
            return redirect('holiday_list')
    
    if request.method == 'POST':
        holiday.name = request.POST.get('name')
        holiday.date = request.POST.get('date')
        holiday.save()
        messages.success(request, 'Holiday updated.')
        return redirect('holiday_list')
    return render(request, 'holiday_form.html', {'action': 'Edit', 'holiday': holiday})


@login_required
@admin_or_hr_required
@company_required
def holiday_delete(request, pk):
    holiday = get_object_or_404(Holiday, id=pk)
    
    # Security: verify the holiday belongs to the user's company
    if not request.user.is_superuser:
        if holiday.company != request.user_company:
            messages.error(request, 'You do not have permission to delete this holiday.')
            return redirect('holiday_list')
    
    if request.method == 'POST':
        holiday.delete()
        messages.success(request, 'Holiday deleted.')
        return redirect('holiday_list')
    return render(request, 'holiday_confirm_delete.html', {'holiday': holiday})


# ---------- Employee Leave Dashboard ----------@login_required
def employee_leaves(request):
    user = request.user
    tab = request.GET.get('tab', 'status')

    leave_types = get_company_filtered(
        request,
        LeaveType.objects.filter(is_active=True)
    )
    leave_balance = []
    for lt in leave_types:
        total = lt.days_allowed
        approved = LeaveRequest.objects.filter(user=user, leave_type=lt, status='Approved')
        used = sum(req.get_duration() for req in approved)
        pending = LeaveRequest.objects.filter(user=user, leave_type=lt, status='Pending')
        pending_days = sum(req.get_duration() for req in pending)
        available = total - used
        leave_balance.append({
            'leave_type': lt,
            'total': total,
            'used': used,
            'pending': pending_days,
            'available': available,
        })

    filter_status = request.GET.get('filter', 'all')
    if filter_status == 'all':
        requests = LeaveRequest.objects.filter(user=user).order_by('-applied_on')
    else:
        requests = LeaveRequest.objects.filter(user=user, status=filter_status).order_by('-applied_on')

    holidays = get_company_filtered(request, Holiday.objects.all()).order_by('date')

    context = {
        'tab': tab,
        'leave_balance': leave_balance,
        'requests': requests,
        'holidays': holidays,
        'filter_status': filter_status,
    }
    return render(request, 'employee_leaves.html', context)


# ---------- Apply for Leave ----------
@login_required
def leave_apply(request):
    if request.method == 'POST':
        leave_type_id = request.POST.get('leave_type')
        is_half_day = request.POST.get('is_half_day') == 'on'
        half_day_session = request.POST.get('half_day_session')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date') if not is_half_day else start_date
        reason = request.POST.get('reason')
        attachment = request.FILES.get('attachment')

        if not leave_type_id or not start_date or not reason:
            messages.error(request, 'Please fill in all required fields.')
            return redirect('leave_apply')

        leave_type = get_object_or_404(LeaveType, id=leave_type_id)
        used = sum(req.get_duration() for req in LeaveRequest.objects.filter(
            user=request.user, leave_type=leave_type, status='Approved'
        ))
        pending = sum(req.get_duration() for req in LeaveRequest.objects.filter(
            user=request.user, leave_type=leave_type, status='Pending'
        ))
        total = leave_type.days_allowed
        available = total - used
        requested_days = 0.5 if is_half_day else (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1
        if requested_days > available:
            messages.error(request, f'You only have {available} days available for {leave_type.name}.')
            return redirect('leave_apply')

        overlapping = LeaveRequest.objects.filter(
            user=request.user,
            leave_type=leave_type,
            status__in=['Pending', 'Approved'],
            start_date__lte=end_date,
            end_date__gte=start_date
        ).exists()
        if overlapping:
            messages.error(request, 'You already have a pending or approved leave in this period.')
            return redirect('leave_apply')

        # ✅ FIX: Get company from user profile
        company = get_user_company(request)
        if not company:
            messages.error(request, 'Your account is not linked to a company. Please contact HR.')
            return redirect('dashboard')

        leave_request = LeaveRequest.objects.create(
            user=request.user,
            company=company,
            leave_type=leave_type,
            is_half_day=is_half_day,
            half_day_session=half_day_session if is_half_day else '',
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            attachment=attachment,
            status='Pending'
        )

        # ─── Route to correct approver(s) ───
        from .approval_utils import notify_approvers

        profile = getattr(request.user, 'profile', None)
        full_name = (profile.full_name if profile else '') or request.user.username
        emp_id = (profile.employee_id if profile else '') or '—'

        msg = (
            f"Leave Request — {full_name} ({emp_id}) "
            f"has requested {leave_type.name} "
            f"from {date.fromisoformat(str(start_date)).strftime('%d %b')} "
            f"to {date.fromisoformat(str(end_date)).strftime('%d %b %Y')}."
        )

        approvers, self_approved = notify_approvers(
            request=request,
            company=company,
            msg=msg,
            obj=leave_request,
            related_type='leaverequest',
        )

        if self_approved:
            messages.success(
                request,
                "Leave request auto-approved as Company Owner (flagged for audit)."
            )
        else:
            messages.success(request, 'Leave request submitted successfully.')

        return redirect('employee_leaves')


    # ✅ Company-filtered leave types
    leave_types = get_company_filtered(
        request,
        LeaveType.objects.filter(is_active=True)
    )
    return render(request, 'leave_apply.html', {'leave_types': leave_types})


# ---------- Admin Leave Approvals ----------
@login_required
@admin_or_hr_required
@company_required
def admin_leaves(request):
    from .utils import get_company_filtered
    from .roles import get_role

    user = request.user
    profile = getattr(user, 'profile', None)
    role = get_role(user)
    company = get_user_company(request) if not user.is_superuser else None

    # ── Build a base queryset for each status, scoped by role ──
    def scope_qs(status):
        if user.is_superuser:
            return LeaveRequest.objects.filter(status=status)

        base = LeaveRequest.objects.filter(
            status=status,
            company=company,
        ).exclude(user=user)          # ← never own leaves

        if role == 'company_owner':
            # Company Owner sees everything in company except own
            return base

        if role == 'hr_admin':
            # HR Admin sees employees + managers only
            return base.filter(
                user__profile__role__in=['employee', 'manager']
            )

        if role == 'manager':
            team_ids = EmployeeProfile.objects.filter(
                manager=profile
            ).values_list('user_id', flat=True)
            return base.filter(user_id__in=team_ids)

        return LeaveRequest.objects.none()

    context = {
        'pending_leaves':  scope_qs('Pending').order_by('-applied_on'),
        'approved_leaves': scope_qs('Approved').order_by('-applied_on'),
        'rejected_leaves': scope_qs('Rejected').order_by('-applied_on'),
    }
    return render(request, 'admin_leaves.html', context)





@login_required
@admin_or_hr_required
@company_required
def leave_approve(request, leave_id):
    from .utils import get_user_company
    
    # ✅ Company-scoped fetch
    if request.user.is_superuser:
        leave = get_object_or_404(LeaveRequest, id=leave_id)
    else:
        leave = get_object_or_404(
            LeaveRequest, 
            id=leave_id, 
            company=get_user_company(request)
        )
    
    if not can_approve_request(request.user, leave):
        messages.error(request, 'You are not authorized to approve this request.')
        return redirect('admin_leaves')
    
    if request.method == 'POST':
        comment = request.POST.get('admin_comment', '')
        leave.status = 'Approved'
        leave.admin_comment = comment
        leave.save()

        # ✅ Mark related action-notifications as read
        Notification.objects.filter(
            related_object_type='leaverequest',
            related_object_id=leave.id,
            is_read=False,
        ).update(is_read=True)

        create_notification(
            leave.user,
            f"Your {leave.leave_type.name} leave request for {leave.start_date} to {leave.end_date} has been approved.",
            notification_type='info',
            related_object=leave
        )
        messages.success(request, 'Leave approved.')
        return redirect('admin_leaves')
    return render(request, 'leave_approve.html', {'leave': leave})


@login_required
@admin_or_hr_required
@company_required
def leave_reject(request, leave_id):
    from .utils import get_user_company
    
    if request.user.is_superuser:
        leave = get_object_or_404(LeaveRequest, id=leave_id)
    else:
        leave = get_object_or_404(
            LeaveRequest, 
            id=leave_id, 
            company=get_user_company(request)
        )
    
    if not can_approve_request(request.user, leave):
        messages.error(request, 'You are not authorized to reject this request.')
        return redirect('admin_leaves')
    
    if request.method == 'POST':
        reason = request.POST.get('rejection_reason')
        if not reason:
            messages.error(request, 'Please provide a rejection reason.')
            return redirect('leave_reject', leave_id=leave.id)
        leave.status = 'Rejected'
        leave.rejection_reason = reason
        leave.save()

        # ✅ Mark related action-notifications as read
        Notification.objects.filter(
            related_object_type='leaverequest',
            related_object_id=leave.id,
            is_read=False,
        ).update(is_read=True)

        create_notification(
            leave.user,
            f"Your {leave.leave_type.name} leave request for {leave.start_date} to {leave.end_date} has been rejected. Reason: {reason}",
            notification_type='info',
            related_object=leave
        )
        messages.success(request, 'Leave rejected.')
        return redirect('admin_leaves')
    return render(request, 'leave_reject.html', {'leave': leave})
    

# ---------- Team Attendance (Admin only) ----------

@login_required
@admin_or_hr_required
@company_required
def team_attendance(request):
    from .utils import get_company_filtered, get_user_company
    
    today = date.today()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    if month < 1 or month > 12: month = today.month
    if year < 2000 or year > 2100: year = today.year
    
    user = request.user
    
    # Base: company-scoped employees
    if user.is_superuser:
        employees = User.objects.filter(is_superuser=False).order_by('username')
    elif user.groups.filter(name='HR Admin').exists():
        company = get_user_company(request)
        employees = User.objects.filter(
            is_superuser=False, profile__company=company
        ).order_by('username')
    else:
        # Manager: only their team
        try:
            profile = user.profile
            team_ids = EmployeeProfile.objects.filter(
                manager=profile
            ).values_list('user_id', flat=True)
            employees = User.objects.filter(id__in=team_ids).order_by('username')
        except EmployeeProfile.DoesNotExist:
            employees = User.objects.none()
    
    attendances = get_company_filtered(
        request,
        Attendance.objects.filter(date__year=year, date__month=month)
    ).select_related('user')
    
    employee_data = []
    for emp in employees:
        emp_records = [att for att in attendances if att.user == emp]
        total_days = len(emp_records)
        present = len([r for r in emp_records if r.status == 'Present'])
        absent = len([r for r in emp_records if r.status == 'Absent'])
        half_day = len([r for r in emp_records if r.status == 'Half-Day'])
        percentage = int((present / total_days) * 100) if total_days > 0 else 0
        
        profile = getattr(emp, 'profile', None)
        shift_name = profile.shift.name if profile and profile.shift else '—'
        shift_timing = ''
        if profile and profile.shift:
            start = profile.shift.start_time.strftime('%I:%M %p')
            end = profile.shift.end_time.strftime('%I:%M %p')
            shift_timing = f"{start} – {end}"
        
        employee_data.append({
            'employee': emp,
            'records': emp_records,
            'total_days': total_days,
            'present': present,
            'absent': absent,
            'half_day': half_day,
            'percentage': percentage,
            'shift_name': shift_name,
            'shift_timing': shift_timing,
        })
    
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    next_disabled = (year == today.year and month == today.month)
    
    context = {
        'employee_data': employee_data,
        'selected_month_name': date(year, month, 1).strftime('%B %Y'),
        'month': month,
        'year': year,
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
        'next_disabled': next_disabled,
        'total_employees': employees.count(),
    }
    return render(request, 'team_attendance.html', context)


@login_required
@hr_admin_required
@company_required
def attendance_report(request):
    from .utils import get_company_filtered
    from django.contrib.auth.models import User
    
    today = date.today()

    # Filter employees by company (superuser sees all, HR Admin sees own company)
    employees = get_company_filtered(
        request,
        User.objects.filter(is_superuser=False)
    ).order_by('username')

    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))

    if month < 1 or month > 12: month = today.month
    if year < 2000 or year > 2100: year = today.year

    # --- Determine end date for current month ---
    first_day = date(year, month, 1)
    _, last_day_num = monthrange(year, month)
    last_day_of_month = date(year, month, last_day_num)

    if year == today.year and month == today.month:
        end_date = today
    else:
        end_date = last_day_of_month

    # --- Filters ---
    department_filter = request.GET.get('department', '')
    employee_search = request.GET.get('employee', '')
    status_filter = request.GET.get('status', '')
    shift_filter = request.GET.get('shift', '')

    if department_filter:
        employees = employees.filter(profile__department__icontains=department_filter)
    if employee_search:
        employees = employees.filter(
            Q(username__icontains=employee_search) |
            Q(profile__full_name__icontains=employee_search)
        )

    # --- Get attendances (limited to end_date) — COMPANY FILTERED ---
    attendances = get_company_filtered(
        request,
        Attendance.objects.filter(
            date__year=year,
            date__month=month,
            date__lte=end_date
        )
    ).select_related('user')

    # --- Get leaves (limited to end_date) — COMPANY FILTERED ---
    all_leaves = get_company_filtered(
        request,
        LeaveRequest.objects.filter(
            status='Approved',
            start_date__lte=end_date,
            end_date__gte=first_day
        )
    ).select_related('user')

    # --- Shifts (company filtered) ---
    all_shifts = get_company_filtered(request, Shift.objects.all()).order_by('name')

    # --- Departments (company filtered) ---
    distinct_departments = get_company_filtered(
        request,
        EmployeeProfile.objects.all()
    ).values_list('department', flat=True).distinct().order_by('department')
    departments = [d for d in distinct_departments if d]

    employee_data = []
    total_working_days = 0
    total_present = 0
    total_absent = 0
    total_leave = 0
    total_late = 0
    total_overtime_minutes = 0

    for emp in employees:
        emp_records = attendances.filter(user=emp)
        emp_leaves = [l for l in all_leaves if l.user == emp]

        present = emp_records.filter(status='Present').count()
        absent = emp_records.filter(status='Absent').count()
        half_day = emp_records.filter(status='Half-Day').count()

        leave_days = 0
        for leave in emp_leaves:
            start = max(leave.start_date, first_day)
            end = min(leave.end_date, end_date)
            leave_days += (end - start).days + 1

        profile = getattr(emp, 'profile', None)
        shift = profile.shift if profile else None

        if shift_filter and shift_filter != 'all':
            if not shift or shift.id != int(shift_filter):
                continue

        late_days = 0
        early_out_days = 0
        overtime_minutes = 0

        daily_records = []

        for att in emp_records.order_by('date'):
            status_label = 'Present'
            if att.status == 'Absent':
                status_label = 'Absent'
            elif att.status == 'Half-Day':
                status_label = 'Half Day'

            if any(start <= att.date <= end for l in emp_leaves for start, end in [(max(l.start_date, first_day), min(l.end_date, end_date))]):
                status_label = 'On Leave'

            if att.check_in_time and att.check_out_time and shift:
                shift_start = timezone.make_aware(datetime.combine(att.date, shift.start_time))
                shift_end = timezone.make_aware(datetime.combine(att.date, shift.end_time))

                if att.check_in_time > shift_start:
                    late_days += 1
                    if status_label == 'Present':
                        status_label = 'Late'

                if att.check_out_time < shift_end:
                    early_out_days += 1
                    if status_label == 'Present':
                        status_label = 'Early Out'

                if att.check_out_time > shift_end:
                    overtime_seconds = (att.check_out_time - shift_end).total_seconds()
                    ot_minutes = int(overtime_seconds // 60)

                    if shift.overtime_allowed and shift.overtime_limit:
                        limit_minutes = shift.overtime_limit * 60
                        if ot_minutes > limit_minutes:
                            ot_minutes = limit_minutes
                else:
                    ot_minutes = 0

                overtime_minutes += ot_minutes

            hours_str = '--'
            if att.check_in_time and att.check_out_time:
                diff = att.check_out_time - att.check_in_time
                h = diff.seconds // 3600
                m = (diff.seconds % 3600) // 60
                hours_str = f"{h}h {m}m"

            if status_filter and status_filter != 'all' and status_filter != status_label:
                continue

            daily_records.append({
                'date': att.date,
                'shift': shift.name if shift else '—',
                'in_time': att.check_in_time.strftime('%I:%M %p') if att.check_in_time else '--:--',
                'out_time': att.check_out_time.strftime('%I:%M %p') if att.check_out_time else '--:--',
                'hours': hours_str,
                'status': status_label,
            })

        if status_filter == 'On Leave' and leave_days == 0:
            continue

        working_days = present + half_day + leave_days
        rate = round((present / working_days) * 100, 1) if working_days > 0 else 0

        total_working_days += working_days
        total_present += present
        total_absent += absent
        total_leave += leave_days
        total_late += late_days
        total_overtime_minutes += overtime_minutes

        employee_data.append({
            'employee': emp,
            'records': daily_records,
            'present': present,
            'absent': absent,
            'half_day': half_day,
            'leave_days': leave_days,
            'working_days': working_days,
            'late_days': late_days,
            'early_out_days': early_out_days,
            'rate': rate,
            'shift': shift.name if shift else '—',
            'department': profile.department if profile else '—',
        })

    total_ot_hours = total_overtime_minutes // 60
    total_ot_minutes = total_overtime_minutes % 60
    total_ot_formatted = f"{total_ot_hours}h {total_ot_minutes}m" if total_overtime_minutes > 0 else "0h 0m"

    # ---------- PDF DOWNLOAD ----------
    if request.GET.get('download') == 'pdf':
        from .utils import get_employee_attendance_for_pdf
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch, cm
        from io import BytesIO
        from django.http import FileResponse

        download_type = request.GET.get('download_type', 'all')
        employee_id = request.GET.get('employee_id')

        pdf_employee_data = employee_data

        if download_type == 'single':
            if not employee_id:
                messages.error(request, 'Please select an employee.')
                return redirect('attendance_report')
            try:
                # Security: verify employee is in the current user's scope
                emp = get_company_filtered(
                    request,
                    User.objects.filter(id=employee_id)
                ).first()
                if not emp:
                    messages.error(request, 'Employee not found or you do not have access.')
                    return redirect('attendance_report')
                pdf_employee_data = [item for item in employee_data if item['employee'].id == emp.id]
                if not pdf_employee_data:
                    messages.error(request, 'Employee not found or you do not have access.')
                    return redirect('attendance_report')
            except Exception:
                messages.error(request, 'Employee not found.')
                return redirect('attendance_report')

        if not pdf_employee_data:
            messages.error(request, 'No data available for the selected filters.')
            return redirect('attendance_report')

        # --- Generate PDF ---
        buffer = BytesIO()
        first_day = date(year, month, 1)
        _, last_day_num = monthrange(year, month)
        last_day = date(year, month, last_day_num)

        # Company name from the current user's company
        if request.user.is_superuser:
            company = Company.objects.first()
        else:
            company = getattr(request, 'user_company', None)
        company_name = company.name if company else 'HRMS'

        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                topMargin=0.5*inch, bottomMargin=0.5*inch,
                                leftMargin=0.5*inch, rightMargin=0.5*inch)
        styles = getSampleStyleSheet()
        normal_style = styles['Normal']
        heading_style = styles['Heading2']

        header_style = ParagraphStyle('HeaderStyle', parent=normal_style, fontSize=14, fontName='Helvetica-Bold', alignment=1, spaceAfter=6)
        subheader_style = ParagraphStyle('SubHeaderStyle', parent=normal_style, fontSize=12, alignment=1, spaceAfter=12)
        info_label_style = ParagraphStyle('InfoLabelStyle', parent=normal_style, fontSize=10, fontName='Helvetica-Bold')
        info_value_style = ParagraphStyle('InfoValueStyle', parent=normal_style, fontSize=10)
        summary_label_style = ParagraphStyle('SummaryLabelStyle', parent=normal_style, fontSize=9, fontName='Helvetica-Bold')

        elements = []

        for idx, emp_data in enumerate(pdf_employee_data):
            if idx > 0:
                elements.append(PageBreak())

            emp = emp_data['employee']
            detailed = get_employee_attendance_for_pdf(emp, year, month, first_day, last_day)
            profile = detailed['profile']
            shift = detailed['shift']
            daily = detailed['daily_data']

            # Company header
            elements.append(Paragraph(company_name, header_style))
            elements.append(Paragraph("Attendance Report", subheader_style))
            month_name = first_day.strftime('%B %Y')
            elements.append(Paragraph(month_name, normal_style))
            elements.append(Spacer(1, 0.3*inch))

            # Employee Info (3 columns, borderless)
            info_data = [
                [
                    Paragraph(f"<b>Employee:</b> {emp.username}", normal_style),
                    Paragraph(f"<b>Employee ID:</b> {profile.employee_id if profile else '—'}", normal_style),
                    Paragraph(f"<b>Department:</b> {profile.department if profile else '—'}", normal_style),
                ],
                [
                    Paragraph(f"<b>Designation:</b> {profile.designation if profile else '—'}", normal_style),
                    Paragraph(f"<b>Manager:</b> {profile.manager.full_name if profile and profile.manager else '—'}", normal_style),
                    Paragraph(f"<b>Shift:</b> {shift.name if shift else '—'}", normal_style),
                ],
                [
                    Paragraph(f"<b>Attendance Type:</b> {profile.get_attendance_type_display() if profile else '—'}", normal_style),
                    Paragraph("", normal_style),
                    Paragraph("", normal_style),
                ],
            ]
            col_widths = [doc.width / 3.0] * 3
            info_table = Table(info_data, colWidths=col_widths)
            info_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('FONTSIZE', (0,0), (-1,-1), 9),
                ('LEFTPADDING', (0,0), (-1,-1), 4),
                ('RIGHTPADDING', (0,0), (-1,-1), 4),
                ('TOPPADDING', (0,0), (-1,-1), 3),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ]))
            elements.append(info_table)
            elements.append(Spacer(1, 0.2*inch))

            # Daily Attendance
            elements.append(Paragraph("Daily Attendance", heading_style))
            table_data = [['Date', 'Day', 'Status', 'Check In', 'Check Out', 'Hours']]
            for day in daily:
                table_data.append([
                    day['date'].strftime('%d %b'),
                    day['day_name'],
                    day['status'],
                    day['check_in'] if day['check_in'] else '—',
                    day['check_out'] if day['check_out'] else '—',
                    day['working_hours'] if day['working_hours'] else '—'
                ])
            table = Table(table_data, colWidths=[1.8*cm, 1.8*cm, 2.2*cm, 2.5*cm, 2.5*cm, 2.5*cm])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.grey),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 9),
                ('FONTSIZE', (0,1), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,0), 6),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,1), (-1,-1), 4),
                ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.lightgrey]),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 0.3*inch))

            # Monthly Summary
            elements.append(Paragraph("Monthly Summary", heading_style))
            ot_hours = int(detailed['overtime_minutes'] // 60)
            ot_minutes = int(detailed['overtime_minutes'] % 60)
            overtime_str = f"{ot_hours}h {ot_minutes}m" if ot_minutes > 0 or ot_hours > 0 else "0h"

            summary_data = [
                [Paragraph("Working Days:", summary_label_style), str(detailed['working_days']),
                 Paragraph("Present:", summary_label_style), str(detailed['present'])],
                [Paragraph("Absent:", summary_label_style), str(detailed['absent']),
                 Paragraph("Leave:", summary_label_style), str(detailed['leave'])],
                [Paragraph("Half Day:", summary_label_style), str(detailed['half_day']),
                 Paragraph("Late Arrivals:", summary_label_style), str(detailed['late_arrivals'])],
                [Paragraph("Overtime:", summary_label_style), overtime_str,
                 Paragraph("Total Working Hours:", summary_label_style), detailed['total_working_hours']],
                [Paragraph("Average Working Hours:", summary_label_style), detailed['avg_working_hours'],
                 Paragraph("", summary_label_style), ""],
            ]
            summary_table = Table(summary_data, colWidths=[3*cm, 2.5*cm, 3*cm, 2.5*cm])
            summary_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('FONTSIZE', (0,0), (-1,-1), 9),
                ('LEFTPADDING', (0,0), (-1,-1), 4),
                ('RIGHTPADDING', (0,0), (-1,-1), 4),
                ('TOPPADDING', (0,0), (-1,-1), 3),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
                ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
            ]))
            elements.append(summary_table)
            elements.append(Spacer(1, 0.5*inch))

            # ----- Footer (inside the loop) -----
            local_now = timezone.localtime(timezone.now())
            footer_text = f"Generated on {local_now.strftime('%d %B %Y, %I:%M %p')} · Employee ID: {profile.employee_id if profile else 'N/A'}"
            elements.append(Paragraph(footer_text,
                                      ParagraphStyle('Footer', parent=normal_style, fontSize=7, alignment=1)))

        # ----- Build the document (outside the loop) -----
        doc.build(elements)
        buffer.seek(0)

        month_name = first_day.strftime('%B_%Y')
        if download_type == 'single' and len(pdf_employee_data) == 1:
            emp = pdf_employee_data[0]['employee']
            emp_id = emp.profile.employee_id if emp.profile else f"EMP{emp.id:04d}"
            filename = f"attendance_{emp_id}_{month_name}.pdf"
        else:
            filename = f"attendance_{month_name}.pdf"

        return FileResponse(buffer, as_attachment=True, filename=filename)

    # ---------- CSV DOWNLOAD ----------
    if request.GET.get('download') == 'csv':
        download_type = request.GET.get('download_type', 'all')
        employee_id = request.GET.get('employee_id')

        # --- Single employee mode ---
        if download_type == 'single':
            if not employee_id:
                messages.error(request, 'Please select an employee.')
                return redirect('attendance_report')

            # Security: verify employee is in the user's company scope
            single_user = get_company_filtered(
                request,
                User.objects.filter(id=employee_id)
            ).first()
            if not single_user:
                messages.error(request, 'Employee not found or you do not have access.')
                return redirect('attendance_report')

            filtered_data = [item for item in employee_data if item['employee'].id == single_user.id]
            if not filtered_data:
                messages.error(request, 'Employee not found or you do not have access.')
                return redirect('attendance_report')
            employee_data = filtered_data

        if not employee_data:
            messages.error(request, 'No attendance data available for the selected month.')
            return redirect('attendance_report')

        # --- Generate CSV ---
        month_name = date(year, month, 1).strftime('%B_%Y')

        # Build date columns
        dates = [first_day + timedelta(days=i) for i in range((end_date - first_day).days + 1)]
        date_headers = [d.strftime('%b %d') for d in dates]

        # CSV filename
        if download_type == 'single' and len(employee_data) == 1:
            emp = employee_data[0]['employee']
            emp_id = emp.employee_id if emp.employee_id else f"EMP{emp.id:04d}"
            filename = f"attendance_{emp_id}_{month_name}.csv"
        else:
            filename = f"attendance_{month_name}.csv"

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)

        # Header
        header = ['Employee ID', 'Employee Name', 'Department', 'Designation', 'Shift'] + date_headers + ['Present', 'Absent', 'Leave', 'Half Day', 'Late Arrivals', 'Overtime']
        writer.writerow(header)

        # Company-filtered holidays
        holidays = get_company_filtered(
            request,
            Holiday.objects.filter(date__gte=first_day, date__lte=end_date)
        ).values_list('date', flat=True)
        holidays = set(holidays)

        for emp_data in employee_data:
            emp = emp_data['employee']
            profile = emp.profile
            shift = emp.profile.shift if emp.profile and emp.profile.shift else None

            # Build status dict for each date
            status_dict = {}
            for d in dates:
                if d in holidays:
                    status_dict[d] = 'H'
                elif shift:
                    day_name = d.strftime('%a').lower()[:3]
                    if not getattr(shift, day_name, False):
                        status_dict[d] = 'WO'
                else:
                    status_dict[d] = ''

            # Attendance records (company filtered)
            emp_att_records = get_company_filtered(
                request,
                Attendance.objects.filter(user=emp, date__gte=first_day, date__lte=end_date)
            )
            for att in emp_att_records:
                if att.status == 'Present':
                    status_dict[att.date] = 'P'
                elif att.status == 'Half-Day':
                    status_dict[att.date] = 'HD'

            # Leave requests (company filtered)
            emp_leave_requests = get_company_filtered(
                request,
                LeaveRequest.objects.filter(
                    user=emp, status='Approved',
                    start_date__lte=end_date, end_date__gte=first_day
                )
            )
            for leave in emp_leave_requests:
                start = max(leave.start_date, first_day)
                end = min(leave.end_date, end_date)
                for d in (start + timedelta(n) for n in range((end - start).days + 1)):
                    status_dict[d] = 'L'

            # Build row
            row = [
                profile.employee_id if profile else '',
                emp.username,
                profile.department if profile else '',
                profile.designation if profile else '',
                shift.name if shift else '',
            ]

            # For each date, get status; default 'A' if not set
            for d in dates:
                status = status_dict.get(d)
                if status is None or status == '':
                    status = 'A'
                row.append(status)

            # Compute totals
            daily_statuses = row[5:]
            present_count = sum(1 for s in daily_statuses if s == 'P')
            absent_count = sum(1 for s in daily_statuses if s == 'A')
            leave_count = sum(1 for s in daily_statuses if s == 'L')
            half_count = sum(1 for s in daily_statuses if s == 'HD')
            late_count = emp_data.get('late_days', 0)

            ot_minutes_total = 0
            for att in emp_att_records.filter(status='Present'):
                if shift and att.check_in_time and att.check_out_time:
                    shift_end = timezone.make_aware(datetime.combine(att.date, shift.end_time))
                    if att.check_out_time > shift_end:
                        ot = (att.check_out_time - shift_end).total_seconds() // 60
                        if shift.overtime_allowed and shift.overtime_limit:
                            ot = min(ot, shift.overtime_limit * 60)
                        ot_minutes_total += ot

            row.extend([
                present_count, absent_count, leave_count, half_count, late_count,
                f"{int(ot_minutes_total//60)}h {int(ot_minutes_total%60)}m" if ot_minutes_total else "0h"
            ])
            writer.writerow(row)

        return response

    # ---------- Normal page rendering ----------
    prev_month = month-1 if month>1 else 12
    prev_year = year if month>1 else year-1
    next_month = month+1 if month<12 else 1
    next_year = year if month<12 else year+1
    next_disabled = (year==today.year and month==today.month)

    context = {
        'employee_data': employee_data,
        'today': today,
        'month_name': date(year, month, 1).strftime('%B %Y'),
        'month': month,
        'year': year,
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
        'next_disabled': next_disabled,
        'total_employees': employees.count(),
        'total_working_days': total_working_days,
        'total_present': total_present,
        'total_absent': total_absent,
        'total_leave': total_leave,
        'total_late': total_late,
        'total_overtime': total_ot_formatted,
        'departments': departments,
        'shifts': all_shifts,
        'department_filter': department_filter,
        'employee_search': employee_search,
        'status_filter': status_filter,
        'shift_filter': shift_filter,
    }
    return render(request, 'attendance_report.html', context)


# ---------- Employee Attendance Detail ----------

@login_required
@hr_admin_required
@company_required
def employee_attendance_detail(request, user_id):
    from .utils import get_user_company, get_company_filtered
    
    # ─── Search redirect (company-scoped) ───
    search_query = request.GET.get('search')
    if search_query:
        employees_qs = get_company_filtered(
            request,
            User.objects.filter(is_superuser=False)
        )
        employee = employees_qs.filter(
            Q(username__icontains=search_query) |
            Q(profile__full_name__icontains=search_query)
        ).first()
        if employee:
            return redirect('employee_attendance_detail', user_id=employee.id)
        else:
            messages.warning(request, 'Employee not found.')
    
    # ─── Security: ownership check ───
    if request.user.is_superuser:
        employee = get_object_or_404(User, id=user_id)
    else:
        company = get_user_company(request)
        employee = get_object_or_404(
            User, id=user_id, profile__company=company
        )
    
    profile = get_object_or_404(EmployeeProfile, user=employee)
    
    today = date.today()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    if month < 1 or month > 12: month = today.month
    if year < 2000 or year > 2100: year = today.year
    
    first_day = date(year, month, 1)
    _, last_day_num = monthrange(year, month)
    last_day = date(year, month, last_day_num)
    
    # ─── Attendance (company-filtered) ───
    attendances = get_company_filtered(
        request,
        Attendance.objects.filter(
            user=employee,
            date__year=year,
            date__month=month
        )
    ).order_by('date')
    
    # ─── Leaves (company-filtered) ───
    leaves = get_company_filtered(
        request,
        LeaveRequest.objects.filter(
            user=employee,
            status='Approved',
            start_date__lte=last_day,
            end_date__gte=first_day
        )
    )
    
    # ─── Stats ───
    present = attendances.filter(status='Present').count()
    absent = attendances.filter(status='Absent').count()
    half_day = attendances.filter(status='Half-Day').count()
    
    leave_days = 0
    for leave in leaves:
        start = max(leave.start_date, first_day)
        end = min(leave.end_date, last_day)
        leave_days += (end - start).days + 1
    
    shift = profile.shift if profile else None
    
    late_days = 0
    early_out_days = 0
    total_overtime_minutes = 0
    
    daily_records = []
    for att in attendances:
        status_label = 'Present'
        if att.status == 'Absent':
            status_label = 'Absent'
        elif att.status == 'Half-Day':
            status_label = 'Half Day'
        
        if any(start <= att.date <= end for l in leaves
               for start, end in [(max(l.start_date, first_day), min(l.end_date, last_day))]):
            status_label = 'On Leave'
        
        if att.check_in_time and att.check_out_time and shift:
            shift_start = timezone.make_aware(datetime.combine(att.date, shift.start_time))
            shift_end = timezone.make_aware(datetime.combine(att.date, shift.end_time))
            
            if att.check_in_time > shift_start:
                late_days += 1
                if status_label == 'Present':
                    status_label = 'Late'
            
            if att.check_out_time < shift_end:
                early_out_days += 1
                if status_label == 'Present':
                    status_label = 'Early Out'
            
            if att.check_out_time > shift_end:
                overtime_seconds = (att.check_out_time - shift_end).total_seconds()
                total_overtime_minutes += int(overtime_seconds // 60)
        
        hours_str = '--'
        if att.check_in_time and att.check_out_time:
            diff = att.check_out_time - att.check_in_time
            h = diff.seconds // 3600
            m = (diff.seconds % 3600) // 60
            hours_str = f"{h}h {m}m"
        
        daily_records.append({
            'date': att.date,
            'shift': shift.name if shift else '—',
            'in_time': timezone.localtime(att.check_in_time).strftime('%I:%M %p') if att.check_in_time else '--:--',
            'out_time': timezone.localtime(att.check_out_time).strftime('%I:%M %p') if att.check_out_time else '--:--',
            'hours': hours_str,
            'status': status_label,
        })
    
    working_days = present + half_day + leave_days
    rate = round((present / working_days) * 100, 1) if working_days > 0 else 0
    
    ot_hours = total_overtime_minutes // 60
    ot_minutes = total_overtime_minutes % 60
    ot_formatted = f"{ot_hours}h {ot_minutes}m" if total_overtime_minutes > 0 else "—"
    
    # ─── Month navigation ───
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    next_disabled = (year == today.year and month == today.month)
    
    # ─── All employees (company-scoped, single assignment) ───
    all_employees = get_company_filtered(
        request,
        User.objects.filter(is_superuser=False)
    ).select_related('profile').order_by('username')
    
    context = {
        'employee': employee,
        'profile': profile,
        'daily_records': daily_records,
        'present': present,
        'absent': absent,
        'half_day': half_day,
        'leave_days': leave_days,
        'working_days': working_days,
        'late_days': late_days,
        'early_out_days': early_out_days,
        'overtime': ot_formatted,
        'rate': rate,
        'month': month,
        'year': year,
        'month_name': first_day.strftime('%B %Y'),
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
        'next_disabled': next_disabled,
        'shift': shift.name if shift else 'Not assigned',
        'today': today,
        'all_employees': all_employees,
        'search_query': search_query or '',
    }
    return render(request, 'employee_attendance_detail.html', context)
    


# ---------- Attendance Module (Dedicated Page) ----------
def minutes_to_time(minutes):
    if minutes == 0 or minutes is None:
        return "--:--"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours:02d}:{mins:02d}"



@login_required
def attendance_view(request):
    user = request.user
    today = date.today()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))

    if month < 1 or month > 12: month = today.month
    if year < 2000 or year > 2100: year = today.year

    _, last_day = monthrange(year, month)
    first_date = date(year, month, 1)
    last_date = date(year, month, last_day)

    attendances = Attendance.objects.filter(
        user=user, date__gte=first_date, date__lte=last_date
    ).order_by('date')
    att_dict = {att.date: att for att in attendances}

    all_dates = []
    total_working_hours = 0
    total_in_minutes = 0
    total_out_minutes = 0
    complete_count = 0

    for day in range(1, last_day + 1):
        current_date = date(year, month, day)
        att = att_dict.get(current_date)

        if att:
            # ✅ Trust the DB status for flagged/flow states
            if att.status in ('Missing Checkout', 'Under Review',
                            'On Leave', 'Half-Day', 'Late', 'Early Out'):
                status = att.status
            elif att.check_in_time and att.check_out_time:
                status = 'Present'
            elif att.check_in_time:
                status = 'Missing Checkout'
            else:
                status = 'Absent'

            check_in = att.check_in_time
            check_out = att.check_out_time
            work_seconds = (check_out - check_in).total_seconds() if check_in and check_out else 0
            overtime_seconds = max(0, work_seconds - 8 * 3600) if work_seconds else 0
            if check_in and check_out:
                complete_count += 1
                total_working_hours += work_seconds / 3600
                total_in_minutes += check_in.hour * 60 + check_in.minute
                total_out_minutes += check_out.hour * 60 + check_out.minute
        else:
            status, check_in, check_out, work_seconds, overtime_seconds = 'Absent', None, None, 0, 0

        check_in_display = timezone.localtime(check_in).strftime('%I:%M %p') if check_in else '--:--'
        check_out_display = timezone.localtime(check_out).strftime('%I:%M %p') if check_out else '--:--'
        work_hours = f"{int(work_seconds // 3600):02d}:{int((work_seconds % 3600) // 60):02d}" if work_seconds else '--:--'
        overtime_display = f"{int(overtime_seconds // 3600):02d}:{int((overtime_seconds % 3600) // 60):02d}" if overtime_seconds else '--:--'
        can_regularize = status in ('Missing Checkout', 'Incomplete', 'Absent')

        all_dates.append({
            'date': current_date,
            'status': status,
            'check_in': check_in_display,
            'check_out': check_out_display,
            'work_hours': work_hours,
            'overtime': overtime_display,
            'can_regularize': can_regularize,
            'attendance_id': att.id if att else None,
            'is_weekend': current_date.weekday() >= 5,
        })

    # ✅ Sort ONCE outside the loop
    all_dates.sort(key=lambda x: x['date'], reverse=True)

    avg_working_hours = round(total_working_hours / complete_count, 2) if complete_count > 0 else 0
    avg_in_time = minutes_to_time(total_in_minutes / complete_count) if complete_count > 0 else "--:--"
    avg_out_time = minutes_to_time(total_out_minutes / complete_count) if complete_count > 0 else "--:--"
    pending_regularization = RegularizationRequest.objects.filter(user=user, status='Pending').exists()

    context = {
        'all_dates': all_dates,
        'avg_working_hours': avg_working_hours,
        'avg_in_time': avg_in_time,
        'avg_out_time': avg_out_time,
        'total_days': last_day,
        'completed_days': complete_count,
        'month': month, 'year': year,
        'month_name': first_date.strftime('%B %Y'),
        'pending_regularization': pending_regularization,
        'today': today,
    }
    return render(request, 'attendance/attendance_status.html', context)


# ---------- Regularization ----------

@login_required
def regularize_request(request):
    if request.method == 'POST':
        date_str  = request.POST.get('date')
        check_in  = request.POST.get('check_in')
        check_out = request.POST.get('check_out')
        reason    = request.POST.get('reason')

        if not (date_str and reason):
            messages.error(request, 'Please fill in all required fields.')
            return render(request, 'attendance/regularize_request.html', {
                'prefilled_date': date_str or request.GET.get('date', ''),
            })

        # ─── Prevent duplicate pending/approved regularizations ───
        existing_req = RegularizationRequest.objects.filter(
            user=request.user,
            date=date_str,
            status__in=['Pending', 'Approved']
        ).exists()
        if existing_req:
            messages.error(
                request,
                'You already have a pending or approved regularization for this date.'
            )
            return redirect('regularize_request_list')

        # ─── Check the existing attendance record ───
        # Regularization is ALLOWED when:
        #   • No attendance exists at all
        #   • OR attendance exists with status 'Missing Checkout' / 'Under Review'
        # Regularization is BLOCKED when:
        #   • A finalized record already exists (Present, Absent, On Leave, etc.)
        existing_att = Attendance.objects.filter(
            user=request.user,
            date=date_str,
        ).first()

        if existing_att:
            allowed_statuses = ('Missing Checkout', 'Under Review', 'Absent', 'Incomplete')
            if existing_att.status not in allowed_statuses:
                messages.error(
                    request,
                    'Attendance already exists for this date. '
                    'Only missing checkouts can be regularized.'
                )
                return redirect('attendance_view')

        # ─── Company check ───
        company = get_user_company(request)
        if not company:
            messages.error(request, 'Your account is not linked to a company.')
            return redirect('dashboard')

        # ─── Create the regularization request ───
        reg_req = RegularizationRequest.objects.create(
            company=company,
            user=request.user,
            date=date_str,
            check_in_time=check_in if check_in else None,
            check_out_time=check_out if check_out else None,
            reason=reason,
            status='Pending',
        )

        # ─── Flip the attendance status → Under Review ───
        from .attendance_utils import mark_under_review
        mark_under_review(request.user, date_str)

        # ─── Notify approver ───
        
        # ─── Notify approver ───
        from .approval_utils import notify_approvers
        profile = getattr(request.user, 'profile', None)
        full_name = (profile.full_name if profile else '') or request.user.username
        emp_id = (profile.employee_id if profile else '') or '—'

        msg = (
            f"Regularization Request — {full_name} ({emp_id}) "
            f"has requested a regularization for {date_str}."
        )

        approvers, self_approved = notify_approvers(
            request=request,
            company=company,
            msg=msg,
            obj=reg_req,
            related_type='regularizationrequest',
        )

        if self_approved:
            # Owner's own regularization auto-approves → close the day
            from .attendance_utils import mark_under_review
            Attendance.objects.filter(
                user=request.user,
                date=date_str,
            ).update(status='Present')

            messages.success(
                request,
                "Regularization auto-approved as Company Owner."
            )
        else:
            messages.success(request, 'Regularization request submitted successfully.')

        return redirect('regularize_request_list')


    # ─── GET: pre-fill form from ?date= query param ───
    prefilled_date = request.GET.get('date', '')

    attendance = None
    if prefilled_date:
        attendance = Attendance.objects.filter(
            user=request.user,
            date=prefilled_date,
        ).first()

    return render(request, 'attendance/regularize_request.html', {
        'prefilled_date': prefilled_date,
        'attendance':     attendance,
    })



@login_required
def regularize_request_list(request):
    from .utils import get_company_filtered
    from django.db.models import Q
    from core.models import EmployeeProfile

    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else None

    if request.user.is_superuser:
        # Superuser: all companies
        requests = RegularizationRequest.objects.all().order_by('-requested_at')

    elif role == 'HR Admin' or request.user.groups.filter(name='HR Admin').exists():
        # HR Admin: whole company
        requests = get_company_filtered(
            request, RegularizationRequest.objects.all()
        ).order_by('-requested_at')

    elif role == 'Manager':
        # Manager: own + their team's requests
        team_user_ids = EmployeeProfile.objects.filter(
            manager=profile
        ).values_list('user_id', flat=True)

        requests = get_company_filtered(
            request, RegularizationRequest.objects.all()
        ).filter(
            Q(user=request.user) | Q(user_id__in=team_user_ids)
        ).order_by('-requested_at')

    else:
        # Employee: only their own
        requests = RegularizationRequest.objects.filter(
            user=request.user
        ).order_by('-requested_at')

    return render(
        request,
        'attendance/regularize_request_list.html',
        {'requests': requests}
    )


@login_required
@admin_or_hr_required
@company_required
def regularize_reject(request, req_id):
    from .utils import get_user_company

    if request.user.is_superuser:
        reg_req = get_object_or_404(RegularizationRequest, id=req_id)
    else:
        reg_req = get_object_or_404(
            RegularizationRequest, id=req_id,
            company=get_user_company(request)
        )

    if request.method == 'POST':
        reason = request.POST.get('rejection_reason')
        if not reason:
            messages.error(request, 'Please provide a rejection reason.')
            return redirect('regularize_reject', req_id=reg_req.id)

        # ─── Update the regularization request ───
        reg_req.status = 'Rejected'
        reg_req.admin_comment = reason
        reg_req.save()

        # ─── Set the attendance to 'Absent' ───
        existing_att = Attendance.objects.filter(
            user=reg_req.user,
            date=reg_req.date,
        ).first()

        if existing_att:
            existing_att.status = 'Absent'
            existing_att.state = 'checked_in'
            existing_att.check_out_time = None
            existing_att.total_working_time = None
            existing_att.save(update_fields=[
                'status', 'state', 'check_out_time', 'total_working_time',
            ])

        # ─── Mark the notification as read ───
        Notification.objects.filter(
            related_object_type='regularizationrequest',
            related_object_id=reg_req.id,
            is_read=False,
        ).update(is_read=True)

        # ─── Notify the employee ───
        Notification.objects.create(
            user=reg_req.user,
            company=reg_req.company,
            message=(
                f"Your regularization request for "
                f"{reg_req.date.strftime('%d %b %Y')} was rejected. "
                f"Reason: {reason}"
            ),
            notification_type='info',
        )

        messages.success(request, f'Regularization rejected for {reg_req.user.username}.')
        return redirect('regularize_request_list')

    return render(request, 'attendance/regularize_reject.html', {'reg_req': reg_req})

@login_required
@admin_or_hr_required            # ← existing, already allows managers ✅
@company_required
def regularize_approve(request, req_id):
    from datetime import datetime
    from django.utils.dateparse import parse_time
    from datetime import timedelta
    from django.core.exceptions import PermissionDenied   # ← CHANGED (added)

    if request.user.is_superuser:
        reg_req = get_object_or_404(RegularizationRequest, id=req_id)
    else:
        reg_req = get_object_or_404(
            RegularizationRequest, id=req_id,
            company=get_user_company(request)
        )

    # ─── Manager scope: only own team ───                 # ← CHANGED (added block)
    if not request.user.is_superuser:
        profile = getattr(request.user, 'profile', None)
        if profile and profile.role == 'Manager':
            if reg_req.user.profile.manager_id != profile.id:
                raise PermissionDenied

    if request.method == 'POST':
        comment = request.POST.get('admin_comment', '')
        reg_req.status = 'Approved'
        reg_req.admin_comment = comment
        reg_req.save()

        # ─── Parse times ───
        def to_time(val):
            if val is None or val == '':
                return None
            if hasattr(val, 'hour'):
                return val
            return parse_time(str(val))

        check_in_time  = to_time(reg_req.check_in_time)
        check_out_time = to_time(reg_req.check_out_time)

        # ─── Build datetimes ───
        check_in_dt  = None
        check_out_dt = None

        if check_in_time and reg_req.date:
            check_in_dt = timezone.make_aware(
                datetime.combine(reg_req.date, check_in_time)
            )
        if check_out_time and reg_req.date:
            check_out_dt = timezone.make_aware(
                datetime.combine(reg_req.date, check_out_time)
            )

        # ─── Determine final status ───
        final_status = 'Absent'
        final_state  = 'checked_in'
        working_time = None

        if check_in_dt and check_out_dt and check_out_dt > check_in_dt:
            working_time = check_out_dt - check_in_dt
            hours = working_time.total_seconds() / 3600
            final_status = 'Half-Day' if hours < 4 else 'Present'
            final_state  = 'checked_out'

        elif check_in_dt and not check_out_dt:
            final_status = 'Half-Day'
            final_state  = 'checked_in'

        # ─── Upsert the attendance record ───
        Attendance.objects.update_or_create(
            user=reg_req.user,
            date=reg_req.date,
            defaults={
                'company':            reg_req.company,
                'check_in_time':      check_in_dt or reg_req.user.attendance_set.filter(
                                          date=reg_req.date
                                      ).values_list('check_in_time', flat=True).first(),
                'check_out_time':     check_out_dt,
                'status':             final_status,
                'state':              final_state,
                'total_working_time': working_time,
            },
        )

        # ─── Mark related notification as read ───
        Notification.objects.filter(
            related_object_type='regularizationrequest',
            related_object_id=reg_req.id,
            is_read=False,
        ).update(is_read=True)

        # ─── Notify the employee ───
        Notification.objects.create(
            user=reg_req.user,
            company=reg_req.company,
            message=(
                f"Your regularization request for "
                f"{reg_req.date.strftime('%d %b %Y')} was approved "
                f"({final_status})."
            ),
            notification_type='info',
        )

        messages.success(
            request,
            f'Regularization approved for {reg_req.user.username} — {final_status}.'
        )
        return redirect('regularize_request_list')

    return render(request, 'attendance/regularize_approve.html', {'reg_req': reg_req})

# ---------- Notification List ----------
@login_required
def notification_list(request):
    notifications = Notification.objects.filter(
        user=request.user
    ).order_by('-created_at')

    # Only auto-mark INFO notifications as read when the list is viewed.
    # Action notifications stay unread until HR acts on them.
    Notification.objects.filter(
        user=request.user,
        is_read=False,
        notification_type='info',
    ).update(is_read=True)

    context = {
        'notifications': notifications,
    }
    return render(request, 'notifications.html', context)



# ---------- Profile ----------
@login_required
def profile(request):
    user = request.user
    profile, created = EmployeeProfile.objects.get_or_create(user=user)
    
    if request.method == 'POST':
        # ⛔ Do NOT allow username change
        # user.username = request.POST.get('username')   <-- REMOVED
        
        user.email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')
        if password1:
            if password1 == password2:
                user.set_password(password1)
            else:
                messages.error(request, 'Passwords do not match.')
                return redirect('profile')
        user.save()
        
        profile.full_name = request.POST.get('full_name')
        profile.date_of_birth = request.POST.get('date_of_birth') or None
        profile.date_of_joining = request.POST.get('date_of_joining') or None
        profile.designation = request.POST.get('designation')
        profile.department = request.POST.get('department')
        profile.phone = request.POST.get('phone')
        profile.address = request.POST.get('address')
        
        # ❌ REMOVED: attendance_type and office_location – employees cannot change these
        # profile.attendance_type = request.POST.get('attendance_type')
        # profile.office_location_id = request.POST.get('office_location') or None
        
        profile.save()
        
        messages.success(request, 'Profile updated successfully.')
        return redirect('profile')
    
    # GET request – no offices needed since we removed those fields
    context = {
        'user': user,
        'profile': profile,
    }
    return render(request, 'profile.html', context)
    


# ---------- Attendance Overview Data ----------
def attendance_overview_data(request):
    """Return JSON data for attendance overview chart."""
    from .utils import get_company_filtered

    period = request.GET.get('period', 'week')
    today = date.today()

    if period == 'week':
        start_date = today - timedelta(days=today.weekday())     # Monday
        end_date = start_date + timedelta(days=6)                # Sunday (full week)
    elif period == 'month':
        start_date = date(today.year, today.month, 1)
        end_date = today
    elif period == 'last_month':
        last_month = today.replace(day=1) - timedelta(days=1)
        start_date = date(last_month.year, last_month.month, 1)
        end_date = date(last_month.year, last_month.month, last_month.day)
    else:
        return JsonResponse({'error': 'Invalid period'}, status=400)

    date_range = [start_date + timedelta(days=i)
                  for i in range((end_date - start_date).days + 1)]

    # ✅ Company-filtered employee count (no redirect)
    total_employees = get_company_filtered(
        request,
        User.objects.filter(
            is_superuser=False,
            profile__is_active=True,
        )
    ).count()

    if total_employees == 0:
        return JsonResponse({
            'labels': [], 'present': [], 'on_leave': [],
            'absent': [], 'total_employees': 0
        })

    labels, present_pct, on_leave_pct, absent_pct = [], [], [], []

    for d in date_range:
        # ── Future day (weekly view only) → null so line stops, label stays ──
        if period == 'week' and d > today:
            labels.append(d.strftime('%a'))
            present_pct.append(None)
            on_leave_pct.append(None)
            absent_pct.append(None)
            continue

        present = get_company_filtered(
            request,
            Attendance.objects.filter(
                date=d,
                status='Present',
                user__is_superuser=False,
                user__profile__is_active=True,
            )
        ).values('user').distinct().count()

        on_leave = get_company_filtered(
            request,
            LeaveRequest.objects.filter(
                status='Approved',
                start_date__lte=d,
                end_date__gte=d,
                user__is_superuser=False,
                user__profile__is_active=True,
            )
        ).values('user').distinct().count()

        # Denominator = employees expected to work (exclude those on leave)
        expected = max(0, total_employees - on_leave)

        present_pct_val = round((present / expected) * 100, 1) if expected else 0
        on_leave_pct_val = round((on_leave / total_employees) * 100, 1) if total_employees else 0
        absent_pct_val = max(0, 100 - present_pct_val - on_leave_pct_val)

        labels.append(d.strftime('%a' if period == 'week' else '%d %b'))
        present_pct.append(present_pct_val)
        on_leave_pct.append(on_leave_pct_val)
        absent_pct.append(absent_pct_val)

    return JsonResponse({
        'labels': labels,
        'present': present_pct,
        'on_leave': on_leave_pct,
        'absent': absent_pct,
        'total_employees': total_employees,
    })


# ---------- Setup Page ----------
@login_required
@company_required
def setup(request):
    from .utils import get_company_filtered

    shifts      = get_company_filtered(request, Shift.objects.all()).order_by('name')
    leave_types = get_company_filtered(request, LeaveType.objects.all()).order_by('name')
    holidays    = get_company_filtered(request, Holiday.objects.all()).order_by('date')

    # Which tab to open on load — defaults to 'attendance'
    active_tab = request.GET.get('tab', 'attendance')
    if active_tab not in ('attendance', 'assign', 'leave-types', 'holidays'):
        active_tab = 'attendance'

    context = {
        'shifts':      shifts,
        'leave_types': leave_types,
        'holidays':    holidays,
        'active_tab':  active_tab,
    }
    return render(request, 'setup.html', context)
    

# ---------- Shift Management (Admin only) ----------

@login_required
@hr_admin_required
@company_required
def shift_list(request):
    from .utils import get_company_filtered
    shifts = get_company_filtered(request, Shift.objects.all()).order_by('start_time')
    return render(request, 'shift_list.html', {'shifts': shifts})
    
@login_required
@hr_admin_required
@company_required
def shift_create(request):
    from .utils import get_user_company   # ✅ Added local import
    
    if request.method == 'POST':
        Shift.objects.create(
            company=get_user_company(request),
            name=request.POST.get('name'),
            start_time=request.POST.get('start_time'),
            end_time=request.POST.get('end_time'),
            break_start=request.POST.get('break_start') or None,
            break_end=request.POST.get('break_end') or None,
            grace_period=int(request.POST.get('grace_period', 0)),
            min_working_hours=int(request.POST.get('min_working_hours', 480)),
            overtime_allowed=request.POST.get('overtime_allowed') == 'on',
            overtime_limit=float(request.POST.get('overtime_limit', 2)),
            mon=request.POST.get('mon') == 'on',
            tue=request.POST.get('tue') == 'on',
            wed=request.POST.get('wed') == 'on',
            thu=request.POST.get('thu') == 'on',
            fri=request.POST.get('fri') == 'on',
            sat=request.POST.get('sat') == 'on',
            sun=request.POST.get('sun') == 'on',
        )
        messages.success(request, 'Shift created successfully.')
        return redirect('shift_list')
    return render(request, 'shift_form.html', {'action': 'Create'})



@login_required
@hr_admin_required
@company_required
def shift_edit(request, pk):
    from .utils import get_user_company
    
    # ─── Security: ownership check ───
    if request.user.is_superuser:
        shift = get_object_or_404(Shift, id=pk)
    else:
        company = get_user_company(request)
        shift = get_object_or_404(Shift, id=pk, company=company)
    
    if request.method == 'POST':
        shift.name = request.POST.get('name')
        shift.start_time = request.POST.get('start_time')
        shift.end_time = request.POST.get('end_time')
        shift.break_start = request.POST.get('break_start') or None
        shift.break_end = request.POST.get('break_end') or None
        shift.grace_period = int(request.POST.get('grace_period', 0))
        shift.min_working_hours = int(request.POST.get('min_working_hours', 480))
        shift.overtime_allowed = request.POST.get('overtime_allowed') == 'on'
        shift.overtime_limit = float(request.POST.get('overtime_limit', 2))
        shift.mon = request.POST.get('mon') == 'on'
        shift.tue = request.POST.get('tue') == 'on'
        shift.wed = request.POST.get('wed') == 'on'
        shift.thu = request.POST.get('thu') == 'on'
        shift.fri = request.POST.get('fri') == 'on'
        shift.sat = request.POST.get('sat') == 'on'
        shift.sun = request.POST.get('sun') == 'on'
        shift.save()
        messages.success(request, 'Shift updated successfully.')
        return redirect('shift_list')
    
    return render(request, 'shift_form.html', {'action': 'Edit', 'shift': shift})

@login_required
@hr_admin_required
@company_required
def shift_delete(request, pk):
    from .utils import get_user_company   # ✅ Added
    
    if request.user.is_superuser:
        shift = get_object_or_404(Shift, id=pk)
    else:
        shift = get_object_or_404(Shift, id=pk, company=get_user_company(request))
    
    if request.method == 'POST':
        shift.delete()
        messages.success(request, 'Shift deleted successfully.')
        return redirect('shift_list')
    return render(request, 'shift_confirm_delete.html', {'shift': shift})

# ---------- Bulk Shift Assignment (Admin only) ----------

@login_required
@admin_or_hr_required
@company_required
def assign_shift(request):
    from .utils import get_user_company, get_company_filtered
    
    user = request.user

    if request.method == 'POST':
        shift_id = request.POST.get('shift')
        employee_ids = request.POST.getlist('employees')
        effective_from = request.POST.get('effective_from')

        if not shift_id or not employee_ids:
            messages.error(request, 'Please select at least one employee and a shift.')
            return redirect('assign_shift')

        # ─── Security: shift must belong to user's company ───
        if user.is_superuser:
            shift = get_object_or_404(Shift, id=shift_id)
        else:
            company = get_user_company(request)
            shift = get_object_or_404(Shift, id=shift_id, company=company)

        # ─── Filter employee_ids by role and company ───
        if user.is_superuser:
            # Superuser can assign any employee
            allowed_profiles = EmployeeProfile.objects.filter(user_id__in=employee_ids)
        elif user.groups.filter(name='HR Admin').exists():
            # HR Admin: only own company employees
            company = get_user_company(request)
            allowed_profiles = EmployeeProfile.objects.filter(
                user_id__in=employee_ids, company=company
            )
        else:
            # Manager: only their team
            try:
                profile = user.profile
                team_members = EmployeeProfile.objects.filter(
                    manager=profile
                ).values_list('user_id', flat=True)
                allowed_profiles = EmployeeProfile.objects.filter(
                    user_id__in=employee_ids
                ).filter(user_id__in=team_members)   # ✅ Chained filter (was commented out)
            except EmployeeProfile.DoesNotExist:
                allowed_profiles = EmployeeProfile.objects.none()

        allowed_ids = list(allowed_profiles.values_list('user_id', flat=True))
        
        if not allowed_ids:
            messages.error(request, 'No valid employees selected for shift assignment.')
            return redirect('assign_shift')

        updated = EmployeeProfile.objects.filter(user_id__in=allowed_ids).update(
            shift=shift,
            shift_effective_from=effective_from if effective_from else None
        )
        messages.success(request, f'Shift "{shift.name}" assigned to {updated} employee(s).')
        return redirect('assign_shift')

    # ─── GET – filter everything by company ───
    shifts = get_company_filtered(request, Shift.objects.all()).order_by('name')

    # Filter employees based on role
    if user.is_superuser:
        employees = User.objects.filter(is_superuser=False).select_related('profile').order_by('username')
    elif user.groups.filter(name='HR Admin').exists():
        company = get_user_company(request)
        employees = User.objects.filter(
            is_superuser=False, profile__company=company
        ).select_related('profile').order_by('username')
    else:
        # Manager: only their team
        try:
            profile = user.profile
            team_ids = EmployeeProfile.objects.filter(
                manager=profile
            ).values_list('user_id', flat=True)
            employees = User.objects.filter(id__in=team_ids).select_related('profile').order_by('username')
        except EmployeeProfile.DoesNotExist:
            employees = User.objects.none()

    # Get filter parameters
    department_filter = request.GET.get('department', '')
    designation_filter = request.GET.get('designation', '')
    location_filter = request.GET.get('location', '')
    team_filter = request.GET.get('team', '')

    # Apply filters
    filtered_employees = employees
    if department_filter:
        filtered_employees = filtered_employees.filter(profile__department__icontains=department_filter)
    if designation_filter:
        filtered_employees = filtered_employees.filter(profile__designation__icontains=designation_filter)
    if location_filter:
        filtered_employees = filtered_employees.filter(profile__location__icontains=location_filter)
    if team_filter:
        filtered_employees = filtered_employees.filter(profile__team__icontains=team_filter)

    # Build employee list
    employee_list = []
    for emp_user in filtered_employees:
        profile = getattr(emp_user, 'profile', None)
        employee_list.append({
            'id': emp_user.id,
            'username': emp_user.username,
            'full_name': profile.full_name if profile else emp_user.username,
            'shift_name': profile.shift.name if profile and profile.shift else 'None',
            'department': profile.department if profile else '',
            'designation': profile.designation if profile else '',
            'location': getattr(profile, 'location', ''),
            'team': getattr(profile, 'team', ''),
        })

    # ─── Distinct departments/designations from the SAME company only ───
    distinct_departments = get_company_filtered(
        request, EmployeeProfile.objects.all()
    ).values_list('department', flat=True).distinct().order_by('department')
    
    distinct_designations = get_company_filtered(
        request, EmployeeProfile.objects.all()
    ).values_list('designation', flat=True).distinct().order_by('designation')

    context = {
        'employees': employee_list,
        'shifts': shifts,
        'department_filter': department_filter,
        'designation_filter': designation_filter,
        'location_filter': location_filter,
        'team_filter': team_filter,
        'distinct_departments': [d for d in distinct_departments if d],
        'distinct_designations': [d for d in distinct_designations if d],
    }
    return render(request, 'assign_shift.html', context)



# ---------- Employee Search API (for autocomplete) ----------


@login_required
def employee_search_api(request):
    from .utils import get_company_filtered
    
    query = request.GET.get('q', '')
    if len(query) < 1:
        return JsonResponse([], safe=False)

    employees = get_company_filtered(
        request,
        User.objects.filter(is_superuser=False)
    ).filter(
        Q(username__icontains=query) |
        Q(profile__full_name__icontains=query)
    )[:10].select_related('profile')

    results = []
    for emp in employees:
        profile = getattr(emp, 'profile', None)
        results.append({
            'id': emp.id,
            'username': emp.username,
            'full_name': profile.full_name if profile else emp.username,
            'employee_id': profile.employee_id if profile else '',
        })
    return JsonResponse(results, safe=False)



    

def error_404(request, exception):
    return render(request, '404.html', status=404)

def error_500(request):
    return render(request, '500.html', status=500)

def error_403(request, exception):
    return render(request, '403.html', status=403)

def error_400(request, exception):
    return render(request, '400.html', status=400)



    
# ---------- Attendance Report PDF ----------
@login_required
@hr_admin_required
@company_required
def attendance_report_pdf(request):
    from .utils import get_employee_attendance_for_pdf

    today = date.today()
    month = int(request.GET.get('month', today.month))
    year  = int(request.GET.get('year',  today.year))
    download_type = request.GET.get('download_type', 'all')
    employee_id   = request.GET.get('employee_id')

    if request.user.is_superuser:
        employees = User.objects.filter(is_superuser=False).order_by('username')
    elif request.user.groups.filter(name='HR Admin').exists():
        company = get_user_company(request)
        employees = User.objects.filter(
            is_superuser=False, profile__company=company
        ).order_by('username')
    else:
        try:
            profile = request.user.profile
            team_ids = EmployeeProfile.objects.filter(
                manager=profile
            ).values_list('user_id', flat=True)
            employees = User.objects.filter(id__in=team_ids).order_by('username')
        except EmployeeProfile.DoesNotExist:
            employees = User.objects.none()

    if request.GET.get('department'):
        employees = employees.filter(
            profile__department__icontains=request.GET['department'])
    if request.GET.get('employee'):
        s = request.GET['employee']
        employees = employees.filter(
            Q(username__icontains=s) | Q(profile__full_name__icontains=s))
    if request.GET.get('shift') and request.GET['shift'] != 'all':
        employees = employees.filter(profile__shift_id=request.GET['shift'])

    if download_type == 'single':
        if not employee_id:
            messages.error(request, 'Please select an employee.')
            return redirect('attendance_report')
        emp = employees.filter(id=employee_id).first()
        if not emp:
            messages.error(request, 'Employee not found or you do not have access.')
            return redirect('attendance_report')
        employees = [emp]

    if not employees:
        messages.error(request, 'No employees found for the selected filters.')
        return redirect('attendance_report')

    buffer    = BytesIO()
    first_day = date(year, month, 1)
    _, last_day_num = monthrange(year, month)
    last_day  = date(year, month, last_day_num)

    if request.user.is_superuser:
        company = Company.objects.first()
    else:
        company = get_user_company(request)
    company_name = (company.name if company else 'HRMS').upper()
    month_label  = first_day.strftime('%B %Y')

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=14 * mm, bottomMargin=14 * mm,
        leftMargin=14 * mm, rightMargin=14 * mm,
    )
    PAGE_W = doc.width

    INK      = colors.HexColor('#0f172a')
    MUTED    = colors.HexColor('#64748b')
    FAINT    = colors.HexColor('#94a3b8')
    LIGHTER  = colors.HexColor('#cbd5e1')
    HAIR     = colors.HexColor('#e2e8f0')
    SOFT     = colors.HexColor('#f1f5f9')
    SOFTER   = colors.HexColor('#f8fafc')
    WHITE    = colors.HexColor('#ffffff')

    styles = getSampleStyleSheet()

    s_company = ParagraphStyle('Comp', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=22,
        textColor=WHITE, leading=26)
    s_period = ParagraphStyle('Per', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=16,
        textColor=WHITE, leading=19, alignment=TA_RIGHT)
    s_section = ParagraphStyle('Sec', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8,
        textColor=FAINT, leading=10, letterSpacing=1.5)
    s_emp_name = ParagraphStyle('EN', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=15,
        textColor=INK, leading=18)
    s_meta_label = ParagraphStyle('ML', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=6.5,
        textColor=FAINT, leading=8.5, letterSpacing=1)
    s_meta_value = ParagraphStyle('MV', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=10,
        textColor=INK, leading=12)
    s_kpi_label = ParagraphStyle('KL', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7,
        textColor=FAINT, leading=9, letterSpacing=1, alignment=TA_CENTER)
    s_kpi_value = ParagraphStyle('KV', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=22,
        textColor=INK, leading=26, alignment=TA_CENTER)
    s_thead = ParagraphStyle('TH', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7.5,
        textColor=WHITE, leading=10, letterSpacing=0.8)
    s_thead_c = ParagraphStyle('THC', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7.5,
        textColor=WHITE, leading=10, letterSpacing=0.8, alignment=TA_CENTER)
    s_thead_r = ParagraphStyle('THR', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7.5,
        textColor=WHITE, leading=10, letterSpacing=0.8, alignment=TA_RIGHT)
    s_cell_date = ParagraphStyle('CD', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=9,
        textColor=INK, leading=11)
    s_cell_day = ParagraphStyle('CDay', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7,
        textColor=FAINT, leading=9, letterSpacing=1, alignment=TA_CENTER)
    s_cell_c = ParagraphStyle('CC', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9,
        textColor=MUTED, leading=11, alignment=TA_CENTER)
    s_cell_r = ParagraphStyle('CR', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9,
        textColor=INK, leading=11, alignment=TA_RIGHT)
    s_chip = ParagraphStyle('Chip', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7,
        textColor=INK, leading=9, letterSpacing=0.5, alignment=TA_CENTER)
    s_chip_muted = ParagraphStyle('ChipM', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7,
        textColor=MUTED, leading=9, letterSpacing=0.5, alignment=TA_CENTER)
    s_footer_val = ParagraphStyle('FV', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8.5,
        textColor=MUTED, leading=10.5)
    s_footer_note = ParagraphStyle('FN', parent=styles['Normal'],
        fontName='Helvetica-Oblique', fontSize=7.5,
        textColor=FAINT, leading=10, alignment=TA_CENTER)

    def chip(text):
        t = (text or '').upper()
        style = s_chip_muted if t in ('ABSENT', 'WEEKEND', 'HOLIDAY') else s_chip
        bg    = HAIR if t in ('ABSENT', 'WEEKEND', 'HOLIDAY') else SOFT
        c = Table([[Paragraph(t, style)]], colWidths=[22*mm], rowHeights=[6*mm])
        c.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), bg),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ('ROUNDEDCORNERS', [3, 3, 3, 3]),
        ]))
        return c

    elements = []
    total    = len(employees)
    now_str  = timezone.localtime(timezone.now()).strftime('%d %b %Y · %I:%M %p')

    for page_idx, emp in enumerate(employees):
        if page_idx > 0:
            elements.append(PageBreak())

        emp_data = get_employee_attendance_for_pdf(emp, year, month, first_day, last_day)
        profile  = emp_data['profile']
        shift    = emp_data['shift']
        daily    = emp_data['daily_data']

        masthead = Table(
            [[
                Paragraph(
                    "<b>ATTENDANCE REPORT</b><br/>"
                    f"<font size='22'>{company_name}</font>",
                    s_company,
                ),
                Paragraph(
                    "<b>PERIOD</b><br/>"
                    f"<font size='16'>{month_label}</font><br/>"
                    f"<font size='8'>Generated {now_str}</font>",
                    s_period,
                ),
            ]],
            colWidths=[PAGE_W * 0.55, PAGE_W * 0.45],
            rowHeights=[32 * mm],
        )
        masthead.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), INK),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (0,-1), 24),
            ('RIGHTPADDING', (0,0), (0,-1), 12),
            ('LEFTPADDING', (1,0), (1,-1), 12),
            ('RIGHTPADDING', (1,0), (1,-1), 24),
            ('ROUNDEDCORNERS', [8, 8, 8, 8]),
        ]))
        elements.append(masthead)
        elements.append(Spacer(1, 20))

        emp_name = profile.full_name if profile else emp.username
        emp_uid  = profile.employee_id if profile else '—'

        emp_card = Table(
            [[Paragraph(
                "<b>EMPLOYEE</b><br/>"
                f"<font size='15'>{emp_name}</font><br/>"
                f"<font size='9' color='#64748b'>ID · {emp_uid}</font>",
                s_emp_name,
            )]],
            colWidths=[PAGE_W],
            rowHeights=[24 * mm],
        )
        emp_card.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), SOFTER),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 22),
            ('RIGHTPADDING', (0,0), (-1,-1), 22),
            ('ROUNDEDCORNERS', [8, 8, 8, 8]),
        ]))
        elements.append(emp_card)
        elements.append(Spacer(1, 8))

        meta_items = [
            ("DEPARTMENT",  profile.department if profile else '—'),
            ("DESIGNATION", profile.designation if profile else '—'),
            ("SHIFT",       shift.name if shift else '—'),
            ("MANAGER",     (profile.manager.full_name
                             if profile and profile.manager else '—')),
        ]
        meta_labels = [Paragraph(l, s_meta_label) for l, _ in meta_items]
        meta_values = [Paragraph(v, s_meta_value) for _, v in meta_items]

        meta_table = Table([meta_labels, meta_values], colWidths=[PAGE_W / 4] * 4)
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), SOFTER),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 20),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,0), 12),
            ('BOTTOMPADDING', (0,0), (-1,0), 2),
            ('TOPPADDING', (0,1), (-1,1), 0),
            ('BOTTOMPADDING', (0,1), (-1,1), 14),
            ('ROUNDEDCORNERS', [8, 8, 8, 8]),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 22))

        ot_h = int(emp_data['overtime_minutes'] // 60)
        ot_m = int(emp_data['overtime_minutes'] % 60)
        ot_str = f"{ot_h}h {ot_m}m" if (ot_h or ot_m) else "0h"

        kpis = [
            ("WORKING DAYS", str(emp_data['working_days'])),
            ("PRESENT",      str(emp_data['present'])),
            ("ABSENT",       str(emp_data['absent'])),
            ("LEAVE",        str(emp_data['leave'])),
            ("OVERTIME",     ot_str),
        ]
        kpi_labels = [Paragraph(l, s_kpi_label) for l, _ in kpis]
        kpi_values = [Paragraph(v, s_kpi_value) for _, v in kpis]

        kpi_table = Table([kpi_labels, kpi_values],
                          colWidths=[PAGE_W / 5] * 5,
                          rowHeights=[9 * mm, 18 * mm])
        kpi_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), SOFT),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LINEAFTER', (0,0), (-2,-1), 1, WHITE),
            ('ROUNDEDCORNERS', [8, 8, 8, 8]),
        ]))
        elements.append(kpi_table)
        elements.append(Spacer(1, 22))

        elements.append(Paragraph("DAILY ATTENDANCE", s_section))
        elements.append(Spacer(1, 10))

        thead_row = [
            Paragraph("DATE",      s_thead),
            Paragraph("DAY",       s_thead_c),
            Paragraph("STATUS",    s_thead_c),
            Paragraph("CHECK IN",  s_thead_c),
            Paragraph("CHECK OUT", s_thead_c),
            Paragraph("HOURS",     s_thead_r),
        ]

        daily_rows = [thead_row]
        weekend_idx = []
        for ridx, day in enumerate(daily, start=1):
            if day['day_name'] in ('Saturday', 'Sunday'):
                weekend_idx.append(ridx)
            daily_rows.append([
                Paragraph(day['date'].strftime('%d %b'), s_cell_date),
                Paragraph(day['day_name'][:3].upper(),   s_cell_day),
                chip(day['status']),
                Paragraph(day['check_in']  or '—',       s_cell_c),
                Paragraph(day['check_out'] or '—',       s_cell_c),
                Paragraph(day['working_hours'] or '—',   s_cell_r),
            ])

        daily_cols = [
            PAGE_W * 0.12, PAGE_W * 0.09, PAGE_W * 0.22,
            PAGE_W * 0.19, PAGE_W * 0.19, PAGE_W * 0.19,
        ]

        daily_table = Table(daily_rows, colWidths=daily_cols, repeatRows=1)
        daily_style = [
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('BACKGROUND', (0,0), (-1,0), INK),
            ('TOPPADDING', (0,0), (-1,0), 12),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
            ('LINEBELOW', (0,1), (-1,-1), 0.5, HAIR),
            ('BOX', (0,0), (-1,-1), 0.75, LIGHTER),
            ('ROUNDEDCORNERS', [8, 8, 8, 8]),
        ]
        for ridx in weekend_idx:
            daily_style.append(('BACKGROUND', (0,ridx), (-1,ridx), SOFTER))

        daily_table.setStyle(TableStyle(daily_style))
        elements.append(daily_table)

        elements.append(Spacer(1, 24))

        footer = Table(
            [[
                Paragraph(f"<b>EMPLOYEE ID</b><br/>"
                          f"<font color='#64748b'>{emp_uid}</font>", s_footer_val),
                Paragraph(f"<b>PERIOD</b><br/>"
                          f"<font color='#64748b'>{month_label}</font>", s_footer_val),
                Paragraph(f"<b>GENERATED</b><br/>"
                          f"<font color='#64748b'>{now_str}</font>", s_footer_val),
                Paragraph(f"<b>PAGE</b><br/>"
                          f"<font color='#64748b'>{page_idx + 1} of {total}</font>", s_footer_val),
            ]],
            colWidths=[PAGE_W / 4] * 4,
        )
        footer.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), SOFTER),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 16),
            ('RIGHTPADDING', (0,0), (-1,-1), 12),
            ('TOPPADDING', (0,0), (-1,-1), 12),
            ('BOTTOMPADDING', (0,0), (-1,-1), 12),
            ('ROUNDEDCORNERS', [8, 8, 8, 8]),
        ]))
        elements.append(footer)
        elements.append(Spacer(1, 10))
        elements.append(Paragraph(
            "This is a system-generated attendance report. "
            "For queries, contact your HR administrator.",
            s_footer_note,
        ))

    doc.build(elements)
    buffer.seek(0)

    month_name = first_day.strftime('%B_%Y')
    if download_type == 'single' and len(employees) == 1:
        emp = employees[0]
        emp_id = (emp.profile.employee_id
                  if hasattr(emp, 'profile') and emp.profile
                  else f"EMP{emp.id:04d}")
        filename = f"attendance_{emp_id}_{month_name}.pdf"
    else:
        filename = f"attendance_{month_name}.pdf"

    return FileResponse(buffer, as_attachment=True, filename=filename)
    
    

# *********************payroll


@login_required
@hr_admin_required
@payroll_required
@company_required
def payroll_dashboard(request):
    from .utils import get_user_company
    from django.db.models import Sum, Count, Q

    if request.user.is_superuser:
        company = Company.objects.first()
    else:
        company = get_user_company(request)

    # ── Employee counts ──
    total_employees = EmployeeProfile.objects.filter(company=company).count()
    employees_with_salary = EmployeeSalary.objects.filter(
        company=company, status='active'
    ).values('employee').distinct().count()

    # ── Salary config totals ──
    salary_agg = EmployeeSalary.objects.filter(
        company=company, status='active'
    ).aggregate(
        total_basic=Sum('basic_salary'),
        total_hra=Sum('hra'),
        total_allowance=Sum('allowance'),
        total_gross=Sum('gross_salary'),
    )

    # ── Payroll month totals (all months in DB) ──
    payroll_agg = Payroll.objects.filter(company=company).aggregate(
        total_ot=Sum('overtime_amount'),
        total_unpaid_deduction=Sum('unpaid_leave_deduction'),
        total_other_deduction=Sum('other_deduction'),
        total_net=Sum('net_salary'),
    )

    # ── Payroll status counts ──
    payroll_stats = Payroll.objects.filter(company=company).aggregate(
        draft=Count('id', filter=Q(status='draft')),
        processed=Count('id', filter=Q(status='processed')),
        paid=Count('id', filter=Q(status='paid')),
    )

    context = {
        'total_employees': total_employees,
        'employees_with_salary': employees_with_salary,
        'employees_without_salary': total_employees - employees_with_salary,

        # Salary config totals
        'total_basic': salary_agg['total_basic'] or 0,
        'total_hra': salary_agg['total_hra'] or 0,
        'total_allowance': salary_agg['total_allowance'] or 0,
        'total_gross': salary_agg['total_gross'] or 0,

        # Payroll month totals
        'total_overtime': payroll_agg['total_ot'] or 0,
        'total_unpaid_leave_deduction': payroll_agg['total_unpaid_deduction'] or 0,
        'total_other_deduction': payroll_agg['total_other_deduction'] or 0,
        'total_net': payroll_agg['total_net'] or 0,

        # Payroll status
        'draft_payroll': payroll_stats['draft'] or 0,
        'processed_payroll': payroll_stats['processed'] or 0,
        'paid_payroll': payroll_stats['paid'] or 0,
    }
    return render(request, 'payroll/dashboard.html', context)



@login_required
@hr_admin_required
@payroll_required
@company_required
def employee_salary_list(request):
    from .utils import get_user_company
    
    if request.user.is_superuser:
        employees = EmployeeProfile.objects.all().order_by('full_name')
    else:
        company = get_user_company(request)
        employees = EmployeeProfile.objects.filter(company=company).order_by('full_name')
    
    salary_data = []
    for emp in employees:
        salary = EmployeeSalary.objects.filter(employee=emp, status='active').first()
        salary_data.append({
            'employee': emp,
            'has_salary': salary is not None,
            'salary': salary,
        })
    return render(request, 'payroll/employee_salary_list.html', {'salary_data': salary_data})
    
@login_required
@hr_admin_required
@payroll_required
@company_required
def employee_salary_create(request):
    from .utils import get_user_company
    from decimal import Decimal

    user_company = get_user_company(request)

    if request.user.is_superuser:
        employees = EmployeeProfile.objects.all().order_by('full_name')
    else:
        employees = EmployeeProfile.objects.filter(company=user_company).order_by('full_name')

    if request.method == 'POST':
        employee_id = request.POST.get('employee')
        salary_type = request.POST.get('salary_type')
        basic_salary = Decimal(request.POST.get('basic_salary') or 0)
        hra = Decimal(request.POST.get('hra') or 0)
        allowance = Decimal(request.POST.get('allowance') or 0)
        overtime_rate = Decimal(request.POST.get('overtime_rate') or 0)   # ✅ NEW
        effective_from = request.POST.get('effective_from')

        if not employee_id:
            messages.error(request, 'Please select an employee.')
            return redirect('employee_salary_create')

        if request.user.is_superuser:
            employee = get_object_or_404(EmployeeProfile, id=employee_id)
        else:
            employee = get_object_or_404(
                EmployeeProfile, id=employee_id, company=user_company
            )

        company = employee.company
        if not company:
            messages.error(request, f'{employee.full_name} has no company assigned.')
            return redirect('employee_salary_create')

        existing = EmployeeSalary.objects.filter(employee=employee, status='active').first()
        if existing:
            messages.error(request, 'Salary is already configured for this employee.')
            return redirect('employee_salary_edit', pk=existing.id)

        EmployeeSalary.objects.create(
            company=company,
            employee=employee,
            salary_type=salary_type,
            basic_salary=basic_salary,
            hra=hra,
            allowance=allowance,
            overtime_rate=overtime_rate,        # ✅ NEW
            # ❌ REMOVED: deduction=deduction,
            effective_from=effective_from,
            status='active',
        )
        messages.success(request, f'Salary added for {employee.full_name}')
        return redirect('employee_salary_list')

    return render(request, 'payroll/employee_salary_form.html', {
        'employees': employees,
        'action': 'Add',
    })



@login_required
@hr_admin_required
@payroll_required
@company_required
def employee_salary_edit(request, pk):
    from .utils import get_user_company
    from decimal import Decimal

    if request.user.is_superuser:
        salary = get_object_or_404(EmployeeSalary, id=pk)
    else:
        company = get_user_company(request)
        salary = get_object_or_404(EmployeeSalary, id=pk, company=company)

    if request.method == 'POST':
        salary.salary_type = request.POST.get('salary_type')
        salary.basic_salary = Decimal(request.POST.get('basic_salary') or 0)
        salary.hra = Decimal(request.POST.get('hra') or 0)
        salary.allowance = Decimal(request.POST.get('allowance') or 0)
        salary.overtime_rate = Decimal(request.POST.get('overtime_rate') or 0)   # ✅ NEW
        # ❌ REMOVED: salary.deduction = ...
        salary.effective_from = request.POST.get('effective_from')
        salary.status = request.POST.get('status')
        salary.save()
        messages.success(request, 'Salary updated successfully')
        return redirect('employee_salary_list')

    return render(request, 'payroll/employee_salary_form.html', {
        'salary': salary,
        'action': 'Edit',
    })



@login_required
@hr_admin_required
@payroll_required
@company_required
def payroll_processing(request):
    from .utils import get_user_company, calculate_monthly_payroll
    from datetime import datetime as dt

    if request.user.is_superuser:
        company = Company.objects.first()
    else:
        company = get_user_company(request)

    month = int(request.GET.get('month', dt.now().month))
    year = int(request.GET.get('year', dt.now().year))

    active_salaries = EmployeeSalary.objects.filter(
    company=company, status='active'
).select_related('employee', 'employee__user')

    payroll_data = []
    for salary in active_salaries:
        emp = salary.employee
        # Calculate fresh (or read existing)
        calc = calculate_monthly_payroll(emp, year, month, salary)
        existing = Payroll.objects.filter(
            company=company, employee=emp, month=month, year=year
        ).first()
        payroll_data.append({
            'employee': emp,
            'salary': salary,
            'calc': calc,
            'has_payroll': existing is not None,
            'payroll': existing,
        })

    context = {
        'payroll_data': payroll_data,
        'month': month,
        'year': year,
        'months': range(1, 13),
        'years': range(2020, 2031),
    }
    return render(request, 'payroll/payroll_processing.html', context)



@login_required
@hr_admin_required
@payroll_required
@company_required
def payroll_generate(request):
    from .utils import get_user_company, calculate_monthly_payroll
    
    if request.method != 'POST':
        return redirect('payroll_processing')

    if request.user.is_superuser:
        company = Company.objects.first()
    else:
        company = get_user_company(request)

    month = int(request.POST.get('month'))
    year = int(request.POST.get('year'))

    salaries = EmployeeSalary.objects.filter(company=company, status='active')

    created = 0
    for salary in salaries:
        emp = salary.employee
        if Payroll.objects.filter(
            company=company, employee=emp, month=month, year=year
        ).exists():
            continue

        calc = calculate_monthly_payroll(emp, year, month, salary)

        Payroll.objects.create(
            company=company,
            employee=emp,
            month=month,
            year=year,
            basic_salary=calc['basic_salary'],
            hra=calc['hra'],
            allowance=calc['allowance'],
            gross_salary=calc['gross_salary'],
            working_days=calc['working_days'],
            present_days=calc['present_days'],
            absent_days=calc['absent_days'],
            paid_leave_days=calc['paid_leave_days'],
            unpaid_leave_days=calc['unpaid_leave_days'],
            overtime_hours=calc['overtime_hours'],
            overtime_rate=calc['overtime_rate'],
            overtime_amount=calc['overtime_amount'],
            absent_deduction=calc['absent_deduction'],
            unpaid_leave_deduction=calc['unpaid_leave_deduction'],
            other_deduction=calc['other_deduction'],
            deduction=calc['other_deduction'],  # keep old field in sync
            net_salary=calc['net_payable'],
            status='draft',
        )
        created += 1

    messages.success(request, f'Generated {created} payroll records for {month}/{year}')
    return redirect('payroll_processing')



@login_required
@hr_admin_required
@payroll_required
@company_required
def payroll_process(request, pk):
    from .utils import get_user_company
    
    if request.user.is_superuser:
        payroll = get_object_or_404(Payroll, id=pk)
    else:
        payroll = get_object_or_404(
            Payroll, id=pk, company=get_user_company(request)
        )
    
    payroll.status = 'processed'
    payroll.save()
    messages.success(request, 'Payroll processed')
    return redirect('payroll_processing')



@login_required
@hr_admin_required
@payroll_required
@company_required
def payroll_paid(request, pk):
    from .utils import get_user_company
    
    if request.user.is_superuser:
        payroll = get_object_or_404(Payroll, id=pk)
    else:
        payroll = get_object_or_404(
            Payroll, id=pk, company=get_user_company(request)
        )
    
    payroll.status = 'paid'
    payroll.save()
    messages.success(request, 'Payroll marked as Paid')
    return redirect('payroll_processing')


@login_required
@hr_admin_required
@payroll_required
@company_required
def payroll_list(request):
    from .utils import get_user_company
    if request.user.is_superuser:
        payrolls = Payroll.objects.all().order_by('-year', '-month')
    else:
        company = get_user_company(request)
        payrolls = Payroll.objects.filter(company=company).order_by('-year', '-month')
    return render(request, 'payroll/payroll_list.html', {'payrolls': payrolls})

    

@login_required
@hr_admin_required
@company_required
def payroll_delete(request, pk):
    """
    Delete a payroll record — ONLY if it's still a Draft.
    Processed and Paid records are locked forever.
    """
    if request.user.is_superuser:
        payroll = get_object_or_404(Payroll, id=pk)
    else:
        payroll = get_object_or_404(
            Payroll, id=pk, company=get_user_company(request)
        )

    # Only Drafts can be deleted
    if payroll.status.lower() != 'draft':
        messages.error(
            request,
            f"This payroll is already '{payroll.status}' and cannot be deleted. "
            f"Only Draft payrolls can be regenerated."
        )
        return redirect('payroll_list')

    if request.method == 'POST':
        month = payroll.month
        year = payroll.year
        employee_name = (
            payroll.employee.full_name or payroll.employee.user.username
        )
        payroll.delete()

        messages.success(
            request,
            f"Draft payroll for {employee_name} ({month}/{year}) deleted. "
            f"You can now regenerate it from Payroll Processing."
        )
        return redirect('payroll_list')

    return render(request, 'payroll/payroll_confirm_delete.html', {
        'payroll': payroll,
    })




@login_required
@hr_admin_required
@payroll_required
@company_required
def payslip_pdf(request, pk):
    from .utils import get_user_company, number_to_words
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    from io import BytesIO
    from django.http import FileResponse
    from decimal import Decimal

    # ─── Ownership check ───
    if request.user.is_superuser:
        payroll = get_object_or_404(Payroll, id=pk)
    else:
        payroll = get_object_or_404(
            Payroll, id=pk, company=get_user_company(request)
        )

    employee = payroll.employee
    company = payroll.company

    BLACK = colors.HexColor('#000000')
    WHITE = colors.HexColor('#ffffff')
    DARK  = colors.HexColor('#555555')      # for header background

    # ─── Values ───
    def d(v):
        return v if v is not None else Decimal('0')

    hra       = d(payroll.hra)
    ot_amount = d(payroll.overtime_amount)
    abs_ded   = d(payroll.absent_deduction)
    ul_ded    = d(payroll.unpaid_leave_deduction)
    other_ded = d(payroll.other_deduction)

    gross     = d(payroll.gross_salary) + ot_amount
    total_ded = abs_ded + ul_ded + other_ded
    net       = d(payroll.net_salary)

    # ─── Document ───
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=16 * mm, bottomMargin=16 * mm,
        leftMargin=18 * mm, rightMargin=18 * mm,
        title=f"Payslip — {employee.full_name or employee.user.username} — "
              f"{payroll.month:02d}/{payroll.year}",
        author=company.name if company else 'HRMS',
        subject='Payslip',
    )

    PAGE_W = doc.width

    # ═══════════════════════════════════════════════════
    # STYLES
    # ═══════════════════════════════════════════════════
    styles = getSampleStyleSheet()

    # ── Masthead ──
    company_style = ParagraphStyle(
        'Company', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=16,
        textColor=BLACK, leading=19,
    )
    period_big_style = ParagraphStyle(
        'PeriodBig', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=14,
        textColor=BLACK, leading=16,
        alignment=TA_RIGHT,
    )

    # ── Section label (uppercase, small) ──
    section_label_style = ParagraphStyle(
        'SectionLabel', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7.5,
        textColor=BLACK, leading=9.5,
    )

    # ── Field labels / values ──
    field_label_style = ParagraphStyle(
        'FieldLabel', parent=styles['Normal'],
        fontName='Helvetica', fontSize=7,
        textColor=BLACK, leading=9,
    )
    field_value_style = ParagraphStyle(
        'FieldValue', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9.5,
        textColor=BLACK, leading=12,
    )
    field_value_bold_style = ParagraphStyle(
        'FieldValueBold', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=9.5,
        textColor=BLACK, leading=12,
    )

    # ── Table headers — WHITE on DARK ──
    col_header_style = ParagraphStyle(
        'ColHeader', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8,
        textColor=WHITE, leading=10,
    )
    col_header_right_style = ParagraphStyle(
        'ColHeaderRight', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8,
        textColor=WHITE, leading=10,
        alignment=TA_RIGHT,
    )

    # ── Table body cells ──
    cell_style = ParagraphStyle(
        'Cell', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9,
        textColor=BLACK, leading=11.5,
    )
    cell_amount_style = ParagraphStyle(
        'CellAmount', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9,
        textColor=BLACK, leading=11.5,
        alignment=TA_RIGHT,
    )
    cell_bold_style = ParagraphStyle(
        'CellBold', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=9,
        textColor=BLACK, leading=11.5,
    )
    cell_bold_amount_style = ParagraphStyle(
        'CellBoldAmount', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=9,
        textColor=BLACK, leading=11.5,
        alignment=TA_RIGHT,
    )

    # ── Net payable ──
    net_label_style = ParagraphStyle(
        'NetLabel', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=9,
        textColor=BLACK, leading=11,
        alignment=TA_RIGHT,
    )
    net_amount_style = ParagraphStyle(
        'NetAmount', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=18,
        textColor=BLACK, leading=20,
        alignment=TA_RIGHT,
    )

    words_style = ParagraphStyle(
        'Words', parent=styles['Normal'],
        fontName='Helvetica-Oblique', fontSize=8,
        textColor=BLACK, leading=10,
    )
    footer_style = ParagraphStyle(
        'Footer', parent=styles['Normal'],
        fontName='Helvetica', fontSize=7,
        textColor=BLACK, leading=9.5,
    )
    footer_note_style = ParagraphStyle(
        'FooterNote', parent=styles['Normal'],
        fontName='Helvetica-Oblique', fontSize=7,
        textColor=BLACK, leading=9.5, alignment=TA_CENTER,
    )

    elements = []

    # ═══════════════════════════════════════════════════
    # MASTHEAD
    # ═══════════════════════════════════════════════════
    masthead = Table(
        [[
            Paragraph(
                (company.name if company else 'HRMS').upper()
                + "<br/>"
                + "<font size='8' face='Helvetica'>Salary Statement</font>",
                company_style,
            ),
            Paragraph(
                "<font size='8'>P A Y S L I P</font><br/>"
                f"<font size='14'><b>{payroll.month:02d}/{payroll.year}</b></font><br/>"
                f"<font size='7'>Issued "
                f"{timezone.localtime(timezone.now()).strftime('%d %b %Y')}</font>",
                period_big_style,
            ),
        ]],
        colWidths=[PAGE_W * 0.6, PAGE_W * 0.4],
    )
    masthead.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(masthead)
    elements.append(Spacer(1, 14))

    elements.append(HRFlowable(
        width="100%", thickness=1, color=BLACK,
        spaceBefore=0, spaceAfter=16,
    ))

    # ═══════════════════════════════════════════════════
    # EMPLOYEE + ATTENDANCE — two-column
    # ═══════════════════════════════════════════════════
    emp_name = employee.full_name or employee.user.username
    emp_id   = employee.employee_id or '—'
    dept     = employee.department or '—'
    desig    = employee.designation or '—'

    emp_block = [
        [Paragraph("EMPLOYEE", section_label_style), ''],
        [Paragraph("Name", field_label_style),
         Paragraph(emp_name, field_value_bold_style)],
        [Paragraph("ID", field_label_style),
         Paragraph(emp_id, field_value_style)],
        [Paragraph("Designation", field_label_style),
         Paragraph(desig, field_value_style)],
        [Paragraph("Department", field_label_style),
         Paragraph(dept, field_value_style)],
    ]
    emp_table = Table(emp_block, colWidths=[PAGE_W * 0.15, PAGE_W * 0.35])
    emp_table.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ('TOPPADDING',    (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
    ]))

    att_block = [
        [Paragraph("ATTENDANCE", section_label_style), ''],
        [Paragraph("Working Days", field_label_style),
         Paragraph(str(payroll.working_days), field_value_style)],
        [Paragraph("Present", field_label_style),
         Paragraph(str(payroll.present_days), field_value_style)],
        [Paragraph("Absent", field_label_style),
         Paragraph(str(payroll.absent_days), field_value_style)],
        [Paragraph("Paid / Unpaid Leave", field_label_style),
         Paragraph(
             f"{payroll.paid_leave_days or 0} / {payroll.unpaid_leave_days or 0}",
             field_value_style,
         )],
    ]
    att_table = Table(att_block, colWidths=[PAGE_W * 0.22, PAGE_W * 0.28])
    att_table.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('TOPPADDING',    (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
    ]))

    layout_row = Table(
        [[emp_table, att_table]],
        colWidths=[PAGE_W * 0.5, PAGE_W * 0.5],
    )
    layout_row.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(layout_row)
    elements.append(Spacer(1, 20))

    # ═══════════════════════════════════════════════════
    # SALARY BREAKDOWN — with dark header + full grid
    # ═══════════════════════════════════════════════════
    elements.append(Paragraph("SALARY", section_label_style))
    elements.append(Spacer(1, 10))

    salary_data = [
        # Header row
        [
            Paragraph("Earnings", col_header_style),
            Paragraph("Amount", col_header_right_style),
            Paragraph("Deductions", col_header_style),
            Paragraph("Amount", col_header_right_style),
        ],
        # Basic / Absence
        [
            Paragraph("Basic", cell_style),
            Paragraph(f"Rs. {payroll.basic_salary:,.2f}", cell_amount_style),
            Paragraph("Absence / LOP", cell_style),
            Paragraph(f"Rs. {abs_ded:,.2f}", cell_amount_style),
        ],
        # HRA / Unpaid Leave
        [
            Paragraph("HRA", cell_style),
            Paragraph(f"Rs. {hra:,.2f}", cell_amount_style),
            Paragraph("Unpaid Leave", cell_style),
            Paragraph(f"Rs. {ul_ded:,.2f}", cell_amount_style),
        ],
        # Allowance / Other Deduction
        [
            Paragraph("Allowance", cell_style),
            Paragraph(f"Rs. {payroll.allowance:,.2f}", cell_amount_style),
            Paragraph("Other Deduction", cell_style),
            Paragraph(f"Rs. {other_ded:,.2f}", cell_amount_style),
        ],
        # Overtime / (blank deduction side)
        [
            Paragraph("Overtime", cell_style),
            Paragraph(f"Rs. {ot_amount:,.2f}", cell_amount_style),
            '', '',
        ],
        # Total row
        [
            Paragraph("Total Earnings", cell_bold_style),
            Paragraph(f"Rs. {gross:,.2f}", cell_bold_amount_style),
            Paragraph("Total Deduction", cell_bold_style),
            Paragraph(f"Rs. {total_ded:,.2f}", cell_bold_amount_style),
        ],
    ]

    col_lbl = PAGE_W * 0.28
    col_amt = PAGE_W * 0.22
    salary_table = Table(
        salary_data,
        colWidths=[col_lbl, col_amt, col_lbl, col_amt],
        repeatRows=1,
    )
    salary_table.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),

        # ── Dark header row ──
        ('BACKGROUND',    (0,0), (-1,0), DARK),
        ('TEXTCOLOR',     (0,0), (-1,0), WHITE),
        ('LINEBELOW',     (0,0), (-1,0), 0.5, DARK),

        # ── Full grid on the body ──
        ('GRID',          (0,1), (-1,-1), 0.4, BLACK),

        # ── Total row emphasis ──
        ('BACKGROUND',    (0,-1), (-1,-1), colors.HexColor('#f2f2f2')),
        ('LINEABOVE',     (0,-1), (-1,-1), 0.75, BLACK),
        ('LINEBELOW',     (0,-1), (-1,-1), 0.75, BLACK),

        # ── Vertical divider between Earnings and Deductions ──
        ('LINEBEFORE',    (2,0), (2,-1), 0.75, BLACK),
    ]))
    elements.append(salary_table)
    elements.append(Spacer(1, 4))

    # ─── In words ───
    net_words_text = number_to_words(net) + ' Rupees Only'
    elements.append(Paragraph(
        f"In words: <b>{net_words_text}</b>",
        words_style,
    ))
    elements.append(Spacer(1, 22))

    # ═══════════════════════════════════════════════════
    # NET PAYABLE
    # ═══════════════════════════════════════════════════
    net_block = Table(
        [[
            Paragraph(
                "NET PAYABLE<br/>"
                "<font size='7' face='Helvetica'>After all deductions</font>",
                net_label_style,
            ),
            Paragraph(f"Rs. {net:,.2f}", net_amount_style),
        ]],
        colWidths=[PAGE_W * 0.6, PAGE_W * 0.4],
    )
    net_block.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('TOPPADDING',    (0,0), (-1,-1), 14),
        ('BOTTOMPADDING', (0,0), (-1,-1), 14),
        ('LINEABOVE',     (0,0), (-1,0), 1.5, BLACK),
        ('LINEBELOW',     (0,0), (-1,0), 1.5, BLACK),
    ]))
    elements.append(net_block)

    # ═══════════════════════════════════════════════════
    # FOOTER
    # ═══════════════════════════════════════════════════
    elements.append(Spacer(1, 26))

    local_now = timezone.localtime(timezone.now())
    footer_cells = [
        [
            Paragraph(
                f"<b>EMPLOYEE ID</b><br/>{employee.employee_id if employee else '—'}",
                footer_style,
            ),
            Paragraph(
                f"<b>GENERATED</b><br/>"
                f"{local_now.strftime('%d %b %Y, %I:%M %p')}",
                footer_style,
            ),
            Paragraph(
                f"<b>STATUS</b><br/>{payroll.get_status_display()}",
                footer_style,
            ),
        ],
    ]
    footer_table = Table(footer_cells, colWidths=[PAGE_W / 3] * 3)
    footer_table.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(HRFlowable(
        width="100%", thickness=0.5, color=BLACK,
        spaceBefore=0, spaceAfter=10,
    ))
    elements.append(footer_table)
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(
        "This is a computer-generated payslip and does not require a signature.",
        footer_note_style,
    ))

    # ─── Build ───
    doc.build(elements)
    buffer.seek(0)

    emp_id_safe = (
        employee.employee_id if employee and employee.employee_id
        else f"EMP{employee.id:04d}"
    )
    filename = f"payslip_{emp_id_safe}_{payroll.month:02d}_{payroll.year}.pdf"

    return FileResponse(buffer, as_attachment=True, filename=filename)




@login_required
@hr_admin_required
@payroll_required
@company_required
def payslip_view(request, pk):
    from .utils import get_user_company, number_to_words

    if request.user.is_superuser:
        payroll = get_object_or_404(Payroll, id=pk)
    else:
        payroll = get_object_or_404(
            Payroll, id=pk, company=get_user_company(request)
        )

    net_words = number_to_words(payroll.net_salary) + ' Rupees Only'

    return render(request, 'payroll/payslip.html', {
        'payroll': payroll,
        'net_in_words': net_words,
    })



# ─── Helper: find HR Admins for a company ───
def _get_company_hr_admins(company):
    """Return active HR Admin users belonging to the given company."""
    if not company:
        return User.objects.none()
    return User.objects.filter(
        groups__name='HR Admin',
        profile__company=company,
        is_active=True,
    ).distinct()


# ─── Helper: is this user allowed to review reset requests? ───
def _is_hr_admin(user):
    if not user.is_authenticated:
        return False
    return user.groups.filter(name='HR Admin').exists()


# ─── Helper: get the request, scoped to HR Admin's company ───
def _get_hr_scoped_request(user, request_id):
    """
    Return the PasswordResetRequest if it belongs to the HR Admin's company.
    Raises 404 otherwise (never leaks existence of other companies' data).
    """
    profile = getattr(user, 'profile', None)
    company = getattr(profile, 'company', None)
    return get_object_or_404(
        PasswordResetRequest.objects.select_related(
            'user', 'employee', 'company', 'reviewed_by'
        ),
        id=request_id,
        company=company,
    )


# ─────────────────────────────────────────
# 1. Employee — Submit request
# ─────────────────────────────────────────
@ratelimit(key='ip', rate='5/h', method='POST', block=False)
@require_http_methods(['GET', 'POST'])
def forgot_password(request):
    """
    Always shows the same message regardless of whether the identifier exists.
    Prevents user enumeration.
    """

    # ✅ Rate limit guard
    if request.method == 'POST' and getattr(request, 'limited', False):
        messages.error(request, 'Too many requests. Please try again later.')
        return render(request, 'core/forgot_password.html', {
            'form': ForgotPasswordForm(),
            'submitted': False,
        })

    if request.user.is_authenticated:
        return redirect('dashboard')

    form = ForgotPasswordForm(request.POST or None)
    submitted = False

    if request.method == 'POST' and form.is_valid():
        identifier = form.cleaned_data['identifier']

        # Try by employee_id first, then by username
        employee = (
            EmployeeProfile.objects
            .select_related('user', 'company')
            .filter(employee_id__iexact=identifier)
            .first()
        )
        if not employee:
            employee = (
                EmployeeProfile.objects
                .select_related('user', 'company')
                .filter(user__username__iexact=identifier)
                .first()
            )

        # If found → create request (idempotent)
        if employee and employee.user.is_active:
            already_pending = PasswordResetRequest.objects.filter(
                user=employee.user,
                status=PasswordResetRequest.STATUS_PENDING,
            ).exists()

            if not already_pending:
                with transaction.atomic():
                    reset_req = PasswordResetRequest.objects.create(
                        user=employee.user,
                        employee=employee,
                        company=employee.company,
                        status=PasswordResetRequest.STATUS_PENDING,
                    )

                    # ── Route the notification by applicant's role ──
                    is_owner       = getattr(employee, 'is_company_owner', False)
                    applicant_role = employee.role

                    if is_owner:
                        recipients = list(
                            User.objects.filter(is_superuser=True, is_active=True)
                        )
                    elif applicant_role == 'hr_admin':
                        recipients = [
                            p.user for p in EmployeeProfile.objects.filter(
                                company=employee.company,
                                is_company_owner=True,
                                user__is_active=True,
                            ).exclude(id=employee.id)
                        ]
                    else:
                        recipients = [
                            p.user for p in EmployeeProfile.objects.filter(
                                company=employee.company,
                                role='hr_admin',
                                is_company_owner=False,
                                user__is_active=True,
                            ).exclude(id=employee.id)
                        ]

                    for recipient in recipients:
                        Notification.objects.create(
                            user=recipient,
                            company=employee.company,
                            message=(
                                f"Password Reset Request — "
                                f"{employee.full_name or employee.user.username} "
                                f"({employee.employee_id}) has requested a password reset."
                            ),
                            notification_type='action',
                            related_object_id=reset_req.id,
                            related_object_type='passwordresetrequest',
                        )

        submitted = True

    return render(request, 'core/forgot_password.html', {
        'form': form,
        'submitted': submitted,
    })
    



# ─────────────────────────────────────────
# 2. HR Admin — View request detail
# ─────────────────────────────────────────
@login_required
@company_required
def password_reset_request_detail(request, request_id):
    if not _is_hr_admin(request.user):
        return redirect('dashboard')

    reset_req = _get_hr_scoped_request(request.user, request_id)

    return render(request, 'core/password_reset_request_detail.html', {
        'reset_req': reset_req,
    })


# ─────────────────────────────────────────
# 3. HR Admin — Approve → redirect to Set New Password
# ─────────────────────────────────────────
@login_required
@company_required
@require_http_methods(['POST'])
def password_reset_approve(request, request_id):
    if not _is_hr_admin(request.user):
        return redirect('dashboard')

    reset_req = _get_hr_scoped_request(request.user, request_id)

    if reset_req.status != PasswordResetRequest.STATUS_PENDING:
        messages.warning(request, "This request has already been processed.")
        return redirect('password_reset_request_detail', request_id=reset_req.id)

    # Prevent HR Admin from resetting their own password through this flow
    if reset_req.user_id == request.user.id:
        messages.error(request, "You cannot reset your own password through this workflow.")
        return redirect('password_reset_request_detail', request_id=reset_req.id)

    reset_req.status       = PasswordResetRequest.STATUS_APPROVED
    reset_req.reviewed_by  = request.user
    reset_req.reviewed_at  = timezone.now()
    reset_req.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])

    return redirect('password_reset_set_new', request_id=reset_req.id)


# ─────────────────────────────────────────
# 4. HR Admin — Reject
# ─────────────────────────────────────────
@login_required
@company_required
@require_http_methods(['POST'])
def password_reset_reject(request, request_id):
    if not _is_hr_admin(request.user):
        return redirect('dashboard')

    reset_req = _get_hr_scoped_request(request.user, request_id)

    if reset_req.status != PasswordResetRequest.STATUS_PENDING:
        messages.warning(request, "This request has already been processed.")
        return redirect('password_reset_request_detail', request_id=reset_req.id)

    reset_req.status       = PasswordResetRequest.STATUS_REJECTED
    reset_req.reviewed_by  = request.user
    reset_req.reviewed_at  = timezone.now()
    reset_req.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])

    messages.success(request, "Password reset request rejected.")
    return redirect('admin_leaves')  # or any landing page; 'dashboard' also works


# ─────────────────────────────────────────
# 5. HR Admin — Set new password
# ─────────────────────────────────────────
@login_required
@company_required
def password_reset_set_new(request, request_id):
    if not _is_hr_admin(request.user):
        return redirect('dashboard')

    reset_req = _get_hr_scoped_request(request.user, request_id)

    # Only allowed when request is Approved (or already Completed for viewing)
    if reset_req.status not in (
        PasswordResetRequest.STATUS_APPROVED,
        PasswordResetRequest.STATUS_COMPLETED,
    ):
        messages.warning(request, "This request must be approved before setting a password.")
        return redirect('password_reset_request_detail', request_id=reset_req.id)

    # Already completed → just show success
    if reset_req.status == PasswordResetRequest.STATUS_COMPLETED:
        return render(request, 'core/password_reset_set_new.html', {
            'reset_req': reset_req,
            'completed': True,
        })

    form = SetNewPasswordForm(
        request.POST or None,
        user=reset_req.user,
    )

    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            target_user = reset_req.user
            target_user.set_password(form.cleaned_data['password1'])
            target_user.save(update_fields=['password'])

            reset_req.status       = PasswordResetRequest.STATUS_COMPLETED
            reset_req.completed_at = timezone.now()
            reset_req.save(update_fields=['status', 'completed_at'])

            # Notify the employee (message only — never the password)
            Notification.objects.create(
                user=target_user,
                company=reset_req.company,
                message=(
                    "Your password has been changed by your HR Admin. "
                    "You can now log in using your new password."
                ),
                notification_type='info',
                related_object_id=reset_req.id,
                related_object_type='passwordresetrequest',
            )

        return render(request, 'core/password_reset_set_new.html', {
            'reset_req': reset_req,
            'completed': True,
        })

    return render(request, 'core/password_reset_set_new.html', {
        'reset_req': reset_req,
        'form': form,
        'completed': False,
    })

    

@login_required
def change_password(request):
    """
    Any logged-in user can change their OWN password.
    Requires the current password for security.
    """
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # Keep the user logged in after password change
            update_session_auth_hash(request, user)
            messages.success(request, "Your password has been changed successfully.")
            return redirect('profile')
    else:
        form = PasswordChangeForm(request.user)

    return render(request, 'core/change_password.html', {'form': form})


def _validate_password_fields(user, password1, password2, is_create):
    """Uses the SAME validators as Django's PasswordChangeForm."""
    errors = []

    if is_create:
        if not password1:
            errors.append("Password is required.")
            return errors
        if not password2:
            errors.append("Please confirm the password.")
            return errors
    else:
        if not password1 and not password2:
            return errors
        if not password1:
            errors.append("Please enter the new password.")
            return errors
        if not password2:
            errors.append("Please confirm the new password.")
            return errors

    if password1 != password2:
        errors.append("Passwords do not match.")
        return errors

    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    try:
        validate_password(password1, user=user)
    except ValidationError as exc:
        errors.extend(exc.messages)

    return errors


    # **************texting 
def test_view(request):
    return HttpResponse("Django is working!")