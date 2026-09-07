"""
Django management command to seed Khet2Kitchen (K2K) Dual-Channel Demand & Supply Chain data.

Creates and verifies:
1. B2B Wholesale Order (e.g. 1,000 kg Tomatoes at Rs. 30/kg for institutional buyers).
2. D2C Community Weekly Drop Order (e.g. 1,000 kg Tomatoes at Rs. 45/kg for 100 gated-society families).

Outputs rich financial models, ASCII flow diagrams, and profitability comparisons.
"""

import sys
from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone

from supply_chain.models import Crop, DemandOrder, MicroHub, User


class Command(BaseCommand):
    help = "Seeds K2K Dual-Channel Supply Chain Demand Orders (B2B Wholesale & D2C Community Drops)"

    def handle(self, *args, **options):
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

        self.stdout.write(self.style.NOTICE("=" * 80))
        self.stdout.write(self.style.NOTICE("[K2K] KHET2KITCHEN DUAL-CHANNEL SUPPLY CHAIN SEEDER"))
        self.stdout.write(self.style.NOTICE("=" * 80))

        # 1. Ensure MicroHub exists
        hub, _ = MicroHub.objects.get_or_create(
            code="HUB-HYD-01",
            defaults={
                "name": "Shamshabad Agritech Micro-Hub",
                "location": "Survey 142, Shamshabad Rural Junction",
                "district": "Rangareddy",
                "state": "Telangana",
                "pincode": "501218",
                "capacity_kg": Decimal("50000.00"),
                "is_active": True,
            },
        )

        # 2. Ensure Crop (Tomato) exists
        crop = Crop.objects.filter(name__icontains="Tomato").first()
        if not crop:
            crop, _ = Crop.objects.get_or_create(
                code="CROP-TOMATO-01",
                defaults={
                    "name": "Roma Field Tomato",
                    "category": Crop.Category.VEGETABLE,
                    "base_price": Decimal("30.00"),
                    "shelf_life_days": 10,
                },
            )

        # 3. Ensure Retailer / Buyer User exists
        b2b_retailer, _ = User.objects.get_or_create(
            identifier="retailer@k2k.org",
            defaults={
                "email": "retailer@k2k.org",
                "phone_number": "+919123456780",
                "first_name": "Suresh",
                "last_name": "Reddy",
                "role": User.Role.RETAILER,
                "address": "Metro Wholesale Mart, Begumpet, Hyderabad",
                "state": "Telangana",
                "pincode": "500016",
            },
        )
        if not b2b_retailer.has_usable_password():
            b2b_retailer.set_password("retailer1234")
            b2b_retailer.save()

        community_coordinator, _ = User.objects.get_or_create(
            identifier="rwa.coordinator@k2k.org",
            defaults={
                "email": "rwa.coordinator@k2k.org",
                "phone_number": "+919849012345",
                "first_name": "Ananya",
                "last_name": "Sharma",
                "role": User.Role.RETAILER,
                "address": "My Home Bhooja RWA Association, Hitec City, Hyderabad",
                "state": "Telangana",
                "pincode": "500081",
            },
        )
        if not community_coordinator.has_usable_password():
            community_coordinator.set_password("community1234")
            community_coordinator.save()

        # 4. Generate B2B Wholesale Demand Order
        # Example: 1,000 kg Tomatoes at Rs. 30/kg
        delivery_date = timezone.now().date() + timedelta(days=2)
        b2b_order, created_b2b = DemandOrder.objects.update_or_create(
            retailer=b2b_retailer,
            crop=crop,
            channel=DemandOrder.Channel.B2B,
            defaults={
                "required_volume_kg": Decimal("1000.00"),
                "target_price_per_kg": Decimal("30.00"),
                "delivery_community_name": "Institutional Wholesale Client",
                "num_households": 1,
                "input_advance_amount": Decimal("0.00"),
                "supplier_cost_amount": Decimal("0.00"),
                "required_date": delivery_date,
                "status": DemandOrder.Status.ALLOCATED,
                "delivery_address": "Metro Cash & Carry Regional Distribution Hub, Shamshabad, Hyderabad",
            },
        )

        # 5. Generate COMMUNITY Pre-Order Demand Order
        # Example: 1,000 kg Tomatoes for 100 gated-society families at Rs. 45/kg
        community_order, created_com = DemandOrder.objects.update_or_create(
            retailer=community_coordinator,
            crop=crop,
            channel=DemandOrder.Channel.COMMUNITY,
            defaults={
                "required_volume_kg": Decimal("1000.00"),
                "target_price_per_kg": Decimal("45.00"),
                "delivery_community_name": "My Home Bhooja Pavilion",
                "num_households": 100,
                "input_advance_amount": Decimal("3000.00"),  # Rs. 3,000 retail value inputs
                "supplier_cost_amount": Decimal("2500.00"),  # Rs. 2,500 wholesale manufacturer procurement
                "required_date": delivery_date,
                "status": DemandOrder.Status.ALLOCATED,
                "delivery_address": "Pavilion Drop Zone, Block 4, My Home Bhooja, Hitec City, Hyderabad - 500081",
            },
        )

        # 6. Calculate Financial Breakdowns
        b2b_metrics = b2b_order.calculate_financial_breakdown()
        com_metrics = community_order.calculate_financial_breakdown()

        # 7. Print Formatted Outputs
        self.stdout.write(self.style.SUCCESS(f"\n[OK] B2B Wholesale Order Ready: {b2b_order.order_id} (Created: {created_b2b})"))
        self.stdout.write(self.style.SUCCESS(f"[OK] Community Pre-Order Ready: {community_order.order_id} (Created: {created_com})"))

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("SCENARIO 1: B2B WHOLESALE MODEL (INSTITUTIONAL BULK)")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Volume: {b2b_metrics['volume_kg']:.0f} kg | Price: Rs. {b2b_metrics['price_per_kg']:.2f}/kg | Channel: {b2b_metrics['channel_display']}")
        self.stdout.write("-" * 80)
        self.stdout.write(f"  Gross Platform Inflow:               Rs. {b2b_metrics['gross_inflow']:>10.2f}")
        self.stdout.write(f"  Farmer Net UPI Payout (~80% rate):  -Rs. {b2b_metrics['farmer_net_upi_settlement']:>10.2f}")
        self.stdout.write(f"  Bulk Freight (Point-to-Point):      -Rs. {b2b_metrics['single_truck_transit_cost']:>10.2f}")
        self.stdout.write(f"  Hub & Tech Infrastructure Ops:      -Rs. {b2b_metrics['hub_and_tech_ops_cost']:>10.2f}")
        self.stdout.write(f"  Packaging (Standard crates return): -Rs. {b2b_metrics['eco_packaging_cost']:>10.2f}")
        self.stdout.write(f"  Payment Gateway Fee:                -Rs. {b2b_metrics['payment_gateway_fee']:>10.2f}")
        self.stdout.write("-" * 80)
        self.stdout.write(f"  Total Platform Outflows:             Rs. {b2b_metrics['total_outflows']:>10.2f}")
        self.stdout.write(self.style.WARNING(
            f"  Net Platform Profit:                 Rs. {b2b_metrics['net_platform_profit']:>10.2f} ({b2b_metrics['net_profit_margin_pct']:.1f}% Net Margin)"
        ))

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("SCENARIO 2: D2C COMMUNITY WEEKLY MARKETS (RWA PRE-ORDER MODEL)")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Volume: {com_metrics['volume_kg']:.0f} kg | Price: Rs. {com_metrics['price_per_kg']:.2f}/kg | Families: {com_metrics['households']} households")
        self.stdout.write(f"Delivery Location: {com_metrics['community_name']}")
        self.stdout.write("-" * 80)

        # ASCII Diagram
        diagram = f"""
    [Community Pre-Orders: Rs. {com_metrics['gross_inflow']:,.0f}]
    ({com_metrics['volume_kg']:,.0f} kg ordered by {com_metrics['households']} families at Rs. {com_metrics['price_per_kg']:.0f}/kg)
    |
    v
    [Payment Gateway: 2% (-Rs. {com_metrics['payment_gateway_fee']:,.0f}) -> Net Inflow: Rs. {com_metrics['net_inflow']:,.0f}]
    |
    +---------------------------+-------------------------------+
    |                                                           |
    [Platform Operating Costs]                [Gross Farmer Payout: Rs. {com_metrics['gross_farmer_payout']:,.0f}]
    * Single-Truck Transit: -Rs. {com_metrics['single_truck_transit_cost']:,.0f}              |
    * Eco-Packaging Crates: -Rs. {com_metrics['eco_packaging_cost']:,.0f}              v
    * Hub & Tech Operations: -Rs. {com_metrics['hub_and_tech_ops_cost']:,.0f}             [Django Settlement Signal]
    * Payment Gateway (2%):  -Rs. {com_metrics['payment_gateway_fee']:,.0f}              |
    * Supplier Repayment:    -Rs. {com_metrics['supplier_input_repayment']:,.0f}              +---------------+---------------+
                                                            v                               v
                                                    [Input Deduction]               [Farmer Net UPI]
                                                       -Rs. {com_metrics['input_debt_deduction']:,.0f}                   Rs. {com_metrics['farmer_net_upi_settlement']:,.0f}
        """
        self.stdout.write(diagram)

        self.stdout.write("-" * 80)
        self.stdout.write("PHASE-BY-PHASE OPERATIONAL & FINANCIAL BREAKDOWN:")
        self.stdout.write("  Phase 1 (Zero-CAC Input Financing):")
        self.stdout.write(f"    * K2K Input Procurement Cost:        Rs. {com_metrics['supplier_input_repayment']:,.2f}")
        self.stdout.write(f"    * In-Kind Advance Retail Value:       Rs. {com_metrics['input_debt_deduction']:,.2f} (Delivered to farmer)")
        self.stdout.write("  Phase 2 (Community Aggregation Inflow):")
        self.stdout.write(f"    * Thursday Pre-Orders (100 families): Rs. {com_metrics['gross_inflow']:,.2f}")
        self.stdout.write(f"    * Upfront Gateway Clearance (98%):    Rs. {com_metrics['net_inflow']:,.2f} (Received pre-harvest)")
        self.stdout.write("  Phase 3 (Predictive Harvest & Settlement):")
        self.stdout.write(f"    * Harvest Directive: Exactly {com_metrics['volume_kg']:,.0f} kg (Zero surplus / Zero waste)")
        self.stdout.write(f"    * Gross Produce Valuation:            Rs. {com_metrics['gross_farmer_payout']:,.2f}")
        self.stdout.write(f"    * Post-Save Signal Deduction:        -Rs. {com_metrics['input_debt_deduction']:,.2f} (Input debt recovered)")
        self.stdout.write(f"    * Direct Farmer UPI Net Wire:         Rs. {com_metrics['farmer_net_upi_settlement']:,.2f}")
        self.stdout.write("  Phase 4 (Point-to-Point Bulk Logistics):")
        self.stdout.write(f"    * Single-Truck Apartment Transit:    -Rs. {com_metrics['single_truck_transit_cost']:,.2f} (Zero gig-riders)")
        self.stdout.write(f"    * Eco-Friendly Reusable Packaging:   -Rs. {com_metrics['eco_packaging_cost']:,.2f}")
        self.stdout.write(f"    * Micro-Hub & Platform Tech Ops:     -Rs. {com_metrics['hub_and_tech_ops_cost']:,.2f}")
        self.stdout.write(f"    * Input Supplier Repayment:          -Rs. {com_metrics['supplier_input_repayment']:,.2f}")
        self.stdout.write("-" * 80)
        self.stdout.write(f"  Gross Inflow (Consumer Payments):       +Rs. {com_metrics['gross_inflow']:>10.2f}")
        self.stdout.write(f"  Net Payout to Farmer:                   -Rs. {com_metrics['farmer_net_upi_settlement']:>10.2f}")
        self.stdout.write(f"  Repayment to Input Supplier:            -Rs. {com_metrics['supplier_input_repayment']:>10.2f}")
        self.stdout.write(f"  Single-Truck Bulk Transit:              -Rs. {com_metrics['single_truck_transit_cost']:>10.2f}")
        self.stdout.write(f"  Packaging & Crates:                     -Rs. {com_metrics['eco_packaging_cost']:>10.2f}")
        self.stdout.write(f"  Tech, Hub Operations & Payment Gateway: -Rs. {com_metrics['hub_and_tech_ops_cost'] + com_metrics['payment_gateway_fee']:>10.2f}")
        self.stdout.write("-" * 80)
        self.stdout.write(self.style.SUCCESS(
            f"  NET PLATFORM PROFIT:                    Rs. {com_metrics['net_platform_profit']:>10.2f} (~{com_metrics['net_profit_margin_pct']:.1f}% NET MARGIN)"
        ))
        self.stdout.write("=" * 80)

        # Comparative Summary Table
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("DUAL-MODEL COMPARATIVE PROFITABILITY MATRIX")
        self.stdout.write("=" * 80)
        self.stdout.write(f"{'Metric':<32} | {'B2B Wholesale':<20} | {'Community Drop (RWA)':<20}")
        self.stdout.write("-" * 80)
        self.stdout.write(f"{'Volume (kg)':<32} | {b2b_metrics['volume_kg']:<20.0f} | {com_metrics['volume_kg']:<20.0f}")
        self.stdout.write(f"{'Consumer/Client Price (/kg)':<32} | Rs. {b2b_metrics['price_per_kg']:<16.2f} | Rs. {com_metrics['price_per_kg']:<16.2f}")
        self.stdout.write(f"{'Gross Revenue':<32} | Rs. {b2b_metrics['gross_inflow']:<16.2f} | Rs. {com_metrics['gross_inflow']:<16.2f}")
        self.stdout.write(f"{'Farmer Net Settlement':<32} | Rs. {b2b_metrics['farmer_net_upi_settlement']:<16.2f} | Rs. {com_metrics['farmer_net_upi_settlement']:<16.2f}")
        self.stdout.write(f"{'Transit & Packaging':<32} | Rs. {b2b_metrics['single_truck_transit_cost'] + b2b_metrics['eco_packaging_cost']:<16.2f} | Rs. {com_metrics['single_truck_transit_cost'] + com_metrics['eco_packaging_cost']:<16.2f}")
        self.stdout.write(f"{'Hub, Gateway & Supplier':<32} | Rs. {b2b_metrics['hub_and_tech_ops_cost'] + b2b_metrics['payment_gateway_fee']:<16.2f} | Rs. {com_metrics['hub_and_tech_ops_cost'] + com_metrics['payment_gateway_fee'] + com_metrics['supplier_input_repayment']:<16.2f}")
        self.stdout.write("-" * 80)
        self.stdout.write(f"{'Net Platform Profit':<32} | Rs. {b2b_metrics['net_platform_profit']:<16.2f} | Rs. {com_metrics['net_platform_profit']:<16.2f}")
        self.stdout.write(f"{'Net Profit Margin':<32} | {b2b_metrics['net_profit_margin_pct']:<19.1f}% | {com_metrics['net_profit_margin_pct']:<19.1f}%")
        self.stdout.write("=" * 80 + "\n")
