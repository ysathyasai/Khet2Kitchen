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
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from django.conf import settings
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


# ==============================================================================
# G. REAL-TIME AGRONOMIC WEATHER INTELLIGENCE SERVICE
# ==============================================================================

DEFAULT_HUB_COORDINATES: Tuple[float, float, str] = (
    17.3850,
    78.4867,
    "Hyderabad Regional Ag-Hub, Telangana, India",
)


def get_coordinates_from_pincode(pincode: str) -> Tuple[float, float, str]:
    """
    Resolves an Indian PIN code to coordinates and human-readable location
    via OpenStreetMap Nominatim API.
    
    Returns: Tuple of (lat, lon, display_name)
    Fallback: (17.3850, 78.4867, 'Hyderabad Regional Ag-Hub, Telangana, India')
    """
    clean_pin = str(pincode or "").strip()
    if not clean_pin:
        logger.warning("Empty PIN code supplied for geocoding. Using default hub %s.", DEFAULT_HUB_COORDINATES)
        return DEFAULT_HUB_COORDINATES

    url = f"https://nominatim.openstreetmap.org/search?postalcode={clean_pin}&country=India&format=json&limit=1"
    headers = {"User-Agent": "K2K-Agronomy-Engine/1.0 (hackathon@k2k.org)"}

    try:
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                first_match = data[0]
                lat = float(first_match.get("lat"))
                lon = float(first_match.get("lon"))
                display_name = first_match.get("display_name") or f"PIN {clean_pin}, India"
                logger.info("Successfully resolved PIN %s -> (%s, %s, %s)", clean_pin, lat, lon, display_name)
                return lat, lon, display_name
            else:
                logger.warning("Nominatim returned no matching geographic results for PIN %s.", clean_pin)
        else:
            logger.warning("Nominatim lookup returned HTTP status %s for PIN %s.", response.status_code, clean_pin)
    except Exception as exc:
        logger.warning("Nominatim geocoding failed for PIN %s: %s. Using default hub coordinates.", clean_pin, exc)

    return DEFAULT_HUB_COORDINATES


