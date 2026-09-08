"""
OTP Authentication Views
Handles login flow with Email OTP
"""

from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.http import JsonResponse
from core.models import User
from core.otp_services import EmailOTPService

logger = logging.getLogger(__name__)


# ============================================================================
# EMAIL OTP VIEWS
# ============================================================================

class EmailOTPLoginView(View):
    """
    Step 1: User enters email and requests OTP
    Template: core/email_otp_login.html
    """
    
    def get(self, request):
        """Display email login form."""
        return render(request, 'core/email_otp_login.html')
    
    def post(self, request):
        """Send OTP to provided email."""
        email = request.POST.get('email', '').strip().lower()
        
        if not email:
            messages.error(request, "Please enter a valid email address.")
            return redirect('email_otp_login')
        
        # Send OTP via email
        success, message, otp_code = EmailOTPService.send_otp(email)
        
        if success:
            # Store email in session for verification step
            request.session['pending_email'] = email
            request.session['otp_method'] = 'email'
            
            messages.success(request, message)
            return redirect('email_otp_verify')
        else:
            messages.error(request, message)
            return redirect('email_otp_login')


class EmailOTPVerifyView(View):
    """
    Step 2: User verifies OTP and logs in
    Template: core/email_otp_verify.html
    """
    
    def get(self, request):
        """Display OTP verification form."""
        email = request.session.get('pending_email')
        
        if not email:
            messages.error(request, "No pending OTP. Please request a new one.")
            return redirect('email_otp_login')
        
        return render(request, 'core/email_otp_verify.html', {'email': email})
    
    def post(self, request):
        """Verify OTP and auto-login user."""
        email = request.session.get('pending_email')
        otp_code = request.POST.get('otp_code', '').strip()
        
        if not email:
            messages.error(request, "Session expired. Please request OTP again.")
            return redirect('email_otp_login')
        
        if not otp_code:
            messages.error(request, "Please enter the OTP.")
            return redirect('email_otp_verify')
        
        # Verify OTP
        is_valid, message = EmailOTPService.verify_otp(email, otp_code)
        
        if not is_valid:
            messages.error(request, message)
            return redirect('email_otp_verify')
        
        # OTP is valid - get or create user
        try:
            # Get existing farmer by email or create new one
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'identifier': email,
                    'role': User.Role.FARMER,
                    'is_active': True
                }
            )
            
            # Update identifier if it was created with phone before
            if not user.identifier:
                user.identifier = email
                user.save()
            
            # Log in user
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            
            # Clean up session
            del request.session['pending_email']
            del request.session['otp_method']
            
            # Delete OTP record (one-time use)
            OTPVerification.objects.filter(identifier=email, delivery_channel='EMAIL').delete()
            
            messages.success(request, f"Welcome {user.get_full_name()}!")
            
            # Redirect to dashboard
            return redirect(user.get_dashboard_url())
        
        except Exception as e:
            logger.error(f"Error during email OTP login: {str(e)}")
            messages.error(request, f"Login error: {str(e)}")
            return redirect('email_otp_login')


class EmailOTPResendView(View):
    """Resend OTP to email if it expired."""
    
    def post(self, request):
        """Resend OTP to the same email."""
        email = request.session.get('pending_email')
        
        if not email:
            return JsonResponse({'success': False, 'message': 'No pending email found'})
        
        success, message, otp_code = EmailOTPService.send_otp(email)
        
        return JsonResponse({
            'success': success,
            'message': message
        })


# ============================================================================
# LOGOUT VIEW
# ============================================================================

@require_http_methods(["GET", "POST"])
def logout_view(request):
    """Log out user and redirect to login."""
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('otp_method_choice')
