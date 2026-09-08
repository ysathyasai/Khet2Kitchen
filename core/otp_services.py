"""
Project Khet2Kitchen (K2K) - Unified Authentication Services Layer
Provides:
1. International Phone Number Normalization (E.164 with +91 Indian fallback)
2. Email OTP Dispatch & Verification (Cached 5-minute expiry, non-destructive to passwords)
"""

import logging
import random
import re
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


# ============================================================================
# 1. PHONE SANITIZATION & NORMALIZATION (E.164)
# ============================================================================

def normalize_phone_number(raw_phone: str) -> str:
    """
    Normalizes input phone numbers into standard international E.164 format (+91...).
    
    Rules:
    - Strips all spaces, hyphens, parentheses, dots, and formatting characters.
    - If a 10-digit number is provided (e.g., '9876543210'), automatically prepends '+91'.
    - If an 11-digit number starting with '0' is provided (e.g., '09876543210'), strips '0' and prepends '+91'.
    - If a 12-digit number starting with '91' is provided (e.g., '919876543210'), prepends '+'.
    - If number already starts with '+', validates and preserves the country code.
    """
    if not raw_phone:
        return ""

    raw_str = str(raw_phone).strip()
    # Strip spaces, hyphens, parentheses, dots
    cleaned = re.sub(r"[\s\-\(\)\.]", "", raw_str)
    if not cleaned:
        return ""

    if cleaned.startswith("+"):
        digits_only = re.sub(r"[^\d]", "", cleaned[1:])
        return f"+{digits_only}"

    digits = re.sub(r"[^\d]", "", cleaned)
    if len(digits) == 10:
        return f"+91{digits}"
    elif len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    elif len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    elif digits:
        return f"+{digits}"

    return ""


def is_email_identifier(identifier: str) -> bool:
    """Checks whether the user entered an email address or a phone number."""
    return "@" in str(identifier)


# ============================================================================
# 2. EMAIL OTP SERVICE (Cache-Backed 5-Min Expiry, Non-Destructive)
# ============================================================================

