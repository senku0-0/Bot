from django.urls import path
from .views import index, webhook_message

urlpatterns = [
    path('', index, name='index'),
    path('hooks/sunshine/message', webhook_message, name='sunshine_webhook'),
]