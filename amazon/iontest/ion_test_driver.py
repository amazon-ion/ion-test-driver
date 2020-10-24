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

"""Cross-implementation test driver.

Usage:
    ion_test_driver.py [--implementation <description>]... [--ion-tests <description>] [--test <type>]...
                       [--local-only] [--cmake <path>] [--git <path>] [--maven <path>] [--java <path>] [--npm <path>]
                       [--node <path>] [--output-dir <dir>] [--results-file <file>] [<test_file>]...
    ion_test_driver.py --results-diff <first_description> <second_description> <results_file> [--output-dir <dir>]
    ion_test_driver.py (--list)
    ion_test_driver.py (-h | --help)

Options:
    --cmake <path>                      Path to the cmake executable.

    --git <path>                        Path to the git executable.

    --maven <path>                      Path to the maven executable.

    --npm <path>                        Path to npm executable.

    --node <path>                       Path to the node executable.

    --java <path>                       Path to the java executable.

    -h, --help                          Show this screen.

    -i, --implementation <description>  Test an additional implementation specified by a description of the form
                                        name,location,revision. Name must match one of the names returned by `--list`.
                                        Location may be a local path or a URL. Revision is optional, may be either a
                                        branch name or commit hash, and defaults to `master`.

    -I, --ion-tests <description>       Override the default ion-tests location by providing a description of the form
                                        location,revision. Location may be a local path or a URL. Revision is optional,
                                        may be either a branch name or commit hash, and defaults to `master`.

    -l, --list                          List the implementations that can be built by this tool.

    -L, --local-only                    Test using only local implementations specified by `--implementation`.

    -o, --output-dir <dir>              Root directory for all of this command's output. [default: .]

    -r, --results-file <file>           Path to the results output file. By default, this will be placed in a file named
                                        `ion-test-driver-results.ion` under the directory specified by the
                                        `--output-dir` option.

    -R, --results-diff                  Given two implementation descriptions of the forms name,commit_hash or
                                        name,location,revision. Name is the implementation's name and revision is
                                        optional, may be either a branch name or commit hash. Analyze an existing
                                        results file to identify any differences between the two implementations.
                                        The order of two implementations matters and the analysis result is based on the
                                        first implementation.

    -t, --test <type>                   Perform a particular test type or types, chosen from `good`, `bad`, `equivs`,
                                        `non-equivs`, and `all`. [default: all]


"""
import os
import shutil
import sys
from io import FileIO
from subprocess import check_call, check_output, Popen, PIPE
import six
from amazon.ion import simpleion
from amazon.ion.core import IonType
from amazon.ion.equivalence import ion_equals
from amazon.ion.simple_types import IonPySymbol, IonPyList
from amazon.ion.util import Enum
from docopt import docopt

from amazon.iontest.ion_test_driver_config import TOOL_DEPENDENCIES, ION_BUILDS, ION_IMPLEMENTATIONS, ION_TESTS_SOURCE, \
    RESULTS_FILE_DEFAULT, TOOL_TEST_COMMAND
from amazon.iontest.ion_test_driver_util import COMMAND_SHELL, log_call


ION_SUFFIX_TEXT = '.ion'
ION_SUFFIX_BINARY = '.10n'
ION_TEST_DRIVER_PATH = os.path.abspath(__file__)


def check_tool_dependencies(args):
    """
    Verifies that all dependencies declared by `TOOL_DEPENDENCIES` are executable.
    :param args: If any of the tool dependencies are present, uses the value to override the default location.
    """
    names = TOOL_DEPENDENCIES.keys()
    for name in names:
        path = args['--' + name]
        if path:
            TOOL_DEPENDENCIES[name] = path
    for name, path in six.iteritems(TOOL_DEPENDENCIES):
        try:
            no_output = open(os.devnull, 'w')
            check_call([path, TOOL_TEST_COMMAND[name]], stdout=no_output, shell=COMMAND_SHELL)
        except:
            raise ValueError(name + " not found. Try specifying its location using --" + name + ".")
        finally:
            no_output.close()


class IonResource:
    def __init__(self, output_root, name, location, revision):
        """
        Provides the installation logic for a resource required to run the tests.

        :param output_root: Root directory for the build output.
        :param name: Name of the resource.
        :param location: Location from which to git clone the resource.
        :param revision: Git revision of the resource.
        """
        self.__output_root = output_root
        try:
            self._build = ION_BUILDS[name]
        except KeyError:
            raise ValueError('No installer for %s.' % name)
        self._name = name
        self._prefix = self._build.prefix
        self._build_dir = None
        self.__build_log = None
        self.__identifier = None
        self._executable = None
        self.__location = location
        self.__revision = revision

    @property
    def identifier(self):
        if self.__identifier is None:
            raise ValueError('Implementation %s must be installed before receiving an identifier.' % self._name)
        return self.__identifier

    def __git_clone_revision(self):
        # The commit is not yet known; clone into a temporary location to determine the commit and decide whether the
        # code for that revision is already present. If it is, use the existing code, as it may have already been built.
        tmp_dir_root = os.path.abspath((os.path.join(self.__output_root, 'build', 'tmp')))
        try:
            tmp_dir = os.path.abspath(os.path.join(tmp_dir_root, self._name))
            if not os.path.isdir(tmp_dir_root):
                os.makedirs(tmp_dir_root)
            tmp_log = os.path.abspath(os.path.join(tmp_dir_root, 'tmp_log.txt'))
            log_call(tmp_log, (TOOL_DEPENDENCIES['git'], 'clone', '--recurse-submodules', self.__location,
                     tmp_dir))
            os.chdir(tmp_dir)
            if self.__revision is not None:
                log_call(tmp_log, (TOOL_DEPENDENCIES['git'], 'checkout', self.__revision))
                log_call(tmp_log, (TOOL_DEPENDENCIES['git'], 'submodule', 'update', '--init'))
            commit = check_output((TOOL_DEPENDENCIES['git'], 'rev-parse', '--short', 'HEAD')).strip()
            self.__identifier = self._name + '_' + commit.decode()
            self._build_dir = os.path.abspath(os.path.join(self.__output_root, 'build', self.__identifier))
            logs_dir = os.path.abspath(os.path.join(self.__output_root, 'build', 'logs'))
            if not os.path.isdir(logs_dir):
                os.makedirs(logs_dir)
            self.__build_log = os.path.abspath(os.path.join(logs_dir, self.__identifier + '.txt'))
            if not os.path.exists(self._build_dir):
                shutil.move(tmp_log, self.__build_log)  # This build is being used, overwrite an existing log (if any).
                shutil.move(tmp_dir, self._build_dir)
            else:
                print("%s already present. Using existing source." % self._build_dir)
        finally:
            shutil.rmtree(tmp_dir_root)

    def install(self):
        print('Installing %s revision %s.' % (self._name, self.__revision))
        self.__git_clone_revision()
        os.chdir(self._build_dir)
        self._build.install(self.__build_log)
        os.chdir(self.__output_root)
        print('Done installing %s.' % self.identifier)
        return self._build_dir


