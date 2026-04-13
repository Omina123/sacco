from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models.functions import TruncMonth
from home.de import treasurer_required
from .forms import *
import csv
from django.db.models import Q, Sum, Avg

from django.contrib import messages
from django.db.models import Sum
from django.contrib.admin.views.decorators import staff_member_required
from datetime import date, timedelta
from .deco import staff_required
from .models import Transaction, ActivityLog
from dateutil.relativedelta import relativedelta # Use 'pip install python-dateutil'
from django.http import HttpResponse
from .mpesa_utils import get_mpesa_access_token, get_mpesa_password
import requests
from django.utils import timezone
from django.db import  transaction
from decimal import Decimal, DecimalException
from decimal import Decimal, InvalidOperation
from datetime import datetime
from dateutil.relativedelta import relativedelta
from django.forms import modelformset_factory
from django.db.models import F
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .utils import generate_transaction_ref , calculate_insurance # Make sure you have a function to generate unique references
import json
from .pamision import role_required
def home(request):
    total_members=Profile.objects.count()
    total_loans=Loan.objects.count()
    context={
        'total_members':total_members,
        'total_loans':total_loans
    }
    return render(request, "home.html",context)
def about(request):
    return render (request, "about.html")
def Contact(request):
    return render (request,  "contact.html")
def Service(request):
    return render (request,  "services.html")


@csrf_exempt
def mpesa_callback(request):
    data = json.loads(request.body)
    try:
        callback = data['Body']['stkCallback']
        if callback['ResultCode'] == 0:
            metadata = callback['CallbackMetadata']['Item']
            amount = Decimal(next(i['Value'] for i in metadata if i['Name'] == 'Amount'))
            receipt = next(i['Value'] for i in metadata if i['Name'] == 'MpesaReceiptNumber')
            account_ref = next(i['Value'] for i in metadata if i['Name'] == 'AccountReference')

            with transaction.atomic():
                # --- LOGIC SEPARATION BASED ON PREFIX ---
                
                if "SHARES" in account_ref:
                    user_id = account_ref.split('-')[-1]
                    profile = Profile.objects.get(user_id=user_id)
                    target_member = profile
                    
                    CapitalShare.objects.create(
                        member=profile,
                        amount=amount,
                        reference=receipt,
                        date_paid=timezone.now()
                    )
                    t_type = 'shares'

                elif "SAVINGS" in account_ref:
                    # New logic for Monthly Savings
                    profile_id = account_ref.split('-')[-1]
                    profile = Profile.objects.get(id=profile_id)
                    target_member = profile
                    
                    # Assuming your model is named 'Saving' or 'Savings'
                    MonthlyContribution.objects.create(
                        member=profile,
                        amount=amount,
                        reference=receipt,
                        date_paid=timezone.now()
                    )
                    t_type = 'savings'

                elif "XMAS" in account_ref:
                    loan_id = account_ref.split('-')[-1]
                    loan = XmasLoan.objects.get(id=loan_id)
                    target_member = loan.member
                    
                    LoanRepayment.objects.create(
                        member=loan.member,
                        amount_paid=amount,
                        reference=receipt,
                        is_xmas=True
                    )
                    
                    if loan.remaining_balance <= 0:
                        loan.status = 'cleared'
                        loan.save()
                    t_type = 'repayment'

                else:
                    # Default: Normal Loan Repayment
                    loan_id = account_ref.split('-')[-1]
                    loan = Loan.objects.get(id=loan_id)
                    target_member = loan.member
                    
                    LoanRepayment.objects.create(
                        loan=loan,
                        member=loan.member,
                        amount_paid=amount,
                        reference=receipt,
                        is_xmas=False
                    )
                    t_type = 'repayment'

                # --- UNIFIED TRANSACTION LOG ---
                Transaction.objects.create(
                    member=target_member,
                    transaction_type=t_type,
                    amount=amount,
                    reference=receipt
                )

        return JsonResponse({"ResultCode": 0})
    except Exception as e:
        print("Callback Error:", e)
        return JsonResponse({"ResultCode": 1, "ErrorMessage": str(e)})
        return JsonResponse({"ResultCode": 1})
    from django.db import IntegrityError, transaction

def apply_xmas_loan(request):
    profile = request.user.profile
    current_year = timezone.now().year
    
    # Check if an application already exists for this year
    existing_loan = XmasLoan.objects.filter(member=profile, year=current_year).first()
    
    # LOGIC: If a loan exists, only allow re-application if it was rejected
    if existing_loan:
        if existing_loan.status == 'rejected':
            # Option: Delete the rejected application to clear the unique constraint
            existing_loan.delete() 
        else:
            # Block application if it's pending, approved, or disbursed
            messages.warning(request, f"You already have a {existing_loan.get_status_display()} holiday loan for {current_year}.")
            return redirect('member_dashboard')

    # Calculate max limit (3.5x savings)
    total_savings = MonthlyContribution.objects.filter(member=profile).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    max_limit = total_savings * Decimal('3.5')

    if request.method == 'POST':
        try:
            amount_input = request.POST.get('amount')
            amount = Decimal(amount_input)

            if amount > max_limit:
                messages.error(request, f"Limit Exceeded! Your maximum X-Mass loan is KES {max_limit}")
            elif amount <= 0:
                messages.error(request, "Please enter a valid amount.")
            else:
                # Using a transaction to ensure database integrity
                with transaction.atomic():
                    XmasLoan.objects.create(
                        member=profile,
                        amount_requested=amount,
                        year=current_year
                    )
                messages.success(request, "X-Mass Loan request submitted successfully!")
                return redirect('member_dashboard')
        except (ValueError, TypeError, DecimalException):
            messages.error(request, "Please enter a valid numerical amount.")

    return render(request, 'xmas.html', {'max_limit': max_limit})
def pay_xmas_loan(request):
    current_year = timezone.now().year

    loan = XmasLoan.objects.filter(
        member=request.user.profile,
        year=current_year,
        status='disbursed'
    ).first()

    if not loan:
        messages.error(request, "You do not have an active disbursed Xmas Loan for this year.")
        return redirect('member_dashboard')

    # Suggested installment logic
    suggested_installment = min(loan.monthly_installment, loan.remaining_balance)

    # Remaining months calculation
    remaining_months = 0
    if loan.monthly_installment > 0:
        remaining_months = int((loan.remaining_balance / loan.monthly_installment).quantize(Decimal('1')))

    if request.method == 'POST':
        amount_input = request.POST.get('amount')
        try:
            amount_to_pay = Decimal(amount_input)
            if amount_to_pay <= 0:
                raise ValueError
        except (ValueError, TypeError, InvalidOperation):
            messages.error(request, "Please enter a valid numerical amount.")
            return redirect('pay_xmas_loan')

        # Trigger M-Pesa instead of saving to DB
        # We redirect to the initiate_stk_push view or call its logic directly
        return initiate_stk_push(request) 

    return render(request, 'pay_loanx.html', {
        'loan': loan,
        'suggested_installment': suggested_installment,
        'remaining_months': remaining_months
    })
