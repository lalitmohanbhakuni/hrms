from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
import uuid

# ---------- Company Model ----------
class Company(models.Model):
    name = models.CharField(max_length=100)
    subdomain = models.CharField(max_length=50, unique=True)
    code_prefix = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    payroll_enabled = models.BooleanField(default=False)
    face_registration_enabled = models.BooleanField(
        default=False,
        help_text="Enable face-recognition kiosk attendance for this company.",
    )
    device_tracking_enabled = models.BooleanField(
        default=False,
        help_text="Enable employee device management feature (Manage Devices).",
    )

    def __str__(self):
        return self.name

# ---------- Attendance Model (MOVED OUTSIDE Company) ----------
class Attendance(models.Model):
    # ─── Status for reports and business logic ───
    STATUS_CHOICES = [
        ('Present',           'Present'),
        ('Absent',            'Absent'),
        ('On Leave',          'On Leave'),
        ('Late',              'Late'),
        ('Early Out',         'Early Out'),
        ('Half-Day',          'Half-Day'),
        ('Missing Checkout',  'Missing Checkout'),
        ('Under Review',      'Under Review'),
    ]

    # ─── State for clock in/out flow ───
    STATE_CHOICES = [
        ('checked_in',       'Checked In'),
        ('checked_out',      'Checked Out'),
        ('auto_checked_out', 'Auto Checked Out'),
    ]
    

    user    = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE,
        null=True, blank=True,
    )
    # date = models.DateField()                         # ✅ fixed earlier
    date = models.DateField(default=timezone.localdate)   # ← add this
    check_in_time  = models.DateTimeField(null=True, blank=True)
    check_out_time = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,                                # bumped from 10
        choices=STATUS_CHOICES,
        default='Present',
    )

    total_working_time = models.DurationField(null=True, blank=True)

    state = models.CharField(
        max_length=20,
        choices=STATE_CHOICES,
        default='checked_in',
    )

    # ─── Location fields ───
    check_in_latitude  = models.DecimalField(
        max_digits=10, decimal_places=6,
        null=True, blank=True,
        help_text="Latitude of check-in location",
    )
    check_in_longitude = models.DecimalField(
        max_digits=10, decimal_places=6,
        null=True, blank=True,
        help_text="Longitude of check-in location",
    )
    check_in_distance  = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Distance from office in meters",
    )
    check_out_latitude = models.DecimalField(
        max_digits=10, decimal_places=6,
        null=True, blank=True,
        help_text="Latitude of check-out location",
    )
    check_out_longitude = models.DecimalField(
        max_digits=10, decimal_places=6,
        null=True, blank=True,
        help_text="Longitude of check-out location",
    )

    # ─── Shift snapshot (historical record) ───
    shift = models.ForeignKey(
        'Shift',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='attendance_records',
        help_text="The shift that was active on this date",
    )
    # ═══════════════════════════════════════════════════════
    #  ATTENDANCE ANALYSIS FIELDS (Late / OT / Half-Day)
    # ═══════════════════════════════════════════════════════
    late_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Minutes late from shift start (after grace period)"
    )
    overtime_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Overtime minutes worked beyond shift end"
    )
    early_out_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Minutes left before shift end"
    )
    is_half_day = models.BooleanField(
        default=False,
        help_text="True if worked less than half of min working hours"
    )
    missing_checkout = models.BooleanField(
        default=False,
        help_text="True if clock in but no clock out"
    )


    class Meta:
        # One attendance record per user per day
        unique_together = [['user', 'date']]
        ordering = ['-date']
        indexes = [
            models.Index(fields=['company', 'date']),
            models.Index(fields=['user', 'date']),
            models.Index(fields=['state', 'check_out_time']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.date} ({self.status})"

    # ─────────────────────────────────────────────────────
    # NOTE: save() override REMOVED.
    #
    # The old save() forced status='Present' whenever a check-in
    # existed, which would silently overwrite custom statuses like
    # 'Missing Checkout' or 'Under Review'.
    #
    # Now views set `status` explicitly, and it sticks.
    # ─────────────────────────────────────────────────────



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
    )
    name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_start = models.TimeField(null=True, blank=True)
    break_end = models.TimeField(null=True, blank=True)
    grace_period = models.IntegerField(default=0, help_text="Minutes")
    min_working_hours = models.IntegerField(default=480, help_text="Minutes")
    overtime_allowed = models.BooleanField(default=True)
    overtime_limit = models.IntegerField(default=2, help_text="Maximum overtime hours per day")

    # ────────── NEW FIELD ──────────
    overtime_multiplier = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=1.50,
        help_text="Multiplier for OT rate. 1.50 = 1.5×, 2.00 = 2×."
    )

    # ────────── NEW FIELD ──────────
    min_overtime_minutes = models.IntegerField(
        default=0,
        help_text="Minimum OT in minutes to count. Below this, OT is ignored (e.g. 30)"
    )
    # ──────────────────────────────

    # ──────────────────────────────

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
# ---------- Office Location Model ----------

