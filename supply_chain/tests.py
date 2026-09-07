"""
Tests for Khet2Kitchen (K2K) Supply Chain Dual-Pricing & Fulfillment Models.
"""

from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from rest_framework.test import APIClient

from supply_chain.models import Crop, DemandOrder, MicroHub, User


class SupplyChainDualPricingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.hub = MicroHub.objects.create(
            name="Test Micro-Hub",
            code="HUB-TEST-01",
            location="Test Location",
            district="Hyderabad",
            state="Telangana",
            pincode="500001",
            capacity_kg=Decimal("10000.00"),
        )
        self.crop = Crop.objects.create(
            code="CROP-TOMATO-TEST",
            name="Test Tomato",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("30.00"),
            shelf_life_days=10,
        )
        self.retailer = User.objects.create_user(
            identifier="test.retailer@k2k.org",
            role=User.Role.RETAILER,
            first_name="Retailer",
            last_name="One",
        )

    def test_b2b_demand_order_financial_breakdown(self):
        """Test B2B wholesale calculation for 1,000 kg at Rs. 30/kg."""
        order = DemandOrder.objects.create(
            retailer=self.retailer,
            crop=self.crop,
            channel=DemandOrder.Channel.B2B,
            required_volume_kg=Decimal("1000.00"),
            target_price_per_kg=Decimal("30.00"),
            required_date=timezone.now().date() + timedelta(days=2),
        )
        breakdown = order.calculate_financial_breakdown()

        self.assertEqual(breakdown["channel"], DemandOrder.Channel.B2B)
        self.assertEqual(breakdown["gross_inflow"], 30000.0)
        self.assertEqual(breakdown["farmer_net_upi_settlement"], 24000.0)
        self.assertEqual(breakdown["single_truck_transit_cost"], 2000.0)
        self.assertEqual(breakdown["hub_and_tech_ops_cost"], 1000.0)
        self.assertEqual(breakdown["total_outflows"], 27000.0)
        self.assertEqual(breakdown["net_platform_profit"], 3000.0)
        self.assertAlmostEqual(breakdown["net_profit_margin_pct"], 10.0, places=1)

    def test_community_demand_order_financial_breakdown(self):
        """Test Community RWA pre-order calculation for 1,000 kg at Rs. 45/kg (yielding ~28.5% net margin)."""
        order = DemandOrder.objects.create(
            retailer=self.retailer,
            crop=self.crop,
            channel=DemandOrder.Channel.COMMUNITY,
            required_volume_kg=Decimal("1000.00"),
            target_price_per_kg=Decimal("45.00"),
            delivery_community_name="My Home Bhooja Pavilion",
            num_households=100,
            input_advance_amount=Decimal("3000.00"),
            supplier_cost_amount=Decimal("2500.00"),
            required_date=timezone.now().date() + timedelta(days=2),
        )
        breakdown = order.calculate_financial_breakdown()

        self.assertEqual(breakdown["channel"], DemandOrder.Channel.COMMUNITY)
        self.assertEqual(breakdown["gross_inflow"], 45000.0)
        self.assertEqual(breakdown["payment_gateway_fee"], 900.0)
        self.assertEqual(breakdown["gross_farmer_payout"], 26750.0)
        self.assertEqual(breakdown["input_debt_deduction"], 3000.0)
        self.assertEqual(breakdown["farmer_net_upi_settlement"], 23750.0)
        self.assertEqual(breakdown["supplier_input_repayment"], 2500.0)
        self.assertEqual(breakdown["single_truck_transit_cost"], 2500.0)
        self.assertEqual(breakdown["eco_packaging_cost"], 1500.0)
        self.assertEqual(breakdown["hub_and_tech_ops_cost"], 1000.0)
        self.assertEqual(breakdown["total_outflows"], 32150.0)
        self.assertEqual(breakdown["net_platform_profit"], 12850.0)
        self.assertAlmostEqual(breakdown["net_profit_margin_pct"], 28.56, places=1)

    def test_demand_order_api_endpoints(self):
        """Test DRF endpoints: list, filter, breakdown, channel-analytics, and simulate-pricing."""
        b2b_order = DemandOrder.objects.create(
            retailer=self.retailer,
            crop=self.crop,
            channel=DemandOrder.Channel.B2B,
            required_volume_kg=Decimal("1000.00"),
            target_price_per_kg=Decimal("30.00"),
            required_date=timezone.now().date() + timedelta(days=1),
        )
        com_order = DemandOrder.objects.create(
            retailer=self.retailer,
            crop=self.crop,
            channel=DemandOrder.Channel.COMMUNITY,
            required_volume_kg=Decimal("1000.00"),
            target_price_per_kg=Decimal("45.00"),
            num_households=100,
            required_date=timezone.now().date() + timedelta(days=2),
        )

        # 1. List demand orders
        res = self.client.get("/api/supply-chain/demand-orders/")
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.json()), 2)

        # 2. Filter by channel
        res_com = self.client.get("/api/supply-chain/demand-orders/?channel=COMMUNITY")
        self.assertEqual(res_com.status_code, 200)
        for item in res_com.json():
            self.assertEqual(item["channel"], DemandOrder.Channel.COMMUNITY)

        # 3. Financial Breakdown detail endpoint
        res_fb = self.client.get(f"/api/supply-chain/demand-orders/{com_order.pk}/financial-breakdown/")
        self.assertEqual(res_fb.status_code, 200)
        self.assertEqual(res_fb.json()["net_platform_profit"], 12850.0)

        # 4. Channel Analytics endpoint
        res_ca = self.client.get("/api/supply-chain/demand-orders/channel-analytics/")
        self.assertEqual(res_ca.status_code, 200)
        self.assertIn("channels", res_ca.json())
        self.assertIn("comparison_summary", res_ca.json())

        # 5. Simulate Pricing Sandbox endpoint
        sim_payload = {
            "channel": "COMMUNITY",
            "volume_kg": 1000,
            "price_per_kg": 45,
            "num_households": 100,
        }
        res_sim = self.client.post("/api/supply-chain/demand-orders/simulate-pricing/", sim_payload, format="json")
        self.assertEqual(res_sim.status_code, 200)
        self.assertEqual(res_sim.json()["net_platform_profit"], 12850.0)

    def test_seed_k2k_data_management_command(self):
        """Test management command execution."""
        call_command("seed_k2k_data")
        self.assertTrue(DemandOrder.objects.filter(channel=DemandOrder.Channel.B2B).exists())
        self.assertTrue(DemandOrder.objects.filter(channel=DemandOrder.Channel.COMMUNITY).exists())
