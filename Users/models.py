from decimal import Decimal

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
    # Matches: 
    # 1. ^\d{1,4} -> 1 to 4 digits at the start
    # 2. [a-zA-Z]{3} -> Exactly 3 letters (A-Z or a-z) in any order
    # 3. \d+$ -> One or more digits at the end
    # Examples: 123PTA001, 2024pTo55, 21XYZ00028
    
    pattern = r'^\d{1,4}[a-zA-Z]{1,3}\d+$'
    
    if not re.match(pattern, value):
        raise ValidationError(
            "PF Number must start with 1-4 digits, followed by exactly 3 letters "
            "(e.g., PTA, pTo) and then more digits (e.g., 2024PTA001)."
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
        ('5', 'Human Resource'),
    )
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='4')
    email = models.EmailField(unique=True, blank=False, null=False)
    is_verified = models.BooleanField(default=False)
    otp = models.CharField(max_length=6, blank=True, null=True)

    def generate_otp(self):
        self.otp = str(random.randint(100000, 999999))
        self.save()

    def __str__(self):
        return self.username
    # def generate_otp(self):
    #     self.otp = str(random.randint(100000, 999999))
    #     self.save()

class Profile(models.Model):
    GENDER_CHOICES = (
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
    )
    EMPLOYMENT_CHOICES = (
        ('PERMANENT', 'Permanent & Pensionable'),
        ('CONTRACT', 'Contract Terms'),
    )
    employment_status = models.CharField(
        max_length=20, 
        choices=EMPLOYMENT_CHOICES, 
        default='PERMANENT'
    )
    contract_expiry = models.DateField(
        null=True, 
        blank=True, 
        help_text="Required only for contract-based members"
    )

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    phone_number = models.CharField(
        max_length=12,blank=True, null=True,
        validators=[validate_kenyan_phone]
    )
    id_number = models.CharField(max_length=20)
    
    # Updated Membership Number with range validation


    membership_number = models.CharField(
    max_length=20,
    unique=True,
    blank=True,
    null=True
)
    # Updated PF Number with flexible year/prefix validation
    pf_number = models.CharField(
        max_length=20, 
        unique=True,
        null=True,
        blank=True,  
        validators=[validate_pf_number]
    )
    
    # Added Date of Birth
    date_of_birth = models.DateField(null=True, blank=True)
    next_of_kin = models.CharField(max_length=255, blank=True, null=True)   
    Next_of_kin_phone = models.CharField(
        max_length=12,
        validators=[validate_kenyan_phone],
        blank=True,
        null=True
    )
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    address = models.CharField(max_length=255, blank=True, null=True)
    date_joined = models.DateField(auto_now_add=True)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    gross_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    salary_needs_review = models.BooleanField(default=False)
    monthly_saving_target = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    share_goal = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    month = models.DateField(null=True, blank=True )
    agreed_to_declaration = models.BooleanField(default=False)
    declaration_timestamp = models.DateTimeField(null=True, blank=True)


    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username}"
    def is_profile_updated(self):
        required_fields = [
        self.phone_number,
        self.address,
        self.pf_number,
        
    ]
        return all(required_fields)
    def can_access_sacco_services(self):
        """
        Ensures the member has both updated their details 
        AND signed the legal declaration.
        """
        return self.is_profile_updated() and self.agreed_to_declaration