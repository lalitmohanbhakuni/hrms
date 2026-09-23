import ipaddress
import logging
from .models import EmployeeProfile

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
#  CLIENT IP MIDDLEWARE
#  Resolves the real client IP behind Cloudflare/Render proxies.
#  Must run BEFORE CommonMiddleware/CsrfViewMiddleware so that
#  django-ratelimit sees a valid HTTP_X_FORWARDED_FOR header.
# ═══════════════════════════════════════════════════════════

class ClientIPMiddleware:
    """
    Resolve the real client IP safely.

    Priority:
      1. CF-Connecting-IP           (Cloudflare — unspoofable)
      2. Last IP in X-Forwarded-For (Render proxy appended)
      3. REMOTE_ADDR                (local dev — no proxy)

    Always writes a valid IP to request.META['HTTP_X_FORWARDED_FOR']
    so downstream consumers (django-ratelimit, logging) never crash.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        client_ip = self._get_client_ip(request)

        # Fallback if all headers missing (local dev)
        if not client_ip:
            client_ip = self._clean(request.META.get('REMOTE_ADDR'))

        # Final fallback — never crash
        if not client_ip:
            client_ip = '127.0.0.1'

        request.META['HTTP_X_FORWARDED_FOR'] = client_ip
        request.META['CLIENT_IP'] = client_ip

        return self.get_response(request)

    @staticmethod
    def _get_client_ip(request):
        # 1. Cloudflare — single, unspoofable IP
        cf_ip = ClientIPMiddleware._clean(
            request.META.get('HTTP_CF_CONNECTING_IP')
        )
        if cf_ip:
            return cf_ip

        # 2. X-Forwarded-For — trust the LAST IP (appended by proxy)
        xff = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
        if xff:
            parts = [p.strip() for p in xff.split(',') if p.strip()]
            if parts:
                return ClientIPMiddleware._clean(parts[-1])

        # 3. REMOTE_ADDR
        return ClientIPMiddleware._clean(request.META.get('REMOTE_ADDR'))

    @staticmethod
    def _clean(value):
        """Strip CIDR mask + validate IP. Returns None if invalid."""
        if not value:
            return None
        value = value.strip()
        if '/' in value:
            value = value.split('/')[0]
        try:
            ipaddress.ip_address(value)
            return value
        except ValueError:
            return None


# ═══════════════════════════════════════════════════════════
#  COMPANY MIDDLEWARE
#  Attaches request.user_company for multi-tenant isolation.
#  Must run AFTER AuthenticationMiddleware.
# ═══════════════════════════════════════════════════════════

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