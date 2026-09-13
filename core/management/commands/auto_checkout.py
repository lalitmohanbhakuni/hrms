"""
Auto-flag open check-ins as 'Missing Checkout'.

IMPORTANT: This command does NOT fabricate check-out times.
- check_out_time stays null
- total_working_time stays null
- status changes to 'Missing Checkout'
- Employee must regularize to close the day
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta

from core.models import Attendance


def _to_time(val):
    """Normalize str / time / None to a datetime.time."""
    if val is None or val == '':
        return None
    if hasattr(val, 'hour'):
        return val
    from django.utils.dateparse import parse_time
    return parse_time(str(val))


def compute_auto_checkout_threshold(attendance, shift):
    """
    Return the datetime after which an unclosed attendance
    should be flagged as 'Missing Checkout'.

    Formula:
        shift_end + grace_period + overtime_limit (if OT) + 1 hour
    """
    if not attendance.date:
        return None

    # No shift → 24 hours after check-in
    if not shift or not shift.end_time:
        if attendance.check_in_time:
            return attendance.check_in_time + timedelta(hours=24)
        return None

    end_t = _to_time(shift.end_time)
    if not end_t:
        return None

    shift_end_dt = timezone.make_aware(
        datetime.combine(attendance.date, end_t)
    )

    grace   = timedelta(minutes=shift.grace_period or 0)
    cushion = timedelta(hours=1)

    ot = timedelta(0)
    if shift.overtime_allowed and shift.overtime_limit:
        try:
            ot = timedelta(hours=float(shift.overtime_limit))
        except (TypeError, ValueError):
            ot = timedelta(0)

    return shift_end_dt + grace + ot + cushion


class Command(BaseCommand):
    help = (
        'Flag forgotten check-outs as "Missing Checkout". '
        'Does NOT fabricate check-out times.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Print each flagged record',
        )

    def handle(self, *args, **options):
        now = timezone.now()

        # ─── Find ALL open check-ins (not just today) ───
        open_records = Attendance.objects.filter(
            state='checked_in',
            check_out_time__isnull=True,
        ).select_related('user__profile__shift')

        flagged = 0

        for att in open_records:
            profile = getattr(att.user, 'profile', None)
            shift   = profile.shift if profile else None

            threshold = compute_auto_checkout_threshold(att, shift)

            if threshold and now >= threshold:
                # ⚠️ Do NOT set check_out_time — leave it null
                # ⚠️ Do NOT set total_working_time — leave it null
                att.status = 'Missing Checkout'
                att.state  = 'auto_checked_out'
                att.save(update_fields=['status', 'state'])

                flagged += 1

                if options['verbose']:
                    self.stdout.write(
                        f'  → {att.user.username} | {att.date} | '
                        f'in={att.check_in_time.strftime("%H:%M")} | '
                        f'threshold={threshold.strftime("%d %b %H:%M")}'
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f'Auto-checkout complete. Flagged {flagged} record(s).'
            )
        )