class OfficeLocation(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    allowed_radius = models.IntegerField(default=200, help_text="Radius in meters")
    is_active = models.BooleanField(default=True)

    # ✅ Multi-prefix — comma-separated
    allowed_ip_prefix = models.CharField(
        max_length=500,
        blank=True,
        help_text="Comma-separated IP prefixes (e.g. '127.0,103.159.42,49.36.180'). "
                  "Leave blank to require GPS only."
    )

    def __str__(self):
        return f'{self.name} — {self.company.name if self.company else "No company"}'

    def matches_ip(self, client_ip):
        """Check if client IP starts with ANY of the allowed prefixes."""
        if not self.allowed_ip_prefix or not client_ip:
            return False
        for prefix in self.allowed_ip_prefix.split(','):
            prefix = prefix.strip()
            if prefix and client_ip.startswith(prefix + '.'):
                return True
        return False

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.allowed_ip_prefix:
            for prefix in self.allowed_ip_prefix.split(','):
                prefix = prefix.strip()
                if not prefix:
                    continue
                parts = prefix.split('.')
                if len(parts) not in (2, 3):
                    raise ValidationError({
                        'allowed_ip_prefix':
                            f'"{prefix}" must be 2 or 3 octets (e.g. "49.36" or "49.36.180").'
                    })
                for p in parts:
                    if not p.isdigit() or not 0 <= int(p) <= 255:
                        raise ValidationError({
                            'allowed_ip_prefix':
                                f'Invalid octet "{p}" in "{prefix}". Each must be 0-255.'
                        })

    def save(self, *args, **kwargs):
        if self.allowed_ip_prefix:
            self.allowed_ip_prefix = self.allowed_ip_prefix.strip()
        super().save(*args, **kwargs)
        

            
        
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

    # ── NEW: Pending shift (takes effect on the effective date) ──
    pending_shift = models.ForeignKey(
        Shift,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pending_for_profiles',
        help_text="Shift queued to take over on pending_shift_effective_from",
    )
    pending_shift_effective_from = models.DateField(
        null=True, blank=True,
        help_text="Date when pending_shift becomes the active shift",
    )

    # ----- NEW: Role Field -----
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='employee',
        help_text="Employee role for permissions and approval routing"
    )

    is_company_owner = models.BooleanField(
        default=False,
        help_text="True for the primary HR Admin who self-approves their own requests.",
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

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['company'],
                condition=models.Q(is_company_owner=True),
                name='one_owner_per_company',
            ),
        ]

    # ── INSERT THESE TWO LINES HERE ──
    is_active = models.BooleanField(default=True)
    terminated_at = models.DateField(null=True, blank=True)
    # ─────────────────────────────────
    
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
    SESSION_CHOICES = [
        ('full',         'Full Day'),
        ('first_half',   'First Half (Morning)'),
        ('second_half',  'Second Half (Afternoon)'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)

    # ── Legacy fields (kept for backward compat with old records) ──
    is_half_day = models.BooleanField(default=False)
    half_day_session = models.CharField(
        max_length=10, choices=HALF_DAY_CHOICES, blank=True, null=True
    )

    # ── Dates + sessions (new: supports mixed start/end halves) ──
    start_date = models.DateField()
    start_session = models.CharField(
        max_length=15, choices=SESSION_CHOICES, default='full'
    )
    end_date = models.DateField()
    end_session = models.CharField(
        max_length=15, choices=SESSION_CHOICES, default='full'
    )

    reason = models.TextField()
    attachment = models.FileField(
        upload_to='leave_attachments/', blank=True, null=True
    )
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='Pending'
    )
    applied_on = models.DateTimeField(auto_now_add=True)
    admin_comment = models.TextField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True, null=True)
    is_self_approved = models.BooleanField(
        default=False,
        help_text="True when the requester self-approved as Company Owner.",
    )

    def __str__(self):
        return f"{self.user.username} - {self.leave_type.name} ({self.start_date} to {self.end_date})"

    def get_duration(self):
        """
        Compute duration in days, supporting mixed start/end sessions.

        Examples:
          Start=1st half, End=2nd half (same day)  → 1.0
          Start=2nd half, End=2nd half (same day)  → 0.5
          Start=2nd half, End=1st half (3 days)    → 2.0
          Start=full,     End=full (3 days)        → 3.0
        """
        from decimal import Decimal

        # ── Backward compat: legacy half-day records ──
        if self.is_half_day and self.start_date == self.end_date:
            return Decimal('0.5')

        start_sess = self.start_session or 'full'
        end_sess   = self.end_session   or 'full'

        # ── Same-day leave ──
        if self.start_date == self.end_date:
            if start_sess == 'full' or end_sess == 'full':
                return Decimal('1.0')
            if start_sess == end_sess:
                return Decimal('0.5')                  # half + same half
            return Decimal('1.0')                      # 1st + 2nd = full

        # ── Multi-day leave ──
        total = Decimal('0')

        # Start day
        total += Decimal('1.0') if start_sess == 'full' else Decimal('0.5')

        # Middle days (always full)
        middle_days = (self.end_date - self.start_date).days - 1
        if middle_days > 0:
            total += Decimal(str(middle_days))

        # End day
        total += Decimal('1.0') if end_sess == 'full' else Decimal('0.5')

        return total
        


