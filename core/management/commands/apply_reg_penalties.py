from django.core.management.base import BaseCommand
from datetime import date
from decimal import Decimal
from calendar import monthrange
from core.models import (
    EmployeeProfile, Attendance, RegularizationRequest,
    RegularizationCategory, LateDeduction, EmployeeSalary,
)
from core.utils import get_leave_balance


class Command(BaseCommand):
    help = "Auto-deduct leave / LOP for regularizations over monthly quota."

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True)
        parser.add_argument('--month', type=int, required=True)
        parser.add_argument('--employee', type=str, default=None)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        year, month = opts['year'], opts['month']
        dry = opts['dry_run']
        first = date(year, month, 1)
        last = date(year, month, monthrange(year, month)[1])

        if not dry:
            deleted, _ = LateDeduction.objects.filter(
                attendance_date__gte=first,
                attendance_date__lte=last,
                source='REG_OVERAGE',
            ).exclude(status='PROCESSED').delete()
            if deleted:
                self.stdout.write(f"Cleared {deleted} previous REG_OVERAGE rows.")

        employees = EmployeeProfile.objects.filter(is_active=True)
        if opts['employee']:
            employees = employees.filter(employee_id=opts['employee'])

        total = 0
        for emp in employees:
            total += self._process(emp, year, month, first, last, dry)

        style = self.style.WARNING if dry else self.style.SUCCESS
        prefix = "[DRY RUN] " if dry else ""
        self.stdout.write(style(f"{prefix}Done. {total} penalties created."))

    def _process(self, emp, year, month, first, last, dry):
        from collections import defaultdict

        # Get all irregular days this month
        all_irregular = list(
            Attendance.objects.filter(
                user=emp.user,
                date__gte=first, date__lte=last,
                status__in=['Missing Checkout', 'Incomplete'],
            ).order_by('date')
        )

        # Group by category (via system_type)
        by_category = defaultdict(list)
        for att in all_irregular:
            cat = self._category_for(emp, att)
            if cat and cat.over_limit_action == 'auto_deduct':
                by_category[cat].append(att)

        created = 0
        for cat, days in by_category.items():
            # First `monthly_limit` days are free (self-service quota)
            over_quota_days = days[cat.monthly_limit:]

            for att in over_quota_days:
                # Skip if this day was regularized (approved)
                if RegularizationRequest.objects.filter(
                    user=emp.user, date=att.date, status='Approved',
                ).exists():
                    continue

                if self._create_penalty(emp, att, cat, year, month, dry):
                    created += 1

        return created

    def _category_for(self, emp, att):
        sys_type = 'forgot_checkout' if att.check_in_time else 'miss_punch'
        return RegularizationCategory.objects.filter(
            company=emp.company, system_type=sys_type, is_active=True,
        ).first()

    def _create_penalty(self, emp, att, cat, year, month, dry):
        penalty = Decimal(str(cat.penalty_days or Decimal('0.50')))
        if penalty <= 0:
            return False

        _sal = EmployeeSalary.objects.filter(employee=emp, status='active').first()
        if not _sal:
            self.stdout.write(self.style.WARNING(
                f"  ! No salary config for {emp.employee_id} — skipping."
            ))
            return False

        gross = Decimal(str(
            (_sal.basic_salary or 0) + (_sal.hra or 0) + (_sal.allowance or 0)
        ))
        wd = self._working_days(emp, year, month)
        per_day = (gross / Decimal(str(wd))).quantize(Decimal('0.01')) if wd else Decimal('0')

        available = Decimal('0')
        if cat.target_leave_type:
            bal = get_leave_balance(emp.user, cat.target_leave_type, year=year)
            available = max(Decimal('0'), bal.get('available', Decimal('0')))

        leave_days = min(available, penalty)
        remainder = penalty - leave_days

        lop_days = Decimal('0')
        salary_amount = Decimal('0')
        if remainder > 0 and cat.insufficient_balance_action == 'lop':
            lop_days = remainder
            salary_amount = (per_day * remainder).quantize(Decimal('0.01'))

        if leave_days <= 0 and lop_days <= 0 and salary_amount <= 0:
            return False

        if dry:
            self.stdout.write(
                f"  [DRY] {emp.employee_id} {att.date} -> {penalty}d "
                f"(leave={leave_days}, lop={lop_days}, Rs.{salary_amount})"
            )
            return True

        LateDeduction.objects.create(
            employee=emp,
            company=emp.company,
            attendance_date=att.date,
            deduction_type='LEAVE' if leave_days > 0 else 'SALARY',
            penalty_days=penalty,
            leave_type=cat.target_leave_type,
            leave_days=leave_days,
            lop_days=lop_days,
            salary_amount=salary_amount,
            status='PENDING_PAYROLL' if lop_days > 0 else 'APPLIED',
            source='REG_OVERAGE',
        )
        self.stdout.write(
            f"  OK {emp.employee_id} {att.date} -> {penalty}d "
            f"(leave={leave_days}, lop={lop_days})"
        )
        return True

    def _working_days(self, emp, year, month):
        wd = 0
        _, last = monthrange(year, month)
        flags = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        for d in range(1, last + 1):
            dd = date(year, month, d)
            if emp.shift and getattr(emp.shift, flags[dd.weekday()], False):
                wd += 1
        return wd