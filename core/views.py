from datetime import timedelta
from decimal import Decimal
import json
import logging
import uuid
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import TemplateDoesNotExist
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from core.otp_services import (
    EmailOTPService,
    FirebaseService,
    normalize_phone_number,
    is_email_identifier,
)

from django.db.models import Q
from django.urls import reverse

from core.decorators import role_required
from core.forms import (
    ConsumerFeedbackForm,
    CropCreateForm,
    CropUpdateForm,
    DemandOrderCreateForm,
    InputSupplyForm,
    UserRegistrationForm,
)
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
        detected_action = gemini_result.get("action")
        action_target = gemini_result.get("action_target") or ""
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
            "action": detected_action,
            "action_target": action_target,
            "language": lang,
        })
        request.session["k2k_voice_chat_history"] = chat_history[-15:]
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
            "action": detected_action,
            "action_target": action_target,
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
# Central Dispatcher & Public Landing Page
# ==============================================================================

def landing_page_view(request):
    """
    Public-facing landing page for Project Khet2Kitchen (K2K).
    Smart Redirect: If the user is authenticated, automatically route them
    to their respective dashboard based on their role (FARMER, RETAILER, SUPPLIER, or Admin).
    If anonymous / unauthenticated, strictly render templates/core/landing.html.
    """
    if request.user.is_authenticated:
        role = getattr(request.user, "role", None)
        if role == User.Role.FARMER:
            return redirect("farmer_dashboard")
        elif role == User.Role.RETAILER:
            return redirect("retailer_dashboard")
        elif role == User.Role.SUPPLIER:
            return redirect("supplier_dashboard")
        elif role == User.Role.CONSUMER:
            return redirect("consumer_dashboard")
        elif role == User.Role.ADMIN or request.user.is_staff:
            return redirect("admin_command_dashboard")
        return redirect(request.user.get_dashboard_url())

    return render(request, "core/landing.html")


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

