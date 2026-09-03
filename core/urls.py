from django.urls import path
from . import views

urlpatterns = [
    # Auth & Dashboard
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('', views.dashboard, name='home'),
    
    # Attendance
    path('clock-in/', views.clock_in, name='clock_in'),
    path('clock-out/', views.clock_out, name='clock_out'),
    
    # Employee Management
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/create/', views.employee_create, name='employee_create'),
    path('employees/delete/<int:user_id>/', views.employee_delete, name='employee_delete'),
    
    # Leave Types (Admin)
    path('leave-types/', views.leave_type_list, name='leave_type_list'),
    path('leave-types/create/', views.leave_type_create, name='leave_type_create'),
    path('leave-types/edit/<int:pk>/', views.leave_type_edit, name='leave_type_edit'),
    path('leave-types/delete/<int:pk>/', views.leave_type_delete, name='leave_type_delete'),
    
    # Holidays (Admin)
    path('holidays/', views.holiday_list, name='holiday_list'),
    path('holidays/create/', views.holiday_create, name='holiday_create'),
    path('holidays/edit/<int:pk>/', views.holiday_edit, name='holiday_edit'),
    path('holidays/delete/<int:pk>/', views.holiday_delete, name='holiday_delete'),
    
    # Employee Leave Dashboard
    path('employee-leaves/', views.employee_leaves, name='employee_leaves'),
    path('leaves/', views.employee_leaves, name='leave_list'),  # alias for templates
    
    # Leave Apply
    path('leave-apply/', views.leave_apply, name='leave_apply'),
    
    # Admin Leave Approvals
    path('admin-leaves/', views.admin_leaves, name='admin_leaves'),
    path('leave-approve/<int:leave_id>/', views.leave_approve, name='leave_approve'),
    path('leave-reject/<int:leave_id>/', views.leave_reject, name='leave_reject'),
    
    # Team Attendance
    path('team/', views.team_attendance, name='team_attendance'),
    
    # Attendance Report
    path('attendance-report/', views.attendance_report, name='attendance_report'),
    
    # Notifications
    path('notifications/', views.notification_list, name='notification_list'),

    # --- Attendance Module URLs ---
    path('attendance/', views.attendance_view, name='attendance_view'),
    path('attendance/regularize-request/', views.regularize_request, name='regularize_request'),
    path('attendance/regularize-list/', views.regularize_request_list, name='regularize_request_list'),
    path('attendance/regularize-approve/<int:req_id>/', views.regularize_approve, name='regularize_approve'),
    path('attendance/regularize-reject/<int:req_id>/', views.regularize_reject, name='regularize_reject'),

    # --- NEW: Setup / Management Dashboards ---
    path('setup/', views.setup_dashboard, name='setup_dashboard'),
    path('setup/leave-types/', views.manage_leave_types, name='manage_leave_types'),
    path('setup/holidays/', views.manage_holidays, name='manage_holidays'),
    path('setup/employees/', views.manage_employees, name='manage_employees'),
    
    # --- Setup Delete URLs (You already had these) ---
    path('setup/leave-types/delete/<int:pk>/', views.delete_leave_type, name='delete_leave_type'),
    path('setup/holidays/delete/<int:pk>/', views.delete_holiday, name='delete_holiday'),
    path('setup/employees/delete/<int:pk>/', views.delete_employee, name='delete_employee'),

    # Test
    path('test/', views.test_view, name='test'),
]