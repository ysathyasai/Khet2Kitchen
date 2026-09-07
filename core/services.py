"""
K2K Intelligence Engine - Core Business Logic Services.
Contains modular domain algorithms for:
1. Demand Forecasting (Simulated ML pipeline).
2. Supply-to-Demand Allocation (Direct produce matching).
3. Transparent Pricing & Disintermediation Breakdown.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import logging
from typing import Any, Dict, List, Optional, Union

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import Batch, Crop, DemandOrder, MicroHub

logger = logging.getLogger(__name__)


# ==============================================================================
# A. DEMAND PREDICTION SERVICE
# ==============================================================================

def predict_demand(
    crop_id: Union[int, Crop],
    target_date: Optional[Union[date, str]] = None,
) -> Dict[str, Any]:
    """
    Simulates an AI demand prediction engine for a given crop and delivery date.
    
    In production, this interfaces with a trained time-series forecasting model
    (e.g., Prophet, XGBoost, or Gemini Time-Series Analytics) utilizing wholesale
    mandi arrivals, retail consumption cycles, and weather patterns.

    :param crop_id: Primary key or instance of Crop.
    :param target_date: Forecast delivery date (defaults to 7 days from today).
    :return: Dictionary containing predicted_volume_kg, expected_price_per_kg,
             confidence_score, trend, and rationale.
    """
    if isinstance(crop_id, Crop):
        crop = crop_id
    else:
        try:
            crop = Crop.objects.get(pk=crop_id)
        except (Crop.DoesNotExist, ValueError) as exc:
            logger.error("Crop ID %s not found for demand prediction: %s", crop_id, exc)
            raise ObjectDoesNotExist(f"Crop with ID {crop_id} does not exist.") from exc

    # Parse target_date
    if target_date is None:
        target_date = timezone.now().date() + timezone.timedelta(days=7)
    elif isinstance(target_date, str):
        try:
            target_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            target_date = timezone.now().date() + timezone.timedelta(days=7)

    # Deterministic simulation based on crop attributes, seasonal month, and date
    month = target_date.month
    day_of_year = target_date.timetuple().tm_yday
    
    # Generate seed hash for deterministic yet realistic fluctuations
    hash_seed = int(hashlib.md5(f"{crop.code}-{target_date}".encode()).hexdigest()[:6], 16)

    # Base volumes calibrated by produce category
    category_base_volumes = {
        Crop.Category.VEGETABLE: Decimal("1800.00"),
        Crop.Category.FRUIT: Decimal("1200.00"),
        Crop.Category.GRAIN: Decimal("5000.00"),
        Crop.Category.PULSE: Decimal("2500.00"),
        Crop.Category.SPICE: Decimal("400.00"),
    }
    base_volume = category_base_volumes.get(crop.category, Decimal("1500.00"))

    # Seasonal multiplier (higher demand during festive Q3/Q4 months: Oct-Jan)
    seasonality_factor = Decimal("1.15") if month in [9, 10, 11, 12, 1] else Decimal("0.95")
    
    # Pseudo-random variance between -10% and +20%
    variance_pct = Decimal(str((hash_seed % 31) - 10)) / Decimal("100.0")
    predicted_volume_kg = (base_volume * seasonality_factor * (Decimal("1.0") + variance_pct)).quantize(
        Decimal("1.00"), rounding=ROUND_HALF_UP
    )

    # Expected price prediction (micro-fluctuation against baseline)
    price_variance_pct = Decimal(str(((hash_seed // 7) % 21) - 10)) / Decimal("100.0")
    expected_price_per_kg = (crop.base_price * (Decimal("1.0") + price_variance_pct)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Confidence score between 82.0% and 96.5%
    confidence_score = Decimal(str(82 + (hash_seed % 150) / 10.0)).quantize(
        Decimal("0.10"), rounding=ROUND_HALF_UP
    )

    trend = "HIGH_DEMAND" if variance_pct > Decimal("0.08") else ("STABLE" if variance_pct >= Decimal("-0.05") else "MODERATE")

    rationales = [
        f"Anticipated urban hospitality and direct retail demand surge in Mumbai-Pune corridor for {crop.name}.",
        f"Stable commercial procurement demand expected with favorable shelf-life of {crop.shelf_life_days} days.",
        f"Micro-hub arrival trend indicates prime harvest window for {crop.name} with premium grade yields.",
    ]
    rationale = rationales[hash_seed % len(rationales)]

    return {
        "crop_id": crop.id,
        "crop_name": crop.name,
        "crop_code": crop.code,
        "crop_category": crop.get_category_display(),
        "target_date": target_date.strftime("%Y-%m-%d"),
        "predicted_volume_kg": predicted_volume_kg,
        "expected_price_per_kg": expected_price_per_kg,
        "confidence_score": confidence_score,
        "trend": trend,
        "rationale": rationale,
    }


# ==============================================================================
# B. SUPPLY ALLOCATION SERVICE (MATCHING ENGINE)
# ==============================================================================

@transaction.atomic
def allocate_supply_to_order(
    demand_order: Union[int, str, DemandOrder]
) -> Dict[str, Any]:
    """
    Matches available farmer harvest batches to an urban retailer's DemandOrder.
    
    Logic:
    1. Finds candidate batches in MicroHubs for the specified Crop where status is
       eligible ('RECEIVED' or 'QUALITY_INSPECTED') and volume > 0.
    2. Prioritizes batches by highest AI Grade ('A' -> 'B' -> 'C') and FIFO (received_at).
    3. Allocates produce volume until order.required_volume_kg is met.
    4. Updates batch status and order status atomically.

    :param demand_order: DemandOrder instance, PK, or order_id string.
    :return: Summary dictionary detailing allocated batches and fulfillment status.
    """
    if isinstance(demand_order, DemandOrder):
        order = demand_order
    elif isinstance(demand_order, int):
        order = DemandOrder.objects.select_for_update().get(pk=demand_order)
    else:
        order = DemandOrder.objects.select_for_update().get(order_id=str(demand_order))

    if order.status == DemandOrder.Status.FULFILLED:
        logger.info("DemandOrder %s is already fulfilled.", order.order_id)
        return {
            "order_id": order.order_id,
            "status": order.status,
            "message": "Order is already fulfilled.",
            "allocated_batches": [],
            "total_allocated_kg": Decimal("0.00"),
            "remaining_required_kg": Decimal("0.00"),
        }

    remaining_needed_kg = Decimal(str(order.required_volume_kg))
    allocated_batches_summary: List[Dict[str, Any]] = []
    total_allocated_kg = Decimal("0.00")

    # Fetch available candidate batches with row-level locks
    candidate_batches = (
        Batch.objects.select_for_update()
        .filter(
            crop=order.crop,
            status__in=[Batch.Status.RECEIVED, Batch.Status.QUALITY_INSPECTED],
            volume_kg__gt=Decimal("0.00"),
        )
        .order_by("ai_grade", "received_at")  # 'A' < 'B' < 'C' alphabetically
    )

    for batch in candidate_batches:
        if remaining_needed_kg <= Decimal("0.00"):
            break

        current_batch_vol = Decimal(str(batch.volume_kg))
        if current_batch_vol <= Decimal("0.00"):
            continue

        if current_batch_vol <= remaining_needed_kg:
            # Full consumption of this batch
            volume_to_take = current_batch_vol
            batch.status = Batch.Status.ALLOCATED
            batch.save(update_fields=["status", "updated_at"])
        else:
            # Partial allocation: deduct needed volume, residual stays active in hub
            volume_to_take = remaining_needed_kg
            batch.volume_kg = (current_batch_vol - volume_to_take).quantize(Decimal("0.01"))
            if batch.volume_kg <= Decimal("0.50"):
                batch.status = Batch.Status.ALLOCATED
            batch.save(update_fields=["volume_kg", "status", "updated_at"])

        remaining_needed_kg = (remaining_needed_kg - volume_to_take).quantize(Decimal("0.01"))
        total_allocated_kg = (total_allocated_kg + volume_to_take).quantize(Decimal("0.01"))

        allocated_batches_summary.append({
            "batch_id": batch.batch_id,
            "farmer_name": batch.farmer.get_full_name(),
            "hub_name": batch.hub.name,
            "ai_grade": batch.ai_grade,
            "allocated_volume_kg": volume_to_take,
            "price_per_kg": batch.calculate_price_per_kg(),
            "subtotal": (volume_to_take * batch.calculate_price_per_kg()).quantize(Decimal("0.01")),
        })

    # Update DemandOrder status
    if remaining_needed_kg <= Decimal("0.00"):
        order.status = DemandOrder.Status.FULFILLED
    elif total_allocated_kg > Decimal("0.00"):
        order.status = DemandOrder.Status.ALLOCATED
    
    order.save(update_fields=["status", "updated_at"])

    return {
        "order_id": order.order_id,
        "crop_name": order.crop.name,
        "required_volume_kg": order.required_volume_kg,
        "total_allocated_kg": total_allocated_kg,
        "remaining_required_kg": max(Decimal("0.00"), remaining_needed_kg),
        "status": order.status,
        "is_fully_fulfilled": (order.status == DemandOrder.Status.FULFILLED),
        "allocated_batches": allocated_batches_summary,
    }


# ==============================================================================
# C. TRANSPARENT PRICING BREAKDOWN SERVICE
# ==============================================================================

def generate_transparent_pricing_breakdown(
    batch: Union[int, str, Batch]
) -> Dict[str, Any]:
    """
    Computes the exact transparent financial payout for a farmer's batch,
    proving middleman disintermediation and direct value return.

    Formula:
    1. Base Value = volume_kg * crop.base_price
    2. Grade Modifier =
         Grade A: +20% quality premium
         Grade B: 0% standard
         Grade C: -25% commercial discount
    3. Logistics Deduction = flat hub logistics fee per kg (e.g., ₹1.50/kg)
    4. Final Payout = (Base Value + Grade Modifier Amount) - Logistics Deduction
    5. Disintermediation Gain = Final Payout vs traditional Mandi payout (~28% commission/wastage loss)

    :param batch: Batch instance, PK, or batch_id string.
    :return: Itemized financial breakdown dictionary.
    """
    if isinstance(batch, Batch):
        batch_obj = batch
    elif isinstance(batch, int):
        try:
            batch_obj = Batch.objects.select_related("crop", "hub", "farmer").get(pk=batch)
        except Batch.DoesNotExist as exc:
            raise ObjectDoesNotExist(f"Batch with PK {batch} does not exist.") from exc
    else:
        try:
            batch_obj = Batch.objects.select_related("crop", "hub", "farmer").get(batch_id=str(batch))
        except Batch.DoesNotExist as exc:
            raise ObjectDoesNotExist(f"Batch with ID '{batch}' does not exist.") from exc

    volume_kg = Decimal(str(batch_obj.volume_kg))
    base_price = Decimal(str(batch_obj.crop.base_price))

    # 1. Base Value
    base_value = (volume_kg * base_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 2. Grade Modifier Percentage & Amount
    grade_modifier_percentages = {
        Batch.Grade.GRADE_A: Decimal("0.20"),
        Batch.Grade.GRADE_B: Decimal("0.00"),
        Batch.Grade.GRADE_C: Decimal("-0.25"),
    }
    modifier_pct = grade_modifier_percentages.get(batch_obj.ai_grade, Decimal("0.00"))
    grade_modifier_amount = (base_value * modifier_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Value before deductions
    gross_value = base_value + grade_modifier_amount

    # 3. Flat Hub Logistics Fee (₹1.50/kg standard micro-hub fee)
    flat_logistics_rate_per_kg = Decimal("1.50")
    logistics_deduction = (volume_kg * flat_logistics_rate_per_kg).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # 4. Final Net Farmer Payout
    final_payout = max(Decimal("0.00"), gross_value - logistics_deduction).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    effective_price_per_kg = (
        (final_payout / volume_kg).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if volume_kg > Decimal("0.00")
        else Decimal("0.00")
    )

    # 5. Traditional Middleman / APMC Comparison
    # Traditional middlemen take:
    # - 8.5% Commission Agent (Arhatiya) fee
    # - 6.0% Unloading / Hamali fee
    # - 13.5% Arbitrary quality docking & weight reduction
    # Farmer receives only ~72% of gross value in traditional channels
    traditional_mandi_payout = (gross_value * Decimal("0.72")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    disintermediation_gain = max(Decimal("0.00"), final_payout - traditional_mandi_payout).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    extra_income_pct = (
        ((disintermediation_gain / traditional_mandi_payout) * Decimal("100.0")).quantize(
            Decimal("0.10"), rounding=ROUND_HALF_UP
        )
        if traditional_mandi_payout > Decimal("0.00")
        else Decimal("0.00")
    )

    return {
        "batch_id": batch_obj.batch_id,
        "crop_name": batch_obj.crop.name,
        "hub_name": batch_obj.hub.name,
        "volume_kg": volume_kg,
        "ai_grade": batch_obj.ai_grade,
        "ai_confidence_score": batch_obj.ai_confidence_score,
        "base_price_per_kg": base_price,
        "base_value": base_value,
        "grade_modifier_pct": int(modifier_pct * 100),
        "grade_modifier_amount": grade_modifier_amount,
        "gross_value": gross_value,
        "logistics_rate_per_kg": flat_logistics_rate_per_kg,
        "logistics_deduction": logistics_deduction,
        "final_payout": final_payout,
        "effective_price_per_kg": effective_price_per_kg,
        # Middleman disintermediation metrics
        "traditional_mandi_payout": traditional_mandi_payout,
        "disintermediation_gain": disintermediation_gain,
        "extra_income_pct": extra_income_pct,
    }


# ==============================================================================
# D. DIGITAL WALLET PAYOUT SETTLEMENT
# ==============================================================================

@transaction.atomic
def process_batch_payout(
    batch: Union[int, str, Batch]
) -> Dict[str, Any]:
    """
    Executes instant direct settlement into the farmer's Digital Wallet
    upon successful AI quality inspection. Eliminates traditional 30-60 day
    commission agent payment delays.

    :param batch: Batch instance, PK, or batch_id string.
    :return: Payout result summary including updated wallet balance and ledger transaction ID.
    """
    from core.models import FarmerWallet

    if isinstance(batch, Batch):
        batch_obj = batch
    elif isinstance(batch, int):
        batch_obj = Batch.objects.select_related("farmer", "crop", "hub").get(pk=batch)
    else:
        batch_obj = Batch.objects.select_related("farmer", "crop", "hub").get(batch_id=str(batch))

    breakdown = generate_transparent_pricing_breakdown(batch_obj)
    final_payout = breakdown["final_payout"]

    # Provision or retrieve farmer wallet
    wallet, _ = FarmerWallet.objects.get_or_create(
        farmer=batch_obj.farmer,
        defaults={"current_balance": Decimal("0.00")},
    )

    # Credit wallet with immutable ledger entry
    desc = (
        f"Payout for Batch {batch_obj.batch_id}: {batch_obj.volume_kg}kg "
        f"{batch_obj.crop.name} (Grade {batch_obj.ai_grade})"
    )
    transaction_record = wallet.credit(final_payout, desc)

    logger.info(
        "Processed wallet payout for Batch %s: ₹%s credited to farmer %s",
        batch_obj.batch_id,
        final_payout,
        batch_obj.farmer.identifier,
    )

    return {
        "success": True,
        "batch_id": batch_obj.batch_id,
        "farmer_identifier": batch_obj.farmer.identifier,
        "credited_amount": float(final_payout),
        "new_wallet_balance": float(wallet.current_balance),
        "transaction_id": transaction_record.id,
        "timestamp": transaction_record.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "pricing_breakdown": breakdown,
    }


# ==============================================================================
# E. BATCH TRACEABILITY SERVICE
# ==============================================================================

def get_batch_traceability(batch_id: str) -> Dict[str, Any]:
    """
    Generates a full provenance audit trail for a produce batch from origin
    farm, through micro-hub AI grading, to urban retailer fulfillment.

    :param batch_id: Unique batch identifier (e.g., 'K2K-BTH-20260906-XXXX')
    :return: Structured traceability timeline dictionary.
    """
    try:
        batch = Batch.objects.select_related("farmer", "crop", "hub").get(batch_id=str(batch_id).strip())
    except Batch.DoesNotExist as exc:
        raise ObjectDoesNotExist(f"Batch with identifier '{batch_id}' not found.") from exc

    farmer = batch.farmer
    hub = batch.hub
    crop = batch.crop

    # Find matched pre-orders if allocated or delivered
    matched_order = (
        DemandOrder.objects.filter(crop=crop, status__in=[DemandOrder.Status.ALLOCATED, DemandOrder.Status.FULFILLED])
        .select_related("retailer")
        .order_by("-updated_at")
        .first()
    )

    timeline_events = [
        {
            "step": 1,
            "title": "Harvested at Origin Farm",
            "icon": "🌱",
            "status": "COMPLETED",
            "date": batch.harvest_date.strftime("%d %b %Y"),
            "details": f"Farm: {farmer.get_full_name()} • Location: {farmer.address or 'Niphad Cluster'}, {farmer.state or 'Maharashtra'}",
            "verified": True,
        },
        {
            "step": 2,
            "title": "Drop-off & AI Quality Grading",
            "icon": "🏬",
            "status": "COMPLETED",
            "date": batch.received_at.strftime("%d %b %Y %H:%M"),
            "details": f"Hub: {hub.name} ({hub.code}) • Optical Grade: Grade {batch.ai_grade} ({batch.ai_confidence_score}% confidence)",
            "verified": True,
        },
        {
            "step": 3,
            "title": "Direct Bank Settlement",
            "icon": "💳",
            "status": "COMPLETED",
            "date": batch.received_at.strftime("%d %b %Y %H:%M"),
            "details": f"Farmer Digital Wallet credited with ₹{batch.calculate_valuation()} • Middleman fee 0.0%",
            "verified": True,
        },
        {
            "step": 4,
            "title": "Urban Cold-Chain Transit",
            "icon": "🚚",
            "status": "IN_PROGRESS" if batch.status == Batch.Status.ALLOCATED else ("COMPLETED" if batch.status == Batch.Status.DELIVERED else "STAGED_AT_HUB"),
            "date": timezone.now().strftime("%d %b %Y"),
            "details": (
                f"Consigned to: {matched_order.retailer.get_full_name()} ({matched_order.delivery_address or 'Mumbai Metro'})"
                if matched_order
                else "Active in Micro-Hub cold buffer (5°C - 8°C ambient humidity control)"
            ),
            "verified": bool(matched_order),
        },
    ]

    return {
        "success": True,
        "batch_id": batch.batch_id,
        "crop_name": crop.name,
        "crop_category": crop.get_category_display(),
        "volume_kg": float(batch.volume_kg),
        "ai_grade": batch.ai_grade,
        "ai_confidence_score": float(batch.ai_confidence_score),
        "status": batch.get_status_display(),
        "farm_origin": {
            "farmer_name": farmer.get_full_name(),
            "location": farmer.address or "Nashik Agricultural Cluster",
            "state": farmer.state or "Maharashtra",
            "harvest_date": batch.harvest_date.strftime("%Y-%m-%d"),
        },
        "hub_details": {
            "hub_name": hub.name,
            "hub_code": hub.code,
            "district": hub.district,
            "state": hub.state,
        },
        "hub_inspection": {
            "hub_name": hub.name,
            "hub_code": hub.code,
            "location": f"{hub.location}, {hub.district}",
            "ai_grade": batch.ai_grade,
            "confidence_score": float(batch.ai_confidence_score),
            "inspected_at": batch.received_at.strftime("%d %b %Y %H:%M"),
        },
        "financial_settlement": {
            "net_payout": float(batch.calculate_valuation()),
            "disintermediation_saving": float((batch.calculate_valuation() * Decimal("0.28")).quantize(Decimal("0.01"))),
            "settled_via": "K2K Direct Farmer Wallet",
            "settlement_status": "COMPLETED",
        },
        "logistics_cold_chain": {
            "cold_chain_temp": "4°C - 8°C (Controlled Atmosphere)",
            "urban_delivery_status": "In-Transit to Retail Fulfillment Center" if batch.status == Batch.Status.ALLOCATED else "Micro-Hub Buffer",
            "estimated_arrival": (timezone.now() + timedelta(hours=3)).strftime("%d %b %Y %H:%M"),
            "vehicle_type": "3.5T Solar Reefer Van",
        },
        "timeline": timeline_events,
    }


# ==============================================================================
# F. MOCKED DYNAMIC ROUTING SERVICE
# ==============================================================================

def mock_dynamic_route(hub_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Simulates AI multi-stop dynamic dispatch routing optimizing vehicle capacity,
    crop perishability windows, and urban retail delivery corridors.

    :param hub_id: Primary key of origin MicroHub (optional).
    :return: Optimized routing plan dictionary.
    """
    if hub_id:
        hub = MicroHub.objects.filter(pk=hub_id).first()
    else:
        hub = MicroHub.objects.filter(is_active=True).first()

    hub_name = hub.name if hub else "Nashik Agro Cluster Hub #1"
    hub_code = hub.code if hub else "HUB-NSK-01"

    stops = [
        {
            "stop_number": 1,
            "type": "PICKUP",
            "location": f"{hub_name} ({hub_code})",
            "volume_loaded_kg": 1500.0,
            "eta": "06:00 AM",
        },
        {
            "stop_number": 2,
            "type": "DELIVERY",
            "recipient": "FreshBazaar Distribution Center (Bandra Kurla Complex, Mumbai)",
            "volume_delivered_kg": 1000.0,
            "eta": "08:45 AM",
        },
        {
            "stop_number": 3,
            "type": "DELIVERY",
            "recipient": "QuickMart Urban Fulfillment Store (Vashi Sector 19, Navi Mumbai)",
            "volume_delivered_kg": 500.0,
            "eta": "09:45 AM",
        },
    ]

    optimized_stops = [
        {
            "stop_number": 1,
            "retailer_name": "FreshBazaar Distribution Center",
            "crop": "Red Onion & Tomato",
            "volume_kg": 1000.0,
            "priority": "HIGH (Perishable)",
            "distance_km": 142.5,
            "eta_minutes": 165,
        },
        {
            "stop_number": 2,
            "retailer_name": "QuickMart Urban Fulfillment Store",
            "crop": "Roma Field Tomato",
            "volume_kg": 500.0,
            "priority": "STANDARD",
            "distance_km": 174.5,
            "eta_minutes": 225,
        },
    ]

    return {
        "route_id": f"K2K-ROUTE-{timezone.now().strftime('%Y%m%d')}-01",
        "origin_hub": hub_name,
        "origin_code": hub_code,
        "hub_name": hub_name,
        "vehicle_type": "3.5T Reefer Van (Solar Cold Chain Enabled)",
        "dispatch_vehicle": {
            "id": "REEFER-EV-04",
            "type": "3.5T Reefer Van (Solar Cold Chain Enabled)",
            "battery_level": "92%",
            "co2_savings_kg": 46.2,
        },
        "cold_chain_temp": "5.4°C (Optimal for Leafy & Solanaceous Produce)",
        "perishability_priority": "CRITICAL - Dispatch within 6 hours (Tomato & Alphonso Mango priority)",
        "total_distance_km": 174.5,
        "estimated_transit_time": "3 hours 45 mins",
        "co2_emissions_saved_kg": 46.2,
        "stops": stops,
        "optimized_stops": optimized_stops,
        "total_stops": len(stops),
        "total_volume_kg": 1500.0,
        "total_estimated_time_minutes": 225,
    }

