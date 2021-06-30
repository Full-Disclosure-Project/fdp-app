from django.utils.translation import ugettext_lazy as _
from django.utils.text import slugify
from django.utils.html import urlize
from django.utils.timezone import now
from django.db.models import ForeignKey, OneToOneField, ManyToManyField, IntegerField, DecimalField
from django.core.exceptions import ValidationError
from django.conf import settings
#: TODO: Confidentliaty filtering
#: TODO from inheritable.models import Confidentiable
from .models import BulkImport
from inheritable.models import AbstractFileValidator, AbstractUrlValidator, AbstractConfiguration, AbstractDateValidator
from core.models import Grouping, GroupingAlias, GroupingRelationship, Person, PersonAlias, PersonContact, \
    PersonIdentifier, PersonTitle, PersonGrouping, Incident, PersonIncident, PersonPhoto, PersonPayment
from sourcing.models import Content, ContentIdentifier, ContentCase, ContentPerson, ContentPersonAllegation, \
    ContentPersonPenalty, Attachment
from supporting.models import County, GroupingRelationshipType, PersonIdentifierType, Trait, Title, IncidentTag, \
    Location, EncounterReason, State, ContentIdentifierType, ContentCaseOutcome, AllegationOutcome, Allegation, \
    ContentType, PersonGroupingType, LeaveStatus, AttachmentType
from rest_framework.serializers import ModelSerializer, CharField, EmailField
from rest_framework.fields import empty
from reversion.revisions import create_revision
from datetime import datetime
from json import dumps as json_dumps
from re import compile as re_compile
from urllib.request import urlretrieve
from urllib.parse import urlparse
from os.path import exists as path_exists, basename as path_basename, dirname as path_dirname
from os import makedirs as os_makedirs
from errno import EEXIST
from decimal import Decimal, InvalidOperation


