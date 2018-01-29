from __future__ import unicode_literals

import datetime
import re
from zipfile import is_zipfile, ZipFile

from django.db import transaction
from django.utils.translation import ugettext_lazy as _
from rest_framework import serializers, exceptions
from waldur_ansible.models import PythonManagement, Job, PythonManagementInitializeRequest, \
    PythonManagementSynchronizeRequest, PythonManagementFindVirtualEnvsRequest, \
    PythonManagementFindInstalledLibrariesRequest, PythonManagementDeleteRequest, PythonManagementDeleteVirtualEnvRequest
from waldur_ansible.utils import execute_safely
from waldur_core.core import models as core_models
from waldur_core.core.models import StateMixin
from waldur_core.core.serializers import AugmentedSerializerMixin, JSONField, BaseSummarySerializer
from waldur_core.core.state_utils import StateUtils
from waldur_core.core.utils import get_detail_view_name
from waldur_core.structure.permissions import _has_admin_access
from waldur_core.structure.serializers import PermissionFieldFilteringMixin
from waldur_openstack.openstack_tenant import models as openstack_models

from . import models

# TODO use immutable dictionary
REQUEST_TYPES_PLAIN_NAMES = {
    PythonManagement: 'overall',
    PythonManagementInitializeRequest: 'initialization',
    PythonManagementSynchronizeRequest: 'synchronization',
    PythonManagementFindVirtualEnvsRequest: 'virtual_envs_search',
    PythonManagementFindInstalledLibrariesRequest: 'installed_libraries_search',
    PythonManagementDeleteRequest: 'python_management_deletion',
    PythonManagementDeleteVirtualEnvRequest: 'virtual_environment_deletion',
}


class PlaybookParameterSerializer(serializers.ModelSerializer):
    name = serializers.RegexField('^[\w]+$')

    class Meta(object):
        model = models.PlaybookParameter
        fields = ('name', 'description', 'required', 'default')


class PlaybookSerializer(AugmentedSerializerMixin, serializers.HyperlinkedModelSerializer):
    archive = serializers.FileField(write_only=True)
    parameters = PlaybookParameterSerializer(many=True)

    class Meta(object):
        model = models.Playbook
        fields = ('url', 'uuid', 'name', 'description', 'archive', 'entrypoint', 'parameters', 'image')
        protected_fields = ('entrypoint', 'parameters', 'archive')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
        }

    def validate_archive(self, value):
        if not is_zipfile(value):
            raise serializers.ValidationError(_('ZIP file must be uploaded.'))
        elif not value.name.endswith('.zip'):
            raise serializers.ValidationError(_("File must have '.zip' extension."))

        zip_file = ZipFile(value)
        invalid_file = zip_file.testzip()
        if invalid_file is not None:
            raise serializers.ValidationError(
                _('File {filename} in archive {archive_name} has an invalid type.'.format(
                    filename=invalid_file, archive_name=zip_file.filename)))

        return value

    def validate(self, attrs):
        if self.instance:
            return attrs

        zip_file = ZipFile(attrs['archive'])
        entrypoint = attrs['entrypoint']
        if entrypoint not in zip_file.namelist():
            raise serializers.ValidationError(
                _('Failed to find entrypoint {entrypoint} in archive {archive_name}.'.format(
                    entrypoint=entrypoint, archive_name=zip_file.filename)))

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        parameters_data = validated_data.pop('parameters')
        archive = validated_data.pop('archive')
        validated_data['workspace'] = models.Playbook.generate_workspace_path()

        zip_file = ZipFile(archive)
        zip_file.extractall(validated_data['workspace'])
        zip_file.close()

        playbook = models.Playbook.objects.create(**validated_data)
        for parameter_data in parameters_data:
            models.PlaybookParameter.objects.create(playbook=playbook, **parameter_data)

        return playbook


