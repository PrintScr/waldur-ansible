from django.utils.translation import ugettext_lazy as _
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import decorators, response, status, mixins
from rest_framework.mixins import ListModelMixin
from rest_framework.viewsets import GenericViewSet
from waldur_ansible.backend_processing import cache_utils
from waldur_ansible.backend_processing.locking_service import PythonManagementBackendLockingService, \
    PythonManagementBackendLockBuilder, \
    PYTHON_MANAGEMENT_ENTRY_POINT_LOCK_TIMEOUT, PYTHON_MANAGEMENT_TIMEOUT
from waldur_ansible.models import PythonManagementInitializeRequest, PythonManagementSynchronizeRequest, \
    PythonManagementFindVirtualEnvsRequest, \
    PythonManagementFindInstalledLibrariesRequest, PythonManagement, Job, PythonManagementDeleteVirtualEnvRequest, \
    PythonManagementDeleteRequest
from waldur_ansible.pip_service import PipService
from waldur_ansible.python_management_service import PythonManagementService
from waldur_core.core import exceptions as core_exceptions
from waldur_core.core import mixins as core_mixins
from waldur_core.core import validators as core_validators
from waldur_core.core import views as core_views
from waldur_core.core.managers import SummaryQuerySet
from waldur_core.core.mixins import ensure_atomic_transaction
from waldur_core.core.models import SshPublicKey
from waldur_core.structure import models as structure_models
from waldur_core.structure import views as structure_views
from waldur_core.structure.filters import GenericRoleFilter
from waldur_core.structure.metadata import ActionsMetadata
from waldur_core.structure.permissions import is_staff, is_administrator
from django.conf import settings

from . import filters, models, serializers, executors

python_management_requests_models = [PythonManagementInitializeRequest, PythonManagementSynchronizeRequest,
                                     PythonManagementFindVirtualEnvsRequest,
                                     PythonManagementFindInstalledLibrariesRequest,
                                     PythonManagementDeleteVirtualEnvRequest, PythonManagementDeleteRequest]


def build_applications_queryset():
    queryset = SummaryQuerySet([Job, PythonManagement])
    return queryset


def get_project_jobs_count(project):
    return build_applications_queryset().filter(service_project_link__project=project).count()


structure_views.ProjectCountersView.register_counter('ansible', get_project_jobs_count)


class ApplicationsSummaryViewSet(ListModelMixin, GenericViewSet):
    serializer_class = serializers.SummaryApplicationSerializer

    def get_queryset(self):
        return build_applications_queryset()

    def list(self, request, *args, **kwargs):
        return super(ApplicationsSummaryViewSet, self).list(request, *args, **kwargs)


class PlaybookViewSet(core_views.ActionsViewSet):
    lookup_field = 'uuid'
    queryset = models.Playbook.objects.all().order_by('pk')
    unsafe_methods_permissions = [is_staff]
    serializer_class = serializers.PlaybookSerializer


def check_all_related_resource_are_stable(job):
    States = structure_models.NewResource.States
    stable_states = (States.OK, States.ERRED)
    if not all(resource.state in stable_states for resource in job.get_related_resources()):
        raise core_exceptions.IncorrectStateException(_('Related resources are not stable yet. '
                                                        'Please wait until provisioning is completed.'))


class JobViewSet(core_mixins.CreateExecutorMixin, core_views.ActionsViewSet):
    lookup_field = 'uuid'
    queryset = models.Job.objects.all().order_by('pk')
    filter_backends = (GenericRoleFilter, DjangoFilterBackend)
    filter_class = filters.AnsibleJobsFilter
    unsafe_methods_permissions = [is_administrator]
    serializer_class = serializers.JobSerializer
    metadata_class = ActionsMetadata
    create_executor = executors.RunJobExecutor

    destroy_validators = [
        check_all_related_resource_are_stable,
        core_validators.StateValidator(models.Job.States.OK, models.Job.States.ERRED)
    ]
    delete_executor = executors.DeleteJobExecutor


