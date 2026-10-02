import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hrms.settings')
django.setup()

from core.models import EmployeeProfile, LateComingRule
from core.utils import get_late_rule_for_date, get_leave_balance
from datetime import date
from decimal import Decimal

p = EmployeeProfile.objects.get(employee_id='TST002')

# 1. Rule details — especially the fields we need
rule = LateComingRule.objects.get(id=1)
print("=== RULE ===")
print(f"  is_enabled                 : {rule.is_enabled}")
print(f"  effective_from             : {rule.effective_from}")
print(f"  calculation_method         : {rule.calculation_method}")
print(f"  monthly_allowed_late_marks : {rule.monthly_allowed_late_marks}")
print(f"  penalty_type               : {rule.penalty_type}")
print(f"  penalty_amount             : {rule.penalty_amount}")
print(f"  target_leave_type          : {rule.target_leave_type}")
print(f"  insufficient_balance_action: {rule.insufficient_balance_action}")   # ← KEY
print(f"  half_day_cutoff_minutes    : {rule.half_day_cutoff_minutes}")
print()

# 2. What get_late_rule_for_date returns
rule2 = get_late_rule_for_date(p.company, date(2026, 9, 4))
print("=== get_late_rule_for_date(p.company, 2026-09-04) ===")
print(f"  → {rule2}")
print()

# 3. CL balance
print("=== LEAVE BALANCE ===")
try:
    bal = get_leave_balance(p.user, rule.target_leave_type, year=2026)
    print(f"  balance for '{rule.target_leave_type}': {bal}")
except Exception as e:
    print(f"  ERROR: {type(e).__name__} — {e}")
print()

# 4. What the function would compute for one late
penalty_days = Decimal('0.25')
available = Decimal('0')
if rule.target_leave_type:
    try:
        _bal = get_leave_balance(p.user, rule.target_leave_type, year=2026)
        available = max(Decimal('0'), _bal.get('available', Decimal('0')))
    except Exception as e:
        print(f"  get_leave_balance error: {e}")
        available = Decimal('0')

print("=== SIMULATION for one 0.25 penalty ===")
print(f"  penalty_days : {penalty_days}")
print(f"  available    : {available}")
if available >= penalty_days:
    print(f"  → FULL LEAVE, leave_days_value = {penalty_days}")
else:
    leave_days_value = available
    remainder = penalty_days - available
    print(f"  → PARTIAL, leave_days_value = {leave_days_value}, remainder = {remainder}")
    if rule.insufficient_balance_action == 'lop':
        print(f"  → insufficient_balance_action = 'lop' → lop_days_value = {remainder}")
    else:
        print(f"  → insufficient_balance_action = '{rule.insufficient_balance_action}' → lop_days_value = 0")
        print(f"  → ROW WILL BE SKIPPED (all values <= 0)")
