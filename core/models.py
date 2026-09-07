import re
import uuid
from decimal import Decimal
from typing import Union
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.managers import UserManager


phone_regex = RegexValidator(
    regex=r"^\+?[1-9]\d{9,14}$",
    message=_("Phone number must be entered in the format: '+919876543210' or '9876543210' (10 to 15 digits)."),
)


# ==============================================================================
# 1. CUSTOM USER MODEL (RBAC)
# ==============================================================================

class User(AbstractBaseUser, PermissionsMixin):
    """
    Unified Custom User model supporting four distinct business roles:
    - FARMER: Logs in via Mobile Number (and eventually OTP).
    - RETAILER: Logs in via Email / Password.
    - SUPPLIER: Logs in via Email / Password.
    - ADMIN: Logs in via Email / Password (2FA-ready).
    """

    class Role(models.TextChoices):
        FARMER = "FARMER", _("Farmer")
        RETAILER = "RETAILER", _("Retailer")
        SUPPLIER = "SUPPLIER", _("Supplier")
        ADMIN = "ADMIN", _("Admin")

    # Unified identifier used as USERNAME_FIELD
    identifier = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        verbose_name=_("Login Identifier"),
        help_text=_("Mobile number for farmers; Email address for retailers, suppliers, and admins."),
    )

    phone_number = models.CharField(
        validators=[phone_regex],
        max_length=17,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Mobile Number"),
    )

    email = models.EmailField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Email Address"),
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.FARMER,
        db_index=True,
        verbose_name=_("User Role"),
    )

    first_name = models.CharField(max_length=100, blank=True, verbose_name=_("First Name"))
    last_name = models.CharField(max_length=100, blank=True, verbose_name=_("Last Name"))
    address = models.TextField(blank=True, verbose_name=_("Physical Address"))
    state = models.CharField(max_length=100, blank=True, verbose_name=_("State"))
    pincode = models.CharField(max_length=10, blank=True, verbose_name=_("PIN Code"))

    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    is_staff = models.BooleanField(default=False, verbose_name=_("Staff Status"))
    date_joined = models.DateTimeField(default=timezone.now, verbose_name=_("Date Joined"))

    objects = UserManager()

    USERNAME_FIELD = "identifier"
    REQUIRED_FIELDS = ["role"]

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ["-date_joined"]

    def __str__(self):
        return f"{self.get_full_name() or self.identifier} ({self.get_role_display()})"

    def clean(self):
        super().clean()

        # Enforce role-specific required credentials
        if self.role == self.Role.FARMER:
            if not self.phone_number:
                raise ValidationError({"phone_number": _("Mobile number is mandatory for farmers.")})
            if not self.identifier:
                self.identifier = self.phone_number
        else:
            if not self.email:
                raise ValidationError({"email": _("Email address is mandatory for this role.")})
            if not self.identifier:
                self.identifier = self.email

    def save(self, *args, **kwargs):
        # Auto-sync identifier before saving
        if not self.identifier:
            if self.role == self.Role.FARMER and self.phone_number:
                self.identifier = self.phone_number
            elif self.email:
                self.identifier = self.email

        # Normalize email
        if self.email:
            self.email = self.email.lower().strip()
        if self.phone_number:
            self.phone_number = str(self.phone_number).strip()

        super().save(*args, **kwargs)

    # --------------------------------------------------------------------------
    # Fat Model Helper Properties & Methods
    # --------------------------------------------------------------------------
    @property
    def is_farmer(self) -> bool:
        return self.role == self.Role.FARMER

    @property
    def is_retailer(self) -> bool:
        return self.role == self.Role.RETAILER

    @property
    def is_supplier(self) -> bool:
        return self.role == self.Role.SUPPLIER

    @property
    def is_admin_user(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

    def get_full_name(self) -> str:
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.identifier

    def get_short_name(self) -> str:
        return self.first_name or self.identifier

    def get_dashboard_url(self) -> str:
        """Returns the canonical dashboard URL for this user's role."""
        if self.role == self.Role.FARMER:
            return reverse("farmer_dashboard")
        elif self.role == self.Role.RETAILER:
            return reverse("retailer_dashboard")
        elif self.role == self.Role.SUPPLIER:
            return reverse("supplier_dashboard")
        elif self.role == self.Role.ADMIN or self.is_staff:
            return reverse("admin_command_dashboard")
        return reverse("login")


# ==============================================================================
# 2. CORE DATABASE MODELS
# ==============================================================================

class MicroHub(models.Model):
    """
    Physical aggregation and drop-off hubs located close to agricultural clusters.
    Equipped with weighing and AI optical grading stations.
    """
    name = models.CharField(max_length=150, unique=True, verbose_name=_("Hub Name"))
    code = models.CharField(max_length=30, unique=True, db_index=True, verbose_name=_("Hub Code"))
    location = models.CharField(max_length=255, verbose_name=_("Address / Village / Tehsil"))
    district = models.CharField(max_length=100, verbose_name=_("District"))
    state = models.CharField(max_length=100, verbose_name=_("State"))
    pincode = models.CharField(max_length=10, verbose_name=_("PIN Code"))
    
    # Capacity in kilograms
    capacity_kg = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name=_("Storage Capacity (kg)"),
        help_text=_("Maximum physical storage capacity in kilograms."),
    )

    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Micro Hub")
        verbose_name_plural = _("Micro Hubs")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code}) - {self.district}, {self.state}"

    # Fat Model Logic
    def get_current_stored_volume(self) -> Decimal:
        """Calculates volume of batches currently held in the hub (active inventory)."""
        active_statuses = [Batch.Status.RECEIVED, Batch.Status.QUALITY_INSPECTED, Batch.Status.ALLOCATED]
        total = self.batches.filter(status__in=active_statuses).aggregate(
            total_kg=models.Sum("volume_kg")
        )["total_kg"]
        return total or Decimal("0.00")

    def get_available_capacity(self) -> Decimal:
        """Returns the remaining capacity in kg."""
        return max(Decimal("0.00"), self.capacity_kg - self.get_current_stored_volume())

    def can_accommodate(self, required_kg: Decimal) -> bool:
        """Checks whether the hub has sufficient headroom for incoming produce."""
        return self.get_available_capacity() >= required_kg


