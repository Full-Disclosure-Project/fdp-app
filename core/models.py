from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _
from django.conf import settings
from django.db.models import Q, Prefetch, Exists
from django.db.models.expressions import RawSQL, Subquery, OuterRef
from django.apps import apps
from inheritable.models import Archivable, Descriptable, AbstractForeignKeyValidator, \
    AbstractExactDateBounded, AbstractKnownInfo, AbstractAlias, AbstractAsOfDateBounded, Confidentiable, \
    AbstractFileValidator, AbstractUrlValidator, Linkable, AbstractConfiguration
from supporting.models import State, Trait, PersonRelationshipType, Location, PersonIdentifierType, County, \
    Title, GroupingRelationshipType, PersonGroupingType, IncidentLocationType, EncounterReason, IncidentTag, \
    PersonIncidentTag, LeaveStatus, SituationRole, TraitType
from fdpuser.models import FdpOrganization
from datetime import date


class Person(Confidentiable, Descriptable):
    """ Person such as an plaintiff, victim, officer, etc.

    Attributes:
        :name (str): Full name of person.
        :birth_date_range_start (date): Starting range for birth date.
        :birth_date_range_end (date): Ending range for birth date.
        :is_law_enforcement (bool): True if person is part of law enforcement, false otherwise.
        :traits (m2m): Zero or more traits used to describe the person in the system.
        :fdp_organizations (m2m): FDP organizations, which have exclusive access to person. Leave blank if all
        registered users can access.

    """
    name = models.CharField(
        null=False,
        blank=True,
        help_text=_('Full name of person'),
        max_length=settings.MAX_NAME_LEN,
        verbose_name=_('name')
    )

    birth_date_range_start = models.DateField(
        null=True,
        blank=True,
        help_text=_('If birth date is known, ensure start and end ranges are the same'),
        verbose_name=_('Starting range for birth date')
    )

    birth_date_range_end = models.DateField(
        null=True,
        blank=True,
        help_text=_('If birth date is known, ensure start and end ranges are the same'),
        verbose_name=_('Ending range for birth date')
    )

    is_law_enforcement = models.BooleanField(
        null=False,
        blank=False,
        default=False,
        verbose_name=_('Is law enforcement'),
        help_text=_('Select if person is part of law enforcement'),
    )

    traits = models.ManyToManyField(
        Trait,
        related_name='persons',
        related_query_name='person',
        db_table='{d}person_trait'.format(d=settings.DB_PREFIX),
        blank=True,
        help_text=_('Traits used to describe the person'),
        verbose_name=_('traits')
    )

    fdp_organizations = models.ManyToManyField(
        FdpOrganization,
        related_name='persons',
        related_query_name='person',
        db_table='{d}person_fdp_organization'.format(d=settings.DB_PREFIX),
        blank=True,
        help_text=_('FDP organizations, which have exclusive access to person. Leave blank if all registered users '
                    'can access.'),
        verbose_name=_('organization access')
    )

    #: Fields to display in the model form.
    form_fields = \
        ['name', 'birth_date_range_start', 'birth_date_range_end', 'traits'] + Confidentiable.confidentiable_form_fields

    def __get_birth_date(self):
        """ Retrieve the human-friendly version of the person's birth date.

        :return: Human-friendly version of the person's birth date.
        """
        # both are known
        if self.birth_date_range_start and self.birth_date_range_end:
            if self.birth_date_range_start == self.birth_date_range_end:
                return self.birth_date_range_start
            else:
                return '{b} {s} {n} {e}'.format(
                    b=_('between'),
                    s=self.birth_date_range_start,
                    n=_('and'),
                    e=self.birth_date_range_end
                )
        # only start date is known
        elif self.birth_date_range_start and not self.birth_date_range_end:
            return '{a} {s}'.format(a=_('after'), s=self.birth_date_range_start)
        # only end date is known
        elif self.birth_date_range_end and not self.birth_date_range_start:
            return '{b} {e}'.format(b=_('before'), e=self.birth_date_range_end)
        # nothing is known
        else:
            return None

    @property
    def birth_date(self):
        """ Human-friendly version of the person's birth date.

        :return: Human-friendly version of the person's birth date.
        """
        return self.__get_birth_date()

    @staticmethod
    def __calculate_age(birth_date):
        """ Calculate the age of a person given a particular known birth date.

        :param birth_date: Known birth date.
        :return: Age of person.
        """
        birth_year = getattr(birth_date, 'year', None)
        birth_month = getattr(birth_date, 'month', None)
        birth_day = getattr(birth_date, 'day', None)
        if not (birth_year and birth_month and birth_day):
            return 0
        d = date.today()
        return d.year - birth_year - ((d.month, d.day) < (birth_month, birth_day))

    def __get_age(self):
        """ Retrieve the human-friendly version of the person's age.

        :return: Human-friendly version of the person's age.
        """
        # both birth date ranges are known
        if self.birth_date_range_start and self.birth_date_range_end:
            if self.birth_date_range_start == self.birth_date_range_end:
                return self.__calculate_age(birth_date=self.birth_date_range_start)
            else:
                return '{b} {e} {n} {s}'.format(
                    b=_('between'),
                    e=self.__calculate_age(birth_date=self.birth_date_range_end),
                    n=_('and'),
                    s=self.__calculate_age(birth_date=self.birth_date_range_start)
                )
        # only start date is known
        elif self.birth_date_range_start and not self.birth_date_range_end:
            return '{s} {o}'.format(
                s=self.__calculate_age(birth_date=self.birth_date_range_start),
                o=_('or younger')
            )
        # only end date is known
        elif self.birth_date_range_end and not self.birth_date_range_start:
            return '{e} {o}'.format(
                e=self.__calculate_age(birth_date=self.birth_date_range_end),
                o=_('or older')
            )
        # nothing is known
        else:
            return ''

    @property
    def age(self):
        """ Human-friendly version of the person's age.

        :return: Human-friendly version of the person's age.
        """
        return self.__get_age()

    def clean(self):
        """ Ensure that superfluous whitespace in names is removed.

        :return: Nothing.
        """
        super(Person, self).clean()
        if self.name:
            self.name = ' '.join(self.name.split())

    def __str__(self):
        """Defines string representation for a person.

        :return: String representation of a person.
        """
        return self.name

    @staticmethod
    def __get_attachment_prefetch(user, prefix):
        """ Retrieves a Prefetch object for Attachment model.

        :param prefix: Prefix for related name through which to retrieve attachments.
        :param user: User requesting Prefetch object.
        :return: Prefetch object for Attachment model.
        """
        m = apps.get_model('sourcing', 'Attachment')
        return m.get_prefetch(user=user, prefix=prefix, to_attr='officer_attachments')

    @staticmethod
    def __get_content_identifier_prefetch(user, prefix):
        """ Retrieves a Prefetch object for ContentIdentifier model.

        :param user: User requesting Prefetch object.
        :param prefix: Prefix for related name through which to retrieve  content identifiers.
        :return: Prefetch object for ContentIdentifier model.
        """
        m = apps.get_model('sourcing', 'ContentIdentifier')
        return m.get_prefetch(user=user, prefix=prefix, to_attr='officer_content_identifiers')

    @staticmethod
    def __get_content_case_prefetch(prefix):
        """ Retrieves a Prefetch object for ContentCase model.

        :param prefix: Prefix for related name through which to retrieve content cases.
        :return: Prefetch object for ContentCase model.
        """
        m = apps.get_model('sourcing', 'ContentCase')
        return m.get_prefetch(prefix=prefix, to_attr='officer_content_case')

    @classmethod
    def __get_content_person_prefetch(cls, user, prefix, person_filter_dict, content_filter_dict):
        """ Retrieves a Prefetch object for ContentPerson model.

        :param user: User requesting Prefetch object.
        :param prefix: Prefix for related name through which to retrieve content persons.
        :param person_filter_dict: Dictionary that can be expanded into keyword arguments for optional filtering of
        persons.
        :param content_filter_dict: Dictionary that can be expanded into keyword arguments for optional filtering of
        contents.
        :return: Prefetch object for ContentPerson model.
        """
        m = apps.get_model('sourcing', 'ContentPerson')
        queryset = m.get_filtered_queryset(
            user=user,
            person_filter_dict=person_filter_dict,
            content_filter_dict=content_filter_dict
        )
        p = prefix if prefix else ''
        return Prefetch(
            '{p}content_persons'.format(p=p),
            queryset=queryset.prefetch_related(
                cls.__get_content_person_allegation_prefetch(prefix=None),
                cls.__get_content_person_penalty_prefetch(prefix=None)
            ),
            to_attr='officer_content_persons'
        )

    @classmethod
    def __get_content_person_allegation_prefetch(cls, prefix):
        """ Retrieves a Prefetch object for ContentPersonAllegation model.

        :param prefix: Prefix for related name through which to retrieve content person allegations.
        :return: Prefetch object for ContentPersonAllegation model
        """
        m = apps.get_model('sourcing', 'ContentPersonAllegation')
        p = prefix if prefix else ''
        return Prefetch(
            '{p}content_person_allegations'.format(p=p),
            queryset=m.active_objects.select_related(*m.get_select_related()).filter(
                Q(**m.get_active_filter(prefix='allegation')) & Q(
                    Q(allegation_outcome__isnull=True)
                    |
                    Q(**m.get_active_filter(prefix='allegation_outcome'))
                )
            ),
            to_attr='officer_allegations'
        )

    @classmethod
    def __get_content_person_penalty_prefetch(cls, prefix):
        """ Retrieves a Prefetch object for ContentPersonPenalty model.

        :param prefix: Prefix for related name through which to retrieve content person penalties.
        :return: Prefetch object for ContentPersonPenalty model
        """
        m = apps.get_model('sourcing', 'ContentPersonPenalty')
        p = prefix if prefix else ''
        return Prefetch(
            '{p}content_person_penalties'.format(p=p), queryset=m.active_objects.all(), to_attr='officer_penalties'
        )

    @classmethod
    def __get_content_query(cls, user, filter_by_dict, filter_by_exists, person_filter_dict):
        """ Retrieves a content queryset that is optionally filtered.

        :param user: User retrieving the queryset.
        :param filter_by_dict: Dictionary defining the filtering for the query set.
        :param filter_by_exists: Instance of django.db.models.Exists(...) defining the filtering for the query set.
        :param person_filter_dict: Dictionary defining the keyword argument filtering for the person queryset in the
        prefetched ContentPerson queryset.
        :return: Content queryset.
        """
        m = apps.get_model('sourcing', 'Content')
        qs = m.active_objects.all() if not filter_by_dict else m.active_objects.filter(**filter_by_dict)
        # filter queryset by an instance of Django's Exists() class
        if filter_by_exists is not None:
            qs = qs.filter(filter_by_exists)
        qs = qs.filter_for_confidential_by_user(user=user)
        return qs.filter(
            Q(Q(type__isnull=True) | Q(**m.get_active_filter(prefix='type')))
        ).select_related('type').prefetch_related(
            cls.__get_attachment_prefetch(user=user, prefix=None),
            cls.__get_content_identifier_prefetch(user=user, prefix=None),
            cls.__get_content_case_prefetch(prefix=None),
            # include in this are the allegation and penalty prefetch objects
            cls.__get_content_person_prefetch(
                user=user,
                prefix=None,
                person_filter_dict=person_filter_dict,
                content_filter_dict=None
            )
        )

    @classmethod
    def get_incident_query(cls, user):
        """ Retrieves an incident queryset that is filtered for confidentiality.

        :param user: User retrieving the queryset.
        :return: Incident queryset.
        """
        return Incident.active_objects.all().filter_for_confidential_by_user(user=user).filter(
            Q(
                Q(
                    Q(**Location.get_active_filter(prefix='location'))
                    |
                    Q(location__isnull=True)
                )
                &
                Q(
                    Q(**IncidentLocationType.get_active_filter(prefix='location_type'))
                    |
                    Q(location_type__isnull=True)
                )
                &
                Q(
                    Q(**EncounterReason.get_active_filter(prefix='encounter_reason'))
                    |
                    Q(encounter_reason__isnull=True)
                )
            )
        ).select_related('location', 'location_type', 'encounter_reason')

    @classmethod
    def get_person_incident_query(cls, user, filter_dict, person_pk, person_filter_by_dict):
        """ Retrieves a person incident queryset that is optionally filtered.

        :param user: User retrieving the queryset.
        :param filter_dict: Dictionary defining the filtering for the queryset.
        :param person_pk: Primary key by which to filter the person sub-query. May be None if not limited to one person.
        :param person_filter_by_dict: Dictionary defining the filtering for the person sub-query.
        :return: Person incident queryset.
        """
        qs = PersonIncident.active_objects.all().select_related('person', 'incident', 'situation_role').filter(
            Q(
                Q(situation_role__isnull=True) | Q(**SituationRole.get_active_filter(prefix='situation_role'))
            )
            &
            Q(incident__in=cls.get_incident_query(user=user))
            &
            Q(person__in=cls.__get_person_subquery(user=user, pk=person_pk, filter_by_dict=person_filter_by_dict))
        )
        # additional filtering for person incident queryset
        if filter_dict:
            qs = qs.filter(**filter_dict)
        return qs

    @classmethod
    def __get_person_relationship_query(cls, user, for_object_person):
        """ Retrieves a person relationship queryset.

        :param user: User requesting queryset.
        :param for_object_person: True if queryset is intended for an object person in the relationship, false if
        queryset is intended for a subject person in the relationship.
        :return:
        """
        other_person = 'subject_person' if for_object_person else 'object_person'
        filter_dict = {
            '{other_person}__in'.format(other_person=other_person): cls.__get_person_subquery(
                user=user,
                pk=None,
                filter_by_dict={'{other_person}_relationship__isnull'.format(other_person=other_person): False}
            )
        }
        return PersonRelationship.active_objects.select_related(other_person, 'type').filter(
            **filter_dict, **PersonRelationshipType.get_active_filter(prefix='type')
        )

    @staticmethod
    def __get_person_subquery(user, pk, filter_by_dict):
        """ Retrieves a Subquery object for Person model.

        :param user: User requesting Subquery object.
        :param pk: Primary key of person to exclude from subquery.
        :param filter_by_dict: Dictionary defining the filtering for the subquery.
        :return: Subquery object for Person model.
        """
        qs = Person.active_objects.all() if not filter_by_dict else Person.active_objects.filter(**filter_by_dict)
        qs = qs.filter_for_confidential_by_user(user=user)
        if pk:
            qs = qs.exclude(pk=pk)
        return Subquery(qs.values('pk'))

    @classmethod
    def __get_content_person_query(cls, user, filter_dict):
        """ Retrieves a content person queryset that is optionally filtered.

        :param user: User retrieving the queryset.
        :param filter_dict: Dictionary defining the filtering for the queryset.
        :return: Content person queryset.
        """
        m = apps.get_model('sourcing', 'ContentPerson')
        queryset = m.get_filtered_queryset(user=user, person_filter_dict=None, content_filter_dict=None)
        # additional filtering for case content person queryset
        if filter_dict:
            queryset = queryset.filter(**filter_dict)
        return queryset

    @classmethod
    def get_officer_profile_queryset(cls, pk, user):
        """ Filters the queryset for a particular user (depending on whether the user is an administrator, etc.)

        :return: Filtered queryset from which officer will be retrieved.
        """
        # ensure that only officers are retrieved
        qs = cls.active_objects.filter(is_law_enforcement=True)
        # ensure that user has privileges for officer
        qs = qs.filter_for_confidential_by_user(user=user)
        # include the related data
        qs = qs.prefetch_related(
            Prefetch('person_photos', queryset=PersonPhoto.active_objects.all(), to_attr='officer_photos'),
            Prefetch('person_aliases', queryset=PersonAlias.active_objects.all(), to_attr='officer_aliases'),
            Prefetch('person_social_media_profiles', queryset=PersonSocialMediaProfile.active_objects.all(),
                     to_attr='officer_social_media_profiles'),
            Prefetch(
                'person_identifiers',
                queryset=PersonIdentifier.active_objects.filter(
                    **PersonIdentifier.get_active_filter(prefix='person_identifier_type')
                ).select_related('person_identifier_type').order_by(
                    RawSQL(
                        PersonIdentifier.order_by_sql_year.format(t=PersonIdentifier.get_db_table(), o=''),
                        params=[]
                    ).desc(),
                    RawSQL(
                        PersonIdentifier.order_by_sql_month.format(t=PersonIdentifier.get_db_table(), o=''),
                        params=[]
                    ).desc(),
                    RawSQL(
                        PersonIdentifier.order_by_sql_day.format(t=PersonIdentifier.get_db_table(), o=''),
                        params=[]
                    ).desc()
                ),
                to_attr='officer_identifiers'
            ),
            Prefetch(
                'person_groupings',
                # don't need to filter persons, since filtered above
                queryset=PersonGrouping.active_objects.filter(
                    Q(**Grouping.get_active_filter(prefix='grouping'))
                    &
                    Q(Q(type__isnull=True) | Q(**PersonGroupingType.get_active_filter(prefix='type'))),
                ).select_related(*PersonGrouping.get_select_related()).prefetch_related('grouping__counties').order_by(
                    RawSQL(
                        PersonGrouping.order_by_sql_year.format(t=PersonGrouping.get_db_table(), o=''),
                        params=[]
                    ).desc(),
                    RawSQL(
                        PersonGrouping.order_by_sql_month.format(t=PersonGrouping.get_db_table(), o=''),
                        params=[]
                    ).desc(),
                    RawSQL(
                        PersonGrouping.order_by_sql_day.format(t=PersonGrouping.get_db_table(), o=''),
                        params=[]
                    ).desc()
                ),
                to_attr='officer_commands'
            ),
            Prefetch(
                'traits',
                queryset=Trait.active_objects.filter(
                    Q(type__isnull=True) | Q(**TraitType.get_active_filter(prefix='type'))
                ).select_related('type'),
                to_attr='officer_traits'
            ),
            Prefetch(
                'person_titles',
                queryset=PersonTitle.active_objects.filter(
                    **Title.get_active_filter(prefix='title')
                ).select_related('title').order_by(
                    RawSQL(
                        PersonTitle.order_by_sql_year.format(t=PersonTitle.get_db_table(), o=''),
                        params=[]
                    ).desc(),
                    RawSQL(
                        PersonTitle.order_by_sql_month.format(t=PersonTitle.get_db_table(), o=''),
                        params=[]
                    ).desc(),
                    RawSQL(
                        PersonTitle.order_by_sql_day.format(t=PersonTitle.get_db_table(), o=''),
                        params=[]
                    ).desc()
                ),
                to_attr='officer_titles'
            ),
            Prefetch(
                'person_incidents',
                queryset=(cls.get_person_incident_query(
                    user=user, filter_dict=None, person_pk=None, person_filter_by_dict=None
                )).prefetch_related(
                    Prefetch(
                        'incident__tags',
                        queryset=IncidentTag.active_objects.all(),
                        to_attr='officer_incident_tags'
                    ),
                    Prefetch(
                        'tags',
                        queryset=PersonIncidentTag.active_objects.all(),
                        to_attr='officer_person_incident_tags'
                    ),
                    Prefetch(
                        'incident__person_incidents',
                        queryset=cls.get_person_incident_query(
                            user=user,
                            filter_dict=None,
                            person_pk=pk,
                            person_filter_by_dict={'pk': OuterRef('person_id'), 'is_law_enforcement': True}
                        ),
                        to_attr='officer_other_persons'
                    ),
                    Prefetch(
                        'incident__contents',
                        queryset=cls.__get_content_query(
                            user=user,
                            filter_by_dict={},
                            filter_by_exists=None,
                            person_filter_dict={'pk': pk}
                        ),
                        to_attr='officer_incident_contents'
                    ),
                    Prefetch(
                        'incident__contents',
                        queryset=cls.__get_content_query(
                            user=user,
                            filter_by_dict={},
                            filter_by_exists=Exists(
                                # don't need to filter for confidentiality, since both content and person is filtered
                                # in the outer queries
                                (apps.get_model('sourcing', 'ContentPerson')).objects.filter(
                                    person_id=pk,
                                    content_id=OuterRef('pk')
                                )
                            ),
                            person_filter_dict={'pk': pk}
                        ),
                        to_attr='officer_snapshot_contents'
                    )
                ),
                to_attr='officer_misconducts'
            ),
            Prefetch(
                'person_payments',
                queryset=PersonPayment.active_objects.filter(
                    Q(Q(county__isnull=True) | Q(**County.get_active_filter(prefix='county')))
                    &
                    Q(Q(leave_status__isnull=True) | Q(**LeaveStatus.get_active_filter(prefix='leave_status')))
                ).select_related('county', 'leave_status').order_by(
                    RawSQL(
                        PersonPayment.order_by_sql_year.format(t=PersonPayment.get_db_table(), o=''),
                        params=[]
                    ).desc(),
                    RawSQL(
                        PersonPayment.order_by_sql_month.format(t=PersonPayment.get_db_table(), o=''),
                        params=[]
                    ).desc(),
                    RawSQL(
                        PersonPayment.order_by_sql_day.format(t=PersonPayment.get_db_table(), o=''),
                        params=[]
                    ).desc()
                ),
                to_attr='officer_payments'
            ),
            Prefetch(
                'content_persons',
                queryset=cls.__get_content_person_query(
                    user=user,
                    filter_dict={
                        'content__in': Subquery(
                            cls.__get_content_query(
                                user=user,
                                filter_by_dict={'pk': OuterRef('content_id')},
                                filter_by_exists=None,
                                person_filter_dict=None
                            ).exclude(incidents__person_incident__person_id=pk).values('pk')
                        )
                    }
                ).prefetch_related(
                    cls.__get_attachment_prefetch(user=user, prefix='content__'),
                    cls.__get_content_identifier_prefetch(user=user, prefix='content__'),
                    cls.__get_content_case_prefetch(prefix='content__'),
                    cls.__get_content_person_allegation_prefetch(prefix=None),
                    cls.__get_content_person_penalty_prefetch(prefix=None),
                    Prefetch(
                        'content__content_persons',
                        queryset=cls.__get_content_person_query(
                            user=user,
                            filter_dict={
                                'person__in': cls.__get_person_subquery(
                                    user=user, pk=pk, filter_by_dict={
                                        'content_person__isnull': False,
                                        'is_law_enforcement': True
                                    }
                                )
                            }
                        ),
                        to_attr='officer_other_persons'
                    ),
                ).distinct(),
                to_attr='officer_contents'
            ),
            Prefetch(
                'subject_person_relationships',
                queryset=cls.__get_person_relationship_query(user=user, for_object_person=False),
                to_attr='officer_subject_person_relationships'
            ),
            Prefetch(
                'object_person_relationships',
                queryset=cls.__get_person_relationship_query(user=user, for_object_person=True),
                to_attr='officer_object_person_relationships'
            )
        )
        return qs

    @classmethod
    def get_officer_attachments(cls, pk, user):
        """ Retrieve a list of all attachments for an officer.

        :param pk: Primary key used to identify the officer.
        :param user: User requesting attachments for the officer.
        :return: List of attachments.
        """
        files_to_zip = []
        qs = cls.get_officer_profile_queryset(pk=pk, user=user)
        officer = qs.get(pk=pk)
        # Attachments within the Misconduct section
        for misconduct in officer.officer_misconducts:
            for content in misconduct.incident.officer_incident_contents:
                for attachment in content.officer_attachments:
                    if attachment.file:
                        files_to_zip.append(attachment.file)
        # "Unsummarized" misconduct records
        for content_person in officer.officer_contents:
            for attachment in content_person.content.officer_attachments:
                if attachment.file:
                    files_to_zip.append(attachment.file)
        return files_to_zip

    @classmethod
    def get_title_sql(cls, person_table_alias):
        """ Retrieves title (rank) SQL query that can be used when retrieving persons queryset.

        :param person_table_alias: Alias for person table or query containing primary key for person.
        :return: SQL retrieving latest person title.
        """
        return """
            SELECT ZR."name"
            FROM "{person_title}" AS ZPR
            INNER JOIN "{title}" AS ZR
            ON ZPR."title_id" = ZR."id"
            AND ZR.{active_filter}
            WHERE ZPR."person_id" = {person}."id"
            AND ZPR.{active_filter}
            ORDER BY {order_by}
            LIMIT 1                    
        """.format(
            person_title=PersonTitle.get_db_table(),
            title=Title.get_db_table(),
            person=person_table_alias,
            active_filter=PersonTitle.ACTIVE_FILTER,
            order_by=PersonTitle.order_by_sql.format(t='ZPR', o=PersonTitle.DESCENDING)
        )

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
        return queryset

    class Meta:
        db_table = '{d}person'.format(d=settings.DB_PREFIX)
        verbose_name = _('person')
        verbose_name_plural = _('people')
        ordering = ['name']


