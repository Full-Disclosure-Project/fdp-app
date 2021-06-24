from django.forms import HiddenInput
from django import forms
from django.core.validators import ValidationError
from django.conf import settings
from django.utils.translation import gettext as _
from inheritable.models import AbstractDateValidator
from inheritable.forms import AbstractWizardModelForm, DateWithComponentsField, DateWithCalendarInput, \
    RelationshipField, AbstractWizardInlineFormSet, AbstractWizardModelFormSet, DateWithCalendarAndSplitInput, \
    DateWithCalendarAndCombineInput, PopupForm, AsyncSearchCharField
from sourcing.models import ContentIdentifier, ContentCase, Content, ContentPerson, Attachment, \
    ContentPersonAllegation, ContentPersonPenalty
from core.models import Grouping, GroupingAlias, GroupingRelationship, Person, PersonAlias, PersonIdentifier, \
    PersonGrouping, PersonTitle, PersonRelationship, PersonContact, PersonPayment, Incident, PersonIncident, \
    GroupingIncident, PersonPhoto
from supporting.models import County, GroupingRelationshipType, PersonRelationshipType, Location


class DynamicCountyField(forms.ChoiceField):
    """ Dynamically populated county field, that only contains options when the user focuses on it.

    Overrides the validation, to ensure that selected options are considered OK, even though the possible choices list
    remain empty.

    """
    def validate(self, value):
        """ Ensure that selected option is an active county. All possible choices will not be available to this field.

        :param value: Value selected by user.
        :return: Nothing.
        """
        if value:
            if not County.active_objects.filter(pk=value).exists():
                raise ValidationError(
                    _('The selected county is no longer an option. Please select a different county.')
                )


class WizardSearchForm(forms.Form):
    """ Synchronous form to search for content, incidents, persons or groupings to edit through a data management
    wizard.

    Fields:
        search (str): Free-text search criteria.
        type (str): Hidden value defining context for search form, e.g. for content, incidents, persons or groupings.

    """
    #: Types of data management wizard forms.
    content_type = 'content'
    incident_type = 'incident'
    person_type = 'person'
    grouping_type = 'grouping'
    #: Minimum length for types of data management wizard forms.
    min_type_length = 6
    #: Maximum length for types of data management wizard forms.
    max_type_length = 8

    search = forms.CharField(
        label=_('Search'),
        max_length=settings.MAX_NAME_LEN,
        help_text=_('Search')
    )

    type = forms.CharField(
        min_length=min_type_length,
        max_length=max_type_length,
        widget=forms.HiddenInput()
    )


class GroupingAliasModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of grouping alias model.

    Fields:

    """
    #: Fields to show in the form
    fields_to_show = ['name']

    #: Prefix to use for form
    prefix = 'aliases'

    #: Extra parameter when creating a grouping alias formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a grouping alias formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a grouping alias formset
    formset_can_order = False

    class Meta:
        model = GroupingAlias
        fields = GroupingAlias.form_fields
        fields_order = GroupingAlias.form_fields


#: Starting and ending fields are added to grouping relationships
grouping_relationship_form_fields = GroupingRelationship.form_fields.copy()
grouping_relationship_form_fields.insert(0, 'grouping_relationship')
grouping_relationship_form_fields.append('grouping_relationship_started')
grouping_relationship_form_fields.append('grouping_relationship_ended')


def deferred_get_grouping_relationship_types():
    """ Retrieves the grouping relationship types when called.

    Used in GroupingRelationshipModelForm so that queryset is only accessed  in the context of the view, rather than in
    the context of the module loading.

    Resolves following issue encountered during initial Django database migration for all FDP apps:

        django.db.utils.ProgrammingError: relation "fdp_grouping_relationship_type" does not exist

    :return: List of tuples representing active grouping relationship types.
    """
    return [(str(r.pk), r.__str__()) for r in GroupingRelationshipType.active_objects.all()]


class GroupingRelationshipModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of grouping relationship models.

    Fields:
        :grouping_relationship_started (date): Date that grouping relationship started, potentially with unknown date
        components.
        :grouping_relationship_ended (date): Date that grouping relationship ended, potentially with unknown date
        components.
        :grouping_relationship (list): List of values representing the relationship.
        :primary_key (int): Id used to update record.
    """
    grouping_relationship_started = DateWithComponentsField(
        required=True,
        label=_('Start date'),
        fields=()  # ignored
    )

    grouping_relationship_ended = DateWithComponentsField(
        required=True,
        label=_('End date'),
        fields=()  # ignored
    )

    grouping_relationship = RelationshipField(
        # Note that required=True will be overwritten in __init__(...), the field label will be styled as if required,
        # and custom validation on the individual field components will be used.
        required=True,
        label=_('Relationship'),
        queryset=deferred_get_grouping_relationship_types,
        fields=()  # ignored
    )

    primary_key = forms.IntegerField(
        required=False,
        label=_('Primary key'),
        widget=HiddenInput(),
        help_text=_('Id used to update record')
    )

    #: Fields to show in the form
    fields_to_show = [
                         'grouping_relationship_started', 'grouping_relationship_ended', 'grouping_relationship'
                     ] + GroupingRelationship.form_fields

    #: Key in cleaned data dictionary indicating the grouping for whom the relationship form is saved.
    for_grouping_key = '_for_grouping'

    #: Prefix to use for form
    prefix = 'relationships'

    #: Extra parameter when creating a grouping relationship formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a grouping relationship formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a grouping relationship formset
    formset_can_order = False

    def __init__(self, for_grouping=None, has_primary_key=None, *args, **kwargs):
        """ If we're editing an instance of a grouping relationship, then set the start and end date and relationship
        initial values.

        :param for_grouping: Grouping for whom relationship will be defined in this grouping relationship model form.
        :param has_primary_key: Primary key used to identify relationship that is being updated. Will be None for new
        relationships.
        :param args:
        :param kwargs:
        """
        super(GroupingRelationshipModelForm, self).__init__(*args, **kwargs)
        # dates for relationship
        self.set_initial_composite_dates(
            start_field_name='grouping_relationship_started',
            end_field_name='grouping_relationship_ended'
        )
        # tuple representing relationship
        self.set_initial_relationship(
            field_name='grouping_relationship',
            relationship_type=self.init_grouping_relationship,
            for_obj_id=None if not for_grouping else for_grouping.pk
        )
        # primary key for existing grouping relationship corresponding to form, if such exists in the database
        if has_primary_key:
            self.fields['primary_key'].initial = has_primary_key

    def save(self, commit=True):
        """ Ensure that individual date components are set for starting and ending dates, and individual relationship
        components are set.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # update starting and ending date components
        self.instance = self.set_date_components(
            model_instance=self.instance,
            start_field_val=self.cleaned_data['grouping_relationship_started'],
            end_field_val=self.cleaned_data['grouping_relationship_ended']
        )
        self.set_relationship_components(
            model_instance=self.instance,
            field_val=self.cleaned_data['grouping_relationship'],
            subject_field_name='subject_grouping_id',
            object_field_name='object_grouping_id',
            type_field_name='type_id',
            for_id=self.cleaned_data[self.for_grouping_key]
        )
        return super(GroupingRelationshipModelForm, self).save(commit=commit)

    class Meta:
        model = GroupingRelationship
        fields = grouping_relationship_form_fields.copy()
        fields_order = grouping_relationship_form_fields.copy()


class GroupingModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of grouping model.

    Fields:
        :belongs_to_grouping_name (str): Name of the top-level grouping to which this grouping belongs.
    """
    belongs_to_grouping_name = AsyncSearchCharField(
        required=False,
        label=_('Belongs to'),
    )

    #: Fields to show in the form
    fields_to_show = Grouping.form_fields

    def __init__(self, *args, **kwargs):
        """ Ensure counties selection can be wrapped in client-side wrapper for multiple selections.

        :param args:
        :param kwargs:
        """
        super(GroupingModelForm, self).__init__(*args, **kwargs)
        self.prep_multiple_select(field_name='counties')
        self.fields['belongs_to_grouping_name'].widget.attrs.update({'class': 'groupingname'})
        # instance of model exists
        if hasattr(self, 'instance') and self.instance:
            instance = self.instance
            if hasattr(instance, 'belongs_to_grouping') and instance.belongs_to_grouping:
                self.fields['belongs_to_grouping_name'].initial = instance.belongs_to_grouping.__str__()

    def save(self, commit=True):
        """ Ensure that full_clean is called for the model instance.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # saved instance
        saved_instance = super(GroupingModelForm, self).save(commit=commit)
        # clean again
        saved_instance.full_clean()
        return saved_instance

    class Meta:
        model = Grouping
        fields = Grouping.form_fields
        fields_order = Grouping.form_fields
        widgets = {
            'inception_date': DateWithCalendarInput(),
            'cease_date': DateWithCalendarInput(),
            'belongs_to_grouping': HiddenInput(attrs={'class': 'grouping'})
        }


#: Form set connecting the grouping alias to grouping
GroupingAliasModelFormSet = forms.inlineformset_factory(
    Grouping,
    GroupingAlias,
    form=GroupingAliasModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=GroupingAliasModelForm.formset_extra,
    can_delete=GroupingAliasModelForm.formset_can_delete,
    can_order=GroupingAliasModelForm.formset_can_order,
)


#: Form set connecting the grouping relationship to grouping
GroupingRelationshipModelFormSet = forms.modelformset_factory(
    GroupingRelationship,
    GroupingRelationshipModelForm,
    formset=AbstractWizardModelFormSet,
    extra=GroupingRelationshipModelForm.formset_extra,
    can_delete=GroupingRelationshipModelForm.formset_can_delete,
    can_order=GroupingRelationshipModelForm.formset_can_order
)


#: Starting, ending and as of date fields are added to person identifiers
person_identifier_form_fields = PersonIdentifier.form_fields.copy()
person_identifier_form_fields.append('as_of')
person_identifier_form_fields.append('identifier_started')
person_identifier_form_fields.append('identifier_ended')


class PersonIdentifierModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of person identifier model.

    Fields:
        :identifier_started (date): Date that person identifier started, potentially with unknown date components.
        :identifier_ended (date): Date that person identifier ended, potentially with unknown date components.
    """
    identifier_started = DateWithComponentsField(
        required=True,
        label=_('Start date'),
        fields=()  # ignored
    )

    identifier_ended = DateWithComponentsField(
        required=True,
        label=_('End date'),
        fields=()  # ignored
    )

    #: Fields to show in the form
    fields_to_show = person_identifier_form_fields.copy()

    #: Prefix to use for form
    prefix = 'identifiers'

    #: Extra parameter when creating a person identifier formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a person identifier formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a person identifier formset
    formset_can_order = False

    def __init__(self, *args, **kwargs):
        """ Add class to identifier type SELECT elements, so that they can be made filterable on the client-side.

        Add class to identifier INPUT elements, so that it can be easily identified on the client-side.

        :param args:
        :param kwargs:
        """
        super(PersonIdentifierModelForm, self).__init__(*args, **kwargs)
        # CSS class names for fields in interface
        type_field = 'person_identifier_type'
        self.fields[type_field].widget.attrs.update({'class': 'personidentifiertype'})
        self.fields['identifier'].widget.attrs.update({'class': 'identifierinput'})
        # composite date fields
        self.set_initial_composite_dates(start_field_name='identifier_started', end_field_name='identifier_ended')

    def save(self, commit=True):
        """ Ensure that individual date components are set for starting and ending dates.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # update starting and ending date components
        self.instance = self.set_date_components(
            model_instance=self.instance,
            start_field_val=self.cleaned_data['identifier_started'],
            end_field_val=self.cleaned_data['identifier_ended']
        )
        return super(PersonIdentifierModelForm, self).save(commit=commit)

    class Meta:
        model = PersonIdentifier
        fields = person_identifier_form_fields.copy()
        fields_order = person_identifier_form_fields.copy()


#: Starting and ending date fields are added to person groupings
person_grouping_form_fields = PersonGrouping.form_fields.copy()
person_grouping_form_fields.insert(2, 'person_grouping_started')
person_grouping_form_fields.insert(3, 'person_grouping_ended')


class PersonGroupingModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of person grouping model.

    Fields:
        :person_grouping_started (date): Date that person grouping started, potentially with unknown date components.
        :person_grouping_ended (date): Date that person grouping ended, potentially with unknown date components.
        :grouping_name (str): Name of the grouping to which the person is linked. Used for autocomplete search.
    """
    person_grouping_started = DateWithComponentsField(
        required=True,
        label=_('Start date'),
        fields=()  # ignored
    )

    person_grouping_ended = DateWithComponentsField(
        required=True,
        label=_('End date'),
        fields=()  # ignored
    )

    grouping_name = AsyncSearchCharField(
        required=True,
        label=_('Grouping'),
    )

    #: Fields to show in the form
    fields_to_show = ['grouping_name'] + person_grouping_form_fields.copy()

    #: Prefix to use for form
    prefix = 'persongroupings'

    #: Extra parameter when creating a person grouping formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a person grouping formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a person grouping formset
    formset_can_order = False

    def __init__(self, *args, **kwargs):
        """ If we're editing an instance of a person grouping, then set the start and end initial values.

        Add class to person-grouping type SELECT elements, so that they can be made filterable on the client-side.

        :param args:
        :param kwargs:
        """
        super(PersonGroupingModelForm, self).__init__(*args, **kwargs)
        # CSS class names for fields in interface
        self.fields['type'].widget.attrs.update({'class': 'persongroupingtype'})
        self.fields['grouping_name'].widget.attrs.update({'class': 'groupingname'})
        # composite date fields
        self.set_initial_composite_dates(
            start_field_name='person_grouping_started',
            end_field_name='person_grouping_ended'
        )
        # instance of model exists
        if hasattr(self, 'instance') and self.instance:
            instance = self.instance
            if hasattr(instance, 'grouping') and instance.grouping:
                self.fields['grouping_name'].initial = instance.grouping.__str__()

    def save(self, commit=True):
        """ Ensure that individual date components are set for starting and ending dates.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # update starting and ending date components
        self.instance = self.set_date_components(
            model_instance=self.instance,
            start_field_val=self.cleaned_data['person_grouping_started'],
            end_field_val=self.cleaned_data['person_grouping_ended']
        )
        return super(PersonGroupingModelForm, self).save(commit=commit)

    class Meta:
        model = PersonGrouping
        fields = person_grouping_form_fields.copy()
        fields_order = person_grouping_form_fields.copy()
        widgets = {'grouping': HiddenInput(attrs={'class': 'grouping'})}


#: Starting and ending date fields are added to person titles
person_title_form_fields = PersonTitle.form_fields.copy()
person_title_form_fields.append('person_title_started')
person_title_form_fields.append('person_title_ended')


class PersonTitleModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of person title model.

    Fields:
        :person_title_started (date): Date that person title started, potentially with unknown date components.
        :person_title_ended (date): Date that person title ended, potentially with unknown date components.
    """
    person_title_started = DateWithComponentsField(
        required=True,
        label=_('Start date'),
        fields=()  # ignored
    )

    person_title_ended = DateWithComponentsField(
        required=True,
        label=_('End date'),
        fields=()  # ignored
    )

    #: Fields to show in the form
    fields_to_show = person_title_form_fields.copy()

    #: Prefix to use for form
    prefix = 'titles'

    #: Extra parameter when creating a person title formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a person title formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a person title formset
    formset_can_order = False

    def __init__(self, *args, **kwargs):
        """ If we're editing an instance of a person title, then set the start and end initial values.

        Add class to title type SELECT elements, so that they can be made filterable on the client-side.

        :param args:
        :param kwargs:
        """
        super(PersonTitleModelForm, self).__init__(*args, **kwargs)
        # CSS class names for fields in interface
        self.fields['title'].widget.attrs.update({'class': 'title'})
        # composite date fields
        self.set_initial_composite_dates(
            start_field_name='person_title_started',
            end_field_name='person_title_ended'
        )

    def save(self, commit=True):
        """ Ensure that individual date components are set for starting and ending dates.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # update starting and ending date components
        self.instance = self.set_date_components(
            model_instance=self.instance,
            start_field_val=self.cleaned_data['person_title_started'],
            end_field_val=self.cleaned_data['person_title_ended']
        )
        return super(PersonTitleModelForm, self).save(commit=commit)

    class Meta:
        model = PersonTitle
        fields = person_title_form_fields.copy()
        fields_order = person_title_form_fields.copy()


#: Starting and ending date, and counties fields are added to person payments
person_payment_form_fields = PersonPayment.form_fields.copy()
person_payment_form_fields.insert(1, 'person_payment_started')
person_payment_form_fields.insert(2, 'person_payment_ended')
person_payment_form_fields.insert(3, 'dynamic_county')


class PersonPaymentModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of person payment model.

    Fields:
        :person_payment_started (date): Date that person payment started, potentially with unknown date components.
        :person_payment_ended (date): Date that person payment ended, potentially with unknown date components.
        :dynamic_county (list): List of counties in which person payment record occurs.
    """
    person_payment_started = DateWithComponentsField(
        required=False,
        label=_('Start date'),
        fields=()  # ignored
    )

    person_payment_ended = DateWithComponentsField(
        required=False,
        label=_('End date'),
        fields=()  # ignored
    )

    dynamic_county = DynamicCountyField(
        required=False,
        label=_('County'),
        choices=[]
    )

    #: Fields to show in the form
    fields_to_show = person_payment_form_fields.copy()

    #: Prefix to use for form
    prefix = 'payments'

    #: Extra parameter when creating a person payment formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a person payment formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a person payment formset
    formset_can_order = False

    def __init__(self, *args, **kwargs):
        """ If we're editing an instance of a person payment, then set the start and end initial values.

        Add class to payment type SELECT elements, so that they can be made filterable on the client-side.

        :param args:
        :param kwargs:
        """
        super(PersonPaymentModelForm, self).__init__(*args, **kwargs)
        f = 'dynamic_county'
        # form is built on POST data, but not saved (e.g. validation fails)
        unparsed_dynamic_county = self.data.get('{prefix}-{f}'.format(prefix=self.prefix, f=f))
        parsed_dynamic_county = int(unparsed_dynamic_county[0]) if unparsed_dynamic_county else None
        # composite date fields
        self.set_initial_composite_dates(
            start_field_name='person_payment_started',
            end_field_name='person_payment_ended'
        )
        # instance of model exists
        if hasattr(self, 'instance') and self.instance:
            instance = self.instance
            if instance.county_id:
                self.fields[f].initial = instance.county_id
                self.fields[f].choices = [(instance.county_id, instance.county)]
            elif parsed_dynamic_county:
                self.fields[f].initial = parsed_dynamic_county
                self.fields[f].choices = [(parsed_dynamic_county, _('Selected'))]
        self.fields[f].widget.attrs.update({'class': 'dynamiccounty'})

    def save(self, commit=True):
        """ Ensure that individual date components are set for starting and ending dates.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # update starting and ending date components
        self.instance = self.set_date_components(
            model_instance=self.instance,
            start_field_val=self.cleaned_data['person_payment_started'],
            end_field_val=self.cleaned_data['person_payment_ended']
        )
        # Updating counties
        self.instance.county_id = self.cleaned_data['dynamic_county']
        return super(PersonPaymentModelForm, self).save(commit=commit)

    class Meta:
        model = PersonPayment
        fields = person_payment_form_fields.copy()
        fields_order = person_payment_form_fields.copy()


class PersonAliasModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of person alias model.

    Fields:

    """
    #: Fields to show in the form
    fields_to_show = PersonAlias.form_fields

    #: Prefix to use for form
    prefix = 'aliases'

    #: Extra parameter when creating a person alias formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a person alias formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a person alias formset
    formset_can_order = False

    class Meta:
        model = PersonAlias
        fields = PersonAlias.form_fields
        fields_order = PersonAlias.form_fields