@login_required
@role_required(allowed_roles=['1', '2', '3', '4'])  # Allow all roles to access dashboard
def member_dashboard(request):
    profile = request.user.profile
    
    # 1. Basic Data Retrieval
    loans = Loan.objects.filter(member=profile).order_by('-application_date')
    savings_list = MonthlyContribution.objects.filter(member=profile).order_by('-created_at')
    shares_list = CapitalShare.objects.filter(member=profile)
    xmas_loans = XmasLoan.objects.filter(member=profile).order_by('-application_date')

    # 2. NEW: Fetch notifications for this user (where they are a guarantor)
    # Shows requests for loans that are still pending and where they haven't responded yet
    pending_guarantor_requests = Guarantor.objects.filter(
        guarantor=profile,
        status='pending',
        loan__status='pending_guarantors' 
    ).select_related('loan__member__user')

    running_total_remaining_balance = Decimal('0.00')
    running_total_penalties = Decimal('0.00')

    # 3. Process Loans for the Portfolio Table
    for loan in loans:
        # Repayment totals
        total_paid_lec = LoanRepayment.objects.filter(loan=loan).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
        total_payable_lec = LoanRepaymentSchedule.objects.filter(loan=loan).aggregate(Sum('amount_due'))['amount_due__sum'] or Decimal('0.00')

        loan.total_paid = total_paid_lec
        loan.total_payable_l = total_payable_lec
        loan.remaining_balance = total_payable_lec - total_paid_lec

        # Penalty calculation
        loan.penalty_due = calculate_penalty(loan)
        running_total_penalties += loan.penalty_due

        # Only add to "Current Debt" card if the loan is actually active/disbursed
        if loan.status in ['approved', 'disbursed']:
            running_total_remaining_balance += loan.remaining_balance

    # 4. Top Summary Cards Math
    total_savings = savings_list.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    total_shares = shares_list.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    total_repaid_all_time = LoanRepayment.objects.filter(loan__member=profile).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

    context = {
        'xmas_loans': xmas_loans,
        'profile': profile,
        'loans': loans,
        'savings': savings_list,
        'shares': shares_list,
        'total_savings': total_savings,
        'total_shares': total_shares,
        'total_loans': running_total_remaining_balance,
        'total_repaid': total_repaid_all_time,
        'total_penalties': running_total_penalties,
        # Pass the new notifications to the template
        'pending_guarantor_requests': pending_guarantor_requests,
    }

    return render(request, 'r_dashboard.html', context)


@login_required
def respond_guarantor(request, guarantor_id, action):
    # 1. Security Check
    guarantor_req = get_object_or_404(Guarantor, id=guarantor_id, guarantor=request.user.profile)
    loan = guarantor_req.loan
    
    # 2. Status Guard (Prevents responding to already processed loans)
    if loan.status != 'pending_guarantors':
        messages.error(request, "This loan is no longer awaiting guarantor responses.")
        return redirect('member_dashboard')

    with transaction.atomic():
        if action == 'accept':
            guarantor_req.status = 'accepted'
            guarantor_req.save()
            
            accepted_count = loan.guarantor_set.filter(status='accepted').count()
            
            if accepted_count >= 3:
                # Update loan status
                loan.status = 'pending' 
                # Save the specific message for the applicant to see later
                loan.remarks = f"All 3 guarantors have accepted. The loan for {loan.member.user.get_full_name()} is now moving to staff approval."
                loan.save()
                
                # Feedback for the person clicking (the guarantor)
                messages.success(request, "Final guarantor approval recorded.")
            else:
                messages.info(request, f"Response recorded. Waiting for {3 - accepted_count} more guarantor(s).")
        
        elif action == 'reject':
            guarantor_req.status = 'rejected'
            guarantor_req.save()
            
            loan.status = 'rejected'
            loan.remarks = f"Loan cancelled: Rejected by guarantor {request.user.get_full_name()}."
            loan.save()
            messages.warning(request, "You declined the request. The application has been cancelled.")

    return redirect('member_dashboard')

# Ensure you import your STK helper: from .utils import initiate_stk_push


def treasurer_deposit_savings(request, member_id):
    member_profile = get_object_or_404(Profile, id=member_id)

    if request.method == "POST":
        form = SavingsForm(request.POST)
        payment_method = request.POST.get('payment_method')

        if form.is_valid():
            # Extract cleaned data
            amount = form.cleaned_data['amount']
            contribution_date = form.cleaned_data['month']

            if payment_method == 'mpesa':
                # Prep for STK Push
                request.POST = request.POST.copy()
                request.POST['payment_type'] = 'savings'
                request.POST['member_id'] = member_profile.id
                # Pass amount to the STK function if needed
                return initiate_stk_push(request)
            
            else:
                try:
                    with transaction.atomic():
                        # Save the MonthlyContribution record
                        saving = form.save(commit=False)
                        saving.member = member_profile
                        saving.save()

                        # Create the corresponding Transaction log
                        Transaction.objects.create(
                            member=member_profile,
                            transaction_type='savings',
                            amount=amount,
                            reference=f"CASH-{request.POST.get('receipt_no', 'MANUAL')}"
                        )

                    messages.success(request, f"Cash deposit of KES {amount} for {contribution_date} recorded.")
                    return redirect('Members')
                except Exception as e:
                    messages.error(request, f"Database Error: {str(e)}")
        else:
            # This will show you exactly why validation failed in your console
            print(form.errors) 
            messages.error(request, "Invalid data. Please ensure the amount and month are correct.")
            
    else:
        form = SavingsForm()

    return render(request, 'treasurer_confirm_depost.html', {
        'member': member_profile, 
        'form': form
    })
def deposit_savings(request):
    """Member-only view: Strictly M-Pesa"""
    if request.method == "POST":
        form = SavingsForm(request.POST)
        if form.is_valid():
            # Inject payment_type so initiate_stk_push knows what to do
            request.POST = request.POST.copy()
            request.POST['payment_type'] = 'savings'
            # (member_id is not needed here as initiate_stk_push defaults to request.user.profile)
            
            return initiate_stk_push(request)
    else:
        form = SavingsForm()
        
    return render(request, "deposit_savings.html", {"form": form})
@login_required
@role_required(allowed_roles=[1])
def admin_dashboard(request):
    if getattr(request.user, 'user_type', None) != '1' and not request.user.is_superuser:
        return redirect('access_denied')
    pending_loans = Loan.objects.filter(
        status__in=['pending', 'partially_approved']
    )
    pending_xmas_loans = XmasLoan.objects.filter(
        status__in=['pending', 'partially_approved']
    ).order_by('-application_date')
    approved_loans = Loan.objects.filter(status='approved')
    rejected_loans = Loan.objects.filter(status='rejected')
    
    all_members = Profile.objects.all() 

    total_savings_pool = MonthlyContribution.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    total_members = Profile.objects.count()
    total_interest_earned = Loan.objects.filter(status='completed').aggregate(Sum('amount'))['amount__sum'] or 0

    context = {
        'pending_xmas_loans': pending_xmas_loans,
        'pending_loans': pending_loans,
        'total_savings_pool': total_savings_pool,
        'total_members': total_members,
        'total_interest_earned': total_interest_earned,
        'approved_loans': approved_loans,
        'rejected_loans': rejected_loans,
        'all_members': all_members,
    }
    return render(request, 'rev.html', context)


