"""
OTP Authentication Views
Handles login flow with Email OTP
"""

import logging
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
        success, message, otp_code, *rest = EmailOTPService.send_otp(email)
        
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
        email = request.session.get('pending_email')
        if not email:
            messages.warning(request, "Please request an OTP first.")
            return redirect('email_otp_login')
        
        return render(request, 'core/email_otp_verify.html', {'email': email})

    def post(self, request):
        email = request.session.get('pending_email')
        otp = request.POST.get('otp', '').strip()
        
        if not email:
            messages.error(request, "Session expired. Please request a new OTP.")
            return redirect('email_otp_login')
        
        if not otp:
            messages.error(request, "Please enter the OTP.")
            return render(request, 'core/email_otp_verify.html', {'email': email})
        
        # Verify OTP
        is_valid, message = EmailOTPService.verify_otp(email, otp, request=request)
        
        if not is_valid:
            messages.error(request, message)
            return render(request, 'core/email_otp_verify.html', {'email': email})
        
        # OTP is valid, get or create user
        try:
            user = User.objects.get(email=email)
            # Log the user in
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            
            # Clean up session
            del request.session['pending_email']
            if 'otp_method' in request.session:
                del request.session['otp_method']
            
            messages.success(request, f"Welcome back, {user.get_full_name() or user.username}!")
            
            # Redirect to role-based dashboard
            return redirect('dashboard_dispatch')
            
        except User.DoesNotExist:
            # User doesn't exist, redirect to registration with pre-filled email
            messages.info(request, "Email verified! Please complete your registration.")
            request.session['verified_email'] = email
            return redirect('signup')


class EmailOTPResendView(View):
    """Resend OTP to the pending email."""
    def post(self, request):
        """Resend OTP to the same email."""
        email = request.session.get('pending_email')
        
        if not email:
            return JsonResponse({'success': False, 'message': 'No pending email found', 'email_sent': False})
        
        success, message, otp_code, *rest = EmailOTPService.send_otp(email)
        email_sent = rest[0] if rest else False
        
        return JsonResponse({
            'success': success,
            'message': message,
            'email_sent': email_sent,
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
