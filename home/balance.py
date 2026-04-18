from django.db.models import Sum
from decimal import Decimal
from .models import (
    Expense, MonthlyContribution, Loan, LoanRepayment, 
    RegistrationFee, Transaction
)

class BalanceSheetService:
    @staticmethod
    def generate_balance_sheet(year):
        # Helper to ensure we always work with Decimals
        def to_decimal(value):
            return Decimal(str(value or 0))

        # --- ASSETS ---
        # Note 7: Cash and Bank (Inflows vs Outflows)
        # INFLOWS: Savings + Loan Repayments + Shares + Registration Fees
        in_types = ['deposit', 'repayment', 'shares', 'registration']
        inflows = to_decimal(Transaction.objects.filter(
            created_at__year=year, 
            transaction_type__in=in_types
        ).aggregate(Sum('amount'))['amount__sum'])

        # OUTFLOWS: Loans Disbursed + Expenses Paid
        out_types = ['loan', 'expense']
        outflows = to_decimal(Transaction.objects.filter(
            created_at__year=year, 
            transaction_type__in=out_types
        ).aggregate(Sum('amount'))['amount__sum'])
        
        cash_and_bank = inflows - outflows

        # Note 9: Loans to Members (Outstanding Principal)
        total_loaned = to_decimal(Loan.objects.filter(
            application_date__year=year,
            status__in=['approved', 'disbursed']
        ).aggregate(Sum('amount'))['amount__sum'])
        
        total_repaid = to_decimal(LoanRepayment.objects.filter(
            payment_date__year=year
        ).aggregate(Sum('amount_paid'))['amount_paid__sum'])
        
        net_loans = total_loaned - total_repaid

        # --- LIABILITIES ---
        # Note 12: Members' Deposits (Total Savings pool)
        members_deposits = to_decimal(MonthlyContribution.objects.filter(
            month__year=year
        ).aggregate(Sum('amount'))['amount__sum'])
        
        # Note 13: Accrued Expenses
        accrued_expenses = to_decimal(Expense.objects.filter(
            date_spent__year=year
        ).aggregate(Sum('amount_spent'))['amount_spent__sum'])

        # Note 14: Interest on Deposits Payable
        interest_payable = to_decimal(Transaction.objects.filter(
            created_at__year=year, 
            transaction_type='interest'
        ).aggregate(Sum('amount'))['amount__sum'])

        # --- SHAREHOLDERS' FUNDS (EQUITY) ---
        # Note 16: Share Capital (Actual Capital/Registration pool)
        share_capital = to_decimal(RegistrationFee.objects.filter(
            paid=True, 
            paid_at__year=year
        ).aggregate(Sum('amount'))['amount__sum'])

        # Final Totals
        total_assets = cash_and_bank + net_loans
        total_liabilities = members_deposits + accrued_expenses + interest_payable
        
        # Note 17: Reserves (Retained Earnings / Surplus)
        # This is the balancing figure: Assets - (Liabilities + Equity)
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