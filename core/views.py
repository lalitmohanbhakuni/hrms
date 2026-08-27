from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import date
from .models import Attendance

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