# ---------- Regularization Request Model ----------

class RegularizationType(models.Model):
    """
    HR-managed list of regularization type options.
    Each type maps to a fixed BEHAVIOR code the Python uses for auto-detection.
    """
    BEHAVIOR_CHOICES = [
        ('miss_punch',      'No attendance row exists'),
        ('forgot_checkout', 'Checked in but never checked out'),
        ('wrong_punch',     'Both times present — wrong values'),
        ('other',           'Fallback / catch-all'),
        ('manual',          'Employee picks this manually'),
    ]

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='reg_types'
    )
    label = models.CharField(
        max_length=100,
        help_text="Name shown in the dropdown, e.g. 'Miss Punch'.",
    )
    behavior = models.CharField(
        max_length=20,
        choices=BEHAVIOR_CHOICES,
        default='manual',
        help_text="What the backend does when this type is picked.",
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('company', 'label')]
        ordering = ['order', 'id']
        verbose_name_plural = 'Regularization Types'

    def __str__(self):
        return f"{self.company.name} — {self.label}"


class RegularizationCategory(models.Model):
    """
    HR Admin–managed categories for regularization requests.
    Employees pick one when submitting; limits enforced per employee, per month.

    NEW: Over-limit handling — when an employee exceeds their monthly quota,
    the system can either block further submissions, or auto-deduct from
    paid leave (with LOP fallback) at month-end.
    """
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='reg_categories'
    )
    name = models.CharField(max_length=100)

    # ══════════════════════════════════════════════════════════
    # system_type — maps category to attendance state
    # ══════════════════════════════════════════════════════════
    system_type = models.CharField(
        max_length=30,
        choices=[
            ('miss_punch',      'Miss Punch — no attendance row'),
            ('forgot_checkout', 'Forgot Checkout — checked in, no checkout'),
            ('wrong_punch',     'Wrong Punch — wrong times'),
            ('short_hours',     'Short Hours — worked less than shift'),
            ('other',           'Other'),
        ],
        default='other',
        help_text="Attendance state this category handles.",
    )

    monthly_limit = models.PositiveIntegerField(
        default=3, help_text="Max requests per employee per month."
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    # ══════════════════════════════════════════════════════════
    # Over-limit handling
    # ══════════════════════════════════════════════════════════
    over_limit_action = models.CharField(
        max_length=20,
        choices=[
            ('block',       'Block — cannot submit'),
            ('auto_deduct', 'Auto-Deduct on Quota Exhaustion'),
        ],
        default='block',
        help_text="What happens when employee exceeds the monthly limit.",
    )

    # ── NEW: penalty_type ──
    penalty_type = models.CharField(
        max_length=10,
        choices=[
            ('leave',  'Deduct Leave'),
            ('salary', 'Deduct Salary'),
        ],
        default='leave',
        help_text="How the penalty is charged.",
    )

    penalty_days = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('0.50'),
        help_text="0.5 = half day, 1.0 = full day. Applied per over-limit day.",
    )
    target_leave_type = models.ForeignKey(
        'LeaveType',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='reg_over_limit_deductions',
        help_text="Which leave type absorbs the penalty first.",
    )
    insufficient_balance_action = models.CharField(
        max_length=10,
        choices=[
            ('lop',  'Loss of Pay (LOP)'),
            ('skip', 'Skip — waive remainder'),
        ],
        default='lop',
        help_text="What happens when leave balance is insufficient.",
    )

    class Meta:
        unique_together = [('company', 'name')]
        ordering = ['order', 'id']
        verbose_name_plural = 'Regularization Categories'

    def __str__(self):
        return f"{self.company.name} — {self.name}"


