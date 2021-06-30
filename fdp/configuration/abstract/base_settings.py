"""

Please DO NOT modify!

This file is imported and provides definitions for all settings files.

"""

from .constants import CONST_AXES_AUTH_BACKEND, CONST_DJANGO_AUTH_BACKEND, CONST_MAX_ATTACHMENT_FILE_BYTES, \
    CONST_SUPPORTED_ATTACHMENT_FILE_TYPES, CONST_MAX_PERSON_PHOTO_FILE_BYTES, CONST_SUPPORTED_PERSON_PHOTO_FILE_TYPES
from django.urls import reverse_lazy
from django.core.exceptions import ImproperlyConfigured
from pathlib import Path
from importlib.util import find_spec, module_from_spec
import os


# Build paths inside the project like this: BASE_DIR / 'subdir'.
# resolve() .parent (fdp) .parent (fdp) .parent (configuration) .parent (abstract)
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
# .parent (root with conf)
ONE_UP_BASE_DIR = BASE_DIR.parent
CONF_DIR = ONE_UP_BASE_DIR / 'conf'


# Name of environment variable for Django secret key.
ENV_VAR_FOR_FDP_SECRET_KEY = 'FDP_SECRET_KEY'
# Name of environment variable for database name.
ENV_VAR_FOR_FDP_DATABASE_NAME = 'FDP_DATABASE_NAME'
# Name of environment variable for database user.
ENV_VAR_FOR_FDP_DATABASE_USER = 'FDP_DATABASE_USER'
# Name of environment variable for database password.
ENV_VAR_FOR_FDP_DATABASE_PASSWORD = 'FDP_DATABASE_PASSWORD'
# Name of environment variable for database host.
ENV_VAR_FOR_FDP_DATABASE_HOST = 'FDP_DATABASE_HOST'
# Name of environment variable for database port.
ENV_VAR_FOR_FDP_DATABASE_PORT = 'FDP_DATABASE_PORT'
# Name of environment variable for key used in querystring encryption.
ENV_VAR_FOR_FDP_QUERYSTRING_PASSWORD = 'FDP_QUERYSTRING_PASSWORD'
# Name of environment variable for private key used by reCAPTCHA.
ENV_VAR_FOR_FDP_RECAPTCHA_PRIVATE_KEY = 'FDP_RECAPTCHA_PRIVATE_KEY'
# Name of environment variable for user name to authenticate sending emails.
ENV_VAR_FOR_FDP_EMAIL_HOST_USER = 'FDP_EMAIL_HOST_USER'
# Name of environment variable for password to authenticate sending emails.
ENV_VAR_FOR_FDP_EMAIL_HOST_PASSWORD = 'FDP_EMAIL_HOST_PASSWORD'


# Value indicating that external authentication is supported through Microsoft Azure Active Directory
AAD_EXT_AUTH = 'aad'
# Value indicating that no external authentication is supported, i.e. only Django's authentication backend is used
NO_EXT_AUTH = 'none'


# Default is no external authentication mechanism
EXT_AUTH = NO_EXT_AUTH


# By default, FDP is configured to support user authentication through the default Django backend and optionally through
# Azure Active Directory. This setting may be overwritten if the azure_backend_only_settings.py file is imported into
# the main settings.py file, to enforce user authentication only through Azure Active Directory.
USE_ONLY_AZURE_AUTH = False


def get_from_environment_var(environment_var, raise_exception, default_val=None):
    """ Retrieves the value of an environment variable that may be used to configure the system.

    :param environment_var: Name of environment variable whose value to retrieve.
    :param raise_exception: True if exception should be raised if the environment variable does not exist, false if
    method should return None. If True, then default_val will be ignored.
    :param default_val: Default value to return if environment variable does not exist, and raise_exception is False.
    :return: Value of environment variable or the default_val if it is specified; otherwise None.
    """
    # if environment variable is not defined AND exception is desired
    if raise_exception and environment_var not in os.environ:
        raise ImproperlyConfigured('Environment variable {e} was expected but not found.'.format(e=environment_var))
    # environment variable is defined OR exception was not desired
    return os.environ.get(environment_var, default_val)


