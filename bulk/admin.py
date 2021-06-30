from django.contrib import admin
from django.utils.translation import ugettext_lazy as _
from .models import BulkImport, FdpImportFile, FdpImportMapping, FdpImportRun
from inheritable.admin import FdpInheritableBaseAdmin, HostOnlyAdmin
from data_wizard.models import Identifier, Run
from data_wizard.sources.models import URLSource
from data_wizard.sources.admin import ImportActionModelAdmin


@admin.register(BulkImport)
class BulkImportAdmin(HostOnlyAdmin):
    """ Admin interface for bulk imports.

    """
    _list_display = [
        'source_imported_from', 'table_imported_from', 'pk_imported_from', 'table_imported_to', 'pk_imported_to',
        'timestamp'
    ]
    list_display = _list_display
    list_display_links = _list_display
    list_filter = ['source_imported_from', 'table_imported_to', 'table_imported_from']
    search_fields = [
        'source_imported_from', 'table_imported_from', 'pk_imported_from', 'table_imported_to', 'pk_imported_to'
    ]
    ordering = ['timestamp', 'table_imported_to', 'pk_imported_to']


@admin.register(FdpImportFile)
class FileModelAdmin(FdpInheritableBaseAdmin, ImportActionModelAdmin):
    """ Admin interface for uploaded files ready for import through Django Data Wizard package.

    See: https://github.com/wq/django-data-wizard

    """
    _list_display = ['name', 'file', 'date']
    list_display = _list_display
    list_display_links = _list_display
    ordering = ['-date', 'name', 'file']

    @staticmethod
    def __only_host_admin(request):
        """ Limits access to only host administrators and super users.

        :return: True if user is host administrator or super user, false otherwise.
        """
        return (request.user.is_host and request.user.has_admin_access) or request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        """ Restricts view permissions to only host administrators and super users.

        :param request: Http request object.
        :param obj: Optional object being viewed.
        :return: True if user is host administrator or super user, false otherwise.
        """
        return self.__only_host_admin(request=request) \
            and super(FileModelAdmin, self).has_view_permission(request=request, obj=obj)

    def has_add_permission(self, request):
        """ Restricts add permissions to only host administrators and super users.

        :param request: HTTP request object.
        :return: True if user has access to add data, false otherwise.
        """
        return self.__only_host_admin(request=request) \
            and super(FileModelAdmin, self).has_add_permission(request=request)

    def has_change_permission(self, request, obj=None):
        """ Restricts change permissions to only host administrators and super users.

        :param request: HTTP request object.
        :param obj: Object that is to be edited.
        :return: True if user has access to change data, false otherwise.
        """
        return self.__only_host_admin(request=request) \
            and super(FileModelAdmin, self).has_change_permission(request=request, obj=obj)

    def has_delete_permission(self, request, obj=None):
        """ Restricts delete permissions to only host administrators and super users.

        :param request: HTTP request object.
        :param obj: Object that is to be deleted.
        :return: True if user has access to delete data, false otherwise.
        """
        return self.__only_host_admin(request=request) \
            and super(FileModelAdmin, self).has_delete_permission(request=request, obj=obj)

    def has_module_permission(self, request):
        """ Restricts module permissions to only host administrators and super users.

        :param request: HTTP request object.
        :return: True if user has access to module, false otherwise.
        """
        return self.__only_host_admin(request=request) \
            and super(FileModelAdmin, self).has_module_permission(request=request)


#  Unregister admin for Identifiers since it is registered below
admin.site.unregister(Identifier)


#  Unregister admin for Runs since it is registered below
admin.site.unregister(Run)


