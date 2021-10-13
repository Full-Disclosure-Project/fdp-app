from django.test import Client, RequestFactory
from django.utils.translation import ugettext_lazy as _
from django.utils.timezone import now
from django.urls import reverse, NoReverseMatch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib import admin
from django.conf import settings
from django.apps import apps
from django.views.generic.base import RedirectView
from .models import FdpUser, PasswordReset, FdpOrganization, FdpCSPReport
from .forms import FdpUserCreationForm, FdpUserChangeForm
from .views import FdpLoginView
from bulk.models import BulkImport, FdpImportFile, FdpImportMapping, FdpImportRun
from bulk.views import DownloadImportFileView
from inheritable.models import AbstractConfiguration
from inheritable.tests import AbstractTestCase, local_test_settings_required, azure_test_settings_required, \
    azure_only_test_settings_required
from sourcing.models import Attachment, Content, ContentPerson
from sourcing.views import DownloadAttachmentView
from changing.views import IndexTemplateView as changing_index_view
from core.models import Person
from core.views import DownloadPersonPhotoView
from profiles.models import CommandSearch, CommandView, OfficerSearch, OfficerView
from profiles.views import IndexTemplateView as profiles_index_view
from verifying.models import VerifyContentCase, VerifyPerson, VerifyType
from fdp.configuration.abstract.constants import CONST_AZURE_AUTH_APP
from fdp.urlconf.constants import CONST_TWO_FACTOR_PROFILE_URL_NAME, CONST_LOGIN_URL_NAME
from unittest.mock import patch as mock_patch
from os import environ
from data_wizard.sources.models import FileSource
from axes.models import AccessLog, AccessAttempt
from two_factor.models import PhoneDevice
from two_factor.views import LoginView
from two_factor.admin import AdminSiteOTPRequired
from axes.models import AccessAttempt
import secrets
import logging

logger = logging.getLogger(__name__)


