from nodeconductor.core import NodeConductorExtension


class AnsibleExtension(NodeConductorExtension):

    class Settings:
        WALDUR_ANSIBLE = {
            'PLAYBOOKS_DIR_NAME': 'ansible_playbooks',
            'PRESERVE_PLAYBOOKS_AFTER_DELETION': False,
        }

    @staticmethod
    def django_app():
        return 'waldur_ansible'

    @staticmethod
    def rest_urls():
        from .urls import register_in
        return register_in
