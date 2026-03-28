from django.shortcuts import redirect
from .models import CashierShiftSession


class ActiveShiftMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/billing/") and request.user.is_authenticated:
            if not CashierShiftSession.objects.filter(
                opened_by=request.user, status="open"
            ).exists():
                return redirect("billing:open_shift")
        return self.get_response(request)
