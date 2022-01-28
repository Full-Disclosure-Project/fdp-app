from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from django.utils.http import unquote_plus
from django.urls import reverse
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import QueryDict
from django.forms import formsets
from inheritable.models import Archivable, AbstractImport, AbstractSql, AbstractUrlValidator, AbstractSearchValidator, \
    JsonData, Confidentiable
from inheritable.forms import DateWithComponentsField
from inheritable.views import AdminSyncTemplateView, AdminSyncFormView, AdminSyncCreateView, AdminSyncUpdateView, \
    AdminAsyncJsonView, PopupContextMixin
from fdpuser.models import FdpOrganization
from sourcing.models import Attachment, Content, ContentIdentifier, ContentPerson, ContentPersonAllegation, \
    ContentPersonPenalty
from supporting.models import ContentType, County, Location
from .forms import WizardSearchForm, GroupingModelForm, GroupingAliasModelFormSet, GroupingRelationshipModelForm, \
    GroupingRelationshipModelFormSet, PersonModelForm, PersonAliasModelFormSet, PersonIdentifierModelFormSet, \
    PersonContactModelFormSet, PersonPaymentModelFormSet, PersonGroupingModelFormSet,PersonTitleModelFormSet, \
    PersonRelationshipModelForm, PersonRelationshipModelFormSet, IncidentModelForm, PersonIncidentModelFormSet, \
    GroupingIncidentModelFormSet, LocationModelForm, ContentIdentifierModelFormSet, ContentCaseModelFormSet, \
    ContentPersonModelFormSet, ContentModelForm, ContentAttachmentModelFormSet, AttachmentModelForm, \
    ContentIncidentModelFormSet, ContentPersonAllegationModelFormSet, ContentPersonPenaltyModelFormSet, \
    ContentPersonAllegationModelForm, ContentPersonPenaltyModelForm, ReadOnlyContentModelForm, \
    PersonPhotoModelFormSet, PersonSocialMediaProfileModelFormSet
from core.models import Person, PersonIdentifier, Grouping, GroupingAlias, GroupingRelationship, Incident, \
    PersonGrouping, PersonRelationship, PersonIncident, GroupingIncident
from abc import abstractmethod
# Load a customized algorithm for person searches
ChangingPersonSearch = AbstractImport.load_changing_search(
    file_setting='FDP_PERSON_CHANGING_SEARCH_FILE',
    class_setting='FDP_PERSON_CHANGING_SEARCH_CLASS',
    file_default='def_person',
    class_default='PersonChangingSearch'
)
# Load a customized algorithm for incident searches
ChangingIncidentSearch = AbstractImport.load_changing_search(
    file_setting='FDP_INCIDENT_CHANGING_SEARCH_FILE',
    class_setting='FDP_INCIDENT_CHANGING_SEARCH_CLASS',
    file_default='def_incident',
    class_default='IncidentChangingSearch'
)
# Load a customized algorithm for content searches
ChangingContentSearch = AbstractImport.load_changing_search(
    file_setting='FDP_CONTENT_CHANGING_SEARCH_FILE',
    class_setting='FDP_CONTENT_CHANGING_SEARCH_CLASS',
    file_default='def_content',
    class_default='ContentChangingSearch'
)
# Load a customized algorithm for grouping searches
ChangingGroupingSearch = AbstractImport.load_changing_search(
    file_setting='FDP_GROUPING_CHANGING_SEARCH_FILE',
    class_setting='FDP_GROUPING_CHANGING_SEARCH_CLASS',
    file_default='def_grouping',
    class_default='GroupingChangingSearch'
)


class AbstractPopupView(PopupContextMixin):
    """ Abstract view from which pages adding and editing models in a popup context inherit.

    Examples include location forms (locations can be added inline on incident forms), and incident forms (incidents
    can be added inline on content forms).

    """

    def _close_popup(self, popup_model_form, not_popup_url):
        """ Closes the popup window, or if form is not rendered in a popup window, then redirects to next step.

        :param popup_model_form: Model form that inherits from inheritable.models.PopupForm.
        :param not_popup_url: Url that represents the next step if the form was not rendered in a popup window.
        :return: Link either to close popup window or to the next step.
        """

        request = getattr(self, 'request')
        post_data = request.POST if getattr(request, 'POST', None) else None
        # form is rendered as a popup
        if post_data and popup_model_form.is_rendered_as_popup(post_data=post_data):
            popup_id = popup_model_form.get_popup_id(post_data=post_data)
            # form has a corresponding object
            if hasattr(self, 'object'):
                pk = self.object.pk
                str_rep = self.object.__str__()
                return self._redirect_to_close_popup(popup_id=popup_id, pk=pk, str_rep=str_rep)
        # form is not rendered as a popup, or it did not have a corresponding object
        return not_popup_url


class IndexTemplateView(AdminSyncTemplateView):
    """ Page that allows users to select the data management tool they wish to use, such as the person wizard,
    advanced admin, etc.

    """
    template_name = 'admin_home.html'

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(IndexTemplateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('Admin'),
            'description': _('Select the data management tool.'),
        })
        return context


class AbstractWizardSearchFormView(AdminSyncFormView):
    """ Abstract view from which all pages inherit that offer the user an option to search for an existing or create a
    new object through the data management wizard, e.g. content, incidents, persons and groupings.

    """
    object_name = _('record')
    object_name_plural = _('records')
    template_name = 'search.html'
    form_class = WizardSearchForm
    help_text = _('Search by keywords')
    css_class = ''
    form_type = ''

    def __init__(self, **kwargs):
        """ Initializes the form property that will be set once the form is validated and passed to the method building
        the success URL.

        :param args:
        :param kwargs:
        """
        super(AbstractWizardSearchFormView, self).__init__(**kwargs)
        self.form = None

    def get_initial(self):
        """ Specify in the initial data the context for the search form, e.g. content, incidents, persons or groupings.
        """
        initial = super(AbstractWizardSearchFormView, self).get_initial()
        initial['type'] = self.form_type
        return initial

    @staticmethod
    def _get_search_querystring(search_text):
        """ Sets the querystring used to specify the original unparsed search criteria.

        :param search_text: A single string of search criteria entered by the user.
        :return: Querystring used to specify the original unparsed  search criteria.
        """
        querystring = QueryDict('', mutable=True)
        # record original search criteria
        original_search = search_text
        # set the querystring
        querystring = AbstractUrlValidator.add_encrypted_value_to_querystring(
            querystring=querystring, key=AbstractUrlValidator.GET_ORIGINAL_PARAM, value_to_add=original_search
        )
        return querystring

    def get_success_url(self):
        """ Build link to search results containing the original unparsed search criteria as querystring GET parameter.

        :return: Link to search results for original unparsed search criteria.
        """
        search_text = self.form.cleaned_data['search']
        # process the search string entered by the user
        querystring = self._get_search_querystring(search_text=search_text)
        return '{url}?{querystring}'.format(
            url=reverse('changing:list', kwargs={'type': self.form_type}),
            querystring=querystring.urlencode()
        )

    def get_context_data(self, **kwargs):
        """ Adds the title, description and search form to the view context.

        :param kwargs:
        :return: Context for view, including title, description and search form.
        """
        context = super(AbstractWizardSearchFormView, self).get_context_data(**kwargs)
        context.update({
            'title': _('{r}'.format(r=self.object_name_plural.capitalize())),
            'description': _('Search for and change an existing {r} or create a new {r}.'.format(r=self.object_name)),
            'object_name': self.object_name,
            'object_name_plural': self.object_name_plural,
            'help_text': self.help_text,
            'css_class': self.css_class
        })
        return context

    def form_valid(self, form):
        """ Displays paginated list of records matching search criteria.

        Called when a valid form data is submitted via POST method.

        Returns a HttpResponse object.

        :param form: Search form that was submitted by user.
        :return:
        """
        self.form = form
        return super(AbstractWizardSearchFormView, self).form_valid(form=form)


class ContentWizardSearchFormView(AbstractWizardSearchFormView):
    """ Page that offers the user an option to search for an existing or create a new content through the data
    management wizard.

    """
    object_name = _('content')
    object_name_plural = _('content')
    help_text = _('Search for existing content by identifiers, people and keywords')
    css_class = 'content'
    form_type = WizardSearchForm.content_type


class IncidentWizardSearchFormView(AbstractWizardSearchFormView):
    """ Page that offers the user an option to search for an existing or create a new incident through the data
    management wizard.

    """
    object_name = _('incident')
    object_name_plural = _('incidents')
    help_text = _('Search for existing incidents by dates, people and keywords')
    css_class = 'incident'
    form_type = WizardSearchForm.incident_type


class PersonWizardSearchFormView(AbstractWizardSearchFormView):
    """ Page that offers the user an option to search for an existing or create a new person through the data
    management wizard.

    """
    object_name = _('person')
    object_name_plural = _('people')
    help_text = _('Search for existing persons by names, identifiers and  keywords')
    css_class = 'person'
    form_type = WizardSearchForm.person_type


class GroupingWizardSearchFormView(AbstractWizardSearchFormView):
    """ Page that offers the user an option to search for an existing or create a new grouping through the data
    management wizard.

    """
    object_name = _('grouping')
    object_name_plural = _('groupings')
    help_text = _('Search for existing groupings by names and keywords')
    css_class = 'grouping'
    form_type = WizardSearchForm.grouping_type


