from django import forms
from .models import *
from Users.models import Profile

class LoanApplicationForm(forms.ModelForm):

    guarantors = forms.ModelMultipleChoiceField(
        queryset=Profile.objects.none(),
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2'}),
        help_text="Hold Ctrl (or Cmd) to select multiple members"
    )

    def __init__(self, *args, **kwargs):   # ✅ FIXED (was *ar)
        user_profile = kwargs.pop('user_profile', None)
        super().__init__(*args, **kwargs)

        if user_profile:
            self.fields['guarantors'].queryset = Profile.objects.exclude(id=user_profile.id)

    # ✅ MUST BE INSIDE THE CLASS
    class Meta:
        model = Loan
        fields = ['purpose', 'amount', 'duration_months', 'interest_rate']
        widgets = {
            'purpose': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 50000'}),
            'duration_months': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Months'}),
            'interest_rate': forms.NumberInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
        }
class SavingsForm(forms.ModelForm):
    class Meta:
        model = MonthlyContribution
        # Exclude 'member' because we set it automatically in the view
        fields = ['amount', 'month'] 
        widgets = {
            'month': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control'}),
        }
class LoanForm(forms.ModelForm):
    class Meta:
        model =Loan
        fields='__all__'
class LoanPurposeForm(forms.ModelForm):
    class Meta:
        model= LoanPurpose
        fields='__all__'

class LoanRepaymentForm(forms.ModelForm):
    class Meta:
        model = LoanRepayment
        fields = ['loan', 'amount_paid', 'reference']
        widgets = {
            'loan': forms.Select(attrs={'class': 'form-select'}),
            'amount_paid': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Amount to pay'}),
            'reference': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'M-Pesa / Bank Ref'}),
        }
    def __init__(self, *args, **kwargs):
        user_profile = kwargs.pop('user_profile', None)
        super().__init__(*args, **kwargs)
        if user_profile:
          # Only show loans that are Approved and not yet fully Completed
            self.fields['loan'].queryset = Loan.objects.filter(
                member=user_profile, 
                status='approved'
            )
# class SharesForm(forms.ModelForm):
#     class Meta:
#         model =SharePurchase
#         fields='__all__'
        
# class SettinForm(forms.ModelForm):
#     class Meta:
#         model= LoanSetting
#         fields='__all__'