from decimal import Decimal
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

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

        # 5. Consumers (Authenticate via Mobile or Email)
        consumer1, created = User.objects.get_or_create(
            identifier="consumer@k2k.in",
            defaults={
                "email": "consumer@k2k.in",
                "phone_number": "+919876543299",
                "role": User.Role.CONSUMER,
                "first_name": "Priya",
                "last_name": "Reddy",
                "state": "Telangana",
                "address": "Jubilee Hills, Road No. 36, Hyderabad",
                "pincode": "500033",
            },
        )
        if created:
            consumer1.set_password("consumer1234")
            consumer1.save()
        self.stdout.write(self.style.SUCCESS("[OK] Created Consumer: consumer@k2k.in (pwd: consumer1234)"))

        # 6. MicroHubs
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
        potato, _ = Crop.objects.get_or_create(
            code="CROP-POTATO-05",
            defaults={
                "name": "Jyoti Field Potato",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("24.00"),
                "shelf_life_days": 40,
            },
        )
        cucumber, _ = Crop.objects.get_or_create(
            code="CROP-CUCUMBER-06",
            defaults={
                "name": "English Crisp Cucumber",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("26.00"),
                "shelf_life_days": 12,
            },
        )
        carrot, _ = Crop.objects.get_or_create(
            code="CROP-CARROT-07",
            defaults={
                "name": "Red Ooty Carrot",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("35.00"),
                "shelf_life_days": 20,
            },
        )
        capsicum, _ = Crop.objects.get_or_create(
            code="CROP-CAPSICUM-08",
            defaults={
                "name": "Green Bell Capsicum",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("45.00"),
                "shelf_life_days": 14,
            },
        )
        palak, _ = Crop.objects.get_or_create(
            code="CROP-PALAK-09",
            defaults={
                "name": "Fresh Farm Palak (Spinach)",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("25.00"),
                "shelf_life_days": 6,
            },
        )
        coriander, _ = Crop.objects.get_or_create(
            code="CROP-CORIANDER-10",
            defaults={
                "name": "Aromatic Coriander Greens",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("40.00"),
                "shelf_life_days": 5,
            },
        )
        mint, _ = Crop.objects.get_or_create(
            code="CROP-MINT-11",
            defaults={
                "name": "Field Fresh Pudina (Mint)",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("38.00"),
                "shelf_life_days": 6,
            },
        )
        ginger, _ = Crop.objects.get_or_create(
            code="CROP-GINGER-12",
            defaults={
                "name": "Mahabaleshwar Fresh Ginger",
                "category": Crop.Category.SPICE,
                "base_price": Decimal("90.00"),
                "shelf_life_days": 45,
            },
        )
        garlic, _ = Crop.objects.get_or_create(
            code="CROP-GARLIC-13",
            defaults={
                "name": "Mandsaur Grade-A Garlic",
                "category": Crop.Category.SPICE,
                "base_price": Decimal("120.00"),
                "shelf_life_days": 60,
            },
        )
        self.stdout.write(self.style.SUCCESS("[OK] Seeded Master Catalog Produce: Onion, Tomato, Mango, Chilli, Potato, Cucumber, Carrot, Capsicum, Palak, Coriander, Mint, Ginger, Garlic"))

        # 6b. Everyday Consumer-Grade Loose Produce (Small-Quantity Retail Groceries)
        loose_items_data = [
            {
                "code": "CROP-LOOSE-TMT-500G",
                "name": "Fresh Farm Tomatoes (500g)",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("18.00"),
                "shelf_life_days": 8,
                "farmer": farmer1,
            },
            {
                "code": "CROP-LOOSE-CHL-250G",
                "name": "Piquant Green Chillies (250g)",
                "category": Crop.Category.SPICE,
                "base_price": Decimal("14.00"),
                "shelf_life_days": 12,
                "farmer": farmer1,
            },
            {
                "code": "CROP-LOOSE-ONN-1KG",
                "name": "Nashik Red Onions (1kg Net Bag)",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("32.00"),
                "shelf_life_days": 30,
                "farmer": farmer1,
            },
            {
                "code": "CROP-LOOSE-POT-1KG",
                "name": "Jyoti Farm Potatoes (1kg Bag)",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("26.00"),
                "shelf_life_days": 35,
                "farmer": farmer1,
            },
            {
                "code": "CROP-LOOSE-PLK-250G",
                "name": "Tender Palak / Spinach (250g Bunch)",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("15.00"),
                "shelf_life_days": 5,
                "farmer": farmer1,
            },
            {
                "code": "CROP-LOOSE-CUC-500G",
                "name": "Crisp Salad Cucumbers (500g)",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("20.00"),
                "shelf_life_days": 10,
                "farmer": farmer1,
            },
            {
                "code": "CROP-LOOSE-HRB-200G",
                "name": "Fresh Coriander & Mint Herbs (200g)",
                "category": Crop.Category.VEGETABLE,
                "base_price": Decimal("12.00"),
                "shelf_life_days": 5,
                "farmer": farmer1,
            },
        ]
        for l_data in loose_items_data:
            Crop.objects.update_or_create(
                code=l_data["code"],
                defaults={
                    "name": l_data["name"],
                    "category": l_data["category"],
                    "base_price": l_data["base_price"],
                    "shelf_life_days": l_data["shelf_life_days"],
                    "farmer": l_data["farmer"],
                    "is_active": True,
                    "status": "Harvested",
                },
            )
        self.stdout.write(self.style.SUCCESS(f"[OK] Seeded {len(loose_items_data)} Consumer-Grade Loose Produce Items (500g Tomatoes, 250g Green Chillies, 1kg Onions, etc.)"))

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

        # 14. Curated B2B Wholesale Combos for Retailers, Restaurants & Kiranas (12 Curated Packs)
        wholesale_combos_catalog = [
            {
                "code": "KIT-B2B-GRN-50",
                "name": "Commercial Leafy Greens Bulk Pack (50kg)",
                "category": Kit.Category.HERBS,
                "description": "High-turnover daily greens for supermarkets and hotel kitchens: fresh Palak, Mint, and Coriander harvested 4 hours prior to micro-hub aggregation.",
                "badge_text": "20% WHOLESALE MARGIN",
                "discount_percentage": Decimal("20.00"),
                "bulk_weight_kg": Decimal("50.00"),
                "origin_cluster": "Medchal Peri-Urban FPO Cluster, Telangana",
                "hub": hub_hyd,
                "tiered_pricing_json": {"1-4": 1800, "5-9": 1650, "10+": 1500},
                "items": [(palak, 25000), (coriander, 15000), (mint, 10000)],
            },
            {
                "code": "KIT-B2B-SLD-40",
                "name": "Hotel & Restaurant Salad Essentials (40kg)",
                "category": Kit.Category.VEGETABLE,
                "description": "Crisp salad-grade cucumbers, firm Roma tomatoes, and green capsicums tailored for QSR burger, sandwich, and buffet salad bars.",
                "badge_text": "QSR & Hotel Choice",
                "discount_percentage": Decimal("18.00"),
                "bulk_weight_kg": Decimal("40.00"),
                "origin_cluster": "Shamshabad Greenhouse Hub, Hyderabad",
                "hub": hub_hyd,
                "tiered_pricing_json": {"1-4": 2200, "5-9": 2050, "10+": 1900},
                "items": [(cucumber, 15000), (tomato, 15000), (capsicum, 10000)],
            },
            {
                "code": "KIT-B2B-ROOT-100",
                "name": "Daily Kirana Root Veggie Crate (100kg)",
                "category": Kit.Category.VEGETABLE,
                "description": "High-durability commercial crate of red onions, Jyoti potatoes, and fresh carrots. Zero grading loss with uniform size distribution.",
                "badge_text": "High Volume Staple",
                "discount_percentage": Decimal("22.00"),
                "bulk_weight_kg": Decimal("100.00"),
                "origin_cluster": "Niphad Onion-Potato Collective, Maharashtra",
                "hub": hub1,
                "tiered_pricing_json": {"1-4": 2600, "5-9": 2400, "10+": 2250},
                "items": [(onion, 50000), (potato, 35000), (carrot, 15000)],
            },
            {
                "code": "KIT-B2B-SPICE-30",
                "name": "Biryani & Curry Masala Aromatics Bulk Pack (30kg)",
                "category": Kit.Category.HERBS,
                "description": "Essential aromatics for cloud kitchens and caterers: potent Warangal green chillies, aromatic mint, garlic, and ginger.",
                "badge_text": "Caterer Favorite",
                "discount_percentage": Decimal("15.00"),
                "bulk_weight_kg": Decimal("30.00"),
                "origin_cluster": "Warangal & Ranga Reddy Spices Cluster",
                "hub": hub_hyd,
                "tiered_pricing_json": {"1-4": 3400, "5-9": 3200, "10+": 3000},
                "items": [(chilli, 10000), (mint, 8000), (ginger, 6000), (garlic, 6000)],
            },
            {
                "code": "KIT-B2B-QSR-35",
                "name": "QSR Burger & Sandwich Veggie Bundle (35kg)",
                "category": Kit.Category.COMBO,
                "description": "Selected uniform slicing tomatoes, crunchy salad cucumbers, and bell capsicum for fast-food chains and urban cafes.",
                "badge_text": "Grade-A Crisp",
                "discount_percentage": Decimal("17.00"),
                "bulk_weight_kg": Decimal("35.00"),
                "origin_cluster": "Patancheru Hydroponic Corridor",
                "hub": hub_hyd,
                "tiered_pricing_json": {"1-4": 2100, "5-9": 1950, "10+": 1800},
                "items": [(tomato, 15000), (cucumber, 12000), (capsicum, 8000)],
            },
            {
                "code": "KIT-B2B-SBR-60",
                "name": "South Indian Tiffin & Sambar Bulk Crate (60kg)",
                "category": Kit.Category.VEGETABLE,
                "description": "Designed for tiffin centers and breakfast joints: heavy-pulp tomatoes, sambar onions, green chillies, and fresh coriander.",
                "badge_text": "Tiffin Center Special",
                "discount_percentage": Decimal("20.00"),
                "bulk_weight_kg": Decimal("60.00"),
                "origin_cluster": "Mahbubnagar FPO Cluster, Telangana",
                "hub": hub_hyd,
                "tiered_pricing_json": {"1-4": 2400, "5-9": 2250, "10+": 2100},
                "items": [(tomato, 25000), (onion, 20000), (chilli, 5000), (coriander, 10000)],
            },
            {
                "code": "KIT-B2B-STREET-80",
                "name": "Poha, Chaat & Street Food Staples (80kg)",
                "category": Kit.Category.VEGETABLE,
                "description": "Bulk street-food cart and chaat essentials: bulk potatoes, chopped-ready onions, piquant chillies, and coriander bundles.",
                "badge_text": "25% Wholesale Margin",
                "discount_percentage": Decimal("25.00"),
                "bulk_weight_kg": Decimal("80.00"),
                "origin_cluster": "Vikarabad Agro-Cluster, Telangana",
                "hub": hub_hyd,
                "tiered_pricing_json": {"1-4": 2200, "5-9": 2000, "10+": 1850},
                "items": [(potato, 40000), (onion, 30000), (chilli, 5000), (coriander, 5000)],
            },
            {
                "code": "KIT-B2B-JUICE-50",
                "name": "Juice Bar & Café Seasonal Fruit Bulk Box (50kg)",
                "category": Kit.Category.FRUIT,
                "description": "Sweet, naturally ripened Ratnagiri and Jagtial mangoes and seasonal fruits directly from certified farmer orchards.",
                "badge_text": "Direct Orchard Sourced",
                "discount_percentage": Decimal("15.00"),
                "bulk_weight_kg": Decimal("50.00"),
                "origin_cluster": "Jagtial Fruit Farmers Producer Co",
                "hub": hub_hyd,
                "tiered_pricing_json": {"1-4": 4500, "5-9": 4200, "10+": 3900},
                "items": [(mango, 35000), (carrot, 15000)],
            },
            {
                "code": "KIT-B2B-EXOTIC-25",
                "name": "Exotic Kitchen & Continental Veg Pack (25kg)",
                "category": Kit.Category.COMBO,
                "description": "Specialty produce for continental restaurants: bell capsicums, crisp cucumbers, carrots, and hydroponic herbs.",
                "badge_text": "Fine Dining Choice",
                "discount_percentage": Decimal("18.00"),
                "bulk_weight_kg": Decimal("25.00"),
                "origin_cluster": "Ooty-Shadnagar Cold-Chain Hub",
                "hub": hub_hyd,
                "tiered_pricing_json": {"1-4": 2800, "5-9": 2600, "10+": 2400},
                "items": [(capsicum, 10000), (cucumber, 8000), (carrot, 7000)],
            },
            {
                "code": "KIT-B2B-DIET-30",
                "name": "Diet & Health Food Kitchens Bundle (30kg)",
                "category": Kit.Category.VEGETABLE,
                "description": "Nutrient-dense spinach greens, organic carrots, salad tomatoes, and mint for modern health cafes and meal-prep businesses.",
                "badge_text": "Organic Certified Batch",
                "discount_percentage": Decimal("16.00"),
                "bulk_weight_kg": Decimal("30.00"),
                "origin_cluster": "Medak Organic Farmer Collective",
                "hub": hub_hyd,
                "tiered_pricing_json": {"1-4": 1900, "5-9": 1750, "10+": 1600},
                "items": [(palak, 12000), (carrot, 10000), (tomato, 5000), (mint, 3000)],
            },
            {
                "code": "KIT-B2B-MEGA-150",
                "name": "Dhaba & Caterers Mega Onion-Tomato-Potato Base (150kg)",
                "category": Kit.Category.VEGETABLE,
                "description": "Heavy-volume base produce for large wedding caterers, canteens, and dhabas. Pre-palletized for fast forklift handling.",
                "badge_text": "Mega Bulk Value",
                "discount_percentage": Decimal("24.00"),
                "bulk_weight_kg": Decimal("150.00"),
                "origin_cluster": "Nizamabad & Nashik Aggregation Belt",
                "hub": hub1,
                "tiered_pricing_json": {"1-4": 3800, "5-9": 3500, "10+": 3200},
                "items": [(onion, 60000), (potato, 60000), (tomato, 30000)],
            },
            {
                "code": "KIT-B2B-HERB-15",
                "name": "Fresh Herbs & Microgreens Gourmet Pack (15kg)",
                "category": Kit.Category.HERBS,
                "description": "Hyper-fresh fragrant herbs including fresh coriander, field mint, and green chillies packed in humidity-retaining bio-crates.",
                "badge_text": "Ultra Fresh 4hr Harvest",
                "discount_percentage": Decimal("20.00"),
                "bulk_weight_kg": Decimal("15.00"),
                "origin_cluster": "Hyderabad Peri-Urban Hydroponic Greens",
                "hub": hub_hyd,
                "tiered_pricing_json": {"1-4": 1400, "5-9": 1300, "10+": 1200},
                "items": [(coriander, 7000), (mint, 5000), (chilli, 3000)],
            },
        ]

        first_wholesale_combo = None
        for c_data in wholesale_combos_catalog:
            combo_obj, _ = Kit.objects.update_or_create(
                code=c_data["code"],
                defaults={
                    "name": c_data["name"],
                    "category": c_data["category"],
                    "description": c_data["description"],
                    "badge_text": c_data["badge_text"],
                    "discount_percentage": c_data["discount_percentage"],
                    "bulk_weight_kg": c_data["bulk_weight_kg"],
                    "origin_cluster": c_data["origin_cluster"],
                    "hub": c_data["hub"],
                    "tiered_pricing_json": c_data["tiered_pricing_json"],
                    "target_audience": Kit.TargetAudience.RETAILER,
                    "is_wholesale": True,
                    "is_active": True,
                },
            )
            if not first_wholesale_combo:
                first_wholesale_combo = combo_obj
            for item_crop, qty_g in c_data["items"]:
                KitItem.objects.update_or_create(
                    kit=combo_obj,
                    crop=item_crop,
                    defaults={"quantity_grams": qty_g},
                )

        self.stdout.write(self.style.SUCCESS(f"[OK] Seeded {len(wholesale_combos_catalog)} Curated B2B Wholesale Combos for Retailers"))

        # Seed sample RetailerBulkOrder for Suresh Reddy (retailer1)
        if first_wholesale_combo:
            unit_price = first_wholesale_combo.get_price_for_quantity(2)
            total_price = (unit_price * Decimal("2.00")).quantize(Decimal("0.01"))
            total_weight = (first_wholesale_combo.get_total_weight_kg() * Decimal("2.00")).quantize(Decimal("0.01"))

            # Create linked DemandOrder
            demand_b2b_sample, _ = DemandOrder.objects.update_or_create(
                order_id="K2K-ORD-B2B-DEMO-BLK1",
                defaults={
                    "retailer": retailer1,
                    "crop": tomato,
                    "channel": DemandOrder.Channel.B2B,
                    "required_volume_kg": total_weight,
                    "target_price_per_kg": (total_price / total_weight).quantize(Decimal("0.01")),
                    "delivery_community_name": first_wholesale_combo.origin_cluster,
                    "num_households": 1,
                    "required_date": timezone.now().date() + timedelta(days=2),
                    "status": DemandOrder.Status.ALLOCATED,
                    "delivery_address": "FreshBazaar Central Warehouse, Begumpet, Hyderabad",
                },
            )

            RetailerBulkOrder.objects.update_or_create(
                order_id="K2K-BLK-DEMO-001",
                defaults={
                    "retailer": retailer1,
                    "combo": first_wholesale_combo,
                    "quantity": 2,
                    "unit_price": unit_price,
                    "total_price": total_price,
                    "total_weight_kg": total_weight,
                    "status": RetailerBulkOrder.Status.ALLOCATED,
                    "demand_order": demand_b2b_sample,
                    "hub": first_wholesale_combo.hub,
                    "payment_status": "PAID_INSTANT",
                    "payment_ref": "UPI-B2B-HYD-981245",
                    "delivery_address": "FreshBazaar Central Warehouse, Begumpet, Hyderabad",
                },
            )
            self.stdout.write(self.style.SUCCESS("[OK] Seeded Sample B2B Retailer Bulk Order for FreshBazaar Retailer"))

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

        # 15. Seed Sample Consumer Order & Feedback for Demo Consumer
        demo_consumer_order, o_created = ConsumerOrder.objects.get_or_create(
            order_id="K2K-ORD-DEMO-001",
            defaults={
                "user": consumer1,
                "customer_name": "Priya Reddy",
                "customer_phone": "+919876543299",
                "customer_email": "consumer@k2k.in",
                "delivery_address": "Flat 402, Green Meadows, Jubilee Hills Road No. 36, Hyderabad",
                "pincode": "500033",
                "total_amount": Decimal("185.00"),
                "discount_amount": Decimal("27.75"),
                "final_paid_amount": Decimal("157.25"),
                "status": ConsumerOrder.Status.DELIVERED,
                "payment_method": "UPI_INSTANT",
            },
        )
        if o_created:
            ConsumerOrderItem.objects.create(
                order=demo_consumer_order,
                item_type=ConsumerOrderItem.ItemType.KIT,
                kit=kit_sambar,
                farmer=farmer1,
                item_name="Sambar Essentials Farm Kit",
                quantity=Decimal("1.00"),
                unit="kit",
                unit_price=Decimal("157.25"),
                subtotal=Decimal("157.25"),
                farmer_payout=Decimal("141.50"),
                is_settled_to_wallet=True,
            )
            ConsumerFeedback.objects.create(
                order=demo_consumer_order,
                consumer=consumer1,
                rating=5,
                freshness_rating=5,
                delivery_rating=5,
                comment="The farm tomatoes arrived dewy and firm! The aroma reminded me of homegrown vegetables from my grandmother's village.",
                farmer_note="Dear Ramesh ji, thank you for waking up early to harvest these vegetables. We can taste your hard work in every bite of our dinner!",
            )
            self.stdout.write(self.style.SUCCESS("[OK] Seeded Sample Consumer Order & Feedback for Priya Reddy"))

        self.stdout.write(self.style.SUCCESS("\n[SUCCESS] Localized demo dataset seeded successfully with full multi-role data isolation!"))

