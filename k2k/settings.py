"""
Django settings for Project Khet2Kitchen (K2K).
Configured for Role-Based Access Control, MySQL support, and Render deployment.
"""

import os
import sys
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file if available
load_dotenv(BASE_DIR / '.env')

# Quick-start development settings - unsuitable for production
SECRET_KEY = os.getenv(
    'SECRET_KEY',
    'django-insecure-k2k-agricultural-supply-chain-dev-key-change-in-production'
)

DEBUG = os.getenv('DEBUG', 'True').strip().lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv('ALLOWED_HOSTS', '*').split(',')
    if host.strip()
]
if '*' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('*')

CSRF_TRUSTED_ORIGINS = [
    "https://*.ngrok-free.dev",
    "https://*.ngrok-free.app",
    "https://*.onrender.com",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    
    # Khet2Kitchen Apps & REST Framework
    'rest_framework',
    'core.apps.CoreConfig',
    'supply_chain.apps.SupplyChainConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'k2k.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'k2k.wsgi.application'

# Database Configuration
# Uses DATABASE_URL for PostgreSQL (Neon) / production, with SQLite fallback for local development.
# Uses isolated in-memory SQLite during automated test runs for speed and safety.
if 'test' in sys.argv:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }
else:
    DATABASES = {
        'default': dj_database_url.config(
            default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
            conn_max_age=600,
            conn_health_checks=True,
            ssl_require=True,
        )
    }

# SQLite does not support sslmode; strip it when falling back to SQLite locally
if 'sqlite' in DATABASES['default'].get('ENGINE', ''):
    DATABASES['default'].get('OPTIONS', {}).pop('sslmode', None)


# Custom User Model (RBAC)
AUTH_USER_MODEL = 'core.User'

# Authentication Backends (supports mobile number or email login)
AUTHENTICATION_BACKENDS = [
    'core.backends.DualAuthBackend',
    'django.contrib.auth.backends.ModelBackend',
]

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard_dispatch'
LOGOUT_REDIRECT_URL = 'login'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

# WhiteNoise storage configuration for production
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
WHITENOISE_MANIFEST_STRICT = False

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Hybrid Vernacular Voice Assistant Settings
SARVAM_API_KEY = os.getenv('SARVAM_API_KEY', '').strip()
SARVAM_API_BASE_URL = os.getenv('SARVAM_API_BASE_URL', 'https://api.sarvam.ai').strip()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL_NAME = os.getenv('GEMINI_MODEL_NAME', 'gemini-3.6-flash').strip()

# Authentication & Redirect Settings
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard_dispatch'
LOGOUT_REDIRECT_URL = 'home'

EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 't')
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'yejjusatyasai2007@gmail.com')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'Khet2Kitchen <yejjusatyasai2007@gmail.com>')
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', 5))  # 5s fail-safe socket timeout to prevent worker hangs on Render



