from decimal import Decimal
import json
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import TemplateDoesNotExist
from django.views.decorators.http import require_POST

from core.decorators import role_required
from core.models import (
    Batch,
    Crop,
    DemandOrder,
    FarmerWallet,
    HarvestSchedule,
    MicroHub,
    User,
    WalletTransaction,
)
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
from core.sarvam_voice_service import SarvamVoiceService
from core.vision import analyze_crop_image
from core.voice_services import (
    detect_spoken_language,
    generate_speech,
    process_intent_with_gemini,
    transcribe_audio,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Computer Vision AI Grading API Endpoint
# ==============================================================================

@require_POST
def api_grade_batch(request):
    """
    Simulates optical quality grading on an uploaded harvest produce photo.
    Creates an active Batch, triggers automated settlement into the FarmerWallet,
    and returns complete financial and traceability metadata.
    """
    image_file = request.FILES.get("image")
    crop_id = request.POST.get("crop_id") or request.GET.get("crop_id")
    volume_str = request.POST.get("volume_kg", "100.00")

    if not crop_id:
        return JsonResponse({"success": False, "error": "crop_id parameter is required."}, status=400)

    try:
        crop = Crop.objects.get(pk=crop_id)
    except (Crop.DoesNotExist, ValueError):
        return JsonResponse({"success": False, "error": f"Crop with ID {crop_id} does not exist."}, status=404)

    if not image_file:
        return JsonResponse({"success": False, "error": "Produce image file is required for optical scanning."}, status=400)

    try:
        volume_kg = max(Decimal("1.00"), Decimal(str(volume_str)))
    except Exception:
        volume_kg = Decimal("100.00")

    # 1. Run Computer Vision quality assessment
    try:
        vision_report = analyze_crop_image(image_file, crop)
    except Exception as exc:
        logger.error("Vision AI analysis failed: %s", exc)
        return JsonResponse({"success": False, "error": f"Vision AI analysis failed: {exc}"}, status=500)

    grade = vision_report["grade"]
    confidence_score = vision_report["confidence_score"]

    # 2. Identify or select the farmer
    if request.user.is_authenticated and getattr(request.user, "role", None) == User.Role.FARMER:
        farmer = request.user
    else:
        farmer = User.objects.filter(role=User.Role.FARMER).first()

    hub = MicroHub.objects.filter(is_active=True).first()

    batch_obj = None
    wallet_info = None

    # 3. Create persistent Batch and execute instantaneous wallet settlement
    if farmer and hub:
        try:
            batch_obj = Batch.objects.create(
                farmer=farmer,
                hub=hub,
                crop=crop,
                volume_kg=volume_kg,
                ai_grade=grade,
                ai_confidence_score=confidence_score,
                status=Batch.Status.QUALITY_INSPECTED,
            )
            payout_result = process_batch_payout(batch_obj)
            wallet_info = {
                "wallet_credited": payout_result["credited_amount"],
                "new_wallet_balance": payout_result["new_wallet_balance"],
                "transaction_id": payout_result["transaction_id"],
            }
        except Exception as exc:
            logger.error("Batch creation or payout settlement failed: %s", exc)

    # 4. Compute Breakdown for the response payload
    base_price = crop.base_price
    base_value = (volume_kg * base_price).quantize(Decimal("0.01"))
    modifiers = {
        Batch.Grade.GRADE_A: Decimal("0.20"),
        Batch.Grade.GRADE_B: Decimal("0.00"),
        Batch.Grade.GRADE_C: Decimal("-0.25"),
    }
    modifier_pct = modifiers.get(grade, Decimal("0.00"))
    grade_modifier_amount = (base_value * modifier_pct).quantize(Decimal("0.01"))
    gross_value = base_value + grade_modifier_amount

    logistics_rate = Decimal("1.50")
    logistics_deduction = (volume_kg * logistics_rate).quantize(Decimal("0.01"))
    final_payout = max(Decimal("0.00"), gross_value - logistics_deduction).quantize(Decimal("0.01"))

    effective_price_per_kg = (final_payout / volume_kg).quantize(Decimal("0.01"))
    traditional_mandi_payout = (gross_value * Decimal("0.72")).quantize(Decimal("0.01"))
    disintermediation_gain = max(Decimal("0.00"), final_payout - traditional_mandi_payout).quantize(Decimal("0.01"))
    extra_income_pct = (
        ((disintermediation_gain / traditional_mandi_payout) * Decimal("100.0")).quantize(Decimal("0.10"))
        if traditional_mandi_payout > Decimal("0.00")
        else Decimal("0.00")
    )

    return JsonResponse({
        "success": True,
        "batch_id": batch_obj.batch_id if batch_obj else f"K2K-BTH-SIMULATED",
        "crop_id": crop.id,
        "crop_name": crop.name,
        "volume_kg": float(volume_kg),
        "grade": grade,
        "grade_display": vision_report["grade_display"],
        "confidence_score": float(confidence_score),
        "defect_percentage": float(vision_report["defect_percentage"]),
        "rationale": vision_report["rationale"],
        "wallet": wallet_info,
        "metrics": {
            "color_uniformity_pct": float(vision_report["metrics"]["color_uniformity_pct"]),
            "size_consistency_pct": float(vision_report["metrics"]["size_consistency_pct"]),
            "surface_firmness": vision_report["metrics"]["surface_firmness"],
            "optical_scan_resolution": vision_report["metrics"]["optical_scan_resolution"],
        },
        "financial_breakdown": {
            "base_price_per_kg": float(base_price),
            "base_value": float(base_value),
            "grade_modifier_pct": int(modifier_pct * 100),
            "grade_modifier_amount": float(grade_modifier_amount),
            "gross_value": float(gross_value),
            "logistics_rate_per_kg": float(logistics_rate),
            "logistics_deduction": float(logistics_deduction),
            "final_payout": float(final_payout),
            "effective_price_per_kg": float(effective_price_per_kg),
            "traditional_mandi_payout": float(traditional_mandi_payout),
            "disintermediation_gain": float(disintermediation_gain),
            "extra_income_pct": float(extra_income_pct),
        },
    })


# ==============================================================================
# Batch Traceability & Provenance API Endpoint
# ==============================================================================

def api_trace_batch(request, batch_id):
    """
    Returns full provenance timeline for a produce batch.
    Used by retailers and consumers to verify direct farm origin and AI inspection.
    """
    try:
        data = get_batch_traceability(batch_id)
        payload = {"success": True, "traceability": data}
        payload.update(data)
        return JsonResponse(payload)
    except ObjectDoesNotExist as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=404)
    except Exception as exc:
        logger.error("Traceability API failed for %s: %s", batch_id, exc)
        return JsonResponse({"success": False, "error": f"Failed to retrieve batch traceability: {exc}"}, status=500)