def get_from_conf_file(conf_file, raise_exception):
    """ Retrieves the contents of a .conf file that may be used to configure the system.

    :param conf_file: Name of .conf file including the file extension, e.g. myfile.conf.
    :param raise_exception: True if exception should be raised if the .conf file does not exist, false if method should
    return None.
    :return: Contents of the .conf file, or None if raise_exception=False and .conf file does not exist.
    """
    # all .conf files MUST end with the extension .conf
    str_conf_file = str(conf_file).strip()
    if not str_conf_file.endswith('.conf'):
        raise ImproperlyConfigured('Configuration file {c} must end with .conf extension.'.format(c=str_conf_file))
    # full configuration file path
    conf_file_path = CONF_DIR / conf_file
    # if .conf file does not exist
    if not conf_file_path.exists():
        # if exception is desired when .conf file does not exist
        if raise_exception:
            raise ImproperlyConfigured('Configuration file {c} was expected but not found.'.format(c=conf_file_path))
        # if exception is not desired when .conf file does not exist
        else:
            return None
    # .conf file exists
    else:
        with open(conf_file_path) as opened_conf_file:
            conf_file_contents = opened_conf_file.read().strip()
        return conf_file_contents


def get_from_environment_var_or_conf_file(environment_var, conf_file, default_val):
    """ Attempts to retrieve the contents of an environment variable, and if it does not exist, then attempts to
    retrieve the contents of a .conf file.

    :param environment_var: Name of environment variable whose value to retrieve.
    :param conf_file: Name of .conf file including the file extension, e.g. myfile.conf.
    :param default_val: Default value to use if neither the environment variable, nor the .conf file exist.
    :return: Value retrieved from environment variable or .conf file, or the default value.
    """
    # try the environment variable first
    val_to_get = get_from_environment_var(environment_var=environment_var, raise_exception=False, default_val=None)
    # environment variable was not defined or empty
    if not val_to_get:
        # try the .conf file second
        val_to_get = get_from_conf_file(conf_file=conf_file, raise_exception=False)
        # .conf file did not exist or was empty
        if not val_to_get:
            # use the default value
            val_to_get = default_val
    return val_to_get


def load_python_package_module(module_as_str, err_msg, raise_exception):
    """ Dynamically loads a module for a Python package.

    :param module_as_str: Fully qualified module as a string, e.g. my_package.my_module.
    :param err_msg: Exception message if module is not available.
    :param raise_exception: True if an exception should be raised if the module cannot be loaded, False if None should
    be returned.
    :return: Loaded module, or None if raise_exception is False and the module cannot be loaded.
    """
    dot = '.'
    # module_as_str = first_module.second_module.third_module...
    if dot in module_as_str:
        # split_modules = [first_module, second_module, third_module, ...]
        split_modules = module_as_str.split(dot)
        recombined_modules = ''
        for split_module in split_modules[:-1]:
            # recombined_modules = first_module
            # recombined_modules = first_module.second_module
            # recombined_modules = first_module.second_module.third_module
            recombined_modules = split_module if not recombined_modules \
                else '{r}.{s}'.format(r=recombined_modules, s=split_module)
            # check for partial module specification
            spec_for_recombined_modules = find_spec(recombined_modules)
            # some parent package for request module is not installed
            if not spec_for_recombined_modules:
                # exception should be raised
                if raise_exception:
                    raise Exception(err_msg)
                # fail silently
                else:
                    return None
    # check for full module specification
    spec_for_module = find_spec(module_as_str)
    # package for requested module is not installed
    if not spec_for_module:
        # exception should be raised
        if raise_exception:
            raise Exception(err_msg)
        # fail silently
        else:
            return None
    # load module in the package
    module = module_from_spec(spec_for_module)
    # initialize module
    spec_for_module.loader.exec_module(module)
    return module


