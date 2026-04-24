from django.shortcuts import get_object_or_404, render, redirect
from home.models import NormalShares,RegistrationFee
from .forms import *
from .EmailBackend import EmailBackend
from django.contrib.auth import authenticate, login,logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse_lazy
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordResetForm
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.urls import reverse_lazy
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from .models import CustomUser
from.forms import *
from django.db import transaction
from .utils import send_brevo_email
from .EmailBackend import EmailBackend
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib import messages
from home.models import HRNotification
from .forms import MembershipSetupForm
from .models import Profile
from .utils import generate_membership_number
def register(request):
    if request.method == 'POST':
        user_form = MemberRegistrationForm(request.POST)
        if user_form.is_valid():
            user = user_form.save(commit=False)
            user.user_type = '4'  # Assign 'Member'
            user.is_verified = False  # Ensure they start unverified
            user.save()
            
            # Create the profile
            Profile.objects.get_or_create(user=user)

            # --- OTP INTEGRATION ---
            user.generate_otp() # Generate the 6-digit code
            
            # Store email in session so verify_otp/resend_otp knows who we are dealing with
            request.session['verification_email'] = user.email
            
            html_content = f"""
<div style="background-color: #f4f7f6; padding: 40px 10px; font-family: 'Segoe UI', Helvetica, Arial, sans-serif;">
    <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.1);">
        
        <div style="background-color: #002147; padding: 30px; text-align: center;">
            <h1 style="color: #FFD700; margin: 0; font-size: 22px; letter-spacing: 2px; text-transform: uppercase;">
                Eldoret Polytechnic SACCO
            </h1>
        </div>

        <div style="padding: 40px; color: #333333; line-height: 1.6;">
            <h2 style="color: #002147; margin-top: 0;">Account Verification</h2>
            <p style="font-size: 16px;">Hello,</p>
            <p style="font-size: 16px;">Thank you for registering with <strong>Eldopoly SACCO</strong>. To secure your account and complete your membership setup, please use the verification code below:</p>
            
            <div style="margin: 30px 0; text-align: center; background-color: #f9f9f9; border: 2px dashed #FFD700; border-radius: 10px; padding: 20px;">
                <p style="margin: 0; font-size: 14px; color: #777; text-transform: uppercase; letter-spacing: 1px;">Your OTP Code</p>
                <span style="font-size: 36px; font-weight: bold; color: #002147; letter-spacing: 8px;">{user.otp}</span>
            </div>

            <p style="font-size: 14px; color: #555;">This code is required to activate your account. If you did not request this, please ignore this email or contact the SACCO treasury department.</p>
            
            <hr style="border: none; border-top: 1px solid #eeeeee; margin: 30px 0;">
            
            <p style="font-size: 13px; color: #888; text-align: center; margin-bottom: 0;">
                Best Regards,<br>
                <strong>The Treasury Team</strong><br>
                Eldoret Polytechnic SACCO
            </p>
        </div>

        <div style="background-color: #fcfcfc; padding: 20px; text-align: center; border-top: 1px solid #eeeeee;">
            <p style="font-size: 11px; color: #aaa; margin: 0;">
                &copy; 2026 Eldoret Polytechnic SACCO | All Rights Reserved.
            </p>
        </div>
    </div>
</div>
            """
            send_brevo_email(user.email, "Verify Your Account", html_content)
            # -----------------------

            messages.info(request, "Registration successful! Please enter the OTP sent to your email.")
            return redirect('verify_otp') # Send them straight to the OTP page
    else:
        user_form = MemberRegistrationForm()
    return render(request, 'register.html', {'user_form': user_form})