class Crop(models.Model):
    """
    Catalog of agricultural produce managed by the platform,
    as well as farmer-specific plantings and expected harvest batches.
    """
    class Category(models.TextChoices):
        VEGETABLE = "VEGETABLE", _("Vegetable")
        FRUIT = "FRUIT", _("Fruit")
        GRAIN = "GRAIN", _("Grain & Cereal")
        PULSE = "PULSE", _("Pulse / Legume")
        SPICE = "SPICE", _("Spice")

    farmer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        limit_choices_to={"role": User.Role.FARMER},
        related_name="crops",
        verbose_name=_("Farmer"),
    )
    name = models.CharField(max_length=100, verbose_name=_("Crop Name"))
    code = models.CharField(max_length=40, blank=True, db_index=True, verbose_name=_("Crop Code"))
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.VEGETABLE,
        verbose_name=_("Category"),
    )
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("25.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name=_("Base Price (₹/kg)"),
        help_text=_("Baseline standard price per kg for Grade B produce."),
    )
    shelf_life_days = models.PositiveIntegerField(
        default=20,
        verbose_name=_("Shelf Life (Days)"),
        help_text=_("Typical shelf life in days under ambient micro-hub conditions."),
    )
    planted_date = models.DateField(
        null=True,
        blank=True,
        default=timezone.now,
        verbose_name=_("Planted Date"),
    )
    harvest_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Expected Harvest Date"),
    )
    expected_yield_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("1000.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name=_("Expected Yield (kg)"),
    )
    status = models.CharField(
        max_length=30,
        default="Growing",
        verbose_name=_("Crop Status"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Crop")
        verbose_name_plural = _("Crops")
        ordering = ["-created_at"]

    def __str__(self):
        owner = f" ({self.farmer.get_full_name()})" if self.farmer else ""
        return f"{self.name}{owner} - ₹{self.base_price}/kg"

    def save(self, *args, **kwargs):
        if not self.code:
            clean_name = re.sub(r"[^A-Za-z0-9]", "", self.name).upper()[:6] or "CROP"
            unique_token = uuid.uuid4().hex[:4].upper()
            self.code = f"CRP-{clean_name}-{unique_token}"
        super().save(*args, **kwargs)

    def get_status_class(self) -> str:
        mapping = {
            "Growing": "status-growing",
            "Planting": "status-planting",
            "Harvested": "status-harvested",
            "At Hub (Graded)": "status-hub",
        }
        return mapping.get(self.status, "status-growing")

    # Fat Model Logic
    def calculate_grade_price(self, grade: str) -> Decimal:
        """
        Dynamically adjusts price per kg according to AI quality grade:
        - Grade A: +20% premium over base price.
        - Grade B: Standard base price.
        - Grade C: -25% discount against base price.
        """
        multipliers = {
            Batch.Grade.GRADE_A: Decimal("1.20"),
            Batch.Grade.GRADE_B: Decimal("1.00"),
            Batch.Grade.GRADE_C: Decimal("0.75"),
        }
        multiplier = multipliers.get(grade, Decimal("1.00"))
        return (self.base_price * multiplier).quantize(Decimal("0.01"))



class Batch(models.Model):
    """
    Represents a specific harvest dropped off by a farmer at a MicroHub.
    Graded optically by AI to guarantee trust and pricing fairness.
    """
    class Grade(models.TextChoices):
        GRADE_A = "A", _("Grade A (Export / Premium)")
        GRADE_B = "B", _("Grade B (Standard Retail)")
        GRADE_C = "C", _("Grade C (Processing / Economy)")

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", _("Received at Hub")
        QUALITY_INSPECTED = "QUALITY_INSPECTED", _("AI Quality Graded")
        ALLOCATED = "ALLOCATED", _("Allocated to Demand Orders")
        IN_TRANSIT = "IN_TRANSIT", _("In Transit to Retailer")
        DELIVERED = "DELIVERED", _("Delivered")
        REJECTED = "REJECTED", _("Rejected")

    batch_id = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
        db_index=True,
        verbose_name=_("Batch Identifier"),
    )

    farmer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": User.Role.FARMER},
        related_name="harvest_batches",
        verbose_name=_("Farmer"),
    )

    hub = models.ForeignKey(
        MicroHub,
        on_delete=models.PROTECT,
        related_name="batches",
        verbose_name=_("Micro Hub"),
    )

    crop = models.ForeignKey(
        Crop,
        on_delete=models.PROTECT,
        related_name="batches",
        verbose_name=_("Crop"),
    )

    volume_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.10"))],
        verbose_name=_("Volume (kg)"),
    )

    ai_grade = models.CharField(
        max_length=1,
        choices=Grade.choices,
        default=Grade.GRADE_B,
        verbose_name=_("AI Grade"),
    )

    ai_confidence_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        verbose_name=_("AI Confidence Score (%)"),
        help_text=_("Confidence percentage score from computer vision quality assessment (0 - 100)."),
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.RECEIVED,
        db_index=True,
        verbose_name=_("Batch Status"),
    )

    harvest_date = models.DateField(
        default=timezone.now,
        verbose_name=_("Harvest Date"),
    )

    received_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Received At"),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Last Updated"),
    )

    class Meta:
        verbose_name = _("Harvest Batch")
        verbose_name_plural = _("Harvest Batches")
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.batch_id} - {self.crop.name} ({self.volume_kg}kg, Grade {self.ai_grade})"

    def clean(self):
        super().clean()
        if self.farmer and self.farmer.role != User.Role.FARMER:
            raise ValidationError({"farmer": _("Only registered farmers can register harvest batches.")})

    def save(self, *args, **kwargs):
        if not self.batch_id:
            # Generate deterministic, clean business identifier: K2K-BTH-<YYYYMMDD>-<HEX>
            date_str = timezone.now().strftime("%Y%m%d")
            unique_token = uuid.uuid4().hex[:6].upper()
            self.batch_id = f"K2K-BTH-{date_str}-{unique_token}"
        super().save(*args, **kwargs)

    # Fat Model Logic
    def calculate_price_per_kg(self) -> Decimal:
        """Determines price per kg based on crop base price and AI grade."""
        return self.crop.calculate_grade_price(self.ai_grade)

    def calculate_valuation(self) -> Decimal:
        """Total payout valuation for this batch."""
        return (self.volume_kg * self.calculate_price_per_kg()).quantize(Decimal("0.01"))

    def mark_inspected(self, grade: str, confidence_score: Decimal):
        """Transitions batch status upon AI inspection completion."""
        self.ai_grade = grade
        self.ai_confidence_score = confidence_score
        self.status = self.Status.QUALITY_INSPECTED
        self.save(update_fields=["ai_grade", "ai_confidence_score", "status", "updated_at"])