class WizardSearchResultsTemplateView(AdminSyncTemplateView):
    """ Page that allows users to browse search results and select one to edit through the data management wizard.

    """
    template_name = 'search_results.html'
    __pk_key = 'pk'
    __name_key = 'name'
    __link_key = 'link'

    def __init__(self, *args, **kwargs):
        """ Initialize the queryset count to zero, list of results to empty, the search criteria to nothing, and the
        search class that contains the searching algorithm, the model used to instantiate that search class, the
        method used to retrieve specific select query, and the method used to retrieve specific list.

        :param args:
        :param kwargs:
        """
        super(WizardSearchResultsTemplateView, self).__init__(*args, **kwargs)
        self.__count = 0
        self.__result_list = []
        self.__search_class = None
        self.__search_class_model = None
        self.__get_specific_select_query = None
        self.__get_specific_list = None

    def __parse_filters(self):
        """ Parses out the search criteria specified in the GET parameter that will be used to filter search results.

        :return: Nothing.
        """
        g = self.request.GET
        keys = list(g.keys())
        # retrieve a mapping from unencrypted keys to encrypted keys
        key_mapping = AbstractUrlValidator.get_key_mapping(list_of_keys=keys)
        # get original search criteria
        original_search_text = AbstractUrlValidator.get_unencrypted_value_from_querystring(
            querystring=g,
            key=AbstractUrlValidator.GET_ORIGINAL_PARAM,
            default_value='',
            key_mapping=key_mapping
        )
        # definition used for searching algorithm
        self.__search_class = self.__search_class_model(
            original_search_criteria=original_search_text,
            unique_table_suffix=self.__search_class_model.get_unique_table_suffix(user=self.request.user)
        )
        # parse the search criteria
        self.__search_class.common_parse_search_criteria()

    def __define_count_query(self):
        """ Defines the count version of the searching query.

        Sets the following properties:
         - self._count_params
         - self._sql_count_query

        :return: Nothing.
        """
        # SELECT COUNT(*) FROM ... SQL query to count persons matching search criteria
        self._sql_count_query = """
            {sql_temp_table} SELECT COUNT(DISTINCT "{entity_to_count}"."id") {sql_from};
        """.format(
            sql_temp_table=self.__search_class.temp_table_query,
            entity_to_count=self.__search_class.entity_to_count,
            sql_from=self.__search_class.sql_from_query
        )
        self._count_params = self.__search_class.temp_table_params + self.__search_class.from_params

    def __get_person_select_query(self):
        """ Retrieves the select version of the searching query for persons.

        :return: Nothing.
        """
        # SELECT * FROM ... SQL query to retrieve persons matching search criteria
        return """
            {sql_temp_table}
            SELECT
                A."id",
                A."name",
                MAX(A."score"),
                (
                    SELECT string_agg(ZPI."identifier", ', ')
                    FROM "{person_identifier}" AS ZPI
                    WHERE ZPI."person_id" = A."id"
                    AND ZPI.{active_filter}
                    GROUP BY ZPI."person_id"
                ) AS "ids",
                ( {title_sql} ) AS "title",
                (
                    SELECT string_agg(DISTINCT ZPG."name", ', ')
                    FROM "{grouping}" AS ZPG
                    INNER JOIN "{person_grouping}" AS ZPPG
                    ON ZPG."id" = ZPPG."grouping_id"
                    AND ZPPG."person_id" = A."id"
                    AND ZPPG.{active_filter}                    
                    WHERE ZPG.{active_filter}
                ) AS "groupings"
            FROM
                (
                SELECT
                    "{person}"."id",
                    "{person}"."name" AS "name",
                    {sql_score}
                {sql_from}
            ) A
            GROUP BY A."id", A."name"
            ORDER BY MAX(A."score") DESC
            LIMIT {max};
        """.format(
            active_filter=Archivable.ACTIVE_FILTER,
            sql_temp_table=self.__search_class.temp_table_query,
            title_sql=Person.get_title_sql(person_table_alias='A'),
            person=Person.get_db_table(),
            person_identifier=PersonIdentifier.get_db_table(),
            person_grouping=PersonGrouping.get_db_table(),
            grouping=Grouping.get_db_table(),
            sql_from=self.__search_class.sql_from_query,
            sql_score=self.__search_class.sql_score_query,
            max=AbstractSearchValidator.MAX_WIZARD_SEARCH_RESULTS
        )

    def __get_person_list(self, records):
        """ Retrieves a list of dictionaries that represent the persons retrieved through the search.

        :return: List of dictionaries.
        """
        return [
            {
                self.__pk_key: person.id,
                self.__name_key: '{n}{i}{t}{g}'.format(
                    n='' if not person.name else person.name,
                    i='{s}{i}'.format(
                        s=' - ' if person.name and person.ids else '',
                        i='' if not person.ids else person.ids
                    ),
                    t='{s}{t}'.format(
                        s=' - ' if (person.name or person.ids) and person.title else '',
                        t='' if not person.title else person.title
                    ),
                    g='{s}{g}'.format(
                        s=' - ' if (person.name or person.ids or person.title) and person.groupings else '',
                        g='' if not person.groupings else person.groupings
                    )
                ),
                self.__link_key: reverse('changing:edit_person', kwargs={'pk': person.id})
            }
            for person in records
        ]

    def __get_content_select_query(self):
        """ Retrieves the select version of the searching query for content.

        :return: Nothing.
        """
        # confidential filter for content identifier
        content_identifier_confidential_filter = ContentIdentifier.get_confidential_filter(
            user=self.request.user,
            org_table=ContentIdentifier.get_db_table_for_many_to_many(
                many_to_many_key=ContentIdentifier.fdp_organizations
            ),
            unique_alias='ZCICO',
            org_obj_col='contentidentifier_id',
            obj_col='id',
            org_org_col='{p}organization_id'.format(p=settings.DB_PREFIX.lower().strip('_')),
            prefix=ContentIdentifier.get_db_table(),
        )
        # SELECT * FROM ... SQL query to retrieve contents matching search criteria
        return """
            {sql_temp_table}
            SELECT
                A."id",
                A."name",
                A."publication_date",
                A."content_type_name",
                MAX(A."score") AS "score",
                (
                    SELECT string_agg("{content_identifier}"."identifier", ', ')
                    FROM "{content_identifier}"
                    WHERE "{content_identifier}"."content_id" = A."id"
                    AND ({content_identifier_confidential_filter})
                    AND "{content_identifier}".{active_filter}
                    GROUP BY "{content_identifier}"."content_id"
                ) AS "ids"
            FROM
                (
                SELECT
                    "{content}"."id",
                    "{content}"."name" AS "name",
                    "{content}"."publication_date" AS "publication_date",
                    COALESCE("{content_type}"."name",'') AS "content_type_name",
                    {sql_score}
                {sql_from}
            ) A
            GROUP BY A."id", A."name", A."publication_date", A."content_type_name"
            ORDER BY MAX(A."score") DESC
            LIMIT {max};
        """.format(
            content_identifier_confidential_filter=content_identifier_confidential_filter,
            active_filter=Archivable.ACTIVE_FILTER,
            sql_temp_table=self.__search_class.temp_table_query,
            content=Content.get_db_table(),
            content_identifier=ContentIdentifier.get_db_table(),
            content_type=ContentType.get_db_table(),
            sql_from=self.__search_class.sql_from_query,
            sql_score=self.__search_class.sql_score_query,
            max=AbstractSearchValidator.MAX_WIZARD_SEARCH_RESULTS
        )

    def __get_content_list(self, records):
        """ Retrieves a list of dictionaries that represent the content retrieved through the search.

        :return: List of dictionaries.
        """
        return [
            {
                self.__pk_key: content.id,
                self.__name_key: '{n}{i}{d}{t}'.format(
                    n='' if not content.name else content.name,
                    i='{s}{i}'.format(
                        s=' - ' if content.name and content.ids else '',
                        i='' if not content.ids else content.ids
                    ),
                    d='{s}{d}'.format(
                        s=' - ' if (content.name or content.ids) and content.publication_date else '',
                        d='' if not content.publication_date else content.publication_date
                    ),
                    t='{s}{t}'.format(
                        s=' - ' if (
                                           content.name or content.ids or content.publication_date
                                   ) and content.content_type_name else '',
                        t='' if not content.content_type_name else content.content_type_name
                    )
                ),
                self.__link_key: reverse('changing:edit_content', kwargs={'pk': content.id})
            }
            for content in records
        ]

    def __get_incident_select_query(self):
        """ Retrieves the select version of the searching query for incidents.

        :return: Nothing.
        """
        # SELECT * FROM ... SQL query to retrieve incidents matching search criteria
        return """
            {sql_temp_table}
            SELECT
                A."id",
                A."description",
                A."incident_dates",
                MAX(A."score")
            FROM
                (
                SELECT
                    "{incident}"."id",
                    "{incident}"."description" AS "description",
                    {sql_dates} AS "incident_dates",
                    {sql_score}
                {sql_from}
            ) A
            GROUP BY A."id", A."description", A."incident_dates"
            ORDER BY MAX(A."score") DESC
            LIMIT {max};
        """.format(
            active_filter=Archivable.ACTIVE_FILTER,
            sql_dates=Incident.sql_dates.format(t='"{incident}"'.format(incident=Incident.get_db_table())),
            sql_temp_table=self.__search_class.temp_table_query,
            incident=Incident.get_db_table(),
            sql_from=self.__search_class.sql_from_query,
            sql_score=self.__search_class.sql_score_query,
            max=AbstractSearchValidator.MAX_WIZARD_SEARCH_RESULTS
        )

    def __get_incident_list(self, records):
        """ Retrieves a list of dictionaries that represent the incidents retrieved through the search.

        :return: List of dictionaries.
        """
        return [
            {
                self.__pk_key: incident.id,
                self.__name_key: '{d}{t}'.format(
                    d='' if not incident.incident_dates else incident.incident_dates,
                    t='{s}{t}'.format(
                        s=' - ' if incident.truncated_description and incident.incident_dates else '',
                        t='' if not incident.truncated_description else incident.truncated_description
                    ),
                ),
                self.__link_key: reverse('changing:edit_incident', kwargs={'pk': incident.id, 'content_id': 0})
            }
            for incident in records
        ]

    def __get_grouping_select_query(self):
        """ Retrieves the select version of the searching query for groupings.

        :return: Nothing.
        """
        # SELECT * FROM ... SQL query to retrieve groupings matching search criteria
        return """
            {sql_temp_table}
            SELECT
                A."id",
                A."name",
                MAX(A."score"),
                (
                    SELECT string_agg(ZGA."name", ', ')
                    FROM "{grouping_alias}" AS ZGA
                    WHERE ZGA."grouping_id" = A."id"
                    AND ZGA.{active_filter}
                    GROUP BY ZGA."grouping_id"
                ) AS "aliases"
            FROM
                (
                SELECT
                    "{grouping}"."id",
                    "{grouping}"."name" AS "name",
                    {sql_score}
                {sql_from}
            ) A
            GROUP BY A."id", A."name"
            ORDER BY MAX(A."score") DESC
            LIMIT {max};
        """.format(
            active_filter=Archivable.ACTIVE_FILTER,
            sql_temp_table=self.__search_class.temp_table_query,
            grouping=Grouping.get_db_table(),
            grouping_alias=GroupingAlias.get_db_table(),
            sql_from=self.__search_class.sql_from_query,
            sql_score=self.__search_class.sql_score_query,
            max=AbstractSearchValidator.MAX_WIZARD_SEARCH_RESULTS
        )

    def __get_grouping_list(self, records):
        """ Retrieves a list of dictionaries that represent the groupings retrieved through the search.

        :return: List of dictionaries.
        """
        return [
            {
                self.__pk_key: grouping.id,
                self.__name_key: '{n}{a}'.format(
                    n='' if not grouping.name else grouping.name,
                    a='{s}{a}'.format(
                        s=' - ' if grouping.name and grouping.aliases else '',
                        a='' if not grouping.aliases else grouping.aliases
                    ),
                ),
                self.__link_key: reverse('changing:edit_grouping', kwargs={'pk': grouping.id})
            }
            for grouping in records
        ]

    def __define_select_query(self):
        """ Defines the select version of the searching query.

        Sets the following properties:
         - self._select_params
         - self._sql_select_query

        :return: Nothing.
        """
        # SELECT * FROM ... SQL query to retrieve records matching search criteria
        self._sql_select_query = self.__get_specific_select_query()
        self._select_params = self.__search_class.temp_table_params \
                              + self.__search_class.score_params \
                              + self.__search_class.from_params

    def __do_search(self):
        """ Perform the search and set the queryset and queryset count properties.

        :return: Nothing.
        """
        # user performing the search
        user = self.request.user
        # parse out the search criteria
        self.__parse_filters()
        # define the body of the query
        self.__search_class.common_define_sql_query_body(user=user)
        # define the scoring for rows in the query
        self.__search_class.common_define_sql_query_score()
        # define the count version of the searching query
        self.__define_count_query()
        # define the select version of the searching query
        self.__define_select_query()
        # perform count query
        records_count = AbstractSql.exec_single_val_sql(sql_query=self._sql_count_query, sql_params=self._count_params)
        # perform select query
        model = self.__search_class.entity
        records = model.objects.raw(self._sql_select_query, self._select_params)
        self.__count = records_count
        result_list = self.__get_specific_list(records=records)
        result_ids = [r[self.__pk_key] for r in result_list]
        num_of_result_ids = len(result_ids)
        # perform an extra direct confidentiality filtering for search results
        queryset = model.active_objects.all()
        if issubclass(model, Confidentiable):
            queryset = queryset.filter_for_confidential_by_user(user=user)
        # perform an extra indirect confidentiality filtering for search results
        queryset = model.filter_for_admin(queryset=queryset, user=user)
        # double check that all results are still accessible after direct and indirect confidentiality filtering
        if queryset.filter(pk__in=result_ids).count() != num_of_result_ids:
            raise Exception(
                _('{c} attempted to leak confidentiality through its search results. '
                  'Please review its search algorithm'.format(c=self.__search_class_model))
            )
        # otherwise, set the result list
        self.__result_list = result_list

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(WizardSearchResultsTemplateView, self).get_context_data(**kwargs)
        form_type = self.kwargs.get('type', '')
        # search results for content
        if form_type == WizardSearchForm.content_type:
            self.__search_class_model = ChangingContentSearch
            self.__get_specific_select_query = self.__get_content_select_query
            self.__get_specific_list = self.__get_content_list
            object_name = ContentWizardSearchFormView.object_name
            object_name_plural = ContentWizardSearchFormView.object_name_plural
            prev_url = reverse('changing:content')
        # search results for incident
        elif form_type == WizardSearchForm.incident_type:
            self.__search_class_model = ChangingIncidentSearch
            self.__get_specific_select_query = self.__get_incident_select_query
            self.__get_specific_list = self.__get_incident_list
            object_name = IncidentWizardSearchFormView.object_name
            object_name_plural = IncidentWizardSearchFormView.object_name_plural
            prev_url = reverse('changing:incidents')
        # search results for person
        elif form_type == WizardSearchForm.person_type:
            self.__search_class_model = ChangingPersonSearch
            self.__get_specific_select_query = self.__get_person_select_query
            self.__get_specific_list = self.__get_person_list
            object_name = PersonWizardSearchFormView.object_name
            object_name_plural = PersonWizardSearchFormView.object_name_plural
            prev_url = reverse('changing:persons')
        # search results for grouping
        elif form_type == WizardSearchForm.grouping_type:
            self.__search_class_model = ChangingGroupingSearch
            self.__get_specific_select_query = self.__get_grouping_select_query
            self.__get_specific_list = self.__get_grouping_list
            object_name = GroupingWizardSearchFormView.object_name
            object_name_plural = GroupingWizardSearchFormView.object_name_plural
            prev_url = reverse('changing:groupings')
        # unexpected
        else:
            raise Exception(_('Unsupported wizard search results type'))
        # perform the search and set the properties containing the search results queryset and the total queryset count
        self.__do_search()
        context.update({
            'title': _('Search Results'),
            'description': _('Browse the list of results matching the search criteria.'),
            'prev_url': prev_url,
            'object_name': object_name,
            'object_name_plural': object_name_plural,
            'result_list': self.__result_list,
            'count': self.__count,
            'pk_key': self.__pk_key,
            'name_key': self.__name_key,
            'link_key': self.__link_key,
        })
        return context


