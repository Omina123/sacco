from django.db.models import Sum, Q
from django.utils import timezone
from decimal import Decimal
from .models import (
    Expense, MonthlyContribution, Loan, LoanRepayment, 
    CapitalShareRefund, XmasRefund, RegistrationFee, Transaction
)

class SaccoReportService:
    @staticmethod
    def generate_annual_report(year):
        # 1. Operational Expenses (Detailed for the table)
        # We fetch individual expenses to show dates and specific descriptions
        expenses = Expense.objects.filter(date_spent__year=year).order_by('-date_spent')
        total_expenses = expenses.aggregate(Sum('amount_spent'))['amount_spent__sum'] or Decimal('0.00')

        # 2. Member Equity & Contributions
        total_contributions = MonthlyContribution.objects.filter(
            month__year=year
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

        total_reg_fees = RegistrationFee.objects.filter(
            paid=True, paid_at__year=year
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

        # 3. Loan Portfolio
        loan_stats = Loan.objects.filter(
            application_date__year=year, 
            status__in=['approved', 'disbursed']
        ).aggregate(
            total_disbursed=Sum('amount'),
            total_interest=Sum('interest')
        )
        total_disbursed = loan_stats['total_disbursed'] or Decimal('0.00')

        total_repayments = LoanRepayment.objects.filter(
            payment_date__year=year
        ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

        # 4. Cash Flow Logic (CORRECTED)
        # Inflows: Contributions + Repayments + Reg Fees + Shares
        inflows = Transaction.objects.filter(
            created_at__year=year, 
            transaction_type__in=['deposit', 'repayment', 'shares', 'registration']
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

        # Outflows: Loans + Expenses + Refunds
        outflows = Transaction.objects.filter(
            created_at__year=year, 
            transaction_type__in=['loan', 'expense', 'refund']
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

        return {
            'year': year,
            'expenses': expenses,
            'total_expenses': total_expenses,
            'total_contributions': total_contributions,
            'total_reg_fees': total_reg_fees,
            'total_disbursed': total_disbursed,
            'total_repayments': total_repayments,
            'net_cash_flow': inflows - outflows
        }