from . import views, models


def register_in(router):
    router.register(r'ansible-playbooks', views.PlaybookViewSet, base_name=models.Playbook.get_url_name())
    router.register(r'ansible-jobs', views.JobViewSet, base_name=models.Job.get_url_name())
    router.register(r'python-management', views.PythonManagementViewSet, base_name='python_management')
    router.register(r'pip-packages', views.PipPackagesViewSet, base_name='pip_packages')
    router.register(r'applications', views.ApplicationsSummaryViewSet, base_name='applications')
    router.register(r'waldur_ssh_keys', views.WaldurSshKeysViewSet, base_name='waldur_ssh_keys')