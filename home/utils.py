from decimal import Decimal
from dateutil.relativedelta import relativedelta
from .models import LoanRepaymentSchedule

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