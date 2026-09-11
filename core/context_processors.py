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