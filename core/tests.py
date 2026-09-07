import base64
from decimal import Decimal
from django.contrib.auth import authenticate
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import Batch, Crop, DemandOrder, MicroHub, User, FarmerWallet, WalletTransaction, HarvestSchedule
from core.services import (
    allocate_supply_to_order,
    generate_transparent_pricing_breakdown,
    predict_demand,
    process_batch_payout,
    get_batch_traceability,
    mock_dynamic_route,
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

    def test_transcribe_audio_fallback_and_signature(self):
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
        self.assertTrue(any(crop_kw in res["response_text"] for crop_kw in ["Tomato", "Tomato Special", "टमाटर", "टमाटर स्पेशल"]))
        cleaned_sched = res["response_text"].replace(",", "")
        self.assertTrue(any(v in cleaned_sched for v in ["1200", "1,200", "सितंबर", "September", "कटाई", "harvest", "शेड्यूल"]))

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

    def test_farmer_audio_file_upload_success(self):
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