class DemandOrder(models.Model):
    """
    Represents an urban retailer's pre-order on the platform, establishing
    demand visibility before produce leaves the micro-hub.
    """
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending Matching")
        ALLOCATED = "ALLOCATED", _("Batches Allocated")
        DISPATCHED = "DISPATCHED", _("Dispatched from Hub")
        FULFILLED = "FULFILLED", _("Fulfilled & Delivered")
        CANCELLED = "CANCELLED", _("Cancelled")

    order_id = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
        db_index=True,
        verbose_name=_("Order Identifier"),
    )

    retailer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": User.Role.RETAILER},
        related_name="demand_orders",
        verbose_name=_("Retailer"),
    )

    crop = models.ForeignKey(
        Crop,
        on_delete=models.PROTECT,
        related_name="demand_orders",
        verbose_name=_("Crop"),
    )

    required_volume_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("1.00"))],
        verbose_name=_("Required Volume (kg)"),
    )

    required_date = models.DateField(
        verbose_name=_("Required Delivery Date"),
        help_text=_("The date by which the retailer needs produce delivered."),
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name=_("Order Status"),
    )

    delivery_address = models.TextField(blank=True, verbose_name=_("Delivery Address"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Demand Order")
        verbose_name_plural = _("Demand Orders")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order_id} - {self.retailer.get_full_name()} ({self.required_volume_kg}kg {self.crop.name})"

    def clean(self):
        super().clean()
        if getattr(self, "retailer_id", None) and self.retailer and self.retailer.role != User.Role.RETAILER:
            raise ValidationError({"retailer": _("Only registered retailers can place demand orders.")})

    def save(self, *args, **kwargs):
        if not self.order_id:
            date_str = timezone.now().strftime("%Y%m%d")
            unique_token = uuid.uuid4().hex[:6].upper()
            self.order_id = f"K2K-ORD-{date_str}-{unique_token}"
        super().save(*args, **kwargs)

    # Fat Model Logic
    def calculate_estimated_cost(self) -> Decimal:
        """Estimates order cost based on required volume and crop base price."""
        return (self.required_volume_kg * self.crop.base_price).quantize(Decimal("0.01"))

    def mark_fulfilled(self):
        """Marks order as delivered and fulfilled."""
        self.status = self.Status.FULFILLED
        self.save(update_fields=["status", "updated_at"])


class InputSupply(models.Model):
    """
    Agricultural inputs (fertilizers, certified seeds, drip kits, bio-pesticides)
    inventoried and consigned by suppliers to regional micro-hubs or farmer clusters.
    """
    class Category(models.TextChoices):
        FERTILIZER = "FERTILIZER", _("Organic Fertilizer / Nutrients")
        SEED = "SEED", _("Certified Seeds & Seedlings")
        EQUIPMENT = "EQUIPMENT", _("Irrigation & Agri-Tools")
        PESTICIDE = "PESTICIDE", _("Bio-Pesticide / Crop Care")
        PACKAGING = "PACKAGING", _("Crates & Storage Packaging")

    class Status(models.TextChoices):
        IN_STOCK = "IN_STOCK", _("In Stock (Warehouse)")
        LOW_STOCK = "LOW_STOCK", _("Low Stock (Reorder Alert)")
        CONSIGNED = "CONSIGNED", _("Consigned at Micro-Hub")
        RESERVED = "RESERVED", _("Reserved by Farmer")
        OUT_OF_STOCK = "OUT_OF_STOCK", _("Out of Stock")

    supplier = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": User.Role.SUPPLIER},
        related_name="input_supplies",
        verbose_name=_("Supplier"),
    )
    hub = models.ForeignKey(
        MicroHub,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplied_inputs",
        verbose_name=_("Assigned Micro-Hub"),
    )
    name = models.CharField(max_length=150, verbose_name=_("Item / Product Name"))
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.FERTILIZER,
        verbose_name=_("Category"),
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name=_("Stock Quantity"),
    )
    unit = models.CharField(max_length=30, default="Bags", verbose_name=_("Unit"))
    price_per_unit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name=_("Price per Unit (₹)"),
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.IN_STOCK,
        verbose_name=_("Inventory Status"),
    )
    description = models.TextField(blank=True, verbose_name=_("Specifications / Details"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Input Supply")
        verbose_name_plural = _("Input Supplies")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.quantity} {self.unit}) - {self.supplier.get_full_name()}"

    def calculate_total_valuation(self) -> Decimal:
        return (self.quantity * self.price_per_unit).quantize(Decimal("0.01"))


