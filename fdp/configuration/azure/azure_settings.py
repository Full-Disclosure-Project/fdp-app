"""

Please DO NOT modify!

This file is imported and provides definitions for the main settings.py file.

Make any customizations in the main settings.py file.

Used to define default settings file to configure hosting in a Microsoft Azure environment.

"""
from fdp.configuration.abstract.constants import CONST_AZURE_AUTH_BACKEND, CONST_AZURE_OTP_MIDDLEWARE, \
    CONST_AZURE_AUTH_APP, CONST_AZURE_TEMPLATE_CONTEXT_PROCESSORS
from fdp.configuration.abstract.base_settings import *
from django.core.management.utils import get_random_secret_key
from base64 import b64encode
from os import urandom


# Specifies that FDP is configured for hosting in Microsoft Azure environment
USE_AZURE_SETTINGS = True


# Name of environment variable for Azure Storage account access key.
ENV_VAR_FOR_FDP_AZURE_STORAGE_ACCOUNT_KEY = 'FDP_AZURE_STORAGE_ACCOUNT_KEY'
# Name of environment variable for Azure Active Directory client ID
ENV_VAR_FOR_FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY = 'FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY'
# Name of environment variable for Azure Active Directory tenant ID
ENV_VAR_FOR_FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID = 'FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID'
# Name of environment variable for Azure Active Directory client secret
ENV_VAR_FOR_FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET = 'FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET'


class AzureKeyVaultException(Exception):
    """ Custom class used by the FDP to raise its own exceptions in the context of accessing and interacting with the
    Azure Key Vault.

    """
    pass


# default is to ignore Azure Key Vault, unless package is installed and vault name is specified
TRY_AZURE_KEY_VAULT = False
secret_client = None
# load if azure-keyvault-secrets package is installed
# see: https://github.com/Azure/azure-sdk-for-python/tree/master/sdk/keyvault/azure-keyvault-secrets
azure_keyvault_secrets_module = load_python_package_module(
    module_as_str='azure.keyvault.secrets',
    err_msg=None,
    raise_exception=False
)
if azure_keyvault_secrets_module:
    # Name of the Azure Key Vault
    AZURE_KEY_VAULT_NAME = get_from_environment_var(
        environment_var='FDP_AZURE_KEY_VAULT_NAME', raise_exception=False, default_val=None
    )
    # Only try Azure Key Vault is package is installed AND vault name is specified
    TRY_AZURE_KEY_VAULT = False if not AZURE_KEY_VAULT_NAME else True
    if TRY_AZURE_KEY_VAULT:
        # load if azure-identity package is installed
        # see: https://github.com/Azure/azure-sdk-for-python/tree/master/sdk/identity/azure-identity
        azure_identity_module = load_python_package_module(
            module_as_str='azure.identity',
            err_msg='Please install the package: azure-identity',
            raise_exception=True
        )
        credential = azure_identity_module.ManagedIdentityCredential()
        secret_client = azure_keyvault_secrets_module.SecretClient(
            vault_url='https://{v}.vault.azure.net'.format(v=AZURE_KEY_VAULT_NAME),
            credential=credential
        )


def get_from_azure_key_vault(secret_name):
    """ Attempts to retrieve the contents of a Secret in the Azure Key Vault, and if it does not exist returns None.

    :param secret_name: Name of Secret in Azure Key Vault that should be retrieved.
    :return: The value stored in the Secret in the Azure Key Vault, or None otherwise.
    """
    secret = None
    # skip access attempt for Azure Key Vault, if vault name wasn't specified or corresponding package wasn't installed
    if TRY_AZURE_KEY_VAULT:
        # Secret names cannot have underscores
        parsed_secret_name = str(secret_name).replace('_', '-')
        try:
            azure_key_vault_secret = secret_client.get_secret(parsed_secret_name)
            secret = azure_key_vault_secret.value
        except Exception as err:
            # modules loaded dynamically with find_spec and loader.exec_module have different class definitions than the
            # modules that define this exception, even if they are from the same source, i.e. azure.core.exceptions
            # so as a temporary measure, compare string representations of the classes instead of using isinstance(...)
            err_class = err.__class__.__name__
            # Occurs if a secret does not exist
            if err_class == 'ResourceNotFoundError':
                secret = None
            # Occurs during deployment to Azure, during the collectstatic step
            elif err_class == 'ServiceRequestError':
                raise AzureKeyVaultException(err)
            # Unexpected error
            else:
                raise err
    return secret