def calculate_loan_risk(member_profile, requested_amount):
    total_active_loans = Loan.objects.filter(
        member=member_profile, 
        status__in=['pending','approved']
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    total_savings = CapitalShare.objects.filter(member=member_profile).aggregate(Sum('amount'))['amount__sum'] or 0

    risk_score = Decimal(requested_amount) / (Decimal(total_savings) + 1) + Decimal(total_active_loans) * Decimal('0.5')
    # Lower score = lower risk
    return risk_score
@login_required
def apply_loan(request):
    profile = request.user.profile
    
    # 1. Basic Eligibility
    if profile.gross_salary <= 0 or profile.net_salary <= 0:
        messages.error(request, "Salary details not verified by HR.")
        return redirect('member_dashboard')

    # 2. Identify Existing Loan for Top-Up
    # We look for an 'approved' loan that isn't fully paid yet
    active_loan = Loan.objects.filter(member=profile, status='approved').first()
    
    # Assume your Loan model has a method or logic to get the remaining balance
    # If not, you'd calculate (Principal + Interest) - Amount Paid
    current_balance = active_loan.get_remaining_balance() if active_loan else Decimal('0.00')

    # 3. Calculate Global Limits
    total_savings = CapitalShare.objects.filter(member=profile).aggregate(Sum('amount'))['amount__sum'] or 0
    global_cap = Decimal(total_savings) * Decimal('3.5')
    
    # Other pending applications (excluding the one we might be replacing)
    other_exposure = Loan.objects.filter(
        member=profile,
        status__in=['pending_guarantors', 'pending', 'approved', 'disbursed']
    ).exclude(id=active_loan.id if active_loan else None).aggregate(Sum('amount'))['amount__sum'] or 0
    
    # 3. Final available room for NORMAL loans
    # Notice we are not subtracting anything from the XmasLoan model here.
    
    
    # Final borrowing room
    available_limit = global_cap - Decimal(other_exposure)

    # 4. Formset Setup
    GuarantorFormSet = modelformset_factory(
        Guarantor, form=GuarantorForm, extra=3, max_num=3, validate_min=True, min_num=3
    )

    context = {
        'loan_limit': available_limit,
        'active_loan': active_loan,
        'current_balance': current_balance,
        'total_savings': total_savings,
    }

    if request.method == 'POST':
        form = LoanApplicationForm(request.POST) 
        formset = GuarantorFormSet(request.POST, queryset=Guarantor.objects.none())

        if form.is_valid() and formset.is_valid():
            loan = form.save(commit=False)
            loan.member = profile
            
            new_principal = Decimal(loan.amount)
            months = Decimal(loan.duration_months)

            # --- TOP-UP VALIDATION ---
            if active_loan:
                if new_principal <= current_balance:
                    messages.error(request, f"Top-up amount must be greater than your current balance of KES {current_balance:,.2f}")
                    return render(request, 'apply_loan.html', context)
                
                loan.is_topup = True
                loan.replaces_loan = active_loan
                # The 'New Money' the user actually gets
                disbursement_amount = new_principal - current_balance
            else:
                disbursement_amount = new_principal

            # --- SALARY AFFORDABILITY (1/3 RULE) ---
            gross = Decimal(profile.gross_salary)
            net = Decimal(profile.net_salary)
            one_third_floor = gross / Decimal('3')
            
            insurance = calculate_insurance(new_principal, months)
            monthly_payment = (new_principal + (new_principal * Decimal('0.259') * (months/12))) / months

            if (net - monthly_payment) < one_third_floor:
                messages.error(request, "This loan exceeds the 1/3 salary take-home rule.")
                return render(request, 'apply_loan.html', context)

            # --- LIMIT CHECK ---
            if new_principal > available_limit:
                messages.error(request, f"Max limit is KES {available_limit:,.2f}")
                return render(request, 'apply_loan.html', context)

            # --- GUARANTOR VALIDATION ---
            # (Standard unique guarantor and capacity logic here as per previous versions)
            # ... [Omitted for brevity, but same as previous function] ...

            try:
                with transaction.atomic():
                    loan.status = 'pending_guarantors'
                    # Apply a top-up commission if your SACCO has one (e.g. 5% of balance)
                    topup_commission = current_balance * Decimal('0.05') if active_loan else 0
                    
                    loan.interest = new_principal * Decimal('0.259') 
                    loan.insurance = insurance + topup_commission
                    loan.save()

                    # Save Guarantors
                    instances = formset.save(commit=False)
                    for instance in instances:
                        instance.loan = loan
                        instance.save()

                msg = f"Top-up applied! You will receive KES {disbursement_amount:,.2f} after clearing your old loan."
                messages.success(request, msg if active_loan else "Loan submitted successfully.")
                return redirect('member_dashboard')
            except Exception as e:
                messages.error(request, f"Error: {str(e)}")

    else:
        form = LoanApplicationForm()
        formset = GuarantorFormSet(queryset=Guarantor.objects.none())

    context.update({'form': form, 'formset': formset})
    return render(request, 'apply_loan.html', context)


def approve_xmas_loan(request, loan_id):
    loan = get_object_or_404(XmasLoan, id=loan_id)
    user = request.user
    u_type = getattr(user, 'user_type', None)

    # ❌ Prevent approving finalized loans
    if loan.status in ['rejected', 'approved']:
        messages.error(request, "This holiday loan is already finalized.")
        return redirect('staff_dashboard')

    # ---------------------------------------------------------
    # 1️⃣ STAFF FIRST (Type '2')
    # ---------------------------------------------------------
    if u_type == '2':
        loan.staff_approved = True
        loan.status = "partially_approved"
        loan.save()
        messages.success(request, "Staff approval recorded.")
        return redirect('staff_dashboard')

    # ---------------------------------------------------------
    # 2️⃣ TREASURER SECOND (Type '3')
    # ---------------------------------------------------------
    elif u_type == '3':
        if not loan.staff_approved:
            messages.error(request, "Wait for Staff to approve this holiday loan first.")
            return redirect('staff_dashboard')

        loan.treasurer_approved = True
        loan.status = "partially_approved"
        loan.save()
        messages.success(request, "Treasurer approval recorded.")
        return redirect('treasurer_dashboard')

    # ---------------------------------------------------------
    # 3️⃣ ADMIN LAST / FINAL (Type '1')
    # ---------------------------------------------------------
    elif u_type == '1' or user.is_superuser:
        if not (loan.staff_approved and loan.treasurer_approved):
            messages.error(request, "Staff and Treasurer must sign off before final approval.")
            return redirect('admin_dashboard')

        with transaction.atomic():
            loan.admin_approved = True
            loan.status = "approved"
            loan.approval_date = timezone.now()

            # --- X-MASS CALCULATIONS (Fixed 25.9% Interest, 3 Months) ---
            principal = Decimal(str(loan.amount_requested))
            interest_rate = Decimal('0.259') 
            duration_months = 3

            total_interest = principal * interest_rate
            total_payable = principal + total_interest
            monthly_installment = total_payable / Decimal(str(duration_months))

            # --- GENERATE 3-MONTH SCHEDULE ---
            # Clean old schedules if they exist
            LoanRepaymentSchedule.objects.filter(loan_id=loan.id, is_xmas=True).delete()

            for i in range(1, duration_months + 1):
                LoanRepaymentSchedule.objects.create(
                    xmas_loan=loan,
                    loan=None,# Link to the Xmas loan
                    installment_number=i,
                    due_date=loan.approval_date.date() + relativedelta(months=i),
                    amount_due=monthly_installment,
                    is_paid=False,
                    is_xmas=True # Helpful flag to distinguish from regular loans
                )

            loan.save()

        messages.success(request, f"X-Mass Loan Fully Approved! Total: KES {total_payable:,.2f}")
        return redirect('admin_dashboard')

    return redirect('member_dashboard')

def reject_xmas_loan(request, loan_id):
    """If any official rejects, the application status is set to 'rejected'."""
    loan = get_object_or_404(XmasLoan, id=loan_id)
    user = request.user
    u_type = getattr(user, 'user_type', None)
    
    loan.status = 'rejected'
    loan.save()
    
    messages.warning(request, "Holiday loan application has been rejected.")
    
    # Finalized Redirection logic
    if u_type == '1' or user.is_superuser:
        return redirect('admin_dashboard')
    elif u_type == '2':
        return redirect('staff_dashboard')  
    elif u_type == '3':
        return redirect('treasurer_dashboard') # Fixed typo and changed to redirect
    
    return redirect('member_dashboard')


@login_required
@role_required(allowed_roles=['3'])  # Treasurer only
def loan_detail(request, loan_id):
    loan = get_object_or_404(Loan, id=loan_id)

    guarantors = Guarantor.objects.filter(loan=loan)

    return render(request, 'dat.html', {
        'loan': loan,
        'guarantors': guarantors,
    })

def calculate_penalty(loan):
    overdue_schedules = LoanRepaymentSchedule.objects.filter(
        loan=loan,
        is_paid=False,
        due_date__lt=date.today()
    )
    
    penalty_rate = Decimal('0.02')  # 2% per month
    total_penalty = Decimal('0.00')
    
    for installment in overdue_schedules:
        months_overdue = (date.today().year - installment.due_date.year) * 12 + (date.today().month - installment.due_date.month)
        if months_overdue > 0:
            total_penalty += installment.amount_due * penalty_rate * months_overdue
    
    return total_penalty

@login_required


# Make sure your function is imported

def pay_loan(request):
    profile = request.user.profile

    # 🔍 Get active loan
    active_loan = Loan.objects.filter(
        member=profile,
        status__in=['approved', 'disbursed']
    ).order_by('-id').first()

    if not active_loan:
        messages.info(request, "No active loan found to pay.")
        return redirect('member_dashboard')

    # 🔥 Calculate penalties
    overdue_schedules = LoanRepaymentSchedule.objects.filter(
        loan=active_loan,
        is_paid=False,
        due_date__lt=date.today()
    )

    penalty_rate = Decimal('0.02')
    total_penalty = Decimal('0.00')

    for inst in overdue_schedules:
        months = (date.today().year - inst.due_date.year) * 12 + (date.today().month - inst.due_date.month)
        if months > 0:
            total_penalty += inst.amount_due * penalty_rate * months

    # 🚫 Handle manual payment (Treasurer only)
    if request.method == "POST":
        if request.user.user_type == '4':  # Member
            messages.error(request, "Members can only pay via M-Pesa.")
            return redirect('pay_loan')

        form = LoanRepaymentForm(request.POST, user_profile=profile)

        if form.is_valid():
            try:
                with transaction.atomic():
                    repayment = form.save(commit=False)
                    repayment.member = profile
                    repayment.loan = active_loan
                    repayment.save()

                    # 💰 Distribute payment across schedules
                    amount = repayment.amount_paid
                    schedules = LoanRepaymentSchedule.objects.filter(
                        loan=active_loan,
                        is_paid=False
                    ).order_by('due_date')

                    for inst in schedules:
                        if amount <= 0:
                            break
                        if amount >= inst.amount_due:
                            amount -= inst.amount_due
                            inst.is_paid = True
                            inst.save()
                        else:
                            break

                    # 💾 Excess → Monthly Contribution
                    if amount > 0:
                        MonthlyContribution.objects.create(
                            member=profile,
                            amount=amount,
                            month=timezone.now().date()
                        )

                    # ✅ Update loan status
                    total_payable = LoanRepaymentSchedule.objects.filter(
                        loan=active_loan
                    ).aggregate(Sum('amount_due'))['amount_due__sum'] or Decimal('0')

                    total_paid = LoanRepayment.objects.filter(
                        loan=active_loan
                    ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0')

                    if total_paid >= (total_payable + total_penalty):
                        active_loan.status = 'completed'
                        active_loan.save()

                messages.success(request, f"Payment of KES {repayment.amount_paid:,.2f} recorded.")
                return redirect('pay_loan')

            except Exception as e:
                messages.error(request, f"Error: {str(e)}")

    else:
        form = LoanRepaymentForm(user_profile=profile)

    # 📊 UI calculations
    total_loan_payable = LoanRepaymentSchedule.objects.filter(
        loan=active_loan
    ).aggregate(Sum('amount_due'))['amount_due__sum'] or Decimal('0')

    total_repaid = LoanRepayment.objects.filter(
        loan=active_loan
    ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0')

    remaining_balance = (total_loan_payable - total_repaid) + total_penalty

    next_installment = LoanRepaymentSchedule.objects.filter(
        loan=active_loan,
        is_paid=False
    ).order_by('due_date').first()

    # 🔥 Use your calculate_insurance function
    insurance_total = calculate_insurance(active_loan.amount, active_loan.duration_months)
    duration = active_loan.duration_months or 1

    monthly_principal = active_loan.amount / duration
    monthly_insurance = insurance_total / duration

    if next_installment:
        monthly_interest = next_installment.amount_due - monthly_principal - monthly_insurance
    else:
        monthly_interest = Decimal('0')

    progress_percent = (total_repaid / total_loan_payable * 100) if total_loan_payable > 0 else 0

    return render(request, 'pay_loan.html', {
        'form': form,
        'active_loan': active_loan,
        'remaining_balance': remaining_balance,
        'total_loan_payable': total_loan_payable,
        'next_installment': next_installment,
        'monthly_principal': monthly_principal,
        'monthly_interest': monthly_interest,
        'insurance_amount': insurance_total,
        'progress_percent': progress_percent,
        'total_penalty': total_penalty,
    })
@role_required(allowed_roles=['3'])  # Only Treasurer
def treasurer_pay_Xloan(request, loan_id):
    loan = get_object_or_404(XmasLoan, id=loan_id)

    if request.user.user_type != '3':  # Only Treasurer
        messages.error(request, "Unauthorized access")
        return redirect('treasurer_dashboard')

    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get('amount'))

            with transaction.atomic():
                # 1️⃣ Record repayment
                repayment = LoanRepayment.objects.create(
                    is_xmas=True,
                    member=loan.member,
                    amount_paid=amount,
                    reference=generate_transaction_ref("TR")
                )

                # 2️⃣ Apply to repayment schedule 
                # CHANGE: Use xmas_loan=loan instead of loan=loan
                amount_to_distribute = amount
                schedules = LoanRepaymentSchedule.objects.filter(
                    xmas_loan=loan, is_paid=False, is_xmas=True
                ).order_by('due_date')

                for installment in schedules:
                    if amount_to_distribute <= 0:
                        break
                    if amount_to_distribute >= installment.amount_due:
                        amount_to_distribute -= installment.amount_due
                        installment.is_paid = True
                        installment.save()
                    else:
                        # Optional: partial payment logic could go here
                        break

                # 3️⃣ Excess goes to savings
                if amount_to_distribute > 0:
                    MonthlyContribution.objects.create(
                        member=loan.member,
                        amount=amount_to_distribute,
                        month=timezone.now().date()
                    )

                # 4️⃣ Update loan status
                # CHANGE: Aggregate based on the xmas_loan field
                total_payable = LoanRepaymentSchedule.objects.filter(
                    xmas_loan=loan
                ).aggregate(Sum('amount_due'))['amount_due__sum'] or Decimal('0.00')

                # Using the @property you already defined in the XmasLoan model
                if loan.total_paid >= total_payable:
                    loan.status = 'completed'
                    loan.save()

                # 5️⃣ Log transaction
                Transaction.objects.create(
                    member=loan.member,
                    transaction_type='repayment',
                    amount=amount,
                    reference=repayment.reference
                )

            messages.success(request, f"Payment of KES {amount} recorded for {loan.member}")
            return redirect('treasurer_dashboard')

        except Exception as e:
            messages.error(request, f"Error processing payment: {str(e)}")

    return render(request, "treasurer_pay.html", {"loan": loan})
@login_required
@role_required(allowed_roles=['3'])  # Only Treasurer
def treasurer_pay_loan(request, loan_id):
    loan = get_object_or_404(Loan, id=loan_id)

    if request.user.user_type != '3':  # Only Treasurer
        messages.error(request, "Unauthorized access")
        return redirect('treasurer_dashboard')
    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get('amount'))

            with transaction.atomic():
                # 1️⃣ Record repayment
                repayment = LoanRepayment.objects.create(
                    loan=loan,
                    member=loan.member,
                    amount_paid=amount,
                    reference=generate_transaction_ref("TR")
                )

                # 2️⃣ Apply to repayment schedule
                amount_to_distribute = amount
                schedules = LoanRepaymentSchedule.objects.filter(
                    loan=loan, is_paid=False
                ).order_by('due_date')

                for installment in schedules:
                    if amount_to_distribute <= 0:
                        break
                    if amount_to_distribute >= installment.amount_due:
                        amount_to_distribute -= installment.amount_due
                        installment.is_paid = True
                        installment.save()
                    else:
                        break

                # 3️⃣ Excess goes to savings
                if amount_to_distribute > 0:
                    MonthlyContribution.objects.create(
                        member=loan.member,
                        amount=amount_to_distribute,
                        month=timezone.now().date()
                    )

                # 4️⃣ Update loan status
                total_payable = LoanRepaymentSchedule.objects.filter(
                    loan=loan
                ).aggregate(Sum('amount_due'))['amount_due__sum'] or Decimal('0.00')

                total_paid = LoanRepayment.objects.filter(
                    loan=loan
                ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

                if total_paid >= total_payable:
                    loan.status = 'completed'
                    loan.save()

                # 5️⃣ Log transaction
                Transaction.objects.create(
                    member=loan.member,
                    transaction_type='repayment',
                    amount=amount,
                    reference=repayment.reference
                )

            messages.success(request, f"Payment of KES {amount} recorded for {loan.member}")
            return redirect('treasurer_dashboard')

        except Exception as e:
            messages.error(request, f"Error processing payment: {str(e)}")

    # Render the page for GET request
    return render(request, "treasurer_pay_loan.html", {"loan": loan})
@login_required
@role_required(allowed_roles=['2', '4'])  # Staff and Admin
def staff_dashboard(request):
    # Ensure only staff can access
    if not request.user.is_authenticated:
        return redirect('login')  # redundant with @login_required but safe

    if request.user.user_type != '2' and not request.user.is_superuser:
        return redirect('access_denied')  # Redirect to an access denied page or show message

    # Your dashboard logic here
    pending_loans = Loan.objects.filter(
        staff_approved=False,
        status__in=['pending', 'partially_approved']
    ).order_by('-application_date')
    pending_xmas_loans = XmasLoan.objects.filter(status='pending').order_by('-application_date')

    total_savings_pool = MonthlyContribution.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    total_members = Profile.objects.count()
    total_interest_earned = LoanRepaymentSchedule.objects.filter(is_paid=True).aggregate(Sum('amount_due'))['amount_due__sum'] or 0

    context = {
        'pending_loans': pending_loans,
        'total_savings_pool': total_savings_pool,
        'total_members': total_members,
        'total_interest_earned': total_interest_earned,
        'pending_xmas_loans': pending_xmas_loans,
    }

    return render(request, 'stf.html', context)
def rejected_loans_view(request):
    rejected_loans = Loan.objects.filter(status='rejected')
    context = {
        'rejected_loans': rejected_loans
    }
    return render(request, 'rejected_loans.html', context)
def Completed_loans(request):
    complete=Loan.objects.filter(status="completed")
    context={
        'complete':complete
        
    }
    return render (request, 'complet.html',context)
def approved_loans_view(request):
    approved_loans = Loan.objects.filter(status='approved')
    context = {
        'approved_loans': approved_loans
    }
    return render(request, 'approved_loan.html', context)
def Xm_approved(request):
    approved_loans = XmasLoan.objects.filter(status='approved')
    context = {
        'approved_loans': approved_loans
    }
    return render(request, 'approved_Xm.html', context)

def pending_loans_view(request):
    pending_loans = Loan.objects.filter(status='pending')
    context = {
        'pending_loans': pending_loans
    }
    return render(request, 'pending_loans.html', context)
def active_xmas_loan(request):
    # This covers both the string status and the boolean flag
    xm_active = XmasLoan.objects.filter(status='disbursed', is_disbursed=True)
    return render(request, 'xm_active.html', {'xm_active': xm_active})
@transaction.atomic
def disburse_loan_xmass(request, loan_id):
    loan = get_object_or_404(XmasLoan, id=loan_id)

    # 1. Validation: Use the new property to check for the 3 sign-offs
    if loan.approval_progress < 3:
        messages.error(request, "This loan requires Staff, Treasurer, and Admin approval before disbursement.")
        return redirect('treasurer_dashboard')

    if loan.is_disbursed:
        messages.warning(request, "This loan has already been disbursed.")
        return redirect('treasurer_dashboard')

    # 2. Update Loan Record
    loan.is_disbursed = True
    loan.status = 'disbursed'
    loan.disbursement_date = timezone.now()
    loan.save()

    # 3. Financial Record
    # Note: Using amount_requested as per your XmasLoan model
    record_transaction(
        member_profile=loan.member,
        type='loan_disbursement',
        amount=loan.amount_requested,
        reference=f"XMASS-{loan.id}-{timezone.now().year}"
    )

    messages.success(request, f"Successfully disbursed KES {loan.amount_requested} to {loan.member}.")
    return redirect('treasurer_dashboard')
def active_loan(request):
    # Filter for disbursed loans
    active_loans = Loan.objects.filter(status='disbursed')
    
    context = {
        "active_loans": active_loans # Changed from 'active_lons'
    }
    return render(request, 'active.html', context)
def monthly_repayment_report(request):
    prof = Profile.objects.all()
    report_data = LoanRepayment.objects.annotate(
        month=TruncMonth('payment_date')
    ).values(
        'month',
        'member__user__first_name',
        'member__user__last_name',
        'member__pf_number',  # <-- Add this
        'loan__id'
    ).annotate(
        total_paid=Sum('amount_paid')
    ).order_by('-month')

    context = {
        'report_data': report_data,
        'prof': prof
    }
    return render(request, 'report.html', context)

@login_required
@role_required(allowed_roles=['1','3'])  # Treasurer only
def treasurer_dashboard(request):
    # 1. Security Check (Uncommented for safety)
    if getattr(request.user, 'user_type', None) != '3' and not request.user.is_superuser:
        return redirect('access_denied')  # Redirect to an access denied page or show message

    # 2. Filter loans specifically awaiting THIS treasurer's signature
    # We look for loans that are not yet approved by treasurer but aren't rejected
    awaiting_treasurer = Loan.objects.filter(
        treasurer_approved=False, 
        status__in=['pending', 'partially_approved']
    ).order_by('-application_date')

    # 3. Financial Calculations
    # Using Decimal('0') ensures compatibility with DecimalField in models
    total_savings = MonthlyContribution.objects.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    total_shares = CapitalShare.objects.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    active_loans_value = Loan.objects.filter(
    is_disbursed=True
).aggregate(total=Sum('amount'))['total'] or Decimal('0')   
    # Calculate Interest Earned (Payments made minus estimated principal portion or just total interest collected)
    total_interest_earned = LoanRepaymentSchedule.objects.filter(is_paid=True).aggregate(Sum('amount_due'))['amount_due__sum'] or Decimal('0')
    pending_xmas_loans = XmasLoan.objects.filter(
        status__in=['pending', 'partially_approved'], 
        treasurer_approved=False
    )
    # Calculate Liquidity
    total_repayments = LoanRepayment.objects.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0')
    
    # Formula: (Money In) - (Money Out)
    available_cash = (total_savings + total_shares + total_repayments) - active_loans_value

    # 4. Recent Activity
    recent_transactions = Transaction.objects.all().order_by('-created_at')[:10]

    context = {
        'pending_xmas_loans': pending_xmas_loans,
        'awaiting_treasurer': awaiting_treasurer,
        'total_savings': total_savings,
        'total_shares': total_shares,
        'active_loans_value': active_loans_value,
        'available_cash': available_cash,
        'total_interest': total_interest_earned,
        'recent_transactions': recent_transactions,
    }

    return render(request, 'treasurer_dashboard.html', context)



def all_savings(request):
    savings = MonthlyContribution.objects.all()
    total_savings = savings.aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'savings': savings,
        'total_savings': total_savings
    }
    return render(request, 'sav.html', context)

def my_savings(request):
    profile = request.user.profile

    savings = MonthlyContribution.objects.filter(member=profile).order_by('-month')

    total_savings = savings.aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'savings': savings,
        'total_savings': total_savings
    }

    return render(request, 'mysaving.html', context)