class RegularizationRequest(models.Model):
    STATUS_CHOICES = [
        ('Pending',  'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    date = models.DateField()
    check_in_time = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    reason = models.TextField()
    category = models.ForeignKey(
        RegularizationCategory,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='requests',
        help_text="Which rule bucket this request falls under.",
    )
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


#*********************** PasswordResetRequest
            
class PasswordResetRequest(models.Model):
    """
    Employee-initiated password reset request.
    HR Admin approves and sets the new password directly.
    """
    STATUS_PENDING   = 'Pending'
    STATUS_APPROVED  = 'Approved'
    STATUS_REJECTED  = 'Rejected'
    STATUS_COMPLETED = 'Completed'

    STATUS_CHOICES = [
        (STATUS_PENDING,   'Pending'),
        (STATUS_APPROVED,  'Approved'),
        (STATUS_REJECTED,  'Rejected'),
        (STATUS_COMPLETED, 'Completed'),
    ]

    user       = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='password_reset_requests',
    )
    employee   = models.ForeignKey(
        'core.EmployeeProfile',
        on_delete=models.CASCADE,
        related_name='password_reset_requests',
    )
    company    = models.ForeignKey(
        'core.Company',
        on_delete=models.CASCADE,
        related_name='password_reset_requests',
    )
    status     = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by  = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_password_resets',
    )
    reviewed_at  = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"{self.user.username} — {self.status}"




# ─────────────────────────────────────────
# Late Coming Rules (per company)
# ─────────────────────────────────────────


