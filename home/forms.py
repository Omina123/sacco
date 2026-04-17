from django import forms
from .models import *
from Users.models import Profile
from Users.models import CustomUser

class LoanApplicationForm(forms.ModelForm):
    
    DURATION_CHOICES = [(i, f"{i} Months") for i in range(1, 49)]
    
    duration_months = forms.ChoiceField(
        choices=DURATION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_duration_months'}),
        label="Loan Duration"
    )

    def __init__(self, *args, **kwargs):
        user_profile = kwargs.pop('user_profile', None)
        super().__init__(*args, **kwargs)

        if 'purpose' in self.fields:
            self.fields['purpose'].widget.attrs.update({'class': 'form-control'})

        if 'amount' in self.fields:
            self.fields['amount'].widget.attrs.update({'class': 'form-control'})

    class Meta:
        model = Loan
        fields = ['purpose', 'amount', 'duration_months']
        
class GuarantorForm(forms.ModelForm):
    class Meta:
        model = Guarantor
        fields = ['guarantor', 'guaranteed_amount']

    def __init__(self, *args, **kwargs):
        user_profile = kwargs.pop('user_profile', None)
        super().__init__(*args, **kwargs)

        if user_profile:
            self.fields['guarantor'].queryset = Profile.objects.exclude(id=user_profile.id)

class MonthlyContributionForm(forms.ModelForm):
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
    status__in=['approved', 'disbursed']
)


class SharesForm(forms.ModelForm):
    class Meta:
        model = CapitalShare
        fields = ['amount', 'month']

        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter amount e.g. 5000',
                'min': '1',
                'step': '0.01'
            }),
            'month': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
                'placeholder': 'Select contribution month'
            }),
        }
class SavingsForm(forms.ModelForm):
    class Meta:
        model = MonthlyContribution
        fields = ['amount', 'month']
        widgets = {
            'month': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control'}),
        }    
# class SettinForm(forms.ModelForm):
#     class Meta:
#         model= LoanSetting
#         fields='__all__'


class CapitalShareRefundForm(forms.ModelForm):
    class Meta:
        model = CapitalShareRefund
        fields = ['amount_requested', 'reason']

    def clean_amount_requested(self):
        amount = self.cleaned_data['amount_requested']
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than 0")
        return amount
from django import forms
from .models import Expense

class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            'expense_type', 'amount_spent', 'date_spent', 
            'payment_method', 'description', 'receipt_image'
        ]
        widgets = {
            'expense_type': forms.Select(attrs={'class': 'form-select'}),
            'amount_spent': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00'}),
            'date_spent': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_method': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'receipt_image': forms.FileInput(attrs={'class': 'form-control'}),
        }