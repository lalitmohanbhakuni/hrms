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
    check_in_time  = models.DateTimeField()
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
    """
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='reg_categories'
    )
    name = models.CharField(max_length=100)
    monthly_limit = models.PositiveIntegerField(
        default=3, help_text="Max requests per employee per month."
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

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

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name='late_coming_rule'
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