@login_required
def my_loans(request):
    profile = request.user.profile

    # Only loans for this member, ordered by newest first
    loans = Loan.objects.filter(member=profile).order_by('-application_date')

    context = {
        'loans': loans
    }
    return render(request, 'my_loans.html', context)
def my_shares(request):
    profile = request.user.profile

    shares = CapitalShare.objects.filter(member=profile).order_by('-date_paid')

    total_shares = shares.aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'shares': shares,
        'total_shares': total_shares
    }

    return render(request, 'my_shares.html', context)
# @login_required
def approve_loan(request, loan_id):
    loan = get_object_or_404(Loan, id=loan_id)
    user = request.user
    u_type = getattr(user, 'user_type', None)

    # ❌ Prevent approving rejected or already approved loans
    if loan.status in ['rejected', 'approved']:
        messages.error(request, "Loan already finalized.")
        return redirect('member_dashboard')

    # -------------------------
    # ✅ ENFORCE APPROVAL ORDER
    # -------------------------

    # 1️⃣ STAFF FIRST
    if u_type == '2':
        loan.staff_approved = True
        loan.status = "partially_approved"
        loan.save()
        messages.success(request, "Staff approved.")
        return redirect('staff_dashboard')

    # 2️⃣ TREASURER SECOND (only after staff)
    elif u_type == '3':
        if not loan.staff_approved:
            messages.error(request, "Staff must approve first.")
            return redirect('treasurer_dashboard')

        loan.treasurer_approved = True
        loan.status = "partially_approved"
        loan.save()
        messages.success(request, "Treasurer approved.")
        return redirect('treasurer_dashboard')

    # 3️⃣ ADMIN LAST (FINAL)
    elif u_type == '1' or user.is_superuser:
        if not (loan.staff_approved and loan.treasurer_approved):
            messages.error(request, "Staff and Treasurer must approve first.")
            return redirect('admin_dashboard')

        # -------------------------
        # ✅ FINAL APPROVAL
        # -------------------------
        with transaction.atomic():
            loan.admin_approved = True
            loan.status = "approved"
            loan.approval_date = timezone.now()

            # --- CALCULATIONS ---
            principal = Decimal(str(loan.amount))
            interest_rate = Decimal('0.259')
            duration_years = Decimal(str(loan.duration_months)) / Decimal('12')

            total_interest = principal * interest_rate * duration_years
            insurance = calculate_insurance(principal, loan.duration_months)
            total_payable = principal + total_interest + insurance
            monthly_installment = total_payable / Decimal(str(loan.duration_months))

            # --- SCHEDULE ---
            LoanRepaymentSchedule.objects.filter(loan=loan).delete()

            for i in range(1, loan.duration_months + 1):
                LoanRepaymentSchedule.objects.create(
                    loan=loan,
                    installment_number=i,
                    due_date=loan.approval_date.date() + relativedelta(months=i),
                    amount_due=monthly_installment,
                    is_paid=False
                )

            loan.save()

        messages.success(
            request,
            f"Loan Fully Approved! Total: KES {total_payable:,.2f}"
        )
        return redirect('admin_dashboard')

    return redirect('member_dashboard')
