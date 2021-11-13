"""

Please DO NOT modify!

This file is imported and provides definitions for the main settings.py file.

Make any customizations in the main settings.py file.

Used to enforce user authentication only through the Microsoft Azure Active Directory backend.

"""
from fdp.configuration.abstract.constants import CONST_AXES_AUTH_BACKEND, CONST_AZURE_AUTH_BACKEND, \
    CONST_AZURE_AD_PROVIDER
from django.urls import reverse_lazy


#: Support only the Azure Active Directory user authentication backend
USE_ONLY_AZURE_AUTH = True


#: Always redirect the login URL to the Azure Active Directory login
LOGIN_URL = reverse_lazy('social:begin', args=[CONST_AZURE_AD_PROVIDER])


#: Disable Django's default database-driven user authentication
AUTHENTICATION_BACKENDS = [
    # Django Axes: https://django-axes.readthedocs.io/en/latest/
    CONST_AXES_AUTH_BACKEND,
    # Azure Active Directory: https://python-social-auth.readthedocs.io/en/latest/backends/azuread.html
    CONST_AZURE_AUTH_BACKEND
]


#: Describes options that are listed on the federated login page. See fdpuser.views.FederatedLoginTemplateView.
# In the format of: [
#     {
#         'label': '...text to display for option...',
#         'url_pattern_name': '...name of url pattern including namespace if relevant...',
#         'url_pattern_args': '...positional arguments for url pattern',
#         'css': {'css_property_1': 'css_value_1', 'css_property_2': 'css_value_2', ...},
#         'css_hover': {'css_property_1': 'css_value_1', 'css_property_2': 'css_value_2', ...},
#     },
#     {...}, ...
# ]
# If no options are listed, the federated login page will be skipped, and the user will be automatically redirected to
# the primary login page.
FEDERATED_LOGIN_OPTIONS = []
