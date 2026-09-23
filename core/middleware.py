import ipaddress
import logging
from .models import EmployeeProfile
from django.http import HttpResponseForbidden


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

class URLGuardMiddleware:
    """
    Centralized URL-based access control.

    Runs AFTER AuthenticationMiddleware + CompanyMiddleware.
    Blocks users from URLs they don't have permission for, based on their group.

    Rules:
      * Superuser       → bypasses all URL checks
      * HR Admin        → can access everything except /admin/
      * Manager         → can access Team/Approvals only
      * Employee        → no admin/HR URLs
    """

    # HR Admin only (Managers blocked)
    HR_ONLY_PREFIXES = (
        '/setup/',
        '/employees/',
        '/shifts/',
        '/leave-types/',
        '/holidays/',
        '/attendance-report/',
        '/employee-attendance/',
        '/assign-shift/',
        '/payroll/',
        '/reg-category/',
    )

    # HR Admin OR Manager
    MANAGER_OR_HR_PREFIXES = (
        '/team/',
        '/admin-leaves/',
        '/leave-approve/',
        '/leave-reject/',
        '/attendance/regularize-list/',
        '/attendance/regularize-approve/',
        '/attendance/regularize-reject/',
    )

    # Superuser only
    SUPERUSER_PREFIXES = (
        '/admin/',          # Django admin
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        user = getattr(request, 'user', None)

        # Unauthenticated → let downstream views handle (login_required etc.)
        if not user or not user.is_authenticated:
            return self.get_response(request)

        # Superuser → everything except Django admin also passes
        if user.is_superuser:
            return self.get_response(request)

        is_hr  = user.groups.filter(name='HR Admin').exists()
        is_mgr = user.groups.filter(name='Manager').exists()

        # ─── Superuser-only URL ───
        for prefix in self.SUPERUSER_PREFIXES:
            if path.startswith(prefix):
                return HttpResponseForbidden("Access denied.")

        # ─── HR-only URL ───
        for prefix in self.HR_ONLY_PREFIXES:
            if path.startswith(prefix):
                if not is_hr:
                    return HttpResponseForbidden("Access denied.")
                break

        # ─── Manager or HR URL ───
        for prefix in self.MANAGER_OR_HR_PREFIXES:
            if path.startswith(prefix):
                if not (is_hr or is_mgr):
                    return HttpResponseForbidden("Access denied.")
                break

        return self.get_response(request)
        