class AbstractGroupingView:
    """ Abstract view from which pages adding and editing grouping inherit.

    """
    _model = Grouping
    _form_class = GroupingModelForm
    _template_name = 'grouping_form.html'
    _aliases_key = 'grouping_alias_model_formset'
    _relationships_key = 'grouping_relationship_model_formset'
    _aliases_dict = {'prefix': 'aliases'}
    _relationships_dict = {'prefix': 'relationships'}

    @staticmethod
    def _get_success_url():
        """ Retrieves the link to the data management home page.

        :return: Link to data management home page.
        """
        return reverse('changing:index')

    def __get_grouping_relationship_model_formset(self, post_data, relationships_dict, user):
        """ Retrieves the grouping relationship model formset.

        :param post_data: POST data submitted through request that includes inline formsets. Will be None if request
        method type is not POST.
        :param relationships_dict: Dictionary of keyword arguments to pass into relationships formset initialization.
        :param user: User for which grouping relationship model formset should be retrieved.
        :return: Grouping relationship model formset.
        """
        # if POST data was submitted, then build the grouping relationship model formset based on it
        if post_data:
            return GroupingRelationshipModelFormSet(post_data, **relationships_dict)
        # POST data was not submitted, so build the formset based on the grouping relationships linked to the grouping
        else:
            # grouping
            obj_instance = self.object if hasattr(self, 'object') and self.object else None
            # accessible queryset of grouping relationships
            accessible_queryset = self.__get_accessible_queryset(user=user)
            # all relationships where the grouping appears as a subject or object
            relationships = accessible_queryset.filter(
                Q(subject_grouping_id=obj_instance.pk) | Q(object_grouping_id=obj_instance.pk)
            ) if obj_instance else GroupingRelationship.objects.none()
            # prefix for relationship forms
            prefix = relationships_dict['prefix']
            # management data for formset
            data = GroupingRelationshipModelForm.get_formset_management_form_data(
                prefix=prefix,
                total_forms=0,
                initial_forms=0,
                max_forms=''
            )
            # build formset iteratively
            formset = GroupingRelationshipModelFormSet(data, **relationships_dict)
            for i, relationship in enumerate(relationships):
                form = GroupingRelationshipModelForm(
                    instance=relationship,
                    for_grouping=obj_instance,
                    has_primary_key=relationship.pk,
                    prefix='{p}-{i}'.format(p=prefix, i=i)
                )
                form.add_management_fields()
                formset.forms.append(form)
            formset.set_total_forms(num_of_forms=relationships.count())
            return formset

    @staticmethod
    def __save_grouping_relationship_model_formset(grouping_relationship_model_formset, instance):
        """ Saves the grouping relationship model formset.

        :param grouping_relationship_model_formset: Grouping relationship model formset to save.
        :param instance: Grouping whose relationships are being saved.
        :return: Nothing.
        """
        if grouping_relationship_model_formset:
            for form in grouping_relationship_model_formset:
                # form for relationship may have had primary key for record defined
                primary_key = form.cleaned_data.get('primary_key', None)
                # this relationship should be deleted
                if form.cleaned_data.get(formsets.DELETION_FIELD_NAME, False):
                    # primary key exists with which existing record can be identified
                    if primary_key:
                        relationship_to_delete = GroupingRelationship.active_objects.get(pk=primary_key)
                        relationship_to_delete.delete()
                # this relationship should be created or updated
                else:
                    form.cleaned_data[GroupingRelationshipModelForm.for_grouping_key] = instance.pk
                    form.save()

    @staticmethod
    def __get_accessible_queryset(user):
        """ Retrieves queryset that is accessible by the user, filtered for indirect confidentiality.

        :param user: User accessing queryset.
        :return: Queryset.
        """
        return GroupingRelationship.filter_for_admin(queryset=GroupingRelationship.active_objects.all(), user=user)

    @classmethod
    def _validate_relationship_formset(cls, relationship_forms, user):
        """ Validate the grouping relationship model formset.

        :param relationship_forms: Grouping relationship model formset to validate.
        :param user: User submitting grouping relationship model formset.
        :return: True if grouping relationship model formset is valid, false otherwise.
        """
        # the relationship formset is defined
        if relationship_forms:
            # add back corresponding model instances to forms before validating them
            for relationship_form in relationship_forms:
                primary_key_field = relationship_form['primary_key']
                # form has primary key field
                if primary_key_field:
                    primary_key = primary_key_field.value()
                    # form has primary key value
                    if primary_key:
                        accessible_queryset = cls.__get_accessible_queryset(user=user)
                        relationship_form.instance = accessible_queryset.get(pk=primary_key)
            # validate forms
            return relationship_forms.is_valid()
        else:
            return False

    def _update_context_with_formsets(self, context, post_data, aliases_dict, relationships_dict, user):
        """ Updates the context dictionary with the inline formsets for groupings.

        :param context: Existing context dictionary to update.
        :param post_data: POST data submitted through request that includes inline formsets. Will be None if request
        method type is not POST.
        :param aliases_dict: Dictionary of keyword arguments to pass into aliases formset initialization.
        :param relationships_dict: Dictionary of keyword arguments to pass into relationships formset initialization.
        :param user: User requesting view.
        :return: Nothing.
        """
        context.update({
            'grouping': _('Grouping'),
            'json_search_criteria': AbstractUrlValidator.JSON_SRCH_CRT_PARAM,
            'counties': County.active_objects.all(),
            self._aliases_key: GroupingAliasModelFormSet(
                **aliases_dict
            ) if not post_data else GroupingAliasModelFormSet(post_data, **aliases_dict),
            self._relationships_key: self.__get_grouping_relationship_model_formset(
                post_data=post_data,
                relationships_dict=relationships_dict,
                user=user
            ),
        })

    def _save_forms(self, form, alias_forms, relationship_forms):
        """ Save the grouping form, and the corresponding inline forms.

        :param form: Grouping form to save.
        :param alias_forms: Inline grouping alias forms to save.
        :param relationship_forms: Inline grouping relationship forms to save.
        :return: Nothing.
        """
        with transaction.atomic():
            # save the grouping
            self.object = form.save()
            # pass saved instance
            alias_forms.instance = self.object
            # save data collected through inline forms
            alias_forms.save()
            self.__save_grouping_relationship_model_formset(
                grouping_relationship_model_formset=relationship_forms,
                instance=self.object
            )


class GroupingCreateView(AdminSyncCreateView, AbstractGroupingView):
    """ Page through which new grouping can be added.

    """
    model = AbstractGroupingView._model
    form_class = AbstractGroupingView._form_class
    template_name = AbstractGroupingView._template_name

    def get_success_url(self):
        """ Retrieves the link to the data management home page.

        :return: Link to data management home page.
        """
        return self._get_success_url()

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(GroupingCreateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('New grouping'),
            'description': _('Fill out fields to define a new grouping.'),
        })
        self._update_context_with_formsets(
            context=context,
            post_data=self.request.POST,
            aliases_dict=self._aliases_dict,
            relationships_dict=self._relationships_dict,
            user=self.request.user
        )
        return context

    def form_valid(self, form):
        """ Ensure that the inline formsets are saved to the database.

        :param form: Form representing grouping model instance.
        :return: Redirection to next step of wizard or form with errors displayed.
        """
        context = self.get_context_data()
        alias_forms = context[self._aliases_key]
        relationship_forms = context[self._relationships_key]
        forms_are_valid = alias_forms.is_valid()
        if forms_are_valid:
            if self._validate_relationship_formset(relationship_forms=relationship_forms, user=self.request.user):
                self._save_forms(form=form, alias_forms=alias_forms, relationship_forms=relationship_forms)
                return super(GroupingCreateView, self).form_valid(form)
        return self.form_invalid(form=form)


class GroupingUpdateView(AdminSyncUpdateView, AbstractGroupingView):
    """ Page through which existing grouping can be updated.

    """
    model = AbstractGroupingView._model
    form_class = AbstractGroupingView._form_class
    template_name = AbstractGroupingView._template_name

    def get_success_url(self):
        """ Retrieves the link to the data management home page.

        :return: Link to data management home page.
        """
        return self._get_success_url()

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(GroupingUpdateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('Update grouping'),
            'description': _('Update fields for grouping.'),
        })
        self._update_context_with_formsets(
            context=context,
            post_data=self.request.POST,
            aliases_dict={'instance': self.object, **self._aliases_dict},
            relationships_dict={**self._relationships_dict},
            user=self.request.user
        )
        return context

    def form_valid(self, form):
        """ Ensure that the inline formsets are saved to the database.

        :param form: Form representing grouping model instance.
        :return: Redirection to next step of wizard or form with errors displayed.
        """
        context = self.get_context_data()
        alias_forms = context[self._aliases_key]
        relationship_forms = context[self._relationships_key]
        forms_are_valid = alias_forms.is_valid()
        if forms_are_valid:
            if self._validate_relationship_formset(relationship_forms=relationship_forms, user=self.request.user):
                self._save_forms(form=form, alias_forms=alias_forms, relationship_forms=relationship_forms)
                return super(GroupingUpdateView, self).form_valid(form)
        return self.form_invalid(form=form)

    def get_object(self, queryset=None):
        """ Retrieves grouping to update in view.

        Direct and indirect confidentiality filtering performed in parent class(es).

        Ensures that people and incidents linked to this grouping are accessible by the user.

        :param queryset: Queryset from which to retrieve object.
        :return: Grouping to update in view.
        """
        user = self.request.user
        obj = super(GroupingUpdateView, self).get_object(queryset=queryset)
        # filter for confidential incidents linked through grouping incidents
        grouping_incidents_for_grouping = obj.grouping_incidents.all()
        grouping_incidents_for_user = GroupingIncident.filter_for_admin(
            queryset=grouping_incidents_for_grouping,
            user=user
        )
        if grouping_incidents_for_grouping.difference(grouping_incidents_for_user).exists():
            raise PermissionError(_('User does not have permission to a grouping-incident'))
        # filter for confidential persons linked through person groupings
        person_groupings_for_grouping = obj.person_groupings.all()
        person_groupings_for_user = PersonGrouping.filter_for_admin(
            queryset=person_groupings_for_grouping,
            user=user
        )
        if person_groupings_for_grouping.difference(person_groupings_for_user).exists():
            raise PermissionError(_('User does not have permission to a person-grouping'))
        return obj


class AbstractAsyncGetModelView(AdminAsyncJsonView):
    """ Abstract definition of methods and attributes used to define asynchronous retrieval of data used in
    the data wizard ("changing") forms.

    All classes defining asynchronous retrieval inherit from this class, e.g. the class used to asynchronously
    retrieve groupings.

    """
    #: Key name for the user's exact search terms in the dictionary of criteria used to filter the search results.
    _exact_terms_key = 'exact_terms'
    #: Key name for the unique value in the dictionary that is used to populate the JQuery Autocomplete tool.
    _value_key = 'value'
    #: Key name for the text label in the dictionary that is used to populate the JQuery Autocomplete tool.
    _label_key = 'label'

    def _get_filter_dict(self, request):
        """ Retrieves a dictionary of criteria used to filter the search results.

        :param request: Http request object through which criteria to filter search results were submitted by the user.
        :return: Dictionary of criteria.
        """
        post_data = self.get_post_data(request)
        search_text = str(post_data.pop(AbstractUrlValidator.JSON_SRCH_CRT_PARAM))
        if not search_text:
            raise Exception(_('No search criteria specified'))
        # strip whitespace and convert to lowercase
        search_text = ' '.join(search_text.split()).lower()
        return {self._exact_terms_key: search_text}

    @abstractmethod
    def _get_specific_queryset(self, filter_dict):
        """ Retrieves a queryset of search results based on the search criteria entered by the user.

        :param filter_dict: Dictionary of search criteria.
        :return: Queryset of search results.
        """
        pass

    @abstractmethod
    def _get_specific_error_message(self):
        """ Retrieves an error message that is specific to the class inheriting from the parent abstract class.

        Error message should be a message indicating that asynchronous retrieval of the specific
        records (e.g. groupings) has failed.

        :return: String representation of the specific error message.
        """
        pass

    @abstractmethod
    def _get_specific_data_list(self, filtered_queryset):
        """ Retrieves a list of data in a format expected by the JQuery Autocomplete tool.

        :param filtered_queryset: A queryset that has been filtered for confidentiality and includes results matching
        the user entered search criteria.
        :return: List of dictionaries, each with a structure matching the JQuery Autocomplete tool.
        """
        pass

    def post(self, request, *args, **kwargs):
        """ Retrieves the results matching the search criteria entered by the user.

        :param request: Http request object through which search criteria were submitted.
        :param args: Ignored.
        :param kwargs: Ignored.
        :return: JSON formatted response containing the search results or an error that was encountered.
        """
        filter_dict = self._get_filter_dict(request=request)
        try:
            queryset = self._get_specific_queryset(filter_dict=filter_dict)
            model = queryset.model
            # filter queryset for confidentiality
            filtered_queryset = model.filter_for_admin(queryset=queryset, user=request.user)
            # matches format expected by JQuery Autocomplete
            json = JsonData(data=self._get_specific_data_list(filtered_queryset=filtered_queryset))
        except ValidationError as err:
            json = self.jsonify_validation_error(err=err, b=self._get_specific_error_message())
        except Exception as err:
            json = self.jsonify_error(err=err, b=self._get_specific_error_message())
        return self.render_to_response(json=json)