class LateComingRule(models.Model):
    METHOD_CHOICES = [
        ('marks',   'Late Marks (simple)'),
        ('minutes', 'Late Minutes (precise)'),
    ]
    PENALTY_CHOICES = [
        ('leave',  'Deduct Leave'),
        ('salary', 'Deduct Salary'),
        ('none',   'No Penalty'),
    ]
    INSUFFICIENT_CHOICES = [
        ('lop',  'Loss of Pay (LOP)'),
        ('skip', 'Skip Deduction'),
    ]

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='late_coming_rules'
    )
    is_enabled = models.BooleanField(default=True)
    calculation_method = models.CharField(
        max_length=10, choices=METHOD_CHOICES, default='marks',
        help_text="How late arrivals are counted and penalized."
    )

    # ── Method 1: Late Marks ──
    monthly_allowed_late_marks = models.PositiveIntegerField(default=3)
    penalty_type = models.CharField(
        max_length=10, choices=PENALTY_CHOICES, default='leave'
    )
    penalty_amount = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.25
    )
    half_day_cutoff_minutes = models.PositiveIntegerField(default=45)
    target_leave_type = models.ForeignKey(
        'LeaveType',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='late_rules_using_this',
        help_text="Which leave type absorbs late-arrival penalties. If empty, all penalties go to LOP.",
    )
    
    insufficient_balance_action = models.CharField(
        max_length=10, choices=INSUFFICIENT_CHOICES, default='lop'
    )

    updated_at = models.DateTimeField(auto_now=True)

    # ── Policy versioning ──
    effective_from = models.DateField(
        null=True, blank=True,
        help_text="Policy applies from this date onwards",
    )
    effective_to = models.DateField(
        null=True, blank=True,
        help_text="Policy applies up to this date (inclusive). Null = still active.",
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Auto-incremented when a new version is created",
    )

    def __str__(self):
        return f"Late Coming Rules — {self.company.name}"
        

class LateMinuteSlab(models.Model):
    """
    Minute-based slabs used when LateComingRule.calculation_method = 'minutes'.
    Each slab defines: from_minutes ≤ total_late_minutes ≤ to_minutes → penalty_days
    """
    rule = models.ForeignKey(
        LateComingRule, on_delete=models.CASCADE, related_name='minute_slabs'
    )
    from_minutes = models.PositiveIntegerField(
        help_text="Inclusive lower bound (e.g. 60)."
    )
    to_minutes = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Inclusive upper bound. Leave blank for 'and above'.",
    )
    penalty_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Days of leave to deduct (e.g. 0.25 = quarter day).",
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'from_minutes']
        verbose_name_plural = 'Late Minute Slabs'

    def __str__(self):
        rng = f"{self.from_minutes}-{self.to_minutes}" if self.to_minutes else f"{self.from_minutes}+"
        return f"{rng} min → {self.penalty_days} day"
        

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
    absent_days = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    present_days = models.DecimalField(max_digits=6, decimal_places=1, default=0)                          # ✅ NEW
    paid_leave_days = models.DecimalField(max_digits=6, decimal_places=1, default=0)   # ✅ NEW
    unpaid_leave_days = models.DecimalField(max_digits=6, decimal_places=1, default=0) # ✅ NEW

    absent_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0) 

    half_day_days      = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    half_day_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)

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
    

    # ── Late Coming (from LateComingRule) ──
    late_days              = models.PositiveIntegerField(default=0)
    late_halfday_days      = models.PositiveIntegerField(default=0)
    late_deduction         = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    late_halfday_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    late_penalty_days      = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    late_leave_days        = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    late_lop_days          = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    


    class Meta:
        unique_together = ('company', 'employee', 'month', 'year')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.employee.full_name} - {self.month}/{self.year} ({self.status})"
        

    @property
    def total_deduction(self):
        return (
            (self.absent_deduction or 0)
            + (self.half_day_deduction or 0)
            + (self.unpaid_leave_deduction or 0)
            + (self.other_deduction or 0)
            + (self.late_deduction or 0)
            + (self.late_halfday_deduction or 0)
        )

    @property
    def total_earnings(self):
        return (self.gross_salary or 0) + (self.overtime_amount or 0)

    @property
    def total_deductions(self):
        return self.total_deduction