class FdpModelSerializer(ModelSerializer):
    """ Base serializer class from which all FDP model serializer classes inherit.

    Records imported record in the bulk import table.

        Attributes:
            :external_id (str): Unique identifier for record outside of FDP.

    """
    #: Key in original_validated_data dictionary indicating that no validated data is recorded.
    no_validated_data_key = 'note'

    #: Value in original_validated_data dictionary indicating that no validated data is recorded.
    no_validated_data_value = str(_('No validated data was recorded.'))

    def __init__(self, instance=None, data=empty, **kwargs):
        """ Initialize the attribute that will store the validated data dictionary before it is modified.

        Also, initializes the attribute that will store a dictionary of validated attributes that are kept outside the
        default model serializer validation.

        :param instance:
        :param data:
        :param kwargs:
        """
        super(FdpModelSerializer, self).__init__(instance=instance, data=data, **kwargs)
        self.original_validated_data = {self.no_validated_data_key: self.no_validated_data_value}
        self.custom_validated_data = {}

    external_id = CharField(
        required=False,
        label=_('Unique ID for record outside of FDP')
    )

    #: Fields that should be excluded from the list of mappable target serializer fields.
    excluded_fields = ['is_archived']

    #: Fields for Confidentiable models that should be excluded from the list of mappable target serializer fields.
    confidentiable_excluded_fields = ['fdp_organizations', 'for_host_only', 'for_admin_only']

    #: Fields for AbstractExactDateBounded models that should be excluded from the list of mappable target serializer
    # fields.
    abstract_exact_date_bounded_excluded_fields = [
        'start_year', 'end_year', 'start_month', 'end_month', 'start_day', 'end_day'
    ]

    #: Fields for AbstractAsOfDateBounded models that should be excluded from the list of mappable target serializer
    # fields.
    abstract_as_of_date_bounded_excluded_fields = abstract_exact_date_bounded_excluded_fields + ['as_of']

    def __create(self, validated_data, external_id):
        """ Creates a new record, and stores its details in the bulk import table.

        :param validated_data: Dictionary of validated data to import. The 'external_id' key and its value have already
        been popped from it.
        :param external_id: A unique identifier for the record outside of FDP that can be used reference it in future
        imports.
        :return: Instance of newly created record.
        """
        instance = super(FdpModelSerializer, self).create(validated_data=validated_data)
        self_meta = getattr(self, 'Meta')
        model_class = self_meta.model
        bulk_import = BulkImport(
            source_imported_from=str(_('Django Data Wizard package import file')),
            table_imported_from=str(self.__class__.__name__),
            table_imported_to=str(model_class.get_db_table()),
            pk_imported_from=str(external_id),
            pk_imported_to=int(instance.pk),
            data_imported=json_dumps(self.original_validated_data, default=str),
            notes=''
        )
        bulk_import.full_clean()
        bulk_import.save()
        return instance

    def create(self, validated_data):
        """ Creates a new record and stores its details in the bulk import table.

        :param validated_data: Dictionary of validated data to import.
        :return: Instance of newly created record.
        """
        # validated data has not yet been recorded
        if self.original_validated_data.get(self.no_validated_data_key, '') == self.no_validated_data_value:
            self.original_validated_data = validated_data.copy()
        external_id = validated_data.pop('external_id', 'Undefined')
        # versioning is turned of for the records to be imported
        if AbstractConfiguration.disable_versioning_for_data_wizard_imports():
            # disable versioning to improve performance
            # If manage_manually=True, versions will not be saved when a model’s save() method is called. This allows
            # version control to be switched off for a given revision block.
            # If atomic=True, the revision block will be wrapped in a transaction.atomic().
            # see: https://django-reversion.readthedocs.io/en/stable/views.html#decorators
            with create_revision(manage_manually=True, atomic=False):
                return self.__create(validated_data=validated_data, external_id=external_id)
        # versioning is turned on for the records to be imported
        else:
            return self.__create(validated_data=validated_data, external_id=external_id)

    def update(self, instance, validated_data):
        """ Update is disabled.

        :param instance: Instance of record to update.
        :param validated_data: Dictionary of validated data with which to update record.
        :return: Instance of updated record.
        """
        raise Exception(_('Updating data through the Django Data Wizard package for FDP is not yet supported'))

    def is_valid(self, raise_exception=False):
        """ Validates data to import.

        Drops values that represent unknowns, relying on model default.

        :param raise_exception: True if exception should be raised if data is invalid, false otherwise.
        :return: True if data is valid, false otherwise.
        """
        # cycle through all initial data
        for key in self.initial_data.keys():
            # initial data is some version of unknown
            if self.initial_data[key] in ['NA', 'N/A', 'na', 'n/a', '']:
                self_meta = getattr(self, 'Meta')
                model_class = self_meta.model
                model_class_meta = getattr(model_class, '_meta')
                field_to_check = model_class_meta.get_field(key)
                # unknown data refers to a foreign key or number so standardize
                if isinstance(field_to_check, ForeignKey) or isinstance(field_to_check, IntegerField) \
                        or isinstance(field_to_check, DecimalField) or isinstance(field_to_check, OneToOneField) \
                        or isinstance(field_to_check, ManyToManyField):
                    self.initial_data[key] = None
        return super(FdpModelSerializer, self).is_valid(raise_exception=raise_exception)

    def _convert_null_to_blank(self, field_name):
        """ Convert a null value to a blank value for a field.

        :param field_name: Name of field whose value, if null, should be converted to blank.
        :return: Nothing.
        """
        # convert null address to blank
        field_value = self.initial_data.get(field_name, '')
        self.initial_data[field_name] = '' if not field_value else field_value

    def _match_by_unique_name(self, name_to_match, model, validated_data_key):
        """ Matches a model instance in the queryset using the unique name for that instance.

        :param name_to_match: Unique name used to identify and match model instance.
        :param model: Model for which instance should be identified and matched.
        :param validated_data_key: Key in dictionary of validated data that will hold matched model instance. If
        omitted, method will return matched model instance.
        :return: Nothing if validated_data_key is specified. Otherwise, method returns the matched model instance.
        """
        filter_dict = {'name__iexact': name_to_match}
        qs = model.objects.filter(**filter_dict)
        # TODO: Confidentiality filtering
        # TODO: if issubclass(model, Confidentiable):
        # TODO:     user = self.context['request'].user
        # TODO:     qs = qs.filter_for_confidential_by_user(user=user)
        # could not exactly match a single record
        if qs.count() != 1:
            raise ValidationError(
                _('There is not exactly one {m} with the name {n}'.format(m=model.__name__, n=name_to_match))
            )
        # matched exactly with a single record
        else:
            # model instance matched by unique name
            matched_instance = qs.get(**filter_dict)
            # no validated data key was passed in, so just return the matched instance
            if not validated_data_key:
                return matched_instance
            # validated data key was passed in
            else:
                # multiple model instances will eventually be stored in a list
                if validated_data_key in self._validated_data \
                        and isinstance(self._validated_data[validated_data_key], list):
                    self._validated_data[validated_data_key].append(matched_instance.pk)
                # only one model instance will be stored
                else:
                    self._validated_data[validated_data_key] = matched_instance.pk

    def _match_by_external_id(self, external_id_to_match, model, validated_data_key):
        """ Matches a model instance in the queryset using the external ID for that instance.

        :param external_id_to_match: Unique external ID used to identify and match model instance.
        :param model: Model for which instance should be identified and matched.
        :param validated_data_key: Key in dictionary of validated data that will hold matched model instance. If
        omitted, method will return matched model instance.
        :return: Nothing if validated_data_key is specified. Otherwise, method returns the matched model instance.
        """
        model_qs = model.objects.all()
        # TODO: Confidentiality filtering
        # TODO: if issubclass(model, Confidentiable):
        # TODO:     user = self.context['request'].user
        # TODO:     model_qs = model_qs.filter_for_confidential_by_user(user=user)
        qs = BulkImport.objects.filter(pk_imported_from=external_id_to_match, table_imported_to=model.get_db_table())
        qs = qs.filter(pk_imported_to__in=model_qs)
        # could not exactly match a single record
        if qs.count() != 1:
            raise ValidationError(
                _(
                    'There is not exactly one {m} with the external ID {n}'.format(
                        m=model.__name__,
                        n=external_id_to_match
                    )
                )
            )
        # matched exactly with a single record
        else:
            # model instance matched by unique external ID
            matched_instance = model_qs.get(pk=qs[0].pk_imported_to)
            # no validated data key was passed in, so just return the matched model instance
            if not validated_data_key:
                return matched_instance
            # validated data key was passed in
            else:
                # multiple model instances will eventually be stored in a list
                if validated_data_key in self._validated_data \
                        and isinstance(self._validated_data[validated_data_key], list):
                    self._validated_data[validated_data_key].append(matched_instance.pk)
                # only one model instance will be stored
                else:
                    self._validated_data[validated_data_key] = matched_instance.pk

    @staticmethod
    def _format_phone_number(unformatted_phone_number):
        """ Formats a phone number so that it includes only digits.

        :param unformatted_phone_number: Unformatted phone number that should be formatted.
        :return: Formatted phone number.
        """
        return ''.join(filter(str.isdigit, str(unformatted_phone_number)))

    @staticmethod
    def __is_whitelisted_url(url):
        """ Checks whether the starting portion of the URL has been whitelisted.

        :param url: Url to check.
        :return: True if starting portion of URL has been whitelisted, false otherwise.
        """
        # convert to lowercase and remove superfluous whitespace
        url_to_verify = url.strip().lower()
        # list of whitelisted URLs
        whitelisted_urls = AbstractConfiguration.whitelisted_django_data_wizard_urls()
        # cycle through whitelisted URLs
        for whitelisted_url in whitelisted_urls:
            if url_to_verify.startswith(whitelisted_url.strip().lower()):
                return True
        return False

    @staticmethod
    def __is_local_access(netloc):
        """ Checks whether the netloc component retrieve by Python's parse.urlparse() method is attempting local access.

        :param netloc: Netloc component to check.
        :return: True if netloc component is attempting local access, false otherwise.
        """
        # convert to lowercase and remove superfluous whitespace
        netloc_to_verify = netloc.strip().lower()
        # cycle through all variations of local access that are not already covered in __is_private_ip() method
        for prefix in ['localhost']:
            if netloc_to_verify.startswith(prefix):
                return True
        return False

    @staticmethod
    def __is_private_ip(ip_address):
        """ Checks whether an IP address is private.

        See: https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

        :param ip_address: IP address to check.
        :return: True if IP address is private, false otherwise.
        """
        is_private = False
        # Build the list of IP prefix for V4 and V6 addresses
        ip_prefix = []
        # Add prefix for loopback addresses
        ip_prefix.append("127.")
        ip_prefix.append("0.")
        # Add IP V4 prefix for private addresses
        # See https://en.wikipedia.org/wiki/Private_network
        ip_prefix.append("10.")
        ip_prefix.append("172.16.")
        ip_prefix.append("172.17.")
        ip_prefix.append("172.18.")
        ip_prefix.append("172.19.")
        ip_prefix.append("172.20.")
        ip_prefix.append("172.21.")
        ip_prefix.append("172.22.")
        ip_prefix.append("172.23.")
        ip_prefix.append("172.24.")
        ip_prefix.append("172.25.")
        ip_prefix.append("172.26.")
        ip_prefix.append("172.27.")
        ip_prefix.append("172.28.")
        ip_prefix.append("172.29.")
        ip_prefix.append("172.30.")
        ip_prefix.append("172.31.")
        ip_prefix.append("192.168.")
        ip_prefix.append("169.254.")
        # Add IP V6 prefix for private addresses
        # See https://en.wikipedia.org/wiki/Unique_local_address
        # See https://en.wikipedia.org/wiki/Private_network
        # See https://simpledns.com/private-ipv6
        ip_prefix.append("fc")
        ip_prefix.append("fd")
        ip_prefix.append("fe")
        ip_prefix.append("ff")
        ip_prefix.append("::1")
        # Verify the provided IP address
        # Remove whitespace characters from the beginning/end of the string
        # and convert it to lower case
        # Lower case is for preventing any IPV6 case bypass using mixed case
        # depending on the source used to get the IP address
        ip_to_verify = ip_address.strip().lower()
        # Perform the check against the list of prefix
        for prefix in ip_prefix:
            if ip_to_verify.startswith(prefix):
                is_private = True
                break
        return is_private

    @staticmethod
    def _get_links_from_string(str_with_links):
        """ Retrieves list of links from a string.

        :param str_with_links: String from which to retrieve links.
        :return: List of links that were found in string.
        """
        # list of links retrieved from the string
        list_of_links = []
        # first split the string by commas
        split_by_commas = str_with_links.split(',')
        # next remove out round parentheses
        for split_by_comma in split_by_commas:
            mapping_table = str.maketrans(dict.fromkeys('()'))
            parentheses_removed_str = split_by_comma.translate(mapping_table)
            # use Django's urlize method to wrap links in <a href="...">
            # see: https://docs.djangoproject.com/en/3.1/ref/templates/builtins/#urlize
            links_wrapped_in_a_href = urlize(text=parentheses_removed_str)
            # use regular expressions to identify <a href="..." wrappers
            regex_links = re_compile(r'<a\shref=(["\'])(.*?)\1')
            # matches will be in form of: [(", link1,), (", link2,), ...]
            list_of_matches = regex_links.findall(links_wrapped_in_a_href)
            # at least some matches were found
            if list_of_matches:
                # for each tuple in the list of matches
                for match_tuple in list_of_matches:
                    # for each tuple element in a tuple match
                    # tuple elements will include single or double quotes, and the value of the HREF attribute
                    list_of_links.extend(
                        [tuple_element for tuple_element in match_tuple if tuple_element not in ['\'', '"']]
                    )
        return list_of_links

    @staticmethod
    def __create_directories_for_path(full_path):
        """ Create all directories defined in a full path, if they do not yet exist.

        Full path will include the file name.

        :param full_path: Full path including the file name for which to create directories.
        :return: Nothing.
        """
        # the directories for the full path may not exist
        if not path_exists(path_dirname(full_path)):
            # try and create all directories required for the full path
            try:
                os_makedirs(path_dirname(full_path))
            # Check for race condition
            except OSError as exc:
                if exc.errno != EEXIST:
                    raise

    @classmethod
    def __download_files_from_links_without_auth(
            cls, links, external_id, root_path, base_path, extension_validator
    ):
        """ Downloads files from a list of links without requiring any authentication.

        :param links: List of links, each containing a file to download.
        :param external_id: ID of containing record for files outside of the Fdp database.
        :param root_path: Root path on server into which files should be downloaded, such as the media root.
        :param base_path: Base path on server that will be appended to root path into which files should be downloaded,
        such as the person photos base path, or the attachments base path.
        :param extension_validator: Method that takes a single value parameter to validate the file type that is
        downloaded.
        :return: List of relative paths on the server for the files that were downloaded.
        """
        timestamp = now()
        # convert external ID to slug, since it will be a folder name
        external_id = slugify(external_id)
        unique_padding = 0
        relative_paths = []
        for i, download_link in enumerate(links, start=0):
            # parse the download link
            parsed_url = urlparse(download_link)
            # check for private ip address
            if cls.__is_private_ip(ip_address=parsed_url.netloc):
                raise ValidationError(_('Private IP addresses are not allowed.'))
            # check for access to local interface
            if cls.__is_local_access(netloc=parsed_url.netloc):
                raise ValidationError(_('Local access is not allowed'))
            # check if in the whitelist
            if not cls.__is_whitelisted_url(url=f'{parsed_url.scheme}://{parsed_url.netloc}/{parsed_url.path}'):
                raise ValidationError(_('URL is not whitelisted, see markdown file for settings documentation'))
            # name of file in download link
            filename = path_basename(parsed_url.path)
            # create an instance of a dummy file, so that the default validator can be used (e.g. to validate its file
            # extension)
            file_to_validate = cls.FileToValidate()
            file_to_validate.name = filename
            # validate file type
            extension_validator(value=file_to_validate)
            # find a unique folder path that does not yet exist
            full_path = None
            relative_path = None
            while full_path is None or path_exists(full_path):
                unique_padding += 1
                # relative path
                relative_path = '{base_path}{id}/{counter}/{yr}/{mon}/{day}/{hr}/{min}/{sec}/{filename}'.format(
                    base_path=base_path,
                    id=external_id,
                    counter=i + unique_padding,
                    yr=timestamp.year,
                    mon=timestamp.month,
                    day=timestamp.day,
                    hr=timestamp.hour,
                    min=timestamp.minute,
                    sec=timestamp.second,
                    filename=filename
                )
                # full path when relative and root paths are joined
                full_path = AbstractFileValidator.join_relative_and_root_paths(
                    relative_path=relative_path,
                    root_path=root_path
                )
            # verify that path is a real path (i.e. no directory traversal takes place)
            # will raise exception if path is not a real path
            AbstractFileValidator.check_path_is_expected(
                relative_path=relative_path,
                root_path=root_path,
                expected_path_prefix=full_path,
                err_msg=_('File path may contain directory traversal'),
                err_cls=ValidationError
            )
            # create any missing directories in the full path
            cls.__create_directories_for_path(full_path=full_path)
            # full path now exists, so download the file
            urlretrieve(url=download_link, filename=full_path)
            # append relative path for file
            relative_paths.append(relative_path)
        return relative_paths

    @classmethod
    def _download_person_photos_from_links_without_auth(cls, links, external_person_id):
        """ Downloads person photos for a person from a list of links without requiring any authentication.

        :param links: List of links, each containing a photo to download.
        :param external_person_id: ID of person record outside of the Fdp database.
        :return: List of relative paths on the server for the person photos that were downloaded.
        """
        return cls.__download_files_from_links_without_auth(
            links=links,
            external_id=external_person_id,
            root_path=settings.MEDIA_ROOT,
            base_path=AbstractUrlValidator.PERSON_PHOTO_BASE_URL,
            extension_validator=AbstractFileValidator.validate_photo_file_extension
        )

    @classmethod
    def _download_attachment_files_from_links_without_auth(cls, links, external_content_id):
        """ Downloads attachment files for a content from a list of links without requiring any authentication.

        :param links: List of links, each containing an attachment file to download.
        :param external_content_id: ID of content record outside of the Fdp database.
        :return: List of relative paths on the server for the attachment files that were downloaded.
        """
        return cls.__download_files_from_links_without_auth(
            links=links,
            external_id=external_content_id,
            root_path=settings.MEDIA_ROOT,
            base_path=AbstractUrlValidator.ATTACHMENT_BASE_URL,
            extension_validator=AbstractFileValidator.validate_attachment_file_extension
        )

    @staticmethod
    def _convert_string_to_date(date_str_to_convert):
        """ Converts a string representing a date, into a date object.

        :param date_str_to_convert: String representing date.
        :return: Date object.
        """
        # date formats to try
        # see: https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes
        date_formats_to_try = ['%Y-%m-%d', '%B %d, %Y', '%m/%d/%Y', '%d-%b-%Y', '%m/%d/%y', '%d-%b-%y']
        i = 0
        # try all the formats, until date is converted
        while i < len(date_formats_to_try):
            i = i + 1
            # format to try
            date_format_to_try = date_formats_to_try[i - 1]
            try:
                # attempt to convert
                converted_date = datetime.strptime(date_str_to_convert, date_format_to_try)
                # year in date format was only represented as YY, e.g. 56 for 1956
                if '%y' in date_format_to_try:
                    # 1956 can be interpreted as 2056
                    if converted_date > datetime.now():
                        converted_date = datetime(
                            year=converted_date.year - 100, month=converted_date.month, day=converted_date.day
                        )
                # converted date
                return converted_date
            except ValueError:
                pass
        raise ValidationError(_('{d} date is in an unrecognized format'.format(d=date_str_to_convert)))

    @staticmethod
    def _add_if_does_not_exist(model, filter_dict, add_dict):
        """ Look for an instance of a model in the model's queryset, and add if it does not exist.

        :param model: Model for which instance should be added if it does not exist.
        :param filter_dict: Dictionary of keyword arguments that can be expanded to filter the queryset to look for the
        instance.
        :param add_dict: Dictionary of keyword arguments that can be expanded to define the instance to create.
        :return: Instance of model that may have been added if it does not exist.
        """
        # record does not yet exist
        if not model.objects.filter(**filter_dict).exists():
            instance = model(**add_dict)
            instance.full_clean()
            instance.save()
        # record matched by using filter dictionary
        else:
            instance = model.objects.get(**filter_dict)
        return instance

    def _validate_date(self, custom_date_field, model_date_field_prefix, model_alt_date_field_prefix=None):
        """ Validates a date field that contains all three date components together, i.e. a complete date.

        If validated, splits field into its individual date components.

        :param custom_date_field: Name of custom field that contains full date. An example may be "start_date".
        :param model_date_field_prefix: Prefix that defines the individual date component fields on the model.
        An example may be "start" for "start_year", "start_month" and "start_day" component fields.
        :param model_alt_date_field_prefix: Prefix that defines an alternative collection of individual date component
        fields on the model. An example may be "end" for "end_year", "end_month", "end_day" component fields. Will be
        ignored if not defined.
        :return: Nothing.
        """
        date_as_str = self.validated_data.pop(custom_date_field, '')
        if date_as_str:
            date_as_date = self._convert_string_to_date(date_str_to_convert=date_as_str)
            # required components (e.g. starting dates or single dates)
            self._validated_data['{p}_year'.format(p=model_date_field_prefix)] = date_as_date.year
            self._validated_data['{p}_month'.format(p=model_date_field_prefix)] = date_as_date.month
            self._validated_data['{p}_day'.format(p=model_date_field_prefix)] = date_as_date.day
            # optional alternative components (e.g. ending dates)
            if model_alt_date_field_prefix:
                self._validated_data['{p}_year'.format(p=model_alt_date_field_prefix)] = date_as_date.year
                self._validated_data['{p}_month'.format(p=model_alt_date_field_prefix)] = date_as_date.month
                self._validated_data['{p}_day'.format(p=model_alt_date_field_prefix)] = date_as_date.day

    def _validate_date_component(self, date_component_field, validator, raise_exception):
        """ Validates an individual date component field.

        Examples may be: "year of start", "year of end", "month of start", etc.

        If validated, places individual date component back into the initial data dictionary for further
        model and field specific validation.

        If validation fails and raise_exception is False, then converts individual date component to the unknown value.

        If validation fails and raise_exception is True, then raises a ValidationError.

        :param date_component_field: Name of field containing individual date component to validate.
        :param validator: Method to call to perform field-specific validation, such as checking if in acceptable range.
        :param raise_exception: True if exception should be raised, when individual date component cannot be cast as
        an integer, false if individual date component should be set to the unknown value in such case.
        :return: Nothing.
        """
        # only validate individual date component if it was specified
        if date_component_field in self.initial_data:
            date_component = self.initial_data[date_component_field]
            # standardize undefined date component
            if not date_component:
                date_component = 0
            # cast as integer
            try:
                int_date_component = int(date_component)
            except ValueError:
                # exception is expected
                if raise_exception:
                    raise ValidationError(_('{v} is not a valid {f}'.format(v=date_component, f=date_component_field)))
                else:
                    int_date_component = 0
            # perform additional validation (e.g. checking if in acceptable range)
            try:
                validator(int_date_component)
            except ValidationError as err:
                # exception is expected
                if raise_exception:
                    raise err
                else:
                    int_date_component = 0
            # replace the individual date component
            self.initial_data[date_component_field] = int_date_component

    def __handle_declared_field_conflict(self, foreign_key_field):
        """ Handles the potential conflict that can occur when fields declared in the serializer class use the name of
        a field that is defined in the model class and so override it.

        In such situation, validation from the field declared in the serializer class is used.

        To address this, declared fields that conflict with model fields are removed before validation.

        :param foreign_key_field: Name of field defined in the model class.
        :return: Nothing.
        """
        # fields declared in the serializer class that override the fields declared in the model class
        # (i.e. if both have the same name)
        # will create a conflict during validation
        # (i.e. validation from the declared field is used)
        # in that case, remove the declared field
        if foreign_key_field in self._declared_fields:
            self._declared_fields.pop(foreign_key_field)

    def _validate_foreign_key_by_external_id(self, foreign_key_field, foreign_key_model, raise_exception):
        """ Validates the value intended for a foreign key field, retrieved through its external ID.

        Examples may be: "person" for an instance of a person title, etc.

        Retrieves model instance that is used as the foreign key value through the corresponding external ID, and if
        validated, places it into the initial data dictionary.

        If validation fails and raise_exception is False, then converts foreign key value to None.

        If validation fails and raise_exception is True, then raises a ValidationError.

        :param foreign_key_field: Name of field containing foreign key to validate.
        :param foreign_key_model: Model whose instances are linked to through the foreign key.
        :param raise_exception: True if exception should be raised when foreign key is not valid, false if foreign key
         should be set to None if not valid.
        :return: Nothing.
        """
        # only validates for foreign key value if it is part of initial data
        if foreign_key_field in self.initial_data:
            self.__handle_declared_field_conflict(foreign_key_field=foreign_key_field)
            # retrieve the external ID
            external_id = self.initial_data.pop(foreign_key_field)
            # standardize undefined value
            if not external_id:
                external_id = None
            if external_id:
                try:
                    # use the bulk import table to retrieve the model instance based on its external ID
                    instance = self._match_by_external_id(
                        external_id_to_match=external_id,
                        model=foreign_key_model,
                        validated_data_key=None
                    )
                except ValidationError as err:
                    # exception is expected
                    if raise_exception:
                        raise err
                    else:
                        instance = None
            else:
                if raise_exception:
                    raise ValidationError('No external ID for {f} was specified'.format(f=foreign_key_field))
                else:
                    instance = None
            self.initial_data[foreign_key_field] = None if not instance else instance.pk

    def _validate_foreign_key_by_name(self, foreign_key_field, foreign_key_model, create_unknown, raise_exception):
        """ Validates the value intended for a foreign key field, retrieved by name and added if it does not exist.

        Examples may be: "type" for an instance of a person grouping, etc.

        Retrieves or adds model instance that is used as the foreign key value via its name, and if validated, places it
        into the initial data dictionary.

        If validation fails and raise_exception is False, then converts foreign key value to None.

        If validation fails and raise_exception is True, then raises a ValidationError.

        :param foreign_key_field: Name of field containing foreign key to validate.
        :param foreign_key_model: Model whose instances are linked to through the foreign key.
        :param create_unknown: True if a model instance with "unknown" as its name should be created if the value of
        the foreign key field is not defined, false if a None value should be assigned to the foreign key field.
        :param raise_exception: True if exception should be raised when foreign key is not valid, false if foreign key
         should be set to an unknown value if not valid.
        :return: Nothing.
        """
        # only validates for foreign key value if it is specified in the initial data
        if foreign_key_field in self.initial_data:
            self.__handle_declared_field_conflict(foreign_key_field=foreign_key_field)
            # retrieve the by name
            by_name = self.initial_data.pop(foreign_key_field)
            # standardize undefined value
            by_name = str(by_name).strip() if by_name else None
            # name by which to reference model instance for foreign key is defined
            if by_name:
                try:
                    # retrieve the model instance based on its name, or add it to the table
                    instance = self._add_if_does_not_exist(
                        model=foreign_key_model,
                        filter_dict={'name__iexact': by_name},
                        add_dict={'name': by_name}
                    )
                except ValidationError as err:
                    # exception is expected
                    if raise_exception:
                        raise err
                    else:
                        instance = None
            # name by which to reference model instance for foreign key is not defined
            else:
                # if exception is expected and no unknown model instance should be created in cases of unknown
                if raise_exception and not create_unknown:
                    raise ValidationError('No "by name" field for {f} was specified'.format(f=foreign_key_field))
                else:
                    instance = None
            # value for foreign key is undefined and an unknown model instance is expected to be created
            if instance is None and create_unknown:
                # retrieve the model instance based on its name, or add it to the table
                unknown_name = 'Unknown'
                instance = self._add_if_does_not_exist(
                    model=foreign_key_model,
                    filter_dict={'name__iexact': unknown_name},
                    add_dict={'name': unknown_name}
                )
            self.initial_data[foreign_key_field] = None if not instance else instance.pk

    def _validate_checkbox_field(self, unvalidated_checkbox_field, validated_checkbox_field):
        """ Validates a checkbox field.

        If validated, places it into the validated checkbox field in the _validated_data dictionary.

        :return: Nothing.
        """
        # text generated by checkbox
        is_checked_str = self.validated_data.pop(unvalidated_checkbox_field, '')
        if is_checked_str and is_checked_str.lower() == 'checked':
            self._validated_data[validated_checkbox_field] = True

    def _validate_decimal(self, decimal_field, validator, raise_exception):
        """ Validates a decimal field.

        Examples may be: "base salary", "regular hours", etc.

        If validated, places decimal back into the initial data dictionary for further model and field specific
        validation.

        If validation fails and raise_exception is False, then converts decimal to the unknown value.

        If validation fails and raise_exception is True, then raises a ValidationError.

        :param decimal_field: Name of field containing decimal value to validate.
        :param validator: Method to call to perform field-specific validation, such as checking if in acceptable range.
        :param raise_exception: True if exception should be raised, when decimal value cannot be cast as
        a decimal, false if decimal value should be set to the unknown value in such case.
        :return: Nothing.
        """
        # only validate decimal field if it was specified
        if decimal_field in self.initial_data:
            untyped_decimal_value = self.initial_data[decimal_field]
            # standardize undefined decimal value
            if not untyped_decimal_value:
                decimal_value = None
            # otherwise decimal value is defined
            else:
                try:
                    # strip out all characters except digits and decimals
                    str_decimal_value = ''.join(filter(lambda x: x.isdigit() or x == '.', str(untyped_decimal_value)))
                    # attempt to convert
                    decimal_value = Decimal(str_decimal_value)
                except (ValueError, InvalidOperation):
                    # exception is expected
                    if raise_exception:
                        raise ValidationError(
                            _('{v} is not a valid {f}'.format(v=untyped_decimal_value, f=decimal_field))
                        )
                    else:
                        decimal_value = None
            if validator is not None and decimal_value is not None:
                # perform additional validation (e.g. checking if in acceptable range)
                try:
                    validator(decimal_value)
                except ValidationError as err:
                    # exception is expected
                    if raise_exception:
                        raise err
                    else:
                        decimal_value = None
            # replace the decimal value
            self.initial_data[decimal_field] = decimal_value

    class FileToValidate:
        """ Dummy class used to simulate a FieldFile object so that validation can be performed on key parts of it
        during import.

        An example is to include the filename as an attribute of an instance of this class, so that the default
        validator methods can be used for person photos and attachments.

        """
        pass


