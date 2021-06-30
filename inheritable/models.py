from django.db import models, connection
from django.db.models import Q
from django.http import QueryDict
from django.core.exceptions import ValidationError, ImproperlyConfigured
from django.core.validators import RegexValidator
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils.timezone import now
from django.utils._os import safe_join
from fdp.configuration.abstract.constants import CONST_AZURE_AD_PROVIDER, CONST_MAX_ATTACHMENT_FILE_BYTES, \
    CONST_MAX_PERSON_PHOTO_FILE_BYTES, CONST_SUPPORTED_ATTACHMENT_FILE_TYPES, CONST_SUPPORTED_PERSON_PHOTO_FILE_TYPES
from datetime import date
from os import path
from cryptography.fernet import Fernet
from axes.helpers import get_client_ip_address
from io import BytesIO
from zipfile import ZipFile
from re import match as re_match
from abc import abstractmethod
from importlib import import_module
from dateparser.search import search_dates
from posixpath import normpath
from pathlib import Path
from os.path import commonprefix, realpath


class Metable(models.Model):
    """ Base class from which all model classes inherit.

    Creates a wrapper around the Django Model class to create some shorthand for retrieving table names and
    localized verbose names.

    Attributes:
        There are no attributes.

    """
    @classmethod
    def get_db_table(cls):
        """ Retrieves the name of the database table that stores instances of the model.

        :return: Full string representing the table name, including the prefix.
        """
        meta = getattr(cls, '_meta')
        return meta.db_table

    @staticmethod
    def get_db_table_for_many_to_many(many_to_many_key):
        """ Retrieves the name of the database table that stores instances of the through model connecting two models
        through many-to-many relationship.

        :param many_to_many_key: Instance of many-to-many relationship on main model. E.g. Content.attachments.
        :return: Full string representing the table name, including the prefix.
        """
        meta = getattr(many_to_many_key.through, '_meta')
        return meta.db_table

    @staticmethod
    def get_fk_model(foreign_key):
        """ Retrieves the model to which a foreign key or one-to-one relationship links.

        :param foreign_key: Foreign key or one-to-one relationship.
        :return: Model for foreign key or one-to-one.
        """
        return foreign_key.remote_field.model

    @classmethod
    def get_verbose_name_plural(cls):
        """ Retrieves the localized name that represents plural instances of the model.

        :return: String representing plural instances of the model.
        """
        meta = getattr(cls, '_meta')
        return meta.verbose_name_plural

    class Meta:
        abstract = True


class ArchivableQuerySet(models.QuerySet):
    """ A base queryset for objects to enforce optional access to non-archived records.

    """
    def filter_for_archive(self, active_only):
        """ Filter the queryset for all records or only those that are non-archived.

        :param active_only: True if only non-archived records should be retrieved, false otherwise.
        :return: Filtered queryset.
        """
        return self.__get_archivable_queryset(qs=self, active_only=active_only)

    @staticmethod
    def __get_archivable_queryset(qs, active_only):
        """ Retrieves an record queryset filtered optionally for non-archived records (i.e. "active_only"=True).

        :param qs: Queryset that may have already been filtered.
        :param active_only: True if only non-archived records should be retrieved, false otherwise.
        :return: Record queryset filtered optionally for non-archived records.
        """
        # only retrieve active records
        if active_only:
            return qs.filter(is_archived=False)
        # retrieve all records
        else:
            return qs


class ArchivableManager(models.Manager):
    """ A manager for records that can be archived, i.e. soft-deleted.

    """
    def __init__(self, *args, **kwargs):
        """ Checks whether to retrieve only active records, or all records.

        :param args:
        :param kwargs: May include boolean "active_only" specifying whether to retrieve only active records or all
        records.
        """
        self.active_only = kwargs.pop('active_only', True)
        super(ArchivableManager, self).__init__(*args, **kwargs)

    def get_queryset(self):
        """ Retrieves either only active records, or all records for the query set.

        :return: Query set to retrieve.
        """
        return ArchivableQuerySet(self.model, using=self._db).filter_for_archive(active_only=self.active_only)


class Archivable(Metable):
    """ Base class from which all archivable classes inherit.

    Archiving provides a soft-delete alternative to permanently deleting a record, allowing the record to remain in the
    database but not be displayed in queries.

    Class is also registered with the Django-Reversion API.

    See: https://django-reversion.readthedocs.io/en/stable/api.html#registering-models

    Attributes:
        :is_archived (bool): True if record is archived, false otherwise.

    """
    is_archived = models.BooleanField(
        null=False,
        blank=False,
        default=False,
        verbose_name=_('Is archived'),
        help_text=_('Select if record is archived'),
    )

    # all records
    objects = ArchivableManager(active_only=False)
    # only active records
    active_objects = ArchivableManager(active_only=True)

    # String representation of the is archived field
    __IS_ARCHIVED_FLD = 'is_archived'

    # filter that can be included in a RAW query to limit it to only active (not archived) records.
    ACTIVE_FILTER = '"{f}" = False'.format(f=__IS_ARCHIVED_FLD)

    @classmethod
    def get_active_filter(cls, prefix='', separator='__'):
        """ Retrieves a filter that can be applied to a query set to limit it to only active (not archived) records.

        :param prefix: Prefix that may define a hierarchy of objects, each to be filtered for active only.
        :param separator: Characters separating the different objects in the hierarchy.

        :return: A dictionary representation of the filter.
        """
        # if prefix ends with the separator, then remove it (will be re-added later)
        if prefix.endswith(separator):
            prefix = prefix[:-len(separator)]
        # create the hierarchy of objects to apply the active only filter to
        hierarchy = prefix.split(separator)
        active_filter = {}
        # add an active filter for each object in the hierarchy
        obj_prefix = ''
        for obj in hierarchy:
            active_filter[
                '{p}{s1}{o}{s2}{a}'.format(
                    p=obj_prefix,
                    s1='' if not obj_prefix else separator,
                    o=obj,
                    s2=separator,
                    a=cls.__IS_ARCHIVED_FLD
                )
            ] = False
            obj_prefix = '{p}{s}{o}'.format(p=obj_prefix, s='' if not obj_prefix else separator, o=obj)
        return active_filter

    @classmethod
    @abstractmethod
    def filter_for_admin(cls, queryset, user):
        """ Filter a queryset for the admin interfaces.

        Assumes that queryset has already been filtered for direct confidentiality, i.e. whether user has access to
        each record based on the record's level of confidentiality. E.g. a confidentiable queryset of Person.

        Can be used to filter for indirect confidentiality, i..e whether user has access to each record based on other
        relevant records' levels of confidentiality. E.g. a queryset of PersonAlias linking to a confidentiality
        queryset of Person.

        :param queryset: Queryset to filter.
        :param user: User for which to filter queryset.
        :return: Filtered queryset.
        """
        pass

    class Meta:
        abstract = True


class ArchivableSearchCategory(Archivable):
    """ An archivable model that is used to categorize some search criteria.

    An example is title, which is may appear in search criteria when identifying officers.

    """
    @classmethod
    def get_as_list(cls, fields):
        """ Retrieves all active records for a model in list format, to easily check entered search criteria against
        them.

        :param fields: A list of fields to include in the dictionary representing a record. The primary key will be
        included by default, and so should be omitted from the list of fields.

        :return: A list of dictionaries containing each record's properties.
        """
        return list(cls.active_objects.all().only('pk', *fields))

    @classmethod
    def filter_for_admin(cls, queryset, user):
        """ Filter a queryset for the admin interfaces.

        Assumes that queryset has already been filtered for direct confidentiality, i.e. whether user has access to
        each record based on the record's level of confidentiality. E.g. a confidentiable queryset of Person.

        Can be used to filter for indirect confidentiality, i..e whether user has access to each record based on other
        relevant records' levels of confidentiality. E.g. a queryset of PersonAlias linking to a confidentiality
        queryset of Person.

        :param queryset: Queryset to filter.
        :param user: User for which to filter queryset.
        :return: Filtered queryset.
        """
        raise Exception(_('All classes that inherit from ArchivableSearchCategory should implement filter_for_admin'))

    class Meta:
        abstract = True


class ConfidentiableQuerySet(ArchivableQuerySet):
    """ A base queryset for objects such as incidents and contents to enforce optional access restrictions for a FDP
    organization, for administrators and/or users belonging to the host organization.

    """
    def filter_for_confidential_by_user(self, user):
        """ Filter the queryset for a particular user with a particular set of permissions.

        :param user: User for which to filter the queryset.
        :return: Filtered queryset.
        """
        return self.__get_confidentiable_queryset(
            qs=self,
            is_host=user.is_host or user.is_superuser,
            is_admin=user.is_administrator or user.is_superuser,
            fdp_organization_id=user.fdp_organization_id
        )

    def filter_for_confidential_directly(self, is_host, is_admin, fdp_organization_id):
        """ Filter the queryset directly.

        :param is_host: True if user requesting records belongs to the host organization, false otherwise.
        :param is_admin: True if user requesting records is an administrator, false otherwise.
        :param fdp_organization_id: The ID of the FDP organization to which user requesting data belongs.
        :return: Record queryset filtered directly.
        """
        return self.__get_confidentiable_queryset(
            qs=self, is_host=is_host, is_admin=is_admin, fdp_organization_id=fdp_organization_id
        )

    @staticmethod
    def __get_confidentiable_queryset(qs, is_host, is_admin, fdp_organization_id):
        """ Retrieves a record queryset filtered optionally for users belonging to the host organization
        (i.e. "is_host"), for administrators (i.e. "is_admin"), and/or for a particular FDP organization
        (i.e. fdp_organization_id = ...).

        If changing the logic below, ensure that Confidentiable.get_confidential_filter(...) is synchronized.

        :param qs: Queryset that may have already been filtered.
        :param is_host: True if user requesting records belongs to the host organization, false otherwise.
        :param is_admin: True if user requesting records is an administrator, false otherwise.
        :param fdp_organization_id: The ID of the FDP organization to which user requesting data belongs.
        :return: Record queryset filtered by context.
        """
        # If changing the logic below, ensure that Confidentiable.get_confidential_filter(...) is synchronized.
        # User is an administrator and belongs to the host organization, then we don't need additional filtering
        if is_host and is_admin:
            return qs
        # User is not an administrator and belongs to the host organization, so show all non-admin data
        elif is_host and not is_admin:
            # host staff member (non-admin) has no specified organization
            if fdp_organization_id is None:
                return qs.filter(for_admin_only=False, fdp_organizations__id__isnull=True)
            # host staff member (non-admin) has an organization specified
            else:
                return qs.filter(
                    Q(for_admin_only=False, fdp_organizations__id__isnull=True) |
                    Q(for_admin_only=False, fdp_organizations__id=fdp_organization_id)
                )
        # User is an administrator, does not belong to the host organization, and we don't know where they belong
        elif (not is_host) and is_admin and (fdp_organization_id is None):
            return qs.filter(fdp_organizations__id__isnull=True, for_host_only=False)
        # User is not an administrator, does not belong to the host organization, and we don't know where they belong
        elif (not is_host) and (not is_admin) and (fdp_organization_id is None):
            return qs.filter(fdp_organizations__id__isnull=True, for_host_only=False, for_admin_only=False)
        # User is an administrator, does not belong to the host organization, and belongs to a FDP organization
        elif (not is_host) and is_admin and (fdp_organization_id is not None):
            return qs.filter(
                Q(fdp_organizations__id__isnull=True, for_host_only=False) |
                Q(fdp_organizations__id=fdp_organization_id, for_host_only=False)
            )
        # User is not an administrator, does not belong to the host organization, and belongs to a FDP organization
        elif (not is_host) and (not is_admin) and (fdp_organization_id is not None):
            return qs.filter(
                Q(fdp_organizations__id__isnull=True, for_host_only=False, for_admin_only=False) |
                Q(fdp_organizations__id=fdp_organization_id, for_host_only=False, for_admin_only=False)
            )
        # there was an invalid configuration of the properties
        else:
            raise ImproperlyConfigured(_('Record query set is not filtered correctly for confidentiality'))


class ConfidentiableManager(ArchivableManager):
    """ A manager for objects such as incidents and contents to enforce optional access restrictions for a FDP
    organization, for administrators and/or for users belonging to the host organization.

    """
    use_for_related_fields = True

    def __init__(self, *args, **kwargs):
        """ Checks whether to apply any filtering when retrieving confidential and other restricted records.

        :param args:
        :param kwargs: May include whether the user requesting data belongs to the host organization (i.e. "is_host"),
        whether the user is an administrator (i.e. "is_admin"), and/or the ID of the FDP organization
        (i.e. "fdp_organization_id") for which confidential records can be retrieved.
        """
        is_host_key = 'is_host'
        is_admin_key = 'is_admin'
        fdp_organization_key = 'fdp_organization_id'
        # requesting an unfiltered queryset through the back-end (i.e. through admin)
        if is_host_key not in kwargs and is_admin_key not in kwargs and fdp_organization_key not in kwargs:
            self.is_host = True
            self.fdp_organization_id = None
            self.is_admin = True
        # filtered through FDP code
        else:
            self.is_host = kwargs.pop(is_host_key, False)
            self.fdp_organization_id = kwargs.pop(fdp_organization_key, None)
            self.is_admin = kwargs.pop(is_admin_key, False)
        super(ConfidentiableManager, self).__init__(*args, **kwargs)

    def get_queryset(self):
        """ Retrieves:
             - filtered confidential records for users belonging to the host organization (is_host = True)
             - filtered confidential records for a particular FDP organization (i.e. fdp_organization_id = ...)
             - filtered administrator only records (i.e. is_admin = True)
             - generally available records.

        :return: Query set to retrieve.
        """
        return ConfidentiableQuerySet(self.model, using=self._db).filter_for_archive(
            active_only=self.active_only
        ).filter_for_confidential_directly(
            is_host=self.is_host, is_admin=self.is_admin, fdp_organization_id=self.fdp_organization_id
        )

    def get_queryset_for_user(self, user):
        """ Retrieves a queryset that is filtered for a particular user.

        :param user: User whose permissions will determine the queryset that can be retrieved.
        :return: Filtered queryset.
        """
        return self.get_queryset().filter_for_confidential_by_user(user=user)