# ═══════════════════════════════════════════════════════════════
#  LATE DEDUCTION LEDGER
#  Every late penalty creates ONE immutable transaction.
#  Stores the exact policy that was applied at that time.
# ═══════════════════════════════════════════════════════════════
class LateDeduction(models.Model):
    DEDUCTION_TYPE = [
        ('LEAVE',  'Deduct Leave'),
        ('SALARY', 'Deduct Salary'),
    ]
    STATUS_CHOICES = [
        ('APPLIED',          'Applied'),            # Leave consumed immediately
        ('PENDING_PAYROLL',  'Pending Payroll'),    # Salary cut awaited
        ('PROCESSED',        'Processed'),          # Salary cut done
        ('CANCELLED',        'Cancelled'),          # Reversed by HR
    ]
    SOURCE_CHOICES = [
        ('LATE_COMING', 'Late Coming'),
        ('REG_OVERAGE', 'Regularization over-limit'),
    ]

    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name='late_deductions',
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='late_deductions',
    )
    attendance_date = models.DateField(
        help_text="Date the employee was late (the attendance date)",
    )

    # ── What happened ──
    deduction_type = models.CharField(max_length=10, choices=DEDUCTION_TYPE)
    penalty_days   = models.DecimalField(max_digits=6, decimal_places=2)

    # ── If LEAVE ──
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='late_deductions',
    )
    leave_days  = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    lop_days    = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    # ── If SALARY ──
    salary_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
    )

    # ── Snapshot of the rule used (for history) ──
    #   { "policy_version": 1, "deduction_per_late": "0.25",
    #     "free_marks": 3, "half_day_cutoff": 120,
    #     "late_days": 5, "billable_lates": 2 }
    policy_snapshot = models.JSONField(default=dict, blank=True)

    # ── Reference to the policy row (if kept) ──
    policy_ref_id = models.PositiveIntegerField(null=True, blank=True)

    # ── State ──
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='LATE_COMING')

    # ── Payroll link (once processed) ──
    payroll = models.ForeignKey(
        'Payroll',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='late_deductions',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-attendance_date']
        indexes = [
            models.Index(fields=['company', 'attendance_date']),
            models.Index(fields=['employee', 'status']),
            models.Index(fields=['status', 'deduction_type']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'attendance_date', 'source'],
                name='unique_late_deduction_per_day',
            ),
        ]

    def __str__(self):
        return (
            f"{self.employee.employee_id} | {self.attendance_date} | "
            f"{self.deduction_type} | {self.penalty_days} | {self.status}"
        )
        

# core/models.py
class EmployeeDevice(models.Model):
    """WebAuthn credentials for attendance verification"""
    
    DEVICE_TYPES = [
        ('mobile', 'Mobile'),
        ('laptop', 'Laptop/Desktop'),
    ]
    
    REGISTRATION_STATUS = [
        ('pending', 'Pending HR Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attendance_devices')
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    
    # WebAuthn data
    device_type = models.CharField(max_length=10, choices=DEVICE_TYPES)
    credential_id = models.BinaryField(max_length=255, unique=True)  # WebAuthn credential ID
    public_key = models.BinaryField()                                 # Public key
    sign_count = models.PositiveIntegerField(default=0)               # Replay prevention
    transports = models.CharField(max_length=100, blank=True)         # usb, nfc, ble, internal
    
    # Metadata
    device_name = models.CharField(max_length=255, blank=True)
    user_agent = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)  # ⬅️ NEW (optional)
    
    # Status
    is_active = models.BooleanField(default=True)
    is_primary = models.BooleanField(default=False)
    
    # ⬇️⬇️⬇️ HR APPROVAL (NEW) ⬇️⬇️⬇️
    registration_status = models.CharField(
        max_length=20,
        choices=REGISTRATION_STATUS,
        default='approved',
        db_index=True,
        help_text="HR approval status for this device"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='approved_attendance_devices'
    )
    rejection_reason = models.CharField(max_length=200, blank=True)
    # ⬆️⬆️⬆️ HR APPROVAL END ⬆️⬆️⬆️
    
    # Timestamps
    registered_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    disabled_by = models.ForeignKey(User, null=True, blank=True, 
                                     on_delete=models.SET_NULL, 
                                     related_name='disabled_attendance_devices')
    disabled_reason = models.CharField(max_length=200, blank=True)  # ⬅️ NEW (optional)
    
    class Meta:
        ordering = ['-last_used_at']
        indexes = [
            models.Index(fields=['user', 'device_type', 'is_active']),
            models.Index(fields=['company', 'registration_status']),  # ⬅️ NEW
        ]
    
    def __str__(self):
        return f"{self.user.username} — {self.device_type} ({self.registration_status})"



