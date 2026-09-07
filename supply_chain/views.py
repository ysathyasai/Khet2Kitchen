"""
Khet2Kitchen (K2K) Supply Chain Views & Intelligence Engine.

Provides DemandOrderViewSet with Dual-Pricing Intelligence Engine factoring in channel:
- B2B Wholesale: Bulk institutional orders, point-to-point freight, standard ~10% volume margin.
- COMMUNITY: Gated society pre-orders, upfront payment inflow, eco-packaging, single-truck apartment drop,
  automated input financing deduction, and ~28.5% net platform profit margin.
"""

from decimal import Decimal
from django.db.models import Sum, Count, Avg, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from supply_chain.models import DemandOrder, Crop, User
from supply_chain.serializers import (
    DemandOrderSerializer,
    FinancialBreakdownSerializer,
    ChannelAnalyticsSerializer,
)


class DemandOrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing and analyzing Demand Orders across B2B and COMMUNITY channels.
    Includes built-in pricing intelligence algorithms for bulk freight vs. community drops.
    """
    queryset = DemandOrder.objects.select_related("retailer", "crop").all()
    serializer_class = DemandOrderSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        channel = self.request.query_params.get("channel")
        if channel in [DemandOrder.Channel.B2B, DemandOrder.Channel.COMMUNITY]:
            qs = qs.filter(channel=channel)
        order_status = self.request.query_params.get("status")
        if order_status:
            qs = qs.filter(status=order_status)
        crop_id = self.request.query_params.get("crop_id")
        if crop_id:
            qs = qs.filter(crop_id=crop_id)
        return qs

    @staticmethod
    def compute_b2b_metrics(volume_kg: Decimal, price_per_kg: Decimal = Decimal("30.00")) -> dict:
        """
        Calculates financial and logistics metrics for B2B Wholesale orders.
        - High volume, slim margins (~10%).
        - Direct point-to-point bulk freight.
        - Wholesale institutional clearing.
        """
        vol = Decimal(str(volume_kg))
        price = Decimal(str(price_per_kg))
        gross_inflow = (vol * price).quantize(Decimal("0.01"))
        
        # Farmer gets ~80% of wholesale price
        farmer_rate = (price * Decimal("0.80")).quantize(Decimal("0.01"))
        gross_farmer_payout = (vol * farmer_rate).quantize(Decimal("0.01"))
        farmer_net_upi = gross_farmer_payout
        
        # Bulk freight based on volume tier
        transit_cost = (
            Decimal("2000.00") if vol >= Decimal("800.00")
            else (vol * Decimal("2.00")).quantize(Decimal("0.01"))
        )
        eco_packaging = Decimal("0.00")  # Standard reusable transport crates
        hub_tech_ops = (
            Decimal("1000.00") if vol >= Decimal("800.00")
            else (vol * Decimal("1.00")).quantize(Decimal("0.01"))
        )
        gateway_fee = Decimal("0.00")  # Direct NEFT/RTGS institutional transfer
        supplier_repayment = Decimal("0.00")
        input_deduction = Decimal("0.00")

        total_outflows = (farmer_net_upi + transit_cost + eco_packaging + hub_tech_ops).quantize(Decimal("0.01"))
        net_profit = (gross_inflow - total_outflows).quantize(Decimal("0.01"))
        margin_pct = (
            ((net_profit / gross_inflow) * Decimal("100.0")).quantize(Decimal("0.10"))
            if gross_inflow > Decimal("0.00") else Decimal("0.00")
        )

        return {
            "channel": DemandOrder.Channel.B2B,
            "channel_display": "B2B Wholesale / Institutional Bulk",
            "volume_kg": float(vol),
            "price_per_kg": float(price),
            "gross_inflow": float(gross_inflow),
            "payment_gateway_fee": float(gateway_fee),
            "net_inflow": float(gross_inflow),
            "gross_farmer_payout": float(gross_farmer_payout),
            "input_debt_deduction": float(input_deduction),
            "farmer_net_upi_settlement": float(farmer_net_upi),
            "supplier_input_repayment": float(supplier_repayment),
            "single_truck_transit_cost": float(transit_cost),
            "eco_packaging_cost": float(eco_packaging),
            "hub_and_tech_ops_cost": float(hub_tech_ops),
            "total_platform_operating_costs": float(transit_cost + hub_tech_ops),
            "total_outflows": float(total_outflows),
            "net_platform_profit": float(net_profit),
            "net_profit_margin_pct": float(margin_pct),
            "households": 1,
            "community_name": "Institutional Wholesale Client",
        }

    @staticmethod
    def compute_community_metrics(
        volume_kg: Decimal,
        price_per_kg: Decimal = Decimal("45.00"),
        input_advance: Decimal = None,
        supplier_cost: Decimal = None,
        households: int = 100,
        community_name: str = "Partnered Gated Society Pavilion",
    ) -> dict:
        """
        Calculates financial and logistics metrics for COMMUNITY RWA pre-order drops.
        - Upfront consumer payment inflow (Thursday lock-in).
        - 2% payment gateway fee.
        - AI-graded farmer gross payout (₹26.75/kg baseline).
        - Automated input advance deduction (-₹3,000/ton retail value) cleared to farmer UPI net.
        - Input supplier repayment (-₹2,500/ton wholesale cost).
        - Single-truck direct apartment pavilion bulk delivery (-₹2,500/ton).
        - Eco-friendly community crate packaging (-₹1,500/ton).
        - Rural micro-hub & tech operations (-₹1,000/ton).
        - High net margin (~28.5% net profit: ₹12,850 on ₹45,000 for 1,000 kg).
        """
        vol = Decimal(str(volume_kg))
        price = Decimal(str(price_per_kg))
        gross_inflow = (vol * price).quantize(Decimal("0.01"))

        # 1. Upfront Payment Gateway Fee (2%)
        gateway_fee = (gross_inflow * Decimal("0.02")).quantize(Decimal("0.01"))
        net_inflow = (gross_inflow - gateway_fee).quantize(Decimal("0.01"))

        # 2. Farmer Gross Valuation (₹26.75/kg baseline)
        gross_farmer_rate = Decimal("26.75")
        gross_farmer_payout = (vol * gross_farmer_rate).quantize(Decimal("0.01"))

        # 3. Input Advance Debt Deduction (default ₹3.00/kg retail value)
        input_deduction = (
            Decimal(str(input_advance)) if input_advance is not None and Decimal(str(input_advance)) > Decimal("0.00")
            else (vol * Decimal("3.00")).quantize(Decimal("0.01"))
        )
        farmer_net_upi = max(Decimal("0.00"), gross_farmer_payout - input_deduction).quantize(Decimal("0.01"))

        # 4. Supplier Wholesale Cost Repayment (default ₹2.50/kg)
        supplier_repayment = (
            Decimal(str(supplier_cost)) if supplier_cost is not None and Decimal(str(supplier_cost)) > Decimal("0.00")
            else (vol * Decimal("2.50")).quantize(Decimal("0.01"))
        )

        # 5. Single-Truck Bulk Transit to Apartment Pavilion
        transit_cost = (
            Decimal("2500.00") if vol >= Decimal("800.00")
            else (vol * Decimal("2.50")).quantize(Decimal("0.01"))
        )

        # 6. Eco-Friendly Community Crates & Reusable Packaging
        packaging_cost = (
            Decimal("1500.00") if vol >= Decimal("800.00")
            else (vol * Decimal("1.50")).quantize(Decimal("0.01"))
        )

        # 7. Rural Micro-Hub & Technology Operations
        hub_tech_ops = (
            Decimal("1000.00") if vol >= Decimal("800.00")
            else (vol * Decimal("1.00")).quantize(Decimal("0.01"))
        )

        # Total Outflows & Net Margin
        total_outflows = (
            farmer_net_upi + supplier_repayment + transit_cost + packaging_cost + hub_tech_ops + gateway_fee
        ).quantize(Decimal("0.01"))
        net_platform_profit = (gross_inflow - total_outflows).quantize(Decimal("0.01"))
        net_margin_pct = (
            ((net_platform_profit / gross_inflow) * Decimal("100.0")).quantize(Decimal("0.10"))
            if gross_inflow > Decimal("0.00") else Decimal("0.00")
        )

        return {
            "channel": DemandOrder.Channel.COMMUNITY,
            "channel_display": "Community Weekly Markets (RWA Pre-Order)",
            "volume_kg": float(vol),
            "price_per_kg": float(price),
            "gross_inflow": float(gross_inflow),
            "payment_gateway_fee": float(gateway_fee),
            "net_inflow": float(net_inflow),
            "gross_farmer_payout": float(gross_farmer_payout),
            "input_debt_deduction": float(input_deduction),
            "farmer_net_upi_settlement": float(farmer_net_upi),
            "supplier_input_repayment": float(supplier_repayment),
            "single_truck_transit_cost": float(transit_cost),
            "eco_packaging_cost": float(packaging_cost),
            "hub_and_tech_ops_cost": float(hub_tech_ops),
            "total_platform_operating_costs": float(transit_cost + packaging_cost + hub_tech_ops + gateway_fee + supplier_repayment),
            "total_outflows": float(total_outflows),
            "net_platform_profit": float(net_platform_profit),
            "net_profit_margin_pct": float(net_margin_pct),
            "households": households,
            "community_name": community_name,
        }

    @action(detail=True, methods=["get"], url_path="financial-breakdown")
    def financial_breakdown(self, request, pk=None):
        """
        Returns full financial breakdown for a specific demand order based on its channel.
        """
        order = self.get_object()
        breakdown = order.calculate_financial_breakdown()
        return Response(breakdown, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="channel-analytics")
    def channel_analytics(self, request):
        """
        Returns channel comparison analytics comparing B2B Wholesale vs. Community Markets:
        - Order volume, gross inflow, net farmer payout, operating costs, net profit, margin %.
        """
        orders = self.get_queryset()
        channels = [DemandOrder.Channel.B2B, DemandOrder.Channel.COMMUNITY]
        channel_data = []

        for ch in channels:
            ch_orders = [o for o in orders if o.channel == ch]
            breakdowns = [o.calculate_financial_breakdown() for o in ch_orders]
            
            total_vol = sum(b["volume_kg"] for b in breakdowns)
            total_inflow = sum(b["gross_inflow"] for b in breakdowns)
            total_farmer = sum(b["farmer_net_upi_settlement"] for b in breakdowns)
            total_ops = sum(b["total_platform_operating_costs"] for b in breakdowns)
            total_profit = sum(b["net_platform_profit"] for b in breakdowns)
            avg_margin = (
                (total_profit / total_inflow * 100.0) if total_inflow > 0 else 0.0
            )

            channel_data.append({
                "channel": ch,
                "channel_display": "B2B Wholesale" if ch == DemandOrder.Channel.B2B else "Community Weekly Markets",
                "order_count": len(ch_orders),
                "total_volume_kg": round(total_vol, 2),
                "total_gross_inflow": round(total_inflow, 2),
                "total_farmer_payout": round(total_farmer, 2),
                "total_operating_costs": round(total_ops, 2),
                "total_platform_profit": round(total_profit, 2),
                "avg_profit_margin_pct": round(avg_margin, 2),
            })

        return Response({
            "channels": channel_data,
            "comparison_summary": {
                "b2b_margin_benchmark": "10.0% (Volume/Institutional)",
                "community_margin_benchmark": "28.5% (D2C Direct-to-Society)",
                "operational_advantages": [
                    "Zero gig-delivery rider costs via single-truck bulk pavilion drop",
                    "Zero post-harvest inventory spoilage via Thursday demand lock-in",
                    "Automated working-capital recovery via post_save settlement signal",
                ]
            }
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="simulate-pricing")
    def simulate_pricing(self, request):
        """
        Simulation sandbox: dynamically calculate economics for arbitrary volume, channel, and pricing.
        Payload:
        - channel: 'B2B' or 'COMMUNITY'
        - volume_kg: float (e.g. 1000)
        - price_per_kg: float (e.g. 30 or 45)
        - households: optional int
        - community_name: optional str
        """
        channel = request.data.get("channel", DemandOrder.Channel.B2B).upper()
        try:
            vol = Decimal(str(request.data.get("volume_kg", 1000)))
        except (ValueError, TypeError):
            return Response({"error": "Invalid volume_kg parameter"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            price = Decimal(str(request.data.get("price_per_kg", 45 if channel == DemandOrder.Channel.COMMUNITY else 30)))
        except (ValueError, TypeError):
            return Response({"error": "Invalid price_per_kg parameter"}, status=status.HTTP_400_BAD_REQUEST)

        if channel == DemandOrder.Channel.COMMUNITY:
            input_adv = request.data.get("input_advance_amount")
            supp_cost = request.data.get("supplier_cost_amount")
            households = int(request.data.get("num_households", 100))
            community = request.data.get("community_name", "Partnered Gated Society Pavilion")
            result = self.compute_community_metrics(
                volume_kg=vol,
                price_per_kg=price,
                input_advance=Decimal(str(input_adv)) if input_adv is not None else None,
                supplier_cost=Decimal(str(supp_cost)) if supp_cost is not None else None,
                households=households,
                community_name=community,
            )
        else:
            result = self.compute_b2b_metrics(volume_kg=vol, price_per_kg=price)

        return Response(result, status=status.HTTP_200_OK)