class AsyncGetGroupingsView(AbstractAsyncGetModelView):
    """ Asynchronously retrieves groupings that can be linked to a model instance.

    """

    def _get_specific_queryset(self, filter_dict):
        """ Retrieves a queryset of search results based on the search criteria entered by the user.

        :param filter_dict: Dictionary of search criteria.
        :return: Queryset of search results.
        """
        # matching against list of terms entered by user
        exact_terms = filter_dict[self._exact_terms_key]
        # retrieve groupings
        groupings = Grouping.active_objects.all().filter(
            Q(name__icontains=exact_terms) | Q(grouping_alias__name__icontains=exact_terms)
        )
        return groupings

    def _get_specific_error_message(self):
        """ Retrieves an error message that is specific to the class inheriting from the parent abstract class.

        Error message should be a message indicating that asynchronous retrieval of the specific
        records (e.g. groupings) has failed.

        :return: String representation of the specific error message.
        """
        return _('Could not retrieve groupings. Please reload the page.')

    def _get_specific_data_list(self, filtered_queryset):
        """ Retrieves a list of data in a format expected by the JQuery Autocomplete tool.

        :param filtered_queryset: A queryset that has been filtered for confidentiality and includes results matching
        the user entered search criteria.
        :return: List of dictionaries, each with a structure matching the JQuery Autocomplete tool.
        """
        top_x = 5
        pk = 'pk'
        name = 'name'
        return [
            {
                self._value_key: grouping_dict[pk],
                self._label_key: grouping_dict[name]
            } for grouping_dict in filtered_queryset.distinct().values(pk, name)[:top_x]
        ]


class AbstractPersonView:
    """ Abstract view from which pages adding and editing person inherit.

    """
    _model = Person
    _form_class = PersonModelForm
    _template_name = 'person_form.html'
    _identifiers_key = 'person_identifier_model_formset'
    _groupings_key = 'person_grouping_model_formset'
    _titles_key = 'person_title_model_formset'
    _payments_key = 'person_payment_model_formset'
    _aliases_key = 'person_alias_model_formset'
    _social_media_profiles_key = 'person_social_media_profiles_model_formset'
    _relationships_key = 'person_relationship_model_formset'
    _contacts_key = 'person_contact_model_formset'
    _photos_key = 'person_photo_model_formset'
    _identifiers_dict = {'prefix': 'identifiers'}
    _groupings_dict = {'prefix': 'persongroupings'}
    _titles_dict = {'prefix': 'titles'}
    _payments_dict = {'prefix': 'payments'}
    _aliases_dict = {'prefix': 'aliases'}
    _social_media_profiles_dict = {'prefix': 'social-media-profile'}
    _relationships_dict = {'prefix': 'relationships'}
    _contacts_dict = {'prefix': 'contacts'}
    _photos_dict = {'prefix': 'photos'}

    @staticmethod
    def _get_success_url():
        """ Retrieves the link to the data management home page.

        :return: Link to data management home page.
        """
        return reverse('changing:index')

    def __get_person_relationship_model_formset(self, post_data, relationships_dict, user):
        """ Retrieves the person relationship model formset.

        :param post_data: POST data submitted through request that includes inline formsets. Will be None if request
        method type is not POST.
        :param relationships_dict: Dictionary of keyword arguments to pass into relationships formset initialization.
        :param user: User for which person relationship model formset should be retrieved.
        :return: Person relationship model formset.
        """
        if post_data:
            return PersonRelationshipModelFormSet(post_data, **relationships_dict)
        else:
            # person
            obj_instance = self.object if hasattr(self, 'object') and self.object else None
            # accessible queryset of person relationships
            accessible_queryset = self.__get_accessible_queryset(user=user)
            # all relationships where the person appears as a subject or object
            relationships = accessible_queryset.filter(
                Q(subject_person_id=obj_instance.pk) | Q(object_person_id=obj_instance.pk)
            ) if obj_instance else PersonRelationship.objects.none()
            # prefix for relationship forms
            prefix = relationships_dict['prefix']
            # management data for formset
            data = PersonRelationshipModelForm.get_formset_management_form_data(
                prefix=prefix,
                total_forms=0,
                initial_forms=0,
                max_forms=''
            )
            # build formset iteratively
            formset = PersonRelationshipModelFormSet(data, **relationships_dict)
            for i, relationship in enumerate(relationships):
                form = PersonRelationshipModelForm(
                    instance=relationship,
                    for_person=obj_instance,
                    has_primary_key=relationship.pk,
                    prefix='{p}-{i}'.format(p=prefix, i=i)
                )
                form.add_management_fields()
                formset.forms.append(form)
            formset.set_total_forms(num_of_forms=relationships.count())
            return formset

    @staticmethod
    def __save_person_relationship_model_formset(person_relationship_model_formset, instance):
        """ Saves the person relationship model formset.

        :param person_relationship_model_formset: Person relationship model formset to save.
        :param instance: Person whose relationships are being saved.
        :return: Nothing.
        """
        if person_relationship_model_formset:
            for form in person_relationship_model_formset:
                # form for relationship may have had primary key for record defined
                primary_key = form.cleaned_data.get('primary_key', None)
                # this relationship should be deleted
                if form.cleaned_data.get(formsets.DELETION_FIELD_NAME, False):
                    # primary key exists with which existing record can be identified
                    if primary_key:
                        relationship_to_delete = PersonRelationship.active_objects.get(pk=primary_key)
                        relationship_to_delete.delete()
                # this relationship should be created or updated
                else:
                    form.cleaned_data[PersonRelationshipModelForm.for_person_key] = instance.pk
                    form.save()

    @staticmethod
    def __get_accessible_queryset(user):
        """ Retrieves queryset that is accessible by the user, filtered for indirect confidentiality.

        :param user: User accessing queryset.
        :return: Queryset.
        """
        return PersonRelationship.filter_for_admin(queryset=PersonRelationship.active_objects.all(), user=user)

    @classmethod
    def _validate_relationship_formset(cls, relationship_forms, user):
        """ Validate the person relationship model formset.

        :param relationship_forms: Person relationship model formset to validate.
        :param user: User submitting person relationship model formset.
        :return: True if person relationship model formset is valid, false otherwise.
        """
        # the relationship formset is defined
        if relationship_forms:
            # add back corresponding model instances to forms before validating them
            for relationship_form in relationship_forms:
                primary_key_field = relationship_form['primary_key']
                # form has primary key field
                if primary_key_field:
                    primary_key = primary_key_field.value()
                    # form has primary key value
                    if primary_key:
                        accessible_queryset = cls.__get_accessible_queryset(user=user)
                        relationship_form.instance = accessible_queryset.get(pk=primary_key)
            # validate forms
            return relationship_forms.is_valid()
        else:
            return False

    def _update_context_with_formsets(
            self, context, post_data, files_data, identifiers_dict, groupings_dict, titles_dict, payments_dict,
            aliases_dict, relationships_dict, contacts_dict, photos_dict, user, social_media_profiles_dict,
    ):
        """ Updates the context dictionary with the inline formsets for persons.

        :param context: Existing context dictionary to update.
        :param post_data: POST data submitted through request that includes inline formsets. Will be None if request
        method type is not POST.
        :param identifiers_dict: Dictionary of keyword arguments to pass into identifiers formset initialization.
        :param groupings_dict: Dictionary of keyword arguments to pass into person-groupings formset initialization.
        :param titles_dict: Dictionary of keyword arguments to pass into titles formset initialization.
        :param payments_dict: Dictionary of keyword arguments to pass into payments formset initialization.
        :param aliases_dict: Dictionary of keyword arguments to pass into aliases formset initialization.
        :param social_media_profiles_dict: Dictionary of keyword arguments to pass into social_media_profiles formset initialization
        :param relationships_dict: Dictionary of keyword arguments to pass into relationships formset initialization.
        :param contacts_dict: Dictionary of keyword arguments to pass into contacts formset initialization.
        :param photos_dict: Dictionary of keyword arguments to pass into photos formset initialization.
        :param user: User requesting view.
        :return: Nothing.
        """
        context.update({
            'person': _('Person'),
            'json_search_criteria': AbstractUrlValidator.JSON_SRCH_CRT_PARAM,
            'counties': County.active_objects.all(),
            self._identifiers_key: PersonIdentifierModelFormSet(
                **identifiers_dict
            ) if not post_data else PersonIdentifierModelFormSet(post_data, **identifiers_dict),
            self._groupings_key: PersonGroupingModelFormSet(
                **groupings_dict
            ) if not post_data else PersonGroupingModelFormSet(post_data, **groupings_dict),
            self._titles_key: PersonTitleModelFormSet(
                **titles_dict
            ) if not post_data else PersonTitleModelFormSet(post_data, **titles_dict),
            self._payments_key: PersonPaymentModelFormSet(
                **payments_dict
            ) if not post_data else PersonPaymentModelFormSet(post_data, **payments_dict),
            self._aliases_key: PersonAliasModelFormSet(
                **aliases_dict
            ) if not post_data else PersonAliasModelFormSet(post_data, **aliases_dict),
            self._social_media_profiles_key: PersonSocialMediaProfileModelFormSet(
                **social_media_profiles_dict
            ) if not post_data else PersonSocialMediaProfileModelFormSet(post_data, **social_media_profiles_dict),
            self._relationships_key: self.__get_person_relationship_model_formset(
                post_data=post_data,
                relationships_dict=relationships_dict,
                user=user
            ),
            self._contacts_key: PersonContactModelFormSet(
                **contacts_dict
            ) if not post_data else PersonContactModelFormSet(post_data, **contacts_dict),
            self._photos_key: PersonPhotoModelFormSet(
                **photos_dict
            ) if not post_data else PersonPhotoModelFormSet(post_data, files_data, **photos_dict),
        })

    def _save_forms(
            self, form, identifier_forms, grouping_forms, title_forms, payment_forms, alias_forms,
            relationship_forms, contact_forms, photo_forms, social_media_profile_forms
    ):
        """ Save the person form, and the corresponding inline forms.

        :param form: Person form to save.
        :param identifier_forms: Inline person identifier forms to save.
        :param grouping_forms: Inline person grouping forms to save.
        :param title_forms: Inline person title forms to save.
        :param payment_forms: Inline person payment forms to save.
        :param alias_forms: Inline person alias forms to save.
        :param relationship_forms: Inline person relationship forms to save.
        :param contact_forms: Inline person contact forms to save.
        :param photo_forms: Inline person photo forms to save.
        :param social_media_profile_forms: Inline person social media profile forms to save
        :return: Nothing.
        """
        with transaction.atomic():
            # save the person
            self.object = form.save()
            # pass saved instance
            identifier_forms.instance = self.object
            grouping_forms.instance = self.object
            title_forms.instance = self.object
            payment_forms.instance = self.object
            alias_forms.instance = self.object
            contact_forms.instance = self.object
            photo_forms.instance = self.object
            social_media_profile_forms.instance = self.object
            # save data collected through inline forms
            identifier_forms.save()
            grouping_forms.save()
            title_forms.save()
            payment_forms.save()
            alias_forms.save()
            self.__save_person_relationship_model_formset(
                person_relationship_model_formset=relationship_forms,
                instance=self.object
            )
            contact_forms.save()
            photo_forms.save()
            social_media_profile_forms.save()


class PersonCreateView(AdminSyncCreateView, AbstractPersonView):
    """ Page through which new person can be added.

    """
    model = AbstractPersonView._model
    form_class = AbstractPersonView._form_class
    template_name = AbstractPersonView._template_name

    def get_success_url(self):
        """ Retrieves the link to the data management home page.

        :return: Link to data management home page.
        """
        return self._get_success_url()

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(PersonCreateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('New person'),
            'description': _('Fill out fields to define a new person.'),
        })
        self._update_context_with_formsets(
            context=context,
            post_data=self.request.POST,
            files_data=self.request.FILES,
            identifiers_dict=self._identifiers_dict,
            groupings_dict=self._groupings_dict,
            titles_dict=self._titles_dict,
            payments_dict=self._payments_dict,
            aliases_dict=self._aliases_dict,
            relationships_dict=self._relationships_dict,
            contacts_dict=self._contacts_dict,
            photos_dict=self._photos_dict,
            user=self.request.user,
            social_media_profiles_dict=self._social_media_profiles_dict
        )
        return context

    def form_valid(self, form):
        """ Ensure that the inline formsets are saved to the database.

        :param form: Form representing person model instance.
        :return: Redirection to next step of wizard or form with errors displayed.
        """
        context = self.get_context_data()
        identifier_forms = context[self._identifiers_key]
        grouping_forms = context[self._groupings_key]
        title_forms = context[self._titles_key]
        payment_forms = context[self._payments_key]
        alias_forms = context[self._aliases_key]
        relationship_forms = context[self._relationships_key]
        contact_forms = context[self._contacts_key]
        photo_forms = context[self._photos_key]
        social_media_profile_forms = context[self._social_media_profiles_key]
        forms_are_valid = identifier_forms.is_valid() and grouping_forms.is_valid() and title_forms.is_valid() \
                          and payment_forms.is_valid() and alias_forms.is_valid() and contact_forms.is_valid() \
                          and photo_forms.is_valid() and social_media_profile_forms.is_valid()
        if forms_are_valid:
            if self._validate_relationship_formset(relationship_forms=relationship_forms, user=self.request.user):
                self._save_forms(
                    form=form, identifier_forms=identifier_forms, grouping_forms=grouping_forms,
                    title_forms=title_forms, payment_forms=payment_forms, alias_forms=alias_forms,
                    relationship_forms=relationship_forms, contact_forms=contact_forms, photo_forms=photo_forms,
                    social_media_profile_forms=social_media_profile_forms
                )
                return super(PersonCreateView, self).form_valid(form)
        return self.form_invalid(form=form)