# ==============================================================================
# Mocked Dynamic Dispatch Routing API Endpoint
# ==============================================================================

def api_dynamic_route(request, hub_id=None):
    """
    Returns AI-optimized dispatch route from a MicroHub to urban retailers.
    """
    try:
        route_plan = mock_dynamic_route(hub_id)
        return JsonResponse({
            "success": True,
            "route": route_plan,
            "route_plan": route_plan,
        })
    except Exception as exc:
        logger.error("Dynamic route calculation failed: %s", exc)
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


# ==============================================================================
# Digital Wallet Withdrawal Endpoint
# ==============================================================================

@require_POST
@login_required
def api_withdraw_wallet(request):
    """
    Enables farmers to withdraw funds from their digital wallet to their bank/UPI account.
    """
    if getattr(request.user, "role", None) != User.Role.FARMER:
        return JsonResponse({"success": False, "error": "Only registered farmers can initiate withdrawals."}, status=403)

    amount_str = request.POST.get("amount")
    if not amount_str:
        return JsonResponse({"success": False, "error": "Withdrawal amount is required."}, status=400)

    try:
        amount = Decimal(str(amount_str))
        wallet, _ = FarmerWallet.objects.get_or_create(farmer=request.user)
        tx = wallet.debit(amount, f"Instant IMPS settlement to {request.user.phone_number}@upi")
        return JsonResponse({
            "success": True,
            "message": f"₹{amount} successfully settled to your bank account via instant UPI rail.",
            "new_balance": float(wallet.current_balance),
            "transaction_id": tx.id,
        })
    except ValidationError as exc:
        msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
        return JsonResponse({"success": False, "error": msg}, status=400)
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