class IonImplementation(IonResource):
    def __init__(self, output_root, name, location, revision):
        """
        An executable `IonResource`; used to represent different Ion implementations.
        """
        super(IonImplementation, self).__init__(output_root, name, location, revision)

    def execute(self, *args):
        # TODO execute commands in 'interactive mode' to avoid creating a new short-lived process for each invocation.
        if self._build_dir is None:
            raise ValueError('Implementation %s has not been installed.' % self._name)
        if self._executable is None:
            if self._build.execute is None:
                raise ValueError('Implementation %s is not executable.' % self._name)
            self._executable = os.path.abspath(os.path.join(self._build_dir, self._build.execute))
        if not os.path.isfile(self._executable):
            raise ValueError('Executable for %s does not exist.' % self._name)
        _, stderr = Popen((self._prefix + (self._executable,) + args), stderr=PIPE, shell=COMMAND_SHELL).communicate()
        return stderr


class TestResult:
    def __init__(self, impl_id, output_location, error_location):
        """
        Retrieves the ErrorReports generated by calls to any implementation's CLI.
        :param impl_id: The implementation instance that generated the reports.
        :param output_location: The data generated by this test run (may be an EventStream for a read test, an Ion
            stream for a write test, or a ComparisonReport for a verification test).
        :param error_location: The ErrorReport (if any) generated by this test run.
        """
        self.impl_id = impl_id
        self.output_location = output_location
        self.error_location = error_location
        self.__errors = None

    @property
    def errors(self):
        if self.__errors is None:
            if os.path.isfile(self.error_location):
                errors_in = FileIO(self.error_location, mode='rb')
                try:
                    errors_stream = simpleion.load(errors_in, single_value=False)
                finally:
                    errors_in.close()
                self.__errors = IonPyList.from_value(IonType.LIST, errors_stream)
            else:
                self.__errors = IonPyList.from_value(IonType.LIST, [])
        return self.__errors

    @property
    def has_errors(self):
        return len(self.errors) != 0


class CompareResult(TestResult):
    def __init__(self, impl_id, report_location, error_location):
        """
        Retrieves the ComparisonReport generated by calls to any implementation's CLI.
        """
        super(CompareResult, self).__init__(impl_id, report_location, error_location)
        self.__comparison_report = None

    @property
    def comparison_report(self):
        if self.__comparison_report is None:
            if os.path.isfile(self.output_location):
                comparisons_in = FileIO(self.output_location, mode='rb')
                try:
                    comparison_failure_stream = simpleion.load(comparisons_in, single_value=False)
                finally:
                    comparisons_in.close()
                self.__comparison_report = IonPyList.from_value(IonType.LIST, comparison_failure_stream)
            else:
                self.__comparison_report = IonPyList.from_value(IonType.LIST, [])
        return self.__comparison_report

    @property
    def has_comparison_failures(self):
        return len(self.comparison_report) != 0

    def reset(self):
        # Force the error and comparison reports to be re-read.
        self.__errors = None
        self.__comparison_report = None


class TestReport(dict):
    PASS = IonPySymbol.from_value(IonType.SYMBOL, 'PASS')
    FAIL = IonPySymbol.from_value(IonType.SYMBOL, 'FAIL')
    READ_ERROR = 'read_error'
    WRITE_ERROR = 'write_error'
    READ_COMPARE = 'read_compare'
    WRITE_COMPARE = 'write_compare'
    ERROR_REPORT_ANNOTATION = (IonPySymbol.from_value(IonType.SYMBOL, 'ErrorReport'),)
    COMPARISON_REPORT_ANNOTATION = (IonPySymbol.from_value(IonType.SYMBOL, 'ComparisonReport'),)
    RESULT_FIELD = 'result'
    COMPARISON_FAILURES_FIELD = 'failures'
    ERRORS_FIELD = 'errors'

    def __init__(self):
        """
        Collects any errors and comparison failures that occur in the read, read_verify, write, and write_verify phases
        of a single test for a single implementation.
        """
        super(dict, self).__init__()
        self[TestReport.RESULT_FIELD] = TestReport.PASS

    def __set_read_write_error(self, key, error_report):
        error_report.ion_annotations = TestReport.ERROR_REPORT_ANNOTATION
        self[key] = error_report
        self[TestReport.RESULT_FIELD] = TestReport.FAIL

    def __set_comparison_failure(self, key, comparison_report, error_report):
        if comparison_report is None and error_report is None:
            raise ValueError('Failed a comparison for %s for no apparent reason.' % key)
        self[key] = {}
        if comparison_report is not None:
            comparison_report.ion_annotations = TestReport.COMPARISON_REPORT_ANNOTATION
            self[key][TestReport.COMPARISON_FAILURES_FIELD] = comparison_report
        if error_report is not None:
            error_report.ion_annotations = TestReport.ERROR_REPORT_ANNOTATION
            self[key][TestReport.ERRORS_FIELD] = error_report
        self[TestReport.RESULT_FIELD] = TestReport.FAIL

    def error(self, result, is_read):
        """
        Adds the given TestResult as an error.
        :param result: A TestResult for which result.has_errors is True.
        :param is_read: True if and only if this error occurred in the read phase.
        """
        field = TestReport.READ_ERROR if is_read else TestReport.WRITE_ERROR
        self.__set_read_write_error(field, result.errors)

    def fail_compare(self, compare_result, is_read):
        """
        Adds the given CompareResult as a comparison failure.
        :param compare_result: A ComparisonResult for which compare_result.has_comparison_failures is true.
        :param is_read: True if and only if this error occurred in the read verification phase.
        """
        field = TestReport.READ_COMPARE if is_read else TestReport.WRITE_COMPARE
        self.__set_comparison_failure(
            field,
            compare_result.comparison_report if compare_result.has_comparison_failures else None,
            compare_result.errors if compare_result.has_errors else None
        )

    @property
    def has_failure(self):
        return self[TestReport.RESULT_FIELD] == TestReport.FAIL


