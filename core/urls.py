from django.contrib.auth import views as auth_views
from django.urls import path

from core import views

urlpatterns = [
    # Central Landing Page & Dashboard Dispatcher
    path("", views.landing_page_view, name="home"),
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

    # Dynamic Farmer Actions (Add, Edit, Inspect)
    path("farmer/crops/add/", views.add_crop_view, name="add_crop"),
    path("farmer/crops/<int:crop_id>/edit/", views.edit_crop_view, name="edit_crop"),
    path("farmer/crops/<int:crop_id>/inspect/", views.crop_inspect_view, name="crop_inspect"),

    # Dynamic Retailer Actions
    path("retailer/orders/create/", views.add_demand_order_view, name="add_demand_order"),
    path("retailer/orders/<str:order_id>/allocate/", views.allocate_order_view, name="allocate_order"),
    path("retailer/combos/", views.retailer_combos_view, name="retailer_combos"),
    path("retailer/combos/<int:combo_id>/purchase/", views.retailer_purchase_combo_view, name="retailer_purchase_combo"),

    # Dynamic Supplier Actions
    path("supplier/inputs/add/", views.add_input_supply_view, name="add_input_supply"),
    path("supplier/inputs/<int:supply_id>/update/", views.update_input_supply_view, name="update_input_supply"),

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

    # Direct-to-Consumer (D2C) Marketplace & AI Recipe-to-Combo Routes
    path("consumer/", views.consumer_shop_view, name="consumer_shop"),
    path("consumer/shop/", views.consumer_shop_view, name="consumer_shop_alt"),
    path("consumer/dashboard/", views.consumer_dashboard_view, name="consumer_dashboard"),
    path("consumer/combo/", views.ai_combo_builder_view, name="ai_combo_builder"),
    path("consumer/checkout/", views.consumer_checkout_view, name="consumer_checkout"),
    path("consumer/order/<str:order_id>/", views.consumer_order_success_view, name="consumer_order_success"),
    path("consumer/order/<str:order_id>/feedback/", views.consumer_add_feedback_view, name="consumer_add_feedback"),

    # Authentication Routes
    path(
        "auth/send-otp/",
        views.send_otp_view,
        name="send_otp",
    ),
    path(
        "signup/",
        views.signup_view,
        name="signup",
    ),
    path(
        "login/",
        views.login_view,
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(next_page="home"),
        name="logout",
    ),
]