@login_required
def reject_loan(request, loan_id):
    loan = get_object_or_404(Loan, id=loan_id)
    user = request.user

    # ❌ stop if already finalized
    if loan.status in ['approved', 'rejected']:
        messages.error(request, "Loan already finalized.")
        return redirect('member_dashboard')

    # 🔴 ONE REJECTION = FULL REJECTION
    loan.status = "rejected"
    loan.save()

    messages.error(request, "Loan rejected.")

    u_type = getattr(user, 'user_type', None)
    if user.is_superuser or u_type == '1': 
        return redirect('admin_dashboard')
    if u_type == '2': 
        return redirect('staff_dashboard')
    if u_type == '3': 
        return redirect('treasurer_dashboard')

    return redirect('member_dashboard')
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


@login_required
def disburse_loan(request, loan_id):
    loan = get_object_or_404(Loan, id=loan_id)

    if loan.status != 'approved':
        messages.error(request, "Loan must be approved first.")
        return redirect('treasurer_dashboard')

    if loan.is_disbursed:
        messages.warning(request, "Loan already disbursed.")
        return redirect('treasurer_dashboard')

    with transaction.atomic():
        loan.is_disbursed = True
        loan.status = 'disbursed'   # 🔥 ADD THIS
        loan.disbursed_at = timezone.now()
        loan.save()

        # Record transaction (money leaving SACCO)
        record_transaction(
            member_profile=loan.member,
            type='loan_disbursement',
            amount=loan.amount,
            reference=f"DISB-Loan#{loan.id}"
        )

    messages.success(request, "Loan disbursed successfully.")
    return redirect('treasurer_dashboard')


