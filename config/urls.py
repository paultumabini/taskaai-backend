"""
config/urls.py

Root URL configuration for the backend service.

Routes:
- /admin/  -> Django admin site
- /api/    -> TaskaAI API (tasks.urls)
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('tasks.urls')),
]
