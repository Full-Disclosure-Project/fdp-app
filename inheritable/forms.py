from django.core.exceptions import ValidationError
from django.forms import BooleanField, MultiValueField, ModelForm, CharField, IntegerField, TextInput, Select, \
    ChoiceField
from django.db.utils import ProgrammingError
from django.forms import formsets
from django.forms.formsets import BaseFormSet
from django.forms.fields import BoundField
from django.forms.models import BaseInlineFormSet, BaseModelFormSet
from django.forms.widgets import MultiWidget, NumberInput, HiddenInput, DateInput
from django.utils.translation import ugettext_lazy as _
from .models import AbstractDateValidator


class AbstractWizardFormSet(BaseFormSet):
    """ Adds a class to the DELETE field widget, so that it can be easily identified on the client-side.

    This is used to manually hide deleted forms in some instances, such as when a form is submitted, does not validate,
    and then is returned and re-rendered on the client-side.

    In these cases, since form visibility is manipulated on the client-side (e.g. through templates), deleted forms can
    be easily hidden.

    """
    @staticmethod
    def add_class_to_delete(form):
        """ Adds a CSS class to the DELETE field widget.

        :param form: Form containing DELETE field
        :return: Nothing.
        """
        # add class to delete field
        if formsets.DELETION_FIELD_NAME in form.fields:
            form.fields[formsets.DELETION_FIELD_NAME].widget.attrs.update({'class': 'formdel'})

    def add_fields(self, form, index):
        """ Adds a CSS class to the DELETE field widget.

        :param form: Form for which to add fields.
        :param index: Index in formset, at which form exists.
        :return: Nothing.
        """
        super(AbstractWizardFormSet, self).add_fields(form=form, index=index)
        self.add_class_to_delete(form=form)


class AbstractWizardModelFormSet(BaseModelFormSet):
    """ Adds a class to the DELETE field widget, so that it can be easily identified on the client-side.

    This is used to manually hide deleted forms in some instances, such as when a form is submitted, does not validate,
    and then is returned and re-rendered on the client-side.

    In these cases, since form visibility is manipulated on the client-side (e.g. through templates), deleted forms can
    be easily hidden.

    """
    def add_fields(self, form, index):
        """ Adds a CSS class to the DELETE field widget.

        :param form: Form for which to add fields.
        :param index: Index in formset, at which form exists.
        :return: Nothing.
        """
        super(AbstractWizardModelFormSet, self).add_fields(form=form, index=index)
        AbstractWizardFormSet.add_class_to_delete(form=form)

    def set_total_forms(self, num_of_forms):
        """ Set the total number of forms in the management form for the formset.

        :param num_of_forms: Total number of forms.
        :return: Nothing.
        """
        self.management_form.data['{p}-{t}'.format(p=self.management_form.prefix, t='TOTAL_FORMS')] = num_of_forms


class AbstractWizardInlineFormSet(BaseInlineFormSet):
    """ Adds a class to the DELETE field widget, so that it can be easily identified on the client-side.

    This is used to manually hide deleted forms in some instances, such as when a form is submitted, does not validate,
    and then is returned and re-rendered on the client-side.

    In these cases, since form visibility is manipulated on the client-side (e.g. through templates), deleted forms can
    be easily hidden.

    """
    def add_fields(self, form, index):
        """ Adds a CSS class to the DELETE field widget.

        :param form: Form for which to add fields.
        :param index: Index in formset, at which form exists.
        :return: Nothing.
        """
        super(AbstractWizardInlineFormSet, self).add_fields(form=form, index=index)
        AbstractWizardFormSet.add_class_to_delete(form=form)