class PersonUpdateView(AdminSyncUpdateView, AbstractPersonView):
    """ Page through which existing person can be updated.

    """
    model = AbstractPersonView._model
    form_class = AbstractPersonView._form_class
    template_name = AbstractPersonView._template_name

    def get_success_url(self):
        """ Retrieves the link to the data management home page.

        :return: Link to data management home page.
        """
        return self._get_success_url()

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(PersonUpdateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('Update person'),
            'description': _('Update fields for person.'),
        })
        self._update_context_with_formsets(
            context=context,
            post_data=self.request.POST,
            files_data=self.request.FILES,
            identifiers_dict={'instance': self.object, **self._identifiers_dict},
            groupings_dict={'instance': self.object, **self._groupings_dict},
            titles_dict={'instance': self.object, **self._titles_dict},
            payments_dict={'instance': self.object, **self._payments_dict},
            aliases_dict={'instance': self.object, **self._aliases_dict},
            relationships_dict={**self._relationships_dict},
            contacts_dict={'instance': self.object, **self._contacts_dict},
            photos_dict={'instance': self.object, **self._photos_dict},
            user=self.request.user,
            social_media_profiles_dict={'instance': self.object, **self._social_media_profiles_dict}
        )
        return context

    def form_valid(self, form):
        """ Ensure that the inline formsets are saved to the database.

        :param form: Form representing person model instance.
        :return: Redirection to next step of wizard or form with errors displayed.
        """
        context = self.get_context_data()
        identifier_forms = context[self._identifiers_key]
        grouping_forms = context[self._groupings_key]
        title_forms = context[self._titles_key]
        payment_forms = context[self._payments_key]
        alias_forms = context[self._aliases_key]
        relationship_forms = context[self._relationships_key]
        contact_forms = context[self._contacts_key]
        photo_forms = context[self._photos_key]
        social_media_profile_forms = context[self._social_media_profiles_key]
        forms_are_valid = identifier_forms.is_valid() and grouping_forms.is_valid() and title_forms.is_valid() \
                          and payment_forms.is_valid() and alias_forms.is_valid() and contact_forms.is_valid() \
                          and photo_forms.is_valid() and social_media_profile_forms.is_valid()
        if forms_are_valid:
            if self._validate_relationship_formset(relationship_forms=relationship_forms, user=self.request.user):
                self._save_forms(
                    form=form, identifier_forms=identifier_forms, grouping_forms=grouping_forms,
                    title_forms=title_forms, payment_forms=payment_forms, alias_forms=alias_forms,
                    relationship_forms=relationship_forms, contact_forms=contact_forms, photo_forms=photo_forms,
                    social_media_profile_forms=social_media_profile_forms
                )
                return super(PersonUpdateView, self).form_valid(form)
        return self.form_invalid(form=form)

    def get_object(self, queryset=None):
        """ Retrieves person to update in view.

        Direct and indirect confidentiality filtering performed in parent class(es).

        Ensures that other people and incidents linked to this person are accessible by the user.

        :param queryset: Queryset from which to retrieve object.
        :return: Person to update in view.
        """
        user = self.request.user
        obj = super(PersonUpdateView, self).get_object(queryset=queryset)
        # filter for confidential incidents linked through person incidents
        person_incidents_for_person = obj.person_incidents.all()
        person_incidents_for_user = PersonIncident.filter_for_admin(queryset=person_incidents_for_person, user=user)
        if person_incidents_for_person.difference(person_incidents_for_user).exists():
            raise PermissionError(_('User does not have permission to a person-incident'))
        # filter for confidential people linked through person relationships
        object_persons_for_person = obj.subject_person_relationships.all()
        subject_persons_for_person = obj.object_person_relationships.all()
        object_persons_for_user = PersonRelationship.filter_for_admin(queryset=object_persons_for_person, user=user)
        subject_persons_for_user = PersonRelationship.filter_for_admin(queryset=subject_persons_for_person, user=user)
        if subject_persons_for_person.difference(subject_persons_for_user).exists() \
                or object_persons_for_person.difference(object_persons_for_user).exists():
            raise PermissionError(_('User does not have permission to a person-relationship'))
        return obj


class AsyncGetPersonsView(AbstractAsyncGetModelView):
    """ Asynchronously retrieves persons that can be linked to a model instance.

    """

    def _get_specific_queryset(self, filter_dict):
        """ Retrieves a queryset of search results based on the search criteria entered by the user.

        :param filter_dict: Dictionary of search criteria.
        :return: Queryset of search results.
        """
        # queryset filtered for direct confidentiality
        # (will be filtered for indirect confidentiality in AbstractAsyncGetModelView)
        accessible_queryset = Person.active_objects.all().filter_for_confidential_by_user(user=self.request.user)
        # matching against list of terms entered by user
        exact_terms = filter_dict[self._exact_terms_key]
        # retrieve persons
        persons = accessible_queryset.filter(
            Q(name__icontains=exact_terms)
            |
            Q(person_alias__name__icontains=exact_terms)
            |
            Q(person_identifier__identifier__icontains=exact_terms)
        )
        return persons

    def _get_specific_error_message(self):
        """ Retrieves an error message that is specific to the class inheriting from the parent abstract class.

        Error message should be a message indicating that asynchronous retrieval of the specific
        records (e.g. persons) has failed.

        :return: String representation of the specific error message.
        """
        return _('Could not retrieve persons. Please reload the page.')

    def _get_specific_data_list(self, filtered_queryset):
        """ Retrieves a list of data in a format expected by the JQuery Autocomplete tool.

        :param filtered_queryset: A queryset that has been filtered for confidentiality and includes results matching
        the user entered search criteria.
        :return: List of dictionaries, each with a structure matching the JQuery Autocomplete tool.
        """
        top_x = 5
        pk = 'pk'
        name = 'name'
        return [
            {
                self._value_key: person_dict[pk],
                self._label_key: person_dict[name]
            } for person_dict in filtered_queryset.distinct().values(pk, name)[:top_x]
        ]


class AbstractIncidentView(AbstractPopupView):
    """ Abstract view from which pages adding and editing incident inherit.

    """
    _model = Incident
    _form_class = IncidentModelForm
    _template_name = 'incident_form.html'
    _persons_key = 'person_incident_model_formset'
    _groupings_key = 'grouping_incident_model_formset'
    _persons_dict = {'prefix': 'personincidents'}
    _groupings_dict = {'prefix': 'groupingincidents'}

    @staticmethod
    def __get_param_value_from_querystring(param_name, querystring_param_names, querystring_dict):
        """ Retrieves a parameter value from the querystring, if it exists.

        :param param_name: Name of parameter, whose value should be retrieved.
        :param querystring_param_names: List of available querystring parameter names.
        :param querystring_dict: Dictionary representing querystring parameter names and values.
        :return: Value for the parameter, if it existed in the querystring.
        """
        # parameter name was specified in querystring
        if param_name in querystring_param_names:
            # get parameter value
            param_value = querystring_dict.get(param_name, None)
            return param_value if param_value else None
        # parameter name was not specified in querystring
        return None

    @staticmethod
    def __get_param_values_list_from_querystring(param_name, querystring_param_names, querystring_dict):
        """ Retrieves a parameter values list from the querystring, if it exists.

        :param param_name: Name of parameter, whose values list should be retrieved.
        :param querystring_param_names: List of available querystring parameter names.
        :param querystring_dict: Dictionary representing querystring parameter names and values.
        :return: Values list for the parameter, if it existed in the querystring.
        """
        # parameter name was specified in querystring
        if param_name in querystring_param_names:
            # get parameter values list
            param_values_list = querystring_dict.getlist(param_name)
            return param_values_list if param_values_list else None
        # parameter name was not specified in querystring
        return None

    @classmethod
    def __get_content_data_from_querystring(cls, querystring_dict):
        """ Retrieves data representing the content from the querystring dictionary, if any of it exists.

        The initial data for the incident to create can be defined using this data.

        :param querystring_dict: Dictionary representing the querystring.
        :return: Dictionary of data representing data for content to which incident may eventually be linked.
        """
        # list of available querystring parameter names
        querystring_param_names = list(querystring_dict.keys())
        # dictionary that can be expanded into keyword arguments to retrieve values from the querystring
        params = {'querystring_param_names': querystring_param_names, 'querystring_dict': querystring_dict}
        # dictionary of data representing content
        return {
            AbstractUrlValidator.GET_START_YEAR_PARAM: cls.__get_param_value_from_querystring(
                param_name=AbstractUrlValidator.GET_START_YEAR_PARAM, **params
            ),
            AbstractUrlValidator.GET_START_MONTH_PARAM: cls.__get_param_value_from_querystring(
                param_name=AbstractUrlValidator.GET_START_MONTH_PARAM, **params
            ),
            AbstractUrlValidator.GET_START_DAY_PARAM: cls.__get_param_value_from_querystring(
                param_name=AbstractUrlValidator.GET_START_DAY_PARAM, **params
            ),
            AbstractUrlValidator.GET_END_YEAR_PARAM: cls.__get_param_value_from_querystring(
                param_name=AbstractUrlValidator.GET_END_YEAR_PARAM, **params
            ),
            AbstractUrlValidator.GET_END_MONTH_PARAM: cls.__get_param_value_from_querystring(
                param_name=AbstractUrlValidator.GET_END_MONTH_PARAM, **params
            ),
            AbstractUrlValidator.GET_END_DAY_PARAM: cls.__get_param_value_from_querystring(
                param_name=AbstractUrlValidator.GET_END_DAY_PARAM, **params
            ),
            AbstractUrlValidator.GET_FOR_HOST_ONLY_PARAM: cls.__get_param_value_from_querystring(
                param_name=AbstractUrlValidator.GET_FOR_HOST_ONLY_PARAM, **params
            ),
            AbstractUrlValidator.GET_FOR_ADMIN_ONLY_PARAM: cls.__get_param_value_from_querystring(
                param_name=AbstractUrlValidator.GET_FOR_ADMIN_ONLY_PARAM, **params
            ),
            AbstractUrlValidator.GET_ORGS_PARAM: cls.__get_param_values_list_from_querystring(
                param_name=AbstractUrlValidator.GET_ORGS_PARAM, **params
            )
        }

    @classmethod
    def get_content_data_from_querystring(cls, request):
        """ Retrieves data representing the content from the querystring dictionary, if any of it exists.

        :return: Dictionary of data representing data for content to which incident may eventually be linked.
        """
        if request:
            # if this is a GET request
            if request.method == 'GET':
                return cls.__get_content_data_from_querystring(querystring_dict=request.GET)
        return None

    @staticmethod
    def get_accessible_content_queryset(user):
        """ Retrieves a queryset of content that is accessible for the user.

        Filters for direct and indirect confidentiality.

        :param user: User for which queryset should be retrieved.
        :return: Queryset.
        """
        # filtered for direct confidentiality
        queryset = Content.active_objects.all().filter_for_confidential_by_user(user=user)
        # filtered for indirect confidentiality
        return Content.filter_for_admin(queryset=queryset, user=user)

    def _get_success_url(self):
        """ Retrieves the link to the data management home page.

        :return: Link to data management home page.
        """
        return self._close_popup(popup_model_form=IncidentModelForm, not_popup_url=reverse('changing:index'))

    def _update_context_with_formsets(self, context, post_data, persons_dict, groupings_dict):
        """ Updates the context dictionary.

        :param context: Existing context dictionary to update.
        :param post_data: POST data submitted through request. Will be None if request method type is not POST.
        :param persons_dict: Dictionary of keyword arguments to pass into person-incidents formset initialization.
        :param groupings_dict: Dictionary of keyword arguments to pass into grouping-incidents formset initialization.
        :return: Nothing.
        """
        context = self._add_popup_context(context=context)
        context.update({
            'json_search_criteria': AbstractUrlValidator.JSON_SRCH_CRT_PARAM,
            'add_location_url': AbstractUrlValidator.get_link(
                url=reverse('changing:add_location'),
                is_popup=True,
                popup_id=None
            ),
            self._persons_key: PersonIncidentModelFormSet(
                **persons_dict
            ) if not post_data else PersonIncidentModelFormSet(post_data, **persons_dict),
            self._groupings_key: GroupingIncidentModelFormSet(
                **groupings_dict
            ) if not post_data else GroupingIncidentModelFormSet(post_data, **groupings_dict),
        })

    def _save_forms(self, form, person_forms, grouping_forms):
        """ Save the incident form.

        :param form: Incident form to save.
        :param person_forms: Inline person-incident forms to save.
        :param grouping_forms: Inline grouping-incident forms to save.
        :return: Nothing.
        """
        with transaction.atomic():
            # save the incident
            self.object = form.save()
            # pass saved instance
            person_forms.instance = self.object
            grouping_forms.instance = self.object
            # save data collected through inline forms
            person_forms.save()
            grouping_forms.save()