def get_random_querystring_password():
    """ Retrieves a randomized password that can be used to encrypt/decrypt querystrings.

    Password will be 32 bytes and be in base-64 encoding.

    :return: Randomized 32 bytes in base-64 encoding.
    """
    random_bytes = urandom(32)
    token = b64encode(random_bytes)
    return token


# External authentication mechanism.
EXT_AUTH = get_from_environment_var(
    environment_var='FDP_EXTERNAL_AUTHENTICATION', raise_exception=False, default_val=NO_EXT_AUTH
)
EXT_AUTH = str(EXT_AUTH).lower()


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.1/howto/deployment/checklist/


# SECURITY WARNING: keep the secret key used in production secret!
# if Django secret key is in Azure Key Vault, then retrieve it
# attempt to retrieve Django secret key from Azure Key Vault
try:
    SECRET_KEY = get_from_azure_key_vault(secret_name=ENV_VAR_FOR_FDP_SECRET_KEY)
# azure.core.exceptions.ServiceRequestError occurred
# raised during collectstatic command call while deploying
except AzureKeyVaultException:
    SECRET_KEY = None
    # don't try any more Azure Key Vault access
    TRY_AZURE_KEY_VAULT = False
# if Django secret key is not in Azure Key Vault, then get it from an environment variable
if not SECRET_KEY:
    SECRET_KEY = get_from_environment_var(
        environment_var=ENV_VAR_FOR_FDP_SECRET_KEY,
        raise_exception=False,
        default_val=''
    )
    # Django secret key was not in Azure Key Vault or environment variable
    # Offer randomly generated secret key so that Django can run collectstatic during deployment
    if not SECRET_KEY:
        SECRET_KEY = get_random_secret_key()


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False


DEF_FDP_HOST = get_from_environment_var(environment_var='FDP_ALLOWED_HOST', raise_exception=False, default_val=None)
if not DEF_FDP_HOST:
    # Added automatically through Kudu
    # See: https://github.com/projectkudu/kudu/wiki/Azure-runtime-environment
    DEF_FDP_HOST = get_from_environment_var(environment_var='WEBSITE_HOSTNAME', raise_exception=False, default_val=None)
localhost_ip = '127.0.0.1'
ALLOWED_HOSTS = [DEF_FDP_HOST, localhost_ip] if DEF_FDP_HOST else [localhost_ip]