class PersonContact(Archivable, Descriptable):
    """ Contact information for a person such as an plaintiff, victim, officer, etc.

    Attributes:
        :phone_number (str): Phone number for person.
        :email (str): Email address for person.
        :address (str): Address, including building number, street name, unit # and PO box if available for person.
        :city (str): City for address of person.
        :state (fk): State for address of person.
        :zip_code (str): ZIP code for address of person.
        :is_current (bool): True if contact information is current for person, false otherwise.
        :person (fk): Person linked to contact information.
    """
    phone_number = models.CharField(
        null=False,
        blank=True,
        help_text=_('Phone number for person'),
        max_length=256,
        verbose_name=_('phone number')
    )

    email = models.EmailField(
        null=False,
        blank=True,
        help_text=_('Email address for'),
        verbose_name=_('email')
    )

    address = models.CharField(
        null=False,
        blank=True,
        default='',
        help_text=_('Building number, street name, unit # and PO box if available'),
        max_length=settings.MAX_NAME_LEN,
        verbose_name=_('address')
    )

    city = models.CharField(
        null=False,
        blank=True,
        default='',
        help_text=_('City for address of person'),
        max_length=settings.MAX_NAME_LEN,
        verbose_name=_('city')
    )

    state = models.ForeignKey(
        State,
        on_delete=models.SET_NULL,
        related_name='person_contacts',
        related_query_name='person_contact',
        blank=True,
        null=True,
        help_text=_('State for address of person'),
        verbose_name=_('state')
    )

    zip_code = models.CharField(
        null=False,
        blank=True,
        default='',
        help_text=_('ZIP code for address of person'),
        max_length=settings.MAX_NAME_LEN,
        verbose_name=_('zip code')
    )

    is_current = models.BooleanField(
        null=False,
        blank=False,
        default=False,
        verbose_name=_('Is current'),
        help_text=_('Select if contact information is currently used by person'),
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name='person_contacts',
        related_query_name='person_contact',
        blank=False,
        null=False,
        help_text=_('Person linked to contact information'),
        verbose_name=_('person')
    )

    #: Fields to display in the model form.
    form_fields = ['phone_number', 'email', 'address', 'city', 'state', 'zip_code', 'is_current', 'person']

    def __str__(self):
        """Defines string representation for a person contact.

        :return: String representation of a person contact.
        """
        return '{x}: {e} {y}: {p} {w}: {a} {f} {z}'.format(
            x=_('Email'),
            y=_('Phone'),
            w=_('Address'),
            f=_('for'),
            e=self.email,
            p=self.phone_number,
            a=self.address,
            z=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='person')
        )

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
        return queryset.filter(
            person__in=Person.filter_for_admin(
                queryset=Person.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            )
        )

    class Meta:
        db_table = '{d}person_contact'.format(d=settings.DB_PREFIX)
        verbose_name = _('person contact')
        ordering = ['person', 'is_current', 'state', 'city', 'address']


