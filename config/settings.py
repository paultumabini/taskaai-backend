"""
settings.py — Django configuration for TaskaAI

How environment variables are loaded:
──────────────────────────────────────
python-dotenv's load_dotenv() is called at the top of manage.py before
Django imports this file. It reads the .env file and copies every key=value
pair into os.environ. After that, os.environ.get('KEY') works exactly like
reading a real system environment variable — no manual loading needed here.

In production (Railway), the platform injects environment variables directly,
so .env is not needed there and must never be committed to Git.

Variable resolution priority (highest → lowest):
  1. Real OS environment variables (export KEY=val or Railway dashboard)
  2. .env file values loaded by load_dotenv()
  3. The fallback default in os.environ.get('KEY', 'default')
"""

import os
from datetime import timedelta
from pathlib import Path

# BASE_DIR resolves to the taskaai_backend/ folder.
# Used to construct absolute paths for STATIC_ROOT etc.
BASE_DIR = Path(__file__).resolve().parent.parent


# ── SECURITY ──────────────────────────────────────────────────────────────────

# SECRET_KEY signs cookies, sessions, CSRF tokens, and password reset links.
# Any attacker who knows this can forge tokens — use a long random string in prod.
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production-min-50-chars')

# DEBUG=True enables:
#   - Detailed HTML error pages with full stack traces
#   - The DRF browsable API at /api/
#   - Automatic static file serving (no need for WhiteNoise in dev)
# Must be False in production — stack traces leak sensitive info.
DEBUG = os.environ.get('DEBUG', 'True') == 'True'

# ALLOWED_HOSTS — Django rejects requests whose HTTP Host header is not in this list.
# This prevents HTTP Host header injection attacks.
# In production add your Railway domain: e.g. myapp.up.railway.app
ALLOWED_HOSTS = os.environ.get(
    'ALLOWED_HOSTS', 'localhost,127.0.0.1,0.0.0.0'
).split(',')


# ── INSTALLED APPS ────────────────────────────────────────────────────────────

INSTALLED_APPS = [
    # Django built-ins
    'django.contrib.admin',         # /admin/ management UI
    'django.contrib.auth',          # User model, password hashing, authentication
    'django.contrib.contenttypes',  # required by auth and admin for generic relations
    'django.contrib.sessions',      # session framework (used by admin)
    'django.contrib.messages',      # one-time flash messages (used by admin)
    'django.contrib.staticfiles',   # static file handling (CSS/JS)

    # Third-party
    'rest_framework',               # Django REST Framework: serializers, viewsets, routers
    'rest_framework_simplejwt',     # JWT access/refresh token authentication
    'corsheaders',                  # CORS headers so the React frontend can call the API

    # Our app
    'tasks',                        # Task, Project, Tag models + all API views
]


# ── MIDDLEWARE ────────────────────────────────────────────────────────────────
# Middleware runs on every request in listed order (first = outermost wrapper).
# Response passes through in reverse order.

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',

    # CorsMiddleware MUST be before CommonMiddleware.
    # It intercepts the preflight OPTIONS request and adds CORS headers
    # before Django's other middleware can return a 301/302 redirect.
    'corsheaders.middleware.CorsMiddleware',

    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',

    # CsrfViewMiddleware validates the CSRF token on POST/PUT/PATCH/DELETE.
    # DRF's JWT authentication is CSRF-exempt for API views.
    # The Django admin still uses CSRF cookies, so we keep this middleware.
    # See CSRF_TRUSTED_ORIGINS below for why register endpoint needs it.
    'django.middleware.csrf.CsrfViewMiddleware',

    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
    },
}]

WSGI_APPLICATION = 'config.wsgi.application'


# ── DATABASE ──────────────────────────────────────────────────────────────────
# PostgreSQL for all environments.
# psycopg2-binary is the Python adapter — it translates Python objects to
# PostgreSQL wire protocol. All credentials come from .env / Render env vars.
#
# sslmode=require is applied automatically for remote hosts (Neon/production).
# Local PostgreSQL does not support SSL, so sslmode is omitted when DB_HOST
# is localhost or 127.0.0.1.

_db_host = os.environ.get('DB_HOST', 'localhost')
_db_options = {'sslmode': 'require'} if _db_host not in ('localhost', '127.0.0.1', '0.0.0.0', '') else {}

DATABASES = {
    'default': {
        'ENGINE':   'django.db.backends.postgresql',
        'NAME':     os.environ.get('DB_NAME'),
        'USER':     os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST':     _db_host,
        'PORT':     os.environ.get('DB_PORT'),
        'OPTIONS':  _db_options,
    }
}


# ── DJANGO REST FRAMEWORK ─────────────────────────────────────────────────────

