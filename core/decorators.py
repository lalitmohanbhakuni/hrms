from django.contrib.auth.decorators import user_passes_test
from django.conf import settings
from django.shortcuts import redirect
from django.contrib import messages

def is_admin_or_hr(user):
    """
    Check if user is superuser OR in any ADMIN_ROLES group.
    This includes Managers.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    admin_roles = getattr(settings, 'ADMIN_ROLES', ['HR Admin'])
    return user.groups.filter(name__in=admin_roles).exists()

def admin_or_hr_required(view_func):
    """
    Decorator for views that require admin or HR roles.
    Allows: Superuser, HR Admin, Manager, and other ADMIN_ROLES.
    """
    return user_passes_test(is_admin_or_hr)(view_func)


def is_hr_admin_or_superuser(user):
    """
    Stricter check: Only Superuser or HR Admin (NOT Manager).
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name='HR Admin').exists()

def hr_admin_required(view_func):
    """
    Decorator for views that require Superuser or HR Admin ONLY.
    Managers are NOT allowed.
    """
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.is_superuser or request.user.groups.filter(name='HR Admin').exists():
            return view_func(request, *args, **kwargs)
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard')
    return wrapper