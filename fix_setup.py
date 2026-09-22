import re
from pathlib import Path

path = Path('core/views.py')
src  = path.read_text()

new_setup = '''# ---------- Setup Page ----------

@login_required
@company_required
def setup(request):
    from .utils import get_company_filtered, get_user_company
    from .models import LateComingRule, RegularizationCategory

    user    = request.user
    company = get_user_company(request)

    # --- Late rule (single row per company) ---
    late_rule = None
    if company:
        late_rule, _ = LateComingRule.objects.get_or_create(company=company)

    # --- Save late rule on POST ---
    if request.method == 'POST' and company:
        form_type = request.POST.get('form_type')

        if form_type == 'late' and late_rule:
            late_rule.is_enabled                 = 'is_enabled' in request.POST
            late_rule.monthly_allowed_late_marks = int(request.POST.get('monthly_allowed_late_marks') or 3)
            late_rule.penalty_type               = request.POST.get('penalty_type') or 'leave'
            late_rule.penalty_amount             = Decimal(request.POST.get('penalty_amount') or '0.25')
            late_rule.half_day_cutoff_minutes    = int(request.POST.get('half_day_cutoff_minutes') or 45)
            late_rule.save()
            messages.success(request, 'Late coming rules updated.')
            return redirect('setup')

    # --- Existing lists ---
    shifts      = get_company_filtered(request, Shift.objects.all()).order_by('name')
    leave_types = get_company_filtered(request, LeaveType.objects.all()).order_by('name')
    holidays    = get_company_filtered(request, Holiday.objects.all()).order_by('date')

    # --- Dynamic regularization categories ---
    reg_categories = []
    if company:
        reg_categories = RegularizationCategory.objects.filter(
            company=company
        ).order_by('order', 'id')

    active_tab = request.GET.get('tab', 'attendance')
    if active_tab not in ('attendance', 'assign', 'leave-types', 'holidays'):
        active_tab = 'attendance'

    context = {
        'shifts':         shifts,
        'leave_types':    leave_types,
        'holidays':       holidays,
        'active_tab':     active_tab,
        'late_rule':      late_rule,
        'reg_categories': reg_categories,
    }
    return render(request, 'setup.html', context)


'''

pattern = re.compile(
    r'# ---------- Setup Page ----------.*?(?=# ---------- Shift Management)',
    re.DOTALL,
)

if not pattern.search(src):
    print("Pattern not found - aborting.")
    raise SystemExit(1)

new_src = pattern.sub(new_setup, src, count=1)

if new_src == src:
    print("No change made.")
    raise SystemExit(1)

path.write_text(new_src)
print("setup() replaced successfully.")
