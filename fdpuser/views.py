from django.utils.translation import gettext as _
from django.core.mail import send_mail, mail_admins
from django.core.exceptions import ImproperlyConfigured
from django.contrib.auth.views import PasswordResetView
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.utils.decorators import method_decorator
from django.conf import settings
from inheritable.models import AbstractIpAddressValidator, AbstractConfiguration, JsonData
from inheritable.views import SecuredSyncTemplateView, SecuredSyncRedirectView, SecuredAsyncJsonView
from .models import PasswordReset, FdpUser
from .forms import FdpUserPasswordResetForm, FdpUserPasswordResetWithReCaptchaForm
from two_factor.views import LoginView
from two_factor.views.utils import class_view_decorator
from django_otp import devices_for_user
from formtools.wizard.views import normalize_name
from csp.decorators import csp_update, csp_replace
from time import time


class SettingsTemplateView(SecuredSyncTemplateView):
    """ Page that allows users to change settings related to their account, such as 2FA and passwords.

    """
    template_name = 'settings.html'

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(SettingsTemplateView, self).get_context_data(**kwargs)
        u = self.request.user
        context.update({
            'title': _('Settings'),
            'description': _('Manage settings related to your account.'),
            'email': u.email,
            'name': u.get_full_name(),
            'role': u.role_txt,
            'fdp_organization': u.organization_txt
        })
        return context


class ConfirmPasswordChangeTemplateView(SecuredSyncTemplateView):
    """ Page that allows users to confirm that they wish to change their password.

    """
    template_name = 'confirm_password_change.html'

    def test_func(self):
        """ Ensures that user has a changeable password.

        :return: True if user has a changeable password, false otherwise.
        """
        return super(ConfirmPasswordChangeTemplateView, self).test_func() and self.request.user.has_changeable_password

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(ConfirmPasswordChangeTemplateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('Change Password'),
            'description': _('Confirmation to change the password.')
        })
        return context

    def dispatch(self, request, *args, **kwargs):
        """ Ensures that required settings are specified for a password change email.

        :param request: Http request object.
        :param args:
        :param kwargs:
        :return:
        """
        if not AbstractConfiguration.can_do_password_reset():
            raise ImproperlyConfigured('Password reset is not supported with this configuration')
        return super(ConfirmPasswordChangeTemplateView, self).dispatch(request=request, *args, **kwargs)


class ConfirmTwoFactorResetTemplateView(SecuredSyncTemplateView):
    """ Page that allows users to confirm that they wish to reset their 2FA.

    """
    template_name = 'confirm_2fa_reset.html'

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(ConfirmTwoFactorResetTemplateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('Reset 2FA'),
            'description': _('Confirmation to reset two factor authentication.')
        })
        return context


class ResetPasswordRedirectView(SecuredSyncRedirectView):
    """ Trip to server, redirecting to the login page, resetting the user's password.

    """
    pattern_name = 'password_reset_done'

    def test_func(self):
        """ Ensures that user has a changeable password.

        :return: True if user has a changeable password, false otherwise.
        """
        return super(ResetPasswordRedirectView, self).test_func() and self.request.user.has_changeable_password

    def dispatch(self, request, *args, **kwargs):
        """ Invalidate user's current password, log out user, record password reset and send
        email.

        :param request: Http request object.
        :param args:
        :param kwargs:
        :return:
        """
        if not AbstractConfiguration.can_do_password_reset():
            raise ImproperlyConfigured('Password reset is not supported with this configuration')
        user = request.user
        ip_address = AbstractIpAddressValidator.get_ip_address(request=request)
        # limit hasn't been reached for user or IP address to reset password
        if PasswordReset.can_reset_password(user=user, ip_address=ip_address, email=None):
            response = super(ResetPasswordRedirectView, self).dispatch(request, *args, **kwargs)
            # Create password reset form
            form = FdpUserPasswordResetForm({'email': user.email})
            if form.is_valid():
                # Invalidate current password
                PasswordReset.invalidate_password_logout(user=user, request=request)
                # Send the password reset link
                form.save(request=request)
            # something is wrong with the form's configuration
            else:
                raise Exception('FDPUserPasswordResetForm was not valid')
        # limit has been reached for password resets
        else:
            raise Exception('Password reset rate limits have been reached')
        return response


