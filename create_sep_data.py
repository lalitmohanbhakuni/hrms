import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hrms.settings')
django.setup()

from datetime import date, time, timedelta, datetime
from django.utils import timezone
from core.models import Attendance, EmployeeProfile

p = EmployeeProfile.objects.get(employee_id='TST002')
p_user = p.user
p_company = p.company
YEAR, MONTH = 2026, 9

deleted = Attendance.objects.filter(user=p_user, date__year=YEAR, date__month=MONTH).delete()
print(f"Deleted old rows: {deleted}\n")


def make_att(day, in_h, in_m, out_h, out_m, status='Present'):
    dt_in  = timezone.make_aware(datetime.combine(date(YEAR, MONTH, day), time(in_h, in_m)))
    dt_out = timezone.make_aware(datetime.combine(date(YEAR, MONTH, day), time(out_h, out_m)))
    total = dt_out - dt_in - timedelta(hours=1)
    if status == 'Half-Day':
        total = dt_out - dt_in

    att = Attendance.objects.create(
        user=p_user,
        company=p_company,
        date=date(YEAR, MONTH, day),
        check_in_time=dt_in,
        check_out_time=dt_out,
        state='checked_out',
        status=status,
        total_working_time=total,
    )

    shift_start = timezone.make_aware(datetime.combine(date(YEAR, MONTH, day), p.shift.start_time))
    late_min = int((dt_in - shift_start).total_seconds() // 60)
    tag = "HALF-DAY" if status == 'Half-Day' else ("LATE" if late_min > 10 else "")
    print(f"{att.date} | in={in_h:02d}:{in_m:02d} out={out_h:02d}:{out_m:02d} | late={late_min:>3}m | {status} {tag}")


print("── WEEK 1: 3 FREE + 1 PENALTY ──")
make_att(1,  9, 15, 18, 15)
make_att(2,  9, 30, 18, 30)
make_att(3,  9, 45, 18, 45)
make_att(4,  9, 20, 18, 20)

print("\n── WEEK 2: 2 PENALTY + HALF-DAY ──")
make_att(7, 10,  0, 19,  0)
make_att(8, 10, 30, 19, 30)
make_att(9, 10, 50, 19, 50, 'Half-Day')
make_att(10, 9,  0, 18,  0)
make_att(11, 9,  0, 18,  0)

print("\n── WEEKS 3–5: NORMAL ──")
for day in [14, 15, 16, 17, 18, 21, 22, 23, 24, 25, 28, 29, 30]:
    make_att(day, 9, 0, 18, 0)

total = Attendance.objects.filter(user=p_user, date__year=YEAR, date__month=MONTH).count()
print(f"\n✅ Total Sep rows: {total}")
