from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal

# ---------- Company Model ----------
class Company(models.Model):
    name = models.CharField(max_length=100)
    subdomain = models.CharField(max_length=50, unique=True)
    code_prefix = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    payroll_enabled = models.BooleanField(default=False)

    def __str__(self):
        return self.name


# ---------- Attendance Model (MOVED OUTSIDE Company) ----------
class Attendance(models.Model):
    # Existing status for reports
    STATUS_CHOICES = [
        ('Present', 'Present'),
        ('Absent', 'Absent'),
        ('Half-Day', 'Half-Day'),
    ]
    
    # New state for clock in/out flow
    STATE_CHOICES = [
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('auto_checked_out', 'Auto Checked Out'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    date = models.DateField(auto_now_add=True)
    check_in_time = models.DateTimeField()
    check_out_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Present')
    
    total_working_time = models.DurationField(null=True, blank=True)
    state = models.CharField(
        max_length=20,
        choices=[('checked_in', 'Checked In'), ('checked_out', 'Checked Out'), ('auto_checked_out', 'Auto Checked Out')],
        default='checked_in'
    )
    
    # ---------- NEW LOCATION FIELDS ----------
    check_in_latitude = models.DecimalField(
        max_digits=10, 
        decimal_places=6, 
        null=True, 
        blank=True,
        help_text="Latitude of check-in location"
    )
    check_in_longitude = models.DecimalField(
        max_digits=10, 
        decimal_places=6, 
        null=True, 
        blank=True,
        help_text="Longitude of check-in location"
    )
    check_in_distance = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Distance from office in meters"
    )
    
    check_out_latitude = models.DecimalField(
        max_digits=10, 
        decimal_places=6, 
        null=True, 
        blank=True,
        help_text="Latitude of check-out location"
    )
    check_out_longitude = models.DecimalField(
        max_digits=10, 
        decimal_places=6, 
        null=True, 
        blank=True,
        help_text="Longitude of check-out location"
    )
    # -----------------------------------------

    def __str__(self):
        return f"{self.user.username} - {self.date}"

    def save(self, *args, **kwargs):
        if self.check_out_time or self.state in ['checked_out', 'auto_checked_out']:
            self.status = 'Present'
        elif self.check_in_time and not self.check_out_time:
            self.status = 'Present'
        super().save(*args, **kwargs)



# ---------- Leave Type Model ----------
class LeaveType(models.Model):
    name = models.CharField(max_length=50)
    days_allowed = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    is_active = models.BooleanField(default=True)
    is_paid = models.BooleanField(default=True)  # ✅ NEW - distinguishes paid vs unpaid
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        unique_together = ('company', 'name')

    def __str__(self):
        return self.name

        

# ---------- Holiday Model ----------
class Holiday(models.Model):
    name = models.CharField(max_length=100)
    date = models.DateField(unique=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    
    def __str__(self):
        return f"{self.name} - {self.date}"
    
    @property
    def day(self):
        return self.date.strftime('%A')


# ---------- Shift Model ----------
class Shift(models.Model):
    company = models.ForeignKey(
        Company, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True
    )  # <-- ADD THIS
    name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_start = models.TimeField(null=True, blank=True)
    break_end = models.TimeField(null=True, blank=True)
    grace_period = models.IntegerField(default=0, help_text="Minutes")
    min_working_hours = models.IntegerField(default=480, help_text="Minutes")
    overtime_allowed = models.BooleanField(default=True)
    overtime_limit = models.IntegerField(default=2, help_text="Maximum overtime hours per day")
    mon = models.BooleanField(default=True)
    tue = models.BooleanField(default=True)
    wed = models.BooleanField(default=True)
    thu = models.BooleanField(default=True)
    fri = models.BooleanField(default=True)
    sat = models.BooleanField(default=False)
    sun = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def get_working_days(self):
        days = []
        day_map = [
            ('mon', 'Mon'), ('tue', 'Tue'), ('wed', 'Wed'),
            ('thu', 'Thu'), ('fri', 'Fri'), ('sat', 'Sat'), ('sun', 'Sun')
        ]
        for key, label in day_map:
            if getattr(self, key, False):
                days.append(label)
        if not days:
            return "No days set"
        if len(days) == 7:
            return "Every day"
        day_order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        indices = [day_order.index(d) for d in days]
        indices.sort()
        if indices == list(range(min(indices), max(indices) + 1)):
            if len(indices) == 1:
                return days[0]
            return f"{days[0]} - {days[-1]}"
        return ", ".join(days)


# ---------- Office Location Model ----------
class OfficeLocation(models.Model):
    name = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=10, decimal_places=6)
    longitude = models.DecimalField(max_digits=10, decimal_places=6)
    allowed_radius = models.PositiveIntegerField(help_text="Radius in meters", default=200)
    is_active = models.BooleanField(default=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return self.name


# ---------- Employee Profile Model (MOVED OUTSIDE Company) ----------
class EmployeeProfile(models.Model):
    ATTENDANCE_TYPES = [
        ('office', 'Office'),
        ('remote', 'Remote'),
        ('flexible', 'Flexible'),
    ]

    ROLE_CHOICES = [
        ('employee', 'Employee'),
        ('manager', 'Manager'),
        ('hr_admin', 'HR Admin'),
    ]

    

    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    employee_id = models.CharField(max_length=20)
    full_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    date_of_joining = models.DateField(null=True, blank=True)
    designation = models.CharField(max_length=100, blank=True)
    department = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True)
    shift_effective_from = models.DateField(null=True, blank=True, help_text="Date when this shift becomes effective")

    # ----- NEW: Role Field -----
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='employee',
        help_text="Employee role for permissions and approval routing"
    )
    

    # ----- NEW: Manager Relationship -----
    manager = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='team_members',
        help_text="The manager this employee reports to."
    )
    
    
    # ---------- NEW FIELDS FOR LOCATION CHECK-IN ----------
    attendance_type = models.CharField(
        max_length=10, 
        choices=ATTENDANCE_TYPES, 
        default='office',
        help_text="Office: requires location check. Remote/Flexible: no location restriction."
    )
    office_location = models.ForeignKey(
        OfficeLocation, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        help_text="Required if Attendance Type is 'Office'."
    )
    # ----------------------------------------------------

    class Meta:
        unique_together = ('company', 'employee_id')

    def __str__(self):
        return self.full_name or self.user.username