#: Starting and ending date, and composite relationship fields are added to person relationships
person_relationship_form_fields = PersonRelationship.form_fields.copy()
person_relationship_form_fields.insert(0, 'person_relationship')
person_relationship_form_fields.append('person_relationship_started')
person_relationship_form_fields.append('person_relationship_ended')


def deferred_get_person_relationship_types():
    """ Retrieves the person relationship types when called.

    Used in PersonRelationshipModelForm so that queryset is only accessed  in the context of the view, rather than in
    the context of the module loading.

    Resolves following issue encountered during initial Django database migration for all FDP apps:

        django.db.utils.ProgrammingError: relation "fdp_person_relationship_type" does not exist

    :return: List of tuples representing active person relationship types.
    """
    return [(str(r.pk), r.__str__()) for r in PersonRelationshipType.active_objects.all()]


class PersonRelationshipModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of person relationship models.

    Fields:
        :person_relationship_started (date): Date that person relationship started, potentially with unknown date
        components.
        :person_relationship_ended (date): Date that person relationship ended, potentially with unknown date
        components.
        :person_relationship (list): List of values representing the relationship.
        :primary_key (int): Id used to update record.
    """
    person_relationship_started = DateWithComponentsField(
        required=True,
        label=_('Start date'),
        fields=()  # ignored
    )

    person_relationship_ended = DateWithComponentsField(
        required=True,
        label=_('End date'),
        fields=()  # ignored
    )

    person_relationship = RelationshipField(
        # Note that required=True will be overwritten in __init__(...), the field label will be styled as if required,
        # and custom validation on the individual field components will be used.
        required=True,
        label=_('Relationship'),
        queryset=deferred_get_person_relationship_types,
        fields=()  # ignored
    )

    primary_key = forms.IntegerField(
        required=False,
        label=_('Primary key'),
        widget=HiddenInput(),
        help_text=_('Id used to update record')
    )

    #: Fields to show in the form
    fields_to_show = person_relationship_form_fields.copy()

    #: Key in cleaned data dictionary indicating the person for whom the relationship form is saved.
    for_person_key = '_for_person'

    #: Extra parameter when creating a person relationship formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a person relationship formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a person relationship formset
    formset_can_order = False

    def __init__(self, for_person=None, has_primary_key=None, *args, **kwargs):
        """ If we're editing an instance of a person relationship, then set the start and end date and relationship
        initial values.

        :param for_person: Person for whom relationship will be defined in this person relationship model form.
        :param has_primary_key: Primary key used to identify relationship that is being updated. Will be None for new
        relationships.
        :param args:
        :param kwargs:
        """
        super(PersonRelationshipModelForm, self).__init__(*args, **kwargs)
        # dates for relationship
        self.set_initial_composite_dates(
            start_field_name='person_relationship_started',
            end_field_name='person_relationship_ended'
        )
        # tuple representing relationship
        self.set_initial_relationship(
            field_name='person_relationship',
            relationship_type=self.init_person_relationship,
            for_obj_id=None if not for_person else for_person.pk
        )
        # primary key for existing person relationship corresponding to form, if such exists in the database
        if has_primary_key:
            self.fields['primary_key'].initial = has_primary_key

    def save(self, commit=True):
        """ Ensure that individual date components are set for starting and ending dates, and individual relationship
        components are set.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # update starting and ending date components
        self.instance = self.set_date_components(
            model_instance=self.instance,
            start_field_val=self.cleaned_data['person_relationship_started'],
            end_field_val=self.cleaned_data['person_relationship_ended']
        )
        self.set_relationship_components(
            model_instance=self.instance,
            field_val=self.cleaned_data['person_relationship'],
            subject_field_name='subject_person_id',
            object_field_name='object_person_id',
            type_field_name='type_id',
            for_id=self.cleaned_data[self.for_person_key]
        )
        return super(PersonRelationshipModelForm, self).save(commit=commit)

    class Meta:
        model = PersonRelationship
        fields = person_relationship_form_fields.copy()
        fields_order = person_relationship_form_fields.copy()


class PersonContactModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of person contact model.

    Fields:

    """
    #: Fields to show in the form
    fields_to_show = PersonContact.form_fields

    #: Prefix to use for form
    prefix = 'contacts'

    #: Extra parameter when creating a person contact formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a person contact formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a person contact formset
    formset_can_order = False

    class Meta:
        model = PersonContact
        fields = PersonContact.form_fields
        fields_order = PersonContact.form_fields


class PersonPhotoModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of person photo model.

    Fields:

    """
    #: Fields to show in the form
    fields_to_show = PersonPhoto.form_fields

    #: Prefix to use for form`
    prefix = 'photos'

    #: Extra parameter when creating a person photo formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a person photo formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a person photo formset
    formset_can_order = False

    class Meta:
        model = PersonPhoto
        fields = PersonPhoto.form_fields
        fields_order = PersonPhoto.form_fields


#: Known birth date are added to person
person_form_fields = Person.form_fields.copy()
person_form_fields.insert(4, 'known_birth_date')


class PersonModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of person model.

    Fields:
        :known_birth_date (date): Exact birth date of person, if known.

    """
    known_birth_date = forms.DateField(
        required=False,
        label=_('Birth date'),
        widget=DateWithCalendarAndSplitInput(),
    )

    #: Fields to show in the form
    fields_to_show = person_form_fields.copy()

    def __init__(self, *args, **kwargs):
        """ Set the single known birth date, if one exists.

        Prepare multiple SELECT elements.

        :param args:
        :param kwargs:
        """
        super(PersonModelForm, self).__init__(*args, **kwargs)
        self.prep_multiple_select(field_name='fdp_organizations')
        self.prep_multiple_select(field_name='traits')
        # instance of model exists
        if hasattr(self, 'instance') and self.instance:
            instance = self.instance
            # check if birth date range is actually a single date
            single_date = AbstractDateValidator.combine_date_range_into_single_date(
                start_date=instance.birth_date_range_start,
                end_date=instance.birth_date_range_end
            )
            if single_date:
                self.fields['known_birth_date'].initial = single_date

    def save(self, commit=True):
        """ Ensure that full_clean is called for the model instance.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # split single birth date into birth date range
        date_range = AbstractDateValidator.split_single_date_into_date_range(
            date_val=self.cleaned_data['known_birth_date']
        )
        # the single date could be split into a date range
        if date_range:
            self.instance.birth_date_range_start = date_range[0]
            self.instance.birth_date_range_end = date_range[1]
        # only clean if saving to the database and no errors have been encountered
        if commit and not self.errors:
            self.instance.full_clean()
        # saved instance
        saved_instance = super(PersonModelForm, self).save(commit=commit)
        # clean again
        saved_instance.full_clean()
        return saved_instance

    class Meta:
        model = Person
        fields = person_form_fields.copy()
        fields_order = person_form_fields.copy()
        widgets = {
            'birth_date_range_start': DateWithCalendarAndCombineInput(),
            'birth_date_range_end': DateWithCalendarInput()
        }