# A tuple representing a HTTP header/value combination that signifies a request is secure. This controls the behavior
# of the request object’s is_secure() method. By default, is_secure() determines if a request is secure by confirming
# that a requested URL uses https://. This method is important for Django’s CSRF protection, and it may be used by your
# own code or third-party apps. If your Django app is behind a proxy, though, the proxy may be “swallowing” whether the
# original request uses HTTPS or not. If there is a non-HTTPS connection between the proxy and Django then is_secure()
# would always return False – even for requests that were made via HTTPS by the end user. In contrast, if there is an
# HTTPS connection between the proxy and Django then is_secure() would always return True – even for requests that were
# made originally via HTTP. In this situation, configure your proxy to set a custom HTTP header that tells Django
# whether the request came in via HTTPS, and set SECURE_PROXY_SSL_HEADER so that Django knows what header to look for.
# Set a tuple with two elements – the name of the header to look for and the required value.
# For example: SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# This tells Django to trust the X-Forwarded-Proto header that comes from our proxy, and any time its value is 'https',
# then the request is guaranteed to be secure (i.e., it originally came in via HTTPS).
# You should only set this setting if you control your proxy or have some other guarantee that it sets/strips this
# header appropriately. Note that the header needs to be in the format as used by request.META – all caps and likely
# starting with HTTP_. (Remember, Django automatically adds 'HTTP_' to the start of x-header  names before making the
# header available in request.META.) Default value is: None.
# See: https://docs.microsoft.com/en-us/azure/app-service/configure-language-python#detect-https-session
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# external authentication such as through Azure Active Directory is supported
if EXT_AUTH == AAD_EXT_AUTH:
    # Django Social Auth: https://python-social-auth.readthedocs.io/en/latest/configuration/django.html
    # Azure Client ID
    SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY = get_from_azure_key_vault(
        secret_name=ENV_VAR_FOR_FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY
    )
    if not SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY:
        SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY = get_from_environment_var(
            environment_var=ENV_VAR_FOR_FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY,
            raise_exception=False,
            default_val=None
        )
    # Azure Tenant ID
    SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID = get_from_azure_key_vault(
        secret_name=ENV_VAR_FOR_FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID
    )
    if not SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID:
        SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID = get_from_environment_var(
            environment_var=ENV_VAR_FOR_FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID,
            raise_exception=False,
            default_val=None
        )
    # Azure Client Secret
    SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET = get_from_azure_key_vault(
        secret_name=ENV_VAR_FOR_FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET
    )
    if not SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET:
        SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET = get_from_environment_var(
            environment_var=ENV_VAR_FOR_FDP_SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET,
            raise_exception=False,
            default_val=None
        )
    # either client or tenant ID, or secret is missing, so cannot support Azure Active Directory
    if not (
        SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY and
        SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID and
        SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET
    ):
        EXT_AUTH = NO_EXT_AUTH
    # only continue configuring support for Azure Active Directory, if the client and tenant IDs were retrieved
    else:
        # Replace Django only 2FA with both Django 2FA and Azure 2FA
        MIDDLEWARE = FIRST_MIDDLEWARE + CONST_AZURE_OTP_MIDDLEWARE + LAST_MIDDLEWARE
        INSTALLED_APPS.append(CONST_AZURE_AUTH_APP)
        TEMPLATE_CONTEXT_PROCESSORS.extend(CONST_AZURE_TEMPLATE_CONTEXT_PROCESSORS)
        CSP_FORM_ACTION = CSP_FORM_ACTION + ('https://www.office.com/', 'https://login.microsoftonline.com/',)
        # See: https://python-social-auth.readthedocs.io/en/latest/backends/azuread.html
        # Ensure that the Django default authentication backend 'django.contrib.auth.backends.ModelBackend' is before
        AUTHENTICATION_BACKENDS.append(CONST_AZURE_AUTH_BACKEND)
        # Django Social Auth: https://python-social-auth.readthedocs.io/en/latest/configuration/django.html
        # Enable JSONB field to store extracted extra data in PostgreSQL
        SOCIAL_AUTH_POSTGRES_JSONFIELD = True
        # Custom namespace for URL entries
        SOCIAL_AUTH_URL_NAMESPACE = 'social'
        # Authentication workflow is handled by an operations pipeline
        SOCIAL_AUTH_PIPELINE = (
            # Get the information we can about the user and return it in a simple
            # format to create the user instance later. On some cases the details are
            # already part of the auth response from the provider, but sometimes this
            # could hit a provider API.
            'social_core.pipeline.social_auth.social_details',
            # Get the social uid from whichever service we're authing thru. The uid is
            # the unique identifier of the given user in the provider.
            'social_core.pipeline.social_auth.social_uid',
            # Verifies that the current auth process is valid within the current
            # project, this is where emails and domains whitelists are applied (if
            # defined).
            'social_core.pipeline.social_auth.auth_allowed',
            # Checks if the current social-account is already associated in the site.
            'social_core.pipeline.social_auth.social_user',
            # Make up a username for this person, appends a random string at the end if
            # there's any collision.
            # Disabled since it is replaced by a customized method that enforces case insensitivity
            # during username comparisons.
            # 'social_core.pipeline.user.get_username',
            'fdp.pipeline.get_username',
            # Send a validation email to the user to verify its email address.
            # Disabled by default.
            # 'social_core.pipeline.mail.mail_validation',
            # Associates the current social details with another user account with
            # a similar email address. Disabled by default.
            # 'social_core.pipeline.social_auth.associate_by_email',
            # Create a user account if we haven't found one yet.
            # Disabled since it is replaced by customized method to set is_host
            # and only_external_auth properties.
            # 'social_core.pipeline.user.create_user',
            'fdp.pipeline.create_user',
            # Create the record that associates the social account with the user.
            'social_core.pipeline.social_auth.associate_user',
            # Populate the extra_data field in the social record with the values
            # specified by settings (and the default ones like access_token, etc).
            'social_core.pipeline.social_auth.load_extra_data',
            # Update the user record with any changed info from the auth service.
            'social_core.pipeline.user.user_details',
        )
        # Used to set search_fields property for Admin
        SOCIAL_AUTH_ADMIN_USER_SEARCH_FIELDS = ['email']
        # Allow the scope that is granted to the access token to be defined as default
        SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_IGNORE_DEFAULT_SCOPE = False
        # The auth process finishes with a redirect, by default it’s done to the value of SOCIAL_AUTH_LOGIN_REDIRECT_URL
        # but can be overridden with next GET argument. If this setting is True, this application will vary the domain
        # of the final URL and only redirect to it if it’s on the same domain.
        SOCIAL_AUTH_SANITIZE_REDIRECTS = True
        # On projects behind a reverse proxy that uses HTTPS, the redirect URIs can have the wrong schema
        # (http:// instead of https://) if the request lacks the appropriate headers, which might cause errors during
        # the auth process. To force HTTPS in the final URIs set this setting to True
        SOCIAL_AUTH_REDIRECT_IS_HTTPS = True
        # A list of domain names to be white-listed. Any user with an email address on any of the allowed domains will
        # login successfully, otherwise AuthForbidden is raised.
        _whitelisted_domains_str = get_from_environment_var(
            environment_var='FDP_SOCIAL_AUTH_OAUTH2_WHITELISTED_DOMAINS',
            raise_exception=True
        )
        _whitelisted_domains_list = [] if not _whitelisted_domains_str else str(_whitelisted_domains_str).split(',')
        SOCIAL_AUTH_OAUTH2_WHITELISTED_DOMAINS = [str(d).strip() for d in _whitelisted_domains_list]
        # When disconnecting an account, it is recommended to trigger a token revoke action in the authentication
        # provider,  that way we inform it that the token won’t be used anymore and can be disposed. By default the
        # action is not triggered because it’s not a common option on every provider, and tokens should be disposed
        # automatically after a short time.
        SOCIAL_AUTH_REVOKE_TOKENS_ON_DISCONNECT = True
        # De-authentication workflow is handled by an operations pipeline
        SOCIAL_AUTH_DISCONNECT_PIPELINE = (
            # Verifies that the social association can be disconnected from the current user (ensure that the user
            # login mechanism is not compromised by this disconnection).
            # Disabled since Azure Active Directory users will always receive NotAllowedToDisconnect exception.
            # 'social_core.pipeline.disconnect.allowed_to_disconnect',
            # Collects the social associations to disconnect.
            'social_core.pipeline.disconnect.get_entries',
            # Revoke any access_token when possible.
            'social_core.pipeline.disconnect.revoke_tokens',
            # Removes the social associations.
            'social_core.pipeline.disconnect.disconnect',
            # Forcibly logs out Django user
            'fdp.pipeline.logout_user',
        )