class AbstractWizardModelForm(ModelForm):
    """ Abstract model form from which all model forms inherit that are rendered through the data management wizard.

    """
    #: Parameter used to indicate whether a field is hidden when it is rendered in HTML.
    hide_param = 'hide_in_html'

    #: CSS class used to style required fields and their corresponding labels.
    required_css_class = 'required'

    #: List of fields to show when they are rendered in HTML.
    fields_to_show = []

    #: Types of relationships that can be initialized by set_initial_relationship(...)
    init_person_relationship = 1
    init_grouping_relationship = 2

    def __init__(self, *args, **kwargs):
        """ Hide all fields unless they are contained within the fields_to_show list.

        Change all date input formats to mm/dd/yyyy.

        """
        super(AbstractWizardModelForm, self).__init__(*args, **kwargs)
        for field in self.fields:
            setattr(self.fields[field], self.hide_param, field not in self.fields_to_show)
            # change all date input formats to mm/dd/yyyy
            if isinstance(self.fields[field].widget, DateInput):
                self.fields[field].widget.format = '%m/%d/%Y'

    def _clean_start_and_end_date_components(self, cleaned_data, compound_start_date_field, compound_end_date_field):
        """ Clean the compound start and end date fields.

        :param cleaned_data: Dictionary of cleaned data.
        :param compound_start_date_field: Value retrieved from compound start date.
        :param compound_end_date_field: Value retrieved from compound end date.
        :return: Nothing.
        """
        # compound start date is defined
        compound_start_date = cleaned_data.get(compound_start_date_field, None)
        if compound_start_date:
            # assume format is mm/dd/yyyy, so convert to [mm, dd, yyyy]
            start_date = self.__split_start_date_components(start_field_val=compound_start_date)
            start_month = int(start_date[0])
            start_day = int(start_date[1])
            start_year = int(start_date[2])
        else:
            start_month = AbstractDateValidator.UNKNOWN_DATE
            start_day = AbstractDateValidator.UNKNOWN_DATE
            start_year = AbstractDateValidator.UNKNOWN_DATE
        # compound end date is defined
        compound_end_date = cleaned_data.get(compound_end_date_field, None)
        if compound_end_date:
            # assume format is mm/dd/yyyy, so convert to [mm, dd, yyyy]
            end_date = self.__split_end_date_components(end_field_val=compound_end_date)
            end_month = int(end_date[0])
            end_day = int(end_date[1])
            end_year = int(end_date[2])
        else:
            end_month = AbstractDateValidator.UNKNOWN_DATE
            end_day = AbstractDateValidator.UNKNOWN_DATE
            end_year = AbstractDateValidator.UNKNOWN_DATE
        # validated that compound start date is before compound end date
        if compound_start_date and compound_end_date:
            self.Meta.model.check_start_date_before_end_date(
                start_year=start_year,
                start_month=start_month,
                start_day=start_day,
                end_year=end_year,
                end_month=end_month,
                end_day=end_day
            )

    def set_initial_composite_dates(self, start_field_name=None, end_field_name=None):
        """ Set the DateWithComponentsFields (i.e. composite date fields) for the form for both starting and ending
        dates.

        :param start_field_name: Name of DateWithComponentsField storing starting date components.
        :param end_field_name: Name of DateWithComponentsField storing ending date components.
        :return: Nothing.
        """
        # instance of model exists
        if hasattr(self, 'instance') and self.instance:
            instance = self.instance
            # there is a start field on the form, so set the initial value
            if start_field_name:
                self.fields[start_field_name].initial = '{mm}/{dd}/{yyyy}'.format(
                    yyyy=instance.start_year,
                    mm=instance.start_month,
                    dd=instance.start_day
                )
            # there is an end field on the form, so set the initial value
            if end_field_name:
                self.fields[end_field_name].initial = '{mm}/{dd}/{yyyy}'.format(
                    yyyy=instance.end_year,
                    mm=instance.end_month,
                    dd=instance.end_day
                )

    def set_initial_relationship(self, field_name, relationship_type, for_obj_id):
        """ Set the RelationshipField (i.e. composite relationship fields) for the form.

        :param field_name: Name of RelationshipField storing relationship components.
        :param relationship_type: Type of relationship that should be initialized.
        :param for_obj_id: ID of main object, for which to initialize relationship.
        :return: Nothing.
        """
        # instance of model exists
        if hasattr(self, 'instance') and self.instance:
            instance = self.instance
            # initialize person relationship
            if relationship_type == self.init_person_relationship:
                if hasattr(instance, 'subject_person') and instance.subject_person:
                    subject_id = instance.subject_person.pk
                    subject_str = instance.subject_person.__str__()
                else:
                    subject_id = ''
                    subject_str = ''
                if hasattr(instance, 'object_person') and instance.object_person:
                    object_id = instance.object_person.pk
                    object_str = instance.object_person.__str__()
                else:
                    object_id = ''
                    object_str = ''
                type_id = instance.type.pk if hasattr(instance, 'type') and instance.type else ''
            # initialize grouping relationship
            elif relationship_type == self.init_grouping_relationship:
                if hasattr(instance, 'subject_grouping') and instance.subject_grouping:
                    subject_id = instance.subject_grouping.pk
                    subject_str = instance.subject_grouping.__str__()
                else:
                    subject_id = ''
                    subject_str = ''
                if hasattr(instance, 'object_grouping') and instance.object_grouping:
                    object_id = instance.object_grouping.pk
                    object_str = instance.object_grouping.__str__()
                else:
                    object_id = ''
                    object_str = ''
                type_id = instance.type.pk if hasattr(instance, 'type') and instance.type else ''
            else:
                raise Exception(_('Unsupported relationship type to be initialized'))
            # the object for which to initialize the relationship should be removed from the relationship
            if subject_id == for_obj_id:
                subject_id = ''
                subject_str = ''
            else:
                object_id = ''
                object_str = ''
            self.fields[field_name].initial = \
                '{subject_id}{s}{subject_str}{s}{type}{s}{object_id}{s}{object_str}'.format(
                subject_id=subject_id,
                subject_str=subject_str,
                type=type_id,
                object_id=object_id,
                object_str=object_str,
                s=RelationshipWidget.split_chars
            )

    @staticmethod
    def __split_start_date_components(start_field_val):
        """ Splits the value of a start date defined through a DateWithComponentsField into its individual date
        components.

        Assumption: incoming format is mm/dd/yyyy, and so outgoing format is [mm, dd, yyyy].

        :param start_field_val: Value of start date defined through a DateWithComponentsField.
        :return: Individual date components for start date in a list.
        """
        # assume format is mm/dd/yyyy, so convert to [mm, dd, yyyy]
        return str(start_field_val).split('/')

    @staticmethod
    def __split_end_date_components(end_field_val):
        """ Splits the value of a end date defined through a DateWithComponentsField into its individual date
        components.

        Assumption: incoming format is mm/dd/yyyy, and so outgoing format is [mm, dd, yyyy].

        :param end_field_val: Value of end date defined through a DateWithComponentsField.
        :return: Individual date components for end date in a list.
        """
        # assume format is mm/dd/yyyy, so convert to [mm, dd, yyyy]
        return str(end_field_val).split('/')

    @classmethod
    def set_date_components(cls, model_instance, start_field_val=None, end_field_val=None):
        """ Set the individual date components for a model instance given the values from DateWithComponentsFields for
        both the starting and ending dates.

        :param model_instance: Instance of model whose individual date components should be set.
        :param start_field_val: Value of a DateWithComponentsField for the starting date.
        :param end_field_val: Value of a DateWithComponentsField for the ending date.
        :return: Model instance with individual date components.
        """
        # start date was passed in
        if start_field_val:
            # assume format is mm/dd/yyyy, so convert to [mm, dd, yyyy]
            start_date = cls.__split_start_date_components(start_field_val=start_field_val)
            model_instance.start_month = int(start_date[0])
            model_instance.start_day = int(start_date[1])
            model_instance.start_year = int(start_date[2])

        # end date was passed in
        if end_field_val:
            # assume format is mm/dd/yyyy, so convert to [mm, dd, yyyy]
            end_date = cls.__split_end_date_components(end_field_val=end_field_val)
            model_instance.end_month = int(end_date[0])
            model_instance.end_day = int(end_date[1])
            model_instance.end_year = int(end_date[2])

        return model_instance

    @staticmethod
    def set_relationship_components(
            model_instance, field_val, subject_field_name, object_field_name, type_field_name, for_id
    ):
        """ Set the individual relationship components for a model instance given the values from RelationshipField.

        :param model_instance: Instance of model whose individual relationship components should be set.
        :param field_val: Value of a RelationshipField.
        :param subject_field_name: Name of subject field in the relationship.
        :param object_field_name: Name of object field in the relationship.
        :param type_field_name: Name of type field in the relationship.
        :param for_id: ID of person, grouping or other instance for which the relationship is intended.
        :return: Model instance with individual relationship components.
        """
        # assume format is '{subject_id}{s}{subject_str}{s}{type}{s}{object_id}{s}{object_str}',
        # so convert to [subject_id, subject_str, type, object_id, object_str]
        list_of_vals = str(field_val).split(RelationshipWidget.split_chars)
        if len(list_of_vals) != 5:
            raise Exception(_('Relationship widget value has invalid formatting'))
        subject_id = list_of_vals[0] if list_of_vals[0] else for_id
        type_id = list_of_vals[2]
        object_id = list_of_vals[3] if list_of_vals[3] else for_id
        setattr(model_instance, subject_field_name, subject_id)
        setattr(model_instance, type_field_name, type_id)
        setattr(model_instance, object_field_name, object_id)
        return model_instance

    def save(self, commit=True):
        """ Ensure that full_clean is called for the model instance.

        :param commit: True if instance should be saved into the database, false otherwise.
        :return: Model instance that was created through the form.
        """
        # only clean if saving to the database and no errors have been encountered
        if commit and not self.errors:
            self.instance.full_clean()
        return super(AbstractWizardModelForm, self).save(commit=commit)

    @staticmethod
    def get_formset_management_form_data(prefix, total_forms=0, initial_forms=0, max_forms=''):
        """ Retrieves a dictionary containing the management form data for a formset.

        :param prefix: Prefix for the formset.
        :param total_forms: Total number of forms in the formset.
        :param initial_forms: Number of initial forms in the formset.
        :param max_forms: Maximum number of forms in the formset. Use empty string if no maximum.
        :return: Dictionary containing the management form data for a formset.
        """
        return {
            '{prefix}-TOTAL_FORMS'.format(prefix=prefix): '{i}'.format(i=total_forms),
            '{prefix}-INITIAL_FORMS'.format(prefix=prefix): '{i}'.format(i=initial_forms),
            '{prefix}-MAX_NUM_FORMS'.format(prefix=prefix): '{i}'.format(i=max_forms)
        }

    def prep_multiple_select(self, field_name):
        """ Adds a CSS class name to a multiple SELECT element, so that it can easily be wrapped in the Select2 package.

        :param field_name: Name of field to which to add CSS class name.
        :return: Nothing.
        """
        self.fields[field_name].widget.attrs.update({'class': 'multiselect'})

    def add_management_fields(self):
        """ Manually add the field that stores whether the form is deleted.

        :return: Nothing.
        """
        if formsets.DELETION_FIELD_NAME not in self.fields:
            self.fields[formsets.DELETION_FIELD_NAME] = BooleanField(label=_('Delete'), required=False)