class IncidentCreateView(AdminSyncCreateView, AbstractIncidentView):
    """ Page through which new incident can be added.

    """
    model = AbstractIncidentView._model
    form_class = AbstractIncidentView._form_class
    template_name = AbstractIncidentView._template_name

    def get_success_url(self):
        """ Retrieves the link to the data management home page.

        :return: Link to data management home page.
        """
        return self._get_success_url()

    def get_initial(self):
        """ Optionally set initial values for incident based on content values that were passed through the querystring.

        :return: Dictionary of initial values for incident.
        """
        initial = super(IncidentCreateView, self).get_initial()
        # retrieve data representing content for which incident is being created
        content_data = self.get_content_data_from_querystring(request=self.request)
        # some content data may have been specified
        if content_data:
            start_year = content_data.get(AbstractUrlValidator.GET_START_YEAR_PARAM, None)
            start_month = content_data.get(AbstractUrlValidator.GET_START_MONTH_PARAM, None)
            start_day = content_data.get(AbstractUrlValidator.GET_START_DAY_PARAM, None)
            end_year = content_data.get(AbstractUrlValidator.GET_END_YEAR_PARAM, None)
            end_month = content_data.get(AbstractUrlValidator.GET_END_MONTH_PARAM, None)
            end_day = content_data.get(AbstractUrlValidator.GET_END_DAY_PARAM, None)
            for_host_only = content_data.get(AbstractUrlValidator.GET_FOR_HOST_ONLY_PARAM, None)
            for_admin_only = content_data.get(AbstractUrlValidator.GET_FOR_ADMIN_ONLY_PARAM, None)
            fdp_orgs = content_data.get(AbstractUrlValidator.GET_ORGS_PARAM, None)
            initial.update(
                {
                    'incident_started': DateWithComponentsField.compress_vals(
                        data_list=[
                            str(start_month) if start_month else '0',
                            str(start_day) if start_day else '0',
                            str(start_year) if start_year else '0'
                        ]
                    ),
                    'incident_ended': DateWithComponentsField.compress_vals(
                        data_list=[
                            str(end_month) if end_month else '0',
                            str(end_day) if end_day else '0',
                            str(end_year) if end_year else '0'
                        ]
                    ),
                    'for_admin_only': for_admin_only if for_admin_only else False,
                    'for_host_only': for_host_only if for_host_only else False,
                }
            )
            # only include in initial if the FDP organizations are defines
            if fdp_orgs:
                # initialize incident form with confidentiality settings from content
                initial.update({'fdp_organizations': FdpOrganization.active_objects.filter(pk__in=fdp_orgs)})
        return initial

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(IncidentCreateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('New incident'),
            'description': _('Fill out fields to define a new incident.'),
        })
        self._update_context_with_formsets(
            context=context,
            post_data=self.request.POST,
            persons_dict=self._persons_dict,
            groupings_dict=self._groupings_dict
        )
        return context

    def form_valid(self, form):
        """ Ensure that any inline formsets are saved to the database.

        :param form: Form representing incident model instance.
        :return: Redirection to next step of wizard or form with errors displayed.
        """
        context = self.get_context_data()
        person_forms = context[self._persons_key]
        grouping_forms = context[self._groupings_key]
        forms_are_valid = person_forms.is_valid() and grouping_forms.is_valid()
        if forms_are_valid:
            self._save_forms(form=form, person_forms=person_forms, grouping_forms=grouping_forms)
            return super(IncidentCreateView, self).form_valid(form)
        return self.form_invalid(form=form)


class IncidentUpdateView(AdminSyncUpdateView, AbstractIncidentView):
    """ Page through which existing incident can be updated.

    """
    model = AbstractIncidentView._model
    form_class = AbstractIncidentView._form_class
    template_name = AbstractIncidentView._template_name

    def __init__(self, **kwargs):
        """ Initializes the property storing the content ID for which this incident is being updated.

        Will be passed to the method building the success URL.

        :param args:
        :param kwargs: Keyword arguments that contain the ID of content for which this incident is being updated.
        """
        super(IncidentUpdateView, self).__init__(**kwargs)
        self.content_id = 0

    @staticmethod
    def get_next_incident_id(content_id, cur_incident_id, user):
        """ Retrieves the ID of the next incident to update, in the context of a particular content.

        Used to cycle through incidents after creating or updating content, in order to link suggested persons to each
        incident.

        :param content_id: ID of content, in whose context the next incident to update should be retrieved.
        Will be the content that was created or updated through the data wizard.
        :param cur_incident_id: Id of incident that is currently being updated. May be None if content was just
        created or updated, and so no incident has yet been updated.
        :param user: User for which to retrieve next incident ID.
        :return: ID of the next incident to update, or None if no such ID exists.
        """
        # content is undefined
        if not content_id:
            return None
        # content is inaccessible
        content_qs = Content.filter_for_admin(
            queryset=Content.active_objects.filter(pk=content_id).filter_for_confidential_by_user(user=user),
            user=user
        )
        if not content_qs.exists():
            return None
        # content has no people linked
        content_person_qs = ContentPerson.filter_for_admin(
            queryset=ContentPerson.active_objects.filter(content_id=content_id),
            user=user
        )
        if not content_person_qs.exists():
            return None
        # content is defined, accessible and has people linked to it
        content = content_qs.prefetch_related('incidents').get(pk=content_id)
        incident_qs = content.incidents.all()
        # filter incidents for direct and indirect confidentiality
        incident_qs = Incident.filter_for_admin(
            queryset=incident_qs.filter_for_confidential_by_user(user=user),
            user=user
        )
        # order incident IDs in ascending order
        incident_ids = incident_qs.order_by('pk').values_list('pk', flat=True)
        # content was just created or updated, and so no incident has yet been updated
        if not cur_incident_id and incident_ids:
            return incident_ids[0]
        # cycle through the incidents
        for incident_id in incident_ids:
            # since incident IDs are in ascending order, we're on the next incident ID
            if incident_id > cur_incident_id:
                return incident_id
        # we were already on last incident, so there is no next incident ID to return
        return None

    def get_success_url(self):
        """ Retrieves the link to the data management home page, or the link to the next incident to update.

        :return: Link to data management home page.
        """
        # retrieve the ID of the next incident to update
        next_incident_id = self.get_next_incident_id(
            content_id=self.content_id,
            cur_incident_id=self.object.pk,
            user=self.request.user
        )
        # there is another incident to update with suggested persons based on the content links
        if next_incident_id is not None:
            return reverse('changing:edit_incident', kwargs={'pk': next_incident_id, 'content_id': self.content_id})
        # there are no more incidents to update
        else:
            return self._get_success_url()

    def __get_persons_from_content_links(self):
        """ Retrieves a queryset of persons that are linked to the content to which this incident is linked, but are
        not yet linked to this incident.

        :return: Queryset of persons.
        """
        # incident being updated
        incident_id = self.object.pk
        # user updating incident
        user = self.request.user
        # content that are already linked to the incident
        content_qs = Content.filter_for_admin(
            queryset=Content.active_objects.filter(
                incidents__pk=incident_id
            ).filter_for_confidential_by_user(user=user),
            user=user
        )
        # content ids
        linked_content_ids = content_qs.distinct().values_list('pk', flat=True)
        # people linked to the content that are already linked to the incident
        content_person_qs = ContentPerson.filter_for_admin(
            queryset=ContentPerson.active_objects.filter(content_id__in=linked_content_ids),
            user=user
        )
        # persons linked to content
        persons_qs = Person.filter_for_admin(
            queryset=Person.active_objects.filter(
                pk__in=content_person_qs.values_list('person_id', flat=True)
            ).filter_for_confidential_by_user(user=user),
            user=user
        )
        # exclude persons that are already linked to the incident
        persons_qs = persons_qs.exclude(
            pk__in=PersonIncident.active_objects.filter(
                incident_id=incident_id
            ).values_list('person_id', flat=True)
        )
        # distinct persons
        return persons_qs.distinct()

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(IncidentUpdateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('Update incident'),
            'description': _('Update fields for incident.'),
            'suggested_persons': [{'pk': p.pk, 'name': p.__str__()} for p in self.__get_persons_from_content_links()]
        })
        self._update_context_with_formsets(
            context=context,
            post_data=self.request.POST,
            persons_dict={'instance': self.object, **self._persons_dict},
            groupings_dict={'instance': self.object, **self._groupings_dict}
        )
        # id of content for which incident is being updated, may be zero if incident updated outside of content context
        content_id = self.kwargs.get('content_id', None)
        self.content_id = 0 if not content_id else int(content_id)
        return context

    def form_valid(self, form):
        """ Ensure that the formsets are saved to the database.

        :param form: Form representing incident model instance.
        :return: Redirection to next step of wizard or form with errors displayed.
        """
        context = self.get_context_data()
        person_forms = context[self._persons_key]
        grouping_forms = context[self._groupings_key]
        forms_are_valid = person_forms.is_valid() and grouping_forms.is_valid()
        if forms_are_valid:
            self._save_forms(form=form, person_forms=person_forms, grouping_forms=grouping_forms)
            return super(IncidentUpdateView, self).form_valid(form)
        return self.form_invalid(form=form)

    def get_object(self, queryset=None):
        """ Retrieves incident to update in view.

        Direct and indirect confidentiality filtering performed in parent class(es).

        Ensures that people linked to this incident are accessible by the user.

        :param queryset: Queryset from which to retrieve object.
        :return: Incident to update in view.
        """
        user = self.request.user
        obj = super(IncidentUpdateView, self).get_object(queryset=queryset)
        # filter for confidential persons linked through person incidents
        person_incidents_for_incident = obj.person_incidents.all()
        person_incidents_for_user = PersonIncident.filter_for_admin(
            queryset=person_incidents_for_incident,
            user=user
        )
        if person_incidents_for_incident.difference(person_incidents_for_user).exists():
            raise PermissionError(_('User does not have permission to a person-incident'))
        return obj


class AbstractLocationView(AbstractPopupView):
    """ Abstract view from which pages adding and editing location inherit.

    """
    _model = Location
    _form_class = LocationModelForm
    _template_name = 'location_form.html'

    def _get_success_url(self):
        """ Retrieves the link to the next step in the data management wizard, closing the popup.

        :return: URL to link location to a model instance.
        """
        return self._close_popup(popup_model_form=LocationModelForm, not_popup_url=reverse('changing:index'))


class LocationCreateView(AdminSyncCreateView, AbstractLocationView):
    """ Page through which new location can be added.

    """
    model = AbstractLocationView._model
    form_class = AbstractLocationView._form_class
    template_name = AbstractLocationView._template_name

    def get_success_url(self):
        """ Retrieves the URL to the next step in the data management wizard, closing the popup.

        :return: URL to link location to a model instance.
        """
        return self._get_success_url()

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(LocationCreateView, self).get_context_data(**kwargs)
        context = self._add_popup_context(context=context)
        context.update({
            'title': _('New location'),
            'description': _('Fill out fields to define a new location.'),
        })
        return context


class ClosePopupTemplateView(AdminSyncTemplateView):
    """ Page that closes the popup window and passes data back to the window opener.

    """
    template_name = 'close_popup.html'

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(ClosePopupTemplateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('Close popup'),
            'description': _('Closing the popup window. Please wait.'),
            'popup_id': self.kwargs.get('popup_id'),
            'pk': self.kwargs.get('pk'),
            'str_rep': unquote_plus(self.kwargs.get('str_rep'))
        })
        return context


class AbstractContentView:
    """ Abstract view from which pages adding and editing content inherit.

    """
    _model = Content
    _form_class = ContentModelForm
    _template_name = 'content_form.html'
    _identifiers_key = 'content_identifier_model_formset'
    _case_key = 'content_case_model_formset'
    _persons_key = 'content_person_model_formset'
    _attachments_key = 'content_attachment_model_formset'
    _incidents_key = 'content_incident_model_formset'
    _identifiers_dict = {'prefix': 'identifiers'}
    _case_dict = {'prefix': 'cases'}
    _persons_dict = {'prefix': 'persons'}
    _attachments_dict = {'prefix': 'attachments'}
    _incidents_dict = {'prefix': 'incidents'}

    def _get_success_url(self):
        """ Retrieves the link to the next step in the data management tool.

        :return: Link to the next step in the data management tool.
        """
        content = getattr(self, 'object', None)
        # content has been created for view
        if content:
            pk = getattr(content, 'pk', None)
            request = getattr(self, 'request', None)
            user = None if not request else getattr(request, 'user', None)
            # content has been saved in database
            if pk:
                # check if content has any content-person links
                content_person_qs = ContentPerson.filter_for_admin(
                    queryset=ContentPerson.active_objects.filter(content_id=pk),
                    user=user
                )
                # there are content-person links for content
                if content_person_qs.exists():
                    return reverse('changing:link_allegations_penalties', kwargs={'pk': pk})
                # there are no content-person links for content
                else:
                    return reverse('changing:index')
        raise Exception(_('Content did not exist after CreateView or UpdateView was finished'))

    def _update_context_with_formsets(
            self, context, post_data, identifiers_dict, case_dict, persons_dict, attachments_dict, incidents_dict
    ):
        """ Updates the context dictionary with the inline formsets.

        :param context: Existing context dictionary to update.
        :param post_data: POST data submitted through request that includes inline formsets. Will be None if request
        method type is not POST.
        :param identifiers_dict: Dictionary of keyword arguments to pass into content identifiers formset
        initialization.
        :param case_dict: Dictionary of keyword arguments to pass into content case formset initialization.
        :param persons_dict: Dictionary of keyword arguments to pass into content persons formset initialization.
        :param attachments_dict: Dictionary of keyword arguments to pass into content attachments formset
        initialization.
        :param incidents_dict: Dictionary of keyword arguments to pass into content incidents formset initialization.
        :return: Nothing.
        """
        context.update({
            'json_search_criteria': AbstractUrlValidator.JSON_SRCH_CRT_PARAM,
            'add_attachment_url': AbstractUrlValidator.get_link(
                url=reverse('changing:add_attachment'),
                is_popup=True,
                popup_id=None
            ),
            'add_incident_url': AbstractUrlValidator.get_link(
                url=reverse('changing:add_incident'),
                is_popup=True,
                popup_id=None
            ),
            self._identifiers_key: ContentIdentifierModelFormSet(
                **identifiers_dict
            ) if not post_data else ContentIdentifierModelFormSet(post_data, **identifiers_dict),
            self._case_key: ContentCaseModelFormSet(
                **case_dict
            ) if not post_data else ContentCaseModelFormSet(post_data, **case_dict),
            self._persons_key: ContentPersonModelFormSet(
                **persons_dict
            ) if not post_data else ContentPersonModelFormSet(post_data, **persons_dict),
            self._attachments_key: ContentAttachmentModelFormSet(
                **attachments_dict
            ) if not post_data else ContentAttachmentModelFormSet(post_data, **attachments_dict),
            self._incidents_key: ContentIncidentModelFormSet(
                **incidents_dict
            ) if not post_data else ContentIncidentModelFormSet(post_data, **incidents_dict),
            'start_year_get_param': AbstractUrlValidator.GET_START_YEAR_PARAM,
            'start_month_get_param': AbstractUrlValidator.GET_START_MONTH_PARAM,
            'start_day_get_param': AbstractUrlValidator.GET_START_DAY_PARAM,
            'end_year_get_param': AbstractUrlValidator.GET_END_YEAR_PARAM,
            'end_month_get_param': AbstractUrlValidator.GET_END_MONTH_PARAM,
            'end_day_get_param': AbstractUrlValidator.GET_END_DAY_PARAM,
            'for_host_only_get_param': AbstractUrlValidator.GET_FOR_HOST_ONLY_PARAM,
            'for_admin_only_get_param': AbstractUrlValidator.GET_FOR_ADMIN_ONLY_PARAM,
            'for_organizations_get_param': AbstractUrlValidator.GET_ORGS_PARAM,
        })

    def _save_forms(self, form, identifier_forms, case_forms, person_forms, attachment_forms, incident_forms):
        """ Save the content form, and the corresponding inline forms.

        :param form: Content form to save.
        :param identifier_forms: Inline content identifier forms to save.
        :param case_forms: Inline content case forms to save.
        :param person_forms: Inline content person forms to save.
        :param attachment_forms: Inline content attachment forms to save.
        :param incident_forms: Inline content incident forms to save.
        :return: Nothing.
        """
        with transaction.atomic():
            # save the content
            self.object = form.save()
            # pass saved instance
            identifier_forms.instance = self.object
            case_forms.instance = self.object
            person_forms.instance = self.object
            attachment_forms.instance = self.object
            incident_forms.instance = self.object
            # save data collected through inline forms
            identifier_forms.save()
            case_forms.save()
            person_forms.save()
            attachment_forms.save()
            incident_forms.save()


