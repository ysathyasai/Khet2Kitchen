import base64
from decimal import Decimal
from django.contrib.auth import authenticate
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from unittest.mock import MagicMock, patch
from core.models import (
    Batch,
    ConsumerFeedback,
    ConsumerOrder,
    ConsumerOrderItem,
    Crop,
    DemandOrder,
    FarmerWallet,
    HarvestSchedule,
    InputSupply,
    Kit,
    KitItem,
    MicroHub,
    RecipeCombo,
    RetailerBulkOrder,
    User,
    WalletTransaction,
)
from core.ai_recipe import generate_recipe_combo

from core.services import (
    allocate_supply_to_order,
    fetch_real_weather,
    generate_agronomic_advisory,
    generate_transparent_pricing_breakdown,
    get_batch_traceability,
    get_coordinates_from_pincode,
    mock_dynamic_route,
    predict_demand,
    process_batch_payout,
)
from core.vision import analyze_crop_image
from core.voice_services import (
    generate_speech,
    process_intent_with_gemini,
    transcribe_audio,
)


class UserModelTests(TestCase):
    """Tests custom User model and RBAC constraints."""

    def test_create_farmer_user(self):
        farmer = User.objects.create_user(
            phone_number="+919876543210",
            role=User.Role.FARMER,
            first_name="Ramesh",
            last_name="Kumar",
        )
        self.assertEqual(farmer.identifier, "+919876543210")
        self.assertEqual(farmer.role, User.Role.FARMER)
        self.assertTrue(farmer.is_farmer)
        self.assertFalse(farmer.is_retailer)
        self.assertEqual(farmer.get_dashboard_url(), reverse("farmer_dashboard"))

    def test_create_retailer_user(self):
        retailer = User.objects.create_user(
            email="retailer@freshbazaar.in",
            password="SecurePassword123!",
            role=User.Role.RETAILER,
            first_name="Ananya",
            last_name="Sharma",
        )
        self.assertEqual(retailer.identifier, "retailer@freshbazaar.in")
        self.assertEqual(retailer.role, User.Role.RETAILER)
        self.assertTrue(retailer.is_retailer)
        self.assertTrue(retailer.check_password("SecurePassword123!"))
        self.assertEqual(retailer.get_dashboard_url(), reverse("retailer_dashboard"))

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            identifier="admin@khet2kitchen.com",
            password="SuperAdminSecret456!",
        )
        self.assertEqual(admin.role, User.Role.ADMIN)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_admin_user)
        self.assertEqual(admin.get_dashboard_url(), reverse("admin_command_dashboard"))

    def test_farmer_validation_requires_phone(self):
        farmer = User(role=User.Role.FARMER, email="test@farmer.com")
        with self.assertRaises(ValidationError):
            farmer.clean()

    def test_retailer_validation_requires_email(self):
        retailer = User(role=User.Role.RETAILER, phone_number="+919999988888")
        with self.assertRaises(ValidationError):
            retailer.clean()


class DualAuthBackendTests(TestCase):
    """Tests authentication backend for dual mobile/email log-in."""

    def setUp(self):
        self.farmer = User.objects.create_user(
            phone_number="+919876543210",
            role=User.Role.FARMER,
            password="FarmerSecretPassword1!",
        )
        self.retailer = User.objects.create_user(
            email="retailer@procure.com",
            role=User.Role.RETAILER,
            password="RetailerSecretPassword2!",
        )

    def test_authenticate_farmer_via_mobile(self):
        user = authenticate(username="+919876543210", password="FarmerSecretPassword1!")
        self.assertIsNotNone(user)
        self.assertEqual(user.pk, self.farmer.pk)

    def test_authenticate_retailer_via_email(self):
        user = authenticate(username="retailer@procure.com", password="RetailerSecretPassword2!")
        self.assertIsNotNone(user)
        self.assertEqual(user.pk, self.retailer.pk)

    def test_authenticate_invalid_credentials(self):
        user = authenticate(username="+919876543210", password="WrongPassword!")
        self.assertIsNone(user)


class DomainModelsTests(TestCase):
    """Tests MicroHub, Crop, Batch, and DemandOrder business logic."""

    def setUp(self):
        self.farmer = User.objects.create_user(
            phone_number="+919876543211",
            role=User.Role.FARMER,
            first_name="Suresh",
            last_name="Patel",
        )
        self.retailer = User.objects.create_user(
            email="buyer@quickmart.in",
            password="RetailerPassword!",
            role=User.Role.RETAILER,
            first_name="Vikram",
        )
        self.hub = MicroHub.objects.create(
            name="Nashik Agro Cluster Hub #1",
            code="HUB-NSK-01",
            location="Gat No. 45, Dindori Road",
            district="Nashik",
            state="Maharashtra",
            pincode="422004",
            capacity_kg=Decimal("10000.00"),
        )
        self.crop = Crop.objects.create(
            name="Red Onion (Nashik Special)",
            code="CROP-ONION-01",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("25.00"),
            shelf_life_days=30,
        )

    def test_micro_hub_capacity_calculations(self):
        self.assertEqual(self.hub.get_available_capacity(), Decimal("10000.00"))
        self.assertTrue(self.hub.can_accommodate(Decimal("5000.00")))
        self.assertFalse(self.hub.can_accommodate(Decimal("15000.00")))

        # Create batch stored in hub
        Batch.objects.create(
            farmer=self.farmer,
            hub=self.hub,
            crop=self.crop,
            volume_kg=Decimal("3000.00"),
            ai_grade=Batch.Grade.GRADE_A,
            ai_confidence_score=Decimal("96.50"),
        )
        self.assertEqual(self.hub.get_available_capacity(), Decimal("7000.00"))

    def test_crop_grade_pricing(self):
        self.assertEqual(self.crop.calculate_grade_price(Batch.Grade.GRADE_A), Decimal("30.00"))
        self.assertEqual(self.crop.calculate_grade_price(Batch.Grade.GRADE_B), Decimal("25.00"))
        self.assertEqual(self.crop.calculate_grade_price(Batch.Grade.GRADE_C), Decimal("18.75"))

    def test_batch_auto_id_and_valuation(self):
        batch = Batch.objects.create(
            farmer=self.farmer,
            hub=self.hub,
            crop=self.crop,
            volume_kg=Decimal("100.00"),
            ai_grade=Batch.Grade.GRADE_A,
            ai_confidence_score=Decimal("98.20"),
        )
        self.assertTrue(batch.batch_id.startswith("K2K-BTH-"))
        self.assertEqual(batch.calculate_valuation(), Decimal("3000.00"))

    def test_demand_order_creation_and_estimated_cost(self):
        order = DemandOrder.objects.create(
            retailer=self.retailer,
            crop=self.crop,
            required_volume_kg=Decimal("500.00"),
            required_date=timezone.now().date(),
        )
        self.assertTrue(order.order_id.startswith("K2K-ORD-"))
        self.assertEqual(order.calculate_estimated_cost(), Decimal("12500.00"))


class IntelligenceEngineServiceTests(TestCase):
    """Tests K2K Intelligence Engine services (Demand Prediction, Allocation, Pricing)."""

    def setUp(self):
        self.farmer = User.objects.create_user(
            phone_number="+919876543230",
            role=User.Role.FARMER,
            first_name="Kisan",
            last_name="Bhai",
        )
        self.retailer = User.objects.create_user(
            email="retailer@freshchain.in",
            role=User.Role.RETAILER,
            password="RetailerPassword!",
        )
        self.hub = MicroHub.objects.create(
            name="Pune Hub Alpha",
            code="HUB-PUN-01",
            location="Market Yard",
            district="Pune",
            state="Maharashtra",
            pincode="411037",
            capacity_kg=Decimal("20000.00"),
        )
        self.crop = Crop.objects.create(
            name="Ratnagiri Alphonso Mango",
            code="CROP-MANGO-01",
            category=Crop.Category.FRUIT,
            base_price=Decimal("150.00"),
            shelf_life_days=12,
        )

    # 1. predict_demand tests
    def test_predict_demand_valid_crop(self):
        forecast = predict_demand(self.crop.id)
        self.assertEqual(forecast["crop_id"], self.crop.id)
        self.assertEqual(forecast["crop_name"], "Ratnagiri Alphonso Mango")
        self.assertGreater(forecast["predicted_volume_kg"], Decimal("0.00"))
        self.assertGreater(forecast["expected_price_per_kg"], Decimal("0.00"))
        self.assertGreaterEqual(forecast["confidence_score"], Decimal("80.00"))
        self.assertIn("trend", forecast)
        self.assertIn("rationale", forecast)

    def test_predict_demand_invalid_crop_raises_error(self):
        with self.assertRaises(ObjectDoesNotExist):
            predict_demand(99999)

    # 2. generate_transparent_pricing_breakdown tests
    def test_pricing_breakdown_grade_a(self):
        # 100 kg * 150 base price = 15000 base value
        # Grade A (+20%) = +3000 -> gross = 18000
        # Logistics (100 * 1.50) = 150
        # Final payout = 18000 - 150 = 17850
        batch_a = Batch.objects.create(
            farmer=self.farmer,
            hub=self.hub,
            crop=self.crop,
            volume_kg=Decimal("100.00"),
            ai_grade=Batch.Grade.GRADE_A,
            ai_confidence_score=Decimal("98.00"),
        )
        breakdown = generate_transparent_pricing_breakdown(batch_a)
        self.assertEqual(breakdown["base_value"], Decimal("15000.00"))
        self.assertEqual(breakdown["grade_modifier_pct"], 20)
        self.assertEqual(breakdown["grade_modifier_amount"], Decimal("3000.00"))
        self.assertEqual(breakdown["gross_value"], Decimal("18000.00"))
        self.assertEqual(breakdown["logistics_deduction"], Decimal("150.00"))
        self.assertEqual(breakdown["final_payout"], Decimal("17850.00"))
        self.assertEqual(breakdown["effective_price_per_kg"], Decimal("178.50"))
        self.assertGreater(breakdown["disintermediation_gain"], Decimal("0.00"))

    def test_pricing_breakdown_grade_c(self):
        # 100 kg * 150 = 15000
        # Grade C (-25%) = -3750 -> gross = 11250
        # Logistics = 150
        # Final payout = 11250 - 150 = 11100
        batch_c = Batch.objects.create(
            farmer=self.farmer,
            hub=self.hub,
            crop=self.crop,
            volume_kg=Decimal("100.00"),
            ai_grade=Batch.Grade.GRADE_C,
            ai_confidence_score=Decimal("89.00"),
        )
        breakdown = generate_transparent_pricing_breakdown(batch_c)
        self.assertEqual(breakdown["grade_modifier_pct"], -25)
        self.assertEqual(breakdown["final_payout"], Decimal("11100.00"))

    # 3. allocate_supply_to_order tests
    def test_allocate_supply_full_fulfillment(self):
        # Available batches: 600 kg and 400 kg
        Batch.objects.create(
            farmer=self.farmer,
            hub=self.hub,
            crop=self.crop,
            volume_kg=Decimal("600.00"),
            ai_grade=Batch.Grade.GRADE_A,
            ai_confidence_score=Decimal("95.00"),
            status=Batch.Status.QUALITY_INSPECTED,
        )
        Batch.objects.create(
            farmer=self.farmer,
            hub=self.hub,
            crop=self.crop,
            volume_kg=Decimal("400.00"),
            ai_grade=Batch.Grade.GRADE_B,
            ai_confidence_score=Decimal("91.00"),
            status=Batch.Status.QUALITY_INSPECTED,
        )

        order = DemandOrder.objects.create(
            retailer=self.retailer,
            crop=self.crop,
            required_volume_kg=Decimal("800.00"),
            required_date=timezone.now().date(),
        )

        result = allocate_supply_to_order(order)
        self.assertTrue(result["is_fully_fulfilled"])
        self.assertEqual(result["total_allocated_kg"], Decimal("800.00"))
        self.assertEqual(result["remaining_required_kg"], Decimal("0.00"))
        
        order.refresh_from_db()
        self.assertEqual(order.status, DemandOrder.Status.FULFILLED)