class DateWithCalendarInput(DateInput):
    """ Widget that extends the standard Django date widget by adding a calendar icon.

    See: https://docs.djangoproject.com/en/2.2/ref/forms/widgets/#dateinput

    """
    template_name = 'date_with_calendar_widget.html'

    def get_context(self, name, value, attrs):
        """ Adds an additional class name to the widget's attributes.

        :param name: The name of the field from the name argument.
        :param value: The value as returned by format_value().
        :param attrs: HTML attributes to be set on the rendered widget. The combination of the attrs attribute and the
        attrs argument.
        :return: Returns a dictionary of values to use when rendering the widget template.
        """
        c = 'class'
        # retrieve existing class names
        class_names = attrs.get(c, '')
        # only add preceding whitespace if there already exists other class names
        class_names = '{c}{s}{n}'.format(
            c=class_names,
            s='' if not class_names else ' ',
            n='singledate'
        )
        attrs.update({c: class_names})
        return super(DateWithCalendarInput, self).get_context(name=name, value=value, attrs=attrs)


class DateWithComponentsWidget(MultiWidget):
    """ Widget supporting a date with potentially unknown components.

    See: https://docs.djangoproject.com/en/2.2/ref/forms/widgets/#multiwidget

    """
    template_name = 'dates_with_components_widget.html'

    def __init__(self, *args, **kwargs):
        """ Initialize three number inputs with ranges corresponding to month, day and year.

        :param args:
        :param kwargs:
        """
        super(DateWithComponentsWidget, self).__init__(
            widgets=[
                NumberInput(attrs={'class': 'datemonth', 'size': 2, 'min': 0, 'max': 12, 'type': 'number'}),
                NumberInput(attrs={'class': 'dateday', 'size': 2, 'min': 0, 'max': 31, 'type': 'number'}),
                NumberInput(attrs={'class': 'dateyear', 'size': 4, 'min': 0, 'max': 2100, 'type': 'number'})
            ],
            *args,
            **kwargs
        )

    def decompress(self, value):
        """ Break the mm/dd/yyyy date into its individual date components.

        :param value: Date suppled in the mm/dd/yyyy format.
        :return: List of date components in the order of: month, day, year.
        """
        if value:
            return value.split('/')
        return [0, 0, 0]