#: Form connecting the person identifier to person
PersonIdentifierModelFormSet = forms.inlineformset_factory(
    Person,
    PersonIdentifier,
    form=PersonIdentifierModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=PersonIdentifierModelForm.formset_extra,
    can_delete=PersonIdentifierModelForm.formset_can_delete,
    can_order=PersonIdentifierModelForm.formset_can_order,
)


#: Form connecting the person grouping to person
PersonGroupingModelFormSet = forms.inlineformset_factory(
    Person,
    PersonGrouping,
    form=PersonGroupingModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=PersonGroupingModelForm.formset_extra,
    can_delete=PersonGroupingModelForm.formset_can_delete,
    can_order=PersonGroupingModelForm.formset_can_order,
)


#: Form connecting the person title to person
PersonTitleModelFormSet = forms.inlineformset_factory(
    Person,
    PersonTitle,
    form=PersonTitleModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=PersonTitleModelForm.formset_extra,
    can_delete=PersonTitleModelForm.formset_can_delete,
    can_order=PersonTitleModelForm.formset_can_order,
)


#: Form connecting the person payment to person
PersonPaymentModelFormSet = forms.inlineformset_factory(
    Person,
    PersonPayment,
    form=PersonPaymentModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=PersonPaymentModelForm.formset_extra,
    can_delete=PersonPaymentModelForm.formset_can_delete,
    can_order=PersonPaymentModelForm.formset_can_order,
)


#: Form connecting the person alias to person
PersonAliasModelFormSet = forms.inlineformset_factory(
    Person,
    PersonAlias,
    form=PersonAliasModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=PersonAliasModelForm.formset_extra,
    can_delete=PersonAliasModelForm.formset_can_delete,
    can_order=PersonAliasModelForm.formset_can_order,
)


#: Form connecting the person relationship to person
PersonRelationshipModelFormSet = forms.modelformset_factory(
    PersonRelationship,
    PersonRelationshipModelForm,
    formset=AbstractWizardModelFormSet,
    extra=PersonRelationshipModelForm.formset_extra,
    can_delete=PersonRelationshipModelForm.formset_can_delete,
    can_order=PersonRelationshipModelForm.formset_can_order,
)


#: Form connecting the person contact to person
PersonContactModelFormSet = forms.inlineformset_factory(
    Person,
    PersonContact,
    form=PersonContactModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=PersonContactModelForm.formset_extra,
    can_delete=PersonContactModelForm.formset_can_delete,
    can_order=PersonContactModelForm.formset_can_order,
)


#: Form connecting the person photo to person
PersonPhotoModelFormSet = forms.inlineformset_factory(
    Person,
    PersonPhoto,
    form=PersonPhotoModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=PersonPhotoModelForm.formset_extra,
    can_delete=PersonPhotoModelForm.formset_can_delete,
    can_order=PersonPhotoModelForm.formset_can_order,
)


#: Incident started and incident ended fields are added to incident
incident_form_fields = Incident.form_fields.copy()
incident_form_fields.insert(2, 'incident_started')
incident_form_fields.insert(3, 'incident_ended')


class IncidentModelForm(AbstractWizardModelForm, PopupForm):
    """ Form used to create new and edit existing instances of incident model.

    Fields:
        :incident_started (date): Date that incident was started, potentially with unknown date components.
        :incident_ended (date): Date that incident was ended, potentially with unknown date components.

    """
    incident_started = DateWithComponentsField(
        required=True,
        label=_('Incident started'),
        fields=()  # ignored
    )

    incident_ended = DateWithComponentsField(
        required=True,
        label=_('Incident ended'),
        fields=()  # ignored
    )

    #: Fields to show in the form
    fields_to_show = incident_form_fields.copy()

    def __init__(self, *args, **kwargs):
        """ If we're editing an instance of a case content, then set the incident started and incident ended initial
        values.

        Add CSS class name to multiple select elements.

        :param args:
        :param kwargs:
        """
        super(IncidentModelForm, self).__init__(*args, **kwargs)
        # composite date fields
        self.set_initial_composite_dates(start_field_name='incident_started', end_field_name='incident_ended')
        # confidentiality organizations
        self.prep_multiple_select(field_name='fdp_organizations')
        # incident tags
        self.prep_multiple_select(field_name='tags')
        # CSS class name for location
        self.fields['location'].widget.attrs.update({'class': 'location'})

    def clean(self):
        """ Ensure that incident start occurs before incident end.

        :return: Dictionary of representing cleaned data.
        """
        cleaned_data = super(IncidentModelForm, self).clean()
        if not cleaned_data:
            cleaned_data = self.cleaned_data
        self._clean_start_and_end_date_components(
            cleaned_data=cleaned_data,
            compound_start_date_field='incident_started',
            compound_end_date_field='incident_ended'
        )
        # return the cleaned data dictionary
        return cleaned_data

    def save(self, commit=True):
        """ Ensure that individual date components are set for starting and ending dates.

        Also, ensure that full_clean is called for the model instance.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # update starting and ending date components
        self.instance = self.set_date_components(
            model_instance=self.instance,
            start_field_val=self.cleaned_data['incident_started'],
            end_field_val=self.cleaned_data['incident_ended']
        )
        # only clean if saving to the database and no errors have been encountered
        if commit and not self.errors:
            self.instance.full_clean()
        return super(IncidentModelForm, self).save(commit=commit)

    class Meta:
        model = Incident
        fields = incident_form_fields.copy()
        fields_order = incident_form_fields.copy()


class PersonIncidentModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of person incident model.

    Fields:
        :person_name (str): Name of the person to which the incident is linked. Used for autocomplete search.
    """
    person_name = AsyncSearchCharField(
        required=True,
        label=_('Person'),
    )

    #: Fields to show in the form
    fields_to_show = ['person_name', 'situation_role', 'description', 'is_guess']

    #: Prefix to use for form
    prefix = 'personincidents'

    #: Extra parameter when creating a person incident formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a person incident formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a person incident formset
    formset_can_order = False

    def __init__(self, *args, **kwargs):
        """ If we're editing an instance of a person incident, then set the person name.

        :param args:
        :param kwargs:
        """
        super(PersonIncidentModelForm, self).__init__(*args, **kwargs)
        # CSS class names for fields in interface
        self.fields['person_name'].widget.attrs.update({'class': 'personname'})
        # instance of model exists
        if hasattr(self, 'instance') and self.instance:
            instance = self.instance
            if hasattr(instance, 'person') and instance.person:
                self.fields['person_name'].initial = instance.person.__str__()

    class Meta:
        model = PersonIncident
        fields = PersonIncident.form_fields
        fields_order = PersonIncident.form_fields
        widgets = {'person': HiddenInput(attrs={'class': 'person'})}


class GroupingIncidentModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of grouping incident model.

    Fields:
        :grouping_name (str): Name of the grouping to which the incident is linked. Used for autocomplete search.
    """
    grouping_name = AsyncSearchCharField(
        required=True,
        label=_('Grouping'),
    )

    #: Fields to show in the form
    fields_to_show = ['grouping_name', 'description']

    #: Prefix to use for form
    prefix = 'groupingincidents'

    #: Extra parameter when creating a grouping incident formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a grouping incident formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a grouping incident formset
    formset_can_order = False

    def __init__(self, *args, **kwargs):
        """ If we're editing an instance of a grouping incident, then set the grouping name values.

        :param args:
        :param kwargs:
        """
        super(GroupingIncidentModelForm, self).__init__(*args, **kwargs)
        # CSS class names for fields in interface
        self.fields['grouping_name'].widget.attrs.update({'class': 'groupingname'})
        # instance of model exists
        if hasattr(self, 'instance') and self.instance:
            instance = self.instance
            if hasattr(instance, 'grouping') and instance.grouping:
                self.fields['grouping_name'].initial = instance.grouping.__str__()

    class Meta:
        model = GroupingIncident
        fields = GroupingIncident.form_fields.copy()
        fields_order = GroupingIncident.form_fields.copy()
        widgets = {'grouping': HiddenInput(attrs={'class': 'grouping'})}


#: Form connecting the person incident to incident
PersonIncidentModelFormSet = forms.inlineformset_factory(
    Incident,
    PersonIncident,
    form=PersonIncidentModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=PersonIncidentModelForm.formset_extra,
    can_delete=PersonIncidentModelForm.formset_can_delete,
    can_order=PersonIncidentModelForm.formset_can_order,
)


#: Form connecting the grouping incident to incident
GroupingIncidentModelFormSet = forms.inlineformset_factory(
    Incident,
    GroupingIncident,
    form=GroupingIncidentModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=GroupingIncidentModelForm.formset_extra,
    can_delete=GroupingIncidentModelForm.formset_can_delete,
    can_order=GroupingIncidentModelForm.formset_can_order,
)


class LocationModelForm(AbstractWizardModelForm, PopupForm):
    """ Form used to create new and edit existing instances of location model.

    Fields:

    """
    #: Fields to show in the form
    fields_to_show = Location.form_fields

    #: Prefix to use for form`
    prefix = 'locations'

    def save(self, commit=True):
        """ Ensure that full_clean is called for the model instance.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # only clean if saving to the database and no errors have been encountered
        if commit and not self.errors:
            self.instance.full_clean()
        return super(LocationModelForm, self).save(commit=commit)

    class Meta:
        model = Location
        fields = Location.form_fields
        fields_order = Location.form_fields


class ContentIdentifierModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of content identifier model.

    Fields:

    """
    #: Fields to show in the form
    fields_to_show = ContentIdentifier.form_fields

    #: Prefix to use for form`
    prefix = 'identifiers'

    #: Extra parameter when creating a content identifier formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a content identifier formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a content identifier formset
    formset_can_order = False

    def __init__(self, *args, **kwargs):
        """ Add class to identifier SELECT elements, so that they can be made filterable on the client-side.

        :param args:
        :param kwargs:
        """
        super(ContentIdentifierModelForm, self).__init__(*args, **kwargs)
        # CSS class names for fields in interface
        self.fields['content_identifier_type'].widget.attrs.update({'class': 'contentidentifiertype'})
        self.prep_multiple_select(field_name='fdp_organizations')

    class Meta:
        model = ContentIdentifier
        fields = ContentIdentifier.form_fields
        fields_order = ContentIdentifier.form_fields


class ContentModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of content model.

    Fields:

    """
    #: Fields to show in the form
    fields_to_show = Content.form_fields

    def __init__(self, *args, **kwargs):
        """ Add class to content SELECT element, so that they can be made filterable on the client-side.

        Prepares multiple SELECT elements for the interface.

        :param args:
        :param kwargs:
        """
        super(ContentModelForm, self).__init__(*args, **kwargs)
        self.prep_multiple_select(field_name='fdp_organizations')
        # CSS class names for fields in interface
        self.fields['type'].widget.attrs.update({'class': 'type'})

    def save(self, commit=True):
        """ Ensure that full_clean is called for the model instance.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # only clean if saving to the database and no errors have been encountered
        if commit and not self.errors:
            self.instance.full_clean()
        # saved instance
        saved_instance = super(ContentModelForm, self).save(commit=commit)
        return saved_instance

    class Meta:
        model = Content
        fields = Content.form_fields
        fields_order = Content.form_fields
        widgets = {'publication_date': DateWithCalendarInput()}


#: Starting and ending date fields are added to content case
content_case_form_fields = ContentCase.form_fields.copy()
content_case_form_fields.insert(2, 'case_opened')
content_case_form_fields.insert(3, 'case_closed')


class ContentCaseModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of content case model.

    Fields:
        :case_opened (date): Date that case for content case was opened, potentially with unknown date components.
        :case_closed (date): Date that case for content case was closed, potentially with unknown date components.
    """
    case_opened = DateWithComponentsField(
        required=True,
        label=_('Case opened'),
        fields=()  # ignored
    )

    case_closed = DateWithComponentsField(
        required=True,
        label=_('Case closed'),
        fields=()  # ignored
    )

    #: Fields to show in the form
    fields_to_show = content_case_form_fields.copy()

    #: Prefix to use for form
    prefix = 'cases'

    #: Extra parameter when creating a content case formset
    formset_extra = 1

    #: Maximum number of forms parameter when creating a content case formset
    formset_max_num = 1

    #: Can delete (forms) parameter when creating a content case formset
    formset_can_delete = False

    #: Can order (forms) parameter when creating a content case formset
    formset_can_order = False

    #: Validate maximum (forms) parameter when creating a content case formset
    formset_validate_max = True

    def __init__(self, *args, **kwargs):
        """ If we're editing an instance of a content case, then set the start and end initial values.

        Add class to content case SELECT elements, so that they can be made filterable on the client-side.

        :param args:
        :param kwargs:
        """
        super(ContentCaseModelForm, self).__init__(*args, **kwargs)
        # CSS class names for fields in interface
        self.fields['outcome'].widget.attrs.update({'class': 'outcome'})
        self.fields['court'].widget.attrs.update({'class': 'court'})
        # composite date fields
        self.set_initial_composite_dates(start_field_name='case_opened', end_field_name='case_closed')

    def clean(self):
        """ Ensure that case opened occurs before case closed.

        :return: Dictionary of representing cleaned data.
        """
        cleaned_data = super(ContentCaseModelForm, self).clean()
        if not cleaned_data:
            cleaned_data = self.cleaned_data
        self._clean_start_and_end_date_components(
            cleaned_data=cleaned_data, compound_start_date_field='case_opened', compound_end_date_field='case_closed'
        )
        # return the cleaned data dictionary
        return cleaned_data

    def save(self, commit=True):
        """ Ensure that individual date components are set for starting and ending dates.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # update starting and ending date components
        self.instance = self.set_date_components(
            model_instance=self.instance,
            start_field_val=self.cleaned_data['case_opened'],
            end_field_val=self.cleaned_data['case_closed']
        )
        return super(ContentCaseModelForm, self).save(commit=commit)

    class Meta:
        model = ContentCase
        fields = content_case_form_fields.copy()
        fields_order = content_case_form_fields.copy()


class ContentPersonModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of content person model.

    Fields:
        :person_name (str): Name of the person to which the content is linked. Used for autocomplete search.
    """
    person_name = AsyncSearchCharField(
        required=True,
        label=_('Person'),
    )

    #: Fields to show in the form
    fields_to_show = ContentPerson.form_fields

    #: Prefix to use for form
    prefix = 'persons'

    #: Extra parameter when creating a content person formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a content person formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a content person formset
    formset_can_order = False

    def __init__(self, *args, **kwargs):
        """ If we're editing an instance of a content, then set the initial values for person.

        Add class to content person SELECT elements, so that they can be made filterable on the client-side.

        :param args:
        :param kwargs:
        """
        super(ContentPersonModelForm, self).__init__(*args, **kwargs)
        # CSS class names for fields in interface
        self.fields['situation_role'].widget.attrs.update({'class': 'situationrole'})
        self.fields['person_name'].widget.attrs.update({'class': 'personname'})
        # instance of model exists
        if hasattr(self, 'instance') and self.instance:
            instance = self.instance
            if hasattr(instance, 'person') and instance.person:
                self.fields['person_name'].initial = instance.person.__str__()

    class Meta:
        model = ContentPerson
        fields = ContentPerson.form_fields
        fields_order = ContentPerson.form_fields
        widgets = {'person': HiddenInput(attrs={'class': 'person'})}


class ContentAttachmentModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of attachments connected to content.

    Fields:
        :attachment_name (str): Name of the attachment to which the content is linked. Used for autocomplete search.
    """
    attachment_name = AsyncSearchCharField(
        required=True,
        label=_('Attachment'),
    )

    #: Fields to show in the form
    fields_to_show = Content.content_attachment_form_fields

    #: Prefix to use for form
    prefix = 'attachments'

    #: Extra parameter when creating an attachment linked to content formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating an attachment linked to content formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating an attachment linked to content formset
    formset_can_order = False

    def __init__(self, *args, **kwargs):
        """ If we're editing an instance of an attachment linked to content, then set the initial values.

        :param args:
        :param kwargs:
        """
        super(ContentAttachmentModelForm, self).__init__(*args, **kwargs)
        # CSS class names for fields in interface
        self.fields['attachment_name'].widget.attrs.update({'class': 'attachmentname'})
        # instance of model exists
        if hasattr(self, 'instance') and self.instance:
            instance = self.instance
            if hasattr(instance, 'attachment') and instance.attachment:
                self.fields['attachment_name'].initial = instance.attachment.__str__()

    class Meta:
        model = Content.attachments.through
        fields = Content.content_attachment_form_fields
        fields_order = Content.content_attachment_form_fields
        widgets = {'attachment': HiddenInput(attrs={'class': 'attachment'})}


class ContentIncidentModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of incidents connected to content.

    Fields:
        :incident_name (str): Name of the incident to which the content is linked. Used for autocomplete search.
    """
    incident_name = AsyncSearchCharField(
        required=True,
        label=_('Incident'),
    )

    #: Fields to show in the form
    fields_to_show = Content.content_incident_form_fields

    #: Prefix to use for form
    prefix = 'incidents'

    #: Extra parameter when creating an incident linked to content formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating an incident linked to content formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating an incident linked to content formset
    formset_can_order = False

    def __init__(self, *args, **kwargs):
        """ If we're editing an instance of an incident linked to content, then set the initial values.

        :param args:
        :param kwargs:
        """
        super(ContentIncidentModelForm, self).__init__(*args, **kwargs)
        # CSS class names for fields in interface
        self.fields['incident_name'].widget.attrs.update({'class': 'incidentname'})
        # instance of model exists
        if hasattr(self, 'instance') and self.instance:
            instance = self.instance
            if hasattr(instance, 'incident') and instance.incident:
                self.fields['incident_name'].initial = instance.incident.__str__()

    class Meta:
        model = Content.incidents.through
        fields = Content.content_incident_form_fields
        fields_order = Content.content_incident_form_fields
        widgets = {'incident': HiddenInput(attrs={'class': 'incident'})}


#: Form connecting the content identifier to content
ContentIdentifierModelFormSet = forms.inlineformset_factory(
    Content,
    ContentIdentifier,
    form=ContentIdentifierModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=ContentIdentifierModelForm.formset_extra,
    can_delete=ContentIdentifierModelForm.formset_can_delete,
    can_order=ContentIdentifierModelForm.formset_can_order,
)


#: Form connecting the content case to content
ContentCaseModelFormSet = forms.inlineformset_factory(
    Content,
    ContentCase,
    form=ContentCaseModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=ContentCaseModelForm.formset_extra,
    max_num=ContentCaseModelForm.formset_max_num,
    validate_max=ContentCaseModelForm.formset_validate_max,
    can_delete=ContentCaseModelForm.formset_can_delete,
    can_order=ContentCaseModelForm.formset_can_order,
)


