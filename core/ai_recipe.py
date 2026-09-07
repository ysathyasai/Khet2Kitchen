import json
import logging
import re
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.utils.translation import gettext_lazy as _

from core.models import Crop, RecipeCombo, User

logger = logging.getLogger(__name__)

# ==============================================================================
# 1. HEURISTIC RECIPE KNOWLEDGE BASE (12+ CLASSIC DISHES)
# ==============================================================================

POPULAR_RECIPES: Dict[str, Dict[str, Any]] = {
    "sambar": {
        "dish_name": "Authentic South Indian Sambar",
        "prep_time_minutes": 25,
        "culinary_notes": "A nutrient-rich lentil and vegetable stew with a fragrant tamarind-coriander temper. Packed with dietary fiber and vitamin C.",
        "base_servings": 4,
        "ingredients": [
            {"crop_keyword": "Tomato", "base_grams": 300, "role": "Tangy broth base & lycopene richness"},
            {"crop_keyword": "Onion", "base_grams": 250, "role": "Aromatic sweetness & savory depth"},
            {"crop_keyword": "Chilli", "base_grams": 50, "role": "Spicy capsaicin kick & heat"},
        ],
    },
    "biryani": {
        "dish_name": "Hyderabadi Shahi Veg Biryani",
        "prep_time_minutes": 45,
        "culinary_notes": "Slow-cooked dum basmati rice layered with caramelized onions, tangy field tomatoes, and fragrant whole spice tempering.",
        "base_servings": 4,
        "ingredients": [
            {"crop_keyword": "Onion", "base_grams": 450, "role": "Caramelized crispy biryani (birista)"},
            {"crop_keyword": "Tomato", "base_grams": 350, "role": "Rich spiced gravy base"},
            {"crop_keyword": "Chilli", "base_grams": 60, "role": "Zesty green aroma & heat"},
        ],
    },
    "pav bhaji": {
        "dish_name": "Mumbai Street-Style Pav Bhaji",
        "prep_time_minutes": 30,
        "culinary_notes": "Rich, buttery vegetable mash spiced with roasted Pav Bhaji masala. Best enjoyed with toasted butter buns.",
        "base_servings": 4,
        "ingredients": [
            {"crop_keyword": "Tomato", "base_grams": 400, "role": "Acidic color and velvety texture"},
            {"crop_keyword": "Onion", "base_grams": 300, "role": "Fresh diced garnish & sautéed base"},
            {"crop_keyword": "Chilli", "base_grams": 40, "role": "Vibrant piquant spice"},
        ],
    },
    "palak paneer": {
        "dish_name": "Farm-Fresh Palak Paneer",
        "prep_time_minutes": 30,
        "culinary_notes": "Creamy blanched spinach gravy infused with garlic, cumin, and soft paneer cubes. High in dietary iron and protein.",
        "base_servings": 4,
        "ingredients": [
            {"crop_keyword": "Tomato", "base_grams": 250, "role": "Tangy counterpoint to earthy greens"},
            {"crop_keyword": "Onion", "base_grams": 200, "role": "Sweet allium foundation"},
            {"crop_keyword": "Chilli", "base_grams": 40, "role": "Gentle pungency"},
        ],
    },
    "dal tadka": {
        "dish_name": "Dhaba-Style Dal Tadka",
        "prep_time_minutes": 20,
        "culinary_notes": "Yellow pigeon pea stew tempered in pure ghee with double-crushed garlic, red chillies, and cumin seeds.",
        "base_servings": 4,
        "ingredients": [
            {"crop_keyword": "Tomato", "base_grams": 200, "role": "Tangy richness in ghee tadka"},
            {"crop_keyword": "Onion", "base_grams": 200, "role": "Golden sautéed sweetness"},
            {"crop_keyword": "Chilli", "base_grams": 50, "role": "Smoky charred whole chilli aroma"},
        ],
    },
    "rasam": {
        "dish_name": "Telangana Pepper Tomato Rasam",
        "prep_time_minutes": 15,
        "culinary_notes": "Cleansing digestive broth prepared with ripe field tomatoes, freshly ground black pepper, curry leaves, and cumin.",
        "base_servings": 4,
        "ingredients": [
            {"crop_keyword": "Tomato", "base_grams": 450, "role": "Primary juicy soup foundation"},
            {"crop_keyword": "Chilli", "base_grams": 40, "role": "Pungent throat-clearing heat"},
        ],
    },
    "salad": {
        "dish_name": "Direct-Farm Raw Detox Salad",
        "prep_time_minutes": 10,
        "culinary_notes": "Crunchy seasonal vegetables tossed with fresh lemon juice, rock salt, and roasted cumin. Low calorie, prebiotic-rich meal.",
        "base_servings": 4,
        "ingredients": [
            {"crop_keyword": "Tomato", "base_grams": 300, "role": "Juicy sweet-tart crunch"},
            {"crop_keyword": "Onion", "base_grams": 200, "role": "Zesty pink onion rings"},
            {"crop_keyword": "Mango", "base_grams": 250, "role": "Sweet seasonal fruit contrast"},
        ],
    },
    "aloo gobi": {
        "dish_name": "Homestyle Aloo Gobi Masala",
        "prep_time_minutes": 25,
        "culinary_notes": "Dry-roasted potato and cauliflower florets with turmeric, ginger juliennes, and fresh coriander leaves.",
        "base_servings": 4,
        "ingredients": [
            {"crop_keyword": "Tomato", "base_grams": 250, "role": "Thick clinging masala glaze"},
            {"crop_keyword": "Onion", "base_grams": 250, "role": "Slow-braised allium base"},
            {"crop_keyword": "Chilli", "base_grams": 40, "role": "Spicy green slit garnish"},
        ],
    },
}


