from django_filters.rest_framework import DjangoFilterBackend
from django.utils.translation import ugettext_lazy as _

from waldur_core.core import exceptions as core_exceptions
from waldur_core.core import mixins as core_mixins
from waldur_core.core import validators as core_validators
from waldur_core.core import views as core_views
from waldur_core.structure import models as structure_models
from waldur_core.structure import views as structure_views
from waldur_core.structure.filters import GenericRoleFilter
from waldur_core.structure.metadata import ActionsMetadata
from waldur_core.structure.permissions import is_staff, is_administrator

from . import filters, models, serializers, executors


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


def get_project_jobs_count(project):
    return models.Job.objects.filter(service_project_link__project=project).count()

structure_views.ProjectCountersView.register_counter('ansible', get_project_jobs_count)
