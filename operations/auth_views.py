from django.contrib.auth.views import LoginView


class RememberingLoginView(LoginView):
    template_name = "registration/login.html"
    remember_cookie_name = "mining_erp_username"
    idle_timeout_seconds = 60 * 60

    def form_valid(self, form):
        remember_me = self.request.POST.get("remember_me") == "on"
        response = super().form_valid(form)
        self.request.session.set_expiry(self.idle_timeout_seconds)
        if remember_me:
            response.set_cookie(
                self.remember_cookie_name,
                form.cleaned_data.get("username", ""),
                max_age=60 * 60 * 24 * 30,
                samesite="Lax",
            )
        else:
            response.delete_cookie(self.remember_cookie_name)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["remembered_username"] = self.request.COOKIES.get(
            self.remember_cookie_name, ""
        )
        return context
