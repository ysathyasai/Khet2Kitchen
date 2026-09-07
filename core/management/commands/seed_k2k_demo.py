from decimal import Decimal
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    Batch,
    Crop,
    DemandOrder,
    FarmerWallet,
    HarvestSchedule,
    InputSupply,
    Kit,
    KitItem,
    MicroHub,
    RecipeCombo,
    User,
    WalletTransaction,
)


class Command(BaseCommand):
    help = "Seeds comprehensive demo data for Project Khet2Kitchen (K2K) platform with localized TS/Hyderabad accounts."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("[K2K] Seeding Khet2Kitchen demo data..."))

        # 1. Admin / Superuser
        admin, created = User.objects.get_or_create(
            identifier="admin@k2k.org",
            defaults={
                "email": "admin@k2k.org",
                "role": User.Role.ADMIN,
                "first_name": "K2K",
                "last_name": "Command Admin",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin.set_password("admin1234")
            admin.save()
            self.stdout.write(self.style.SUCCESS("[OK] Created Admin: admin@k2k.org / admin1234"))

        # 2. Farmers (Authenticate via Mobile)
        farmer1, created = User.objects.get_or_create(
            identifier="+919876543210",
            defaults={
                "phone_number": "+919876543210",
                "role": User.Role.FARMER,
                "first_name": "Ramesh",
                "last_name": "Kumar",
                "state": "Maharashtra",
                "address": "Village Niphad, Taluka Niphad",
                "pincode": "422303",
            },
        )
        if created:
            farmer1.set_password("farmer1234")
            farmer1.save()

        farmer2, created = User.objects.get_or_create(
            identifier="+919876543211",
            defaults={
                "phone_number": "+919876543211",
                "role": User.Role.FARMER,
                "first_name": "Sunil",
                "last_name": "Patil",
                "state": "Maharashtra",
                "address": "Village Junnar, Pune Rural",
                "pincode": "410502",
            },
        )
        if created:
            farmer2.set_password("farmer1234")
            farmer2.save()
        self.stdout.write(self.style.SUCCESS("[OK] Created Farmers: +919876543210, +919876543211 (pwd: farmer1234)"))

        # 3. Retailers (Authenticate via Email)
        retailer1, created = User.objects.get_or_create(
            identifier="procure@freshbazaar.in",
            defaults={
                "email": "procure@freshbazaar.in",
                "role": User.Role.RETAILER,
                "first_name": "Ananya",
                "last_name": "Sharma (FreshBazaar Mumbai)",
                "state": "Maharashtra",
                "address": "Bandra Kurla Complex, Mumbai",
                "pincode": "400051",
            },
        )
        if created:
            retailer1.set_password("retailer1234")
            retailer1.save()

        # Localized Demo Retailer (Hyderabad, Telangana)
        retailer_hyd, created = User.objects.get_or_create(
            identifier="hyderabad@freshbazaar.in",
            defaults={
                "email": "hyderabad@freshbazaar.in",
                "role": User.Role.RETAILER,
                "first_name": "FreshBazaar",
                "last_name": "Hyderabad",
                "state": "Telangana",
                "address": "Secunderabad, Telangana",
                "pincode": "500003",
            },
        )
        if created:
            retailer_hyd.set_password("retailer1234")
            retailer_hyd.save()
        self.stdout.write(self.style.SUCCESS("[OK] Created Retailers: procure@freshbazaar.in, hyderabad@freshbazaar.in (pwd: retailer1234)"))

        # 4. Suppliers (Authenticate via Email)
        supplier1, created = User.objects.get_or_create(
            identifier="sales@bioagri.com",
            defaults={
                "email": "sales@bioagri.com",
                "role": User.Role.SUPPLIER,
                "first_name": "BioAgri",
                "last_name": "Solutions",
                "state": "Gujarat",
                "address": "GIDC Industrial Estate, Vadodara",
                "pincode": "390010",
            },
        )
        if created:
            supplier1.set_password("supplier1234")
            supplier1.save()

        # Localized Demo Supplier (Medchal, Telangana)
        supplier_ts, created = User.objects.get_or_create(
            identifier="sales@bioagri-ts.in",
            defaults={
                "email": "sales@bioagri-ts.in",
                "role": User.Role.SUPPLIER,
                "first_name": "BioAgri Solutions",
                "last_name": "TS",
                "state": "Telangana",
                "address": "Medchal, Telangana",
                "pincode": "501401",
            },
        )
        if created:
            supplier_ts.set_password("supplier1234")
            supplier_ts.save()
        self.stdout.write(self.style.SUCCESS("[OK] Created Suppliers: sales@bioagri.com, sales@bioagri-ts.in (pwd: supplier1234)"))

        # 5. MicroHubs
        hub1, _ = MicroHub.objects.get_or_create(
            code="HUB-NSK-01",
            defaults={
                "name": "Nashik Agro Cluster Hub #1",
                "location": "Gat No. 45, Dindori Road",
                "district": "Nashik",
                "state": "Maharashtra",
                "pincode": "422004",
                "capacity_kg": Decimal("25000.00"),
            },
        )
        hub2, _ = MicroHub.objects.get_or_create(
            code="HUB-PUN-02",
            defaults={
                "name": "Pune Western Ghats Hub #2",
                "location": "Plot 12, Manchar Agricultural Market",
                "district": "Pune",
                "state": "Maharashtra",
                "pincode": "410503",
                "capacity_kg": Decimal("30000.00"),
            },
        )
        hub_hyd, _ = MicroHub.objects.get_or_create(
            code="HUB-HYD-01",
            defaults={
                "name": "Hyderabad Agri-Rail Mega Hub #1",
                "location": "Kukatpally Wholesale Rail Siding",
                "district": "Hyderabad",
                "state": "Telangana",
                "pincode": "500072",
                "capacity_kg": Decimal("35000.00"),
            },
        )
        self.stdout.write(self.style.SUCCESS("[OK] Created Micro-Hubs: HUB-NSK-01, HUB-PUN-02, HUB-HYD-01"))

        # 6. Master Catalog Crops (Available for all B2B and AI systems)
        onion, _ = Crop.objects.get_or_create(
            code="CROP-ONION-01",
            defaults={
                "name": "Red Onion (Nashik Special)",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("28.00"),
                "shelf_life_days": 35,
            },
        )
        tomato, _ = Crop.objects.get_or_create(
            code="CROP-TOMATO-02",
            defaults={
                "name": "Roma Field Tomato",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("22.00"),
                "shelf_life_days": 10,
            },
        )
        mango, _ = Crop.objects.get_or_create(
            code="CROP-MANGO-03",
            defaults={
                "name": "Ratnagiri Alphonso Mango",
                "category": Crop.Category.FRUIT,
                "base_price": Decimal("180.00"),
                "shelf_life_days": 14,
            },
        )
        chilli, _ = Crop.objects.get_or_create(
            code="CROP-CHILLI-04",
            defaults={
                "name": "Warangal Teja Red Chilli",
                "category": Crop.Category.SPICE,
                "base_price": Decimal("165.00"),
                "shelf_life_days": 60,
            },
        )
        self.stdout.write(self.style.SUCCESS("[OK] Seeded Master Catalog Produce: Onion, Tomato, Mango, Chilli"))

        # 7. Demo Farmer's My Crops (Strictly Isolated to Demo Farmer 1)
        farmer_crops_data = [
            {
                "name": "Winter Wheat",
                "code": "CROP-WHT-01",
                "category": Crop.Category.GRAIN,
                "planted_date": "2023-10-15",
                "expected_yield_kg": Decimal("8000.00"),
                "status": "Growing",
                "base_price": Decimal("24.00"),
            },
            {
                "name": "Corn",
                "code": "CROP-CRN-01",
                "category": Crop.Category.GRAIN,
                "planted_date": "2024-04-20",
                "expected_yield_kg": Decimal("12000.00"),
                "status": "Growing",
                "base_price": Decimal("20.00"),
            },
            {
                "name": "Soybeans",
                "code": "CROP-SYB-01",
                "category": Crop.Category.PULSE,
                "planted_date": "2024-05-01",
                "expected_yield_kg": Decimal("10000.00"),
                "status": "Planting",
                "base_price": Decimal("46.00"),
            },
            {
                "name": "Barley",
                "code": "CROP-BRL-01",
                "category": Crop.Category.GRAIN,
                "planted_date": "2023-09-30",
                "expected_yield_kg": Decimal("6500.00"),
                "status": "Harvested",
                "base_price": Decimal("18.00"),
            },
            {
                "name": "Hybrid Tomato (Tamatar)",
                "code": "CROP-TMT-DEMO",
                "category": Crop.Category.VEGETABLE,
                "planted_date": "2026-04-10",
                "expected_yield_kg": Decimal("400.00"),
                "status": "At Hub (Graded)",
                "base_price": Decimal("22.00"),
            },
        ]

        demo_crops = {}
        for cdata in farmer_crops_data:
            crop_obj, _ = Crop.objects.get_or_create(
                farmer=farmer1,
                name=cdata["name"],
                defaults={
                    "code": cdata["code"],
                    "category": cdata["category"],
                    "planted_date": cdata["planted_date"],
                    "expected_yield_kg": cdata["expected_yield_kg"],
                    "status": cdata["status"],
                    "base_price": cdata["base_price"],
                },
            )
            demo_crops[cdata["name"]] = crop_obj
        self.stdout.write(self.style.SUCCESS("[OK] Seeded 5 Demo Crops strictly assigned to Demo Farmer (+919876543210)"))

        # 8. Batches
        batch1, _ = Batch.objects.get_or_create(
            batch_id="K2K-BTH-20260906-001A",
            defaults={
                "farmer": farmer1,
                "hub": hub1,
                "crop": onion,
                "volume_kg": Decimal("1500.00"),
                "ai_grade": Batch.Grade.GRADE_A,
                "ai_confidence_score": Decimal("97.80"),
                "status": Batch.Status.QUALITY_INSPECTED,
            },
        )
        batch2, _ = Batch.objects.get_or_create(
            batch_id="K2K-BTH-20260906-002B",
            defaults={
                "farmer": farmer2,
                "hub": hub2,
                "crop": tomato,
                "volume_kg": Decimal("850.00"),
                "ai_grade": Batch.Grade.GRADE_B,
                "ai_confidence_score": Decimal("94.20"),
                "status": Batch.Status.ALLOCATED,
            },
        )
        # Link Batch for the active demo crop
        if "Hybrid Tomato (Tamatar)" in demo_crops:
            Batch.objects.get_or_create(
                batch_id="K2K-BTH-20260907-TMT-DEMO",
                defaults={
                    "farmer": farmer1,
                    "hub": hub1,
                    "crop": demo_crops["Hybrid Tomato (Tamatar)"],
                    "volume_kg": Decimal("400.00"),
                    "ai_grade": Batch.Grade.GRADE_A,
                    "ai_confidence_score": Decimal("98.60"),
                    "status": Batch.Status.QUALITY_INSPECTED,
                },
            )
        self.stdout.write(self.style.SUCCESS("[OK] Created Harvest Batches with AI Quality Grading"))

        # 9. Demand Orders (Retailers)
        # Mumbai Retailer Orders
        DemandOrder.objects.get_or_create(
            order_id="K2K-ORD-20260906-001X",
            defaults={
                "retailer": retailer1,
                "crop": onion,
                "required_volume_kg": Decimal("1000.00"),
                "required_date": (timezone.now() + timedelta(days=2)).date(),
                "status": DemandOrder.Status.PENDING,
                "delivery_address": "FreshBazaar Distribution Center, Kurla, Mumbai",
            },
        )

        # Localized Telangana Retailer Orders (Strictly Isolated to retailer_hyd)
        DemandOrder.objects.get_or_create(
            order_id="K2K-ORD-HYD-001",
            defaults={
                "retailer": retailer_hyd,
                "crop": tomato,
                "required_volume_kg": Decimal("500.00"),
                "required_date": (timezone.now() + timedelta(days=2)).date(),
                "status": DemandOrder.Status.PENDING,
                "delivery_address": "FreshBazaar Central Warehouse, Paradise Circle, Secunderabad, PIN: 500003",
            },
        )
        DemandOrder.objects.get_or_create(
            order_id="K2K-ORD-HYD-002",
            defaults={
                "retailer": retailer_hyd,
                "crop": onion,
                "required_volume_kg": Decimal("1200.00"),
                "required_date": (timezone.now() + timedelta(days=4)).date(),
                "status": DemandOrder.Status.ALLOCATED,
                "delivery_address": "FreshBazaar Retail Depot, Begumpet, Hyderabad, PIN: 500016",
            },
        )
        self.stdout.write(self.style.SUCCESS("[OK] Created Localized Telangana Retailer Demand Orders"))

        # 10. Localized Supplier Inventory (Strictly Isolated to supplier_ts)
        InputSupply.objects.get_or_create(
            supplier=supplier_ts,
            name="Organic Neem Bio-Fertilizer TS",
            defaults={
                "category": InputSupply.Category.FERTILIZER,
                "quantity": Decimal("150.00"),
                "unit": "Bags",
                "price_per_unit": Decimal("480.00"),
                "hub": hub_hyd,
                "status": InputSupply.Status.IN_STOCK,
                "description": "Cold-pressed organic neem cake fortified with Trichoderma. Specially formulated for Telangana red & black cotton soils.",
            },
        )
        InputSupply.objects.get_or_create(
            supplier=supplier_ts,
            name="Telangana Desi Red Chilli Seeds (Warangal Hybrid)",
            defaults={
                "category": InputSupply.Category.SEED,
                "quantity": Decimal("80.00"),
                "unit": "Packets",
                "price_per_unit": Decimal("220.00"),
                "hub": hub_hyd,
                "status": InputSupply.Status.CONSIGNED,
                "description": "High-germination certified Warangal hybrid seed packets with optimal drought resistance.",
            },
        )
        self.stdout.write(self.style.SUCCESS("[OK] Seeded Localized Supplier Inventory for BioAgri Solutions TS (Medchal)"))

        # 11. Digital Wallets & Ledgers
        wallet1, _ = FarmerWallet.objects.get_or_create(
            farmer=farmer1,
            defaults={"current_balance": Decimal("0.00")},
        )
        if wallet1.transactions.count() == 0:
            wallet1.credit(
                Decimal("48150.00"),
                f"Direct Settlement for Batch {batch1.batch_id} (Grade A, 1500 kg @ INR 32.10/kg)"
            )
            wallet1.debit(
                Decimal("10000.00"),
                f"Instant IMPS settlement to {farmer1.phone_number}@upi"
            )
            self.stdout.write(self.style.SUCCESS(f"[OK] Seeded Wallet for {farmer1.get_full_name()}: INR {wallet1.current_balance}"))

        wallet2, _ = FarmerWallet.objects.get_or_create(
            farmer=farmer2,
            defaults={"current_balance": Decimal("0.00")},
        )
        if wallet2.transactions.count() == 0:
            wallet2.credit(
                Decimal("17425.00"),
                f"Direct Settlement for Batch {batch2.batch_id} (Grade B, 850 kg @ INR 20.50/kg)"
            )
            self.stdout.write(self.style.SUCCESS(f"[OK] Seeded Wallet for {farmer2.get_full_name()}: INR {wallet2.current_balance}"))

        # 12. AI Harvest Schedules
        HarvestSchedule.objects.get_or_create(
            farmer=farmer1,
            crop=onion,
            recommended_date=(timezone.now() + timedelta(days=4)).date(),
            defaults={
                "target_volume_kg": Decimal("2500.00"),
                "status": HarvestSchedule.Status.PENDING,
                "notes": "Peak wholesale demand anticipated across Hyderabad and Mumbai retailers. Dry weather window optimal.",
            },
        )
        HarvestSchedule.objects.get_or_create(
            farmer=farmer1,
            crop=tomato,
            recommended_date=(timezone.now() + timedelta(days=8)).date(),
            defaults={
                "target_volume_kg": Decimal("1200.00"),
                "status": HarvestSchedule.Status.PENDING,
                "notes": "Optimal Brix index expected. Schedule early morning harvest to preserve firmness.",
            },
        )
        self.stdout.write(self.style.SUCCESS("[OK] Seeded AI Harvest Schedules for Farmers"))

        # 13. Pre-Packaged Vegetable Kits (D2C Marketplace)
        kit_sambar, _ = Kit.objects.get_or_create(
            code="KIT-D2C-SBR-01",
            defaults={
                "name": "Sambar Essentials Farm Kit",
                "category": Kit.Category.VEGETABLE,
                "description": "Handpicked fresh vegetables for authentic South Indian Sambar: juicy field tomatoes, piquant red onions, and hot green chillies directly from farmer Ramesh Kumar.",
                "discount_percentage": Decimal("15.00"),
                "badge_text": "15% OFF • Best Seller",
                "is_active": True,
            },
        )
        KitItem.objects.get_or_create(kit=kit_sambar, crop=tomato, defaults={"quantity_grams": 1000})
        KitItem.objects.get_or_create(kit=kit_sambar, crop=onion, defaults={"quantity_grams": 500})
        KitItem.objects.get_or_create(kit=kit_sambar, crop=chilli, defaults={"quantity_grams": 100})

        kit_curry, _ = Kit.objects.get_or_create(
            code="KIT-D2C-CRY-01",
            defaults={
                "name": "Daily Curry Veggie Box",
                "category": Kit.Category.VEGETABLE,
                "description": "Essential daily staple box containing premium Nashik red onions, field tomatoes, and fragrant chillies for wholesome everyday family meals.",
                "discount_percentage": Decimal("12.00"),
                "badge_text": "Kitchen Essential",
                "is_active": True,
            },
        )
        KitItem.objects.get_or_create(kit=kit_curry, crop=onion, defaults={"quantity_grams": 1000})
        KitItem.objects.get_or_create(kit=kit_curry, crop=tomato, defaults={"quantity_grams": 800})
        KitItem.objects.get_or_create(kit=kit_curry, crop=chilli, defaults={"quantity_grams": 80})

        kit_leafy, _ = Kit.objects.get_or_create(
            code="KIT-D2C-GRN-01",
            defaults={
                "name": "Leafy Greens & Immunity Kit",
                "category": Kit.Category.HERBS,
                "description": "Rich in dietary fiber and essential micronutrients. Freshly harvested greens, tomatoes, and organic chillies.",
                "discount_percentage": Decimal("15.00"),
                "badge_text": "Farm Fresh • 15% OFF",
                "is_active": True,
            },
        )
        KitItem.objects.get_or_create(kit=kit_leafy, crop=tomato, defaults={"quantity_grams": 600})
        KitItem.objects.get_or_create(kit=kit_leafy, crop=onion, defaults={"quantity_grams": 400})
        KitItem.objects.get_or_create(kit=kit_leafy, crop=chilli, defaults={"quantity_grams": 120})

        kit_fruit, _ = Kit.objects.get_or_create(
            code="KIT-D2C-SLD-01",
            defaults={
                "name": "Salad & Immunity Fruit Box",
                "category": Kit.Category.FRUIT,
                "description": "Nutrient-dense raw salad basket with Ratnagiri sweet mangoes, juicy field tomatoes, and mild salad onions.",
                "discount_percentage": Decimal("10.00"),
                "badge_text": "10% OFF • Vitamin C Boost",
                "is_active": True,
            },
        )
        KitItem.objects.get_or_create(kit=kit_fruit, crop=mango, defaults={"quantity_grams": 1000})
        KitItem.objects.get_or_create(kit=kit_fruit, crop=tomato, defaults={"quantity_grams": 500})
        KitItem.objects.get_or_create(kit=kit_fruit, crop=onion, defaults={"quantity_grams": 300})

        self.stdout.write(self.style.SUCCESS("[OK] Seeded 4 D2C Consumer Kits (Sambar, Curry Box, Leafy Greens, Fruit Box)"))

        # 14. Demo Pre-Generated Recipe Combo
        RecipeCombo.objects.get_or_create(
            dish_name="Authentic South Indian Sambar",
            servings=4,
            defaults={
                "combo_id": "K2K-CMB-SAMBAR-DEMO",
                "prep_time_minutes": 25,
                "culinary_notes": "A nutrient-rich lentil and vegetable stew with a fragrant tamarind-coriander temper.",
                "total_weight_kg": Decimal("0.60"),
                "original_price": Decimal("21.85"),
                "discount_percentage": Decimal("15.00"),
                "combo_price": Decimal("18.57"),
                "items_breakdown": [
                    {"crop_name": "Tomato", "quantity_grams": 300, "role": "Broth base", "standalone_price": 6.60},
                    {"crop_name": "Onion", "quantity_grams": 250, "role": "Savory depth", "standalone_price": 7.00},
                    {"crop_name": "Chilli", "quantity_grams": 50, "role": "Piquant spice", "standalone_price": 8.25},
                ],
            },
        )
        self.stdout.write(self.style.SUCCESS("[OK] Seeded Demo AI Recipe Combo: Authentic South Indian Sambar (4 Servings)"))

        self.stdout.write(self.style.SUCCESS("\n[SUCCESS] Localized demo dataset seeded successfully with full multi-role data isolation!"))