TEMPLATE_FIRST_DICT['OPTIONS'] = {'context_processors': TEMPLATE_CONTEXT_PROCESSORS}
TEMPLATES = [TEMPLATE_FIRST_DICT]


# Database
# https://docs.djangoproject.com/en/3.1/ref/settings/#databases
postgres_db_secret_user = get_from_azure_key_vault(secret_name=ENV_VAR_FOR_FDP_DATABASE_USER)
postgres_db_password = get_from_azure_key_vault(secret_name=ENV_VAR_FOR_FDP_DATABASE_PASSWORD)
DATABASES['default'] = {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': get_from_environment_var(
        environment_var=ENV_VAR_FOR_FDP_DATABASE_NAME,
        raise_exception=False,
        default_val='fdp'
    ),
    # if user name is in Azure Key Vault then retrieve it, otherwise try the environment variable
    'USER': postgres_db_secret_user if postgres_db_secret_user else get_from_environment_var(
        environment_var=ENV_VAR_FOR_FDP_DATABASE_USER,
        raise_exception=False,
        default_val=''
    ),
    # if password is in Azure Key Vault then retrieve it, otherwise try the environment variable
    'PASSWORD': postgres_db_password if postgres_db_password else get_from_environment_var(
        environment_var=ENV_VAR_FOR_FDP_DATABASE_PASSWORD,
        raise_exception=False,
        default_val=''
    ),
    'HOST': get_from_environment_var(environment_var=ENV_VAR_FOR_FDP_DATABASE_HOST, raise_exception=True),
    'PORT': get_from_environment_var(
        environment_var=ENV_VAR_FOR_FDP_DATABASE_PORT, raise_exception=False, default_val=5432
    )
}


