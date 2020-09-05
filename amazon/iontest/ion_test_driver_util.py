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
ion_test_driver utilities.
"""

import os
import sys
from subprocess import check_call

COMMAND_SHELL = False
if sys.platform.startswith('win'):
    COMMAND_SHELL = True  # shell=True on Windows allows the .exe suffix to be omitted.


def log_call(log, args):
    """
    Logs the stdout and stderr for the given subprocess call to the given file.
    """
    log_file = open(log, 'a' if os.path.isfile(log) else 'w')
    try:
        check_call(args, shell=COMMAND_SHELL, stdout=log_file, stderr=log_file)
    finally:
        log_file.close()


class IonBuild:
    def __init__(self, installer, executable, prefix):
        """
        Build information for an Ion resource.

        :param installer: function which builds the resource.
        :param executable: path to the resource's executable (if any), relative to the root of the implementation.
        :param prefix: prefix of the command that runs executable. (e.g java requests java -jar)
        """
        self.install = installer
        self.execute = executable
        self.prefix = prefix


def install_no_op(log):
    pass


NO_OP_BUILD = IonBuild(install_no_op, None, None)