class DateWithComponentsField(MultiValueField):
    """ A collection of fields supporting a date with potentially unknown components.

    See: https://docs.djangoproject.com/en/2.2/ref/forms/fields/#multivaluefield

    """
    widget = DateWithComponentsWidget

    def __init__(self, fields, *args, **kwargs):
        """ Overrides the fields parameter to specify three CharFields.

        :param fields: Saved as _prev_fields attribute.
        :param args:
        :param kwargs:
        """
        # store previous fields parameter, because we will overwrite it
        self._prev_fields = fields
        fields = (
            CharField(),
            CharField(),
            CharField()
        )
        super(DateWithComponentsField, self).__init__(
            fields=fields,
            widget=DateWithComponentsWidget,
            *args,
            **kwargs
        )

    @staticmethod
    def compress_vals(data_list):
        """ Combine individual date components into a single string mm/dd/yyyy.

        :param data_list: List of individual date components in the order of: month, day, year.
        :return: Single string in the format mm/dd/yyyy.
        """
        return '/'.join(data_list)

    def compress(self, data_list):
        """ Combine individual date components into a single string mm/dd/yyyy.

        :param data_list: List of individual date components in the order of: month, day, year.
        :return: Single string in the format mm/dd/yyyy.
        """
        return self.compress_vals(data_list=data_list)


