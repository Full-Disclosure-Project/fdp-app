from django.utils.translation import ugettext_lazy as _
from inheritable.models import AbstractUrlValidator
from inheritable.tests import AbstractTestCase, local_test_settings_required
from fdpuser.models import FdpOrganization, FdpUser
from core.models import Person
from supporting.models import ContentIdentifierType, Allegation
from .models import Attachment, Content, ContentCase, ContentPerson, ContentIdentifier, ContentPersonAllegation, \
    ContentPersonPenalty


class SourcingTestCase(AbstractTestCase):
    """ Performs following tests:

    (1) Test for Admin Changelist, Create Instance, Change Instance, Delete Instance and History Views all permutations
    of user roles, confidentiality levels and relevant models.
            (A) Person has different levels of confidentiality
            (B) Attachment has different levels of confidentiality
            (C) Content has different levels of confidentiality
            (D) Content Identifier has different levels of confidentiality

    (2) Test for Download Attachment View for all permutations of user roles and confidentiality levels.

    """
    @classmethod
    def setUpTestData(cls):
        """ Create the categories that are necessary for typing the data to be created during tests.

        :return: Nothing.
        """
        if not ContentIdentifierType.objects.all().exists():
            ContentIdentifierType.objects.create(name='Name1')
        if not Allegation.objects.all().exists():
            Allegation.objects.create(name='Name1')

    def setUp(self):
        """ Ensure data required for tests has been created.

        :return: Nothing.
        """
        # skip setup and tests unless configuration is compatible
        super().setUp()
        self.assertTrue(ContentIdentifierType.objects.all().exists())
        self.assertTrue(Allegation.objects.all().exists())

    def __add_only_attachments_data(self, fdp_org):
        """ Add attachments with different confidential levels to the test database.

        :param fdp_org: FDP organization to use for some of the attachments.
        :return: Dictionary containing unique names and primary keys for the attachments with different
        confidentiality levels.
        """
        self.assertEqual(Attachment.objects.all().count(), 0)
        attachment_ids = {}
        for i, confidential in enumerate(self._confidentials):
            name = confidential[self._name_key]
            attachment = Attachment.objects.create(
                name=name,
                for_admin_only=confidential[self._for_admin_only_key],
                for_host_only=confidential[self._for_host_only_key],
                file='{b}{f}'.format(b=AbstractUrlValidator.ATTACHMENT_BASE_URL, f='dummy{i}.pdf'.format(i=i))
            )
            self._confidentials[i][self._pk_key] = attachment.pk
            if confidential[self._has_fdp_org_key]:
                attachment.fdp_organizations.add(fdp_org)
            attachment_ids[name] = attachment.pk
        return attachment_ids

    def __add_persons_related_data(self, fdp_org):
        """ Add persons with different confidential levels, and their related data, to the test database.

        :param fdp_org: FDP organization to use for some of the persons.
        :return: List of tuples including models and primary keys for instances referencing persons.
        """
        self.assertEqual(Person.objects.all().count(), 0)
        allegation = Allegation.objects.all()[0]
        # create data without restrictions
        unrestricted_person = Person.objects.create(name='Name1', **self._is_law_dict, **self._not_confidential_dict)
        unrestricted_content = Content.objects.create(name='Name1', **self._not_confidential_dict)
        unrestricted_content_person = ContentPerson.objects.create(
            content=unrestricted_content, person=unrestricted_person
        )
        unrestricted_content_person_link_dict = {'content_person': unrestricted_content_person}
        unrestricted_content_person_allegation = ContentPersonAllegation.objects.create(
            **unrestricted_content_person_link_dict,
            allegation=allegation
        )
        unrestricted_content_person_penalty = ContentPersonPenalty.objects.create(
            **unrestricted_content_person_link_dict
        )
        # create data with restrictions
        # dictionaries containing data with different confidentiality levels
        content_person_ids = {}
        content_person_allegation_ids = {}
        content_person_penalty_ids = {}
        for i, confidential in enumerate(self._confidentials):
            name = confidential[self._name_key]
            person = Person.objects.create(
                name=name,
                is_law_enforcement=True,
                for_admin_only=confidential[self._for_admin_only_key],
                for_host_only=confidential[self._for_host_only_key]
            )
            self._confidentials[i][self._pk_key] = person.pk
            if confidential[self._has_fdp_org_key]:
                person.fdp_organizations.add(fdp_org)
            # connect person to data
            content_person = ContentPerson.objects.create(
                person=person,
                content=Content.objects.create(name='Name{i}'.format(i=i), **self._not_confidential_dict)
            )
            content_person_ids[name] = content_person.pk
            content_person_allegation_ids[name] = (
                ContentPersonAllegation.objects.create(content_person=content_person, allegation=allegation)
            ).pk
            content_person_penalty_ids[name] = (ContentPersonPenalty.objects.create(content_person=content_person)).pk
        return [
            (ContentPerson, content_person_ids, unrestricted_content_person.pk),
            (ContentPersonAllegation, content_person_allegation_ids, unrestricted_content_person_allegation.pk),
            (ContentPersonPenalty, content_person_penalty_ids, unrestricted_content_person_penalty.pk),
        ]

    def __add_attachments_related_data(self, fdp_org):
        """ Add attachments with different confidential levels, and their related data, to the test database.

        :param fdp_org: FDP organization to use for some of the attachments.
        :return: List of tuples including models and primary keys for instances referencing attachments.
        """
        self.assertEqual(Attachment.objects.all().count(), 0)
        allegation = Allegation.objects.all()[0]
        content_identifier_type = ContentIdentifierType.objects.all()[0]
        # create data without restrictions
        unrestricted_person = Person.objects.create(name='Name1', **self._is_law_dict, **self._not_confidential_dict)
        unrestricted_attachment = Attachment.objects.create(name='Name1', **self._not_confidential_dict)
        unrestricted_content = Content.objects.create(name='Name1', **self._not_confidential_dict)
        unrestricted_content.attachments.add(unrestricted_attachment)
        unrestricted_content_link_dict = {'content': unrestricted_content}
        unrestricted_content_person = ContentPerson.objects.create(
            person=unrestricted_person, **unrestricted_content_link_dict
        )
        unrestricted_content_person_link_dict = {'content_person': unrestricted_content_person}
        unrestricted_content_case = ContentCase.objects.create(**unrestricted_content_link_dict)
        unrestricted_content_identifier = ContentIdentifier.objects.create(
            identifier='Name1',
            content_identifier_type=content_identifier_type,
            **self._not_confidential_dict,
            **unrestricted_content_link_dict
        )
        unrestricted_content_person_allegation = ContentPersonAllegation.objects.create(
            **unrestricted_content_person_link_dict, allegation=allegation
        )
        unrestricted_content_person_penalty = ContentPersonPenalty.objects.create(
            **unrestricted_content_person_link_dict
        )
        # create data with restrictions
        # dictionaries containing data with different confidentiality levels
        attachment_ids = {}
        content_ids = {}
        content_person_ids = {}
        content_case_ids = {}
        content_identifier_ids = {}
        content_person_allegation_ids = {}
        content_person_penalty_ids = {}
        for i, confidential in enumerate(self._confidentials):
            name = confidential[self._name_key]
            attachment = Attachment.objects.create(
                name=name,
                for_admin_only=confidential[self._for_admin_only_key],
                for_host_only=confidential[self._for_host_only_key]
            )
            self._confidentials[i][self._pk_key] = attachment.pk
            if confidential[self._has_fdp_org_key]:
                attachment.fdp_organizations.add(fdp_org)
            attachment_ids[name] = attachment.pk
            # connect to data
            content = Content.objects.create(name=name)
            content.attachments.add(attachment)
            content_ids[name] = content.pk
            # connect to data
            restricted_content_link_dict = {'content': content}
            content_person = ContentPerson.objects.create(
                person=Person.objects.create(name='Name1', **self._is_law_dict, **self._not_confidential_dict),
                **restricted_content_link_dict
            )
            content_person_ids[name] = content_person.pk
            content_case_ids[name] = (
                ContentCase.objects.create(
                    description=name,
                    **restricted_content_link_dict
                )
            ).pk
            content_identifier_ids[name] = (
                ContentIdentifier.objects.create(
                    identifier=name,
                    content_identifier_type=content_identifier_type,
                    **self._not_confidential_dict,
                    **restricted_content_link_dict
                )
            ).pk
            content_person_allegation_ids[name] = (
                ContentPersonAllegation.objects.create(content_person=content_person, allegation=allegation)
            ).pk
            content_person_penalty_ids[name] = (ContentPersonPenalty.objects.create(content_person=content_person)).pk
        return [
            (Attachment, attachment_ids, None),
            (Content, content_ids, unrestricted_content.pk),
            (ContentPerson, content_person_ids, unrestricted_content_person.pk),
            (ContentCase, content_case_ids, unrestricted_content_case.pk),
            (ContentIdentifier, content_identifier_ids, unrestricted_content_identifier.pk),
            (ContentPersonAllegation, content_person_allegation_ids, unrestricted_content_person_allegation.pk),
            (ContentPersonPenalty, content_person_penalty_ids, unrestricted_content_person_penalty.pk),
        ]

    def __add_contents_related_data(self, fdp_org):
        """ Add contents with different confidential levels, and their related data, to the test database.

        :param fdp_org: FDP organization to use for some of the contents.
        :return: List of tuples including models and primary keys for instances referencing contents.
        """
        self.assertEqual(Content.objects.all().count(), 0)
        allegation = Allegation.objects.all()[0]
        content_identifier_type = ContentIdentifierType.objects.all()[0]
        # create data without restrictions
        unrestricted_person = Person.objects.create(name='Name1', **self._is_law_dict, **self._not_confidential_dict)
        unrestricted_content = Content.objects.create(name='Name1', **self._not_confidential_dict)
        unrestricted_content_link_dict = {'content': unrestricted_content}
        unrestricted_content_person = ContentPerson.objects.create(
            person=unrestricted_person, **unrestricted_content_link_dict
        )
        unrestricted_content_person_link_dict = {'content_person': unrestricted_content_person}
        unrestricted_content_case = ContentCase.objects.create(**unrestricted_content_link_dict)
        unrestricted_content_identifier = ContentIdentifier.objects.create(
            identifier='Name1',
            content_identifier_type=content_identifier_type,
            **self._not_confidential_dict,
            **unrestricted_content_link_dict
        )
        unrestricted_content_person_allegation = ContentPersonAllegation.objects.create(
            **unrestricted_content_person_link_dict, allegation=allegation
        )
        unrestricted_content_person_penalty = ContentPersonPenalty.objects.create(
            **unrestricted_content_person_link_dict
        )
        # create data with restrictions
        # dictionaries containing data with different confidentiality levels
        content_ids = {}
        content_person_ids = {}
        content_case_ids = {}
        content_identifier_ids = {}
        content_person_allegation_ids = {}
        content_person_penalty_ids = {}
        for i, confidential in enumerate(self._confidentials):
            name = confidential[self._name_key]
            content = Content.objects.create(
                name=name,
                for_admin_only=confidential[self._for_admin_only_key],
                for_host_only=confidential[self._for_host_only_key]
            )
            self._confidentials[i][self._pk_key] = content.pk
            if confidential[self._has_fdp_org_key]:
                content.fdp_organizations.add(fdp_org)
            content_ids[name] = content.pk
            # connect to data
            restricted_content_link_dict = {'content': content}
            content_person = ContentPerson.objects.create(
                person=Person.objects.create(name='Name1', **self._is_law_dict, **self._not_confidential_dict),
                **restricted_content_link_dict
            )
            content_person_ids[name] = content_person.pk
            content_case_ids[name] = (
                ContentCase.objects.create(
                    description=name,
                    **restricted_content_link_dict
                )
            ).pk
            content_identifier_ids[name] = (
                ContentIdentifier.objects.create(
                    identifier=name,
                    content_identifier_type=content_identifier_type,
                    **self._not_confidential_dict,
                    **restricted_content_link_dict
                )
            ).pk
            content_person_allegation_ids[name] = (
                ContentPersonAllegation.objects.create(content_person=content_person, allegation=allegation)
            ).pk
            content_person_penalty_ids[name] = (ContentPersonPenalty.objects.create(content_person=content_person)).pk
        return [
            (Content, content_ids, None),
            (ContentPerson, content_person_ids, unrestricted_content_person.pk),
            (ContentCase, content_case_ids, unrestricted_content_case.pk),
            (ContentIdentifier, content_identifier_ids, unrestricted_content_identifier.pk),
            (ContentPersonAllegation, content_person_allegation_ids, unrestricted_content_person_allegation.pk),
            (ContentPersonPenalty, content_person_penalty_ids, unrestricted_content_person_penalty.pk),
        ]

    def __add_content_identifiers_related_data(self, fdp_org):
        """ Add content identifiers with different confidential levels, and their related data, to the test database.

        :param fdp_org: FDP organization to use for some of the content identifiers.
        :return: List of tuples including models and primary keys for instances referencing content identifiers.
        """
        self.assertEqual(ContentIdentifier.objects.all().count(), 0)
        # create data with restrictions
        # dictionaries containing data with different confidentiality levels
        content_identifier_ids = {}
        for i, confidential in enumerate(self._confidentials):
            name = confidential[self._name_key]
            content = Content.objects.create(name='Name1', **self._not_confidential_dict)
            content_identifier = ContentIdentifier.objects.create(
                identifier=name,
                content_identifier_type=ContentIdentifierType.objects.all()[0],
                content=content,
                for_admin_only=confidential[self._for_admin_only_key],
                for_host_only=confidential[self._for_host_only_key]
            )
            self._confidentials[i][self._pk_key] = content_identifier.pk
            if confidential[self._has_fdp_org_key]:
                content_identifier.fdp_organizations.add(fdp_org)
            content_identifier_ids[name] = content_identifier.pk
        return [
            (ContentIdentifier, content_identifier_ids, None),
        ]

    def __delete_only_attachments_data(self):
        """ Removes all attachments from the test database.

        :return: Nothing.
        """
        Attachment.objects.all().delete()
        self.assertEqual(Attachment.objects.all().count(), 0)

    def __delete_persons_related_data(self):
        """ Removes all persons and related data from the test database.

        :return: Nothing.
        """
        ContentPersonPenalty.objects.all().delete()
        ContentPersonAllegation.objects.all().delete()
        ContentPerson.objects.all().delete()
        Person.objects.all().delete()
        Content.objects.all().delete()
        self.assertEqual(Person.objects.all().count(), 0)

    def __delete_attachments_related_data(self):
        """ Removes all attachments and related data from the test database.

        :return: Nothing.
        """
        Content.objects.all().delete()
        Attachment.objects.all().delete()
        self.assertEqual(Attachment.objects.all().count(), 0)

    def __delete_contents_related_data(self):
        """ Removes all contents and related data from the test database.

        :return: Nothing.
        """
        ContentPersonPenalty.objects.all().delete()
        ContentPersonAllegation.objects.all().delete()
        ContentIdentifier.objects.all().delete()
        ContentCase.objects.all().delete()
        ContentPerson.objects.all().delete()
        Content.objects.all().delete()
        Person.objects.all().delete()
        self.assertEqual(Content.objects.all().count(), 0)

    def __delete_content_identifiers_related_data(self):
        """ Removes all content identifiers and related data from the test database.

        :return: Nothing.
        """
        ContentIdentifier.objects.all().delete()
        Content.objects.all().delete()
        self.assertEqual(ContentIdentifier.objects.all().count(), 0)

    def __test_download_attachment_view(self, fdp_org, other_fdp_org):
        """ Test for Download Attachment View for all permutations of user roles and confidentiality levels.

        :param fdp_org: FDP organization that may be linked to users and data.
        :param other_fdp_org: Another FDP organization that may be linked to users and data.
        :return: Nothing
        """
        # add attachments with different confidentiality levels
        attachment_ids = self.__add_only_attachments_data(fdp_org=fdp_org)
        # number of users already in database
        num_of_users = FdpUser.objects.all().count() + 1
        # test for all user types
        for i, user_role in enumerate(self._user_roles):
            # skip for anonymous user
            if user_role[self._is_anonymous_key]:
                continue
            # create the FDP user in the test database
            fdp_user = self._create_fdp_user(
                is_host=user_role[self._is_host_key],
                is_administrator=user_role[self._is_administrator_key],
                is_superuser=user_role[self._is_superuser_key],
                email_counter=i + num_of_users
            )
            # keyword arguments to expand as parameters into the check methods below
            check_params = {
                'fdp_user': fdp_user,
                'fdp_org': fdp_org,
                'id_map_dict': attachment_ids,
                'view_name': 'sourcing:download_attachment',
                'model_to_download': Attachment,
                'field_with_file': 'file',
                'base_url': AbstractUrlValidator.ATTACHMENT_BASE_URL,
                'expected_err_str': 'User does not have access to attachment'
            }
            # check data for FDP user without FDP org
            self._print_download_view_start_without_org(model_txt='attachment', user_role=user_role)
            self._check_if_can_download(**check_params)
            # change FDP user's organization
            fdp_user.fdp_organization = fdp_org
            fdp_user.full_clean()
            fdp_user.save()
            # check data for FDP user with FDP org
            self._print_download_view_start_with_right_org(model_txt='attachment', user_role=user_role)
            self._check_if_can_download(**check_params)
            # change FDP user's organization
            fdp_user.fdp_organization = other_fdp_org
            fdp_user.full_clean()
            fdp_user.save()
            # check data for FDP user with FDP org
            self._print_download_view_start_with_wrong_org(model_txt='attachment', user_role=user_role)
            self._check_if_can_download(**check_params)
        # remove attachment with different confidentiality levels
        self.__delete_only_attachments_data()

    def __test_person_admin_views(self, fdp_org, other_fdp_org):
        """ Test for Admin Changelist, Create Instance, Change Instance, Delete Instance and History Views all
        permutations of user roles, confidentiality levels and models linked to Person directly and indirectly.

        :param fdp_org: FDP organization that may be linked to users and data.
        :param other_fdp_org: Another FDP organization that may be linked to users and data.
        :return: Nothing
        """
        # add persons with different confidentiality levels
        models = self.__add_persons_related_data(fdp_org=fdp_org)
        # number of users already in database
        num_of_users = FdpUser.objects.all().count() + 1
        # test for all user types
        for i, user_role in enumerate(self._user_roles):
            # skip for anonymous user
            if user_role[self._is_anonymous_key]:
                continue
            # create the FDP user in the test database
            fdp_user = self._create_fdp_user(
                is_host=user_role[self._is_host_key],
                is_administrator=user_role[self._is_administrator_key],
                is_superuser=user_role[self._is_superuser_key],
                email_counter=i + num_of_users
            )
            # keyword arguments to expand as parameters into the check methods below
            check_params = {
                'fdp_user': fdp_user,
                'fdp_org': fdp_org,
                'password': self._password,
                'related_text': 'person',
                'models_to_test': models
            }
            # check data for FDP user without FDP org
            self._print_changelist_start_without_org(model_txt='person', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_without_org(model_txt='person', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[], **check_params)
            self._print_load_change_instance_start_without_org(model_txt='person', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_without_org(model_txt='person', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[], **check_params)
            self._print_load_history_start_without_org(model_txt='person', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_without_org(model_txt='person', user_role=user_role)
            self._load_admin_delete_views(**check_params)
            # change FDP user's organization
            fdp_user.fdp_organization = fdp_org
            fdp_user.full_clean()
            fdp_user.save()
            # check data for FDP user with FDP org
            self._print_changelist_start_with_right_org(model_txt='person', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_with_right_org(model_txt='person', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[], **check_params)
            self._print_load_change_instance_start_with_right_org(model_txt='person', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_with_right_org(model_txt='person', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[], **check_params)
            self._print_load_history_start_with_right_org(model_txt='person', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_with_right_org(model_txt='person', user_role=user_role)
            self._load_admin_delete_views(**check_params)
            # change FDP user's organization
            fdp_user.fdp_organization = other_fdp_org
            fdp_user.full_clean()
            fdp_user.save()
            # check data for FDP user with FDP org
            self._print_changelist_start_with_wrong_org(model_txt='person', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_with_wrong_org(model_txt='person', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[], **check_params)
            self._print_load_change_instance_start_with_wrong_org(model_txt='person', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_with_wrong_org(model_txt='person', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[], **check_params)
            self._print_load_history_start_with_wrong_org(model_txt='person', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_with_wrong_org(model_txt='person', user_role=user_role)
            self._load_admin_delete_views(**check_params)
        # remove persons with different confidentiality levels
        self.__delete_persons_related_data()

    def __test_attachment_admin_views(self, fdp_org, other_fdp_org):
        """ Test for Admin Changelist, Create Instance, Change Instance, Delete Instance and History Views all
        permutations of user roles, confidentiality levels and models linked to Attachment directly and indirectly.

        :param fdp_org: FDP organization that may be linked to users and data.
        :param other_fdp_org: Another FDP organization that may be linked to users and data.
        :return: Nothing
        """
        # add attachments with different confidentiality levels
        models = self.__add_attachments_related_data(fdp_org=fdp_org)
        # number of users already in database
        num_of_users = FdpUser.objects.all().count() + 1
        # test for all user types
        for i, user_role in enumerate(self._user_roles):
            # skip for anonymous user
            if user_role[self._is_anonymous_key]:
                continue
            # create the FDP user in the test database
            fdp_user = self._create_fdp_user(
                is_host=user_role[self._is_host_key],
                is_administrator=user_role[self._is_administrator_key],
                is_superuser=user_role[self._is_superuser_key],
                email_counter=i + num_of_users
            )
            # keyword arguments to expand as parameters into the check methods below
            check_params = {
                'fdp_user': fdp_user,
                'fdp_org': fdp_org,
                'password': self._password,
                'related_text': 'attachment',
                'models_to_test': models
            }
            # check data for FDP user without FDP org
            self._print_changelist_start_without_org(model_txt='attachment', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_without_org(model_txt='attachment', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[Attachment], **check_params)
            self._print_load_change_instance_start_without_org(model_txt='attachment', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_without_org(model_txt='attachment', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[Attachment], **check_params)
            self._print_load_history_start_without_org(model_txt='attachment', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_without_org(model_txt='attachment', user_role=user_role)
            self._load_admin_delete_views(**check_params)
            # change FDP user's organization
            fdp_user.fdp_organization = fdp_org
            fdp_user.full_clean()
            fdp_user.save()
            # check data for FDP user with FDP org
            self._print_changelist_start_with_right_org(model_txt='attachment', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_with_right_org(model_txt='attachment', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[Attachment], **check_params)
            self._print_load_change_instance_start_with_right_org(model_txt='attachment', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_with_right_org(model_txt='attachment', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[Attachment], **check_params)
            self._print_load_history_start_with_right_org(model_txt='attachment', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_with_right_org(model_txt='attachment', user_role=user_role)
            self._load_admin_delete_views(**check_params)
            # change FDP user's organization
            fdp_user.fdp_organization = other_fdp_org
            fdp_user.full_clean()
            fdp_user.save()
            # check data for FDP user with FDP org
            self._print_changelist_start_with_wrong_org(model_txt='attachment', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_with_wrong_org(model_txt='attachment', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[Attachment], **check_params)
            self._print_load_change_instance_start_with_wrong_org(model_txt='attachment', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_with_wrong_org(model_txt='attachment', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[Attachment], **check_params)
            self._print_load_history_start_with_wrong_org(model_txt='attachment', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_with_wrong_org(model_txt='attachment', user_role=user_role)
            self._load_admin_delete_views(**check_params)
        # remove attachment with different confidentiality levels
        self.__delete_attachments_related_data()

    def __test_content_admin_views(self, fdp_org, other_fdp_org):
        """ Test for Admin Changelist, Create Instance, Change Instance, Delete Instance and History Views all
        permutations of user roles, confidentiality levels and models linked to Content directly and indirectly.

        :param fdp_org: FDP organization that may be linked to users and data.
        :param other_fdp_org: Another FDP organization that may be linked to users and data.
        :return: Nothing
        """
        # add contents with different confidentiality levels
        models = self.__add_contents_related_data(fdp_org=fdp_org)
        # number of users already in database
        num_of_users = FdpUser.objects.all().count() + 1
        # test for all user types
        for i, user_role in enumerate(self._user_roles):
            # skip for anonymous user
            if user_role[self._is_anonymous_key]:
                continue
            # create the FDP user in the test database
            fdp_user = self._create_fdp_user(
                is_host=user_role[self._is_host_key],
                is_administrator=user_role[self._is_administrator_key],
                is_superuser=user_role[self._is_superuser_key],
                email_counter=i + num_of_users
            )
            # keyword arguments to expand as parameters into the check methods below
            check_params = {
                'fdp_user': fdp_user,
                'fdp_org': fdp_org,
                'password': self._password,
                'related_text': 'content',
                'models_to_test': models
            }
            # check data for FDP user without FDP org
            self._print_changelist_start_without_org(model_txt='content', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_without_org(model_txt='content', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[Content], **check_params)
            self._print_load_change_instance_start_without_org(model_txt='content', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_without_org(model_txt='content', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[Content], **check_params)
            self._print_load_history_start_without_org(model_txt='content', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_without_org(model_txt='content', user_role=user_role)
            self._load_admin_delete_views(**check_params)
            # change FDP user's organization
            fdp_user.fdp_organization = fdp_org
            fdp_user.full_clean()
            fdp_user.save()
            # check data for FDP user with FDP org
            self._print_changelist_start_with_right_org(model_txt='content', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_with_right_org(model_txt='content', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[Content], **check_params)
            self._print_load_change_instance_start_with_right_org(model_txt='content', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_with_right_org(model_txt='content', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[Content], **check_params)
            self._print_load_history_start_with_right_org(model_txt='content', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_with_right_org(model_txt='content', user_role=user_role)
            self._load_admin_delete_views(**check_params)
            # change FDP user's organization
            fdp_user.fdp_organization = other_fdp_org
            fdp_user.full_clean()
            fdp_user.save()
            # check data for FDP user with FDP org
            self._print_changelist_start_with_wrong_org(model_txt='content', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_with_wrong_org(model_txt='content', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[Content], **check_params)
            self._print_load_change_instance_start_with_wrong_org(model_txt='content', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_with_wrong_org(model_txt='content', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[Content], **check_params)
            self._print_load_history_start_with_wrong_org(model_txt='content', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_with_wrong_org(model_txt='content', user_role=user_role)
            self._load_admin_delete_views(**check_params)
        # remove contents with different confidentiality levels
        self.__delete_contents_related_data()

    def __test_content_identifier_admin_views(self, fdp_org, other_fdp_org):
        """ Test for Admin Changelist, Create Instance, Change Instance, Delete Instance and History Views all
        permutations of user roles, confidentiality levels and models linked to Content Identifier directly and
        indirectly.

        :param fdp_org: FDP organization that may be linked to users and data.
        :param other_fdp_org: Another FDP organization that may be linked to users and data.
        :return: Nothing
        """
        # add content identifiers with different confidentiality levels
        models = self.__add_content_identifiers_related_data(fdp_org=fdp_org)
        # number of users already in database
        num_of_users = FdpUser.objects.all().count() + 1
        # test for all user types
        for i, user_role in enumerate(self._user_roles):
            # skip for anonymous user
            if user_role[self._is_anonymous_key]:
                continue
            # create the FDP user in the test database
            fdp_user = self._create_fdp_user(
                is_host=user_role[self._is_host_key],
                is_administrator=user_role[self._is_administrator_key],
                is_superuser=user_role[self._is_superuser_key],
                email_counter=i + num_of_users
            )
            # keyword arguments to expand as parameters into the check methods below
            check_params = {
                'fdp_user': fdp_user,
                'fdp_org': fdp_org,
                'password': self._password,
                'related_text': 'content_identifier',
                'models_to_test': models
            }
            # check data for FDP user without FDP org
            self._print_changelist_start_without_org(model_txt='content_identifier', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_without_org(model_txt='content_identifier', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[ContentIdentifier], **check_params)
            self._print_load_change_instance_start_without_org(model_txt='content_identifier', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_without_org(model_txt='content_identifier', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[ContentIdentifier], **check_params)
            self._print_load_history_start_without_org(model_txt='content_identifier', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_without_org(model_txt='content_identifier', user_role=user_role)
            self._load_admin_delete_views(**check_params)
            # change FDP user's organization
            fdp_user.fdp_organization = fdp_org
            fdp_user.full_clean()
            fdp_user.save()
            # check data for FDP user with FDP org
            self._print_changelist_start_with_right_org(model_txt='content_identifier', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_with_right_org(model_txt='content_identifier', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[ContentIdentifier], **check_params)
            self._print_load_change_instance_start_with_right_org(model_txt='content_identifier', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_with_right_org(model_txt='content_identifier', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[ContentIdentifier], **check_params)
            self._print_load_history_start_with_right_org(model_txt='content_identifier', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_with_right_org(model_txt='content_identifier', user_role=user_role)
            self._load_admin_delete_views(**check_params)
            # change FDP user's organization
            fdp_user.fdp_organization = other_fdp_org
            fdp_user.full_clean()
            fdp_user.save()
            # check data for FDP user with FDP org
            self._print_changelist_start_with_wrong_org(model_txt='content_identifier', user_role=user_role)
            self._check_admin_change_list_views(models_where_data_never_appears=[], **check_params)
            self._print_create_instance_start_with_wrong_org(model_txt='content_identifier', user_role=user_role)
            self._check_admin_create_instance_views(models_where_data_never_appears=[ContentIdentifier], **check_params)
            self._print_load_change_instance_start_with_wrong_org(model_txt='content_identifier', user_role=user_role)
            self._load_admin_change_instance_views(**check_params)
            self._print_change_instance_start_with_wrong_org(model_txt='content_identifier', user_role=user_role)
            self._check_admin_change_instance_views(models_where_data_never_appears=[ContentIdentifier], **check_params)
            self._print_load_history_start_with_wrong_org(model_txt='content_identifier', user_role=user_role)
            self._load_admin_history_views(**check_params)
            self._print_load_delete_start_with_wrong_org(model_txt='content_identifier', user_role=user_role)
            self._load_admin_delete_views(**check_params)
        # remove content identifiers with different confidentiality levels
        self.__delete_content_identifiers_related_data()

    @local_test_settings_required
    def test_admin_views(self):
        """ Test for Admin Changelist, Create Instance, Change Instance, Delete Instance and History Views all
        permutations of user roles, confidentiality levels and relevant models.

        :return: Nothing
        """
        print(
            _('\nStarting test for Sourcing Data Admin changelist, create instance, change instance, delete instance '
              'and history views for all permutations of user roles, confidentiality levels and relevant models')
        )
        fdp_org = FdpOrganization.objects.create(name='FdpOrganizationSourcing1')
        other_fdp_org = FdpOrganization.objects.create(name='FdpOrganizationSourcing2')
        self.__test_person_admin_views(fdp_org=fdp_org, other_fdp_org=other_fdp_org)
        self.__test_attachment_admin_views(fdp_org=fdp_org, other_fdp_org=other_fdp_org)
        self.__test_content_admin_views(fdp_org=fdp_org, other_fdp_org=other_fdp_org)
        self.__test_content_identifier_admin_views(fdp_org=fdp_org, other_fdp_org=other_fdp_org)
        print(_('\nSuccessfully finished test for Sourcing Data Admin changelist, create instance, change instance, '
                'delete instance and history views for all permutations of user roles, confidentiality levels and '
                'relevant models\n\n'))

    @local_test_settings_required
    def test_download_attachment_view(self):
        """ Test for Download Attachment View for all permutations of user roles and confidentiality levels.

        :return: Nothing
        """
        print(_('\nStarting test for Download Attachment view for all permutations of user roles and'
                ' confidentiality levels'))
        fdp_org = FdpOrganization.objects.create(name='FdpOrganizationDlAtt1')
        other_fdp_org = FdpOrganization.objects.create(name='FdpOrganizationDlAtt2')
        self.__test_download_attachment_view(fdp_org=fdp_org, other_fdp_org=other_fdp_org)
        print(_('\nSuccessfully finished test for Download Attachment view for all permutations of user roles and '
                'confidentiality levels\n\n'))
