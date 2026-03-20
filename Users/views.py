from django.shortcuts import render, redirect
from .forms import *
from .EmailBackend import EmailBackend
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
def register(request):
    if request.method == 'POST':
        user_form = MemberRegistrationForm(request.POST)
        if user_form.is_valid():
            user = user_form.save(commit=False)
            user.user_type = 'member'
            # Note: UserCreationForm handles password hashing automatically
            user.save() 
            return redirect('Login')
    else:
        user_form = MemberRegistrationForm()

    return render(request, 'register.html', {'user_form': user_form})

# --- LOGIN / LOGOUT ---
def Login(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)

        if form.is_valid():
            email = form.cleaned_data['Email']
            password = form.cleaned_data['password']

            user = authenticate(request, username=email, password=password)

            if user is not None:
                login(request, user)

                profile = user.profile

                # Check if profile is filled
                if profile.id_number and profile.phone_number:

                    if user.is_superuser:
                        return redirect('admin_dashboard')

                    elif user.user_type == 'admin':
                        return redirect('admin_dashboard')

                    elif user.user_type == 'staff':
                        return redirect('staff_dashboard')

                    elif user.user_type == 'treasurer':
                        return redirect('treasurer_dashboard')

                    else:
                        return redirect('member_dashboard')

                else:
                    return redirect('update_profile')

            else:
                form.add_error(None, "Invalid email or password")

    else:
        form = LoginForm()

    return render(request, 'login.html', {'form': form})

# def Login(request):
#     if request.method == 'POST':
#         form = LoginForm(request.POST)
#         if form.is_valid():
#             # Match the field name 'Email' from your forms.py
#             email = form.cleaned_data['Email'] 
#             password = form.cleaned_data['password']

#             # Authenticate using the EmailBackend
#             user = authenticate(request, username=email, password=password)
            
#             if user is not None:
#                 login(request, user)
#                 # Dynamic Redirect based on user_typ
#                 profile = user.profile 
#                 #is_profile_complete = profile.id_number is not None and profile.phone_number != ""
#                 if profile.id_number and profile.phone_number:
#                     if user.is_superuser:
#                         return redirect('admin_dashboard')
#                     if user.user_type == 'admin':
#                         return redirect('admin_dashboard') # Ensure these URLs exist
#                     elif user.user_type == 'staff':
#                         return redirect('staff_dashboard')
#                     elif user.user_type == 'treasurer':
#                         return redirect('treasurer_dashboard')
#                 else:
#                     return redirect('update_profile')
#             else:
#                 form.add_error(None, "Invalid email or password")
#     else:
#         form = LoginForm()
#     return render(request, 'login.html', {'form': form})
@login_required
def update_profile(request):
    if request.method == 'POST':
        # Load both forms with the POST data
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileForm(request.POST, request.FILES, instance=request.user.profile)

        if u_form.is_valid() and p_form.is_valid():
            u_form.save() # Saves first_name, last_name, email
            
            profile = p_form.save(commit=False)
            # Ensure unique fields are handled correctly
            if not profile.pf_number: profile.pf_number = None
            if not profile.membership_number: profile.membership_number = None
            profile.save() # Saves ID, Phone, Address, etc.
            
            return redirect('member_dashboard')
    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = ProfileForm(instance=request.user.profile)

    return render(request, 'up.html', {
        'u_form': u_form,
        'p_form': p_form
    })