# A URL-safe base64-encoded 32-byte key that is used by the Fernet symmetric encryption algorithm
# Used to encrypt and decrypt query string parameters
# if querystring encryption is in Azure Key Vault, then retrieve it
QUERYSTRING_PASSWORD = get_from_azure_key_vault(secret_name=ENV_VAR_FOR_FDP_QUERYSTRING_PASSWORD)
# if querystring encryption is not in Azure Key Vault, then retrieve it from environment variable
if not QUERYSTRING_PASSWORD:
    QUERYSTRING_PASSWORD = get_from_environment_var(
        environment_var=ENV_VAR_FOR_FDP_QUERYSTRING_PASSWORD,
        raise_exception=False,
        default_val=get_random_querystring_password()
    )


# Django Data Wizard: https://github.com/wq/django-data-wizard
# Loads files from Azure Storage with an iterable wrapper, so that they can be processed and imported row-by-row.
# If not set, a NotImplementedError is raised when creating a new Run.
# The exception message is: 'This backend doesn't support absolute paths.'
# Default: 'data_wizard.loaders.FileLoader'
DATA_WIZARD['LOADER'] = 'fdp.backends.base_storage.FdpDataWizardFileLoader'


#: Azure Storage for Django: https://django-storages.readthedocs.io/en/latest/backends/azure.html
# Package-wide settings
# This setting is the Windows Azure Storage Account name, which in many cases is also the first part of the url for
# instance: http://azure_account_name.blob.core.windows.net/ would mean: AZURE_ACCOUNT_NAME = "azure_account_name"
AZURE_ACCOUNT_NAME = get_from_environment_var(environment_var='FDP_AZURE_STORAGE_ACCOUNT_NAME', raise_exception=True)
# This is the private key that gives Django access to the Windows Azure Account.
# if key is in Azure Key Vault, then retrieve it
AZURE_ACCOUNT_KEY = get_from_azure_key_vault(secret_name=ENV_VAR_FOR_FDP_AZURE_STORAGE_ACCOUNT_KEY)
# if key is not in Azure Key Vault, then retrieve it from environment variable
if not AZURE_ACCOUNT_KEY:
    AZURE_ACCOUNT_KEY = get_from_environment_var(
        environment_var=ENV_VAR_FOR_FDP_AZURE_STORAGE_ACCOUNT_KEY,
        raise_exception=True
    )
