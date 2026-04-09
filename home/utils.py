from decimal import Decimal
from dateutil.relativedelta import relativedelta
from .models import LoanRepaymentSchedule
import datetime
import uuid
def generate_repayment_schedule(loan):
    monthly_principal = loan.amount / loan.duration_months
    monthly_interest_rate = loan.interest_rate / Decimal('100')
    
    start_date = loan.approval_date.date()

    for i in range(1, loan.duration_months + 1):
        interest = loan.amount * monthly_interest_rate
        total_due = monthly_principal + interest

        LoanRepaymentSchedule.objects.create(
            loan=loan,
            installment_number=i,
            due_date=start_date + relativedelta(months=i),
            amount_due=total_due,
            is_paid=False
        )
 

def generate_transaction_ref(prefix="TX"):
    """Generates a unique transaction reference."""
    date_str = datetime.datetime.now().strftime('%Y%m%d')
    unique_id = uuid.uuid4().hex[:6].upper()
    return f"{prefix}-{date_str}-{unique_id}"
def calculate_insurance(principal, months):
    return ((Decimal('5.03') * Decimal(months) + Decimal('3.03')) * Decimal(principal)) / Decimal('6000')