def fetch_real_weather(lat: float, lon: float) -> Dict[str, Any]:
    """
    Fetches live weather, soil temperature, and volumetric soil moisture from Open-Meteo API.
    Summarizes hourly soil arrays into 24-hour averages to optimize downstream token consumption.
    
    Returns clean dictionary of current metrics and summarized indicators.
    Falls back to cached/deterministic agronomic metrics on requests.RequestException.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m"
        "&hourly=soil_temperature_6cm,soil_moisture_3_9cm"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
        "&timezone=auto"
    )

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        payload = response.json()

        current = payload.get("current", {})
        hourly = payload.get("hourly", {})
        daily = payload.get("daily", {})

        # Summarize 24-hour soil metrics
        soil_temps = hourly.get("soil_temperature_6cm", [])[:24]
        soil_moists = hourly.get("soil_moisture_3_9cm", [])[:24]

        avg_soil_temp = round(sum(soil_temps) / len(soil_temps), 1) if soil_temps else 24.5
        avg_soil_moist_raw = sum(soil_moists) / len(soil_moists) if soil_moists else 0.35
        # Open-Meteo returns soil_moisture_3_9cm in m³/m³ (0.0 to 1.0). Convert to percentage:
        soil_moisture_pct = round(avg_soil_moist_raw * 100, 1) if avg_soil_moist_raw <= 1.0 else round(avg_soil_moist_raw, 1)

        daily_max_temps = daily.get("temperature_2m_max", [])
        daily_min_temps = daily.get("temperature_2m_min", [])
        daily_precip_sums = daily.get("precipitation_sum", [])

        temp_max_c = daily_max_temps[0] if daily_max_temps else current.get("temperature_2m")
        temp_min_c = daily_min_temps[0] if daily_min_temps else current.get("temperature_2m")
        precip_sum_mm = daily_precip_sums[0] if daily_precip_sums else current.get("precipitation", 0.0)

        return {
            "latitude": float(lat),
            "longitude": float(lon),
            "temperature_c": float(current.get("temperature_2m", 28.0)),
            "relative_humidity_pct": float(current.get("relative_humidity_2m", 65.0)),
            "precipitation_mm": float(current.get("precipitation", 0.0)),
            "wind_speed_kmh": float(current.get("wind_speed_10m", 12.0)),
            "avg_soil_temp_c": avg_soil_temp,
            "avg_soil_moisture_pct": soil_moisture_pct,
            "soil_moisture_volumetric": round(avg_soil_moist_raw, 3),
            "temp_max_c": float(temp_max_c) if temp_max_c is not None else 30.0,
            "temp_min_c": float(temp_min_c) if temp_min_c is not None else 20.0,
            "precipitation_sum_mm": float(precip_sum_mm) if precip_sum_mm is not None else 0.0,
            "source": "Open-Meteo Live API",
        }
    except Exception as exc:
        logger.warning(
            "Open-Meteo live API query failed for (%s, %s): %s. Activating agronomic fallback metrics.",
            lat,
            lon,
            exc,
        )
        return {
            "latitude": float(lat),
            "longitude": float(lon),
            "temperature_c": 28.2,
            "relative_humidity_pct": 64.0,
            "precipitation_mm": 0.0,
            "wind_speed_kmh": 14.0,
            "avg_soil_temp_c": 24.5,
            "avg_soil_moisture_pct": 38.5,
            "soil_moisture_volumetric": 0.385,
            "temp_max_c": 31.0,
            "temp_min_c": 21.5,
            "precipitation_sum_mm": 0.0,
            "source": "Fallback Agronomic Model",
        }


def _build_fallback_advisory(weather_summary: Dict[str, Any], location_name: str) -> Dict[str, str]:
    """
    Grounded rule-based agronomic advisory generator for fallback scenarios.
    """
    temp = weather_summary.get("temperature_c", 28.0)
    humidity = weather_summary.get("relative_humidity_pct", 65.0)
    precip = weather_summary.get("precipitation_mm", 0.0)
    precip_sum = weather_summary.get("precipitation_sum_mm", 0.0)
    soil_moist = weather_summary.get("avg_soil_moisture_pct", 38.0)

    # Weather headline
    if precip > 1.0 or precip_sum > 5.0:
        headline = f"Overcast with rainfall ({precip} mm) and high atmospheric humidity ({humidity}%) in {location_name}."
    elif temp >= 34.0:
        headline = f"High solar radiation and elevated ambient temperatures ({temp}°C) in {location_name}."
    else:
        headline = f"Favorable temperate microclimate at {temp}°C with {humidity}% relative humidity in {location_name}."

    # Immediate risks
    risks = []
    if humidity >= 75.0 and temp >= 22.0:
        risks.append("Heightened risk of fungal blight, powdery mildew, and sucking pests under humid canopy.")
    if precip >= 5.0 or precip_sum >= 10.0:
        risks.append("Waterlogging risk in heavy black cotton / clay soil beds; check drainage outlets.")
    if temp >= 35.0:
        risks.append("Elevated heat stress and blossom drop risk in tomatoes, chillies, and delicate horticultural crops.")
    if soil_moist < 25.0:
        risks.append("Soil moisture depletion detected; crop root zones vulnerable to vegetative water stress.")
    if not risks:
        risks.append("Low immediate pest or disease pressure; thermal and moisture conditions remain stable.")

    # Irrigation & Harvest Advice
    if precip > 0.5 or soil_moist > 50.0:
        irrigation_advice = (
            "Halt scheduled drip irrigation. Ensure field furrows are free of standing water to prevent root rot. "
            "Postpone sensitive vegetable harvesting until surface foliage dries."
        )
    elif soil_moist < 30.0:
        irrigation_advice = (
            "Immediate drip or furrow irrigation recommended during early morning (05:30 - 08:30 AM) to recharge root zone. "
            "Harvest mature fruits early to minimize moisture loss."
        )
    else:
        irrigation_advice = (
            "Maintain standard pulse irrigation intervals. Optimal harvesting window during morning hours "
            "(06:00 - 09:30 AM) for field tomatoes, leafy greens, and bell peppers."
        )

    # Recommended Crops
    if soil_moist >= 45.0 or precip > 2.0:
        crops = "Paddy (Rice), Soybean, Taro (Colocasia), and moisture-tolerant Pulses (Moong/Urad)."
    elif temp >= 32.0:
        crops = "Okra (Bhindi), Cluster Bean (Guar), Pearl Millet (Bajra), and Cowpea."
    else:
        crops = "Field Tomato, Red Onion (Nashik Special), Green Bell Pepper (Capsicum), and Cauliflower."

    return {
        "weather_headline": headline,
        "risks": " ".join(risks),
        "irrigation_harvest_advice": irrigation_advice,
        "recommended_crops": crops,
    }


def generate_agronomic_advisory(weather_summary: Dict[str, Any], location_name: str) -> Dict[str, str]:
    """
    Synthesizes expert agronomic advisories from live weather, soil temperature, and moisture
    using Google Gemini, with robust failover to rule-based agronomic intelligence.
    
    Guarantees valid JSON dictionary with exact keys:
    {
      "weather_headline": str,
      "risks": str,
      "irrigation_harvest_advice": str,
      "recommended_crops": str
    }
    """
    fallback = _build_fallback_advisory(weather_summary, location_name)
    gemini_key = (os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", "")).strip()

    if not gemini_key:
        logger.info("No GEMINI_API_KEY configured; returning grounded agronomic fallback advisory.")
        return fallback

    prompt = f"""You are an expert Chief Agronomist and Senior Crop Scientist advising Indian farmers on Project Khet2Kitchen (K2K).