class DateWithCalendarAndSplitInput(DateWithCalendarInput):
    """ Widget that extends the date with calendar icon widget, by adding a split date into date range icon.

    """
    template_name = 'date_with_calendar_and_split_icon_widget.html'


class DateWithCalendarAndCombineInput(DateWithCalendarInput):
    """ Widget that extends the date with calendar icon widget, by adding a combine date range into single date icon.

    """
    template_name = 'date_with_calendar_and_combine_icon_widget.html'


class PopupForm:
    """ A form that may be rendered in a popup window.

    Fields:
        :popup_id (str): Unique identifier for popup window.

    """
    #: Name of input field containing the unique identifier for the popup window.
    popup_id_field = 'popup_id'

    @classmethod
    def is_rendered_as_popup(cls, post_data):
        """ Checks whether the form is rendered as a popup.

        :param post_data: POST data that was submitted through form.
        :return: True if form is rendered as a popup, false otherwise.
        """
        if cls.popup_id_field in post_data and post_data[cls.popup_id_field]:
            return True
        else:
            return False

    @classmethod
    def get_popup_id(cls, post_data):
        """ Retrieves unique identifier for popup.

        :param post_data: POST data that was submitted through form.
        :return: Unique identifier for popup.
        """
        return post_data[cls.popup_id_field]


class RelationshipWidget(MultiWidget):
    """ Widget representing a relationship.

    See: https://docs.djangoproject.com/en/2.2/ref/forms/widgets/#multiwidget

    """
    #: template used to render the widget for the relationship field in HTML
    template_name = 'relationship_widget.html'

    #: Separator characters used to divide the field values when they are all concatenated into a single string.
    split_chars = '-----'

    #: Index of subject ID when field values are represented as a list.
    subject_index = 0

    #: Index of object ID when field values are represented as a list.
    object_index = 3

    #: Index of relationship type when field values are represented as a list.
    verb_index = 2

    def __init__(self, *args, **kwargs):
        """ Initialize inputs representing relationship.

        :param args:
        :param kwargs:
        """
        queryset = kwargs.pop('queryset')
        # try and access the queryset (whether a variable or a callable)
        try:
            choices = queryset() if callable(queryset) else queryset
        # relationship "does not exist" may be raised during initial migrations because the data model has not been
        # fully migrated into the database
        except ProgrammingError as err:
            # exception is expected, assumed to occur during the initial migrations, since data model for supporting app
            # has not yet been created in the database
            if 'does not exist' in str(err):
                choices = []
            # this is an unexpected exception, so raise it again
            else:
                raise
        super(RelationshipWidget, self).__init__(
            widgets=[
                HiddenInput(attrs={'class': 'subjectid'}),
                TextInput(attrs={'class': 'subjectname'}),
                Select(
                    choices=choices,
                    attrs={'class': 'relationshiptype'}),
                HiddenInput(attrs={'class': 'objectid'}),
                TextInput(attrs={'class': 'objectname'}),
            ],
            *args,
            **kwargs
        )

    @classmethod
    def split_field_value_into_list(cls, value):
        """ Splits the field value into a list of values.

        :param value: Field value in string representation.
        :return: Field value in list representation
        """
        if value:
            list_of_vals = value.split(cls.split_chars)
            if len(list_of_vals) != 5:
                raise Exception(_('Decompression failed because RelationshipWidget value has invalid formatting'))
            return list_of_vals
        return ['', '', '', '', '']

    def decompress(self, value):
        """ Break the string into its individual relationship components.

        :param value: String representing relationship.
        :return: List of relationship components in the order of: subject_id, subject_str, type, object_id, object_str.
        """
        return self.split_field_value_into_list(value=value)


