"""
Khet2Kitchen (K2K) Supply Chain Serializers.

Provides DRF serializers for DemandOrder and dual-channel pricing analytics:
- DemandOrderSerializer: Serializes orders with embedded financial breakdown.
- FinancialBreakdownSerializer: Explicit schema for channel-specific economics.
- ChannelAnalyticsSerializer: Aggregate volume, revenue, costs, and profit metrics.
"""

from decimal import Decimal
from rest_framework import serializers
from supply_chain.models import DemandOrder, Crop, User


class FinancialBreakdownSerializer(serializers.Serializer):
    order_id = serializers.CharField()
    channel = serializers.CharField()
    channel_display = serializers.CharField()
    volume_kg = serializers.FloatField()
    price_per_kg = serializers.FloatField()
    gross_inflow = serializers.FloatField()
    payment_gateway_fee = serializers.FloatField()
    net_inflow = serializers.FloatField()
    gross_farmer_payout = serializers.FloatField()
    input_debt_deduction = serializers.FloatField()
    farmer_net_upi_settlement = serializers.FloatField()
    supplier_input_repayment = serializers.FloatField()
    single_truck_transit_cost = serializers.FloatField()
    eco_packaging_cost = serializers.FloatField()
    hub_and_tech_ops_cost = serializers.FloatField()
    total_platform_operating_costs = serializers.FloatField()
    total_outflows = serializers.FloatField()
    net_platform_profit = serializers.FloatField()
    net_profit_margin_pct = serializers.FloatField()
    households = serializers.IntegerField()
    community_name = serializers.CharField()


class DemandOrderSerializer(serializers.ModelSerializer):
    channel_display = serializers.CharField(source="get_channel_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    crop_name = serializers.CharField(source="crop.name", read_only=True)
    retailer_name = serializers.SerializerMethodField()
    estimated_cost = serializers.SerializerMethodField()
    financial_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = DemandOrder
        fields = [
            "id",
            "order_id",
            "channel",
            "channel_display",
            "retailer",
            "retailer_name",
            "crop",
            "crop_name",
            "required_volume_kg",
            "target_price_per_kg",
            "delivery_community_name",
            "num_households",
            "input_advance_amount",
            "supplier_cost_amount",
            "required_date",
            "status",
            "status_display",
            "delivery_address",
            "estimated_cost",
            "financial_breakdown",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "order_id", "created_at", "updated_at"]

    def get_retailer_name(self, obj) -> str:
        if obj.retailer:
            return obj.retailer.get_full_name() or obj.retailer.identifier
        return "Unknown"

    def get_estimated_cost(self, obj) -> float:
        return float(obj.calculate_estimated_cost())

    def get_financial_breakdown(self, obj) -> dict:
        return obj.calculate_financial_breakdown()


class ChannelAnalyticsSerializer(serializers.Serializer):
    channel = serializers.CharField()
    order_count = serializers.IntegerField()
    total_volume_kg = serializers.FloatField()
    total_gross_inflow = serializers.FloatField()
    total_farmer_payout = serializers.FloatField()
    total_operating_costs = serializers.FloatField()
    total_platform_profit = serializers.FloatField()
    avg_profit_margin_pct = serializers.FloatField()
