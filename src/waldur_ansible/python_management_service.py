from waldur_ansible.backend_processing.locking_service import PythonManagementBackendLockingService
from waldur_ansible.models import PythonManagementSynchronizeRequest, \
    PythonManagementDeleteVirtualEnvRequest
from waldur_core.core.models import StateMixin


class PythonManagementService(object):
    
    @staticmethod
    def identify_changed_created_removed_envs(all_transient_virtual_environments, persisted_virtual_environments):

        removed_virtual_environments = []
        virtual_environments_to_create = []
        virtual_environments_to_change = []

        for virtual_environment in persisted_virtual_environments:
            libraries_to_remove = []
            libraries_to_install = []
            virtual_environment_name = virtual_environment.name
            corresponding_transient_virtual_environment = PythonManagementService.find_corresponding_transient_virtual_environment(
                virtual_environment_name, all_transient_virtual_environments)
            if not corresponding_transient_virtual_environment:
                removed_virtual_environments.append(virtual_environment)
            else:
                transient_libraries = corresponding_transient_virtual_environment['installed_libraries']
                persisted_libraries = virtual_environment.installed_libraries.all()

                for installed_library in persisted_libraries:
                    transient_library = PythonManagementService.find_corresponding_transient_library(
                        installed_library, transient_libraries)
                    if not transient_library:
                        libraries_to_remove.append(
                            {'name': installed_library.name, 'version': installed_library.version})

                for transient_library in transient_libraries:
                    persisted_library = PythonManagementService.find_corresponding_persisted_library(
                        transient_library, persisted_libraries)

                    if not persisted_library:
                        libraries_to_install.append(transient_library)

                if libraries_to_remove or libraries_to_install:
                    virtual_environments_to_change.append({
                        'name': virtual_environment_name,
                        'libraries_to_install': libraries_to_install,
                        'libraries_to_remove': libraries_to_remove})

        for transient_virtual_environment in all_transient_virtual_environments:
            persisted_virtual_environment = PythonManagementService.find_corresponding_persisted_virtual_environment(
                transient_virtual_environment['name'], persisted_virtual_environments)
            if not persisted_virtual_environment:
                virtual_environments_to_create.append(transient_virtual_environment)

        return virtual_environments_to_create, virtual_environments_to_change, removed_virtual_environments

    @staticmethod
    def is_global_request(request):
        return not request.virtual_env_name

    @staticmethod
    def is_request_executing(request):
        return request.state != StateMixin.States.OK and request.state != StateMixin.States.ERRED

    @staticmethod
    def find_corresponding_persisted_library(transient_library, persisted_libraries):
        for persisted_library in persisted_libraries:
            if persisted_library.name == transient_library['name'] and persisted_library.version == transient_library['version']:
                return persisted_library
        return None

    @staticmethod
    def find_corresponding_transient_library(persisted_library, transient_libraries):
        for transient_library in transient_libraries:
            if transient_library['name'] == persisted_library.name and transient_library['version'] == persisted_library.version:
                return transient_library
        return None

    @staticmethod
    def find_corresponding_persisted_virtual_environment(virtual_environment_name, persisted_virtual_environments):
        for persisted_virtual_environment in persisted_virtual_environments:
            if persisted_virtual_environment.name == virtual_environment_name:
                return persisted_virtual_environment
        return None

    @staticmethod
    def find_corresponding_transient_virtual_environment(virtual_environment_name,
                                                         transient_virtual_environments):
        for transient_virtual_environment in transient_virtual_environments:
            if transient_virtual_environment['name'] == virtual_environment_name:
                return transient_virtual_environment
        return None


    @staticmethod
    def create_or_refuse_requests(python_management_request_executor, persisted_python_management, removed_virtual_environments,
        virtual_environments_to_change, virtual_environments_to_create):
        locked_virtual_envs = []
        for virtual_environment_to_create in virtual_environments_to_create:
            sync_request = PythonManagementSynchronizeRequest(
                python_management=persisted_python_management,
                libraries_to_install=virtual_environment_to_create['installed_libraries'],
                virtual_env_name=virtual_environment_to_create['name'])

            PythonManagementService.create_or_refuse_request(python_management_request_executor, locked_virtual_envs, sync_request)

        for removed_virtual_environment in removed_virtual_environments:
            delete_virt_env_request = PythonManagementDeleteVirtualEnvRequest(
                python_management=persisted_python_management,
                virtual_env_name=removed_virtual_environment.name)

            PythonManagementService.create_or_refuse_request(python_management_request_executor, locked_virtual_envs, delete_virt_env_request)

        for virtual_environment_to_change in virtual_environments_to_change:
            sync_request = PythonManagementSynchronizeRequest(
                python_management=persisted_python_management,
                libraries_to_install=virtual_environment_to_change['libraries_to_install'],
                libraries_to_remove=virtual_environment_to_change['libraries_to_remove'],
                virtual_env_name=virtual_environment_to_change['name'])

            PythonManagementService.create_or_refuse_request(python_management_request_executor, locked_virtual_envs, sync_request)

        return locked_virtual_envs

    @staticmethod
    def create_or_refuse_request(python_management_request_executor, locked_virtual_envs, sync_request):
        if PythonManagementBackendLockingService.is_processing_allowed(sync_request):
            sync_request.save()
            python_management_request_executor.execute(sync_request, async=True)
        else:
            locked_virtual_envs.append(sync_request.virtual_env_name)