class Confidentiable(Archivable):
    """ Base class from which all classes inherit if they wish to declare records confidential.

    Confidential records can only be accessed by specified FDP organizations, and optionally, only by their
    administrators.

    Attributes:
        :for_admin_only (bool): True if only administrators from the selected FDP organizations can access record.
        :for_host_only (bool): True if only users belonging to the host organization can access record.

    Note:
        On all inheriting classes, must specify attribute: fdp_organizations = models.ManyToManyField(...)

    """
    for_admin_only = models.BooleanField(
        null=False,
        blank=False,
        default=False,
        help_text=_('Select if only administrators for the specified organizations can access.'),
        verbose_name=_('admin only')
    )

    for_host_only = models.BooleanField(
        null=False,
        blank=False,
        default=False,
        help_text=_('Select if only users belonging to the host organization can access. When combined with \'admin '
                    'only\', then only host administrators can access.'),
        verbose_name=_('host only')
    )

    #: Fields to display in model form
    confidentiable_form_fields = ['for_host_only', 'for_admin_only', 'fdp_organizations']

    def __all_fdp_organizations(self):
        """ Retrieve a comma separated list of all FDP organizations that can access record.

        :return: Comma separated list of all FDP organizations.
        """
        fdp_organizations = getattr(self, 'fdp_organizations')
        return _('No restriction') if not fdp_organizations.all().exists() \
            else ', '.join([s.__str__() for s in fdp_organizations.all()])

    @property
    def all_fdp_organizations(self):
        """ Retrieve a comma separated list of all FDP organizations that can access record.

        :return: Comma separated list of all FDP organizations.
        """
        return self.__all_fdp_organizations()

    # all records
    objects = ConfidentiableManager(active_only=False, is_admin=True, is_host=True, fdp_organization_id=None)

    # only active records
    active_objects = ConfidentiableManager(active_only=True, is_admin=True, is_host=True, fdp_organization_id=None)

    # only unrestricted records
    unrestricted_objects = ConfidentiableManager(
        active_only=True, is_admin=False, is_host=False, fdp_organization_id=None
    )

    # String representation of the for admin only field
    __FOR_ADMIN_ONLY_FLD = 'for_admin_only'

    # String representation of the for host only field
    __FOR_HOST_ONLY_FLD = 'for_host_only'

    @classmethod
    def get_confidential_filter(cls, user, org_table, unique_alias, org_obj_col, obj_col, org_org_col, prefix=None):
        """ Retrieves a filter that can be applied to a query set to limit it to only the confidentiable records that
        can be accessed by a user.

        If changing this, ensure that ConfidentiableQuerySet.__get_confidentiable_queryset(...) is also synchronized.

        :param user: User for which records will be filtered.
        :param org_table: Name of table linking main object table with the organization table,
        e.g. "fdp_case_content_identifier_fdp_organization".
        :param unique_alias: Unique alias that will be given to the org_table, e.g. ZCCIO.
        :param org_obj_col: Column storing main object record ID in org_table, e.g. casecontentidentifier_id.
        :param obj_col: Column storing primary key in main object table, e.g. id.
        :param org_org_col: Column storing organization ID in org_table, e.g. fdporganization_id.
        :param prefix: Alias for or full name of the main object table, e.g. "fdp_case_content_identifier".
        :return: String of raw SQL that will filter a queryset by confidentiality.
        """
        # If changing this, ensure that ConfidentiableQuerySet.__get_confidentiable_queryset(...) is also synchronized.
        prefix = '' if not prefix else '"{p}".'.format(p=prefix)
        is_host = user.is_host or user.is_superuser
        is_admin = user.is_administrator or user.is_superuser
        fdp_organization_id = user.fdp_organization_id
        # User is an administrator and belongs to the host organization, then we don't need additional filtering
        if is_host and is_admin:
            return 'True = True'
        # User is not an administrator and belongs to the host organization, so show all non-admin data
        elif is_host and not is_admin:
            # host staff member (non-admin) has no specified organization
            if fdp_organization_id is None:
                return """
                (                     
                    {p}"{for_admin_only}" = False
                    AND NOT EXISTS (
                        SELECT 'X' FROM "{org_table}" AS {unique_alias}
                        WHERE {unique_alias}."{org_obj_col}" = {p}"{obj_col}"  
                    )
                )                
                """.format(
                    p=prefix,
                    for_admin_only=cls.__FOR_ADMIN_ONLY_FLD,
                    org_table=org_table,
                    unique_alias=unique_alias,
                    org_obj_col=org_obj_col,
                    obj_col=obj_col
                )
            # host staff member (non-admin) has an organization specified
            else:
                return """
                    (
                        (
                            {p}"{for_admin_only}" = False
                            AND NOT EXISTS (
                                SELECT 'X' FROM "{org_table}" AS {unique_alias}
                                WHERE {unique_alias}."{org_obj_col}" = {p}"{obj_col}"  
                            )
                        )
                    OR
                        (
                            {p}"{for_admin_only}" = False
                            AND EXISTS (
                                SELECT 'X' FROM "{org_table}" AS {unique_alias}
                                WHERE {unique_alias}."{org_obj_col}" = {p}"{obj_col}"
                                AND {unique_alias}."{org_org_col}" = {org_id}  
                            )                    
                        )
                    )
                """.format(
                    p=prefix,
                    for_admin_only=cls.__FOR_ADMIN_ONLY_FLD,
                    org_table=org_table,
                    unique_alias=unique_alias,
                    org_obj_col=org_obj_col,
                    obj_col=obj_col,
                    org_org_col=org_org_col,
                    org_id=fdp_organization_id
                )
        # User is an administrator, does not belong to the host organization, and we don't know where they belong
        elif (not is_host) and is_admin and (fdp_organization_id is None):
            return """
                (
                    {p}"{for_host_only}" = False AND NOT EXISTS (
                        SELECT 'X' FROM "{org_table}" AS {unique_alias}
                        WHERE {unique_alias}."{org_obj_col}" = {p}"{obj_col}"  
                    )
                )
            """.format(
                p=prefix,
                for_host_only=cls.__FOR_HOST_ONLY_FLD,
                org_table=org_table,
                unique_alias=unique_alias,
                org_obj_col=org_obj_col,
                obj_col=obj_col
            )
        # User is not an administrator, does not belong to the host organization, and we don't know where they belong
        elif (not is_host) and (not is_admin) and (fdp_organization_id is None):
            return """
                (
                    {p}"{for_host_only}" = False 
                    AND {p}"{for_admin_only}" = False
                    AND NOT EXISTS (
                        SELECT 'X' FROM "{org_table}" AS {unique_alias}
                        WHERE {unique_alias}."{org_obj_col}" = {p}"{obj_col}"  
                    )
                )
            """.format(
                p=prefix,
                for_host_only=cls.__FOR_HOST_ONLY_FLD,
                for_admin_only=cls.__FOR_ADMIN_ONLY_FLD,
                org_table=org_table,
                unique_alias=unique_alias,
                org_obj_col=org_obj_col,
                obj_col=obj_col
            )
        # User is an administrator, does not belong to the host organization, and belongs to a FDP organization
        elif (not is_host) and is_admin and (fdp_organization_id is not None):
            return """
                (
                    (
                        {p}"{for_host_only}" = False 
                        AND NOT EXISTS (
                            SELECT 'X' FROM "{org_table}" AS {unique_alias}
                            WHERE {unique_alias}."{org_obj_col}" = {p}"{obj_col}"  
                        )
                    )
                OR
                    (
                        {p}"{for_host_only}" = False 
                        AND EXISTS (
                            SELECT 'X' FROM "{org_table}" AS {unique_alias}
                            WHERE {unique_alias}."{org_obj_col}" = {p}"{obj_col}"
                            AND {unique_alias}."{org_org_col}" = {org_id}  
                        )                    
                    )
                )
            """.format(
                p=prefix,
                for_host_only=cls.__FOR_HOST_ONLY_FLD,
                for_admin_only=cls.__FOR_ADMIN_ONLY_FLD,
                org_table=org_table,
                unique_alias=unique_alias,
                org_obj_col=org_obj_col,
                obj_col=obj_col,
                org_org_col=org_org_col,
                org_id=fdp_organization_id
            )
        # User is not an administrator, does not belong to the host organization, and belongs to a FDP organization
        elif (not is_host) and (not is_admin) and (fdp_organization_id is not None):
            return """
                (
                    (
                        {p}"{for_host_only}" = False 
                        AND {p}"{for_admin_only}" = False
                        AND NOT EXISTS (
                            SELECT 'X' FROM "{org_table}" AS {unique_alias}
                            WHERE {unique_alias}."{org_obj_col}" = {p}"{obj_col}"  
                        )
                    )
                OR
                    (
                        {p}"{for_host_only}" = False
                        AND {p}"{for_admin_only}" = False
                        AND EXISTS (
                            SELECT 'X' FROM "{org_table}" AS {unique_alias}
                            WHERE {unique_alias}."{org_obj_col}" = {p}"{obj_col}"
                            AND {unique_alias}."{org_org_col}" = {org_id}  
                        )                    
                    )
                )
            """.format(
                p=prefix,
                for_host_only=cls.__FOR_HOST_ONLY_FLD,
                for_admin_only=cls.__FOR_ADMIN_ONLY_FLD,
                org_table=org_table,
                unique_alias=unique_alias,
                org_obj_col=org_obj_col,
                obj_col=obj_col,
                org_org_col=org_org_col,
                org_id=fdp_organization_id
            )
        # there was an invalid configuration of the properties
        else:
            raise ImproperlyConfigured(_('Confidential filter incorrectly configured'))

    @classmethod
    def filter_for_admin(cls, queryset, user):
        """ Filter a queryset for the admin interfaces.

        Assumes that queryset has already been filtered for direct confidentiality, i.e. whether user has access to
        each record based on the record's level of confidentiality. E.g. a confidentiable queryset of Person.

        Can be used to filter for indirect confidentiality, i..e whether user has access to each record based on other
        relevant records' levels of confidentiality. E.g. a queryset of PersonAlias linking to a confidentiality
        queryset of Person.

        :param queryset: Queryset to filter.
        :param user: User for which to filter queryset.
        :return: Filtered queryset.
        """
        raise Exception(_('All classes that inherit from Confidentiable should implement filter_for_admin'))

    class Meta:
        abstract = True


class Linkable(models.Model):
    """ Base class from which all linkable classes inherit.

    Can be used to help define the accuracy of a link between two models, such as for PersonIncident
    and ContentPerson.

    Attributes:
        :is_guess (bool): True if link is a guess, false otherwise.

    """
    is_guess = models.BooleanField(
        null=False,
        blank=False,
        default=False,
        verbose_name=_('Is this a guess'),
        help_text=_('Select if link is a guess')
    )

    class Meta:
        abstract = True


class Descriptable(models.Model):
    """ Base class from which all descriptable classes inherit.

    Descriptions are verbose user-friendly narratives about a person, incident or person grouping.

    Attributes:
        :description (str): Verbose user-friendly narrative.

    Attributes:
        :truncated_description (str): Truncated version of the verbose user-friendly narrative.

    """
    description = models.TextField(
        null=False,
        blank=True,
        verbose_name=_('Description'),
        help_text=_('Verbose, user-friendly narrative'),
    )

    def __get_truncated_description(self):
        """ Retrieve the truncated description ending with a suffix (e.g. "...").

        :return: Truncated description.
        """
        return AbstractStringValidator.truncate_description(description=self.description)

    @property
    def truncated_description(self):
        """ Truncated description ending with a suffix (e.g. "...").

        :return: Truncated description.
        """
        return self.__get_truncated_description()

    class Meta:
        abstract = True


