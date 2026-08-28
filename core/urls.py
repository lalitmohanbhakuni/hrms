from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('clock-in/', views.clock_in, name='clock_in'),
    path('clock-out/', views.clock_out, name='clock_out'),
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/create/', views.employee_create, name='employee_create'),
    path('employees/delete/<int:user_id>/', views.employee_delete, name='employee_delete'),
    path('attendance-report/', views.attendance_report, name='attendance_report'),
    path('', views.dashboard, name='home'),
    path('test/', views.test_view, name='test'),
]