class FdpPasswordResetView(PasswordResetView):
    """ Overrides the PasswordResetView to ensure that rate limit is checked before a password reset, and that the
    password reset is logged.

    Also, passes the nonce to the widget that is used to render the reCAPTCHA field, so that an inline JavaScript block
    can be validated under the Content Security Policies (CSPs).

    """
    # Form extended so that password reset is logged and recaptcha is used
    form_class = FdpUserPasswordResetWithReCaptchaForm

    def get_form_kwargs(self):
        """ Adds the nonce that is used validate an inline JavaScript block under the Content Security Policies (CSPs).

        :return: Dictionary of kwargs with which to instantiate form.
        """
        form_kwargs = super().get_form_kwargs()
        # will eventually be passed to the get_context(...) method of the widget used to render the reCAPTCHA field
        form_kwargs['csp_nonce'] = self.request.csp_nonce
        return form_kwargs

    @method_decorator(csrf_protect)
    @csp_update(
        FRAME_SRC='https://www.google.com/recaptcha/',
        SCRIPT_SRC=['https://www.google.com/recaptcha/', 'https://www.gstatic.com/recaptcha/', "'unsafe-eval'"]
    )
    def dispatch(self, *args, **kwargs):
        """ Check whether password reset is supported with the particular settings configuration.

        For example, configuring authentication through only Azure Active Directory will disable password resets.

        Changes the Content Security Policies (CSPs), to allow for access to external Google reCAPTCHA resources.

        :param args:
        :param kwargs:
        :return: Response redirecting to successful password reset regardless of whether a password was actually reset
        or not.
        """
        if not AbstractConfiguration.can_do_password_reset():
            raise ImproperlyConfigured('Password reset is not supported with this configuration')
        return super(FdpPasswordResetView, self).dispatch(*args, **kwargs)

    def form_valid(self, form):
        """ Invalidates a user's current password, logs the user out, records the password reset and sends
        an email with a tokenized link to change the password.

        Users who are authenticated externally such as through Azure Active Directory, will not have their passwords
        reset, nor any emails sent. (They do not have "changeable" passwords according to FDP.)

        Similarly, no password reset will be performed and no email sent for a user who does not exist.

        Finally, users who are normally eligible for password resets, but have reached their password reset limits,
        will also not have their passwords reset, nor any emails sent.

        To minimize user-enumeration attacks, the view will redirect to a successful password reset view regardless of
        whether the password was actually successfully reset and regardless of whether an email was sent.

        Note from Django: "Be aware that sending an email costs extra time, hence you may be vulnerable to an email
        address enumeration timing attack due to a difference between the duration of a reset request for an existing
        email address and the duration of a reset request for a nonexistent email address. To reduce the overhead, you
        can use a 3rd party package that allows to send emails asynchronously, e.g. django-mailer."

        See: https://docs.djangoproject.com/en/3.2/topics/auth/default/#django.contrib.auth.views.PasswordResetView

        :param form: Form submitted that contains email address of user whose password reset is requested.
        :return: Response rendering successful password reset page, regardless of actual success.
        """
        request = self.request
        if request.method == 'POST':
            ip_address = AbstractIpAddressValidator.get_ip_address(request=request)
            email = request.POST.get('email', None)
            # user exists, is internally authenticated and has not reached password reset limits for email or IP address
            if PasswordReset.can_reset_password(user=None, ip_address=ip_address, email=email):
                user = FdpUser.objects.get(email=email)
                # Invalidate current password
                PasswordReset.invalidate_password_logout(user=user, request=request)
            # user does not exist, is externally authenticated, or has reached password reset limits for email or IP
            # address
            else:
                # replace specified email with an invalid email address that does not exist
                form.cleaned_data['email'] = 'DOESNOTEXIST'
        return super().form_valid(form=form)