# Administrator for site
ADMINS = []


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Django Two-Factor Authentication: https://django-two-factor-auth.readthedocs.io/en/stable/
    'django_otp',
    'django_otp.plugins.otp_static',
    'django_otp.plugins.otp_totp',
    'two_factor',
    # Django Compressor: https://django-compressor.readthedocs.io/en/latest/
    'compressor',
    # Django Axes: https://django-axes.readthedocs.io/en/latest/
    'axes',
    # Django Reversion: https://django-reversion.readthedocs.io/en/stable/
    'reversion',
    # Django Content Security Policy Reports: https://github.com/adamalton/django-csp-reports
    'cspreports',
    # Django reCAPTCHA: https://github.com/praekelt/django-recaptcha
    'captcha',
    # Django Data Wizard: https://github.com/wq/django-data-wizard
    'data_wizard',
    'data_wizard.sources',
    # abstract base classes attributes and functionality reused throughout project
    'inheritable',
    # extends standard Django authentication and user roles to customize project
    'fdpuser',
    # data model organizing lookup data such as categories for relationships, etc.
    'supporting',
    # data model organizing core data such as Persons, Incidents, Groupings, etc.
    'core',
    # data model organizing attachments and content for incidents such as lawsuits, social media posts, etc.
    'sourcing',
    # data model organizing bulk data imports and uploads, such as data migrations
    'bulk',
    # allows users to change data through guided data entry wizards
    'changing',
    # allows users to search for and retrieve officer profiles
    'profiles',
    # data model organizing user verification of data
    'verifying',
]


# Will be used in Django's standard MIDDLEWARE setting
# MIDDLEWARE = FIRST_MIDDLEWARE + OTP_MIDDLEWARE + LAST_MIDDLEWARE
FIRST_MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Django-CSP: https://django-csp.readthedocs.io/en/latest/
    'csp.middleware.CSPMiddleware',
]
OTP_MIDDLEWARE = [
    # Django Two-Factor Authentication: https://django-two-factor-auth.readthedocs.io/en/stable/
    'django_otp.middleware.OTPMiddleware',
]
LAST_MIDDLEWARE = [
    # Django Axes: https://django-axes.readthedocs.io/en/latest/
    'axes.middleware.AxesMiddleware',
]
MIDDLEWARE = FIRST_MIDDLEWARE + OTP_MIDDLEWARE + LAST_MIDDLEWARE

ROOT_URLCONF = 'fdp.urls'

# Will be used in Django's standard TEMPLATES setting
# TEMPLATES = [...{...'OPTIONS': {'context_processors': TEMPLATE_CONTEXT_PROCESSORS}...]
TEMPLATE_CONTEXT_PROCESSORS = [
    'django.template.context_processors.debug',
    'django.template.context_processors.request',
    'django.contrib.auth.context_processors.auth',
    'django.contrib.messages.context_processors.messages'
]
# Defines a part of the dictionary that is the first item in the Django's standard TEMPLATES setting list
# TEMPLATE_FIRST_DICT['OPTIONS'] = {'context_processors': TEMPLATE_CONTEXT_PROCESSORS}
# TEMPLATES = [TEMPLATE_FIRST_DICT]
TEMPLATE_FIRST_DICT = {
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [
        BASE_DIR,
        BASE_DIR / 'templates',
    ],
    'APP_DIRS': True,
}

WSGI_APPLICATION = 'fdp.wsgi.application'


# Database
# https://docs.djangoproject.com/en/3.1/ref/settings/#databases
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3'
    }
}


# Custom User: https://docs.djangoproject.com/en/3.1/topics/auth/customizing/#substituting-a-custom-user-model
# Simplified user model where email as username
AUTH_USER_MODEL = 'fdpuser.FdpUser'
# URL where requests are redirected after login when the contrib.auth.login view gets no next parameter
LOGIN_REDIRECT_URL = '/'
# Disabled for Django Two-Factor Authentication (see below)
# URL where requests are redirected for login, especially when using the login_required() decorator
# LOGIN_URL = '/admin/login'
# URL where requests are redirected after a user logs out using LogoutView (if view does not get a next_page argument)
LOGOUT_REDIRECT_URL = '/'


# Password validation
# https://docs.djangoproject.com/en/3.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 12,
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/3.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

# Disable translation system
USE_I18N = False

USE_L10N = False

USE_TZ = True

DATE_FORMAT = 'm/d/Y'

SHORT_DATE_FORMAT = 'm/d/Y'


# This setting defines the additional locations the staticfiles app will traverse if the FileSystemFinder finder
# is enabled, e.g. if you use the collectstatic or findstatic management command or use the static file serving
# view.
# This should be set to a list of strings that contain full paths to your additional files directory(ies).
# Default: [] (Empty list)
STATICFILES_DIRS = (BASE_DIR / 'static',)