class AbstractModelWithAliasesSerializer(FdpModelSerializer):
    """ Abstract serializer from which all model serializers inherit that also include aliases in the import.

    Examples include the Grouping Air Table serializer and the Person Air Table serializer.

    Attributes:
        :unsplit_aliases (str): Aliases separated by commas.
    """
    unsplit_aliases = CharField(
        required=False,
        allow_null=True,
        label=_('Aliases separated by commas')
    )

    #: Key used to reference in the _validated_data dictionary, the list of aliases to add for a model instance.
    _split_aliases_key = 'split_aliases'

    def is_valid(self, raise_exception=False):
        """ Split the string representing aliases into a list of aliases.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        # validate record
        is_valid = super(AbstractModelWithAliasesSerializer, self).is_valid(raise_exception=raise_exception)
        # record is valid
        if is_valid:
            # split aliases
            unsplit_aliases = self.validated_data.pop('unsplit_aliases', '')
            split_aliases = str(unsplit_aliases).split(',') if unsplit_aliases else []
            self._validated_data[self._split_aliases_key] = [a.strip() for a in split_aliases if a.strip()]
        return is_valid


class AbstractAsOfDateBoundedModelSerializer(FdpModelSerializer):
    """ Abstract serializer from which all model serializers inherit that also include individual date components in
    the import, as well as a boolean as of option.

    Examples include the Person Grouping Air Table serializer and the Person Title Air Table serializer.

    See the inheritable.models.AbstractAsOfDateBounded class.

    Attributes:
        :start_year (str): Date component meant to store starting year.
        :start_month (str): Date component meant to store starting month.
        :start_day (str): Date component meant to store starting day.
        :end_year (str): Date component meant to store ending year.
        :end_month (str): Date component meant to store ending month.
        :end_day (str): Date component meant to store ending day.
        :as_of_checkbox (str): As of checkbox.
    """
    start_year = CharField(
        required=False,
        allow_null=True,
        label=_('Starting year with {u} as unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE))
    )

    start_month = CharField(
        required=False,
        allow_null=True,
        label=_('Starting month with {u} as unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE))
    )

    start_day = CharField(
        required=False,
        allow_null=True,
        label=_('Starting day with {u} as unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE))
    )

    end_year = CharField(
        required=False,
        allow_null=True,
        label=_('Ending year with {u} as unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE))
    )

    end_month = CharField(
        required=False,
        allow_null=True,
        label=_('Ending month with {u} as unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE))
    )

    end_day = CharField(
        required=False,
        allow_null=True,
        label=_('Ending day with {u} as unknown'.format(u=AbstractDateValidator.UNKNOWN_DATE))
    )

    as_of_checkbox = CharField(
        required=False,
        allow_null=True,
        label=_('As of checkbox')
    )

    #: Fields that should be excluded from the list of mappable target serializer fields.
    excluded_fields = FdpModelSerializer.excluded_fields + ['as_of']

    def __validate_as_of_checkbox(self):
        """ Validates the As of checkbox field.

        :return: Nothing.
        """
        self._validate_checkbox_field(unvalidated_checkbox_field='as_of_checkbox', validated_checkbox_field='as_of')

    def is_valid(self, raise_exception=False):
        """ Validate the individual date components.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        # False: convert invalid individual date components to unknowns, and still import record
        # True: don't import record if an individual date component is invalid
        raise_exception = False
        v_dict = {'raise_exception': raise_exception}
        # validate and replace copy of individual start date components in self.initial_data
        self._validate_date_component(
            date_component_field='start_year', validator=AbstractDateValidator.validate_year, **v_dict
        )
        self._validate_date_component(
            date_component_field='start_month', validator=AbstractDateValidator.validate_month, **v_dict
        )
        self._validate_date_component(
            date_component_field='start_day', validator=AbstractDateValidator.validate_day, **v_dict
        )
        # validate and replace copy of individual end date components in self.initial_data
        self._validate_date_component(
            date_component_field='end_year', validator=AbstractDateValidator.validate_year, **v_dict
        )
        self._validate_date_component(
            date_component_field='end_month', validator=AbstractDateValidator.validate_month, **v_dict
        )
        self._validate_date_component(
            date_component_field='end_day', validator=AbstractDateValidator.validate_day, **v_dict
        )
        # perform additional validation such as model specific validation
        is_valid = super(AbstractAsOfDateBoundedModelSerializer, self).is_valid(raise_exception=raise_exception)
        # record is valid
        if is_valid:
            self.__validate_as_of_checkbox()
        return is_valid


