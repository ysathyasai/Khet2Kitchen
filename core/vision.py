"""
K2K Computer Vision AI Grading Engine.
Simulates an edge-optical neural inspection station installed at Micro-Hubs.
"""

from decimal import Decimal, ROUND_HALF_UP
import hashlib
import logging
import random
from typing import Any, Dict, Optional, Union

from django.core.exceptions import ObjectDoesNotExist
from core.models import Batch, Crop

logger = logging.getLogger(__name__)


def analyze_crop_image(
    image_file: Any,
    crop_id: Union[int, Crop],
) -> Dict[str, Any]:
    """
    Simulates a Convolutional Neural Network (CNN) / Vision Transformer (ViT)
    optical quality inspection model for harvested agricultural produce.

    In production:
    - Receives RGB image stream from high-resolution micro-hub conveyor camera.
    - Evaluates produce geometry, skin color histogram, blemish detection,
      and ripeness grading.
    - Yields standard AGMARK/APEDA compatible export grades.

    Hackathon MVP Simulation:
    - Weighted probabilities: 60% Grade A (Export), 30% Grade B (Retail), 10% Grade C (Processing).
    - Confidence score: 82.0% - 99.4%.
    - Defect percentage tailored to grade.
    - Inspection metrics & crop-specific rationale.

    :param image_file: Uploaded file object or image filename/bytes.
    :param crop_id: Crop instance or primary key.
    :return: Quality inspection report dictionary.
    """
    if isinstance(crop_id, Crop):
        crop = crop_id
    else:
        try:
            crop = Crop.objects.get(pk=crop_id)
        except (Crop.DoesNotExist, ValueError) as exc:
            logger.error("Crop ID %s not found for vision grading: %s", crop_id, exc)
            raise ObjectDoesNotExist(f"Crop with ID {crop_id} does not exist.") from exc

    # Extract seed from image properties for deterministic repeat inspections
    seed_str = ""
    if hasattr(image_file, "name"):
        seed_str += str(image_file.name)
    if hasattr(image_file, "size"):
        seed_str += f"-{image_file.size}"
    if not seed_str:
        seed_str = f"{crop.code}-{random.randint(1000, 9999)}"

    hash_val = int(hashlib.md5(seed_str.encode()).hexdigest()[:6], 16)

    # 1. Weighted Grade Probability: 60% Grade A, 30% Grade B, 10% Grade C
    probability_roll = (hash_val % 100)
    if probability_roll < 60:
        grade = Batch.Grade.GRADE_A
        confidence_base = 92.0
        defect_min, defect_max = 0.8, 3.8
    elif probability_roll < 90:
        grade = Batch.Grade.GRADE_B
        confidence_base = 86.0
        defect_min, defect_max = 4.2, 11.0
    else:
        grade = Batch.Grade.GRADE_C
        confidence_base = 81.0
        defect_min, defect_max = 14.5, 26.5

    # 2. Confidence Score
    confidence_variance = (hash_val % 75) / 10.0
    confidence_score = Decimal(str(min(99.4, confidence_base + confidence_variance))).quantize(
        Decimal("0.10"), rounding=ROUND_HALF_UP
    )

    # 3. Defect Percentage
    defect_range = defect_max - defect_min
    defect_val = defect_min + ((hash_val % 100) / 100.0) * defect_range
    defect_percentage = Decimal(str(defect_val)).quantize(Decimal("0.10"), rounding=ROUND_HALF_UP)

    # 4. Color & Surface Metrics
    color_uniformity = Decimal(str(round(98.0 - float(defect_percentage) * 1.5, 1)))
    size_consistency = Decimal(str(round(96.0 - float(defect_percentage) * 1.2, 1)))
    surface_firmness = "Firm (Optimal)" if grade == Batch.Grade.GRADE_A else ("Normal Ambient" if grade == Batch.Grade.GRADE_B else "Soft / Immediate Processing")

    # 5. Crop-Specific Rationales
    grade_rationales = {
        Batch.Grade.GRADE_A: [
            f"Superb uniform pigmentation across {crop.name}. Zero deep cuts, optimal skin sheen, and calibrated export diameter.",
            f"Prime quality detected: High density, uniform circular geometry, negligible skin blemishes under 3%.",
            f"Premium grade harvest: Optimal color saturation and firm calyx structure. Qualified for Tier-1 urban retail.",
        ],
        Batch.Grade.GRADE_B: [
            f"Standard commercial quality for {crop.name}. Minor surface discoloration and slight size variation, ideal for supermarket shelves.",
            f"Good harvest batch: Intact skin firmness, acceptable minor skin abrasions under 10%.",
            f"Healthy produce with slight asymmetry. Meets domestic direct-retail procurement standards.",
        ],
        Batch.Grade.GRADE_C: [
            f"Processing grade: Surface blemishes and size asymmetry exceed standard retail thresholds. Recommended for dehydration / pulp processing.",
            f"Noticeable skin abrasions and color mottling detected. Dispatched for local institutional catering / food processors.",
            f"Commercial grade with {defect_percentage}% cosmetic defects. Non-exportable, discounted for secondary food processing.",
        ],
    }
    rationale_options = grade_rationales[grade]
    rationale = rationale_options[hash_val % len(rationale_options)]

    return {
        "crop_id": crop.id,
        "crop_name": crop.name,
        "crop_code": crop.code,
        "grade": grade,
        "grade_display": f"Grade {grade} ({'Export Premium' if grade == 'A' else ('Standard Retail' if grade == 'B' else 'Processing Economy')})",
        "confidence_score": confidence_score,
        "defect_percentage": defect_percentage,
        "rationale": rationale,
        "metrics": {
            "color_uniformity_pct": color_uniformity,
            "size_consistency_pct": size_consistency,
            "surface_firmness": surface_firmness,
            "optical_scan_resolution": "4K Multispectral",
        },
    }
