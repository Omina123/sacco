from django.db import models
from Users.models import Profile

import uuid
import datetime
from django.core.validators import MinValueValidator,MaxValueValidator
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum

def generate_transaction_ref(prefix="TX"):
    """Generates a unique reference: TX-20260313-ABC123"""
    date_str = datetime.datetime.now().strftime('%Y%m%d')
    unique_id = str(uuid.uuid4()).upper()[:6]
    return f"{prefix}-{date_str}-{unique_id}"
# -------------------------
# SHARE SETTINGS
# -------------------------
class ShareSettings(models.Model):

    minimum_shares = models.DecimalField(max_digits=10, decimal_places=2)
    share_value = models.DecimalField(max_digits=10, decimal_places=2)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Share Value {self.share_value}"


# -------------------------
# CAPITAL SHARES
# -------------------------
class CapitalShare(models.Model):

    member = models.ForeignKey(Profile, on_delete=models.CASCADE)

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    month =models.DateField()
    date_created=models.DateTimeField(auto_now_add=True)

    

    def __str__(self):
        return f"{self.member} - {self.amount}"


# -------------------------
# MONTHLY CONTRIBUTIONS
# -------------------------
class MonthlyContribution(models.Model):

    member = models.ForeignKey(Profile, on_delete=models.CASCADE,related_name='saving_records')

    amount = models.IntegerField(null=True, blank=True)

    month = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.member} - {self.month}"

class XmasLoan(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('disbursed', 'Disbursed'),
        ('partially_approved', 'Partially Approved'),
        ('cleared', 'Cleared'),
        ('rejected', 'Rejected'),
    ]

    member = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='xmas_loans')
    amount_requested = models.DecimalField(max_digits=12, decimal_places=2)
    # Updated default to 25.9
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=25.9) 
    repayment_period = models.IntegerField(default=3) 
    application_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    year = models.IntegerField(default=timezone.now().year)
    staff_approved = models.BooleanField(default=False)
    treasurer_approved = models.BooleanField(default=False)
    admin_approved = models.BooleanField(default=False)
    
    approval_date = models.DateTimeField(null=True, blank=True)
    disbursement_date = models.DateTimeField(null=True, blank=True)
    installments = models.IntegerField(default=1) # Duration in months
    is_disbursed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('member', 'year')
        
    def monthly_installment(self):
        """Calculates the fixed monthly payment."""
        if self.installments > 0:
            return self.total_payable / self.installments
        return self.total_payable

    @property
    def monthly_installment(self):
        """Calculates the fixed monthly payment."""
        if self.installments > 0:
            return self.total_payable / self.installments
        return self.total_payable

    @property
    def max_eligible_amount(self):
        from .models import MonthlyContribution 
        total_saved = MonthlyContribution.objects.filter(member=self.member).aggregate(
            Sum('amount')
        )['amount__sum'] or Decimal('0.00')
        return total_saved * Decimal('0.259')

    @property
    def approval_progress(self):
        return sum([self.admin_approved, self.staff_approved, self.treasurer_approved])

    @property
    def is_fully_approved(self):
        return self.staff_approved and self.treasurer_approved and self.admin_approved

    @property
    def total_interest(self):
        """Interest = Principal * 25.9%"""
        return self.amount_requested * (self.interest_rate / Decimal('100'))

    @property
    def total_payable(self):
        """Principal + 25.9% Interest"""
        return self.amount_requested + self.total_interest

    @property
    def total_paid(self):
        """Sums all repayments linked to this member's Xmas loan for this specific year"""
        from .models import LoanRepayment
        return LoanRepayment.objects.filter(
            member=self.member, 
            is_xmas=True,
            payment_date__year=self.year # Matches the repayment to the loan year
        ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

    @property
    def remaining_balance(self):
        """Calculates balance without needing an ID"""
        balance = self.total_payable - self.total_paid
        return max(balance, Decimal('0.00'))

    def __str__(self):
        return f"Xmas Loan {self.year} - {self.member.user.username}"
# -------------------------
# LOAN PURPOSES
# -------------------------
class LoanPurpose(models.Model):
    

    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name



    def __str__(self):
        return f"Loan {self.loan.id} Installment {self.installment_number}"
# -------------------------
# LOANS
# -------------------------
class Loan(models.Model):

    STATUS = (
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('partially_approved', 'Partially Approved'),
    ('disbursed', 'Disbursed'),
    ('defaulted', 'Defaulted'),
    ('completed', 'Completed'),
    ('rejected', 'Rejected'),
)
    purpo=(
        ('normal Loan', 'Normal Loan'),
        ('choll fees', 'Scholl fees'),
        ('emergency', 'Emergency'),
        ('personal', 'Personal'),
        
    )

    member = models.ForeignKey(Profile, on_delete=models.CASCADE,related_name="member_loans")

    purpose = models.CharField(max_length=50, choices=purpo,default='normal Loan')
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    Othes_Guarantor = models.CharField(max_length=56,blank=True,null=True)
    interest_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('12.00'))  # Default interest rate of 12%
    insurance= models.DecimalField(max_digits=10,decimal_places=2 , null=True, blank=True)
    interest= models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_topup = models.BooleanField(default=False)
    replaces_loan = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)

    duration_months = models.IntegerField(
        
        validators=[MinValueValidator(1),
                    MaxValueValidator(48)])

    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    admin_approved = models.BooleanField(default=False)
    staff_approved = models.BooleanField(default=False)
    treasurer_approved = models.BooleanField(default=False)

    # approval_count = models.IntegerField(default=0)
    

    application_date = models.DateTimeField(auto_now_add=True)

    approval_date = models.DateTimeField(null=True, blank=True)
    is_disbursed = models.BooleanField(default=False)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    @property
    def approval_count(self):
        return sum([
            self.admin_approved,
            self.staff_approved,
            self.treasurer_approved
        ])
    @property
    def insurance_fee(self):
        """25.9% of the principal loan amount"""
        return self.amount * Decimal('0.259')
    @property
    def total_payable(self):
        """Principal + Interest + Insurance"""
        # Ensure values aren't None before calculating
        interest = self.interest if self.interest else Decimal('0.00')
        insurance = self.insurance if self.insurance else Decimal('0.00')
        return self.amount + interest + insurance

    @property
    def monthly_installment(self):
        """Calculates the fixed monthly payment (Total Payable / Duration)"""
        if self.duration_months and self.duration_months > 0:
            return self.total_payable / Decimal(self.duration_months)
        return Decimal('0.00')

    
    def __str__(self):
        return f"Loan {self.id} - {self.member}"


