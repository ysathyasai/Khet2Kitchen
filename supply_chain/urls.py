"""
URL routing for K2K Supply Chain API endpoints.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from supply_chain.views import DemandOrderViewSet

router = DefaultRouter()
router.register(r"demand-orders", DemandOrderViewSet, basename="demand-order")

urlpatterns = [
    path("", include(router.urls)),
]