class ContentCreateView(AdminSyncCreateView, AbstractContentView):
    """ Page through which new content can be added.

    """
    model = AbstractContentView._model
    form_class = AbstractContentView._form_class
    template_name = AbstractContentView._template_name

    def get_success_url(self):
        """ Retrieves the link to the data management home page.

        :return: Link to data management home page.
        """
        return self._get_success_url()

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(ContentCreateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('New content'),
            'description': _('Fill out fields to define a new content.'),
        })
        self._update_context_with_formsets(
            context=context,
            post_data=self.request.POST,
            identifiers_dict=self._identifiers_dict,
            case_dict=self._case_dict,
            persons_dict=self._persons_dict,
            attachments_dict=self._attachments_dict,
            incidents_dict=self._incidents_dict
        )
        return context

    def form_valid(self, form):
        """ Ensure that the inline formsets are saved to the database.

        :param form: Form representing content model instance.
        :return: Redirection to next step of wizard or form with errors displayed.
        """
        context = self.get_context_data()
        identifier_forms = context[self._identifiers_key]
        case_forms = context[self._case_key]
        person_forms = context[self._persons_key]
        attachment_forms = context[self._attachments_key]
        incident_forms = context[self._incidents_key]
        forms_are_valid = identifier_forms.is_valid() and case_forms.is_valid() and person_forms.is_valid() \
                          and attachment_forms.is_valid() and incident_forms.is_valid()
        if forms_are_valid:
            self._save_forms(
                form=form,
                identifier_forms=identifier_forms,
                case_forms=case_forms,
                person_forms=person_forms,
                attachment_forms=attachment_forms,
                incident_forms=incident_forms
            )
            return super(ContentCreateView, self).form_valid(form)
        return self.form_invalid(form=form)


class ContentUpdateView(AdminSyncUpdateView, AbstractContentView):
    """ Page through which existing content can be updated.

    """
    model = AbstractContentView._model
    form_class = AbstractContentView._form_class
    template_name = AbstractContentView._template_name
    #: Variable used to indicate whether content and directly related data (e.g. identifiers, case, and people) are
    # editable. True in ContentUpdateView and false in AllegationPenaltyLinkUpdateView.
    _is_editable_content = True

    def get_success_url(self):
        """ Retrieves the link to the data management home page.

        :return: Link to data management home page.
        """
        return self._get_success_url()

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(ContentUpdateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('Update content'),
            'description': _('Update fields for content.'),
            # True if existing content has a case, false otherwise
            # Not used to create content, since user decides in data wizard using initial SELECT element whether the
            # content will have case or not
            'is_case': True if getattr(self.object, 'content_case', None) else False
        })
        self._update_context_with_formsets(
            context=context,
            # never pass POST data if content isn't editable (e.g. in AllegationPenaltyLinkUpdateView)
            post_data=self.request.POST if self._is_editable_content else None,
            identifiers_dict={'instance': self.object, **self._identifiers_dict},
            case_dict={'instance': self.object, **self._case_dict},
            persons_dict={'instance': self.object, **self._persons_dict},
            attachments_dict={'instance': self.object, **self._attachments_dict},
            incidents_dict={'instance': self.object, **self._incidents_dict}
        )
        return context

    def form_valid(self, form):
        """ Ensure that the inline formsets are saved to the database.

        :param form: Form representing content model instance.
        :return: Redirection to next step of wizard or form with errors displayed.
        """
        # only validate directly linked data if content is editable
        if self._is_editable_content:
            context = self.get_context_data()
            identifier_forms = context[self._identifiers_key]
            case_forms = context[self._case_key]
            person_forms = context[self._persons_key]
            attachment_forms = context[self._attachments_key]
            incident_forms = context[self._incidents_key]
            forms_are_valid = identifier_forms.is_valid() and case_forms.is_valid() and person_forms.is_valid() \
                              and attachment_forms.is_valid() and incident_forms.is_valid()
            if forms_are_valid:
                self._save_forms(
                    form=form,
                    identifier_forms=identifier_forms,
                    case_forms=case_forms,
                    person_forms=person_forms,
                    attachment_forms=attachment_forms,
                    incident_forms=incident_forms
                )
                return super(ContentUpdateView, self).form_valid(form)
            return self.form_invalid(form=form)
        # otherwise skip validation (e.g. only allegation and penalty forms needed validation)
        else:
            return super(ContentUpdateView, self).form_valid(form)

    @staticmethod
    def filter_for_additional_confidentiality(content, user):
        """ Performs additional confidentiality checks for content to ensure that associated data such as people,
        attachments, incidents and content identifiers are all accessible by the user.

        Assumes direct and indirect confidentiality filtering is already performed for content elsewhere.

        Used by ContentUpdateView.get_object(...) and AllegationPenaltyLinkTemplateView.get_object(...).

        :param content: Content for which to perform additional confidentiality checks.
        :param user: Users requesting content.
        :return: Nothing.
        """
        # filter for confidential persons linked through content persons
        content_persons_for_content = content.content_persons.all()
        content_persons_for_user = ContentPerson.filter_for_admin(queryset=content_persons_for_content, user=user)
        if content_persons_for_content.difference(content_persons_for_user).exists():
            raise PermissionError(_('User does not have permission to a content-person'))
        # filter for confidential content identifiers linked through content identifiers
        content_identifiers_for_content = content.content_identifiers.all()
        content_identifiers_for_user = content_identifiers_for_content.filter_for_confidential_by_user(user=user)
        if content_identifiers_for_content.difference(content_identifiers_for_user).exists():
            raise PermissionError(_('User does not have permission to a content-identifier'))
        # filter for confidential attachments linked directly
        attachments_for_content = content.attachments.all()
        attachments_for_user = attachments_for_content.filter_for_confidential_by_user(user=user)
        if attachments_for_content.difference(attachments_for_user).exists():
            raise PermissionError(_('User does not have permission to an attachment'))
        # filter for confidential incidents linked directly
        incidents_for_content = content.incidents.all()
        incidents_for_user = incidents_for_content.filter_for_confidential_by_user(user=user)
        if incidents_for_content.difference(incidents_for_user).exists():
            raise PermissionError(_('User does not have permission to an incident'))

    def get_object(self, queryset=None):
        """ Retrieves content to update in view.

        Direct and indirect confidentiality filtering performed in parent class(es).

        Ensures that people, incidents, attachments, content identifiers linked to this content are accessible by the
        user.

        :param queryset: Queryset from which to retrieve object.
        :return: Content to update in view.
        """
        # filters for direct and indirect confidentiality
        obj = super(ContentUpdateView, self).get_object(queryset=queryset)
        # filters for additional confidentiality
        self.filter_for_additional_confidentiality(content=obj, user=self.request.user)
        return obj


class AsyncGetAttachmentsView(AbstractAsyncGetModelView):
    """ Asynchronously retrieves attachments that can be linked to a model instance.

    """

    def _get_specific_queryset(self, filter_dict):
        """ Retrieves a queryset of search results based on the search criteria entered by the user.

        :param filter_dict: Dictionary of search criteria.
        :return: Queryset of search results.
        """
        # queryset filtered for direct confidentiality
        # (will be filtered for indirect confidentiality in AbstractAsyncGetModelView)
        accessible_queryset = Attachment.active_objects.all().filter_for_confidential_by_user(user=self.request.user)
        # matching against list of terms entered by user
        exact_terms = filter_dict[self._exact_terms_key]
        # retrieve attachments
        attachments = accessible_queryset.filter(
            Q(name__icontains=exact_terms) | Q(link__icontains=exact_terms) | Q(file__icontains=exact_terms)
        )
        return attachments

    def _get_specific_error_message(self):
        """ Retrieves an error message that is specific to the class inheriting from the parent abstract class.

        Error message should be a message indicating that asynchronous retrieval of the specific
        records (e.g. persons) has failed.

        :return: String representation of the specific error message.
        """
        return _('Could not retrieve attachments. Please reload the page.')

    def _get_specific_data_list(self, filtered_queryset):
        """ Retrieves a list of data in a format expected by the JQuery Autocomplete tool.

        :param filtered_queryset: A queryset that has been filtered for confidentiality and includes results matching
        the user entered search criteria.
        :return: List of dictionaries, each with a structure matching the JQuery Autocomplete tool.
        """
        top_x = 5
        pk = 'pk'
        name = 'name'
        return [
            {
                self._value_key: attachment_dict[pk],
                self._label_key: attachment_dict[name]
            } for attachment_dict in filtered_queryset.distinct().values(pk, name)[:top_x]
        ]


class AbstractAttachmentView(AbstractPopupView):
    """ Abstract view from which pages adding and editing attachment inherit.

    """
    _model = Attachment
    _form_class = AttachmentModelForm
    _template_name = 'attachment_form.html'

    def _get_success_url(self):
        """ Retrieves the link to the next step in the data management wizard, closing the popup.

        :return: URL to link attachment to a model instance.
        """
        return self._close_popup(popup_model_form=AttachmentModelForm, not_popup_url=reverse('changing:index'))


class AttachmentCreateView(AdminSyncCreateView, AbstractAttachmentView):
    """ Page through which new attachment can be added.

    """
    model = AbstractAttachmentView._model
    form_class = AbstractAttachmentView._form_class
    template_name = AbstractAttachmentView._template_name

    def get_success_url(self):
        """ Retrieves the URL to the next step in the data management wizard, closing the popup.

        :return: URL to link attachment to a model instance.
        """
        return self._get_success_url()

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(AttachmentCreateView, self).get_context_data(**kwargs)
        context = self._add_popup_context(context=context)
        context.update({
            'title': _('New attachment'),
            'description': _('Fill out fields to define a new attachment.'),
        })
        return context


class AsyncGetIncidentsView(AbstractAsyncGetModelView):
    """ Asynchronously retrieves incidents that can be linked to a model instance.

    """

    def _get_specific_queryset(self, filter_dict):
        """ Retrieves a queryset of search results based on the search criteria entered by the user.

        :param filter_dict: Dictionary of search criteria.
        :return: Queryset of search results.
        """
        # queryset filtered for direct confidentiality
        # (will be filtered for indirect confidentiality in AbstractAsyncGetModelView)
        accessible_queryset = Incident.active_objects.all().filter_for_confidential_by_user(user=self.request.user)
        # matching against list of terms entered by user
        exact_terms = filter_dict[self._exact_terms_key]
        # retrieve incidents
        incidents = accessible_queryset.filter(description__icontains=exact_terms)
        return incidents

    def _get_specific_error_message(self):
        """ Retrieves an error message that is specific to the class inheriting from the parent abstract class.

        Error message should be a message indicating that asynchronous retrieval of the specific
        records (e.g. persons) has failed.

        :return: String representation of the specific error message.
        """
        return _('Could not retrieve incidents. Please reload the page.')

    def _get_specific_data_list(self, filtered_queryset):
        """ Retrieves a list of data in a format expected by the JQuery Autocomplete tool.

        :param filtered_queryset: A queryset that has been filtered for confidentiality and includes results matching
        the user entered search criteria.
        :return: List of dictionaries, each with a structure matching the JQuery Autocomplete tool.
        """
        top_x = 5
        return [
            {
                self._value_key: incident.pk,
                self._label_key: incident.__str__()
            } for incident in filtered_queryset.distinct()[:top_x]
        ]


