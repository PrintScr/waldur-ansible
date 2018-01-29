
import json
import os
import subprocess  # nosec

import logging
import six
from django.conf import settings
from waldur_ansible.backend_processing.additional_extra_args_builders import build_sync_request_extra_args, \
    build_additional_extra_args
from waldur_ansible.backend_processing.exceptions import AnsibleBackendError
from waldur_ansible.backend_processing.extracted_information_handler import NullExtractedInformationHandler, \
    InstalledLibrariesExtractedInformationHandler, PythonManagementFindVirtualEnvsRequestExtractedInformationHandler, \
    PythonManagementDeletionRequestExtractedInformationHandler
from waldur_ansible.backend_processing.locking_service import PythonManagementBackendLockingService
from waldur_ansible.backend_processing.output_lines_post_processors import NullOutputLinesPostProcessor, \
    InstalledLibrariesOutputLinesPostProcessor, InstalledVirtualEnvironmentsOutputLinesPostProcessor
from waldur_ansible.constants import PythonManagementConstants
from waldur_ansible.executors import PythonManagementRequestExecutor
from waldur_ansible.models import PythonManagementInitializeRequest, PythonManagementSynchronizeRequest, \
    PythonManagementFindVirtualEnvsRequest, PythonManagementFindInstalledLibrariesRequest, \
    PythonManagementDeleteVirtualEnvRequest, PythonManagementDeleteRequest
from waldur_core.core.views import RefreshTokenMixin

logger = logging.getLogger(__name__)

class PythonManagementBackend(object):

    def process_python_management_request(self, python_management_request):
        PythonManagementBackendHelper.process_request(python_management_request)


class PythonManagementInitializationBackend(PythonManagementBackend):

    def process_python_management_request(self, python_management_initialization_request):
        super(PythonManagementInitializationBackend, self).process_python_management_request(python_management_initialization_request)

        for synchronization_request in python_management_initialization_request.sychronization_requests.all():
            PythonManagementRequestExecutor.execute(synchronization_request, async=True)

