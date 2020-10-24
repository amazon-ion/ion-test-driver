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
import shutil
from os import listdir
from os.path import isfile, join

from tests.util import run_ion_test_driver, compare_two_files

TEST_FILE_NAME = 'res_diff_tests'
TEST_FILE_PATH = os.path.join(os.path.split(os.path.abspath(__file__))[0], TEST_FILE_NAME)
EXPECT_FILE_NAME = 'res_diff_expect'
EXPECT_FILE_PATH = os.path.join(os.path.split(os.path.abspath(__file__))[0], EXPECT_FILE_NAME)

TEST_FILES = [f for f in listdir(TEST_FILE_PATH) if isfile(join(TEST_FILE_PATH, f)) and f.split('.')[-1] == 'ion']
TEMP_FILE = os.path.join(TEST_FILE_PATH, 'temp')


def pytest_generate_tests(metafunc):
    metafunc.parametrize('file', TEST_FILES)


def test_compute(file):
    expect_res = True if file.split('_')[0] == 'pass' else False
    if not os.path.exists(TEMP_FILE):
        os.mkdir(TEMP_FILE)
    output_path, ret = run_ion_test_driver(os.path.join(TEST_FILE_PATH, file), 'ion-java,1', 'ion-java,2', TEMP_FILE)
    res = compare_two_files(output_path, os.path.join(EXPECT_FILE_PATH, file))
    os.remove(output_path)
    shutil.rmtree(TEMP_FILE)
    assert ret == 0 if expect_res is True else ret != 0
    assert res is True