# backend static file finders
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    # Django-Compressor https://django-compressor.readthedocs.io/en/latest/
    'compressor.finders.CompressorFinder'
]


# Protection against Denial-of-service (DoS) Attacks
# Maximum size in bytes of request body
DATA_UPLOAD_MAX_MEMORY_SIZE = 2621440
# Maximum number of parameters in GET and POST requests
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000


# Set X-XSS-Protection: 1; mode=block header on all responses
# See https://docs.djangoproject.com/en/3.1/ref/middleware/#x-xss-protection
SECURE_BROWSER_XSS_FILTER = True
# Set X-Content-Type-Options: nosniff header on all responses
# https://docs.djangoproject.com/en/3.1/ref/middleware/#x-content-type-options
SECURE_CONTENT_TYPE_NOSNIFF = True


# Number of seconds for which password reset link is valid
# 259200 seconds is 3 days
# 86400 seconds is 1 day
PASSWORD_RESET_TIMEOUT = 86400


# Number of seconds after which session cookie expires
# 1200 = 20 minutes
# 3600 = 60 minutes
SESSION_COOKIE_AGE = 3600
# Update session with each request so that cookie age is renewed
SESSION_SAVE_EVERY_REQUEST = True
# Secure session cookies can be HTTPS only
SESSION_COOKIE_SECURE = True
# Force session to expire when closing browser
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Secure CSRF cookies can be HTTPS only
CSRF_COOKIE_SECURE = True

# Always redirect to HTTPS
SECURE_SSL_REDIRECT = True

# Http Strict Transport Security instructs browser to refuse unsecured HTTP connections (only HTTPS allowed)
# 86400 = 1 day
# 10368000 = 120 days
# 31536000 = 1 year
# Set HSTS header for x seconds
SECURE_HSTS_SECONDS = 31536000
# Add includeSubDomains directive to HSTS header
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# Disallow serving parts of site within frames to itself
# https://docs.djangoproject.com/en/3.1/ref/clickjacking/#setting-x-frame-options-for-all-responses
X_FRAME_OPTIONS = 'DENY'


# Custom global defaults
# Prefix used in the database to identify FDP tables
DB_PREFIX = 'fdp_'
# Maximum number of character for name fields in the database
MAX_NAME_LEN = 254
# Django Site Header
SITE_HEADER = 'Full Disclosure Project'
# Standardized text value representing something "unknown" or "not defined" in the database
UNKNOWN = 'Unknown'


# List of apps that have models in the admin interface
# Used in fdpuser.models.FdpUser.has_perm()
APPS_IN_ADMIN = ['fdpuser', 'changing', 'core', 'sourcing', 'supporting', 'verifying']


# Explicitly define local-memory caching as default,
# and then add workaround for Django Axes (https://django-axes.readthedocs.io/en/latest/)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    },
    'axes_cache': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}


# Settings for Django-Compressor
# http://django-compressor.readthedocs.io/en/latest
COMPRESS_CSS_FILTERS = [
    'compressor.filters.cssmin.rCSSMinFilter',
    'compressor.filters.template.TemplateFilter',
    'compressor.filters.css_default.CssAbsoluteFilter'
]
COMPRESS_JS_FILTERS = [
    'compressor.filters.jsmin.JSMinFilter',
    'compressor.filters.template.TemplateFilter'
]


# Django Axes: https://django-axes.readthedocs.io/en/latest/
# Connect with workaround DummyCache because of issue with local-memory caching used as default
AXES_CACHE = 'axes_cache'
# Number of login attempts before record is created for failed login
AXES_FAILURE_LIMIT = 3
# Number of hours of user inactivity after which old failed logins are forgotten
AXES_COOLOFF_TIME = 48
# Prevents the login from IP under a particular user if the attempt limit has been exceeded
AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP = True
# The names of request.META attributes as a tuple of strings to check to get the client IP address
# See: https://django-axes.readthedocs.io/en/latest/4_configuration.html#configuring-reverse-proxies
AXES_META_PRECEDENCE_ORDER = [
    # For Heroku, see: https://devcenter.heroku.com/articles/http-routing#heroku-headers
    'HTTP_X_FORWARDED_FOR',
    'REMOTE_ADDR',
    # For Python Anywhere, see: http://help.pythonanywhere.com/pages/WebAppClientIPAddresses/
    'HTTP_X_REAL_IP'
]


