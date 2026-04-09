from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models.functions import TruncMonth
from home.de import treasurer_required
from .forms import *
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
from decimal import Decimal
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

 #
# -------------------------
# Member Dashboard
# -------------------------
#@login_required


@csrf_exempt
def mpesa_callback(request):
    data = json.loads(request.body)
    try:
        callback = data['Body']['stkCallback']
        if callback['ResultCode'] == 0:
            metadata = callback['CallbackMetadata']['Item']
            amount = next(i['Value'] for i in metadata if i['Name'] == 'Amount')
            receipt = next(i['Value'] for i in metadata if i['Name'] == 'MpesaReceiptNumber')
            account_ref = next(i['Value'] for i in metadata if i['Name'] == 'AccountReference')

            # --- LOGIC SEPARATION ---
            
            if "SHARES" in account_ref:
                # 1. Handle Share Purchase
                user_id = account_ref.split('-')[-1]
                profile = Profile.objects.get(user_id=user_id)
                
                CapitalShare.objects.create(
                    member=profile,
                    amount=amount,
                    reference=receipt,
                    date_paid=timezone.now()
                )
                print(f"Shares saved for {profile.user.username}")

            else:
                # 2. Handle Loan Repayment (Your existing logic)
                loan_id = account_ref.split('-')[-1]
                loan = Loan.objects.get(id=loan_id)
                
                LoanRepayment.objects.create(
                    loan=loan,
                    member=loan.member,
                    amount_paid=amount,
                    reference=receipt
                )
                # Note: You might want to trigger your schedule update logic here too
                print(f"Loan repayment saved for {loan.member.user.username}")

        return JsonResponse({"ResultCode": 0})
    except Exception as e:
        print("Callback Error:", e)
        return JsonResponse({"ResultCode": 1})
@login_required
@role_required(allowed_roles=['1', '2', '3', '4'])  # Allow all roles to access dashboard
def member_dashboard(request):
    profile = request.user.profile
    
    # 1. Basic Data Retrieval
    loans = Loan.objects.filter(member=profile).order_by('-application_date')
    savings_list = MonthlyContribution.objects.filter(member=profile).order_by('-created_at')
    shares_list = CapitalShare.objects.filter(member=profile)

    # 2. NEW: Fetch notifications for this user (where they are a guarantor)
    # Shows requests for loans that are still pending and where they haven't responded yet
    pending_guarantor_requests = Guarantor.objects.filter(
        guarantor=profile,
        status='pending',
        loan__status='pending'
    ).select_related('loan__member__user')

    running_total_remaining_balance = Decimal('0.00')
    running_total_penalties = Decimal('0.00')

    # 3. Process Loans for the Portfolio Table
    for loan in loans:
        # Repayment totals
        total_paid = LoanRepayment.objects.filter(loan=loan).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
        total_payable = LoanRepaymentSchedule.objects.filter(loan=loan).aggregate(Sum('amount_due'))['amount_due__sum'] or Decimal('0.00')

        loan.total_paid = total_paid
        loan.total_payable = total_payable
        loan.remaining_balance = total_payable - total_paid

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

    return render(request, 'me.html', context)




