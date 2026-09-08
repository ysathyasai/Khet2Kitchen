from django.contrib.auth.base_user import BaseUserManager
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """
    Custom manager for User model supporting dynamic identifiers:
    - FARMER: defaults identifier to mobile number.
    - RETAILER / SUPPLIER / ADMIN: defaults identifier to email.
    """

    def create_user(
        self,
        identifier=None,
        email=None,
        phone_number=None,
        password=None,
        role=None,
        **extra_fields,
    ):
        """
        Creates and saves a User with the given credentials and role.
        """
        from core.models import User  # Local import to prevent circular dependency

        if role is None:
            # Default to FARMER if phone_number is supplied, otherwise RETAILER
            role = User.Role.FARMER if phone_number and not email else User.Role.RETAILER

        if email:
            email = self.normalize_email(email)

        if phone_number:
            phone_number = str(phone_number).strip()

        # Derive identifier if not explicitly provided
        if not identifier:
            identifier = phone_number or email
            if not identifier:
                raise ValueError(_("Users must have a mobile phone number or email address."))

        extra_fields.setdefault("is_active", True)

        user = self.model(
            identifier=identifier,
            email=email,
            phone_number=phone_number,
            role=role,
            **extra_fields,
        )

        if password:
            user.set_password(password)
        else:
            # For farmers logging in via OTP initially
            user.set_unusable_password()

        user.save(using=self._db)
        return user

    def create_superuser(self, identifier, email=None, password=None, **extra_fields):
        """
        Creates and saves a Superuser (ADMIN role) with email and password.
        """
        from core.models import User

        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", User.Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        if not email and "@" in identifier:
            email = identifier

        return self.create_user(
            identifier=identifier,
            email=email,
            password=password,
            **extra_fields,
        )

    # Role-based filtered querysets for clean domain querying
    def farmers(self):
        from core.models import User
        return self.get_queryset().filter(role=User.Role.FARMER)

    def retailers(self):
        from core.models import User
        return self.get_queryset().filter(role=User.Role.RETAILER)

    def suppliers(self):
        from core.models import User
        return self.get_queryset().filter(role=User.Role.SUPPLIER)

    def admins(self):
        from core.models import User
        return self.get_queryset().filter(role=User.Role.ADMIN)