class TestType(Enum):
    BAD = 0
    GOOD = 1
    NON_EQUIVS = 3
    EQUIVS = 2
    EQUIV_TIMELINE = 4

    @property
    def is_good(self):
        return self > TestType.BAD

    @property
    def is_bad(self):
        return self == TestType.BAD

    def __str__(self):
        return '%s' % self.name.lower().replace('_', '-')

    @property
    def compare_type(self):
        if self > TestType.GOOD:
            return str(self)
        return 'basic'


def test_type_from_str(name):
    name_lower = name.lower()
    if str(TestType.BAD) == name_lower:
        return TestType.BAD
    if str(TestType.GOOD) == name_lower:
        return TestType.GOOD
    if str(TestType.EQUIVS) == name_lower:
        return TestType.EQUIVS
    if str(TestType.NON_EQUIVS) == name_lower:
        return TestType.NON_EQUIVS
    if str(TestType.EQUIV_TIMELINE) == name_lower:
        return TestType.EQUIV_TIMELINE
    raise ValueError("Given string '%s' does not map to a known TestType" % name)


class TestFile:
    ERROR_TYPE_FIELD = 'error_type'
    ERROR_MESSAGE_FIELD = 'message'
    ERROR_LOCATION_FIELD = 'location'
    ERROR_TYPE_STATE_SYMBOL = IonPySymbol.from_value(IonType.SYMBOL, 'STATE')
    DATA_DIR = 'data'
    ERRORS_DIR = 'errors'
    REPORT_DIR = 'report'
    READ_DATA_DIR = os.path.join('read', DATA_DIR)
    READ_ERRORS_DIR = os.path.join('read', ERRORS_DIR)
    WRITE_DIR = 'write'
    READ_VERIFY_DIR = 'read_verify'
    WRITE_VERIFY_DIR = 'write_verify'

    def __init__(self, test_type, path, output_root, ion_implementations):
        """
        Provides the test logic and collects the results for testing a single test file against all implementations.
        :param path: Path to the test file.
        :param test_type: The test file's TestType.
        :param output_root: The root directory in which to write the test results for this test file.
        :param ion_implementations: The implementations for which to test this file.
        """
        self.path = path
        self.short_path = os.path.split(self.path)[-1]
        self.__read_results = []
        self.__write_results = []
        self.__type = test_type
        self.__results_root = os.path.join(output_root, str(test_type), self.short_path)
        self.__report = {impl.identifier: TestReport() for impl in ion_implementations}  # Initializes PASS results
        self.__ion_implementations = ion_implementations

    def __execute_with(self, ion_implementation, error_location, args):
        stderr = ion_implementation.execute(*args)
        if len(stderr) != 0:
            # Any output to stderr is likely caused by an uncaught error in the implementation under test. This forces a
            # failure to avoid false negatives.
            error_file = FileIO(error_location, 'wb')
            try:
                error = {
                    TestFile.ERROR_TYPE_FIELD: TestFile.ERROR_TYPE_STATE_SYMBOL,
                    TestFile.ERROR_MESSAGE_FIELD: 'Implementation %s produced stderr output "%s" for command %r.' % (
                        ion_implementation.identifier, stderr.decode(), args
                    ),
                    TestFile.ERROR_LOCATION_FIELD: self.path
                }
                simpleion.dump(error, error_file, binary=False)
            finally:
                error_file.close()

    def __new_results_file(self, short_name, *dirs):
        results_dir = os.path.join(self.__results_root, *dirs)
        if not os.path.isdir(results_dir):
            os.makedirs(results_dir)
        return os.path.join(results_dir, short_name)

    def __read_with(self, ion_implementation):
        read_output = self.__new_results_file(ion_implementation.identifier + ION_SUFFIX_TEXT, TestFile.READ_DATA_DIR)
        read_errors = self.__new_results_file(ion_implementation.identifier + ION_SUFFIX_TEXT, TestFile.READ_ERRORS_DIR)
        self.__execute_with(ion_implementation, read_errors,
                            ('process', '--error-report', read_errors, '--output', read_output, '--output-format',
                             'events', self.path))
        result = TestResult(ion_implementation.identifier, read_output, read_errors)
        self.__read_results.append(result)
        return result

    def __compare(self, ion_implementation, compare_type, compare_result, inputs, is_read, is_sets=False):
        self.__execute_with(ion_implementation, compare_result.error_location,
                            ('compare', '--error-report', compare_result.error_location, '--output',
                             compare_result.output_location, '--comparison-type', compare_type, *inputs))
        if not compare_result.has_errors and not compare_result.has_comparison_failures:
            if not is_sets and self.__type.compare_type != 'basic':
                compare_result.reset()
                self.__compare(ion_implementation, self.__type.compare_type, compare_result, inputs,
                               is_read, is_sets=True)
        if compare_result.has_errors or compare_result.has_comparison_failures:
            try:
                self.__report[ion_implementation.identifier].fail_compare(compare_result, is_read)
            except KeyError:
                raise ValueError("Attempted to verify with an implementation that did not produce results.")

    def __verify(self, results, is_read):
        if self.__type.is_bad:
            error_results = list(filter(lambda res: not res.has_errors, results))
            success_results = list(filter(lambda res: res.has_errors, results))
        else:
            error_results = list(filter(lambda res: res.has_errors, results))
            success_results = list(filter(lambda res: not res.has_errors, results))
        for error_result in error_results:
            try:
                self.__report[error_result.impl_id].error(error_result, is_read)
            except KeyError:
                raise ValueError("Attempted to verify with an implementation that did not produce results.")
        if len(success_results) == 0:
            # Every input caused an error. There's nothing to compare.
            return
        verify_dir = TestFile.READ_VERIFY_DIR if is_read else TestFile.WRITE_VERIFY_DIR
        outputs = [x.output_location for x in success_results]
        if not self.__type.is_bad:
            # For bad inputs, reading the original input again would cause a failure before the comparison begins.
            outputs.append(self.path)
        for ion_implementation in self.__ion_implementations:
            compare_output = self.__new_results_file(ion_implementation.identifier + ION_SUFFIX_TEXT, verify_dir,
                                                     TestFile.REPORT_DIR)
            compare_errors = self.__new_results_file(ion_implementation.identifier + ION_SUFFIX_TEXT, verify_dir,
                                                     TestFile.ERRORS_DIR)
            self.__compare(ion_implementation, 'basic',
                           CompareResult(ion_implementation.identifier, compare_output, compare_errors),
                           outputs, is_read)

    def __write_with(self, ion_implementation):
        if self.__type.is_bad:
            raise ValueError("Writing bad/ vectors is not supported.")
        if self.__report[ion_implementation.identifier].has_failure:
            # Skip implementations that failed in a previous phase.
            return
        write_output_root = os.path.join(TestFile.WRITE_DIR, ion_implementation.identifier)
        for read_result in self.__read_results:
            if not read_result.has_errors:  # Skip read results that failed in a previous phase.
                for encoding in ('text', 'binary'):
                    suffix = ION_SUFFIX_TEXT if encoding == 'text' else ION_SUFFIX_BINARY
                    write_output = self.__new_results_file(read_result.impl_id + suffix, write_output_root,
                                                           encoding, TestFile.DATA_DIR)
                    write_errors = self.__new_results_file(read_result.impl_id + ION_SUFFIX_TEXT, write_output_root,
                                                           encoding, TestFile.ERRORS_DIR)
                    self.__execute_with(ion_implementation, write_errors,
                                        ('process', '--error-report', write_errors, '--output', write_output,
                                         '--output-format', encoding, read_result.output_location))
                    self.__write_results.append(TestResult(ion_implementation.identifier, write_output, write_errors))

    def read(self):
        """
        Uses all implementations to read this file as an EventStream. The results are stored in, for example,
        results/good/one.ion/read/data/ion-c_abcd123.ion and results/good/one.ion/read/errors/ion-c_abcd123.ion.
        """
        for ion_implementation in self.__ion_implementations:
            self.__read_with(ion_implementation)

    def verify_reads(self):
        """
        Determines which implementations succeeded in the read phase by examining any ErrorReports produced. Verifies
        that all implementations agree that all successfully-read EventStreams are equivalent, are equivalent to the
        original, and comply with any extra equivalence semantics prescribed by the test type. The results are stored
        in, for example, results/good/one.ion/read_verify/report/ion-c_abcd123.ion and
        results/good/one.ion/read_verify/errors/ion-c_abcd123.ion.
        """
        self.__verify(self.__read_results, is_read=True)

    def write(self):
        """
        For all implementations that passed both the read and verify_reads phases, re-writes each implementation's
        EventStream as both text and binary Ion streams. The results are stored in, for example,
        results/good/one.ion/write/ion-c_abcd123/binary/data/ion-java_def4567.10n and
        results/good/one.ion/write/ion-c_abcd123/binary/errors/ion-java_def4567.ion (where ion-c_abcd123 is the
        implementation that performed the write, and ion-java_def4567 is the implementation that produced the initial
        EventStream).
        """
        if self.__type.is_bad:  # bad files skip this phase.
            return
        for ion_implementation in self.__ion_implementations:
            self.__write_with(ion_implementation)

    def verify_writes(self):
        """
        Determines which implementations succeeded in the write phase by examining any ErrorReports produced. Verifies
        that all implementations agree that all successfully-written Ion streams are equivalent, are equivalent
        to the original, and comply with any extra equivalence semantics prescribed by the test type. The results are
        stored in, for example, results/good/one.ion/write_verify/report/ion-c_abcd123.ion and
        results/good/one.ion/write_verify/errors/ion-c_abcd123.ion.
        """
        if self.__type.is_bad:  # bad files skip this phase.
            return
        self.__verify(self.__write_results, is_read=False)

    def add_results_to(self, results):
        """
        Adds this TestFile's report to a master report that tracks results for all TestTypes.
        """
        results.setdefault(str(self.__type), {})[self.short_path] = self.__report