class FdpUserTestCase(AbstractTestCase):
    """ Performs following tests:

    (1) Test access to views:
            (a) For all user types

    (2) Test throttling for password resets and password changes
            (a) For all user types

    (3) Test Guest Admin accessing all permutations of user roles

    (4) Test Guest Admin create new user (check that organizations match)

    (5) Test Admin permission escalation

    (6) Test Guest Admin access to host-only views

    (7) Test login view, 2FA, URL patterns and file serving for local development configuration

    (8) Test login view, 2FA, URL patterns and file serving for Microsoft Azure configuration

    (9) Test login view, 2FA, URL patterns and file serving for Microsoft Azure configuration with only AAD
    authentication

    (10) Test enforcement of EULA requirement, including:
            (a) EULA is not required when EULAs are disabled;
            (b) EULA agreement is first required before accessing profiles and changing index pages; and
            (c) EULA agreement is only required once when accessing profiles and changing index pages.

    """
    def setUp(self):
        """ Configure RECPATCHA to be in test mode.

        :return: Nothing.
        """
        # skip setup and tests unless configuration is compatible
        super().setUp()
        # used to test password resets
        environ[self._recaptcha] = 'True'
        # create a bulk import file
        self._add_fdp_import_file()
        # create a person photo
        self._add_person_photo()
        # create an attachment
        self._add_attachment()

    def tearDown(self):
        """ Configure RECAPTCHA to no longer be in test mode.
        """
        environ[self._recaptcha] = 'False'

    #: Suffix for user email for user without organization.
    __without_org_suffix = '_without_org'

    #: Suffix for user email for user with correct organization.
    __with_org_suffix = '_with_org'

    #: Suffix for user email for user with incorrect organization.
    __wrong_org_suffix = '_wrong_org'

    def __verify_user_cannot_log_in(self, c, user):
        """ Verifies that user cannot log in through Django authentication.

        :param c: Instantiated testing client for Django.
        :param user: User to verify.
        :return: Http response that is returned by GET request to access homepage.
        """
        # except 400 Bad Request, because view is not configured to handle POST request for login
        response = self._do_django_username_password_authentication(
            c=c,
            username=user.email,
            password=self._password,
            login_status_code=400,
            # if not specified, reverse will attempt to convert '/social/login/azu...'
            override_login_url=reverse('two_factor:{n}'.format(n=CONST_LOGIN_URL_NAME))
        )
        # override and try anyway to force a login
        response.client.force_login(user=user, backend=None)
        # verify redirect to login screen
        response = self._do_get(
            c=response.client,
            url='/',
            expected_status_code=302 if not user.only_external_auth else 400,
            login_startswith=reverse('two_factor:{n}'.format(n=CONST_LOGIN_URL_NAME))
        )
        return response

    def __get_static_file_types(self, callable_name):
        """ Retrieves a list of dictionaries representing types of static files that can be served by views for download
        by the user.

        :param callable_name: Name of method is called to serve static files.

        :return: List of dictionaries.
        """
        return [
            {
                'type': 'bulk import',
                'path_kwargs': {'path': self._get_fdp_import_file_file_path_for_view()},
                'view_name': 'bulk:download_import_file',
                'expected_callable': f'bulk.views.DownloadImportFileView.{callable_name}',
                'view_class': DownloadImportFileView
            },
            {
                'type': 'person photo',
                'path_kwargs': {'path': self._get_person_photo_file_path_for_view()},
                'view_name': 'core:download_person_photo',
                'expected_callable': f'core.views.DownloadPersonPhotoView.{callable_name}',
                'view_class': DownloadPersonPhotoView
            },
            {
                'type': 'attachment',
                'path_kwargs': {'path': self._get_attachment_file_path_for_view()},
                'view_name': 'sourcing:download_attachment',
                'expected_callable': f'sourcing.views.DownloadAttachmentView.{callable_name}',
                'view_class': DownloadAttachmentView
            }
        ]

    def __check_emails_not_in_response(self, email, response_content):
        """ Checks that email addresses with all three suffixes are not appearing in the string representation of the
        HTTP response that was returned through a view.

        :param email: Base email to check for.
        :param response_content: String representation of the HTTP response that was returned.
        :return: Nothing.
        """
        self.assertNotIn('{email}{suffix}'.format(email=email, suffix=self.__without_org_suffix), response_content)
        self.assertNotIn('{email}{suffix}'.format(email=email, suffix=self.__with_org_suffix), response_content)
        self.assertNotIn('{email}{suffix}'.format(email=email, suffix=self.__wrong_org_suffix), response_content)

    def __add_fdp_users(self, fdp_org, other_fdp_org):
        """ Adds the FDP users that will be tested.

        :param fdp_org: FDP organization to which a FDP user can be linked.
        :param other_fdp_org: Another FDP organization to which a FDP user can be linked.
        :return: A tuple:
                    List of IDs of users without FDP organization,
                    list of IDs of users with FDP organization,
                    list of IDs of users with another FDP organization.
        """
        without_org_ids = {}
        with_org_ids = {}
        wrong_org_ids = {}
        # for all user types
        for i, user_role in enumerate(self._user_roles):
            # skip for anonymous user
            if user_role[self._is_anonymous_key]:
                continue
            # email address will contain uniquely identifiable string
            email = (user_role[self._label]).replace(' ', '').lower()
            # create the FDP user in the test database
            without_org_fdp_user = self._create_fdp_user(
                is_host=user_role[self._is_host_key],
                is_administrator=user_role[self._is_administrator_key],
                is_superuser=user_role[self._is_superuser_key],
                email='{email}{withoutorg}@google.com'.format(email=email, i=i, withoutorg=self.__without_org_suffix)
            )
            without_org_ids[email] = without_org_fdp_user.pk
            # create the FDP user in the test database
            with_org_fdp_user = self._create_fdp_user(
                is_host=user_role[self._is_host_key],
                is_administrator=user_role[self._is_administrator_key],
                is_superuser=user_role[self._is_superuser_key],
                email='{email}{withorg}@google.com'.format(email=email, i=i, withorg=self.__with_org_suffix)
            )
            with_org_fdp_user.fdp_organization = fdp_org
            with_org_fdp_user.full_clean()
            with_org_fdp_user.save()
            with_org_ids[email] = with_org_fdp_user.pk
            # create the FDP user in the test database
            other_org_fdp_user = self._create_fdp_user(
                is_host=user_role[self._is_host_key],
                is_administrator=user_role[self._is_administrator_key],
                is_superuser=user_role[self._is_superuser_key],
                email='{email}{wrongorg}@freedobject.com'.format(email=email, i=i, wrongorg=self.__wrong_org_suffix)
            )
            other_org_fdp_user.fdp_organization = other_fdp_org
            other_org_fdp_user.full_clean()
            other_org_fdp_user.save()
            wrong_org_ids[email] = other_org_fdp_user.pk
        return without_org_ids, with_org_ids, wrong_org_ids

    def __get_changelist_response(self, fdp_user):
        """ Retrieves a response after sending a request to the admin changelist view for FDP User.

        :param fdp_user: FDP user sending request.
        :return: String representation of the response.
        """
        return self._get_response_from_get_request(
            fdp_user=fdp_user,
            url=reverse('admin:fdpuser_fdpuser_changelist'),
            expected_status_code=200,
            login_startswith=None
        )

    def __get_change_response(self, fdp_user, expected_status_code, login_startswith, pk):
        """ Retrieves a response when sending a request to the admin change instance view for FDP.

        :param fdp_user: FDP user sending request.
        :param expected_status_code: Expected HTTP status code that is returned in the response.
        :param login_startswith: Url to which response may be redirected. Only used when HTTP status code is 302.
        :param pk: Primary key for model instance to change.
        :return: String representation of the response.
        """
        return self._get_response_from_get_request(
            fdp_user=fdp_user,
            url=reverse('admin:fdpuser_fdpuser_change', args=(pk,)),
            expected_status_code=expected_status_code,
            login_startswith=login_startswith
        )

    def __get_history_response(self, fdp_user, expected_status_code, login_startswith, pk):
        """ Retrieves a response when sending a request to the admin history view for FDP.

        :param fdp_user: FDP user sending request.
        :param expected_status_code: Expected HTTP status code that is returned in the response.
        :param login_startswith: Url to which response may be redirected. Only used when HTTP status code is 302.
        :param pk: Primary key for model instance for which to retrieve history.
        :return: String representation of the response.
        """
        return self._get_response_from_get_request(
            fdp_user=fdp_user,
            url=reverse('admin:fdpuser_fdpuser_history', args=(pk,)),
            expected_status_code=expected_status_code,
            login_startswith=login_startswith
        )

    def __get_delete_response(self, fdp_user, expected_status_code, login_startswith, pk):
        """ Retrieves a response when sending a request to the admin delete instance view for FDP.

        :param fdp_user: FDP user sending request.
        :param expected_status_code: Expected HTTP status code that is returned in the response.
        :param login_startswith: Url to which response may be redirected. Only used when HTTP status code is 302.
        :param pk: Primary key for model instance to delete.
        :return: String representation of the response.
        """
        return self._get_response_from_get_request(
            fdp_user=fdp_user,
            url=reverse('admin:fdpuser_fdpuser_delete', args=(pk,)),
            expected_status_code=expected_status_code,
            login_startswith=login_startswith
        )

    def __delete_password_resets(self):
        """ Removes all password reset records from the test database.

        :return: Nothing.
        """
        PasswordReset.objects.all().delete()
        self.assertEqual(PasswordReset.objects.all().count(), 0)

    def __add_data_for_officer_profile(self):
        """ Add data to create a basic version of the officer profile, including the enabling functionality to download
        all attachments for the profile.

        :return: Nothing.
        """
        # officer (whose profile will be accessed below)
        officer = Person.objects.create(name='Name1', **self._is_law_dict, **self._not_confidential_dict)
        # connection between attachment and officer
        content = Content.objects.create(name='Content1', **self._not_confidential_dict)
        # Use SimpleUploadedFile to populate dummy file for testing download functionality in officer profile
        dummy_file = SimpleUploadedFile("dummy_file.txt", b"This is a test file")
        attachment = Attachment.objects.create(name='dummy', file=dummy_file)
        content.attachments.add(attachment)
        ContentPerson.objects.create(person=officer, content=content)
        # This primary key will be used in tests when referencing self._views
        self.assertNotEqual(self._default_pk, officer.pk)
        self._default_pk = officer.pk

    def __check_perm_escalate(self, user_to_change, user_changing, perm_escalation_dict):
        """ Check the permission escalation for a particular user by a particular user.

        :param user_to_change: User that is being changed during the permission escalation attempt.
        :param user_changing: User that is doing the changing during the permission escalation attempt.
        :param perm_escalation_dict: The dictionary of keyword arguments that will be expanded to define the permission
        escalation in the cleaned data portion of the FdpUserChangeForm.
        :return: Nothing.
        """
        # values for user before permission escalation is attempted
        prev_fdp_organization = user_to_change.fdp_organization
        prev_is_host = user_to_change.is_host
        prev_is_superuser = user_to_change.is_superuser
        # simulate change form
        change_form = FdpUserChangeForm(instance=user_to_change)
        request = self.UserRequest()
        request.user = user_changing
        change_form.request = request
        change_form.cleaned_data = {'email': user_to_change.email, **perm_escalation_dict}
        changed_user = change_form.save(commit=True)
        database_user = FdpUser.objects.get(pk=changed_user.pk)
        # compare values before and after permission escalation attempt
        if prev_fdp_organization is None:
            self.assertTrue(changed_user.fdp_organization is None)
            self.assertTrue(database_user.fdp_organization is None)
        else:
            self.assertEqual(prev_fdp_organization, changed_user.fdp_organization)
            self.assertEqual(prev_fdp_organization, database_user.fdp_organization)
        self.assertEqual(prev_is_host, changed_user.is_host)
        self.assertEqual(prev_is_host, database_user.is_host)
        self.assertEqual(prev_is_superuser, changed_user.is_superuser)
        self.assertEqual(prev_is_superuser, database_user.is_superuser)

    @staticmethod
    def __delete_data_for_officer_profile():
        """ Deletes data that may have been created for the officer profile.

        :return: Nothing.
        """
        ContentPerson.objects.all().delete()
        Content.objects.all().delete()
        Attachment.objects.all().delete()
        Person.objects.all().delete()

    @staticmethod
    def tautology():
        """ Always returns True.

        Used to dynamically add a callable to the user instance, so that when is_verified() is called by the 2FA
        middleware, the user is verified.

        :return: Always true.
        """
        return True

    def __check_azure_user_skips_2fa(self, has_django_auth_backend):
        """ Checks authentication steps for a user who is expected to be authenticated through Azure Active Directory.

        :param has_django_auth_backend: True if Django authentication backend is enabled, false if it is disabled.
        :return: Nothing.
        """
        enable_2fa_txt = 'Enable 2FA'
        azure_user = self._create_fdp_user(email_counter=FdpUser.objects.all().count() + 1, **self._host_admin_dict)
        c = Client(**self._local_client_kwargs)
        # force username/password authentication for newly added user, but 2FA is not yet validated
        c.force_login(user=azure_user, backend=None)
        # confirm user requires 2FA
        try:
            response = self._do_get(c=c, url='/', expected_status_code=403, login_startswith=None)
            self.assertIn(enable_2fa_txt, str(response.content))
        # if Django authentication backend is disabled, then NoReverseMatch is expected for the 'setup' pattern name
        # (since 2FA is not fully configured)
        except NoReverseMatch as err:
            self.assertIn('setup', str(err))
            # exception should only be raised if Django authentication backend is disabled
            self.assertFalse(has_django_auth_backend)
        # change user so that they are externally authenticable, and have a social auth link
        azure_user.only_external_auth = True
        azure_user.save()
        user_social_auth_model = apps.get_model(CONST_AZURE_AUTH_APP, 'UserSocialAuth')
        user_social_auth_model.objects.create(
            user=azure_user,
            uid=str(user_social_auth_model.objects.all().count()),
            provider=AbstractConfiguration.azure_active_directory_provider
        )
        # confirm user does not require 2FA
        response = self._do_get(c=c, url='/', expected_status_code=200, login_startswith=None)
        self.assertNotIn(enable_2fa_txt, str(response.content))
        # change user so that they are a superuser
        azure_user.is_superuser = True
        azure_user.save()
        # confirm user cannot log in
        try:
            self._do_get(c=c, url='/', expected_status_code=403, login_startswith=None)
        # if Django authentication backend is disabled, then NoReverseMatch is expected for the 'setup' pattern name
        # (since 2FA is not fully configured)
        except NoReverseMatch as err:
            self.assertIn('setup', str(err))
            # exception should only be raised if Django authentication backend is disabled
            self.assertFalse(has_django_auth_backend)
        # undo superuser change and reconfirm login is still possible
        azure_user.is_superuser = False
        azure_user.save()
        response = self._do_get(c=c, url='/', expected_status_code=200, login_startswith=None)
        self.assertNotIn(enable_2fa_txt, str(response.content))
        # change user so that they are inactive
        azure_user.is_active = False
        azure_user.save()
        # confirm user cannot log in
        self._do_get(
            c=c,
            url='/',
            expected_status_code=302,
            login_startswith=reverse('two_factor:{n}'.format(n=CONST_LOGIN_URL_NAME))
        )

    def __check_callable_serving_static(self, user, path_kwargs, view_name, expected_callable, view_class):
        """ Checks that the expected method is called while serving a static file for download.

        Used to check how bulk import files, person photos and attachments are served for download in different
        configurations.

        :param user: User requesting to download static file.
        :param path_kwargs: Dictionary of keyword arguments that can be expanded to define the path where the file
        exists. Will be passed as a kwargs parameter in reverse(...).
        :param view_name: Name of view that will be passed as a parameter into reverse(...) to serve file download.
        :param expected_callable: Method that is expected to be called while serving the static file.
        :param view_class: Class of view that will render the response while serving the static file.
        :return: Nothing.
        """
        request = RequestFactory().get(reverse(view_name, kwargs=path_kwargs))
        # add callable to ensure 2FA verification passes
        setattr(user, 'is_verified', self.tautology)
        request.user = user
        with mock_patch(expected_callable) as mocked_callable:
            # instantiate view
            download_view = view_class.as_view()
            # get method for view is called
            download_view(request, **path_kwargs)
            # assert that expected method was called during handling of GET request
            mocked_callable.assert_called_once()

    def __check_for_eula(self, fdp_user, response, url, expected_view):
        """ Checks that a user is first required to agree to a EULA before access a URL that requires it.

        :param fdp_user: User attempting to access URL.
        :param response: Http response object once user has been logged in. Contains "client" attribute for further
        tests.
        :param url: Url that user is attempting to access.
        :param expected_view: View that is expected to render the page that the user is accessing through the URL.
        :return: Nothing.
        """
        eula_txt = 'end user license agreement'
        all_kwargs = {'url': url, 'login_startswith': None}
        success_kwargs = {'expected_status_code': 200, **all_kwargs}
        forbidden_kwargs = {'expected_status_code': 403, **all_kwargs}
        # ensure that at start of check, user does not have any EULA agreement
        fdp_user.agreed_to_eula = None
        fdp_user.full_clean()
        fdp_user.save()
        with self.settings(FDP_EULA_SPLASH_ENABLE=False):
            self.assertFalse(AbstractConfiguration.eula_splash_enabled())
            response = self._do_get(c=response.client, **success_kwargs)
            self.assertNotIn(eula_txt, str(response.content))
            self._assert_class_based_view(response=response, expected_view=expected_view)
            logger.debug(f'With EULA disabled, and without agreeing to EULA, user can access: {url}')
        self.assertTrue(AbstractConfiguration.eula_splash_enabled())
        response = self._do_get(c=response.client, **forbidden_kwargs)
        self.assertIn(eula_txt, str(response.content))
        self.assertEqual(response.template_name, 'fdpuser/templates/eula_required.html')
        logger.debug(f'With EULA enabled, user must first agree to EULA before accessing: {url}')
        fdp_user.agreed_to_eula = now()
        fdp_user.full_clean()
        fdp_user.save()
        response = self._do_get(c=response.client, **success_kwargs)
        self.assertNotIn(eula_txt, str(response.content))
        self._assert_class_based_view(response=response, expected_view=expected_view)
        logger.debug(f'With EULA enabled, once agreeing to EULA, user can access: {url}')

    @local_test_settings_required
    def test_access_to_views(self):
        """ Test access to views:
                (a) For all user types

        :return: Nothing.
        """
        logger.debug(_('\nStarting test for access to views'))
        self.__add_data_for_officer_profile()
        # number of users already in database
        num_of_users = FdpUser.objects.all().count() + 1
        for i, user_role in enumerate(self._user_roles):
            # cycle through all views to test
            for view_to_test in self._views:
                # build the view using data that was just added
                if not view_to_test[self._url_key]:
                    view_to_test[self._url_key] = reverse(
                        view_to_test[self._url_reverse_viewname_key],
                        kwargs={view_to_test[self._url_reverse_kwargs_pk_key]: self._default_pk}
                    )
                fdp_user = None
                response = None
                view_label = view_to_test[self._label]
                client = Client(**self._local_client_kwargs)
                client.logout()
                # create user and login for authenticated users
                if not user_role[self._is_anonymous_key]:
                    # create the FDP user in the test database
                    fdp_user = self._create_fdp_user(
                        is_host=user_role[self._is_host_key],
                        is_administrator=user_role[self._is_administrator_key],
                        is_superuser=user_role[self._is_superuser_key],
                        email_counter=i + num_of_users
                    )
                    two_factor = self._create_2fa_record(user=fdp_user)
                    # log in user
                    response = self._do_login(
                        c=client,
                        username=fdp_user.email,
                        password=self._password,
                        two_factor=two_factor,
                        login_status_code=200,
                        two_factor_status_code=200,
                        will_login_succeed=True
                    )
                # all users can access any view where anonymous access is granted
                if view_to_test[self._is_anonymous_accessible_key]:
                    expected_status_code = 200
                # authenticated user can access any view where staff access is granted (and not change password)
                elif (not user_role[self._is_anonymous_key]) and view_to_test[self._is_staff_accessible_key] \
                        and not (view_to_test[self._url_key] in (
                            reverse('fdpuser:change_password'), reverse('fdpuser:reset_2fa'),)
                ):
                    expected_status_code = 200
                # admin user can access any view where admin is granted (and not change password)
                elif (not user_role[self._is_anonymous_key]) and user_role[self._is_administrator_key] \
                        and view_to_test[self._is_admin_accessible_key] \
                        and not (view_to_test[self._url_key] in (
                        reverse('fdpuser:change_password'), reverse('fdpuser:reset_2fa'),)
                ):
                    expected_status_code = 200
                # super user can access any view where admin is granted (and not change password)
                elif (not user_role[self._is_anonymous_key]) and (not user_role[self._is_administrator_key]) \
                        and user_role[self._is_superuser_key] \
                        and not (view_to_test[self._url_key] in (
                        reverse('fdpuser:change_password'), reverse('fdpuser:reset_2fa'),)
                ):
                    expected_status_code = 200
                # otherwise no access
                else:
                    expected_status_code = 302
                change_or_reset = (reverse('fdpuser:change_password'), reverse('fdpuser:reset_2fa'))
                login_startswith = reverse('password_reset_done') \
                    if view_to_test[self._url_key] in change_or_reset \
                    else (
                        reverse(settings.LOGIN_URL) if not str(view_to_test[self._url_key]).startswith('/admin')
                        else reverse('admin:login')
                )
                logger.debug(_('\nStarting sub-test for {v} for a {u} with expected status code {s}{r}'.format(
                    v=view_label,
                    u=user_role,
                    s=expected_status_code,
                    r=_(' with redirect to {u}'.format(u=login_startswith)) if expected_status_code == 302 else ''
                )))
                try:
                    self._do_get(
                        c=response.client if response else client,
                        url=view_to_test[self._url_key],
                        expected_status_code=expected_status_code,
                        login_startswith=login_startswith
                    )
                except AttributeError as err:
                    # anonymous user attempting to reset 2FA
                    if str(err) == '\'AnonymousUser\' object has no attribute \'email\'' \
                            and user_role[self._is_anonymous_key] \
                            and view_to_test[self._url_key] == reverse('fdpuser:reset_2fa'):
                        pass
                    else:
                        raise err
                except Exception as err:
                    # anonymous user attempting to reset password
                    if str(err) == 'Password reset rate limits have been reached' \
                            and user_role[self._is_anonymous_key] \
                            and view_to_test[self._url_key] == reverse('fdpuser:change_password'):
                        pass
                    else:
                        raise err
                # logout authenticated users and delete them
                if not user_role[self._is_anonymous_key]:
                    client.logout()
                    fdp_user.delete()
        self.__delete_data_for_officer_profile()
        logger.debug(_('\nSuccessfully finished test for access to views\n\n'))

    @local_test_settings_required
    def test_password_reset_throttling(self):
        """ Test throttling for password reset
                (a) For all user types based on IP address
                (b) For all user types based on user

        :return: Nothing.
        """
        logger.debug(_('\nStarting test for password reset and password change throttling'))
        max_password_resets = settings.MAX_PWD_RESET_PER_IP_ADDRESS_PER_DAY
        max_password_changes = settings.MAX_PWD_RESET_PER_USER_PER_DAY
        url = reverse('password_reset')
        done_url = reverse('password_reset_done')
        chng_url = reverse('fdpuser:change_password')
        # test resetting passwords for all user types
        for j, user_role in enumerate(self._user_roles):
            client = Client(**self._local_client_kwargs)
            client.logout()
            # skip "creating" the anonymous user
            if not user_role[self._is_anonymous_key]:
                # test resetting any password
                logger.debug(_('\nStarting sub-test to reset password '
                        'for {u} by anonymous user'.format(u=user_role[self._label])))
                data = {}
                self.__delete_password_resets()
                # prior to each password reset attempt, create the user
                for i in range(max_password_resets):
                    # create the FDP user in the test database
                    fdp_user = self._create_fdp_user(
                        is_host=user_role[self._is_host_key],
                        is_administrator=user_role[self._is_administrator_key],
                        is_superuser=user_role[self._is_superuser_key],
                        email='donotreply.{j}.{i}@google.com'.format(j=j, i=i)
                    )
                    data = {
                        'email': fdp_user.email,
                        'recaptcha_response_field': 'PASSED',
                        'g-recaptcha-response': 'PASSED'
                    }
                    two_factor = self._create_2fa_record(user=fdp_user)
                    # try login that is successful
                    self._do_login(
                        c=client,
                        username=fdp_user.email,
                        password=self._password,
                        two_factor=two_factor,
                        login_status_code=200,
                        two_factor_status_code=200,
                        will_login_succeed=True
                    )
                    client.logout()
                    self._do_get(c=client, url=url, expected_status_code=200, login_startswith=None)
                    self._do_post(c=client, url=url, data=data, expected_status_code=302, login_startswith=done_url)
                    logger.debug(_('Password reset #{i} is successful'.format(i=i + 1)))
                    self.assertEqual(PasswordReset.objects.all().count(), i + 1)
                    self.assertTrue(PasswordReset.objects.all().order_by('-pk')[0].ip_address)
                # assert that we've reached the limit for password resets
                self.assertEqual(PasswordReset.objects.all().count(), max_password_resets)
                # no more password resets should be allowed (will fail silently)
                self._do_get(c=client, url=url, expected_status_code=200, login_startswith=None)
                self._do_post(c=client, url=url, data=data, expected_status_code=302, login_startswith=done_url)
                # assert that no more password resets were made
                self.assertEqual(PasswordReset.objects.all().count(), max_password_resets)
                logger.debug(_('Preceding password reset was successfully blocked'))
                PasswordReset.objects.all().delete()
                self.assertEqual(PasswordReset.objects.all().count(), 0)
                # test changing own password
                # create the FDP user in the test database
                logger.debug(_('\nStarting sub-test for {u} to change their own password'.format(u=user_role[self._label])))
                fdp_user = self._create_fdp_user(
                    is_host=user_role[self._is_host_key],
                    is_administrator=user_role[self._is_administrator_key],
                    is_superuser=user_role[self._is_superuser_key],
                    email_counter=j + FdpUser.objects.all().count() + 1
                )
                # prior to each password reset attempt, create the user
                for k in range(max_password_changes):
                    two_factor = self._create_2fa_record(user=fdp_user)
                    # try login that is successful
                    self._do_login(
                        c=client,
                        username=fdp_user.email,
                        password=self._password,
                        two_factor=two_factor,
                        login_status_code=200,
                        two_factor_status_code=200,
                        will_login_succeed=True
                    )
                    self._do_get(c=client, url=chng_url, expected_status_code=302, login_startswith=url)
                    logger.debug(_('Password change #{k} is successful'.format(k=k + 1)))
                    fdp_user.set_password(self._password)
                    fdp_user.save()
                # this login should fail
                two_factor = self._create_2fa_record(user=fdp_user)
                self._do_login(
                    c=client,
                    username=fdp_user.email,
                    password=self._password,
                    two_factor=two_factor,
                    login_status_code=200,
                    two_factor_status_code=200,
                    will_login_succeed=True
                )
                try:
                    self._do_get(c=client, url=chng_url, expected_status_code=302, login_startswith=url)
                    raise Exception(_('Should never arrive here, since above password change should fail'))
                except Exception as err:
                    if not str(err) == 'Password reset rate limits have been reached':
                        raise Exception(_('Should not arrive here, but an unexpected problem occurred'))
                logger.debug(_('Following password change was successfully blocked'))
        self.__delete_password_resets()
        FdpUser.objects.all().delete()
        self.assertEqual(FdpUser.objects.all().count(), 0)
        logger.debug(_('\nSuccessfully finished test for password reset and password change throttling\n\n'))

    @local_test_settings_required
    def test_guest_admin_user_access(self):
        """ Test guest administrators accessing users for all permutations user roles.

        :return: Nothing
        """
        admin_index = reverse('admin:index')
        logger.debug(_('\nStarting test for guest administrators to access users for all permutations of user roles'))
        fdp_org_1 = FdpOrganization.objects.create(name='FdpOrganization1FdpUser')
        fdp_org_2 = FdpOrganization.objects.create(name='FdpOrganization2FdpUser')
        guest_admin_without_org = self._create_fdp_user(email='donotreply001@google.com', **self._guest_admin_dict)
        guest_admin_with_org = self._create_fdp_user(email='donotreply002@google.com', **self._guest_admin_dict)
        guest_admin_with_org.fdp_organization = fdp_org_1
        guest_admin_with_org.full_clean()
        guest_admin_with_org.save()
        without_org_ids, with_org_ids, wrong_org_ids = self.__add_fdp_users(fdp_org=fdp_org_1, other_fdp_org=fdp_org_2)
        without_org_content = self.__get_changelist_response(fdp_user=guest_admin_without_org)
        with_org_content = self.__get_changelist_response(fdp_user=guest_admin_with_org)
        # test for all user types
        for i, user_role in enumerate(self._user_roles):
            # skip for anonymous user
            if user_role[self._is_anonymous_key]:
                continue
            # email address will contain uniquely identifiable string
            email = (user_role[self._label]).replace(' ', '').lower()
            # for Guest Administrator without FDP organization
            logger.debug(
                'Starting changelist view sub-test for {n} for guest administrator without a FDP organization'.format(
                    n=user_role[self._label]
                )
            )
            # only non-host and non-superuser
            if (not user_role[self._is_host_key]) and (not user_role[self._is_superuser_key]):
                self.assertIn(
                    '{email}{suffix}'.format(email=email, suffix=self.__without_org_suffix),
                    without_org_content
                )
            else:
                self.__check_emails_not_in_response(email=email, response_content=without_org_content)
            # for Guest Administrator with FDP organization
            logger.debug(
                'Starting changelist view sub-test for {n} for guest administrator with a FDP organization'.format(
                    n=user_role[self._label]
                )
            )
            # only non-host and non-superuser
            if (not user_role[self._is_host_key]) and (not user_role[self._is_superuser_key]):
                self.assertIn('{email}{suffix}'.format(email=email, suffix=self.__with_org_suffix), with_org_content)
            else:
                self.__check_emails_not_in_response(email=email, response_content=with_org_content)
            # for Guest Administrator without FDP organization
            logger.debug(
                'Starting change instance view sub-test for {n} for '
                'guest administrator without a FDP organization'.format(n=user_role[self._label])
            )
            # only non-host and non-superuser
            if (not user_role[self._is_host_key]) and (not user_role[self._is_superuser_key]):
                expected_status_code = 200
                login_startswith = None
            else:
                expected_status_code = 302
                login_startswith = admin_index
            self.__get_change_response(
                fdp_user=guest_admin_without_org, expected_status_code=expected_status_code,
                login_startswith=login_startswith, pk=without_org_ids[email]
            )
            self.__get_change_response(
                fdp_user=guest_admin_without_org, expected_status_code=302,
                login_startswith=admin_index, pk=with_org_ids[email]
            )
            self.__get_change_response(
                fdp_user=guest_admin_without_org, expected_status_code=302,
                login_startswith=admin_index, pk=wrong_org_ids[email]
            )
            # for Guest Administrator with FDP organization
            logger.debug(
                'Starting change instance view sub-test for {n} for guest administrator with a FDP organization'.format(
                    n=user_role[self._label]
                )
            )
            # only non-host and non-superuser
            if (not user_role[self._is_host_key]) and (not user_role[self._is_superuser_key]):
                expected_status_code = 200
                login_startswith = None
            else:
                expected_status_code = 302
                login_startswith = admin_index
            self.__get_change_response(
                fdp_user=guest_admin_with_org, expected_status_code=expected_status_code,
                login_startswith=login_startswith, pk=with_org_ids[email]
            )
            self.__get_change_response(
                fdp_user=guest_admin_with_org, expected_status_code=302,
                login_startswith=admin_index, pk=without_org_ids[email]
            )
            self.__get_change_response(
                fdp_user=guest_admin_with_org, expected_status_code=302,
                login_startswith=admin_index, pk=wrong_org_ids[email]
            )
            # for Guest Administrator without FDP organization
            logger.debug(
                'Starting history view sub-test for {n} for guest administrator without a FDP organization'.format(
                    n=user_role[self._label]
                )
            )
            # only non-host and non-superuser
            if (not user_role[self._is_host_key]) and (not user_role[self._is_superuser_key]):
                # guest administrators cannot access history
                expected_status_code = 403
                login_startswith = None
            else:
                expected_status_code = 403
                login_startswith = admin_index
            self.__get_history_response(
                fdp_user=guest_admin_without_org, expected_status_code=expected_status_code,
                login_startswith=login_startswith, pk=without_org_ids[email]
            )
            self.__get_history_response(
                fdp_user=guest_admin_without_org, expected_status_code=403,
                login_startswith=admin_index, pk=with_org_ids[email]
            )
            self.__get_history_response(
                fdp_user=guest_admin_without_org, expected_status_code=403,
                login_startswith=admin_index, pk=wrong_org_ids[email]
            )
            # for Guest Administrator with FDP organization
            logger.debug(
                'Starting history view sub-test for {n} for guest administrator with a FDP organization'.format(
                    n=user_role[self._label]
                )
            )
            # only non-host and non-superuser
            if (not user_role[self._is_host_key]) and (not user_role[self._is_superuser_key]):
                # guest administrators cannot access history
                expected_status_code = 403
                login_startswith = None
            else:
                expected_status_code = 403
                login_startswith = admin_index
            self.__get_history_response(
                fdp_user=guest_admin_with_org, expected_status_code=expected_status_code,
                login_startswith=login_startswith, pk=with_org_ids[email]
            )
            self.__get_history_response(
                fdp_user=guest_admin_with_org, expected_status_code=403,
                login_startswith=admin_index, pk=without_org_ids[email]
            )
            self.__get_history_response(
                fdp_user=guest_admin_with_org, expected_status_code=403,
                login_startswith=admin_index, pk=wrong_org_ids[email]
            )
            # for Guest Administrator without FDP organization
            logger.debug(
                'Starting delete instance view sub-test for {n} '
                'for guest administrator without a FDP organization'.format(
                    n=user_role[self._label]
                )
            )
            # only non-host and non-superuser
            if (not user_role[self._is_host_key]) and (not user_role[self._is_superuser_key]):
                expected_status_code = 200
                login_startswith = None
            else:
                expected_status_code = 302
                login_startswith = admin_index
            self.__get_delete_response(
                fdp_user=guest_admin_without_org, expected_status_code=expected_status_code,
                login_startswith=login_startswith, pk=without_org_ids[email]
            )
            self.__get_delete_response(
                fdp_user=guest_admin_without_org, expected_status_code=302,
                login_startswith=admin_index, pk=with_org_ids[email]
            )
            self.__get_delete_response(
                fdp_user=guest_admin_without_org, expected_status_code=302,
                login_startswith=admin_index, pk=wrong_org_ids[email]
            )
            # for Guest Administrator with FDP organization
            logger.debug(
                'Starting delete instance view sub-test for {n} for guest administrator with a FDP organization'.format(
                    n=user_role[self._label]
                )
            )
            # only non-host and non-superuser
            if (not user_role[self._is_host_key]) and (not user_role[self._is_superuser_key]):
                expected_status_code = 200
                login_startswith = None
            else:
                expected_status_code = 302
                login_startswith = admin_index
            self.__get_delete_response(
                fdp_user=guest_admin_with_org, expected_status_code=expected_status_code,
                login_startswith=login_startswith, pk=with_org_ids[email]
            )
            self.__get_delete_response(
                fdp_user=guest_admin_with_org, expected_status_code=302,
                login_startswith=admin_index, pk=without_org_ids[email]
            )
            self.__get_delete_response(
                fdp_user=guest_admin_with_org, expected_status_code=302,
                login_startswith=admin_index, pk=wrong_org_ids[email]
            )
        logger.debug(_('\nSuccessfully finished test for guest administrators to '
                'access users for all permutations of user roles\n\n'))

    @local_test_settings_required
    def test_guest_admin_new_user(self):
        """ Test guest administrators creating new users.

        Ensure that FDP organization of new user matches FDP organization of guest administrator.

        :return: Nothing
        """
        logger.debug(_('\nStarting test for guest administrators to create new users'))
        fdp_org = FdpOrganization.objects.create(name='FdpOrganization3FdpUser')
        num_of_users = FdpUser.objects.all().count()
        guest_admin_without_org = self._create_fdp_user(email_counter=num_of_users + 1, **self._guest_admin_dict)
        guest_admin_with_org = self._create_fdp_user(email_counter=num_of_users + 2, **self._guest_admin_dict)
        guest_admin_with_org.fdp_organization = fdp_org
        guest_admin_with_org.full_clean()
        guest_admin_with_org.save()
        # for Guest Administrator without FDP organization
        logger.debug(_('Starting sub-test for guest admin without FDP organization to create new user '
                '(check if new user\'s organization matches)'))
        email = 'donotreply0@google.com'
        without_org_create_form = FdpUserCreationForm(instance=FdpUser(email=email))
        without_org_request = self.UserRequest()
        without_org_request.user = guest_admin_without_org
        without_org_create_form.request = without_org_request
        without_org_create_form.cleaned_data = {'email': email, 'password1': self._password}
        without_org_created_user = without_org_create_form.save(commit=True)
        self.assertEqual(without_org_created_user.fdp_organization, guest_admin_without_org.fdp_organization)
        # for Guest Administrator without FDP organization
        logger.debug(_('Starting sub-test for guest admin with FDP organization to create new user '
                '(check if new user\'s organization matches)'))
        email = 'donotreply00@google.com'
        with_org_create_form = FdpUserCreationForm(instance=FdpUser(email=email))
        with_org_request = self.UserRequest()
        with_org_request.user = guest_admin_with_org
        with_org_create_form.request = with_org_request
        with_org_create_form.cleaned_data = {'email': email, 'password1': self._password}
        with_org_created_user = with_org_create_form.save(commit=True)
        self.assertEqual(with_org_created_user.fdp_organization, guest_admin_with_org.fdp_organization)
        logger.debug(_('\nSuccessfully finished test for guest administrators to create new users\n\n'))

    @local_test_settings_required
    def test_admin_permission_escalation(self):
        """ Test administrators escalating permissions.

        :return: Nothing
        """
        logger.debug(_('\nStarting test for administrators to escalate permissions'))
        fdp_org = FdpOrganization.objects.create(name='FdpOrganization4FdpUser')
        other_fdp_org = FdpOrganization.objects.create(name='FdpOrganization5FdpUser')
        num_of_users = FdpUser.objects.all().count()
        base_perm_escalate_dict = {'is_host': True, 'is_administrator': True, 'is_superuser': True, 'is_active': True}
        # create guest admins with and without organizations
        guest_admin_no_org = self._create_fdp_user(email_counter=num_of_users + 1, **self._guest_admin_dict)
        guest_admin_yes_org = self._create_fdp_user(email_counter=num_of_users + 2, **self._guest_admin_dict)
        guest_admin_yes_org.fdp_organization = fdp_org
        guest_admin_yes_org.full_clean()
        guest_admin_yes_org.save()
        # create users who are guest admins also that can be changed by the original guest admins
        no_org_user = self._create_fdp_user(email_counter=num_of_users + 3, **self._guest_admin_dict)
        yes_org_user = self._create_fdp_user(email_counter=num_of_users + 4, **self._guest_admin_dict)
        yes_org_user.fdp_organization = fdp_org
        yes_org_user.full_clean()
        yes_org_user.save()
        # create host admin
        host_admin = self._create_fdp_user(email_counter=num_of_users + 5, **self._host_admin_dict)
        # create users who are host admins also that can be changed by the original host admins
        host_user = self._create_fdp_user(email_counter=num_of_users + 6, **self._host_admin_dict)
        # change guest admin user without organization using another guest admin user without organization
        logger.debug(_('Starting sub-test for guest admin without FDP organization escalating another guest admin user\'s '
                'permissions and assigning them FDP organization'))
        self.__check_perm_escalate(
            user_to_change=no_org_user,
            user_changing=guest_admin_no_org,
            perm_escalation_dict={**{'fdp_organization': fdp_org}, **base_perm_escalate_dict}
        )
        # change guest admin user with organization using another guest admin user with organization
        logger.debug(_('Starting sub-test for guest admin with FDP organization escalating another guest admin user\'s '
                'permissions and assigning them another FDP organization'))
        self.__check_perm_escalate(
            user_to_change=yes_org_user,
            user_changing=guest_admin_yes_org,
            perm_escalation_dict={**{'fdp_organization': other_fdp_org}, **base_perm_escalate_dict}
        )
        # change host admin user without organization using another host admin user without organization
        logger.debug(_('Starting sub-test for host admin without FDP organization escalating another host admin user\'s '
                'permissions'))
        self.__check_perm_escalate(
            user_to_change=host_user,
            user_changing=host_admin,
            perm_escalation_dict={**{'fdp_organization': None}, **base_perm_escalate_dict}
        )
        logger.debug(_('\nSuccessfully finished test for administrators to escalate permissions\n\n'))

    @local_test_settings_required
    def test_guest_admin_host_only_access(self):
        """ Test guest administrators accessing host-only views.

        :return: Nothing
        """
        logger.debug(_('\nStarting test for guest administrators to access host-only views'))
        num_of_users = FdpUser.objects.all().count()
        fdp_org = FdpOrganization.objects.create(name='FdpOrganization6FdpUser')
        guest_admin = self._create_fdp_user(email_counter=num_of_users + 1, **self._guest_admin_dict)
        guest_admin.fdp_organization = fdp_org
        guest_admin.full_clean()
        guest_admin.save()
        # cycle through all models to test
        for model_to_test in [
            PasswordReset, FdpOrganization, FdpCSPReport,
            BulkImport, FdpImportFile, FdpImportMapping, FdpImportRun,
            FileSource,
            AccessLog, AccessAttempt,
            PhoneDevice,
            CommandSearch, CommandView, OfficerSearch, OfficerView,
            VerifyContentCase, VerifyPerson, VerifyType
        ] + (
            [] if CONST_AZURE_AUTH_APP not in settings.INSTALLED_APPS else [
                #: Django Social Auth package may not be installed
                #: See https://python-social-auth.readthedocs.io/en/latest/configuration/django.html
                apps.get_model(CONST_AZURE_AUTH_APP, 'Association'),
                apps.get_model(CONST_AZURE_AUTH_APP, 'None'),
                apps.get_model(CONST_AZURE_AUTH_APP, 'UserSocialAuth'),
            ]
        ):
            url = reverse(
                'admin:{app}_{model_to_test}_changelist'.format(
                    app=model_to_test._meta.app_label,
                    model_to_test=model_to_test._meta.model_name
                )
            )
            logger.debug(
                'Starting host-only view access sub-test for {n} for guest administrator'.format(
                    n=model_to_test._meta.model_name
                )
            )
            self._get_response_from_get_request(
                fdp_user=guest_admin,
                url=url,
                expected_status_code=403,
                login_startswith=None
            )
        logger.debug(_('\nSuccessfully finished test for guest administrators to access host-only views\n\n'))

    @local_test_settings_required
    def test_local_dev_configuration(self):
        """ Test login view, 2FA, URL patterns and file serving for a configuration that is intended for a local
        development environment.

        :return: Nothing.
        """
        logger.debug(_('\nStarting test for login view, 2FA, URL patterns and '
                'file serving for local development configuration'))
        # test is only relevant for local development configuration
        self.assertTrue(AbstractConfiguration.is_using_local_configuration())
        self.assertFalse(AbstractConfiguration.is_using_azure_configuration())
        logger.debug('Checking that view for login is from Django Two-Factor Authentication package')
        c = Client(**self._local_client_kwargs)
        # redirect to login expected
        response = self._do_get(
            c=c,
            url='/',
            expected_status_code=302,
            login_startswith=reverse('two_factor:{n}'.format(n=CONST_LOGIN_URL_NAME))
        )
        # follow redirect
        response = self._do_get(c=response.client, url=response.url, expected_status_code=200, login_startswith=None)
        # assert that the default 2FA Login view is used to receive username and password
        self._assert_class_based_view(response=response, expected_view=LoginView)
        logger.debug('Checking that 2FA is encountered after Django authentication with username and password')
        host_admin = self._create_fdp_user(email_counter=FdpUser.objects.all().count() + 1, **self._host_admin_dict)
        user_kwargs = {'username': host_admin.email, 'password': self._password, 'login_status_code': 200}
        self._create_2fa_record(user=host_admin)
        response = self._do_django_username_password_authentication(c=response.client, **user_kwargs)
        # default 2FA Login view is expected for OTP step
        self._assert_2fa_step_in_login_view(response=response, expected_view=LoginView)
        logger.debug('Checking that social-auth login is not defined')
        self.assertRaises(
            NoReverseMatch,
            reverse,
            'social:begin',
            kwargs={'args': [AbstractConfiguration.azure_active_directory_provider]}
        )
        for static_file_type in self.__get_static_file_types(callable_name='serve_static_file'):
            logger.debug('Checking that {t} files are served '
                  'using serve_static_file(...) method'.format(t=static_file_type['type']))
            self.__check_callable_serving_static(
                user=host_admin,
                path_kwargs=static_file_type['path_kwargs'],
                view_name=static_file_type['view_name'],
                expected_callable=static_file_type['expected_callable'],
                view_class=static_file_type['view_class']
            )
        logger.debug('Checking that users with only_external_auth=True cannot log in with username and password')
        host_admin.only_external_auth = True
        host_admin.save()
        response = self._do_django_username_password_authentication(c=response.client, **user_kwargs)
        # default 2FA Login view is expected for username/password step
        self._assert_username_and_password_step_in_login_view(response=response, expected_view=LoginView)
        logger.debug('Checking that 2FA is enforced for the Admin site')
        self.assertEqual(admin.site.__class__, AdminSiteOTPRequired)
        logger.debug(_('\nSuccessfully finished test for '
                'login view, 2FA, URL patterns and file serving for local development configuration\n\n'))

    @azure_test_settings_required
    def test_azure_configuration(self):
        """ Test login view, 2FA, URL patterns and file serving for a configuration that is intended for a
        Microsoft Azure environment.

        User authentication occurs through BOTH the Django backend and Azure Active Directory.

        Files are served through the Azure mechanism only.

        :return: Nothing.
        """
        logger.debug(_('\nStarting test for login view, 2FA, URL patterns and '
                'file serving for Microsoft Azure configuration'))
        # test is only relevant for Microsoft Azure configuration
        self.assertFalse(AbstractConfiguration.is_using_local_configuration())
        self.assertTrue(AbstractConfiguration.is_using_azure_configuration())
        self.assertTrue(AbstractConfiguration.can_do_azure_active_directory())
        self.assertFalse(AbstractConfiguration.use_only_azure_active_directory())
        logger.debug('Checking that view for login is from custom extension of Django Two-Factor Authentication package')
        c = Client(**self._local_client_kwargs)
        # redirect to login expected
        response = self._do_get(
            c=c,
            url='/',
            expected_status_code=302,
            login_startswith=reverse('two_factor:{n}'.format(n=CONST_LOGIN_URL_NAME))
        )
        # follow redirect
        response = self._do_get(c=response.client, url=response.url, expected_status_code=200, login_startswith=None)
        # assert that the default 2FA Login view is used to receive username and password
        self._assert_class_based_view(response=response, expected_view=FdpLoginView)
        logger.debug('Checking that 2FA is encountered after Django authentication with username and password')
        host_admin = self._create_fdp_user(email_counter=FdpUser.objects.all().count() + 1, **self._host_admin_dict)
        # user is authenticable by Django backend
        self.assertFalse(FdpUser.is_user_azure_authenticated(user=host_admin))
        user_kwargs = {'username': host_admin.email, 'password': self._password, 'login_status_code': 200}
        self._create_2fa_record(user=host_admin)
        response = self._do_django_username_password_authentication(c=response.client, **user_kwargs)
        self.assertEqual(response.status_code, 200)
        # default 2FA Login view is expected for OTP step
        self._assert_2fa_step_in_login_view(response=response, expected_view=FdpLoginView)
        logger.debug('Checking that social-auth login is defined')
        self.assertIsNotNone(reverse('social:begin', args=[AbstractConfiguration.azure_active_directory_provider]))
        for static_file_type in self.__get_static_file_types(callable_name='serve_azure_storage_static_file'):
            logger.debug('Checking that {t} files are served '
                  'using serve_azure_storage_static_file(...) method'.format(t=static_file_type['type']))
            self.__check_callable_serving_static(
                user=host_admin,
                path_kwargs=static_file_type['path_kwargs'],
                view_name=static_file_type['view_name'],
                expected_callable=static_file_type['expected_callable'],
                view_class=static_file_type['view_class']
            )
        logger.debug('Checking that users with only_external_auth=True cannot log in with username and password')
        host_admin.only_external_auth = True
        host_admin.save()
        response = self._do_django_username_password_authentication(c=response.client, **user_kwargs)
        # default 2FA Login view is expected for username/password step
        self._assert_username_and_password_step_in_login_view(response=response, expected_view=FdpLoginView)
        logger.debug('Checking that 2FA is enforced for the Admin site')
        self.assertEqual(admin.site.__class__, AdminSiteOTPRequired)
        logger.debug('Checking that Azure users skip 2FA step')
        self.__check_azure_user_skips_2fa(has_django_auth_backend=True)
        logger.debug(_('\nSuccessfully finished test for '
                'login view, 2FA, URL patterns and file serving for Microsoft Azure configuration\n\n'))

    @azure_only_test_settings_required
    def test_azure_only_configuration(self):
        """ Test login view, 2FA, URL patterns and file serving for a configuration that is intended for a
        Microsoft Azure environment.

        User authentication occurs through ONLY Azure Active Directory.

        Files are served through the Azure mechanism only.

        :return: Nothing.
        """
        logger.debug(_('\nStarting test for login view, 2FA, URL patterns and '
                'file serving for "only" Microsoft Azure configuration'))
        # test is only relevant for "only" Microsoft Azure configuration
        self.assertFalse(AbstractConfiguration.is_using_local_configuration())
        self.assertTrue(AbstractConfiguration.is_using_azure_configuration())
        self.assertTrue(AbstractConfiguration.can_do_azure_active_directory())
        self.assertTrue(AbstractConfiguration.use_only_azure_active_directory())
        logger.debug('Checking that view for login redirects to social auth with Azure Active Directory provider')
        c = Client(**self._local_client_kwargs)
        # redirect to login expected, which is itself a redirect view
        response = self._do_get(
            c=c,
            url='/',
            expected_status_code=302,
            login_startswith=reverse('two_factor:{n}'.format(n=CONST_LOGIN_URL_NAME))
        )
        # redirect to social auth login expected
        response = self._do_get(
            c=response.client,
            url=response.url,
            expected_status_code=302,
            login_startswith=reverse('social:begin', args=[AbstractConfiguration.azure_active_directory_provider])
        )
        self._assert_class_based_view(response=response, expected_view=RedirectView)
        logger.debug('Checking that non-Azure users cannot log in')
        host_admin = self._create_fdp_user(email_counter=FdpUser.objects.all().count() + 1, **self._host_admin_dict)
        self.assertFalse(FdpUser.is_user_azure_authenticated(user=host_admin))
        self._create_2fa_record(user=host_admin)
        response = self.__verify_user_cannot_log_in(c=response.client, user=host_admin)
        logger.debug('Checking that social-auth login is defined')
        self.assertIsNotNone(reverse('social:begin', args=[AbstractConfiguration.azure_active_directory_provider]))
        for static_file_type in self.__get_static_file_types(callable_name='serve_azure_storage_static_file'):
            logger.debug('Checking that {t} files are served '
                  'using serve_azure_storage_static_file(...) method'.format(t=static_file_type['type']))
            self.__check_callable_serving_static(
                user=host_admin,
                path_kwargs=static_file_type['path_kwargs'],
                view_name=static_file_type['view_name'],
                expected_callable=static_file_type['expected_callable'],
                view_class=static_file_type['view_class']
            )
        logger.debug('Checking that users with only_external_auth=True cannot log in with username and password')
        host_admin.only_external_auth = True
        host_admin.save()
        response = self.__verify_user_cannot_log_in(c=response.client, user=host_admin)
        logger.debug('Checking that Django Two-Factor Authentication profile is not defined')
        self._do_get(
            c=response.client,
            url=reverse('two_factor:{p}'.format(p=CONST_TWO_FACTOR_PROFILE_URL_NAME)),
            expected_status_code=404,
            login_startswith=None
        )
        logger.debug('Checking that 2FA is enforced for the Admin site')
        self.assertEqual(admin.site.__class__, AdminSiteOTPRequired)
        logger.debug('Checking that Azure users skip 2FA step')
        self.__check_azure_user_skips_2fa(has_django_auth_backend=False)
        logger.debug(_('\nSuccessfully finished test for '
                'login view, 2FA, URL patterns and file serving for "only" Microsoft Azure configuration\n\n'))

    @local_test_settings_required
    def test_axes_redacts_attempted_passwords(self):
        """Test to check that plain-text password attempts aren't stored by Axes in access attempts records.
        """
        logger.debug(_('\nStarting test for Axes redacts attempted passwords in logs'))

        def axes_record_contains(value: str, record: AccessAttempt) -> bool:
            """Return True if given string found in an AxesAttempt record. Iterates through all attributes of a given
            object.

            :param value: String to search for
            :type value: str
            :param record: AxesAttempt record
            :type record: object
            :return: True if the string is found, False if not
            :rtype: bool
            """
            for element in record.__dict__.keys():
                try:
                    if value in record.__dict__[element]:
                        return True
                except TypeError:
                    pass
            return False

        username = secrets.token_urlsafe().replace('-', '').replace('_', '') + "@example.com"
        password = secrets.token_urlsafe().replace('-', '').replace('_', '')
        client = Client(**self._local_client_kwargs)
        response = self._do_django_username_password_authentication(
            c=client,
            username=username,
            password=password,
            login_status_code=200
        )

        axes_attempt_record = AccessAttempt.objects.all()[0]

        if not axes_record_contains(username, axes_attempt_record):
            raise Exception("Username not found in Axes attempt record. Can't complete test.")

        self.assertTrue(not axes_record_contains(password, axes_attempt_record),
                        "Plain-text login attempt password found in Axes record.")
        logger.debug(_('\nSuccessfully finished test for Axes redacts attempted passwords in logs\n\n'))

    @local_test_settings_required
    def test_eula_requirement(self):
        """ Test enforcement of EULA requirement, including:
                (a) EULA is not required when EULAs are disabled;
                (b) EULA agreement is first required before accessing profiles and changing index pages; and
                (c) EULA agreement is only required once when accessing profiles and changing index pages.
        :return: Nothing.
        """
        logger.debug(_('\nStarting test for enforcement of EULA requirements'))
        num_of_users = FdpUser.objects.all().count()
        fdp_organization = FdpOrganization.objects.create(name='FdpOrganization7FdpUser')
        # test for all user types
        for i, user_role in enumerate(self._user_roles):
            # skip for anonymous user
            if user_role[self._is_anonymous_key]:
                continue
            # user without organization
            fdp_user = self._create_fdp_user(
                is_host=user_role[self._is_host_key],
                is_administrator=user_role[self._is_administrator_key],
                is_superuser=user_role[self._is_superuser_key],
                email_counter=i + num_of_users
            )
            # log user in
            client = Client(**self._local_client_kwargs)
            client.logout()
            two_factor = self._create_2fa_record(user=fdp_user)
            response = self._do_login(
                c=client,
                username=fdp_user.email,
                password=self._password,
                two_factor=two_factor,
                login_status_code=200,
                two_factor_status_code=200,
                will_login_succeed=True
            )
            all_kwargs = {'fdp_user': fdp_user, 'response': response}
            staff_kwargs = {'url': reverse('profiles:index'), 'expected_view': profiles_index_view, **all_kwargs}
            admin_kwargs = {'url': reverse('changing:index'), 'expected_view': changing_index_view, **all_kwargs}
            logger.debug(f'Starting {user_role[self._label]} without organization sub-test')
            self.__check_for_eula(**staff_kwargs)
            # if user is an administrator or superuser, then try the admin URL also
            if fdp_user.is_administrator or fdp_user.is_superuser:
                self.__check_for_eula(**admin_kwargs)
            logger.debug(f'Starting {user_role[self._label]} with organization sub-test')
            # add organization to user
            fdp_user.fdp_organization = fdp_organization
            fdp_user.full_clean()
            fdp_user.save()
            self.__check_for_eula(**staff_kwargs)
            # if user is an administrator or superuser, then try the admin URL also
            if fdp_user.is_administrator or fdp_user.is_superuser:
                self.__check_for_eula(**admin_kwargs)
        logger.debug(_('\nSuccessfully finished test for enforcement of EULA requirements\n\n'))