@login_required
def respond_guarantor(request, guarantor_id, action):
    # Ensure the person responding is actually the assigned guarantor
    guarantor_req = get_object_or_404(Guarantor, id=guarantor_id, guarantor=request.user.profile)
    loan = guarantor_req.loan
    
    if action == 'accept':
        guarantor_req.status = 'accepted'
        guarantor_req.save()
        
        # --- NEW LOGIC: CHECK FOR ALL 3 APPROVALS ---
        accepted_count = Guarantor.objects.filter(loan=loan, status='accepted').count()
        # Use this to be 100% sure of the count
        # accepted_count = loan.guarantors.filter(status='accepted').count()
        
        if accepted_count >= 3:
            # Only change the loan status once all three have said yes
            loan.status = 'pending' # Or 'awaiting_staff' depending on your flow
            loan.save()
            messages.success(request, f"All 3 guarantors have accepted. The loan for {loan.member.user.get_full_name()} is now moving to staff approval.")
        else:
            messages.info(request, f"You accepted the request. Waiting for {3 - accepted_count} more guarantor(s).")
    
    elif action == 'reject':
        # If even ONE guarantor rejects, the whole loan application fails immediately
        guarantor_req.status = 'rejected'
        guarantor_req.save()
        
        loan.status = 'rejected'
        loan.save()
        messages.warning(request, "You declined the request. The loan application has been automatically cancelled.")
    
    return redirect('member_dashboard')
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
@login_required
@role_required(allowed_roles=[1])
def admin_dashboard(request):
    pending_loans = Loan.objects.filter(
        status__in=['pending', 'partially_approved']
    )
    
    approved_loans = Loan.objects.filter(status='approved')
    rejected_loans = Loan.objects.filter(status='rejected')
    
    all_members = Profile.objects.all() 

    total_savings_pool = MonthlyContribution.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    total_members = Profile.objects.count()
    total_interest_earned = Loan.objects.filter(status='completed').aggregate(Sum('amount'))['amount__sum'] or 0

    context = {
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

    GuarantorFormSet = modelformset_factory(
        Guarantor,
        form=GuarantorForm,
        extra=3,
        max_num=3,
        validate_min=True,
        min_num=3
    )

    # LIMITS
    total_active_loans = Loan.objects.filter(
        member=profile,
        status__in=['pending', 'approved']
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    total_savings = CapitalShare.objects.filter(
        member=profile
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    loan_limit = Decimal(total_savings) * Decimal('3.5')

    context = {
        'loan_limit': loan_limit,
        'total_savings': total_savings,
        'member_active_loans': total_active_loans,
    }

    if request.method == 'POST':
        form = LoanApplicationForm(request.POST, user_profile=profile)
        formset = GuarantorFormSet(request.POST, queryset=Guarantor.objects.none())

        if form.is_valid() and formset.is_valid():
            loan = form.save(commit=False)
            loan.member = profile

            principal = Decimal(loan.amount)
            months = Decimal(loan.duration_months)

            # 🔥 NEW INSURANCE
            principal = Decimal(loan.amount)
            months = Decimal(loan.duration_months)

            # 🔥 INSURANCE
            insurance = calculate_insurance(principal, months)

            # 🔥 INTEREST (use your rate)
            interest_rate = Decimal('0.259')  # 25.9% yearly
            years = months / Decimal('12')

            interest = principal * interest_rate * years

            # ✅ SAVE TO DB
            loan.insurance = insurance
            loan.interest = interest
            # 🔥 SALARY LOGIC
            gross = Decimal(loan.Gross_salary)
            net = Decimal(loan.net_salary)

            one_third_gross = gross / Decimal('3')
            affordability = one_third_gross - net

            monthly_payment = (principal + loan.insurance) / months

            if affordability <= 0:
                messages.error(request, "Loan rejected: Your net salary is too high compared to gross.")
                context.update({'form': form, 'formset': formset})
                return render(request, 'apply_loan.html', context)

            if affordability < monthly_payment:
                messages.error(request, f"Loan rejected: Salary cannot support monthly payment of KES {monthly_payment:,.2f}")
                context.update({'form': form, 'formset': formset})
                return render(request, 'apply_loan.html', context)

            # LIMIT CHECK
            if loan.amount > loan_limit:
                messages.error(request, f"Max loan limit is KES {loan_limit:,.2f}")
                context.update({'form': form, 'formset': formset})
                return render(request, 'apply_loan.html', context)

            # GUARANTORS
            total_guaranteed_amount = Decimal('0.00')
            selected = []

            for g_form in formset:
                if g_form.cleaned_data:
                    g_profile = g_form.cleaned_data.get('guarantor')
                    g_amount = g_form.cleaned_data.get('guaranteed_amount')

                    if g_profile == profile:
                        messages.error(request, "You cannot guarantee your own loan.")
                        context.update({'form': form, 'formset': formset})
                        return render(request, 'apply_loan.html', context)

                    selected.append(g_profile)

                    g_sav = CapitalShare.objects.filter(member=g_profile).aggregate(Sum('amount'))['amount__sum'] or 0
                    g_lim = Decimal(g_sav) * Decimal('3.5')
                    g_act = Loan.objects.filter(member=g_profile, status__in=['pending','approved']).aggregate(Sum('amount'))['amount__sum'] or 0

                    available = g_lim - Decimal(g_act)

                    if g_amount > available:
                        messages.error(request, f"{g_profile.user.get_full_name()} has only KES {available:,.2f}")
                        context.update({'form': form, 'formset': formset})
                        return render(request, 'apply_loan.html', context)

                    total_guaranteed_amount += g_amount

            if len(set(selected)) < 3:
                messages.error(request, "Select 3 unique guarantors.")
                context.update({'form': form, 'formset': formset})
                return render(request, 'apply_loan.html', context)

            if total_guaranteed_amount < loan.amount:
                messages.error(request, "Guarantors do not fully cover loan.")
                context.update({'form': form, 'formset': formset})
                return render(request, 'apply_loan.html', context)
            if loan.purpose != 'normal Loan' and loan.duration_months > 12:
                messages.error(request, "Only Normal Loans can exceed 12 months.")
                context.update({'form': form, 'formset': formset})
                return render(request, 'apply_loan.html', context)

            try:
                with transaction.atomic():
                    loan.status = 'pending'
                    loan.save()

                    guarantors = formset.save(commit=False)
                    for g in guarantors:
                        g.loan = loan
                        g.save()

                messages.success(request, "Loan submitted successfully.")
                return redirect('member_dashboard')

            except Exception as e:
                messages.error(request, str(e))

        else:
            messages.error(request, "Fix form errors.")

    else:
        form = LoanApplicationForm(user_profile=profile)
        formset = GuarantorFormSet(queryset=Guarantor.objects.none())

    context.update({'form': form, 'formset': formset})
    return render(request, 'apply_loan.html', context)

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

    total_savings_pool = MonthlyContribution.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    total_members = Profile.objects.count()
    total_interest_earned = LoanRepaymentSchedule.objects.filter(is_paid=True).aggregate(Sum('amount_due'))['amount_due__sum'] or 0

    context = {
        'pending_loans': pending_loans,
        'total_savings_pool': total_savings_pool,
        'total_members': total_members,
        'total_interest_earned': total_interest_earned,
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

def pending_loans_view(request):
    pending_loans = Loan.objects.filter(status='pending')
    context = {
        'pending_loans': pending_loans
    }
    return render(request, 'pending_loans.html', context)
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
    
    # Calculate Liquidity
    total_repayments = LoanRepayment.objects.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0')
    
    # Formula: (Money In) - (Money Out)
    available_cash = (total_savings + total_shares + total_repayments) - active_loans_value

    # 4. Recent Activity
    recent_transactions = Transaction.objects.all().order_by('-created_at')[:10]

    context = {
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
@login_required
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
def initiate_stk_push(request):
    if request.method == "POST":
        payment_type = request.POST.get('payment_type') # 'loan' or 'shares'
        amount = request.POST.get('amount')
        phone = request.user.profile.phone_number 
        
        access_token = get_mpesa_access_token()
        password, timestamp = get_mpesa_password()
        headers = {"Authorization": f"Bearer {access_token}"}

        # --- DYNAMIC REFERENCE LOGIC ---
        if payment_type == 'shares':
            # Use User ID since shares aren't always tied to a specific 'Loan ID'
            account_ref = f"SHARES-{request.user.id}"
            description = "Buying SACCO Shares"
        else:
            # Default to Loan Repayment
            loan_id = request.POST.get('loan_id')
            account_ref = f"LOAN-{loan_id}"
            description = "Loan Repayment"

        request_body = {
            "BusinessShortCode": "174379",
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(float(amount)),
            "PartyA": phone,
            "PartyB": "174379",
            "PhoneNumber": phone,
            "CallBackURL": "https://yourdomain.com/mpesa-callback/", # Change to your actual Ngrok/Domain
            "AccountReference": account_ref, # This is the "tag" we discussed!
            "TransactionDesc": description
        }
        
        response = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=request_body,
            headers=headers
        )
        
        messages.success(request, f"M-Pesa prompt for {description} sent to {phone}!")
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
                return redirect('approved_loans')

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

def Members(request):
    # Fetch all members and prefetch related loans for efficiency
    members = Profile.objects.prefetch_related('member_loans')  # ✅ works
    return render(request, 'mem.html', {'members': members})