class AbstractPersonLinkModelSerializer(FdpModelSerializer):
    """ Abstract serializer from which all model serializers inherit for models that include a foreign key to the
    person model.

    Examples include the Person Grouping Air Table serializer, the Person Title Air Table serializer and the Person
    Payment Air Table serializer.

    Attributes:
        :person (str): Person matched by external person ID.
    """
    person = CharField(
        required=False,
        allow_null=True,
        label=_('Person - match by external person ID')
    )

    #: Fields that should be excluded from the list of mappable target serializer fields.
    excluded_fields = FdpModelSerializer.excluded_fields

    def __validate_person_foreign_key(self):
        """ Validates the value of the person foreign key field through its external ID that provides an indirect link
        to the instance through the Bulk Import table.

        :return: Nothing.
        """
        self._validate_foreign_key_by_external_id(
            foreign_key_field='person',
            foreign_key_model=Person,
            raise_exception=True
        )

    def is_valid(self, raise_exception=False):
        """ Validate the person foreign key field.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        # retrieve a person instance using the external ID found in the Bulk Import table, and place the model
        # instance into the self.initial_data
        self.__validate_person_foreign_key()
        # perform additional validation such as model specific validation
        return super(AbstractPersonLinkModelSerializer, self).is_valid(raise_exception=raise_exception)


class AbstractContentLinkModelSerializer(FdpModelSerializer):
    """ Abstract serializer from which all model serializers inherit for models that include a foreign key to the
    content model.

    Examples include the Content Identifier Air Table serializer and the Content Person Air Table serializer.

    Attributes:
        :content (str): Content matched by external content ID.
    """
    content = CharField(
        required=False,
        allow_null=True,
        label=_('Content - match by external content ID')
    )

    #: Fields that should be excluded from the list of mappable target serializer fields.
    excluded_fields = FdpModelSerializer.excluded_fields

    def __validate_content_foreign_key(self):
        """ Validates the value of the content foreign key field through its external ID that provides an indirect link
        to the instance through the Bulk Import table.

        :return: Nothing.
        """
        self._validate_foreign_key_by_external_id(
            foreign_key_field='content',
            foreign_key_model=Content,
            raise_exception=True
        )

    def is_valid(self, raise_exception=False):
        """ Validate the content foreign key field.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        # retrieve a content instance using the external ID found in the Bulk Import table, and place the model
        # instance into the self.initial_data
        self.__validate_content_foreign_key()
        # perform additional validation such as model specific validation
        return super(AbstractContentLinkModelSerializer, self).is_valid(raise_exception=raise_exception)


class GroupingAirTableSerializer(AbstractModelWithAliasesSerializer):
    """ Serializer for groupings that were defined through the Air Table templates.

    Attributes:
        :belongs_to_grouping_by_external_id (str): Grouping to which record belongs, matched by external grouping ID.
        :reports_to_grouping_by_external_id (str): Grouping to which record reports, matched by external grouping ID.
        :unsplit_counties (str): External county IDs separated by commas.
        :inception_date_mdy (str): Inception date in MONTHY/DAY/YEAR format.
    """
    belongs_to_grouping_by_external_id = CharField(
        required=False,
        allow_null=True,
        label=_('Belongs to grouping - match by external grouping ID')
    )

    reports_to_grouping_by_external_id = CharField(
        required=False,
        allow_null=True,
        label=_('Reports to grouping - match by external grouping ID')
    )

    unsplit_counties = CharField(
        required=False,
        allow_null=True,
        label=_('External county IDs separated by commas')
    )

    inception_date_mdy = CharField(
        required=False,
        allow_null=True,
        label=_('Inception date in MONTH/DAY/YEAR format')
    )

    #: Key used to reference in the _validated_data dictionary, the grouping instance to which record belongs.
    __belongs_to_grouping_instance_id_key = 'belongs_to_grouping_instance'

    #: Key used to reference in the _validated_data dictionary, the grouping instance to which record reports.
    __reports_to_grouping_instance_id_key = 'reports_to_grouping_instance'

    #: Key used to reference in the _validated_data dictionary, the list of counties to add for a grouping.
    __split_counties_key = 'split_counties'

    def __validate_phone_number(self):
        """ Validates the phone number field.

        If validated, places it back into the phone number field.

        :return: Nothing.
        """
        # strip out all invalid characters from the phone number
        phone_number_field = 'phone_number'
        if phone_number_field in self.initial_data:
            self.initial_data[phone_number_field] = self._format_phone_number(
                unformatted_phone_number=self.initial_data[phone_number_field]
            )

    def __validate_belongs_to_grouping(self):
        """ Validates the belongs to grouping field.

        If validated, prepares the corresponding Grouping instance.

        :return: Nothing.
        """
        # parse belongs to grouping matched by external grouping ID
        belongs_grouping_external_id_key = 'belongs_to_grouping_by_external_id'
        belongs_to_grouping_by_external_id = self.validated_data.pop(belongs_grouping_external_id_key, None)
        if belongs_to_grouping_by_external_id:
            self._match_by_external_id(
                external_id_to_match=belongs_to_grouping_by_external_id,
                model=Grouping,
                validated_data_key=self.__belongs_to_grouping_instance_id_key
            )

    def __validate_report_to_grouping(self):
        """ Validates the reports to grouping field.

        If validated, prepares the corresponding Grouping instance.

        :return: Nothing.
        """
        # parse reports to grouping matched by external grouping ID
        reports_grouping_external_id_key = 'reports_to_grouping_by_external_id'
        reports_to_grouping_by_external_id = self.validated_data.pop(reports_grouping_external_id_key, None)
        if reports_to_grouping_by_external_id:
            self._match_by_external_id(
                external_id_to_match=reports_to_grouping_by_external_id,
                model=Grouping,
                validated_data_key=self.__reports_to_grouping_instance_id_key
            )

    def __validate_unsplit_counties(self):
        """ Validates the unsplit counties field.

        If validated, prepares the corresponding County instances.

        :return: Nothing.
        """
        # split counties
        unsplit_counties_key = 'unsplit_counties'
        unsplit_counties = self.validated_data.pop(unsplit_counties_key, '')
        split_counties = str(unsplit_counties).split(',') if unsplit_counties else []
        self._validated_data[self.__split_counties_key] = []
        if split_counties:
            for county_external_id in split_counties:
                stripped_county_external_id = county_external_id.strip()
                if stripped_county_external_id:
                    self._match_by_external_id(
                        external_id_to_match=stripped_county_external_id,
                        model=County,
                        validated_data_key=self.__split_counties_key
                    )

    def __validate_inception_date(self):
        """ Validates the inception date field.

        If validated, places it back into the inception date field.

        :return: Nothing.
        """
        # inception date in M/D/Y format
        inception_date_mdy_str = self.validated_data.pop('inception_date_mdy', '')
        if inception_date_mdy_str:
            self._validated_data['inception_date'] = datetime.strptime(inception_date_mdy_str, '%m/%d/%Y')

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        self.__validate_phone_number()
        # convert null address to blank
        self._convert_null_to_blank(field_name='address')
        # convert null email to blank
        self._convert_null_to_blank(field_name='email')
        # validate record
        is_valid = super(GroupingAirTableSerializer, self).is_valid(raise_exception=raise_exception)
        # record is valid
        if is_valid:
            self.__validate_belongs_to_grouping()
            self.__validate_report_to_grouping()
            self.__validate_unsplit_counties()
            self.__validate_inception_date()
        return is_valid

    def create(self, validated_data):
        """ Creates a new grouping and its related data.

        :param validated_data: Dictionary of validated data used to creating new grouping and its related data.
        :return: Instance of newly created grouping.
        """
        # validated data before values are popped from it
        self.original_validated_data = validated_data.copy()
        # pop custom fields from validated data
        split_aliases = validated_data.pop(self._split_aliases_key, [])
        split_county_ids = validated_data.pop(self.__split_counties_key, [])
        belongs_to_grouping_instance_id = validated_data.pop(self.__belongs_to_grouping_instance_id_key, None)
        reports_to_grouping_instance_id = validated_data.pop(self.__reports_to_grouping_instance_id_key, None)
        # instance has been added into bulk import table
        instance = super(GroupingAirTableSerializer, self).create(validated_data=validated_data)
        # create grouping aliases
        for alias in split_aliases:
            grouping_alias = GroupingAlias(grouping=instance, name=alias)
            grouping_alias.full_clean()
            grouping_alias.save()
        # optionally link counties
        for county_id in split_county_ids:
            county = County.objects.get(pk=county_id)
            instance.counties.add(county)
        # optionally link to a "belongs to" grouping
        if belongs_to_grouping_instance_id:
            instance.belongs_to_grouping_id = belongs_to_grouping_instance_id
            instance.full_clean()
            instance.save()
        # optionally create "reports to" relationship with other grouping
        if reports_to_grouping_instance_id:
            reports_to_txt = 'reports to'
            grouping_relationship_type = self._add_if_does_not_exist(
                model=GroupingRelationshipType,
                filter_dict={'name__iexact': reports_to_txt},
                add_dict={'name': reports_to_txt, 'hierarchy': GroupingRelationshipType.RIGHT_IS_SUPERIOR}
            )
            grouping_relationship = GroupingRelationship(
                subject_grouping=instance,
                type=grouping_relationship_type,
                object_grouping=Grouping.objects.get(pk=reports_to_grouping_instance_id)
            )
            grouping_relationship.full_clean()
            grouping_relationship.save()
        return instance

    class Meta:
        model = Grouping
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = FdpModelSerializer.excluded_fields + [
            'belongs_to_grouping', 'cease_date', 'counties', 'description', 'inception_date', 'is_inactive'
        ]


