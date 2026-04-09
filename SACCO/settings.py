from pathlib import Path
import os
import dj_database_url  # Optional but recommended
import environ
BASE_DIR = Path(__file__).resolve().parent.parent


# Initialize environ
env = environ.Env()
# Read the .env file
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# Now replace your hardcoded key with this:
BREVO_API_KEY = env('BREVO_API_KEY')

# You can also use it for your Django Secret Key
SECRET_KEY = env('SECRET_KEY')
DEBUG = env.bool('DEBUG', default=False)
ALLOWED_HOSTS = ['*']  # or set your Render URL

# --------------------------
# APPLICATIONS
# --------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'Users',
    'home',
    'crispy_forms',
    'crispy_bootstrap5',
    'django_bootstrap5',
    'mathfilters',
]

# --------------------------
# MIDDLEWARE
# --------------------------
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # must come right after SecurityMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# --------------------------
# URLS & WSGI
# --------------------------
ROOT_URLCONF = 'SACCO.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],  # optional: custom templates
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'SACCO.wsgi.application'

# --------------------------
# DATABASE
# --------------------------
DATABASES = {
    'default': dj_database_url.config(
        default='postgresql://eldoret_user:mRntB6itarrj0Jj8ay4CRj2pEkRb4TQj@dpg-d7b9fcmdqaus73d60mj0-a.oregon-postgres.render.com/eldoret',
        conn_max_age=600,
        ssl_require=True
    )
}

# --------------------------
# AUTH
# --------------------------
AUTH_USER_MODEL = 'Users.CustomUser'
AUTHENTICATION_BACKENDS = [
    "Users.EmailBackend.EmailBackend",  # custom email backend
    "django.contrib.auth.backends.ModelBackend",  # fallback
]
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'member_dashboard'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

# --------------------------
# INTERNATIONALIZATION
# --------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# --------------------------
# STATIC FILES
# --------------------------
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')  # where collectstatic will copy files
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]  # local development files
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# --------------------------
# MEDIA FILES (optional if you have uploads)
# --------------------------
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# --------------------------
# EXTERNAL SERVICES (MPESA)
# --------------------------
MPESA_CONSUMER_KEY = os.environ.get('MPESA_CONSUMER_KEY', 'zGwNsbORIOzKwqA2P3sgr0ArDopPQotM1iyyRhjGmdGj7n4T')
MPESA_CONSUMER_SECRET = os.environ.get('MPESA_CONSUMER_SECRET', 'EMjOYhpEjagIsSvwa5Yucq68e7hGL9yAvWRvZqqLJQ9uS1E5a0ufLD73vkV8ALtg')
MPESA_SHORTCODE = '174379'
MPESA_PASSKEY = os.environ.get('MPESA_PASSKEY', 'bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919')

# --------------------------
# DEFAULT PK
# --------------------------
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'