def generate_test_files(tests_dir, test_types, test_file_filter, results_root, ion_implementations):
    """
    Walks the given `tests_dir`, classifying and filtering the files therein based on the directory structure.
    :param tests_dir: Root of the ion-tests directory.
    :param test_types: Collection of TestType to filter the files on.
    :param test_file_filter: Collection of filename suffixes (e.g. good/blobs.ion) to whitelist.
    :param results_root: Root of the results to be generated by the tests.
    :param ion_implementations: Collection of implementations to test
    :return: Each TestFile as it is found.
    """
    def filter_files(test_type):
        for test_file in files:
            if not (test_file.endswith(ION_SUFFIX_TEXT) or test_file.endswith(ION_SUFFIX_BINARY)):
                continue
            full_test_file = os.path.join(root, test_file)
            if len(test_file_filter) != 0:
                found = False
                for filter_matcher in test_file_filter:
                    if full_test_file.endswith(filter_matcher):
                        found = True
                        break
                if not found:
                    continue
            yield TestFile(test_type, full_test_file, results_root, ion_implementations)

    test_file_root = os.path.abspath(os.path.join(tests_dir, 'iontestdata'))
    if not os.path.exists(test_file_root):
        raise ValueError("Invalid ion-tests directory. Could not find test files.")
    for root, dirs, files in os.walk(test_file_root):
        if os.path.join('iontestdata', str(TestType.GOOD)) in root:
            if os.path.join(str(TestType.GOOD), str(TestType.EQUIVS)) in root and TestType.EQUIVS in test_types:
                for equivs_file in filter_files(TestType.EQUIVS):
                    yield equivs_file
            elif os.path.join(str(TestType.GOOD), str(TestType.NON_EQUIVS)) in root \
                    and TestType.NON_EQUIVS in test_types:
                for nonequivs_file in filter_files(TestType.NON_EQUIVS):
                    yield nonequivs_file
            elif os.path.join(str(TestType.GOOD), 'timestamp', 'equivTimeline') in root \
                    and TestType.EQUIV_TIMELINE in test_types:
                for equiv_timeline_file in filter_files(TestType.EQUIV_TIMELINE):
                    yield equiv_timeline_file
            elif TestType.GOOD in test_types:
                for good_file in filter_files(TestType.GOOD):
                    yield good_file
        elif os.path.join('iontestdata', str(TestType.BAD)) in root and TestType.BAD in test_types:
            for bad_file in filter_files(TestType.BAD):
                yield bad_file