# ---------- Leave Request Model ----------
class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]
    HALF_DAY_CHOICES = [
        ('First', 'First Half'),
        ('Second', 'Second Half'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    is_half_day = models.BooleanField(default=False)
    half_day_session = models.CharField(max_length=10, choices=HALF_DAY_CHOICES, blank=True, null=True)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    attachment = models.FileField(upload_to='leave_attachments/', blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    applied_on = models.DateTimeField(auto_now_add=True)
    admin_comment = models.TextField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.leave_type.name} ({self.start_date} to {self.end_date})"
    
    def get_duration(self):
        if self.is_half_day:
            return 0.5
        return (self.end_date - self.start_date).days + 1


# ---------- Regularization Request Model ----------
class RegularizationRequest(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    date = models.DateField()
    check_in_time = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    admin_comment = models.TextField(blank=True, null=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.status}"


# ---------- Notification Model ----------
class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('info', 'Information'),
        ('action', 'Action Required'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    message = models.TextField()
    notification_type = models.CharField(max_length=10, choices=NOTIFICATION_TYPES, default='info')
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object_type = models.CharField(max_length=50, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.message[:30]}..."


# ---------- Employee Salary Model ----------
# ---------- Employee Salary Model ----------
class EmployeeSalary(models.Model):
    SALARY_TYPES = [
        ('monthly', 'Monthly'),
        ('daily', 'Daily'),
        ('hourly', 'Hourly'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE)
    salary_type = models.CharField(max_length=10, choices=SALARY_TYPES, default='monthly')
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hra = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    overtime_rate = models.DecimalField(                    # ✅ NEW
        max_digits=10, decimal_places=2, default=0,
        help_text="Pay per overtime hour in ₹"
    )
    # ❌ REMOVED: deduction
    gross_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    effective_from = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('company', 'employee', 'effective_from')
        ordering = ['-effective_from']

    def __str__(self):
        return f"{self.employee.full_name} - {self.effective_from}"

    def save(self, *args, **kwargs):
        basic = Decimal(str(self.basic_salary or 0))
        hra = Decimal(str(self.hra or 0))
        allowance = Decimal(str(self.allowance or 0))
        self.gross_salary = basic + hra + allowance
        self.net_salary = self.gross_salary   # Fixed salary has no deduction
        super().save(*args, **kwargs)

            


# ---------- Payroll Model ----------
class Payroll(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('processed', 'Processed'),
        ('paid', 'Paid'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE)
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()

    # ── Salary snapshot ──
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hra = models.DecimalField(max_digits=12, decimal_places=2, default=0)          # ✅ NEW
    allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Attendance snapshot ──
    working_days = models.PositiveIntegerField(default=0)
    absent_days = models.PositiveIntegerField(default=0)                           # ✅ NEW
    present_days = models.PositiveIntegerField(default=0)                          # ✅ NEW
    paid_leave_days = models.DecimalField(max_digits=6, decimal_places=1, default=0)   # ✅ NEW
    unpaid_leave_days = models.DecimalField(max_digits=6, decimal_places=1, default=0) # ✅ NEW

    absent_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0) 
    # ── Overtime snapshot ──
    overtime_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)   # ✅ NEW
    overtime_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)   # ✅ NEW
    overtime_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0) # ✅ NEW

    # ── Deductions ──
    unpaid_leave_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # ✅ NEW
    other_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)         # ✅ NEW
    deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)               # old field — keep for migration, will mirror other_deduction

    net_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # This is Net Payable

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        unique_together = ('company', 'employee', 'month', 'year')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.employee.full_name} - {self.month}/{self.year} ({self.status})"
        

    # ✅ ADD THESE TWO PROPERTIES HERE
    @property
    def total_earnings(self):
        return (self.gross_salary or 0) + (self.overtime_amount or 0)

    @property
    def total_deductions(self):
        return (self.unpaid_leave_deduction or 0) + (self.other_deduction or 0)