class AttendanceDevicePolicy(models.Model):
    """HR-controlled settings"""
    
    company = models.OneToOneField(Company, on_delete=models.CASCADE)
    
    # Master switch
    enabled = models.BooleanField(default=False, 
        help_text="Require device verification for Clock In/Out")
    
    # Limits
    max_mobile_devices = models.PositiveIntegerField(default=1)
    max_laptop_devices = models.PositiveIntegerField(default=1)
    
    # Behavior
    allow_hr_override = models.BooleanField(default=True)
    notify_hr_on_new_device = models.BooleanField(default=True)
    allow_employee_self_remove = models.BooleanField(default=False)
    allow_ip_fallback = models.BooleanField(default=True, 
        help_text="If device fails, allow office IP as fallback")
    
    # ⬇️ HR APPROVAL
    require_hr_approval = models.BooleanField(
        default=False,
        help_text="New devices require HR approval before activation"
    )
    
    # Timestamps
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='device_policy_updates'
    )
    
    def __str__(self):
        status = "ON" if self.enabled else "OFF"
        return f"{self.company.name} — Device Verification {status}"


# ═══════════════════════════════════════════════════════════════
# FACE REGISTRATION & KIOSK MODELS
# ═══════════════════════════════════════════════════════════════

class KioskDevice(models.Model):
    """
    One record per physical kiosk tablet/PC at a factory gate.
    Kiosk authenticates with a device_token — no user password needed.
    """
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='kiosk_devices'
    )
    name = models.CharField(
        max_length=100,
        help_text="e.g. Main Gate, Factory Floor, Admin Block",
    )
    location = models.CharField(
        max_length=200, blank=True,
        help_text="Physical location description",
    )
    device_token = models.CharField(
        max_length=64, unique=True,
        help_text="Auto-generated secure token for device auth",
    )
    is_active = models.BooleanField(default=True)
    allow_clock_in = models.BooleanField(default=True)
    allow_clock_out = models.BooleanField(default=True)

    # ← ADD THIS
    min_hours_before_out = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=2.0,
        help_text="Minimum hours between clock-in and clock-out",
    )

    # ── PIN-based device activation ──
    activation_pin = models.CharField(
        max_length=10,
        blank=True,
        help_text="Auto-generated 4-digit PIN for first-time activation",
    )
    is_activated = models.BooleanField(
        default=False,
        help_text="True after device enters correct PIN once",
    )
    activated_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the device was first activated",
    )
    device_fingerprint = models.CharField(
        max_length=200,
        blank=True,
        help_text="Browser fingerprint stored at activation",
    )
    

    # Audit
    last_ping = models.DateTimeField(null=True, blank=True)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_kiosks',
    )

    class Meta:
        unique_together = [('company', 'name')]
        ordering = ['company', 'name']

    def save(self, *args, **kwargs):
        if not self.device_token:
            self.device_token = uuid.uuid4().hex + uuid.uuid4().hex[:16]
        if not self.activation_pin:
            import secrets
            self.activation_pin = str(secrets.randbelow(9000) + 1000)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.company.name} — {self.name}"


