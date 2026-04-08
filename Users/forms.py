from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, Profile
class UserRoleForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['user_type', 'is_active', 'is_staff']
        widgets = {
            'user_type': forms.Select(attrs={'class': 'form-select'}),
        }
# Member registration form
class MemberRegistrationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'password1', 'password2')  # user_type removed

from django import forms
from .models import Profile

class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ('phone_number', 'id_number', 'membership_number', 'pf_number', 'gender', 'address')

    def __init__(self, *args, **kwargs):
        super(ProfileForm, self).__init__(*args, **kwargs)
        
        # Define specific placeholders
        placeholders = {
            'phone_number': 'e.g. 254712345678',
            'id_number': 'Enter National ID Number',
            'membership_number': 'e.g. ELDO-1234',
            'pf_number': 'e.g. 2021N00028',
            'address': 'Enter your physical address',
        }

        for field_name, placeholder_text in placeholders.items():
            if field_name in self.fields:
                self.fields[field_name].widget.attrs.update({
                    'placeholder': placeholder_text,
                    'class': 'form-control' # Adds Bootstrap styling
                })
        
        # Special handling for the Gender dropdown class
        if 'gender' in self.fields:
            self.fields['gender'].widget.attrs.update({'class': 'form-select'})

class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['username','first_name', 'last_name'] # The "remaining" fields
class LoginForm(forms.Form):
    Email = forms.CharField(
        widget=forms.EmailInput(
            attrs={
                "placeholder": "Email",
                "class": "form-control"
            }
        ))
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Password",
                "class": "form-control"
            }
        ))
