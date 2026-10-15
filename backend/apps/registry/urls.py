from django.urls import path
from .views import registry_cases, registry_register, registry_promote, registry_unregister, registry_compare
urlpatterns = [
    path('cases/', registry_cases),
    path('register/', registry_register),
    path('promote/', registry_promote),
    path('unregister/', registry_unregister),
    path('compare/', registry_compare),
]
