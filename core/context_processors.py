from .models import Notification, LeaveRequest

def notification_context(request):
    if request.user.is_authenticated:
        notifications = Notification.objects.filter(
            user=request.user, is_read=False
        ).order_by('-created_at')[:10]
        pending_actions = []
        if request.user.is_superuser:
            pending_actions = LeaveRequest.objects.filter(
                status='Pending'
            ).order_by('-applied_on')[:10]
        return {
            'notifications': notifications,
            'pending_actions': pending_actions,
            'unread_count': notifications.count(),
        }
    return {}

def company_context(request):
    """
    Makes current_company available to every template.
    Useful for showing the company name in the header.
    """
    if request.user.is_authenticated:
        return {
            'current_company': getattr(request, 'user_company', None),
            'is_platform_admin': request.user.is_superuser,
        }
    return {}



def late_rule_status(request):
    """
    Provides `late_rule_enabled` to all templates.
    True only if the user's company has an enabled Late Coming Rule.
    """
    if not request.user.is_authenticated:
        return {'late_rule_enabled': False}

    from .models import LateComingRule, Company

    # Determine target company
    if request.user.is_superuser:
        company = Company.objects.first()
    else:
        profile = getattr(request.user, 'profile', None)
        company = getattr(profile, 'company', None)

    if not company:
        return {'late_rule_enabled': False}

    exists = LateComingRule.objects.filter(
        company=company,
        is_enabled=True,
    ).exists()

    return {'late_rule_enabled': exists}
    