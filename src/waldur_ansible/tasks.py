import errno
import logging
from shutil import rmtree

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(name='waldur_ansible.tasks.delete_playbook_workspace')
def delete_playbook_workspace(workspace_path):
    logger.debug('Deleting playbook workspace %s.', workspace_path)
    try:
        rmtree(workspace_path)
    except OSError as e:
        if e.errno == errno.ENOENT:
            logger.info('Playbook workspace %s does not exist.', workspace_path)
        else:
            logger.warning('Failed to delete playbook workspace %s.', workspace_path)
            raise
    else:
        logger.info('Playbook workspace %s has been deleted.', workspace_path)


@shared_task(name='waldur_ansible.sync_pip_packages')
def sync_pip_packages():
    """
    This task is used by Celery beat in order to periodically
    schedule available PIP packages synchronization.
    """
    schedule_sync()

def schedule_sync():
    """
    This function calls task only if it is not already running.
    The goal is to avoid race conditions during concurrent task execution.
    """
    from waldur_ansible.backend_processing import cache_utils
    from waldur_ansible.backend_processing.locking_service import PIP_SYNCING_LOCK, PIP_SYNCING_TIMEOUT
    if settings.WALDUR_ANSIBLE.get('SYNC_PIP_PACKAGES_TASK_ENABLED') or cache_utils.is_syncing(PIP_SYNCING_LOCK):
        return

    cache_utils.renew_task_status(PIP_SYNCING_LOCK, PIP_SYNCING_TIMEOUT)
    _sync_pip_packages.apply_async(countdown=10)

@shared_task()
def _sync_pip_packages():
    """
    This task actually calls backend. It is called asynchronously
    either by signal handler or Celery beat schedule.
    """
    from waldur_ansible.backend_processing.pip_backend import PipPackageListBackend
    PipPackageListBackend().synchronize_pip_package_list()