def write_results(results, results_file, impls):
    """
    Writes test results from `results`, which complies with the following schema-by-example.
    {
        good: {
            'test_file_1.ion': {
                'ion-c_abcd123': {
                    result: PASS
                },
                'ion-java_def4567': {
                    result: PASS
                }
            },
            'test_file_2.ion': {
                'ion-c_abcd123': {
                    result: FAIL,
                    read_error: ErrorReport::[{
                        error_type: READ,
                        message: "ion_reader_text.c:999 Line 1 index 3: Repeated underscore in numeric value.",
                        location: "test_file_2.ion"
                    }]
                },
                'ion-java_def4567': {
                    result: PASS
                }
            }
        },
        bad: {
            'test_file_3.ion': {
                'ion-c_abcd123' : {
                    result: FAIL,
                    errors: []
                },
                'ion-java_def4567': {
                    result: PASS
                }
            }
        },
        equivs: {
            'test_file_4.ion': {
                'ion-c_abcd123': {
                    result: FAIL,
                    read_compare: {
                        errors: [],
                        failures: ComparisonReport::[{
                            result: NOT_EQUAL,
                            lhs: {
                                location: "ion-c_abcd123.ion",
                                event: {
                                    event_type: SCALAR,
                                    ion_type: INT,
                                    value_text: "1",
                                    value_binary: [0x21, 0x01],
                                    depth:1
                                },
                                event_index: 2
                            },
                            rhs: {
                                location: "test_file_4.ion",
                                event: {
                                    event_type: SCALAR,
                                    ion_type: INT,
                                    value_text: "2",
                                    value_binary: [0x21, 0x02],
                                    depth:1
                                },
                                event_index:2
                            },
                            message: "1 vs. 2"
                        }]
                    }
                },
                'ion-java_def4567': {
                    result: FAIL,
                    write_error: ErrorReport::[{
                        error_type: WRITE,
                        message: "IonManagedBinaryWriter.java:999 UnsupportedOperationException",
                        location: "test_file_4.ion"
                    }]
                }
            }
        }
    }
    """
    # NOTE: A lot of this is a hack necessitated by the fact that ion-python does not yet support pretty-printing Ion
    # text. Once it does, the only thing this method needs to do is 'dump' to results_file with pretty-printing enabled.
    if '.' in results_file:
        results_file_raw = results_file[0:results_file.rfind('.')] + '_raw.ion'
    else:
        results_file_raw = results_file + '_raw.ion'
    results_out = FileIO(results_file_raw, mode='wb')
    try:
        simpleion.dump(results, results_out, binary=False)
    finally:
        results_out.close()
    ionc = list(filter(lambda x: 'ion-c' in x.identifier, impls))[0]
    ionc.execute('process', '--output', results_file, results_file_raw)


def test_all(impls, tests_dir, test_types, test_file_filter, results_root, results_file):
    """
    Locates all ion-tests files in the given location that match the given types and filter, tests them with all of the
    given implementations, and writes the test results in the location described by results_root/results_file.
    """
    print('Running tests.', end='', flush=True)
    results = {}
    for test_file in generate_test_files(tests_dir, test_types, test_file_filter, results_root, impls):
        test_file.read()
        test_file.verify_reads()
        test_file.write()
        test_file.verify_writes()
        test_file.add_results_to(results)
        print('.', end='', flush=True)
    results_location = os.path.join(results_root, results_file)
    write_results(results, results_location, impls)
    print('\nTests complete. Results written to %s.' % results_location)


def tokenize_description(description, has_name):
    """
    Splits comma-separated resource descriptions into tokens.
    :param description: String describing a resource, as described in the ion-test-driver CLI help.
    :param has_name: If True, there may be three tokens, the first of which must be the resource's name. Otherwise,
        there may be a maximum of two tokens, which represent the location and optional revision.
    :return: If `has_name` is True, three components (name, location, revision). Otherwise, two components
        (name, location)
    """
    components = description.split(',')
    max_components = 3
    if not has_name:
        max_components = 2
    if len(components) < max_components:
        revision = 'master'
    else:
        revision = components[max_components - 1]
    if len(components) < max_components - 1:
        raise ValueError("Invalid implementation description.")
    if has_name:
        return components[0], components[max_components - 2], revision
    else:
        return components[max_components - 2], revision


def parse_implementations(descriptions, output_root):
    return [IonImplementation(output_root, *tokenize_description(description, has_name=True))
            for description in descriptions]


def write_errors(report, first_field, first_report, second_field, second_report, field, msg):
    report[TestFile.ERROR_MESSAGE_FIELD] = msg
    errors = {}
    if first_field is not None:
        errors[first_field] = first_report
    if second_field is not None:
        errors[second_field] = second_report
    report[field] = errors


def write_to_report(cur_result, final_result, check_report, file, field):
    cur_result[field] = check_report
    final_result[file] = cur_result


def validate_read_location(location, test_file):
    location_array = location.split("/")
    if location_array[-1] != test_file:
        if location_array[-2] != 'data' or location_array[-3] != 'read' or location_array[-6] != 'results':
            raise ValueError("Invalid location path in file: " + test_file)


def validate_write_location(location, test_file):
    location_array = location.split("/")
    if location_array[-1] != test_file:
        if location_array[-2] != 'data' or (location_array[-3] != 'binary' and location_array[-3] != 'text') or location_array[-5] != 'write' or location_array[-8] != 'results':
            raise ValueError("Invalid location path in file: " + test_file)


