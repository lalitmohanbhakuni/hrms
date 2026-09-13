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

    Returns [] for the company owner (self-approval case).
    """
    requester_id = requester.id
    profile = getattr(requester, 'profile', None)
    owner = get_company_owner(company)

    # ─── 1. Company Owner → self-approve ───
    if profile and profile.is_company_owner:
        return []

    # ─── 2. Regular HR Admin → Company Owner ───
    if requester.groups.filter(name='HR Admin').exists():
        if owner and owner.user_id != requester_id:
            return [owner.user]

        # No owner yet → peers (or nobody)
        peers = list(
            User.objects.filter(
                groups__name='HR Admin',
                profile__company=company,
                is_active=True,
            )
            .exclude(id=requester_id)
            .distinct()
        )
        return peers

    # ─── 3. Has a manager → that manager ───
    if profile and profile.manager:
        return [profile.manager.user]

    # ─── 4. No manager → Company Owner ───
    if owner:
        return [owner.user]

    # ─── 5. Fallback → all HR Admins ───
    return list(
        User.objects.filter(
            groups__name='HR Admin',
            profile__company=company,
            is_active=True,
        ).distinct()
    )


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