class PersonAirTableSerializer(AbstractModelWithAliasesSerializer):
    """ Serializer for persons that were defined through the Air Table templates.

    Attributes:
        :exact_birth_date (str): Exact birth date.
        :law_enforcement_checkbox (str): Law enforcement checkbox.
        :phone_number (str): Phone number for person contact.
        :email_number (str): Email for person contact.
        :identifier_type (str): Type for person identifier, matched by unique name or added if it does not exist.
        :identifier (str): Identifier for person identifier.
        :person_title (str): Title which person holds, matched by unique title name or added if it does not exist.
        :unsplit_traits (str): Trait names separated by commas.
        :unsplit_groupings (str): External grouping IDs separated by commas.
        :unsplit_person_photos (str): Person photo links separated by commas, from which to download without
        authentication.
    """
    exact_birth_date = CharField(
        required=False,
        allow_null=True,
        label=_('Exact birth date')
    )

    law_enforcement_checkbox = CharField(
        required=False,
        allow_null=True,
        label=_('Law enforcement checkbox')
    )

    phone_number = CharField(
        required=False,
        allow_null=True,
        label=_('Phone number for person contact')
    )

    email = EmailField(
        required=False,
        allow_null=True,
        label=_('Email for person contact')
    )

    identifier_type = CharField(
        required=False,
        allow_null=True,
        label=_('Type for person identifier - match by unique name, or add if it does not exist')
    )

    identifier = CharField(
        required=False,
        allow_null=True,
        label=_('Identifier for person identifier')
    )

    person_title = CharField(
        required=False,
        allow_null=True,
        label=_('Title held by person - match by unique title name, or add if does not exist')
    )

    unsplit_traits = CharField(
        required=False,
        allow_null=True,
        label=_('Trait names separated by commas - add if does not exist')
    )

    unsplit_groupings = CharField(
        required=False,
        allow_null=True,
        label=_('External grouping IDs separated by commas')
    )

    unsplit_person_photos = CharField(
        required=False,
        allow_null=True,
        label=_('Person photo links separated by commas, from which to download without authentication')
    )

    #: Key used to reference in the _validated_data dictionary, the phone number for the person contact.
    __phone_number_key = 'phone_number_formatted'

    #: Key used to reference in the _validated_data dictionary, the email for the person contact.
    __email_key = 'email_formatted'

    #: Key used to reference in the _validated_data dictionary, the type for the person identifier.
    __identifier_type_key = 'person_identifier_type'

    #: Key used to reference in the _validated_data dictionary, the identifier for the person identifier.
    __identifier_key = 'person_identifier'

    #: Key used to reference in the _validated_data dictionary, name of the title instance to which person is linked.
    __title_instance_name_key = 'title_instance'

    #: Key used to reference in the _validated_data dictionary, the list of traits to add for a person.
    __split_traits_key = 'split_traits'

    #: Key used to reference in the _validated_data dictionary, the list of groupings to add for a person.
    __split_groupings_key = 'split_groupings'

    #: Key used to reference in the _validated_data dictionary, the list of person photos to add for a person.
    __split_person_photos_key = 'split_person_photos'

    def __validate_exact_birth_date(self):
        """ Validates the exact birth date field.

        If validated, places it into the birth date range start and end fields.

        :return: Nothing.
        """
        # exact birth date in dd-mmm-yy format
        exact_birth_date_str = self.validated_data.pop('exact_birth_date', None)
        if exact_birth_date_str:
            exact_birth_date = self._convert_string_to_date(date_str_to_convert=exact_birth_date_str)
            self._validated_data['birth_date_range_start'] = exact_birth_date
            self._validated_data['birth_date_range_end'] = exact_birth_date

    def __validate_is_law_enforcement_checkbox(self):
        """ Validates the Is Law Enforcement checkbox field.

        :return: Nothing.
        """
        self._validate_checkbox_field(
            unvalidated_checkbox_field='law_enforcement_checkbox',
            validated_checkbox_field='is_law_enforcement'
        )

    def __validate_phone_number(self):
        """ Validates the phone number field.

        If validated, prepares it for the corresponding Person Contact instance.

        :return: Nothing.
        """
        # phone number
        unformatted_phone_number = self.validated_data.pop('phone_number', '')
        if unformatted_phone_number:
            self._validated_data[self.__phone_number_key] = self._format_phone_number(
                unformatted_phone_number=unformatted_phone_number
            )

    def __validate_email(self):
        """ Validates the email field.

        If validated, prepares it for the corresponding Person Contact instance.

        :return: Nothing.
        """
        # email
        unformatted_email = self.validated_data.pop('email', '')
        if unformatted_email:
            self._validated_data[self.__email_key] = unformatted_email.strip()

    def __validate_identifier_and_identifier_type(self):
        """ Validates the identifier and identifier type fields.

        If validated, prepares them for the corresponding Person Identifier instance.

        :return: Nothing.
        """
        # type and identifier for identifier
        identifier_type = self.validated_data.pop('identifier_type', '')
        identifier = self.validated_data.pop('identifier', '')
        if identifier_type or identifier:
            if not identifier_type:
                raise ValidationError(_('Type missing for person identifier {i}'.format(i=identifier)))
            if not identifier:
                raise ValidationError(
                    _('Identifier missing for person identifier type {t}'.format(t=identifier_type))
                )
            self._validated_data[self.__identifier_type_key] = str(identifier_type).strip()
            self._validated_data[self.__identifier_key] = str(identifier).strip()

    def __validate_title(self):
        """ Validates the title field.

        If validated, prepares it for the corresponding Person Title instance.

        :return: Nothing.
        """
        # parse title to which person is linked, matched by unique title name, add if it does not exist
        person_title_key = 'person_title'
        person_title = self.validated_data.pop(person_title_key, None)
        if person_title:
            self._validated_data[self.__title_instance_name_key] = str(person_title).strip()

    def __validate_traits(self):
        """ Validates the traits field.

        If validated, prepares them for the corresponding many-to-many traits relationships.

        :return: Nothing.
        """
        # split traits
        unsplit_traits_key = 'unsplit_traits'
        unsplit_traits = self.validated_data.pop(unsplit_traits_key, '')
        split_traits = str(unsplit_traits).split(',') if unsplit_traits else []
        self._validated_data[self.__split_traits_key] = []
        if split_traits:
            for trait_name in split_traits:
                stripped_trait_name = trait_name.strip()
                if stripped_trait_name:
                    self._validated_data[self.__split_traits_key].append(stripped_trait_name)

    def __validate_groupings(self):
        """ Validates the groupings field.

        If validated, prepares them for the corresponding Person Grouping instances.

        :return: Nothing.
        """
        # split groupings
        unsplit_groupings_key = 'unsplit_groupings'
        unsplit_groupings = self.validated_data.pop(unsplit_groupings_key, '')
        split_groupings = str(unsplit_groupings).split(',') if unsplit_groupings else []
        self._validated_data[self.__split_groupings_key] = []
        if split_groupings:
            for grouping_external_id in split_groupings:
                stripped_grouping_external_id = grouping_external_id.strip()
                if stripped_grouping_external_id:
                    self._match_by_external_id(
                        external_id_to_match=stripped_grouping_external_id,
                        model=Grouping,
                        validated_data_key=self.__split_groupings_key
                    )

    def __validate_person_photos(self):
        """ Validates the person photos field.

        If validated, prepares them for the corresponding Person Photo instances.

        :return: Nothing.
        """
        # split person photos
        unsplit_person_photos_key = 'unsplit_person_photos'
        unsplit_person_photos = self.validated_data.pop(unsplit_person_photos_key, '')
        if unsplit_person_photos:
            # retrieve list of links from a string
            person_photo_links = self._get_links_from_string(str_with_links=unsplit_person_photos)
            # some person photo links exist for this record
            if person_photo_links:
                undefined = 'undefined'
                # external id
                external_person_id = self.validated_data.get('external_id', undefined)
                # download the photos from links without authentication
                person_photo_paths = self._download_person_photos_from_links_without_auth(
                    links=person_photo_links,
                    external_person_id=undefined if not external_person_id else external_person_id
                )
                if person_photo_paths:
                    self._validated_data[self.__split_person_photos_key] = person_photo_paths

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        name = self.initial_data.get('name', None)
        if not(name and str(name).strip()):
            self.initial_data['name'] = str(_('Unnamed'))
        # validate record
        is_valid = super(PersonAirTableSerializer, self).is_valid(raise_exception=raise_exception)
        # record is valid
        if is_valid:
            self.__validate_exact_birth_date()
            self.__validate_is_law_enforcement_checkbox()
            self.__validate_phone_number()
            self.__validate_email()
            self.__validate_identifier_and_identifier_type()
            self.__validate_title()
            self.__validate_traits()
            self.__validate_groupings()
            self.__validate_person_photos()
        return is_valid

    def create(self, validated_data):
        """ Creates a new person and its related data.

        :param validated_data: Dictionary of validated data used to creating new person and its related data.
        :return: Instance of newly created person.
        """
        # validated data before values are popped from it
        self.original_validated_data = validated_data.copy()
        # pop custom fields from validated data
        split_aliases = validated_data.pop(self._split_aliases_key, [])
        phone_number = validated_data.pop(self.__phone_number_key, '')
        email = validated_data.pop(self.__email_key, '')
        identifier_type = validated_data.pop(self.__identifier_type_key, '')
        identifier = validated_data.pop(self.__identifier_key, '')
        title_name = validated_data.pop(self.__title_instance_name_key, '')
        split_traits = validated_data.pop(self.__split_traits_key, [])
        split_grouping_ids = validated_data.pop(self.__split_groupings_key, [])
        split_person_photo_paths = validated_data.pop(self.__split_person_photos_key, [])
        # instance has been added into bulk import table
        instance = super(PersonAirTableSerializer, self).create(validated_data=validated_data)
        # optionally create person aliases
        for alias in split_aliases:
            person_alias = PersonAlias(person=instance, name=alias)
            person_alias.full_clean()
            person_alias.save()
        # optionally create person contact
        if phone_number or email:
            person_contact = PersonContact(
                person=instance,
                phone_number=phone_number,
                email=email,
                is_current=True
            )
            person_contact.full_clean()
            person_contact.save()
        # optionally create person identifier
        if identifier and identifier_type:
            person_identifier_type = self._add_if_does_not_exist(
                model=PersonIdentifierType,
                filter_dict={'name__iexact': identifier_type},
                add_dict={'name': identifier_type}
            )
            person_identifier = PersonIdentifier(
                identifier=identifier,
                person_identifier_type=person_identifier_type,
                person=instance
            )
            person_identifier.full_clean()
            person_identifier.save()
        # optionally create person title
        if title_name:
            title = self._add_if_does_not_exist(
                model=Title,
                filter_dict={'name__iexact': title_name},
                add_dict={'name': title_name}
            )
            person_title = PersonTitle(person=instance, title=title)
            person_title.full_clean()
            person_title.save()
        # optionally link traits
        for trait_name in split_traits:
            trait = self._add_if_does_not_exist(
                model=Trait,
                filter_dict={'name__iexact': trait_name},
                add_dict={'name': trait_name}
            )
            instance.traits.add(trait)
        # optionally create person groupings
        for grouping_id in split_grouping_ids:
            grouping = Grouping.objects.get(pk=grouping_id)
            person_grouping = PersonGrouping(person=instance, grouping=grouping, is_inactive=False)
            person_grouping.full_clean()
            person_grouping.save()
        # optionally create person photos
        for person_photo_path in split_person_photo_paths:
            person_photo = PersonPhoto(person=instance, photo=person_photo_path)
            person_photo.full_clean()
            person_photo.save()
        return instance

    class Meta:
        model = Person
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = FdpModelSerializer.excluded_fields + FdpModelSerializer.confidentiable_excluded_fields + [
            'birth_date_range_start', 'birth_date_range_end', 'description', 'is_law_enforcement', 'traits'
        ]


