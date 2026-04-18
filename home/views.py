from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models.functions import TruncMonth
from home.de import treasurer_required
from .forms import *
import csv
import datetime
from .service import SaccoReportService
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
from Users.models import CustomUser
import json
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required

@login_required
def update_savings_goal(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            new_goal = Decimal(data.get('goal', 0))
            
            profile = request.user.profile
            profile.monthly_saving_target = new_goal
            profile.save()
            
            return JsonResponse({'status': 'success', 'new_goal': str(new_goal)})
        except (ValueError, Decimal.InvalidOperation):
            return JsonResponse({'status': 'error', 'message': 'Invalid amount'}, status=400)
    return JsonResponse({'status': 'error'}, status=405)
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
  


@login_required
def approve_share_refund(request, refund_id):
    refund = get_object_or_404(CapitalShareRefund, id=refund_id)
    u_type = getattr(request.user, 'user_type', None)

    if refund.status in ['rejected', 'disbursed']:
        messages.error(request, "This share refund is already finalized.")
        return redirect('capital_share_refund_queue')

    # 1. Staff Approval
    if u_type == '2':
        refund.staff_approved = True
        refund.status = "partially_approved"
        messages.success(request, "Staff approval recorded for share refund.")

    # 2. Treasurer Approval
    elif u_type == '3':
        if not refund.staff_approved:
            messages.error(request, "Staff must approve this share refund first.")
        else:
            refund.treasurer_approved = True
            refund.status = "partially_approved"
            messages.success(request, "Treasurer approval recorded for share refund.")

    # 3. Admin Final Approval
    elif u_type == '1' or request.user.is_superuser:
        if not (refund.staff_approved and refund.treasurer_approved):
            messages.error(request, "Staff and Treasurer must approve first.")
        else:
            refund.admin_approved = True
            refund.status = "approved"
            messages.success(request, "Share refund fully approved. Ready for disbursement.")
    
    else:
        messages.error(request, "Unauthorized action.")

    refund.save()
    return redirect('capital_share_refund_queue')
@login_required
def reject_share_refund(request, refund_id):
    refund = get_object_or_404(CapitalShareRefund, id=refund_id)
    u_type = getattr(request.user, 'user_type', None)

    if u_type not in ['1', '2', '3'] and not request.user.is_superuser:
        messages.error(request, "Unauthorized.")
        return redirect('member_dashboard')

    if refund.status in ['disbursed', 'rejected']:
        messages.warning(request, "This refund is already finalized.")
    else:
        refund.status = 'rejected'
        refund.save()
        messages.success(request, f"Share refund for {refund.member.user.get_full_name()} has been rejected.")

    return redirect('capital_share_refund_queue')
@login_required
@transaction.atomic
def disburse_share_refund(request, refund_id):
    # 1. Permission Check
    if getattr(request.user, 'user_type', None) != '3':
        messages.error(request, "Only the Treasurer can disburse share refunds and close accounts.")
        return redirect('capital_share_refund_queue')

    refund = get_object_or_404(CapitalShareRefund, id=refund_id)

    # 2. Validation Checks
    if not refund.admin_approved:
        messages.error(request, "Admin final sign-off is required before disbursement.")
        return redirect('capital_share_refund_queue')

    member = refund.member
    user = member.user  # To delete later

    try:
        # 3. Calculate Outstanding Loans (If any)
        # Assuming you have a Loan model with a status and a method to get balance
        active_loans = Loan.objects.filter(member=member, status='active')
        total_loan_debt = sum(loan.total_balance() for loan in active_loans) # Adjust to your loan balance logic
        
        processing_fee = 1000
        gross_shares = refund.amount_requested
        
        # 4. Final Calculation
        total_deductions = total_loan_debt + processing_fee
        final_payout = gross_shares - total_deductions

        if final_payout < 0:
            messages.error(request, f"Cannot disburse. Member owes KES {abs(final_payout)} more than their shares.")
            return redirect('capital_share_refund_queue')

        # 5. Update Capital Share Ledger (Record the Exit)
        CapitalShare.objects.create(
            member=member,
            amount=-(gross_shares),
            date_received=timezone.now().date(),
            # remarks=f"Full Exit: Deducted {total_loan_debt} (Loans) & {processing_fee} (Fee)"
        )

        # 6. Update Refund Status (For audit trails before deletion)
        refund.status = 'disbursed'
        refund.net_amount = final_payout
        refund.date_disbursed = timezone.now()
        refund.save()

        # 7. THE SYSTEM PURGE (Delete Member and User)
        # Note: Depending on your foreign keys, this might cascade delete the refund record too.
        # If you want to keep the record for audit, set member to NULL in CapitalShareRefund first.
        
        user_display_name = user.get_full_name()
        user.delete() # This usually deletes the Member profile too if using OneToOneField

        messages.success(request, 
            f"Successfully closed account for {user_display_name}. "
            f"Final Payout: KES {final_payout:,.2f} (Deducted KES {total_loan_debt} in loans & KES 1000 fee)."
        )

    except Exception as e:
        messages.error(request, f"Disbursement and Exit failed: {str(e)}")
        # transaction.atomic will rollback everything above if an error happens here

    return redirect('capital_share_refund_queue')
def apply_xmas_refund(request):
    profile = request.user.profile
    current_year = timezone.now().year
    
    # 1. Get the member's monthly saving rate (assuming it's consistent)
    # We look for the most recent contribution to find the 'rate'
    last_contribution = MonthlyContribution.objects.filter(member=profile).order_by('-month').first()
    
    if not last_contribution:
        messages.error(request, "You have no saving records to qualify for a refund.")
        return redirect('member_dashboard')

    # 2. Logic: 500 x 12 (or whatever their monthly rate is)
    monthly_rate = last_contribution.amount
    total_eligible_amount = monthly_rate * 12

    # 3. Check if they already applied this year
    already_applied = XmasRefund.objects.filter(member=profile, year=current_year).exists()

    if request.method == 'POST':
        if already_applied:
            messages.warning(request, f"You have already applied for your {current_year} Xmas refund.")
        else:
            XmasRefund.objects.create(
                member=profile,
                amount_requested=total_eligible_amount,
                year=current_year
            )
            messages.success(request, f"Refund request for KES {total_eligible_amount} submitted successfully!")
        return redirect('member_dashboard')

    context = {
        'monthly_rate': monthly_rate,
        'total_eligible_amount': total_eligible_amount,
        'already_applied': already_applied,
        'current_year': current_year
    }
    return render(request, 'apply_xmas_refund.html', context)
def cancel_share_refund(request, refund_id):
    refund = get_object_or_404(CapitalShareRefund, id=refund_id, member=request.user.profile)
    
    if refund.is_cancellable:
        refund.delete() # Or set status to 'cancelled' if you want to keep records
        messages.success(request, "Your share refund request has been cancelled.")
    else:
        messages.error(request, "This refund cannot be cancelled at this stage.")
        
    return redirect('member_dashboard')

def apply_share_refund(request):
    profile = request.user.profile
    current_year = timezone.now().year

    # prevent multiple active requests
    existing = CapitalShareRefund.objects.filter(
        member=profile,
        year=current_year,
        status__in=['pending', 'partially_approved', 'approved']
    ).first()

    if existing:
        messages.warning(request, "You already have a pending share refund request.")
        return redirect('member_dashboard')

    # total shares
    total_shares = CapitalShare.objects.filter(member=profile).aggregate(
        Sum('amount')
    )['amount__sum'] or Decimal('0.00')

    if total_shares <= 0:
        messages.error(request, "You have no capital shares to refund.")
        return redirect('member_dashboard')

    processing_fee_rate = Decimal('0.05')  # 5%

    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount'))

        if amount > total_shares:
            messages.error(request, "You cannot refund more than your total shares.")
            return redirect('apply_share_refund')

        # CALCULATIONS
        processing_fee = 1000
        net_amount = amount - processing_fee

        effective_date = timezone.now() + timedelta(days=90)

        refund = CapitalShareRefund.objects.create(
            member=profile,
            amount_requested=amount,
            reason=request.POST.get('reasons'),
            
            net_amount=net_amount,
            effective_date=effective_date
        )

        # =========================
        # NOTIFICATIONS (MEMBER)
        # =========================
        messages.success(
            request,
            f"Your share refund request has been submitted successfully. "
            f"Net amount you will receive: KES {net_amount:,.2f}. "
            f"Processing fee applied: KES {processing_fee:,.2f}. "
            f"This refund will be effective after 3 months."
        )

       

        return redirect('member_dashboard')

    return render(request, 'apply_share_refund.html', {
        'total_shares': total_shares
    })



def capital_share_refund_queue(request):
    user = request.user
    u_type = getattr(user, 'user_type', None)

    # allow only staff, treasurer, admin
    if u_type not in ['1', '2', '3']:
        messages.error(request, "Unauthorized access.")
        return redirect('member_dashboard')

    refunds = CapitalShareRefund.objects.select_related('member').order_by('-date_applied')

    return render(request, 'capital_share_refund_queue.html', {
        'refunds': refunds
    })
@login_required
def disburse_xmas_refund(request, refund_id):
    if request.user.user_type != '3': # Treasurer Check
        messages.error(request, "Only the Treasurer can disburse funds.")
        return redirect('manage_refunds_list')

    refund = get_object_or_404(XmasRefund, id=refund_id)

    if not refund.admin_approved:
        messages.error(request, "Admin approval required before disbursement.")
        return redirect('manage_refunds_list')

    if refund.status == 'disbursed':
        messages.warning(request, "This refund has already been processed.")
        return redirect('manage_refunds_list')

    try:
        with transaction.atomic():
            # 1. Update the Refund Status
            refund.status = 'disbursed'
            refund.date_disbursed = timezone.now()
            refund.save()

            # 2. REDUCE SAVINGS: Create a negative contribution entry
            # This acts as a 'Withdrawal' in your ledger logic
            MonthlyContribution.objects.create(
                member=refund.member,
                amount=-(refund.amount_requested), # Negative amount reduces the SUM
                month=timezone.now().date(),
                # You might want to add a 'description' field to your model 
                # to label this as "Xmas Refund Payout"
            )

            messages.success(request, f"KES {refund.amount_requested} disbursed and savings updated.")
            
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")

    return redirect('manage_refunds_list')
@login_required
def approve_xmas_refund(request, refund_id):
    refund = get_object_or_404(XmasRefund, id=refund_id)
    user = request.user
    u_type = getattr(user, 'user_type', None)

    # ❌ Prevent modifying finalized refunds
    if refund.status in ['rejected', 'disbursed']:
        messages.error(request, "This refund is already finalized.")
        return redirect('manage_refunds_list')

    # ---------------------------------------------------------
    # 1️⃣ STAFF APPROVAL
    # ---------------------------------------------------------
    if u_type == '2':
        if refund.staff_approved:
            messages.info(request, "Already approved by staff.")
            return redirect('manage_refunds_list')

        refund.staff_approved = True
        refund.status = "partially_approved"
        refund.save()

        messages.success(request, "Staff approval recorded.")
        return redirect('manage_refunds_list')

    # ---------------------------------------------------------
    # 2️⃣ TREASURER APPROVAL
    # ---------------------------------------------------------
    elif u_type == '3':
        if not refund.staff_approved:
            messages.error(request, "Staff must approve first.")
            return redirect('manage_refunds_list')

        if refund.treasurer_approved:
            messages.info(request, "Already approved by Treasurer.")
            return redirect('manage_refunds_list')

        refund.treasurer_approved = True
        refund.status = "partially_approved"
        refund.save()

        messages.success(request, "Treasurer approval recorded.")
        return redirect('manage_refunds_list')

    # ---------------------------------------------------------
    # 3️⃣ ADMIN FINAL APPROVAL
    # ---------------------------------------------------------
    elif u_type == '1' or user.is_superuser:
        if not (refund.staff_approved and refund.treasurer_approved):
            messages.error(request, "Staff and Treasurer must approve first.")
            return redirect('manage_refunds_list')

        if refund.admin_approved:
            messages.info(request, "Already approved by Admin.")
            return redirect('manage_refunds_list')

        refund.admin_approved = True
        refund.status = "approved"
        refund.save()

        messages.success(request, "Refund fully approved. Ready for disbursement.")
        return redirect('manage_refunds_list')

    else:
        messages.error(request, "Unauthorized action.")
        return redirect('manage_refunds_list')
def manage_refunds_list(request):
    refunds = XmasRefund.objects.all().order_by('-date_applied')
    # Passing the role string ('1', '2', etc.) to the template
    user_role = request.user.user_type
    
    context = {
        'refunds': refunds,
        'user_role': user_role,
    }
    return render(request, 'admin_refund_list.html', context)
def reject_xmas_refund(request, refund_id):
    refund = get_object_or_404(XmasRefund, id=refund_id)
    user = request.user
    u_type = getattr(user, 'user_type', None)

    # Only staff/treasurer/admin can reject
    if u_type not in ['1', '2', '3'] and not user.is_superuser:
        messages.error(request, "You are not allowed to reject this refund.")
        return redirect('member_dashboard')

    # Prevent rejecting finalized
    if refund.status in ['disbursed', 'rejected']:
        messages.warning(request, "This refund is already finalized.")
        return redirect('staff_dashboard')

    refund.status = 'rejected'
    refund.save()

    messages.success(request, "Refund has been rejected.")
    return redirect('staff_dashboard')
def apply_xmas_loan(request):
    profile = request.user.profile

    # -----------------------------------
    # TOTAL SHARE-BASED LIMIT (10%)
    # -----------------------------------
    total_shares = CapitalShare.objects.filter(member=profile).aggregate(
        Sum('amount')
    )['amount__sum'] or Decimal('0.00')

    total_limit = total_shares * Decimal('0.10')

    # -----------------------------------
    # CURRENT ACTIVE LOANS (TOP-UP LOGIC)
    # -----------------------------------
    active_loans = XmasLoan.objects.filter(
        member=profile
    ).exclude(status__in=['rejected', 'cleared'])

    # 🔥 BEST METHOD (uses remaining balance)
    total_borrowed = sum(loan.remaining_balance for loan in active_loans)

    # -----------------------------------
    # AVAILABLE LIMIT
    # -----------------------------------
    available_limit = total_limit - total_borrowed

    if available_limit <= 0:
        messages.error(
            request,
            "You have reached your loan limit. Clear your existing loan to borrow again."
        )
        return redirect('member_dashboard')

    # -----------------------------------
    # HANDLE FORM SUBMISSION
    # -----------------------------------
    if request.method == 'POST':

        # ✅ SAFE INPUT HANDLING (FIXED BUG)
        amount_input = request.POST.get('amount', '').strip()

        if not amount_input:
            messages.error(request, "Please enter an amount.")
            return redirect(request.path)

        try:
            amount = Decimal(str(amount_input))
        except (InvalidOperation, ValueError):
            messages.error(request, "Enter a valid numeric amount.")
            return redirect(request.path)

        # -----------------------------------
        # VALIDATIONS
        # -----------------------------------
        if amount <= 0:
            messages.error(request, "Amount must be greater than zero.")

        elif amount > available_limit:
            messages.error(
                request,
                f"Limit exceeded! You can only borrow up to KES {available_limit:,.2f}"
            )

        else:
            # -----------------------------------
            # CREATE LOAN
            # -----------------------------------
            with transaction.atomic():
                XmasLoan.objects.create(
                    member=profile,
                    amount_requested=amount,
                    interest_rate=Decimal('9.10'),
                    installments=3,
                    repayment_period=3
                )

            messages.success(
                request,
                f"Loan applied successfully! Remaining limit: KES {(available_limit - amount):,.2f}"
            )
            return redirect('member_dashboard')

    # -----------------------------------
    # RENDER PAGE
    # -----------------------------------
    return render(request, 'xmas.html', {
        'max_limit': available_limit,
        'total_limit': total_limit,
        'borrowed': total_borrowed,
    })
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
# def member_dashboard(request):
#     profile = request.user.profile
    
#     # 1. Basic Data Retrieval
#     loans = Loan.objects.filter(member=profile).order_by('-application_date')
#     savings_list = MonthlyContribution.objects.filter(member=profile).order_by('-created_at')
#     shares_list = CapitalShare.objects.filter(member=profile)
#     xmas_loans = XmasLoan.objects.filter(member=profile).order_by('-application_date')
#     active_refunds = CapitalShareRefund.objects.filter(
#     member=request.user.profile, 
#     status__in=['pending', 'partially_approved', 'approved']
# )
#     # 2. NEW: Fetch notifications for this user (where they are a guarantor)
#     # Shows requests for loans that are still pending and where they haven't responded yet
#     pending_guarantor_requests = Guarantor.objects.filter(
#         guarantor=profile,
#         status='pending',
#         loan__status='pending_guarantors' 
#     ).select_related('loan__member__user')

#     running_total_remaining_balance = Decimal('0.00')
#     running_total_penalties = Decimal('0.00')

#     # 3. Process Loans for the Portfolio Table
#     for loan in loans:
#         # Repayment totals
#         total_paid_lec = LoanRepayment.objects.filter(loan=loan).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
#         total_payable_lec = LoanRepaymentSchedule.objects.filter(loan=loan).aggregate(Sum('amount_due'))['amount_due__sum'] or Decimal('0.00')

#         loan.total_paid = total_paid_lec
#         loan.total_payable_l = total_payable_lec
#         loan.remaining_balance = total_payable_lec - total_paid_lec

#         # Penalty calculation
#         loan.penalty_due = calculate_penalty(loan)
#         running_total_penalties += loan.penalty_due

#         # Only add to "Current Debt" card if the loan is actually active/disbursed
#         if loan.status in ['approved', 'disbursed']:
#             running_total_remaining_balance += loan.remaining_balance

#     # 4. Top Summary Cards Math
#     total_savings = savings_list.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
#     total_shares = shares_list.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
#     total_repaid_all_time = LoanRepayment.objects.filter(loan__member=profile).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

#     context = {
#         'xmas_loans': xmas_loans,
#         'profile': profile,
#         'loans': loans,
#         'savings': savings_list,
#         'shares': shares_list,
#         'total_savings': total_savings,
#         'total_shares': total_shares,
#         'total_loans': running_total_remaining_balance,
#         'total_repaid': total_repaid_all_time,
#         'total_penalties': running_total_penalties,
#         # Pass the new notifications to the template
#         'pending_guarantor_requests': pending_guarantor_requests,
#         'active_refunds': active_refunds,
#     }

#     return render(request, 'r_dashboard.html', context)


def member_dashboard(request):
    profile = request.user.profile
    today = date.today()
    
    # 1. Basic Data Retrieval
    loans = Loan.objects.filter(member=profile).order_by('-application_date')
    xmas_loans = XmasLoan.objects.filter(member=profile).order_by('-application_date')
    savings_list = MonthlyContribution.objects.filter(member=profile).order_by('-month', '-created_at')
    shares_list = CapitalShare.objects.filter(member=profile)
    active_refunds = CapitalShareRefund.objects.filter(
    member=request.user.profile, 
    status__in=['pending', 'partially_approved', 'approved']
)
    
    # 2. Dynamic Approval Counts for Portfolio Badges
    # Counts loans that are either waiting for approval or currently active
    active_normal_count = loans.filter(status__in=['pending', 'approved', 'disbursed']).count()
    active_xmas_count = xmas_loans.filter(status__in=['pending', 'approved', 'disbursed']).count()

    # 3. Unified Loan Portfolio Calculations
    running_total_remaining_balance = Decimal('0.00')

    # Calculate Normal Loans
    for loan in loans:
        total_paid = LoanRepayment.objects.filter(loan=loan).aggregate(
            Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
        total_payable = LoanRepaymentSchedule.objects.filter(loan=loan).aggregate(
            Sum('amount_due'))['amount_due__sum'] or Decimal('0.00')

        loan.remaining_balance = total_payable - total_paid

        if loan.status in ['approved', 'disbursed']:
            running_total_remaining_balance += loan.remaining_balance

    # Calculate Xmas Loans (Adding to the same running total)
    for xmas in xmas_loans:
        # Assuming remaining_balance is a property/method on your XmasLoan model
        if xmas.status in ['approved', 'disbursed']:
            running_total_remaining_balance += xmas.remaining_balance

    # 4. Savings Progress Tracking
    current_month_savings = MonthlyContribution.objects.filter(
        member=profile,
        month__month=today.month,
        month__year=today.year
    ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

    target = getattr(profile, 'monthly_saving_target', Decimal('0.00'))
    progress_pct = (current_month_savings / target * 100) if target > 0 else 0

    # 5. Global Summary Totals
    total_savings = savings_list.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    total_shares = shares_list.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

    context = {
        'profile': profile,
        'loans': loans,
        'xmas_loans': xmas_loans,
        'active_normal_count': active_normal_count, # Use in Normal Badge
        'active_xmas_count': active_xmas_count,     # Use in Xmas Badge
        'savings': savings_list,
        'shares': shares_list,
        
        # Summary Totals
        'total_savings': total_savings,
        'total_shares': total_shares,
        'total_loans': running_total_remaining_balance, # Combined total
        'active_refunds': active_refunds,
        # Savings Goal Data
        'current_month_savings': current_month_savings,
        'progress_pct': min(float(progress_pct), 100),
        'saving_target': target,
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
                            transaction_type='deposit',
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
    pending_xmas_refunds = XmasRefund.objects.filter(
        status__in=['pending', 'partially_refunded']
    )
    approved_loans = Loan.objects.filter(status='approved')
    rejected_loans = Loan.objects.filter(status='rejected')
    pending_shares_refunds = CapitalShareRefund.objects.filter(
        status__in =['pending', 'partially_refunded'],
        treasurer_approved=False
    ).order_by('-date_applied')
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
        'pending_shares_refunds': pending_shares_refunds,
        'pending_xmas_refunds': pending_xmas_refunds,
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

    # --- 1. PRE-CHECK DATA ---
    active_loan = Loan.objects.filter(
        member=profile, 
        status__in=['approved', 'disbursed']
    ).first()
    
    current_balance = active_loan.get_remaining_balance() if active_loan else Decimal('0.00')
    total_savings = CapitalShare.objects.filter(member=profile).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    global_cap = Decimal(total_savings) * Decimal('3.5')

    other_exposure = Loan.objects.filter(
        member=profile,
        status__in=['pending_guarantors', 'pending', 'approved', 'disbursed']
    ).exclude(id=active_loan.id if active_loan else None).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

    available_limit = global_cap - Decimal(other_exposure)

    # --- 2. GUARANTOR RESTRICTION ---
    # Only allow '4' (Member) to be selected as a guarantor.
    # Exclude Admin, Staff, Treasurer, and HR.
    GuarantorFormSet = modelformset_factory(
        Guarantor,
        form=GuarantorForm,
        extra=1,
        max_num=10,
        validate_min=True,
        min_num=2
    )

    if request.method == 'POST':
        form = LoanApplicationForm(request.POST)
        formset = GuarantorFormSet(request.POST, queryset=Guarantor.objects.none())

        if form.is_valid() and formset.is_valid():
            loan = form.save(commit=False)
            loan.member = profile

            # --- 3. DURATION VALIDATION ---
            # Normal Loan = max 48 months | Everything else = max 12 months
            duration = int(loan.duration_months)
            # Assuming your form/model has a 'loan_type' field. Adjust 'normal' to your actual choice value.
            if loan.loan_type == 'normal':
                if duration > 48:
                    messages.error(request, "Normal Loans cannot exceed 48 months.")
                    return redirect('apply_loan')
            else:
                if duration > 12:
                    messages.error(request, f"{loan.loan_type.title()} Loans cannot exceed 12 months.")
                    return redirect('apply_loan')

            # --- 4. TIERED INTEREST & AFFORDABILITY MATH ---
            P = Decimal(str(loan.amount))
            M = duration

            if M <= 12: rate = Decimal('0.091')
            elif M <= 24: rate = Decimal('0.175')
            elif M <= 36: rate = Decimal('0.259')
            else: rate = Decimal('0.349')

            interest_amt = rate * P
            insurance_amt = ((Decimal('5.03') * Decimal(M) + Decimal('3.03')) * P) / Decimal('6000')
            total_payable = P + interest_amt + insurance_amt
            monthly_installment = total_payable / Decimal(M)

            gross = Decimal(profile.gross_salary)
            net = Decimal(profile.net_salary)
            take_home_limit = gross / Decimal('3')

            # --- 5. 🚨 1/3 RULE & HR NOTIFICATION ---
            if (net - monthly_installment) < take_home_limit:
                HRNotification.objects.create(
                    member=profile,
                    message=f"FAILED 1/3 RULE: {profile.user.get_full_name()} requested KES {P:,.2f} for {M} months."
                )
                profile.salary_needs_review = True
                profile.save()
                messages.error(request, "Loan rejected: Violates 1/3 salary rule. HR notified. try again after 48 hrs")
                return redirect('member_dashboard')

            # --- 6. TOP-UP & LIMITS ---
            if active_loan:
                if P <= current_balance:
                    messages.error(request, f"New loan must exceed current balance of KES {current_balance:,.2f}")
                    return redirect('apply_loan')
                loan.is_topup = True
                loan.replaces_loan = active_loan

            if P > available_limit:
                messages.error(request, f"Exceeds borrowing limit. Max: KES {available_limit:,.2f}")
                return redirect('member_dashboard')

            # --- 7. SAVE ---
            try:
                with transaction.atomic():
                    loan.status = 'pending_guarantors'
                    loan.save()
                    guarantors = formset.save(commit=False)
                    for g in guarantors:
                        # Double check guarantor type in backend for security
                        if g.member.user.user_type != '4':
                            raise ValueError(f"User {g.member.user.get_full_name()} is not a regular Member and cannot guarantee loans.")
                        g.loan = loan
                        g.save()

                messages.success(request, "Application submitted to guarantors.")
                return redirect('member_dashboard')
            except Exception as e:
                messages.error(request, f"Error: {str(e)}")
                return redirect('member_dashboard')

    else:
        form = LoanApplicationForm()
        # Filter the queryset in the formset to only show '4' (Members)
        formset = GuarantorFormSet(queryset=Guarantor.objects.none())

    # Update your context to pass the filtered members list for the frontend search
    eligible_guarantors = Profile.objects.filter(user__user_type='4').exclude(user=request.user)

    context = {
        'loan_limit': available_limit,
        'form': form,
        'formset': formset,
        'eligible_guarantors': eligible_guarantors
    }
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
    pending_shares_refunds = CapitalShareRefund.objects.filter(
        status__in =['pending'],
        treasurer_approved=False
    ).order_by('-date_applied')
    # Your dashboard logic here
    pending_loans = Loan.objects.filter(
        staff_approved=False,
        status__in=['pending', 'partially_approved']
    ).order_by('-application_date')
    pending_xmas_loans = XmasLoan.objects.filter(status='pending').order_by('-application_date')

    total_savings_pool = MonthlyContribution.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    total_members = Profile.objects.count()
    total_interest_earned = LoanRepaymentSchedule.objects.filter(is_paid=True).aggregate(Sum('amount_due'))['amount_due__sum'] or 0
    pending_xmas_refunds = XmasRefund.objects.filter(
        status__in=['pending', 'partially_refunded']
    )
    context = {
        'pending_xmas_refunds': pending_xmas_refunds,
        'pending_loans': pending_loans,
        'total_savings_pool': total_savings_pool,
        'total_members': total_members,
        'total_interest_earned': total_interest_earned,
        'pending_xmas_loans': pending_xmas_loans,
        'pending_shares_refunds': pending_shares_refunds,
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
    pending_shares_refunds = CapitalShareRefund.objects.filter(
        status__in =['pending', 'partially_approved'],
        treasurer_approved=False)
    pending_xmas_refunds = XmasRefund.objects.filter(
        status__in=['pending', 'partially_approved']
    )
    # Ca
    # lculate Liquidity
    total_repayments = LoanRepayment.objects.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0')
    
    # Formula: (Money In) - (Money Out)
    available_cash = (total_savings + total_shares + total_repayments) - active_loans_value

    # 4. Recent Activity
    recent_transactions = Transaction.objects.all().order_by('-created_at')[:10]

    context = {
        'pending_shares_refunds': pending_shares_refunds,
        'pending_xmas_loans': pending_xmas_loans,
        'awaiting_treasurer': awaiting_treasurer,
        'total_savings': total_savings,
        'total_shares': total_shares,
        'active_loans_value': active_loans_value,
        'available_cash': available_cash,
        'total_interest': total_interest_earned,
        'recent_transactions': recent_transactions,
        'pending_xmas_refunds': pending_xmas_refunds,
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
    
    # We fetch loans - the calculated interest/insurance are now stored in the DB
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

def sacco_reportings(request):
    if getattr(request.user, 'user_type', None) != '3' and not request.user.is_superuser:
        return redirect('access_denied')

    members = Profile.objects.select_related('user')

    shares = CapitalShare.objects.select_related('member', 'member__user').order_by('-date_created')
    total_shares = shares.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

    loans = Loan.objects.select_related('member', 'member__user').order_by('-application_date')
    total_loans = loans.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

    repayments = LoanRepayment.objects.select_related('member', 'member__user').order_by('-payment_date')
    total_repaid = repayments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

    # Outstanding = Total Payable - Total Repaid
    total_payable = sum([loan.total_payable for loan in loans])
    outstanding_balance = Decimal(total_payable) - Decimal(total_repaid)

    context = {
        'members': members,
        'member_count': members.count(),
        'shares': shares,
        'total_shares': total_shares,
        'loans': loans,
        'total_loans': total_loans,
        'repayments': repayments,
        'total_repaid': total_repaid,
        'outstanding_balance': outstanding_balance,
    }

    return render(request, 'sacco_reporting.html', context)
@role_required(allowed_roles=['3', '5'])  # HR Only
def Members(request):
    # Fetch all members and prefetch related loans for efficiency
    members = Profile.objects.prefetch_related('member_loans')  # ✅ works
    return render(request, 'mem.html', {'members': members})


@login_required
def Human_Resource(request):
    if getattr(request.user, 'user_type', None) != '5' and not request.user.is_superuser:
            return redirect('access_denied')
    query = request.GET.get('q')

    # -------------------------
    # BASE QUERY
    # -------------------------
    users = Profile.objects.select_related('user')

    # 🔥 FILTER USERS NEEDING REVIEW FIRST
    flagged_users = users.filter(salary_needs_review=True)

    # -------------------------
    # SEARCH
    # -------------------------
    if query:
        users = users.filter(
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(pf_number__icontains=query)
        )

    # -------------------------
    # HR NOTIFICATIONS (ONLY RELEVANT)
    # -------------------------
    notifications = HRNotification.objects.filter(
        is_read=False
    ).select_related('member').order_by('-created_at')
      # Mark as read immediately for simplicity

    # -------------------------
    # STATS
    # -------------------------
    stats = users.aggregate(
        total_gross=Sum('gross_salary'),
        total_net=Sum('net_salary'),
        avg_gross=Avg('gross_salary')
    )

    # -------------------------
    # CONTEXT
    # -------------------------
    context = {
        'users': users,
        'flagged_users': flagged_users,  # 🔥 NEW
        'total_gross': stats['total_gross'] or 0,
        'total_net': stats['total_net'] or 0,
        'avg_gross': stats['avg_gross'] or 0,
        'member_count': users.count(),
        'notifications': notifications,
        'notification_count': notifications.count(),
        'flagged_count': flagged_users.count(),  # 🔥 NEW
    }

    return render(request, 'hr.html', context)
# views.py




from django.shortcuts import render
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from .models import Loan, LoanRepayment
import datetime as dt_module  # Avoids naming conflicts with 'datetime' class

def performance_analysis_view(request):
    monthly_stats = {}

    # 1. Fetch Disbursed Loans
    loans = (
        Loan.objects.filter(is_disbursed=True)
        .annotate(month=TruncMonth('disbursed_at'))
        .values('month')
        .annotate(total=Sum('amount'))
    )

    # 2. Fetch Repayments
    repayments = (
        LoanRepayment.objects.annotate(month=TruncMonth('payment_date'))
        .values('month')
        .annotate(total=Sum('amount_paid'))
    )

    # 3. Merge logic for Chart.js
    for l in loans:
        if l['month']:
            m_str = l['month'].strftime("%b %Y")
            monthly_stats[m_str] = {'disbursed': float(l['total']), 'repaid': 0}

    for r in repayments:
        if r['month']:
            m_str = r['month'].strftime("%b %Y")
            total_r = float(r['total'])
            if m_str in monthly_stats:
                monthly_stats[m_str]['repaid'] = total_r
            else:
                monthly_stats[m_str] = {'disbursed': 0, 'repaid': total_r}

    # 4. Chronological Sorting (Using dt_module to prevent AttributeError)
    sorted_months = sorted(
        monthly_stats.keys(), 
        key=lambda x: dt_module.datetime.strptime(x, "%b %Y")
    )
    
    # 5. Financial Calculations
    total_disbursed = float(sum(l['total'] for l in loans) or 0)
    total_repaid = float(sum(r['total'] for r in repayments) or 0)
    
    # Calculate Recovery Rate (Capped at 100% for the UI)
    if total_disbursed > 0:
        actual_rate = (total_repaid / total_disbursed) * 100
        display_recovery = min(round(actual_rate, 1), 100.0)
        surplus = max(0, total_repaid - total_disbursed)
    else:
        display_recovery = 0
        surplus = 0

    context = {
        'labels': sorted_months,
        'loan_totals': [monthly_stats[m]['disbursed'] for m in sorted_months],
        'repayment_totals': [monthly_stats[m]['repaid'] for m in sorted_months],
        'total_disbursed': total_disbursed,
        'total_repaid': total_repaid,
        'recovery_rate': display_recovery,
        'surplus': surplus,
        'actual_yield': round((total_repaid / total_disbursed * 100), 1) if total_disbursed > 0 else 0
    }
    
    return render(request, 'analysis.html', context)
from django.db.models import Sum
from decimal import Decimal

def monthly_sacco_report(request):
    month = int(request.GET.get('month', timezone.now().month))
    year = int(request.GET.get('year', timezone.now().year))
    
    report_data = []
    profiles = Profile.objects.all().select_related('user')

    for profile in profiles:
        # -------------------------------
        # 1. SAVINGS (XMAS GOAL) 
        # -------------------------------
        # FIX: Check the MonthlyContribution table specifically for the selected month
        savings_paid = MonthlyContribution.objects.filter(
            member=profile,
            month__month=month,
            month__year=year
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

        # Use the goal set in profile
        savings_target = profile.monthly_saving_target or Decimal('0.00')
        
        # Status logic: Paid if they met the goal (or paid anything if goal is 0)
        savings_status = savings_paid >= savings_target if savings_target > 0 else savings_paid > 0

        # -------------------------------
        # 2. CAPITAL SHARES
        # -------------------------------
        # FIX: Use __in for multiple types and correct filter syntax
        shares_paid = Transaction.objects.filter(
            member=profile,
            transaction_type='shares',
            created_at__month=month,
            created_at__year=year
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
        share_target = Decimal('1000.00')
        shares_status = shares_paid >= share_target

        # -------------------------------
        # 3. LOAN LOGIC (Normal, Xmas, School, Emergency)
        # -------------------------------
        def get_loan_data(purpose_name, is_xmas_model=False):
            if is_xmas_model:
                loan = XmasLoan.objects.filter(member=profile, status__in=['approved', 'disbursed']).first()
            else:
                loan = Loan.objects.filter(member=profile, purpose=purpose_name, status__in=['approved', 'disbursed']).first()
            
            if loan:
                expected = loan.monthly_installment
                repayment_filter = {'payment_date__month': month, 'payment_date__year': year}
                
                if is_xmas_model:
                    repayment_filter['member'] = profile
                    repayment_filter['is_xmas'] = True
                else:
                    repayment_filter['loan'] = loan
                
                paid = LoanRepayment.objects.filter(**repayment_filter).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
                return expected, paid, (paid >= expected)
            return Decimal('0.00'), Decimal('0.00'), False

        norm_exp, norm_paid, norm_status = get_loan_data('normal Loan')
        xmas_exp, xmas_paid, xmas_status = get_loan_data(None, is_xmas_model=True)
        sch_exp, sch_paid, sch_status = get_loan_data('choll fees')
        emg_exp, emg_paid, emg_status = get_loan_data('emergency')

        # -------------------------------
        # 4. BUILD ROW
        # -------------------------------
        row = {
            'name': profile.user.get_full_name() or profile.user.username,
            'pf': profile.pf_number,
            'savings_paid': savings_paid, # Pass actual paid amount to template
            'savings_target': savings_target,
            'savings_status': savings_status,
            'shares_paid': shares_paid,
            'shares_target': share_target,
            'shares_status': shares_status,
            'normal_loan': norm_exp,
            'normal_paid': norm_paid,
            'normal_status': norm_status,
            'xmas_loan': xmas_exp,
            'xmas_paid': xmas_paid,
            'xmas_status': xmas_status,
            'school_fees': sch_exp,
            'school_paid': sch_paid,
            'school_status': sch_status,
            'emergency': emg_exp,
            'emergency_paid': emg_paid,
            'emergency_status': emg_status,
            'total_actual_paid': (savings_paid + shares_paid + norm_paid + xmas_paid + sch_paid + emg_paid)
        }
        report_data.append(row)

    # 5. CSV EXPORT LOGIC
    if 'export' in request.GET:
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="SACCO_Report_{month}_{year}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Member Name', 'PF Number', 'Savings', 'Shares', 'Normal', 'Xmas', 'School', 'Emergency'])

        for r in report_data:
            writer.writerow([
                r['name'], r['pf'],
                0 if r['savings_status'] else r['savings_target'],
                0 if r['shares_status'] else r['shares_target'],
                0 if r['normal_status'] else r['normal_loan'],
                0 if r['xmas_status'] else r['xmas_loan'],
                0 if r['school_status'] else r['school_fees'],
                0 if r['emergency_status'] else r['emergency'],
            ])
        return response

    context = {
        'report_data': report_data,
        'month': month,
        'year': year,
        'years': range(2023, 2030),
        'months_choices': [(i, date(2000, i, 1).strftime('%b')) for i in range(1, 13)],
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
    user_profile = request.user.profile
    
    # --- MEMBER SPECIFIC DATA ---
    monthly_savings = MonthlyContribution.objects.filter(member=user_profile)
    capital_shares = CapitalShare.objects.filter(member=user_profile)
    
    total_savings = (monthly_savings.aggregate(Sum('amount'))['amount__sum'] or 0) + \
                    (capital_shares.aggregate(Sum('amount'))['amount__sum'] or 0)

    # Combined Ledger (Historical list of everything the member did)
    ledger_entries = []
    for s in monthly_savings:
        ledger_entries.append({'date': s.created_at, 'type': 'Monthly Saving', 'amount': s.amount, 'month': s.month})
    for c in capital_shares:
        ledger_entries.append({'date': c.date_created, 'type': 'Capital Share', 'amount': c.amount, 'month': c.month})
    
    ledger_entries = sorted(ledger_entries, key=lambda x: x['date'], reverse=True)

    repayments = LoanRepayment.objects.filter(member=user_profile).order_by('-payment_date')
    total_repaid = repayments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
    
    # Active Debt Calculation
    active_loans = Loan.objects.filter(member=user_profile, status='disbursed').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    active_xmas = XmasLoan.objects.filter(member=user_profile, is_disbursed=True).aggregate(Sum('amount_requested'))['amount_requested__sum'] or Decimal('0.00')
    current_loan_balance = (active_loans + active_xmas) - total_repaid

    # --- TREASURER CASH FLOW LOGIC (Global Overview) ---
    cashflow_stats = {}
    if request.user.user_type in ['1', '2', '3']:
        # INFLOWS
        in_savings = MonthlyContribution.objects.aggregate(Sum('amount'))['amount__sum'] or 0
        in_shares = CapitalShare.objects.aggregate(Sum('amount'))['amount__sum'] or 0
        in_repayments = LoanRepayment.objects.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
        in_reg_fees = RegistrationFee.objects.filter(paid=True).aggregate(Sum('amount'))['amount__sum'] or 0
        
        total_inflow = in_savings + in_shares + in_repayments + in_reg_fees

        # OUTFLOWS
        out_loans = Loan.objects.filter(status='disbursed').aggregate(Sum('amount'))['amount__sum'] or 0
        out_xmas = XmasLoan.objects.filter(status='disbursed').aggregate(Sum('amount_requested'))['amount_requested__sum'] or 0
        out_expenses = Expense.objects.aggregate(Sum('amount_spent'))['amount_spent__sum'] or 0
        out_refunds = CapitalShareRefund.objects.filter(status='disbursed').aggregate(Sum('amount_requested'))['amount_requested__sum'] or 0
        
        total_outflow = out_loans + out_xmas + out_expenses + out_refunds

        cashflow_stats = {
            'total_in': total_inflow,
            'total_out': total_outflow,
            'net_cash': total_inflow - total_outflow,
            'expense_ratio': (out_expenses / total_inflow * 100) if total_inflow > 0 else 0,
            'breakdown': {
                'expenses': out_expenses,
                'refunds': out_refunds,
                'repayments': in_repayments
            }
        }

    context = {
        'total_savings': total_savings,
        'ledger': ledger_entries,
        'current_balance': current_loan_balance,
        'total_repaid': total_repaid,
        'history': repayments,
        'cashflow_stats': cashflow_stats,
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
from datetime import datetime, date

# ... (inside your sacco_financial_ledger_view) ...

# ---------------------------------------------------------
# 3. SORTING & TOTALS
# ---------------------------------------------------------

# Helper function to ensure we are comparing apples to apples (date vs date)
def normalize_date(d):
    if isinstance(d, datetime):
        return d.date()
    return d

# Update the sorting line to use the helper


def sacco_financial_ledger_view(request):
    # ---------------------------------------------------------
    # 1. FETCH ALL FINANCIAL DATA (ENTIRE SACCO)
    # ---------------------------------------------------------
    # Savings & Shares
    monthly_savings = MonthlyContribution.objects.all().select_related('member__user')
    capital_shares = CapitalShare.objects.all().select_related('member__user')
    
    # Loans (Disbursed only)
    loans = Loan.objects.filter(status='disbursed').select_related('member__user')
    xmas_loans = XmasLoan.objects.filter(is_disbursed=True).select_related('member__user')
    
    # Repayments (From your updated Schedule model)
    paid_schedules = LoanRepaymentSchedule.objects.filter(is_paid=True).select_related(
        'loan__member__user', 'xmas_loan__member__user'
    )

    ledger_entries = []

    # ---------------------------------------------------------
    # 2. MAP DATA TO LEDGER COLUMNS
    # ---------------------------------------------------------
    # Process Savings/Shares (Column: RCVD)
    for s in monthly_savings:
        ledger_entries.append({
            'date': s.created_at,
            'member': s.member.user.get_full_name(),
            'acc': s.member.membership_number,
            'type': 'Monthly Contribution',
            'share_rcvd': s.amount,
            'loan_amt': 0, 'loan_repaid': 0, 'int_paid': 0
        })

    for c in capital_shares:
        ledger_entries.append({
            'date': c.date_created,
            'member': c.member.user.get_full_name(),
            'acc': c.member.membership_number,
            'type': 'Capital Share',
            'share_rcvd': c.amount,
            'loan_amt': 0, 'loan_repaid': 0, 'int_paid': 0
        })

    # Process Disbursements (Column: LOANED)
    for l in loans:
        ledger_entries.append({
            'date': l.disbursed_at,
            'member': l.member.user.get_full_name(),
            'acc': l.member.membership_number,
            'type': 'Loan Disbursed',
            'share_rcvd': 0,
            'loan_amt': l.amount,
            'loan_repaid': 0, 'int_paid': 0
        })

    for xl in xmas_loans:
        ledger_entries.append({
            'date': xl.disbursement_date,
            'member': xl.member.user.get_full_name(),
            'acc': xl.member.membership_number,
            'type': 'Xmas Loan Disbursed',
            'share_rcvd': 0,
            'loan_amt': xl.amount_requested,
            'loan_repaid': 0, 'int_paid': 0
        })

    # Process Repayments (Columns: REPAID & INTEREST PAID)
    for sched in paid_schedules:
        # Determine the correct member based on loan type
        member_obj = sched.xmas_loan.member if sched.is_xmas else sched.loan.member
        
        ledger_entries.append({
            'date': sched.date_paid or sched.due_date,
            'member': member_obj.user.get_full_name(),
            'acc': member_obj.membership_number,
            'type': f"Repayment (Inst. {sched.installment_number})",
            'share_rcvd': 0,
            'loan_amt': 0,
            'loan_repaid': sched.principal_amount, # Principal part
            'int_paid': sched.interest_amount,     # Interest part
        })

    # ---------------------------------------------------------
    # 3. SORTING & TOTALS
    # ---------------------------------------------------------
    # Sort entire SACCO history by newest first
    ledger_entries = sorted(
    ledger_entries, 
    key=lambda x: normalize_date(x['date']) if x['date'] else date.min, 
    reverse=True
)

    # Calculate Summary Totals
    total_savings = (monthly_savings.aggregate(Sum('amount'))['amount__sum'] or 0) + \
                    (capital_shares.aggregate(Sum('amount'))['amount__sum'] or 0)
    
    total_out = (loans.aggregate(Sum('amount'))['amount__sum'] or 0) + \
                (xmas_loans.aggregate(Sum('amount_requested'))['amount_requested__sum'] or 0)
                
    total_repaid = paid_schedules.aggregate(Sum('principal_amount'))['principal_amount__sum'] or 0
    total_interest = paid_schedules.aggregate(Sum('interest_amount'))['interest_amount__sum'] or 0

    context = {
        'ledger': ledger_entries,
        'total_savings': total_savings,
        'total_out': total_out,
        'total_repaid': total_repaid,
        'total_interest': total_interest,
        'liquidity': (total_savings + total_repaid + total_interest) - total_out
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
@login_required
@role_required(allowed_roles=['3']) # Treasurer
def treasurer_edit_loan_amount(request, loan_id):
    loan = get_object_or_404(Loan, id=loan_id)
    
    # Only allow editing if the loan isn't disbursed yet
    if loan.status == 'disbursed':
        messages.error(request, "Cannot edit an already disbursed loan.")
        return redirect('treasurer_dashboard')

    if request.method == "POST":
        new_amount = Decimal(request.POST.get('amount'))
        
        # Logic: If the Treasurer changes the amount, update it.
        # You might want to log who changed it.
        loan.amount = new_amount
        loan.save()
        
        messages.success(request, f"Loan amount adjusted to KES {new_amount}")
        return redirect('treasurer_dashboard')

    return render(request, 'treasurer_edit_loan.html', {'loan': loan})


from .balance import BalanceSheetService
from django.http import JsonResponse
from .models import Transaction, MonthlyContribution, Loan, LoanRepayment

def get_note_details(request, note_id):
    year = request.GET.get('year', timezone.now().year)
    data = []

    if note_id == "7": # Cash and Bank
        records = Transaction.objects.filter(created_at__year=year).order_by('-created_at')
        for r in records:
            data.append({
                'date': r.created_at.strftime('%Y-%m-%d'),
                'desc': f"{r.get_transaction_type_display()} - {r.member}",
                'amount': float(r.amount),
                'type': 'in' if r.transaction_type in ['deposit', 'repayment'] else 'out'
            })

    elif note_id == "12": # Members' Deposits
        records = MonthlyContribution.objects.filter(month__year=year).order_by('-month')
        for r in records:
            data.append({
                'date': r.month.strftime('%b %Y'),
                'desc': f"Contribution: {r.member}",
                'amount': float(r.amount),
                'type': 'in'
            })

    # Add more elif blocks for Note 9, 13, 16, etc.

    return JsonResponse({'results': data})
def balance_sheet_view(request):
    # Get the year from the query parameters, default to current year
    current_year = timezone.now().year
    year = request.GET.get('year', current_year)
    
    try:
        year = int(year)
    except ValueError:
        year = current_year

    # Generate the formal balance sheet data using the service
    report_data = BalanceSheetService.generate_balance_sheet(year)
    
    # Range for the year selector dropdown
    year_range = range(current_year - 5, current_year + 1)

    return render(request, 'balance_sheet.html', {
        'report': report_data,
        'year_range': year_range,
        'selected_year': year
    })

@login_required
def my_statement(request):
    # Get the member profile for the logged-in user
    # try:
    #     member = request.user.Profile  # Assuming a OneToOneField from Member to User
    # except AttributeError:
    #     # If user is admin/staff without a member profile
    #     return redirect('member_dashboard')
    start_month = int(request.GET.get('start_month', 1))
    end_month = int(request.GET.get('end_month', timezone.now().month))
    user =request.user
    member = get_object_or_404(Profile, user=user)
    year = 2026
    monthly_stats = []
    
    # 1. Calculate Balances Brought Forward (before 2026)
    # This matches the "Bal. b/d" row on your card
    initial_shares = CapitalShare.objects.filter(
        member=member, 
        date_created__year__lt=year
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    # 2. Get monthly activity for the current year
    running_share_bal = initial_shares
    
    # We loop through months 1 to 12
    for m in range(1, 13):
        shares = CapitalShare.objects.filter(
            member=member, 
           date_created__year=year, 
           date_created__month=m
        )
        
        received = shares.filter(amount__gt=0).aggregate(Sum('amount'))['amount__sum'] or 0
        withdrawn = abs(shares.filter(amount__lt=0).aggregate(Sum('amount'))['amount__sum'] or 0)
        
        running_share_bal += (received - withdrawn)
        
        # Only add to list if there was activity or it's a past month
        if m <= timezone.now().month:
            monthly_stats.append({
                'date': datetime.datetime(year, m, 1),
                'share_received': received if received > 0 else "",
                'share_withdrawn': withdrawn if withdrawn > 0 else "",
                'running_share_bal': running_share_bal,
                # Add loan logic here similarly
            })

    context = {
        'member': member,
        'monthly_stats': monthly_stats,
        'initial_shares': initial_shares,
        'current_shares': running_share_bal,
        'today': timezone.now(),
        'start_month': start_month,
        'end_month': end_month,
    }
    return render(request, 'statement_template.html', context)

def add_expense_view(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            # Commit=False allows us to attach the user profile before saving
            expense = form.save(commit=False)
            expense.recorded_by = request.user.profile 
            expense.save()
            
            messages.success(request, f"Expense for {expense.get_expense_type_display()} recorded successfully!")
            return redirect('treasurer_dashboard') # Redirect to your ledger
    else:
        form = ExpenseForm()
    
    return render(request, 'add_expense.html', {'form': form})

from django import template

register = template.Library()

@register.filter
def replace(value, arg):
    """
    Usage: {{ value|replace:"_, " }} 
    Replaces the first part of the argument with the second part.
    """
    if len(arg.split(',')) != 2:
        return value
    
    old, new = arg.split(',')
    return value.replace(old, new)
def sacco_report(request, year=None, month=None):
    # Default to current month if not provided
    today = timezone.now()
    report_year = year or today.year
    report_month = month or today.month
    
    # --- FILTERS ---
    # Monthly Contribution uses 'month' field (DateField)
    # Expense uses 'date_spent' (DateField)
    # Loans use 'application_date' (DateTimeField)
    
    # 1. TOTAL SAVINGS THIS MONTH
    monthly_savings = MonthlyContribution.objects.filter(
        month__year=report_year, month__month=report_month
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    
    monthly_shares = CapitalShare.objects.filter(
        month__year=report_year, month__month=report_month
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    # 2. LOANS DISBURSED THIS MONTH
    normal_loans = Loan.objects.filter(
        status='disbursed', 
        disbursed_at__year=report_year, 
        disbursed_at__month=report_month
    )
    total_normal_disbursed = normal_loans.aggregate(Sum('amount'))['amount__sum'] or 0
    total_normal_interest = normal_loans.aggregate(Sum('interest'))['interest__sum'] or 0
    
    xmas_loans = XmasLoan.objects.filter(
        is_disbursed=True,
        disbursement_date__year=report_year,
        disbursement_date__month=report_month
    )
    total_xmas_disbursed = xmas_loans.aggregate(Sum('amount_requested'))['amount_requested__sum'] or 0
    total_xmas_interest = total_xmas_disbursed * Decimal('0.091')

    # 3. LOAN REPAYMENTS RECEIVED THIS MONTH
    repayments = LoanRepayment.objects.filter(
        payment_date__year=report_year,
        payment_date__month=report_month
    ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0

    # 4. EXPENDITURE THIS MONTH
    expenses_list = Expense.objects.filter(
        date_spent__year=report_year,
        date_spent__month=report_month
    )
    total_expenses = expenses_list.aggregate(Sum('amount_spent'))['amount_spent__sum'] or 0
    
    # Per Expenditure Breakdown
    expense_breakdown = expenses_list.values('expense_type').annotate(total=Sum('amount_spent'))

    # 5. FINAL CALCULATION
    total_inflow = monthly_savings + monthly_shares + repayments
    net_cash_flow = total_inflow - (total_normal_disbursed + total_xmas_disbursed + total_expenses)

    context = {
        'report_date': datetime(int(report_year), int(report_month), 1),
        'savings': monthly_savings + monthly_shares,
        'repayments': repayments,
        'loans_out': total_normal_disbursed + total_xmas_disbursed,
        'interest_earned': total_normal_interest + total_xmas_interest,
        'expenses': total_expenses,
        'expense_breakdown': expense_breakdown,
        'net_flow': net_cash_flow,
        'inflow': total_inflow,
    }
    
    return render(request, 'sacco.html', context)


import datetime
def Bank_Statement(request):
    # Get year from user input, default to current year
    current_year = datetime.datetime.now().year
    year = request.GET.get('year', current_year)
    
    try:
        year = int(year)
    except ValueError:
        year = current_year

    report_data = SaccoReportService.generate_annual_report(year)
    
    # Generate list of years for the selection dropdown (e.g., last 5 years)
    year_range = range(current_year - 5, current_year + 1)
    
    return render(request, 'financial_audit.html', {
        'report': report_data,
        'year_range': year_range,
        'selected_year': year
    })


def bank_financial_report(request):
    # --- 1. NORMAL LOANS ---
    # Summing fields already stored in the Loan model (Principal, Interest, Insurance)
    normal_stats = Loan.objects.filter(is_disbursed=True).aggregate(
        principal=Sum('amount'),
        interest=Sum('interest'),
        insurance=Sum('insurance')
    )
    
    normal_interest = normal_stats['interest'] or Decimal('0.00')
    normal_principal = normal_stats['principal'] or Decimal('0.00')
    normal_insurance = normal_stats['insurance'] or Decimal('0.00')

    # --- 2. XMAS LOANS ---
    # Calculating interest based on your 9.1% fixed rate logic
    xmas_principal = XmasLoan.objects.filter(is_disbursed=True).aggregate(
        total=Sum('amount_requested'))['total'] or Decimal('0.00')
    
    xmas_interest = xmas_principal * Decimal('0.091')

    # --- 3. CONSOLIDATED TOTALS ---
    total_principal = normal_principal + xmas_principal
    
    # We keep them separate for the context, but sum them for the grand total
    total_interest_combined = normal_interest + xmas_interest
    
    grand_total = total_principal + total_interest_combined + normal_insurance

    context = {
        # Individual Interests (Separated)
        'normal_interest': normal_interest,
        'xmas_interest': xmas_interest,
        
        # Totals
        'principal': total_principal,
        'insurance': normal_insurance,
        'grand_total': grand_total,
        'report_date': datetime.datetime.now(),
    }
    return render(request, 'bank.html', context)

def member_loan_details_view(request, profile_id):
    # 1. Get the member
    member = get_object_or_404(Profile, id=profile_id)
    
    # 2. Fetch all Normal Loans
    normal_loans = member.member_loans.all().order_by('-application_date')
    
    # 3. Fetch all Xmas Loans
    xmas_loans = member.xmas_loans.all().order_by('-application_date')
    
    context = {
        'member': member,
        'normal_loans': normal_loans,
        'xmas_loans': xmas_loans,
    }
    return render(request, 'member_loans.html', context)