@login_required
def initiate_stk_push(request):
    if request.method == "POST":
        payment_type = request.POST.get('payment_type') # 'loan', 'shares', 'xmas', or 'savings'
        amount = request.POST.get('amount')
        
        # --- MULTI-USER LOGIC ---
        # Treasurer can initiate for others, or members for themselves
        member_id = request.POST.get('member_id')
        if member_id:
            target_profile = get_object_or_404(Profile, id=member_id)
        else:
            target_profile = request.user.profile

        phone = target_profile.phone_number 
        
        # Helper functions for M-Pesa Auth
        access_token = get_mpesa_access_token()
        password, timestamp = get_mpesa_password()
        headers = {"Authorization": f"Bearer {access_token}"}

        # --- BUSINESS DETAILS ---
        business_no = "400222"
        sacco_acc_no = "1072289#"

        # --- DYNAMIC REFERENCE LOGIC ---
        # We combine the Sacco Account No with the specific tag for the callback to read
        if payment_type == 'shares':
            account_ref = f"{sacco_acc_no}SHARES{target_profile.user.id}"
            description = f"Shares - {target_profile.user.username}"
            
        elif payment_type == 'savings':
            account_ref = f"{sacco_acc_no}SAVINGS{target_profile.id}"
            description = f"Savings - {target_profile.user.username}"
            
        elif payment_type == 'xmas':
            loan_id = request.POST.get('loan_id')
            account_ref = f"{sacco_acc_no}XMAS{loan_id}"
            description = "Xmas Loan Repayment"
            
        else:
            # Default to Normal Loan Repayment
            loan_id = request.POST.get('loan_id')
            account_ref = f"{sacco_acc_no}LOAN{loan_id}"
            description = "Loan Repayment"

        # --- API REQUEST BODY ---
        request_body = {
            "BusinessShortCode": business_no,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline", # Standard for Paybill STK
            "Amount": int(float(amount)),
            "PartyA": phone,
            "PartyB": business_no,  # For Paybill, PartyB is the ShortCode
            "PhoneNumber": phone,
            "CallBackURL": "https://yourdomain.com/mpesa-callback/", # Change to your live URL/Ngrok
            "AccountReference": account_ref, 
            "TransactionDesc": description
        }
        
        try:
            # If moving to production, change 'sandbox' to 'api'
            mpesa_endpoint = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
            
            response = requests.post(
                mpesa_endpoint,
                json=request_body,
                headers=headers
            )
            
            response_data = response.json()
            
            if response_data.get("ResponseCode") == "0":
                messages.success(request, f"STK Push for {description} sent successfully to {phone}!")
            else:
                error_msg = response_data.get('CustomerMessage', 'Failed to send prompt')
                messages.error(request, f"M-Pesa Error: {error_msg}")
                
        except Exception as e:
            messages.error(request, f"Connection Error: {str(e)}")
        
        # Redirect back based on user role
        if request.user.groups.filter(name='Treasurer').exists():
            return redirect('approved_loans')
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
#

