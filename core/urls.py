from django.contrib.auth import views as auth_views
from django.urls import path

from core import views

urlpatterns = [
    # Central Dashboard Dispatcher
    path("", views.dashboard_dispatcher_view, name="home"),
    path("dashboard/", views.dashboard_dispatcher_view, name="dashboard_dispatch"),

    # Role-Specific Dashboard Routes
    path("farmer/dashboard/", views.farmer_dashboard_view, name="farmer_dashboard"),
    path("farmer/graded-produce/", views.farmer_graded_produce_view, name="farmer_graded_produce"),
    path("farmer/pricing/", views.farmer_pricing_view, name="farmer_pricing"),
    path("farmer/orders/", views.farmer_orders_view, name="farmer_orders"),
    path("farmer/wallet/", views.farmer_wallet_view, name="farmer_wallet"),
    path("farmer/logistics/", views.farmer_logistics_view, name="farmer_logistics"),
    path("farmer/weather/", views.farmer_weather_view, name="farmer_weather"),
    path("retailer/dashboard/", views.retailer_dashboard_view, name="retailer_dashboard"),
    path("supplier/dashboard/", views.supplier_dashboard_view, name="supplier_dashboard"),
    path("k2k-command/", views.admin_dashboard_view, name="admin_command_dashboard"),

    # Supply Allocation Action
    path("retailer/orders/<str:order_id>/allocate/", views.allocate_order_view, name="allocate_order"),

    # Computer Vision AI Grading API
    path("api/grade-batch/", views.api_grade_batch, name="api_grade_batch"),

    # Batch Traceability API
    path("api/trace-batch/<str:batch_id>/", views.api_trace_batch, name="api_trace_batch"),

    # Mocked Dynamic Dispatch Routing API
    path("api/route-plan/", views.api_dynamic_route, name="api_dynamic_route"),
    path("api/route-plan/<int:hub_id>/", views.api_dynamic_route, name="api_dynamic_route_hub"),

    # Digital Wallet Withdrawal Action
    path("api/wallet/withdraw/", views.api_withdraw_wallet, name="api_withdraw_wallet"),

    # Hybrid Vernacular Voice Assistant API
    path("api/voice/assist/", views.api_voice_assist, name="api_voice_assist"),
    path("api/v1/voice-assistant/process-command/", views.api_voice_assist, name="api_voice_assist_v1"),

    # Real-time Agronomic Weather Intelligence API
    path("api/weather-advisory/", views.api_weather_advisory, name="api_weather_advisory"),

    # Authentication Routes
    path(
        "signup/",
        views.signup_view,
        name="signup",
    ),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="core/login.html"),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
]
