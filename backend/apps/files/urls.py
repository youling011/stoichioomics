from django.urls import path
from .views import files_root
urlpatterns = [path('', files_root)]