class PersonAlias(Archivable, AbstractAlias):
    """ Aliases for a person, e.g. nicknames, common misspellings, etc.

    Attributes:
        :person (fk): Person who is known by this alias.

    """
    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name='person_aliases',
        related_query_name='person_alias',
        blank=False,
        null=False,
        help_text=_('Person who is known by this alias'),
        verbose_name=_('person')
    )

    #: Fields to display in the model form.
    form_fields = ['name', 'person']

    def __str__(self):
        """Defines string representation for a person alias.

        :return: String representation of a person alias.
        """
        return '{a} {f} {p}'.format(
            a=self.name,
            f=_('for'),
            p=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='person')
        )

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
        return queryset.filter(
            person__in=Person.filter_for_admin(
                queryset=Person.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            )
        )

    class Meta:
        db_table = '{d}person_alias'.format(d=settings.DB_PREFIX)
        verbose_name = _('Person alias')
        verbose_name_plural = _('Person aliases')
        unique_together = ('person', 'name')
        ordering = ['person', 'name']


class PersonSocialMediaProfile(Archivable):
    """ Social media related to a person, e.g. links and names used in the social media
    """

    link = models.URLField(
        null=False,
        blank=False,
        default='',
        help_text='URL to social media profile/feed owned by this person',
        max_length=2048,
        verbose_name="social media profile/feed URL"
    )
    link_name = models.CharField(
        null=False,
        blank=False,
        default='',
        help_text='Named used in this social media profile related to this person',
        max_length=300,
        verbose_name='social media profile name/handel'
    )
    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name='person_social_media_profiles',
        related_query_name='person_social_media_profile',
        blank=False,
        null=False,
        help_text='Person who is known to own this social media profile',
        verbose_name='person'
    )

    #: Fields to display in the model form.
    form_fields = ['link_name', 'link', 'person']

    def __str__(self):
        """Defines string representation for a person social media.

        :return: String representation of a social media.
        """
        person_name = AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='person')
        #convert to fstring
        return f"{self.link_name}, {self.link} person fk:{person_name}"

    @classmethod
    def filter_for_admin(cls, queryset, user):
        return queryset

    """ meta class is to add additional settings about the object model
    """
    class Meta:
        db_table = '{d}person_social_media_profile'.format(d=settings.DB_PREFIX)
        verbose_name = 'Person social media profile'
        verbose_name_plural = 'Person social media profiles'
        ordering = ['person', 'link_name', 'link']


