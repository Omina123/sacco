from django.db.models import Sum
from .models import (
    Expense, MonthlyContribution, Loan, LoanRepayment, 
    RegistrationFee, Transaction
)

class BalanceSheetService:
    @staticmethod
    def generate_balance_sheet(year):
        # --- ASSETS ---
        # Note 7: Cash and Bank (Inflows vs Outflows)
        inflows = Transaction.objects.filter(created_at__year=year, transaction_type__in=['deposit', 'repayment']).aggregate(Sum('amount'))['amount__sum'] or 0
        outflows = Transaction.objects.filter(created_at__year=year, transaction_type__in=['loan', 'shares', 'expense']).aggregate(Sum('amount'))['amount__sum'] or 0
        cash_and_bank = inflows - outflows

        # Note 9: Loans to Members (Outstanding Principal)
        total_loaned = Loan.objects.filter(application_date__year=year).aggregate(Sum('amount'))['amount__sum'] or 0
        total_repaid = LoanRepayment.objects.filter(payment_date__year=year).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
        net_loans = total_loaned - total_repaid

        # --- LIABILITIES ---
        # Note 12: Members' Deposits
        members_deposits = MonthlyContribution.objects.filter(month__year=year).aggregate(Sum('amount'))['amount__sum'] or 0
        
        # Note 13: Accrued Expenses (Operational costs like Audit Fees, Bank Charges)
        accrued_expenses = Expense.objects.filter(date_spent__year=year).aggregate(Sum('amount_spent'))['amount_spent__sum'] or 0

        # Note 14: Interest on Deposits Payable (Based on bank statement data)
        interest_payable = Transaction.objects.filter(created_at__year=year, transaction_type='interest').aggregate(Sum('amount'))['amount__sum'] or 0

        # --- SHAREHOLDERS' FUNDS (EQUITY) ---
        # Note 16: Share Capital (Registration fees)
        share_capital = RegistrationFee.objects.filter(paid=True, paid_at__year=year).aggregate(Sum('amount'))['amount__sum'] or 0

        total_assets = cash_and_bank + net_loans
        total_liabilities = members_deposits + accrued_expenses + interest_payable
        
        # Note 17: Reserves (The balancing figure/Retained Earnings)
        reserves = total_assets - (total_liabilities + share_capital)

        return {
            'year': year,
            'assets': {
                'cash': cash_and_bank,
                'loans': net_loans,
                'total': total_assets,
            },
            'liabilities': {
                'deposits': members_deposits,
                'accrued': accrued_expenses,
                'interest': interest_payable,
                'total': total_liabilities,
            },
            'equity': {
                'shares': share_capital,
                'reserves': reserves,
            },
            'total_equity_and_liabilities': total_liabilities + share_capital + reserves
        }