@login_required
def purchase_shares(request):
    user_profile = request.user.profile

    # Only members (not treasurers) can access this
    if request.user.user_type != '3':  # assuming '3' is treasurer
        if request.method == "POST":
            form = SharesForm(request.POST)
            if form.is_valid():
                share = form.save(commit=False)
                share.member = user_profile
                share.save()
                messages.success(request, f"Share purchase of KES {share.amount} has been recorded. Please complete M-Pesa payment.")
                return redirect("member_dashboard")
        else:
            form = SharesForm()
        return render(request, "shares.html", {"form": form})
    
    # If treasurer, we could later add manual + mpesa
    return redirect("treasurer_dashboard")
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
@login_required
@role_required(allowed_roles=['3'])
def treasurer_purchase_shares(request, member_id):
    member_profile = get_object_or_404(Profile, id=member_id)

    if request.method == "POST":
        form = SharesForm(request.POST)

        if form.is_valid():
            try:
                with transaction.atomic():
                    share = form.save(commit=False)
                    share.member = member_profile
                    share.save()

                    # Transaction record
                    Transaction.objects.create(
                        member=member_profile,
                        transaction_type='shares',
                        amount=share.amount,
                        # reference=f"CASH-{request.POST.get('receipt_no')}"
                    )

                messages.success(
                    request,
                    f"KES {share.amount} shares recorded for {member_profile.user.get_full_name()}"
                )
                return redirect('Members')

            except Exception as e:
                messages.error(request, f"Database Error: {str(e)}")
        else:
            messages.error(request, "Please correct the form errors.")

    else:
        form = SharesForm()

    return render(request, 'treasurer_confirm_share.html', {
        'member': member_profile,
        'form': form
    })
@login_required
@role_required(allowed_roles=['1', '2', '3', '4'])  # Staff, Treasurer, Admin
def member_individual_report(request):
    # Get the profile of the currently logged-in user
    member = request.user.profile 
    
    shares = CapitalShare.objects.filter(member=member).order_by('-date_created')
    total_shares = shares.aggregate(Sum('amount'))['amount__sum'] or 0
    
    loans = Loan.objects.filter(member=member).order_by('-application_date')
    
    repayments = LoanRepayment.objects.filter(member=member).order_by('-payment_date')
    total_repaid = repayments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
    
    context = {
        'member': member,
        'shares': shares,
        'total_shares': total_shares,
        'loans': loans,
        'repayments': repayments,
        'total_repaid': total_repaid,
    }
    return render(request, 'member_report.html', context)
@role_required(allowed_roles=['3', '5'])  # HR Only
def Members(request):
    # Fetch all members and prefetch related loans for efficiency
    members = Profile.objects.prefetch_related('member_loans')  # ✅ works
    return render(request, 'mem.html', {'members': members})

def Human_Resource(request):
    if getattr(request.user, 'user_type', None) != '5' and not request.user.is_superuser:
        return redirect('access_denied')
    query = request.GET.get('q')
    users = Profile.objects.all().select_related('user')
    
    # Dashboard Aggregates
    total_gross = users.aggregate(Sum('gross_salary'))['gross_salary__sum'] or 0
    total_net = users.aggregate(Sum('net_salary'))['net_salary__sum'] or 0
    avg_gross = users.aggregate(Avg('gross_salary'))['gross_salary__avg'] or 0
    
    if query:
        users = users.filter(
            Q(user__first_name__icontains=query) | 
            Q(user__last_name__icontains=query) |
            Q(pf_number__icontains=query)
        )
        
    context = {
        'users': users,
        'total_gross': total_gross,
        'total_net': total_net,
        'avg_gross': avg_gross,
        'member_count': users.count(),
    }
        
    return render(request, 'hr.html', context)
# views.py


