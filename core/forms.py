import re
from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from .models import User, FarmerWallet


class UserRegistrationForm(forms.ModelForm):
    """
    Secure User Registration Form for Project Khet2Kitchen (K2K).
    Supports multi-role registration with data mirroring:
    - Farmers authenticate via Mobile Phone Number.
    - Retailers and Suppliers authenticate via Email Address.
    Auto-provisions zero-balance FarmerWallet within an atomic transaction.
    """

    ROLE_CHOICES = [
        (User.Role.FARMER, _("Farmer (Direct Supply & Guaranteed MSP Floor)")),
        (User.Role.RETAILER, _("Retailer (Procure Fresh Produce B2B)")),
        (User.Role.SUPPLIER, _("Supplier (Seeds, Fertilizer & Agri-Equipment)")),
    ]

    name = forms.CharField(
        max_length=150,
        required=True,
        label=_("Full Name"),
        widget=forms.TextInput(attrs={
            "placeholder": "e.g. Ramesh Kumar or Ananya Sharma",
            "class": "form-input",
            "autofocus": True,
        }),
    )

    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        required=True,
        label=_("I am registering as"),
        widget=forms.Select(attrs={
            "class": "form-input",
            "id": "id_role_select",
        }),
    )

    identifier = forms.CharField(
        max_length=255,
        required=True,
        label=_("Phone Number or Email"),
        widget=forms.TextInput(attrs={
            "placeholder": "+919876543210 or user@business.com",
            "class": "form-input",
            "id": "id_identifier_input",
        }),
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "••••••••",
            "class": "form-input",
        }),
        label=_("Password / OTP"),
        min_length=6,
    )

    class Meta:
        model = User
        fields = ["name", "role", "identifier", "password"]

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if not name:
            raise ValidationError(_("Please enter your full name."))
        return name

    def clean_identifier(self):
        identifier = self.cleaned_data.get("identifier", "").strip()
        if not identifier:
            raise ValidationError(_("Please enter a phone number or email address."))

        # Unique identifier validation
        if User.objects.filter(identifier=identifier).exists():
            raise ValidationError(_("An account with this identifier already exists."))

        role = self.cleaned_data.get("role")
        if role == User.Role.FARMER:
            digits_only = re.sub(r"\D", "", identifier)
            if len(digits_only) < 10:
                raise ValidationError(_("Farmer identifier must be a valid mobile phone number with at least 10 digits."))
            if User.objects.filter(phone_number=identifier).exists():
                raise ValidationError(_("An account with this mobile phone number already exists."))
        elif role in (User.Role.RETAILER, User.Role.SUPPLIER):
            try:
                validate_email(identifier)
            except ValidationError:
                raise ValidationError(_("Identifier must be a valid email address for Retailers and Suppliers."))
            if User.objects.filter(email=identifier.lower()).exists():
                raise ValidationError(_("An account with this email address already exists."))

        return identifier

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        identifier = cleaned_data.get("identifier")

        if role and identifier:
            if role == User.Role.FARMER:
                digits_only = re.sub(r"\D", "", identifier)
                if len(digits_only) < 10:
                    self.add_error("identifier", _("Farmer identifier must be a valid mobile phone number with at least 10 digits."))
                elif User.objects.filter(phone_number=identifier).exists():
                    self.add_error("identifier", _("An account with this mobile phone number already exists."))
            elif role in (User.Role.RETAILER, User.Role.SUPPLIER):
                try:
                    validate_email(identifier)
                except ValidationError:
                    self.add_error("identifier", _("Identifier must be a valid email address for Retailers and Suppliers."))
                if User.objects.filter(email=identifier.lower()).exists():
                    self.add_error("identifier", _("An account with this email address already exists."))

        return cleaned_data

    def _post_clean(self):
        role = self.cleaned_data.get("role")
        identifier = self.cleaned_data.get("identifier")
        if role:
            self.instance.role = role

        if role and identifier:
            self.instance.identifier = identifier
            if role == User.Role.FARMER:
                self.instance.phone_number = identifier
                self.instance.email = None
            elif role in (User.Role.RETAILER, User.Role.SUPPLIER):
                self.instance.email = identifier.lower()
                self.instance.phone_number = None

        name = self.cleaned_data.get("name")
        if name:
            first_name, _, last_name = name.strip().partition(" ")
            self.instance.first_name = first_name
            self.instance.last_name = last_name

        # If form-level fields already failed validation, skip model full_clean()
        # to prevent unlisted model fields (email/phone) from raising form-mapping ValueErrors.
        if self.errors:
            return

        super()._post_clean()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])

        # CRITICAL FIX 1 (Name Splitting)
        first_name, _, last_name = self.cleaned_data["name"].strip().partition(" ")
        user.first_name = first_name
        user.last_name = last_name

        # CRITICAL FIX 2 (Double Column Assignment)
        identifier = self.cleaned_data["identifier"].strip()
        role = self.cleaned_data["role"]
        user.identifier = identifier
        user.role = role

        if role == User.Role.FARMER:
            user.phone_number = identifier
        elif role in (User.Role.RETAILER, User.Role.SUPPLIER):
            user.email = identifier.lower()

        if commit:
            with transaction.atomic():
                user.save()
                if user.role == User.Role.FARMER:
                    FarmerWallet.objects.create(farmer=user, current_balance=Decimal("0.00"))

        return user
