from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.utils import timezone
from datetime import date, timedelta, datetime
from .models import Attendance, LeaveType, Holiday, LeaveRequest, Notification, RegularizationRequest, EmployeeProfile, Shift
from .forms import EmployeeForm
from django.http import HttpResponse, JsonResponse
from calendar import monthrange
from django.db.models import Q
import calendar as cal

# ---------- Helper: Notification Functions ----------
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


# ---------- Login & Logout ----------
def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    return redirect('login')


# ---------- Dashboard ----------

@login_required
def dashboard(request):
    user = request.user
    today = date.today()

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
            # Make it timezone-aware using the current timezone
            shift_start = timezone.make_aware(shift_start)
            check_in = today_attendance.check_in_time
            if check_in > shift_start:
                late_minutes = int((check_in - shift_start).total_seconds() // 60)
                
        

    # ---------- Attendance Calendar ----------
    first_day = date(year, month, 1)
    _, num_days = monthrange(year, month)
    last_day = date(year, month, num_days)

    attendance_dict = {att.date.day: att.status for att in monthly_history}

    leave_requests = LeaveRequest.objects.filter(
        user=user,
        status='Approved',
        start_date__lte=last_day,
        end_date__gte=first_day
    )
    leave_dates = set()
    for req in leave_requests:
        start = max(req.start_date, first_day)
        end = min(req.end_date, last_day)
        for d in range((end - start).days + 1):
            leave_dates.add((start + timedelta(days=d)).day)

    calendar_data = []
    for day in range(1, num_days + 1):
        current_date = date(year, month, day)
        is_weekend = current_date.weekday() >= 5
        if is_weekend:
            status = 'weekend'
        elif day in attendance_dict:
            status = attendance_dict[day]
        elif day in leave_dates:
            status = 'leave'
        else:
            status = 'none'
        calendar_data.append({
            'day': day,
            'date': current_date,
            'status': status,
            'is_weekend': is_weekend,
        })

    first_weekday = first_day.weekday()

    pending_leaves = LeaveRequest.objects.filter(user=user, status='Pending').count()

    # ---------- Leave Balance ----------
    leave_types = LeaveType.objects.filter(is_active=True)
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

    all_today_attendance = None
    all_employees = None
    pending_leave_requests = []

    if user.is_superuser:
        all_today_attendance = Attendance.objects.filter(date=today).select_related('user')
        all_employees = User.objects.all().order_by('username')
        all_employees_attendance = Attendance.objects.filter(
            date__year=admin_year,
            date__month=admin_month
        ).select_related('user').order_by('user__username', 'date')
        pending_leave_requests = LeaveRequest.objects.filter(status='Pending').order_by('-applied_on')[:10]
    else:
        all_employees_attendance = None

    # ---------- Monthly Chart Data ----------
    attendance_chart_labels = []
    attendance_chart_present = []
    attendance_chart_absent = []
    attendance_chart_half = []

    if user.is_superuser:
        year_attendances = Attendance.objects.filter(date__year=today.year)
        for month_num in range(1, 13):
            month_attendances = year_attendances.filter(date__month=month_num)
            month_name = date(today.year, month_num, 1).strftime('%b')
            attendance_chart_labels.append(month_name)
            attendance_chart_present.append(month_attendances.filter(status='Present').count())
            attendance_chart_absent.append(month_attendances.filter(status='Absent').count())
            attendance_chart_half.append(month_attendances.filter(status='Half-Day').count())

    # ---------- Weekly Bar Chart Data (All 7 days, future days = 0) ----------
    # Defaults for non‑admin
    weekly_days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    weekly_day_present = [0, 0, 0, 0, 0, 0, 0]
    weekly_day_absent = [0, 0, 0, 0, 0, 0, 0]
    weekly_day_half = [0, 0, 0, 0, 0, 0, 0]
    weekly_day_onleave = [0, 0, 0, 0, 0, 0, 0]
    start_of_week = today - timedelta(days=today.weekday())
    week_start = start_of_week
    week_end = start_of_week + timedelta(days=6)

    # For admin, calculate real data
    if user.is_superuser:
        total_employees = User.objects.filter(is_superuser=False).count()
        start_of_week = today - timedelta(days=today.weekday())
        weekly_days = []
        weekly_day_present = []
        weekly_day_absent = []
        weekly_day_half = []
        weekly_day_onleave = []

        for i in range(7):
            day = start_of_week + timedelta(days=i)
            if day <= today:
                present = Attendance.objects.filter(
                    date=day,
                    status='Present',
                    user__is_superuser=False
                ).values('user').distinct().count()
                half = Attendance.objects.filter(
                    date=day,
                    status='Half-Day',
                    user__is_superuser=False
                ).values('user').distinct().count()
                on_leave = LeaveRequest.objects.filter(
                    status='Approved',
                    start_date__lte=day,
                    end_date__gte=day,
                    user__is_superuser=False
                ).values('user').distinct().count()
                absent = total_employees - present - on_leave
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
    else:
        # For non-admin, total_employees is still needed for stats
        total_employees = User.objects.filter(is_superuser=False).count()

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
    present_today = Attendance.objects.filter(
        date=today,
        status='Present',
        user__is_superuser=False
    ).values('user').distinct().count()

    absent_today = total_employees - present_today

    if user.is_superuser:
        pending_actions_count = LeaveRequest.objects.filter(status='Pending').count()
    else:
        pending_actions_count = LeaveRequest.objects.filter(user=user, status='Pending').count()

    next_holiday = Holiday.objects.filter(date__gte=today).order_by('date').first()

    # On Leave Today
    on_leave_today = LeaveRequest.objects.filter(
        status='Approved',
        start_date__lte=today,
        end_date__gte=today
    ).values('user').distinct().count()

    # Timer total seconds
    today_total_seconds = 0
    if today_attendance and today_attendance.total_working_time:
        today_total_seconds = int(today_attendance.total_working_time.total_seconds())
     

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
        # Leave balance
        'leave_balance': leave_balance,
        'total_available': total_available,
        'total_used': total_used,
        'total_pending': total_pending,
        # Pending leave requests
        'pending_leave_requests': pending_leave_requests,
        # Chart data
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
        # Stats
        'total_employees': total_employees,
        'present_today': present_today,
        'absent_today': absent_today,
        'pending_actions_count': pending_actions_count,
        'next_holiday': next_holiday,
        'today_total_seconds': today_total_seconds,
        # Calendar
        'calendar_data': calendar_data,
        'first_weekday': first_weekday,
        'month': month,
        'year': year,
        'on_leave_today': on_leave_today,
        'employee_shift': employee_shift,
        'late_minutes': late_minutes
    }
    return render(request, 'dashboard.html', context)
    