# ==============================================================================
# Hybrid Vernacular Voice Assistant Endpoint (Sarvam AI + Google Gemini)
# ==============================================================================

@require_POST
@login_required
def api_voice_assist(request):
    """
    Handles audio query from farmer via Sarvam AI STT, processes intent and
    retrieves database ground-truth via Google Gemini, and converts the response
    to speech using Sarvam AI Bulbul TTS.
    """
    if getattr(request.user, "role", None) != User.Role.FARMER:
        return JsonResponse({"success": False, "error": "Only registered farmers can access the voice assistant."}, status=403)

    audio_file = request.FILES.get("audio") or request.FILES.get("audio_file") or request.FILES.get("file")
    query_text = (
        request.POST.get("text")
        or request.POST.get("voice_transcript")
        or request.POST.get("query")
        or request.POST.get("command")
        or request.POST.get("message")
        or ""
    ).strip()

    req_lang = (request.POST.get("language") or request.POST.get("language_code") or "auto").strip()

    if not query_text and getattr(request, "content_type", "") == "application/json":
        try:
            body_data = json.loads(request.body.decode("utf-8"))
            query_text = (
                body_data.get("text")
                or body_data.get("voice_transcript")
                or body_data.get("query")
                or body_data.get("command")
                or body_data.get("message")
                or ""
            ).strip()
            if not req_lang or req_lang == "auto":
                req_lang = (body_data.get("language") or body_data.get("language_code") or "auto").strip()
            if not query_text and "query" in body_data:
                query_text = (body_data.get("query") or "").strip()
        except Exception:
            pass

    # Support clearing/resetting conversation memory
    reset_chat = (
        request.POST.get("reset_chat", "").lower() in ("1", "true", "yes") or
        request.GET.get("reset_chat", "").lower() in ("1", "true", "yes")
    )
    if reset_chat:
        request.session["k2k_voice_chat_history"] = []
        request.session["k2k_voice_user_name"] = None
        request.session.modified = True
        return JsonResponse({"success": True, "message": "Voice conversation context reset.", "conversation_history": []})

    safe_text = query_text.encode('ascii', 'backslashreplace').decode('ascii') if query_text else ""
    try:
        print(f"\n{'='*60}\n[K2K VOICE ASSISTANT] Query received from {request.user.identifier}\nAudio: {bool(audio_file)} | Text: '{safe_text}'\n{'='*60}", flush=True)
    except Exception:
        pass

    if not audio_file and not query_text:
        try:
            print("[K2K VOICE ASSISTANT] Rejected: empty audio and text.", flush=True)
        except Exception:
            pass
        return JsonResponse({"success": False, "error": "Audio file or text query is required."}, status=400)

    try:
        transcribed_text = ""
        stt_detected_lang = None

        # 1. Retrieve multi-turn conversation memory from session
        chat_history = request.session.get("k2k_voice_chat_history", [])
        user_preferred_name = request.session.get("k2k_voice_user_name", None)

        # 2. STT: If audio file was uploaded, transcribe via Sarvam Saaras v3
        if audio_file:
            stt_transcript, stt_lang = SarvamVoiceService.transcribe_audio(audio_file, language_hint=req_lang)
            if stt_transcript:
                transcribed_text = stt_transcript
                stt_detected_lang = stt_lang
            elif query_text:
                transcribed_text = query_text
            else:
                transcribed_text = ""
        else:
            transcribed_text = query_text

        if not transcribed_text:
            is_en = req_lang.startswith("en")
            fallback_msg = (
                "I couldn't hear your voice clearly. Please tap the microphone to speak again."
                if is_en
                else "माफ़ कीजिए, आपकी आवाज़ साफ़ नहीं आई। कृपया दोबारा बोलें।"
            )
            return JsonResponse({
                "success": False,
                "error": "Could not understand audio. Please try speaking again.",
                "response_text": fallback_msg,
                "voice_reply_text": fallback_msg,
                "audio_source": "browser_speech",
                "language_code": "en-IN" if is_en else "hi-IN",
            })

        # Determine exact spoken language (English vs Indic)
        language_code = detect_spoken_language(
            transcribed_text,
            req_lang=req_lang if req_lang != "auto" else (stt_detected_lang or "auto"),
        )

        # 3. INTENT & DB GROUNDING via Gemini (with automatic DB-grounded fallback)
        gemini_result = process_intent_with_gemini(
            transcribed_text=transcribed_text,
            farmer_user=request.user,
            language_code=language_code,
            conversation_history=chat_history,
            preferred_name=user_preferred_name,
        )

        response_text = gemini_result["response_text"]
        detected_intent = gemini_result["intent"]
        lang = gemini_result.get("language_code", language_code)

        # 4. Update session conversation context
        extracted_name = gemini_result.get("extracted_farmer_name")
        if extracted_name:
            user_preferred_name = extracted_name
            request.session["k2k_voice_user_name"] = user_preferred_name

        chat_history.append({
            "user": transcribed_text,
            "assistant": response_text,
            "intent": detected_intent,
            "language": lang,
        })
        request.session["k2k_voice_chat_history"] = chat_history[-10:]
        request.session.modified = True

        # 5. TTS: Synthesize speech via Sarvam Bulbul v3 (speaker="shubh")
        # If credits are finished or API fails, returns None and signals browser_speech fallback
        audio_base64, audio_source = generate_speech(response_text, language_code=lang, return_source=True)
        if not audio_base64:
            audio_source = "browser_speech"
        sarvam_tts_enabled = bool(audio_base64 and audio_source == "sarvam")

        return JsonResponse({
            "success": True,
            "transcript": transcribed_text,
            "transcribed_text": transcribed_text,
            "detected_language": lang,
            "language": lang,
            "language_code": lang,
            "intent": detected_intent,
            "voice_reply_text": response_text,
            "response_text": response_text,
            "audio_base64": audio_base64 or "",
            "audio_source": audio_source,
            "sarvam_tts_enabled": sarvam_tts_enabled,
            "stt_detected_language": stt_detected_lang,
            "preferred_name": user_preferred_name or "",
            "conversation_history": chat_history,
        })
    except Exception as exc:
        logger.error("Voice assistant processing failed: %s", exc)
        return JsonResponse({
            "success": False,
            "error": f"Voice Assistant error: {exc}",
            "response_text": "माफ़ कीजिए, वॉयस सेवा में कुछ तकनीकी समस्या आई है। कृपया कुछ देर बाद प्रयास करें।",
            "audio_source": "browser_speech",
        }, status=500)