class PersonPhoto(Archivable, Descriptable):
    """ Photos for a person.

    Attributes:
        :person (fk): Person represented in photo.
        :photo (file): Photo representing person.

    """
    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name='person_photos',
        related_query_name='person_photo',
        blank=False,
        null=False,
        help_text=_('Person represented in photo'),
        verbose_name=_('person')
    )

    photo = models.FileField(
        upload_to='{b}%Y/%m/%d/%H/%M/%S/'.format(b=AbstractUrlValidator.PERSON_PHOTO_BASE_URL),
        blank=False,
        null=False,
        help_text=_(
            'Photo representing person. Should be less than {s}MB.'.format(
                s=AbstractFileValidator.get_megabytes_from_bytes(
                    num_of_bytes=AbstractConfiguration.max_person_photo_file_bytes()
                )
            )
        ),
        validators=[
            AbstractFileValidator.validate_photo_file_size,
            AbstractFileValidator.validate_photo_file_extension
        ],
        unique=True,
    )

    #: Fields to display in the model form.
    form_fields = ['photo', 'person']

    def __str__(self):
        """Defines string representation for a person photo.

        :return: String representation of a person photo.
        """
        return '{f} {p}'.format(
            f=_('for'),
            p=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='person')
        )

    def clean(self):
        """ Ensure that the photo path contains no directory traversal.

        :return: Nothing
        """
        super(PersonPhoto, self).clean()
        # full path when relative and root paths are joined
        full_path = AbstractFileValidator.join_relative_and_root_paths(
            relative_path=self.photo,
            root_path=settings.MEDIA_ROOT
        )
        # verify that path is a real path (i.e. no directory traversal takes place)
        # will raise exception if path is not a real path
        AbstractFileValidator.check_path_is_expected(
            relative_path=self.photo,
            root_path=settings.MEDIA_ROOT,
            expected_path_prefix=full_path,
            err_msg=_('Person photo path may contain directory traversal'),
            err_cls=ValidationError
        )

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
        return queryset.filter(
            person__in=Person.filter_for_admin(
                queryset=Person.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            )
        )

    class Meta:
        db_table = '{d}person_photo'.format(d=settings.DB_PREFIX)
        verbose_name = _('Person photo')
        ordering = ['person']


class PersonIdentifier(Archivable, AbstractAsOfDateBounded):
    """ Identifier for a person such as a passport number, driver's license number, etc.

    Attributes:
        :identifier (str): Identifier number such as the driver's license number, passport number, or similar.
        :person_identifier_type (fk): Type of documentation containing identifier, such as driver's license, passport,
        or similar.
        :person (fk): Person linked to this identifier.
    """
    identifier = models.CharField(
        null=False,
        blank=False,
        help_text=_('Identifier number, such as the driver\'s license number, passport number, or similar'),
        max_length=settings.MAX_NAME_LEN,
        verbose_name=_('identifier')
    )

    person_identifier_type = models.ForeignKey(
        PersonIdentifierType,
        on_delete=models.CASCADE,
        related_name='person_identifiers',
        related_query_name='person_identifier',
        blank=False,
        null=False,
        help_text=_('Type of documentation containing identifier, such as driver\'s license, passport, or similar'),
        verbose_name=_('type')
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name='person_identifiers',
        related_query_name='person_identifier',
        blank=False,
        null=False,
        help_text=_('Person linked to this identifier'),
        verbose_name=_('person')
    )

    #: Fields to display in the model form.
    form_fields = ['person_identifier_type', 'identifier', 'person']

    def __str__(self):
        """Defines string representation for a person identifier.

        :return: String representation of a person identifier.
        """
        return '{t} #{n} {f} {p}'.format(
            t=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='person_identifier_type'),
            n=self.identifier,
            f=_('for'),
            p=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='person')
        )

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
        return queryset.filter(
            person__in=Person.filter_for_admin(
                queryset=Person.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            )
        )

    class Meta:
        db_table = '{d}person_identifier'.format(d=settings.DB_PREFIX)
        verbose_name = _('Person identifier')
        unique_together = ('person', 'person_identifier_type', 'identifier')
        ordering = ['person', 'person_identifier_type'] + AbstractAsOfDateBounded.order_by_date_fields