class RBACDashboardViewTests(TestCase):
    """Tests role-based routing, views, and service layer template integration."""

    def setUp(self):
        self.client = Client()
        self.farmer = User.objects.create_user(
            phone_number="+919876543220",
            role=User.Role.FARMER,
            password="TestPassword1!",
        )
        self.retailer = User.objects.create_user(
            email="retailer@store.com",
            role=User.Role.RETAILER,
            password="TestPassword2!",
        )
        self.admin_user = User.objects.create_superuser(
            identifier="admin@k2k.org",
            password="AdminPassword3!",
        )
        self.hub = MicroHub.objects.create(
            name="Test Hub",
            code="HUB-TEST-01",
            location="Test Road",
            district="Nashik",
            state="Maharashtra",
            pincode="422001",
            capacity_kg=Decimal("15000.00"),
        )
        self.crop = Crop.objects.create(
            name="Test Crop",
            code="CROP-TEST-01",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("20.00"),
            shelf_life_days=15,
        )

    def test_unauthenticated_user_redirected_to_login(self):
        response = self.client.get(reverse("dashboard_dispatch"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_farmer_dispatcher_routes_to_farmer_dashboard(self):
        self.client.force_login(self.farmer)
        response = self.client.get(reverse("dashboard_dispatch"))
        self.assertRedirects(response, reverse("farmer_dashboard"))

    def test_farmer_dashboard_renders_pricing_breakdown(self):
        Batch.objects.create(
            farmer=self.farmer,
            hub=self.hub,
            crop=self.crop,
            volume_kg=Decimal("200.00"),
            ai_grade=Batch.Grade.GRADE_A,
            ai_confidence_score=Decimal("97.50"),
            status=Batch.Status.QUALITY_INSPECTED,
        )
        self.client.force_login(self.farmer)
        response = self.client.get(reverse("farmer_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Transparent Payout & Disintermediation Breakdown")
        self.assertContains(response, "Grade A")

    def test_retailer_dashboard_renders_ai_recommendations(self):
        self.client.force_login(self.retailer)
        response = self.client.get(reverse("retailer_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI Demand Forecast & Recommended Pre-Orders")
        self.assertContains(response, "Model Confidence:")

    def test_retailer_can_trigger_auto_match_allocation(self):
        Batch.objects.create(
            farmer=self.farmer,
            hub=self.hub,
            crop=self.crop,
            volume_kg=Decimal("500.00"),
            ai_grade=Batch.Grade.GRADE_B,
            ai_confidence_score=Decimal("92.00"),
            status=Batch.Status.QUALITY_INSPECTED,
        )
        order = DemandOrder.objects.create(
            retailer=self.retailer,
            crop=self.crop,
            required_volume_kg=Decimal("300.00"),
            required_date=timezone.now().date(),
        )
        self.client.force_login(self.retailer)
        response = self.client.post(reverse("allocate_order", args=[order.order_id]))
        self.assertRedirects(response, reverse("retailer_dashboard"))
        order.refresh_from_db()
        self.assertEqual(order.status, DemandOrder.Status.FULFILLED)

    def test_farmer_denied_access_to_retailer_dashboard(self):
        self.client.force_login(self.farmer)
        response = self.client.get(reverse("retailer_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_command_dashboard(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin_command_dashboard"))
        self.assertEqual(response.status_code, 200)


class VisionEngineTests(TestCase):
    """Tests Computer Vision quality inspection simulation."""

    def setUp(self):
        self.crop = Crop.objects.create(
            name="Nashik Red Onion",
            code="CROP-ONION-TEST",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("30.00"),
            shelf_life_days=25,
        )

    def test_analyze_crop_image_valid_output(self):
        mock_file = SimpleUploadedFile("onion_sample.jpg", b"fake_image_binary_data", content_type="image/jpeg")
        report = analyze_crop_image(mock_file, self.crop)

        self.assertIn(report["grade"], [Batch.Grade.GRADE_A, Batch.Grade.GRADE_B, Batch.Grade.GRADE_C])
        self.assertGreaterEqual(report["confidence_score"], Decimal("80.00"))
        self.assertLessEqual(report["confidence_score"], Decimal("100.00"))
        self.assertGreater(report["defect_percentage"], Decimal("0.00"))
        self.assertIn("color_uniformity_pct", report["metrics"])
        self.assertTrue(len(report["rationale"]) > 10)

    def test_analyze_crop_image_invalid_crop_raises_error(self):
        mock_file = SimpleUploadedFile("sample.jpg", b"dummy", content_type="image/jpeg")
        with self.assertRaises(ObjectDoesNotExist):
            analyze_crop_image(mock_file, 99999)


class APIGradingEndpointTests(TestCase):
    """Tests the /api/grade-batch/ endpoint."""

    def setUp(self):
        self.client = Client()
        self.crop = Crop.objects.create(
            name="Roma Tomato",
            code="CROP-TOMATO-TEST",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("25.00"),
            shelf_life_days=10,
        )

    def test_api_grade_batch_missing_image_returns_400(self):
        response = self.client.post(reverse("api_grade_batch"), data={"crop_id": self.crop.id})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("Produce image file is required", data["error"])

    def test_api_grade_batch_missing_crop_returns_400(self):
        mock_file = SimpleUploadedFile("tomato.png", b"data", content_type="image/png")
        response = self.client.post(reverse("api_grade_batch"), data={"image": mock_file})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])

    def test_api_grade_batch_invalid_crop_returns_404(self):
        mock_file = SimpleUploadedFile("tomato.png", b"data", content_type="image/png")
        response = self.client.post(reverse("api_grade_batch"), data={"image": mock_file, "crop_id": 99999})
        self.assertEqual(response.status_code, 404)

    def test_api_grade_batch_successful_grading(self):
        mock_file = SimpleUploadedFile("tomato.jpg", b"synthetic_tomato_pixels", content_type="image/jpeg")
        response = self.client.post(
            reverse("api_grade_batch"),
            data={
                "image": mock_file,
                "crop_id": self.crop.id,
                "volume_kg": "250.00",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["crop_name"], "Roma Tomato")
        self.assertEqual(data["volume_kg"], 250.0)
        self.assertIn(data["grade"], ["A", "B", "C"])
        self.assertIn("financial_breakdown", data)
        self.assertGreater(data["financial_breakdown"]["final_payout"], 0)
        self.assertGreater(data["financial_breakdown"]["disintermediation_gain"], 0)


class FarmerWalletModelTests(TestCase):
    """Tests FarmerWallet and WalletTransaction ledger operations."""

    def setUp(self):
        self.farmer = User.objects.create_user(
            phone_number="+919876543277",
            role=User.Role.FARMER,
            first_name="Raju",
            last_name="Shetty",
        )
        self.wallet = FarmerWallet.objects.create(farmer=self.farmer)

    def test_default_wallet_balance_is_zero(self):
        self.assertEqual(self.wallet.current_balance, Decimal("0.00"))

    def test_credit_increases_balance_and_creates_transaction(self):
        tx = self.wallet.credit(Decimal("1500.50"), "Harvest payout")
        self.assertEqual(self.wallet.current_balance, Decimal("1500.50"))
        self.assertEqual(tx.amount, Decimal("1500.50"))
        self.assertEqual(tx.transaction_type, WalletTransaction.TransactionType.CREDIT)
        self.assertEqual(tx.description, "Harvest payout")
        self.assertEqual(self.wallet.transactions.count(), 1)

    def test_debit_decreases_balance_and_creates_transaction(self):
        self.wallet.credit(Decimal("2000.00"), "Initial deposit")
        tx = self.wallet.debit(Decimal("800.00"), "Withdrawal to bank")
        self.assertEqual(self.wallet.current_balance, Decimal("1200.00"))
        self.assertEqual(tx.amount, Decimal("800.00"))
        self.assertEqual(tx.transaction_type, WalletTransaction.TransactionType.DEBIT)
        self.assertEqual(self.wallet.transactions.count(), 2)

    def test_debit_exceeding_balance_raises_validation_error(self):
        self.wallet.credit(Decimal("500.00"), "Small credit")
        with self.assertRaises(ValidationError) as ctx:
            self.wallet.debit(Decimal("600.00"), "Overdraft attempt")
        self.assertIn("Insufficient wallet balance", str(ctx.exception))
        self.assertEqual(self.wallet.current_balance, Decimal("500.00"))

    def test_invalid_negative_or_zero_amounts(self):
        with self.assertRaises(ValidationError):
            self.wallet.credit(Decimal("-10.00"), "Invalid")
        with self.assertRaises(ValidationError):
            self.wallet.credit(Decimal("0.00"), "Zero")
        with self.assertRaises(ValidationError):
            self.wallet.debit(Decimal("-50.00"), "Invalid debit")


class HarvestScheduleModelTests(TestCase):
    """Tests HarvestSchedule creation, choices, and helpers."""

    def setUp(self):
        self.farmer = User.objects.create_user(
            phone_number="+919876543288",
            role=User.Role.FARMER,
        )
        self.crop = Crop.objects.create(
            name="Green Bell Pepper",
            code="CROP-PEPPER-01",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("40.00"),
            shelf_life_days=10,
        )

    def test_create_harvest_schedule(self):
        schedule = HarvestSchedule.objects.create(
            farmer=self.farmer,
            crop=self.crop,
            recommended_date=timezone.now().date(),
            target_volume_kg=Decimal("750.00"),
            notes="Morning plucking advised.",
        )
        self.assertEqual(schedule.status, HarvestSchedule.Status.PENDING)
        self.assertEqual(schedule.target_volume_kg, Decimal("750.00"))
        self.assertFalse(schedule.is_overdue)


class BatchPayoutServiceTests(TestCase):
    """Tests process_batch_payout service and automated wallet crediting."""

    def setUp(self):
        self.farmer = User.objects.create_user(
            phone_number="+919876543299",
            role=User.Role.FARMER,
        )
        self.hub = MicroHub.objects.create(
            name="Hub Beta",
            code="HUB-BETA-01",
            location="Beta Road",
            district="Kolar",
            state="Karnataka",
            pincode="563101",
            capacity_kg=Decimal("10000.00"),
        )
        self.crop = Crop.objects.create(
            name="Carrot",
            code="CROP-CARROT-01",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("30.00"),
            shelf_life_days=20,
        )

    def test_process_batch_payout_credits_wallet(self):
        # 100 kg * 30 base = 3000
        # Grade A (+20%) = +600 -> gross = 3600
        # Logistics (100 * 1.50) = 150
        # Payout = 3450
        batch = Batch.objects.create(
            farmer=self.farmer,
            hub=self.hub,
            crop=self.crop,
            volume_kg=Decimal("100.00"),
            ai_grade=Batch.Grade.GRADE_A,
            ai_confidence_score=Decimal("98.00"),
            status=Batch.Status.QUALITY_INSPECTED,
        )
        result = process_batch_payout(batch)

        self.assertEqual(result["credited_amount"], Decimal("3450.00"))
        self.assertEqual(result["new_wallet_balance"], Decimal("3450.00"))

        wallet = FarmerWallet.objects.get(farmer=self.farmer)
        self.assertEqual(wallet.current_balance, Decimal("3450.00"))
        self.assertEqual(wallet.transactions.count(), 1)
        tx = wallet.transactions.first()
        self.assertEqual(tx.amount, Decimal("3450.00"))
        self.assertIn(batch.batch_id, tx.description)


class BatchTraceabilityServiceTests(TestCase):
    """Tests get_batch_traceability service generating 4-stage provenance."""

    def setUp(self):
        self.farmer = User.objects.create_user(
            phone_number="+919876543266",
            role=User.Role.FARMER,
            first_name="Harish",
            last_name="Gowda",
            address="Kolar Gold Fields, Rural",
        )
        self.hub = MicroHub.objects.create(
            name="Kolar Micro-Hub",
            code="HUB-KLR-01",
            location="NH-75 Bypass",
            district="Kolar",
            state="Karnataka",
            pincode="563101",
            capacity_kg=Decimal("25000.00"),
        )
        self.crop = Crop.objects.create(
            name="Capsicum Green",
            code="CROP-CAP-01",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("45.00"),
            shelf_life_days=12,
        )
        self.batch = Batch.objects.create(
            farmer=self.farmer,
            hub=self.hub,
            crop=self.crop,
            volume_kg=Decimal("500.00"),
            ai_grade=Batch.Grade.GRADE_A,
            ai_confidence_score=Decimal("96.40"),
            status=Batch.Status.QUALITY_INSPECTED,
        )

    def test_get_batch_traceability_valid_structure(self):
        trace = get_batch_traceability(self.batch.batch_id)

        self.assertEqual(trace["batch_id"], self.batch.batch_id)
        self.assertEqual(trace["crop_name"], "Capsicum Green")
        self.assertEqual(trace["volume_kg"], 500.0)

        # Stage 1: Farm Origin
        self.assertIn("farm_origin", trace)
        self.assertEqual(trace["farm_origin"]["farmer_name"], "Harish Gowda")

        # Stage 2: Hub Inspection
        self.assertIn("hub_inspection", trace)
        self.assertEqual(trace["hub_inspection"]["hub_name"], "Kolar Micro-Hub")
        self.assertEqual(trace["hub_inspection"]["ai_grade"], "A")

        # Stage 3: Financial Settlement
        self.assertIn("financial_settlement", trace)
        self.assertGreater(trace["financial_settlement"]["net_payout"], 0)
        self.assertGreater(trace["financial_settlement"]["disintermediation_saving"], 0)

        # Stage 4: Logistics
        self.assertIn("logistics_cold_chain", trace)
        self.assertIn("4°C", trace["logistics_cold_chain"]["cold_chain_temp"])

    def test_get_batch_traceability_invalid_batch_raises_404(self):
        with self.assertRaises((ObjectDoesNotExist, Batch.DoesNotExist)):
            get_batch_traceability("NON-EXISTENT-BATCH")


class DynamicRouteServiceTests(TestCase):
    """Tests mock_dynamic_route multi-stop scheduling and CO2 savings."""

    def test_mock_dynamic_route_structure(self):
        route_plan = mock_dynamic_route()

        self.assertIn("dispatch_vehicle", route_plan)
        self.assertIn("optimized_stops", route_plan)
        self.assertIn("total_volume_kg", route_plan)
        self.assertIn("co2_savings_kg", route_plan["dispatch_vehicle"])
        self.assertGreater(route_plan["dispatch_vehicle"]["co2_savings_kg"], 0)


class TraceabilityAndRouteAPITests(TestCase):
    """Tests /api/trace-batch/ and /api/route-plan/ endpoints."""

    def setUp(self):
        self.client = Client()
        self.farmer = User.objects.create_user(
            phone_number="+919876543255",
            role=User.Role.FARMER,
        )
        self.hub = MicroHub.objects.create(
            name="Test Hub Gamma",
            code="HUB-GAM-01",
            location="Bypass Road",
            district="Nashik",
            state="Maharashtra",
            pincode="422003",
            capacity_kg=Decimal("15000.00"),
        )
        self.crop = Crop.objects.create(
            name="Cabbage",
            code="CROP-CAB-01",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("15.00"),
            shelf_life_days=20,
        )
        self.batch = Batch.objects.create(
            farmer=self.farmer,
            hub=self.hub,
            crop=self.crop,
            volume_kg=Decimal("300.00"),
            ai_grade=Batch.Grade.GRADE_B,
            ai_confidence_score=Decimal("91.00"),
            status=Batch.Status.QUALITY_INSPECTED,
        )

    def test_trace_batch_endpoint_success(self):
        url = reverse("api_trace_batch", args=[self.batch.batch_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["traceability"]["batch_id"], self.batch.batch_id)
        self.assertEqual(data["traceability"]["crop_name"], "Cabbage")

    def test_trace_batch_endpoint_not_found(self):
        url = reverse("api_trace_batch", args=["K2K-INVALID-123"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("not found", data["error"].lower())

    def test_route_plan_endpoint(self):
        url = reverse("api_dynamic_route")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("route_plan", data)


class WalletWithdrawalAPITests(TestCase):
    """Tests /api/wallet/withdraw/ endpoint."""

    def setUp(self):
        self.client = Client()
        self.farmer = User.objects.create_user(
            phone_number="+919876543244",
            role=User.Role.FARMER,
            password="FarmerPassword1!",
        )
        self.retailer = User.objects.create_user(
            email="retailer@domain.com",
            role=User.Role.RETAILER,
            password="RetailerPassword2!",
        )
        self.wallet = FarmerWallet.objects.create(
            farmer=self.farmer,
            current_balance=Decimal("5000.00"),
        )

    def test_unauthenticated_user_redirected(self):
        response = self.client.post(reverse("api_withdraw_wallet"), {"amount": "1000"})
        self.assertEqual(response.status_code, 302)

    def test_retailer_denied_withdrawal(self):
        self.client.force_login(self.retailer)
        response = self.client.post(reverse("api_withdraw_wallet"), {"amount": "1000"})
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertFalse(data["success"])

    def test_farmer_missing_amount_returns_400(self):
        self.client.force_login(self.farmer)
        response = self.client.post(reverse("api_withdraw_wallet"), {})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])

    def test_farmer_insufficient_balance_returns_400(self):
        self.client.force_login(self.farmer)
        response = self.client.post(reverse("api_withdraw_wallet"), {"amount": "10000"})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("Insufficient wallet balance", data["error"])

    def test_farmer_successful_withdrawal(self):
        self.client.force_login(self.farmer)
        response = self.client.post(reverse("api_withdraw_wallet"), {"amount": "2000.00"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["new_balance"], 3000.0)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.current_balance, Decimal("3000.00"))
        self.assertEqual(self.wallet.transactions.count(), 1)
        self.assertEqual(self.wallet.transactions.first().transaction_type, WalletTransaction.TransactionType.DEBIT)


class VoiceServicesUnitTests(TestCase):
    """Tests Sarvam AI STT/TTS and Gemini intent reasoning service layer."""

    def setUp(self):
        self.farmer = User.objects.create_user(
            phone_number="+919876543233",
            role=User.Role.FARMER,
            first_name="Rameshwar",
            last_name="Patil",
        )
        self.wallet = FarmerWallet.objects.create(
            farmer=self.farmer,
            current_balance=Decimal("25450.00"),
        )
        self.crop = Crop.objects.create(
            name="Tomato Special",
            code="CROP-TOM-VOICE",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("24.00"),
            shelf_life_days=10,
        )
        self.schedule = HarvestSchedule.objects.create(
            farmer=self.farmer,
            crop=self.crop,
            recommended_date=timezone.now().date(),
            target_volume_kg=Decimal("1200.00"),
            notes="Morning plucking advised.",
        )

    @patch("core.sarvam_voice_service.SarvamVoiceService.transcribe_audio")
    def test_transcribe_audio_fallback_and_signature(self, mock_transcribe):
        mock_transcribe.return_value = ("मेरा वॉलेट बैलेंस कितना है?", "hi")
        dummy_audio = SimpleUploadedFile("voice.wav", b"RIFF....WAVEfmt ....data....", content_type="audio/wav")
        transcript, lang = transcribe_audio(dummy_audio)
        self.assertIsInstance(transcript, str)
        self.assertTrue(len(transcript) > 0)
        self.assertIn("IN", lang)

    def test_process_intent_wallet_balance(self):
        res = process_intent_with_gemini("मेरा वॉलेट बैलेंस कितना है?", self.farmer)
        self.assertEqual(res["intent"], "wallet_balance")
        cleaned_text = res["response_text"].replace(",", "")
        self.assertTrue("25450" in cleaned_text or "25,450" in res["response_text"])
        self.assertTrue(any(part in res["response_text"] for part in ["Ramesh", "Rameshwar", "रमेश", "रामेश्वर", "किसान"]))

    def test_process_intent_harvest_schedule(self):
        res = process_intent_with_gemini("अगली फसल कटाई कब करनी है?", self.farmer)
        self.assertEqual(res["intent"], "harvest_schedule")
        self.assertTrue(any(crop_kw in res["response_text"] for crop_kw in ["Tomato", "Tomato Special", "टमाटर", "टमाटर स्पेशल", "फसल", "कटाई"]))
        cleaned_sched = res["response_text"].replace(",", "")
        self.assertTrue(any(v in cleaned_sched for v in ["1200", "1,200", "सितंबर", "September", "कटाई", "harvest", "शेड्यूल", "दिन"]))

    def test_process_intent_general_advice(self):
        res = process_intent_with_gemini("मुझे खेती के बारे में कुछ बताइए", self.farmer)
        self.assertEqual(res["intent"], "general_advice")
        self.assertTrue(len(res["response_text"]) > 20)

    def test_process_intent_english_query_and_name_extraction(self):
        # Farmer introduces self in English
        res = process_intent_with_gemini("Hello I am Santosh Patil, what is my wallet balance?", self.farmer)
        self.assertEqual(res["intent"], "wallet_balance")
        self.assertTrue(res["language_code"].startswith("en"))
        self.assertIn("Santosh", res["response_text"])
        self.assertNotIn("Ramesh", res["response_text"])
        cleaned_text = res["response_text"].replace(",", "")
        self.assertTrue("25450" in cleaned_text or "25,450" in res["response_text"])

    def test_generate_speech_returns_valid_base64_audio(self):
        audio_b64 = generate_speech("नमस्ते किसान भाई, आपका बैलेंस सुरक्षित है।", "hi-IN")
        self.assertIsInstance(audio_b64, str)
        self.assertTrue(len(audio_b64) > 50)
        # Verify it decodes into a valid WAV header
        raw_bytes = base64.b64decode(audio_b64)
        self.assertTrue(raw_bytes.startswith(b"RIFF"))


class VoiceAssistEndpointTests(TestCase):
    """Tests /api/voice/assist/ endpoint."""

    def setUp(self):
        self.client = Client()
        self.farmer = User.objects.create_user(
            phone_number="+919876543299",
            role=User.Role.FARMER,
            first_name="Gopal",
        )
        self.retailer = User.objects.create_user(
            email="retailer@voice.com",
            role=User.Role.RETAILER,
            password="Password123!",
        )
        self.wallet = FarmerWallet.objects.create(
            farmer=self.farmer,
            current_balance=Decimal("15000.00"),
        )

    def test_unauthenticated_request_redirects(self):
        response = self.client.post(reverse("api_voice_assist"), {"text": "Hello"})
        self.assertEqual(response.status_code, 302)

    def test_retailer_access_denied(self):
        self.client.force_login(self.retailer)
        response = self.client.post(reverse("api_voice_assist"), {"text": "Hello"})
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertFalse(data["success"])

    def test_empty_request_returns_400(self):
        self.client.force_login(self.farmer)
        response = self.client.post(reverse("api_voice_assist"), {})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])

    def test_farmer_text_query_success(self):
        self.client.force_login(self.farmer)
        response = self.client.post(reverse("api_voice_assist"), {"text": "मेरा वॉलेट बैलेंस कितना है?"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["intent"], "wallet_balance")
        cleaned_text = data["response_text"].replace(",", "")
        self.assertTrue("15000" in cleaned_text or "15,000" in data["response_text"])
        self.assertTrue(len(data["audio_base64"]) > 0)

    @patch("core.views.SarvamVoiceService.transcribe_audio")
    def test_farmer_audio_file_upload_success(self, mock_transcribe):
        mock_transcribe.return_value = ("मेरा वॉलेट बैलेंस कितना है?", "hi-IN")
        self.client.force_login(self.farmer)
        dummy_audio = SimpleUploadedFile("input.wav", b"RIFF....dummy_sound....", content_type="audio/wav")
        response = self.client.post(reverse("api_voice_assist"), {"audio": dummy_audio})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("response_text", data)
        self.assertIn("audio_base64", data)

    def test_endpoint_preserves_session_context_and_reset(self):
        self.client.force_login(self.farmer)
        # Turn 1: Self-introduction in English
        r1 = self.client.post(reverse("api_voice_assist"), {"text": "Hello I am Santosh Patil"})
        self.assertEqual(r1.status_code, 200)
        d1 = r1.json()
        self.assertTrue(d1["success"])
        self.assertIn("Santosh", d1["preferred_name"])
        self.assertTrue(d1["detected_language"].startswith("en"))

        # Turn 2: Follow-up question in English without repeating name
        r2 = self.client.post(reverse("api_voice_assist"), {"text": "Actually I want to sell tomatoes as soon as possible"})
        self.assertEqual(r2.status_code, 200)
        d2 = r2.json()
        self.assertTrue(d2["success"])
        self.assertIn("Santosh", d2["response_text"])
        self.assertNotIn("Ramesh", d2["response_text"])
        self.assertTrue(d2["detected_language"].startswith("en"))
        self.assertEqual(len(d2["conversation_history"]), 2)

        # Reset chat session
        r_reset = self.client.post(reverse("api_voice_assist"), {"reset_chat": "1"})
        self.assertEqual(r_reset.status_code, 200)
        d_reset = r_reset.json()
        self.assertEqual(d_reset["conversation_history"], [])

        # Turn 3: New conversation query starts fresh
        r3 = self.client.post(reverse("api_voice_assist"), {"text": "What is my wallet balance?"})
        self.assertEqual(r3.status_code, 200)
        d3 = r3.json()
        self.assertEqual(len(d3["conversation_history"]), 1)
        self.assertTrue(d3["detected_language"].startswith("en"))


class WeatherIntelligenceServicesTests(TestCase):
    """Tests Nominatim geocoding, Open-Meteo telemetry parsing, and Gemini advisory generation."""

    @patch("core.services.requests.get")
    def test_get_coordinates_from_pincode_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "lat": "20.0475524",
                "lon": "73.8034663",
                "display_name": "422004, Nashik, Maharashtra, India",
            }
        ]
        mock_get.return_value = mock_response

        lat, lon, display_name = get_coordinates_from_pincode("422004")
        self.assertAlmostEqual(lat, 20.0475524)
        self.assertAlmostEqual(lon, 73.8034663)
        self.assertIn("Nashik", display_name)

    @patch("core.services.requests.get")
    def test_get_coordinates_from_pincode_empty_fallback(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        lat, lon, display_name = get_coordinates_from_pincode("999999")
        self.assertEqual(lat, 17.3850)
        self.assertEqual(lon, 78.4867)
        self.assertIn("Hyderabad", display_name)

    @patch("core.services.requests.get")
    def test_get_coordinates_from_pincode_network_exception_fallback(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("DNS resolution failed")

        lat, lon, display_name = get_coordinates_from_pincode("422004")
        self.assertEqual(lat, 17.3850)
        self.assertEqual(lon, 78.4867)
        self.assertIn("Hyderabad", display_name)

    @patch("core.services.requests.get")
    def test_fetch_real_weather_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "current": {
                "temperature_2m": 27.5,
                "relative_humidity_2m": 68.0,
                "precipitation": 1.2,
                "wind_speed_10m": 15.4,
            },
            "hourly": {
                "soil_temperature_6cm": [24.0, 24.2, 24.5, 24.8],
                "soil_moisture_3_9cm": [0.42, 0.42, 0.43, 0.43],
            },
            "daily": {
                "temperature_2m_max": [28.5],
                "temperature_2m_min": [21.0],
                "precipitation_sum": [3.5],
            },
        }
        mock_get.return_value = mock_response

        weather = fetch_real_weather(20.0475, 73.8035)
        self.assertEqual(weather["temperature_c"], 27.5)
        self.assertEqual(weather["relative_humidity_pct"], 68.0)
        self.assertEqual(weather["precipitation_mm"], 1.2)
        self.assertEqual(weather["avg_soil_temp_c"], 24.4)
        self.assertEqual(weather["avg_soil_moisture_pct"], 42.5)
        self.assertEqual(weather["source"], "Open-Meteo Live API")

    @patch("core.services.requests.get")
    def test_fetch_real_weather_exception_fallback(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("Connection timeout")

        weather = fetch_real_weather(20.0475, 73.8035)
        self.assertIn("temperature_c", weather)
        self.assertIn("avg_soil_moisture_pct", weather)
        self.assertEqual(weather["source"], "Fallback Agronomic Model")

    def test_generate_agronomic_advisory_rule_based_fallback(self):
        weather_summary = {
            "temperature_c": 29.0,
            "relative_humidity_pct": 78.0,
            "precipitation_mm": 2.5,
            "wind_speed_kmh": 12.0,
            "avg_soil_temp_c": 24.0,
            "avg_soil_moisture_pct": 46.0,
            "temp_max_c": 31.0,
            "temp_min_c": 22.0,
            "precipitation_sum_mm": 6.0,
        }
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            advisory = generate_agronomic_advisory(weather_summary, "Nashik Hub")

        self.assertIn("weather_headline", advisory)
        self.assertIn("risks", advisory)
        self.assertIn("irrigation_harvest_advice", advisory)
        self.assertIn("recommended_crops", advisory)
        self.assertTrue(len(advisory["weather_headline"]) > 10)
        self.assertTrue(len(advisory["risks"]) > 10)


class WeatherAdvisoryAPITests(TestCase):
    """Tests /api/weather-advisory/ endpoint."""

    def setUp(self):
        self.client = Client()

    @patch("core.views.fetch_real_weather")
    @patch("core.views.generate_agronomic_advisory")
    def test_weather_advisory_with_coordinates(self, mock_advisory, mock_weather):
        mock_weather.return_value = {
            "temperature_c": 26.5,
            "relative_humidity_pct": 65.0,
            "avg_soil_moisture_pct": 40.0,
        }
        mock_advisory.return_value = {
            "weather_headline": "Pleasant morning with moderate humidity.",
            "risks": "Low pest hazard.",
            "irrigation_harvest_advice": "Proceed with regular harvesting.",
            "recommended_crops": "Tomatoes and Onions.",
        }

        response = self.client.get("/api/weather-advisory/?lat=20.0475&lon=73.8035")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertAlmostEqual(data["location"]["latitude"], 20.0475)
        self.assertAlmostEqual(data["location"]["longitude"], 73.8035)
        self.assertIn("weather", data)
        self.assertIn("advisory", data)
        self.assertEqual(data["advisory"]["weather_headline"], "Pleasant morning with moderate humidity.")

    @patch("core.views.get_coordinates_from_pincode")
    @patch("core.views.fetch_real_weather")
    @patch("core.views.generate_agronomic_advisory")
    def test_weather_advisory_with_pincode(self, mock_advisory, mock_weather, mock_geo):
        mock_geo.return_value = (20.0475, 73.8035, "Nashik, Maharashtra")
        mock_weather.return_value = {
            "temperature_c": 28.0,
            "relative_humidity_pct": 60.0,
            "avg_soil_moisture_pct": 38.0,
        }
        mock_advisory.return_value = {
            "weather_headline": "Sunny and clear.",
            "risks": "Minimal pest risk.",
            "irrigation_harvest_advice": "Optimal morning harvest.",
            "recommended_crops": "Bell Pepper and Cauliflower.",
        }

        response = self.client.get("/api/weather-advisory/?pincode=422004")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["location"]["pincode"], "422004")
        self.assertEqual(data["location"]["display_name"], "Nashik, Maharashtra")

    def test_weather_advisory_invalid_coordinates_returns_400(self):
        response = self.client.get("/api/weather-advisory/?lat=invalid&lon=73.8035")
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("Invalid latitude or longitude", data["error"])

    def test_weather_advisory_post_method_not_allowed(self):
        response = self.client.post("/api/weather-advisory/", {})
        self.assertEqual(response.status_code, 405)
        data = response.json()
        self.assertFalse(data["success"])


class UserRegistrationTests(TestCase):
    """
    Test suite for Khet2Kitchen User Registration (Signup) flow.
    Verifies multi-role onboarding, name splitting, dual column mirroring,
    and automatic atomic FarmerWallet provisioning.
    """

    def test_farmer_signup_success(self):
        signup_data = {
            "name": "Rameshwar Rao",
            "role": "FARMER",
            "identifier": "+919876543999",
            "password": "FarmPassword123!",
        }
        response = self.client.post(reverse("signup"), signup_data)
        self.assertRedirects(response, reverse("farmer_dashboard"))

        # Verify User creation and fields
        user = User.objects.get(identifier="+919876543999")
        self.assertEqual(user.first_name, "Rameshwar")
        self.assertEqual(user.last_name, "Rao")
        self.assertEqual(user.phone_number, "+919876543999")
        self.assertEqual(user.role, User.Role.FARMER)
        self.assertTrue(user.check_password("FarmPassword123!"))

        # Verify FarmerWallet provisioning with zero balance
        self.assertTrue(hasattr(user, "wallet"))
        self.assertEqual(user.wallet.current_balance, Decimal("0.00"))

        # Verify user is logged in
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_retailer_signup_success(self):
        signup_data = {
            "name": "Pooja Mehta",
            "role": "RETAILER",
            "identifier": "pooja.mehta@freshmart.in",
            "password": "RetailPass456!",
        }
        response = self.client.post(reverse("signup"), signup_data)
        self.assertRedirects(response, reverse("retailer_dashboard"))

        # Verify User creation and email population
        user = User.objects.get(identifier="pooja.mehta@freshmart.in")
        self.assertEqual(user.first_name, "Pooja")
        self.assertEqual(user.last_name, "Mehta")
        self.assertEqual(user.email, "pooja.mehta@freshmart.in")
        self.assertEqual(user.role, User.Role.RETAILER)
        self.assertTrue(user.check_password("RetailPass456!"))

        # Non-farmer user should not have a FarmerWallet
        self.assertFalse(hasattr(user, "wallet"))

    def test_supplier_signup_success(self):
        signup_data = {
            "name": "Kisan Seeds Corp",
            "role": "SUPPLIER",
            "identifier": "orders@kisanseeds.com",
            "password": "SupplierPass789!",
        }
        response = self.client.post(reverse("signup"), signup_data)
        self.assertRedirects(response, reverse("supplier_dashboard"))

        user = User.objects.get(identifier="orders@kisanseeds.com")
        self.assertEqual(user.first_name, "Kisan")
        self.assertEqual(user.last_name, "Seeds Corp")
        self.assertEqual(user.email, "orders@kisanseeds.com")
        self.assertEqual(user.role, User.Role.SUPPLIER)

    def test_farmer_signup_invalid_phone_rejected(self):
        signup_data = {
            "name": "Farmer Bad Phone",
            "role": "FARMER",
            "identifier": "12345",  # Under 10 digits
            "password": "Password123!",
        }
        response = self.client.post(reverse("signup"), signup_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "identifier",
            "Farmer identifier must be a valid mobile phone number with at least 10 digits.",
        )
        self.assertFalse(User.objects.filter(identifier="12345").exists())

    def test_retailer_signup_invalid_email_rejected(self):
        signup_data = {
            "name": "Retailer Bad Email",
            "role": "RETAILER",
            "identifier": "not-a-valid-email",
            "password": "Password123!",
        }
        response = self.client.post(reverse("signup"), signup_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "identifier",
            "Identifier must be a valid email address for Retailers and Suppliers.",
        )
        self.assertFalse(User.objects.filter(identifier="not-a-valid-email").exists())

    def test_duplicate_identifier_rejected(self):
        User.objects.create_user(
            phone_number="+919876543210",
            role=User.Role.FARMER,
            first_name="Existing",
            last_name="Farmer",
        )
        signup_data = {
            "name": "Duplicate Farmer",
            "role": "FARMER",
            "identifier": "+919876543210",
            "password": "Password123!",
        }
        response = self.client.post(reverse("signup"), signup_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "identifier",
            "An account with this identifier already exists.",
        )

    def test_signup_page_renders_cleanly(self):
        response = self.client.get(reverse("signup"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/signup.html")
        self.assertContains(response, "Join Khet2Kitchen")
        self.assertContains(response, "Complete Registration")


class DataIsolationAndDynamicActionTests(TestCase):
    """
    Validates strict data isolation across Farmer, Retailer, and Supplier domains,
    and tests dynamic CRUD actions (add/edit/inspect crop, post demand order, input supply management).
    """

    def setUp(self):
        self.client = Client()
        # Farmer 1 with 1 crop
        self.farmer1 = User.objects.create_user(
            phone_number="+919876543210",
            role=User.Role.FARMER,
            first_name="Ramesh",
            last_name="Patel",
            password="FarmerPassword1!",
        )
        self.crop1 = Crop.objects.create(
            farmer=self.farmer1,
            name="Private Farmer1 Wheat",
            code="CROP-WHT-F1",
            category=Crop.Category.GRAIN,
            expected_yield_kg=Decimal("8000.00"),
            planted_date="2024-01-10",
            status="Growing",
            base_price=Decimal("24.00"),
        )
        # Farmer 2 with NO crops initially
        self.farmer2 = User.objects.create_user(
            phone_number="+919876543299",
            role=User.Role.FARMER,
            first_name="New",
            last_name="Kisan",
            password="FarmerPassword2!",
        )

        # Retailers
        self.retailer1 = User.objects.create_user(
            email="retailer1@k2k.in",
            role=User.Role.RETAILER,
            first_name="FreshBazaar",
            last_name="Mumbai",
            password="RetailerPassword1!",
        )
        self.order1 = DemandOrder.objects.create(
            order_id="ORD-MUM-001",
            retailer=self.retailer1,
            crop=self.crop1,
            required_volume_kg=Decimal("1000.00"),
            required_date=timezone.now().date(),
            delivery_address="FreshBazaar Mumbai Depot",
        )
        self.retailer2 = User.objects.create_user(
            email="hyderabad@freshbazaar.in",
            role=User.Role.RETAILER,
            first_name="FreshBazaar",
            last_name="Hyderabad",
            password="RetailerPassword2!",
        )

        # Suppliers
        self.supplier1 = User.objects.create_user(
            email="sales@bioagri.com",
            role=User.Role.SUPPLIER,
            first_name="BioAgri",
            last_name="National",
            password="SupplierPassword1!",
        )
        self.supply1 = InputSupply.objects.create(
            supplier=self.supplier1,
            name="Organic Neem Fertilizer",
            category=InputSupply.Category.FERTILIZER,
            quantity=Decimal("100.00"),
            unit="Bags",
            price_per_unit=Decimal("450.00"),
            status=InputSupply.Status.IN_STOCK,
        )
        self.supplier2 = User.objects.create_user(
            email="sales@bioagri-ts.in",
            role=User.Role.SUPPLIER,
            first_name="BioAgri",
            last_name="Telangana",
            password="SupplierPassword2!",
        )

    def test_new_farmer_dashboard_is_empty_by_default(self):
        """A newly registered farmer must not see other farmers' crops."""
        self.client.login(username="+919876543299", password="FarmerPassword2!")
        response = self.client.get(reverse("farmer_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["my_crops"]), 0)
        self.assertContains(response, "No crops registered yet")
        self.assertNotContains(response, "Private Farmer1 Wheat")

    def test_farmer_cannot_edit_other_farmer_crop(self):
        """Cross-tenant crop editing is prevented with HTTP 404."""
        self.client.login(username="+919876543299", password="FarmerPassword2!")
        edit_url = reverse("edit_crop", args=[self.crop1.id])
        response = self.client.post(edit_url, {
            "expected_yield_kg": "9999",
            "harvest_date": "2024-12-31",
            "status": "Harvested",
        })
        self.assertEqual(response.status_code, 404)
        self.crop1.refresh_from_db()
        self.assertEqual(self.crop1.expected_yield_kg, Decimal("8000.00"))

    def test_farmer_cannot_inspect_other_farmer_crop(self):
        """Cross-tenant crop inspection is prevented with HTTP 404."""
        self.client.login(username="+919876543299", password="FarmerPassword2!")
        inspect_url = reverse("crop_inspect", args=[self.crop1.id])
        response = self.client.get(inspect_url)
        self.assertEqual(response.status_code, 404)

    def test_farmer_crop_crud_lifecycle(self):
        """Owner can dynamically add, edit, and inspect their own crop."""
        self.client.login(username="+919876543299", password="FarmerPassword2!")
        
        # 1. Add Crop
        add_url = reverse("add_crop")
        add_res = self.client.post(add_url, {
            "name": "Hybrid Tomato (Tamatar)",
            "category": Crop.Category.VEGETABLE,
            "expected_yield_kg": "1200",
            "planted_date": "2026-03-01",
            "harvest_date": "2026-04-15",
            "status": "Growing",
        })
        self.assertEqual(add_res.status_code, 302)
        new_crop = Crop.objects.filter(farmer=self.farmer2, name="Hybrid Tomato (Tamatar)").first()
        self.assertIsNotNone(new_crop)
        self.assertEqual(new_crop.expected_yield_kg, Decimal("1200.00"))

        # 2. Edit Crop
        edit_url = reverse("edit_crop", args=[new_crop.id])
        edit_res = self.client.post(edit_url, {
            "expected_yield_kg": "1500",
            "harvest_date": "2026-04-20",
            "status": "At Hub (Graded)",
        })
        self.assertEqual(edit_res.status_code, 302)
        new_crop.refresh_from_db()
        self.assertEqual(new_crop.expected_yield_kg, Decimal("1500.00"))
        self.assertEqual(new_crop.status, "At Hub (Graded)")

        # 3. Inspect Crop (JSON API)
        inspect_url = reverse("crop_inspect", args=[new_crop.id])
        inspect_res = self.client.get(inspect_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(inspect_res.status_code, 200)
        data = inspect_res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["crop"]["name"], "Hybrid Tomato (Tamatar)")
        self.assertEqual(len(data["timeline"]), 5)

        # 4. Inspect Crop (Dedicated Web Page)
        inspect_page_res = self.client.get(inspect_url)
        self.assertEqual(inspect_page_res.status_code, 200)
        self.assertTemplateUsed(inspect_page_res, "core/crop_inspect.html")
        self.assertContains(inspect_page_res, "Hybrid Tomato (Tamatar)")

    def test_retailer_demand_order_data_isolation_and_creation(self):
        """Retailer dashboard strictly isolates orders and allows posting new requirements."""
        self.client.login(username="hyderabad@freshbazaar.in", password="RetailerPassword2!")
        
        # Fresh retailer has 0 orders
        res = self.client.get(reverse("retailer_dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["demand_orders"].count(), 0)
        self.assertContains(res, "No pre-orders placed yet")

        # Post new demand order
        add_order_url = reverse("add_demand_order")
        post_res = self.client.post(add_order_url, {
            "crop": self.crop1.id,
            "required_volume_kg": "500",
            "required_date": timezone.now().date(),
            "delivery_address": "FreshBazaar Hyderabad, Secunderabad, PIN: 500003",
        })
        self.assertEqual(post_res.status_code, 302)
        hyd_order = DemandOrder.objects.filter(retailer=self.retailer2).first()
        self.assertIsNotNone(hyd_order)
        self.assertEqual(hyd_order.required_volume_kg, Decimal("500.00"))

        # Retailer 1 dashboard does not show Retailer 2 order
        self.client.login(username="retailer1@k2k.in", password="RetailerPassword1!")
        res1 = self.client.get(reverse("retailer_dashboard"))
        self.assertEqual(res1.context["demand_orders"].count(), 1)
        self.assertEqual(res1.context["demand_orders"].first().order_id, self.order1.order_id)

    def test_supplier_inventory_data_isolation_and_stock_updates(self):
        """Supplier dashboard isolates input catalog and supports adding/updating stock."""
        self.client.login(username="sales@bioagri-ts.in", password="SupplierPassword2!")

        # Fresh supplier has 0 items
        res = self.client.get(reverse("supplier_dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["inventory_items"].count(), 0)
        self.assertContains(res, "No input supplies registered yet")

        # Add new input supply
        add_url = reverse("add_input_supply")
        add_res = self.client.post(add_url, {
            "name": "Bio-Potash Telangana Gold",
            "category": InputSupply.Category.FERTILIZER,
            "quantity": "50",
            "unit": "Bags",
            "price_per_unit": "520.00",
            "status": InputSupply.Status.IN_STOCK,
            "description": "Potash mobilizing biofertilizer for TS soils.",
        })
        self.assertEqual(add_res.status_code, 302)
        ts_item = InputSupply.objects.filter(supplier=self.supplier2).first()
        self.assertIsNotNone(ts_item)
        self.assertEqual(ts_item.quantity, Decimal("50.00"))

        # Update stock
        update_url = reverse("update_input_supply", args=[ts_item.id])
        update_res = self.client.post(update_url, {
            "quantity": "75",
            "price_per_unit": "510.00",
            "status": "LOW_STOCK",
        })
        self.assertEqual(update_res.status_code, 302)
        ts_item.refresh_from_db()
        self.assertEqual(ts_item.quantity, Decimal("75.00"))
        self.assertEqual(ts_item.price_per_unit, Decimal("510.00"))
        self.assertEqual(ts_item.status, "LOW_STOCK")

        # Cross-tenant update blocked with 404
        self.client.login(username="sales@bioagri.com", password="SupplierPassword1!")
        hacker_res = self.client.post(update_url, {"quantity": "0"})
        self.assertEqual(hacker_res.status_code, 404)


class LandingPageViewTests(TestCase):
    """Tests for public landing page and smart root redirect behavior."""

    def setUp(self):
        self.client = Client()
        self.farmer = User.objects.create_user(
            phone_number="+919876543290",
            password="FarmerPassword1!",
            role=User.Role.FARMER,
            first_name="Ramesh",
        )
        self.retailer = User.objects.create_user(
            email="retailer@freshbazaar.in",
            password="RetailerPassword1!",
            role=User.Role.RETAILER,
            first_name="Ananya",
        )

    def test_anonymous_user_landing_page_renders(self):
        """Anonymous users requesting GET / get 200 OK and see the high-converting landing page."""
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/landing.html")
        self.assertContains(response, "Khet2Kitchen")
        self.assertContains(response, "The Intelligent Agritech Supply Chain")
        self.assertContains(response, "100% Transparent Pricing")
        self.assertContains(response, "AI Optical Grading")
        self.assertContains(response, "Dynamic Route Optimization")
        self.assertContains(response, "Smart India Hackathon")
        self.assertNotContains(response, "mailto:")

    def test_authenticated_farmer_redirects_to_farmer_dashboard(self):
        """Authenticated farmer requesting GET / is redirected to /farmer/dashboard/."""
        self.client.login(username="+919876543290", password="FarmerPassword1!")
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("farmer_dashboard"))

    def test_authenticated_retailer_redirects_to_retailer_dashboard(self):
        """Authenticated retailer requesting GET / is redirected to /retailer/dashboard/."""
        self.client.login(username="retailer@freshbazaar.in", password="RetailerPassword1!")
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("retailer_dashboard"))

    def test_anonymous_user_can_access_login_and_signup(self):
        """Anonymous user can access /login/ and /signup/ without getting redirected to root or blocked."""
        login_res = self.client.get(reverse("login"))
        self.assertEqual(login_res.status_code, 200)
        self.assertTemplateUsed(login_res, "core/login.html")

        signup_res = self.client.get(reverse("signup"))
        self.assertEqual(signup_res.status_code, 200)
        self.assertTemplateUsed(signup_res, "core/signup.html")

    def test_authenticated_user_accessing_login_redirects_to_dashboard(self):
        """Authenticated user visiting /login/ is redirected to their respective dashboard."""
        self.client.login(username="+919876543290", password="FarmerPassword1!")
        res = self.client.get(reverse("login"))
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse("farmer_dashboard"))


class ConsumerD2CTests(TestCase):
    """
    Unit & integration tests for Direct-to-Consumer (D2C) marketplace,
    pre-packaged vegetable kits, AI recipe-to-combo engine, and direct farmer wallet payouts.
    """

    def setUp(self):
        self.client = Client()

        # Create demo farmer and wallet
        self.farmer = User.objects.create_user(
            identifier="+919876543222",
            phone_number="+919876543222",
            role=User.Role.FARMER,
            first_name="Ramesh",
            last_name="Kumar",
        )
        self.farmer_wallet = FarmerWallet.objects.create(
            farmer=self.farmer,
            current_balance=Decimal("0.00"),
        )

        # Create crops assigned to this farmer
        self.crop_tomato = Crop.objects.create(
            code="CROP-TST-TOM-01",
            name="Roma Field Tomato",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("20.00"),
            farmer=self.farmer,
            is_active=True,
        )
        self.crop_onion = Crop.objects.create(
            code="CROP-TST-ONN-01",
            name="Red Onion",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("30.00"),
            farmer=self.farmer,
            is_active=True,
        )
        self.crop_chilli = Crop.objects.create(
            code="CROP-TST-CHL-01",
            name="Green Chilli",
            category=Crop.Category.SPICE,
            base_price=Decimal("100.00"),
            farmer=self.farmer,
            is_active=True,
        )

        # Create a sample consumer Kit
        self.kit = Kit.objects.create(
            name="Sambar Essentials Test Kit",
            code="KIT-TST-SBR-01",
            category=Kit.Category.VEGETABLE,
            description="Tomato + Onion + Chilli bundle for Sambar",
            discount_percentage=Decimal("15.00"),
            badge_text="15% OFF",
            is_active=True,
        )
        # Kit items: 1000g Tomato (₹20.00), 500g Onion (₹15.00) => Total Orig = ₹35.00
        KitItem.objects.create(kit=self.kit, crop=self.crop_tomato, quantity_grams=1000)
        KitItem.objects.create(kit=self.kit, crop=self.crop_onion, quantity_grams=500)

    def test_kit_creation_and_pricing_calculation(self):
        """Validates bundle pricing calculation, discount deductions, and consumer savings."""
        orig_price = self.kit.calculate_original_price()
        self.assertEqual(orig_price, Decimal("35.00"))

        # 15% discount on ₹35.00 = ₹29.75
        bundle_price = self.kit.calculate_bundle_price()
        self.assertEqual(bundle_price, Decimal("29.75"))

        # Savings = 35.00 - 29.75 = 5.25
        savings = self.kit.get_savings()
        self.assertEqual(savings, Decimal("5.25"))

        # Total weight
        self.assertEqual(self.kit.total_weight_grams(), 1500)

    @patch("core.ai_recipe.query_gemini_recipe", return_value=None)
    def test_ai_dish_combo_calculation_and_servings_scaling(self, mock_gemini):
        """Validates that the AI recipe engine dynamically scales ingredient quantities based on member count."""
        combo_4 = generate_recipe_combo("Sambar", servings=4, persist=False)
        self.assertEqual(combo_4["servings"], 4)
        self.assertTrue(any("Tomato" in item["crop_name"] for item in combo_4["items"]))

        combo_8 = generate_recipe_combo("Sambar", servings=8, persist=False)
        self.assertEqual(combo_8["servings"], 8)

        # Total produce weight for 8 members should be exactly double 4 members (0.60kg vs 1.20kg)
        self.assertAlmostEqual(combo_8["total_weight_kg"], combo_4["total_weight_kg"] * 2, delta=0.01)

        # Payout should be 90% of combo price
        expected_payout = (Decimal(str(combo_4["combo_price"])) * Decimal("0.90")).quantize(Decimal("0.01"))
        self.assertEqual(Decimal(str(combo_4["farmer_payout"])), expected_payout)

    @patch("core.ai_recipe.query_gemini_recipe")
    def test_ai_dish_combo_with_gemini_structured_response(self, mock_gemini):
        """Validates that when Gemini API returns structured JSON, it is parsed and mapped correctly."""
        mock_gemini.return_value = {
            "dish_title": "Chef Special Hyderabadi Biryani",
            "prep_time_minutes": 40,
            "culinary_notes": "Slow-cooked dum vegetables with caramelized onions.",
            "ingredients": [
                {"crop_name": "Tomato", "quantity_grams": 400, "role": "Gravy acidity"},
                {"crop_name": "Onion", "quantity_grams": 500, "role": "Crispy birista"},
            ],
        }
        combo = generate_recipe_combo("Biryani", servings=4, persist=False)
        self.assertEqual(combo["dish_name"], "Chef Special Hyderabadi Biryani")
        self.assertEqual(combo["prep_time_minutes"], 40)
        self.assertEqual(len(combo["items"]), 2)
        self.assertEqual(combo["discount_percentage"], 15.0)


    def test_direct_d2c_kit_order_and_farmer_wallet_credit(self):
        """
        Validates placing a D2C kit order creates a settled ConsumerOrder
        and immediately credits the farmer's FarmerWallet with an immutable ledger entry.
        """
        initial_balance = self.farmer_wallet.current_balance
        self.assertEqual(initial_balance, Decimal("0.00"))

        post_data = {
            "item_type": "KIT",
            "item_id": self.kit.id,
            "quantity": "2",
            "customer_name": "Priya Verma",
            "customer_phone": "+91 91234 56789",
            "customer_email": "priya@example.com",
            "delivery_address": "Flat 301, Lakeview Apts, Gachibowli, Hyderabad",
            "pincode": "500032",
        }

        response = self.client.post(reverse("consumer_checkout"), post_data)
        self.assertEqual(response.status_code, 302)

        order = ConsumerOrder.objects.filter(customer_name="Priya Verma").first()
        self.assertIsNotNone(order)
        self.assertEqual(order.status, ConsumerOrder.Status.PAID_SETTLED)
        self.assertEqual(order.payment_method, "UPI_INSTANT")

        # 2 kits @ 29.75 = 59.50 final paid amount
        self.assertEqual(order.final_paid_amount, Decimal("59.50"))

        # Check line item
        line_item = order.items.first()
        self.assertIsNotNone(line_item)
        self.assertTrue(line_item.is_settled_to_wallet)

        # Refresh farmer wallet and check credit
        self.farmer_wallet.refresh_from_db()
        self.assertGreater(self.farmer_wallet.current_balance, initial_balance)

        # Verify wallet transaction ledger
        tx = self.farmer_wallet.transactions.first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.transaction_type, WalletTransaction.TransactionType.CREDIT)
        self.assertIn("D2C Kit Sale", tx.description)

    def test_direct_d2c_produce_order_and_farmer_wallet_credit(self):
        """Validates placing a direct produce order credits the specific crop farmer."""
        post_data = {
            "item_type": "PRODUCE",
            "item_id": self.crop_tomato.id,
            "quantity_kg": "5.00",
            "customer_name": "Rohan Gupta",
            "customer_phone": "+91 99887 76655",
            "delivery_address": "Banjara Hills, Hyderabad",
            "pincode": "500034",
        }

        res = self.client.post(reverse("consumer_checkout"), post_data)
        self.assertEqual(res.status_code, 302)

        order = ConsumerOrder.objects.filter(customer_name="Rohan Gupta").first()
        self.assertIsNotNone(order)
        # 5kg * ₹20/kg = ₹100.00
        self.assertEqual(order.final_paid_amount, Decimal("100.00"))

        self.farmer_wallet.refresh_from_db()
        # 92% of ₹100 = ₹92.00 credited
        self.assertEqual(self.farmer_wallet.current_balance, Decimal("92.00"))

    def test_direct_d2c_combo_order_creation_and_settlement(self):
        """Validates purchasing an AI recipe combo creates order and settles to farmer wallet."""
        combo = RecipeCombo.objects.create(
            dish_name="Authentic South Indian Sambar",
            servings=4,
            prep_time_minutes=25,
            culinary_notes="Nutrient-dense sambar",
            total_weight_kg=Decimal("1.20"),
            original_price=Decimal("100.00"),
            discount_percentage=Decimal("15.00"),
            combo_price=Decimal("85.00"),
            items_breakdown=[
                {
                    "crop_id": self.crop_tomato.id,
                    "crop_name": "Roma Field Tomato",
                    "quantity_grams": 400,
                    "role": "Tangy broth base",
                    "base_price_per_kg": 20.00,
                    "standalone_price": 8.00,
                    "farmer_id": self.farmer.id,
                    "farmer_name": "Ramesh Kumar",
                    "farmer_location": "Telangana",
                }
            ],
        )

        post_data = {
            "item_type": "COMBO",
            "item_id": combo.id,
            "customer_name": "Deepak Joshi",
            "customer_phone": "+91 94400 12345",
            "delivery_address": "Kondapur, Hyderabad",
            "pincode": "500084",
        }

        res = self.client.post(reverse("consumer_checkout"), post_data)
        self.assertEqual(res.status_code, 302)

        order = ConsumerOrder.objects.filter(customer_name="Deepak Joshi").first()
        self.assertIsNotNone(order)
        self.assertEqual(order.final_paid_amount, Decimal("85.00"))

        # Verify farmer wallet credited
        self.farmer_wallet.refresh_from_db()
        self.assertGreater(self.farmer_wallet.current_balance, Decimal("0.00"))

    def test_consumer_shop_and_combo_views_render_successfully(self):
        """Validates public accessibility and correct template rendering for consumer portal."""
        # 1. Shop view
        shop_res = self.client.get(reverse("consumer_shop"))
        self.assertEqual(shop_res.status_code, 200)
        self.assertTemplateUsed(shop_res, "core/consumer_shop.html")
        self.assertContains(shop_res, "Khet2Kitchen")
        self.assertContains(shop_res, "D2C Farm Store")
        self.assertContains(shop_res, "Sambar Essentials Test Kit")

        # 2. AI Combo Builder HTML view
        combo_res = self.client.get(reverse("ai_combo_builder") + "?dish_name=Sambar&servings=4")
        self.assertEqual(combo_res.status_code, 200)
        self.assertTemplateUsed(combo_res, "core/consumer_combo_detail.html")
        self.assertContains(combo_res, "Sambar")

        # 3. AI Combo Builder JSON API
        api_res = self.client.get(
            reverse("ai_combo_builder") + "?dish_name=Sambar&servings=4&format=json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(api_res.status_code, 200)
        json_data = api_res.json()
        self.assertEqual(json_data["status"], "success")
        self.assertIn("combo", json_data)

        # 4. Order Success view
        order = ConsumerOrder.objects.create(
            customer_name="Test Consumer",
            customer_phone="+91 99999 88888",
            delivery_address="Hitech City, Hyderabad",
            pincode="500081",
            total_amount=Decimal("100.00"),
            final_paid_amount=Decimal("85.00"),
            status=ConsumerOrder.Status.PAID_SETTLED,
        )
        success_res = self.client.get(reverse("consumer_order_success", args=[order.order_id]))
        self.assertEqual(success_res.status_code, 200)
        self.assertTemplateUsed(success_res, "core/consumer_order_success.html")
        self.assertContains(success_res, order.order_id)


class ConsumerAccountAndFeedbackTests(TestCase):
    """
    Test suite for Consumer active accounts, order storage,
    dashboard tracking, and farmer review/feedback system.
    """

    def setUp(self):
        self.client = Client()
        self.farmer = User.objects.create_user(
            identifier="+919876543210",
            phone_number="+919876543210",
            role=User.Role.FARMER,
            first_name="Ramesh",
            last_name="Kumar",
            password="farmerpassword",
        )
        self.farmer_wallet = FarmerWallet.objects.create(
            farmer=self.farmer,
            current_balance=Decimal("0.00"),
        )
        self.crop = Crop.objects.create(
            name="Organic Roma Tomato",
            code="CR-TOM-01",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("25.00"),
            farmer=self.farmer,
            is_active=True,
        )
        self.consumer = User.objects.create_user(
            identifier="priya@consumer.in",
            email="priya@consumer.in",
            phone_number="+919876543299",
            role=User.Role.CONSUMER,
            first_name="Priya",
            last_name="Reddy",
            address="Jubilee Hills, Hyderabad",
            pincode="500033",
            password="consumerpassword",
        )

    def test_consumer_role_properties_and_dashboard_url(self):
        """Verifies Consumer role flags and routing configuration."""
        self.assertTrue(self.consumer.is_consumer)
        self.assertFalse(self.farmer.is_consumer)
        self.assertEqual(self.consumer.get_dashboard_url(), reverse("consumer_dashboard"))

        # Verify landing page smart redirect for authenticated consumer
        self.client.force_login(self.consumer)
        res = self.client.get(reverse("home"))
        self.assertRedirects(res, reverse("consumer_dashboard"))

    def test_consumer_registration_with_email_and_mobile(self):
        """Verifies consumers can register using either an email or mobile phone."""
        # 1. Registration via Email
        res_email = self.client.post(reverse("signup"), {
            "name": "Kavita Rao",
            "role": User.Role.CONSUMER,
            "identifier": "kavita.rao@example.com",
            "password": "strongpassword123",
        })
        self.assertRedirects(res_email, reverse("consumer_dashboard"))
        user_email = User.objects.get(identifier="kavita.rao@example.com")
        self.assertEqual(user_email.role, User.Role.CONSUMER)
        self.assertEqual(user_email.first_name, "Kavita")
        self.assertEqual(user_email.last_name, "Rao")
        self.assertEqual(user_email.email, "kavita.rao@example.com")
        self.assertIsNone(user_email.phone_number)

        # 2. Registration via Mobile Phone Number (log out first)
        self.client.logout()
        res_phone = self.client.post(reverse("signup"), {
            "name": "Arjun Mehta",
            "role": User.Role.CONSUMER,
            "identifier": "+919876500099",
            "password": "strongpassword123",
        })
        self.assertRedirects(res_phone, reverse("consumer_dashboard"))
        user_phone = User.objects.get(identifier="+919876500099")
        self.assertEqual(user_phone.role, User.Role.CONSUMER)
        self.assertEqual(user_phone.phone_number, "+919876500099")

    def test_authenticated_consumer_checkout_associates_order_user(self):
        """Verifies that placing an order while logged in as consumer binds order.user."""
        self.client.force_login(self.consumer)

        post_data = {
            "item_type": "PRODUCE",
            "item_id": self.crop.id,
            "quantity_kg": "4.00",
            "delivery_address": "Road 36, Jubilee Hills, Hyderabad",
            "pincode": "500033",
        }

        res = self.client.post(reverse("consumer_checkout"), post_data)
        self.assertEqual(res.status_code, 302)

        order = ConsumerOrder.objects.filter(user=self.consumer).first()
        self.assertIsNotNone(order)
        self.assertEqual(order.user, self.consumer)
        self.assertEqual(order.customer_name, "Priya Reddy")
        self.assertEqual(order.customer_phone, "+919876543299")
        self.assertEqual(order.customer_email, "priya@consumer.in")
        self.assertEqual(order.final_paid_amount, Decimal("100.00"))

    def test_consumer_dashboard_view_renders_with_orders_and_stats(self):
        """Verifies consumer portal dashboard shows active orders, savings, and farmer impact."""
        # Create an order for consumer
        order = ConsumerOrder.objects.create(
            user=self.consumer,
            customer_name="Priya Reddy",
            customer_phone="+919876543299",
            customer_email="priya@consumer.in",
            delivery_address="Jubilee Hills, Hyderabad",
            pincode="500033",
            total_amount=Decimal("120.00"),
            discount_amount=Decimal("20.00"),
            final_paid_amount=Decimal("100.00"),
            status=ConsumerOrder.Status.PAID_SETTLED,
        )
        ConsumerOrderItem.objects.create(
            order=order,
            item_type=ConsumerOrderItem.ItemType.PRODUCE,
            crop=self.crop,
            farmer=self.farmer,
            item_name="Organic Roma Tomato",
            quantity=Decimal("4.00"),
            unit="kg",
            unit_price=Decimal("25.00"),
            subtotal=Decimal("100.00"),
            farmer_payout=Decimal("92.00"),
            is_settled_to_wallet=True,
        )

        self.client.force_login(self.consumer)
        response = self.client.get(reverse("consumer_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/consumer_dashboard.html")

        # Context metrics
        self.assertEqual(response.context["total_orders"], 1)
        self.assertEqual(response.context["total_spent"], Decimal("100.00"))
        self.assertEqual(response.context["total_discount_saved"], Decimal("20.00"))
        self.assertEqual(response.context["total_farmer_payout"], Decimal("92.00"))

        # HTML assertions
        self.assertContains(response, order.order_id)
        self.assertContains(response, "Organic Roma Tomato")
        self.assertContains(response, "₹92.00")
        self.assertContains(response, "Rate Produce Freshness & Thank Farmer")

    def test_consumer_feedback_submission_and_direct_farmer_note(self):
        """Verifies submitting feedback stores ratings and direct farmer appreciation notes."""
        order = ConsumerOrder.objects.create(
            user=self.consumer,
            customer_name="Priya Reddy",
            customer_phone="+919876543299",
            customer_email="priya@consumer.in",
            delivery_address="Jubilee Hills, Hyderabad",
            pincode="500033",
            total_amount=Decimal("100.00"),
            final_paid_amount=Decimal("100.00"),
            status=ConsumerOrder.Status.DELIVERED,
        )

        self.client.force_login(self.consumer)
        feedback_data = {
            "rating": "5",
            "freshness_rating": "5",
            "delivery_rating": "5",
            "comment": "Absolutely crisp and flavorful tomatoes!",
            "farmer_note": "Thank you Ramesh ji for growing such pure, chemical-free food!",
        }

        res = self.client.post(
            reverse("consumer_add_feedback", args=[order.order_id]),
            feedback_data,
        )
        self.assertEqual(res.status_code, 302)

        feedback = ConsumerFeedback.objects.filter(order=order).first()
        self.assertIsNotNone(feedback)
        self.assertEqual(feedback.consumer, self.consumer)
        self.assertEqual(feedback.rating, 5)
        self.assertEqual(feedback.freshness_rating, 5)
        self.assertEqual(feedback.delivery_rating, 5)
        self.assertEqual(feedback.comment, "Absolutely crisp and flavorful tomatoes!")
        self.assertEqual(feedback.farmer_note, "Thank you Ramesh ji for growing such pure, chemical-free food!")

        # Verify rendered in dashboard
        dash_res = self.client.get(reverse("consumer_dashboard"))
        self.assertContains(dash_res, "Thank you Ramesh ji for growing such pure, chemical-free food!")
        self.assertContains(dash_res, "Shared with Farmer")

    def test_consumer_feedback_unauthorized_access_prevented(self):
        """Verifies that an unauthorized user cannot submit feedback on someone else's order."""
        other_user = User.objects.create_user(
            identifier="other@consumer.in",
            email="other@consumer.in",
            role=User.Role.CONSUMER,
            password="otherpassword",
        )
        order = ConsumerOrder.objects.create(
            user=self.consumer,
            customer_name="Priya Reddy",
            customer_phone="+919876543299",
            delivery_address="Jubilee Hills",
            total_amount=Decimal("50.00"),
            final_paid_amount=Decimal("50.00"),
            status=ConsumerOrder.Status.DELIVERED,
        )

        # Log in as other_user and attempt to post feedback for Priya's order
        self.client.force_login(other_user)
        res = self.client.post(
            reverse("consumer_add_feedback", args=[order.order_id]),
            {"rating": "1", "freshness_rating": "1", "delivery_rating": "1"},
        )
        self.assertRedirects(res, reverse("consumer_dashboard"))

        # Confirm no feedback was created
        self.assertFalse(ConsumerFeedback.objects.filter(order=order).exists())


class RetailerWholesaleComboTests(TestCase):
    """Verifies B2B Retailer Hub Curated Wholesale Combos and 1-Click Procurement."""

    def setUp(self):
        self.client = Client()
        self.farmer = User.objects.create_user(
            identifier="+919876543210",
            phone_number="+919876543210",
            role=User.Role.FARMER,
            first_name="Ramesh",
            last_name="Kumar",
        )
        self.retailer = User.objects.create_user(
            identifier="retailer@freshbazaar.in",
            email="retailer@freshbazaar.in",
            role=User.Role.RETAILER,
            first_name="Suresh",
            last_name="Reddy",
            address="FreshBazaar Mega Warehouse, Begumpet, Hyderabad",
        )
        self.consumer = User.objects.create_user(
            identifier="consumer@k2k.in",
            email="consumer@k2k.in",
            role=User.Role.CONSUMER,
            first_name="Priya",
        )
        self.hub = MicroHub.objects.create(
            name="Shamshabad Agritech Micro-Hub",
            code="HUB-HYD-01",
            location="Shamshabad",
            district="Rangareddy",
            state="Telangana",
            pincode="501218",
            capacity_kg=Decimal("50000.00"),
        )
        self.crop_tomato = Crop.objects.create(
            farmer=self.farmer,
            name="Field Tomato",
            code="CROP-TOM-TEST",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("30.00"),
            shelf_life_days=10,
        )
        self.crop_palak = Crop.objects.create(
            farmer=self.farmer,
            name="Spinach Palak",
            code="CROP-PLK-TEST",
            category=Crop.Category.VEGETABLE,
            base_price=Decimal("25.00"),
            shelf_life_days=6,
        )
        self.wholesale_combo = Kit.objects.create(
            code="KIT-B2B-TEST-50",
            name="Commercial Leafy Greens & Salad Pack (50kg)",
            category=Kit.Category.HERBS,
            description="High-turnover daily greens for supermarkets and hotel kitchens.",
            badge_text="20% WHOLESALE MARGIN",
            discount_percentage=Decimal("20.00"),
            bulk_weight_kg=Decimal("50.00"),
            origin_cluster="Medchal Peri-Urban FPO Cluster, Telangana",
            hub=self.hub,
            target_audience=Kit.TargetAudience.RETAILER,
            is_wholesale=True,
            is_active=True,
            tiered_pricing_json={"1-4": 1800, "5-9": 1650, "10+": 1500},
        )
        KitItem.objects.create(kit=self.wholesale_combo, crop=self.crop_palak, quantity_grams=30000)
        KitItem.objects.create(kit=self.wholesale_combo, crop=self.crop_tomato, quantity_grams=20000)

    def test_wholesale_combo_model_properties_and_tiers(self):
        """Verifies bulk weight, pricing tiers, and savings calculations."""
        combo = self.wholesale_combo
        self.assertTrue(combo.is_wholesale)
        self.assertEqual(combo.target_audience, Kit.TargetAudience.RETAILER)
        self.assertEqual(combo.get_total_weight_kg(), Decimal("50.00"))

        # Original: (30kg * 25) + (20kg * 30) = 750 + 600 = 1350.00
        self.assertEqual(combo.calculate_original_price(), Decimal("1350.00"))
        # Bundle: 1350 - 20% = 1080.00
        self.assertEqual(combo.calculate_bundle_price(), Decimal("1080.00"))
        self.assertEqual(combo.get_savings(), Decimal("270.00"))

        # Tiered pricing lookup
        self.assertEqual(combo.get_price_for_quantity(2), Decimal("1800.00"))
        self.assertEqual(combo.get_price_for_quantity(6), Decimal("1650.00"))
        self.assertEqual(combo.get_price_for_quantity(15), Decimal("1500.00"))
        self.assertIn("[B2B Bulk]", str(combo))

    def test_retailer_combos_view_access_control(self):
        """Ensures non-retailers cannot view the wholesale catalog, but retailers can."""
        url = reverse("retailer_combos")

        # Anonymous user redirected to login
        res_anon = self.client.get(url)
        self.assertEqual(res_anon.status_code, 302)

        # Consumer user denied (403 Forbidden)
        self.client.force_login(self.consumer)
        res_consumer = self.client.get(url)
        self.assertEqual(res_consumer.status_code, 403)

        # Authenticated Retailer granted access
        self.client.force_login(self.retailer)
        res_retailer = self.client.get(url)
        self.assertEqual(res_retailer.status_code, 200)
        self.assertContains(res_retailer, "Commercial Leafy Greens &amp; Salad Pack (50kg)")
        self.assertContains(res_retailer, "Medchal Peri-Urban FPO Cluster")

    def test_retailer_1click_purchase_bulk_combo(self):
        """Verifies 1-click bulk procurement creates RetailerBulkOrder, DemandOrder, and settles farmer."""
        self.client.force_login(self.retailer)
        url = reverse("retailer_purchase_combo", args=[self.wholesale_combo.id])

        res = self.client.post(url, {"quantity": 2})
        self.assertRedirects(res, reverse("retailer_combos"))

        # Verify RetailerBulkOrder
        bulk_order = RetailerBulkOrder.objects.filter(retailer=self.retailer).first()
        self.assertIsNotNone(bulk_order)
        self.assertEqual(bulk_order.combo, self.wholesale_combo)
        self.assertEqual(bulk_order.quantity, 2)
        self.assertEqual(bulk_order.unit_price, Decimal("1800.00"))
        self.assertEqual(bulk_order.total_price, Decimal("3600.00"))
        self.assertEqual(bulk_order.total_weight_kg, Decimal("100.00"))
        self.assertEqual(bulk_order.status, RetailerBulkOrder.Status.ALLOCATED)
        self.assertTrue(bulk_order.order_id.startswith("K2K-BLK-"))

        # Verify linked DemandOrder
        demand_order = bulk_order.demand_order
        self.assertIsNotNone(demand_order)
        self.assertEqual(demand_order.channel, DemandOrder.Channel.B2B)
        self.assertEqual(demand_order.required_volume_kg, Decimal("100.00"))
        self.assertEqual(demand_order.status, DemandOrder.Status.ALLOCATED)

        # Verify farmer wallet credited
        wallet = FarmerWallet.objects.get(farmer=self.farmer)
        self.assertGreater(wallet.current_balance, Decimal("0.00"))
        tx = WalletTransaction.objects.filter(wallet=wallet, description__contains=bulk_order.order_id).first()
        self.assertIsNotNone(tx)
        self.assertIn("B2B Wholesale Settlement", tx.description)

    def test_retailer_dashboard_displays_wholesale_combos(self):
        """Verifies the Retailer Dashboard includes the Curated Wholesale Combos grid."""
        self.client.force_login(self.retailer)
        res = self.client.get(reverse("retailer_dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("wholesale_combos", res.context)
        self.assertContains(res, "Wholesale Curated Combos")
        self.assertContains(res, "Commercial Leafy Greens &amp; Salad Pack (50kg)")