# Django-CSP: https://django-csp.readthedocs.io/en/latest/
# Prevents fetching and executing plugin resources embedded using <object>, <embed> or <applet> tags.
CSP_OBJECT_SRC = ("'none'",)
# The nonce directive means that <script> elements will be allowed to execute only if they contain a nonce attribute
# matching the randomly-generated value which appears in the policy. In the presence of a CSP nonce the unsafe-inline
# directive will be ignored by modern browsers. Older browsers, which don't support nonces, will see unsafe-inline and
# allow inline scripts to execute.
# script-src 'strict-dynamic' https: http: 'strict-dynamic' allows the execution of scripts dynamically added to the
# page, as long as they were loaded by a safe, already-trusted script. In the presence of 'strict-dynamic'
# the https: and http: whitelist entries will be ignored by modern browsers. Older browsers will allow the loading of
# scripts from any URL.
CSP_SCRIPT_SRC = (
    "'unsafe-inline'",
    "'self'",
    'https://cdnjs.cloudflare.com/ajax/libs/slick-carousel/',
    'https://ajax.googleapis.com/ajax/libs/jquery/',
    'https://ajax.googleapis.com/ajax/libs/jqueryui/',
    'https://cdnjs.cloudflare.com/ajax/libs/vex-js/',
    'https://cdnjs.cloudflare.com/ajax/libs/select2/',
)
# Disables <base> URIs, preventing attackers from changing the locations of scripts loaded from relative URLs. If
# your application uses <base> tags, base-uri 'self' is usually also safe.
CSP_BASE_URI = ("'none'",)
# Defines valid sources for embedding the resource using <frame> <iframe> <object> <embed> <applet>.
# Setting this directive to 'none' should be roughly equivalent to X-Frame-Options: DENY
CSP_FRAME_ANCESTORS = ("'none'",)
# The default-src is the default policy for loading content such as JavaScript, Images, CSS, Fonts, AJAX requests,
# Frames, HTML5 Media.
CSP_DEFAULT_SRC = (
    "'unsafe-inline'",
    "'self'",
    'https://cdnjs.cloudflare.com/ajax/libs/slick-carousel/',
    'https://ajax.googleapis.com/ajax/libs/jqueryui/',
    'https://cdnjs.cloudflare.com/ajax/libs/vex-js/',
    'https://cdnjs.cloudflare.com/ajax/libs/select2/',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/',
    "'self' data:",
)
# Defines valid sources that can be used as a HTML <form> action.
CSP_FORM_ACTION = ("'self'",)
# The font-src directive restricts the URLs from which font resources may be loaded.
CSP_FONT_SRC = (
    "'self'",
    'https://cdnjs.cloudflare.com/ajax/libs/slick-carousel/',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/',
)
# Causes all violations to the policy to be reported to the supplied URL
# so you can debug them.
CSP_REPORT_URI = reverse_lazy('report_csp')


# Django Content Security Policy Reports: https://github.com/adamalton/django-csp-reports
# True to email administrators, false otherwise
CSP_REPORTS_EMAIL_ADMINS = False
# True to log violations, false otherwise
CSP_REPORTS_LOG = False
# Specifies log function available in Python logging module, e.g. 'warning'
CSP_REPORTS_LOG_LEVEL = 'warning'
# True to save reports to database, false otherwise.
CSP_REPORTS_SAVE = True
# Iterable dot-separated string paths to functions to be executed when a report is received.
# Each function is pass the HttpRequest of the CSP report
CSP_REPORTS_ADDITIONAL_HANDLERS = []
# Specifies logger name to be used for logging CSP reports, if enabled, e.g. 'CSP Reports'
CSP_REPORTS_LOGGER_NAME = 'CSP Reports'