class PythonManagementViewSet(core_mixins.AsyncExecutor, core_views.ActionsViewSet):
    lookup_field = 'uuid'
    queryset = models.PythonManagement.objects.all().order_by('pk')
    serializer_class = serializers.PythonManagementSerializer
    python_management_request_executor = executors.PythonManagementRequestExecutor

    def retrieve(self, request, *args, **kwargs):
        python_management = self.get_object()
        python_management_serializer = self.get_serializer(python_management)

        requests = SummaryQuerySet(python_management_requests_models).filter(
            python_management=python_management).order_by("-created")
        requests_serializer = serializers.SummaryPythonManagementRequestsSerializer(
            requests, many=True, context={'select_output': False})

        return response.Response(
            {'python_management': python_management_serializer.data, 'requests': requests_serializer.data})

    @ensure_atomic_transaction
    def perform_create(self, serializer):
        python_management = serializer.save()

        virtual_environments = serializer.validated_data.get('virtual_environments')

        initialization_request = PythonManagementInitializeRequest(python_management=python_management)
        initialization_request.save()

        for virtual_environment in virtual_environments:
            libraries_to_install = []
            for library in virtual_environment['installed_libraries']:
                libraries_to_install.append(library)
            PythonManagementSynchronizeRequest.objects.create(
                python_management=python_management,
                initialization_request=initialization_request,
                libraries_to_install=libraries_to_install,
                virtual_env_name=virtual_environment['name'])

        self.python_management_request_executor.execute(initialization_request, async=self.async_executor)

    @ensure_atomic_transaction
    def perform_destroy(self, persisted_python_management):
        entry_point_lock = PythonManagementBackendLockBuilder.build_entry_point_lock(persisted_python_management)
        if cache_utils.is_syncing(entry_point_lock):
            return self.build_python_management_locked_response()
        cache_utils.renew_task_status(entry_point_lock, PYTHON_MANAGEMENT_ENTRY_POINT_LOCK_TIMEOUT)

        try:
            delete_request = PythonManagementDeleteRequest(python_management=persisted_python_management)

            if not PythonManagementBackendLockingService.is_processing_allowed(delete_request):
                return self.build_python_management_locked_response()

            delete_request.save()
            self.python_management_request_executor.execute(delete_request, async=self.async_executor)
        finally:
            cache_utils.release_task_status(entry_point_lock)

    @ensure_atomic_transaction
    def perform_update(self, serializer):
        persisted_python_management = self.get_object()
        persisted_virtual_environments = persisted_python_management.virtual_environments.all()
        serializer.is_valid(raise_exception=True)

        entry_point_lock = PythonManagementBackendLockBuilder.build_entry_point_lock(persisted_python_management)

        if cache_utils.is_syncing(entry_point_lock):
            return self.build_python_management_locked_response()
        cache_utils.renew_task_status(entry_point_lock, PYTHON_MANAGEMENT_ENTRY_POINT_LOCK_TIMEOUT)

        try:
            all_transient_virtual_environments = serializer.validated_data.get('virtual_environments')

            virtual_environments_to_create, virtual_environments_to_change, removed_virtual_environments = \
                PythonManagementService.identify_changed_created_removed_envs(
                    all_transient_virtual_environments, persisted_virtual_environments)

            if cache_utils.is_syncing(
                    PythonManagementBackendLockBuilder.build_global_lock(persisted_python_management)):
                return self.build_python_management_locked_response()

            locked_virtual_envs = PythonManagementService.create_or_refuse_requests(
                self.python_management_request_executor, persisted_python_management, removed_virtual_environments,
                virtual_environments_to_change, virtual_environments_to_create)

            if locked_virtual_envs:
                return self.build_python_management_locked_response(locked_virtual_envs=locked_virtual_envs)
        finally:
            cache_utils.release_task_status(entry_point_lock)

    def build_python_management_locked_response(self, locked_virtual_envs=None):
        if not locked_virtual_envs:
            locked_virtual_envs = []
        return response.Response(
            {
                'locked': _('Python management is locked, please retry later'),
                'global_lock': not bool(locked_virtual_envs),
                'locked_virtual_envs': locked_virtual_envs
            },
            status=status.HTTP_423_LOCKED)

    @decorators.detail_route(methods=['get'])
    @ensure_atomic_transaction
    def find_virtual_environments(self, request, uuid=None):
        persisted_python_management = self.get_object()

        entry_point_lock = PythonManagementBackendLockBuilder.build_entry_point_lock(persisted_python_management)
        if cache_utils.is_syncing(entry_point_lock):
            return self.build_python_management_locked_response()
        cache_utils.renew_task_status(entry_point_lock, PYTHON_MANAGEMENT_TIMEOUT)

        try:
            find_virtual_envs_request = PythonManagementFindVirtualEnvsRequest(
                python_management=persisted_python_management)

            if not PythonManagementBackendLockingService.is_processing_allowed(find_virtual_envs_request):
                return self.build_python_management_locked_response()

            find_virtual_envs_request.save()
            self.python_management_request_executor.execute(find_virtual_envs_request, async=self.async_executor)
            return response.Response({'status': _('Find installed virtual environments process has been scheduled.')},
                                     status=status.HTTP_202_ACCEPTED)
        finally:
            cache_utils.release_task_status(entry_point_lock)

    @decorators.detail_route(url_path="find_installed_libraries/(?P<virtual_env_name>.+)", methods=['get'])
    @ensure_atomic_transaction
    def find_installed_libraries(self, request, virtual_env_name=None, uuid=None):
        persisted_python_management = self.get_object()

        entry_point_lock = PythonManagementBackendLockBuilder.build_entry_point_lock(persisted_python_management)
        if cache_utils.is_syncing(entry_point_lock):
            return self.build_python_management_locked_response()
        cache_utils.renew_task_status(entry_point_lock, PYTHON_MANAGEMENT_TIMEOUT)

        try:
            find_installed_libraries_request = PythonManagementFindInstalledLibrariesRequest(
                python_management=persisted_python_management, virtual_env_name=virtual_env_name)

            if not PythonManagementBackendLockingService.is_processing_allowed(find_installed_libraries_request):
                return self.build_python_management_locked_response()

            find_installed_libraries_request.save()
            self.python_management_request_executor.execute(find_installed_libraries_request, async=self.async_executor)
            return response.Response(
                {'status': _('Find installed libraries in virtual environment process has been scheduled.')},
                status=status.HTTP_202_ACCEPTED)
        finally:
            cache_utils.release_task_status(entry_point_lock)

    @decorators.detail_route(url_path="requests/(?P<request_uuid>.+)", methods=['get'])
    def find_request_with_output_by_uuid(self, request, uuid=None, request_uuid=None):
        requests = SummaryQuerySet(python_management_requests_models).filter(python_management=self.get_object(),
                                                                             uuid=request_uuid)
        serializer = serializers.SummaryPythonManagementRequestsSerializer(
            requests, many=True, context={'select_output': True})
        return response.Response(serializer.data)


class PipPackagesViewSet(GenericViewSet):

    @decorators.list_route(url_path="find_library_versions/(?P<queried_library_name>.+)", methods=['get'])
    def find_library_versions(self, request, queried_library_name=None):
        versions = PipService.find_versions(queried_library_name)

        return response.Response({'versions': versions})

    @decorators.list_route(url_path="autocomplete_library/(?P<queried_library_name>.+)", methods=['get'])
    def autocomplete_library_name(self, request, queried_library_name=None):
        matching_libraries = PipService.autocomplete_library_name(queried_library_name)

        return response.Response({'libraries': matching_libraries})


class WaldurSshKeysViewSet(mixins.ListModelMixin, GenericViewSet):

    def list(self, request, *args, **kwargs):
        return response.Response({'waldur_public_key': SshPublicKey.objects.get(uuid=settings.WALDUR_ANSIBLE['PUBLIC_KEY_UUID']).public_key})
