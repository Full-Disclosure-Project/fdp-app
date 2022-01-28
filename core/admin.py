from django.contrib import admin
from inheritable.admin import FdpInheritableAdmin, ArchivableAdmin, ConfidentiableAdmin
from .models import Person, PersonContact, PersonAlias, PersonPhoto, PersonIdentifier, PersonTitle, \
    PersonRelationship, PersonPayment, Grouping, GroupingAlias, GroupingRelationship, \
    PersonGrouping, Incident, PersonIncident, GroupingIncident, PersonSocialMediaProfile


@admin.register(Person)
class PersonAdmin(FdpInheritableAdmin, ConfidentiableAdmin):
    """ Admin interface for persons.
    """
    _list_display = [
                        'name', 'birth_date_range_start', 'birth_date_range_end', 'is_law_enforcement'
                    ] + ConfidentiableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = ['traits', 'is_law_enforcement'] + ConfidentiableAdmin.list_filter
    search_fields = ['name']
    ordering = ['name']


@admin.register(PersonContact)
class PersonContactAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for contact information for persons.
    """
    _list_display = ['is_current', 'person', 'phone_number', 'email', 'address'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = ['is_current', 'state'] + ArchivableAdmin.list_filter
    search_fields = ['person__name', 'phone_number', 'email', 'address', 'city', 'zip_code']
    ordering = ['person__name', 'is_current', 'address']


@admin.register(PersonAlias)
class PersonAliasAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for person aliases.

    """
    _list_display = ['person', 'name'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = [] + ArchivableAdmin.list_filter
    search_fields = ['name', 'person__name']
    ordering = ['person__name', 'name']


@admin.register(PersonSocialMediaProfile)
class PersonSocialMediaProfileAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for person's social media.
    """
    _list_display = ['person', 'link_name', 'link']+ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    autocomplete_fields = ["person"]
    search_fields = ['link_name']


@admin.register(PersonPhoto)
class PersonPhotoAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for person photos.

    """
    _list_display = ['person'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = [] + ArchivableAdmin.list_filter
    search_fields = ['person__name']
    ordering = ['person__name']


@admin.register(PersonIdentifier)
class PersonIdentifierAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for person identifiers.

    """
    _list_display = ['person', 'person_identifier_type', 'identifier'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = ['person_identifier_type'] + ArchivableAdmin.list_filter
    search_fields = ['identifier', 'person__name']
    ordering = ['person__name', 'person_identifier_type__name']


@admin.register(PersonTitle)
class PersonTitleAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for person titles.

    """
    _list_display = ['person', 'title', 'as_of_bounding_dates'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = ['title'] + PersonTitle.list_filter_fields + ArchivableAdmin.list_filter
    search_fields = ['person__name']
    ordering = ['person__name'] + PersonTitle.order_by_date_fields


@admin.register(PersonRelationship)
class PersonRelationshipAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for relationships between people.

    """
    _list_display = ['as_of_bounding_dates', 'subject_person', 'type', 'object_person'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = ['type'] + PersonRelationship.list_filter_fields + ArchivableAdmin.list_filter
    search_fields = ['subject_person__name', 'object_person__name']
    ordering = PersonRelationship.order_by_date_fields + ['subject_person__name', 'type__name', 'object_person__name']


@admin.register(PersonPayment)
class PersonPaymentAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for person payments.

    """
    _list_display = ['person', 'as_of_bounding_dates', 'county'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = PersonPayment.list_filter_fields + ['county'] + ArchivableAdmin.list_filter
    search_fields = ['person__name']
    ordering = ['person__name'] + PersonPayment.order_by_date_fields


@admin.register(Grouping)
class GroupingAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for groupings of people.

    """
    _list_display = ['name', 'is_law_enforcement', 'is_inactive', 'belongs_to_grouping'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = ['counties', 'is_law_enforcement', 'is_inactive', 'belongs_to_grouping'] + ArchivableAdmin.list_filter
    search_fields = ['name', 'phone_number', 'email', 'address']
    ordering = ['name']


@admin.register(GroupingAlias)
class GroupingAliasAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for grouping aliases.

    """
    _list_display = ['grouping', 'name'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = [] + ArchivableAdmin.list_filter
    search_fields = ['name', 'grouping__name']
    ordering = ['grouping__name', 'name']


@admin.register(GroupingRelationship)
class GroupingRelationshipAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for grouping relationships.

    """
    _list_display = [
                       'as_of_bounding_dates', 'subject_grouping', 'type', 'object_grouping'
                   ] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = GroupingRelationship.list_filter_fields + ['type'] + ArchivableAdmin.list_filter
    search_fields = ['subject_grouping__name', 'object_grouping__name']
    ordering = GroupingRelationship.order_by_date_fields + [
        'subject_grouping__name', 'type__name', 'object_grouping__name'
    ]


@admin.register(PersonGrouping)
class PersonGroupingAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for links between persons and groupings.

    """
    _list_display = ['person', 'as_of_bounding_dates', 'grouping', 'type', 'is_inactive'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = PersonGrouping.list_filter_fields + ['type', 'is_inactive'] + ArchivableAdmin.list_filter
    search_fields = ['person__name', 'grouping__name']
    ordering = ['person__name'] + PersonGrouping.order_by_date_fields + ['grouping__name']


@admin.register(Incident)
class IncidentAdmin(FdpInheritableAdmin, ConfidentiableAdmin):
    """ Admin interface for incidents.

    """
    _list_display = ['exact_bounding_dates', 'location', 'truncated_description'] + ConfidentiableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = Incident.list_filter_fields + [
        'encounter_reason', 'location_type', 'tags'
    ] + ConfidentiableAdmin.list_filter
    search_fields = ['description']
    ordering = Incident.order_by_date_fields + []


@admin.register(PersonIncident)
class PersonIncidentAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for links between persons and incidents.

    """
    _list_display = ['person', 'situation_role', 'incident'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = ['situation_role', 'tags', 'is_guess'] + ArchivableAdmin.list_filter
    search_fields = ['person__name', 'incident__description']
    ordering = [
        'person__name', 'situation_role__name', 'incident__start_year', 'incident__start_month', 'incident__start_day',
        'incident__end_year', 'incident__end_month', 'incident__end_day'
    ]


@admin.register(GroupingIncident)
class GroupingIncidentAdmin(FdpInheritableAdmin, ArchivableAdmin):
    """ Admin interface for links between groupings and incidents.

    """
    _list_display = ['grouping', 'incident'] + ArchivableAdmin.list_display
    list_display = _list_display
    list_display_links = _list_display
    list_filter = [] + ArchivableAdmin.list_filter
    search_fields = ['grouping__name', 'incident__description']
    ordering = [
        'grouping__name', 'incident__start_year', 'incident__start_month', 'incident__start_day',
        'incident__end_year', 'incident__end_month', 'incident__end_day'
    ]
