from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .forms import *
from django.contrib import messages
from django.db.models import Sum
from django.contrib.admin.views.decorators import staff_member_required
from datetime import date, timedelta

from .models import Transaction, ActivityLog
from dateutil.relativedelta import relativedelta # Use 'pip install python-dateutil'
from django.http import HttpResponse
from .mpesa_utils import get_mpesa_access_token, get_mpesa_password
import requests
from django.utils import timezone
from django.db import  transaction
from decimal import Decimal
from dateutil.relativedelta import relativedelta


def home(request):
    return render(request, "home.html")
def about(request):
    return render (request, "about.html")
def Contact(request):
    return render (request,  "contact.html")
def Service(request):
    return render (request,  "services.html")


# -------------------------
# Member Dashboard
# -------------------------
#@login_required

def member_dashboard(request):
    profile = request.user.profile
    
    # 1. Fetch all records for this member
    loans = Loan.objects.filter(member=profile)
    savings_list = MonthlyContribution.objects.filter(member=profile).order_by('-created_at')
    shares_list = CapitalShare.objects.filter(member=profile)

    # 2. Calculate Top Card Totals
    total_savings = savings_list.aggregate(Sum('amount'))['amount__sum'] or 0
    total_shares = shares_list.aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Calculate Total Repaid across all loans
    total_repaid = LoanRepayment.objects.filter(member=profile).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
    
    # Calculate Total Debt (Principal of Approved Loans - Total Repaid)
    total_principal = loans.filter(status='approved').aggregate(Sum('amount'))['amount__sum'] or 0
    total_loans_debt = total_principal - total_repaid

    # 3. Dynamic Calculation for the Loan Table
    # We add attributes to each loan object so the HTML can see them
    for loan in loans:
        total_paid = LoanRepayment.objects.filter(
            loan=loan
        ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

        total_payable = LoanRepaymentSchedule.objects.filter(
            loan=loan
        ).aggregate(Sum('amount_due'))['amount_due__sum'] or Decimal('0.00')

        loan.total_paid = total_paid
        loan.total_payable = total_payable
        loan.remaining_balance = total_payable - total_paid

    context = {
        'profile': profile,
        'loans': loans,
        'savings': savings_list,  # Used in the Recent Savings table
        'shares': shares_list,    # Used in the Shares breakdown
        'total_savings': total_savings,
        'total_shares': total_shares,
        'total_loans': total_loans_debt,
        'total_repaid': total_repaid,
    }
    return render(request, 'r_dashboard.html', context)

def deposit_savings(request):
    if request.method == "POST":
        form = SavingsForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                saving = form.save(commit=False)
                saving.member = request.user.profile
                saving.save()

                # Log it!
                record_transaction(
                    member_profile=request.user.profile,
                    type='deposit',
                    amount=saving.amount,
                    reference=f"Savings Deposit for {saving.month}"
                )
                
            messages.success(request, "Savings updated successfully.")
            return redirect("member_dashboard")
    else:
        form = SavingsForm()
    return render(request, "deposit_savings.html", {"form": form})


def admin_dashboard(request):
    # 1. Fetching the Pending Loans for the table
    pending_loans = Loan.objects.filter(status='pending')
    approved_loans = Loan.objects.filter(status='approved')
    rejected_loans = Loan.objects.filter(status='rejected')
    
    # 2. Calculating Summary Card Data
    # Total Savings Pool: Sum of all MonthlyContribution amounts
    total_savings_pool = MonthlyContribution.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Total Members count
    total_members = Profile.objects.count()
    
    # Total Interest Earned (Example logic: Sum of all completed loans)
    total_interest_earned = Loan.objects.filter(status='completed').aggregate(Sum('amount'))['amount__sum'] or 0

    context = {
        'pending_loans': pending_loans,
        'total_savings_pool': total_savings_pool,
        'total_members': total_members,
        'total_interest_earned': total_interest_earned,
        'approved_loans':approved_loans,
        'rejected_loans':rejected_loans
    }

    # IMPORTANT: Ensure this matches the template name you are using
    return render(request, 'admin.html', context)

@login_required
def apply_loan(request):
    profile = request.user.profile

    # -------------------------
    # 1. CHECK EXISTING ACTIVE LOAN
    # -------------------------
    active_loan = Loan.objects.filter(
        member=profile,
        status__in=['pending', 'approved']
    ).exists()

    if active_loan:
        messages.warning(request, "You already have an active loan.")
        return redirect('member_dashboard')

    # -------------------------
    # 2. CALCULATE USER LOAN LIMIT
    # -------------------------
    total_savings = MonthlyContribution.objects.filter(
        member=profile
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    loan_limit = Decimal(total_savings) * Decimal('3.5')

    # -------------------------
    # 3. HANDLE FORM
    # -------------------------
    if request.method == 'POST':
        form = LoanApplicationForm(request.POST, user_profile=profile)

        if form.is_valid():
            loan = form.save(commit=False)
            loan.member = profile

            # -------------------------
            # 4. CHECK USER LIMIT
            # -------------------------
            if loan.amount > loan_limit:
                messages.error(request, f"Your max loan limit is KES {loan_limit:,.2f}")
                return redirect('apply_loan')

            selected_guarantors = form.cleaned_data['guarantors']

            # -------------------------
            # 5. MINIMUM GUARANTORS CHECK
            # -------------------------
            if len(selected_guarantors) < 3:
                messages.error(request, "You must select at least 3 guarantors.")
                return redirect('apply_loan')

            # -------------------------
            # 6. GUARANTOR VALIDATION
            # -------------------------
            total_guaranteed = Decimal('0.00')

            for g_profile in selected_guarantors:

                # Guarantor savings
                g_savings = MonthlyContribution.objects.filter(
                    member=g_profile
                ).aggregate(Sum('amount'))['amount__sum'] or 0

                g_limit = Decimal(g_savings) * Decimal('3.5')

                # Existing loans
                g_active_loans = Loan.objects.filter(
                    member=g_profile,
                    status__in=['pending', 'approved']
                ).aggregate(Sum('amount'))['amount__sum'] or 0

                available_limit = g_limit - Decimal(g_active_loans)

                if available_limit <= 0:
                    messages.error(
                        request,
                        f"{g_profile.user.get_full_name()} has no available guarantee limit."
                    )
                    return redirect('apply_loan')

                total_guaranteed += available_limit

            # -------------------------
            # 7. FINAL GUARANTEE CHECK
            # -------------------------
            if total_guaranteed < loan.amount:
                messages.error(
                    request,
                    "Guarantors cannot fully cover this loan amount."
                )
                return redirect('apply_loan')

            # -------------------------
            # 8. SAVE LOAN + GUARANTORS
            # -------------------------
            with transaction.atomic():
                loan.status = 'pending'
                loan.save()

                share_per_guarantor = loan.amount / len(selected_guarantors)

                for g_profile in selected_guarantors:
                    Guarantor.objects.create(
                        loan=loan,
                        guarantor=g_profile,
                        guaranteed_amount=share_per_guarantor
                    )

            messages.success(request, "Loan application submitted successfully!")
            return redirect('member_dashboard')

    else:
        form = LoanApplicationForm(user_profile=profile)

    # -------------------------
    # 9. CONTEXT
    # -------------------------
    context = {
        'form': form,
        'loan_limit': loan_limit,
        'total_savings': total_savings
    }

    return render(request, 'apply_loan.html', context)
@login_required
def pay_loan(request):
    profile = request.user.profile

    # Get active loan
    active_loan = Loan.objects.filter(
        member=profile,
        status='approved'
    ).order_by('-id').first()

    next_installment = None
    monthly_principal = Decimal('0.00')
    monthly_interest = Decimal('0.00')
    total_loan_payable = Decimal('0.00')
    remaining_loan_balance = Decimal('0.00')

    if request.method == "POST":
        form = LoanRepaymentForm(request.POST, user_profile=profile)

        if form.is_valid() and active_loan:
            try:
                with transaction.atomic():
                    repayment = form.save(commit=False)
                    repayment.member = profile
                    repayment.loan = active_loan
                    repayment.save()

                    # 🔥 HANDLE INSTALLMENTS
                    amount_remaining = repayment.amount_paid

                    schedules = LoanRepaymentSchedule.objects.filter(
                        loan=active_loan,
                        is_paid=False
                    ).order_by('due_date')

                    for inst in schedules:
                        if amount_remaining >= inst.amount_due:
                            inst.is_paid = True
                            inst.save()
                            amount_remaining -= inst.amount_due
                        else:
                            break

                    # ✅ HANDLE EXCESS → MOVE TO SAVINGS
                    excess_amount = amount_remaining

                    if excess_amount > 0:
                        MonthlyContribution.objects.create(
                            member=profile,
                            amount=excess_amount,
                            month=timezone.now().date()
                        )

                        record_transaction(
                            member_profile=profile,
                            type='deposit',
                            amount=excess_amount,
                            reference=f"Excess from Loan #{active_loan.id}"
                        )

                        messages.info(
                            request,
                            f"Excess KES {excess_amount:,.2f} moved to savings."
                        )

                    # 🔥 TOTAL CHECK (FINAL COMPLETION)
                    total_paid = LoanRepayment.objects.filter(
                        loan=active_loan
                    ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

                    total_payable = LoanRepaymentSchedule.objects.filter(
                        loan=active_loan
                    ).aggregate(Sum('amount_due'))['amount_due__sum'] or Decimal('0.00')

                    if total_paid >= total_payable:
                        active_loan.status = 'completed'
                        active_loan.save()

                        LoanRepaymentSchedule.objects.filter(
                            loan=active_loan,
                            is_paid=False
                        ).update(is_paid=True)

                        messages.success(request, "Loan fully paid successfully.")

                    # Record repayment transaction
                    record_transaction(
                        member_profile=profile,
                        type='repayment',
                        amount=repayment.amount_paid,
                        reference=f"Loan #{active_loan.id} Repayment"
                    )

                return redirect('pay_loan')

            except Exception as e:
                messages.error(request, f"Error: {str(e)}")
        else:
            messages.error(request, "Invalid form submission.")

    else:
        form = LoanRepaymentForm(user_profile=profile)

    # -------------------------
    # DISPLAY CALCULATIONS
    # -------------------------
    if active_loan:
        next_installment = LoanRepaymentSchedule.objects.filter(
            loan=active_loan,
            is_paid=False
        ).order_by('due_date').first()

        if next_installment and active_loan.duration_months > 0:
            monthly_principal = active_loan.amount / active_loan.duration_months
            monthly_interest = next_installment.amount_due - monthly_principal

        total_loan_payable = LoanRepaymentSchedule.objects.filter(
            loan=active_loan
        ).aggregate(Sum('amount_due'))['amount_due__sum'] or Decimal('0.00')

        total_repaid = LoanRepayment.objects.filter(
            loan=active_loan
        ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

        remaining_loan_balance = total_loan_payable - total_repaid

    context = {
        'form': form,
        'active_loan': active_loan,
        'next_installment': next_installment,
        'monthly_principal': monthly_principal,
        'monthly_interest': monthly_interest,
        'total_loan_payable': total_loan_payable,
        'remaining_balance': remaining_loan_balance,
    }

    return render(request, 'pay_loan.html', context)
@staff_member_required
def manage_loan_requests(request):
    # Fetch loans waiting for admin action
    pending_loans = Loan.objects.filter(status='pending')
    
    return render(request, 'approve.html', {'loans': pending_loans})

@staff_member_required

def approve_loan(request, loan_id):
    loan = get_object_or_404(Loan, id=loan_id)

    if request.method == "POST":
        action = request.POST.get('action')

        if action == 'approve':

            # 🔒 Prevent re-approving same loan
            if loan.status == 'approved':
                messages.warning(request, "Loan already approved.")
                return redirect('admin_dashboard')

            # 🔒 Prevent duplicate schedules
            if LoanRepaymentSchedule.objects.filter(loan=loan).exists():
                messages.warning(request, "Repayment schedule already exists.")
                return redirect('admin_dashboard')

            # ✅ Update loan
            loan.status = 'approved'
            loan.approval_date = timezone.now()
            loan.save()

            # ✅ Calculate interest
            total_interest = (
                loan.amount *
                (loan.interest_rate / Decimal('100')) *
                (loan.duration_months / Decimal('12'))
            )

            total_payable = loan.amount + total_interest

            # ✅ Monthly installment
            monthly_installment = total_payable / loan.duration_months

            # ✅ Generate repayment schedule
            for i in range(1, loan.duration_months + 1):
                LoanRepaymentSchedule.objects.create(
                    loan=loan,
                    installment_number=i,
                    due_date=loan.approval_date.date() + relativedelta(months=i),
                    amount_due=monthly_installment,
                    is_paid=False
                )

            messages.success(
                request,
                f"Loan Approved ✅ | Total Interest: KES {total_interest:,.2f} | Monthly: KES {monthly_installment:,.2f}"
            )

            return redirect('admin_dashboard')

        elif action == 'reject':
            loan.status = 'rejected'
            loan.save()

            messages.warning(request, "Loan has been rejected.")
            return redirect('admin_dashboard')

    return redirect('admin_dashboard')
def record_transaction(member_profile, type, amount, reference=None, loan=None):
    if not reference:
        # Map transaction types to prefixes
        prefixes = {'deposit': 'DEP', 'repayment': 'REP', 'shares': 'SHR'}
        prefix = prefixes.get(type, 'TX')
        reference = generate_transaction_ref(prefix)
    
    with transaction.atomic():
        return Transaction.objects.create(
            member=member_profile,
            transaction_type=type,
            amount=amount,
            reference=reference
        )


def initiate_stk_push(request):
    if request.method == "POST":
        loan_id = request.POST.get('loan_id')
        phone = request.user.profile.phone_number # Ensure format is 2547XXXXXXXX
        amount = request.POST.get('amount')
        
        access_token = get_mpesa_access_token()
        password, timestamp = get_mpesa_password()
        
        headers = {"Authorization": f"Bearer {access_token}"}
        
        request_body = {
            "BusinessShortCode": "174379",
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(float(amount)),
            "PartyA": phone,
            "PartyB": "174379",
            "PhoneNumber": phone,
            "CallBackURL": "https://yourdomain.com/mpesa-callback/",
            "AccountReference": f"Loan-{loan_id}",
            "TransactionDesc": "Loan Repayment"
        }
        
        response = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=request_body,
            headers=headers
        )
        
        messages.success(request, "Check your phone to enter M-Pesa PIN!")
        return redirect('member_dashboard')

def download_receipt(request, saving_id):
    saving = get_object_or_404(MonthlyContribution, id=saving_id, member=request.user.profile)
    
    # Create the receipt content
    content = f"""
    =========================================
               ELDOPOLY SACCO RECEIPT
    =========================================
    Date: {saving.created_at.strftime('%Y-%m-%d %H:%M')}
    Member: {saving.member.user.get_full_name()}
    Member ID: #{saving.member.id}
    -----------------------------------------
    Transaction Type: MONTHLY SAVINGS
    Period: {saving.month.strftime('%B %Y')}
    Amount Paid: KES {saving.amount:,.2f}
    -----------------------------------------
    Thank you for saving with us!
    =========================================
    """
    
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename="Receipt_{saving.id}.txt"'
    return response
def Setting_loan(request):
     pass
#     if request.method == "POST":
#         form = SettinForm(request.POST)
#         if form.is_valid():
#             form.save()
            
#             return redirect("member_dashboard")
#     else:
#         form = SettinForm()
    
#     return render(request, "aploan.html", {"form": form})
@login_required
def purchase_shares(request):
    pass
    # if request.method == "POST":
    #     form = SharesForm(request.POST)
    #     if form.is_valid():
    #         share = form.save(commit=False)
    #         share.member = request.user.profile
    #         share.amount = share.quantity * share.share_setting.price_per_share
    #         share.save()
    #         return redirect("member_dashboard")
    # else:
    #     form = SharesForm()
    
    # return render(request, "shares.html", {"form": form})
def LoanP(request):
    if request.method == "POST":
        form = LoanPurposeForm(request.POST)
        if form.is_valid():
            form.save()
            # Fixed the messages syntax error as well
            messages.success(request, "Saved successfully") 
            return redirect('admin_dashboard')
    else:
        # This handles the initial GET request
        form = LoanPurposeForm()
        
    # Now 'form' exists regardless of the request method
    return render(request, "p.html", {'form': form})