class PersonTitle(Archivable, AbstractAsOfDateBounded):
    """ Title for a person such as detective, fdptain, director, etc.

    Attributes:
        :title (fk): Title of person during period.
        :person (fk): Person holding title during period.
    """
    title = models.ForeignKey(
        Title,
        on_delete=models.CASCADE,
        related_name='person_titles',
        related_query_name='person_title',
        blank=False,
        null=False,
        help_text=_('Title of person during period'),
        verbose_name=_('title')
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name='person_titles',
        related_query_name='person_title',
        blank=False,
        null=False,
        help_text=_('Person holding title during period'),
        verbose_name=_('person')
    )

    #: Fields to display in the model form.
    form_fields = ['title', 'person', 'as_of']

    def __str__(self):
        """Defines string representation for a person title.

        :return: String representation of a person title.
        """
        return '{p} {w} {r}'.format(
            p=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='person'),
            w=_('with title'),
            r=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='title')
        )

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
        return queryset.filter(
            person__in=Person.filter_for_admin(
                queryset=Person.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            )
        )

    class Meta:
        db_table = '{d}person_title'.format(d=settings.DB_PREFIX)
        verbose_name = _('Person title')
        unique_together = (
            'person', 'title', 'start_year', 'end_year', 'start_month', 'end_month', 'start_day', 'end_day'
        )
        ordering = ['person'] + AbstractAsOfDateBounded.order_by_date_fields


class PersonRelationship(Archivable, AbstractAsOfDateBounded):
    """ Defines a relationship between two persons in the format: subject verb object.

    For example subject_person=Person #1, type=is brother of, object_person=Person #2.

    Attributes:
        :subject_person (fk): Subject person in the relationship.
        :type (fk): Defines the relationship between the subject and object persons.
        :object_person (fk): Object person in the relationship.

    """
    subject_person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name='subject_person_relationships',
        related_query_name='subject_person_relationship',
        blank=False,
        null=False,
        help_text=_('Subject person in the relationship defined by "subject verb object"'),
        verbose_name=_('subject person')
    )

    type = models.ForeignKey(
        PersonRelationshipType,
        on_delete=models.CASCADE,
        related_name='person_relationships',
        related_query_name='person_relationship',
        blank=False,
        null=False,
        help_text=_('Defines the relationship, i.e. the verb portion of "subject verb object"'),
        verbose_name=_('relationship')
    )

    object_person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name='object_person_relationships',
        related_query_name='object_person_relationship',
        blank=False,
        null=False,
        help_text=_('Object person in the relationship defined by subject verb object'),
        verbose_name=_('object person')
    )

    #: Fields to display in the model form.
    form_fields = ['as_of']

    def __str__(self):
        """Defines string representation for a person relationship.

        :return: String representation of a person relationship.
        """
        return '{s} {v} {o}'.format(
            s=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='subject_person'),
            v=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='type'),
            o=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='object_person')
        )

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
        return queryset.filter(
            subject_person__in=Person.filter_for_admin(
                queryset=Person.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            ),
            object_person__in=Person.filter_for_admin(
                queryset=Person.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            )
        )

    class Meta:
        db_table = '{d}person_relationship'.format(d=settings.DB_PREFIX)
        verbose_name = _('Person relationship')
        unique_together = (
            'subject_person', 'type', 'object_person',
            'start_year', 'end_year', 'start_month', 'end_month', 'start_day', 'end_day'
        )
        ordering = ['subject_person', 'type', 'object_person']


class PersonPayment(Archivable, AbstractAsOfDateBounded):
    """ A payment made to a payment for work over a period of time.

    Attributes:
        :base_salary (decimal): Base salary of person during period.
        :regular_hours (decimal): Hours worked, excluding overtime, by person during period.
        :regular_gross_pay (decimal): Gross pay, excluding overtime, for person during period.
        :overtime_hours (decimal): Overtime hours worked by person during period.
        :overtime_pay (decimal): Overtime pay for person during period.
        :total_other_pay (decimal): Total other pay for person during period.
        :county (fk): County where work was performed.
        :leave_status (fk): Leave status during pay period.
        :person (fk): Person who was paid.
    """
    base_salary = models.DecimalField(
        null=True,
        blank=True,
        max_digits=8,
        decimal_places=2,
        help_text=_('Base salary for person during period'),
        verbose_name=_('base salary')
    )

    regular_hours = models.DecimalField(
        null=True,
        blank=True,
        max_digits=6,
        decimal_places=2,
        help_text=_('Hours worked, excluding overtime, by person during period'),
        verbose_name=_('regular hours')
    )

    regular_gross_pay = models.DecimalField(
        null=True,
        blank=True,
        max_digits=8,
        decimal_places=2,
        help_text=_('Gross pay, excluding overtime, for person during period'),
        verbose_name=_('regular gross pay')
    )

    overtime_hours = models.DecimalField(
        null=True,
        blank=True,
        max_digits=6,
        decimal_places=2,
        help_text=_('Overtime hours worked by person during period'),
        verbose_name=_('overtime hours')
    )

    overtime_pay = models.DecimalField(
        null=True,
        blank=True,
        max_digits=8,
        decimal_places=2,
        help_text=_('Overtime pay for person during period'),
        verbose_name=_('overtime pay')
    )

    total_other_pay = models.DecimalField(
        null=True,
        blank=True,
        max_digits=8,
        decimal_places=2,
        help_text=_('Total other pay for person during period'),
        verbose_name=_('total other pay')
    )

    county = models.ForeignKey(
        County,
        on_delete=models.SET_NULL,
        related_name='person_payments',
        related_query_name='person_payment',
        blank=True,
        null=True,
        help_text=_('County where work was performed'),
        verbose_name=_('county')
    )

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name='person_payments',
        related_query_name='person_payment',
        blank=False,
        null=False,
        help_text=_('Person that was paid'),
        verbose_name=_('person')
    )

    leave_status = models.ForeignKey(
        LeaveStatus,
        on_delete=models.SET_NULL,
        related_name='person_payments',
        related_query_name='person_payment',
        blank=True,
        null=True,
        help_text=_('Leave status during pay period'),
        verbose_name=_('leave status')
    )

    #: Fields to display in the model form.
    form_fields = [
        'as_of', 'leave_status', 'base_salary', 'regular_hours', 'regular_gross_pay', 'overtime_hours', 'overtime_pay',
        'total_other_pay', 'person',
    ]

    def __str__(self):
        """Defines string representation for a person payment.

        :return: String representation of a person payment.
        """
        return '{p} {d} {f} {o}'.format(
            p=_('payment for'),
            d=self.as_of_bounding_dates,
            f=_('for'),
            o=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='person')
        )

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
        return queryset.filter(
            person__in=Person.filter_for_admin(
                queryset=Person.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            )
        )

    class Meta:
        db_table = '{d}person_payment'.format(d=settings.DB_PREFIX)
        verbose_name = _('person payment')
        unique_together = (
            'person', 'start_year', 'end_year', 'start_month', 'end_month', 'start_day', 'end_day'
        )
        ordering = ['person'] + AbstractAsOfDateBounded.order_by_date_fields


