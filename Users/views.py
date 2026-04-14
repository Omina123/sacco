from django.shortcuts import get_object_or_404, render, redirect

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

def register(request):
    if request.method == 'POST':
        user_form = MemberRegistrationForm(request.POST)
        if user_form.is_valid():
            user = user_form.save(commit=False)
            user.user_type = '4'  # Assign 'Member'
            user.save()
            
            # CRITICAL: Create the empty profile so the user can log in
            # and later fill it out via 'update_profile'
            Profile.objects.get_or_create(user=user)
            
            # messages.success(request, "Registration successful! Please login to complete your profile.")
            return redirect('succfy')
    else:
        user_form = MemberRegistrationForm()
    return render(request, 'register.html', {'user_form': user_form})

# # --- LOGIN / LOGOUT ---

# from django.utils import timezone
# from django.db import transaction
# from django.contrib import messages
# from django.shortcuts import render, redirect
# from .models import CustomUser, Profile
# from .forms import MemberRegistrationForm
# from .utils import send_brevo_email


# def register(request):
#     if request.method == 'POST':
#         form = MemberRegistrationForm(request.POST)

#         if form.is_valid():
#             try:
#                 with transaction.atomic():
#                     # ✅ Create user but don't verify yet
#                     user = form.save(commit=False)
#                     user.user_type = '4'
#                     user.is_verified = False  # 🔥 IMPORTANT
#                     user.generate_otp()  # 🔥 generate OTP here
#                     user.save()

#                     # ✅ Create profile
#                     Profile.objects.get_or_create(user=user)

#                     # ✅ Store email in session
#                     request.session['verification_email'] = user.email

#                     # ✅ Send OTP email (PROFESSIONAL TEMPLATE)
#                     html_content = f"""
#                     <div style="font-family: Arial; padding: 20px;">
#                         <h2 style="color:#0B1F3A;">Verify Your Account</h2>
#                         <p>Hello {user.first_name},</p>
#                         <p>Your OTP code is:</p>
#                         <h1 style="color:#D4AF37;">{user.otp}</h1>
#                         <p>This code expires soon.</p>
#                         <hr>
#                         <small>St. Peters Parish SACCO</small>
#                     </div>
#                     """

#                     send_brevo_email(
#                         to_email=user.email,
#                         subject="Account Verification OTP",
#                         html_content=html_content
#                     )

#                     messages.success(request, "OTP sent to your email. Verify your account.")
#                     return redirect('verify_otp')

#             except Exception as e:
#                 messages.error(request, f"Error: {str(e)}")

#     else:
#         form = MemberRegistrationForm()

    return render(request, 'register.html', {'user_form': form})
def Login(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            # 'email' here acts as the identifier (Email or PF Number)
            email = form.cleaned_data['Email']
            password = form.cleaned_data['password']

            # authenticate() will use EmailBackend to check both email and pf_number
            user = authenticate(request, username=email, password=password)
            
            if user is not None:
                # if not user.is_verified:
                #     messages.error(request, "Your account is not verified. Please verify OTP first.")
                #     request.session['verification_email'] = user.email
                #     return redirect('verify_otp')
                
                login(request, user)  # Log the user in
                
                profile = user.profile

                # Redirect based on user type and profile completion
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
                    # Redirect to complete profile if ID or Phone is missing
                    return redirect('update_profile')
            else:
                form.add_error(None, "Invalid email/PF Number or password")
    else:
        form = LoginForm()
    return render(request, 'login.html', {'form': form})
#     if request.method == 'POST':
#         form = LoginForm(request.POST)
#         if form.is_valid():
#             email = form.cleaned_data['Email']
#             password = form.cleaned_data['password']

#             user = authenticate(request, username=email, password=password)
            
#             if user is not None:
#                 if not user.is_verified:
#                     messages.error(request, "Your account is not verified. Please verify OTP first.")
#                     request.session['verification_email'] = user.email
#                     return redirect('verify_otp')
#                 login(request, user)  # ONLY once
                
#                 profile = user.profile

#                 # Redirect based on user type
#                 if profile.id_number and profile.phone_number:
#                     if user.is_superuser or user.user_type == '1':
#                         return redirect('admin_dashboard')
#                     elif user.user_type == '2':
#                         return redirect('staff_dashboard')
#                     elif user.user_type == '3':
#                         return redirect('treasurer_dashboard')
#                     elif user.user_type == '5':
#                         return redirect('Human_Resource')
#                     else:
#                         return redirect('member_dashboard')
#                 else:
#                     return redirect('update_profile')
#             else:
#                 form.add_error(None, "Invalid email or password")
#     else:
#         form = LoginForm()
#     return render(request, 'login.html', {'form': form})

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
            profile.membership_number = profile.membership_number or None

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
    # if request.user.user_type != '1' and not request.user.is_superuser:
    #     messages.error(request, "Unauthorized access.")
    #     return redirect('member_dashboard')

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
    # Fetch the profile of the user HR wants to update
    profile = get_object_or_404(Profile, id=user_id)

    if request.method == "POST":
        form = EditSalaryForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
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
                subject="Password Reset Request - St. Peters Parish", 
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
            messages.success(request, "Verified! You can now login.")
            return redirect('s')
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
        <div style="font-family: Arial; padding: 20px; border-top: 5px solid #FFD700;">
            <h2>New Verification Code</h2>
            <p>Your new OTP is: <strong style="font-size: 24px; color: #212529;">{user.otp}</strong></p>
            <p>This code replaces your previous one.</p>
        </div>
        """
        send_brevo_email(user.email, "New OTP - St. Peters Parish", html_content)
        
        messages.success(request, "A fresh code has been sent to your email.")
    except CustomUser.DoesNotExist:
        messages.error(request, "User not found.")
        
    return redirect('verify_otp')