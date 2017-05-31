from django.apps import AppConfig
from django.db.models import signals

from . import handlers


class AnsibleConfig(AppConfig):
    name = 'waldur_ansible'
    verbose_name = 'Waldur Ansible'

    def ready(self):
        Playbook = self.get_model('Playbook')

        signals.pre_delete.connect(
            handlers.cleanup_playbook,
            sender=Playbook,
            dispatch_uid='waldur_ansible.handlers.cleanup_playbook',
        )
