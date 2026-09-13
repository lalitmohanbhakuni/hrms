# core/roles.py
"""
Central role helpers. Single source of truth for role checks.
Role strings in DB: 'employee' | 'manager' | 'hr_admin'
Company Owner = hr_admin + is_company_owner=True
"""


def get_role(user):
    """Return effective role string, or None."""
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'superuser'
    profile = getattr(user, 'profile', None)
    if not profile:
        return None
    if profile.role == 'hr_admin' and getattr(profile, 'is_company_owner', False):
        return 'company_owner'
    return profile.role


def is_hr_admin(user):
    """hr_admin OR company_owner OR superuser."""
    return get_role(user) in ('hr_admin', 'company_owner', 'superuser')


def is_company_owner(user):
    return get_role(user) in ('company_owner', 'superuser')


def is_manager(user):
    return get_role(user) == 'manager'


def can_approve_leave_for(approver, applicant):
    """
    Returns True if `approver` may approve `applicant`'s leave.
    Enforces the full approval matrix.
    """
    if approver.id == applicant.id:
        return False

    a_role = get_role(approver)
    u_role = get_role(applicant)

    if a_role == 'superuser':
        return True

    # Company Owner's own leave → auto-approved, never in queue
    if u_role == 'company_owner':
        return False

    # HR Admin's leave → only Company Owner can approve
    if u_role == 'hr_admin':
        return a_role == 'company_owner'

    # Manager's leave → HR Admin or Company Owner
    if u_role == 'manager':
        return a_role in ('hr_admin', 'company_owner')

    # Employee's leave → their assigned manager, or HR Admin / Owner
    if u_role == 'employee':
        if a_role == 'manager':
            ap = getattr(approver, 'profile', None)
            up = getattr(applicant, 'profile', None)
            return (
                ap is not None
                and up is not None
                and up.manager_id == ap.id
            )
        return a_role in ('hr_admin', 'company_owner')

    return False