# The custom domain to use. This can be set in the Azure Portal.
# For example, www.mydomain.com or mycdn.azureedge.net.
# It may contain a host:port when using the emulator (AZURE_EMULATED_MODE = True).
AZURE_STORAGE_ACCOUNT_SUFFX = get_from_environment_var(
    environment_var='FDP_AZURE_STORAGE_ACCOUNT_SUFFIX', raise_exception=False, default_val='blob.core.windows.net'
)
AZURE_CUSTOM_DOMAIN = '{a}.{s}'.format(a=AZURE_ACCOUNT_NAME, s=AZURE_STORAGE_ACCOUNT_SUFFX)
# Seconds before a URL expires, set to None to never expire it. Be aware the container must have public read
# permissions in order to access a URL without expiration date. Default is None
AZURE_URL_EXPIRATION_SECS = 20
# The file storage engine to use when collecting static files with the collectstatic management command.
# A ready-to-use instance of the storage backend defined in this setting can be found at
# django.contrib.staticfiles.storage.staticfiles_storage.
# Default: 'django.contrib.staticfiles.storage.StaticFilesStorage'
STATICFILES_STORAGE = 'fdp.backends.azure_storage.StaticAzureStorage'
# This is where the static files uploaded through Django will be uploaded.
# The container must be already created, since the storage system will not attempt to create it.
AZURE_STATIC_CONTAINER = get_from_environment_var(
    environment_var='FDP_AZURE_STATIC_CONTAINER', raise_exception=False, default_val='static'
)
# Seconds before a URL expires, set to None to never expire it. Be aware the container must have public read
# permissions in order to access a URL without expiration date. Default is None
AZURE_STATIC_URL_EXPIRATION_SECS = get_from_environment_var(
    environment_var='FDP_AZURE_STATIC_EXPIRY', raise_exception=False, default_val=None
)
# URL to use when referring to static files located in STATIC_ROOT.
# Example: "/static/" or "http://static.example.com/"
# If not None, this will be used as the base path for asset definitions (the Media class) and the staticfiles
# app. It must end in a slash if set to a non-empty value.
# Default: None
STATIC_URL = 'https://{d}/{c}/'.format(d=AZURE_CUSTOM_DOMAIN, c=AZURE_STATIC_CONTAINER)
# The absolute path to the directory where collectstatic will collect static files for deployment.
# Example: "/var/www/example.com/static/"
# If the staticfiles contrib app is enabled (as in the default project template), the collectstatic management
# command will collect static files into this directory. See the how-to on managing static files for more
# details about usage.
# Default: None
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')


# Default file storage class to be used for any file-related operations that don’t specify a particular storage
# system. See Managing files.
# Default: 'django.core.files.storage.FileSystemStorage'
DEFAULT_FILE_STORAGE = 'fdp.backends.azure_storage.MediaAzureStorage'
# This is where the media files uploaded through Django will be uploaded.
# The container must be already created, since the storage system will not attempt to create it.
AZURE_MEDIA_CONTAINER = get_from_environment_var(
    environment_var='FDP_AZURE_MEDIA_CONTAINER', raise_exception=False, default_val='media'
)
# URL that handles the media served from MEDIA_ROOT, used for managing stored files. It must end in a slash if
# set to a non-empty value. You will need to configure these files to be served in both development and
# production environments.
# If you want to use {{ MEDIA_URL }} in your templates, add 'django.template.context_processors.media' in the
# 'context_processors' option of TEMPLATES.
# Default: '' (Empty string)
MEDIA_URL = 'https://{d}/{c}/'.format(d=AZURE_CUSTOM_DOMAIN, c=AZURE_MEDIA_CONTAINER)
# Seconds before a URL expires, set to None to never expire it. Be aware the container must have public read
# permissions in order to access a URL without expiration date. Default is None
AZURE_MEDIA_URL_EXPIRATION_SECS = get_from_environment_var(
    environment_var='FDP_AZURE_MEDIA_EXPIRY', raise_exception=False, default_val=AZURE_URL_EXPIRATION_SECS
)