class Grouping(Archivable, Descriptable):
    """ Grouping of people such as a command, precinct, human rights organization, police force, etc.

    Attributes:
        :name (str): Name of grouping.
        :phone_number (str): Phone number for grouping.
        :email (str): Email address for grouping.
        :address (str): Full address for grouping.
        :inception_date (date): Date grouping came into existence.
        :cease_date (date): Date grouping ceased to exist.
        :counties (m2m): Counties in which grouping operates.
        :is_inactive (bool): True if link between person and grouping is no longer active.
        :is_law_enforcement (bool): True if grouping is part of law enforcement, false otherwise.
        :belongs_to_grouping (fk): The top-level grouping to which this grouping belongs.
    """
    name = models.CharField(
        null=False,
        blank=True,
        help_text=_('Name of grouping'),
        max_length=settings.MAX_NAME_LEN,
        verbose_name=_('name')
    )

    phone_number = models.CharField(
        null=False,
        blank=True,
        default='',
        help_text=_('Phone number for grouping'),
        max_length=256,
        verbose_name=_('phone number')
    )

    email = models.EmailField(
        null=False,
        blank=True,
        default='',
        help_text=_('Email address for grouping'),
        verbose_name=_('email')
    )

    address = models.CharField(
        null=False,
        blank=True,
        default='',
        help_text=_('Full address for grouping'),
        max_length=settings.MAX_NAME_LEN,
        verbose_name=_('address')
    )

    is_inactive = models.BooleanField(
        null=False,
        blank=False,
        default=False,
        verbose_name=_('Is inactive'),
        help_text=_('Select if the grouping is no longer active')
    )

    is_law_enforcement = models.BooleanField(
        null=False,
        blank=False,
        default=False,
        verbose_name=_('Is law enforcement'),
        help_text=_('Select if grouping is part of law enforcement'),
    )

    inception_date = models.DateField(
        null=True,
        blank=True,
        help_text=_('Date grouping came into existence'),
        verbose_name=_('inception date')
    )

    cease_date = models.DateField(
        null=True,
        blank=True,
        help_text=_('Date grouping ceased to exist'),
        verbose_name=_('cease date')
    )

    counties = models.ManyToManyField(
        County,
        related_name='groupings',
        related_query_name='grouping',
        db_table='{d}grouping_county'.format(d=settings.DB_PREFIX),
        blank=True,
        help_text=_('Counties in which the grouping operates'),
        verbose_name=_('counties')
    )

    belongs_to_grouping = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        related_name='groupings',
        related_query_name='grouping',
        blank=True,
        null=True,
        help_text=_('The top-level grouping to which this grouping belongs. Leave blank and use grouping relationships '
                    'if there are more than one relevant top-level groupings.'),
        verbose_name=_('belongs to')
    )

    #: Fields to display in the model form.
    form_fields = [
        'name', 'phone_number', 'email', 'address', 'is_inactive', 'inception_date', 'cease_date', 'counties',
        'description', 'belongs_to_grouping', 'belongs_to_grouping_name'
    ]

    #: Maximum number of person-groupings that are retrieved in a queryset for the grouping profiles.
    max_person_groupings = 1000

    def __str__(self):
        """Defines string representation for a grouping.

        :return: String representation of a grouping.
        """
        return self.name

    def clean(self):
        """ Ensures that the belonging link does not reference itself.

        :return: Nothing.
        """
        super(Grouping, self).clean()
        # record already exists, i.e. has primary key in database
        pk = getattr(self, 'pk', None)
        if pk:
            # check that "belongs to" does not reference itself
            if pk == getattr(self, 'belongs_to_grouping_id', None):
                raise ValidationError(_('A grouping cannot belong to itself'))

    @staticmethod
    def __get_attachment_prefetch(user, prefix):
        """ Retrieves a Prefetch object for Attachment model.

        :param prefix: Prefix for related name through which to retrieve attachments.
        :param user: User requesting Prefetch object.
        :return: Prefetch object for Attachment model.
        """
        m = apps.get_model('sourcing', 'Attachment')
        return m.get_prefetch(user=user, prefix=prefix, to_attr='command_attachments')

    @staticmethod
    def __get_content_identifier_prefetch(user, prefix):
        """ Retrieves a Prefetch object for ContentIdentifier model.

        :param user: User requesting Prefetch object.
        :param prefix: Prefix for related name through which to retrieve  content identifiers.
        :return: Prefetch object for ContentIdentifier model.
        """
        m = apps.get_model('sourcing', 'ContentIdentifier')
        return m.get_prefetch(user=user, prefix=prefix, to_attr='command_content_identifiers')

    @staticmethod
    def __get_content_case_prefetch(prefix):
        """ Retrieves a Prefetch object for ContentCase model.

        :param prefix: Prefix for related name through which to retrieve content cases.
        :return: Prefetch object for ContentCase model.
        """
        m = apps.get_model('sourcing', 'ContentCase')
        return m.get_prefetch(prefix=prefix, to_attr='command_content_case')

    @classmethod
    def __get_content_query(cls, user, filter_by_dict):
        """ Retrieves a content queryset that is optionally filtered.

        :param user: User retrieving the queryset.
        :param filter_by_dict: Dictionary defining the filtering for the query set.
        :return: Content queryset.
        """
        m = apps.get_model('sourcing', 'Content')
        qs = m.active_objects.all() if not filter_by_dict else m.active_objects.filter(**filter_by_dict)
        qs = qs.filter_for_confidential_by_user(user=user)
        return qs.filter(
            Q(Q(type__isnull=True) | Q(**m.get_active_filter(prefix='type')))
        ).select_related('type').prefetch_related(
            cls.__get_attachment_prefetch(user=user, prefix=None),
            cls.__get_content_identifier_prefetch(user=user, prefix=None),
            cls.__get_content_case_prefetch(prefix=None),
        )

    @classmethod
    def __get_grouping_incident_query(cls, user, filter_dict):
        """ Retrieves a grouping incident queryset that is optionally filtered.

        :param user: User retrieving the queryset.
        :param filter_dict: Dictionary defining the filtering for the queryset.
        :return: Grouping incident queryset.
        """
        qs = GroupingIncident.active_objects.filter(incident__in=Person.get_incident_query(user=user)).select_related(
            'grouping', 'incident'
        )
        # additional filtering for grouping incident queryset
        if filter_dict:
            qs = qs.filter(**filter_dict)
        return qs

    @classmethod
    def __get_person_grouping_query(cls, accessible_officers, is_inactive):
        """ Retrieves a person grouping queryset that is filtered by active/inactive and a list of accessible officers.

        :param accessible_officers: List or queryset of officers that can be accessed by the user.
        :param is_inactive: True if only inactive person-groupings should be retrieved, false if only active
        person-groupings should be retrieved.
        :return: Person grouping queryset.
        """
        return PersonGrouping.active_objects.filter(
            id__in=Subquery(
                PersonGrouping.active_objects.filter(
                    # only active career segments
                    Q(is_inactive=is_inactive)
                    &
                    # only for current grouping
                    Q(grouping_id=OuterRef('grouping_id'))
                    &
                    # only accessible officer
                    Q(person__in=accessible_officers)
                    &
                    # only active or missing categorization
                    Q(Q(type__isnull=True) | Q(**PersonGroupingType.get_active_filter(prefix='type')))
                ).values_list('id', flat=True)[:cls.max_person_groupings]
            )
        ).select_related(*PersonGrouping.get_select_related()).order_by(
            RawSQL(
                PersonGrouping.order_by_sql_year.format(t=PersonGrouping.get_db_table(), o=''),
                params=[]
            ).desc(),
            RawSQL(
                PersonGrouping.order_by_sql_month.format(t=PersonGrouping.get_db_table(), o=''),
                params=[]
            ).desc(),
            RawSQL(
                PersonGrouping.order_by_sql_day.format(t=PersonGrouping.get_db_table(), o=''),
                params=[]
            ).desc()
        )

    @staticmethod
    def __get_grouping_subquery(pk, filter_by_dict):
        """ Retrieves a Subquery object for Grouping model.

        :param pk: Primary key of grouping to exclude from subquery.
        :param filter_by_dict: Dictionary defining the filtering for the subquery.
        :return: Subquery object for Grouping model.
        """
        qs = Grouping.active_objects.all() if not filter_by_dict else Grouping.active_objects.filter(**filter_by_dict)
        if pk:
            qs = qs.exclude(pk=pk)
        return Subquery(qs.values('pk'))

    @classmethod
    def __get_grouping_relationship_query(cls, for_object_grouping):
        """ Retrieves a grouping relationship queryset.

        :param for_object_grouping: True if queryset is intended for an object grouping in the relationship, false if
        queryset is intended for a subject grouping in the relationship.
        :return:
        """
        other_grouping = 'subject_grouping' if for_object_grouping else 'object_grouping'
        filter_dict = {
            '{other_grouping}__in'.format(other_grouping=other_grouping): cls.__get_grouping_subquery(
                pk=None,
                filter_by_dict={'{other_grouping}_relationship__isnull'.format(other_grouping=other_grouping): False}
            )
        }
        return GroupingRelationship.active_objects.select_related(other_grouping, 'type').filter(
            **filter_dict, **GroupingRelationshipType.get_active_filter(prefix='type')
        )

    @classmethod
    def get_command_profile_queryset(cls, user):
        """ Filters the queryset for a particular user (depending on whether the user is an administrator, etc.)

        :return: Filtered queryset from which command will be retrieved.
        """
        # ensure that only commands are retrieved
        qs = cls.active_objects.filter(is_law_enforcement=True)
        # accessible officers for user
        accessible_officers = Person.active_objects.filter(is_law_enforcement=True).filter_for_confidential_by_user(
            user=user
        )
        # include the related data
        qs = qs.prefetch_related(
            Prefetch('counties', queryset=County.active_objects.all(), to_attr='command_counties'),
            Prefetch('grouping_aliases', queryset=GroupingAlias.active_objects.all(), to_attr='command_aliases'),
            Prefetch(
                'person_groupings',
                # don't need to filter groupings, since filtered above
                queryset=cls.__get_person_grouping_query(accessible_officers=accessible_officers, is_inactive=False),
                to_attr='command_active_officers'
            ),
            Prefetch(
                'person_groupings',
                # don't need to filter groupings, since filtered above
                queryset=cls.__get_person_grouping_query(accessible_officers=accessible_officers, is_inactive=True),
                to_attr='command_inactive_officers'
            ),
            Prefetch(
                'grouping_incidents',
                queryset=(cls.__get_grouping_incident_query(user=user, filter_dict=None)).prefetch_related(
                    Prefetch(
                        'incident__tags',
                        queryset=IncidentTag.active_objects.all(),
                        to_attr='command_incident_tags'
                    ),
                    Prefetch(
                        'incident__person_incidents',
                        queryset=Person.get_person_incident_query(
                            user=user,
                            filter_dict=None,
                            person_pk=None,
                            person_filter_by_dict={'is_law_enforcement': True}
                        ),
                        to_attr='command_other_persons'
                    ),
                    Prefetch(
                        'incident__contents',
                        queryset=cls.__get_content_query(user=user, filter_by_dict={}),
                        to_attr='command_contents'
                    )
                ),
                to_attr='command_misconducts'
            ),
            Prefetch(
                'subject_grouping_relationships',
                queryset=cls.__get_grouping_relationship_query(for_object_grouping=False),
                to_attr='command_subject_grouping_relationships'
            ),
            Prefetch(
                'object_grouping_relationships',
                queryset=cls.__get_grouping_relationship_query(for_object_grouping=True),
                to_attr='command_object_grouping_relationships'
            )
        )
        return qs

    @classmethod
    def get_command_attachments(cls, pk, user):
        """ Retrieve a list of all attachments for a command.

        :param pk: Primary key used to identify the command.
        :param user: User requesting attachments for the command.
        :return: List of attachments.
        """
        files_to_zip = []
        qs = cls.get_command_profile_queryset(user=user)
        command = qs.get(pk=pk)
        # Attachments within the Misconduct section
        for misconduct in command.command_misconducts:
            for content in misconduct.incident.command_contents:
                for attachment in content.command_attachments:
                    if attachment.file:
                        files_to_zip.append(attachment.file)
        return files_to_zip

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
        return queryset

    class Meta:
        db_table = '{d}grouping'.format(d=settings.DB_PREFIX)
        verbose_name = _('grouping')
        unique_together = ('name', 'address')
        ordering = ['name']


