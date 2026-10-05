from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from .models import Attendance, LeaveType, Holiday, LeaveRequest, Notification, RegularizationRequest, EmployeeProfile
from .models import Shift
from .models import OfficeLocation
from .models import Company, EmployeeSalary, Payroll

from .models import (
    KioskDevice, FaceCredential, FaceRegistrationConsent,
    KioskAttendanceLog, KioskSession,
)



# Inline profile in User admin
class EmployeeProfileInline(admin.StackedInline):
    model = EmployeeProfile
    can_delete = False
    verbose_name_plural = 'Employee Profile'

class CustomUserAdmin(UserAdmin):
    inlines = (EmployeeProfileInline,)

admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)

# Register other models
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

@admin.register(RegularizationRequest)
class RegularizationRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'status', 'requested_at']
    list_filter = ['status']
    search_fields = ['user__username', 'reason']


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_time', 'end_time', 'grace_period', 'min_working_hours']
    list_filter = ['overtime_allowed']

@admin.register(OfficeLocation)
class OfficeLocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'latitude', 'longitude', 'allowed_radius', 'is_active')
    
@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'subdomain', 'code_prefix', 'payroll_enabled')
    list_editable = ('payroll_enabled',)  # Superuser can toggle here
    list_filter = ('payroll_enabled',)
    search_fields = ('name', 'subdomain')



@admin.register(EmployeeSalary)
class EmployeeSalaryAdmin(admin.ModelAdmin):
    list_display = ('employee', 'company', 'basic_salary', 'gross_salary', 'net_salary', 'status')
    list_filter = ('company', 'status', 'salary_type')
    search_fields = ('employee__full_name', 'employee__employee_id')

@admin.register(Payroll)
class PayrollAdmin(admin.ModelAdmin):
    list_display = ('employee', 'company', 'month', 'year', 'net_salary', 'status')
    list_filter = ('company', 'status', 'month', 'year')
    search_fields = ('employee__full_name', 'employee__employee_id')

@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'employee_id', 'company', 'department', 'designation', 'role')
    list_filter = ('company', 'department', 'role')
    search_fields = ('full_name', 'employee_id', 'user__username', 'user__email')
    # readonly_fields = ('user',)


@admin.register(KioskDevice)
class KioskDeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'is_active', 'last_ping', 'created_at')
    list_filter = ('company', 'is_active')
    search_fields = ('name', 'location')
    readonly_fields = ('device_token', 'created_at', 'last_ping', 'last_ip')

@admin.register(FaceCredential)
class FaceCredentialAdmin(admin.ModelAdmin):
    list_display = ('employee', 'company', 'is_active', 'match_count', 'fail_count', 'registered_at')
    list_filter = ('company', 'is_active')
    search_fields = ('employee__employee_id', 'employee__full_name')
    readonly_fields = ('vector_1', 'vector_2', 'vector_3', 'vector_4', 'vector_5')

@admin.register(FaceRegistrationConsent)
class FaceConsentAdmin(admin.ModelAdmin):
    list_display = ('employee', 'consent_given', 'consent_given_at', 'revoked')
    list_filter = ('consent_given', 'revoked')
    search_fields = ('employee__employee_id', 'employee__full_name')

@admin.register(KioskAttendanceLog)
class KioskLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'kiosk', 'employee', 'action', 'result', 'confidence')
    list_filter = ('result', 'action', 'kiosk')
    search_fields = ('employee__employee_id', 'employee__full_name')
    readonly_fields = ('timestamp',)

@admin.register(KioskSession)
class KioskSessionAdmin(admin.ModelAdmin):
    list_display = ('kiosk', 'is_active', 'started_at', 'last_seen_at')
    list_filter = ('is_active', 'kiosk')
    

try:
    admin.site.unregister(Company)
except admin.sites.NotRegistered:
    pass

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'code_prefix', 'subdomain',
        'payroll_enabled', 'device_tracking_enabled',
        'face_registration_enabled', 'created_at',
    )
    list_filter = (
        'payroll_enabled', 'device_tracking_enabled',
        'face_registration_enabled',
    )
    search_fields = ('name', 'code_prefix', 'subdomain')
    readonly_fields = ('created_at',)

    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'code_prefix', 'subdomain', 'created_at')
        }),
        ('Feature Toggles', {
            'fields': (
                'payroll_enabled',
                'device_tracking_enabled',
                'face_registration_enabled',
            ),
            'description': (
                'Enable or disable optional features for this company. '
                'Changes take effect immediately. '
                '<b>Face Registration</b> allows kiosk attendance via camera.'
            ),
        }),
    )
    