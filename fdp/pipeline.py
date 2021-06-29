from django.contrib.auth import logout
from django.shortcuts import redirect
from fdpuser.models import FdpUser
from importlib.util import find_spec, module_from_spec
from uuid import uuid4
# check if social-auth-app-django package is installed
# see: https://python-social-auth.readthedocs.io/en/latest/configuration/django.html
social_core_pipeline_user_spec = find_spec('social_core.pipeline.user')
social_core_utils_spec = find_spec('social_core.utils')
# social-auth-app-django package is not installed
if not (social_core_pipeline_user_spec and social_core_utils_spec):
    raise Exception('Please install the package: social-auth-app-django')
# load pipeline.user module in the social-auth-app-django package
social_core_pipeline_user_module = module_from_spec(social_core_pipeline_user_spec)
# initialize pipeline.user module
social_core_pipeline_user_spec.loader.exec_module(social_core_pipeline_user_module)
# load utils module in the social-auth-app-django package
social_core_utils_module = module_from_spec(social_core_utils_spec)
# initialize ..utils module
social_core_utils_spec.loader.exec_module(social_core_utils_module)


def get_username(strategy, details, backend, user=None, *args, **kwargs):
    """ Generate a username for this user, and append a random string at the end if there is any collision.

    Based on get_username method in Python Social Auth package social-core/social_core/pipeline/user.py version 4.1.0.

    :param strategy: Current strategy giving access to current store, backend and request.
    :param details: User details given by authentication provider.
    :param backend: Backend in which user exists or will eventually be created.
    :param user: Will be none if new user should be created.
    :param args:  Ignored.
    :param kwargs: Ignored.
    :return: Dictionary containing username.
    """
    if 'username' not in backend.setting('USER_FIELDS', social_core_pipeline_user_module.USER_FIELDS):
        return
    storage = strategy.storage

    if not user:
        email_as_username = strategy.setting('USERNAME_IS_FULL_EMAIL', False)
        uuid_length = strategy.setting('UUID_LENGTH', 16)
        max_length = storage.user.username_max_length()
        do_slugify = strategy.setting('SLUGIFY_USERNAMES', False)
        do_clean = strategy.setting('CLEAN_USERNAMES', True)

        def identity_func(val):
            return val

        if do_clean:
            override_clean = strategy.setting('CLEAN_USERNAME_FUNCTION')
            if override_clean:
                clean_func = social_core_utils_module.module_member(override_clean)
            else:
                clean_func = storage.user.clean_username
        else:
            clean_func = identity_func

        if do_slugify:
            override_slug = strategy.setting('SLUGIFY_FUNCTION')
            if override_slug:
                slug_func = social_core_utils_module.module_member(override_slug)
            else:
                slug_func = social_core_utils_module.slugify
        else:
            slug_func = identity_func

        if email_as_username and details.get('email'):
            username = details['email']
        elif details.get('username'):
            username = details['username']
        else:
            username = uuid4().hex

        short_username = (username[:max_length - uuid_length]
                          if max_length is not None
                          else username)
        final_username = slug_func(clean_func(username[:max_length]))

        # Generate a unique username for current user using username
        # as base but adding a unique hash at the end. Original
        # username is cut to avoid any field max_length.
        # The final_username may be empty and will skip the loop.

        # FdpUser.objects.filter(...).exists() replaces storage.user.user_exists(username=final_username)
        # See DjangoUserMixin.user_exists(...) in social-app-django/social_django/storage.py
        while not final_username or FdpUser.objects.filter(
                **FdpUser.objects.get_case_insensitive_username_filter_dict(username=final_username)
        ).exists():
            username = short_username + uuid4().hex[:uuid_length]
            final_username = slug_func(clean_func(username[:max_length]))
    else:
        final_username = storage.user.get_username(user)
    return {'username': final_username}


def create_user(strategy, details, backend, user=None, *args, **kwargs):
    """ Create a user account to correspond to the external authentication, if none was found.

    Based on create_user method in Python Social Auth package social-core/social_core/pipeline/user.py version 4.1.0.

    :param strategy: Current strategy giving access to current store, backend and request.
    :param details: User details given by authentication provider.
    :param backend: Backend in which to create user.
    :param user: Will be none if new user should be created.
    :param args: Ignored.
    :param kwargs: Dictionary containing values to assign to user's fields.
    :return: Dictionary containing new user.
    """
    if user:
        return {'is_new': False}

    fields = dict((name, kwargs.get(name, details.get(name)))
                  for name in backend.setting('USER_FIELDS', social_core_pipeline_user_module.USER_FIELDS))
    if not fields:
        return

    # added to ensure that users authenticated through Azure Active Directory are added as host and
    # only externally authenticable
    fields.update({'is_host': True, 'only_external_auth': True})

    # email is required and is assumed to be unique for each user
    # it is retrieved with the 'upn' key from the response dictionary during the firs step fo the social authentication
    # pipeline: social_core.pipeline.social_auth.social_details
    email = fields.get('email', None)
    if not email:
        raise Exception('The user\'s email is missing. If the user is a guest in Azure Active Directory, then an '
                        'optional claim for upn may need to be configured in the directory.')

    # check if user already exists, since email must be unique
    # tokens may have been removed
    e = FdpUser.objects.get_case_insensitive_username_filter_dict(username=email)
    return {
        'is_new': True,
        'user': strategy.create_user(**fields) if not FdpUser.objects.filter(**e).exists() else FdpUser.objects.get(**e)
    }


def logout_user(strategy, *args, **kwargs):
    """ Forcibly logs out the user, after their disconnection from Azure Active Directory is complete.

    :param strategy: Current strategy giving access to current store, backend and request.
    :param args: Ignored.
    :param kwargs: Ignored.
    :return: Nothing.
    """
    request = strategy.request
    logout(request)
    return redirect('https://login.microsoftonline.com/common/oauth2/logout')