class AbstractDateValidator(models.Model):
    """ An abstract definition of constants and methods used to validate dates.

    Attributes:
        There are no attributes.

    """
    # Maximum value that can be inserted into the year field
    MAX_YEAR = 2050

    # Minimum value that can be inserted into the year field, excluding 0
    MIN_YEAR = 1900

    # Maximum value that can be inserted into the month field
    MAX_MONTH = 12

    # Minimum value that can be inserted into the month field, excluding 0
    MIN_MONTH = 1

    # Maximum value that can be inserted into the day field
    MAX_DAY = 31

    # Minimum value that can be inserted into the day field, excluding 0
    MIN_DAY = 1

    # Value used to represent unknown components of the date, e.g. if the day is not known, then 2005-12-0
    UNKNOWN_DATE = 0

    # Localized text indicating that something occurred on a specific date, e.g. On January 1, 2000
    ON_DATE = _('on')

    # Localized text indicating that something started on a specific date, e.g. From January 1, 2000
    FROM_DATE = _('from')

    # Localized text indicating that something had started at least by a specific date, e.g. As of January 1, 2000
    AS_OF_DATE = _('as of')

    # Localized text indicating that something ended on a specific date, e.g. Until January 1, 2000
    UNTIL_DATE = _('until')

    # Localized text indicating that something occurred during a period of time, e.g. During 2018, e.g. During 2018-02
    DURING_DATE = _('during')

    @staticmethod
    def validate_year(value):
        """ Verify that the year input by the user is within the expected range.

        :param value: Year input by user that should be verified.
        :return: Nothing
        """
        if not str(value).isdigit() or value > AbstractDateValidator.MAX_YEAR or (
            value < AbstractDateValidator.MIN_YEAR and value != AbstractDateValidator.UNKNOWN_DATE
        ):
            raise ValidationError(
                _('%(v)s is not a valid year; please enter a value between {s} and {e}, or use {u} if unknown'),
                params={
                    'v': value, 's': AbstractDateValidator.MIN_YEAR,
                    'e': AbstractDateValidator.MAX_YEAR,
                    'u': AbstractDateValidator.UNKNOWN_DATE
                }
            )

    @staticmethod
    def validate_month(value):
        """ Verify that the month input by the user is within the expected range.

        :param value: Month input by user that should be verified.
        :return: Nothing
        """
        if not str(value).isdigit() or value > AbstractDateValidator.MAX_MONTH or (
            value < AbstractDateValidator.MIN_MONTH and value != AbstractDateValidator.UNKNOWN_DATE
        ):
            raise ValidationError(
                _('%(v)s is not a valid month; please enter a value between {s} and {e}, or use {u} if unknown'),
                params={
                    'v': value, 's': AbstractDateValidator.MIN_MONTH,
                    'e': AbstractDateValidator.MAX_MONTH,
                    'u': AbstractDateValidator.UNKNOWN_DATE
                }
            )

    @staticmethod
    def validate_day(value):
        """ Verify that the day input by the user is within the expected range.

        :param value: Day input by user that should be verified.
        :return: Nothing
        """
        if not str(value).isdigit() or value > AbstractDateValidator.MAX_DAY or (
            value < AbstractDateValidator.MIN_DAY and value != AbstractDateValidator.UNKNOWN_DATE
        ):
            raise ValidationError(
                _('%(v)s is not a valid day; please enter a value between {s} and {e}, or use {u} if unknown'),
                params={
                    'v': value, 's': AbstractDateValidator.MIN_DAY,
                    'e': AbstractDateValidator.MAX_DAY,
                    'u': AbstractDateValidator.UNKNOWN_DATE
                }
            )

    @classmethod
    def get_display_text_from_date(cls, year, month, day, prefix=''):
        """ Retrieve the human-friendly display version of a single fuzzy date (i.e. On MM/DD/YYYY).

        :param year: Year component for the fuzzy date, 0 if unknown.
        :param month: Month component for the fuzzy date, 0 if unknown.
        :param day: Day component for the fuzzy date, 0 if unknown.
        :param prefix: Localized prefix to prepend to date, e.g. "On MM/DD/YYYY", "From MM/DD/YYYY", etc.
        :return: A single fuzzy date in human-friendly display form.
        """
        # parameters passed to strftime
        y = '%Y'
        m = '%m'
        d = '%d'
        s = '/'
        # all components known
        if not (year == cls.UNKNOWN_DATE or month == cls.UNKNOWN_DATE or day == cls.UNKNOWN_DATE):
            date_str = date(year, month, day).strftime('{m}{s}{d}{s}{y}'.format(d=d, m=m, y=y, s=s))
        # all components unknown
        elif year == cls.UNKNOWN_DATE and month == cls.UNKNOWN_DATE and day == cls.UNKNOWN_DATE:
            return ''
        # some components missing
        else:
            def_year = 2000
            def_month = 1
            def_day = 1
            year_str = '' if year == cls.UNKNOWN_DATE else '{y}{s}'.format(
                s=s, y=date(year, def_month, def_day).strftime(y)
            )
            month_str = '' if month == cls.UNKNOWN_DATE else '{m}{s}'.format(
                s=s, m=date(def_year, month, def_day).strftime(m)
            )
            day_str = '' if day == cls.UNKNOWN_DATE else '{d}{s}'.format(
                s=s, d=date(def_year, def_month, day).strftime(d)
            )
            date_str = '{m}{d}{y}'.format(
                d=day_str, m=month_str, y=year_str
            ).strip().rstrip(s)
        # prepend "on"/"from"/"until" to date
        return '{o}{d}'.format(o='{p} '.format(p=prefix) if prefix else '', d=date_str)

    @classmethod
    def get_display_text_from_dates(cls, start_year, start_month, start_day, end_year, end_month, end_day, is_as_of):
        """ Retrieve the human-friendly display version of two fuzzy dates (i.e. From MM/DD/YYYY until MM/DD/YYYY).

        :param start_year: Year component for the starting fuzzy date, 0 if unknown.
        :param start_month: Month component for the starting fuzzy date, 0 if unknown.
        :param start_day: Day component for the starting fuzzy date, 0 if unknown.
        :param end_year: Year component for the ending fuzzy date, 0 if unknown.
        :param end_month: Month component for the ending fuzzy date, 0 if unknown.
        :param end_day: Day component for the ending fuzzy date, 0 if unknown.
        :param is_as_of: True if start date is as of, false if start date is exact.
        :return: A single fuzzy date in human-friendly display form.
        """
        from_str = cls.AS_OF_DATE if is_as_of else cls.FROM_DATE        
        # parameters passed to strftime
        y = '%Y'
        m = '%m'
        d = '%d'
        s = '/'
        # if all components are the same
        if start_year == end_year and start_month == end_month and start_day == end_day:
            # During 2018 or during 2018-09
            if (start_year != cls.UNKNOWN_DATE or start_month != cls.UNKNOWN_DATE) and start_day == cls.UNKNOWN_DATE:
                return cls.get_display_text_from_date(
                    year=start_year, month=start_month, day=start_day, prefix=cls.DURING_DATE
                )
            # On 2018-03-23
            else:            
                return cls.get_display_text_from_date(
                    year=start_year, month=start_month, day=start_day, prefix=cls.ON_DATE
                )
        # if starting components are all unknown
        elif start_year == cls.UNKNOWN_DATE and start_month == cls.UNKNOWN_DATE and start_day == cls.UNKNOWN_DATE:
            return cls.get_display_text_from_date(year=end_year, month=end_month, day=end_day, prefix=cls.UNTIL_DATE)
        # if ending components are all unknown
        elif end_year == cls.UNKNOWN_DATE and end_month == cls.UNKNOWN_DATE and end_day == cls.UNKNOWN_DATE:
            return cls.get_display_text_from_date(year=start_year, month=start_month, day=start_day, prefix=from_str)
        # starting components are different than ending components, but both have known components
        else:
            def_year = 2000
            def_month = 1
            def_day = 1
            # starting date
            start_year_str = '' if start_year == cls.UNKNOWN_DATE \
                else '{y}{s}'.format(s=s, y=date(start_year, def_month, def_day).strftime(y))
            start_month_str = '' if start_month == cls.UNKNOWN_DATE \
                else '{m}{s}'.format(s=s, m=date(def_year, start_month, def_day).strftime(m))
            start_day_str = '' if start_day == cls.UNKNOWN_DATE \
                else '{d}{s}'.format(s=s, d=date(def_year, def_month, start_day).strftime(d))
            start_date = '{m}{d}{y}'.format(d=start_day_str, m=start_month_str, y=start_year_str).strip().rstrip(s)
            # ending date
            end_year_str = '' if end_year == cls.UNKNOWN_DATE \
                else '{y}{s}'.format(s=s, y=date(end_year, def_month, def_day).strftime(y))
            end_month_str = '' if end_month == cls.UNKNOWN_DATE \
                else '{m}{s}'.format(s=s, m=date(def_year, end_month, def_day).strftime(m))
            end_day_str = '' if end_day == cls.UNKNOWN_DATE \
                else '{d}{s}'.format(s=s, d=date(def_year, def_month, end_day).strftime(d))
            end_date = '{m}{d}{y}'.format(d=end_day_str, m=end_month_str, y=end_year_str).strip().rstrip(s)
            # prepend "from"/"as of" and append "until" to date
            return '{f} {s} {u} {e}'.format(f=from_str, s=start_date, u=cls.UNTIL_DATE, e=end_date)

    @staticmethod
    def split_single_date_into_date_range(date_val):
        """ Splits a single date into a date range, i.e. start and end date.

        :param date_val: Single date value that should be split into a date range, i.e. start and end date.
        :return: A pair of dates: start date, end date. Will return None if single date is not defined.
        """
        if not date_val:
            return None
        else:
            return date_val, date_val

    @staticmethod
    def combine_date_range_into_single_date(start_date, end_date):
        """ Combines a date range, i.e. start and end date, into a single date.

        :param start_date: Starting date in date range.
        :param end_date: Ending date in date range.
        :return: A single date, or None if starting date and ending date in date ranges are not the same.
        """
        # both dates in date range are defined and are the same
        if start_date and end_date and start_date == end_date:
            return start_date
        # only start date is defined
        elif start_date and not end_date:
            return start_date
        # only end date is defined
        elif end_date and not start_date:
            return end_date
        # otherwise
        else:
            return None

    class Meta:
        abstract = True


class AbstractStringValidator(models.Model):
    """ An abstract definition of constants and methods used to validate strings.

    Attributes:
        There are no attributes.

    """
    # Maximum length of string (truncated description) used to represent a verbose description
    MAX_TRUNCATED_LENGTH = 200

    # Maximum number of words that can be combined into different permutations
    MAX_COMBO_WORDS = 20

    # Maximum number of different permutations that can be crated from words
    MAX_COMBINATIONS = 30

    # Characters to place after truncated description, indicating that the description has been truncated
    SUFFIX = _('...')

    # Length of characters placed after truncated description
    __suffix_length = len(SUFFIX)

    # Length of truncated description, excluding characters placed at the end as a suffix
    __truncated_length = MAX_TRUNCATED_LENGTH - __suffix_length

    @classmethod
    def truncate_description(cls, description):
        """ Truncate a verbose description.

        :param description: Description to truncate.
        :return: Truncated description
        """
        return '{u}'.format(u=settings.UNKNOWN) if not description else (
            '{a}{b}'.format(a=description[:cls.__truncated_length], b=cls.SUFFIX)
            if len(str(description)) > cls.MAX_TRUNCATED_LENGTH else description
        )

    class Meta:
        abstract = True


class AbstractPhoneValidator(models.Model):
    """ An abstract definition for storing phone numbers.

    Attributes:
        There are no attributes.

    """
    phone_validator = RegexValidator(
        regex=r'^\d{10}$',
        message=_('Phone number should contain only numbers and should be 10 characters long, e.g. 0123456789.')
    )

    max_length = 10

    class Meta:
        abstract = True


class AbstractForeignKeyValidator(models.Model):
    """ An abstract definition of constants and methods used to validate foreign keys.

    Attributes:
        There are no attributes.

    """
    @staticmethod
    def stringify_foreign_key(obj, foreign_key, unknown=settings.UNKNOWN):
        """ Creates a string version of the foreign key for an object.

        :param obj: Object whose foreign key should be stringified.
        :param foreign_key: Foreign key that should be stringified.
        :param unknown: Localized text used to represent an unknown value.
        :return: String versoin of the foreign key for the object.
        """
        return '{u}'.format(u=unknown) \
            if not hasattr(obj, foreign_key) or getattr(obj, foreign_key) is None \
            else getattr(obj, foreign_key).__str__()

    class Meta:
        abstract = True


class AbstractFileValidator(models.Model):
    """ An abstract definition of constants and methods used to validate user-uploaded files.

    Attributes:
        There are no attributes.

    """
    # Maximum length for the VARCHAR(...) file field storing the attachment path and filename
    MAX_ATTACHMENT_FILE_LEN = settings.MAX_NAME_LEN

    @staticmethod
    def get_megabytes_from_bytes(num_of_bytes):
        """ Converts bytes into megabytes.

        :param num_of_bytes: Number of bytes to convert to megabytes.
        :return: Number of megabytes.
        """
        return int(num_of_bytes / 1048576)

    @staticmethod
    def get_file_extension(file_path):
        """ Retrieves the file extension, without the preceding dot, for a file path.

        :param file_path: File path for which to retrieve file extension.
        :return: File extension, or blank if not relevant.
        """
        if file_path:
            file_name, extension = path.splitext(file_path)
            extension = extension.lower().lstrip('.')
        else:
            extension = ''
        return extension

    @staticmethod
    def get_file_name(file_path):
        """ Retrieves the file name, without the base url, for a file path.

        :param file_path: File path for which to retireve file name.
        :return: File name, or blank if not relevant
        """
        file_name = path.basename(file_path) if file_path else ''
        return file_name

    @staticmethod
    def validate_attachment_file_extension(value):
        """ Checks that a user uploaded attachment file extension is one that is supported by the system.

        :param value: User uploaded attachment file whose extension should be checked.
        :return: Nothing.
        """
        file_name, extension = path.splitext(value.name)
        extension = extension.lower()
        if extension not in ['.{x}'.format(x=x[1]) for x in AbstractConfiguration.supported_attachment_file_types()]:
            raise ValidationError(_('%(file)s is not a supported file type'), params={'file': value.name})

    @staticmethod
    def validate_attachment_file_size(value):
        """ Checks that a user uploaded attachment file size does not exceed allowable maximum.

        :param value: User uploaded attachment file whose size should be checked.
        :return: Nothing.
        """
        max_size = AbstractConfiguration.max_attachment_file_bytes()
        if value.size > max_size:
            raise ValidationError(
                _('%(file)s is %(size)s bytes exceeding the maximum allowable size of %(max)s bytes'),
                params={'file': value.name, 'size': value.size, 'max': max_size}
            )

    @staticmethod
    def validate_photo_file_extension(value):
        """ Checks that a user uploaded photo file extension is one that is supported by the system.

        :param value: User uploaded photo file whose extension should be checked.
        :return: Nothing.
        """
        file_name, extension = path.splitext(value.name)
        extension = extension.lower()
        if extension not in ['.{x}'.format(x=x[1]) for x in AbstractConfiguration.supported_person_photo_file_types()]:
            raise ValidationError(_('%(file)s is not a supported file type'), params={'file': value.name})

    @staticmethod
    def validate_photo_file_size(value):
        """ Checks that a user uploaded photo file size does not exceed allowable maximum.

        :param value: User uploaded photo file whose size should be checked.
        :return: Nothing.
        """
        max_size = AbstractConfiguration.max_person_photo_file_bytes()
        if value.size > max_size:
            raise ValidationError(
                _('%(file)s is %(size)s bytes exceeding the maximum allowable size of %(max)s bytes'),
                params={'file': value.name, 'size': value.size, 'max': max_size}
            )

    @staticmethod
    def zip_files(files_to_zip):
        """ Create ZIP archive for a list of files.

        :param files_to_zip: List of files to include in the ZIP archive.
        :return: Bytes representing ZIP archive.
        """
        # if there are no files to ZIP, then stop
        if not files_to_zip:
            raise Exception(_('There are no files to zip'))
        # stream to hold ZIP archive
        with BytesIO() as bytes_io:
            # create ZIP archive
            with ZipFile(bytes_io, mode='w') as zip_file:
                # cycle through each file to zip
                for file_to_zip in files_to_zip:
                    # open file
                    with file_to_zip.file.open() as f:
                        # read the file contents
                        zip_file.writestr(path.basename(file_to_zip.name), f.read())
            bytes_io.seek(0)
            zip_bytes = bytes_io.read()
        return zip_bytes

    @staticmethod
    def join_relative_and_root_paths(relative_path, root_path):
        """ Joins a relative path with the root path.

        :param relative_path: Relative path that will be joined to the root path.
        :param root_path: Root path that will be joined to the relative path.
        :return: Full path containing both root and relative paths.
        """
        normalized_relative_path = normpath(str(relative_path)).lstrip('/')
        full_path = Path(safe_join(root_path, normalized_relative_path))
        return full_path

    @classmethod
    def check_path_is_expected(cls, relative_path, root_path, expected_path_prefix, err_msg, err_cls):
        """ Checks that the path entered is in part or in full expected.

        Can prevent some directory traversal attacks.

        Can verify that path starts with a particular folder structure.

        :param relative_path: Relative path that will be joined to the root path.
        :param root_path: Root path that will be joined to the relative path.
        :param expected_path_prefix: Longest prefix that is expected for path. May be entire path, or may be a root,
        such as the media root.
        :param err_msg: Exception message to raise if path entered is not expected.
        :param err_cls: Exception class used to raise exception if path entered is not expected.
        :return: Nothing.
        """
        full_path = cls.join_relative_and_root_paths(relative_path=relative_path, root_path=root_path)
        # verify that full path is in part or in full expected
        if str(commonprefix((realpath(full_path), expected_path_prefix))) != str(expected_path_prefix):
            raise err_cls(err_msg)

    class Meta:
        abstract = True