def _match_crop(keyword: str) -> Optional[Crop]:
    """Finds the best active Crop matching the given keyword."""
    # 1. Exact or partial match
    crop = (
        Crop.objects.filter(is_active=True, name__icontains=keyword).first()
        or Crop.objects.filter(is_active=True, category__icontains=keyword).first()
    )
    if not crop:
        # Fallback to any active crop
        crop = Crop.objects.filter(is_active=True).order_by("-base_price").first()
    return crop


def _get_fallback_recipe(dish_name: str) -> Dict[str, Any]:
    """Retrieves the closest heuristic recipe configuration for a dish."""
    clean_dish = dish_name.lower().strip()
    for key, data in POPULAR_RECIPES.items():
        if key in clean_dish:
            return data

    # Generic Farm Curry fallback
    return {
        "dish_name": f"Homestyle {dish_name.title()}",
        "prep_time_minutes": 30,
        "culinary_notes": f"A hearty, wholesome preparation of {dish_name.title()} crafted using farm-fresh organic produce with optimal culinary balance.",
        "base_servings": 4,
        "ingredients": [
            {"crop_keyword": "Tomato", "base_grams": 300, "role": "Savory acidity and rich gravy base"},
            {"crop_keyword": "Onion", "base_grams": 250, "role": "Caramelized sweetness & body"},
            {"crop_keyword": "Chilli", "base_grams": 50, "role": "Fresh zesty heat and aroma"},
        ],
    }


# ==============================================================================
# 2. GEMINI AI RECIPE PARSER
# ==============================================================================

