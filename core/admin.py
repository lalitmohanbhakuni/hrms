from django.contrib import admin
from .models import Attendance, LeaveType, Holiday, LeaveRequest, Notification

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'check_in_time', 'check_out_time', 'status']
    list_filter = ['status', 'date']
    search_fields = ['user__username']

@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'days_allowed', 'is_active']
    list_filter = ['is_active']

@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ['name', 'date', 'day']
    ordering = ['date']

@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'leave_type', 'start_date', 'end_date', 'status', 'applied_on']
    list_filter = ['status', 'leave_type']
    search_fields = ['user__username', 'reason']

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'is_read', 'created_at']
    list_filter = ['is_read']