class AbstractUrlValidator(models.Model):
    """ An abstract definition of constants and methods used to validate URLs.

    Attributes:
        There are no attributes.

    """
    # leftmost section of URLs used in the context of data management wizard
    CHANGING_BASE_URL = 'changing/'

    # relative URL for the page to close a popup opened through the data management tool
    CHANGING_CLOSE_POPUP_URL = '{b}close/popup'.format(b=CHANGING_BASE_URL)

    # relative URL for the admin home page from which user selects data management tool
    CHANGING_HOME_URL = '{b}home/'.format(b=CHANGING_BASE_URL)

    # relative URL to start the managing content data management tool
    CHANGING_CONTENT_URL = '{b}content/'.format(b=CHANGING_BASE_URL)

    # relative URL to add new content through the data management tool
    ADD_CONTENT_URL = '{b}add/content/'.format(b=CHANGING_CONTENT_URL)

    # relative URL to edit existing content through the data management tool
    EDIT_CONTENT_URL = '{b}update/content/'.format(b=CHANGING_CONTENT_URL)

    # relative URL to link allegations and penalties to existing content through the data management tool
    LINK_ALLEGATIONS_PENALTIES_URL = '{b}link/content/allegations/penalties/'.format(b=CHANGING_CONTENT_URL)

    # relative URL to start the managing incidents data management tool
    CHANGING_INCIDENTS_URL = '{b}incidents/'.format(b=CHANGING_BASE_URL)

    # relative URL to add new incident through the data management tool
    ADD_INCIDENT_URL = '{b}add/incident/'.format(b=CHANGING_INCIDENTS_URL)

    # relative URL to edit existing incident through the data management tool
    EDIT_INCIDENT_URL = '{b}update/incident/'.format(b=CHANGING_INCIDENTS_URL)

    # relative URL to start the managing persons data management tool
    CHANGING_PERSONS_URL = '{b}persons/'.format(b=CHANGING_BASE_URL)

    # relative URL to add new person through the data management tool
    ADD_PERSON_URL = '{b}add/person/'.format(b=CHANGING_PERSONS_URL)

    # relative URL to edit existing person through the data management tool
    EDIT_PERSON_URL = '{b}update/person/'.format(b=CHANGING_PERSONS_URL)

    # relative URL to start the managing groupings data management tool
    CHANGING_GROUPINGS_URL = '{b}groupings/'.format(b=CHANGING_BASE_URL)

    # relative URL to add new grouping through the data management tool
    ADD_GROUPING_URL = '{b}add/grouping/'.format(b=CHANGING_GROUPINGS_URL)

    # relative URL to edit existing grouping through the data management tool
    EDIT_GROUPING_URL = '{b}update/grouping/'.format(b=CHANGING_GROUPINGS_URL)

    # relative URL listing filtered and paginated results matching search criteria entered into the data management tool
    CHANGING_SEARCH_RESULTS_URL = '{b}list/'.format(b=CHANGING_BASE_URL)

    # relative URL to start the managing locations data management tool
    CHANGING_LOCATIONS_URL = '{b}locations/'.format(b=CHANGING_BASE_URL)

    # relative URL to add new location through the data management tool
    ADD_LOCATION_URL = '{b}add/location/'.format(b=CHANGING_LOCATIONS_URL)

    # relative URL to start the managing attachments data management tool
    CHANGING_ATTACHMENTS_URL = '{b}attachments/'.format(b=CHANGING_BASE_URL)

    # relative URL to add new attachment through the data management tool
    ADD_ATTACHMENT_URL = '{b}add/attachment/'.format(b=CHANGING_ATTACHMENTS_URL)

    # leftmost section of URLs used in the context of asynchronous data management tool requests
    ASYNC_CHANGING_BASE_URL = '{b}async/'.format(b=CHANGING_BASE_URL)

    # relative URL for asynchronously retrieving attachments for linking through the data management tool
    ASYNC_GET_ATTACHMENTS_URL = '{b}get/attachments/'.format(b=ASYNC_CHANGING_BASE_URL)

    # relative URL for asynchronously retrieving groupings through the data management tool
    ASYNC_GET_GROUPINGS_URL = '{b}get/groupings/'.format(b=ASYNC_CHANGING_BASE_URL)

    # relative URL for asynchronously retrieving persons through the data management tool
    ASYNC_GET_PERSONS_URL = '{b}get/persons/'.format(b=ASYNC_CHANGING_BASE_URL)

    # relative URL for asynchronously retrieving incidents through the data management tool
    ASYNC_GET_INCIDENTS_URL = '{b}get/incidents/'.format(b=ASYNC_CHANGING_BASE_URL)

    # leftmost section of URLs used in the context of import files for Django Data Wizard package, e.g. downloading
    # See: https://github.com/wq/django-data-wizard
    # this must be synchronized with data_wizard.sources.models.FileSource.file.upload_to
    DATA_WIZARD_IMPORT_BASE_URL = 'datawizard/'

    # leftmost section of URLs used in the context of attachments, e.g. downloading
    ATTACHMENT_BASE_URL = 'attm/'

    # leftmost section of URLs used in the context of person photos, e.g. downloading
    PERSON_PHOTO_BASE_URL = 'person/photo/'

    # leftmost section of URLs used in the context of officers, e.g. searching, retrieving results, and viewing officers
    OFFICER_BASE_URL = 'officer/'

    # relative URL for downloading files for officers
    OFFICER_DOWNLOAD_URL = '{b}download/'.format(b=OFFICER_BASE_URL)

    # relative URL for searching for officers
    OFFICER_SEARCH_URL = '{b}search/'.format(b=OFFICER_BASE_URL)

    # relative URL for retrieving search results for officers
    OFFICER_SEARCH_RESULTS_URL = '{s}results/'.format(s=OFFICER_SEARCH_URL)

    # relative URL for retrieving an officer, excludes the portion of the URL that specifies which officer
    OFFICER_URL = '{b}'.format(b=OFFICER_BASE_URL)

    # relative URL for downloading all files for an officer, excludes the portion of the URL that specifies which
    # officer
    OFFICER_DOWNLOAD_ALL_FILES_URL = '{d}all/'.format(d=OFFICER_DOWNLOAD_URL)

    # leftmost section of URLs used in the context of commands, e.g. searching, retrieving results, and viewing commands
    COMMAND_BASE_URL = 'command/'

    # relative URL for downloading files for commands
    COMMAND_DOWNLOAD_URL = '{b}download/'.format(b=COMMAND_BASE_URL)

    # relative URL for searching for commands
    COMMAND_SEARCH_URL = '{b}search/'.format(b=COMMAND_BASE_URL)

    # relative URL for retrieving search results for commands
    COMMAND_SEARCH_RESULTS_URL = '{s}results/'.format(s=COMMAND_SEARCH_URL)

    # relative URL for retrieving a command, excludes the portion of the URL that specifies which officer
    COMMAND_URL = '{b}'.format(b=COMMAND_BASE_URL)

    # relative URL for downloading all files for a command, excludes the portion of the URL that specifies which
    # command
    COMMAND_DOWNLOAD_ALL_FILES_URL = '{d}all/'.format(d=COMMAND_DOWNLOAD_URL)

    # leftmost section of URLs used in the context of managing FDP users
    FDP_USER_BASE_URL = ''

    # relative URL for a user to manage their own settings
    FDP_USER_SETTINGS_URL = '{b}settings/'.format(b=FDP_USER_BASE_URL)

    # relative URL for a user to confirm changing their own password
    FDP_USER_CONF_PWD_CHNG_URL = '{b}{s}password/change/confirm/'.format(b=FDP_USER_BASE_URL, s=FDP_USER_SETTINGS_URL)

    # relative URL for a user to confirm resetting their own 2FA
    FDP_USER_CONF_2FA_RESET_URL = '{b}{s}2fa/reset/confirm/'.format(b=FDP_USER_BASE_URL, s=FDP_USER_SETTINGS_URL)

    # relative URL for a user to reset their own password
    FDP_USER_CHNG_PWD_URL = '{b}{s}password/reset/'.format(b=FDP_USER_BASE_URL, s=FDP_USER_SETTINGS_URL)

    # relative URL for a user to reset their own 2FA
    FDP_USER_RESET_2FA_URL = '{b}{s}2fa/reset/'.format(b=FDP_USER_BASE_URL, s=FDP_USER_SETTINGS_URL)

    # relative URL for asynchronously renewing a user's session to avoid it expiring
    ASYNC_RENEW_SESSION_URL = '{b}async/renew/session/'.format(b=FDP_USER_BASE_URL)

    # queryset GET parameter used to identify original search criteria entered by user
    GET_ORIGINAL_PARAM = 'orig'

    # queryset GET parameters used to identify starting and ending date components
    GET_START_YEAR_PARAM = 'sy'
    GET_START_MONTH_PARAM = 'sm'
    GET_START_DAY_PARAM = 'sd'
    GET_END_YEAR_PARAM = 'ey'
    GET_END_MONTH_PARAM = 'em'
    GET_END_DAY_PARAM = 'ed'

    # queryset GET parameters used to identify whether a record is specified for host only
    GET_FOR_HOST_ONLY_PARAM = 'hostonly'

    # queryset GET parameters used to identify whether a record is specified for admin only
    GET_FOR_ADMIN_ONLY_PARAM = 'adminonly'

    # queryset GET parameters used to identify organizations to which a record is restricted
    GET_ORGS_PARAM = 'orgs'

    # queryset GET parameter used to identify previous link
    GET_PREV_URL_PARAM = 'back'

    # Encoding used during encryption and decryption of query string parameters and values
    ENCODING = 'utf-8'

    # Maximum length for link fields
    MAX_LINK_LEN = 500

    # name of parameter in JSON used to indicate that the server response contains an exception encountered
    JSON_ERR_PARAM = 'isError'

    # name of parameter in JSON used to contain exception encountered
    JSON_ERR_DAT_PARAM = 'error'

    # name of parameter in JSON used to indicate that the server response contains HTML code
    JSON_HTM_PARAM = 'isHtml'

    # name of parameter in JSON used to contain HTML
    JSON_HTM_DAT_PARAM = 'html'

    # name of parameter in JSON used to indicate that the server response contains data
    JSON_DAT_PARAM = 'isData'

    # name of parameter in JSON used to contain data
    JSON_DAT_DAT_PARAM = 'data'

    # name of parameter in JSON used to indicate that the server response is empty
    JSON_EMP_PARAM = 'isEmpty'

    # name of parameter in JSON used to indicate search criteria
    JSON_SRCH_CRT_PARAM = 'searchCriteria'

    # queryset GET parameter used to indicate that a view is being rendered as a popup
    GET_POPUP_PARAM = 'popup'

    # queryset GET parameter value used to indicate that a view is being rendered as a popup
    GET_POPUP_VALUE = 'TRUE'

    # queryset GET parameter used to indicate the unique identifier of the view that is being rendered as a popup
    GET_UNIQUE_POPUP_ID_PARAM = 'popupid'

    @classmethod
    def add_encrypted_value_to_querystring(cls, querystring, key, value_to_add):
        """ Add an encrypted value to the GET querystring.

        :param querystring: Querystring dictionary (i.e. a QueryDict object) to add the encrypted value to.
        :param key: Key for the value in the querystring.
        :param value_to_add: Value to add to the querystring.
        :return: GET querystring with encrypted value added.
        """
        f = Fernet(settings.QUERYSTRING_PASSWORD)
        encrypted_key = (f.encrypt(str.encode(key))).decode(cls.ENCODING)
        encrypted_value = (f.encrypt(str.encode(str(value_to_add)))).decode(cls.ENCODING)
        querystring.update({encrypted_key: encrypted_value})
        return querystring

    @classmethod
    def get_key_mapping(cls, list_of_keys):
        """ Retrieve a mapping between unencrypted and encrypted keys.

        :param list_of_keys: List of encrypted keys.
        :return: Dictionary mapping unencrypted to encrypted keys.
        """
        key_mapping = {}
        f = Fernet(settings.QUERYSTRING_PASSWORD)
        for k in list_of_keys:
            key_mapping[(f.decrypt(k.encode(cls.ENCODING))).decode(cls.ENCODING)] = k
        return key_mapping

    @classmethod
    def get_unencrypted_value_from_querystring(cls, querystring, key, default_value, key_mapping):
        """ Retrieve an encrypted value from the GET querystring.

        :param querystring: Querystring dictionary from which to retrieve encrypted value.
        :param key: Unencrypted key for the value in the querystring.
        :param default_value: Default value to use if the value is not found in the querystring.
        :param key_mapping: Mapping from unencrypted to encrypted keys in the querystring.
        :return: Unencrypted value retrieved from the GET querystring.
        """
        f = Fernet(settings.QUERYSTRING_PASSWORD)
        if key not in key_mapping:
            return default_value
        encrypted_value = querystring.get(key_mapping[key], default_value)
        if isinstance(encrypted_value, list) and encrypted_value:
            encrypted_value = encrypted_value[0]
        unencrypted_list = (f.decrypt(encrypted_value.encode(cls.ENCODING))).decode(cls.ENCODING) \
            if not encrypted_value == default_value else encrypted_value
        return unencrypted_list

    @classmethod
    def get_link(cls, url, is_popup, popup_id):
        """ Retrieves a link that is optionally framed as a popup.

        :param url: Full url for the link without any querystring. E.g. generated using: reverse('...:...').
        :param is_popup: True if link is in a popup context, false otherwise.
        :param popup_id: Unique identifier for the popup window. Will be None or empty string if not known or relevant.
        :return: Link with optional querystring specifying popup context.
        """
        # creating a link for a popup
        if is_popup:
            # querystring to indicate rendering a view in a popup
            popup_qs = QueryDict('', mutable=True)
            popup_qs.update({cls.GET_POPUP_PARAM: cls.GET_POPUP_VALUE})
            # a unique identifier for the popup window was provided
            if popup_id:
                popup_qs.update({cls.GET_UNIQUE_POPUP_ID_PARAM: popup_id})
            return '{b}?{q}'.format(b=url, q=popup_qs.urlencode())
        # not a popup
        else:
            return url

    class Meta:
        abstract = True