class FaceCredential(models.Model):
    """
    Stores 5 encrypted face vectors (128-dim each) for one employee.
    Vectors are encrypted at rest using Fernet (see utils.py).
    Raw photos are NEVER stored.
    """
    employee = models.OneToOneField(
        EmployeeProfile, on_delete=models.CASCADE,
        related_name='face_credential',
    )
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE,
        related_name='face_credentials',
    )

    # 5 vectors for robustness (front, left, right, smile, neutral)
    vector_1 = models.BinaryField(help_text="Encrypted 128-dim vector")
    vector_2 = models.BinaryField()
    vector_3 = models.BinaryField()
    vector_4 = models.BinaryField()
    vector_5 = models.BinaryField()

    # Metadata
    registered_at = models.DateTimeField(auto_now_add=True)
    registered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='registered_faces',
    )
    is_active = models.BooleanField(default=True)
    last_matched_at = models.DateTimeField(null=True, blank=True)
    match_count = models.PositiveIntegerField(default=0)
    fail_count = models.PositiveIntegerField(default=0)

    # Threshold: 0.4 = strict (few false positives), 0.7 = lenient
    match_threshold = models.FloatField(
        default=0.55,
        help_text="face-api.js euclidean distance threshold",
    )

    # Model version tracking
    model_version = models.CharField(
        max_length=20, default='face-api-1.0',
        help_text="Which face-api.js model was used to register",
    )

    # Re-registration reminder
    re_register_after = models.DateField(
        null=True, blank=True,
        help_text="Re-register every 12 months to account for aging",
    )

    class Meta:
        indexes = [
            models.Index(fields=['company', 'is_active']),
            models.Index(fields=['last_matched_at']),
        ]

    def __str__(self):
        return f"{self.employee.employee_id} — face registered"


class FaceRegistrationConsent(models.Model):
    """
    DPDP Act compliance — employee gives explicit consent for biometric data.
    """
    employee = models.OneToOneField(
        EmployeeProfile, on_delete=models.CASCADE,
        related_name='face_consent',
    )
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE,
        related_name='face_consents',
    )

    # Consent details
    consent_given = models.BooleanField(default=False)
    consent_given_at = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(
        max_length=20, default='1.0',
        help_text="Version of the consent form shown to employee",
    )

    # Signatures
    employee_signature = models.CharField(
        max_length=200, blank=True,
        help_text="Employee typed their full name as consent",
    )
    witnessed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='witnessed_consents',
    )

    # Revocation
    revoked = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        status = "✓" if self.consent_given and not self.revoked else "✗"
        return f"{status} {self.employee.employee_id} consent"


class KioskAttendanceLog(models.Model):
    """
    Audit log of every kiosk face scan — matched or failed.
    """
    ACTION_CHOICES = [
        ('in', 'Clock In'),
        ('out', 'Clock Out'),
    ]
    RESULT_CHOICES = [
        ('match', 'Matched'),
        ('no_match', 'No Match'),
        ('liveness_fail', 'Liveness Failed'),
        ('no_face', 'No Face Detected'),
        ('error', 'Error'),
    ]

    kiosk = models.ForeignKey(
        KioskDevice, on_delete=models.CASCADE,
        related_name='attendance_logs',
    )
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE,
        related_name='kiosk_logs',
    )

    # Matched employee (null if no match)
    employee = models.ForeignKey(
        EmployeeProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='kiosk_scans',
    )

    # What happened
    action = models.CharField(max_length=5, choices=ACTION_CHOICES)
    result = models.CharField(max_length=20, choices=RESULT_CHOICES)
    confidence = models.FloatField(
        null=True, blank=True,
        help_text="Euclidean distance — lower is better",
    )

    # Attendance record created (if matched)
    attendance = models.ForeignKey(
        'Attendance', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='kiosk_logs',
    )

    # Context
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['kiosk', '-timestamp']),
            models.Index(fields=['company', '-timestamp']),
            models.Index(fields=['employee', '-timestamp']),
            models.Index(fields=['result']),
        ]

    def __str__(self):
        emp = self.employee.employee_id if self.employee else 'unknown'
        return f"{self.kiosk.name} | {self.timestamp:%d %b %H:%M} | {emp} | {self.result}"


class KioskSession(models.Model):
    """
    Tracks active kiosk sessions for remote logout / revoke.
    """
    kiosk = models.ForeignKey(
        KioskDevice, on_delete=models.CASCADE,
        related_name='sessions',
    )
    session_key = models.CharField(max_length=64, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-last_seen_at']
        indexes = [
            models.Index(fields=['kiosk', 'is_active']),
        ]

    def __str__(self):
        status = "active" if self.is_active else "revoked"
        return f"{self.kiosk.name} — {status} since {self.started_at:%d %b %H:%M}"

        