class GroupingAlias(Archivable, AbstractAlias):
    """ Aliases for a grouping, e.g. nicknames, common misspellings, etc.

    Attributes:
        :grouping (fk): Grouping who is known by this alias.

    """
    grouping = models.ForeignKey(
        Grouping,
        on_delete=models.CASCADE,
        related_name='grouping_aliases',
        related_query_name='grouping_alias',
        blank=False,
        null=False,
        help_text=_('Grouping which is known by this alias'),
        verbose_name=_('grouping')
    )

    #: Fields to display in the model form.
    form_fields = ['name', 'grouping']

    def __str__(self):
        """Defines string representation for a grouping alias.

        :return: String representation of a grouping alias.
        """
        return '{a} {f} {p}'.format(
            a=self.name,
            f=_('for'),
            p=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='grouping')
        )

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
        return queryset

    class Meta:
        db_table = '{d}grouping_alias'.format(d=settings.DB_PREFIX)
        verbose_name = _('Grouping alias')
        verbose_name_plural = _('Grouping aliases')
        unique_together = ('grouping', 'name')
        ordering = ['grouping', 'name']


class GroupingRelationship(Archivable, AbstractAsOfDateBounded):
    """ Defines a relationship between two groupings in the format: subject verb object.

    For example subject_grouping=Command, type=Belongs To, object_grouping=Precinct.

    Attributes:
        :subject_grouping (fk): Subject grouping in the relationship.
        :type (fk): Defines the relationship between the subject and object groupings.
        :object_grouping (fk): Object grouping in the relationship.

    """
    subject_grouping = models.ForeignKey(
        Grouping,
        on_delete=models.CASCADE,
        related_name='subject_grouping_relationships',
        related_query_name='subject_grouping_relationship',
        blank=False,
        null=False,
        help_text=_('Subject grouping in the relationship defined by "subject verb object"'),
        verbose_name=_('subject grouping')
    )

    type = models.ForeignKey(
        GroupingRelationshipType,
        on_delete=models.CASCADE,
        related_name='grouping_relationships',
        related_query_name='grouping_relationship',
        blank=False,
        null=False,
        help_text=_('Defines the relationship, i.e. the verb portion of "subject verb object"'),
        verbose_name=_('relationship')
    )

    object_grouping = models.ForeignKey(
        Grouping,
        on_delete=models.CASCADE,
        related_name='object_grouping_relationships',
        related_query_name='object_grouping_relationship',
        blank=False,
        null=False,
        help_text=_('Object grouping in the relationship defined by subject verb object'),
        verbose_name=_('object grouping')
    )

    #: Fields to display in the model form.
    form_fields = ['as_of']

    def __str__(self):
        """Defines string representation for a grouping relationship.

        :return: String representation of a grouping relationship.
        """
        return '{s} {v} {o}'.format(
            s=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='subject_grouping'),
            v=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='type'),
            o=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='object_grouping')
        )

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
        return queryset

    class Meta:
        db_table = '{d}grouping_relationship'.format(d=settings.DB_PREFIX)
        verbose_name = _('Grouping relationship')
        unique_together = ('subject_grouping', 'object_grouping', 'type')
        ordering = ['subject_grouping', 'type', 'object_grouping']


class PersonGrouping(Archivable, AbstractAsOfDateBounded):
    """ Links between persons and groupings, e.g. describing an attorney's involvement in a law office or an
    officer's involvement in a command or precinct.

    Attributes:
        :person (fk): Person who is linked to the grouping.
        :grouping (fk): Grouping which is linked to the person.
        :type (fk): Category for link between the person and grouping.
        :is_inactive (bool): True if link between person and grouping is no longer active.

    """
    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name='person_groupings',
        related_query_name='person_grouping',
        blank=False,
        null=False,
        help_text=_('Person who is linked to the grouping'),
        verbose_name=_('person')
    )

    grouping = models.ForeignKey(
        Grouping,
        on_delete=models.CASCADE,
        related_name='person_groupings',
        related_query_name='person_grouping',
        blank=False,
        null=False,
        help_text=_('Grouping which is linked to the person'),
        verbose_name=_('grouping')
    )

    type = models.ForeignKey(
        PersonGroupingType,
        on_delete=models.SET_NULL,
        related_name='person_groupings',
        related_query_name='person_grouping',
        blank=True,
        null=True,
        help_text=_('Category for link between the person and grouping'),
        verbose_name=_('type')
    )

    is_inactive = models.BooleanField(
        null=False,
        blank=False,
        default=False,
        verbose_name=_('Is inactive'),
        help_text=_('Select if the link between person and grouping is no longer active')
    )

    #: Fields to display in the model form.
    form_fields = ['is_inactive', 'as_of', 'grouping', 'type', 'person']

    def __str__(self):
        """Defines string representation for a link between a person and a grouping.

        :return: String representation of a link between a person and a grouping.
        """
        return '{i} {a} {n} {b}'.format(
            i=_('link between'),
            a=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='person'),
            n=_('and'),
            b=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='grouping')
        )

    @staticmethod
    def get_select_related():
        """ Retrieves a list of positional arguments that can be passed into Django's select_related(...) function when
        building an person-grouping queryset.

        :return: List of positional arguments.
        """
        return ['person', 'grouping', 'type']

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
        return queryset.filter(
            person__in=Person.filter_for_admin(
                queryset=Person.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            )
        )

    class Meta:
        db_table = '{d}person_grouping'.format(d=settings.DB_PREFIX)
        verbose_name = _('Link between person and grouping')
        verbose_name_plural = _('Links between people and groupings')
        unique_together = (
            'person', 'grouping', 'type', 'start_year', 'end_year', 'start_month', 'end_month', 'start_day', 'end_day'
        )
        ordering = AbstractAsOfDateBounded.order_by_date_fields + ['grouping', 'person']


