from django.shortcuts import redirect
from functools import wraps

def treasurer_required(view_func):
    """
    Only allows users with user_type 'treasurer' or superusers to access the view.
    Redirects others to login page or member_dashboard.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')  # Redirect if not logged in
        if request.user.user_type != '3' and not request.user.is_superuser:
            return redirect('member_dashboard')  # Redirect if not staff
        return view_func(request, *args, **kwargs)
    return wrapper