class AbstractIpAddressValidator(models.Model):
    """ An abstract definition of constants and methods used to validate IP address.

    Attributes:
        There are no attributes.

    """
    @staticmethod
    def get_ip_address(request):
        """ Retrieve the IP address from the Http request object.

        :param request: Http request object from which to retrieve IP address.
        :return: IP address
        """
        return get_client_ip_address(request=request)

    class Meta:
        abstract = True


class AbstractSearchValidator(models.Model):
    """ An abstract definition of constants and methods used to perform searches.

    Attributes:
        There are no attributes.

    """
    # Maximum number of characters displayed during a search for a verbose field such as a description.
    MAX_CHARS = 40

    # Regular expression pattern used to match an identifier (has at least three digits)
    _identifier_regex_pattern = r'.*\d.*\d.*\d.*'

    # Regular expression pattern used to represent number
    NUM_REGEX_PATTERN = _('(?:number|no|numb|num|identifier|id|#)')

    # Maximum results returned per data management wizard search
    MAX_WIZARD_SEARCH_RESULTS = 25

    # Representation of an empty conditional query used as a starting point when conditional queries are combined
    # dynamically
    EMPTY_Q = Q(pk__in=[])

    # An always false WHEN SQL statement ensuring that CASE WHEN ... THEN ... [WHEN ... THEN ... ] [ELSE] END is defined
    # Assigns integer value that is never used
    EMPTY_WHEN_INT = 'WHEN 1=0 THEN 0'

    # An always true SQL statement to check ensuring that a check is defined, even if no values should be checked
    EMPTY_SQL_CHECK_PASS = '1=1'

    # An always false SQL statement to check ensuring that a check is defined, even if no values should be checked
    EMPTY_SQL_CHECK_FAIL = '1=0'

    @classmethod
    def get_partial_check_sql(cls, num_of_checks, lhs_of_check, is_and, fail_on_default):
        """ Retrieves a dynamically constructed SQL statement performing partial case-insensitive comparisons against a
        list of string values.

        :param num_of_checks: Number of checks to add. Should match the number of string values in the list.
        :param lhs_of_check: Left-hand-side of the check specifying the table or table alias, and the field.
        E.g. "person"."name".
        :param is_and: True if checks should be AND-ed together, false if checks should be OR-ed together.
        :param fail_on_default: True if check should fail if not comparisons are to be made (i.e. num_of_checks < 1),
        false if check should succeed.
        :return: String  representing dynamically constructed SQL statement.
        """
        if num_of_checks > 0:
            partial_check_sql = ''
            for x in range(num_of_checks):
                partial_check_sql += """
                    {c} {lhs} ILIKE '%%' || %s || '%%' 
                """.format(
                    lhs=lhs_of_check,
                    c=('AND' if is_and else 'OR') if x > 0 else ''
                )
        else:
            partial_check_sql = cls.EMPTY_SQL_CHECK_FAIL if fail_on_default else cls.EMPTY_SQL_CHECK_PASS
        return partial_check_sql

    @classmethod
    def get_date_components_check_sql(cls, dates_to_check, table, is_and, fail_on_default):
        """ Retrieves a dynamically constructed SQL statement performing date comparisons against a list of date values.

        Assumes that the SQL statement is against date fields that are broken into individual components.

        :param dates_to_check: List of date values against which to construct comparisons.
        :param table: Name of table or table alias for which date comparisons should be made.
        :param is_and: True if comparisons should be AND-ed together, false if comparisons should be OR-ed together.
        :param fail_on_default: True if check should fail if not comparisons are to be made (i.e. num_of_checks < 1),
        false if check should succeed.
        :return: String representing dynamically constructed SQL statement.
        """
        if dates_to_check:
            date_check_sql = ''
            for i, date_to_check in enumerate(dates_to_check):
                date_check_sql += """
                    {c} (({sql_start}) OR ({sql_end}))
                """.format(
                    sql_start=AbstractExactDateBounded.get_start_date_sql(
                        table=table,
                        start_year=int(date_to_check.year),
                        start_month=int(date_to_check.month),
                        start_day=int(date_to_check.day)
                    ),
                    sql_end=AbstractExactDateBounded.get_end_date_sql(
                        table=table,
                        end_year=int(date_to_check.year),
                        end_month=int(date_to_check.month),
                        end_day=int(date_to_check.day)
                    ),
                    c=('AND' if is_and else 'OR') if i > 0 else ''
                )
        else:
            date_check_sql = cls.EMPTY_SQL_CHECK_FAIL if fail_on_default else cls.EMPTY_SQL_CHECK_PASS
        return date_check_sql

    @classmethod
    def get_date_field_check_sql(cls, dates_to_check, table, field, is_and, fail_on_default):
        """ Retrieves a dynamically constructed SQL statement performing date comparisons against a list of date values.

        Assumes that the SQL statement is against a single date field containing full dates.

        :param dates_to_check: List of date values against which to construct comparisons.
        :param table: Name of table or table alias for which date comparisons should be made.
        :param field: Name of field in table or table alias against which date comparisons should be made.
        :param is_and: True if comparisons should be AND-ed together, false if comparisons should be OR-ed together.
        :param fail_on_default: True if check should fail if not comparisons are to be made (i.e. num_of_checks < 1),
        false if check should succeed.
        :return: String representing dynamically constructed SQL statement.
        """
        if dates_to_check:
            date_check_sql = ''
            for i, date_to_check in enumerate(dates_to_check):
                date_check_sql += """
                    {c} "{table}"."{field}" = '{date}'::date
                """.format(
                    table=table,
                    field=field,
                    date=date_to_check.strftime("%Y-%m-%d"),
                    c=('AND' if is_and else 'OR') if i > 0 else ''
                )
        else:
            date_check_sql = cls.EMPTY_SQL_CHECK_FAIL if fail_on_default else cls.EMPTY_SQL_CHECK_PASS
        return date_check_sql

    @staticmethod
    def get_apostrophe_free_terms(terms):
        """ Retrieves a list of partial search terms with their apostrophes removed.

        :param terms: List of search terms to process.
        :return: List of partial terms with the apostrophe and any single leading characters stripped out.
        """
        apostrophe = '\''
        apostropheless_terms = []
        min_term_len = 2
        # cycle through all terms
        for term in terms:
            # term contains an apostrophe, e.g. O'Brien
            if apostrophe in term:
                # split the term, e.g. [O, Brien]
                chunks = term.split(apostrophe)
                # create list of partial terms that are greater than 2 characters in length, e.g. [Brien]
                apostropheless_terms.extend([chunk for chunk in chunks if len(chunk) > min_term_len])
        return apostropheless_terms

    @classmethod
    def get_adjacent_pairings(cls, search_text, handle_initials):
        """ Retrieves prioritized adjacent pairings while preserving the order for user entered search terms.

        E.g. "My search terms" becomes:
        [
            "My search terms",
            "My", "search", "terms",
            "My search", "search terms"
        ]

        :param search_text: Single string representing search text entered by user.
        :param handle_initials: True if pairings should include and exclude middle initials, false if pairings should
        be made as is.
        :return: List of adjacent pairings for the user entered search terms.
        """
        # maximum number of terms for which to perform algorithm
        max_terms_for_pairings = 6
        # create a list of all permutations of the search terms, include as originally entered and as single words
        pairings = [search_text]
        # split search text into a list of individual search terms
        all_terms = search_text.split()
        # combinations must include all terms individually
        pairings.extend(all_terms)
        # only add combinations if there are not so many words
        if len(all_terms) <= max_terms_for_pairings:
            for i, term in enumerate(all_terms, start=0):
                # if not the last term
                if i+1 < len(all_terms):
                    pairings.extend([' '.join([term, all_terms[i+1]])])
                    # if pairings should both include and exclude middle initials, and not second last term
                    if handle_initials and i+2 < len(all_terms) and re_match(r'[a-z][.]?', all_terms[i+1]):
                        pairings.extend([' '.join([term, all_terms[i+2]])])
        # remove duplicate combinations
        unique_combos = list(set(pairings))
        # sort by length, since max length should be matched first, if possible
        unique_combos.sort(key=len, reverse=True)
        return unique_combos

    @classmethod
    def get_dates(cls, search_text, remove_dates_from_search_text):
        """ Retrieves a list of dates from the search text entered by the user.

        See: https://dateparser.readthedocs.io/en/latest/

        :param search_text: Single string representing search text entered by user.
        :param remove_dates_from_search_text: True if any dates that are identified should be removed from the search
        text, false if the dates should be left.
        :return: A pair: optionally modified search text, list of dates retrieved from search text.
        """
        dates = []
        # settings for dateparser, see: https://dateparser.readthedocs.io/en/latest/#settings
        dp_settings = {'PREFER_DATES_FROM': 'past'}
        if hasattr(settings, 'DATE_ORDER') and settings.DATE_ORDER:
            dp_settings['DATE_ORDER'] = settings.DATE_ORDER
        languages = settings.DATE_LANGUAGES \
            if hasattr(settings, 'DATE_LANGUAGES') and settings.DATE_LANGUAGES else []
        # dateparser.search.search_dates(...) returns [('2019-12-31', datetime.datetime(2019,...)), ...]
        matched_tuples = search_dates(search_text, languages=languages, settings=dp_settings)
        # some dates were found in search text
        if matched_tuples:
            for matched_tuple in matched_tuples:
                date_in_search_text = matched_tuple[0]
                typed_date = matched_tuple[1]
                if remove_dates_from_search_text:
                    search_text = search_text.replace(date_in_search_text, '')
                dates.append(typed_date)
        return search_text, dates

    @classmethod
    def get_person_identifiers(cls, search_text, remove_identifiers_from_search_text):
        """ Retrieves all person identifiers from search text entered by the user.

        :param search_text: Single string representing search text entered by user.
        :param remove_identifiers_from_search_text: True if any identifiers that are identified should be removed
        from the search text, false if the identifiers should be left.
        :return: A pair: optionally modified search text, list of person identifiers retrieved from search text.
        """
        identifiers = []
        parsed_search_terms = []
        # split into individual search terms
        search_terms = search_text.split()
        # some search terms to check
        if search_terms:
            for search_term in search_terms:
                # search term matches regex pattern for person identifier
                if re_match(cls._identifier_regex_pattern, search_term):
                    identifiers.append(search_term)
                    # person identifier should not be removed from search terms
                    if not remove_identifiers_from_search_text:
                        parsed_search_terms.append(search_term)
                # search term is just a generic search term
                else:
                    parsed_search_terms.append(search_term)
            # rebuild search terms, optionally excluding the matched person identifiers
            search_text = ' '.join(parsed_search_terms)
        return search_text, identifiers

    @classmethod
    def get_content_identifiers(cls, search_text, remove_identifiers_from_search_text):
        """ Retrieves all content identifiers from search text entered by the user.

        :param search_text: Single string representing search text entered by user.
        :param remove_identifiers_from_search_text: True if any identifiers that are identified should be removed
        from the search text, false if the identifiers should be left.
        :return: A pair: optionally modified search text, list of content identifiers retrieved from search text.
        """
        identifiers = []
        parsed_search_terms = []
        # split into individual search terms
        search_terms = search_text.split()
        # some search terms to check
        if search_terms:
            for search_term in search_terms:
                # search term matches regex pattern for content identifier
                if re_match(cls._identifier_regex_pattern, search_term):
                    identifiers.append(search_term)
                    # content identifier should not be removed from search terms
                    if not remove_identifiers_from_search_text:
                        parsed_search_terms.append(search_term)
                # search term is just a generic search term
                else:
                    parsed_search_terms.append(search_term)
            # rebuild search terms, optionally excluding the matched content identifiers
            search_text = ' '.join(parsed_search_terms)
        return search_text, identifiers

    @classmethod
    def get_terms(cls, search_text):
        """ Retrieves a list of individual search terms entered by the user.

        :param search_text: Single string representing search text entered by user.
        :return: List of all individual search terms entered by the user.
        """
        # split the search terms into individual terms
        terms = search_text.split()
        # sort by length, since max length should be matched first, if possible
        terms.sort(key=len, reverse=True)
        return terms

    @classmethod
    def get_in_ids_list_check_sql(cls, list_of_ids, extra_check, lhs_of_check, fail_on_default):
        """ Retrieves a dynamically constructed SQL statement performing checks against a list of IDs.

        :param list_of_ids: List of IDs to check against. Must all be integers.
        :param extra_check: An optional additional check to couple with the check against a list of IDs.
        :param lhs_of_check: Left-hand-side of the IDs check specifying the table or table alias, and the field.
        E.g. "person"."id".
        :param fail_on_default: True if check should fail if no comparisons are to be made
        (i.e. there are no IDs in the list).
        :return: String representing dynamically constructed SQL statement.
        """
        if not extra_check:
            extra_check = ''
        if list_of_ids:
            in_ids_list_check_sql = """
                ({extra_check} {lhs}) IN ({list_of_ids})
            """.format(
                extra_check=extra_check,
                lhs=lhs_of_check,
                list_of_ids=','.join([str(int(id_in_list)) for id_in_list in list_of_ids])
            )
        else:
            in_ids_list_check_sql = cls.EMPTY_SQL_CHECK_FAIL if fail_on_default else cls.EMPTY_SQL_CHECK_PASS
        return in_ids_list_check_sql

    class Meta:
        abstract = True