# ==============================================================================
# 3. DIGITAL WALLET & HARVEST SCHEDULING MODELS
# ==============================================================================

class FarmerWallet(models.Model):
    """
    Digital Wallet providing instantaneous, transparent settlement directly
    to farmers without middlemen delays or banking commissions.
    """
    farmer = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": User.Role.FARMER},
        related_name="wallet",
        verbose_name=_("Farmer"),
    )

    current_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name=_("Current Balance (₹)"),
    )

    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Last Updated"))

    class Meta:
        verbose_name = _("Farmer Wallet")
        verbose_name_plural = _("Farmer Wallets")

    def __str__(self):
        return f"Wallet ({self.farmer.get_full_name()}) - ₹{self.current_balance}"

    def credit(self, amount: Union[Decimal, float, int], description: str) -> "WalletTransaction":
        """Adds funds to wallet and records an immutable ledger entry."""
        amount_dec = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount_dec <= Decimal("0.00"):
            raise ValidationError(_("Credit amount must be greater than zero."))

        self.current_balance = (self.current_balance + amount_dec).quantize(Decimal("0.01"))
        self.save(update_fields=["current_balance", "updated_at"])

        return self.transactions.create(
            amount=amount_dec,
            transaction_type=WalletTransaction.TransactionType.CREDIT,
            description=description,
        )

    def debit(self, amount: Union[Decimal, float, int], description: str) -> "WalletTransaction":
        """Withdraws funds from wallet and records an immutable ledger entry."""
        amount_dec = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount_dec <= Decimal("0.00"):
            raise ValidationError(_("Debit amount must be greater than zero."))
        if amount_dec > self.current_balance:
            raise ValidationError(_("Insufficient wallet balance for withdrawal."))

        self.current_balance = (self.current_balance - amount_dec).quantize(Decimal("0.01"))
        self.save(update_fields=["current_balance", "updated_at"])

        return self.transactions.create(
            amount=amount_dec,
            transaction_type=WalletTransaction.TransactionType.DEBIT,
            description=description,
        )


