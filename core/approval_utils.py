"""
Central approval-routing logic with Company Owner support.

Rules:
    1. Company Owner        →  self-approves (flagged)
    2. Regular HR Admin     →  Company Owner approves
    3. Manager with manager →  their manager approves
    4. Manager without mgr  →  Company Owner approves
    5. Employee with mgr    →  their manager approves
    6. Employee without mgr →  Company Owner approves
    7. No owner exists      →  fall back to other HR Admins
"""
from django.contrib.auth.models import User
from .models import EmployeeProfile, Notification


def _notify(user, company, msg, obj, related_type):
    """Create a single action notification."""
    Notification.objects.create(
        user=user,
        company=company,
        message=msg,
        notification_type='action',
        related_object_id=obj.id,
        related_object_type=related_type,
    )


def get_company_owner(company):
    """Return the EmployeeProfile that is the company owner, or None."""
    if not company:
        return None
    return (
        EmployeeProfile.objects.filter(
            company=company,
            is_company_owner=True,
            user__is_active=True,
        )
        .select_related('user')
        .first()
    )


def get_approvers(requester, company):
    """
    Return a list of users who should approve `requester`'s request.

    Rules:
      Company Owner       → [] (self-approve)
      HR Admin            → Company Owner (or peers if no owner)
      Manager             → ALL HR Admins
      Employee with mgr   → their manager
      Employee w/o mgr    → ALL HR Admins
    """
    requester_id = requester.id
    profile = getattr(requester, 'profile', None)
    role = profile.role if profile else None
    owner = get_company_owner(company)

    def hr_admins_excluding_self():
        """All active HR Admins in company except the requester."""
        return list(
            User.objects.filter(
                profile__role='hr_admin',
                profile__company=company,
                profile__is_active=True,
                is_active=True,
            ).exclude(id=requester_id).distinct()
        )

    # ─── 1. Company Owner → self-approve ───
    if profile and profile.is_company_owner:
        return []

    # ─── 2. HR Admin → Company Owner ───
    if role == 'hr_admin' or requester.groups.filter(name='HR Admin').exists():
        if owner and owner.user_id != requester_id:
            return [owner.user]
        # No owner → peers (other HR Admins)
        return hr_admins_excluding_self()

    # ─── 3. Manager → ALL HR Admins ───
    if role == 'manager' or requester.groups.filter(name='Manager').exists():
        return hr_admins_excluding_self()

    # ─── 4. Employee with manager → that manager ───
    if profile and profile.manager and profile.manager.user.is_active:
        return [profile.manager.user]

    # ─── 5. Employee without manager → ALL HR Admins ───
    return hr_admins_excluding_self()


def notify_approvers(request, company, msg, obj, related_type=None):
    """
    Notify the correct approver(s).

    Returns (approvers, self_approved_flag).
    - approvers: list of notified User objects
    - self_approved: True if the owner auto-approved their own request
    """
    if related_type is None:
        related_type = obj._meta.model_name

    approvers = get_approvers(request.user, company)
    profile = getattr(request.user, 'profile', None)

    # ─── Owner self-approves ───
    if not approvers and profile and profile.is_company_owner:
        obj.status = 'Approved'
        if hasattr(obj, 'is_self_approved'):
            obj.is_self_approved = True
        obj.save()

        Notification.objects.create(
            user=request.user,
            company=company,
            message=(
                "Your request was auto-approved as Company Owner. "
                "It has been flagged for audit."
            ),
            notification_type='info',
        )
        return ([], True)

    # ─── Notify normal approvers ───
    for user in approvers:
        _notify(user, company, msg, obj, related_type)

    return (approvers, False)