# This is where the files uploaded through Django will be uploaded.
# The container must be already created, since the storage system will not attempt to create it.
# AZURE_CONTAINER = None
# Set a secure connection (HTTPS), otherwise it makes an insecure connection (HTTP). Default is True
# AZURE_SSL = True
# Number of connections to make when uploading a single file. Default is 2
# AZURE_UPLOAD_MAX_CONN = 2
# Global connection timeout in seconds. Default is 20
# AZURE_CONNECTION_TIMEOUT_SECS = 20
# Maximum memory used by a downloaded file before dumping it to disk. Unit is in bytes. Default is 2MB
# AZURE_BLOB_MAX_MEMORY_SIZE = 2*1024*1024
# Overwrite an existing file when it has the same name as the file being uploaded. Otherwise, rename it.
# Default is False
# AZURE_OVERWRITE_FILES = False
# Default location for the uploaded files. This is a path that gets prepended to every file name.
# AZURE_LOCATION = None
# Whether to use the emulator (i.e Azurite). Defaults to False.
# AZURE_EMULATED_MODE = False
# The host base component of the url, minus the account name. Defaults to Azure (core.windows.net).
# Override this to use the China cloud (core.chinacloudapi.cn).
# AZURE_ENDPOINT_SUFFIX = 'core.windows.net'
# If specified, this will override all other parameters.
# See http://azure.microsoft.com/en-us/documentation/articles/storage-configure-connection-string/ for the
# connection string format.
# AZURE_CONNECTION_STRING = None
# This is similar to AZURE_CONNECTION_STRING, but it’s used when generating the file’s URL. A custom domain or
# CDN may be specified here instead of within AZURE_CONNECTION_STRING. Defaults to AZURE_CONNECTION_STRING’s value.
# AZURE_CUSTOM_CONNECTION_STRING = AZURE_CONNECTION_STRING
# A token credential used to authenticate HTTPS requests. The token value should be updated before its expiration.
# AZURE_TOKEN_CREDENTIAL = None
# A variable to set the Cache-Control HTTP response header.
# E.g. AZURE_CACHE_CONTROL = "public,max-age=31536000,immutable"
# AZURE_CACHE_CONTROL = None
# Use this to set content settings on all objects. To set these on a per-object basis, subclass the backend and
# override AzureStorage.get_object_parameters.
# This is a Python dict and the possible parameters are: content_type, content_encoding, content_language,
# content_disposition, cache_control, and content_md5.
# AZURE_OBJECT_PARAMETERS = None


# Ensure that URLs for Azure Storage static files container are included in the Content Security Policy (CSP)
CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (STATIC_URL,)
CSP_DEFAULT_SRC = CSP_DEFAULT_SRC + (STATIC_URL,)
CSP_STYLE_SRC = CSP_STYLE_SRC + (STATIC_URL,)
CSP_FONT_SRC = CSP_FONT_SRC + (STATIC_URL,)


# Microsoft Azure specific settings for Django-Compressor
# http://django-compressor.readthedocs.io/en/latest
# The dotted path to a Django Storage backend to be used to save the compressed files.
# Django Compressor ships with some additional storage backends:
# (1) 'compressor.storage.GzipCompressorFileStorage': A subclass of the default storage backend, which will additionally
# create *.gz files of each of the compressed files.
# (2) 'compressor.storage.BrotliCompressorFileStorage': A subclass of the default storage backend, which will
# additionally create *.br files of each of the compressed files. It is using the maximum level of compression (11) so
# compression speed will be low.
# Default value is 'compressor.storage.CompressorFileStorage'.
COMPRESS_STORAGE = STATICFILES_STORAGE
# Controls the URL that linked files will be read from and compressed files will be written to.
# Default value is STATIC_URL.
COMPRESS_URL = STATIC_URL
# Controls the absolute file path that linked static will be read from and compressed static will be written to when
# using the default COMPRESS_STORAGE compressor.storage.CompressorFileStorage.
# Default value is STATIC_ROOT.
COMPRESS_ROOT = STATIC_ROOT


# reCAPTCHA Private Key
# if key is in Azure Key Vault, then retrieve it
secret_recaptcha_private_key = get_from_azure_key_vault(secret_name=ENV_VAR_FOR_FDP_RECAPTCHA_PRIVATE_KEY)
# Azure Key Vault has priority, so overwrite any previous setting (e.g. from environment variable or configuration file)
if secret_recaptcha_private_key:
    RECAPTCHA_PRIVATE_KEY = secret_recaptcha_private_key


# User name to authenticate sending emails.
# if user name is in Azure Key Vault, then retrieve it
secret_email_host_user = get_from_azure_key_vault(secret_name=ENV_VAR_FOR_FDP_EMAIL_HOST_USER)
# Azure Key Vault has priority, so overwrite any previous setting (e.g. from environment variable or configuration file)
if secret_email_host_user:
    EMAIL_HOST_USER = secret_email_host_user


# Password to authenticate sending emails.
# if password is in Azure Key Vault, then retrieve it
secret_email_host_password = get_from_azure_key_vault(secret_name=ENV_VAR_FOR_FDP_EMAIL_HOST_PASSWORD)
# Azure Key Vault has priority, so overwrite any previous setting (e.g. from environment variable or configuration file)
if secret_email_host_password:
    EMAIL_HOST_PASSWORD = secret_email_host_password