def _get_farmer_dashboard_context(request, active_nav="dashboard"):
    """
    Shared contextual builder for all Farmer Portal pages in the multi-page architecture.
    Provides unified access to wallet balance, transactions, harvest batches,
    pricing breakdowns, crop schedules, incoming pre-orders, and logistics routes.
    """
    farmer = request.user
    recent_batches = (
        farmer.harvest_batches.select_related("crop", "hub")
        .order_by("-received_at")[:15]
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
    recent_transactions = wallet.transactions.order_by("-timestamp")[:10]

    # Retrieve upcoming AI harvest schedules
    pending_schedules = farmer.harvest_schedules.filter(
        status=HarvestSchedule.Status.PENDING
    ).select_related("crop").order_by("recommended_date")[:10]

    active_hubs = MicroHub.objects.filter(is_active=True)[:6]
    crops = Crop.objects.filter(is_active=True)

    # Pre-orders & Demand Matching
    incoming_orders = DemandOrder.objects.filter(
        status=DemandOrder.Status.PENDING
    ).select_related("crop", "retailer")[:10]

    # Dynamic route calculation for logistics
    first_hub = active_hubs.first()
    try:
        route_plan = mock_dynamic_route(first_hub.id if first_hub else None)
    except Exception as exc:
        logger.warning("Could not compute route plan: %s", exc)
        route_plan = None

    # Dynamic crop list strictly filtered by the authenticated farmer
    my_crops = Crop.objects.filter(farmer=farmer).order_by("-planted_date", "-created_at")

    return {
        "title": "Khet2Kitchen - Kisan Portal",
        "role": "FARMER",
        "user": farmer,
        "farmer": farmer,
        "active_nav": active_nav,
        "wallet": wallet,
        "recent_transactions": recent_transactions,
        "pending_schedules": pending_schedules,
        "batch_breakdowns": batch_breakdowns,
        "active_hubs": active_hubs,
        "crops": crops,
        "incoming_orders": incoming_orders,
        "route_plan": route_plan,
        "my_crops": my_crops,
        "reliability_score": "98.4",
        "financial_summary": {
            "total_gross_value": total_gross_value,
            "total_net_payout": total_net_payout,
            "total_disintermediation_gain": total_disintermediation_gain,
        },
    }


@role_required(User.Role.FARMER)
def farmer_dashboard_view(request):
    """
    1. Farmer's Dashboard & My Crops.
    Features the striking Hero Section, crop summary cards, tabular My Crops data,
    and transparent disintermediation breakdown.
    """
    context = _get_farmer_dashboard_context(request, active_nav="dashboard")
    context["title"] = "Farmer's Dashboard & My Crops - Khet2Kitchen"
    context["crop_create_form"] = CropCreateForm()
    context["crop_update_form"] = CropUpdateForm()
    try:
        return render(request, "core/farmer_dashboard.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({"portal": "Farmer Dashboard", "status": "Operational"})


@role_required(User.Role.FARMER)
def farmer_graded_produce_view(request):
    """
    2. My Graded Produce & AI Scan.
    Integrates optical CV grading dropzone, live laser scanner, AGMARK quality metrics,
    and history of graded batches.
    """
    context = _get_farmer_dashboard_context(request, active_nav="graded_produce")
    context["title"] = "My Graded Produce & Optical AI Scan - Khet2Kitchen"
    try:
        return render(request, "core/farmer_graded_produce.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({"portal": "Graded Produce", "status": "Operational"})


@role_required(User.Role.FARMER)
def farmer_pricing_view(request):
    """
    3. AI Pricing & MSP Floor.
    Displays transparent payout breakdown, guaranteed MSP floor protection,
    and disintermediation comparison vs traditional APMC mandis.
    """
    context = _get_farmer_dashboard_context(request, active_nav="pricing")
    context["title"] = "AI Pricing & Guaranteed MSP Floor - Khet2Kitchen"
    try:
        return render(request, "core/farmer_pricing.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({"portal": "AI Pricing & MSP", "status": "Operational"})


@role_required(User.Role.FARMER)
def farmer_orders_view(request):
    """
    4. Incoming Orders & Allocation.
    Displays urban retailer pre-orders, AI demand matching, and harvest schedules.
    """
    context = _get_farmer_dashboard_context(request, active_nav="orders")
    context["title"] = "Incoming Orders & Demand Allocation - Khet2Kitchen"
    try:
        return render(request, "core/farmer_orders.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({"portal": "Incoming Orders", "status": "Operational"})


@role_required(User.Role.FARMER)
def farmer_wallet_view(request):
    """
    5. Agri-Fintech Payouts & Digital Wallet.
    Displays digital wallet ledger, instant UPI/IMPS withdrawal action, and transaction history.
    """
    context = _get_farmer_dashboard_context(request, active_nav="wallet")
    context["title"] = "Agri-Fintech Payouts & Digital Wallet - Khet2Kitchen"
    try:
        return render(request, "core/farmer_wallet.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({"portal": "Agri-Fintech Wallet", "status": "Operational"})


@role_required(User.Role.FARMER)
def farmer_logistics_view(request):
    """
    6. Dynamic Sweeps & Cold-Chain Fleet.
    Displays dispatch route plan, Reefer EV vehicle metrics, CO2 savings, and micro-hub headroom.
    """
    context = _get_farmer_dashboard_context(request, active_nav="logistics")
    context["title"] = "Dynamic Sweeps & Cold-Chain Fleet - Khet2Kitchen"
    try:
        return render(request, "core/farmer_logistics.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({"portal": "Logistics & Cold-Chain", "status": "Operational"})


@role_required(User.Role.FARMER)
def farmer_weather_view(request):
    """
    7. Weather & Agronomic Risk.
    Integrates real-time Open-Meteo telemetry and Google Gemini agronomic intelligence.
    """
    context = _get_farmer_dashboard_context(request, active_nav="weather")
    context["title"] = "Weather & Agronomic Risk Intelligence - Khet2Kitchen"
    try:
        return render(request, "core/farmer_weather.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({"portal": "Weather & Risk", "status": "Operational"})


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

    # Pre-curated B2B wholesale combos for 1-click bulk procurement
    wholesale_combos = (
        Kit.objects.filter(is_wholesale=True, is_active=True)
        .prefetch_related("items__crop", "hub")
        .order_by("-created_at")[:6]
    )

    context = {
        "title": "Khet2Kitchen - Retailer Procurement",
        "role": "RETAILER",
        "user": retailer,
        "active_nav": "retailer_dashboard",
        "demand_orders": demand_orders,
        "order_form": DemandOrderCreateForm(),
        "market_catalog": market_catalog,
        "ai_recommended_orders": ai_recommended_orders,
        "recent_active_batches": recent_active_batches,
        "wholesale_combos": wholesale_combos,
    }

    try:
        return render(request, "core/retailer_dashboard.html", context)
    except TemplateDoesNotExist:
        return JsonResponse({
            "portal": "Retailer B2B Dashboard",
            "user": retailer.get_full_name() or retailer.identifier,
            "orders_count": demand_orders.count(),
            "ai_recommendations_count": len(ai_recommended_orders),
            "wholesale_combos_count": wholesale_combos.count(),
            "status": "Operational",
        })


@role_required(User.Role.RETAILER)
def retailer_combos_view(request):
    """
    Dedicated Wholesale Curated Combos Store for Retailers, Restaurants, and Kirana Stores.
    Browse curated bulk packs (25kg - 150kg) with tiered wholesale discounts,
    farm origin attribution, and 1-Click B2B procurement.
    """
    retailer = request.user
    category = request.GET.get("category", "").strip().upper()
    search_query = request.GET.get("q", "").strip()

    combos_qs = (
        Kit.objects.filter(is_wholesale=True, is_active=True)
        .prefetch_related("items__crop", "hub")
        .order_by("-created_at")
    )
    if category and category != "ALL":
        combos_qs = combos_qs.filter(category=category)
    if search_query:
        combos_qs = combos_qs.filter(
            Q(name__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(origin_cluster__icontains=search_query)
        )

    my_bulk_orders = (
        retailer.retailer_bulk_orders.select_related("combo", "hub")
        .order_by("-created_at")[:10]
    )

    total_savings_so_far = sum(
        (order.combo.get_savings() * order.quantity for order in my_bulk_orders),
        Decimal("0.00")
    )

    context = {
        "title": "Khet2Kitchen - Curated Wholesale Combos",
        "role": "RETAILER",
        "user": retailer,
        "active_nav": "retailer_combos",
        "combos": combos_qs,
        "selected_category": category or "ALL",
        "search_query": search_query,
        "my_bulk_orders": my_bulk_orders,
        "total_savings_so_far": total_savings_so_far,
        "categories": Kit.Category.choices,
    }
    return render(request, "core/retailer_combos.html", context)


@require_POST
@role_required(User.Role.RETAILER)
def retailer_purchase_combo_view(request, combo_id):
    """
    1-Click Bulk Checkout for Retailers:
    Purchases a curated wholesale combo, generates a RetailerBulkOrder,
    links to DemandOrder, allocates stock, and settles farmer digital wallets.
    """
    retailer = request.user
    combo = get_object_or_404(Kit, id=combo_id, is_wholesale=True, is_active=True)

    try:
        quantity = int(request.POST.get("quantity", 1))
        if quantity < 1:
            quantity = 1
    except (ValueError, TypeError):
        quantity = 1

    delivery_address = request.POST.get("delivery_address", "").strip() or retailer.address or "Retailer Store Dispatch Dock"

    unit_price = combo.get_price_for_quantity(quantity)
    total_price = (unit_price * Decimal(str(quantity))).quantize(Decimal("0.01"))
    pack_weight = combo.get_total_weight_kg()
    total_weight_kg = (pack_weight * Decimal(str(quantity))).quantize(Decimal("0.01"))

    # Link to primary crop or fallback
    primary_item = combo.items.first()
    primary_crop = primary_item.crop if primary_item else Crop.objects.filter(is_active=True).first()

    # Create linked DemandOrder for B2B supply chain visibility
    unit_kg_rate = (total_price / total_weight_kg).quantize(Decimal("0.01")) if total_weight_kg > 0 else Decimal("30.00")
    demand_order = DemandOrder.objects.create(
        retailer=retailer,
        crop=primary_crop,
        channel=DemandOrder.Channel.B2B,
        required_volume_kg=total_weight_kg,
        target_price_per_kg=unit_kg_rate,
        delivery_community_name=combo.origin_cluster or "Institutional Wholesale Client",
        num_households=1,
        required_date=timezone.now().date() + timedelta(days=2),
        status=DemandOrder.Status.ALLOCATED,
        delivery_address=delivery_address,
    )

    # Create RetailerBulkOrder
    bulk_order = RetailerBulkOrder.objects.create(
        retailer=retailer,
        combo=combo,
        quantity=quantity,
        unit_price=unit_price,
        total_price=total_price,
        total_weight_kg=total_weight_kg,
        status=RetailerBulkOrder.Status.ALLOCATED,
        demand_order=demand_order,
        hub=combo.hub,
        payment_status="PAID_INSTANT",
        payment_ref=f"UPI-B2B-{uuid.uuid4().hex[:8].upper()}",
        delivery_address=delivery_address,
    )

    # Settle participating farmer wallets
    for item in combo.items.select_related("crop__farmer"):
        if item.crop and item.crop.farmer:
            farmer = item.crop.farmer
            item_weight_kg = (Decimal(str(item.quantity_grams)) / Decimal("1000.00")) * Decimal(str(quantity))
            farmer_rate = (item.crop.base_price * Decimal("0.80")).quantize(Decimal("0.01"))
            payout_amount = (item_weight_kg * farmer_rate).quantize(Decimal("0.01"))

            if payout_amount > Decimal("0.00"):
                wallet, _ = FarmerWallet.objects.get_or_create(farmer=farmer)
                wallet.credit(
                    amount=payout_amount,
                    description=f"B2B Wholesale Settlement for {quantity}x {combo.name} ({item_weight_kg:.1f}kg {item.crop.name}) - Order {bulk_order.order_id}",
                )

    messages.success(
        request,
        f"Order Placed! Successfully procured {quantity}x '{combo.name}' ({total_weight_kg}kg bulk produce) for ₹{total_price:,.2f}. "
        f"B2B Shipment {bulk_order.order_id} allocated from {combo.hub.name if combo.hub else 'Micro-Hub'}."
    )

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("retailer_combos")


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
    Strictly filters inventory to the authenticated supplier.
    """
    supplier = request.user
    inventory_items = supplier.input_supplies.select_related("hub").order_by("-created_at")
    context = {
        "title": "Khet2Kitchen - Supplier Portal",
        "role": "SUPPLIER",
        "user": supplier,
        "active_nav": "supplier_dashboard",
        "inventory_items": inventory_items,
        "input_form": InputSupplyForm(),
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
        "active_nav": "admin",
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


# ==============================================================================
# Authentication & Onboarding Views
# ==============================================================================

@require_http_methods(["POST"])
def send_otp_view(request):
    """
    POST /auth/send-otp/
    Dispatches a 6-digit OTP for Email or returns formatted instructions for Firebase SMS.
    
    - If identifier contains '@': Generates a 6-digit numeric OTP, stores in cache
      with a 5-minute expiry, and dispatches via Django send_mail.
    - If identifier is a phone number: Returns JSON with normalized E.164 phone
      instructing the frontend to trigger the Firebase client SDK.
    """
    identifier = ""
    if request.content_type == "application/json" and request.body:
        try:
            body_data = json.loads(request.body.decode("utf-8"))
            identifier = (
                body_data.get("identifier")
                or body_data.get("username")
                or body_data.get("email")
                or body_data.get("phone")
                or ""
            )
        except Exception:
            identifier = ""

    if not identifier:
        identifier = (
            request.POST.get("identifier")
            or request.POST.get("username")
            or request.POST.get("email")
            or request.POST.get("phone")
            or ""
        )

    identifier = str(identifier).strip()
    if not identifier:
        return JsonResponse({
            "status": "error",
            "message": "Please enter a valid mobile number or email address."
        }, status=400)

    if is_email_identifier(identifier):
        # Email OTP flow
        success, message, otp_code = EmailOTPService.send_otp(identifier, request=request)
        if success:
            return JsonResponse({
                "status": "success",
                "channel": "email",
                "identifier": identifier.lower(),
                "message": message,
            })
        else:
            return JsonResponse({
                "status": "error",
                "channel": "email",
                "message": message,
            }, status=500)
    else:
        # Phone SMS flow via Firebase client
        normalized_phone = normalize_phone_number(identifier)
        if not normalized_phone or len(normalized_phone) < 10:
            return JsonResponse({
                "status": "error",
                "message": "Please enter a valid 10-digit mobile number."
            }, status=400)

        return JsonResponse({
            "status": "success",
            "channel": "sms",
            "phone": normalized_phone,
            "message": f"Dispatching Firebase SMS OTP to {normalized_phone}...",
        })


def login_view(request):
    """
    Unified Single-View Login for Project Khet2Kitchen (K2K).
    Supports Password, Email OTP, and Firebase SMS OTP seamlessly through the exact same card.
    
    Precedence Order:
    1. Password Check: user = authenticate(request, username=normalized_identifier, password=credential). If valid, login immediately.
    2. Email OTP Check: If password fails and identifier is email, verify against active stored 6-digit Email OTP.
    3. Firebase SMS Token Check: If a Firebase id_token is submitted in POST payload, verify via firebase_admin.auth.verify_id_token(), extract phone, find/provision user, and login.
    """
    if request.user.is_authenticated:
        return redirect(request.user.get_dashboard_url())

    if request.method == "GET":
        return render(request, "core/login.html")

    is_ajax = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or request.content_type == "application/json"
        or request.GET.get("format") == "json"
    )

    identifier = ""
    credential = ""
    firebase_id_token = ""

    if request.content_type == "application/json" and request.body:
        try:
            body_data = json.loads(request.body.decode("utf-8"))
            identifier = body_data.get("username") or body_data.get("identifier") or ""
            credential = body_data.get("password") or body_data.get("otp") or ""
            firebase_id_token = body_data.get("firebase_id_token") or ""
        except Exception:
            pass

    if not identifier:
        identifier = request.POST.get("username") or request.POST.get("identifier") or ""
    if not credential:
        credential = request.POST.get("password") or request.POST.get("otp") or ""
    if not firebase_id_token:
        firebase_id_token = request.POST.get("firebase_id_token") or ""

    identifier = str(identifier).strip()
    credential = str(credential).strip()
    firebase_id_token = str(firebase_id_token).strip()

    if not identifier and not firebase_id_token:
        error_msg = "Please enter your mobile number or email address."
        if is_ajax:
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "core/login.html", {"error": error_msg, "form_errors": True})

    # Determine normalized identifier
    if is_email_identifier(identifier):
        normalized_identifier = identifier.lower()
    else:
        normalized_identifier = normalize_phone_number(identifier)

    # --------------------------------------------------------------------------
    # 1. Password Check (Never invalidated by requesting an OTP)
    # --------------------------------------------------------------------------
    if credential:
        user = authenticate(request, username=normalized_identifier, password=credential)
        if not user and normalized_identifier != identifier:
            user = authenticate(request, username=identifier, password=credential)

        if user and user.is_active:
            login(request, user, backend="core.backends.DualAuthBackend")
            logger.info("User %s successfully logged in via Password", user.identifier)
            if is_ajax:
                return JsonResponse({"status": "success", "redirect_url": user.get_dashboard_url()})
            return redirect(user.get_dashboard_url())

    # --------------------------------------------------------------------------
    # 2. Email OTP Check (If password fails and identifier is an email)
    # --------------------------------------------------------------------------
    if credential and is_email_identifier(identifier):
        is_otp_valid, otp_msg = EmailOTPService.verify_otp(identifier, credential, request=request)
        if is_otp_valid:
            user = User.objects.filter(
                Q(email__iexact=identifier) | Q(identifier__iexact=identifier)
            ).first()

            if user and user.is_active:
                login(request, user, backend="core.backends.DualAuthBackend")
                logger.info("User %s successfully logged in via Email OTP", user.identifier)
                if is_ajax:
                    return JsonResponse({"status": "success", "redirect_url": user.get_dashboard_url()})
                return redirect(user.get_dashboard_url())
            else:
                error_msg = f"Valid OTP, but no active account was found for {identifier}."
                if is_ajax:
                    return JsonResponse({"status": "error", "message": error_msg}, status=400)
                return render(request, "core/login.html", {"error": error_msg, "form_errors": True})

    # --------------------------------------------------------------------------
    # 3. Firebase SMS Token Check (From client Firebase SDK confirmation)
    # --------------------------------------------------------------------------
    if firebase_id_token:
        is_valid_token, token_msg, decoded_token = FirebaseService.verify_id_token(firebase_id_token)
        if is_valid_token:
            token_phone = decoded_token.get("phone_number") or ""
            verified_phone = normalize_phone_number(token_phone) if token_phone else normalized_identifier

            user = User.objects.filter(
                Q(phone_number__iexact=verified_phone) | Q(identifier__iexact=verified_phone)
            ).first()

            if not user and verified_phone:
                # Auto-provision new Farmer profile for verified phone number
                user = User.objects.create_user(
                    identifier=verified_phone,
                    phone_number=verified_phone,
                    role=User.Role.FARMER,
                    first_name="Farmer",
                    is_active=True,
                )
                logger.info("Auto-provisioned new Farmer account for phone: %s", verified_phone)

            if user and user.is_active:
                login(request, user, backend="core.backends.DualAuthBackend")
                logger.info("User %s successfully logged in via Firebase SMS OTP", user.identifier)
                if is_ajax:
                    return JsonResponse({"status": "success", "redirect_url": user.get_dashboard_url()})
                return redirect(user.get_dashboard_url())
            else:
                error_msg = f"Unable to authenticate user for verified phone number {verified_phone}."
                if is_ajax:
                    return JsonResponse({"status": "error", "message": error_msg}, status=400)
                return render(request, "core/login.html", {"error": error_msg, "form_errors": True})
        else:
            error_msg = f"Firebase SMS verification error: {token_msg}"
            if is_ajax:
                return JsonResponse({"status": "error", "message": error_msg}, status=400)
            return render(request, "core/login.html", {"error": error_msg, "form_errors": True})

    # --------------------------------------------------------------------------
    # 4. Authentication Failed
    # --------------------------------------------------------------------------
    error_msg = "Invalid credentials. Please enter a valid password or 6-digit OTP."
    if is_ajax:
        return JsonResponse({"status": "error", "message": error_msg}, status=400)

    return render(request, "core/login.html", {"error": error_msg, "form_errors": True})



def signup_view(request):
    """
    Secure User Registration (Signup) view for Project Khet2Kitchen (K2K).
    Supports Password, Email OTP, and Firebase SMS OTP registration.
    Automatically provisions wallet, mirrors credentials, and routes dynamically.
    """
    if request.user.is_authenticated:
        return redirect(request.user.get_dashboard_url())

    if request.method == "POST":
        firebase_id_token = request.POST.get("firebase_id_token", "").strip()
        raw_identifier = request.POST.get("identifier", "").strip()
        raw_password = request.POST.get("password", "").strip()

        # ----------------------------------------------------------------------
        # 1. Firebase SMS OTP Verification
        # ----------------------------------------------------------------------
        if firebase_id_token:
            is_valid_token, token_msg, decoded_token = FirebaseService.verify_id_token(firebase_id_token)
            if is_valid_token:
                token_phone = decoded_token.get("phone_number") or ""
                verified_phone = normalize_phone_number(token_phone) if token_phone else normalize_phone_number(raw_identifier)

                # If user already exists with this phone number, log them in directly
                existing_user = User.objects.filter(
                    Q(phone_number__iexact=verified_phone) | Q(identifier__iexact=verified_phone)
                ).first()
                if existing_user and existing_user.is_active:
                    login(request, existing_user, backend="core.backends.DualAuthBackend")
                    messages.info(
                        request,
                        f"Welcome back, {existing_user.first_name or existing_user.identifier}! You already have an account.",
                    )
                    return redirect(existing_user.get_dashboard_url())

                # New user registration with verified phone
                post_data = request.POST.copy()
                post_data["identifier"] = verified_phone
                form = UserRegistrationForm(post_data)
                if form.is_valid():
                    user = form.save()
                    login(request, user, backend="core.backends.DualAuthBackend")
                    messages.success(
                        request,
                        f"Welcome to Khet2Kitchen, {user.first_name or user.identifier}! Mobile number verified via SMS.",
                    )
                    return redirect(user.get_dashboard_url())
                return render(request, "core/signup.html", {"form": form})

        # ----------------------------------------------------------------------
        # 2. Email OTP Verification (if 6-digit code entered for email)
        # ----------------------------------------------------------------------
        if is_email_identifier(raw_identifier) and len(raw_password) == 6 and raw_password.isdigit():
            is_otp_valid, otp_msg = EmailOTPService.verify_otp(raw_identifier, raw_password, request=request)
            if is_otp_valid:
                existing_user = User.objects.filter(
                    Q(email__iexact=raw_identifier) | Q(identifier__iexact=raw_identifier)
                ).first()
                if existing_user and existing_user.is_active:
                    login(request, existing_user, backend="core.backends.DualAuthBackend")
                    messages.info(
                        request,
                        f"Welcome back, {existing_user.first_name or existing_user.identifier}! You already have an account.",
                    )
                    return redirect(existing_user.get_dashboard_url())

                form = UserRegistrationForm(request.POST)
                if form.is_valid():
                    user = form.save()
                    login(request, user, backend="core.backends.DualAuthBackend")
                    messages.success(
                        request,
                        f"Welcome to Khet2Kitchen, {user.first_name or user.identifier}! Email verified successfully.",
                    )
                    return redirect(user.get_dashboard_url())
                return render(request, "core/signup.html", {"form": form})

        # ----------------------------------------------------------------------
        # 3. Standard Password Registration
        # ----------------------------------------------------------------------
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend="core.backends.DualAuthBackend")
            messages.success(
                request,
                f"Welcome to Khet2Kitchen, {user.first_name or user.identifier}! Your account has been provisioned.",
            )
            return redirect(user.get_dashboard_url())
    else:
        form = UserRegistrationForm()

    return render(request, "core/signup.html", {"form": form})


# ==============================================================================
# Dynamic Farmer Actions (Add, Edit, Inspect)
# ==============================================================================

@role_required(User.Role.FARMER)
def add_crop_view(request):
    """
    Allows a farmer to dynamically register a new crop / planting.
    Strictly isolated: crop is associated directly with request.user.
    """
    if request.method == "POST":
        form = CropCreateForm(request.POST)
        if form.is_valid():
            crop = form.save(commit=False)
            crop.farmer = request.user
            crop.save()
            messages.success(request, f"Successfully added crop: {crop.name} ({crop.expected_yield_kg} kg)!")
        else:
            messages.error(request, "Failed to add crop. Please check the values entered.")
    return redirect("farmer_dashboard")


@role_required(User.Role.FARMER)
def edit_crop_view(request, crop_id):
    """
    Allows a farmer to edit expected yield, harvest date, and status of their crop.
    Enforces strict ownership check (farmer=request.user).
    """
    crop = get_object_or_404(Crop, id=crop_id, farmer=request.user)

    if request.method == "POST":
        form = CropUpdateForm(request.POST, instance=crop)
        if form.is_valid():
            form.save()
            messages.success(request, f"Updated crop details for {crop.name} successfully.")
            return redirect("farmer_dashboard")
        else:
            messages.error(request, "Failed to update crop. Please check the values entered.")
    else:
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
            return JsonResponse({
                "success": True,
                "id": crop.id,
                "name": crop.name,
                "expected_yield_kg": str(crop.expected_yield_kg),
                "harvest_date": str(crop.harvest_date or ""),
                "status": crop.status,
            })
        form = CropUpdateForm(instance=crop)

    return render(request, "core/crop_edit.html", {"form": form, "crop": crop, "title": f"Edit {crop.name}"})


@role_required(User.Role.FARMER)
def crop_inspect_view(request, crop_id):
    """
    Opens Batch Details / Provenance inspection for a specific crop.
    Enforces strict ownership check (farmer=request.user).
    """
    crop = get_object_or_404(Crop, id=crop_id, farmer=request.user)
    batch = crop.batches.filter(farmer=request.user).order_by("-received_at").first()

    timeline = [
        {
            "step": 1,
            "title": "Seed Certification & Planting",
            "date": crop.planted_date.strftime("%d %b %Y") if crop.planted_date else "Recorded",
            "status": "Completed",
            "badge": "Certified Provenance",
            "desc": f"Planted {crop.name} with verified germination certification.",
        },
        {
            "step": 2,
            "title": "Agronomic Soil & Satellite Health",
            "date": "Active Monitoring",
            "status": "Active" if crop.status in ("Growing", "Planting") else "Completed",
            "badge": "Optimal NDVI",
            "desc": "Real-time satellite vegetative index and root-zone moisture within target threshold.",
        },
        {
            "step": 3,
            "title": "Harvest Window & Yield Forecast",
            "date": crop.harvest_date.strftime("%d %b %Y") if crop.harvest_date else "Optimal Window",
            "status": "Completed" if crop.status in ("Harvested", "At Hub (Graded)") else "Targeted",
            "badge": f"{crop.expected_yield_kg or 'Standard'} kg Targeted",
            "desc": f"Expected harvest payload under guaranteed MSP floor protection.",
        },
        {
            "step": 4,
            "title": "Micro-Hub Intake & AI Quality Scan",
            "date": batch.received_at.strftime("%d %b %Y %H:%M") if batch else "Pending Drop-off",
            "status": "Completed" if batch else "Pending",
            "badge": f"Grade {batch.ai_grade} ({batch.ai_confidence_score}%)" if batch else "Awaiting Drop",
            "desc": f"Batch ID: {batch.batch_id}" if batch else "Batch barcode generated for drop-off at nearest Micro-Hub.",
        },
        {
            "step": 5,
            "title": "Cold-Chain Dispatch & Escrow Settlement",
            "date": "Same-Day Direct",
            "status": "Completed" if batch and batch.status in (Batch.Status.DELIVERED, Batch.Status.ALLOCATED) else "Scheduled",
            "badge": "Instant IMPS",
            "desc": "Direct B2B urban retailer fulfillment with zero APMC commission.",
        },
    ]

    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
        return JsonResponse({
            "success": True,
            "crop": {
                "id": crop.id,
                "name": crop.name,
                "code": crop.code,
                "planted_date": str(crop.planted_date or ""),
                "harvest_date": str(crop.harvest_date or ""),
                "expected_yield_kg": str(crop.expected_yield_kg),
                "status": crop.status,
                "batch_id": batch.batch_id if batch else None,
                "ai_grade": batch.ai_grade if batch else None,
            },
            "timeline": timeline,
        })

    return render(request, "core/crop_inspect.html", {
        "crop": crop,
        "batch": batch,
        "timeline": timeline,
        "title": f"Crop Details - {crop.name}",
    })


# ==============================================================================
# Dynamic Retailer Actions
# ==============================================================================

@require_POST
@role_required(User.Role.RETAILER)
def add_demand_order_view(request):
    """
    Allows a retailer to dynamically post a new demand pre-order.
    Strictly isolated: demand order is tied directly to request.user.
    """
    form = DemandOrderCreateForm(request.POST)
    if form.is_valid():
        order = form.save(commit=False)
        order.retailer = request.user
        order.save()
        messages.success(
            request,
            f"Demand Order {order.order_id} ({order.required_volume_kg}kg {order.crop.name}) posted successfully!"
        )
    else:
        messages.error(request, "Could not post demand order. Please check the inputs.")
    return redirect("retailer_dashboard")


# ==============================================================================
# Dynamic Supplier Actions
# ==============================================================================

@require_POST
@role_required(User.Role.SUPPLIER)
def add_input_supply_view(request):
    """
    Allows a supplier to add an agri-input product to inventory.
    Strictly isolated: input is tied to request.user.
    """
    form = InputSupplyForm(request.POST)
    if form.is_valid():
        supply = form.save(commit=False)
        supply.supplier = request.user
        supply.save()
        messages.success(
            request,
            f"Successfully added {supply.name} ({supply.quantity} {supply.unit}) to your inventory!"
        )
    else:
        messages.error(request, "Failed to add input supply item. Please check the form fields.")
    return redirect("supplier_dashboard")


@require_POST
@role_required(User.Role.SUPPLIER)
def update_input_supply_view(request, supply_id):
    """
    Allows a supplier to update inventory quantities or status.
    Enforces strict ownership check (supplier=request.user).
    """
    supply = get_object_or_404(InputSupply, id=supply_id, supplier=request.user)
    quantity = request.POST.get("quantity")
    price_per_unit = request.POST.get("price_per_unit")
    status = request.POST.get("status")

    try:
        if quantity is not None and str(quantity).strip():
            supply.quantity = Decimal(str(quantity))
        if price_per_unit is not None and str(price_per_unit).strip():
            supply.price_per_unit = Decimal(str(price_per_unit))
        if status in dict(InputSupply.Status.choices):
            supply.status = status
        supply.save()
        messages.success(request, f"Updated stock for {supply.name} ({supply.quantity} {supply.unit}).")
    except Exception as exc:
        logger.error("Error updating input supply %s: %s", supply_id, exc)
        messages.error(request, f"Error updating inventory: {exc}")

    return redirect("supplier_dashboard")


# ==============================================================================
# Direct-to-Consumer (D2C) Marketplace & AI Recipe Combos
# ==============================================================================

def consumer_shop_view(request):
    """
    Public-facing D2C farm store displaying direct farmer produce,
    pre-packaged vegetable kits, and the AI Recipe Combo builder.
    """
    category = request.GET.get("category", "all").strip().lower()
    search_query = request.GET.get("q", "").strip()

    # Query Active Pre-packaged Kits
    kits_qs = Kit.objects.filter(is_active=True).prefetch_related("items__crop")
    if search_query:
        kits_qs = kits_qs.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(code__icontains=search_query)
        )

    # Query Active Direct Farm Produce / Loose Groceries
    crops_qs = Crop.objects.filter(is_active=True).select_related("farmer").order_by("-code", "name")
    if search_query:
        crops_qs = crops_qs.filter(
            Q(name__icontains=search_query) |
            Q(category__icontains=search_query) |
            Q(code__icontains=search_query)
        )

    # Query Recent/Popular Recipe Combos
    combos_qs = RecipeCombo.objects.all().order_by("-created_at")[:6]
    if search_query:
        combos_qs = combos_qs.filter(dish_name__icontains=search_query)

    # Preset quick-selection dishes for the AI combo generator
    preset_dishes = [
        {"name": "Sambar", "icon": "🍲", "tag": "South Indian Classic"},
        {"name": "Biryani", "icon": "🍛", "tag": "Fragrant Dum Style"},
        {"name": "Palak Paneer", "icon": "🥬", "tag": "Iron-Rich Greens"},
        {"name": "Pav Bhaji", "icon": "🥔", "tag": "Mumbai Street Special"},
        {"name": "Dal Tadka", "icon": "🥣", "tag": "Dhaba Style Protein"},
        {"name": "Detox Salad", "icon": "🥗", "tag": "Farm-Fresh Raw"},
    ]

    context = {
        "kits": kits_qs,
        "crops": crops_qs,
        "loose_produce": crops_qs,
        "recent_combos": combos_qs,
        "preset_dishes": preset_dishes,
        "active_category": category,
        "search_query": search_query,
        "title": "K2K Direct Farm Store • 100% Traceable Direct to Consumer",
    }
    return render(request, "core/consumer_shop.html", context)



def ai_combo_builder_view(request):
    """
    AI Dish-to-Combo Engine view: Accepts dish name and serving count,
    calculates required crop grammage, maps to active catalog produce,
    applies a 15% bundle discount, and returns dynamic pricing with transparent farmer payouts.
    Supports both JSON API (for modal/AJAX) and standalone HTML view.
    """
    is_json = (
        request.headers.get("x-requested-with") == "XMLHttpRequest" or
        request.GET.get("format") == "json" or
        request.content_type == "application/json" or
        request.method == "POST"
    )

    dish_name = "Sambar"
    servings = 4

    if request.method == "POST":
        try:
            if request.content_type == "application/json" and request.body:
                body_data = json.loads(request.body.decode("utf-8"))
                dish_name = body_data.get("dish_name") or body_data.get("dish") or dish_name
                servings = body_data.get("servings") or servings
            else:
                dish_name = request.POST.get("dish_name") or request.POST.get("dish") or dish_name
                servings = request.POST.get("servings") or servings
        except Exception as exc:
            logger.warning("Error parsing POST in ai_combo_builder_view: %s", exc)
    else:
        dish_name = request.GET.get("dish_name") or request.GET.get("dish") or dish_name
        servings = request.GET.get("servings") or servings

    try:
        servings = int(servings)
    except (ValueError, TypeError):
        servings = 4

    combo_data = generate_recipe_combo(dish_name=dish_name, servings=servings, persist=True)

    if is_json:
        return JsonResponse({"status": "success", "combo": combo_data})

    # Standalone HTML detail view
    context = {
        "combo": combo_data,
        "dish_name": dish_name,
        "servings": servings,
        "title": f"AI Recipe Combo: {combo_data.get('dish_name')} - K2K Direct",
    }
    return render(request, "core/consumer_combo_detail.html", context)


@require_POST
def consumer_checkout_view(request):
    """
    Direct D2C 1-Click Checkout:
    Places a ConsumerOrder for Produce, Kits, or Recipe Combos,
    and automatically executes instantaneous direct digital wallet credits
    to the respective farmer(s) in FarmerWallet with an immutable audit entry.
    """
    item_type = request.POST.get("item_type", "PRODUCE").strip().upper()
    item_id = request.POST.get("item_id", "").strip()
    quantity_raw = request.POST.get("quantity") or request.POST.get("quantity_kg") or "1"
    try:
        quantity = Decimal(str(quantity_raw))
        if quantity <= Decimal("0.00"):
            quantity = Decimal("1.00")
    except Exception:
        quantity = Decimal("1.00")

    demo_farmer = User.objects.filter(role=User.Role.FARMER).first()

    order_user = request.user if request.user.is_authenticated else None

    req_name = request.POST.get("customer_name", "").strip()
    req_phone = request.POST.get("customer_phone", "").strip()
    req_email = request.POST.get("customer_email", "").strip()
    req_address = request.POST.get("delivery_address", "").strip()
    req_pincode = request.POST.get("pincode", "").strip()

    if order_user:
        customer_name = req_name or order_user.get_full_name() or order_user.identifier
        customer_phone = req_phone or order_user.phone_number or "+91 98765 43210"
        customer_email = req_email or order_user.email or ""
        delivery_address = req_address or order_user.address or "Doorstep Delivery, Urban Kitchen Cluster"
        pincode = req_pincode or order_user.pincode or "500033"
    else:
        customer_name = req_name or "Verified Urban Consumer"
        customer_phone = req_phone or "+91 98765 43210"
        customer_email = req_email
        delivery_address = req_address or "Doorstep Delivery, Urban Kitchen Cluster"
        pincode = req_pincode or "500033"

    order = ConsumerOrder(
        user=order_user,
        customer_name=customer_name or "Valued Consumer",
        customer_phone=customer_phone,
        customer_email=customer_email,
        delivery_address=delivery_address or "Standard Express Dispatch",
        pincode=pincode,
        status=ConsumerOrder.Status.PAID_SETTLED,
        payment_method="UPI_INSTANT",
    )

    total_settled_to_farmers = Decimal("0.00")

    if item_type == "KIT":
        kit = get_object_or_404(Kit, id=item_id)
        qty_int = int(quantity)
        bundle_price = kit.calculate_bundle_price()
        orig_price = kit.calculate_original_price() * Decimal(str(qty_int))
        subtotal = (bundle_price * Decimal(str(qty_int))).quantize(Decimal("0.01"))
        discount = (orig_price - subtotal).quantize(Decimal("0.01"))

        order.total_amount = orig_price
        order.discount_amount = discount
        order.final_paid_amount = subtotal
        order.save()

        # Determine primary farmer from kit items or fallback
        first_item = kit.items.select_related("crop__farmer").first()
        primary_farmer = (first_item.crop.farmer if first_item and first_item.crop else None) or demo_farmer

        kit_farmer_payout = (subtotal * Decimal("0.90")).quantize(Decimal("0.01"))

        ConsumerOrderItem.objects.create(
            order=order,
            item_type=ConsumerOrderItem.ItemType.KIT,
            kit=kit,
            farmer=primary_farmer,
            item_name=kit.name,
            quantity=Decimal(str(qty_int)),
            unit="kit",
            unit_price=bundle_price,
            subtotal=subtotal,
            farmer_payout=kit_farmer_payout,
            is_settled_to_wallet=True,
        )

        # Credit farmers directly for each component item in kit
        kit_items = list(kit.items.select_related("crop__farmer"))
        if kit_items:
            for k_item in kit_items:
                crop_farmer = k_item.crop.farmer or primary_farmer
                if crop_farmer:
                    wallet, _ = FarmerWallet.objects.get_or_create(farmer=crop_farmer)
                    item_kg = Decimal(str(k_item.quantity_grams)) / Decimal("1000.00")
                    item_val = item_kg * k_item.crop.base_price * Decimal(str(qty_int))
                    payout_share = (item_val * (Decimal("100.00") - kit.discount_percentage) / Decimal("100.00") * Decimal("0.90")).quantize(Decimal("0.01"))
                    if payout_share > Decimal("0.00"):
                        wallet.credit(payout_share, f"D2C Kit Sale: {kit.name} ({k_item.crop.name}) - Order {order.order_id}")
                        total_settled_to_farmers += payout_share
        elif primary_farmer:
            wallet, _ = FarmerWallet.objects.get_or_create(farmer=primary_farmer)
            wallet.credit(kit_farmer_payout, f"D2C Kit Sale: {kit.name} - Order {order.order_id}")
            total_settled_to_farmers += kit_farmer_payout

    elif item_type == "COMBO":
        combo = RecipeCombo.objects.filter(Q(id=item_id) if item_id.isdigit() else Q(combo_id=item_id)).first()
        if not combo:
            # Generate on the fly
            dish = request.POST.get("dish_name") or "Sambar"
            servings_cnt = int(request.POST.get("servings") or 4)
            c_data = generate_recipe_combo(dish, servings_cnt, persist=True)
            combo = RecipeCombo.objects.get(id=c_data["combo_db_id"])

        subtotal = combo.combo_price
        orig_price = combo.original_price
        discount = (orig_price - subtotal).quantize(Decimal("0.01"))

        order.total_amount = orig_price
        order.discount_amount = discount
        order.final_paid_amount = subtotal
        order.save()

        total_combo_payout = (subtotal * Decimal("0.90")).quantize(Decimal("0.01"))

        ConsumerOrderItem.objects.create(
            order=order,
            item_type=ConsumerOrderItem.ItemType.COMBO,
            recipe_combo=combo,
            farmer=demo_farmer,
            item_name=f"{combo.dish_name} Combo ({combo.servings} Servings)",
            quantity=Decimal("1.00"),
            unit="combo",
            unit_price=combo.combo_price,
            subtotal=subtotal,
            farmer_payout=total_combo_payout,
            is_settled_to_wallet=True,
        )

        # Distribute direct payouts to each farmer linked in the combo ingredients
        credited_in_combo = Decimal("0.00")
        for ing in combo.items_breakdown:
            f_id = ing.get("farmer_id")
            farmer_obj = User.objects.filter(id=f_id).first() if f_id else demo_farmer
            if farmer_obj:
                wallet, _ = FarmerWallet.objects.get_or_create(farmer=farmer_obj)
                ing_price = Decimal(str(ing.get("standalone_price", "0.00")))
                payout_share = (ing_price * Decimal("0.85") * Decimal("0.90")).quantize(Decimal("0.01"))
                if payout_share > Decimal("0.00"):
                    wallet.credit(
                        payout_share,
                        f"D2C AI Combo: {ing.get('crop_name')} in {combo.dish_name} - Order {order.order_id}"
                    )
                    credited_in_combo += payout_share
                    total_settled_to_farmers += payout_share

        if credited_in_combo == Decimal("0.00") and demo_farmer:
            wallet, _ = FarmerWallet.objects.get_or_create(farmer=demo_farmer)
            wallet.credit(total_combo_payout, f"D2C AI Combo: {combo.dish_name} - Order {order.order_id}")
            total_settled_to_farmers += total_combo_payout

    else:
        # Direct Farm Produce
        crop = get_object_or_404(Crop, id=item_id)
        subtotal = (quantity * crop.base_price).quantize(Decimal("0.01"))
        order.total_amount = subtotal
        order.discount_amount = Decimal("0.00")
        order.final_paid_amount = subtotal
        order.save()

        farmer = crop.farmer or demo_farmer
        farmer_payout = (subtotal * Decimal("0.92")).quantize(Decimal("0.01"))

        ConsumerOrderItem.objects.create(
            order=order,
            item_type=ConsumerOrderItem.ItemType.PRODUCE,
            crop=crop,
            farmer=farmer,
            item_name=f"Farm Fresh {crop.name}",
            quantity=quantity,
            unit="kg",
            unit_price=crop.base_price,
            subtotal=subtotal,
            farmer_payout=farmer_payout,
            is_settled_to_wallet=True,
        )

        if farmer:
            wallet, _ = FarmerWallet.objects.get_or_create(farmer=farmer)
            wallet.credit(farmer_payout, f"D2C Direct Produce Sale: {quantity}kg {crop.name} - Order {order.order_id}")
            total_settled_to_farmers += farmer_payout

    messages.success(
        request,
        f"Order {order.order_id} confirmed! ₹{total_settled_to_farmers} was credited directly into farmer digital wallets."
    )

    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
        return JsonResponse({
            "status": "success",
            "order_id": order.order_id,
            "redirect_url": reverse("consumer_order_success", args=[order.order_id]),
            "settled_amount": float(total_settled_to_farmers),
        })

    return redirect("consumer_order_success", order_id=order.order_id)


def consumer_order_success_view(request, order_id):
    """
    Renders receipt of consumer purchase with radical supply chain transparency,
    displaying itemized farmer payouts credited directly to farmer wallets.
    """
    order = get_object_or_404(ConsumerOrder, order_id=order_id)
    items = order.items.select_related("crop", "kit", "recipe_combo", "farmer").all()
    total_farmer_payout = sum((item.farmer_payout for item in items), Decimal("0.00"))

    context = {
        "order": order,
        "items": items,
        "total_farmer_payout": total_farmer_payout,
        "title": f"Order {order.order_id} Confirmed • K2K Farm Direct",
    }
    return render(request, "core/consumer_order_success.html", context)


@login_required
def consumer_dashboard_view(request):
    """
    Consumer Portal Dashboard.
    Provides active consumers with complete visibility into their account, active and delivered orders,
    live fulfillment timeline, radical transparent farmer payouts, total savings,
    and direct farmer feedback / review submissions.
    """
    # Query orders belonging directly to user, or matching user's phone / email
    filters = Q(user=request.user)
    if request.user.phone_number:
        filters |= Q(customer_phone=request.user.phone_number)
    if request.user.email:
        filters |= Q(customer_email=request.user.email)

    orders = (
        ConsumerOrder.objects.filter(filters)
        .distinct()
        .prefetch_related(
            "items__crop",
            "items__kit",
            "items__recipe_combo",
            "items__farmer",
            "feedbacks",
        )
        .order_by("-created_at")
    )

    # Automatically associate any unlinked past orders matching phone or email to this active user
    for o in orders:
        if not o.user:
            o.user = request.user
            o.save(update_fields=["user"])

    total_orders = orders.count()
    total_spent = sum((o.final_paid_amount for o in orders), Decimal("0.00"))
    total_discount_saved = sum((o.discount_amount for o in orders), Decimal("0.00"))

    total_farmer_payout = Decimal("0.00")
    total_items_count = 0
    for o in orders:
        for it in o.items.all():
            total_farmer_payout += it.farmer_payout
            total_items_count += 1

    # Feedbacks submitted by this consumer
    feedbacks = (
        ConsumerFeedback.objects.filter(consumer=request.user)
        .select_related("order")
        .order_by("-created_at")
    )

    feedback_form = ConsumerFeedbackForm()

    context = {
        "title": "Consumer Portal & Orders • Khet2Kitchen",
        "orders": orders,
        "total_orders": total_orders,
        "total_spent": total_spent,
        "total_discount_saved": total_discount_saved,
        "total_farmer_payout": total_farmer_payout,
        "total_items_count": total_items_count,
        "feedbacks": feedbacks,
        "feedback_form": feedback_form,
    }
    return render(request, "core/consumer_dashboard.html", context)


@login_required
@require_POST
def consumer_add_feedback_view(request, order_id):
    """
    Handles consumer feedback submission for a specific ConsumerOrder.
    Saves overall rating, freshness rating, delivery speed, and direct farmer notes.
    """
    order = get_object_or_404(ConsumerOrder, order_id=order_id)

    # Verify authorization
    is_owner = (
        (order.user == request.user)
        or (request.user.phone_number and order.customer_phone == request.user.phone_number)
        or (request.user.email and order.customer_email == request.user.email)
        or request.user.is_staff
    )

    if not is_owner:
        messages.error(request, "You do not have permission to review this order.")
        return redirect("consumer_dashboard")

    # Link user if not already linked
    if not order.user:
        order.user = request.user
        order.save(update_fields=["user"])

    existing_feedback = getattr(order, "feedback", None)
    form = ConsumerFeedbackForm(request.POST, instance=existing_feedback)
    if form.is_valid():
        feedback = form.save(commit=False)
        feedback.order = order
        feedback.consumer = request.user
        feedback.save()
        messages.success(
            request,
            f"Thank you! Your review and note to the farmers for Order #{order.order_id} have been shared directly."
        )
    else:
        messages.error(request, "Unable to save your feedback. Please check the ratings and try again.")

    next_url = request.POST.get("next") or reverse("consumer_dashboard")
    return redirect(next_url)