class IncidentAirTableSerializer(FdpModelSerializer):
    """ Serializer for incidents that were defined through the Air Table templates.

    Attributes:
        :incident_date (str): Incident date.
        :location_by_name (str): Incident location matched by unique name or added if it does not exist.
        :encounter_reason (str): Encounter reason matched by unique name or added if it does not exist.
        :unsplit_incident_tags (str): Incident tag names separated by commas, add if any do not exist.
        :unsplit_persons (str): External person IDs separated by commas.

    """
    incident_date = CharField(
        required=False,
        allow_null=True,
        label=_('Incident date')
    )

    location_by_name = CharField(
        required=False,
        allow_null=True,
        label=_('Incident location - match by unique name, or add if it does not exist')
    )

    encounter_reason = CharField(
        required=False,
        allow_null=True,
        label=_('Encounter reason - match by unique name, or add if it does not exist')
    )

    unsplit_incident_tags = CharField(
        required=False,
        allow_null=True,
        label=_('Incident tag names separated by commas - add if it does not exist')
    )

    unsplit_persons = CharField(
        required=False,
        allow_null=True,
        label=_('External person IDs separated by commas')
    )

    #: Key used to reference in the _validated_data dictionary, name of location instance to which incident is linked.
    __location_instance_name_key = 'location_instance'

    #: Key used to reference in the _validated_data dictionary, the list of tags to add for a incident.
    __split_incident_tags_key = 'split_incident_tags'

    #: Key used to reference in the _validated_data dictionary, the list of persons to link to a incident.
    __split_persons_key = 'split_persons'

    def __validate_incident_date(self):
        """ Validates the incident date field.

        If validated, splits field into its individual date components.

        :return: Nothing.
        """
        self._validate_date(
            custom_date_field='incident_date',
            model_date_field_prefix='start',
            model_alt_date_field_prefix='end'
        )

    def __validate_location(self):
        """ Validates the location field.

        If validated, prepares it for the corresponding Location instance.

        :return: Nothing.
        """
        # location to which incident is linked, matched by unique name, added if it does not exist
        location_by_name_key = 'location_by_name'
        location_by_name = self.validated_data.pop(location_by_name_key, None)
        if location_by_name:
            self._validated_data[self.__location_instance_name_key] = str(location_by_name).strip()

    def __validate_incident_tags(self):
        """ Validates the incident tags field.

        If validated, prepares it for the corresponding Incident Tag instances.

        :return: Nothing.
        """
        # split incident tags
        unsplit_incident_tags_key = 'unsplit_incident_tags'
        unsplit_incident_tags = self.validated_data.pop(unsplit_incident_tags_key, '')
        split_incident_tags = str(unsplit_incident_tags).split(',') if unsplit_incident_tags else []
        self._validated_data[self.__split_incident_tags_key] = []
        if split_incident_tags:
            for incident_tag_name in split_incident_tags:
                stripped_incident_tag_name = incident_tag_name.strip()
                if stripped_incident_tag_name:
                    self._validated_data[self.__split_incident_tags_key].append(stripped_incident_tag_name)

    def __validate_persons(self):
        """ Validate the persons field.

        If validated, prepares it for the corresponding Person instances.

        :return: Nothing.
        """
        # split persons
        unsplit_persons_key = 'unsplit_persons'
        unsplit_persons = self.validated_data.pop(unsplit_persons_key, '')
        split_persons = str(unsplit_persons).split(',') if unsplit_persons else []
        self._validated_data[self.__split_persons_key] = []
        if split_persons:
            for person_external_id in split_persons:
                stripped_person_external_id = person_external_id.strip()
                if stripped_person_external_id:
                    self._match_by_external_id(
                        external_id_to_match=stripped_person_external_id,
                        model=Person,
                        validated_data_key=self.__split_persons_key
                    )

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        self._convert_null_to_blank(field_name='description')
        # validate the given the encounter reason by its name, and add it as a model instance if it does not already
        # exist, and then place the value into self.initial_data
        self._validate_foreign_key_by_name(
            foreign_key_field='encounter_reason',
            foreign_key_model=EncounterReason,
            create_unknown=False,
            raise_exception=False
        )
        # validate record
        is_valid = super(IncidentAirTableSerializer, self).is_valid(raise_exception=raise_exception)
        # record is valid
        if is_valid:
            self.__validate_incident_date()
            self.__validate_location()
            self.__validate_incident_tags()
            self.__validate_persons()
        return is_valid

    def create(self, validated_data):
        """ Creates a new incident and its related data.

        :param validated_data: Dictionary of validated data used to creating new incident and its related data.
        :return: Instance of newly created incident.
        """
        # validated data before values are popped from it
        self.original_validated_data = validated_data.copy()
        # pop custom fields from validated data
        location_name = validated_data.pop(self.__location_instance_name_key, '')
        split_incident_tags = validated_data.pop(self.__split_incident_tags_key, [])
        split_person_ids = validated_data.pop(self.__split_persons_key, [])
        # instance has been added into bulk import table
        instance = super(IncidentAirTableSerializer, self).create(validated_data=validated_data)
        # optionally link location
        if location_name:
            unknown = 'Unknown'
            state = self._add_if_does_not_exist(
                model=State,
                filter_dict={'name__iexact': 'unknown'},
                add_dict={'name': unknown}
            )
            county = self._add_if_does_not_exist(
                model=County,
                filter_dict={'name__iexact': unknown, 'state': state},
                add_dict={'name': unknown, 'state': state}
            )
            location = self._add_if_does_not_exist(
                model=Location,
                filter_dict={'address__iexact': location_name, 'county': county},
                add_dict={'address': location_name, 'county': county}
            )
            instance.location = location
            instance.full_clean()
            instance.save()
        # optionally link incident tags
        for incident_tag_name in split_incident_tags:
            incident_tag = self._add_if_does_not_exist(
                model=IncidentTag,
                filter_dict={'name__iexact': incident_tag_name},
                add_dict={'name': incident_tag_name}
            )
            instance.tags.add(incident_tag)
        # optionally link persons to incidents
        if split_person_ids:
            # TODO: Confidentiality filtering
            # TODO: accessible_persons = Person.objects.all().filter_for_confidential_by_user(user=user)
            accessible_persons = Person.objects.all()
            for person_id in split_person_ids:
                person_incident = PersonIncident(incident=instance, person=accessible_persons.get(pk=person_id))
                person_incident.full_clean()
                person_incident.save()
        return instance

    class Meta:
        model = Incident
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = FdpModelSerializer.excluded_fields + FdpModelSerializer.confidentiable_excluded_fields \
            + FdpModelSerializer.abstract_exact_date_bounded_excluded_fields \
            + ['location', 'location_type', 'tags']