class WalletTransaction(models.Model):
    """
    Immutable ledger tracking all credits (produce batch sales) and debits (bank withdrawals).
    """
    class TransactionType(models.TextChoices):
        CREDIT = "CREDIT", _("Credit (Produce Payout)")
        DEBIT = "DEBIT", _("Debit (Bank Withdrawal)")

    wallet = models.ForeignKey(
        FarmerWallet,
        on_delete=models.CASCADE,
        related_name="transactions",
        verbose_name=_("Wallet"),
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name=_("Amount (₹)"),
    )

    transaction_type = models.CharField(
        max_length=10,
        choices=TransactionType.choices,
        default=TransactionType.CREDIT,
        verbose_name=_("Transaction Type"),
    )

    description = models.CharField(
        max_length=255,
        verbose_name=_("Description"),
    )

    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Timestamp"),
    )

    class Meta:
        verbose_name = _("Wallet Transaction")
        verbose_name_plural = _("Wallet Transactions")
        ordering = ["-timestamp"]

    def __str__(self):
        sign = "+" if self.transaction_type == self.TransactionType.CREDIT else "-"
        return f"{sign}₹{self.amount} - {self.description} ({self.timestamp.strftime('%d %b %Y %H:%M')})"


class HarvestSchedule(models.Model):
    """
    AI-driven harvest notification pushed to farmers indicating optimal harvest
    windows to match urban demand pre-orders and maximize payouts.
    """
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending Harvest")
        COMPLETED = "COMPLETED", _("Completed & Dropped Off")
        CANCELLED = "CANCELLED", _("Cancelled")

    farmer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": User.Role.FARMER},
        related_name="harvest_schedules",
        verbose_name=_("Farmer"),
    )

    crop = models.ForeignKey(
        Crop,
        on_delete=models.PROTECT,
        related_name="harvest_schedules",
        verbose_name=_("Crop"),
    )

    recommended_date = models.DateField(
        verbose_name=_("Recommended Harvest Date"),
    )

    target_volume_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("1.00"))],
        verbose_name=_("Target Volume (kg)"),
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name=_("Schedule Status"),
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("AI Agronomy Advice"),
        help_text=_("AI recommendation regarding weather window, sugar/brix content, or demand surge."),
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Harvest Schedule")
        verbose_name_plural = _("Harvest Schedules")
        ordering = ["recommended_date"]

    def __str__(self):
        return f"Harvest Alert: {self.crop.name} ({self.target_volume_kg}kg on {self.recommended_date}) - {self.farmer.get_full_name()}"

    @property
    def is_overdue(self) -> bool:
        """Returns True if schedule recommended date has passed and status is still PENDING."""
        return self.recommended_date < timezone.now().date() and self.status == self.Status.PENDING


