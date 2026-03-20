from django.contrib import admin
from django.urls import path, include
from home import views

urlpatterns = [
    path('', views.home, name="home"),
    path ('about', views.about, name= "about"),
    path ('Contact', views.Contact, name= "Contact"),
    path ('Service', views.Service, name= "Service"),
    path('member_dashboard',views.member_dashboard,name='member_dashboard'),
    path('deposit_savings',views.deposit_savings, name='deposit_savings'),
    path('apply_loan',views.apply_loan, name='apply_loan'),
    path('purchase_shares',views.purchase_shares, name='purchase_shares'),
    path ('Setting_loan',views.Setting_loan,name='Setting_loan'),
    path('admin_dashboard',views.admin_dashboard,name='admin_dashboard'),
    path ('LoanP',views.LoanP,name='LoanP'),
    path ('pay_loan',views.pay_loan, name='pay_loan'),
    path ('approve_loan/<int:loan_id>', views.approve_loan, name='approve_loan'),
     path ('download_receipt/<int:saving_id>', views.download_receipt, name='download_receipt'),
    path ('manage_loan_requests', views.manage_loan_requests, name='manage_loan_requests'),
    path ('record_transaction', views.record_transaction, name='record_transaction'),
    path ('initiate_stk_push', views.initiate_stk_push, name='initiate_stk_push'),
    
]