#: Form connecting the content person to content
ContentPersonModelFormSet = forms.inlineformset_factory(
    Content,
    ContentPerson,
    form=ContentPersonModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=ContentPersonModelForm.formset_extra,
    can_delete=ContentPersonModelForm.formset_can_delete,
    can_order=ContentPersonModelForm.formset_can_order,
)


#: Form connecting the attachments to content
ContentAttachmentModelFormSet = forms.inlineformset_factory(
    Content,
    Content.attachments.through,
    form=ContentAttachmentModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=ContentAttachmentModelForm.formset_extra,
    can_delete=ContentAttachmentModelForm.formset_can_delete,
    can_order=ContentAttachmentModelForm.formset_can_order
)


#: Form connecting the incidents to content
ContentIncidentModelFormSet = forms.inlineformset_factory(
    Content,
    Content.incidents.through,
    form=ContentIncidentModelForm,
    formset=AbstractWizardInlineFormSet,
    extra=ContentIncidentModelForm.formset_extra,
    can_delete=ContentIncidentModelForm.formset_can_delete,
    can_order=ContentIncidentModelForm.formset_can_order
)


class AttachmentModelForm(AbstractWizardModelForm, PopupForm):
    """ Form used to create new and edit existing instances of attachment model.

    Fields:

    """
    #: Fields to show in the form
    fields_to_show = Attachment.form_fields

    #: Prefix to use for form`
    prefix = 'attachments'

    def __init__(self, *args, **kwargs):
        """ Add class to SELECT elements, so that they can be made filterable on the client-side.

        :param args:
        :param kwargs:
        """
        super(AttachmentModelForm, self).__init__(*args, **kwargs)
        # CSS class names for fields in interface
        self.prep_multiple_select(field_name='fdp_organizations')

    def save(self, commit=True):
        """ Ensure that full_clean is called for the model instance.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # only clean if saving to the database and no errors have been encountered
        if commit and not self.errors:
            self.instance.full_clean()
        return super(AttachmentModelForm, self).save(commit=commit)

    class Meta:
        model = Attachment
        fields = Attachment.form_fields
        fields_order = Attachment.form_fields


class ContentPersonAllegationModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of content person allegation models.

    Fields:
        :primary_key (int): Id used to update record.
    """
    primary_key = forms.IntegerField(
        required=False,
        label=_('Primary key'),
        widget=HiddenInput(),
        help_text=_('Id used to update record')
    )

    #: Fields to show in the form
    fields_to_show = ContentPersonAllegation.form_fields

    #: Prefix to use for form
    prefix = 'allegations'

    #: Extra parameter when creating a content person allegation formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a content person allegation formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a content person allegation formset
    formset_can_order = False

    def __init__(self, has_primary_key=None, *args, **kwargs):
        """ If we're editing an instance of a content person allegation, then set the initial values.

        :param has_primary_key: Primary key used to identify allegation that is being updated. Will be None for new
        allegations.
        :param args:
        :param kwargs:
        """
        super(ContentPersonAllegationModelForm, self).__init__(*args, **kwargs)
        # primary key for existing content person allegation corresponding to form, if such exists in the database
        if has_primary_key:
            self.fields['primary_key'].initial = has_primary_key

    class Meta:
        model = ContentPersonAllegation
        fields = ContentPersonAllegation.form_fields
        fields_order = ContentPersonAllegation.form_fields
        widgets = {'content_person': HiddenInput(attrs={'class': 'foreignkey'})}


class ContentPersonPenaltyModelForm(AbstractWizardModelForm):
    """ Form used to create new and edit existing instances of content person penalty models.

    Fields:
        :primary_key (int): Id used to update record.
    """
    primary_key = forms.IntegerField(
        required=False,
        label=_('Primary key'),
        widget=HiddenInput(),
        help_text=_('Id used to update record')
    )

    #: Fields to show in the form
    fields_to_show = ContentPersonPenalty.form_fields

    #: Prefix to use for form
    prefix = 'penalties'

    #: Extra parameter when creating a content person penalty formset
    formset_extra = 0

    #: Can delete (forms) parameter when creating a content person penalty formset
    formset_can_delete = True

    #: Can order (forms) parameter when creating a content person penalty formset
    formset_can_order = False

    def __init__(self, has_primary_key=None, *args, **kwargs):
        """ If we're editing an instance of a content person penalty, then set the initial values.

        :param has_primary_key: Primary key used to identify penalty that is being updated. Will be None for new
        penalties.
        :param args:
        :param kwargs:
        """
        super(ContentPersonPenaltyModelForm, self).__init__(*args, **kwargs)
        # primary key for existing content person penalty corresponding to form, if such exists in the database
        if has_primary_key:
            self.fields['primary_key'].initial = has_primary_key

    class Meta:
        model = ContentPersonPenalty
        fields = ContentPersonPenalty.form_fields
        fields_order = ContentPersonPenalty.form_fields
        widgets = {
            'content_person': HiddenInput(attrs={'class': 'foreignkey'}),
            'discipline_date': DateWithCalendarInput()
        }


#: Form set connecting the content person allegation to content person
ContentPersonAllegationModelFormSet = forms.modelformset_factory(
    ContentPersonAllegation,
    ContentPersonAllegationModelForm,
    formset=AbstractWizardModelFormSet,
    extra=ContentPersonAllegationModelForm.formset_extra,
    can_delete=ContentPersonAllegationModelForm.formset_can_delete,
    can_order=ContentPersonAllegationModelForm.formset_can_order
)


#: Form set connecting the content person penalty to content person
ContentPersonPenaltyModelFormSet = forms.modelformset_factory(
    ContentPersonPenalty,
    ContentPersonPenaltyModelForm,
    formset=AbstractWizardModelFormSet,
    extra=ContentPersonPenaltyModelForm.formset_extra,
    can_delete=ContentPersonPenaltyModelForm.formset_can_delete,
    can_order=ContentPersonPenaltyModelForm.formset_can_order
)


class ReadOnlyContentModelForm(ContentModelForm):
    """ Read-only version of content model form used by the view to link allegations and penalties to the content.

    Fields:
        None.
    """
    def is_valid(self):
        """ Form is not intended to be validated, so always return True.

        For a content model form that can be validated, use ContentModelForm.

        :return: Always True.
        """
        return True

    def save(self, commit=True):
        """ Form is not intended to be saved, so do nothing.

        For a content model form that can be saved, use ContentModelForm.

        :param commit: Ignored.
        :return: Nothing.
        """
        return None