def get_name(location, test_file):
    validate_read_location(location, test_file)
    name = location.split("/")[-1]
    if '.' in name:
        name = name[0:name.rfind('.')]
    return name


def get_name_for_write(location, test_file):
    validate_write_location(location, test_file)
    location_array = location.split("/")
    # implementation's name
    impl = location_array[-4]
    if '.' in impl:
        impl = impl[0:impl.rfind('.')]
    # type can be binary or text
    t = location_array[-3]
    # file name that be re-written
    file = location_array[-1]
    if '.' in file:
        file = file[0:file.rfind('.')]
    return impl, t, file


def find_disagree_list(failures_list, impl, test_file):
    disagree_list = []
    for report in failures_list:
        cur_first_impl = get_name(report['lhs']['location'], test_file)
        cur_second_impl = get_name(report['rhs']['location'], test_file)
        if impl == cur_first_impl and cur_second_impl not in disagree_list:
            disagree_list.append(cur_second_impl)
        if impl == cur_second_impl and cur_first_impl not in disagree_list:
            disagree_list.append(cur_first_impl)
    return disagree_list


def get_description_for_write(report, test_file, is_first):
    l = 'lhs' if is_first else 'rhs'
    cur_impl, cur_t, cur_file = get_name_for_write(report[l]['location'], test_file)
    if cur_t != "text" and cur_t != "binary":
        first_name = cur_file
    else:
        first_name = cur_impl + ',' + cur_t + ',' + cur_file
    return first_name


def append_description_for_write(impl, append_to_name, name, disagree_lists):
    if impl == append_to_name.split(',')[0]:
        if append_to_name not in disagree_lists:
            disagree_lists[append_to_name] = []
        if name not in disagree_lists[append_to_name]:
            disagree_lists[append_to_name].append(name)


def find_disagree_lists_for_write(failures_list, impl, test_file):
    disagree_lists = {}
    for report in failures_list:
        first_name = get_description_for_write(report, test_file, True)
        second_name = get_description_for_write(report, test_file, False)
        append_description_for_write(impl, first_name, second_name, disagree_lists)
        append_description_for_write(impl, second_name, first_name, disagree_lists)
    return disagree_lists


def append_list(first_list, second_list, match_impl, append_to_list):
    for impl in first_list:
        if impl not in second_list and impl != match_impl:
            append_to_list.append(impl)


def analyze_list(first_list, second_list, first_impl, second_impl):
    no_more_agree_list = []
    start_agree_list = []
    append_list(first_list, second_list, second_impl, start_agree_list)
    append_list(second_list, first_list, first_impl, no_more_agree_list)
    return no_more_agree_list, start_agree_list


def append_lists(first_lists, second_lists, append_to_lists):
    for k in first_lists.keys():
        if k not in second_lists.keys():
            append_to_lists[k] = first_lists[k]
        else:
            for impl in first_lists[k]:
                if impl not in second_lists[k]:
                    if k not in append_to_lists.keys():
                        append_to_lists[k] = []
                    append_to_lists[k].append(impl)


def analyze_lists(first_lists, second_lists):
    no_more_agree_lists = {}
    start_agree_lists = {}
    append_lists(first_lists, second_lists, start_agree_lists)
    append_lists(second_lists, first_lists, no_more_agree_lists)
    return no_more_agree_lists, start_agree_lists


def is_name_in_lists(lists, name):
    for k in lists.keys():
        if name in lists[k]:
            return True
    return False


def are_lists_agree(first_lists, second_lists):
    for k in first_lists.keys():
        if is_name_in_lists(second_lists, k):
            return False
    for k in second_lists.keys():
        if is_name_in_lists(first_lists, k):
            return False
    return True


def parse_des_for_res_diff(description):
    des_list = description.split(',')
    if len(des_list) == 2:
        name = des_list[0] + '_' + des_list[1]
    elif len(des_list) == 3:
        dir_name, f = os.path.split(ION_TEST_DRIVER_PATH)
        temp_dir = os.path.join(dir_name, 'temp')
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        check_call((TOOL_DEPENDENCIES['git'], 'clone', '--recursive', des_list[1], temp_dir), shell=COMMAND_SHELL)
        os.chdir(temp_dir)
        check_call((TOOL_DEPENDENCIES['git'], 'config', '--global', 'advice.detachedHead', 'false'), shell=COMMAND_SHELL)
        check_call((TOOL_DEPENDENCIES['git'], 'checkout', des_list[2]), shell=COMMAND_SHELL)
        commit = check_output((TOOL_DEPENDENCIES['git'], 'rev-parse', '--short', 'HEAD')).strip()
        name = des_list[0] + '_' + commit.decode()
        os.chdir(dir_name)
        shutil.rmtree(temp_dir)
    else:
        raise ValueError("Invalid implementation description.")
    return name


def write_errors_to_report(report, first_field, first_report, second_field, second_report, error_field, msg, cur_result,
                           final_result, test_file, report_field):
    write_errors(report, first_field, first_report, second_field,
                 second_report, error_field, msg)
    write_to_report(cur_result, final_result, report, test_file, report_field)


def validate_results(report, result_field, read_error, read_compare, write_error, write_compare, impl, test_file):
    if result_field not in report.keys():
        raise ValueError("Invalid result: missing result for '" + impl + "' in '" + test_file + "'.")
    if ion_equals(report[result_field], TestReport.PASS):
        if read_error in report.keys() or read_compare in report.keys() or write_error in report.keys() \
                or write_compare in report.keys():
            raise ValueError("Invalid report: result passes with error(s) for '" + impl + "' in '" + test_file + "'.")