class JobSerializer(AugmentedSerializerMixin,
                    PermissionFieldFilteringMixin,
                    serializers.HyperlinkedModelSerializer):
    service_project_link = serializers.HyperlinkedRelatedField(
        lookup_field='pk',
        view_name='openstacktenant-spl-detail',
        queryset=openstack_models.OpenStackTenantServiceProjectLink.objects.all(),
    )
    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        lookup_field='uuid',
        view_name='openstacktenant-detail',
        read_only=True,
    )
    service_name = serializers.ReadOnlyField(source='service_project_link.service.settings.name')
    service_uuid = serializers.ReadOnlyField(source='service_project_link.service.uuid')
    ssh_public_key = serializers.HyperlinkedRelatedField(
        lookup_field='uuid',
        view_name='sshpublickey-detail',
        queryset=core_models.SshPublicKey.objects.all(),
        required=True,
    )
    ssh_public_key_name = serializers.ReadOnlyField(source='ssh_public_key.name')
    ssh_public_key_uuid = serializers.ReadOnlyField(source='ssh_public_key.uuid')
    project = serializers.HyperlinkedRelatedField(
        source='service_project_link.project',
        lookup_field='uuid',
        view_name='project-detail',
        read_only=True,
    )
    project_name = serializers.ReadOnlyField(source='service_project_link.project.name')
    project_uuid = serializers.ReadOnlyField(source='service_project_link.project.uuid')
    playbook = serializers.HyperlinkedRelatedField(
        lookup_field='uuid',
        view_name=get_detail_view_name(models.Playbook),
        queryset=models.Playbook.objects.all(),
    )
    playbook_name = serializers.ReadOnlyField(source='playbook.name')
    playbook_uuid = serializers.ReadOnlyField(source='playbook.uuid')
    playbook_image = serializers.FileField(source='playbook.image', read_only=True)
    playbook_description = serializers.ReadOnlyField(source='playbook.description')
    arguments = JSONField(default={})
    state = serializers.SerializerMethodField()
    tag = serializers.SerializerMethodField()

    class Meta(object):
        model = models.Job
        fields = ('url', 'uuid', 'name', 'description',
                  'service_project_link', 'service', 'service_name', 'service_uuid',
                  'ssh_public_key', 'ssh_public_key_name', 'ssh_public_key_uuid',
                  'project', 'project_name', 'project_uuid',
                  'playbook', 'playbook_name', 'playbook_uuid',
                  'playbook_image', 'playbook_description',
                  'arguments', 'state', 'output', 'created', 'modified', 'tag')
        read_only_fields = ('output', 'created', 'modified')
        protected_fields = ('service_project_link', 'ssh_public_key', 'playbook', 'arguments')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
        }

    def get_filtered_field_names(self):
        return 'project', 'service_project_link', 'ssh_public_key'

    def get_state(self, obj):
        return obj.get_state_display()

    def get_tag(self, obj):
        return obj.get_tag()

    def check_project(self, attrs):
        if self.instance:
            project = self.instance.service_project_link.project
        else:
            project = attrs['service_project_link'].project
        if not _has_admin_access(self.context['request'].user, project):
            raise exceptions.PermissionDenied()

    def check_arguments(self, attrs):
        playbook = self.instance.playbook if self.instance else attrs['playbook']
        arguments = attrs['arguments']
        parameter_names = playbook.parameters.all().values_list('name', flat=True)
        for argument in arguments.keys():
            if argument not in parameter_names and argument != 'project_uuid':
                raise serializers.ValidationError(_('Argument %s is not listed in playbook parameters.' % argument))

        if playbook.parameters.exclude(name__in=arguments.keys()).filter(required=True, default__exact='').exists():
            raise serializers.ValidationError(_('Not all required playbook parameters were specified.'))

        unfilled_parameters = playbook.parameters.exclude(name__in=arguments.keys())
        for parameter in unfilled_parameters:
            if parameter.default:
                arguments[parameter.name] = parameter.default

    def check_subnet(self, attrs):
        if not self.instance:
            settings = attrs['service_project_link'].service.settings
            if not openstack_models.SubNet.objects.filter(settings=settings).exists():
                raise serializers.ValidationError(_('Selected OpenStack provider does not have any subnet yet.'))
            else:
                attrs['subnet'] = openstack_models.SubNet.objects.filter(settings=settings).first()

    def validate(self, attrs):
        if not self.instance:
            attrs['user'] = self.context['request'].user

        self.check_project(attrs)
        self.check_arguments(attrs)
        self.check_subnet(attrs)
        return attrs


class InstalledPackageSerializer(AugmentedSerializerMixin, serializers.HyperlinkedModelSerializer):
    class Meta(object):
        model = models.InstalledLibrary
        fields = ('name', 'version', 'uuid',)
        read_only_fields = ('uuid',)
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
        }

class VirtualEnvironmentSerializer(AugmentedSerializerMixin, serializers.HyperlinkedModelSerializer):
    installed_libraries = InstalledPackageSerializer(many=True)
    class Meta(object):
        model = models.VirtualEnvironment
        fields = ('name', 'uuid', 'installed_libraries',)
        read_only_fields = ('uuid',)
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
        }

