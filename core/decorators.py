from functools import wraps
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def role_required(allowed_roles, redirect_field_name=REDIRECT_FIELD_NAME, login_url=None):
    """
    Decorator for views that checks that the user is logged in and has
    one of the specified roles.

    :param allowed_roles: A single role or iterable of allowed roles (e.g. [User.Role.FARMER])
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                path = request.build_absolute_uri()
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(path, login_url, redirect_field_name)

            # Superusers and platform admins have blanket access
            if request.user.is_superuser or (
                hasattr(request.user, "role") and request.user.role == "ADMIN"
            ):
                return view_func(request, *args, **kwargs)

            # Check if user's role matches one of allowed roles
            user_role = getattr(request.user, "role", None)
            if user_role in allowed_roles:
                return view_func(request, *args, **kwargs)

            # Deny access if role does not match
            raise PermissionDenied(
                f"Access denied: This portal is restricted to {', '.join(allowed_roles)} accounts."
            )

        return _wrapped_view

    return decorator


class RoleRequiredMixin(AccessMixin):
    """
    CBV mixin that verifies that the current user has the required role.
    """
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if request.user.is_superuser or request.user.role == "ADMIN":
            return super().dispatch(request, *args, **kwargs)

        roles = self.allowed_roles
        if isinstance(roles, str):
            roles = [roles]

        if request.user.role not in roles:
            raise PermissionDenied(
                f"Access denied: Required roles: {', '.join(roles)}"
            )

        return super().dispatch(request, *args, **kwargs)
