from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.utils import timezone
from datetime import date, timedelta
from .models import Attendance, LeaveType, Holiday, LeaveRequest, Notification, RegularizationRequest, EmployeeProfile
from django.http import HttpResponse
from django.db.models import Sum

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

    # ---------- Handle GET parameters safely ----------
    month_str = request.GET.get('month', '')
    year_str = request.GET.get('year', '')
    admin_month_str = request.GET.get('admin_month', '')
    admin_year_str = request.GET.get('admin_year', '')

    month = int(month_str) if month_str and month_str.isdigit() else today.month
    year = int(year_str) if year_str and year_str.isdigit() else today.year
    admin_month = int(admin_month_str) if admin_month_str and admin_month_str.isdigit() else today.month
    admin_year = int(admin_year_str) if admin_year_str and admin_year_str.isdigit() else today.year

    # Validate ranges
    if month < 1 or month > 12: month = today.month
    if year < 2000 or year > 2100: year = today.year
    if admin_month < 1 or admin_month > 12: admin_month = today.month
    if admin_year < 2000 or admin_year > 2100: admin_year = today.year

    selected_date = date(year, month, 1)

    # ---- Attendance for current user ----
    today_attendance = Attendance.objects.filter(user=user, date=today).first()
    monthly_history = Attendance.objects.filter(
        user=user,
        date__year=year,
        date__month=month
    ).order_by('-date')

    pending_leaves = LeaveRequest.objects.filter(user=user, status='Pending').count()

    # ---- Admin: employee selector (optional) ----
    selected_employee = user
    employee_id = request.GET.get('employee_id')
    if user.is_superuser and employee_id:
        try:
            selected_employee = User.objects.get(id=employee_id)
        except User.DoesNotExist:
            pass

    # ---- Admin: all employees attendance & stats ----
    all_today_attendance = None
    all_employees = None

    # Calculate for ALL users (Admins and Employees)
    leave_type_summaries = LeaveType.objects.all().order_by('name') # Leave this empty if you replaced it, but don't delete the line
    upcoming_holidays = Holiday.objects.filter(date__gte=today).order_by('date')[:5]
    total_leave_balance = LeaveType.objects.aggregate(total=Sum('days_allowed'))['total'] or 0

    if user.is_superuser:
        all_today_attendance = Attendance.objects.filter(date=today).select_related('user')
        all_employees = User.objects.all().order_by('username')

        # NEW: Calculate stats for the graph
        total_employees = User.objects.filter(is_active=True, is_staff=False).count()
        present_count = Attendance.objects.filter(date=today, status='Present').count()
        absent_count = max(0, total_employees - present_count)
        half_day_count = Attendance.objects.filter(date=today, status='Half-Day').count()
        late_count = Attendance.objects.filter(date=today, status='Late').count()

        # NEW: Pending leave requests for the admin dashboard
        admin_pending_leaves = LeaveRequest.objects.filter(status='Pending').select_related('user', 'leave_type').order_by('-applied_on')[:5]

        all_employees_attendance = Attendance.objects.filter(
            date__year=admin_year,
            date__month=admin_month
        ).select_related('user').order_by('user__username', 'date')
    else:
        all_employees_attendance = None
        total_employees = 0
        present_count = 0
        absent_count = 0
        half_day_count = 0
        late_count = 0
        admin_pending_leaves = []

    # ---- Navigation for personal month ----
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    next_disabled = (year == today.year and month == today.month)

    # ---- Navigation for admin month ----
    admin_prev_month = admin_month - 1 if admin_month > 1 else 12
    admin_prev_year = admin_year if admin_month > 1 else admin_year - 1
    admin_next_month = admin_month + 1 if admin_month < 12 else 1
    admin_next_year = admin_year if admin_month < 12 else admin_year + 1
    admin_next_disabled = (admin_year == today.year and admin_month == today.month)

    # ---- Build base URL parameters ----
    base_params = f"month={month}&year={year}"
    if employee_id:
        base_params += f"&employee_id={employee_id}"

    admin_base_params = f"admin_month={admin_month}&admin_year={admin_year}"

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
        'selected_month': month,
        'selected_year': year,
        'total_employees': total_employees,
        'present_count': present_count,
        'absent_count': absent_count,
        'half_day_count': half_day_count,
        'late_count': late_count,
        'admin_pending_leaves': admin_pending_leaves,
        'upcoming_holidays': upcoming_holidays,
        'total_leave_balance': total_leave_balance,
    }
    return render(request, 'dashboard.html', context)
    


# ---------- Attendance ----------
@login_required
def clock_in(request):
    today = date.today()
    existing = Attendance.objects.filter(user=request.user, date=today).first()
    if existing:
        messages.warning(request, 'You have already clocked in today!')
    else:
        att = Attendance.objects.create(user=request.user, check_in_time=timezone.now())
        messages.success(request, f'Clocked in at {att.check_in_time.strftime("%H:%M:%S")}')
    return redirect('dashboard')

@login_required
def clock_out(request):
    today = date.today()
    attendance = Attendance.objects.filter(user=request.user, date=today).first()
    if not attendance:
        messages.warning(request, 'You have not clocked in today!')
    elif attendance.check_out_time:
        messages.warning(request, 'You have already clocked out today!')
    else:
        attendance.check_out_time = timezone.now()
        attendance.save()
        messages.success(request, f'Clocked out at {attendance.check_out_time.strftime("%H:%M:%S")}')
    return redirect('dashboard')


# ---------- Helper: Check if user is admin ----------
def is_admin(user):
    return user.is_staff or user.is_superuser


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
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Employee created successfully!')
            return redirect('employee_list')
    else:
        form = UserCreationForm()
    return render(request, 'employee_form.html', {'form': form})

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