class RequiredBoundField(BoundField):
    """ A wrapper around Django's BoundField class that styles corresponding labels as if the bound field was required.

    Used in the inheritable.forms.RelationshipField class.

    See https://docs.djangoproject.com/en/3.2/ref/forms/api/#django.forms.BoundField

    """
    def label_tag(self, contents=None, attrs=None, label_suffix=None):
        """ Retrieves the HTML to represent the label corresponding to the field.

        Adds a CSS class to ensure that the label is styled as if the bound field is required.

        :param contents: Text represented in label.
        :param attrs: Dictionary of attributes that define the label.
        :param label_suffix: Text placed after the label. Default is a colon.
        :return: HTML representing label for field.
        """
        class_key = 'class'
        if not attrs:
            attrs = {}
        if class_key not in attrs:
            attrs[class_key] = AbstractWizardModelForm.required_css_class
        else:
            attrs[class_key] += ' ' + AbstractWizardModelForm.required_css_class
        return super().label_tag(contents=contents, attrs=attrs, label_suffix=label_suffix)


class RelationshipField(MultiValueField):
    """ A collection of fields that represents a relationship.

    See: https://docs.djangoproject.com/en/2.2/ref/forms/fields/#multivaluefield

    """
    widget = RelationshipWidget

    def __init__(self, fields, queryset, *args, **kwargs):
        """ Overrides the fields parameter.

        :param fields: Saved as _prev_fields attribute.
        :param args:
        :param kwargs:
        """
        # overwrite required attribute, and replace it with custom validation and styling of field label as if required
        required_key = 'required'
        if required_key in kwargs:
            kwargs[required_key] = False
        # store previous fields parameter, because we will overwrite it
        self._prev_fields = fields
        fields = (
            IntegerField(),
            CharField(),
            ChoiceField(choices=queryset),
            IntegerField(),
            CharField()
        )
        super(RelationshipField, self).__init__(
            fields=fields,
            widget=RelationshipWidget(queryset=queryset),
            *args,
            **kwargs
        )

    def compress(self, data_list):
        """ Combine field values into a single string.

        :param data_list: List of field values in the order of: subject_id, subject_str, type, object_id, object_str.
        :return: Single string.
        """
        return RelationshipWidget.split_chars.join(['' if not d else str(d) for d in data_list])

    def validate(self, value):
        """ Validate the relationship field by ensuring that:
         - relationship type is defined
         - at least the subject or object in the relationship is defined

        :param value: Field value for relationship represented as a string.
        :return: Nothing.
        """
        super(RelationshipField, self).validate(value=value)
        relationship_widget = self.widget
        decompressed = relationship_widget.split_field_value_into_list(value=value)
        # relationship type missing
        if not decompressed[relationship_widget.verb_index]:
            raise ValidationError(_('The type of relationship is required'))
        # subject or object missing
        if not (decompressed[relationship_widget.subject_index] or decompressed[relationship_widget.object_index]):
            raise ValidationError(_('Other part of relationship is missing'))

    def get_bound_field(self, form, field_name):
        """ Uses a wrapper class for the BoundField so that the label corresponding to the field is always styled
        as required.

        Derived from the get_bound_field(...) method in the Field class in django/forms/fields.py.

        :param form: Form containing bound field.
        :param field_name: Name of field.
        :return: Wrapped bound field instance.
        """
        return RequiredBoundField(form, self, field_name)


class AsyncSearchCharField(CharField):
    """ Used for fields that support asynchronous requests to the server to retrieve values that may match the user's
    input.

    An example includes field that supports person searches when linking persons to incidents in the changing app form.

    """
    def validate(self, value):
        """ Suppresses the required validation on the field, since it always has a corresponding hidden field on which
        required validation will be performed. This hidden field will store the ID of the record that is selected
        through the asynchronous search.

        (1) Allows AsyncSearchCharField(..., required=True, ...) so that its input and label can be rendered with
        appropriate visual queues to indicate that they are required, e.g. using default Django Admin styling and
        required_css_class = 'required' on the containing form; and

        (2) Avoids duplicate error message "This field is required." if the field is left empty.

        :param value: Value stored in the field. Ignored.
        :return: Nothing.
        """
        #: Copied from the validate(...) method in the Field class in django/forms/fields.py, and then commented out.
        #         if value in self.empty_values and self.required:
        #             raise ValidationError(self.error_messages['required'], code='required')
        pass
