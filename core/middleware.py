class CompanyMiddleware:
    """
    Attach the current user's company to every request.

    - Superuser → request.user_company = None  (can access all companies)
    - HR Admin / Manager / Employee → request.user_company = their company
    - Unauthenticated → None
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user_company = None
        request.company = None

        if hasattr(request, 'user') and request.user.is_authenticated:
            # Superuser = platform admin, no company restriction
            if request.user.is_superuser:
                request.user_company = None
            else:
                try:
                    profile = request.user.profile
                    if profile and profile.company:
                        request.user_company = profile.company
                        request.company = profile.company
                except Exception:
                    pass

        return self.get_response(request)