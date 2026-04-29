
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from .models import Profile  # Import your Profile model

class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()

        # 1. Try to find the user by Email
        user = UserModel.objects.filter(email=username).first()

        # 2. If not found by email, try to find by PF Number
        if not user:
            # We look into the Profile model for the pf_number
            profile = Profile.objects.filter(pf_number=username).first()
            if profile:
                user = profile.user

        # 3. Check password and return user if found
        if user and user.check_password(password):
            return user

        return None