def analyze_results(first_implementation, second_implementation, results_file, output_root):
    return_val = 0
    return_err = 1
    result_field = 'result'
    disagree_lists = 'disagree_lists'
    no_longer_agrees_with = 'no_longer_agrees_with'
    now_agrees_with = 'now_agrees_with'

    first_impl = parse_des_for_res_diff(first_implementation)
    second_impl = parse_des_for_res_diff(second_implementation)

    if first_impl.split('_')[0] != second_impl.split('_')[0]:
        raise ValueError("We only support analyzing two different revisions of the same implementation for now.")
    final_result = {}
    data = simpleion.load(FileIO(results_file))

    for test_type in data:
        files = data[test_type]
        for test_file in files:
            implementations = files[test_file]
            cur_result = {}
            first_report = None
            second_report = None
            for test_implementation in implementations:
                report = implementations[test_implementation]
                if test_implementation == first_impl:
                    first_report = report
                if test_implementation == second_impl:
                    second_report = report

            if first_report is None:
                raise ValueError("Didn't find the first implementation for file: '" + test_file + "'.")
            elif second_report is None:
                raise ValueError("Didn't find the second implementation for file: '" + test_file + "'.")

            # Step one analyze result field
            result_report = {}
            validate_results(first_report, result_field, TestReport.READ_ERROR, TestReport.READ_COMPARE,
                             TestReport.WRITE_ERROR, TestReport.WRITE_COMPARE, first_impl, test_file)
            validate_results(second_report, result_field, TestReport.READ_ERROR, TestReport.READ_COMPARE,
                             TestReport.WRITE_ERROR, TestReport.WRITE_COMPARE, second_impl, test_file)
            if ion_equals(first_report[result_field], TestReport.PASS) and \
                    ion_equals(second_report[result_field], TestReport.PASS):
                continue

            # Step two analyze read_error field
            read_report = {}
            first_read_error = first_report[TestReport.READ_ERROR] \
                if TestReport.READ_ERROR in first_report.keys() else []
            second_read_error = second_report[TestReport.READ_ERROR] \
                if TestReport.READ_ERROR in second_report.keys() else []
            if first_read_error != second_read_error:
                new_errors = []
                for err in second_read_error:
                    if err not in first_read_error:
                        new_errors.append(err)
                message = "Read_error: new commit has different read error(s)."
                write_errors_to_report(read_report, first_impl, first_read_error, second_impl, second_read_error,
                                       TestReport.READ_ERROR, message, cur_result, final_result, test_file,
                                       TestReport.READ_ERROR)
                if any(new_errors):
                    return_val = return_err
                    continue

            # Step three analyze read_compare field
            read_compare_report = {}
            # check if 'errors' field same
            first_read_compare = first_report[
                TestReport.READ_COMPARE] if TestReport.READ_COMPARE in first_report.keys() else {}
            second_read_compare = second_report[
                TestReport.READ_COMPARE] if TestReport.READ_COMPARE in second_report.keys() else {}
            first_read_compare_errors = first_read_compare[TestReport.ERRORS_FIELD] \
                if TestReport.ERRORS_FIELD in first_read_compare.keys() else []
            second_read_compare_errors = second_read_compare[TestReport.ERRORS_FIELD] \
                if TestReport.ERRORS_FIELD in second_read_compare.keys() else []
            if first_read_compare_errors != second_read_compare_errors:
                new_errors = []
                for err in second_read_compare_errors:
                    if err not in first_read_compare_errors:
                        new_errors.append(err)
                message = "Read_compare: new commit has different read compare error(s)."
                write_errors_to_report(read_compare_report, first_impl, first_read_compare, second_impl,
                                       second_read_compare, TestReport.READ_COMPARE, message, cur_result,
                                       final_result, test_file, TestReport.READ_COMPARE)
                if any(new_errors):
                    return_val = return_err
                    continue
            # check if 'failures' field same
            first_read_compare_failures = first_read_compare[TestReport.COMPARISON_FAILURES_FIELD] \
                if TestReport.COMPARISON_FAILURES_FIELD in first_read_compare.keys() else []
            second_read_compare_failures = second_read_compare[TestReport.COMPARISON_FAILURES_FIELD] \
                if TestReport.COMPARISON_FAILURES_FIELD in second_read_compare.keys() else []
            if first_read_compare_failures != second_read_compare_failures:
                message = "Read_compare: two revisions have different failures."
                write_errors_to_report(read_compare_report, first_impl, first_read_compare, second_impl,
                                       second_read_compare, TestReport.COMPARISON_FAILURES_FIELD, message, cur_result,
                                       final_result, test_file, TestReport.READ_COMPARE)
                return_val = return_err
                continue
            # get two disagree lists
            first_disagree_list = find_disagree_list(first_read_compare_failures, first_impl, test_file)
            second_disagree_list = find_disagree_list(first_read_compare_failures, second_impl, test_file)
            # analyze disagree list
            if second_impl not in first_disagree_list and first_impl not in second_disagree_list:
                if first_disagree_list != second_disagree_list:
                    message = "Read_compare: two revisions agree with each other " \
                              "but have different disagree lists. "
                    write_errors_to_report(read_compare_report, first_impl, first_disagree_list, second_impl,
                                           second_disagree_list, disagree_lists, message,
                                           cur_result, final_result, test_file, TestReport.READ_COMPARE)
                    no_more_agree_list, start_agree_list = analyze_list(first_disagree_list, second_disagree_list,
                                                                        first_impl, second_impl)
                    if any(no_more_agree_list):
                        return_val = return_err
                        continue
            elif second_impl in first_disagree_list and first_impl in second_disagree_list:
                no_more_agree_list, start_agree_list = analyze_list(first_disagree_list, second_disagree_list,
                                                                    first_impl, second_impl)
                read_compare_report = {
                    TestFile.ERROR_MESSAGE_FIELD: "Read_compare: read behavior changed against other "
                                                  "implementations.",
                    disagree_lists: {first_impl: first_disagree_list, second_impl: second_disagree_list},
                    no_longer_agrees_with: no_more_agree_list,
                    now_agrees_with: start_agree_list
                }
                write_to_report(cur_result, final_result, read_compare_report, test_file, TestReport.READ_COMPARE)
                return_val = return_err
                continue

            # Step four analyze write_error field
            write_report = {}
            first_write_error = first_report[TestReport.WRITE_ERROR] \
                if TestReport.WRITE_ERROR in first_report.keys() else []
            second_write_error = second_report[TestReport.WRITE_ERROR] \
                if TestReport.WRITE_ERROR in second_report.keys() else []
            if first_write_error != second_write_error:
                new_errors = []
                for err in second_write_error:
                    if err not in first_write_error:
                        new_errors.append(err)
                message = "Write_error: new commit has different write error(s)."
                write_errors_to_report(write_report, first_impl, first_write_error, second_impl,
                                       second_write_error, TestReport.WRITE_ERROR, message, cur_result,
                                       final_result, test_file, TestReport.WRITE_ERROR)
                if any(new_errors):
                    return_val = return_err
                    continue

            # Step five analyze write_compare field
            write_compare_report = {}
            # check if 'errors' field same
            first_write_compare = first_report[TestReport.WRITE_COMPARE] \
                if TestReport.WRITE_COMPARE in first_report.keys() else {}
            second_write_compare = second_report[TestReport.WRITE_COMPARE] \
                if TestReport.WRITE_COMPARE in second_report.keys() else {}
            first_write_compare_errors = first_write_compare[TestReport.ERRORS_FIELD] \
                if TestReport.ERRORS_FIELD in first_write_compare.keys() else []
            second_write_compare_errors = second_write_compare[TestReport.ERRORS_FIELD] \
                if TestReport.ERRORS_FIELD in second_write_compare.keys() else []
            if first_write_compare_errors != second_write_compare_errors:
                new_errors = []
                for err in second_write_compare_errors:
                    if err not in first_write_compare_errors:
                        new_errors.append(err)
                message = "Write_compare: new commit has different write compare error(s)"
                write_errors_to_report(write_compare_report, first_impl, first_write_compare, second_impl,
                                       second_write_compare, TestReport.WRITE_COMPARE, message, cur_result,
                                       final_result, test_file, TestReport.WRITE_COMPARE)
                if any(new_errors):
                    return_val = return_err
                    continue
            # check if 'failures' field same
            first_write_compare_failures = first_write_compare[TestReport.COMPARISON_FAILURES_FIELD] \
                if TestReport.COMPARISON_FAILURES_FIELD in first_write_compare.keys() else []
            second_write_compare_failures = second_write_compare[TestReport.COMPARISON_FAILURES_FIELD] \
                if TestReport.COMPARISON_FAILURES_FIELD in second_write_compare.keys() else []
            if first_write_compare_failures != second_write_compare_failures:
                message = "Write_compare: two revisions have different failures."
                write_errors_to_report(write_compare_report, first_impl, first_write_compare, second_impl,
                                       second_write_compare, TestReport.COMPARISON_FAILURES_FIELD, message,
                                       cur_result, final_result, test_file, TestReport.WRITE_COMPARE)
                return_val = return_err
                continue
            # get two disagree lists
            first_disagree_list_for_write = find_disagree_lists_for_write(first_write_compare_failures, first_impl, test_file)
            second_disagree_list_for_write = find_disagree_lists_for_write(second_write_compare_failures, second_impl, test_file)
            if not are_lists_agree(first_disagree_list_for_write, second_disagree_list_for_write):
                no_more_agree_lists, start_agree_lists = analyze_lists(first_disagree_list_for_write,
                                                                       second_disagree_list_for_write)
                write_compare_report = {
                    TestFile.ERROR_MESSAGE_FIELD: "Write_compare: write behavior changed. "
                                                  "Each field within disagree list represents the implementation that "
                                                  "is re-writing other implementations. Description below following "
                                                  "the format: 'impl,type,file' where impl is the implementation used "
                                                  "for writing files, type is either 'text' or 'binary' and "
                                                  "file is the file that is re-written",
                    disagree_lists: {first_impl: first_disagree_list_for_write,
                                     second_impl: second_disagree_list_for_write},
                    no_longer_agrees_with: no_more_agree_lists,
                    now_agrees_with: start_agree_lists,
                }
                write_to_report(cur_result, final_result, write_compare_report, test_file, TestReport.WRITE_COMPARE)
                return_val = return_err
                continue

    if '.' in output_root:
        output_root = output_root[0:output_root.rfind('.')] + '.ion'
    else:
        output_root = output_root + '.ion'
    simpleion.dump(final_result, FileIO(output_root, mode='wb'), binary=False, indent=' ')
    print('Analysis complete with status \'%d\'. Results written to %s.' % (return_val, output_root))
    sys.exit(return_val)


