from django.db import models
from django.contrib.auth.models import AbstractUser
import random
import re
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator

def validate_kenyan_phone(value):
    pattern = r'^2547\d{8}$' 
    if not re.match(pattern, value):
        raise ValidationError("Enter a valid phone number (e.g. 254710000000)")

def validate_pf_number(value):
    # Matches: 1-4 digits, then 'N', then any number of digits
    # Example: 1N123, 2024N55, 21N00028
    pattern = r'^\d{1,4}N\d+$'
    if not re.match(pattern, value):
        raise ValidationError(
            "PF Number must start with 1-4 digits followed by 'N' and more digits (e.g., 2024N001)."
        )

def validate_membership_range(value):
    # Ensures the string entered is a number between 1 and 1000
    try:
        num = int(value)
        if num < 1 or num > 1000:
            raise ValidationError("Membership number must be between 1 and 1000.")
    except ValueError:
        raise ValidationError("Membership number must be a valid numeric value.")

class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
        ('1', 'Admin'),
        ('2', 'Staff'),
        ('3', 'Treasurer'),
        ('4', 'Member'),
    )
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='4')
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
    
    # Updated Membership Number with range validation
    membership_number = models.CharField(
        max_length=20, 
        unique=True, 
        null=True,
        validators=[validate_membership_range]
    )
    
    # Updated PF Number with flexible year/prefix validation
    pf_number = models.CharField(
        max_length=20, 
        unique=True,  
        validators=[validate_pf_number]
    )
    
    # Added Date of Birth
    date_of_birth = models.DateField(null=True, blank=True)
    
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    address = models.CharField(max_length=255, blank=True, null=True)
    date_joined = models.DateField(auto_now_add=True)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username}"