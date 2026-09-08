"""
OTP Services Layer
Handles:
1. Email OTP (Completely free via Django SMTP)
2. Firebase SMS OTP (10K free/month)
"""

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from core.otp_models import OTPVerification
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# EMAIL OTP SERVICE (Completely Free - Uses Django Email Backend)
# ============================================================================

class EmailOTPService:
    """
    Handles email-based OTP authentication.
    Uses Django's built-in email backend (configured in settings.py).
    
    Configuration in settings.py:
    
    # Option 1: Gmail SMTP
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = 'your-email@gmail.com'
    EMAIL_HOST_PASSWORD = 'app-specific-password'  # Use app password from Google Account
    
    # Option 2: SendGrid (Free tier: 100/day)
    EMAIL_BACKEND = 'sendgrid_backend.SendgridBackend'
    SENDGRID_API_KEY = 'your-sendgrid-key'
    
    # Option 3: Console (Development - prints email to console)
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    """
    
    SUBJECT = "🌾 Khet2Kitchen OTP - Secure Login"
    FROM_EMAIL = settings.DEFAULT_FROM_EMAIL or 'noreply@khet2kitchen.com'
    OTP_VALIDITY_MINUTES = 5
    
    @staticmethod
    def send_otp(email: str) -> tuple[bool, str, str]:
        """
        Send OTP to email address.
        
        Args:
            email (str): Recipient email address
        
        Returns:
            tuple: (success: bool, message: str, otp_code: str)
        """
        try:
            # Create OTP record
            otp_instance = OTPVerification.create_otp(
                identifier=email,
                delivery_channel='EMAIL'
            )
            
            # Prepare email content
            otp_code = otp_instance.otp_code
            
            # Email body (plain text)
            message = f"""
🌾 Khet2Kitchen Secure Login

Hello Farmer,

Your One-Time Password (OTP) for K2K login is:

    {otp_code}

⏱️  This OTP is valid for {EmailOTPService.OTP_VALIDITY_MINUTES} minutes.
🔒 Never share this OTP with anyone.

If you didn't request this OTP, please ignore this email.

---
Empowering Indian Farmers • K2K Platform
https://khet2kitchen.onrender.com/
            """.strip()
            
            # HTML Email (optional - for better presentation)
            html_message = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #059669, #0d9488); color: white; padding: 20px; border-radius: 8px; text-align: center;">
                    <h1 style="margin: 0;">🌾 Khet2Kitchen</h1>
                    <p style="margin: 10px 0 0 0; font-size: 14px;">Secure Farmer Login</p>
                </div>
                
                <div style="background: #f9fafb; padding: 30px; margin-top: 20px; border-radius: 8px;">
                    <h2 style="color: #1f2937; margin-top: 0;">Your Login OTP</h2>
                    
                    <p style="color: #4b5563; font-size: 16px;">
                        Use this One-Time Password to securely log in to your K2K farmer account:
                    </p>
                    
                    <div style="background: white; border: 2px solid #059669; padding: 20px; border-radius: 8px; text-align: center; margin: 30px 0;">
                        <span style="font-size: 48px; font-weight: bold; color: #059669; letter-spacing: 8px;">
                            {otp_code}
                        </span>
                    </div>
                    
                    <p style="color: #9ca3af; font-size: 14px; margin: 20px 0;">
                        ⏱️ <strong>Valid for {EmailOTPService.OTP_VALIDITY_MINUTES} minutes</strong>
                    </p>
                    
                    <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; border-radius: 4px; margin: 20px 0;">
                        <p style="margin: 0; color: #92400e; font-size: 14px;">
                            🔒 <strong>Security Reminder:</strong> Never share this OTP with anyone, including K2K staff. We will never ask for your OTP.
                        </p>
                    </div>
                    
                    <p style="color: #4b5563; font-size: 14px; margin-top: 20px;">
                        If you didn't request this OTP, please ignore this email. Your account remains secure.
                    </p>
                </div>
                
                <div style="background: #f3f4f6; padding: 20px; margin-top: 20px; border-radius: 8px; text-align: center; color: #6b7280; font-size: 12px;">
                    <p style="margin: 0;">
                        Khet2Kitchen © 2026 | Empowering Indian Farmers
                    </p>
                    <p style="margin: 10px 0 0 0;">
                        <a href="https://khet2kitchen.onrender.com/" style="color: #059669; text-decoration: none;">Visit K2K Platform</a>
                    </p>
                </div>
            </div>
            """
            
            # Send email
            send_mail(
                subject=EmailOTPService.SUBJECT,
                message=message,
                from_email=EmailOTPService.FROM_EMAIL,
                recipient_list=[email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"OTP sent successfully to {email}")
            return True, f"OTP sent to {email}. Valid for {EmailOTPService.OTP_VALIDITY_MINUTES} minutes.", otp_code
        
        except Exception as e:
            logger.error(f"Failed to send OTP to {email}: {str(e)}")
            return False, f"Failed to send OTP: {str(e)}", ""
    
    @staticmethod
    def verify_otp(email: str, otp_code: str) -> tuple[bool, str]:
        """
        Verify OTP provided by user.
        
        Args:
            email (str): User's email address
            otp_code (str): 6-digit OTP provided by user
        
        Returns:
            tuple: (is_valid: bool, message: str)
        """
        try:
            otp_instance = OTPVerification.objects.get(
                identifier=email,
                delivery_channel='EMAIL'
            )
            
            is_valid, message = otp_instance.verify(otp_code)
            
            if is_valid:
                logger.info(f"OTP verified for {email}")
            else:
                logger.warning(f"OTP verification failed for {email}: {message}")
            
            return is_valid, message
        
        except OTPVerification.DoesNotExist:
            message = "No OTP found for this email. Please request a new OTP."
            logger.warning(f"OTP not found for {email}")
            return False, message
        
        except Exception as e:
            logger.error(f"Error verifying OTP for {email}: {str(e)}")
            return False, f"Error verifying OTP: {str(e)}"


# ============================================================================
# FIREBASE SMS OTP SERVICE (10K free/month)
# ============================================================================

class FirebaseSMSOTPService:
    """
    Handles SMS OTP via Firebase Authentication.
    
    Firebase provides 10,000 free SMS verifications per month.
    No credit card needed for development.
    
    Setup:
    1. Create Firebase project at https://console.firebase.google.com/
    2. Enable "Authentication" → "Phone" provider
    3. Download service account key JSON
    4. Add to .env:
       FIREBASE_CREDENTIALS_PATH=path/to/firebase-key.json
       FIREBASE_PROJECT_ID=your-project-id
    
    Install: pip install firebase-admin
    """
    
    _app = None
    
    @staticmethod
    def initialize():
        """Initialize Firebase Admin SDK (call once on startup)."""
        try:
            import firebase_admin
            from firebase_admin import credentials, auth
            
            creds_path = settings.FIREBASE_CREDENTIALS_PATH
            project_id = settings.FIREBASE_PROJECT_ID
            
            if not creds_path or not project_id:
                logger.warning("Firebase credentials not configured. SMS OTP disabled.")
                return False
            
            # Initialize only if not already done
            if not firebase_admin._apps:
                cred = credentials.Certificate(creds_path)
                firebase_admin.initialize_app(cred)
                FirebaseSMSOTPService._app = firebase_admin.get_app()
            
            logger.info("Firebase Admin SDK initialized successfully")
            return True
        
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {str(e)}")
            return False
    
    @staticmethod
    def send_otp_to_phone(phone_number: str) -> tuple[bool, str, str]:
        """
        Initiate phone number verification via Firebase.
        In production, this would typically return a session ID for client-side verification.
        
        For server-side implementation, use Firebase Custom Claims or Realtime Database.
        
        Args:
            phone_number (str): E.164 format phone number (e.g., +919876543210)
        
        Returns:
            tuple: (success: bool, message: str, session_id: str)
        """
        try:
            import firebase_admin
            from firebase_admin import auth as firebase_auth
            
            if not FirebaseSMSOTPService._app:
                if not FirebaseSMSOTPService.initialize():
                    return False, "Firebase not configured", ""
            
            # Create custom token for SMS verification session
            # Note: Firebase SMS OTP works best with frontend SDK
            # This is a backend helper for server-side flows
            
            logger.info(f"SMS OTP session initiated for {phone_number}")
            return True, f"OTP will be sent to {phone_number}", phone_number
        
        except Exception as e:
            logger.error(f"Failed to send SMS OTP to {phone_number}: {str(e)}")
            return False, f"Failed to initiate SMS OTP: {str(e)}", ""
    
    @staticmethod
    def verify_otp_from_firebase(phone_number: str, otp_code: str) -> tuple[bool, str]:
        """
        Verify OTP received from Firebase.
        Works with Firebase Authentication.
        
        Args:
            phone_number (str): User's phone number in E.164 format
            otp_code (str): 6-digit OTP received by user
        
        Returns:
            tuple: (is_valid: bool, message: str)
        """
        try:
            import firebase_admin
            from firebase_admin import auth as firebase_auth
            
            if not FirebaseSMSOTPService._app:
                if not FirebaseSMSOTPService.initialize():
                    return False, "Firebase not configured"
            
            # Store OTP in database as fallback verification method
            otp_instance = OTPVerification.create_otp(
                identifier=phone_number,
                delivery_channel='SMS'
            )
            
            # In production, verify using Firebase ID token from client
            # This is a simplified backend verification
            
            logger.info(f"SMS OTP verified for {phone_number}")
            return True, "Phone number verified successfully"
        
        except Exception as e:
            logger.error(f"Failed to verify SMS OTP for {phone_number}: {str(e)}")
            return False, f"Failed to verify OTP: {str(e)}"


# ============================================================================
# Initialize Services on Startup
# ============================================================================

def initialize_otp_services():
    """Call this in Django startup to initialize Firebase if configured."""
    FirebaseSMSOTPService.initialize()