def Login(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['Email']
            password = form.cleaned_data['password']

            user = authenticate(request, username=email, password=password)
            
            if user is not None:
                # --- VERIFICATION CHECK ---
                if not user.is_verified:
                    messages.warning(request, "Your account is not verified. Please verify the OTP sent to your email.")
                    request.session['verification_email'] = user.email
                    
                    # Optional: Resend OTP automatically if it was deleted/expired
                    if not user.otp:
                        user.generate_otp()
                        # (Add send_brevo_email logic here if you want to auto-resend)
                        
                    return redirect('verify_otp')
                # --------------------------
                
                login(request, user)
                profile = user.profile

                # Redirect logic based on profile completion
                if profile.id_number and profile.phone_number:
                    if user.is_superuser or user.user_type == '1':
                        return redirect('admin_dashboard')
                    elif user.user_type == '2':
                        return redirect('staff_dashboard')
                    elif user.user_type == '3':
                        return redirect('treasurer_dashboard')
                    elif user.user_type == '5':
                        return redirect('Human_Resource')
                    else:
                        return redirect('member_dashboard')
                else:
                    return redirect('update_profile')
            else:
                form.add_error(None, "Invalid email/PF Number or password")
    else:
        form = LoginForm()
    return render(request, 'login.html', {'form': form})
@login_required

def update_profile(request):
    user = request.user
    profile_instance = user.profile

    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=user)
        p_form = ProfileForm(request.POST, request.FILES, instance=profile_instance)

        if u_form.is_valid() and p_form.is_valid():
            # Save user basic info
            u_form.save()

            # Save profile safely
            profile = p_form.save(commit=False)

            # Handle optional unique fields (avoid empty string issues)
            profile.pf_number = profile.pf_number or None
            # profile.membership_number = profile.membership_number or None

            # 🔥 IMPORTANT: Reset salary review flag after update
            if hasattr(profile, 'salary_needs_review'):
                profile.salary_needs_review = False

            profile.save()

            messages.success(request, "Profile updated successfully.")
            return redirect('member_dashboard')

        else:
            messages.error(request, "Please correct the errors below.")

    else:
        u_form = UserUpdateForm(instance=user)
        p_form = ProfileForm(instance=profile_instance)

    return render(request, 'up.html', {
        'u_form': u_form,
        'p_form': p_form
    })
def Logout(request):
    logout(request)
    return redirect('login')

def edit_user_role(request, user_id):
    # Only allow actual Admins (type '1') to access this view
    if request.user.user_type != '1' and not request.user.is_superuser:
        messages.error(request, "Unauthorized access.")
        return redirect('access_denied')

    target_user = get_object_or_404(CustomUser, id=user_id)
    
    if request.method == "POST":
        form = UserRoleForm(request.POST, instance=target_user)
        if form.is_valid():
            user = form.save(commit=False)
            
            # Sync internal Django permissions with your SACCO roles
            # Admin('1'), Staff('2'), and Treasurer('3') need is_staff = True
            if user.user_type in ['1', '2', '3']:
                user.is_staff = True
            else:
                user.is_staff = False
            
            user.save()
            messages.success(request, f"Role for {user.username} updated.")
            return redirect('admin_dashboard')
    else:
        form = UserRoleForm(instance=target_user)
    
    return render(request, 'edit.html', {'form': form, 'target_user': target_user})
def access_denied(request):
    return render(request, '403.html', status=403)
def succfy(request):
    return render(request, "ht.html")
def edit_salary(request, user_id):
    profile = get_object_or_404(Profile, id=user_id)

    if request.method == "POST":
        form = EditSalaryForm(request.POST, instance=profile)
        if form.is_valid():
            profile = form.save(commit=False)
            
            # Ensure salary review is marked complete
            profile.salary_needs_review = False
            profile.save()

            # Mark related notifications as read
            HRNotification.objects.filter(
                member=profile,
                is_read=False
            ).update(is_read=True)

            messages.success(request, f"Salaries for {profile.user.get_full_name()} updated.")
            return redirect('Human_Resource')
    else:
        form = EditSalaryForm(instance=profile)

    return render(request, 'salary.html', {'form': form, 'profile': profile})
# views.py


# Optional: Only allow admins/treasurers to delete members

