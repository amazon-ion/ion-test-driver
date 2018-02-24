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
import os
import sys
from subprocess import check_call

COMMAND_SHELL = False
if sys.platform.startswith('win'):
    COMMAND_SHELL = True  # shell=True on Windows allows the .exe suffix to be omitted.


def log_call(log, args):
    if os.path.isfile(log):
        log_file = open(log, 'a')
    else:
        log_file = open(log, 'w')
    try:
        check_call(args, shell=COMMAND_SHELL, stdout=log_file, stderr=log_file)
    finally:
        log_file.close()


class IonBuild:
    """
    Args:
        installer[func]: function which builds the implementation.
        executable[text]: path to the implementation's executable, relative to the root of the implementation.
    """
    def __init__(self, installer, executable):
        self.install = installer
        self.execute = executable


def install_no_op(log):
    pass

NO_OP_BUILD = IonBuild(install_no_op, None)
