from django.shortcuts import redirect
from django.urls import reverse

class MembershipRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:

            profile = getattr(request.user, 'profile', None)

            if profile:

                needs_profile_update = not profile.is_profile_updated()
                needs_membership = not profile.membership_number

                if needs_profile_update:
                    allowed_paths = [
                        reverse('update_profile'),
                        reverse('Logout'),
                    ]

                    if request.path not in allowed_paths:
                        return redirect('update_profile')

                elif needs_membership:
                    allowed_paths = [
                        reverse('complete_membership'),
                        reverse('Logout'),
                    ]

                    if request.path not in allowed_paths:
                        return redirect('complete_membership')

        return self.get_response(request)