class PythonManagementBackendHelper(object):
    REQUEST_TYPES_PLAYBOOKS_CORRESPONDENCE = {
        PythonManagementInitializeRequest: PythonManagementConstants.INSTALL_PYTHON_ENVIRONMENT,
        PythonManagementSynchronizeRequest: PythonManagementConstants.SYNCHRONIZE_PACKAGES,
        PythonManagementFindVirtualEnvsRequest: PythonManagementConstants.FIND_INSTALLED_VIRTUAL_ENVIRONMENTS,
        PythonManagementFindInstalledLibrariesRequest: PythonManagementConstants.FIND_INSTALLED_LIBRARIES_FOR_VIRTUAL_ENVIRONMENT,
        PythonManagementDeleteVirtualEnvRequest: PythonManagementConstants.DELETE_VIRTUAL_ENVIRONMENT,
        PythonManagementDeleteRequest: PythonManagementConstants.DELETE_PYTHON_ENVIRONMENT,
    }

    REQUEST_TYPES_EXTRA_ARGS_CORRESPONDENCE = {
        PythonManagementInitializeRequest: None,
        PythonManagementSynchronizeRequest: build_sync_request_extra_args,
        PythonManagementFindVirtualEnvsRequest: build_additional_extra_args,
        PythonManagementFindInstalledLibrariesRequest: build_additional_extra_args,
        PythonManagementDeleteVirtualEnvRequest: build_additional_extra_args,
        PythonManagementDeleteRequest: None,
    }

    REQUEST_TYPES_POST_PROCESSOR_CORRESPONDENCE = {
        PythonManagementInitializeRequest: NullOutputLinesPostProcessor,
        PythonManagementSynchronizeRequest: InstalledLibrariesOutputLinesPostProcessor,
        PythonManagementFindVirtualEnvsRequest: InstalledVirtualEnvironmentsOutputLinesPostProcessor,
        PythonManagementFindInstalledLibrariesRequest: InstalledLibrariesOutputLinesPostProcessor,
        PythonManagementDeleteVirtualEnvRequest: NullOutputLinesPostProcessor,
        PythonManagementDeleteRequest: NullOutputLinesPostProcessor,
    }

    REQUEST_TYPES_HANDLERS_CORRESPONDENCE = {
        PythonManagementInitializeRequest: NullExtractedInformationHandler,
        PythonManagementSynchronizeRequest: InstalledLibrariesExtractedInformationHandler,
        PythonManagementFindVirtualEnvsRequest: PythonManagementFindVirtualEnvsRequestExtractedInformationHandler,
        PythonManagementFindInstalledLibrariesRequest: InstalledLibrariesExtractedInformationHandler,
        PythonManagementDeleteVirtualEnvRequest: NullExtractedInformationHandler,
        PythonManagementDeleteRequest: PythonManagementDeletionRequestExtractedInformationHandler,
    }

    @staticmethod
    def process_request(python_management_request):
        if not PythonManagementBackendLockingService.is_processing_allowed(python_management_request):
            python_management_request.output = \
                'Whole environment or the particular virutal environnment is now being processed, request cannot be executed!'
            python_management_request.save(update_fields=['output'])
            return
        try:
            PythonManagementBackendLockingService.lock_for_processing(python_management_request)

            command = PythonManagementBackendHelper.build_command(python_management_request)
            command_str = ' '.join(command)

            logger.debug('Executing command "%s".', command_str)
            env = dict(
                os.environ,
                ANSIBLE_LIBRARY=settings.WALDUR_ANSIBLE['ANSIBLE_LIBRARY'],
                ANSIBLE_HOST_KEY_CHECKING='False',
            )
            request_class = type(python_management_request)
            lines_post_processor_instance = PythonManagementBackendHelper.intantiate_line_post_processor_class(
                request_class)
            extracted_information_handler = PythonManagementBackendHelper.intantiate_extracted_information_handler_class(
                request_class)
            try:
                for output_line in PythonManagementBackendHelper.process_output_iterator(command, env):
                    python_management_request.output += output_line
                    python_management_request.save(update_fields=['output'])
                    lines_post_processor_instance.post_process_line(output_line)
            except subprocess.CalledProcessError as e:
                logger.info('Failed to execute command "%s".', command_str)
                six.reraise(AnsibleBackendError, e)
            else:
                logger.info('Command "%s" was successfully executed.', command_str)
                extracted_information_handler.handle_extracted_information(
                    python_management_request, lines_post_processor_instance)
        finally:
            PythonManagementBackendLockingService.handle_on_processing_finished(python_management_request)

    @staticmethod
    def intantiate_line_post_processor_class(python_management_request_class):
        lines_post_processor_class = PythonManagementBackendHelper.REQUEST_TYPES_POST_PROCESSOR_CORRESPONDENCE \
            .get(python_management_request_class)
        lines_post_processor_instance = lines_post_processor_class()
        return lines_post_processor_instance

    @staticmethod
    def intantiate_extracted_information_handler_class(python_management_request_class):
        extracted_information_handler_class = PythonManagementBackendHelper.REQUEST_TYPES_HANDLERS_CORRESPONDENCE \
            .get(python_management_request_class)
        extracted_information_handler_instance = extracted_information_handler_class()
        return extracted_information_handler_instance

    @staticmethod
    def process_output_iterator(command, env):
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1, env=env)
        for stdout_line in iter(process.stdout.readline, ""):
            yield stdout_line
        process.stdout.close()
        return_code = process.wait()
        if return_code:
            raise subprocess.CalledProcessError(return_code, command)

    @staticmethod
    def build_command(python_management_request):
        playbook_path = settings.WALDUR_ANSIBLE.get('PYTHON_MANAGEMENT_PLAYBOOKS_DIRECTORY') \
            + PythonManagementBackendHelper.REQUEST_TYPES_PLAYBOOKS_CORRESPONDENCE.get(type(python_management_request)) \
            + '.yml'
        PythonManagementBackendHelper.ensure_playbook_exists_or_raise(playbook_path)

        command = [settings.WALDUR_ANSIBLE.get('PLAYBOOK_EXECUTION_COMMAND', 'ansible-playbook')]

        if settings.WALDUR_ANSIBLE.get('PLAYBOOK_ARGUMENTS'):
            command.extend(settings.WALDUR_ANSIBLE.get('PLAYBOOK_ARGUMENTS'))

        extraVars = PythonManagementBackendHelper.build_extra_vars(python_management_request)
        command.extend(['--extra-vars', extraVars])

        command.extend(['--ssh-common-args', '-o UserKnownHostsFile=/dev/null'])

        return command + [playbook_path]

    @staticmethod
    def ensure_playbook_exists_or_raise(playbook_path):
        if not os.path.exists(playbook_path):
            raise AnsibleBackendError('Playbook %s does not exist.' % playbook_path)

    @staticmethod
    def build_extra_vars(python_management_request):
        extraVars = PythonManagementBackendHelper.build_common_extra_vars(python_management_request)

        additional_extra_args_building_function = PythonManagementBackendHelper.REQUEST_TYPES_EXTRA_ARGS_CORRESPONDENCE.get(type(python_management_request))

        if additional_extra_args_building_function:
            extraVars.update(additional_extra_args_building_function(python_management_request))

        return json.dumps(extraVars)

    @staticmethod
    def build_common_extra_vars(python_management_request):
        python_management = python_management_request.python_management
        return dict(
            api_url=settings.WALDUR_ANSIBLE['API_URL'],
            access_token=RefreshTokenMixin().refresh_token(python_management.user).key,
            project_uuid=python_management.service_project_link.project.uuid.hex,
            provider_uuid=python_management.service_project_link.service.uuid.hex,
            private_key_path=settings.WALDUR_ANSIBLE['PRIVATE_KEY_PATH'],
            public_key_uuid=settings.WALDUR_ANSIBLE['PUBLIC_KEY_UUID'],
            default_system_user=PythonManagementBackendHelper.decide_default_system_user(python_management.instance.image_name),
            # IMPORTANT
            instance_uuid=python_management.instance.uuid.hex,
            virtual_envs_dir_path=python_management.virtual_envs_dir_path,
        )

    @staticmethod
    def decide_default_system_user(image_name):
        if "debian" in image_name:
            return "debian"
        elif "ubuntu" in image_name:
            return "ubuntu"
        else:
            raise ValueError("Cannot find default user for the installed image")
