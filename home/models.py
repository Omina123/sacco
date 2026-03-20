from django.db import models
from Users.models import Profile

import uuid
import datetime
from django.core.validators import MinValueValidator,MaxValueValidator
from decimal import Decimal

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

    date_paid = models.DateField(auto_now_add=True)

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


# -------------------------
# LOAN PURPOSES
# -------------------------
class LoanPurpose(models.Model):

    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name


# -------------------------
# LOANS
# -------------------------
class Loan(models.Model):

    STATUS = (
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('issued', 'Issued'),
    ('defaulted', 'Defaulted'),
    ('completed', 'Completed'),
    ('rejected', 'Rejected'),
)

    member = models.ForeignKey(Profile, on_delete=models.CASCADE,related_name="member_loans")

    purpose = models.ForeignKey(LoanPurpose, on_delete=models.SET_NULL, null=True)

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    Othes_Guarantor = models.CharField(max_length=56,blank=True,null=True)
    interest_rate = models.DecimalField(max_digits=10, decimal_places=2)

    duration_months = models.IntegerField(
        
        validators=[MinValueValidator(1),
                    MaxValueValidator(48)])

    status = models.CharField(max_length=20, choices=STATUS, default='pending')

    application_date = models.DateTimeField(auto_now_add=True)

    approval_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Loan {self.id} - {self.member}"


# -------------------------
# GUARANTORS
# -------------------------
class Guarantor(models.Model):

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE)

    guarantor = models.ForeignKey(Profile, on_delete=models.CASCADE)

    guaranteed_amount = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.guarantor} guaranteeing Loan {self.loan.id}"


# -------------------------
# LOAN REPAYMENT SCHEDULE
# -------------------------
class LoanRepaymentSchedule(models.Model):

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE)

    installment_number = models.IntegerField()

    due_date = models.DateField()

    amount_due = models.DecimalField(max_digits=10, decimal_places=2)

    is_paid = models.BooleanField(default=False)

    def __str__(self):
        return f"Loan {self.loan.id} Installment {self.installment_number}"


# -------------------------
# LOAN REPAYMENTS
# -------------------------
class LoanRepayment(models.Model):

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE)

    member = models.ForeignKey(Profile, on_delete=models.CASCADE)

    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)

    payment_date = models.DateTimeField(auto_now_add=True)

    reference = models.CharField(max_length=100, blank=True, null=True)

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