# ---------- Attendance ----------
@login_required
def clock_in(request):
    today = date.today()
    attendance = Attendance.objects.filter(user=request.user, date=today).first()

    if attendance and attendance.state == 'checked_in':
        messages.warning(request, 'You are already checked in.')
    else:
        if attendance and attendance.state == 'checked_out':
            attendance.check_in_time = timezone.now()
            attendance.state = 'checked_in'
            attendance.save()
        else:
            attendance = Attendance.objects.create(
                user=request.user,
                check_in_time=timezone.now(),
                state='checked_in',
                total_working_time=timedelta(0)
            )
        messages.success(request, f'Clocked in at {attendance.check_in_time.strftime("%H:%M:%S")}')

    return redirect('dashboard')

@login_required
def clock_out(request):
    today = date.today()
    attendance = Attendance.objects.filter(user=request.user, date=today, state='checked_in').first()

    if not attendance:
        messages.warning(request, 'You are not checked in.')
    else:
        interval = timezone.now() - attendance.check_in_time
        if attendance.total_working_time:
            attendance.total_working_time += interval
        else:
            attendance.total_working_time = interval
        attendance.check_out_time = timezone.now()
        attendance.state = 'checked_out'
        attendance.save()
        messages.success(request, f'Clocked out at {attendance.check_out_time.strftime("%H:%M:%S")}. Total worked today: {attendance.total_working_time}')

    return redirect('dashboard')


# ---------- Helper ----------
def is_admin(user):
    return user.is_superuser


# ---------- Employee Management ----------
@login_required
@user_passes_test(is_admin)
def employee_list(request):
    employees = User.objects.all().order_by('username')
    return render(request, 'employee_list.html', {'employees': employees})

