from django.shortcuts import get_object_or_404, render, redirect

from .forms import *
from .EmailBackend import EmailBackend
from django.contrib.auth import authenticate, login,logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages

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

# --- LOGIN / LOGOUT ---

def Login(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['Email']
            password = form.cleaned_data['password']

            user = authenticate(request, username=email, password=password)
            
            if user is not None:
                login(request, user)  # ONLY once
                print("Authenticated:", user)
                login(request, user)
                print("User logged in:", request.user.is_authenticated)
                print("Authenticated:", user)
                print("Is staff?", user.is_staff)
                print("User type:", user.user_type)
                profile = user.profile

                # Redirect based on user type
                if profile.id_number and profile.phone_number:
                    if user.is_superuser or user.user_type == '1':
                        return redirect('admin_dashboard')
                    elif user.user_type == '2':
                        return redirect('staff_dashboard')
                    elif user.user_type == '3':
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
def Logout(request):
    logout(request)
    return redirect('login')
@login_required
def edit_user_role(request, user_id):
    # Only allow actual Admins (type '1') to access this view
    if request.user.user_type != '1' and not request.user.is_superuser:
        messages.error(request, "Unauthorized access.")
        return redirect('member_dashboard')

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
        user_form = UserUpdateForm(request.POST, instance=user)
        profile_form = ProfileUpdateForm(request.POST, request.FILES, instance=profile)

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()

            messages.success(request, "User updated successfully ✅")
            return redirect('Member')  # your member list page

        else:
            messages.error(request, "Please correct the errors below ❌")

    else:
        user_form = UserUpdateForm(instance=user)
        profile_form = ProfileUpdateForm(instance=profile)

    return render(request, 'update_user.html', {
        'user_form': user_form,
        'profile_form': profile_form,
        'user_obj': user
    })