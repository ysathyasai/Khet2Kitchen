from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


class DualAuthBackend(ModelBackend):
    """
    Custom authentication backend supporting:
    - Farmers: logging in via mobile phone number (or identifier).
    - Retailers / Suppliers / Admins: logging in via email address (or identifier).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get("phone_number") or kwargs.get("email") or kwargs.get("identifier")

        if not username:
            return None

        username = str(username).strip()

        # Match against identifier, email (case-insensitive), or phone_number
        try:
            user = User.objects.filter(
                Q(identifier__iexact=username)
                | Q(email__iexact=username)
                | Q(phone_number__iexact=username)
            ).first()
        except Exception:
            return None

        if user and user.is_active:
            # Check password if provided
            if password is not None and user.check_password(password):
                return user
            # Farmer OTP authentication extension point
            if kwargs.get("otp_verified") is True and user.role == User.Role.FARMER:
                return user

        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
