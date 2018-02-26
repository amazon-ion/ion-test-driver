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
    ion_test_driver.py [--implementation <description>]... [--ion-tests <description>] [--test <type>]... [--local-only] [--cmake <path>] [--git <path>] [--output-dir <dir>] [--results-file <file>] [<test_file>]...
    ion_test_driver.py (--list)
    ion_test_driver.py (-h | --help)

Options:
    --cmake <path>                      Path to the cmake executable.

    --git <path>                        Path to the git executable.

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

    -t, --test <type>                   Perform a particular test type or types, chosen from `good`, `bad`, `equivs`,
                                        `non-equivs`, and `all`. [default: all]


"""
import os
import shutil
from io import FileIO
from subprocess import check_call, check_output, Popen, PIPE
import six
from amazon.ion import simpleion
from amazon.ion.core import IonType
from amazon.ion.simple_types import IonPySymbol, IonPyList
from amazon.ion.util import Enum
from docopt import docopt

from amazon.iontest.ion_test_driver_config import TOOL_DEPENDENCIES, ION_BUILDS, ION_IMPLEMENTATIONS, ION_TESTS_SOURCE,\
    RESULTS_FILE_DEFAULT
from amazon.iontest.ion_test_driver_util import COMMAND_SHELL, log_call

"""
Generates a report according to the following schema-by-example. Two versions will be generated: one according to the
following, and one that switches the implementation and test file dimensions.