class PythonManagementRequestMixin(AugmentedSerializerMixin, serializers.HyperlinkedModelSerializer):
    request_type = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    output = serializers.SerializerMethodField()

    class Meta(object):
        model = NotImplemented
        fields = ('uuid', 'output', 'state','created', 'modified','request_type',)
        read_only_fields = ('uuid', 'output', 'state','created', 'modified','request_type',)
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
        }

    def get_output(self, obj):
        if self.context.get('select_output'):
            return obj.output
        else:
            return None

    def get_request_type(self, obj):
        return REQUEST_TYPES_PLAIN_NAMES.get(type(obj))

    def get_state(self, obj):
        return StateUtils.to_human_readable_state(obj.state)

class PythonManagementInitializeRequestSerializer(PythonManagementRequestMixin):

    class Meta(PythonManagementRequestMixin.Meta):
        model = models.PythonManagementInitializeRequest

class PythonManagementFindVirtualEnvsRequestSerializer(PythonManagementRequestMixin):
    class Meta(PythonManagementRequestMixin.Meta):
        model = models.PythonManagementFindVirtualEnvsRequest

class PythonManagementFindInstalledLibrariesRequestSerializer(PythonManagementRequestMixin):
    class Meta(PythonManagementRequestMixin.Meta):
        model = models.PythonManagementFindInstalledLibrariesRequest
        fields = PythonManagementRequestMixin.Meta.fields + ('virtual_env_name',)

class PythonManagementDeleteRequestSerializer(PythonManagementRequestMixin):
    class Meta(PythonManagementRequestMixin.Meta):
        model = models.PythonManagementDeleteRequest

class PythonManagementDeleteVirtualEnvRequestSerializer(PythonManagementRequestMixin):
    class Meta(PythonManagementRequestMixin.Meta):
        model = models.PythonManagementDeleteVirtualEnvRequest
        fields = PythonManagementRequestMixin.Meta.fields + ('virtual_env_name',)

class PythonManagementSynchronizeRequestSerializer(#PermissionFieldFilteringMixin,
                                                   PythonManagementRequestMixin):
    libraries_to_install = JSONField(default={})
    libraries_to_remove = JSONField(default={})

    class Meta(PythonManagementRequestMixin.Meta):
        model = models.PythonManagementSynchronizeRequest
        fields = PythonManagementRequestMixin.Meta.fields \
            + ('libraries_to_install', 'libraries_to_remove', 'virtual_env_name')