class AbstractKnownInfo(models.Model):
    """ Base class from which classes that need a flexible known information structure can inherit.

    Known information allows a user to specify what information is known when making a link between two objects.

    For example, the shield number and last name of an officer may be known and used to link him/her to a particular
    incident.

    Attributes:
        :known_info (json): Known information to create record.

    """
    known_info = models.JSONField(
        null=True,
        blank=True,
        help_text=_('Known information to create record.'),
        verbose_name=_('known information')
    )

    class Meta:
        abstract = True


class AbstractAlias(Descriptable):
    """ Base class from which all alias classes inherit.

    Aliases provide an alternative name for a person, officer, grouping, etc.

    Attributes:
        :name (str): Alternative name.

    """
    name = models.CharField(
        null=False,
        blank=False,
        help_text=_('Alternative name, such as a nickname, acronym, or common misspelling'),
        max_length=settings.MAX_NAME_LEN,
        verbose_name=_('alias')
    )

    class Meta:
        abstract = True


class AbstractExactDateBounded(Descriptable):
    """ Base class from which all classes with exact bounding dates inherit.

    Attributes:
        :start_year (int): Year of start, use 0 if unknown.
        :start_month (int): Month of start, use 0 if unknown.
        :start_day (int): Day of start, use 0 if unknown.
        :end_year (int): Year of end, use 0 if unknown.
        :end_month (int): Month of end, use 0 if unknown.
        :end_day (int): Day of end, use 0 if unknown.

    Properties:
        :exact_bounding_dates (str): User-friendly rendering of the exact bounding dates.

    """
    start_year = models.PositiveSmallIntegerField(
        null=False,
        blank=False,
        default=AbstractDateValidator.UNKNOWN_DATE,
        help_text=_('Year of start, use {u} if unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE)),
        validators=[AbstractDateValidator.validate_year],
        verbose_name=_('starting year')
    )

    start_month = models.PositiveSmallIntegerField(
        null=False,
        blank=False,
        default=AbstractDateValidator.UNKNOWN_DATE,
        help_text=_('Month of start, use {u} if unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE)),
        validators=[AbstractDateValidator.validate_month],
        verbose_name=_('starting month')
    )

    start_day = models.PositiveSmallIntegerField(
        null=False,
        blank=False,
        default=AbstractDateValidator.UNKNOWN_DATE,
        help_text=_('Day of start, use {u} if unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE)),
        validators=[AbstractDateValidator.validate_day],
        verbose_name=_('starting day')
    )

    end_year = models.PositiveSmallIntegerField(
        null=False,
        blank=False,
        default=AbstractDateValidator.UNKNOWN_DATE,
        help_text=_('Year of end, use {u} if unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE)),
        validators=[AbstractDateValidator.validate_year],
        verbose_name=_('ending year')
    )

    end_month = models.PositiveSmallIntegerField(
        null=False,
        blank=False,
        default=AbstractDateValidator.UNKNOWN_DATE,
        help_text=_('Month of end, use {u} if unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE)),
        validators=[AbstractDateValidator.validate_month],
        verbose_name=_('ending month')
    )

    end_day = models.PositiveSmallIntegerField(
        null=False,
        blank=False,
        default=AbstractDateValidator.UNKNOWN_DATE,
        help_text=_('Day of end, use {u} if unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE)),
        validators=[AbstractDateValidator.validate_day],
        verbose_name=_('ending day')
    )

    #: Fields that can be used in inheriting classes to order by date
    order_by_date_fields = [
        'start_year', 'start_month', 'start_day', 'end_year', 'end_month', 'end_day'
    ]

    #: Ascending order for records
    ASCENDING = 'ASC'

    #: Descending order for records
    DESCENDING = 'DESC'

    #: Component for ordering by year in raw SQL
    order_by_sql_year = 'CASE WHEN {t}."end_year" > {t}."start_year" THEN {t}."end_year" ELSE {t}."start_year" END {o}'

    #: Component for ordering by month in raw SQL
    order_by_sql_month = \
        'CASE WHEN {t}."end_year" > {t}."start_year" THEN {t}."end_month" ELSE {t}."start_month" END {o}'

    #: Component for ordering by day in raw SQL
    order_by_sql_day = 'CASE WHEN {t}."end_year" > {t}."start_year" THEN {t}."end_day" ELSE {t}."start_day" END {o}'

    #: Ordering by year, month and day in raw SQL
    order_by_sql = order_by_sql_year + ', ' + order_by_sql_month + ', ' + order_by_sql_day

    #: Fields that can be used in the admin interface to filter by date
    list_filter_fields = order_by_date_fields

    #: String representation of the dates in a raw SQL
    sql_dates = """
        CASE
            WHEN {t}."start_year" = {t}."end_year"
            AND {t}."start_month" = {t}."end_month"
            AND {t}."start_day" = {t}."end_day"
            THEN
                CASE 
                    WHEN {t}."start_year" = 0 
                    THEN '' 
                    ELSE {t}."start_month" || '/' || {t}."start_day" || '/' || {t}."start_year"
                END 
            ELSE
                CASE
                    WHEN {t}."start_year" = 0
                    THEN ''
                    ELSE {t}."start_month" || '/' || {t}."start_day" || '/' || {t}."start_year"
                END
                ||
                CASE
                    WHEN {t}."start_year" = 0 OR {t}."end_year" = 0
                    THEN ''
                    ELSE ' - '
                END
                ||
                CASE
                    WHEN {t}."end_year" = 0
                    THEN ''
                    ELSE  
                    {t}."end_month" || '/' || {t}."end_day" || '/' || {t}."end_year"
                END 
            END  
    """

    #: Identifying date overlap between two unrelated models in raw SQL
    date_overlap_sql = """    
        (
                /* {E} start dates compared with {C} start dates */                                    
                (
                        {E}."start_year" > {C}."start_year" 
                    OR (
                            {E}."start_year" = {C}."start_year" 
                            AND {E}."start_month" > {C}."start_month" 
                            AND {C}."start_month" <> 0
                    ) 
                    OR (
                            {E}."start_year" = {C}."start_year" 
                            AND {E}."start_month" = {C}."start_month" 
                            AND {E}."start_day" >= {C}."start_day" 
                            AND {C}."start_day" <> 0
                    )
                )                              
            AND                              
                /* {E} start dates compared with {C} end dates */                              
                (
                        {E}."start_year" < {C}."end_year" 
                    OR (
                            {E}."start_year" = {C}."end_year" 
                            AND {E}."start_month" < {C}."end_month" 
                            AND {C}."end_month" <> 0
                    ) 
                    OR (
                            {E}."start_year" = {C}."end_year" 
                            AND {E}."start_month" = {C}."end_month" 
                            AND {E}."start_day" <= {C}."end_day"
                            AND {C}."end_month" <> 0
                    )
                )                           
            AND                              
                /* {E} end dates compared with {C} start dates */                                    
                (
                        {E}."end_year" > {C}."start_year" 
                    OR (
                            {E}."end_year" = {C}."start_year" 
                            AND {E}."end_month" > {C}."start_month" 
                            AND {C}."start_month" <> 0
                    )
                    OR (
                            {E}."end_year" = {C}."start_year" 
                            AND {E}."end_month" = {C}."start_month" 
                            AND {E}."end_day" >= {C}."start_day" 
                            AND	 {C}."start_day" <> 0
                    )
                )                              
            AND                              
                /* {E} end dates compared with {C} end dates */                              
                (
                        {E}."end_year" < {C}."end_year" 
                    OR (
                            {E}."end_year" = {C}."end_year" 
                            AND {E}."end_month" < {C}."end_month" 
                            AND {C}."end_month" <> 0
                    )
                    OR (
                            {E}."end_year" = {C}."end_year" 
                            AND {E}."end_month" = {C}."end_month" 
                            AND {E}."end_day" <= {C}."end_day" 
                            AND {C}."end_day" <> 0
                    )
                )                              
        )    
    """

    def __get_exact_bounding_dates(self):
        """ Retrieve the human-friendly version of the exact "fuzzy" exact starting and ending dates.

        :return: Human-friendly version of "fuzzy" exact starting and ending dates.
        """
        return AbstractDateValidator.get_display_text_from_dates(
            start_year=self.start_year, start_month=self.start_month, start_day=self.start_day,
            end_year=self.end_year, end_month=self.end_month, end_day=self.end_day, is_as_of=False
        )

    @property
    def exact_bounding_dates(self):
        """ Human-friendly version of "fuzzy" exact starting and ending dates.

        :return: Human-friendly version of "fuzzy" exact starting and ending dates.
        """
        return self.__get_exact_bounding_dates()

    @classmethod
    def get_start_date_sql(cls, table, start_year, start_month, start_day):
        """ Retrieve a partial SQL query to filter the complete start date.

        :param table: Table or table alias for which to filter start date.
        :param start_year: Start year by which to filter.
        :param start_month: Start month by which to filter.
        :param start_day: Start day by which to filter.
        :return: String containing partial SQL query used to filter the complete start date.
        """
        return '"{t}"."start_year" = {y} AND "{t}"."start_month" = {m} AND "{t}"."start_day" = {d}'.format(
            t=table,
            y=start_year,
            m=start_month,
            d=start_day
        )

    @classmethod
    def get_end_date_sql(cls, table, end_year, end_month, end_day):
        """ Retrieve a partial SQL query to filter the complete end date.

        :param table: Table or table alias for which to filter end date.
        :param end_year: End year by which to filter.
        :param end_month: End month by which to filter.
        :param end_day: End day by which to filter.
        :return: String containing partial SQL query used to filter the complete end date.
        """
        return '"{t}"."end_year" = {y} AND "{t}"."end_month" = {m} AND "{t}"."end_day" = {d}'.format(
            t=table,
            y=end_year,
            m=end_month,
            d=end_day
        )

    @staticmethod
    def check_start_date_before_end_date(
            start_year, start_month, start_day, end_year, end_month, end_day
    ):
        """ Verifies that the start date is before the end date.

        Can be called in an inheriting model form's clean(...) method.

        May raise ValidationError.

        :param start_year: Year component of start date.
        :param start_month: Month component of start date.
        :param start_day: Day component of start date.
        :param end_year: Year component of end date.
        :param end_month: Month component of end date.
        :param end_day: Day component of end date.
        :return: Nothing.
        """
        unknown = AbstractDateValidator.UNKNOWN_DATE
        # only validate if years are defined for both
        if start_year != unknown and end_year != unknown:
            # start year must be either before or equal to end year
            if start_year > end_year:
                raise ValidationError(_('Starting year must be either before or equal to the ending year'))
            # start year and end year are equal, so validate months if they are both defined
            if start_year == end_year and start_month != unknown and end_month != unknown:
                # years are equal, so start month must be either before or equal to end month
                if start_month > end_month:
                    raise ValidationError(_('If starting and ending years are equal, then the starting month '
                                            'must be either before or equal to the ending month'))
                # years are equal, start year and end month are equal, so validate days if they are both defined
                if start_month == end_month and start_day != unknown and end_day != unknown:
                    # years and months are equal, so start date must be either before or equal to end day
                    if start_day > end_day:
                        raise ValidationError(_('If both starting and ending years and months are equal, then the '
                                                'starting day must be either before or equal to the ending day'))

    def _check_start_date_before_end_date(self):
        """ Verifies that the start date is before the end date.

        Can be called in the inheriting model's clean(...) method.

        May raise ValidationError.

        :return: Nothing.
        """
        self.check_start_date_before_end_date(
            start_year=self.start_year,
            start_month=self.start_month,
            start_day=self.start_day,
            end_year=self.end_year,
            end_month=self.end_month,
            end_day=self.end_day
        )

    class Meta:
        abstract = True


class AbstractAsOfDateBounded(AbstractExactDateBounded):
    """ Base class from which all classes with as of bounding dates inherit.

    Attributes:
        :as_of (bool): True if start date is as of, i.e. start date is not true start date, false otherwise.

    Properties:
        :as_of_bounding_dates (str): User-friendly rendering of the as of bounding dates.

    """
    as_of = models.BooleanField(
        null=False,
        blank=False,
        default=False,
        help_text=_('Select if start date is the earliest known start date, but not necessarily the true start date'),
        verbose_name=_('as of')
    )

    #: Fields that can be used in the admin interface to filter by date
    list_filter_fields = AbstractExactDateBounded.order_by_date_fields + ['as_of']

    def __get_as_of_bounding_dates(self):
        """ Retrieve the human-friendly version of the "fuzzy" as of starting and ending dates.

        :return: Human-friendly version of "fuzzy" as of starting and ending dates.
        """
        return AbstractDateValidator.get_display_text_from_dates(
            start_year=self.start_year, start_month=self.start_month, start_day=self.start_day,
            end_year=self.end_year, end_month=self.end_month, end_day=self.end_day, is_as_of=self.as_of
        )

    @property
    def as_of_bounding_dates(self):
        """ Human-friendly version of "fuzzy" as of starting and ending dates.

        :return: Human-friendly version of "fuzzy" as of starting and ending dates.
        """
        return self.__get_as_of_bounding_dates()

    class Meta:
        abstract = True


class AbstractSql(models.Model):
    """ An abstract definition of constants and methods used to interact through SQL queries.

    Attributes:
        There are no attributes.

    """
    @staticmethod
    def exec_single_val_sql(sql_query, sql_params):
        """ Executes a SQL query that retrieves a single value.

        :param sql_query: SQL query to execute.
        :param sql_params: Parameters intended for the SQL query.
        :return: Single value retrieved by SQL query.
        """
        with connection.cursor() as cursor:
            cursor.execute(sql_query, sql_params)
            row = cursor.fetchone()
        return row[0]

    class Meta:
        abstract = True


class AbstractJson(models.Model):
    """ Abstract class from which all Json object wrapper classes inherit.

    """
    def get_json_dict(self):
        """ Retrieves a dictionary representing the JSON object to return through the JsonResponse.

        Must be overwritten.

        :return: Dictionary representing the JSON object.
        """
        pass

    class Meta:
        abstract = True


class JsonError(AbstractJson):
    """ Wrapper class for an error returned as a JSON object.

    Attributes:
        :error (string): Message describing error.
    """
    error = models.TextField(
        null=False,
        blank=False,
        verbose_name=_('error'),
        help_text=_('Message describing error'),
    )

    def get_json_dict(self):
        """ Retrieves a dictionary representing the JSON object containing the error to return through the JsonResponse.

        :return: Dictionary representing the JSON object containing the error.
        """
        return {
            AbstractUrlValidator.JSON_ERR_PARAM: True,
            AbstractUrlValidator.JSON_ERR_DAT_PARAM: self.error if self.error else ''
        }

    class Meta:
        abstract = True


class JsonData(AbstractJson):
    """ Wrapper class for JSON data object returned as a JSON object.

    Attributes:
        :data (json): Dictionary representation of the JSON data object.
    """
    data = models.JSONField(
        null=False,
        blank=True,
        verbose_name=_('JSON data'),
        help_text=_('JSON data to return'),
    )

    def get_json_dict(self):
        """ Retrieves a dictionary representing the JSON object containing the HTML to return through the JsonResponse.

        :return: Dictionary representing the JSON object containing the HTML.
        """
        return {
            AbstractUrlValidator.JSON_DAT_PARAM: True,
            AbstractUrlValidator.JSON_DAT_DAT_PARAM: self.data if self.data else {}
        }

    class Meta:
        abstract = True


class AbstractAnySearch(models.Model):
    """ All profile and changing search classes inherit from this class.

    It provides a definition of the attributes and methods that both profile and changing search classes may find
    useful.

    Attributes:
        :original_search_criteria (str): Original search text as it was entered by the user.
        :unique_table_suffix (str): Unique suffix used for temporary tables for this particular user and search context.

    Properties:
        :parsed_search_criteria (dict): Dictionary of parsed search criteria.
        :temp_table_prefix (str): Prefix that can be used to name temporary tables.
        :create_temp_table_sql (str): SQL statement that can be used to create a temporary table if it does not exist.
        :on_commit_temp_table_sql (str): SQL statement that can be used at the end of a temporary table definition.
        :temp_table_query (str): SQL definition for temporary table portion of query.
        :sql_from_query (str): SQL definition for FROM and WHERE portions of query.
        :temp_table_params (list): List of parameters for SQL definition for temporary table portion of query.
        :from_params (list): List of parameters for SQL definition for FROM and WHERE portions of query.
        :sql_score_query (str): SQL definition for scoring portion of query.
        :score_params (list): List of parameters for SQL definition for scoring portion of query.

    """
    #: Keys used in the dictionary of parsed search criteria, referring to its different components.
    #: Original search criteria as it was entered by the user.
    _original_key = 'original_search_terms'
    #: A list of lowercase search terms, each split by a single whitespace.
    _terms_key = 'terms'
    #: A list of adjacent pairings of search terms.
    _adjacent_pairings_key = 'adjacent_pairings'
    #: A list of primary keys for titles that were parsed out from the search criteria.
    _titles_key = 'titles'
    #: A list of person identifiers that were parsed out from the search criteria.
    _person_identifiers_key = 'person_identifiers'
    #: A list of content identifiers that were parsed out from the search criteria.
    _content_identifiers_key = 'content_identifiers'
    #: A list of primary keys for counties that were parsed out from the search criteria.
    _counties_key = 'counties'
    #: A list of dates that were parsed out from the search criteria.
    _dates_key = 'dates'

    #: Default scores assigned for search criteria
    #: Default primary name score
    _primary_name_score = 10
    #: Default primary alias score
    _primary_alias_score = 5
    #: Default secondary name score
    _secondary_name_score = 2
    #: Default secondary alias score
    _secondary_alias_score = 1
    #: Default primary identifier score
    _primary_identifier_score = 10
    #: Default secondary identifier score
    _secondary_identifier_score = 5
    #: Default primary lookup score
    _primary_lookup_score = 30
    #: Default secondary lookup score
    _secondary_lookup_score = 6
    #: Default primary date score
    _primary_date_score = 60
    #: Default secondary date score
    _secondary_date_score = 30

    #: Name for temporary tables in the database.
    #: Name of Temporary Table for Person table scores in the database.
    _tmp_person_score = '{prefix}person_score{suffix}'
    #: Name of Temporary Table for Grouping table scores in the database.
    _tmp_grouping_score = '{prefix}grouping_score{suffix}'
    #: Name of Temporary Table for Incident table scores in the database.
    _tmp_incident_score = '{prefix}incident_score{suffix}'
    #: Name of Temporary Table for Content table scores in the database.
    _tmp_content_score = '{prefix}content_score{suffix}'
    #: Name of Temporary Table for Attachment table scores in the database.
    _tmp_attachment_score = '{prefix}attachment_score{suffix}'
    #: Name of Temporary Table for Grouping Alias table scores in the database.
    _tmp_grouping_alias_score = '{prefix}grouping_alias_score{suffix}'
    #: Name of Temporary Table for Person Alias table scores in the database.
    _tmp_person_alias_score = '{prefix}person_alias_score{suffix}'
    #: Name of Temporary Table for Person Identifier table scores in the database.
    _tmp_person_identifier_score = '{prefix}person_identifier_score{suffix}'
    #: Name of Temporary Table for Content Identifier table scores in the database.
    _tmp_content_identifier_score = '{prefix}content_identifier_score{suffix}'
    #: Name of Temporary Table for Content Case table scores in the database.
    _tmp_content_case_score = '{prefix}content_case_score{suffix}'

    def _get_primary_name_score(self, name):
        """ Retrieves the search score for a particular name match on the main search object.

        An example is person name during a person search.

        :param name: Name for which search score should be calculated.
        :return: Search score for name.
        """
        return len(name) * self._primary_name_score

    def _get_primary_alias_score(self, alias):
        """ Retrieves the search score for a particular alias match on the main search object.

        An example is person alias during a person search.

        :param alias: Alias for which search score should be calculated.
        :return: Search score for alias.
        """
        return len(alias) * self._primary_alias_score

    def _get_primary_lookup_score(self):
        """ Retrieves the search score for a particular lookup value match on the primary search object.

        An example is person trait during a person search.

        :return: Search score for lookup value.
        """
        return self._primary_lookup_score

    def _get_secondary_lookup_score(self):
        """ Retrieves the search score for a particular lookup value match on the secondary search object.

        An example is grouping county during a person search.

        :return: Search score for lookup value.
        """
        return self._secondary_lookup_score

    def _get_secondary_name_score(self, name):
        """ Retrieves the search score for a particular name match on the secondary search object.

        An example is grouping name during a person search.

        :param name: Name for which search score should be calculated.
        :return: Search score for name.
        """
        return len(name) * self._secondary_name_score

    def _get_secondary_alias_score(self, alias):
        """ Retrieves the search score for a particular alias match on the secondary search object.

        An example is grouping alias during a person search.

        :param alias: Alias for which search score should be calculated.
        :return: Search score for alias.
        """
        return len(alias) * self._secondary_alias_score

    def _get_primary_identifier_score(self, identifier):
        """ Retrieves the search score for a particular identifier match on the main search object.

        An example is person identifier during a person search.

        :param identifier: Identifier for which search score should be calculated.
        :return: Search score for identifier.
        """
        return len(identifier) * self._primary_identifier_score

    def _get_secondary_identifier_score(self, identifier):
        """ Retrieves the search score for a particular identifier match on the secondary search object.

        An example is person identifier during a content search.

        :param identifier: Identifier for which search score should be calculated.
        :return: Search score for identifier.
        """
        return len(identifier) * self._secondary_identifier_score

    def _get_primary_date_score(self):
        """ Retrieves the search score for a particular date match on the primary search object.

        An example is content publication date during a content search.

        :return: Search score for date.
        """
        return self._primary_date_score

    def _get_secondary_date_score(self):
        """ Retrieves the search score for a particular date match on the secondary search object.

        An example is content case date during a content search.

        :return: Search score for date.
        """
        return self._secondary_date_score

    original_search_criteria = models.CharField(
        null=False,
        blank=True,
        max_length=settings.MAX_NAME_LEN,
        help_text=_('Original search text as it was entered by the user'),
        verbose_name=_('original search text')
    )

    unique_table_suffix = models.CharField(
        null=False,
        blank=True,
        max_length=settings.MAX_NAME_LEN,
        help_text=_('Unique suffix used for temporary tables for this particular user and search context'),
        verbose_name=_('unique table suffix')
    )

    @property
    def parsed_search_criteria(self):
        """ Retrieves a dictionary of the parsed search criteria if it exists, otherwise an empty dictionary.

        :return: Dictionary of parsed search criteria if it exists, otherwise an empty dictionary.
        """
        if hasattr(self, '_parsed_search_criteria') and self._parsed_search_criteria:
            return self._parsed_search_criteria
        else:
            return {}

    @property
    def temp_table_query(self):
        """ Retrieves the SQL definition for temporary table portion of query.

        :return: SQL definition.
        """
        if hasattr(self, '_temp_table_query') and self._temp_table_query:
            return self._temp_table_query
        else:
            return ''

    @property
    def sql_from_query(self):
        """ Retrieves the SQL definition for FROM and WHERE portions of query.

        :return: SQL definition.
        """
        if hasattr(self, '_sql_from_query') and self._sql_from_query:
            return self._sql_from_query
        else:
            return ''

    @property
    def sql_score_query(self):
        """ Retrieves the SQL definition for scoring portion of query.

        :return: SQL definition.
        """
        if hasattr(self, '_sql_score_query') and self._sql_score_query:
            return self._sql_score_query
        else:
            return ''

    @property
    def temp_table_params(self):
        """ Retrieves the list of parameters for SQL definition for temporary table portion of query.

        :return: List of parameters.
        """
        if hasattr(self, '_temp_table_params') and self._temp_table_params:
            return self._temp_table_params
        else:
            return []

    @property
    def from_params(self):
        """ Retrieves the list of parameters for SQL definition for FROM and WHERE portions of query.

        :return: List of parameters.
        """
        if hasattr(self, '_from_params') and self._from_params:
            return self._from_params
        else:
            return []

    @property
    def score_params(self):
        """ Retrieves the list of parameters for SQL definition for scoring portion of query.

        :return: List of parameters.
        """
        if hasattr(self, '_score_params') and self._score_params:
            return self._score_params
        else:
            return []

    @property
    def temp_table_prefix(self):
        """ Retrieves a prefix that can be used to name temporary tables.

        :return: Prefix that can be used to name temporary tables.
        """
        return 'temp_'

    @property
    def create_temp_table_sql(self):
        """ Retrieves a SQL statement that can be used to create a temporary table if it does not exist.

        Compatible with PostgreSQL.

        :return: SQL statement.
        """
        return 'CREATE TEMP TABLE IF NOT EXISTS'

    @property
    def on_commit_temp_table_sql(self):
        """ Retrieves a SQL statement that can be used at the end of a temporary table definition.

        Compatible with PostgreSQL.

        :return: SQL statement.
        """
        return 'ON COMMIT DROP;'

    @classmethod
    def get_unique_table_suffix(cls, user):
        """ Retrieves a suffix that can be appended to a temporary table name, to ensure that it is unique.

        Suffix will include the primary key used to identify the user, and a numeric representation of the current time.

        :param user: User for which to create unique suffix.
        :return: Suffix that can be appended to a temporary table name.
        """
        return '_{u}_{i}'.format(u=user.pk, i=str(now().timestamp()).replace('.', ''))

    @abstractmethod
    def parse_search_criteria(self):
        """ Retrieves a dictionary of the parsed search criteria that was entered by the user.

        :return: Dictionary of parsed search criteria.
        """
        pass

    def common_parse_search_criteria(self):
        """ Common portion of algorithm to parse out the search criteria that is entered by the user.

        Makes a call to the customizable portion of the algorithm, then uses the results to set
        the self._parsed_search_criteria property.
        :return: Nothing.
        """
        self._parsed_search_criteria = self.parse_search_criteria()

    @abstractmethod
    def define_sql_query_body(self, user):
        """ Defines the body of the SQL query, and optionally any preceding temporary tables, used to retrieve records
        matching the parsed search criteria.

        :param user: User performing the search.
        :return: A tuple containing four elements in the following order:
            0: SQL statement with optional temporary table definitions
            1: SQL statement with FROM and WHERE portions of main query
            2: Parameters for SQL statement for optional temporary table definitions
            3: Parameters for SQL statement for FROM and WHERE portions of main query
        """
        pass

    def common_define_sql_query_body(self, user):
        """ Common portion of algorithm to define the body of the SQL query, and optionally any preceding temporary
        tables, used to retrieve records matching the parsed search criteria.

        Makes a call to the customizable portion of the algorithm, then uses the results to set the following
        properties:
         - self._temp_table_query
         - self._sql_from_query
         - self._temp_table_params
         - self._from_params

        :param user: User performing the search.
        :return: Nothing.
        """
        temp_table_query, sql_from_query, temp_table_params, from_params = self.define_sql_query_body(user=user)
        self._temp_table_query = temp_table_query
        self._sql_from_query = sql_from_query
        self._temp_table_params = temp_table_params
        self._from_params = from_params

    @abstractmethod
    def define_sql_query_score(self):
        """ Defines the scoring portion of the SQL query used to retrieve records matching the parsed search criteria.

        :return: A tuple containing two elements in the following order:
            0: SQL statement with definition for scoring column in main query
            1: Parameters for SQL statement for definition for scoring column in main query

        """
        pass

    def common_define_sql_query_score(self):
        """ Common portion of algorithm to define the scoring for the SQL query, used to retrieve records matching the
        parsed search criteria.

        Males a call to the customizable portion of the algorithm, then uses the results to set the following
        properties:
         - self._sql_score_query
         - self._score_params

        :return: Nothing.
        """
        sql_score_query, score_params = self.define_sql_query_score()
        self._sql_score_query = sql_score_query
        self._score_params = score_params

    class Meta:
        abstract = True
        managed = False


class AbstractProfileSearch(AbstractAnySearch):
    """ All profile search classes inherit from this class.

    It provides a definition of the attributes and methods that each profile search class must have.

    Attributes:
        None.

    Properties:
        None.

    """
    @abstractmethod
    def parse_search_criteria(self):
        """ Retrieves a dictionary of the parsed search criteria that was entered by the user.

        :return: Dictionary of parsed search criteria.
        """
        pass

    @abstractmethod
    def define_sql_query_body(self, user):
        """ Defines the body of the SQL query, and optionally any preceding temporary tables, used to retrieve records
        matching the parsed search criteria.

        :param user: User performing the search.
        :return: A tuple containing four elements in the following order:
            0: SQL statement with optional temporary table definitions
            1: SQL statement with FROM and WHERE portions of main query
            2: Parameters for SQL statement for optional temporary table definitions
            3: Parameters for SQL statement for FROM and WHERE portions of main query
        """
        pass

    @abstractmethod
    def define_sql_query_score(self):
        """ Defines the scoring portion of the SQL query used to retrieve records matching the parsed search criteria.

        :return: A tuple containing two elements in the following order:
            0: SQL statement with definition for scoring column in main query
            1: Parameters for SQL statement for definition for scoring column in main query

        """
        pass

    class Meta:
        abstract = True
        managed = False


class AbstractChangingSearch(AbstractAnySearch):
    """ All changing search classes inherit from this class.

    It provides a definition of the attributes and methods that each changing search class must have.

    Attributes:
        None.

    Properties:
        :entity_to_count (str): Full name of entity to count when counting total search results.
        Can use the method get_db_table() on the main model being searched.
        :entity (cls): Class for the main model being searched.

    """
    @property
    @abstractmethod
    def entity_to_count(self):
        """ Full name of entity to count when counting total search results. Can use the method get_db_table() on the
        main model being searched.

        :return: String representing full name for entity in database.
        """
        pass

    @property
    @abstractmethod
    def entity(self):
        """ Class for the main model being searched.

        :return: Class for main model.
        """
        pass

    @abstractmethod
    def parse_search_criteria(self):
        """ Retrieves a dictionary of the parsed search criteria that was entered by the user.

        :return: Dictionary of parsed search criteria.
        """
        pass

    @abstractmethod
    def define_sql_query_body(self, user):
        """ Defines the body of the SQL query, and optionally any preceding temporary tables, used to retrieve records
        matching the parsed search criteria.

        :param user: User performing the search.
        :return: A tuple containing four elements in the following order:
            0: SQL statement with optional temporary table definitions
            1: SQL statement with FROM and WHERE portions of main query
            2: Parameters for SQL statement for optional temporary table definitions
            3: Parameters for SQL statement for FROM and WHERE portions of main query
        """
        pass

    @abstractmethod
    def define_sql_query_score(self):
        """ Defines the scoring portion of the SQL query used to retrieve records matching the parsed search criteria.

        :return: A tuple containing two elements in the following order:
            0: SQL statement with definition for scoring column in main query
            1: Parameters for SQL statement for definition for scoring column in main query

        """
        pass

    class Meta:
        abstract = True
        managed = False


class AbstractImport(models.Model):
    """ An abstract definition of methods and constants to load modules and classes dynamically based on settings.

    This is used to enable customization of the system, for instance the algorithms used in profile searches.

    """
    #: Base path for importing modules and classes for profile searches.
    __profile_searches_base_path = 'profiles.searches'

    #: Base path for importing modules and classes for changing searches.
    __changing_searches_base_path = 'changing.searches'

    @staticmethod
    def __get_class(base_path, file_setting, class_setting, file_default, class_default):
        """ Retrieves a class definition that is loaded dynamically.

        Used to enable customization of the system, for instance the algorithms used in profile searches.

        :param base_path: Base path for module to import. See variables defined in this class.
        :param file_setting: Name of variable in Django settings containing module name to import.
        :param class_setting: Name of variable in Django settings containing class name to import.
        :param file_default: Name of module to import if settings are not correctly configured or are undefined.
        :param class_default: Name of class to import if settings are not correctly configured or are undefined.
        :return: Class definition loaded dynamically.
        """
        # Load a module and class dynamically based on the configuration in the settings
        if getattr(settings, file_setting, None) and getattr(settings, class_setting, None):
            # name of module to import from
            module_name = getattr(settings, file_setting)
            # ensure that module name does not end with Python file extension, i.e. ".py"
            dot_py = '.py'
            if module_name.endswith(dot_py):
                module_name = module_name[:-len(dot_py)]
            # module that contains the class
            imported_module = import_module('{b}.{f}'.format(b=base_path, f=module_name))
            # class to import
            if imported_module and getattr(imported_module, getattr(settings, class_setting), None):
                return getattr(imported_module, getattr(settings, class_setting))
        # configuration in the settings was not correct or not defined (e.g. module or class does not exist)
        imported_module = import_module('{b}.{f}'.format(b=base_path, f=file_default))
        return getattr(imported_module, class_default)

    @classmethod
    def load_profile_search(cls, file_setting, class_setting, file_default, class_default):
        """ Retrieves a profile search class definition that is loaded dynamically.

        :param file_setting: Name of variable in Django settings containing module name to import.
        :param class_setting: Name of variable in Django settings containing class name to import.
        :param file_default: Name of module to import if settings are not correctly configured or are undefined.
        :param class_default: Name of class to import if settings are not correctly configured or are undefined.
        :return: Class definition loaded dynamically.
        """
        return cls.__get_class(
            base_path=cls.__profile_searches_base_path,
            file_setting=file_setting,
            class_setting=class_setting,
            file_default=file_default,
            class_default=class_default
        )

    @classmethod
    def load_changing_search(cls, file_setting, class_setting, file_default, class_default):
        """ Retrieves a changing search class definition that is loaded dynamically.

        :param file_setting: Name of variable in Django settings containing module name to import.
        :param class_setting: Name of variable in Django settings containing class name to import.
        :param file_default: Name of module to import if settings are not correctly configured or are undefined.
        :param class_default: Name of class to import if settings are not correctly configured or are undefined.
        :return: Class definition loaded dynamically.
        """
        return cls.__get_class(
            base_path=cls.__changing_searches_base_path,
            file_setting=file_setting,
            class_setting=class_setting,
            file_default=file_default,
            class_default=class_default
        )

    class Meta:
        abstract = True


class AbstractConfiguration(models.Model):
    """ An abstract definition of methods and constants to interact with and interpret settings.

    This is used to encapsulate logic to check multiple settings at once, for instance if password resets are
    configured correctly, or if support for Azure Active Directory is configured correctly.

    """
    #: Value for provider that will define a social authentication record linked to a user authenticated who is
    #: through Azure Active Directory.
    #: See: https://python-social-auth.readthedocs.io/en/latest/backends/azuread.html
    azure_active_directory_provider = CONST_AZURE_AD_PROVIDER

    @staticmethod
    def is_using_local_configuration():
        """ Checks whether settings intended for a local development environment have been configured.

        :return: True if settings are intended for a local development environment, false otherwise.
        """
        return getattr(settings, 'USE_LOCAL_SETTINGS', False)

    @staticmethod
    def is_using_azure_configuration():
        """ Checks whether settings intended for a Microsoft Azure environment have been configured.

        :return: True if settings are intended for a Microsoft Azure environment, false otherwise.
        """
        return getattr(settings, 'USE_AZURE_SETTINGS', False)

    @classmethod
    def can_do_password_reset(cls):
        """ Checks whether the necessary settings have been configured to enable password resets.

        :return: True if password resets are possible, false otherwise.
        """
        # password resets can be performed if configured for local development OR reCAPTCHA and email are defined
        return cls.is_using_local_configuration() or (
            (
                # if both public and private reCAPTCHA keys are defined, AND
                settings.RECAPTCHA_PUBLIC_KEY and settings.RECAPTCHA_PRIVATE_KEY
            ) and (
                # if both email host username and password are defined
                settings.EMAIL_HOST_PASSWORD and settings.EMAIL_HOST_USER
            )
        )

    @staticmethod
    def can_do_azure_active_directory():
        """ Checks whether the necessary settings have been configured to enable support for Azure Active Directory.

        :return: True if Azure Active Directory is supported, false otherwise.
        """
        return settings.EXT_AUTH == settings.AAD_EXT_AUTH

    @classmethod
    def skip_django_2fa_for_azure(cls):
        """ Checks whether the Django implemented 2FA verification step can be skipped for users authenticated through
        Azure Active Directory, since Azure offers its own implementation of 2FA.

        By default all users authenticated through Azure Active Directory skip the Django implemented 2FA step with the
        assumption that 2FA is already implemented through Azure.

        :return: True if the Django implemented 2FA verification step can be skipped for users authenticated through
        Azure Active Directory, false otherwise.
        """
        return cls.can_do_azure_active_directory() and True

    @classmethod
    def use_only_azure_active_directory(cls):
        """ Checks whether the necessary settings have been configured to enforce user authentication only through
        Azure Active Directory.

        :return: True if user authentication is only through Azure Active Directory, false otherwise.
        """
        return cls.can_do_azure_active_directory() and settings.USE_ONLY_AZURE_AUTH

    @staticmethod
    def disable_versioning_for_data_wizard_imports():
        """ Checks whether the necessary settings have been configured to disable record versioning when importing
        through the Django Data Wizard package in the Bulk Import app.

        Versioning can be disabled to improve performance while importing records.

        :return: True if versioning of records should be disabled.
        """
        return getattr(settings, 'DISABLE_REVERSION_FOR_DATA_WIZARD', False)

    @staticmethod
    def num_of_secs_between_data_wizard_import_status_checks():
        """ Checks the necessary settings to retrieve the number of seconds that should elapse between asynchronous GET
        requests to check for the status of importing records through the Django Data Wizard package in the Bulk Import
        app.

        Increasing the number of seconds can improve performance while importing records.

        :return: Number of seconds.
        """
        return getattr(settings, 'DATA_WIZARD_STATUS_CHECK_SECONDS', 1)

    @staticmethod
    def max_attachment_file_bytes():
        """ Checks the necessary setting to retrieve the maximum number of bytes that a user-uploaded file can have
        for an instance of the Attachment model.

        :return: Number of bytes.
        """
        return getattr(settings, 'FDP_MAX_ATTACHMENT_FILE_BYTES',  CONST_MAX_ATTACHMENT_FILE_BYTES)

    @staticmethod
    def supported_attachment_file_types():
        """ Checks the necessary setting to retrieve a list of tuples that define the types of user-uploaded files that
        are supported for an instance of the Attachment model. Each tuple has two items: the first is a user-friendly
        short description of the supported file type; the second is the expected extension of the supported file type.

        :return: List of tuples, each with two items.
        """
        return getattr(settings, 'FDP_SUPPORTED_ATTACHMENT_FILE_TYPES',  CONST_SUPPORTED_ATTACHMENT_FILE_TYPES)

    @staticmethod
    def max_person_photo_file_bytes():
        """ Checks the necessary setting to retrieve the maximum number of bytes that a user-uploaded file can have for
        an instance of the Person Photo model.

        :return: Number of bytes.
        """
        return getattr(settings, 'FDP_MAX_PERSON_PHOTO_FILE_BYTES',  CONST_MAX_PERSON_PHOTO_FILE_BYTES)

    @staticmethod
    def supported_person_photo_file_types():
        """ Checks the necessary setting to retrieve a list of tuples that define the types of user-uploaded files that
        are supported for an instance of the Person Photo model. Each tuple has two items: the first is a user-friendly
        short description of the supported file type; the second is the expected extension of the supported file type.

        :return: List of tuples, each with two items.
        """
        return getattr(settings, 'FDP_SUPPORTED_PERSON_PHOTO_FILE_TYPES',  CONST_SUPPORTED_PERSON_PHOTO_FILE_TYPES)

    @staticmethod
    def whitelisted_django_data_wizard_urls():
        """ Checks the necessary settings to retrieve the whitelisted URLs that will be used to vet publicly accessible
        URLs from which to download files for person photos and attachments during a bulk import with the Django Data
        Wizard package.

        :return: List of whitelisted URLs.
        """
        return getattr(settings, 'FDP_DJANGO_DATA_WIZARD_WHITELISTED_URLS', [])

    class Meta:
        abstract = True
