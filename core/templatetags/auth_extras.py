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