class Incident(Confidentiable, AbstractExactDateBounded):
    """ Incident such as an assault involving an officer.

    Attributes:
        :location (fk): Location where incident occurred.
        :location_type (fk): Type of location where incident occurred.
        :encounter_reason (fk): Reason for encounter during incident.
        :tags (m2m): Tags describing incident.
        :fdp_organizations (m2m): FDP organizations, which have exclusive access to incident. Leave blank if all
        registered users can access.

    """
    location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        related_name='incidents',
        related_query_name='incident',
        blank=True,
        null=True,
        help_text=_('Location where incident occurred'),
        verbose_name=_('location')
    )

    location_type = models.ForeignKey(
        IncidentLocationType,
        on_delete=models.SET_NULL,
        related_name='incidents',
        related_query_name='incident',
        blank=True,
        null=True,
        help_text=_('Type of location where incident occurred'),
        verbose_name=_('location type')
    )

    encounter_reason = models.ForeignKey(
        EncounterReason,
        on_delete=models.SET_NULL,
        related_name='incidents',
        related_query_name='incident',
        blank=True,
        null=True,
        help_text=_('Reason for encounter during incident'),
        verbose_name=_('encounter reason')
    )

    tags = models.ManyToManyField(
        IncidentTag,
        related_name='incidents',
        related_query_name='incident',
        db_table='{d}incident_incident_tag'.format(d=settings.DB_PREFIX),
        blank=True,
        help_text=_('Tags describing incident'),
        verbose_name=_('tags')
    )

    fdp_organizations = models.ManyToManyField(
        FdpOrganization,
        related_name='incidents',
        related_query_name='incident',
        db_table='{d}incident_fdp_organization'.format(d=settings.DB_PREFIX),
        blank=True,
        help_text=_('FDP organizations, which have exclusive access to incident. Leave blank if all registered users '
                    'can access.'),
        verbose_name=_('organization access')
    )

    #: Fields to display in the model form.
    form_fields = [
                      'location', 'location_type', 'encounter_reason', 'tags', 'description'
                  ] + Confidentiable.confidentiable_form_fields

    def __str__(self):
        """ String representation for an incident.

        :return: String representing incident.
        """
        location = AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='location', unknown='')
        dates = self.exact_bounding_dates
        str_rep = '{d}{p}{s}{t}'.format(
            d='' if not dates else '{d} '.format(d=dates.title()),
            p='' if not location else '{i} {p} '.format(i=_('In'), p=location.title()),
            s='- ' if dates or location else '',
            t='...' if not self.description else self.description
        )
        return str_rep

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
        return queryset

    def clean(self):
        """ Verifies that start date comes before end date.

        :return: Nothing.
        """
        # Check that start date is before end date
        self._check_start_date_before_end_date()

    class Meta:
        db_table = '{d}incident'.format(d=settings.DB_PREFIX)
        verbose_name = _('Incident')
        ordering = AbstractExactDateBounded.order_by_date_fields + ['location']


class PersonIncident(Archivable, Descriptable, Linkable, AbstractKnownInfo):
    """ Links between people and incidents, e.g. describing a victim or officer in an incident.

    Attributes:
        :person (fk): Person who is linked to the incident.
        :incident (fk): Incident which is linked to the person.
        :tags (m2m): Tags to describe the links between people and incidents.
        :situation_role (fk): Categorizes person's involvement in the incident.

    """
    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name='person_incidents',
        related_query_name='person_incident',
        blank=False,
        null=False,
        help_text=_('Person who is linked to the incident'),
        verbose_name=_('person')
    )

    incident = models.ForeignKey(
        Incident,
        on_delete=models.CASCADE,
        related_name='person_incidents',
        related_query_name='person_incident',
        blank=False,
        null=False,
        help_text=_('Incident which is linked to the person'),
        verbose_name=_('incident')
    )

    tags = models.ManyToManyField(
        PersonIncidentTag,
        related_name='person_incidents',
        related_query_name='person_incident',
        db_table='{d}person_incident_person_incident_tag'.format(d=settings.DB_PREFIX),
        blank=True,
        help_text=_('Tags describing link between person and incident'),
        verbose_name=_('tags')
    )

    situation_role = models.ForeignKey(
        SituationRole,
        on_delete=models.SET_NULL,
        related_name='person_incidents',
        related_query_name='person_incident',
        blank=True,
        null=True,
        help_text=_('Categorizes the person\'s involvement in the incident'),
        verbose_name=_('situation role')
    )

    #: Fields to display in the model form.
    form_fields = ['situation_role', 'person', 'person_name', 'incident', 'description', 'is_guess']

    def __str__(self):
        """Defines string representation for a link between a person and an incident.

        :return: String representation of a link between a person and an incident.
        """
        if hasattr(self, 'incident') and self.incident:
            incident = self.incident
            location = AbstractForeignKeyValidator.stringify_foreign_key(
                obj=incident,
                foreign_key='location',
                unknown=''
            )
            dates = getattr(incident, 'exact_bounding_dates')
            incident_str = '{d}{p}'.format(
                d='' if not dates else '{d} '.format(d=dates.title()),
                p='' if not location else '{i} {p} '.format(i=_('In'), p=location.title()),
            )
        else:
            incident_str = ''
        return '{a} {b}'.format(
            a=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='person'), b=incident_str
        )

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
        return queryset.filter(
            person__in=Person.filter_for_admin(
                queryset=Person.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            ),
            incident__in=Incident.filter_for_admin(
                queryset=Incident.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            )
        )

    class Meta:
        db_table = '{d}person_incident'.format(d=settings.DB_PREFIX)
        verbose_name = _('Link between person and incident')
        verbose_name_plural = _('Links between people and incidents')
        unique_together = ('person', 'incident', 'situation_role')
        ordering = ['person', 'incident']


class GroupingIncident(Archivable, Descriptable):
    """ Links between groupings and incidents, e.g. describing a command's involvement in an incident.

    Attributes:
        :grouping (fk): Grouping which is linked to the incident.
        :incident (fk): Incident which is linked to the grouping.

    """
    grouping = models.ForeignKey(
        Grouping,
        on_delete=models.CASCADE,
        related_name='grouping_incidents',
        related_query_name='grouping_incident',
        blank=False,
        null=False,
        help_text=_('Grouping which is linked to the incident'),
        verbose_name=_('grouping')
    )

    incident = models.ForeignKey(
        Incident,
        on_delete=models.CASCADE,
        related_name='grouping_incidents',
        related_query_name='grouping_incident',
        blank=False,
        null=False,
        help_text=_('Incident which is linked to the grouping'),
        verbose_name=_('incident')
    )

    #: Fields to display in the model form.
    form_fields = ['grouping_name', 'grouping', 'incident', 'description']

    def __str__(self):
        """Defines string representation for a link between a grouping and an incident.

        :return: String representation of a link between a grouping and an incident.
        """
        return '{i} {a} {n} {b}'.format(
            i=_('link between'),
            a=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='grouping'),
            n=_('and'),
            b=AbstractForeignKeyValidator.stringify_foreign_key(obj=self, foreign_key='incident')
        )

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
        return queryset.filter(
            incident__in=Incident.filter_for_admin(
                queryset=Incident.active_objects.all().filter_for_confidential_by_user(user=user),
                user=user
            )
        )

    class Meta:
        db_table = '{d}grouping_incident'.format(d=settings.DB_PREFIX)
        verbose_name = _('Link between grouping and incident')
        verbose_name_plural = _('Links between groupings and incidents')
        unique_together = ('grouping', 'incident')
        ordering = ['grouping', 'incident']