class ContentAirTableSerializer(FdpModelSerializer):
    """ Serializer for content that were defined through the Air Table templates.

    Attributes:
        :identifier_type (str): Type for content identifier, add if it does not exist.
        :identifier (str): Identifier for content identifier.
        :case_opened_date (str): Case opened date.
        :case_closed_date (str): Case closed date.
        :outcome_by_name (str): Case outcome matched by unique name, added if it does not exist.
        :type (str): Content type matched by unique name, added if it does not exist.
        :unsplit_incidents (str): External incident IDs separated by commas.
        :unsplit_persons (str): External person IDs separated by commas.
        :unsplit_attachment_files (str): Attachment file links separated by commas, from which to download without
        authentication.

    """
    identifier_type = CharField(
        required=False,
        allow_null=True,
        label=_('Type for content identifier, add if it does not exist')
    )

    identifier = CharField(
        required=False,
        allow_null=True,
        label=_('Identifier for content identifier')
    )

    case_opened_date = CharField(
        required=False,
        allow_null=True,
        label=_('Case opened date')
    )

    case_closed_date = CharField(
        required=False,
        allow_null=True,
        label=_('Case closed date')
    )

    outcome_by_name = CharField(
        required=False,
        allow_null=True,
        label=_('Case outcome - match by unique name, add if it does not exist')
    )

    type = CharField(
        required=False,
        allow_null=True,
        label=_('Content type - match by unique name, add if it does not exist')
    )

    unsplit_incidents = CharField(
        required=False,
        allow_null=True,
        label=_('External incident IDs separated by commas')
    )

    unsplit_persons = CharField(
        required=False,
        allow_null=True,
        label=_('External person IDs separated by commas')
    )

    unsplit_attachment_files = CharField(
        required=False,
        allow_null=True,
        label=_('Attachment file links separated by commas, from which to download without authentication')
    )

    #: Key used to reference in the _validated_data dictionary, case opened date for content.
    __case_opened_date_key = 'case_opened'

    #: Key used to reference in the _validated_data dictionary, case closed date for content.
    __case_closed_date_key = 'case_closed'

    #: Key used to reference in the _validated_data dictionary, the type for the content identifier.
    __identifier_type_key = 'content_identifier_type'

    #: Key used to reference in the _validated_data dictionary, the identifier for the content identifier.
    __identifier_key = 'content_identifier'

    #: Key used to reference in the _validated_data dictionary, name of case outcome inst. to which content is linked.
    __outcome_key = 'outcome'

    #: Key used to reference in the _validated_data dictionary, the list of incidents to add for a content.
    __split_incidents_key = 'split_incidents'

    #: Key used to reference in the _validated_data dictionary, the list of persons to link to a content.
    __split_persons_key = 'split_persons'

    #: Key used to reference in the _validated_data dictionary, the list of attachment files to add for a content.
    __split_attachment_files_key = 'split_attachment_files'

    def __validate_identifier_and_identifier_type(self):
        """ Validates the identifier and identifier type fields.

        If validated, prepares them for the corresponding Content Identifier instance.

        :return: Nothing.
        """
        # type and identifier for identifier
        identifier_type = self.validated_data.pop('identifier_type', '')
        identifier = self.validated_data.pop('identifier', '')
        if identifier_type or identifier:
            if not identifier_type:
                raise ValidationError(_('Type missing for content identifier {i}'.format(i=identifier)))
            if not identifier:
                raise ValidationError(
                    _('Identifier missing for content identifier type {t}'.format(t=identifier_type))
                )
            self._validated_data[self.__identifier_type_key] = str(identifier_type).strip()
            self._validated_data[self.__identifier_key] = str(identifier).strip()

    def __validate_case_opened_date(self):
        """ Validates the case opened date field.

        If validated, places it into the case opened date field.

        :return: Nothing.
        """
        # case opened date
        case_opened_date_str = self.validated_data.pop('case_opened_date', '')
        if case_opened_date_str:
            self._validated_data[self.__case_opened_date_key] = self._convert_string_to_date(
                date_str_to_convert=case_opened_date_str
            )

    def __validate_case_closed_date(self):
        """ Validates the case closed date field.

        If validated, places it into the case closed date field.

        :return: Nothing.
        """
        # case closed date
        case_closed_date_str = self.validated_data.pop('case_closed_date', '')
        if case_closed_date_str:
            self._validated_data[self.__case_closed_date_key] = self._convert_string_to_date(
                date_str_to_convert=case_closed_date_str
            )

    def __validate_case_outcome(self):
        """ Validates the case outcome field.

        If validated, prepares them for the corresponding Content Case Outcome instance.

        :return: Nothing.
        """
        # parse case outcome by unique name
        outcome_by_name_key = 'outcome_by_name'
        outcome_by_name = self.validated_data.pop(outcome_by_name_key, None)
        if outcome_by_name:
            self._validated_data[self.__outcome_key] = outcome_by_name

    def __validate_incidents(self):
        """ Validates the incidents field.

        If validated, prepares the corresponding Incident instances.

        :return: Nothing.
        """
        # split incidents
        unsplit_incidents_key = 'unsplit_incidents'
        unsplit_incidents = self.validated_data.pop(unsplit_incidents_key, '')
        split_incidents = str(unsplit_incidents).split(',') if unsplit_incidents else []
        self._validated_data[self.__split_incidents_key] = []
        if split_incidents:
            for external_incident_id in split_incidents:
                stripped_external_incident_id = external_incident_id.strip()
                if stripped_external_incident_id:
                    self._match_by_external_id(
                        external_id_to_match=stripped_external_incident_id,
                        model=Incident,
                        validated_data_key=self.__split_incidents_key
                    )

    def __validate_persons(self):
        """ Validates the persons field.

        If validated, prepares the corresponding Content Person instances.

        :return: Nothing.
        """
        # split persons
        unsplit_persons_key = 'unsplit_persons'
        unsplit_persons = self.validated_data.pop(unsplit_persons_key, '')
        split_persons = str(unsplit_persons).split(',') if unsplit_persons else []
        self._validated_data[self.__split_persons_key] = []
        if split_persons:
            for person_external_id in split_persons:
                stripped_person_external_id = person_external_id.strip()
                if stripped_person_external_id:
                    self._match_by_external_id(
                        external_id_to_match=stripped_person_external_id,
                        model=Person,
                        validated_data_key=self.__split_persons_key
                    )

    def __validate_attachment_files(self):
        """ Validates the attachment files field.

        If validated, prepares them for the corresponding Attachment instances.

        :return: Nothing.
        """
        # split attachment files
        unsplit_attachment_files_key = 'unsplit_attachment_files'
        unsplit_attachment_files = self.validated_data.pop(unsplit_attachment_files_key, '')
        if unsplit_attachment_files:
            # retrieve list of links from a string
            attachment_file_links = self._get_links_from_string(str_with_links=unsplit_attachment_files)
            # some attachment file links exist for this record
            if attachment_file_links:
                undefined = 'undefined'
                # external id
                external_content_id = self.validated_data.get('external_id', undefined)
                # download the files from links without authentication
                attachment_file_paths = self._download_attachment_files_from_links_without_auth(
                    links=attachment_file_links,
                    external_content_id=undefined if not external_content_id else external_content_id
                )
                if attachment_file_paths:
                    self._validated_data[self.__split_attachment_files_key] = attachment_file_paths

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        self._convert_null_to_blank(field_name='description')
        self._convert_null_to_blank(field_name='name')
        # validate the given the content type by its name, and add it as a model instance if it does not already
        # exist, and then place the value into self.initial_data
        self._validate_foreign_key_by_name(
            foreign_key_field='type',
            foreign_key_model=ContentType,
            create_unknown=False,
            raise_exception=False
        )
        # validate record
        is_valid = super(ContentAirTableSerializer, self).is_valid(raise_exception=raise_exception)
        # record is valid
        if is_valid:
            self.__validate_identifier_and_identifier_type()
            self.__validate_case_opened_date()
            self.__validate_case_closed_date()
            self.__validate_case_outcome()
            self.__validate_incidents()
            self.__validate_persons()
            self.__validate_attachment_files()
        return is_valid

    def create(self, validated_data):
        """ Creates a new content and its related data.

        :param validated_data: Dictionary of validated data used to creating new content and its related data.
        :return: Instance of newly created content.
        """
        # validated data before values are popped from it
        self.original_validated_data = validated_data.copy()
        # pop custom fields from validated data
        case_opened_date = validated_data.pop(self.__case_opened_date_key, None)
        case_closed_date = validated_data.pop(self.__case_closed_date_key, None)
        identifier_type = validated_data.pop(self.__identifier_type_key, None)
        identifier = validated_data.pop(self.__identifier_key, '')
        outcome = validated_data.pop(self.__outcome_key, '')
        split_incident_ids = validated_data.pop(self.__split_incidents_key, [])
        split_person_ids = validated_data.pop(self.__split_persons_key, [])
        split_attachment_file_paths = validated_data.pop(self.__split_attachment_files_key, [])
        # instance has been added into bulk import table
        instance = super(ContentAirTableSerializer, self).create(validated_data=validated_data)
        # optionally create content identifier
        if identifier and identifier_type:
            content_identifier_type = self._add_if_does_not_exist(
                model=ContentIdentifierType,
                filter_dict={'name__iexact': identifier_type},
                add_dict={'name': identifier_type}
            )
            content_identifier = ContentIdentifier(
                identifier=identifier,
                content_identifier_type=content_identifier_type,
                content=instance
            )
            content_identifier.full_clean()
            content_identifier.save()
        # optionally create content case
        if case_opened_date or case_closed_date or outcome:
            content_case = ContentCase(content=instance)
            if outcome:
                content_case.outcome = self._add_if_does_not_exist(
                    model=ContentCaseOutcome,
                    filter_dict={'name__iexact': outcome},
                    add_dict={'name': outcome}
                )
            if case_opened_date:
                content_case.start_year = case_opened_date.year
                content_case.start_month = case_opened_date.month
                content_case.start_day = case_opened_date.day
            if case_closed_date:
                content_case.end_year = case_closed_date.year
                content_case.end_month = case_closed_date.month
                content_case.end_day = case_closed_date.day
            content_case.full_clean()
            content_case.save()
        # optionally link incidents to content
        if split_incident_ids:
            # TODO: Confidentiality filtering
            # TODO: accessible_incidents = Incident.objects.all().filter_for_confidential_by_user(user=user)
            accessible_incidents = Incident.objects.all()
            for incident_id in split_incident_ids:
                incident = accessible_incidents.get(pk=incident_id)
                instance.incidents.add(incident)
        # optionally link persons to content
        if split_person_ids:
            # TODO: Confidentiality filtering
            # TODO: accessible_persons = Person.objects.all().filter_for_confidential_by_user(user=user)
            accessible_persons = Person.objects.all()
            for person_id in split_person_ids:
                content_person = ContentPerson(content=instance, person=accessible_persons.get(pk=person_id))
                content_person.full_clean()
                content_person.save()
        # optionally create attachments
        for attachment_file_path in split_attachment_file_paths:
            attachment = Attachment(file=attachment_file_path, name=path_basename(attachment_file_path))
            attachment.full_clean()
            attachment.save()
            instance.attachments.add(attachment)
        return instance

    class Meta:
        model = Content
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = FdpModelSerializer.excluded_fields + FdpModelSerializer.confidentiable_excluded_fields + [
            'attachments', 'incidents', 'link', 'publication_date'
        ]


class AllegationAirTableSerializer(FdpModelSerializer):
    """ Serializer for content-person-allegations that were defined through the Air Table templates.

    Attributes:
        :content_external_id (str): Content external ID to which allegation is linked.
        :person_external_id (str): Person external ID to which allegation is linked.
        :allegation (str): Allegation matched by unique name or added if it does not exist.
        :allegation_outcome (str): Allegation outcome matched by unique name or added if it does not exist.
        :penalty (str): Penalty linked to the same content-person as the allegation.
    """
    content_external_id = CharField(
        required=False,
        allow_null=True,
        label=_('External ID for content that is linked to allegation')
    )

    person_external_id = CharField(
        required=False,
        allow_null=True,
        label=_('External ID for person that is linked to allegation')
    )

    allegation = CharField(
        required=False,
        allow_null=True,
        label=_('Allegation - match by unique name, or add if it does not exist')
    )

    allegation_outcome = CharField(
        required=False,
        allow_null=True,
        label=_('Allegation outcome - match by unique name, or add if it does not exist')
    )

    penalty = CharField(
        required=False,
        allow_null=True,
        label=_('Penalty linked to same content and person as allegation')
    )

    #: Key used to reference in the _validated_data dictionary, penalty that is linked to the same content-person.
    __penalty_key = 'penalty'

    def __validate_content_person(self):
        """ Validates the external content ID and person fields.

        If validated, prepares them for the corresponding Content-Person instance.

        :return: Nothing.
        """
        # build content-person link from content and person
        content_external_id = self.initial_data.pop('content_external_id', None)
        if not content_external_id:
            raise ValidationError(_('No content specified for allegation'))
        else:
            content = self._match_by_external_id(
                external_id_to_match=str(content_external_id).strip(),
                model=Content,
                validated_data_key=None
            )
        person_external_id = self.initial_data.pop('person_external_id', None)
        if not person_external_id:
            raise ValidationError(_('No person specified for allegation'))
        else:
            person = self._match_by_external_id(
                external_id_to_match=str(person_external_id).strip(),
                model=Person,
                validated_data_key=None
            )
        if not content and person:
            raise ValidationError(_('Content-person link could not be made for allegation'))
        else:
            content_person_qs = ContentPerson.objects.filter(content=content, person=person)
            if not content_person_qs.count() == 1:
                raise ValidationError(_('A single content-person link could not be found for allegation'))
            content_person = content_person_qs.get(content=content, person=person)
            self.custom_validated_data['content_person_id'] = content_person.pk

    def __validate_penalty(self):
        """ Validates the Penalty field.

        If validated, prepares it for the corresponding Content Person Penalty instance.

        :return: Nothing.
        """
        # parse penalty
        penalty_key = 'penalty'
        penalty = self.validated_data.pop(penalty_key, None)
        if penalty:
            self._validated_data[self.__penalty_key] = str(penalty).strip()

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        self.__validate_content_person()
        # validate the given the allegation by its name, and add it as a model instance if it does not already
        # exist, and then place the value into self.initial_data
        self._validate_foreign_key_by_name(
            foreign_key_field='allegation',
            foreign_key_model=Allegation,
            create_unknown=True,
            raise_exception=True
        )
        # validate the given the allegation outcome by its name, and add it as a model instance if it does not already
        # exist, and then place the value into self.initial_data
        self._validate_foreign_key_by_name(
            foreign_key_field='allegation_outcome',
            foreign_key_model=AllegationOutcome,
            create_unknown=False,
            raise_exception=False
        )
        # validate record
        is_valid = super(AllegationAirTableSerializer, self).is_valid(raise_exception=raise_exception)
        # record is valid
        if is_valid:
            self.__validate_penalty()
        return is_valid

    def create(self, validated_data):
        """ Creates a new content-person-allegation and its related data.

        :param validated_data: Dictionary of validated data used to creating new content-person-allegation and its
        related data.
        :return: Instance of newly created content-person-allegation.
        """
        validated_data['content_person_id'] = self.custom_validated_data.get('content_person_id', None)
        # validated data before values are popped from it
        self.original_validated_data = validated_data.copy()
        # pop custom fields from validated data
        penalty = validated_data.pop(self.__penalty_key, '')
        # instance has been added into bulk import table
        instance = super(AllegationAirTableSerializer, self).create(validated_data=validated_data)
        # optionally create a penalty
        if penalty:
            content_person_penalty = ContentPersonPenalty(
                penalty_received=penalty,
                content_person=instance.content_person
            )
            content_person_penalty.full_clean()
            content_person_penalty.save()
        return instance

    class Meta:
        model = ContentPersonAllegation
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = FdpModelSerializer.excluded_fields + ['content_person', 'description', 'allegation_count']


class CountyAirTableSerializer(FdpModelSerializer):
    """ Serializer for counties that were defined through the Air Table templates.

    Attributes:
        :state (str): State matched by unique name or added if it does not exist.
    """
    state = CharField(
        required=False,
        allow_null=True,
        label=_('State - match by unique name, or add if it does not exist')
    )

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        # validate the given the state by its name, and add it as a model instance if it does not already
        # exist, and then place the value into self.initial_data
        self._validate_foreign_key_by_name(
            foreign_key_field='state',
            foreign_key_model=State,
            create_unknown=True,
            raise_exception=True
        )
        # validate record
        return super(CountyAirTableSerializer, self).is_valid(raise_exception=raise_exception)

    class Meta:
        model = County
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = FdpModelSerializer.excluded_fields