# Django Two-Factor Authentication: https://django-two-factor-auth.readthedocs.io/en/stable/
# Points to login view handling password authentication followed by a one-time password exchange.
# Can be URL path or URL name as defined in the Django documentation.
LOGIN_URL = 'two_factor:login'
# Generator for QR code images. SVG does not work on IE8 and below.
TWO_FACTOR_QR_FACTORY = 'qrcode.image.svg.SvgImage'
# Number of digits to use for TOTP tokens, can be set to 6 or 8. Setting used for tokens delivered by phone call or
# text message and newly configured token generators. Existing token generator devices will not be affected.
TWO_FACTOR_TOTP_DIGITS = 6


# Settings for sending emails
# See https://docs.djangoproject.com/en/3.1/topics/email/
# Default email address to use for various automated correspondence from the site manager(s).
# This doesn’t include error messages sent to ADMINS and MANAGERS; for that, see SERVER_EMAIL.
FDP_FROM_EMAIL = get_from_environment_var_or_conf_file(
    environment_var='FDP_FROM_EMAIL', conf_file='fdp_from_email.conf', default_val='webmaster@localhost'
)
DEFAULT_FROM_EMAIL = FDP_FROM_EMAIL
# The host to use for sending email.
EMAIL_HOST = get_from_environment_var_or_conf_file(
    environment_var='FDP_EMAIL_HOST', conf_file='fdp_email_host.conf', default_val='localhost'
)
# Username to use for the SMTP server defined in EMAIL_HOST. If empty, Django won’t attempt authentication.
EMAIL_HOST_USER = get_from_environment_var_or_conf_file(
    environment_var=ENV_VAR_FOR_FDP_EMAIL_HOST_USER, conf_file='fdp_email_host_user.conf', default_val=''
)
# Password to use for the SMTP server defined in EMAIL_HOST.
# This setting is used in conjunction with EMAIL_HOST_USER when authenticating to the SMTP server.
# If either of these settings is empty, Django won’t attempt authentication.
EMAIL_HOST_PASSWORD = get_from_environment_var_or_conf_file(
    environment_var=ENV_VAR_FOR_FDP_EMAIL_HOST_PASSWORD, conf_file='fdp_em.conf', default_val=''
)
# Port to use for the SMTP server defined in EMAIL_HOST.
EMAIL_PORT = get_from_environment_var_or_conf_file(
    environment_var='FDP_EMAIL_PORT', conf_file='fdp_email_port.conf', default_val=25
)
# Whether to use a TLS (secure) connection when talking to the SMTP server.
# This is used for explicit TLS connections, generally on port 587.
# If you are experiencing hanging connections, see the implicit TLS setting EMAIL_USE_SSL.
EMAIL_USE_TLS = True
# The email address that error messages come from, such as those sent to ADMINS and MANAGERS.
SERVER_EMAIL = FDP_FROM_EMAIL
# The backend to use for sending emails.
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# Subject-line prefix for email messages sent with django.core.mail.mail_admins or django.core.mail.mail_managers.
# You’ll probably want to include the trailing space.
EMAIL_SUBJECT_PREFIX = 'FDP - '


# Settings for password resets
# Maximum number of password resets per user per 24 hours
MAX_PWD_RESET_PER_USER_PER_DAY = 3
# Maximum number of password resets per IP address per 24 hours
MAX_PWD_RESET_PER_IP_ADDRESS_PER_DAY = 10


# Keys for Google reCAPTCHA using Django-reCAPTCHA package
# See: https://github.com/praekelt/django-recaptcha
# See: https://www.google.com/recaptcha
# Public reCAPTCHA key
RECAPTCHA_PUBLIC_KEY = get_from_environment_var_or_conf_file(
    environment_var='FDP_RECAPTCHA_PUBLIC_KEY', conf_file='fdp_recaptcha_public_key.conf', default_val=''
)
# Private reCAPTCHA key
RECAPTCHA_PRIVATE_KEY = get_from_environment_var_or_conf_file(
    environment_var=ENV_VAR_FOR_FDP_RECAPTCHA_PRIVATE_KEY, conf_file='fdp_ca.conf', default_val=''
)
# Use the noCAPTCHA (checkmark only)
NOCAPTCHA = True
# Google provides test keys which are set as the default for RECAPTCHA_PUBLIC_KEY and RECAPTCHA_PRIVATE_KEY.
# These cannot be used in production since they always validate to true and a warning will be shown on the reCAPTCHA.
# To bypass the security check that prevents the test keys from being used unknowingly
# add SILENCED_SYSTEM_CHECKS = [..., 'captcha.recaptcha_test_key_error', ...] to your settings
SILENCED_SYSTEM_CHECKS = []