# ==============================================================================
# Real-Time Agronomic Weather Intelligence API Endpoint
# ==============================================================================

def api_weather_advisory(request):
    """
    Real-time Agronomic Weather Intelligence API.
    Accepts GET query parameters:
      - lat & lon: Direct geographic coordinates.
      - pincode: 6-digit Indian postal code (resolved via Nominatim).
      - location_name: Optional human-readable region label.

    Resolves coordinates, queries Open-Meteo telemetry (weather, soil temperature,
    volumetric soil moisture), generates Gemini AI agronomic advisory,
    and returns a unified JSON payload with HTTP status 200.
    """
    if request.method != "GET":
        return JsonResponse({"success": False, "error": "Method not allowed. Use GET."}, status=405)

    lat_param = request.GET.get("lat")
    lon_param = request.GET.get("lon")
    pincode = request.GET.get("pincode", "").strip()
    custom_location = request.GET.get("location_name", "").strip()

    lat = None
    lon = None
    resolved_name = custom_location

    if lat_param and lon_param:
        try:
            lat = float(lat_param)
            lon = float(lon_param)
            if not resolved_name:
                resolved_name = f"Coordinates ({lat:.3f}°N, {lon:.3f}°E)"
        except (ValueError, TypeError):
            return JsonResponse({"success": False, "error": "Invalid latitude or longitude format."}, status=400)
    elif pincode:
        lat, lon, geo_name = get_coordinates_from_pincode(pincode)
        if not resolved_name:
            resolved_name = geo_name
    elif request.user.is_authenticated and getattr(request.user, "pincode", None):
        pincode = request.user.pincode
        lat, lon, geo_name = get_coordinates_from_pincode(pincode)
        if not resolved_name:
            resolved_name = geo_name
    else:
        # Default fallback to central Ag-Hub (Hyderabad / Nashik)
        lat, lon, resolved_name = 17.3850, 78.4867, "Hyderabad Regional Ag-Hub, Telangana, India"

    weather_data = fetch_real_weather(lat, lon)
    advisory_data = generate_agronomic_advisory(weather_data, resolved_name)

    return JsonResponse({
        "success": True,
        "location": {
            "latitude": lat,
            "longitude": lon,
            "display_name": resolved_name,
            "pincode": pincode or "",
        },
        "weather": weather_data,
        "advisory": advisory_data,
    }, status=200)