{
    good: {
        'test_file_1.ion': {
            'ion-c_abcd123': {
                result: PASS 
            }
        },
        'test_file_2.ion': {
            'ion-c_abcd123': {
                result: FAIL,
                read_failures: ErrorReport::[{
                    error_type: READ,
                    message: "ion_reader_text.c:999 Line 1 index 3: Numeric values must not have repeated underscores.",
                    location: "test_file_2.ion"
                }]
            }
        }
    },
    bad: {
        'test_file_3.ion': {
            'ion-c_abcd123' : {
                result : FAIL
            }
        }
    },
    equivs: {
        'test_file_4.ion': {
            'ion-c_abcd123': {
                result: PASS
            }
        },
        'test_file_5.ion': {
            'ion-c_abcd123': {
                result: FAIL,
                read_compare: {
                    errors: []
                    failures: [
                        ComparisonResult::{
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
                                location: "test_file_5.ion",
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
                        }
                    ]
                }
            }
        }
    }
}
"""

ION_SUFFIX_TEXT = '.ion'
ION_SUFFIX_BINARY = '.10n'


def check_tool_dependencies(args):
    names = TOOL_DEPENDENCIES.keys()
    for name in names:
        path = args['--' + name]
        if path:
            TOOL_DEPENDENCIES[name] = path
    for name, path in six.iteritems(TOOL_DEPENDENCIES):
        try:
            # NOTE: if a tool dependency is added that doesn't have a `--help` command, the logic should be generalized
            # to call a tool-specific command to test the existence of the executable. This should be a command that
            # always returns zero.
            no_output = open(os.devnull, 'w')
            check_call([path, '--help'], stdout=no_output, shell=COMMAND_SHELL)
        except:
            raise ValueError(name + " not found. Try specifying its location using --" + name + ".")
        finally:
            no_output.close()


class IonResource:
    def __init__(self, output_root, name, location, revision):
        self.__output_root = output_root
        try:
            self._build = ION_BUILDS[name]
        except KeyError:
            raise ValueError('No installer for %s.' % name)
        self._name = name
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
                log_call(tmp_log, (TOOL_DEPENDENCIES['git'], 'submodule', 'update'))
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
        _, stderr = Popen((self._executable,) + args, stderr=PIPE, shell=COMMAND_SHELL).communicate()
        return stderr


class TestResult:
    def __init__(self, impl_id, output_location, error_location):
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
        field = TestReport.READ_ERROR if is_read else TestReport.WRITE_ERROR
        self.__set_read_write_error(field, result.errors)

    def fail_compare(self, compare_result, is_read):
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

    def __init__(self, path, test_type, output_root, ion_implementations):
        self.path = path
        self.short_path = os.path.split(self.path)[-1]
        self.__read_results = []
        self.__write_results = []
        self.__type = test_type
        self.__results_root = os.path.join(output_root, str(test_type), self.short_path)
        self.__report = {impl.identifier: TestReport() for impl in ion_implementations}  # Initializes PASS results
        self.__ion_implementations = ion_implementations

    def __execute_with(self, ion_implementation, error_location, *args):
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
        # Sample directory structure: results/good/one.ion/read/data/ion-c_abcd123.ion
        read_output = self.__new_results_file(ion_implementation.identifier + ION_SUFFIX_TEXT, TestFile.READ_DATA_DIR)
        read_errors = self.__new_results_file(ion_implementation.identifier + ION_SUFFIX_TEXT, TestFile.READ_ERRORS_DIR)
        self.__execute_with(ion_implementation, read_errors,
                            'process', '--error-report', read_errors, '--output', read_output, '--output-format',
                            'events', self.path)
        result = TestResult(ion_implementation.identifier, read_output, read_errors)
        self.__read_results.append(result)
        return result

    def __compare(self, ion_implementation, compare_type, compare_result, inputs, is_read, is_sets=False):
        self.__execute_with(ion_implementation, compare_result.error_location,
                            'compare', '--error-report', compare_result.error_location, '--output',
                            compare_result.output_location, '--comparison-type', compare_type, *inputs)
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
        # Example directory structure: results/good/one.ion/write/ion-c_abcd123/text/data/ion-java_cdef456.ion
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
                                        'process', '--error-report', write_errors, '--output', write_output,
                                        '--output-format', encoding, read_result.output_location)
                    self.__write_results.append(TestResult(ion_implementation.identifier, write_output, write_errors))

    def read(self):
        for ion_implementation in self.__ion_implementations:
            self.__read_with(ion_implementation)

    def verify_reads(self):
        self.__verify(self.__read_results, is_read=True)

    def write(self):
        if self.__type.is_bad:  # bad files skip this phase.
            return
        for ion_implementation in self.__ion_implementations:
            self.__write_with(ion_implementation)

    def verify_writes(self):
        if self.__type.is_bad:  # bad files skip this phase.
            return
        self.__verify(self.__write_results, is_read=False)

    def add_results_to(self, results):
        results.setdefault(str(self.__type), {})[self.short_path] = self.__report


def test_file_class_for(name, test_type):
    class TestFileSubclass(TestFile):
        def __init__(self, path, results_root, ion_implementations):
            super(TestFileSubclass, self).__init__(path, test_type, results_root, ion_implementations)

    TestFileSubclass.__name__ = name
    return TestFileSubclass


GoodTestFile = test_file_class_for('GoodTestFile', TestType.GOOD)
BadTestFile = test_file_class_for('BadTestFile', TestType.BAD)
GoodEquivsTestfile = test_file_class_for('GoodEquivsTestfile', TestType.EQUIVS)
GoodEquivsTimelineTestfile = test_file_class_for('GoodEquivsTimelineTestfile', TestType.EQUIV_TIMELINE)
GoodNonequivsTestfile = test_file_class_for('GoodNonequivsTestfile', TestType.NON_EQUIVS)


def generate_test_files(tests_dir, test_types, test_file_filter, results_root, ion_implementations):
    def filter_files(test_file_cls):
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
            yield test_file_cls(full_test_file, results_root, ion_implementations)

    test_file_root = os.path.abspath(os.path.join(tests_dir, 'iontestdata'))
    if not os.path.exists(test_file_root):
        raise ValueError("Invalid ion-tests directory. Could not find test files.")
    for root, dirs, files in os.walk(test_file_root):
        if os.path.join('iontestdata', str(TestType.GOOD)) in root:
            if os.path.join(str(TestType.GOOD), str(TestType.EQUIVS)) in root and TestType.EQUIVS in test_types:
                for equivs_file in filter_files(GoodEquivsTestfile):
                    yield equivs_file
            elif os.path.join(str(TestType.GOOD), str(TestType.NON_EQUIVS)) in root \
                    and TestType.NON_EQUIVS in test_types:
                for nonequivs_file in filter_files(GoodNonequivsTestfile):
                    yield nonequivs_file
            elif os.path.join(str(TestType.GOOD), 'timestamp', 'equivTimeline') in root \
                    and TestType.EQUIV_TIMELINE in test_types:
                for equiv_timeline_file in filter_files(GoodEquivsTimelineTestfile):
                    yield equiv_timeline_file
            elif TestType.GOOD in test_types:
                for good_file in filter_files(GoodTestFile):
                    yield good_file
        elif os.path.join('iontestdata', str(TestType.BAD)) in root and TestType.BAD in test_types:
            for bad_file in filter_files(BadTestFile):
                yield bad_file


def write_results(results, results_file, impls):
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


def ion_test_driver(arguments):
    if arguments['--help']:
        print(__doc__)
    elif arguments['--list']:
        for impl_name in ION_BUILDS.keys():
            if impl_name != 'ion-tests':
                print(impl_name)
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
