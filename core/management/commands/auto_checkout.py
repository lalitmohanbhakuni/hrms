from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import Attendance

class Command(BaseCommand):
    help = 'Auto-checkout users who forgot to check out at end of day'

    def handle(self, *args, **options):
        # Configurable end of day (default: 23:59:59)
        end_of_day_hour = 23
        end_of_day_minute = 59
        end_of_day_second = 59

        today = timezone.now().date()
        # Find all checked-in records for today (or previous days if they forgot)
        # We'll process today's records that are still checked in
        records = Attendance.objects.filter(
            date=today,
            status='checked_in'
        )

        for att in records:
            # Force check-out at end of day
            checkout_dt = timezone.datetime(
                today.year, today.month, today.day,
                end_of_day_hour, end_of_day_minute, end_of_day_second,
                tzinfo=timezone.get_current_timezone()
            )
            # If now is past end of day, set checkout time to end-of-day
            if timezone.now() > checkout_dt:
                att.check_out_time = checkout_dt
                att.total_working_time = att.check_out_time - att.check_in_time
                att.status = 'auto_checked_out'
                att.save()
                self.stdout.write(f'Auto-checked out {att.user.username} for {att.date}')

        self.stdout.write('Auto-checkout completed.')