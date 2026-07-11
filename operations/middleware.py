from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect


class ApiAdminLoginRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info in {"/api/", "/API/"}:
            user = getattr(request, "user", None)
            if not user or not user.is_authenticated or not user.is_staff:
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
            if request.path_info == "/API/":
                return redirect("/api/")
        return self.get_response(request)