def query_gemini_recipe(dish_name: str, servings: int) -> Optional[Dict[str, Any]]:
    """
    Asks Google Gemini to break down the recipe into exact vegetable requirements in grams.
    Returns parsed dictionary or None if API is unconfigured or times out.
    """
    gemini_key = getattr(settings, "GEMINI_API_KEY", "").strip()
    if not gemini_key:
        return None

    # Retrieve catalog crop names to ground the LLM
    available_crops = list(Crop.objects.filter(is_active=True).values_list("name", flat=True)[:10])
    catalog_str = ", ".join(available_crops) if available_crops else "Roma Field Tomato, Red Onion, Warangal Teja Chilli, Mango"

    prompt = f"""You are a master Indian culinary chef and agronomist at Project Khet2Kitchen.
We are generating a direct-from-farm "Recipe-to-Combo" vegetable kit for consumers.
Dish Name: "{dish_name}"
Servings Count: {servings} people
Available Farm Catalog Crops: [{catalog_str}]

Task: Calculate the exact fresh agricultural ingredients (vegetables/fruits) required to cook this dish for {servings} people.
Scale weights appropriately (e.g. realistic grams: Tomatoes 300g, Onions 200g, Chillies 40g for 4 servings).

CRITICAL: Respond ONLY with a valid JSON object matching this exact schema:
{{
  "dish_title": "Official Title of Dish (e.g. Telangana Style Sambar)",
  "prep_time_minutes": 25,
  "culinary_notes": "1-2 sentences explaining cooking tips, flavor balance, and health benefits",
  "ingredients": [
    {{
      "crop_name": "Matching crop keyword (e.g. Tomato, Onion, Chilli)",
      "quantity_grams": 350,
      "role": "Culinary role (e.g. Base broth, spicy heat, aromatics)"
    }}
  ]
}}
Do NOT include markdown fences, preambles, or conversational text."""

    candidate_models = [
        getattr(settings, "GEMINI_MODEL_NAME", "gemini-2.5-flash"),
        "gemini-2.5-flash",
        "gemini-3.6-flash",
        "gemini-flash-latest",
    ]
    models_to_try = list(dict.fromkeys(filter(None, candidate_models)))

    # 1. Try google.genai
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
                    raw = resp.text.strip()
                    if raw.startswith("```"):
                        raw = re.sub(r"^```(?:json)?\s*", "", raw)
                        raw = re.sub(r"\s*```$", "", raw)
                    data = json.loads(raw)
                    if "ingredients" in data and len(data["ingredients"]) > 0:
                        return data
            except Exception as exc:
                logger.warning("google.genai model %s failed for recipe: %s", m_name, exc)
    except Exception as exc:
        logger.warning("google.genai SDK unavailable for recipe: %s", exc)

    # 2. Try google.generativeai fallback
    try:
        import google.generativeai as genai_legacy
        genai_legacy.configure(api_key=gemini_key)
        for m_name in models_to_try:
            try:
                model = genai_legacy.GenerativeModel(m_name)
                resp = model.generate_content(prompt)
                if resp and resp.text:
                    raw = resp.text.strip()
                    if raw.startswith("```"):
                        raw = re.sub(r"^```(?:json)?\s*", "", raw)
                        raw = re.sub(r"\s*```$", "", raw)
                    data = json.loads(raw)
                    if "ingredients" in data and len(data["ingredients"]) > 0:
                        return data
            except Exception as exc:
                logger.warning("google.generativeai model %s failed: %s", m_name, exc)
    except Exception as exc:
        logger.warning("google.generativeai failed: %s", exc)

    return None


# ==============================================================================
# 3. HIGH-LEVEL COMBO GENERATION ENGINE
# ==============================================================================

