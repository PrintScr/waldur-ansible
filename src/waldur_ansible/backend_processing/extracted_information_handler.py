from waldur_ansible.backend_processing.locking_service import PythonManagementBackendLockingService
from waldur_ansible.executors import PythonManagementRequestExecutor
from waldur_ansible.models import VirtualEnvironment, PythonManagementFindInstalledLibrariesRequest, InstalledLibrary
from waldur_ansible.utils import execute_safely


class InstalledLibrariesExtractedInformationHandler(object):
    def handle_extracted_information(self, request, lines_post_processor):
        self.persist_installed_libraries_in_db(
            request.python_management,
            request.virtual_env_name,
            lines_post_processor.installed_libraries_after_modifications)

    def persist_installed_libraries_in_db(self, python_management, virtual_environment_name, existing_packages):
        virtual_environment = execute_safely(
            lambda: python_management.virtual_environments.get(name=virtual_environment_name))
        if virtual_environment and not existing_packages:
            virtual_environment.delete()
            return

        if not virtual_environment:
            virtual_environment = VirtualEnvironment(name=virtual_environment_name, python_management=python_management)
            virtual_environment.save()

        persisted_packages = virtual_environment.installed_libraries.all()

        self.save_newly_installed_libraries(
            existing_packages, persisted_packages, virtual_environment)

        self.delete_removed_libs(existing_packages, persisted_packages)

    def delete_removed_libs(self, existing_packages, persisted_packages):
        for persisted_package in persisted_packages:
            if not self.isPackagePresent(persisted_package, existing_packages):
                persisted_package.delete()

    def save_newly_installed_libraries(self, existing_packages, persisted_installed_libraries, virtual_environment):
        for installed_package in existing_packages:
            if not self.isPackagePresent(installed_package, persisted_installed_libraries):
                InstalledLibrary.objects.create(
                    name=installed_package.name, version=installed_package.version,
                    virtual_environment=virtual_environment)

    def isPackagePresent(self, package, packages_list):
        for p in packages_list:
            if package.name == p.name and package.version == p.version:
                return True
        return False

class PythonManagementDeletionRequestExtractedInformationHandler(object):
    def handle_extracted_information(self, request, lines_post_processor):
        request.python_management.delete()

class PythonManagementFindVirtualEnvsRequestExtractedInformationHandler(object):
    def handle_extracted_information(self, request, lines_post_processor):
        PythonManagementBackendLockingService.handle_on_processing_finished(request)
        for virtual_env_name in lines_post_processor.installed_virtual_environments:
            find_libs_request = PythonManagementFindInstalledLibrariesRequest.objects.create(
                python_management=request.python_management, virtual_env_name=virtual_env_name)
            PythonManagementRequestExecutor.execute(find_libs_request, async=True)

class NullExtractedInformationHandler(object):
    def handle_extracted_information(self, request, lines_post_processor):
        pass
