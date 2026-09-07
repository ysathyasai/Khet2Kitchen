"""
Khet2Kitchen (K2K) Supply Chain Models.

Provides the DemandOrder model supporting dual revenue & fulfillment channels:
- B2B Wholesale: Bulk institutional and restaurant pre-orders at wholesale rates.
- COMMUNITY: Weekly RWA gated-society subscription boxes at premium farm-fresh retail rates (~28.5% net margin).
"""

from core.models import (
    Batch,
    Crop,
    DemandOrder,
    InputSupply,
    MicroHub,
    User,
)

__all__ = [
    "DemandOrder",
    "Crop",
    "MicroHub",
    "User",
    "Batch",
    "InputSupply",
]