class ResetTwoFactorRedirectView(SecuredSyncRedirectView):
    """ Trip to server, redirecting to the login page, resetting the user's password and 2FA.

    """
    # If password resets are configured, then view redirects to password_reset_done view.
    # If password resets are not configured, then view redirects to logout view.
    pattern_name = 'password_reset_done' if AbstractConfiguration.can_do_password_reset() else 'logout'

    @staticmethod
    def __remove_all_2fa_devices(user):
        """ Removes all 2FA devices for a user.

        :param user: User for which to remove 2FA devices.
        :return: Nothing.
        """
        for device in devices_for_user(user):
            device.delete()

    @classmethod
    def __dispatch_with_password_reset(cls, request, form):
        """ Performs the 2FA reset with password resets configured.

        :param request: Http request object.
        :param form: Validated password reset form.
        :return: Nothing.
        """
        user = request.user
        # invalidate current password and log user out of their account
        PasswordReset.invalidate_password_logout(user=user, request=request)
        # remove all 2FA devices for user
        cls.__remove_all_2fa_devices(user=user)
        # send the password reset link
        form.save(request=request)
        # notify user that their 2FA has been reset
        send_mail(
            _('FDP 2FA Reset'),
            _('Your Full Disclosure Project (FDP) Two-Factor Authentication (2FA) has been reset. If you did '
              'not initiate this reset, please contact {a}.'.format(a=settings.DEFAULT_FROM_EMAIL)),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        # notify admins that user has reset their 2FA
        mail_admins(
            subject=_('FYI - User resets 2FA'),
            message=_('User {u} has reset their 2FA.'.format(u=user.email))
        )

    @classmethod
    def __dispatch_without_password_reset(cls, request):
        """ Performs the 2FA reset without password resets configured.

        :param request: Http request object.
        :return: Nothing.
        """
        user = request.user
        # log user out of their account
        PasswordReset.logout(request=request)
        # remove all 2FA devices for user
        cls.__remove_all_2fa_devices(user=user)

    def dispatch(self, request, *args, **kwargs):
        """ Remove 2FA devices, invalidate user's current password, log out user and send email.

        :param request: Http request object.
        :param args:
        :param kwargs:
        :return: Redirect response to password reset completed view or logout view.
        """
        user = request.user
        response = super(ResetTwoFactorRedirectView, self).dispatch(request, *args, **kwargs)
        # Create password reset form
        form = FdpUserPasswordResetForm({'email': user.email})
        if form.is_valid():
            if AbstractConfiguration.can_do_password_reset():
                self.__dispatch_with_password_reset(request=request, form=form)
            else:
                self.__dispatch_without_password_reset(request=request)
            return response
        # something is wrong with the form's configuration
        else:
            raise Exception('FDPUserPasswordResetForm was not valid')


@class_view_decorator(sensitive_post_parameters())
@class_view_decorator(never_cache)
class FdpLoginView(LoginView):
    """ Extends the login view provided by the Django Two-Factor package to ensure that users can be authenticated
    through an external backend such as Azure Active Directory.

    Overrides the GET method, to allow externally authenticated users to bypass the authentication step.

    For the Django Two-Factor package, see: https://django-two-factor-auth.readthedocs.io/

    """
    def get_prefix(self, request, *args, **kwargs):
        """ Sets the prefix that is used for the ManagementForm.

        Implementation is taken from formtools.wizard.views.WizardView.get_prefix()

        If get_prefix(...) is not redefined, then prefix generated will be 'fdp_login_view' instead of the
        expected 'login_view'.

        In some scenarios, such as when performing automated tests, this prefix mismatch invalidates the ManagementForm,
        and so during a POST request submitted by Django's test client, a SuspiciousOperation may be raised with the
        message: ManagementForm data is missing or has been tampered with.

        :param request: Http request object.
        :param args:
        :param kwargs:
        :return: Prefix used in ManagementForm.
        """
        return normalize_name(LoginView.__name__)

    @staticmethod
    def __check_if_user_externally_authenticated(request):
        """ Checks if a user is externally authenticated, such as through Azure Active Directory.

        :param request: Http request object.
        :return: True if user is externally authenticated, false otherwise.
        """
        user = getattr(request, 'user', None)
        return FdpUser.is_user_azure_authenticated(user=user)

    def get(self, request, *args, **kwargs):
        """ Overrides default GET method handling for Django Two-Factor package, to allow users to authenticate via
        an external backend such as Azure Active Directory, then the authentication step
        (i.e. with the AuthenticationForm) can be skipped.

        For the Django Two-Factor package, see: https://django-two-factor-auth.readthedocs.io/

        Without this change, users who have externally authenticated and have also previously set up their 2FA will
        be redirected to the login form to enter a username and password.

        :param request: Http request object including potentially already authenticated user.
        :param args:
        :param kwargs:
        :return: Http response.
        """
        # run through the default process for the GET method
        response = super(FdpLoginView, self).get(request=request, *args, **kwargs)
        # if Azure Active Directory is configured
        if AbstractConfiguration.can_do_azure_active_directory():
            # if the user was authenticated via an external backend, such as Azure Active Directory
            if self.__check_if_user_externally_authenticated(request=request):
                # following the logic that is defined in the process_step(...) method
                self.storage.reset()
                # these properties will be checked, e.g. the user in has_token_step(...) method
                # retrieve the authenticated user from the HTTP request
                user = request.user
                # add the backend property that will be used in the _set_authenticated_user(...) method
                # use the first backend that is specified in settings
                # default in Django is: 'django.contrib.auth.backends.ModelBackend'
                # TODO: Add ability to configure which authentication backend, in case of multiple options
                if len(settings.AUTHENTICATION_BACKENDS) != 3:
                    raise ImproperlyConfigured('Use of FdpLoginView assumes three authentication backends')
                user.backend = settings.AUTHENTICATION_BACKENDS[0]
                self.storage.authenticated_user = user
                # sets the time of authentication to avoid a session expiry exception
                self.storage.data['authentication_time'] = int(time())
                # if 2FA login process includes a token step
                if self.has_token_step():
                    # skip password authentication and go directly to token step
                    return self.render_goto_step('token')
        # otherwise, follow the default process for the GET method
        return response


class AsyncRenewSessionView(SecuredAsyncJsonView):
    """ Asynchronously renews a user's session to avoid it expiring.

    See function _renewUserSession(...) in static/js/common.js for the client-side script submitting the request.

    """
    def post(self, request, *args, **kwargs):
        """ Asynchronously renews a user's session to avoid it expiring.

        :param request: Http request object through which asynchronous request was submitted.
        :param args: Ignored.
        :param kwargs: Ignored.
        :return: JSON formatted response containing a True boolean value.
        """
        try:
            json = JsonData(data=True)
        except Exception as err:
            json = self.jsonify_error(err=err, b=_('Could not renew session. Please reload the page.'))
        return self.render_to_response(json=json)
