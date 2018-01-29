import re
import urllib2

import redis
from bs4 import BeautifulSoup
from waldur_ansible.constants import PythonManagementConstants


class PipService(object):

    @staticmethod
    def find_versions(queried_library_name):
        parser = BeautifulSoup(urllib2.urlopen("https://pypi.python.org/simple/" + queried_library_name).read(), "lxml")
        library_versions = parser.findAll('a')
        wrong_os_versions = ["win", "mac"]
        python_versions = ["35", "3.5"]
        version_identifying_regex = [re.compile(PipService.buildIdentifyingVersionRegex(identificator)) for identificator in
                                     ["cp", "py"]]
        versions = []
        for library_version in library_versions:
            library_version = library_version.text.lower()
            if not PipService.contains_any_string(library_version, wrong_os_versions) \
                    and (PipService.contains_any_string(library_version, python_versions)
                         or PipService.does_not_contain_python_version(library_version, version_identifying_regex)):
                PipService.find_version_by_regex_and_append(library_version, versions)
        versions = PipService.make_library_list_unique_by_versions(versions)
        versions.sort(reverse=True, key=lambda ver: map(int, PipService.extract_sorting_criterion(ver)))
        return versions

    @staticmethod
    def find_version_by_regex_and_append(library_version, versions):
        rc_regex = re.search('.*(\d+(.)\d+(.)\d+(rc)\d+).*', library_version)
        if rc_regex:
            versions.append(rc_regex.group(1))
        else:
            three_digits_regex = re.search('.*(\d+(.)\d+(.)\d+).*', library_version)
            if three_digits_regex:
                versions.append(three_digits_regex.group(1))
            else:
                two_digits_regex = re.search('.*-(\d+(.)\d+).*', library_version)
                if two_digits_regex:
                    versions.append(two_digits_regex.group(1))

    @staticmethod
    def make_library_list_unique_by_versions(libraries):
        unique_criteria_list = []
        unique_library_list = []
        for library in libraries:
            criterion = PipService.extract_sorting_criterion(library)
            if criterion not in unique_criteria_list:
                unique_criteria_list.append(criterion)
                unique_library_list.append(library)
        return unique_library_list

    @staticmethod
    def buildIdentifyingVersionRegex(identificator):
        return "^(\d\d" + identificator + "|" + identificator + "\d\d)$"

    @staticmethod
    def does_not_contain_python_version(target_string, version_identificators):
        for identificator_regex in version_identificators:
            if identificator_regex.match(target_string):
                return False
        return True

    @staticmethod
    def contains_any_string(target_string, strings):
        for string in strings:
            if string in target_string:
                return True
        return False

    @staticmethod
    def extract_sorting_criterion(raw_version):
        versions = raw_version.split('.')

        last_version = versions[len(versions) - 1]
        special_version_pos = re.search("[a-zA-Z]", last_version)
        if special_version_pos:
            del versions[len(versions) - 1]

            special_version_letter_start = special_version_pos.start()
            versions.append(last_version[:special_version_letter_start])

            special_version_digit = re.search("\d", last_version[special_version_letter_start:])
            if special_version_digit:
                versions.append(last_version[special_version_digit.start() + 1:])
        return versions

    @staticmethod
    def autocomplete_library_name(queried_library_name):
        matching_libraries = PipService.query_redis(queried_library_name)
        matching_libraries.sort(key=lambda p: len(p))
        return matching_libraries

    @staticmethod
    def query_redis(queried_package_name):
        r = redis.StrictRedis(host='localhost', port=6379, db=0)
        matching_libraries = []

        max_result_count = 40
        batch_count = 40
        start_position = r.zrank(PythonManagementConstants.PIP_LIBRARIES_HASH_TABLE_NAME, queried_package_name)

        if not start_position:
            return matching_libraries

        while len(matching_libraries) != max_result_count:
            matching_library_names_parts = r.zrange(PythonManagementConstants.PIP_LIBRARIES_HASH_TABLE_NAME,
                                                    start_position, start_position + batch_count - 1)
            start_position += batch_count

            for entry in matching_library_names_parts:
                safe_length = min(len(entry), len(queried_package_name))
                if PipService.are_retrived_packages_no_longer_match_query(queried_package_name, entry, safe_length):
                    return matching_libraries
                if entry[-1] == PythonManagementConstants.PIP_LIBRARY_ENDING_SYMBOL:
                    matching_libraries.append(entry[0:-1])
                    if len(matching_libraries) == max_result_count:
                        return matching_libraries

        return matching_libraries

    @staticmethod
    def are_retrived_packages_no_longer_match_query(current_entry, library_name, len):
        return current_entry[0:len] != library_name[0:len]