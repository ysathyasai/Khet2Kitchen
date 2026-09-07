"""
Root URL configuration for Project Khet2Kitchen (K2K).
"""

from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Project Khet2Kitchen Administration"
admin.site.site_title = "K2K Admin Portal"
admin.site.index_title = "K2K Supply Chain Operations"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]
