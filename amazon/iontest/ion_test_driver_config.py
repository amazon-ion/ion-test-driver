# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at:
#
#    http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS
# OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the
# License.

"""
Provides the build logic for Ion resources required by the ion_test_driver.
"""

import os

from amazon.iontest.ion_test_driver_util import IonBuild, NO_OP_BUILD, log_call

RESULTS_FILE_DEFAULT = 'ion-test-driver-results.ion'
ION_TESTS_SOURCE = 'https://github.com/amazon-ion/ion-tests.git'
RETRY_ATTEMPTS = 2

# Tools expected to be present on the system. Key: name, value: path. Paths may be overridden using --<name>.
# Accordingly, if tool dependencies are added here, a corresponding option should be added to the CLI.
TOOL_DEPENDENCIES = {
    'cmake': 'cmake',
    'git': 'git',
    'npm': 'npm',
    'node': 'node',
    'java': 'java'
}

# command used for testing the existence of the executable
TOOL_TEST_COMMAND = {
    'cmake': '--help',
    'git': '--help',
    'npm': '-v',
    'node': '-v',
    'java': '-version'
}


def install_ion_c(log):
    log_call(log, (TOOL_DEPENDENCIES['cmake'], '-DCMAKE_BUILD_TYPE=Debug'))
    log_call(log, (TOOL_DEPENDENCIES['cmake'], '--build', '.'))


def install_ion_java(log):
    log_call(log, ('./ion-test-driver-setup'))


def install_ion_js(log):
    log_call(log, (TOOL_DEPENDENCIES['npm'], 'install', '--ignore-scripts'))
    log_call(log, (TOOL_DEPENDENCIES['npm'], 'run-script', 'test-driver'))
    log_call(log, (TOOL_DEPENDENCIES['npm'], 'run-script', 'build-test-driver'))


ION_BUILDS = {
    'ion-c': IonBuild(install_ion_c, os.path.join('tools', 'cli', 'ion'), ()),
    'ion-tests': NO_OP_BUILD,
    'ion-java': IonBuild(install_ion_java, './ion-test-driver-run', ()),
    'ion-js': IonBuild(install_ion_js, os.path.join('test-driver', 'dist', 'Cli.js'),
                       (TOOL_DEPENDENCIES['node'],))
    # TODO add more implementations here
}

# Ion implementations hosted in Github. Local implementations may be tested using the `--implementation` argument,
# and should not be added here. For the proper description format, see the ion_test_driver CLI help.
ION_IMPLEMENTATIONS = [
    'ion-c,https://github.com/amazon-ion/ion-c.git,master',
    'ion-java,https://github.com/amazon-ion/ion-java.git,master',
    'ion-js,https://github.com/amazon-ion/ion-js.git,master'
    # TODO add more Ion implementations here
]
