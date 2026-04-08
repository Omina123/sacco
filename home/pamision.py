from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps

def role_required(allowed_roles=[]):
    """
    Decorator to restrict access based on user_type.
    allowed_roles: List of strings e.g. ['1', '2']
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # 1. Check if logged in
            if not request.user.is_authenticated:
                return redirect('login')
            
            # 2. Allow Superusers always
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            # 3. Check user_type
            user_role = getattr(request.user, 'user_type', None)
            if user_role in allowed_roles:
                return view_func(request, *args, **kwargs)
            
            # 4. If unauthorized
            messages.error(request, "You do not have permission to access this page.")
            return redirect('access_denied') # Or your home page
            
        return _wrapped_view
    return decorator