REST_FRAMEWORK = {
    # JWTAuthentication reads Authorization: Bearer <token> header.
    # It decodes the JWT using SECRET_KEY, verifies the signature and expiry,
    # then sets request.user to the token's subject user automatically.
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),

    # All views require authentication by default.
    # Public endpoints (register, login) explicitly override with AllowAny.
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),

    # Pagination wraps list responses: { count, next, previous, results[] }
    # Frontend handles both formats: const list = data.results ?? data
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}


# ── JWT SETTINGS ──────────────────────────────────────────────────────────────
# simplejwt issues two tokens on login:
#   access  — short-lived (2h), sent with every API request in Authorization header
#   refresh — long-lived (7d), only sent to /auth/refresh/ to renew the access token
#
# ROTATE_REFRESH_TOKENS=True issues a new refresh token each time one is consumed.
# This "sliding session" pattern keeps active users logged in indefinitely while
# still expiring inactive sessions after 7 days.

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':    timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME':   timedelta(days=7),
    'ROTATE_REFRESH_TOKENS':    True,
    'BLACKLIST_AFTER_ROTATION': False,  # set True if you add the blacklist app
}


# ── CORS (Cross-Origin Resource Sharing) ─────────────────────────────────────
#
# Why CORS is needed:
#   React runs on localhost:5173, Django on localhost:8000.
#   Browsers enforce the Same-Origin Policy and block cross-origin requests
#   unless the server explicitly allows them via CORS response headers.
#
# How it works (simplified):
#   1. Browser sends preflight OPTIONS request with Origin: http://localhost:5173
#   2. CorsMiddleware checks if the origin is in CORS_ALLOWED_ORIGINS
#   3. If allowed, adds Access-Control-Allow-Origin header to the response
#   4. Browser sees the header and allows the actual POST/GET/etc. to proceed
#
# In production: add your Vercel URL to CORS_ALLOWED_ORIGINS in .env
# e.g. CORS_ALLOWED_ORIGINS=https://taskaai.vercel.app

CORS_ALLOWED_ORIGINS = os.environ.get(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:5173,http://localhost:3000'
).split(',')

# Allow credentials (cookies) cross-origin — required for the admin panel
# to work correctly when accessed from a browser at a different port.
CORS_ALLOW_CREDENTIALS = True


# ── CSRF TRUSTED ORIGINS ──────────────────────────────────────────────────────
#
# Root cause of the signup "CSRF Failed: Origin checking failed" error:
#
#   Django 4.0+ added CSRF_TRUSTED_ORIGINS as an additional CSRF check.
#   Even though DRF's JWT views are CSRF-exempt for authenticated requests,
#   the /auth/register/ endpoint uses permission_classes=[AllowAny].
#   When AllowAny bypasses authentication, DRF falls back to session auth,
#   which re-enables CSRF checking — triggering this error.
#
# Fix: list all frontend origins here so Django trusts their CSRF tokens.
#
# The @csrf_exempt decorator on RegisterView in views.py is the belt-and-
# suspenders fix — it explicitly disables CSRF for that one endpoint since
# registration is a public endpoint that doesn't need CSRF protection
# (there's no authenticated session to protect against cross-site forgery).
#
# In production add: CSRF_TRUSTED_ORIGINS=https://taskaai.vercel.app

CSRF_TRUSTED_ORIGINS = os.environ.get(
    'CSRF_TRUSTED_ORIGINS',
    'http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173'
).split(',')


# ── OPENAI ────────────────────────────────────────────────────────────────────
# Used by AISuggestView in tasks/views.py to call GPT-4o-mini.
# If empty, the view automatically falls back to rule-based keyword matching —
# no crash, the app still works without an API key.

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')



# ── STATIC FILES ──────────────────────────────────────────────────────────────
# In development: Django serves static files automatically via runserver.
# In production: run `python manage.py collectstatic` to copy all static files
# from each app's /static/ folder into STATIC_ROOT, then serve via nginx/WhiteNoise.

STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


# ── MISCELLANEOUS ─────────────────────────────────────────────────────────────

# BigAutoField uses 64-bit integers for PKs — prevents ID exhaustion on large tables.
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'UTC'
USE_I18N      = True
USE_TZ        = True   # stores all datetimes as UTC in the DB


# ── PASSWORD VALIDATION ───────────────────────────────────────────────────────
# Applied during user creation (register) and password change.
# Validators run in order — all must pass.

AUTH_PASSWORD_VALIDATORS = [
    # Rejects passwords too similar to username or email
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    # Rejects passwords shorter than 8 characters
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    # Rejects from the 20,000-entry common password list
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    # Rejects entirely numeric passwords (e.g. "12345678")
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
