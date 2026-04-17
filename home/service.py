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
        # 1. Operational Expenses (Grouped by EXPENSE_TYPES)
        expense_summary = Expense.objects.filter(date_spent__year=year).values(
            'expense_type'
        ).annotate(total=Sum('amount_spent')).order_by('-total')

        # 2. Member Equity & Contributions
        total_contributions = MonthlyContribution.objects.filter(
            month__year=year
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        total_reg_fees = RegistrationFee.objects.filter(
            paid=True, paid_at__year=year
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        # 3. Loan Portfolio Metrics
        loan_stats = Loan.objects.filter(application_date__year=year).aggregate(
            total_disbursed=Sum('amount'),
            total_insurance_charged=Sum('insurance'),
            total_interest_expected=Sum('interest')
        )

        total_repayments = LoanRepayment.objects.filter(
            payment_date__year=year
        ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0

        # 4. Refunds & Exits
        share_refunds = CapitalShareRefund.objects.filter(
            date_applied__year=year, status='disbursed'
        ).aggregate(Sum('amount_requested'))['amount_requested__sum'] or 0

        xmas_payouts = XmasRefund.objects.filter(
            date_applied__year=year, status='disbursed'
        ).aggregate(Sum('amount_requested'))['amount_requested__sum'] or 0

        # 5. Bank/Cash Position (Derived from Transactions)
        # Note: This assumes 'deposit' and 'repayment' are inflows, 'loan' and 'shares' (refunds) are outflows
        inflows = Transaction.objects.filter(
            created_at__year=year, 
            transaction_type__in=['deposit', 'repayment']
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        outflows = Transaction.objects.filter(
            created_at__year=year, 
            transaction_type__in=['loan', 'shares']
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        return {
            'year': year,
            'expenses': expense_summary,
            'total_contributions': total_contributions,
            'total_reg_fees': total_reg_fees,
            'loan_stats': loan_stats,
            'total_repayments': total_repayments,
            'refunds': {
                'capital_shares': share_refunds,
                'xmas_fund': xmas_payouts
            },
            'net_cash_flow': inflows - outflows
        }