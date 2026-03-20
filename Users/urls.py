from django.contrib import admin
from django.urls import path, include
from Users import views

urlpatterns = [
    path('register', views.register, name='register'),
    path ('Login', views.Login, name='Login'),
    path('update_profile',views.update_profile,name='update_profile'),
    
    
]