def monthly_sacco_report(request):
    month = int(request.GET.get('month', timezone.now().month))
    year = int(request.GET.get('year', timezone.now().year))
    
    report_data = []
    profiles = Profile.objects.all().select_related('user')

    for profile in profiles:

        # -------------------------------
        # 1. SAVINGS & SHARES
        # -------------------------------
        monthly_txs = Transaction.objects.filter(
            member=profile,
            created_at__month=month,
            created_at__year=year
        )

        savings_paid = monthly_txs.filter(
            transaction_type='deposit'  # ✅ FIXED
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

        shares_paid = monthly_txs.filter(
            transaction_type='shares'
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

        # -------------------------------
        # 2. NORMAL LOAN
        # -------------------------------
        normal_loan = Loan.objects.filter(
            member=profile,
            purpose='normal Loan',
            status__in=['approved', 'disbursed']
        ).first()

        if normal_loan:
            expected_normal = normal_loan.monthly_installment
            paid_normal = LoanRepayment.objects.filter(
                loan=normal_loan,
                payment_date__month=month,
                payment_date__year=year
            ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

            normal_inst = expected_normal
            normal_status = paid_normal >= expected_normal
        else:
            normal_inst = Decimal('0.00')
            normal_status = False

        # -------------------------------
        # 3. XMAS LOAN
        # -------------------------------
        xmas_loan = XmasLoan.objects.filter(
            member=profile,
            status__in=['approved', 'disbursed'],
            year=year
        ).first()

        if xmas_loan:
            expected_xmas = xmas_loan.monthly_installment
            paid_xmas = LoanRepayment.objects.filter(
                member=profile,
                is_xmas=True,
                payment_date__month=month,
                payment_date__year=year
            ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

            xmas_inst = expected_xmas
            xmas_status = paid_xmas >= expected_xmas
        else:
            xmas_inst = Decimal('0.00')
            xmas_status = False

        # -------------------------------
        # 4. SCHOOL FEES LOAN
        # -------------------------------
        school_loan = Loan.objects.filter(
            member=profile,
            purpose='choll fees',
            status__in=['approved', 'disbursed']
        ).first()

        if school_loan:
            expected_school = school_loan.monthly_installment
            paid_school = LoanRepayment.objects.filter(
                loan=school_loan,
                payment_date__month=month,
                payment_date__year=year
            ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

            school_inst = expected_school
            school_status = paid_school >= expected_school
        else:
            school_inst = Decimal('0.00')
            school_status = False

        # -------------------------------
        # 5. EMERGENCY LOAN
        # -------------------------------
        emergency_loan = Loan.objects.filter(
            member=profile,
            purpose='emergency',
            status__in=['approved', 'disbursed']
        ).first()

        if emergency_loan:
            expected_emergency = emergency_loan.monthly_installment
            paid_emergency = LoanRepayment.objects.filter(
                loan=emergency_loan,
                payment_date__month=month,
                payment_date__year=year
            ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

            emergency_inst = expected_emergency
            emergency_status = paid_emergency >= expected_emergency
        else:
            emergency_inst = Decimal('0.00')
            emergency_status = False

        # -------------------------------
        # 6. BUILD ROW
        # -------------------------------
        row = {
            'name': profile.user.get_full_name() or profile.user.username,
            'pf': profile.pf_number,

            'savings_amt': savings_paid,
            'savings_status': savings_paid > 0,

            'shares_amt': Decimal('1000.00'),  # fixed
            'shares_status': shares_paid > 0,

            'normal_loan': normal_inst,
            'normal_status': normal_status,

            'xmas_loan': xmas_inst,
            'xmas_status': xmas_status,

            'scholl_fees': school_inst,
            'school_status': school_status,

            'emergency': emergency_inst,
            'emergency_status': emergency_status,

            'total_paid': (
                savings_paid +
                shares_paid +
                normal_inst +
                xmas_inst +
                school_inst +
                emergency_inst
            )
        }

        report_data.append(row)

    # -------------------------------
    # CSV EXPORT
    # -------------------------------
    if 'export' in request.GET:
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="SACCO_Report_{month}_{year}.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Member Name', 'PF Number',
            'Savings', 'Shares',
            'Normal Loan', 'Xmas Loan',
            'School Fees', 'Emergency'
        ])

        for row in report_data:
            writer.writerow([
                row['name'],
                row['pf'],
                0 if row['savings_status'] else 500,
                0 if row['shares_status'] else 1000,
                0 if row['normal_status'] else row['normal_loan'],
                0 if row['xmas_status'] else row['xmas_loan'],
                0 if row['school_status'] else row['scholl_fees'],
                0 if row['emergency_status'] else row['emergency'],
            ])

        return response

    # -------------------------------
    # RENDER
    # -------------------------------
    context = {
        'report_data': report_data,
        'month': month,
        'year': year,
        'years': range(2023, 2100),
        'months': range(1, 13), 
        'months_choices': [
            (1, 'Jan'), (2, 'Feb'), (3, 'Mar'), (4, 'Apr'), 
            (5, 'May'), (6, 'Jun'), (7, 'Jul'), (8, 'Aug'), 
            (9, 'Sep'), (10, 'Oct'), (11, 'Nov'), (12, 'Dec')
        ], 
    }
    

    return render(request, 'monthly_report.html', context)

def export_sacco_report_csv(report_data, month, year):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="SACCO_Report_{month}_{year}.csv"'
    
    writer = csv.writer(response)
    # Header
    writer.writerow(['Member Name', 'PF Number', 'Savings', 'Shares', 'Normal Loan', 'Xmas Loan', 'School Fees', 'Emergency', 'Total Received'])
    
    # Data rows
    for row in report_data:
        writer.writerow([
            row['name'], row['pf'], row['savings_amt'], row['shares_amt'],
            row['normal_loan'], row['xmas_loan'], row['scholl_fees'], row['emergency'], row['total_paid']
        ])
    
    return response



def financial_ledger_view(request):
    user_profile = request.user.profile  # Get current user's profile
    
    # --- MEMBER SAVINGS LOGIC ---
    monthly_savings = MonthlyContribution.objects.filter(member=user_profile)
    capital_shares = CapitalShare.objects.filter(member=user_profile)
    
    total_savings = (monthly_savings.aggregate(Sum('amount'))['amount__sum'] or 0) + \
                    (capital_shares.aggregate(Sum('amount'))['amount__sum'] or 0)

    # Combine for the Ledger Table
    ledger_entries = []
    for s in monthly_savings:
        ledger_entries.append({'date': s.created_at, 'type': 'Monthly Saving', 'amount': s.amount, 'month': s.month})
    for c in capital_shares:
        ledger_entries.append({'date': c.date_created, 'type': 'Capital Share', 'amount': c.amount, 'month': c.month})
    
    # Sort ledger by date descending
    ledger_entries = sorted(ledger_entries, key=lambda x: x['date'], reverse=True)

    # --- MEMBER LOAN LOGIC ---
    repayments = LoanRepayment.objects.filter(member=user_profile).order_by('-payment_date')
    total_repaid = repayments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
    
    active_loans = Loan.objects.filter(member=user_profile, status='disbursed').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    active_xmas = XmasLoan.objects.filter(member=user_profile, is_disbursed=True).aggregate(Sum('amount_requested'))['amount_requested__sum'] or Decimal('0.00')
    
    current_loan_balance = (active_loans + active_xmas) - total_repaid

    # --- TREASURER GLOBAL LOGIC (Only for Admin/Staff/Treasurer) ---
    sacco_stats = {}
    if request.user.user_type in ['1', '2', '3']:
        t_monthly = MonthlyContribution.objects.aggregate(Sum('amount'))['amount__sum'] or 0
        t_shares = CapitalShare.objects.aggregate(Sum('amount'))['amount__sum'] or 0
        t_loans = Loan.objects.filter(status='disbursed').aggregate(Sum('amount'))['amount__sum'] or 0
        t_xmas = XmasLoan.objects.filter(is_disbursed=True).aggregate(Sum('amount_requested'))['amount_requested__sum'] or 0
        t_repaid = LoanRepayment.objects.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
        
        sacco_stats = {
            'total_equity': t_monthly + t_shares,
            'total_out': t_loans + t_xmas,
            'liquidity': (t_monthly + t_shares + t_repaid) - (t_loans + t_xmas)
        }

    context = {
        'total_savings': total_savings,
        'ledger': ledger_entries,
        'current_balance': current_loan_balance,
        'history': repayments,
        'sacco_stats': sacco_stats,
    }
    return render(request, 'financial_report.html', context)


def get_daily_financial_summary():
    """Calculates total cash flow for the current day."""
    today = timezone.now().date()
    
    # Sum of all money coming IN
    inflow = Transaction.objects.filter(
        created_at__date=today,
        transaction_type__in=['deposit', 'repayment', 'shares']
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Sum of all money going OUT
    outflow = Transaction.objects.filter(
        created_at__date=today,
        transaction_type='loan'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    return {
        'inflow': inflow,
        'outflow': outflow,
        'net_flow': inflow - outflow
    }

def sacco_financial_ledger_view(request):

    # -------------------------------
    # 🔹 ALL SAVINGS (WHOLE SACCO)
    # -------------------------------
    monthly_savings = MonthlyContribution.objects.all()
    capital_shares = CapitalShare.objects.all()

    total_monthly = monthly_savings.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    total_shares = capital_shares.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

    total_savings = total_monthly + total_shares

    # -------------------------------
    # 🔹 LEDGER ENTRIES (GLOBAL)
    # -------------------------------
    ledger_entries = []

    # Savings
    for s in monthly_savings:
        ledger_entries.append({
            'date': s.created_at,
            'type': 'Monthly Saving',
            'member': s.member.user.username,
            'amount': s.amount,
            'month': s.month
        })

    # Shares
    for c in capital_shares:
        ledger_entries.append({
            'date': c.date_created,
            'type': 'Capital Share',
            'member': c.member.user.username,
            'amount': c.amount,
            'month': c.month
        })

    # -------------------------------
    # 🔹 LOAN DISBURSEMENTS
    # -------------------------------
    loans = Loan.objects.filter(status='disbursed')
    xmas_loans = XmasLoan.objects.filter(is_disbursed=True)

    total_loans = loans.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    total_xmas = xmas_loans.aggregate(Sum('amount_requested'))['amount_requested__sum'] or Decimal('0.00')

    # Add loans to ledger
    for l in loans:
        ledger_entries.append({
            'date': l.disbursed_at,
            'type': 'Loan Disbursed',
            'member': l.member.user.username,
            'amount': l.amount,
            'month': l.disbursed_at
        })

    for xl in xmas_loans:
        ledger_entries.append({
            'date': xl.disbursement_date,
            'type': 'Xmas Loan Disbursed',
            'member': xl.member.user.username,
            'amount': xl.amount_requested,
            'month': xl.disbursement_date
        })

    # -------------------------------
    # 🔹 REPAYMENTS
    # -------------------------------
    repayments = LoanRepayment.objects.all()

    total_repaid = repayments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

    for r in repayments:
        ledger_entries.append({
            'date': r.payment_date,
            'type': 'Loan Repayment',
            'member': r.member.user.username,
            'amount': r.amount_paid,
            'month': r.payment_date
        })

    # -------------------------------
    # 🔹 SORT LEDGER
    # -------------------------------
    ledger_entries = sorted(ledger_entries, key=lambda x: x['date'] or 0, reverse=True)

    # -------------------------------
    # 🔹 SACCO CORE FINANCIALS
    # -------------------------------
    total_equity = total_savings
    total_out_loans = total_loans + total_xmas

    liquidity = (total_savings + total_repaid) - total_out_loans

    # -------------------------------
    # 🔹 ACTIVE LOAN BALANCE
    # -------------------------------
    total_loan_balance = total_out_loans - total_repaid

    context = {
        'total_savings': total_savings,
        'total_loans': total_out_loans,
        'total_repaid': total_repaid,
        'loan_balance': total_loan_balance,
        'liquidity': liquidity,
        'ledger': ledger_entries,
    }

    return render(request, 'sacco_financial_report.html', context)
def treasurer(request):
    # ... other logic ...
    
    # Get the summary from your function
    summary = get_daily_financial_summary()
    
    # Fetch the last 10 transactions for the live feed
    recent_transactions = Transaction.objects.all().order_by('-created_at')[:10]
    
    return render(request, 'daily.html', {
        'summary': summary,
        'transactions': recent_transactions
    })