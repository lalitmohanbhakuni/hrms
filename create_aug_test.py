cat > create_aug_test.py << 'EOF'
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hrms.settings')
django.setup()

from datetime import date, time, timedelta, datetime
from django.utils import timezone
from core.models import Attendance, EmployeeProfile

p = EmployeeProfile.objects.get(employee_id='TST002')
p_user = p.user
p_company = p.company
YEAR, MONTH = 2026, 8

deleted = Attendance.objects.filter(
    user=p_user, date__year=YEAR, date__month=MONTH
).delete()
print(f"Deleted old Aug rows: {deleted}\n")


def make_att(day, in_h, in_m, status='Present'):
    dt_in = timezone.make_aware(datetime.combine(date(YEAR, MONTH, day), time(in_h, in_m)))
    dt_out = dt_in + timedelta(hours=9)
    total = dt_out - dt_in - timedelta(hours=1)
    if status == 'Half-Day':
        total = dt_out - dt_in

    att = Attendance.objects.create(
        user=p_user,
        company=p_company,
        date=date(YEAR, MONTH, day),
        shift=p.shift,
        check_in_time=dt_in,
        check_out_time=dt_out,
        state='checked_out',
        status=status,
        total_working_time=total,
    )
    shift_start = timezone.make_aware(datetime.combine(date(YEAR, MONTH, day), p.shift.start_time))
    late = int((dt_in - shift_start).total_seconds() // 60)
    tag = "HALF-DAY" if status == 'Half-Day' else ("LATE" if late > 10 else "")
    print(f"{att.date} | in={in_h:02d}:{in_m:02d} | late={late:>3}m | {status} {tag}")


# ── Week 1: 3 free lates + 1 penalty ──
print("── WEEK 1 ──")
make_att(3,  9, 30)                  # 30m  → free #1
make_att(4,  9, 45)                  # 45m  → free #2
make_att(5, 10,  0)                  # 60m  → free #3
make_att(6, 10, 50, 'Half-Day')      # 110m → half-day penalty #1
make_att(7,  9,  0)                  # normal

# ── Week 2: 2 more >100m penalties ──
print("\n── WEEK 2 ──")
make_att(10, 11,  0, 'Half-Day')     # 120m → half-day penalty #2
make_att(11, 11, 15, 'Half-Day')     # 135m → half-day penalty #3
make_att(12,  9,  0)
make_att(13,  9,  0)
make_att(14,  9,  0)

# ── Weeks 3–5: normal ──
print("\n── WEEKS 3–5 ──")
for day in [17, 18, 19, 20, 21,
            24, 25, 26, 27, 28,
            31]:
    make_att(day, 9, 0)

total = Attendance.objects.filter(user=p_user, date__year=YEAR, date__month=MONTH).count()
print(f"\nTotal Aug rows: {total}")
EOF