from django.db import models
from django.contrib.auth.models import AbstractUser
import random
import re
from django.core.exceptions import ValidationError

def validate_kenyan_phone(value):
    pattern = r'^2547\d{8}$'   # 2547XXXXXXXX
    if not re.match(pattern, value):
        raise ValidationError("Enter a valid phone number (e.g. 254710000000)")


class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
        ('admin', 'Admin'),
        ('staff', 'Staff'),
        ('treasurer', 'Treasurer'),
        ('member', 'Member'),
    )

    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='member')
    email = models.EmailField(unique=True)
    is_verified = models.BooleanField(default=False)
    otp = models.CharField(max_length=6, blank=True, null=True)

    def generate_otp(self):
        self.otp = str(random.randint(100000, 999999))
        self.save()

    def __str__(self):
        return self.username


class Profile(models.Model):
    GENDER_CHOICES = (
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
    )

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    phone_number = models.CharField(
        max_length=12,
        validators=[validate_kenyan_phone]
    )
    id_number = models.CharField(max_length=20)
    membership_number = models.CharField(max_length=20, unique=True, null=True)
    pf_number = models.CharField(max_length=20, unique=True, null=True)  # <-- Added PF number
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    address = models.CharField(max_length=255, blank=True, null=True)
    date_joined = models.DateField(auto_now_add=True)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        # This changes "kevin profile" to "Kevin Omina"
        return f"{self.user.get_full_name() or self.user.username}"