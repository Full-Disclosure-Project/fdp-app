# FDP Information System Settings

## Overview

*As of 2021-06-03*

The Full Disclosure Project (FDP) information system can be customized through the use of configuration settings. For most projects, all relevant settings can be specified in environment variables that are accessible by the web application or in configuration files stored in the *../conf/* folder. In some cases, projects can choose to specify additional settings in the *fdp/settings.py* file.

## Django Settings

Many of the available settings for the FDP system are defined and handled through the Django web framework upon which the system is built.

For a full reference of Django settings, see: <https://docs.djangoproject.com/en/3.2/ref/settings/>

There are additional settings available for the FDP system that are defined by the Python packages which are integrated into it. These packages vary based on the hosting environment selected.

## Hosting Environment

The settings for the FDP system have been preconfigured for selected hosting environments, and can be managed in the *fdp/settings.py* file. 

To configure for any hosting environment, add a comment in front of all `import` statements.

To configure for hosting in a *local development* environment, remove the comment from in front of:

    from .local_settings import *

To configure for hosting in a *Microsoft Azure* environment, remove the comment from in front of:

    from .azure_settings import *

Once a hosting environment is configured, specify its relevant settings using the below table.

## Microsoft Azure Active Directory

When hosting in a Microsoft Azure environment is configured as described above, user authentication through an Azure Active Directory can be enabled by specifying the relevant Azure Key Vault secrets and Azure App Service application settings.

Additionally, to enforce user authentication through *only Azure Active Directory*, remove the comment from in front of:

    from .azure_backend_only_settings import *

## Logging

A preconfigured logging mechanism is available in the FDP system, and can be turned on in the *fdp/settings.py* file.

To enable file logging, remove the comment in front of the following line, and specify the file path:

    FDP_ERR_LOGGING['handlers']['file']['filename'] = '/home/site/wwwroot/debug.log'

Then, to allow the assignment to the appropriate Django setting, remove the comment in front of the following line:

    LOGGING = FDP_ERR_LOGGING

## User-uploaded files

Files can be uploaded by users into the FDP system, and linked to instances of both the `Attachment` and `PersonPhoto` models. Though their specifics are different, both have a maximum number of bytes for the file size and vet uploaded files against a list of supported file types. 

Changing the default maximum number of file size bytes for either models will require generating corresponding database migrations through Django's `makemigrations` and `migrate` commands. 

To change the default maximum number of file size bytes for the `Attachment` model, specify the number of bytes:

    FDP_MAX_ATTACHMENT_FILE_BYTES = 104857600

To change the default maximum number of file size bytes for the `PersonPhoto` model, specify the number of bytes:

    FDP_MAX_PERSON_PHOTO_FILE_BYTES = 2097152

Supported file types are defined by a list of tuples, with the first item being a user-friendly description of the supported file type, and the second item being the expected file extension in lowercase:

    ..., ('Microsoft Word 97-2003', 'doc'), ('Microsoft Word 2007+', 'docx'), ...

To add to the list of supported file types for the `Attachment` model:

    FDP_SUPPORTED_ATTACHMENT_FILE_TYPES.append(
        ('User-friendly description for file type', 'ext')
    )

To overwrite the *entire* list of supported file types for the `Attachment` model:

    FDP_SUPPORTED_ATTACHMENT_FILE_TYPES = [
        ... ('User-friendly description for file type', 'ext'), ...
    ]

To add to the list of supported file types for the `PersonPhoto` model:

    FDP_SUPPORTED_PERSON_PHOTO_FILE_TYPES.append(
        ('User-friendly description for file type', 'ext')
    )

To overwrite the *entire* list of supported file types for the `PersonPhoto` model:

    FDP_SUPPORTED_PERSON_PHOTO_FILE_TYPES = [
        ... ('User-friendly description for file type', 'ext'), ...
    ]

## FDP Settings for Azure

For hosting in Microsoft Azure, it is recommended that the most sensitive settings are stored in Microsoft Azure Key Vault as Secrets. Less sensitive settings can be stored in the Azure App Service as Application Settings. The following is one possible configuration:

| Required | Azure Key Vault Secret | Azure App Service Application Setting (environment variable) | Default | Details |
| --- | --- | --- | --- | --- |
|  |  | FDP_EXTERNAL_AUTHENTICATION | `None` | Additional authentication mechanism. Use `'aad'` for Azure Active Directory. |
| Required | | FDP_AZURE_KEY_VAULT_NAME |  | Name for Azure Key Vault. Must be defined to use Secrets in Azure Key Vault. |
| Required | FDP-SECRET-KEY | | |  Secret key for Django. |
| | | FDP_ALLOWED_HOST | From environment variable: `'WEBSITE_HOSTNAME'` | Host for Django to serve. |
| | | FDP_DATABASE_NAME | `'fdp'` | Name of database. |
| Required | FDP-DATABASE-USER | | | Username for database. |
| Required | FDP-DATABASE-PASSWORD | | | Password for database. |
| Required | | FDP_DATABASE_HOST | | Host for database access. |
| | | FDP_DATABASE_PORT | `'5432'` | Port for database access. |
| Required | FDP-QUERYSTRING-PASSWORD | | | URL-safe base64-encoded 32-byte key for querystring encryption. |
| Required | | FDP_AZURE_STORAGE_ACCOUNT_NAME | | Name for Azure Storage account. |
| Required | FDP-AZURE-STORAGE-ACCOUNT-KEY *(specify access key value)* | FDP_AZURE_STORAGE_ACCOUNT_KEY *(specify reference to secret)* | | Access key for Azure Storage account. Specify both in Azure Key Vault (using access key value), and in Azure App Service Application Setting (using reference to secret). |
| | | FDP_AZURE_STORAGE_ACCOUNT_SUFFIX | `'blob.core.windows.net'` | Suffix for Azure Storage account. |
| | | FDP_AZURE_STATIC_CONTAINER | `'static'` | Name for static files container. |
| | | FDP_AZURE_STATIC_EXPIRY | `None` | Seconds for static file expiration. |
| | | FDP_AZURE_MEDIA_CONTAINER | `'media'` | Name for media files container. |
| | | FDP_AZURE_MEDIA_EXPIRY | `20` | Seconds for media file expiration. |
| | FDP-SOCIAL-AUTH-AZUREAD-TENANT-OAUTH2-KEY | | | Azure Active Directory client ID. Only checked if `'aad'` was specified for Azure Active Directory. |
| | FDP-SOCIAL-AUTH-AZUREAD-TENANT-OAUTH2-TENANT-ID | | | Azure Active Directory tenant ID. Only checked if `'aad'` was specified for Azure Active Directory. |
| | FDP-SOCIAL-AUTH-AZUREAD-TENANT-OAUTH2-SECRET | | | Azure Active Directory client secret. Only checked if `'aad'` was specified for Azure Active Directory. |
| | | FDP_SOCIAL_AUTH_OAUTH2_WHITELISTED_DOMAINS | | Comma-separate list of Azure Active Directory domains. Only checked if `'aad'` was specified for Azure Active Directory. |
| | | FDP_FROM_EMAIL | `'webmaster@localhost'` | `FROM` email address for system. |
| | | FDP_EMAIL_HOST | `'localhost'` | Host used to send emails. |
| | FDP-EMAIL-HOST-USER | | | User for login to send emails. |
| | FDP-EMAIL-HOST-PASSWORD | | | Password for login to send emails. |
| | | FDP_EMAIL_PORT | `25` | Port to send emails. |
| | | FDP_RECAPTCHA_PUBLIC_KEY | | Public reCAPTCHA key. |
| | FDP-RECAPTCHA-PRIVATE-KEY | | | Private reCAPTCHA key. |

## FDP Settings for Local Development

For hosting in a local development environment, it is recommended that settings are stored in configuration files. The following is one possible configuration:

| Required | Configuration File (.conf) | Default | Details |
| --- | --- | --- | --- |
| | fdp_from_email | `'webmaster@localhost'` | `FROM` email address for system. | 
| | fdp_email_host | `'localhost'` | Host used to send emails. | 
| | fdp_email_host_user | | User for login to send emails. | 
| | fdp_em | | Password for login to send emails. | 
| | fdp_email_port | `25` | Port to send emails. | 
| | fdp_recaptcha_public_key | | Public reCAPTCHA key. | 
| | fdp_ca | | Private reCAPTCHA key. | 
| Required | fdp_sk | | Secret key for Django. | 
| | fdp_database_name | `'fdp'` | Name of database. | 
| | fdp_database_user | `'django_fdp'` | Username for database. | 
| Required | fdp_ps | | Password for database. | 
| | fdp_database_host | `'localhost'` | Host for database access. | 
| | fdp_database_port | `'5432'` | Port for database access. | 
| Required | fdp_qs | | URL-safe base64-encoded 32-byte key for querystring encryption. | 
