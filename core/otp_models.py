"""
OTP Verification Models for Email-based and Firebase SMS-based authentication.
Supports both Email OTP (completely free via Django SMTP) and Firebase SMS OTP (10K free/month).
"""

from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from datetime import timedelta
import random


class OTPVerification(models.Model):
    """
    Stores OTP verification records for email-based authentication.
    Self-destruct after successful verification or expiration.
    """
    
    DELIVERY_CHANNEL = [
        ('EMAIL', _('Email')),
        ('SMS', _('SMS via Firebase')),
    ]
    
    # Identifier: Email or Phone Number
    identifier = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name=_("Email / Phone Number"),
        help_text=_("Email address for email OTP or phone number for SMS OTP")
    )
    
    # OTP Code (6 digits)
    otp_code = models.CharField(
        max_length=6,
        verbose_name=_("OTP Code"),
        help_text=_("6-digit one-time password")
    )
    
    # Delivery Channel
    delivery_channel = models.CharField(
        max_length=10,
        choices=DELIVERY_CHANNEL,
        default='EMAIL',
        verbose_name=_("Delivery Channel")
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    expires_at = models.DateTimeField(verbose_name=_("Expires At"))
    
    # Verification Status
    is_verified = models.BooleanField(
        default=False,
        verbose_name=_("Is Verified"),
        help_text=_("Mark as True after successful OTP verification")
    )
    
    # Security: Track failed attempts
    attempt_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Failed Attempt Count")
    )
    
    MAX_ATTEMPTS = 5  # Max wrong OTP attempts before lockout
    
    class Meta:
        verbose_name = _("OTP Verification")
        verbose_name_plural = _("OTP Verifications")
        ordering = ['-created_at']
        # Only one active OTP per identifier
        indexes = [
            models.Index(fields=['identifier', 'is_verified']),
            models.Index(fields=['identifier', 'expires_at']),
        ]
    
    def __str__(self):
        return f"OTP for {self.identifier} ({self.get_delivery_channel_display()}) - {'Verified' if self.is_verified else 'Pending'}"
    
    @property
    def is_expired(self) -> bool:
        """Check if OTP has expired."""
        return timezone.now() > self.expires_at
    
    @property
    def is_locked_out(self) -> bool:
        """Check if OTP is locked due to too many failed attempts."""
        return self.attempt_count >= self.MAX_ATTEMPTS
    
    def verify(self, provided_otp: str) -> tuple[bool, str]:
        """
        Verify the provided OTP against the stored OTP.
        Returns: (is_valid: bool, message: str)
        """
        # Check if expired
        if self.is_expired:
            return False, "OTP has expired. Please request a new one."
        
        # Check if locked out
        if self.is_locked_out:
            return False, "Too many failed attempts. Please request a new OTP."
        
        # Check if already verified
        if self.is_verified:
            return False, "OTP already used. Please request a new one."
        
        # Check OTP code
        if self.otp_code == provided_otp:
            self.is_verified = True
            self.save(update_fields=['is_verified'])
            return True, "OTP verified successfully!"
        else:
            self.attempt_count += 1
            self.save(update_fields=['attempt_count'])
            remaining = self.MAX_ATTEMPTS - self.attempt_count
            if remaining > 0:
                return False, f"Incorrect OTP. {remaining} attempts remaining."
            else:
                return False, "OTP verification locked. Please request a new OTP."
    
    @staticmethod
    def generate_otp() -> str:
        """Generate a random 6-digit OTP."""
        return f"{random.randint(100000, 999999)}"
    
    @staticmethod
    def create_otp(identifier: str, delivery_channel: str = 'EMAIL') -> "OTPVerification":
        """
        Create a new OTP for the given identifier.
        Automatically expires in 5 minutes.
        Replaces any previous unverified OTP for the same identifier.
        """
        # Delete previous unverified OTPs for this identifier
        OTPVerification.objects.filter(
            identifier=identifier,
            is_verified=False
        ).delete()
        
        # Create new OTP
        otp_instance = OTPVerification.objects.create(
            identifier=identifier,
            otp_code=OTPVerification.generate_otp(),
            delivery_channel=delivery_channel,
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        
        return otp_instance


class FirebaseUser(models.Model):
    """
    Maps Django User to Firebase Authentication UID.
    Used for Firebase SMS OTP authentication tracking.
    """
    
    user = models.OneToOneField(
        'core.User',
        on_delete=models.CASCADE,
        related_name='firebase_account',
        verbose_name=_("Django User")
    )
    
    firebase_uid = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Firebase UID"),
        help_text=_("Unique identifier from Firebase Authentication")
    )
    
    phone_number = models.CharField(
        max_length=17,
        blank=True,
        verbose_name=_("Verified Phone Number"),
        help_text=_("Phone number verified via Firebase SMS OTP")
    )
    
    is_phone_verified = models.BooleanField(
        default=False,
        verbose_name=_("Phone Number Verified")
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _("Firebase User")
        verbose_name_plural = _("Firebase Users")
    
    def __str__(self):
        return f"Firebase Account for {self.user.get_full_name()}"
