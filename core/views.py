from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.utils import timezone
from datetime import date
from .models import Attendance

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

# ---------- Dashboard & Attendance ----------

@login_required
def dashboard(request):
    user = request.user
    today = date.today()
    
    today_attendance = Attendance.objects.filter(user=user, date=today).first()
    monthly_history = Attendance.objects.filter(
        user=user,
        date__year=today.year,
        date__month=today.month
    ).order_by('-date')
    
    context = {
        'user': user,
        'today_attendance': today_attendance,
        'monthly_history': monthly_history,
        'today': today,
    }
    return render(request, 'dashboard.html', context)

@login_required
def clock_in(request):
    today = date.today()
    existing = Attendance.objects.filter(user=request.user, date=today).first()
    
    if existing:
        messages.warning(request, 'You have already clocked in today!')
    else:
        attendance = Attendance.objects.create(
            user=request.user,
            check_in_time=timezone.now()
        )
        messages.success(request, f'Clocked in at {attendance.check_in_time.strftime("%H:%M:%S")}')
    
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

# ---------- Employee Management (Admin only) ----------

def is_admin(user):
    return user.is_superuser

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

# ---------- Attendance Report (Admin only) ----------

@login_required
@user_passes_test(is_admin)
def attendance_report(request):
    today = date.today()
    employees = User.objects.all().order_by('username')
    
    # Get all attendance records for current month
    attendances = Attendance.objects.filter(
        date__year=today.year,
        date__month=today.month
    ).select_related('user')
    
    # Build a list of employee data with their records
    employee_data = []
    for emp in employees:
        emp_records = [att for att in attendances if att.user == emp]
        employee_data.append({
            'employee': emp,
            'records': emp_records,
            'total_days': len(emp_records),
            'present': len([r for r in emp_records if r.status == 'Present']),
            'absent': len([r for r in emp_records if r.status == 'Absent']),
            'half_day': len([r for r in emp_records if r.status == 'Half-Day']),
        })
    
    context = {
        'employee_data': employee_data,
        'today': today,
        'month_name': today.strftime('%B %Y'),
    }
    return render(request, 'attendance_report.html', context)