class SerializerListFilter(admin.SimpleListFilter):
    """ List filter for serializers.

    Will be used in the FdpImportMappingAdmin and FdpImportRunAdmin interfaces.

    """
    #: Title displayed in the right Admin sidebar just above the filter options.
    title = _('serializer')

    #: Parameter for the filter that will be used in the URL query.
    parameter_name = 'serializer'

    def lookups(self, request, model_admin):
        """ Retrieve the list of tuples that can be used to filter the Admin changelist interface.

        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.

        :param request: Http request object through which Serializer List Filter is retrieved.
        :param model_admin: Model admin class for which Serializer List Filter is retrieved.
        :return: List of tuples representing list filter.
        """
        # defined for the FDP Import Mapping Admin class
        if isinstance(model_admin, FdpImportMappingAdmin):
            # retrieve all serializers for which records exist
            field = 'identifier__serializer'
            serializers = list(model_admin.get_queryset(request=request).distinct(field).values_list(field, flat=True))
            return [
                (
                    serializer,
                    FdpImportMapping.parse_serializer_name(serializer=serializer)
                ) for serializer in serializers
            ]
        # defined for FDP Import Run Admin class
        elif isinstance(model_admin, FdpImportRunAdmin):
            # retrieve all serializers for which records exist
            field = 'run__serializer'
            serializers = list(model_admin.get_queryset(request=request).distinct(field).values_list(field, flat=True))
            return [
                (serializer, FdpImportRun.parse_serializer_name(serializer=serializer)) for serializer in serializers
            ]
        # undefined
        else:
            raise Exception(_('SerializerListFilter lookups(...) is only implemented '
                              'for FdpImportMappingAdmin and FdpImportRunAdmin'))

    def queryset(self, request, queryset):
        """ Retrieves the filtered queryset for the Admin changelist interface.

        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.

        :param request: Http request object through which queryset is retrieved.
        :param queryset: Queryset that can be filtered. Assumed to be for model FdpImportMapping.
        :return: Filtered queryset.
        """
        # full serializer, e.g. bulk.serializer.MySerializer may not be defined
        full_serializer = self.value()
        # not filtering by serializer
        if not full_serializer:
            return queryset
        # filtering by serializer
        else:
            if queryset.model is FdpImportMapping:
                return queryset.filter(identifier__serializer=full_serializer)
            elif queryset.model is FdpImportRun:
                return queryset.filter(run__serializer=full_serializer)
            else:
                raise Exception(_('SerializerListFilter queryset(...) is only implemented '
                                  'for FdpImportMappingAdmin and FdpImportRunAdmin'))


@admin.register(FdpImportMapping)
class FdpImportMappingAdmin(HostOnlyAdmin):
    """ Admin interface for mappings between columns in files to import and available fields in the serializers defined
    using the Data Wizard package.

    See: https://github.com/wq/django-data-wizard

    """
    _list_display = ['serializer', 'column_to_import']
    list_display = _list_display
    list_display_links = _list_display
    list_filter = [SerializerListFilter]
    search_fields = ['identifier__name']

    def has_view_permission(self, request, obj=None):
        """ Disables view permissions for individual records.

        :param request: Http request object.
        :param obj: Optional object being viewed.
        :return: True if user has view permissions, false otherwise.
        """
        # there is a specific object being viewed
        if obj is not None:
            return False
        # no specific object being viewed
        else:
            return super(FdpImportMappingAdmin, self).has_view_permission(request=request, obj=obj)

    def has_add_permission(self, request):
        """ Disables add permissions.

        :param request: HTTP request object.
        :return: Always false.
        """
        return False

    def has_change_permission(self, request, obj=None):
        """ Disables change permissions.

        :param request: HTTP request object.
        :param obj: Object that is to be edited.
        :return: Always false.
        """
        return False


@admin.register(FdpImportRun)
class FdpImportRunAdmin(HostOnlyAdmin):
    """ Admin interface for runs created by importing files using the Data Wizard package.

    See: https://github.com/wq/django-data-wizard

    """
    _list_display = ['serializer', 'record_count', 'last_update']
    list_display = _list_display + ['log_link']
    list_display_links = _list_display
    list_filter = [SerializerListFilter]

    def has_view_permission(self, request, obj=None):
        """ Disables view permissions for individual records.

        :param request: Http request object.
        :param obj: Optional object being viewed.
        :return: True if user has view permissions, false otherwise.
        """
        # there is a specific object being viewed
        if obj is not None:
            return False
        # no specific object being viewed
        else:
            return super(FdpImportRunAdmin, self).has_view_permission(request=request, obj=obj)

    def has_add_permission(self, request):
        """ Disables add permissions.

        :param request: HTTP request object.
        :return: Always false.
        """
        return False

    def has_change_permission(self, request, obj=None):
        """ Disables change permissions.

        :param request: HTTP request object.
        :param obj: Object that is to be edited.
        :return: Always false.
        """
        return False


#  Unregister admin for URL Sources since it is a Server-Side Request Forgery (SSRF) risk
admin.site.unregister(URLSource)