class PythonManagementSerializer(AugmentedSerializerMixin,
                    PermissionFieldFilteringMixin,
                    serializers.HyperlinkedModelSerializer):

    REQUEST_IN_PROGRESS_STATES = (StateMixin.States.CREATION_SCHEDULED, StateMixin.States.CREATING)

    service_project_link = serializers.HyperlinkedRelatedField(
        lookup_field='pk',
        view_name='openstacktenant-spl-detail',
        queryset=openstack_models.OpenStackTenantServiceProjectLink.objects.all(),
    )
    requests_states = serializers.SerializerMethodField()
    virtual_environments = VirtualEnvironmentSerializer(many=True)

    class Meta(object):
        model = models.PythonManagement
        fields = ('uuid', 'instance', 'service_project_link', 'virtual_envs_dir_path',
                  'requests_states', 'created', 'modified', 'virtual_environments',)
        protected_fields = ('service_project_link',)
        read_only_fields = ('request_states', 'created', 'modified',)
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
            'instance': {'lookup_field': 'uuid', 'view_name': 'openstacktenant-instance-detail'},
        }

    def get_filtered_field_names(self):
        return 'service_project_link'

    def get_requests_states(self, python_management):
        states = []
        initialize_request = execute_safely(
            lambda: PythonManagementInitializeRequest.objects.filter(python_management=python_management).latest('id'))
        if initialize_request and self.is_in_progress_or_errored(initialize_request):
            return [self.build_state(initialize_request)]

        states.extend(self.build_search_requests_states(python_management))
        states.extend(self.build_synchronize_requests_states(python_management))

        if not states:
            states.append(self.build_state(python_management, state=StateMixin.States.OK))

        return states

    def build_search_requests_states(self, python_management):
        states = []
        states.extend(
            self.get_state(
                execute_safely(
                    lambda: PythonManagementFindVirtualEnvsRequest.objects
                        .filter(python_management=python_management).latest('id'))))
        states.extend(
            self.get_state(
                execute_safely(
                    lambda: PythonManagementFindInstalledLibrariesRequest.objects
                        .filter(python_management=python_management).latest('id'))))
        return states

    def get_state(self, request):
        if request and  self.is_in_progress_or_errored(request):
            return [self.build_state(request)]
        else:
            return []

    def build_synchronize_requests_states(self, python_management):
        states = []
        synchronize_requests = PythonManagementSynchronizeRequest.objects.filter(python_management=python_management) \
            .order_by('-id')
        last_synchronize_request_group = self.get_last_synchronize_requests_group(synchronize_requests)
        for synchronize_request in last_synchronize_request_group:
            if self.is_in_progress_or_errored(synchronize_request):
                states.append(self.build_state(synchronize_request))
        return states

    def get_last_synchronize_requests_group(self, synchronize_requests):
        last_synchronize_request_group = []

        last_synchronize_request_time = None
        for synchronize_request in synchronize_requests:
            if not last_synchronize_request_time:
                last_synchronize_request_time = synchronize_request.created - datetime.timedelta(minutes=1)
            if synchronize_request.created < last_synchronize_request_time:
                break
            last_synchronize_request_group.append(synchronize_request)

        return last_synchronize_request_group

    def is_in_progress_or_errored(self, request):
        return request.state in PythonManagementSerializer.REQUEST_IN_PROGRESS_STATES \
               or request.state == StateMixin.States.ERRED

    def build_state(self, request, state=None):
        request_state = state if state else request.state
        return {
            'state': StateUtils.to_human_readable_state(request_state),
            'request_type': REQUEST_TYPES_PLAIN_NAMES.get(type(request))
        }

    @transaction.atomic
    def create(self, validated_data):
        python_management = PythonManagement(
            user=validated_data.get('user'),
            instance=validated_data.get('instance'),
            service_project_link=validated_data.get('service_project_link'),
            virtual_envs_dir_path=validated_data.get('virtual_envs_dir_path'))
        python_management.save()
        return python_management

    def validate(self, attrs):
        if not self.instance:
            attrs['user'] = self.context['request'].user

        self.validate_virtual_envs_directory_name(attrs)
        self.validate_virtual_envs_names(attrs)

        self.check_project_permissions(attrs)
        return attrs

    def validate_virtual_envs_names(self, attrs):
        valid_format = re.compile("^[a-zA-Z0-9\-_]*$")
        for i in range(0, len(attrs['virtual_environments'])):
            if not valid_format.match(attrs['virtual_environments'][i]['name']):
                raise exceptions.ValidationError(
                    {'virtual_env['+str(i)+']': _('Virtual environment name has invalid format!')})

    def validate_virtual_envs_directory_name(self, attrs):
        valid_format = re.compile("^[a-zA-Z0-9\-_]*$")
        if not valid_format.match(attrs['virtual_envs_dir_path']):
            raise exceptions.ValidationError(
                {'virtual_envs_dir_path': _('Virtual environments root directory has invalid format!')})

    def check_project_permissions(self, attrs):
        if self.instance:
            project = self.instance.service_project_link.project
        else:
            project = attrs['service_project_link'].project

        if not _has_admin_access(self.context['request'].user, project):
            raise exceptions.PermissionDenied()

class SummaryApplicationSerializer(BaseSummarySerializer):
    @classmethod
    def get_serializer(cls, model):
        if model is PythonManagement:
            return PythonManagementSerializer
        elif model is Job:
            return JobSerializer

class SummaryPythonManagementRequestsSerializer(BaseSummarySerializer):
    @classmethod
    def get_serializer(cls, model):
        if model is PythonManagementInitializeRequest:
            return PythonManagementInitializeRequestSerializer
        elif model is PythonManagementSynchronizeRequest:
            return PythonManagementSynchronizeRequestSerializer
        elif model is PythonManagementFindVirtualEnvsRequest:
            return PythonManagementFindVirtualEnvsRequestSerializer
        elif model is PythonManagementFindInstalledLibrariesRequest:
            return PythonManagementFindInstalledLibrariesRequestSerializer
        elif model is PythonManagementDeleteRequest:
            return PythonManagementDeleteRequestSerializer
        elif model is PythonManagementDeleteVirtualEnvRequest:
            return PythonManagementDeleteVirtualEnvRequestSerializer