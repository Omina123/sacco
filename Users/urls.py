from django import views as auth_views
from Users.views import CustomPasswordResetView, CustomPasswordResetDoneView, CustomPasswordResetConfirmView, CustomPasswordResetCompleteView
from django.contrib import admin
from django.urls import path, include
from Users.views import*


urlpatterns = [
    path('register',register, name='register'),
    path('login/', Login, name='login'),
    path('update_profile',update_profile,name='update_profile'),
    path ('Logout',Logout, name= 'Logout'),
    path('edit_user_role/<int:user_id>',edit_user_role, name='edit_user_role'),
    path('access_denied/', access_denied, name='access_denied'),
    path('succfy/', succfy,name='succfy'),
    path('edit_salary/<int:user_id>/', edit_salary, name='edit_salary'),
    path('add_member/', add_member, name='add_member'),
    path('format_phone', format_phone, name='format_phone'),
    
     path('verify_otp/', verify_otp, name='verify_otp'),
     path('resend_otp/', resend_otp, name='resend_otp'),
    path('delete_member/<int:user_id>/', delete_member, name='delete_member'),
    # path('update_profile/', update_profile, name='update_profile'),
    path('update_user/<int:user_id>/', update_user, name='update_user'),
    path('password-reset/', CustomPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password-reset-complete/', CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('complete_membership/', complete_membership, name='complete_membership'),
    path('member_declaration_view/', member_declaration_view, name='member_declaration_view'),
    path ('update_member_contract/<int:profile_id>/', update_member_contract, name='update_member_contract'),
    path ('management_index/', management_index, name='management_index'),
]