def ion_test_driver(arguments):
    if arguments['--help']:
        print(__doc__)
    elif arguments['--list']:
        for impl_name in ION_BUILDS.keys():
            if impl_name != 'ion-tests':
                print(impl_name)
    elif arguments['--results-diff']:
        output_root = os.path.abspath(arguments['--output-dir'])
        if arguments['--output-dir'] == '.':
            output_root = os.path.join(output_root, 'result.ion')
        first_implementation = arguments['<first_description>']
        second_implementation = arguments['<second_description>']
        results_file = os.path.abspath(arguments['<results_file>'])
        return analyze_results(first_implementation, second_implementation, results_file, output_root)
    else:
        output_root = os.path.abspath(arguments['--output-dir'])
        if not os.path.exists(output_root):
            os.makedirs(output_root)
        implementations = parse_implementations(arguments['--implementation'], output_root)
        if not arguments['--local-only']:
            implementations += parse_implementations(ION_IMPLEMENTATIONS, output_root)
        check_tool_dependencies(arguments)
        for implementation in implementations:
            implementation.install()
        ion_tests_source = arguments['--ion-tests']
        if not ion_tests_source:
            ion_tests_source = ION_TESTS_SOURCE
        ion_tests_dir = IonResource(
            output_root, 'ion-tests', *tokenize_description(ion_tests_source, has_name=False)
        ).install()
        results_root = os.path.join(output_root, 'results')
        results_file = arguments['--results-file']
        if not results_file:
            results_file = RESULTS_FILE_DEFAULT
        test_type_strs = arguments['--test']
        if 'all' in test_type_strs:
            test_types = list(TestType.__iter__())
        else:
            test_types = [test_type_from_str(x) for x in test_type_strs]
        test_file_filter = arguments['<test_file>']
        test_all(implementations, ion_tests_dir, test_types, test_file_filter, results_root, results_file)


if __name__ == '__main__':
    ion_test_driver(docopt(__doc__))