@login_required
@user_passes_test(is_admin)
def employee_create(request):
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            profile = form.save()  # returns the EmployeeProfile object
            # Assign shift if provided
            shift_id = request.POST.get('shift')
            if shift_id:
                profile.shift_id = shift_id
                profile.save()
            messages.success(request, f'Employee {profile.full_name} created successfully!')
            return redirect('employee_list')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = EmployeeForm()

    shifts = Shift.objects.all().order_by('name')
    context = {
        'form': form,
        'action': 'Create',
        'shifts': shifts,
    }
    return render(request, 'employee_form.html', context)

@login_required
@user_passes_test(is_admin)
def employee_edit(request, user_id):
    user = get_object_or_404(User, id=user_id)

    try:
        profile = EmployeeProfile.objects.get(user=user)
    except EmployeeProfile.DoesNotExist:
        profile = EmployeeProfile.objects.create(
            user=user,
            employee_id=f"EMP{user.id:04d}",
            full_name=user.username,
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

        profile.employee_id = request.POST.get('employee_id')
        profile.full_name = request.POST.get('full_name')
        profile.date_of_birth = request.POST.get('date_of_birth') or None
        profile.date_of_joining = request.POST.get('date_of_joining') or None
        profile.designation = request.POST.get('designation', '')
        profile.department = request.POST.get('department', '')
        profile.phone = request.POST.get('phone', '')
        profile.address = request.POST.get('address', '')
        # Update shift if provided
        shift_id = request.POST.get('shift')
        if shift_id:
            profile.shift_id = shift_id
        else:
            profile.shift = None
        profile.save()

        messages.success(request, f'Employee {profile.full_name} updated successfully.')
        return redirect('employee_list')

    shifts = Shift.objects.all().order_by('name')
    context = {
        'user': user,
        'profile': profile,
        'action': 'Edit',
        'shifts': shifts,
    }
    return render(request, 'employee_form.html', context)

@login_required
@user_passes_test(is_admin)
def employee_delete(request, user_id):
    employee = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        if request.user == employee:
            messages.error(request, 'You cannot delete your own account!')
        else:
            employee.delete()
            messages.success(request, 'Employee deleted successfully!')
        return redirect('employee_list')
    return render(request, 'employee_confirm_delete.html', {'employee': employee})

# ---------- Employee Detail ----------
@login_required
@user_passes_test(is_admin)
def employee_detail(request, user_id):
    employee_user = get_object_or_404(User, id=user_id)

    try:
        profile = EmployeeProfile.objects.get(user=employee_user)
    except EmployeeProfile.DoesNotExist:
        profile = EmployeeProfile.objects.create(
            user=employee_user,
            employee_id=f"EMP{employee_user.id:04d}",
            full_name=employee_user.username,
        )
        messages.info(request, f'Profile was missing – created a default profile for {employee_user.username}.')

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

    leave_types = LeaveType.objects.filter(is_active=True)
    leave_balance = []
    for lt in leave_types:
        approved = LeaveRequest.objects.filter(user=employee_user, leave_type=lt, status='Approved')
        used = sum(req.get_duration() for req in approved)
        pending = LeaveRequest.objects.filter(user=employee_user, leave_type=lt, status='Pending')
        pending_days = sum(req.get_duration() for req in pending)
        available = lt.days_allowed - used
        leave_balance.append({
            'leave_type': lt,
            'total': lt.days_allowed,
            'used': used,
            'pending': pending_days,
            'available': available,
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
@user_passes_test(is_admin)
def leave_type_list(request):
    types = LeaveType.objects.all().order_by('name')
    return render(request, 'leave_type_list.html', {'leave_types': types})

@login_required
@user_passes_test(is_admin)
def leave_type_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        days = request.POST.get('days_allowed')
        if name and days:
            LeaveType.objects.create(name=name, days_allowed=days)
            messages.success(request, 'Leave type created.')
            return redirect('leave_type_list')
        else:
            messages.error(request, 'All fields required.')
    return render(request, 'leave_type_form.html', {'action': 'Create'})

@login_required
@user_passes_test(is_admin)
def leave_type_edit(request, pk):
    leave_type = get_object_or_404(LeaveType, id=pk)
    if request.method == 'POST':
        leave_type.name = request.POST.get('name')
        leave_type.days_allowed = request.POST.get('days_allowed')
        leave_type.is_active = 'is_active' in request.POST
        leave_type.save()
        messages.success(request, 'Leave type updated.')
        return redirect('leave_type_list')
    return render(request, 'leave_type_form.html', {'action': 'Edit', 'leave_type': leave_type})

@login_required
@user_passes_test(is_admin)
def leave_type_delete(request, pk):
    leave_type = get_object_or_404(LeaveType, id=pk)
    if request.method == 'POST':
        leave_type.delete()
        messages.success(request, 'Leave type deleted.')
        return redirect('leave_type_list')
    return render(request, 'leave_type_confirm_delete.html', {'leave_type': leave_type})


# ---------- Holidays ----------
@login_required
@user_passes_test(is_admin)
def holiday_list(request):
    holidays = Holiday.objects.all().order_by('date')
    return render(request, 'holiday_list.html', {'holidays': holidays})

@login_required
@user_passes_test(is_admin)
def holiday_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        date_str = request.POST.get('date')
        if name and date_str:
            Holiday.objects.create(name=name, date=date_str)
            messages.success(request, 'Holiday added.')
            return redirect('holiday_list')
        else:
            messages.error(request, 'All fields required.')
    return render(request, 'holiday_form.html', {'action': 'Add'})

@login_required
@user_passes_test(is_admin)
def holiday_edit(request, pk):
    holiday = get_object_or_404(Holiday, id=pk)
    if request.method == 'POST':
        holiday.name = request.POST.get('name')
        holiday.date = request.POST.get('date')
        holiday.save()
        messages.success(request, 'Holiday updated.')
        return redirect('holiday_list')
    return render(request, 'holiday_form.html', {'action': 'Edit', 'holiday': holiday})

@login_required
@user_passes_test(is_admin)
def holiday_delete(request, pk):
    holiday = get_object_or_404(Holiday, id=pk)
    if request.method == 'POST':
        holiday.delete()
        messages.success(request, 'Holiday deleted.')
        return redirect('holiday_list')
    return render(request, 'holiday_confirm_delete.html', {'holiday': holiday})


# ---------- Employee Leave Dashboard ----------
@login_required
def employee_leaves(request):
    user = request.user
    tab = request.GET.get('tab', 'status')

    leave_types = LeaveType.objects.filter(is_active=True)
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

    holidays = Holiday.objects.all().order_by('date')

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

        leave_request = LeaveRequest.objects.create(
            user=request.user,
            leave_type=leave_type,
            is_half_day=is_half_day,
            half_day_session=half_day_session if is_half_day else '',
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            attachment=attachment,
            status='Pending'
        )
        messages.success(request, 'Leave request submitted successfully.')

        notify_admins(
            f"{request.user.username} has applied for {leave_type.name} leave from {start_date} to {end_date}.",
            notification_type='action',
            related_object=leave_request
        )
        return redirect('employee_leaves')

    leave_types = LeaveType.objects.filter(is_active=True)
    return render(request, 'leave_apply.html', {'leave_types': leave_types})


# ---------- Admin Leave Approvals ----------
@login_required
@user_passes_test(is_admin)
def admin_leaves(request):
    pending = LeaveRequest.objects.filter(status='Pending').order_by('-applied_on')
    approved = LeaveRequest.objects.filter(status='Approved').order_by('-applied_on')
    rejected = LeaveRequest.objects.filter(status='Rejected').order_by('-applied_on')
    context = {
        'pending_leaves': pending,
        'approved_leaves': approved,
        'rejected_leaves': rejected,
    }
    return render(request, 'admin_leaves.html', context)

@login_required
@user_passes_test(is_admin)
def leave_approve(request, leave_id):
    leave = get_object_or_404(LeaveRequest, id=leave_id)
    if request.method == 'POST':
        comment = request.POST.get('admin_comment', '')
        leave.status = 'Approved'
        leave.admin_comment = comment
        leave.save()
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
@user_passes_test(is_admin)
def leave_reject(request, leave_id):
    leave = get_object_or_404(LeaveRequest, id=leave_id)
    if request.method == 'POST':
        reason = request.POST.get('rejection_reason')
        if not reason:
            messages.error(request, 'Please provide a rejection reason.')
            return redirect('leave_reject', leave_id=leave.id)
        leave.status = 'Rejected'
        leave.rejection_reason = reason
        leave.save()
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
@user_passes_test(is_admin)
def team_attendance(request):
    today = date.today()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    if month < 1 or month > 12: month = today.month
    if year < 2000 or year > 2100: year = today.year
    selected_date = date(year, month, 1)
    employees = User.objects.filter(is_superuser=False).order_by('username')
    
    attendances = Attendance.objects.filter(
        date__year=year,
        date__month=month
    ).select_related('user')
    
    employee_data = []
    for emp in employees:
        emp_records = [att for att in attendances if att.user == emp]
        total_days = len(emp_records)
        present = len([r for r in emp_records if r.status == 'Present'])
        absent = len([r for r in emp_records if r.status == 'Absent'])
        half_day = len([r for r in emp_records if r.status == 'Half-Day'])
        percentage = int((present / total_days) * 100) if total_days > 0 else 0
        
        # Get shift information
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
    
    prev_month = month-1 if month>1 else 12
    prev_year = year if month>1 else year-1
    next_month = month+1 if month<12 else 1
    next_year = year if month<12 else year+1
    next_disabled = (year==today.year and month==today.month)
    
    context = {
        'employee_data': employee_data,
        'selected_month_name': selected_date.strftime('%B %Y'),
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


# ---------- Attendance Report ----------
@login_required
@user_passes_test(is_admin)
def attendance_report(request):
    today = date.today()
    employees = User.objects.filter(is_superuser=False).order_by('username')
    
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    if month < 1 or month > 12: month = today.month
    if year < 2000 or year > 2100: year = today.year
    
    # --- Determine end date for current month ---
    first_day = date(year, month, 1)
    _, last_day_num = monthrange(year, month)
    last_day_of_month = date(year, month, last_day_num)
    
    if year == today.year and month == today.month:
        end_date = today  # Only up to today for current month
    else:
        end_date = last_day_of_month  # Full month for past months
    
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
    
    # --- Get attendances (limited to end_date) ---
    attendances = Attendance.objects.filter(
        date__year=year,
        date__month=month,
        date__lte=end_date   # 👈 KEY FIX
    ).select_related('user')
    
    # --- Get leaves (limited to end_date) ---
    all_leaves = LeaveRequest.objects.filter(
        status='Approved',
        start_date__lte=end_date,
        end_date__gte=first_day
    ).select_related('user')
    
    all_shifts = Shift.objects.all().order_by('name')
    distinct_departments = EmployeeProfile.objects.values_list('department', flat=True).distinct().order_by('department')
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
                
                # --- OVERTIME CALCULATION (FIXED) ---
                # Only if check-out is AFTER shift end
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
                # ----------------------------------
            
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
@user_passes_test(is_admin)
def employee_attendance_detail(request, user_id):

    # If search parameter is provided, redirect to that employee
    search_query = request.GET.get('search')
    if search_query:
        try:
            # Try to find employee by username or full name
            employee = User.objects.filter(
                is_superuser=False
            ).filter(
                Q(username__icontains=search_query) | 
                Q(profile__full_name__icontains=search_query)
            ).first()
            if employee:
                return redirect('employee_attendance_detail', user_id=employee.id)
            else:
                messages.warning(request, 'Employee not found.')
        except:
            pass
    
    employee = get_object_or_404(User, id=user_id)
    profile = get_object_or_404(EmployeeProfile, user=employee)

    employee = get_object_or_404(User, id=user_id)
    profile = get_object_or_404(EmployeeProfile, user=employee)
    
    today = date.today()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    if month < 1 or month > 12: month = today.month
    if year < 2000 or year > 2100: year = today.year
    
    first_day = date(year, month, 1)
    _, last_day_num = monthrange(year, month)
    last_day = date(year, month, last_day_num)
    
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
    
    # Calculate stats
    present = attendances.filter(status='Present').count()
    absent = attendances.filter(status='Absent').count()
    half_day = attendances.filter(status='Half-Day').count()
    
    # Leave days
    leave_days = 0
    for leave in leaves:
        start = max(leave.start_date, first_day)
        end = min(leave.end_date, last_day)
        leave_days += (end - start).days + 1
    
    # Shift
    shift = profile.shift if profile else None
    
    # Calculate Late, Early Out, OT
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
        
        # Check if on leave
        if any(start <= att.date <= end for l in leaves for start, end in [(max(l.start_date, first_day), min(l.end_date, last_day))]):
            status_label = 'On Leave'
        
        # Late/Early/OT calculation
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
        
        # Calculate hours
        hours_str = '--'
        if att.check_in_time and att.check_out_time:
            diff = att.check_out_time - att.check_in_time
            h = diff.seconds // 3600
            m = (diff.seconds % 3600) // 60
            hours_str = f"{h}h {m}m"
        
        daily_records.append({
            'date': att.date,
            'shift': shift.name if shift else '—',
            'in_time': att.check_in_time.strftime('%I:%M %p') if att.check_in_time else '--:--',
            'out_time': att.check_out_time.strftime('%I:%M %p') if att.check_out_time else '--:--',
            'hours': hours_str,
            'status': status_label,
        })
    
    working_days = present + half_day + leave_days
    rate = round((present / working_days) * 100, 1) if working_days > 0 else 0
    
    # Format overtime
    ot_hours = total_overtime_minutes // 60
    ot_minutes = total_overtime_minutes % 60
    ot_formatted = f"{ot_hours}h {ot_minutes}m" if total_overtime_minutes > 0 else "—"
    
    # Month navigation
    prev_month = month-1 if month>1 else 12
    prev_year = year if month>1 else year-1
    next_month = month+1 if month<12 else 1
    next_year = year if month<12 else year+1
    next_disabled = (year == today.year and month == today.month)

    # Get all employees for dropdown
    all_employees = User.objects.filter(is_superuser=False).select_related('profile').order_by('username')


    # Get all employees for search suggestions
    all_employees = User.objects.filter(is_superuser=False).select_related('profile').order_by('username')

    
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

    from calendar import monthrange
    _, last_day = monthrange(year, month)
    first_date = date(year, month, 1)
    last_date = date(year, month, last_day)

    attendances = Attendance.objects.filter(
        user=user,
        date__gte=first_date,
        date__lte=last_date
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
            status = 'Present' if att.check_in_time and att.check_out_time else 'Incomplete'
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
            status = 'Absent'
            check_in = None
            check_out = None
            work_seconds = 0
            overtime_seconds = 0

        check_in_display = check_in.strftime('%H:%M') if check_in else '--:--'
        check_out_display = check_out.strftime('%H:%M') if check_out else '--:--'
        work_hours = f"{int(work_seconds // 3600):02d}:{int((work_seconds % 3600) // 60):02d}" if work_seconds else '--:--'
        overtime_display = f"{int(overtime_seconds // 3600):02d}:{int((overtime_seconds % 3600) // 60):02d}" if overtime_seconds else '--:--'
        can_regularize = (status in ['Absent', 'Incomplete'])

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

    avg_working_hours = round(total_working_hours / complete_count, 2) if complete_count > 0 else 0
    avg_in_time = minutes_to_time(total_in_minutes / complete_count) if complete_count > 0 else "--:--"
    avg_out_time = minutes_to_time(total_out_minutes / complete_count) if complete_count > 0 else "--:--"

    pending_regularization = RegularizationRequest.objects.filter(
        user=user, status='Pending'
    ).exists()

    context = {
        'all_dates': all_dates,
        'avg_working_hours': avg_working_hours,
        'avg_in_time': avg_in_time,
        'avg_out_time': avg_out_time,
        'total_days': last_day,
        'completed_days': complete_count,
        'month': month,
        'year': year,
        'month_name': first_date.strftime('%B %Y'),
        'pending_regularization': pending_regularization,
        'today': today,
    }
    return render(request, 'attendance/attendance_status.html', context)


# ---------- Regularization ----------
@login_required
def regularize_request(request):
    if request.method == 'POST':
        date_str = request.POST.get('date')
        check_in = request.POST.get('check_in')
        check_out = request.POST.get('check_out')
        reason = request.POST.get('reason')

        if date_str and reason:
            existing = RegularizationRequest.objects.filter(
                user=request.user,
                date=date_str,
                status__in=['Pending', 'Approved']
            ).exists()
            if existing:
                messages.error(request, 'You already have a pending or approved regularization for this date.')
                return redirect('regularize_request')

            if Attendance.objects.filter(user=request.user, date=date_str).exists():
                messages.error(request, 'Attendance already exists for this date.')
                return redirect('regularize_request')

            RegularizationRequest.objects.create(
                user=request.user,
                date=date_str,
                check_in_time=check_in if check_in else None,
                check_out_time=check_out if check_out else None,
                reason=reason,
                status='Pending'
            )
            messages.success(request, 'Regularization request submitted successfully.')
            return redirect('regularize_request_list')
        else:
            messages.error(request, 'Please fill in all required fields.')

    return render(request, 'attendance/regularize_request.html')


@login_required
def regularize_request_list(request):
    user = request.user
    if user.is_superuser:
        requests = RegularizationRequest.objects.all().order_by('-requested_at')
    else:
        requests = RegularizationRequest.objects.filter(user=user).order_by('-requested_at')
    return render(request, 'attendance/regularize_request_list.html', {'requests': requests})


@login_required
@user_passes_test(is_admin)
def regularize_approve(request, req_id):
    reg_req = get_object_or_404(RegularizationRequest, id=req_id)
    if request.method == 'POST':
        comment = request.POST.get('admin_comment', '')
        reg_req.status = 'Approved'
        reg_req.admin_comment = comment
        reg_req.save()

        if reg_req.check_in_time:
            from datetime import datetime
            check_in_dt = datetime.combine(reg_req.date, reg_req.check_in_time)
            check_out_dt = datetime.combine(reg_req.date, reg_req.check_out_time) if reg_req.check_out_time else None
            Attendance.objects.create(
                user=reg_req.user,
                date=reg_req.date,
                check_in_time=check_in_dt,
                check_out_time=check_out_dt,
                status='Present'
            )
        messages.success(request, f'Regularization approved for {reg_req.user.username}.')
        return redirect('regularize_request_list')
    return render(request, 'attendance/regularize_approve.html', {'reg_req': reg_req})


@login_required
@user_passes_test(is_admin)
def regularize_reject(request, req_id):
    reg_req = get_object_or_404(RegularizationRequest, id=req_id)
    if request.method == 'POST':
        reason = request.POST.get('rejection_reason')
        if not reason:
            messages.error(request, 'Please provide a rejection reason.')
            return redirect('regularize_reject', req_id=reg_req.id)
        reg_req.status = 'Rejected'
        reg_req.admin_comment = reason
        reg_req.save()
        messages.success(request, f'Regularization rejected for {reg_req.user.username}.')
        return redirect('regularize_request_list')
    return render(request, 'attendance/regularize_reject.html', {'reg_req': reg_req})


# ---------- Notification List ----------
@login_required
def notification_list(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    notifications.update(is_read=True)   # mark all as read when viewing the list
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
        user.username = request.POST.get('username')
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
        profile.save()
        
        messages.success(request, 'Profile updated successfully.')
        return redirect('profile')
    
    context = {
        'user': user,
        'profile': profile,
    }
    return render(request, 'profile.html', context)


# ---------- Attendance Overview Data ----------

def attendance_overview_data(request):
    """Return JSON data for attendance overview chart (period: week, month, last_month)."""
    period = request.GET.get('period', 'week')
    today = date.today()

    if period == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
        date_range = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    elif period == 'month':
        start_date = date(today.year, today.month, 1)
        end_date = today
        date_range = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    elif period == 'last_month':
        last_month = today.replace(day=1) - timedelta(days=1)
        start_date = date(last_month.year, last_month.month, 1)
        end_date = date(last_month.year, last_month.month, last_month.day)
        date_range = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    else:
        return JsonResponse({'error': 'Invalid period'}, status=400)

    total_employees = User.objects.filter(is_superuser=False).count()
    if total_employees == 0:
        return JsonResponse({'labels': [], 'present': [], 'on_leave': [], 'absent': [], 'total_employees': 0})

    labels = []
    present_pct = []
    on_leave_pct = []
    absent_pct = []

    for d in date_range:
        # Present employees
        present = Attendance.objects.filter(
            date=d,
            status='Present',
            user__is_superuser=False
        ).values('user').distinct().count()

        # On Leave employees (approved leave covering this day)
        on_leave = LeaveRequest.objects.filter(
            status='Approved',
            start_date__lte=d,
            end_date__gte=d,
            user__is_superuser=False
        ).values('user').distinct().count()

        # Absent = total - present - on_leave (on_leave employees are not present)
        absent = total_employees - present - on_leave

        present_pct_val = round((present / total_employees) * 100, 1) if total_employees > 0 else 0
        on_leave_pct_val = round((on_leave / total_employees) * 100, 1) if total_employees > 0 else 0
        absent_pct_val = 100 - present_pct_val - on_leave_pct_val

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
@user_passes_test(is_admin)
def setup(request):
    shifts = Shift.objects.all().order_by('start_time')
    context = {
        'shifts': shifts,
    }
    return render(request, 'setup.html', context)


# ---------- Shift Management (Admin only) ----------
# ---------- Shift Management (Admin only) ----------

@login_required
@user_passes_test(is_admin)
def shift_list(request):
    shifts = Shift.objects.all().order_by('start_time')
    return render(request, 'shift_list.html', {'shifts': shifts})

@login_required
@user_passes_test(is_admin)
def shift_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')
        break_start = request.POST.get('break_start') or None
        break_end = request.POST.get('break_end') or None
        grace_period = int(request.POST.get('grace_period', 0))
        min_working_hours = int(request.POST.get('min_working_hours', 480))
        overtime_allowed = request.POST.get('overtime_allowed') == 'on'
        overtime_limit = float(request.POST.get('overtime_limit', 2))
        mon = request.POST.get('mon') == 'on'
        tue = request.POST.get('tue') == 'on'
        wed = request.POST.get('wed') == 'on'
        thu = request.POST.get('thu') == 'on'
        fri = request.POST.get('fri') == 'on'
        sat = request.POST.get('sat') == 'on'
        sun = request.POST.get('sun') == 'on'

        Shift.objects.create(
            name=name,
            start_time=start_time,
            end_time=end_time,
            break_start=break_start,
            break_end=break_end,
            grace_period=grace_period,
            min_working_hours=min_working_hours,
            overtime_allowed=overtime_allowed,
            overtime_limit=overtime_limit,
            mon=mon,
            tue=tue,
            wed=wed,
            thu=thu,
            fri=fri,
            sat=sat,
            sun=sun
        )
        messages.success(request, 'Shift created successfully.')
        return redirect('shift_list')
    return render(request, 'shift_form.html', {'action': 'Create'})

@login_required
@user_passes_test(is_admin)
def shift_edit(request, pk):
    shift = get_object_or_404(Shift, id=pk)
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
@user_passes_test(is_admin)
def shift_delete(request, pk):
    shift = get_object_or_404(Shift, id=pk)
    if request.method == 'POST':
        shift.delete()
        messages.success(request, 'Shift deleted successfully.')
        return redirect('shift_list')
    return render(request, 'shift_confirm_delete.html', {'shift': shift})

# ---------- Bulk Shift Assignment (Admin only) ----------

# ---------- Bulk Shift Assignment (Admin only) ----------
@login_required
@user_passes_test(is_admin)
def assign_shift(request):
    if request.method == 'POST':
        shift_id = request.POST.get('shift')
        employee_ids = request.POST.getlist('employees')
        effective_from = request.POST.get('effective_from')

        if not shift_id or not employee_ids:
            messages.error(request, 'Please select at least one employee and a shift.')
            return redirect('assign_shift')

        shift = get_object_or_404(Shift, id=shift_id)

        # Update employees with shift and effective date
        updated = EmployeeProfile.objects.filter(user_id__in=employee_ids).update(
            shift=shift,
            shift_effective_from=effective_from if effective_from else None
        )
        messages.success(request, f'Shift "{shift.name}" assigned to {updated} employee(s).')
        return redirect('assign_shift')

    # GET – show the form with filters
    employees = User.objects.filter(is_superuser=False).select_related('profile').order_by('username')
    shifts = Shift.objects.all().order_by('name')

    # Get filter parameters
    department_filter = request.GET.get('department', '')
    designation_filter = request.GET.get('designation', '')
    location_filter = request.GET.get('location', '')
    team_filter = request.GET.get('team', '')

    # Filter employees
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
    for user in filtered_employees:
        profile = getattr(user, 'profile', None)
        employee_list.append({
            'id': user.id,
            'username': user.username,
            'full_name': profile.full_name if profile else user.username,
            'shift_name': profile.shift.name if profile and profile.shift else 'None',
            'department': profile.department if profile else '',
            'designation': profile.designation if profile else '',
            'location': getattr(profile, 'location', ''),
            'team': getattr(profile, 'team', ''),
        })

    # Get distinct departments, designations for filters
    distinct_departments = EmployeeProfile.objects.values_list('department', flat=True).distinct().order_by('department')
    distinct_designations = EmployeeProfile.objects.values_list('designation', flat=True).distinct().order_by('designation')

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
@user_passes_test(is_admin)
def employee_search_api(request):
    query = request.GET.get('q', '')
    if len(query) < 1:
        return JsonResponse([], safe=False)
    
    employees = User.objects.filter(
        is_superuser=False
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

        

# ---------- Test View ----------
def test_view(request):
    return HttpResponse("Django is working!")