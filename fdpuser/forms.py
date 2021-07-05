from django.contrib.auth.forms import UserCreationForm, UserChangeForm, ReadOnlyPasswordHashField, PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from .models import FdpUser, PasswordReset
from captcha.fields import ReCaptchaField
from captcha.widgets import ReCaptchaV2Checkbox


class FdpUserCreationForm(UserCreationForm):
    """ A ModelForm for creating a new FDP user.

    See: https://docs.djangoproject.com/en/2.0/topics/auth/default/#django.contrib.auth.forms.UserCreationForm

    """
    def save(self, commit=True):
        """ Ensures that new users created by guest administrators are tied to the guest administrators' organization.

        :param commit: True if record should be created in database, false otherwise.
        :return: Model instance for new user.
        """
        u = self.request.user
        user = super(FdpUserCreationForm, self).save(commit=commit)
        # guest administrator is creating new user
        if not (u.is_host or u.is_superuser):
            # tie user to same organization as guest administrator has
            user.fdp_organization = u.fdp_organization
            # optionally save record in database
            if commit:
                user.save()
        return user

    class Meta(UserCreationForm.Meta):
        model = FdpUser
        fields = [f for f in UserCreationForm.Meta.fields if f not in FdpUser.removed_fields] + FdpUser.added_fields


class FdpUserChangeForm(UserChangeForm):
    """ A form used in the admin interface to change a FDP user’s information and permissions.

    See: https://docs.djangoproject.com/en/2.0/topics/auth/default/#django.contrib.auth.forms.UserChangeForm

    """
    # Replace the password field with the admin interface's password hash display field
    password = ReadOnlyPasswordHashField()

    def clean_password(self):
        """ Clean the password.

        Regardless of user input, return initial value. Field does not have access to initial value, so return here.

        :return: Initial value for password.
        """
        return self.initial['password']

    def clean_is_superuser(self):
        """ Ensure that superuser property cannot be changed unless changing user is superuser.

        :return: Superuser property.
        """
        u = self.request.user
        return u.is_superuser and self.cleaned_data['is_superuser']

    def clean_is_host(self):
        """ Ensure that host property cannot be changed unless changing user is superuser or host.

        Assumption is if user is not superuser, then they are an administrator.

        :return: Host property.
        """
        u = self.request.user
        return (u.is_superuser or u.is_host) and self.cleaned_data['is_host']

    def clean_is_administrator(self):
        """ Ensure that administrator property cannot be changed unless changing user is superuser or administrator.

        :return: Administrator property.
        """
        u = self.request.user
        return (u.is_superuser or u.is_administrator) and self.cleaned_data['is_administrator']

    def clean_fdp_organization(self):
        """ Ensure that a FDP organization cannot be changed unless changing user is a superuser or host.

        Assumption is if user is not superuser, then they are an administrator.

        :return: FDP organization or None.
        """
        u = self.request.user
        if (u.is_superuser or u.is_host) or (u.fdp_organization == self.cleaned_data['fdp_organization']):
            return self.cleaned_data['fdp_organization']
        else:
            return u.fdp_organization

    class Meta:
        model = FdpUser
        fields = FdpUserCreationForm.Meta.fields


class FdpUserPasswordResetForm(PasswordResetForm):
    """ Overrides the default password reset form, so that each time the password is reset, a log is made.

    """
    def save(self, domain_override=None,
             subject_template_name='registration/password_reset_subject.txt',
             email_template_name='registration/password_reset_email.html',
             use_https=False, token_generator=default_token_generator,
             from_email=None, request=None, html_email_template_name=None,
             extra_email_context=None):
        """ Ensure that each password reset is recorded, and rate limits are checked.

        :param domain_override:
        :param subject_template_name:
        :param email_template_name:
        :param use_https:
        :param token_generator:
        :param from_email:
        :param request:
        :param html_email_template_name:
        :param extra_email_context:
        :return:
        """
        super(FdpUserPasswordResetForm, self).save(
            domain_override=domain_override, subject_template_name=subject_template_name,
            email_template_name=email_template_name, use_https=use_https, token_generator=token_generator,
            from_email=from_email, request=request, html_email_template_name=html_email_template_name,
            extra_email_context=extra_email_context
        )
        email = self.cleaned_data["email"]
        for user in self.get_users(email):
            PasswordReset.objects.create_password_reset(email=user.email, request=request)


class CspFriendlyReCaptchaV2Checkbox(ReCaptchaV2Checkbox):
    """ Overrides the default widget used to render the reCAPTCHA field so that a NONCE can be added to the inline
    JavaScript block in order to comply with Content Security Policies (CSPs).

    """
    template_name = 'csp_friendly_captcha/widget_v2_checkbox.html'

    def get_context(self, name, value, attrs):
        """ Adds nonce to the context dictionary so that it can be used to render inline JavaScript blocks that
        comply with Content Security Policies (CSPs).

        See: https://docs.djangoproject.com/en/3.2/ref/forms/widgets/#django.forms.Widget.get_context

        :param name: Name of field.
        :param value: Value of field.
        :param attrs: Dictionary of attributes that define the widget.
        :return: Dictionary representing context.
        """
        context = super().get_context(name=name, value=value, attrs=attrs)
        # added as property of the widget in the __init__(...) method of the containing form
        context['csp_nonce'] = getattr(self, 'csp_nonce', '')
        return context


class CspFriendlyReCaptchaField(ReCaptchaField):
    """ Overrides the default reCAPTCHA field so that a nonce can be added to the inline JavaScript block in order to
    comply with Content Security Policies (CSPs).

    """
    widget = CspFriendlyReCaptchaV2Checkbox


class FdpUserPasswordResetWithReCaptchaForm(FdpUserPasswordResetForm):
    """ Overrides the FDP user password reset form, so that reCAPTCHA is included. Also, includes nonce that is added
    to the inline JavaScript block in order to comply with Content Security Policies (CSPs).

    """
    captcha = CspFriendlyReCaptchaField()

    def __init__(self, csp_nonce, *args, **kwargs):
        """ Passes nonce used for CSP to the widget so that it can be access from the widget template.

        :param csp_nonce: Nonce value used to validate inline JavaScript blocks under Content Security Policies (CSPs).
        :param args:
        :param kwargs:
        """
        super().__init__(*args, **kwargs)
        # will be used by the get_context(...) method of the widget
        self.fields['captcha'].widget.csp_nonce = csp_nonce