# ==============================================================================
# Central Dispatcher
# ==============================================================================

@login_required
def dashboard_dispatcher_view(request):
    """
    Central router that inspects the authenticated user's role
    and redirects them to their respective portal dashboard.
    """
    return redirect(request.user.get_dashboard_url())


# ==============================================================================
# Role-Specific Dashboards (Skinny Views with Service Layer Integration)
# ==============================================================================

@role_required(User.Role.FARMER)
def farmer_dashboard_view(request):
    """
    Farmer Portal Dashboard - PWA Optimized.
    Integrates with:
    1. Digital Farmer Wallet & Transaction Ledger.
    2. AI Harvest Schedules & Alerts.
    3. Optical AI Grading Station & Transparent Pricing.
    """
    farmer = request.user
    recent_batches = (
        farmer.harvest_batches.select_related("crop", "hub")
        .order_by("-received_at")[:10]
    )

    # Attach transparent pricing breakdown to each batch
    batch_breakdowns = []
    total_gross_value = Decimal("0.00")
    total_net_payout = Decimal("0.00")
    total_disintermediation_gain = Decimal("0.00")

    for batch in recent_batches:
        try:
            breakdown = generate_transparent_pricing_breakdown(batch)
            batch_breakdowns.append({
                "batch": batch,
                "breakdown": breakdown,
            })
            total_gross_value += breakdown["gross_value"]
            total_net_payout += breakdown["final_payout"]
            total_disintermediation_gain += breakdown["disintermediation_gain"]
        except Exception as exc:
            logger.error("Failed to generate pricing breakdown for batch %s: %s", batch.batch_id, exc)
            batch_breakdowns.append({
                "batch": batch,
                "breakdown": None,
            })

    # Retrieve or provision digital wallet
    wallet, _ = FarmerWallet.objects.get_or_create(
        farmer=farmer,
        defaults={"current_balance": Decimal("0.00")},
    )
    recent_transactions = wallet.transactions.order_by("-timestamp")[:6]

    # Retrieve upcoming AI harvest schedules
    pending_schedules = farmer.harvest_schedules.filter(
        status=HarvestSchedule.Status.PENDING
    ).select_related("crop").order_by("recommended_date")[:5]

    active_hubs = MicroHub.objects.filter(is_active=True)[:5]
    crops = Crop.objects.filter(is_active=True)

    context = {
        "title": "Khet2Kitchen - Kisan Portal",
        "role": "FARMER",
        "user": farmer,
        "wallet": wallet,
        "recent_transactions": recent_transactions,
        "pending_schedules": pending_schedules,
        "batch_breakdowns": batch_breakdowns,
        "active_hubs": active_hubs,
        "crops": crops,
        "financial_summary": {
            "total_gross_value": total_gross_value,
            "total_net_payout": total_net_payout,
            "total_disintermediation_gain": total_disintermediation_gain,
        },
    }

    try:
        return render(request, "core/farmer_dashboard.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({
            "portal": "Farmer PWA Dashboard",
            "user": farmer.get_full_name() or farmer.identifier,
            "wallet_balance": float(wallet.current_balance),
            "batches_count": len(batch_breakdowns),
            "financial_summary": {
                "total_net_payout": str(total_net_payout),
                "total_disintermediation_gain": str(total_disintermediation_gain),
            },
            "status": "Operational",
        })