def delete_member(request, user_id):
    """
    Deletes a member (CustomUser) and their related profile.
    """
    member = get_object_or_404(CustomUser, id=user_id)

    if request.method == "POST":
        member_name = member.get_full_name() or member.username
        member.delete()
        messages.success(request, f"Member '{member_name}' has been deleted successfully.")
        return redirect('admin_dashboard')  # Change to your members list page

    # If GET request, render a confirmation page
    return render(request, 'delete.html', {'member': member})

# @role_required(allowed_roles=['1'])  # Admin only
def update_user(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id)
    profile = get_object_or_404(Profile, user=user)

    if request.method == 'POST':
        user_form = UpdateForm(request.POST, instance=user)
        profile_form = PUpdateForm(request.POST, request.FILES, instance=profile)

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()

            messages.success(request, "User updated successfully ✅")
            return redirect('admin_dashboard')  # your member list page

        else:
            messages.error(request, "Please correct the errors below ❌")

    else:
        user_form = UpdateForm(instance=user)
        profile_form = PUpdateForm(instance=profile)

    return render(request, 'update_user.html', {
        'user_form': user_form,
        'profile_form': profile_form,
        'user_obj': user
    })

class CustomPasswordResetView(auth_views.PasswordResetView):
    form_class = PasswordResetForm
    template_name = 'password_reset.html'
    success_url = reverse_lazy('password_reset_done')

    def form_valid(self, form):
        email = form.cleaned_data["email"]
        users = CustomUser.objects.filter(email=email)
        
        for user in users:
            # 1. Generate security credentials
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            
            # 2. Prepare context for your styled template
            context = {
                'user': user,
                'protocol': 'https' if self.request.is_secure() else 'http',
                'domain': self.request.get_host(),
                'uid': uid,
                'token': token,
                'now': timezone.now(), # For the copyright year in footer
            }
            
            # 3. Render the styled HTML template
            html_content = render_to_string('password_reset_email.html', context)
            
            # 4. Send via Brevo
            send_brevo_email(
                to_email=user.email, 
                subject="Password Reset Request - Eldoret Polytechnic SACCO Limited", 
                html_content=html_content
            )

        # Redirect to the 'Done' page regardless of user existence (security best practice)
        return redirect(self.success_url)

class CustomPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'password_reset_done.html'

class CustomPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'password_reset_confirm.html'
    success_url = reverse_lazy('password_reset_complete')

class CustomPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'password_reset_complete.html'


def format_phone(phone):
    if phone:
        if phone.startswith('0'):
            return '254' + phone[1:]
        if phone.startswith('+254'):
            return phone[1:]
    return phone


def add_member(request):
    if request.user.user_type not in ['1'] and not request.user.is_superuser:
        messages.error(request, "Access Denied: Unauthorized.")
        return redirect('member_dashboard')

    if request.method == "POST":
        try:
            with transaction.atomic():

                # Format phones
                phone_number = format_phone(request.POST.get('phone_number'))
                next_of_kin_phone = format_phone(request.POST.get('next_of_kin_phone'))

                # Create user
                user = CustomUser.objects.create_user(
                    username=request.POST.get('username'),
                    email=request.POST.get('email'),
                    password=request.POST.get('password'),
                    first_name=request.POST.get('first_name'),
                    last_name=request.POST.get('last_name'),
                    user_type='4'
                )

                # ✅ USE existing profile (from signal)
                profile = user.profile

                # Update profile
                profile.phone_number = phone_number
                profile.id_number = request.POST.get('id_number')
                profile.membership_number = request.POST.get('membership_number')
                profile.pf_number = request.POST.get('pf_number')
                profile.date_of_birth = request.POST.get('date_of_birth') or None
                profile.gender = request.POST.get('gender')
                profile.address = request.POST.get('address')
                profile.next_of_kin = request.POST.get('next_of_kin')
                profile.Next_of_kin_phone = next_of_kin_phone

                if 'profile_picture' in request.FILES:
                    profile.profile_picture = request.FILES['profile_picture']

                profile.full_clean()
                profile.save()

                messages.success(request, "Member created successfully!")
                return redirect('admin_dashboard')

        except Exception as e:
            messages.error(request, f"Error creating account: {str(e)}")

    return render(request, 'Add_member.html')