class EmailOTPService:
    """
    Manages generation, dispatch, and validation of 6-digit numeric Email OTPs.
    Uses Django Cache with a 300-second (5-minute) TTL.
    Requesting an OTP never invalidates or modifies the user's permanent password.
    """

    OTP_VALIDITY_SECONDS = 300  # 5 minutes
    CACHE_KEY_PREFIX = "k2k_email_otp_"

    @classmethod
    def _make_key(cls, email: str) -> str:
        return f"{cls.CACHE_KEY_PREFIX}{str(email).strip().lower()}"

    @classmethod
    def generate_otp(cls) -> str:
        """Generates a secure 6-digit numeric OTP string."""
        return f"{random.randint(100000, 999999)}"

    @classmethod
    def send_otp(cls, email: str, request=None) -> Tuple[bool, str, str]:
        """
        Generates and stores an OTP for the provided email, then sends it via Django email.
        Returns: (success: bool, message: str, otp_code: str)
        """
        clean_email = str(email).strip().lower()
        if not clean_email or "@" not in clean_email:
            return False, "Please enter a valid email address.", ""

        otp_code = cls.generate_otp()
        cache_key = cls._make_key(clean_email)

        # Store in cache with 5 minutes TTL
        payload = {
            "code": otp_code,
            "created_at": time.time(),
        }
        cache.set(cache_key, payload, timeout=cls.OTP_VALIDITY_SECONDS)

        # Also store in session if request object is available (as resilient fallback)
        if request and hasattr(request, "session"):
            request.session[cache_key] = otp_code

        subject = "🌾 Khet2Kitchen OTP - Secure Login"
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@khet2kitchen.com")

        text_message = f"""
🌾 Khet2Kitchen Secure Login

Hello,

Your One-Time Password (OTP) for K2K login is:

    {otp_code}

⏱️  This OTP is valid for 5 minutes.
🔒 Never share this OTP with anyone.

If you didn't request this OTP, you can safely ignore this email.

---
Empowering Indian Farmers • Khet2Kitchen Platform
https://khet2kitchen.onrender.com/
        """.strip()

        html_message = f"""
        <div style="font-family: Arial, sans-serif; max-width: 540px; margin: 0 auto; padding: 24px; border: 1px solid #E5E9E2; border-radius: 12px; background: #FFFFFF;">
            <div style="background: linear-gradient(135deg, #133826, #059669); color: white; padding: 20px; border-radius: 8px; text-align: center;">
                <h1 style="margin: 0; font-size: 24px;">🌾 Khet2Kitchen</h1>
                <p style="margin: 6px 0 0 0; font-size: 13px; color: #A7F3D0;">Direct Farm-to-Fork Platform</p>
            </div>
            <div style="padding: 24px 8px; text-align: center;">
                <p style="color: #374151; font-size: 15px; margin-bottom: 18px;">
                    Use this 6-digit One-Time Password (OTP) to securely sign in:
                </p>
                <div style="background: #F4F6F1; border: 2px dashed #059669; padding: 16px 24px; border-radius: 8px; display: inline-block; margin: 12px auto;">
                    <span style="font-size: 38px; font-weight: 800; color: #133826; letter-spacing: 8px; font-family: monospace;">
                        {otp_code}
                    </span>
                </div>
                <p style="color: #6B7280; font-size: 13px; margin-top: 16px;">
                    ⏱️ <strong>Valid for 5 minutes</strong>. Never share your OTP with anyone.
                </p>
            </div>
            <div style="border-top: 1px solid #E5E7EB; padding-top: 16px; text-align: center; color: #9CA3AF; font-size: 12px;">
                © 2026 Project Khet2Kitchen (K2K) • Smart India Hackathon
            </div>
        </div>
        """.strip()

        # Send email via Django's configured backend
        try:
            send_mail(
                subject=subject,
                message=text_message,
                from_email=from_email,
                recipient_list=[clean_email],
                html_message=html_message,
                fail_silently=False,
            )
            logger.info("Email OTP dispatched successfully to %s via %s", clean_email, settings.EMAIL_HOST_USER)
            return True, f"OTP sent to {clean_email}. Valid for 5 minutes.", otp_code
        except Exception as exc:
            logger.error("SMTP dispatch failed for %s: %s", clean_email, exc)
            if getattr(settings, "DEBUG", False):
                print(f"\n========================================================")
                print(f"[K2K LOCAL FALLBACK] OTP for {clean_email}: {otp_code}")
                print(f"(SMTP warning: {exc})")
                print(f"To deliver actual emails to inboxes, add your Google App Password to .env:")
                print(f"EMAIL_HOST_PASSWORD=xxxx xxxx xxxx xxxx")
                print(f"========================================================\n")
                return True, f"OTP generated! (Dev mode: OTP is {otp_code} | Check terminal or set EMAIL_HOST_PASSWORD)", otp_code
            return False, f"Failed to send email OTP: {exc}", ""

    @classmethod
    def verify_otp(cls, email: str, provided_otp: str, request=None) -> Tuple[bool, str]:
        """
        Verifies the provided OTP against the stored active cache/session value.
        On success, consumes the OTP so it cannot be replayed.
        """
        clean_email = str(email).strip().lower()
        clean_otp = str(provided_otp).strip()
        if not clean_email or not clean_otp:
            return False, "Email and OTP code are required."

        cache_key = cls._make_key(clean_email)
        cached_data = cache.get(cache_key)
        session_otp = None
        if request and hasattr(request, "session"):
            session_otp = request.session.get(cache_key)

        expected_code = None
        if isinstance(cached_data, dict):
            expected_code = cached_data.get("code")
        elif isinstance(cached_data, str):
            expected_code = cached_data

        if not expected_code and session_otp:
            expected_code = str(session_otp).strip()

        if not expected_code:
            return False, "No active OTP found or OTP expired. Please request a new one."

        if str(expected_code).strip() == clean_otp:
            # Verified! Invalidate immediately to prevent replay
            cache.delete(cache_key)
            if request and hasattr(request, "session"):
                request.session.pop(cache_key, None)
            return True, "Email OTP verified successfully."

        return False, "Invalid OTP. Please check the code and try again."

