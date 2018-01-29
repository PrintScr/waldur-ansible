from waldur_ansible.backend_processing import cache_utils
from waldur_ansible.models import PythonManagementInitializeRequest, PythonManagementSynchronizeRequest, \
    PythonManagementFindVirtualEnvsRequest, PythonManagementFindInstalledLibrariesRequest, \
    PythonManagementDeleteVirtualEnvRequest, PythonManagementDeleteRequest


PIP_SYNCING_LOCK = 'waldur_syncing_pip_packages'
PIP_SYNCING_TIMEOUT = 600

# NB! Do not forget to change corresponding value on the frontend! (see PythonManagementRequest.ts)
PYTHON_MANAGEMENT_TIMEOUT = 3600
PYTHON_MANAGEMENT_ENTRY_POINT_LOCK = 'waldur_python_management_entry_point_'
PYTHON_MANAGEMENT_GLOBAL_LOCK = 'waldur_python_management_global_'
PYTHON_MANAGEMENT_VIRTUAL_ENV_SYNCING_LOCK = 'waldur_python_management_'
PYTHON_MANAGEMENT_ENTRY_POINT_LOCK_TIMEOUT = 120

class NullProcessingFinishedLockingHandler(object):
    def handle_on_processing_finished(self, request):
        pass

class RelatedToVirtualEnvRequestProcessingFinishedLockingHandler(object):
    def handle_on_processing_finished(self, request):
        cache_utils.release_task_status(
            PythonManagementBackendLockBuilder.build_related_to_virt_env_lock(
                request.python_management, request.virtual_env_name))

class GlobalRequestProcessingFinishedLockingHandler(object):
    def handle_on_processing_finished(self, request):
        cache_utils.release_task_status(
            PythonManagementBackendLockBuilder.build_global_lock(request.python_management))


class NullProcessingAllowedDecider(object):
    def is_processing_allowed(self, request):
        return True

class RelatedToVirtualEnvProcessingAllowedDecider(object):
    def is_processing_allowed(self, request):
        virtual_env_lock = PythonManagementBackendLockBuilder.build_related_to_virt_env_lock(
            request.python_management, request.virtual_env_name)
        global_lock = PythonManagementBackendLockBuilder.build_global_lock(request.python_management)
        return not cache_utils.is_syncing(virtual_env_lock) and not cache_utils.is_syncing(global_lock)

class GlobalProcessingAllowedDecider(object):
    def is_processing_allowed(self, request):
        global_lock = PythonManagementBackendLockBuilder.build_global_lock(request.python_management)
        return not cache_utils.is_syncing(global_lock)


class NullSynchronizer(object):
    def lock(self, request):
        pass

class RelatedToVirtualEnvSynchronizer(object):
    def lock(self, request):
        virtual_env_lock = PythonManagementBackendLockBuilder.build_related_to_virt_env_lock(
            request.python_management, request.virtual_env_name)
        cache_utils.renew_task_status(virtual_env_lock, PYTHON_MANAGEMENT_TIMEOUT)

class GlobalSynchronizer(object):
    def lock(self, request):
        global_lock = PythonManagementBackendLockBuilder.build_global_lock(request.python_management)
        cache_utils.renew_task_status(global_lock, PYTHON_MANAGEMENT_TIMEOUT)


class PythonManagementBackendLockingService(object):

    @staticmethod
    def lock_for_processing(request):
        synchronizer = PythonManagementBackendLockBuilder.intantiate_synchronizer(type(request))
        return synchronizer.lock(request)

    @staticmethod
    def is_processing_allowed(request):
        processing_allowed_decider = PythonManagementBackendLockBuilder.intantiate_processing_allowed_decider(type(request))
        return processing_allowed_decider.is_processing_allowed(request)

    @staticmethod
    def handle_on_processing_finished(request):
        locking_handler = PythonManagementBackendLockBuilder.intantiate_processing_finished_locking_handler(type(request))
        locking_handler.handle_on_processing_finished(request)


class PythonManagementBackendLockBuilder(object):

    # Initialize requests do not need locking - there can be no duplicates of same PythonManagement model
    REQUEST_TYPES_PROCESSING_ALLOWED_DECIDER = {
        PythonManagementInitializeRequest: NullProcessingAllowedDecider,
        PythonManagementSynchronizeRequest: RelatedToVirtualEnvProcessingAllowedDecider,
        PythonManagementFindVirtualEnvsRequest: GlobalProcessingAllowedDecider,
        PythonManagementFindInstalledLibrariesRequest: RelatedToVirtualEnvProcessingAllowedDecider,
        PythonManagementDeleteVirtualEnvRequest: RelatedToVirtualEnvProcessingAllowedDecider,
        PythonManagementDeleteRequest: GlobalProcessingAllowedDecider,
    }
    REQUEST_TYPES_SYNCHRONIZERS = {
        PythonManagementInitializeRequest: NullSynchronizer,
        PythonManagementSynchronizeRequest: RelatedToVirtualEnvSynchronizer,
        PythonManagementFindVirtualEnvsRequest: GlobalSynchronizer,
        PythonManagementFindInstalledLibrariesRequest: RelatedToVirtualEnvSynchronizer,
        PythonManagementDeleteVirtualEnvRequest: RelatedToVirtualEnvSynchronizer,
        PythonManagementDeleteRequest: GlobalSynchronizer,
    }
    REQUEST_TYPES_PROCESSING_FINISHED_LOCKING_HANDLER = {
        PythonManagementInitializeRequest: NullProcessingFinishedLockingHandler,
        PythonManagementSynchronizeRequest: RelatedToVirtualEnvRequestProcessingFinishedLockingHandler,
        PythonManagementFindVirtualEnvsRequest: GlobalRequestProcessingFinishedLockingHandler,
        PythonManagementFindInstalledLibrariesRequest: RelatedToVirtualEnvRequestProcessingFinishedLockingHandler,
        PythonManagementDeleteVirtualEnvRequest: RelatedToVirtualEnvRequestProcessingFinishedLockingHandler,
        PythonManagementDeleteRequest: GlobalRequestProcessingFinishedLockingHandler,
    }

    @staticmethod
    def intantiate_processing_allowed_decider(python_management_request_class):
        processing_allowed_decider_class = PythonManagementBackendLockBuilder.REQUEST_TYPES_PROCESSING_ALLOWED_DECIDER \
            .get(python_management_request_class)
        return processing_allowed_decider_class()

    @staticmethod
    def intantiate_processing_finished_locking_handler(python_management_request_class):
        locking_handler_class = PythonManagementBackendLockBuilder.REQUEST_TYPES_PROCESSING_FINISHED_LOCKING_HANDLER \
            .get(python_management_request_class)
        return locking_handler_class()

    @staticmethod
    def intantiate_synchronizer(python_management_request_class):
        locking_handler_class = PythonManagementBackendLockBuilder.REQUEST_TYPES_SYNCHRONIZERS \
            .get(python_management_request_class)
        return locking_handler_class()

    @staticmethod
    def build_related_to_virt_env_lock(persisted_python_management, virtual_env_name):
        return PYTHON_MANAGEMENT_VIRTUAL_ENV_SYNCING_LOCK + str(persisted_python_management.pk) + '_' + virtual_env_name

    @staticmethod
    def build_global_lock(persisted_python_management):
        return PYTHON_MANAGEMENT_GLOBAL_LOCK + str(persisted_python_management.pk)

    @staticmethod
    def build_entry_point_lock(persisted_python_management):
        return PYTHON_MANAGEMENT_ENTRY_POINT_LOCK + str(persisted_python_management.pk)
