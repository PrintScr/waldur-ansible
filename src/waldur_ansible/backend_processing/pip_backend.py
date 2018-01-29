import urllib2

import redis
from bs4 import BeautifulSoup
from waldur_ansible.backend_processing import cache_utils
from waldur_ansible.backend_processing.locking_service import PIP_SYNCING_LOCK
from waldur_ansible.constants import PythonManagementConstants


class PipPackageListBackend(object):
    def synchronize_pip_package_list(self):
        try:
            parser = BeautifulSoup(urllib2.urlopen("https://pypi.python.org/simple/").read(), "lxml")
            package_names = parser.findAll('a')

            r = redis.StrictRedis(host='localhost', port=6379, db=0)

            for package_link in package_names:
                package_name = package_link.text.lower()
                current_package_name = ""

                package_name_except_for_the_last_symbol_range = range(0, len(package_name) - 1)
                for k in package_name_except_for_the_last_symbol_range:
                    current_package_name += package_name[k]
                    r.zadd(PythonManagementConstants.PIP_LIBRARIES_HASH_TABLE_NAME, 0, current_package_name)

                r.zadd(PythonManagementConstants.PIP_LIBRARIES_HASH_TABLE_NAME, 0, package_name + PythonManagementConstants.PIP_LIBRARY_ENDING_SYMBOL)
        finally:
            cache_utils.release_task_status(PIP_SYNCING_LOCK)