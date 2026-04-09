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
    path('delete_member/<int:user_id>/', delete_member, name='delete_member'),
    # path('update_profile/', update_profile, name='update_profile'),
    path('update_user/<int:user_id>/', update_user, name='update_user'),
    
]