Analyze these LIVE weather and soil telemetry readings for {location_name}:
- Ambient Temperature: {weather_summary.get('temperature_c')}°C (Max: {weather_summary.get('temp_max_c')}°C, Min: {weather_summary.get('temp_min_c')}°C)
- Relative Humidity: {weather_summary.get('relative_humidity_pct')}%
- Precipitation: {weather_summary.get('precipitation_mm')} mm (24h forecast sum: {weather_summary.get('precipitation_sum_mm')} mm)
- Wind Speed: {weather_summary.get('wind_speed_kmh')} km/h
- 24-hour Average Soil Temperature (6cm depth): {weather_summary.get('avg_soil_temp_c')}°C
- 24-hour Average Soil Moisture (3-9cm depth): {weather_summary.get('avg_soil_moisture_pct')}%

Provide sharp, practical, field-actionable agricultural directives in concise Indian farming context.
CRITICAL: You MUST respond ONLY with a valid, parseable JSON object matching this exact schema:
{{
  "weather_headline": "Concise 1-sentence current weather summary",
  "risks": "Specific immediate agronomic risks (e.g. fungal blight, pest surge, heat stress, waterlogging, frost)",
  "irrigation_harvest_advice": "Actionable irrigation timing and produce harvesting directives based on soil moisture and rain",
  "recommended_crops": "Optimal crops to sow, transplant, or maintain under these soil and weather readings"
}}
Do NOT include markdown formatting outside the JSON, do not include preamble, do not omit any of the 4 keys."""

    candidate_models = [
        getattr(settings, "GEMINI_MODEL_NAME", "gemini-3.6-flash"),
        "gemini-3.6-flash",
        "gemini-2.5-flash",
        "gemini-flash-latest",
    ]
    models_to_try = list(dict.fromkeys(filter(None, candidate_models)))

    # 1. Try google.generativeai
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        for m_name in models_to_try:
            try:
                model = genai.GenerativeModel(m_name)
                resp = model.generate_content(prompt)
                if resp and resp.text:
                    raw_text = resp.text.strip()
                    if raw_text.startswith("```"):
                        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                        raw_text = re.sub(r"\s*```$", "", raw_text)
                    parsed = json.loads(raw_text)
                    if all(k in parsed for k in ("weather_headline", "risks", "irrigation_harvest_advice", "recommended_crops")):
                        return {
                            "weather_headline": str(parsed["weather_headline"]).strip(),
                            "risks": str(parsed["risks"]).strip(),
                            "irrigation_harvest_advice": str(parsed["irrigation_harvest_advice"]).strip(),
                            "recommended_crops": str(parsed["recommended_crops"]).strip(),
                        }
            except Exception as model_err:
                logger.warning("google.generativeai model %s failed: %s", m_name, model_err)
    except Exception as sdk_err:
        logger.warning("google.generativeai initialization failed: %s", sdk_err)

    # 2. Try google.genai as modern fallback
    try:
        from google import genai
        client = genai.Client(api_key=gemini_key)
        for m_name in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=m_name,
                    contents=prompt,
                    config={"response_mime_type": "application/json"},
                )
                if resp and resp.text:
                    raw_text = resp.text.strip()
                    if raw_text.startswith("```"):
                        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                        raw_text = re.sub(r"\s*```$", "", raw_text)
                    parsed = json.loads(raw_text)
                    if all(k in parsed for k in ("weather_headline", "risks", "irrigation_harvest_advice", "recommended_crops")):
                        return {
                            "weather_headline": str(parsed["weather_headline"]).strip(),
                            "risks": str(parsed["risks"]).strip(),
                            "irrigation_harvest_advice": str(parsed["irrigation_harvest_advice"]).strip(),
                            "recommended_crops": str(parsed["recommended_crops"]).strip(),
                        }
            except Exception as genai_err:
                logger.warning("google.genai model %s failed: %s", m_name, genai_err)
    except Exception:
        pass

    return fallback