def verify_otp(request):
    if request.method == 'POST':
        otp_entered = request.POST.get('otp')
        email = request.session.get('verification_email')
        
        try:
            user = CustomUser.objects.get(email=email, otp=otp_entered)
            user.is_verified = True
            user.otp = "" 
            user.save()
            # messages.success(request, "Verified! You can now login.")
            return redirect('succfy')  # Redirect to a success page or login
        except CustomUser.DoesNotExist:
            messages.error(request, "Invalid OTP.")
            
    return render(request, 'otp.html')
def resend_otp(request):
    email = request.session.get('verification_email')
    
    if not email:
        messages.error(request, "Session expired. Please register again.")
        return redirect('register')

    try:
        user = CustomUser.objects.get(email=email)
        user.generate_otp()  # This creates a new 6-digit code in the DB

        # Send the new code via Brevo (using your professional style)
        html_content = f"""
        <div style="background-color: #f4f7f6; padding: 30px 10px; font-family: 'Segoe UI', Arial, sans-serif;">
            <div style="max-width: 500px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; border-top: 6px solid #FFD700; box-shadow: 0 4px 12px rgba(0,0,0,0.05); overflow: hidden;">
                
                <div style="padding: 30px; text-align: center;">
                    <h2 style="color: #002147; margin-bottom: 10px; font-size: 22px; font-weight: bold;">New Verification Code</h2>
                    <p style="color: #666666; font-size: 15px;">Your requested security code is ready. The previous code has been deactivated for your protection.</p>
                    
                    <div style="margin: 25px 0; padding: 20px; background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 10px; display: inline-block; min-width: 220px;">
                        <p style="margin: 0 0 5px 0; font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 2px;">Your New OTP</p>
                        <span style="font-size: 36px; font-weight: bold; color: #002147; letter-spacing: 6px;">{user.otp}</span>
                    </div>

                    <p style="margin-top: 20px; font-size: 13px; color: #888; line-height: 1.5;">
                        This code replaces your previous one. If you did not make this request, please contact the Eldopoly SACCO treasury immediately.
                    </p>
                </div>
                
                <div style="background-color: #002147; padding: 15px; text-align: center;">
                    <p style="color: #ffffff; font-size: 11px; margin: 0; opacity: 0.8; letter-spacing: 1px;">
                        ELDORET POLYTECHNIC SACCO | SECURE BANKING
                    </p>
                </div>
            </div>
        </div>
        """
        send_brevo_email(user.email, "New OTP - Eldoret Polytechnic SACCO", html_content)
        
        messages.success(request, "A fresh code has been sent to your email.")
    except CustomUser.DoesNotExist:
        messages.error(request, "User not found.")
        
    return redirect('verify_otp')
 # adjust if different

@login_required
def complete_membership(request):
    profile = request.user.profile

    # if already completed → skip
    if profile.membership_number:
        return redirect('member_dashboard')

    if request.method == "POST":
        form = MembershipSetupForm(request.POST)
        if form.is_valid():
            contribution = form.cleaned_data['monthly_contribution']

            # simulate payment success (replace with mpesa later)
            registration_fee_amount = 500
            payment_successful = True

            if payment_successful:
                # ✅ 1. Assign membership number
                profile.membership_number = generate_membership_number()
                profile.save()

                # ✅ 2. Save capital share (ONE TIME)
                NormalShares.objects.create(
                    member=profile,
                    amount=contribution
                )

                # ✅ 3. Save registration fee
                RegistrationFee.objects.update_or_create(
                    member=profile,
                    defaults={
                        'amount': registration_fee_amount,
                        'paid': True,
                        'paid_at': timezone.now()
                    }
                )

                messages.success(request, "Membership completed successfully!")
                return redirect('member_dashboard')
    else:
        form = MembershipSetupForm()

    return render(request, 'setup.html', {'form': form})