# ==============================================================================
# 4. DIRECT-TO-CONSUMER (D2C) & AI RECIPE COMBO MODELS
# ==============================================================================

class Kit(models.Model):
    """
    Pre-packaged vegetable/produce bundle offered to consumers at a discounted bundle price.
    E.g., Leafy Greens Detox Kit, Sambar Essentials Box, Daily Curry Veggie Kit.
    """
    class Category(models.TextChoices):
        VEGETABLE = "VEGETABLE", _("Fresh Vegetables")
        FRUIT = "FRUIT", _("Seasonal Fruits")
        HERBS = "HERBS", _("Fresh Herbs & Greens")
        COMBO = "COMBO", _("Curated Box / Combo")

    name = models.CharField(max_length=150, verbose_name=_("Kit Name"))
    code = models.CharField(max_length=50, unique=True, verbose_name=_("Kit Code"))
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.COMBO,
        verbose_name=_("Category"),
    )
    description = models.TextField(verbose_name=_("Description / Highlights"))
    badge_text = models.CharField(
        max_length=50,
        blank=True,
        default="15% OFF",
        verbose_name=_("Promotional Badge"),
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("90.00"))],
        verbose_name=_("Bundle Discount (%)"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Active in Store"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Consumer Kit")
        verbose_name_plural = _("Consumer Kits")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code}) - ₹{self.calculate_bundle_price()}"

    def calculate_original_price(self) -> Decimal:
        """Calculates total undiscounted sum of all individual kit items."""
        total = sum((item.get_standalone_price() for item in self.items.all()), Decimal("0.00"))
        return total.quantize(Decimal("0.01"))

    def calculate_bundle_price(self) -> Decimal:
        """Calculates bundle price after applying discount_percentage."""
        orig = self.calculate_original_price()
        if self.discount_percentage > Decimal("0.00"):
            discount_multiplier = (Decimal("100.00") - self.discount_percentage) / Decimal("100.00")
            return (orig * discount_multiplier).quantize(Decimal("0.01"))
        return orig

    def get_savings(self) -> Decimal:
        """Calculates rupee savings for the consumer."""
        return (self.calculate_original_price() - self.calculate_bundle_price()).quantize(Decimal("0.01"))

    def total_weight_grams(self) -> int:
        return sum(item.quantity_grams for item in self.items.all())


class KitItem(models.Model):
    """Individual crop/produce component inside a Kit."""
    kit = models.ForeignKey(Kit, on_delete=models.CASCADE, related_name="items", verbose_name=_("Kit"))
    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="kit_appearances", verbose_name=_("Crop Produce"))
    quantity_grams = models.PositiveIntegerField(
        default=500,
        validators=[MinValueValidator(10)],
        verbose_name=_("Quantity (Grams)"),
        help_text=_("Produce weight in grams included in each kit bundle."),
    )

    class Meta:
        verbose_name = _("Kit Item")
        verbose_name_plural = _("Kit Items")
        unique_together = ("kit", "crop")

    def __str__(self):
        return f"{self.quantity_grams}g {self.crop.name} in {self.kit.name}"

    def get_standalone_price(self) -> Decimal:
        """Computes standalone value based on crop base price per kg."""
        kg = Decimal(str(self.quantity_grams)) / Decimal("1000.00")
        return (kg * self.crop.base_price).quantize(Decimal("0.01"))


