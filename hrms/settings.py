import os
from pathlib import Path
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

# ═══════════════════════════════════════════════════════════
#  BASE PATHS
# ═══════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════
#  ENVIRONMENT HELPERS
# ═══════════════════════════════════════════════════════════

def env_bool(name, default=False):
    """Read an environment variable as a boolean."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ('true', '1', 'yes', 'on')


def env_list(name, default=''):
    """Read an environment variable as a comma-separated list."""
    return [x.strip() for x in os.environ.get(name, default).split(',') if x.strip()]


# ═══════════════════════════════════════════════════════════
#  DEBUG — True locally, False in production
#  Production MUST set env var: DEBUG=False
# ═══════════════════════════════════════════════════════════

DEBUG = env_bool('DEBUG', default=True)
IS_PRODUCTION = not DEBUG


# ═══════════════════════════════════════════════════════════
#  SECRET KEY — env-var-only in production
# ═══════════════════════════════════════════════════════════

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        # Local dev fallback — never used in production (DEBUG=False raises below)
        SECRET_KEY = 'django-insecure-dev-only-key-not-for-production-use-1234567890'
    else:
        raise ImproperlyConfigured(
            "SECRET_KEY environment variable must be set in production.\n"
            "Generate one with:\n"
            "    python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )

# Safety net — refuse to boot if a dev key sneaks into production
if IS_PRODUCTION and SECRET_KEY.startswith('django-insecure'):
    raise ImproperlyConfigured(
        "FATAL: 'django-insecure' key detected in production. Generate a new one."
    )


# ═══════════════════════════════════════════════════════════
#  ALLOWED HOSTS & CSRF
# ═══════════════════════════════════════════════════════════

# Base hosts — from env var or safe local defaults
ALLOWED_HOSTS = env_list(
    'ALLOWED_HOSTS',
    '127.0.0.1,localhost'
)
if DEBUG:
    ALLOWED_HOSTS += ['0.0.0.0', '[::1]', '.localhost']

# ✅ Auto-detect Render hostname (Render sets this automatically)
render_hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)

# ✅ Always allow the production Render URL (safety net)
RENDER_PRODUCTION_HOST = 'hrms-1udd.onrender.com'
if RENDER_PRODUCTION_HOST not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_PRODUCTION_HOST)

# CSRF Trusted Origins — from env var or empty
CSRF_TRUSTED_ORIGINS = env_list(
    'CSRF_TRUSTED_ORIGINS',
    ''
)

# ✅ Auto-add Render origin for CSRF (from env var or fallback)
if render_hostname:
    render_origin = f'https://{render_hostname}'
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)

RENDER_PRODUCTION_ORIGIN = f'https://{RENDER_PRODUCTION_HOST}'
if RENDER_PRODUCTION_ORIGIN not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(RENDER_PRODUCTION_ORIGIN)
    


# ═══════════════════════════════════════════════════════════
#  LOGGING — console locally, console in prod (files don't survive ephemeral FS)
# ═══════════════════════════════════════════════════════════

LOG_DIR = BASE_DIR / 'logs'
if not IS_PRODUCTION:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

_handlers = ['console'] if IS_PRODUCTION else ['console', 'file']

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'level': 'ERROR',
            'class': 'logging.FileHandler',
            'filename': str(LOG_DIR / 'error.log'),
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': _handlers,
        'level': 'WARNING',
    },
    'loggers': {
        'django':  {'handlers': _handlers, 'level': 'ERROR', 'propagate': False},
        'core':    {'handlers': _handlers, 'level': 'ERROR', 'propagate': False},
    },
}


# ═══════════════════════════════════════════════════════════
#  APPLICATIONS
# ═══════════════════════════════════════════════════════════

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]


# ═══════════════════════════════════════════════════════════
#  MIDDLEWARE
# ═══════════════════════════════════════════════════════════

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.CompanyMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# ═══════════════════════════════════════════════════════════
#  TEMPLATES
# ═══════════════════════════════════════════════════════════

ROOT_URLCONF = 'hrms.urls'

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
                'core.context_processors.notification_context',
                'core.context_processors.company_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'hrms.wsgi.application'


# ═══════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════

DATABASES = {
    'default': dj_database_url.config(
        default='sqlite:///db.sqlite3',
        conn_max_age=600,
        ssl_require=IS_PRODUCTION,   # SSL only in prod
    )
}


# ═══════════════════════════════════════════════════════════
#  PASSWORD VALIDATION
# ═══════════════════════════════════════════════════════════

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ═══════════════════════════════════════════════════════════
#  INTERNATIONALIZATION
# ═══════════════════════════════════════════════════════════

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

TIME_FORMAT = 'h:i:s A'
DATE_FORMAT = 'd M Y'
DATETIME_FORMAT = 'd M Y h:i:s A'


# ═══════════════════════════════════════════════════════════
#  STATIC FILES
# ═══════════════════════════════════════════════════════════

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# ═══════════════════════════════════════════════════════════
#  DEFAULT PRIMARY KEY
# ═══════════════════════════════════════════════════════════

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ═══════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'


# ═══════════════════════════════════════════════════════════
#  SECURITY HEADERS
# ═══════════════════════════════════════════════════════════

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True   # No-op on modern browsers, harmless
X_FRAME_OPTIONS = 'DENY'

# HTTPS enforcement
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', default=IS_PRODUCTION)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HSTS — tells browsers to only use HTTPS for 1 year
SECURE_HSTS_SECONDS = 31536000 if IS_PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = IS_PRODUCTION
SECURE_HSTS_PRELOAD = IS_PRODUCTION


# ═══════════════════════════════════════════════════════════
#  SESSION SECURITY
# ═══════════════════════════════════════════════════════════

SESSION_COOKIE_SECURE = IS_PRODUCTION   # HTTPS-only cookie in prod
SESSION_COOKIE_HTTPONLY = True          # JS cannot read
SESSION_COOKIE_SAMESITE = 'Lax'         # CSRF defense
SESSION_EXPIRE_AT_BROWSER_CLOSE = False # Keep session for busy HR users
SESSION_COOKIE_AGE = 3600 * 8           # 8 hours (was 1 hour — too short for daily HR work)


# ═══════════════════════════════════════════════════════════
#  CSRF SECURITY
# ═══════════════════════════════════════════════════════════

CSRF_COOKIE_SECURE = IS_PRODUCTION   # HTTPS-only in prod
CSRF_COOKIE_HTTPONLY = False         # MUST be False — template JS needs to read CSRF token for AJAX
CSRF_COOKIE_SAMESITE = 'Lax'


# ═══════════════════════════════════════════════════════════
#  APPLICATION ROLES
# ═══════════════════════════════════════════════════════════

ADMIN_ROLES = [
    'HR Admin',
    'Manager',
    'Supervisor',
    'Team Lead',
    'Operations',
]

# ═══════════════════════════════════════════════════════════
#  MEDIA FILES (user uploads: profile pics, attachments)
# ═══════════════════════════════════════════════════════════

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Ensure directory exists
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════
#  FILE UPLOAD LIMITS (DoS prevention)
# ═══════════════════════════════════════════════════════════

# Files above this stream to disk (default: 2.5 MB)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024        # 5 MB

# Max POST body size (non-file form data)
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024       # 10 MB

# Max number of fields in a POST (form field flood prevention)
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# Allowed image extensions (used by validators below)
ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']
MAX_IMAGE_SIZE_MB = 2

# Allowed attachment extensions
ALLOWED_ATTACHMENT_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx']
MAX_ATTACHMENT_SIZE_MB = 5

