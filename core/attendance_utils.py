from datetime import datetime, timedelta
from django.utils import timezone
from django.utils.dateparse import parse_time

from .models import Attendance


def _to_time(val):
    """Normalize str / time / None to a datetime.time."""
    if val is None or val == '':
        return None
    if hasattr(val, 'hour'):
        return val
    return parse_time(str(val))


def compute_auto_checkout_threshold(attendance, shift):
    """
    Return the datetime after which an unclosed attendance
    should be flagged as 'Missing Checkout'.

    Formula:
        shift_end + grace_period + overtime_limit + 1 hour
    """
    if not attendance.date:
        return None

    # No shift — default to 24h after check-in
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

    grace = timedelta(minutes=shift.grace_period or 0)
    cushion = timedelta(hours=1)

    ot = timedelta(0)
    if shift.overtime_allowed and shift.overtime_limit:
        try:
            ot = timedelta(hours=float(shift.overtime_limit))
        except (TypeError, ValueError):
            ot = timedelta(0)

    return shift_end_dt + grace + ot + cushion


def flag_missing_checkouts(user=None):
    """
    Flag open check-ins that exceeded their auto-checkout threshold
    as 'Missing Checkout'.

    Returns the number of newly flagged records.
    """
    now = timezone.now()

    qs = Attendance.objects.filter(
        state='checked_in',
        check_out_time__isnull=True,
    )
    if user is not None:
        qs = qs.filter(user=user)

    qs = qs.select_related('user__profile__shift')

    flagged = 0
    for att in qs:
        profile = getattr(att.user, 'profile', None)
        shift = profile.shift if profile else None

        threshold = compute_auto_checkout_threshold(att, shift)
        if threshold and now >= threshold:
            att.status = 'Missing Checkout'
            att.state = 'auto_checked_out'      # mark as auto-closed attempt
            # NOTE: check_out_time stays null — the employee must regularize
            att.save(update_fields=['status', 'state'])
            flagged += 1

    return flagged


def mark_under_review(user, date):
    """
    Called from regularize_request view — flips
    'Missing Checkout' → 'Under Review' for a given day.
    """
    return Attendance.objects.filter(
        user=user,
        date=date,
        status='Missing Checkout',
    ).update(status='Under Review')