class RecipeCombo(models.Model):
    """
    AI-generated or predefined recipe ingredient combo (e.g. Sambar for 4 people).
    """
    combo_id = models.CharField(max_length=60, unique=True, editable=False, verbose_name=_("Combo Identifier"))
    dish_name = models.CharField(max_length=150, verbose_name=_("Dish Name"))
    servings = models.PositiveIntegerField(default=4, verbose_name=_("Servings Count"))
    prep_time_minutes = models.PositiveIntegerField(default=30, verbose_name=_("Estimated Prep Time (mins)"))
    culinary_notes = models.TextField(blank=True, verbose_name=_("Culinary Notes / Tips"))
    total_weight_kg = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("1.00"),
        verbose_name=_("Total Weight (kg)"),
    )
    original_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Undiscounted Price (₹)"),
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        verbose_name=_("Bundle Discount (%)"),
    )
    combo_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Discounted Combo Price (₹)"),
    )
    items_breakdown = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Ingredients Breakdown JSON"),
        help_text=_("List of ingredients with crop_name, quantity_grams, role, and price."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Recipe Combo")
        verbose_name_plural = _("Recipe Combos")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.dish_name} Combo ({self.servings} Servings) - ₹{self.combo_price}"

    def save(self, *args, **kwargs):
        if not self.combo_id:
            token = uuid.uuid4().hex[:8].upper()
            slug = re.sub(r'[^a-zA-Z0-9]', '', self.dish_name)[:6].upper()
            self.combo_id = f"K2K-CMB-{slug}-{token}"
        super().save(*args, **kwargs)


class ConsumerOrder(models.Model):
    """
    Tracks Direct-to-Consumer (D2C) marketplace orders with real-time
    farmer wallet payouts upon payment.
    """
    class Status(models.TextChoices):
        PLACED = "PLACED", _("Order Placed")
        PAID_SETTLED = "PAID_SETTLED", _("Paid & Farmer Settled")
        PACKED = "PACKED", _("Packed at Micro-Hub")
        DISPATCHED = "DISPATCHED", _("Out for Cold Delivery")
        DELIVERED = "DELIVERED", _("Delivered to Kitchen")
        CANCELLED = "CANCELLED", _("Cancelled")

    order_id = models.CharField(max_length=50, unique=True, editable=False, db_index=True)
    customer_name = models.CharField(max_length=150, verbose_name=_("Customer Name"))
    customer_phone = models.CharField(max_length=20, verbose_name=_("Customer Phone"))
    customer_email = models.EmailField(max_length=255, blank=True, verbose_name=_("Customer Email"))
    delivery_address = models.TextField(verbose_name=_("Delivery Address"))
    pincode = models.CharField(max_length=10, blank=True, verbose_name=_("PIN Code"))

    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    final_paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PAID_SETTLED)
    payment_method = models.CharField(max_length=30, default="UPI_INSTANT")
    payment_ref = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Consumer D2C Order")
        verbose_name_plural = _("Consumer D2C Orders")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order_id} - {self.customer_name} (₹{self.final_paid_amount})"

    def save(self, *args, **kwargs):
        if not self.order_id:
            date_str = timezone.now().strftime("%Y%m%d")
            token = uuid.uuid4().hex[:6].upper()
            self.order_id = f"K2K-D2C-{date_str}-{token}"
        super().save(*args, **kwargs)


class ConsumerOrderItem(models.Model):
    """
    Individual line item in a ConsumerOrder, attributing revenue
    and payouts directly to individual farmers.
    """
    class ItemType(models.TextChoices):
        PRODUCE = "PRODUCE", _("Direct Farm Produce")
        KIT = "KIT", _("Pre-Packaged Kit")
        COMBO = "COMBO", _("AI Recipe Combo")

    order = models.ForeignKey(ConsumerOrder, on_delete=models.CASCADE, related_name="items")
    item_type = models.CharField(max_length=20, choices=ItemType.choices, default=ItemType.PRODUCE)
    crop = models.ForeignKey(Crop, null=True, blank=True, on_delete=models.SET_NULL)
    kit = models.ForeignKey(Kit, null=True, blank=True, on_delete=models.SET_NULL)
    recipe_combo = models.ForeignKey(RecipeCombo, null=True, blank=True, on_delete=models.SET_NULL)
    farmer = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        limit_choices_to={"role": User.Role.FARMER},
        related_name="d2c_sales",
        verbose_name=_("Farmer Producer"),
    )

    item_name = models.CharField(max_length=150)
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("1.00"))
    unit = models.CharField(max_length=30, default="kg")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    farmer_payout = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("Net direct payout credited to the farmer's wallet (e.g. 90% of subtotal)."),
    )
    is_settled_to_wallet = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("Consumer Order Item")
        verbose_name_plural = _("Consumer Order Items")

    def __str__(self):
        return f"{self.item_name} x {self.quantity} {self.unit} (Order {self.order.order_id})"


