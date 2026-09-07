from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from core.models import User, MicroHub, Crop, Batch, DemandOrder, FarmerWallet, WalletTransaction, HarvestSchedule


class Command(BaseCommand):
    help = "Seeds initial demo data for Project Khet2Kitchen (K2K) platform."

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
                "last_name": "Sharma (FreshBazaar)",
                "state": "Maharashtra",
                "address": "Bandra Kurla Complex, Mumbai",
                "pincode": "400051",
            },
        )
        if created:
            retailer1.set_password("retailer1234")
            retailer1.save()

        retailer2, created = User.objects.get_or_create(
            identifier="orders@quickmart.in",
            defaults={
                "email": "orders@quickmart.in",
                "role": User.Role.RETAILER,
                "first_name": "Vikram",
                "last_name": "Mehta (QuickMart)",
                "state": "Maharashtra",
                "address": "Andheri East, Mumbai",
                "pincode": "400069",
            },
        )
        if created:
            retailer2.set_password("retailer1234")
            retailer2.save()
        self.stdout.write(self.style.SUCCESS("[OK] Created Retailers: procure@freshbazaar.in, orders@quickmart.in (pwd: retailer1234)"))

        # 4. Supplier
        supplier, created = User.objects.get_or_create(
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
            supplier.set_password("supplier1234")
            supplier.save()
        self.stdout.write(self.style.SUCCESS("[OK] Created Supplier: sales@bioagri.com (pwd: supplier1234)"))

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
        self.stdout.write(self.style.SUCCESS("[OK] Created Micro-Hubs: HUB-NSK-01, HUB-PUN-02"))

        # 6. Crops
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
        self.stdout.write(self.style.SUCCESS("[OK] Created Crops: Onion, Tomato, Alphonso Mango"))

        # 7. Batches
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
        self.stdout.write(self.style.SUCCESS("[OK] Created Harvest Batches with AI Quality Grading"))

        # 8. Demand Orders
        order1, _ = DemandOrder.objects.get_or_create(
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
        order2, _ = DemandOrder.objects.get_or_create(
            order_id="K2K-ORD-20260906-002Y",
            defaults={
                "retailer": retailer2,
                "crop": tomato,
                "required_volume_kg": Decimal("500.00"),
                "required_date": (timezone.now() + timedelta(days=1)).date(),
                "status": DemandOrder.Status.ALLOCATED,
                "delivery_address": "QuickMart Hub, Vashi APMC Sector 19, Navi Mumbai",
            },
        )
        self.stdout.write(self.style.SUCCESS("[OK] Created Retailer Demand Orders"))

        # 9. Digital Wallets & Ledgers
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

        # 10. AI Harvest Schedules
        HarvestSchedule.objects.get_or_create(
            farmer=farmer1,
            crop=onion,
            recommended_date=(timezone.now() + timedelta(days=4)).date(),
            defaults={
                "target_volume_kg": Decimal("2500.00"),
                "status": HarvestSchedule.Status.PENDING,
                "notes": "Peak wholesale demand anticipated across Mumbai retailers. Dry weather window optimal.",
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
        HarvestSchedule.objects.get_or_create(
            farmer=farmer2,
            crop=tomato,
            recommended_date=(timezone.now() + timedelta(days=2)).date(),
            defaults={
                "target_volume_kg": Decimal("1500.00"),
                "status": HarvestSchedule.Status.PENDING,
                "notes": "Direct pre-order match reserved for QuickMart chain. Priority cold-chain dispatch.",
            },
        )
        self.stdout.write(self.style.SUCCESS("[OK] Seeded AI Harvest Schedules for Farmers"))

        self.stdout.write(self.style.SUCCESS("\n[SUCCESS] Demo dataset seeded successfully with all 4 Must Have features!"))