@role_required(User.Role.RETAILER)
def retailer_dashboard_view(request):
    """
    Retailer Portal Dashboard - B2B Urban Procurement.
    Integrates with demand forecasting engine to display AI recommended pre-orders
    and batch traceability search.
    """
    retailer = request.user
    demand_orders = (
        retailer.demand_orders.select_related("crop")
        .order_by("-created_at")[:10]
    )
    market_catalog = Crop.objects.filter(is_active=True)[:6]

    # Generate AI demand predictions for catalog produce
    ai_recommended_orders = []
    for crop in market_catalog:
        try:
            forecast = predict_demand(crop)
            ai_recommended_orders.append(forecast)
        except Exception as exc:
            logger.error("Error generating demand forecast for crop %s: %s", crop.name, exc)

    # Active batches available for provenance demonstration
    recent_active_batches = Batch.objects.select_related("crop", "farmer").order_by("-received_at")[:5]

    context = {
        "title": "Khet2Kitchen - Retailer Procurement",
        "role": "RETAILER",
        "user": retailer,
        "demand_orders": demand_orders,
        "market_catalog": market_catalog,
        "ai_recommended_orders": ai_recommended_orders,
        "recent_active_batches": recent_active_batches,
    }

    try:
        return render(request, "core/retailer_dashboard.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({
            "portal": "Retailer B2B Dashboard",
            "user": retailer.get_full_name() or retailer.identifier,
            "orders_count": demand_orders.count(),
            "ai_recommendations_count": len(ai_recommended_orders),
            "status": "Operational",
        })


@require_POST
@role_required(User.Role.RETAILER)
def allocate_order_view(request, order_id):
    """
    Endpoint allowing a retailer or operator to trigger automated supply allocation
    against an active pre-order.
    """
    order = get_object_or_404(DemandOrder, order_id=order_id, retailer=request.user)
    try:
        result = allocate_supply_to_order(order)
        if result["is_fully_fulfilled"]:
            messages.success(
                request,
                f"Order {order.order_id} successfully matched and fulfilled with {result['total_allocated_kg']}kg produce!"
            )
        elif result["total_allocated_kg"] > Decimal("0.00"):
            messages.info(
                request,
                f"Order {order.order_id} partially allocated with {result['total_allocated_kg']}kg. Remaining: {result['remaining_required_kg']}kg."
            )
        else:
            messages.warning(
                request,
                f"No matching available harvest batches found in micro-hubs for {order.crop.name} at this time."
            )
    except Exception as exc:
        logger.error("Allocation failed for order %s: %s", order.order_id, exc)
        messages.error(request, f"Supply allocation error: {exc}")

    return redirect("retailer_dashboard")


@role_required(User.Role.SUPPLIER)
def supplier_dashboard_view(request):
    """
    Supplier Portal Dashboard - Agricultural Inputs & Vendors.
    Connects certified seed, fertilizer, and equipment vendors to farmer clusters.
    """
    supplier = request.user
    context = {
        "title": "Khet2Kitchen - Supplier Portal",
        "role": "SUPPLIER",
        "user": supplier,
        "active_hubs": MicroHub.objects.filter(is_active=True),
    }

    try:
        return render(request, "core/supplier_dashboard.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({
            "portal": "Supplier / Input Vendor Dashboard",
            "user": supplier.get_full_name() or supplier.identifier,
            "email": supplier.email,
            "status": "Operational",
        })


@role_required(User.Role.ADMIN)
def admin_dashboard_view(request):
    """
    Platform Command Dashboard (K2K Command).
    Displays high-level network health, hub capacity, aggregate volumes, and matching pipeline.
    """
    context = {
        "title": "K2K Command Center",
        "role": "ADMIN",
        "user": request.user,
        "metrics": {
            "total_farmers": User.objects.farmers().count(),
            "total_retailers": User.objects.retailers().count(),
            "total_hubs": MicroHub.objects.count(),
            "active_batches": Batch.objects.count(),
            "pending_demand_orders": DemandOrder.objects.filter(
                status=DemandOrder.Status.PENDING
            ).count(),
        },
    }

    try:
        return render(request, "core/admin_command.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({
            "portal": "K2K Command Dashboard",
            "metrics": context["metrics"],
            "status": "Operational",
        })
