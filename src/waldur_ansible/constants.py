import models


def constant(f):
    def fset(self, value):
        raise TypeError
    def fget(self):
        return f()
    return property(fget, fset)

class PythonManagementConstants(object):
    @constant
    def INSTALL_PYTHON_ENVIRONMENT():
        return 'install_python_environment'
    @constant
    def SYNCHRONIZE_PACKAGES():
        return 'synchronize_packages'
    @constant
    def FIND_INSTALLED_LIBRARIES_FOR_VIRTUAL_ENVIRONMENT():
        return 'find_installed_libraries_for_virtual_environment'
    @constant
    def FIND_INSTALLED_VIRTUAL_ENVIRONMENTS():
        return 'find_installed_virtual_environments'
    @constant
    def DELETE_VIRTUAL_ENVIRONMENT():
        return 'delete_virtual_environment'
    @constant
    def DELETE_PYTHON_ENVIRONMENT():
        return 'delete_python_environment'

    @constant
    def PIP_LIBRARY_ENDING_SYMBOL():
        return '^'
    @constant
    def PIP_LIBRARIES_HASH_TABLE_NAME():
        return 'pip_packages'

PythonManagementConstants = PythonManagementConstants()
