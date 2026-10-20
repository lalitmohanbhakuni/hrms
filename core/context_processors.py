from .models import Notification, LeaveRequest

def notification_context(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    notifications = Notification.objects.filter(
        user=user, is_read=False
    ).order_by('-created_at')[:10]
    pending_actions = []
    if user.is_superuser:
        pending_actions = LeaveRequest.objects.filter(
            status='Pending'
        ).order_by('-applied_on')[:10]
    return {
        'notifications': notifications,
        'pending_actions': pending_actions,
        'unread_count': notifications.count(),
    }
    

def company_context(request):
    """
    Makes current_company available to every template.
    Useful for showing the company name in the header.
    """
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return {
            'current_company': None,
            'is_platform_admin': False,
        }
    return {
        'current_company': getattr(request, 'user_company', None),
        'is_platform_admin': getattr(user, 'is_superuser', False),
    }



def late_rule_status(request):
    """
    Provides `late_rule_enabled` to all templates.
    True only if the user's company has an enabled Late Coming Rule.
    """
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return {'late_rule_enabled': False}

    from .models import LateComingRule, Company

    # Determine target company
    if getattr(user, 'is_superuser', False):
        company = Company.objects.first()
    else:
        profile = getattr(user, 'profile', None)
        company = getattr(profile, 'company', None)

    if not company:
        return {'late_rule_enabled': False}

    try:
        exists = LateComingRule.objects.filter(
            company=company,
            is_enabled=True,
        ).exists()
    except Exception:
        exists = False

    return {'late_rule_enabled': exists}



# ⬇️⬇️⬇️ YEH NAYA FUNCTION ADD KAREIN ⬇️⬇️⬇️

def pending_device_count(request):
    """
    Adds pending device approval count to template context
    for HR Admin / Superuser users only.
    Used in sidebar badge.
    """
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return {'pending_device_count': 0}

    # Only for HR Admin / Superuser
    if not getattr(user, 'is_superuser', False):
        profile = getattr(user, 'profile', None)
        if not profile:
            return {'pending_device_count': 0}
        role = (getattr(profile, 'role', '') or '').lower()
        if role != 'hr_admin':
            return {'pending_device_count': 0}
        company = getattr(profile, 'company', None)
    else:
        # Superuser: any company (use first, or query all)
        from .models import Company
        company = Company.objects.first()

    if not company:
        return {'pending_device_count': 0}

    try:
        from .models import EmployeeDevice
        count = EmployeeDevice.objects.filter(
            company=company,
            registration_status='pending',
        ).count()
    except Exception:
        count = 0

    return {'pending_device_count': count}