from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# ---------- Attendance Model ----------
class Attendance(models.Model):
    STATUS_CHOICES = [
        ('Present', 'Present'),
        ('Absent', 'Absent'),
        ('Half-Day', 'Half-Day'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)
    check_in_time = models.DateTimeField()
    check_out_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Present')
    
    def __str__(self):
        return f"{self.user.username} - {self.date}"

    def save(self, *args, **kwargs):
        if self.check_in_time and self.check_out_time:
            self.status = 'Present'
        elif self.check_in_time and not self.check_out_time:
            self.status = 'Present'
        super().save(*args, **kwargs)


# ---------- Leave Type Model ----------
class LeaveType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    days_allowed = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return self.name

        


# ---------- Holiday Model ----------
class Holiday(models.Model):
    name = models.CharField(max_length=100)
    date = models.DateField(unique=True)
    
    def __str__(self):
        return f"{self.name} - {self.date}"
    
    @property
    def day(self):
        return self.date.strftime('%A')

class EmployeeProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    department = models.CharField(max_length=100, blank=True)
    designation = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.user.username




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
    date = models.DateField()
    check_in_time = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    admin_comment = models.TextField(blank=True, null=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.status}"



# ---------- Notification Model (UPDATED) ----------
class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('info', 'Information'),
        ('action', 'Action Required'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    notification_type = models.CharField(max_length=10, choices=NOTIFICATION_TYPES, default='info')
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object_type = models.CharField(max_length=50, blank=True, null=True)  # e.g., 'LeaveRequest'
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.message[:30]}..."


