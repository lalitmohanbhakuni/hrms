from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# ---------- Company Model ----------
class Company(models.Model):
    name = models.CharField(max_length=100)
    subdomain = models.CharField(max_length=50, unique=True)   # e.g., "dml", "op"
    code_prefix = models.CharField(max_length=10)              # e.g., "DML", "OP"
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name



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
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Present')   # keep

    total_working_time = models.DurationField(null=True, blank=True)
    state = models.CharField(
        max_length=20,
        choices=[('checked_in', 'Checked In'), ('checked_out', 'Checked Out'), ('auto_checked_out', 'Auto Checked Out')],
        default='checked_in'
    )
    


    def __str__(self):
        return f"{self.user.username} - {self.date}"

    def save(self, *args, **kwargs):
        # Auto-set status for reports – if checked out, mark Present
        if self.check_out_time or self.state in ['checked_out', 'auto_checked_out']:
            self.status = 'Present'
        elif self.check_in_time and not self.check_out_time:
            self.status = 'Present'   # or maybe 'In Progress' – but you can keep Present
        super().save(*args, **kwargs)



# ---------- Leave Type Model ----------
class LeaveType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    days_allowed = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    is_active = models.BooleanField(default=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)  # NEW
    
    def __str__(self):
        return self.name


# ---------- Holiday Model ----------
class Holiday(models.Model):
    name = models.CharField(max_length=100)
    date = models.DateField(unique=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)  # NEW
    
    def __str__(self):
        return f"{self.name} - {self.date}"
    
    @property
    def day(self):
        return self.date.strftime('%A')


# ---------- Employee Profile Model ----------
class EmployeeProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    employee_id = models.CharField(max_length=20)  # unique per company
    full_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    date_of_joining = models.DateField(null=True, blank=True)
    designation = models.CharField(max_length=100, blank=True)
    department = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    # ... existing fields ...
    shift = models.ForeignKey('Shift', on_delete=models.SET_NULL, null=True, blank=True)
    shift_effective_from = models.DateField(null=True, blank=True, help_text="Date when this shift becomes effective")

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
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)  # NEW
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
        else:
            return (self.end_date - self.start_date).days + 1


# ---------- Regularization Request Model ----------
class RegularizationRequest(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)  # NEW
    date = models.DateField()
    check_in_time = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    admin_comment = models.TextField(blank=True, null=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.status}"



class Shift(models.Model):
    name = models.CharField(max_length=100, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_start = models.TimeField(null=True, blank=True)
    break_end = models.TimeField(null=True, blank=True)
    grace_period = models.IntegerField(default=0, help_text="Minutes")
    min_working_hours = models.IntegerField(default=480, help_text="Minutes")  # 8 hours
    overtime_allowed = models.BooleanField(default=True)
    overtime_limit = models.IntegerField(default=2, help_text="Maximum overtime hours per day")  # NEW
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
        """Return a formatted string of working days based on shift's days."""
        days = []
        day_map = [
            ('mon', 'Mon'),
            ('tue', 'Tue'),
            ('wed', 'Wed'),
            ('thu', 'Thu'),
            ('fri', 'Fri'),
            ('sat', 'Sat'),
            ('sun', 'Sun'),
        ]
        
        for key, label in day_map:
            if getattr(self, key, False):
                days.append(label)
        
        if not days:
            return "No days set"
        
        if len(days) == 7:
            return "Every day"
        
        # Check if days are consecutive (e.g., Mon-Fri)
        day_order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        indices = [day_order.index(d) for d in days]
        indices.sort()
        
        if indices == list(range(min(indices), max(indices) + 1)):
            if len(indices) == 1:
                return days[0]
            return f"{days[0]} - {days[-1]}"
        
        return ", ".join(days)



# ---------- Notification Model ----------
class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('info', 'Information'),
        ('action', 'Action Required'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)  # NEW
    message = models.TextField()
    notification_type = models.CharField(max_length=10, choices=NOTIFICATION_TYPES, default='info')
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object_type = models.CharField(max_length=50, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.message[:30]}..."