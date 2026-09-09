from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from django.conf.urls import handler404, handler500, handler403, handler400

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
    path('employees/create/', views.employee_create, name='employee_create'),  # MUST come first
    path('employees/<int:user_id>/', views.employee_detail, name='employee_detail'),
    path('employees/edit/<int:user_id>/', views.employee_edit, name='employee_edit'),
    path('employees/delete/<int:user_id>/', views.employee_delete, name='employee_delete'),
    path('employees/', views.employee_list, name='employee_list'),  # last
    
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

    path('employees/<int:user_id>/', views.employee_detail, name='employee_detail'),

    path('employee-attendance/<int:user_id>/', views.employee_attendance_detail, name='employee_attendance_detail'),
    path('api/employee-search/', views.employee_search_api, name='employee_search_api'),

    path('setup/', views.setup, name='setup'),



    # Shift Management (Admin only)
    path('shifts/', views.shift_list, name='shift_list'),
    path('shifts/create/', views.shift_create, name='shift_create'),
    path('shifts/edit/<int:pk>/', views.shift_edit, name='shift_edit'),
    path('shifts/delete/<int:pk>/', views.shift_delete, name='shift_delete'),

    path('assign-shift/', views.assign_shift, name='assign_shift'),


    
    # Notifications
    path('notifications/', views.notification_list, name='notification_list'),
    
    # ---------- Attendance Module (new) ----------
    path('attendance/', views.attendance_view, name='attendance_view'),
    path('attendance/regularize-request/', views.regularize_request, name='regularize_request'),
    path('attendance/regularize-list/', views.regularize_request_list, name='regularize_request_list'),
    path('attendance/regularize-approve/<int:req_id>/', views.regularize_approve, name='regularize_approve'),
    path('attendance/regularize-reject/<int:req_id>/', views.regularize_reject, name='regularize_reject'),

    path('attendance-overview-data/', views.attendance_overview_data, name='attendance_overview_data'),
    path('attendance-report/pdf/', views.attendance_report_pdf, name='attendance_report_pdf'),


    path('profile/', views.profile, name='profile'),

    
    # ---------- Password Reset ----------
    # ---------- Password Reset ----------
path('password-reset/', 
     auth_views.PasswordResetView.as_view(
         template_name='registration/password_reset_form.html',
         email_template_name='registration/password_reset_email.html',
         subject_template_name='registration/password_reset_subject.txt'
     ),
     name='password_reset'),
path('password-reset/done/',
     auth_views.PasswordResetDoneView.as_view(
         template_name='registration/password_reset_done.html'
     ),
     name='password_reset_done'),
path('password-reset-confirm/<uidb64>/<token>/',
     auth_views.PasswordResetConfirmView.as_view(
         template_name='registration/password_reset_confirm.html'
     ),
     name='password_reset_confirm'),
path('password-reset-complete/',
     auth_views.PasswordResetCompleteView.as_view(
         template_name='registration/password_reset_complete.html'
     ),
     name='password_reset_complete'),
     
    
    # Test
    path('test/', views.test_view, name='test'),
]