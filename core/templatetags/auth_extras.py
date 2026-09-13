from django import template
from django.conf import settings

register = template.Library()

@register.filter(name='has_group')
def has_group(user, group_name):
    """Check if user is in a specific group."""
    if not user.is_authenticated:
        return False
    return user.groups.filter(name=group_name).exists()

@register.filter(name='is_admin_or_hr')
def is_admin_or_hr(user):
    """Check if user is superuser OR in any ADMIN_ROLES group."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    admin_roles = getattr(settings, 'ADMIN_ROLES', ['HR Admin'])
    return user.groups.filter(name__in=admin_roles).exists()

@register.filter
def filter_action_notifications(notifications):
    """Return only notifications with notification_type='action'."""
    if not notifications:
        return []
    return [n for n in notifications if getattr(n, 'notification_type', '') == 'action']


@register.filter
def filter_info_notifications(notifications):
    """Return only notifications that are NOT action-type."""
    if not notifications:
        return []
    return [n for n in notifications if getattr(n, 'notification_type', '') != 'action']

@register.filter
def filter_unread(notifications):
    """Return only unread notifications."""
    if not notifications:
        return []
    return [n for n in notifications if not getattr(n, 'is_read', False)]
    
@register.filter(name='can_see_payroll')
def can_see_payroll(user):
    """
    Payroll visible only to Superuser, HR Admin, or Company Owner.
    Manager and Employee are excluded.
    Uses profile.role (single source of truth), NOT groups.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'profile', None)
    if not profile:
        return False
    # Both HR Admin and Company Owner have role='hr_admin'
    # (owner = hr_admin + is_company_owner=True)
    return profile.role == 'hr_admin'
    