class AllegationPenaltyLinkUpdateView(ContentUpdateView):
    """ Page through which allegations and penalties can be linked to content-person links through the data management
    tool.

    """
    form_class = ReadOnlyContentModelForm
    _allegations_key = 'content_person_allegation_model_formset'
    _penalties_key = 'content_person_penalty_model_formset'
    _allegations_dict = {'prefix': 'allegations'}
    _penalties_dict = {'prefix': 'penalties'}
    template_name = 'link_allegations_penalties_form.html'
    #: Variable used to indicate whether content and directly related data (e.g. identifiers, case, and people) are
    # editable. True in ContentUpdateView and false in AllegationPenaltyLinkUpdateView.
    _is_editable_content = False

    def get_success_url(self):
        """ Retrieves the link to the data management home page, or the link to the next incident to update.

        :return: Link to data management home page.
        """
        # primary key of content to which allegations and penalties are being linked
        content_id = self.kwargs['pk']
        # retrieve the id of the incident to update, after allegations/penalties are linked to the content
        next_incident_id = IncidentUpdateView.get_next_incident_id(
            content_id=content_id,
            cur_incident_id=0,
            user=self.request.user
        )
        # there is an incident to update, to add the persons that are now linked to the content
        if next_incident_id:
            return reverse('changing:edit_incident', kwargs={'pk': next_incident_id, 'content_id': content_id})
        # there is no incident to update, so go to the main page
        else:
            return reverse('changing:index')

    def get_context_data(self, **kwargs):
        """ Adds the title, description and user details to the view context.

        :param kwargs:
        :return: Context for view, including title, description and user details.
        """
        context = super(AllegationPenaltyLinkUpdateView, self).get_context_data(**kwargs)
        context.update({
            'title': _('Link Allegations and Penalties'),
            'description': _('Link allegations and penalties to the content.'),
            # primary key of content to which allegations and penalties are being linked
            'pk': self.object.pk,
            self._allegations_key: self.__get_content_person_allegation_model_formset(
                post_data=self.request.POST,
                allegations_dict=self._allegations_dict
            ),
            self._penalties_key: self.__get_content_person_penalty_model_formset(
                post_data=self.request.POST,
                penalties_dict=self._penalties_dict
            ),
            # list of all content persons for content, ordered by person name
            'content_person_list': list(self.__get_content_person_queryset()),
            # always overwrite the main content form, so that it cannot be incorrectly rebuilt from POST
            'form': self.form_class(
                instance=self.object,
                initial=self.get_initial(),
                prefix=self.get_prefix()
            )
        })
        return context

    def __get_content_person_queryset(self):
        """ Retrieves the queryset of content people that is linked to the content being changed through the data
        management tool, and is also accessible by the user.

        :return: Queryset of content people.
        """
        # content itself already filtered for direct confidentiality through parent view class
        content_id = self.object.pk
        # filter content persons for indirect confidentiality
        queryset = ContentPerson.filter_for_admin(
            queryset=ContentPerson.active_objects.filter(content_id=content_id),
            user=self.request.user
        )
        # order by person name, so that forms are easier to read in allegations/penalties sections
        return queryset.select_related('person', 'situation_role').order_by('person__name', 'person__pk')

    def __get_accessible_allegation_queryset(self, content_person=None):
        """ Retrieves allegation queryset that is accessible by the user, filtered for indirect confidentiality.

        :param content_person: Content person for which to retrieve allegations. If not defined, then allegations are
        retrieved for content.
        :return: Queryset.
        """
        queryset = ContentPersonAllegation.active_objects.filter(content_person=content_person) \
            if content_person else ContentPersonAllegation.active_objects.filter(content_person__content=self.object)
        # filter allegations by indirect confidentiality
        return ContentPersonAllegation.filter_for_admin(queryset=queryset, user=self.request.user)

    def __get_accessible_penalty_queryset(self, content_person=None):
        """ Retrieves penalty queryset that is accessible by the user, filtered for indirect confidentiality.

        :param content_person: Content person for which to retrieve penalties. If not defined, then penalties are
        retrieved for content.
        :return: Queryset.
        """
        queryset = ContentPersonPenalty.active_objects.filter(content_person=content_person) \
            if content_person else ContentPersonPenalty.active_objects.filter(content_person__content=self.object)
        # filter penalties by indirect confidentiality
        return ContentPersonPenalty.filter_for_admin(queryset=queryset, user=self.request.user)

    def form_valid(self, form):
        """ Ensure that the inline formsets are saved to the database.

        :param form: Form representing content model instance.
        :return: Redirection to next step of wizard or form with errors displayed.
        """
        context = self.get_context_data()
        allegation_forms = context[self._allegations_key]
        penalty_forms = context[self._penalties_key]
        # only validate allegations and penalties
        # do not validate content, content identifiers, content attachments, content incidents and content people
        if self.__validate_content_person_allegation_formset(allegation_forms=allegation_forms) \
                and self.__validate_content_person_penalty_formset(penalty_forms=penalty_forms):
            self.__save_forms(allegation_forms=allegation_forms, penalty_forms=penalty_forms)
            return super(AdminSyncUpdateView, self).form_valid(form)
        return self.form_invalid(form=form)

    def __save_forms(self, allegation_forms, penalty_forms):
        """ Save the inline forms for allegations and penalties corresponding to the content.

        :param allegation_forms: Inline content person allegation forms to save.
        :param penalty_forms: Inline content person penalty forms to save.
        :return: Nothing.
        """
        with transaction.atomic():
            # save data collected through inline forms for allegations and penalties
            self.__save_content_person_allegation_model_formset(
                content_person_allegation_model_formset=allegation_forms
            )
            self.__save_content_person_penalty_model_formset(content_person_penalty_model_formset=penalty_forms)

    def __get_content_person_allegation_model_formset(self, post_data, allegations_dict):
        """ Retrieves the content person allegation model formset.

        :param post_data: POST data submitted through request that includes inline formsets. Will be None if request
        method type is not POST.
        :param allegations_dict: Dictionary of keyword arguments to pass into allegations formset initialization.
        :return: Content person allegation model formset.
        """
        # if POST data was submitted, then build the content person allegation model formset based on it
        if post_data:
            return ContentPersonAllegationModelFormSet(post_data, **allegations_dict)
        # POST data was not submitted, so build the formset based on the content person allegations linked to the
        # content
        else:
            # all content person queryset
            content_person_qs = self.__get_content_person_queryset()
            # prefix for allegation forms
            prefix = allegations_dict['prefix']
            # management data for formset
            data = ContentPersonAllegationModelForm.get_formset_management_form_data(
                prefix=prefix,
                total_forms=0,
                initial_forms=0,
                max_forms=''
            )
            formset = ContentPersonAllegationModelFormSet(data, **allegations_dict)
            num_of_forms = 0
            # cycle through all content persons for content
            for content_person in content_person_qs:
                # accessible queryset of content person allegation
                allegation_qs = self.__get_accessible_allegation_queryset(content_person=content_person)
                # build formset iteratively
                for allegation in allegation_qs:
                    form = ContentPersonAllegationModelForm(
                        instance=allegation,
                        has_primary_key=allegation.pk,
                        prefix='{p}-{i}'.format(p=prefix, i=num_of_forms)
                    )
                    form.add_management_fields()
                    formset.forms.append(form)
                    num_of_forms += 1
            formset.set_total_forms(num_of_forms=num_of_forms)
            return formset

    def __get_content_person_penalty_model_formset(self, post_data, penalties_dict):
        """ Retrieves the content person penalty model formset.

        :param post_data: POST data submitted through request that includes inline formsets. Will be None if request
        method type is not POST.
        :param penalties_dict: Dictionary of keyword arguments to pass into penalties formset initialization.
        :return: Content person penalty model formset.
        """
        # if POST data was submitted, then build the content person penalty model formset based on it
        if post_data:
            return ContentPersonPenaltyModelFormSet(post_data, **penalties_dict)
        # POST data was not submitted, so build the formset based on the content person penalties linked to the
        # content
        else:
            # all content person queryset
            content_person_qs = self.__get_content_person_queryset()
            # prefix for penalty forms
            prefix = penalties_dict['prefix']
            # management data for formset
            data = ContentPersonPenaltyModelForm.get_formset_management_form_data(
                prefix=prefix,
                total_forms=0,
                initial_forms=0,
                max_forms=''
            )
            formset = ContentPersonPenaltyModelFormSet(data, **penalties_dict)
            num_of_forms = 0
            # cycle through all content persons for content
            for content_person in content_person_qs:
                # accessible queryset of content person penalty
                penalty_qs = self.__get_accessible_penalty_queryset(content_person=content_person)
                # build formset iteratively
                for penalty in penalty_qs:
                    form = ContentPersonPenaltyModelForm(
                        instance=penalty,
                        has_primary_key=penalty.pk,
                        prefix='{p}-{i}'.format(p=prefix, i=num_of_forms)
                    )
                    form.add_management_fields()
                    formset.forms.append(form)
                    num_of_forms += 1
            formset.set_total_forms(num_of_forms=num_of_forms)
            return formset

    @staticmethod
    def __save_content_person_allegation_model_formset(content_person_allegation_model_formset):
        """ Saves the content person allegation model formset.

        :param content_person_allegation_model_formset: Content person allegation model formset to save.
        :return: Nothing.
        """
        if content_person_allegation_model_formset:
            for form in content_person_allegation_model_formset:
                # form for allegation may have had primary key for record defined
                primary_key = form.cleaned_data.get('primary_key', None)
                # this allegation should be deleted
                if form.cleaned_data.get(formsets.DELETION_FIELD_NAME, False):
                    # primary key exists with which existing record can be identified
                    if primary_key:
                        # delete record
                        allegation_to_delete = ContentPersonAllegation.active_objects.get(pk=primary_key)
                        allegation_to_delete.delete()
                # this allegation should be created or updated
                else:
                    form.save()

    @staticmethod
    def __save_content_person_penalty_model_formset(content_person_penalty_model_formset):
        """ Saves the content person penalty model formset.

        :param content_person_penalty_model_formset: Content person penalty model formset to save.
        :return: Nothing.
        """
        if content_person_penalty_model_formset:
            for form in content_person_penalty_model_formset:
                # form for penalty may have had primary key for record defined
                primary_key = form.cleaned_data.get('primary_key', None)
                # this penalty should be deleted
                if form.cleaned_data.get(formsets.DELETION_FIELD_NAME, False):
                    # primary key exists with which existing record can be identified
                    if primary_key:
                        # delete record
                        penalty_to_delete = ContentPersonPenalty.active_objects.get(pk=primary_key)
                        penalty_to_delete.delete()
                # this penalty should be created or updated
                else:
                    form.save()

    def __validate_content_person_allegation_formset(self, allegation_forms):
        """ Validate the content person allegation model formset.

        :param allegation_forms: Content person allegation model formset to validate.
        :return: True if content person allegation model formset is valid, false otherwise.
        """
        # the allegation formset is defined
        if allegation_forms:
            content_person_allegation_qs = self.__get_accessible_allegation_queryset(content_person=None)
            # add back corresponding model instances to forms before validating them
            for allegation_form in allegation_forms:
                primary_key_field = allegation_form['primary_key']
                # form has primary key field
                if primary_key_field:
                    primary_key = primary_key_field.value()
                    # form has primary key value
                    if primary_key:
                        # check if content person allegation is accessible
                        if not content_person_allegation_qs.filter(pk=primary_key).exists():
                            raise PermissionError(
                                _('User does not have permission to change content person allegation')
                            )
                        allegation_form.instance = ContentPersonAllegation.active_objects.get(pk=primary_key)
            # validate forms
            return allegation_forms.is_valid()
        else:
            return False

    def __validate_content_person_penalty_formset(self, penalty_forms):
        """ Validate the content person penalty model formset.

        :param penalty_forms: Content person penalty model formset to validate.
        :return: True if content person penalty model formset is valid, false otherwise.
        """
        # the penalty formset is defined
        if penalty_forms:
            content_person_penalty_qs = self.__get_accessible_penalty_queryset(content_person=None)
            # add back corresponding model instances to forms before validating them
            for penalty_form in penalty_forms:
                primary_key_field = penalty_form['primary_key']
                # form has primary key field
                if primary_key_field:
                    primary_key = primary_key_field.value()
                    # form has primary key value
                    if primary_key:
                        # check if content person penalty is accessible
                        if not content_person_penalty_qs.filter(pk=primary_key).exists():
                            raise PermissionError(_('User does not have permission to change content person penalty'))
                        penalty_form.instance = ContentPersonPenalty.active_objects.get(pk=primary_key)
            # validate forms
            return penalty_forms.is_valid()
        else:
            return False