class PersonGroupingAirTableSerializer(AbstractAsOfDateBoundedModelSerializer, AbstractPersonLinkModelSerializer):
    """ Serializer for person-groupings that were defined through the Air Table templates.

    Attributes:
        :grouping (str): Grouping matched by external grouping ID.
        :type (str): Type matched by unique name or added if it does not exist.
        :is_inactive_checkbox (str): Is inactive checkbox.
    """
    grouping = CharField(
        required=False,
        allow_null=True,
        label=_('Grouping - match by external grouping ID')
    )

    type = CharField(
        required=False,
        allow_null=True,
        label=_('Type - match by unique name, or add if it does not exist')
    )

    is_inactive_checkbox = CharField(
        required=False,
        allow_null=True,
        label=_('Is inactive checkbox')
    )

    def __validate_is_inactive_checkbox(self):
        """ Validates the Is Inactive checkbox field.

        :return: Nothing.
        """
        self._validate_checkbox_field(
            unvalidated_checkbox_field='is_inactive_checkbox',
            validated_checkbox_field='is_inactive'
        )

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        # validate the grouping by its external ID, and if validated, place the value into self.initial_data
        self._validate_foreign_key_by_external_id(
            foreign_key_field='grouping',
            foreign_key_model=Grouping,
            raise_exception=True
        )
        # validate the given the type by its name, and add it as a model instance if it does not already
        # exist, and then place the value into self.initial_data
        self._validate_foreign_key_by_name(
            foreign_key_field='type',
            foreign_key_model=PersonGroupingType,
            create_unknown=False,
            raise_exception=False
        )
        # validate record
        is_valid = super(PersonGroupingAirTableSerializer, self).is_valid(raise_exception=raise_exception)
        # record is valid
        if is_valid:
            self.__validate_is_inactive_checkbox()
        return is_valid

    class Meta:
        model = PersonGrouping
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = list(set(AbstractAsOfDateBoundedModelSerializer.excluded_fields +
                           AbstractPersonLinkModelSerializer.excluded_fields +
                           ['is_inactive', 'description']))


class PersonTitleAirTableSerializer(AbstractAsOfDateBoundedModelSerializer, AbstractPersonLinkModelSerializer):
    """ Serializer for person-titles that were defined through the Air Table templates.

    Attributes:
        :title (str): Title matched by unique name or added if it does not exist.
    """
    title = CharField(
        required=False,
        allow_null=True,
        label=_('Title - match by unique name, or add if it does not exist')
    )

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        # validate the given the title by its name, and add it as a model instance if it does not already
        # exist, and then place the value into self.initial_data
        self._validate_foreign_key_by_name(
            foreign_key_field='title',
            foreign_key_model=Title,
            create_unknown=True,
            raise_exception=True
        )
        # validate record
        return super(PersonTitleAirTableSerializer, self).is_valid(raise_exception=raise_exception)

    class Meta:
        model = PersonTitle
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = list(set(AbstractAsOfDateBoundedModelSerializer.excluded_fields +
                           AbstractPersonLinkModelSerializer.excluded_fields +
                           ['description']))


class PersonPaymentAirTableSerializer(AbstractAsOfDateBoundedModelSerializer, AbstractPersonLinkModelSerializer):
    """ Serializer for person payments that were defined through the Air Table templates.

    Attributes:
        :leave_status (str): Leave status matched by unique name or added if it does not exist.
        :county (str): County matched by external county ID.
    """
    leave_status = CharField(
        required=False,
        allow_null=True,
        label=_('Leave status - match by unique name, or add if it does not exist')
    )

    county = CharField(
        required=False,
        allow_null=True,
        label=_('County - match by external county ID')
    )

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        # description can be blank but not None
        self._convert_null_to_blank(field_name='description')
        # validate the given the leave status by its name, and add it as a model instance if it does not already
        # exist, and then place the value into self.initial_data
        self._validate_foreign_key_by_name(
            foreign_key_field='leave_status',
            foreign_key_model=LeaveStatus,
            create_unknown=False,
            raise_exception=False
        )
        # validate the county by its external ID, and if validated, place the value into self.initial_data
        self._validate_foreign_key_by_external_id(
            foreign_key_field='county',
            foreign_key_model=County,
            raise_exception=False
        )
        # validate decimals
        raise_exception = False
        v_dict = {'raise_exception': raise_exception, 'validator': None}
        self._validate_decimal(decimal_field='base_salary', **v_dict)
        self._validate_decimal(decimal_field='regular_hours', **v_dict)
        self._validate_decimal(decimal_field='regular_hours_gross_pay', **v_dict)
        self._validate_decimal(decimal_field='overtime_hours', **v_dict)
        self._validate_decimal(decimal_field='overtime_pay', **v_dict)
        self._validate_decimal(decimal_field='total_other_pay', **v_dict)
        # validate record
        return super(PersonPaymentAirTableSerializer, self).is_valid(raise_exception=raise_exception)

    class Meta:
        model = PersonPayment
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = list(set(AbstractAsOfDateBoundedModelSerializer.excluded_fields +
                           AbstractPersonLinkModelSerializer.excluded_fields +
                           []))


class PersonIncidentAirTableSerializer(AbstractPersonLinkModelSerializer):
    """ Serializer for person-incidents that were defined through the Air Table templates.

    Attributes:
        :incident (str): Incident matched by external incident ID.
        :is_guess_checkbox (str): Is guess checkbox.
    """
    incident = CharField(
        required=False,
        allow_null=True,
        label=_('Incident - match by external incident ID')
    )

    is_guess_checkbox = CharField(
        required=False,
        allow_null=True,
        label=_('Is guess checkbox')
    )

    def __validate_is_guess_checkbox(self):
        """ Validates the Is Guess checkbox field.

        :return: Nothing.
        """
        self._validate_checkbox_field(
            unvalidated_checkbox_field='is_guess_checkbox',
            validated_checkbox_field='is_guess'
        )

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        # validate the incident by its external ID, and if validated, place the value into self.initial_data
        self._validate_foreign_key_by_external_id(
            foreign_key_field='incident',
            foreign_key_model=Incident,
            raise_exception=True
        )
        # validate record
        is_valid = super(PersonIncidentAirTableSerializer, self).is_valid(raise_exception=raise_exception)
        # record is valid
        if is_valid:
            self.__validate_is_guess_checkbox()
        return is_valid

    class Meta:
        model = PersonIncident
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = list(set(AbstractPersonLinkModelSerializer.excluded_fields +
                           ['situation_role', 'description', 'is_guess', 'known_info', 'tags']))


class ContentPersonAirTableSerializer(AbstractPersonLinkModelSerializer, AbstractContentLinkModelSerializer):
    """ Serializer for content-persons that were defined through the Air Table templates.

    Attributes:
        :is_guess_checkbox (str): Is guess checkbox.
    """
    is_guess_checkbox = CharField(
        required=False,
        allow_null=True,
        label=_('Is guess checkbox')
    )

    def __validate_is_guess_checkbox(self):
        """ Validates the Is Guess checkbox field.

        :return: Nothing.
        """
        self._validate_checkbox_field(
            unvalidated_checkbox_field='is_guess_checkbox',
            validated_checkbox_field='is_guess'
        )

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        # validate record
        is_valid = super(ContentPersonAirTableSerializer, self).is_valid(raise_exception=raise_exception)
        # record is valid
        if is_valid:
            self.__validate_is_guess_checkbox()
        return is_valid

    class Meta:
        model = ContentPerson
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = list(set(AbstractPersonLinkModelSerializer.excluded_fields +
                           ['situation_role', 'description', 'is_guess', 'known_info']))


class ContentIdentifierAirTableSerializer(AbstractContentLinkModelSerializer):
    """ Serializer for content-identifiers that were defined through the Air Table templates.

    Attributes:
        :content_identifier_type (str): Content identifier type matched by unique name or added if it does not exist.
    """
    content_identifier_type = CharField(
        required=False,
        allow_null=True,
        label=_('Type - match by unique name, or add if it does not exist')
    )

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        identifier = self.initial_data.get('identifier', None)
        if not(identifier and str(identifier).strip()):
            self.initial_data['identifier'] = str(_('Unknown'))
        # validate the given the content identifier type by its name, and add it as a model instance if it does not
        # already exist, and then place the value into self.initial_data
        self._validate_foreign_key_by_name(
            foreign_key_field='content_identifier_type',
            foreign_key_model=ContentIdentifierType,
            create_unknown=True,
            raise_exception=True
        )
        # validate record
        return super(ContentIdentifierAirTableSerializer, self).is_valid(raise_exception=raise_exception)

    class Meta:
        model = ContentIdentifier
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = list(set(AbstractContentLinkModelSerializer.excluded_fields +
                           FdpModelSerializer.confidentiable_excluded_fields + ['description']))


class AttachmentAirTableSerializer(FdpModelSerializer):
    """ Serializer for attachments that were defined through the Air Table templates.

    Attributes:
        :type (str): Type for attachment, add if it does not exist.
        :file_path (str): Relative path for attachment file.
        :unsplit_content (str): External content IDs separated by commas.
    """
    type = CharField(
        required=False,
        allow_null=True,
        label=_('Type for attachment, add if it does not exist')
    )

    file_path = CharField(
        required=False,
        allow_null=True,
        label=_('Relative path for file')
    )

    unsplit_content = CharField(
        required=False,
        allow_null=True,
        label=_('External content IDs separated by commas')
    )

    #: Key used to reference in the _validated_data dictionary, the list of content that link to the attachment.
    __split_content_key = 'split_content'

    def __validate_content(self):
        """ Validates the content field.

        If validated, prepares the corresponding Content instances.

        :return: Nothing.
        """
        # split content
        unsplit_content_key = 'unsplit_content'
        unsplit_content = self.validated_data.pop(unsplit_content_key, '')
        split_content = str(unsplit_content).split(',') if unsplit_content else []
        self._validated_data[self.__split_content_key] = []
        if split_content:
            for content_external_id in split_content:
                stripped_content_external_id = content_external_id.strip()
                if stripped_content_external_id:
                    self._match_by_external_id(
                        external_id_to_match=stripped_content_external_id,
                        model=Content,
                        validated_data_key=self.__split_content_key
                    )

    def is_valid(self, raise_exception=False):
        """ Validates for optional custom attributes.

        :param raise_exception: True if an exception should be raised during validation.
        :return: True if record is valid, false if record is invalid.
        """
        name = self.initial_data.get('name', None)
        if not(name and str(name).strip()):
            self.initial_data['name'] = str(_('Unnamed'))
        self._convert_null_to_blank(field_name='description')
        # validate the given the type by its name, and add it as a model instance if it does not already
        # exist, and then place the value into self.initial_data
        self._validate_foreign_key_by_name(
            foreign_key_field='type',
            foreign_key_model=AttachmentType,
            create_unknown=False,
            raise_exception=False
        )
        # validate record
        is_valid = super(AttachmentAirTableSerializer, self).is_valid(raise_exception=raise_exception)
        # record is valid
        if is_valid:
            self.__validate_content()
        return is_valid

    def create(self, validated_data):
        """ Creates a new attachment and its related data.

        :param validated_data: Dictionary of validated data used to creating new content and its related data.
        :return: Instance of newly created attachment.
        """
        # validated data before values are popped from it
        self.original_validated_data = validated_data.copy()
        # pop custom fields from validated data
        file_path = validated_data.pop('file_path', None)
        split_content_ids = validated_data.pop(self.__split_content_key, [])
        # instance has been added into bulk import table
        instance = super(AttachmentAirTableSerializer, self).create(validated_data=validated_data)
        # add relative file path and validate
        if file_path:
            instance.file = file_path
            instance.full_clean()
            instance.save()
        # optionally link content with attachment
        if split_content_ids:
            # TODO: Confidentiality filtering
            # TODO: accessible_content = Content.objects.all().filter_for_confidential_by_user(user=user)
            accessible_content = Content.objects.all()
            for content_id in split_content_ids:
                content = accessible_content.get(pk=content_id)
                content.attachments.add(instance)
        return instance

    class Meta:
        model = Attachment
        #: Model fields that are excluded here must be passed into the validated_data dictionary through the
        # self.custom_validated_data dictionary attribute, before the super's create(...) method is called.
        exclude = list(set(FdpModelSerializer.excluded_fields +
                           FdpModelSerializer.confidentiable_excluded_fields + ['extension', 'file']))
