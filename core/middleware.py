import ipaddress
import logging
from .models import EmployeeProfile

logger = logging.getLogger(__name__)


class CompanyMiddleware:
    """
    Attach the current user's company to every request.

    - Superuser → request.user_company = None  (can access all companies)
    - HR Admin / Manager / Employee → request.user_company = their company
    - Unauthenticated → None

    SECURITY:
      * Narrowed exception (DoesNotExist is normal, everything else logs).
      * Uses company_id to avoid an extra DB query.
      * Silently swallowing all errors is dangerous — a broken profile
        would leave user_company = None, and downstream code MUST fail-closed.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user_company = None
        request.company = None

        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            # Superuser = platform admin, no company restriction
            if user.is_superuser:
                request.user_company = None
            else:
                try:
                    profile = user.profile
                    if profile and profile.company_id:
                        request.user_company = profile.company
                        request.company = profile.company
                except EmployeeProfile.DoesNotExist:
                    # Legitimate case — user without a profile (setup incomplete)
                    pass
                except Exception as e:
                    # Unexpected — log it, don't hide it
                    logger.error(
                        f"CompanyMiddleware failed for user_id={user.pk}: {e}",
                        exc_info=True,
                    )

        return self.get_response(request)