# ---------- Leave Types (Admin) ----------
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


# ---------- Holidays (Admin) ----------
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


# ---------- Team Attendance (Admin) ----------
@login_required
@user_passes_test(is_admin)
def team_attendance(request):
    today = date.today()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    if month < 1 or month > 12: month = today.month
    if year < 2000 or year > 2100: year = today.year
    selected_date = date(year, month, 1)
    employees = User.objects.all().order_by('username')
    attendances = Attendance.objects.filter(
        date__year=year, date__month=month
    ).select_related('user')
    employee_data = []
    for emp in employees:
        emp_records = [att for att in attendances if att.user == emp]
        total_days = len(emp_records)
        present = len([r for r in emp_records if r.status == 'Present'])
        absent = len([r for r in emp_records if r.status == 'Absent'])
        half_day = len([r for r in emp_records if r.status == 'Half-Day'])
        percentage = int((present / total_days) * 100) if total_days > 0 else 0
        employee_data.append({
            'employee': emp,
            'records': emp_records,
            'total_days': total_days,
            'present': present,
            'absent': absent,
            'half_day': half_day,
            'percentage': percentage,
        })
    prev_month = month-1 if month>1 else 12
    prev_year = year if month>1 else year-1
    next_month = month+1 if month<12 else 1
    next_year = year if month<12 else year+1
    next_disabled = (year==today.year and month==today.month)
    context = {
        'employee_data': employee_data,
        'selected_month_name': selected_date.strftime('%B %Y'),
        'month': month, 'year': year,
        'prev_month': prev_month, 'prev_year': prev_year,
        'next_month': next_month, 'next_year': next_year,
        'next_disabled': next_disabled,
        'total_employees': employees.count(),
    }
    return render(request, 'team_attendance.html', context)


# ---------- Attendance Report (Admin) ----------
@login_required
@user_passes_test(is_admin)
def attendance_report(request):
    today = date.today()
    employees = User.objects.all().order_by('username')
    attendances = Attendance.objects.filter(
        date__year=today.year, date__month=today.month
    ).select_related('user')
    employee_data = []
    for emp in employees:
        emp_records = [att for att in attendances if att.user == emp]
        total_days = len(emp_records)
        present = len([r for r in emp_records if r.status == 'Present'])
        absent = len([r for r in emp_records if r.status == 'Absent'])
        half_day = len([r for r in emp_records if r.status == 'Half-Day'])
        percentage = int((present / total_days) * 100) if total_days > 0 else 0
        employee_data.append({
            'employee': emp,
            'records': emp_records,
            'total_days': total_days,
            'present': present,
            'absent': absent,
            'half_day': half_day,
            'percentage': percentage,
        })
    context = {
        'employee_data': employee_data,
        'today': today,
        'month_name': today.strftime('%B %Y'),
    }
    return render(request, 'attendance_report.html', context)


# ---------- Attendance Module (Dedicated Page) ----------
# ---------- Regularization Helpers ----------
def minutes_to_time(minutes):
    """Convert minutes to HH:MM format"""
    if minutes == 0 or minutes is None:
        return "--:--"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours:02d}:{mins:02d}"


# ---------- Attendance Module (Dedicated Page) ----------
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
        
        # Create attendance record
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

# ---------- Notification List (Dedicated Page) ----------
@login_required
def notification_list(request):
    """View all notifications for the logged-in user."""
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    # Mark all as read when viewing the full list
    notifications.update(is_read=True)
    context = {
        'notifications': notifications,
    }
    return render(request, 'notifications.html', context)


# ---------- Setup Dashboard (Admin Only) ----------
@user_passes_test(is_admin)
def setup_dashboard(request):
    return render(request, 'setup_dashboard.html')

# Manage Leave Types (Add + List)
@user_passes_test(is_admin)
def manage_leave_types(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        days = request.POST.get('days')
        if name and days:
            LeaveType.objects.create(name=name, days_allowed=days)
            messages.success(request, "Leave Type Added!")
        return redirect('manage_leave_types')
    
    leave_types = LeaveType.objects.all()
    return render(request, 'manage_leave_types.html', {'leave_types': leave_types})

# Manage Holidays (Add + List)
@user_passes_test(is_admin)
def manage_holidays(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        date = request.POST.get('date')
        if name and date:
            Holiday.objects.create(name=name, date=date)
            messages.success(request, "Holiday Added!")
        return redirect('manage_holidays')
        
    holidays = Holiday.objects.all().order_by('date')
    return render(request, 'manage_holidays.html', {'holidays': holidays})

# Employee Management (List Users)
@user_passes_test(is_admin)
def manage_employees(request):
    employees = EmployeeProfile.objects.select_related('user').all()
    return render(request, 'manage_employees.html', {'employees': employees})


@user_passes_test(is_admin)
def delete_leave_type(request, pk):
    LeaveType.objects.get(id=pk).delete()
    messages.success(request, "Leave Type Deleted!")
    return redirect('manage_leave_types')

@user_passes_test(is_admin)
def delete_holiday(request, pk):
    Holiday.objects.get(id=pk).delete()
    messages.success(request, "Holiday Deleted!")
    return redirect('manage_holidays')

@user_passes_test(is_admin)
def delete_employee(request, pk):
    EmployeeProfile.objects.get(id=pk).delete()
    messages.success(request, "Employee Deleted!")
    return redirect('manage_employees')


# ---------- Test View ----------
def test_view(request):
    return HttpResponse("Django is working!")