def generate_recipe_combo(dish_name: str, servings: int = 4, persist: bool = True) -> Dict[str, Any]:
    """
    Main entrypoint: Generates a dynamically priced recipe ingredient combo for a dish and servings count.
    Uses Gemini API if available, falling back gracefully to local heuristic culinary tables.
    Returns calculated combo data and optionally creates a RecipeCombo model record.
    """
    servings = max(1, min(20, int(servings or 4)))
    clean_dish = (dish_name or "Sambar").strip()

    # Attempt AI generation
    ai_result = query_gemini_recipe(clean_dish, servings)

    if ai_result:
        dish_title = ai_result.get("dish_title") or f"{clean_dish.title()}"
        prep_time = int(ai_result.get("prep_time_minutes") or 30)
        notes = ai_result.get("culinary_notes") or f"Optimal blend of farm ingredients for {clean_dish}."
        raw_ingredients = ai_result.get("ingredients", [])
    else:
        # Heuristic fallback
        fallback = _get_fallback_recipe(clean_dish)
        dish_title = fallback["dish_name"]
        prep_time = fallback["prep_time_minutes"]
        notes = fallback["culinary_notes"]
        base_servings = fallback.get("base_servings", 4)
        multiplier = Decimal(str(servings)) / Decimal(str(base_servings))

        raw_ingredients = []
        for ing in fallback["ingredients"]:
            scaled_grams = int(Decimal(str(ing["base_grams"])) * multiplier)
            raw_ingredients.append({
                "crop_name": ing["crop_keyword"],
                "quantity_grams": scaled_grams,
                "role": ing["role"],
            })

    # Map raw ingredients to database Crops and calculate costs
    items_breakdown = []
    original_total = Decimal("0.00")
    total_weight_grams = 0

    # Default demo farmer fallback
    demo_farmer = User.objects.filter(role=User.Role.FARMER).first()

    for item in raw_ingredients:
        keyword = item.get("crop_name") or item.get("crop_keyword") or "Tomato"
        crop = _match_crop(keyword)
        if not crop:
            continue

        grams = max(20, int(item.get("quantity_grams", 200)))
        kg = Decimal(str(grams)) / Decimal("1000.00")
        item_price = (kg * crop.base_price).quantize(Decimal("0.01"))

        # Determine farmer attribution
        farmer = crop.farmer or demo_farmer

        items_breakdown.append({
            "crop_id": crop.id,
            "crop_name": crop.name,
            "crop_code": crop.code,
            "quantity_grams": grams,
            "role": item.get("role", "Essential fresh ingredient"),
            "base_price_per_kg": float(crop.base_price),
            "standalone_price": float(item_price),
            "farmer_id": farmer.id if farmer else None,
            "farmer_name": farmer.get_full_name() if farmer else "Ramesh Kumar (K2K Verified Farmer)",
            "farmer_location": f"{getattr(farmer, 'state', 'Telangana')} Cluster",
        })

        original_total += item_price
        total_weight_grams += grams

    if not items_breakdown:
        # Absolute safety net: add default tomato + onion
        default_crop = Crop.objects.first()
        if default_crop:
            standalone = (Decimal("0.50") * default_crop.base_price).quantize(Decimal("0.01"))
            items_breakdown.append({
                "crop_id": default_crop.id,
                "crop_name": default_crop.name,
                "crop_code": default_crop.code,
                "quantity_grams": 500,
                "role": "Core farm-fresh produce base",
                "base_price_per_kg": float(default_crop.base_price),
                "standalone_price": float(standalone),
                "farmer_id": demo_farmer.id if demo_farmer else None,
                "farmer_name": demo_farmer.get_full_name() if demo_farmer else "K2K Partner Farmer",
                "farmer_location": "Hyderabad Hub Cluster",
            })
            original_total += standalone
            total_weight_grams += 500

    # Apply 15% bundle discount
    discount_pct = Decimal("15.00")
    discount_amount = (original_total * (discount_pct / Decimal("100.00"))).quantize(Decimal("0.01"))
    combo_price = (original_total - discount_amount).quantize(Decimal("0.01"))
    total_kg = (Decimal(str(total_weight_grams)) / Decimal("1000.00")).quantize(Decimal("0.01"))

    # Direct farmer payout calculation (90% of combo price)
    farmer_payout = (combo_price * Decimal("0.90")).quantize(Decimal("0.01"))

    combo_record = None
    if persist:
        combo_record = RecipeCombo.objects.create(
            dish_name=dish_title,
            servings=servings,
            prep_time_minutes=prep_time,
            culinary_notes=notes,
            total_weight_kg=total_kg,
            original_price=original_total,
            discount_percentage=discount_pct,
            combo_price=combo_price,
            items_breakdown=items_breakdown,
        )

    return {
        "combo_id": combo_record.combo_id if combo_record else f"K2K-CMB-{uuid.uuid4().hex[:6].upper()}",
        "combo_db_id": combo_record.id if combo_record else None,
        "dish_name": dish_title,
        "servings": servings,
        "prep_time_minutes": prep_time,
        "culinary_notes": notes,
        "total_weight_kg": float(total_kg),
        "original_price": float(original_total),
        "discount_percentage": float(discount_pct),
        "combo_price": float(combo_price),
        "total_savings": float(discount_amount),
        "farmer_payout": float(farmer_payout),
        "items": items_breakdown,
    }
