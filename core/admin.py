from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

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
    User,
    WalletTransaction,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("identifier", "role", "phone_number", "email", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active", "date_joined")
    search_fields = ("identifier", "phone_number", "email", "first_name", "last_name")
    ordering = ("-date_joined",)

    fieldsets = (
        (None, {"fields": ("identifier", "password")}),
        (_("Role & Identification"), {"fields": ("role", "phone_number", "email")}),
        (_("Personal Info"), {"fields": ("first_name", "last_name", "address", "state", "pincode")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("identifier", "role", "phone_number", "email", "password1", "password2"),
        }),
    )


@admin.register(MicroHub)
class MicroHubAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "district", "state", "capacity_kg", "is_active", "created_at")
    list_filter = ("state", "district", "is_active")
    search_fields = ("name", "code", "district", "state")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "base_price", "shelf_life_days", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("batch_id", "crop", "farmer", "hub", "volume_kg", "ai_grade", "ai_confidence_score", "status", "received_at")
    list_filter = ("status", "ai_grade", "crop", "hub")
    search_fields = ("batch_id", "farmer__identifier", "farmer__phone_number", "crop__name")
    readonly_fields = ("batch_id", "received_at", "updated_at")


@admin.register(DemandOrder)
class DemandOrderAdmin(admin.ModelAdmin):
    list_display = ("order_id", "retailer", "crop", "required_volume_kg", "required_date", "status", "created_at")
    list_filter = ("status", "crop", "required_date")
    search_fields = ("order_id", "retailer__identifier", "retailer__email", "crop__name")
    readonly_fields = ("order_id", "created_at", "updated_at")


@admin.register(FarmerWallet)
class FarmerWalletAdmin(admin.ModelAdmin):
    list_display = ("farmer", "current_balance", "updated_at")
    search_fields = ("farmer__identifier", "farmer__phone_number")
    readonly_fields = ("updated_at",)


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("wallet", "amount", "transaction_type", "description", "timestamp")
    list_filter = ("transaction_type", "timestamp")
    search_fields = ("wallet__farmer__identifier", "description")
    readonly_fields = ("timestamp",)


@admin.register(HarvestSchedule)
class HarvestScheduleAdmin(admin.ModelAdmin):
    list_display = ("farmer", "crop", "recommended_date", "target_volume_kg", "status", "created_at")
    list_filter = ("status", "crop", "recommended_date")
    search_fields = ("farmer__identifier", "crop__name")


@admin.register(InputSupply)
class InputSupplyAdmin(admin.ModelAdmin):
    list_display = ("name", "supplier", "category", "quantity", "unit", "price_per_unit", "status", "hub", "created_at")
    list_filter = ("category", "status", "hub")
    search_fields = ("name", "supplier__identifier", "supplier__email")
    readonly_fields = ("created_at", "updated_at")


class KitItemInline(admin.TabularInline):
    from core.models import KitItem
    model = KitItem
    extra = 1


@admin.register(Kit)
class KitAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "discount_percentage", "badge_text", "is_active", "created_at")
    list_filter = ("category", "is_active")
    search_fields = ("name", "code")
    inlines = [KitItemInline]


@admin.register(RecipeCombo)
class RecipeComboAdmin(admin.ModelAdmin):
    list_display = ("dish_name", "combo_id", "servings", "combo_price", "discount_percentage", "created_at")
    list_filter = ("servings", "created_at")
    search_fields = ("dish_name", "combo_id")
    readonly_fields = ("combo_id", "created_at")


class ConsumerOrderItemInline(admin.TabularInline):
    from core.models import ConsumerOrderItem
    model = ConsumerOrderItem
    extra = 0
    readonly_fields = ("farmer_payout", "is_settled_to_wallet")


class ConsumerFeedbackInline(admin.StackedInline):
    model = ConsumerFeedback
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(ConsumerOrder)
class ConsumerOrderAdmin(admin.ModelAdmin):
    list_display = ("order_id", "user", "customer_name", "customer_phone", "final_paid_amount", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("order_id", "customer_name", "customer_phone", "customer_email", "user__identifier")
    readonly_fields = ("order_id", "created_at", "updated_at")
    inlines = [ConsumerOrderItemInline, ConsumerFeedbackInline]


@admin.register(ConsumerFeedback)
class ConsumerFeedbackAdmin(admin.ModelAdmin):
    list_display = ("order", "consumer", "rating", "freshness_rating", "delivery_rating", "created_at")
    list_filter = ("rating", "freshness_rating", "delivery_rating", "created_at")
    search_fields = ("order__order_id", "consumer__identifier", "consumer__phone_number", "comment", "farmer_note")
    readonly_fields = ("created_at",)