# -------------------------
# GUARANTORS
# -------------------------
class Guarantor(models.Model):
    STATUS = (
        ('pending', 'Pending Response'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('partially_approved', 'Partially Approved'),
    )

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE)
    guarantor = models.ForeignKey(Profile, on_delete=models.CASCADE)
    guaranteed_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS, default='pending')

    def __str__(self):
        return f"{self.guarantor} - {self.status} for Loan {self.loan.id}"

    @staticmethod
    def available_guarantors():
        # Exclude those with active loans
        used_guarantors = Guarantor.objects.filter(
            loan__status__in=['pending', 'approved', 'disbursed'],
            status='accepted'
        ).values_list('guarantor_id', flat=True)
        return Profile.objects.exclude(id__in=used_guarantors)

# -------------------------
# LOAN REPAYMENT SCHEDULE
# -------------------------
class LoanRepaymentSchedule(models.Model):
    is_xmas = models.BooleanField(default=False)
    xmas_loan = models.ForeignKey(XmasLoan, on_delete=models.CASCADE, null=True, blank=True, related_name='schedules')

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE,null=True, blank=True)

    installment_number = models.IntegerField()
    

    due_date = models.DateField()

    amount_due = models.DecimalField(max_digits=10, decimal_places=2)

    is_paid = models.BooleanField(default=False)

    def __str__(self):
        if self.is_xmas:
            return f"Xmas Loan {self.xmas_loan.id} Installment {self.installment_number}"
        return f"Loan {self.loan.id} Installment {self.installment_number}"


# -------------------------
# LOAN REPAYMENTS
# -------------------------
class LoanRepayment(models.Model):

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE,null=True,blank=True)

    member = models.ForeignKey(Profile, on_delete=models.CASCADE)

    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)

    payment_date = models.DateTimeField(auto_now_add=True)

    reference = models.CharField(max_length=100, blank=True, null=True)
    is_xmas = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.member} - {self.amount_paid}"


# -------------------------
# TRANSACTIONS
# -------------------------
class Transaction(models.Model):

    TRANSACTION_TYPES = (
        ('deposit', 'Deposit'),
        ('loan', 'Loan Disbursement'),
        ('repayment', 'Loan Repayment'),
        ('shares', 'Share Capital'),
    )

    member = models.ForeignKey(Profile, on_delete=models.CASCADE)

    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    reference = models.CharField(max_length=100, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.member} - {self.transaction_type}"
class ActivityLog(models.Model):

    user = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True)

    action = models.CharField(max_length=255)

    ip_address = models.GenericIPAddressField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.action}"