# A list of authentication backend classes (as strings) to use when attempting to authenticate a user.
# See: https://docs.djangoproject.com/en/3.1/ref/settings/?from=olddocs#authentication-backends
AUTHENTICATION_BACKENDS = [
    # Django Axes: https://django-axes.readthedocs.io/en/latest/
    CONST_AXES_AUTH_BACKEND,
    # Django's default database-driven authentication
    CONST_DJANGO_AUTH_BACKEND
]


# Settings for date matching
# Languages supported when matching dates during searches
# Through Django dateparser package
# See: https://dateparser.readthedocs.io/en/latest/#supported-languages-and-locales
DATE_LANGUAGES = ['en']


# Django Data Wizard: https://github.com/wq/django-data-wizard
DATA_WIZARD = {
    # Implement confidentiality filtering and corresponding automated tests in bulk upload before changing this.
    'PERMISSION': 'bulk.models.IsHostAdminUser',
    # The threading backend creates a separate thread for long-running asynchronous tasks (i.e. auto and data).
    # The threading backend leverages the Django cache to pass results back to the status API. As of Django Data
    # Wizard 1.1.0, this backend is the default unless you have configured Celery.
    'BACKEND': 'data_wizard.backends.threading',
    # Always map IDs (skip manual mapping). Unknown IDs will be passed on as-is to the serializer, which will cause
    # per-row errors unless using natural keys.
    'IDMAP': 'data_wizard.idmap.always',
}
# Set to True to disable record versioning by the Django-Reversion package when importing records through the Django
# Data Wizard package. See: https://django-reversion.readthedocs.io/en/stable/
DISABLE_REVERSION_FOR_DATA_WIZARD = True
# The number of seconds in between each asynchronous GET request to check for the status of importing records through
# the Django Data Wizard package.
DATA_WIZARD_STATUS_CHECK_SECONDS = 3


# Added in Django 3.2
# Default model field for primary keys that are added to models automatically.
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Logging may be enabled in settings.py with: LOGGING = FDP_ERR_LOGGING
# For more information on Django logging, see: https://docs.djangoproject.com/en/3.1/topics/logging/
FDP_ERR_LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'ERROR',
            'class': 'logging.FileHandler',
            'filename': '/home/site/wwwroot/debug.log',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'ERROR',
            'propagate': True,
        },
    },
}


# A URL that handles serving user-uploaded media files for some storage systems such as the Azure Storage account.
# This setting will be ignored, if the MEDIA_URL setting can be used such as in the local development environment.
# It must end in a slash if set to a non-empty value.
# See the Django setting MEDIA_URL for similarities.
FDP_MEDIA_URL = '/perm/media/'


# The maximum number of bytes that a user-uploaded file can have for an instance of the Attachment model.
FDP_MAX_ATTACHMENT_FILE_BYTES = CONST_MAX_ATTACHMENT_FILE_BYTES


# A list of tuples that define the types of user-uploaded files that are supported for an instance of the Attachment
# model. Each tuple has two items: the first is a user-friendly short description of the supported file type; the second
# is the expected extension of the supported file type.
FDP_SUPPORTED_ATTACHMENT_FILE_TYPES = CONST_SUPPORTED_ATTACHMENT_FILE_TYPES


# The maximum number of bytes that a user-uploaded file can have for an instance of the Person Photo model.
FDP_MAX_PERSON_PHOTO_FILE_BYTES = CONST_MAX_PERSON_PHOTO_FILE_BYTES


# A list of tuples that define the types of user-uploaded files that are supported for an instance of the Person Photo
# model. Each tuple has two items: the first is a user-friendly short description of the supported file type; the second
# is the expected extension of the supported file type.
FDP_SUPPORTED_PERSON_PHOTO_FILE_TYPES = CONST_SUPPORTED_PERSON_PHOTO_FILE_TYPES
