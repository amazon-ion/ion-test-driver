Ion Test Driver
============================

A cross-implementation test driver for
[Amazon Ion](http://amzn.github.io/ion-docs/) readers and writers.

[![Build Status](https://travis-ci.org/amzn/ion-test-driver.svg?branch=master)](https://travis-ci.org/amzn/ion-test-driver)

License
============================

This tool is licensed under the Apache 2.0 License.

Usage
============================

The entry point for the tool is `amazon/iontest/ion_test_driver.py`,
which targets Python 3.5+. Running the script with the `--help`
command will enumerate the available options.

Design
============================

The cross-implementation test harness compares the behavior of all
Ion implementations in order to assert consensus.

This provides developers:

-   An automated way of verifying that all implementations maintain
    consistent reading/writing behavior.
-   A large amount of test coverage with minimal test-specific
    integration effort.

This provides users:

-   A centralized dashboard summarizing the limitations of each
    implementation, which may be used when evaluating which
    implementation to use.
-   Confidence that their Ion data is not coupled to a particular
    reader/writer implementation.

Prerequisites
-------------

Each implementation should have its own set of unit tests to assert
correctness of its behavior. There are three reasons for this:

1. The cross-implementation test harness depends on each implementation,
   not vice-versa; intra-implementation unit tests are therefore
   required for rapid development of that implementation.
2. Integration with the cross-implementation harness requires Ion
   readers and writers that can correctly perform their basic functions
   (in order to send and receive instructions through the CLI).
3. The cross-implementation testing harness is not intended to verify
   correctness of each implementation; rather, its purpose is to
   verify behavioral consensus among all implementations under the
   assumption that at least one of them is correct.

In addition to certain hand-coded unit tests used to exercise targeted
code paths, each implementation should have its own ion-tests harness
that fully implements the `good`, `bad`, `good/equivs`, and
`good/non-equivs` semantics. This will provide some duplicate coverage
upon integration with the cross-implementation testing harness, but will
enable a rapid development and testing cycle within that implementation.
It is advisable to implement this test harness such that it can read Ion
streams into EventStreams (described in the sections that follow),
compare in-memory EventStreams for equivalence, and write EventStreams
to Ion streams. This will simplify integration with the
cross-implementation testing harness.

Structures
----------

### SymbolToken

**ImportLocation**: `(import_name: string, location: int)`

**SymbolToken**: `(text: string, import_location: ImportLocation)`,
where `(null, null)` represents symbol zero.

*Note*: Implementations that are fully spec-compliant will already
provide a SymbolToken implementation that is compatible with the above
definition.

### Event

An Event represents a single read or write event within an Ion stream. A
stream of such Events is an EventStream, which can be interpreted as
both Ion reader output and Ion writer input. When Ion stream A is read
as EventStream E, and E is written as Ion stream B, A and B must be
equivalent under the Ion data model.

When a field is not valid for a particular event, that field should be
omitted. Missing fields should be treated equivalently to `null` fields
(for any type of `null`).

**EventType**:
`symbol[CONTAINER_START | CONTAINER_END | SCALAR | SYMBOL_TABLE | STREAM_END]`

**IonType**:
`symbol[NULL | BOOL | INT | FLOAT | DECIMAL | TIMESTAMP | SYMBOL | STRING | CLOB | BLOB | LIST | SEXP | STRUCT]`

**ImportDescriptor**:
`(import_name: string, max_id: int, version: int)`

**Event**:
`(event_type: EventType, ion_type: IonType, field_name: SymbolToken, annotations: list<SymbolToken>, value_text: string, value_binary: list<byte>, imports: list<ImportDescriptor>, depth: int)`

**EventStream**:
`stream<Event>`, initiated (after the IVM, if applicable) by the top-level
symbol `$ion_event_stream`.

### ErrorReport

**ErrorType**: `symbol[READ | WRITE | STATE]`

**ErrorDescription**:
`(error_type: ErrorType, message: string, location: string, event_index: int)`,
where `location` refers to the input file (for `READ` and certain `STATE`
errors), or the output file (for `WRITE` and certain `STATE` errors);
`event_index` refers to the index of the event being processed when the
error was raised, if known; and `message` can be used to convey the source
file and line number at which the error occurred, and a reason for the error.

**ErrorReport**: `stream<ErrorDescription>`

### ComparisonReport

**ComparisonResultType**: `symbol[EQUAL | NOT_EQUAL | ERROR]`

**ComparisonContext**:
`(location: string, event: Event, event_index: int)`

**ComparisonResult**:
`(result: ComparisonResultType, lhs: ComparisonContext, rhs: ComparisonContext, message: string)`

**ComparisonReport**: `stream<ComparisonResult>`

ComparisonResults should only be generated when the result of the
comparison differs from what was expected.

For example, comparing the stream (contained in `stream_a.ion`)
`abc [1]` to (contained in `stream_b.ion`) `abc [2]` would produce the
following serialized ComparisonReport when the two streams are expected
to be equivalent:

    {result: NOT_EQUAL, lhs:{location: "stream_a.ion", event: {event_type: SCALAR, ion_type: INT, value_text: "1", value_binary: [0x21, 0x01], depth:1}, event_index: 2}, rhs:{location: "stream_b.ion", event: {event_type: SCALAR, ion_type: INT, value_text: "2", value_binary: [0x21, 0x02], depth:1}, event_index:2}, message: "1 vs. 2"}

Note that this ComparisonReport contains only one ComparisonResult
because only one event pair was not equal.

### PerformanceReport

**PerformanceIO**:
`(name: string, size: int)`

**PerformanceReport**:
`(options: string, input: PerformanceIO, output: PerformanceIO, memory_usage: int, elapsed_time: int)`

For example, the command

    ion-c process -f binary -p perf.ion -o customer.10n customer.ion

could produce the following serialized PerformanceReport:

    {options: "-f binary", output: {name: "customer.10n", size: 12345}, input: {name: "customer.ion", size: 12345}, memory_usage:12345, elapsed_time:12345}

### ReadInstruction

**ReadInstruction**: `symbol[NEXT | SKIP]`, where NEXT tells the reader to
emit the event representing the next value in the stream (stepping in if
it is currently positioned on a container), and SKIP (which does nothing
at the top-level) tells the reader to skip to the end of the current
container, step out, and emit a CONTAINER\_END event.

**ReadInstructionStream**: `stream<ReadInstruction>`

Terms
-----

### Embedded Ion stream

In a `good/equivs` or `good/non-equivs` vector, a string element of a
top-level Ion sequence (list or s-expression) annotated with
"embedded\_documents" (soon to be "$ion\_embedded\_streams"). This
string should be interpreted as a stream of text Ion data. For example,
in the following Ion stream,

    $ion_embedded_streams::(
        "$ion_1_0 abc"
        '''$ion_1_0 $ion_symbol_table::{symbols:["abc"]} $10'''
    )

both of the elements of the s-expression are interpreted as Ion streams.

### Embedded EventStream

In an EventStream, a sequence of Events between the depth-zero
CONTAINER\_START and CONTAINER\_END events for an Ion sequence (list or
s-expression) with the "embedded\_documents" (soon to be
"$ion\_embedded\_streams") annotation, representing a standalone
EventStream. These embedded EventStreams always restart at depth zero
and end with a STREAM\_END event. For example, the following
EventStream

    $ion_event_stream
    {event_type: CONTAINER_START, ion_type: SEXP, annotations: [{text:"$ion_embedded_streams"}], depth:0}
    {event_type: SCALAR, ion_type: INT, value_text: "10", value_binary: [0x21, 0x0A], depth:0}
    {event_type: STREAM_END, depth:0}
    {event_type: SCALAR, ion_type: INT, value_text: "10", value_binary: [0x21, 0x0A], depth:0}
    {event_type: STREAM_END, depth:0}
    {event_type: CONTAINER_END, ion_type: SEXP, depth:0}
    {event_type: STREAM_END, depth:0}

contains two embedded EventStreams, each with a single top-level int.

Testing equality
----------------

### ImportLocation

Both import_name and location must be defined, and the corresponding
fields must be exactly equal.

### SymbolToken

1.  Compare *text*. If equal, the symbol tokens are equivalent. If not
    equal,
2.  Compare *import_location*s.

### Event

1.  Compare *event\_type*. If equal,
2.  Compare *depth*. If equal,
3.  Compare *ion\_type*. If equal,
4.  Compare *field\_name* for SymbolToken equality. If equal,
5.  Compare each annotation in *annotations* for SymbolToken equality.
    If equal,
6.  For SCALAR events, read the *value\_text* and *value\_binary* from
    both events into EventStreams, which each must contain exactly one
    SCALAR event. Extract the scalar value from each of these events
    into the appropriate programming language type. Assert that the
    *value\_text* and *value\_binary* values from the same Event are
    equivalent. Finally, compare under the Ion data model either value
    against the value produced by the other event.

### EventStream

The recursive algorithm for determining EventStream equality is better
expressed in code than in prose. However, there are a few things to
note:

-   EventStream equivalence cannot simply be determined by comparing
    Events at corresponding indices. This is because
    -   A container value is comprised of at least two Events, and
        structs are unordered.
    -   Streams with symbol table boundaries at different positions in
        the stream may still be equivalent. Therefore, when a
        SYMBOL\_TABLE event is encountered in either stream, that event
        must be skipped.
-   Between the CONTAINER\_START and CONTAINER\_END events for structs,
    value Events need to be matched using field names. Because structs
    may have multiple values for the same field name, determining that
    two events have equal field names but unequal values is not
    sufficient to determine non-equivalence unless all other field
    name/value pairs have already been compared.

Standardized CLI
----------------

The CLI provides a common language-agnostic interface for all
implementations. It is designed to be useful not only to the tests, but
also to users. That said, it contains certain features that may not be
useful to users (e.g. support for embedded streams); it may be desirable
to provide wrappers over this CLI that simplify common commands (e.g.
jq-like filtering) and hide the features that exist to facilitate
internal testing. In the end, each implementation that integrates with
the test harness will have a well-tested user-facing CLI (or set of
CLIs).

Each implementation of the CLI should support being used in
"interactive mode," which may be entered by invoking the executable
with zero arguments. In this mode, the CLI will accept commands and
provide responses until interrupted; the behavior of the individual
commands will be equivalent between interactive and non-interactive
modes. This may be useful in languages with a high startup and/or
shutdown cost.

Command invocations that result in errors will exit with non-zero status
codes. All other command invocations will exit with status code zero.

    Usage:
        ion
        ion process [--output <file>] [--error-report <file>] [--output-format (text | pretty | binary | events | none)]    [--catalog <file>]... [--imports <file>]... [--perf-report <file>] [--filter <filter> | --traverse <file>]  [-] [<input_file>]...
        ion compare [--output <file>] [--error-report <file>] [--output-format (text | pretty | binary | none)]             [--catalog <file>]... [--comparison-type (basic | equivs | non-equivs | equiv-timeline)]                    [-] [<input_file>]...
        ion extract [--output <file>] [--error-report <file>] [--output-format (text | pretty | binary | none)]             (--symtab-name <name>) (--symtab-version <version>)                                                         [-] [<input_file>]...
        ion help    [extract | compare | process]
        ion --help
        ion version
        ion --version

    Commands:
        extract     Extract the symbols from the given input(s) into a shared symbol table with the given name and
                    version.

        compare     Compare all inputs (which may contain Ion streams and/or EventStreams) against all other inputs
                    using the Ion data model's definition of equality. Write a ComparisonReport to the output.

        process     Read the input file(s) (optionally, specifying ReadInstructions or a filter) and re-write in the
                    format specified by --output.

        help        Print this general help. If provided a command, prints help specific to that command.

        version     Print version information about this tool.

    Options:
        -o, --output <file>
            Output location. [default: stdout]

        -f, --output-format <type>
            Output format, from the set (text | pretty | binary | events| none). 'events' is only available with the
            'process' command, and outputs a serialized EventStream representing the input Ion stream(s).
            [default: pretty]

        -e, --error-report <file>
            ErrorReport location. [default: stderr]
        
        -p, --perf-report <file>
            PerformanceReport location. If left unspecified, a performance report is not generated.
        
        -c, --catalog <file>
            Location(s) of files containing Ion streams of shared symbol tables from which to populate a catalog. This
            catalog will be used by all readers and writers when encountering shared symbol table import descriptors.
        
        -i, --imports <file>
            Location(s) of files containing list(s) of shared symbol table import descriptors. These imports will be
            used by writers during serialization. If a catalog is available (see: --catalog), the writer will attempt
            to match those import descriptors to actual shared symbol tables using the catalog.
        
        -F, --filter <filter>
            JQ-style filter to perform on the input stream(s) before writing the result.
        
        -t, --traverse <file>
            Location of a file containing a stream of ReadInstructions to use when reading the input stream(s) instead
            of performing a full traversal.
        
        -n, --symtab-name <symtab_name>
            Name of the shared symbol table to be extracted.
        
        -V, --symtab-version <symtab_version>
            Version of the shared symbol table to be extracted.
        
        -y, --comparison-type (basic | equivs | non-equivs | equiv-timeline)
            Comparison semantics to be used with the compare command, from the set (basic | equivs | non-equivs |
            equiv-timeline). Any embedded streams in the inputs are compared for EventStream equality. 'basic' performs
            a standard data-model comparison between the corresponding events (or embedded streams) in the inputs.
            'equivs' verifies that each value (or embedded stream) in a top-level sequence is equivalent to every other
            value (or embedded stream) in that sequence. 'non-equivs' does the same, but verifies that the values (or
            embedded streams) are not equivalent. 'equiv-timeline' is the same as 'equivs', except that when top-level
            sequences contain timestamp values, they are considered equivalent if they represent the same instant
            regardless of whether they are considered equivalent by the Ion data model. [default: basic]

        -h, --help
            Synonym for the help command.
        
        --version
            Synonym for the version command.
        
    Examples:
        Read input.10n and pretty-print it to stdout.
            $ ion process input.10n

        Read input.ion (using a catalog comprised of the shared symbol tables contained in catalog.10n) without
        re-writing, and write a performance report to stdout.
            $ ion process --output-format none --catalog catalog.10n --perf-report -- input.10n
            
        Read input.10n according to the ReadInstructions specified by instructions.ion and write the resulting Events
        to output.ion.
            $ ion process -o output.ion -f events -t instructions.ion input.10n

        Extract a shared symbol table with name "foo_table" and version 1 from the piped Ion stream and write it in
        binary format to foo_table.10n.
            $ echo 'foo' | ion extract -n 'foo_table' -V 1 -o foo_table.10n -f binary -
            
        Read input1.ion and input2.10n and output to stdout any values in the streams that match the filter .foo.
            $ ion process --filter .foo input1.ion input2.10n

        Compare each stream in read_events.ion, input1.ion, and input2.10n against all other streams in the set and
        output a ComparisonReport to comparison_report.ion.
            $ ion compare -o comparison_report.ion read_events.ion input1.ion input2.10n

Reading Ion streams
-------------------

### With ReadInstructions to define the traversal

ReadInstructions can be translated into reader API calls, allowing tests
to define a traversal for a particular test stream (see `--traverse`).

When not positioned on a container, the NEXT instruction translates into
`reader.next()` in ion-java. When positioned on a container (meaning
that the `event_type` of the last event emitted was CONTAINER\_START),
the NEXT instruction translates to `reader.stepIn()` followed by
`reader.next()` in ion-java. In both cases, emit an event representing
the value at the reader's new position.

When at the top-level and not positioned on a container, the SKIP
instruction has no effect. When at a depth of at least one and not
positioned on a container, the SKIP instruction translates to
`reader.stepOut()` in ion-java. When positioned on a container at any
depth (meaning that the last event emitted had event\_type
CONTAINER\_START), the SKIP instruction translates to `reader.next()` in
ion-java, which skips over the container without stepping in. Whenever
SKIP has an effect, emit a CONTAINER\_END event.

If the ReadInstruction stream ends before the reader reaches the end of
its Ion stream,

-   If the reader is at depth zero, finish reading and convey success.
-   If the reader is at depth greater than zero, write an
    ErrorDescription to the ErrorReport.

If the reader reaches the end of the stream (and emits a STREAM\_END
event) before the ReadInstruction stream ends, write an ErrorDescription
to the ErrorReport.

### Without ReadInstructions

Perform a full traversal of the test stream, stepping into and fully
iterating every container encountered.

Reading an Ion stream into an EventStream
-----------------------------------------

With or without ReadInstructions, an Ion stream can be read into an
EventStream (`--output-format events`).

When the reader encounters a value that is not a system value, create an
event of the appropriate event\_type (CONTAINER\_START for containers,
otherwise SCALAR), and set the event's `ion_type` to the type of the
current value. Also set the event's `depth` to the reader's current
depth (where the top-level is depth zero), set the event's `field_name`
if the value is in a struct, and set any annotations on the current
value. For SCALAR events, initialize temporary writers (with any shared
symbol tables required by symbol tokens with unknown text) to
re-serialize their values as both text and binary Ion (including a local
symbol table, if required) into the event's `value_text` and
`value_binary` fields, respectively. If the scalar is a symbol value
with the same text as an IVM, the serialized Ion value contained in
the `value_text` and `value_binary` fields must be annotated with the
special `$ion_user_value` annotation. This prevents the writers from
interpreting the IVM-like symbol as an IVM and prescribing IVM
semantics. This annotation is always ignored by EventStream readers.

When the reader reaches the end of the current container, create a
CONTAINER\_END event with the same `ion_type` and depth as that
container's corresponding CONTAINER\_START event; leave all other fields
in the event undefined.

When the reader encounters a local symbol table, create a SYMBOL\_TABLE
event. Set this event's `imports` field to a list of ImportDescriptors
representing any shared symbol table imports included by the new local
symbol table. These will be used by writers following this event in the
stream. Set the event's `depth` to zero and leave all other fields in
the event undefined. SYMBOL\_TABLE events are always skipped during
EventStream comparison.

Denote the end of the stream with a STREAM\_END event. Set the event's
`depth` to zero and leave all other fields in the event undefined.

If, before the end of the stream, the reader raises an error for any
reason, write an ErrorDescription to the ErrorReport. Abort reading
without writing any additional Events to the EventStream.

### Example

A `good` input file called `bar_baz_foo.ion` with the contents

    bar::baz::{foo:1}

read using the command

    $ ion process --output bar_baz_foo_read_events.ion --output-format events bar_baz_foo.ion

would serialize the following EventStream to
`bar_baz_foo_read_events.ion`:

    $ion_event_stream
    {event_type: CONTAINER_START, ion_type: STRUCT, annotations:[{text:"bar"}, {text:"baz"}], depth:0}
    {event_type: SCALAR, ion_type: INT, field_name: {text:"foo"}, value_text: "1", value_binary: [0x21, 0x01], depth:1}
    {event_type: CONTAINER_END, ion_type: STRUCT, depth:0}
    {event_type: STREAM_END, depth:0}

A `bad` input file called `repeatedUnderscore.ion` with the contents

`[1__0]`

would generate the serialized event stream

    $ion_event_stream
    {event_type: CONTAINER_START, ion_type: LIST, depth:0}

and an ErrorReport similar to the following:

    {error_type: READ, message: "ion_reader_text.c:999 Line 1 index 3: Numeric values must not have repeated underscores.", location: "bad/repeatedUnderscore.ion", event_index: 1}

### Embedded Ion streams

Read each embedded Ion stream in the input as a separate EventStream.
Insert these streams back into the source stream, replacing the string
SCALAR events from which they originated.

#### Example

A `good/equivs` input file called `ten.ion` with the contents

    $ion_embedded_streams::(
        "$ion_1_0 10"
        "1_0"
    )

read using the command

    $ ion process --output ten_events_embedded.ion --output-format events ten.ion

would serialize the following EventStream to `ten_events_embedded.ion`:

    $ion_event_stream
    {event_type: CONTAINER_START, ion_type: SEXP, annotations: [{text:"$ion_embedded_streams"}], depth:0}
    {event_type: SCALAR, ion_type: INT, value_text: "10", value_binary: [0x21, 0x0A], depth:0}
    {event_type: STREAM_END, depth:0}
    {event_type: SCALAR, ion_type: INT, value_text: "10", value_binary: [0x21, 0x0A], depth:0}
    {event_type: STREAM_END, depth:0}
    {event_type: CONTAINER_END, ion_type: SEXP, depth:0}
    {event_type: STREAM_END, depth:0}

Writing an Ion stream from an EventStream
-----------------------------------------

A serialized EventStream can be used as a sequence of write instructions
(`--output-format (text | pretty | binary)`). Using the combination of an
Event's `event_type` and its `ion_type`, translate the Event into a
writer API. For example, encountering a SCALAR event with `ion_type` INT
in ion-java would translate to `writer.writeInt`. Encountering a
CONTAINER\_START event with ion\_type STRUCT in ion-c would translate to
`ion_writer_start_container(writer, tid_STRUCT)`.

For SCALAR events, use temporary readers to read the Events'
`value_text` and `value_binary`; test these values for data model
equivalence. If they are not equivalent, abort and write an
ErrorDescription to the ErrorReport.

For CONTAINER\_END events, finish the current container.

For SYMBOL\_TABLE events, flush the writer's existing local symbol table
and any buffered data, forcing the writer to create a new local symbol
table that imports the list of symbol tables declared by the `imports`
field of the Event. This ensures that symbol tokens with unknown text
that occur in subsequent events in the stream can be written correctly.

For STREAM\_END events, finish the writer's current stream, forcing the
writer to flush any buffered data. If additional Events follow, the
writer must first write an Ion version marker.

If the writer raises an error at any point, or the EventStream ends
without a STREAM\_END event, abort writing and write an ErrorDescription
to the ErrorReport.

### Example

The input file `one_events.ion` with the contents

    $ion_event_stream
    {event_type: SCALAR, ion_type: INT, value_text: "1", value_binary: [0x21, 0x01], depth:0}
    {event_type: STREAM_END, depth:0}

written using

    $ ion process --output one.ion --output-format text     one_events.ion
    $ ion process --output one.10n --output-format binary   one_events.ion

would first read the EventStream into memory and use temporary readers
to read the SCALAR event's `value_text` and `value_binary`. After
verifying that these are equivalent, it would write to `one.ion` with
the contents

    1

and to `one.10n` with the bytes

    \xE0\x01\x00\xEA\x21\x01

### Embedded EventStreams

Write any embedded EventStreams in the input using a temporary text Ion
writer, and write the resulting text Ion as a single Ion string per
embedded EventStream. Future iterations of the test harness may allow
these embedded streams to be written in the binary Ion format.

#### Example

The input file `ten_events_embedded.ion` with the contents

    $ion_event_stream
    {event_type: CONTAINER_START, ion_type: SEXP, annotations: [{text:"$ion_embedded_streams"}], depth:0}
    {event_type: SCALAR, ion_type: INT, value_text: "10", value_binary: [0x21, 0x0A], depth:0}
    {event_type: STREAM_END, depth:0}
    {event_type: SCALAR, ion_type: INT, value_text: "10", value_binary: [0x21, 0x0A], depth:0}
    {event_type: STREAM_END, depth:0}
    {event_type: CONTAINER_END, ion_type: SEXP, depth:0}
    {event_type: STREAM_END, depth:0}

read using the command

    $ ion process --output ten_embedded.ion --output-format text ten_events_embedded.ion

would write the following to `ten_embedded.ion`:

    $ion_embedded_streams::(
        "10"
        "10"
    )

End-to-end examples
-------------------

Assume there are two implementations. The CLI executables for both are
available to the cross-implementation test harness under the names
`ion-c` and `ion-java`.

The following file locations are defined:

    INPUT_FILE: The vector under test.

    READ_EVENTS_ION_C:          The EventStream generated by ion-c while reading the input data.
    READ_EVENTS_ION_C_ERROR:    The ErrorReport generated by ion-c during the read test for the input file.
    READ_EVENTS_ION_JAVA:       The EventStream generated by ion-java while reading the input data.
    READ_EVENTS_ION_JAVA_ERROR: The ErrorReport generated by ion-java during the read test for the input file.

    READ_VERIFY_ION_C:          The ComparisonReport generated by ion-c during the verification phase of the read test for the input file.
    READ_VERIFY_ION_C_ERROR:    The ErrorReport generated by ion-c during the verification phase of the read test for the input file.
    READ_VERIFY_ION_JAVA:       The ComparisonReport generated by ion-java during the verification phase of the read test for the input file.
    READ_VERIFY_ION_JAVA_ERROR: The ErrorReport generated by ion-java during the verification phase of the read test for the input file.

    READ_VERIFY_EQUIVS_ION_C:           The ComparisonReport generated by ion-c during the equivs/non-equivs semantics verification phase of the read test.
    READ_VERIFY_EQUIVS_ION_C_ERROR:     The ErrorReport generated by ion-c during the equivs/non-equivs semantics verification phase of the read test.
    READ_VERIFY_EQUIVS_ION_JAVA:        The ComparisonReport generated by ion-java during the equivs/non-equivs semantics verification phase of the read test.
    READ_VERIFY_EQUIVS_ION_JAVA_ERROR:  The ErrorReport generated by ion-java during the equivs/non-equivs semantics verification phase of the read test.

    WRITE_STREAM_ION_C_ION_C_TEXT:              The text Ion stream written by ion-c from the EventStream read by ion-c.
    WRITE_STREAM_ION_C_ION_C_TEXT_ERROR:        The ErrorReport generated by ion-c while attempting to write a text Ion stream from the EventStream read by ion-c.
    WRITE_STREAM_ION_C_ION_C_BINARY:            The binary Ion stream written by ion-c from the EventStream read by ion-c.
    WRITE_STREAM_ION_C_ION_C_BINARY_ERROR:      The ErrorReport generated by ion-c while attempting to write a binary Ion stream from the EventStream read by ion-c.
    WRITE_STREAM_ION_C_ION_JAVA_TEXT:           The text Ion stream written by ion-c from the EventStream read by ion-java.
    WRITE_STREAM_ION_C_ION_JAVA_TEXT_ERROR:     The ErrorReport generated by ion-c while attempting to write a text Ion stream from the EventStream read by ion-java.
    WRITE_STREAM_ION_C_ION_JAVA_BINARY:         The binary Ion stream written by ion-c from the EventStream read by ion-java.
    WRITE_STREAM_ION_C_ION_JAVA_BINARY_ERROR:   The ErrorReport generated by ion-c while attempting to write a binary Ion stream from the EventStream read by ion-java.
    WRITE_STREAM_ION_JAVA_ION_C_TEXT:           The text Ion stream written by ion-java from the EventStream read by ion-c.
    WRITE_STREAM_ION_JAVA_ION_C_TEXT_ERROR:     The ErrorReport generated by ion-java while attempting to write a text Ion stream from the EventStream read by ion-c.
    WRITE_STREAM_ION_JAVA_ION_C_BINARY:         The binary Ion stream written by ion-java from the EventStream read by ion-c.
    WRITE_STREAM_ION_JAVA_ION_C_BINARY_ERROR:   The ErrorReport generated by ion-java while attempting to write a binary Ion stream from the EventStream read by ion-c.
    WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT:        The text Ion stream written by ion-java from the EventStream read by ion-java.
    WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT_ERROR:  The ErrorReport generated by ion-java while attempting to write a text Ion stream from the EventStream read by ion-java.
    WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY:      The binary Ion stream written by ion-java from the EventStream read by ion-java.
    WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY_ERROR:The ErrorReport generated by ion-java while attempting to write a binary Ion stream from the EventStream read by ion-java.

    WRITE_VERIFY_ION_C:             The ComparisonReport generated by ion-c during the verification phase of the write test for the input file.
    WRITE_VERIFY_ION_C_ERROR:       The ErrorReport generated by ion-c during the verification phase of the write test for the input file.
    WRITE_VERIFY_ION_JAVA:          The ComparisonReport generated by ion-java during the verification phase of the write test for the input file.
    WRITE_VERIFY_ION_JAVA_ERROR:    The ErrorReport generated by ion-java during the verification phase of the write test for the input file.

    WRITE_VERIFY_EQUIVS_ION_C:          The ComparisonReport generated by ion-c during the equivs/non-equivs semantics verification phase of the write test.
    WRITE_VERIFY_EQUIVS_ION_C_ERROR:    The ErrorReport generated by ion-c during the equivs/non-equivs semantics verification phase of the write test.
    WRITE_VERIFY_EQUIVS_ION_JAVA:       The ComparisonReport generated by ion-java during the equivs/non-equivs semantics verification phase of the write test.
    WRITE_VERIFY_EQUIVS_ION_JAVA_ERROR: The ErrorReport generated by ion-java during the equivs/non-equivs semantics verification phase of the write test.

### Basic good and bad files

The harness selects a test file, which contains the Ion stream `1`, to
be the INPUT\_FILE.

#### Phase 1: Collect read results from all implementations

Using the CLI, write a file containing the stream of Events that were
read from the input Ion stream. The CLI supports being provided with an
optional catalog (see `--catalog`) to use while reading, which enables
streams with local symbol tables that declare shared imports to be
tested with or without a catalog.

    $ ion-c     process --output READ_EVENTS_ION_C    --output-format events --error-report READ_EVENTS_ION_C_ERROR       INPUT_FILE
    $ ion-java  process --output READ_EVENTS_ION_JAVA --output-format events --error-report READ_EVENTS_ION_JAVA_ERROR    INPUT_FILE

At this point, both READ\_EVENTS\_ION\_C and READ\_EVENTS\_ION\_JAVA
should contain an EventStream which is data model equivalent to

    $ion_event_stream
    {event_type: SCALAR, ion_type: INT, value_text: "1", value_binary: [0x21, 0x01], depth:0}
    {event_type: STREAM_END, depth:0}

#### Phase 2: Verify read results

Because this is a `good` file, the test harness expects none of the
implementations to have raised an error on read. It verifies this by
confirming that the ErrorReports located at READ\_EVENTS\_ION\_C\_ERROR
and READ\_EVENTS\_ION\_JAVA\_ERROR are empty. If either is not, the test
harness extracts messages from them and fails the test for the
implementation that generated the offending ErrorReport for this vector.
If this were a `bad` file, the test harness would expect all of the
implementations to have equivalent incomplete event streams and
non-empty ErrorReports.

If any of the implementations read the vector successfully, the next step
is to make sure all successful implementations agree on the read results by
asking each of them to compare their EventStream against those generated by
all others.

    $ ion-c     compare --output READ_VERIFY_ION_C      --error-report READ_VERIFY_ION_C_ERROR      READ_EVENTS_ION_C READ_EVENTS_ION_JAVA INPUT_FILE
    $ ion-java  compare --output READ_VERIFY_ION_JAVA   --error-report READ_VERIFY_ION_JAVA_ERROR   READ_EVENTS_ION_C READ_EVENTS_ION_JAVA INPUT_FILE

First, check the error reports at READ\_VERIFY\_ION\_C\_ERROR and
READ\_VERIFY\_ION\_JAVA\_ERROR. If either of them is not empty, extract
messages from them and fail the test for that implementation for this
vector.

At this point, both READ\_VERIFY\_ION\_C and READ\_VERIFY\_ION\_JAVA
should contain empty ComparisonReports, because equivalence was expected
and no elements of the EventStream differed. If this is not the case
(meaning that there is at least one ComparisonResult in the
ComparisonReport, and its type is either NOT\_EQUAL or ERROR), extract
an error message, and fail the test for that implementation for this
vector.

#### Phase 3: Generate write results

(*Note*: `bad` vectors skip phases 3 and 4.)

Using the EventStreams generated by implementations that successfully
passed phase 2, write Ion streams in both text and binary Ion.

    $ ion-c process --output-format text    --output WRITE_STREAM_ION_C_ION_C_TEXT      --error-report WRITE_STREAM_ION_C_ION_C_TEXT_ERROR        READ_EVENTS_ION_C
    $ ion-c process --output-format binary  --output WRITE_STREAM_ION_C_ION_C_BINARY    --error-report WRITE_STREAM_ION_C_ION_C_BINARY_ERROR      READ_EVENTS_ION_C
    $ ion-c process --output-format text    --output WRITE_STREAM_ION_C_ION_JAVA_TEXT   --error-report WRITE_STREAM_ION_C_ION_JAVA_TEXT_ERROR     READ_EVENTS_ION_JAVA
    $ ion-c process --output-format binary  --output WRITE_STREAM_ION_C_ION_JAVA_BINARY --error-report WRITE_STREAM_ION_C_ION_JAVA_BINARY_ERROR   READ_EVENTS_ION_JAVA

    $ ion-java process --output-format text     --output WRITE_STREAM_ION_JAVA_ION_C_TEXT       --error-report WRITE_STREAM_ION_JAVA_ION_C_TEXT_ERROR         READ_EVENTS_ION_C
    $ ion-java process --output-format binary   --output WRITE_STREAM_ION_JAVA_ION_C_BINARY     --error-report WRITE_STREAM_ION_JAVA_ION_C_BINARY_ERROR       READ_EVENTS_ION_C
    $ ion-java process --output-format text     --output WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT    --error-report WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT_ERROR      READ_EVENTS_ION_JAVA
    $ ion-java process --output-format binary   --output WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY  --error-report WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY_ERROR    READ_EVENTS_ION_JAVA

This should produce four text and four binary streams, all of which
should be data-model equivalent to the text Ion `1`.

#### Phase 4: Verify write results

Verify that all implementations agree that all of the re-written streams
are equivalent to the original stream and to each other.

    $ ion-c     compare --output WRITE_VERIFY_ION_C     --error-report WRITE_VERIFY_ION_C_ERROR     INPUT_FILE ION_C_ION_C_TEXT_FILE WRITE_STREAM_ION_C_ION_C_BINARY WRITE_STREAM_ION_C_ION_JAVA_TEXT WRITE_STREAM_ION_C_ION_JAVA_BINARY WRITE_STREAM_ION_JAVA_ION_C_TEXT WRITE_STREAM_ION_JAVA_ION_C_BINARY WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY
    $ ion-java  compare --output WRITE_VERIFY_ION_JAVA  --error-report WRITE_VERIFY_ION_JAVA_ERROR  INPUT_FILE ION_C_ION_C_TEXT_FILE WRITE_STREAM_ION_C_ION_C_BINARY WRITE_STREAM_ION_C_ION_JAVA_TEXT WRITE_STREAM_ION_C_ION_JAVA_BINARY WRITE_STREAM_ION_JAVA_ION_C_TEXT WRITE_STREAM_ION_JAVA_ION_C_BINARY WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY

The same technique is used to verify the comparison and error reports
generated by these commands within the test harness as was used in
Phase 2.

If the test harness has made it to this point without raising an error,
then the test for this vector is successful.

### Good/non-equivs file with embedded streams

The harness selects a `good/non-equivs` test file to be the INPUT\_FILE.
The file has the following contents:

    $ion_embedded_streams::(
        "1"
        "1.0"
    )

#### Phase 1: Collect read results from all implementations

Using the CLI, write a file containing the stream of Events that were
read from the input Ion stream. The embedded Ion streams are detected
because of the `$ion_embedded_streams` annotation.

    $ ion-c     process --output READ_EVENTS_ION_C    --output-format events --error-report READ_EVENTS_ION_C_ERROR       INPUT_FILE
    $ ion-java  process --output READ_EVENTS_ION_JAVA --output-format events --error-report READ_EVENTS_ION_JAVA_ERROR    INPUT_FILE

At this point, both READ\_EVENTS\_ION\_C and READ\_EVENTS\_ION\_JAVA
should contain an EventStream which is data model equivalent to

    $ion_event_stream
    {event_type: CONTAINER_START, ion_type: SEXP, annotations: [{text:"$ion_embedded_streams"}], depth:0}
    {event_type: SCALAR, ion_type: INT, value_text: "1", value_binary: [0x21, 0x01], depth:0}
    {event_type: STREAM_END, depth:0}
    {event_type: SCALAR, ion_type: DECIMAL, value_text: "1.0", value_binary: [0x52, 0xC1, 0x0A], depth:0}
    {event_type: STREAM_END, depth:0}
    {event_type: CONTAINER_END, ion_type: SEXP, depth:0}
    {event_type: STREAM_END, depth:0}

#### Phase 2: Verify read results

Just as in phase 2 of the previous example, the test harness verifies
that none of the implementations generated non-empty ErrorReports in
READ\_EVENTS\_ION\_C\_ERROR and READ\_EVENTS\_ION\_JAVA\_ERROR.

Also as in phase 2 of the previous example, read results from all
successful implementations should now be compared for equivalence with
each other and with the input file. The embedded Ion streams will be
compared against the corresponding embedded EventStreams in the other
files.

    $ ion-c     compare --output READ_VERIFY_ION_C      --error-report READ_VERIFY_ION_C_ERROR      READ_EVENTS_ION_C READ_EVENTS_ION_JAVA INPUT_FILE
    $ ion-java  compare --output READ_VERIFY_ION_JAVA   --error-report READ_VERIFY_ION_JAVA_ERROR   READ_EVENTS_ION_C READ_EVENTS_ION_JAVA INPUT_FILE

These commands should produce empty ComparisonReports in
READ\_VERIFY\_ION\_C and READ\_VERIFY\_ION\_JAVA because equivalence is
expected.

Now, the same inputs must be compared according to the `good/equivs` or
`good/non-equivs` test semantics, which require that all elements of
top-level sequences be either equal or not equal to all other elements
of the same sequence. Since this is a `good/non-equivs` vector, the
`--comparison-type non-equivs` option achieves this.

    $ ion-c     compare --output READ_VERIFY_EQUIVS_ION_C      --error-report READ_VERIFY_EQUIVS_ION_C_ERROR      --comparison_type non-equivs READ_EVENTS_ION_C READ_EVENTS_ION_JAVA  INPUT_FILE
    $ ion-java  compare --output READ_VERIFY_EQUIVS_ION_JAVA   --error-report READ_VERIFY_EQUIVS_ION_JAVA_ERROR   --comparison_type non-equivs READ_EVENTS_ION_C READ_EVENTS_ION_JAVA  INPUT_FILE

These commands should produce empty ComparisonReports in
READ\_VERIFY\_EQUIVS\_ION\_C and READ\_VERIFY\_EQUIVS\_ION\_JAVA. Since
non-equivalence is expected, any ComparisonResults present in the
ComparisonReport will have type EQUAL or ERROR. The test harness must
report these as errors and fail the test for that implementation for
this vector.

#### Phase 3: Generate write results

Using the EventStreams generated by all implementations that
successfully passed phase 2, write Ion streams in both text and binary
Ion. The embedded EventStreams will be detected and written as string
values containing Ion text.

    $ ion-c process --output-format text    --output WRITE_STREAM_ION_C_ION_C_TEXT      --error-report WRITE_STREAM_ION_C_ION_C_TEXT_ERROR        READ_EVENTS_ION_C
    $ ion-c process --output-format binary  --output WRITE_STREAM_ION_C_ION_C_BINARY    --error-report WRITE_STREAM_ION_C_ION_C_BINARY_ERROR      READ_EVENTS_ION_C
    $ ion-c process --output-format text    --output WRITE_STREAM_ION_C_ION_JAVA_TEXT   --error-report WRITE_STREAM_ION_C_ION_JAVA_TEXT_ERROR     READ_EVENTS_ION_JAVA
    $ ion-c process --output-format binary  --output WRITE_STREAM_ION_C_ION_JAVA_BINARY --error-report WRITE_STREAM_ION_C_ION_JAVA_BINARY_ERROR   READ_EVENTS_ION_JAVA

    $ ion-java process --output-format text     --output WRITE_STREAM_ION_JAVA_ION_C_TEXT       --error-report WRITE_STREAM_ION_JAVA_ION_C_TEXT_ERROR         READ_EVENTS_ION_C
    $ ion-java process --output-format binary   --output WRITE_STREAM_ION_JAVA_ION_C_BINARY     --error-report WRITE_STREAM_ION_JAVA_ION_C_BINARY_ERROR       READ_EVENTS_ION_C
    $ ion-java process --output-format text     --output WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT    --error-report WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT_ERROR      READ_EVENTS_ION_JAVA
    $ ion-java process --output-format binary   --output WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY  --error-report WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY_ERROR    READ_EVENTS_ION_JAVA

This should produce four text and four binary streams, all of which
should be data-model equivalent to the text Ion:

    $ion_embedded_streams::(
        "1"
        "1.0"
    )

#### Phase 4: Verify write results

Verify that all implementations agree that all of the re-written streams
are equivalent to the original stream and to each other.

    $ ion-c     compare --output WRITE_VERIFY_ION_C     --error-report WRITE_VERIFY_ION_C_ERROR     INPUT_FILE ION_C_ION_C_TEXT_FILE WRITE_STREAM_ION_C_ION_C_BINARY WRITE_STREAM_ION_C_ION_JAVA_TEXT WRITE_STREAM_ION_C_ION_JAVA_BINARY WRITE_STREAM_ION_JAVA_ION_C_TEXT WRITE_STREAM_ION_JAVA_ION_C_BINARY WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY
    $ ion-java  compare --output WRITE_VERIFY_ION_JAVA  --error-report WRITE_VERIFY_ION_JAVA_ERROR  INPUT_FILE ION_C_ION_C_TEXT_FILE WRITE_STREAM_ION_C_ION_C_BINARY WRITE_STREAM_ION_C_ION_JAVA_TEXT WRITE_STREAM_ION_C_ION_JAVA_BINARY WRITE_STREAM_ION_JAVA_ION_C_TEXT WRITE_STREAM_ION_JAVA_ION_C_BINARY WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY

Now, verify that the `good/non-equivs` semantics still hold for the
re-written streams.

    $ ion-c     compare --comparison-type non-equivs    --output WRITE_VERIFY_EQUIVS_ION_C     --error-report WRITE_VERIFY_EQUIVS_ION_C_ERROR     INPUT_FILE ION_C_ION_C_TEXT_FILE WRITE_STREAM_ION_C_ION_C_BINARY WRITE_STREAM_ION_C_ION_JAVA_TEXT WRITE_STREAM_ION_C_ION_JAVA_BINARY WRITE_STREAM_ION_JAVA_ION_C_TEXT WRITE_STREAM_ION_JAVA_ION_C_BINARY WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY
    $ ion-java  compare --comparison-type non-equivs    --output WRITE_VERIFY_EQUIVS_ION_JAVA  --error-report WRITE_VERIFY_EQUIVS_ION_JAVA_ERROR  INPUT_FILE ION_C_ION_C_TEXT_FILE WRITE_STREAM_ION_C_ION_C_BINARY WRITE_STREAM_ION_C_ION_JAVA_TEXT WRITE_STREAM_ION_C_ION_JAVA_BINARY WRITE_STREAM_ION_JAVA_ION_C_TEXT WRITE_STREAM_ION_JAVA_ION_C_BINARY WRITE_STREAM_ION_JAVA_ION_JAVA_TEXT WRITE_STREAM_ION_JAVA_ION_JAVA_BINARY

The same technique is used to verify the comparison and error reports
generated by these commands within the test harness as was used in
Phase 2.

If the test harness has made it to this point without raising an error,
then the test for this vector is successful.

Handling failures
--------------------------------

Inevitably, some implementations will fail to pass the tests for certain
vectors. Failures should be reported in ErrorReports, but must not cause
the entire test run to fail. When an implementation fails a test for a
particular vector and the fix for the defect can be deferred, an issue
referencing the failure and describing the defect should be added to that
implementation's queue. Determining which implementation actually failed
may require some investigation. If, for example, one out of N
implementations disagrees during verification of another implementation's
EventStream, the user must decide which implementation (or
implementations) contains a defect and only create an issue for the
offending implementation(s).

Repository structure
--------------------

The test harness will exist in its own repository. It will locally clone
the latest commit of ion-tests and all Ion implementations.

Starting a test run will involve triggering a build of each
implementation, distributing work to each implementation through that
implementation's CLI, determining success or failure of the tests by
processing ErrorReports and ComparisonReports, and generating a visual
report of the results to be used by developers and prospective users
to determine relative compliance between the implementations.

Ultimately, in the spirit of continuous integration, pushing a change to
any of the implementations (or ion-tests) should update the test
harness's dependency to the latest version and kick off a test run.

Integrate ion-test-driver into pipeline
---------------------------------------

The last step is integrating the ion-test-driver into GitHub Actions pipeline to trigger the ion-test-driver for every 
pull request.

### Result analysis option (--res-diff)

Option --res-diff is able to analyze an existing result file to identify any differences between the two revisions.
To compare two revisions of each test file:
1. Compare the two revisions `result` field, and if they both pass, then proceed to the next file. 
Otherwise proceed to the next step.
2. Check `read_error` field. If both of them have the same read_error or don't have any errors, proceed to the next step. 
Otherwise, write `read performance changed` error to the final report and then move on to the next step.
3. Check `read_compare` field. Analyze the given read_compare report and find all the disagree revision pairs. 
After extracting the two disagree lists, compare the master branch and new commit using these two cases:
**3.1.** If they agree with each other, their disagree lists should be the same. Raise a `cli compare diff` error if they 
are not the same.
**3.2.** If they disagree with each other, write down what implementations that the master commit no longer 
agrees with and what implementations the new master starts agree with.
4. Check `write_error` - refer to step 2.
5. Check `write_compare` - refer to step 3.

### GitHub Actions files

The GitHub Actions logic is under each implementation's `.github/workflow` direction. 

### Workflow procedure

The workflow of the pipeline follows the steps stated below when a PR is created in a implementation:
1. Running ion-test-driver and including the new commit in it.
2. Using --res-diff option to analyze the result from the step above and find the difference between HEAD and the new 
commit of the implementations.
3. If the new commit changes reader/writer behaviors and analysis result returns a non-zero value, open an issue for it.

Implementation plan
-------------------

Not all of the features described above need to be implemented
immediately. The core functionality is prioritized in versions 1 and 2,
while longer-term needs are addressed in versions 3 and 4.

### Version 1: Current ion-tests semantics

Version 1 will implement the functionality required to
support all current ion-tests semantics (`good`, `bad`, `good/equivs`,
`good/non-equivs`, and embedded streams) in ion-c, ion-python, and
ion-java. Other language implementations can be added incrementally.

Minimally, this involves implementing the following CLI commands and
options in each language:

-   `process`
    - `--output`
    - `--output-format`
    - `--error-report`
-   `compare`
    - `--output`
    - `--output-format`
    - `--error-report`
    - `--comparison-type`

This also involves providing the ion-test-harness as a command-line tool
that reports its results in the Ion text format.

### Version 2: Additional shared symbol table support

Version 2 will add more support for tests that include shared symbol
table processing. This is not commonly leveraged in the current suite
of ion-tests vectors.

This involves adding the following options to the existing CLI commands:

-   `process`
    - `--catalog`
    - `--imports`
-   `compare`
    - `--catalog`
    - `--imports`

At this point, more ion-tests vectors that leverage shared symbol tables
(including symbol tokens with unknown text) should be added. ion-tests
should also define a set (or sets) of shared symbol tables that may be
used to populate a test catalog (or catalogs). Because all valid Ion data
can be roundtripped with or without actually resolving the shared symbol
table imports, test vectors with local symbol tables that declare shared
imports could be run both with and without the test catalog to verify
that the implementation correctly handles both cases.

Additionally, the ion-test-harness tool should be enhanced to provide
easier-to-read HTML reports, which may be published for the benefit
of users.

### Version 3: Fuzz testing

Version 3 will add fuzz testing for randomly generated traversals
(generated by the test harness) over the input data. The results can be
used to verify that all implementations behave in the same way for that
traversal, regardless of whether the traversal is valid.

Non-normative traversals (e.g. stepping out of a container before
consuming all of its values, or stepping over a nested container below
depth zero) are essential to test in intra-implementation unit tests,
and are known to have been the source of bugs in the past.

This involves adding the following option to the existing CLI commands:

-   `process`
    - `--traverse`

### Version 4: Extension of the CLI

Version 4 will add features that will improve the CLI's usefulness to
users. This includes support for JQ-like filtering, which is a common ask
from users who wish Ion had tooling parity with JSON; performance testing
and report generation, allowing for the CLI to be used to drive automated
cross-implementation performance testing in the future; and shared symbol
table extraction from sample data.

This requires adding the `extract` command and adding the following
options to the CLI:

-   `process`
    - `--perf-report`
    - `--filter`
-   `extract`
    - `--output`
    - `--output-format`
    - `--error-report`
    - `--symtab-name`
    - `--symtab-version`
-   `-h, help`
-   `-v, version`

FAQ:
----

**Q**: Does the test harness verify correctness?

**A**: No -- it verifies consensus. Verifying correctness to the spec for
a particular implementation must be left to that implementation's unit
tests. If at least one of the implementations has correct behavior for a
particular test vector, and this test harness confirms consensus among
all implementations for that vector, then all implementations have
correct behavior for that test vector.

**Q**: Will this catch intra-implementation symmetrical read-then-write
bugs? For example, given the Ion data `1`, the implementation
incorrectly reads the value `8` into memory. It then incorrectly writes
the value `1`.

**A**: Not necessarily. Serializing the event stream, which is used to
verify read behavior, still requires use of the implementation's Ion
writers, which would mask the error (the risk is somewhat lessened by
the fact that the streams are re-written as both text and binary Ion,
requiring the defect to be present in both writers in order to be
masked). For this reason, this test harness cannot fully replace
intra-implementation read tests. Note that intra-implementation
symmetrical write-then-read bugs WOULD be caught, because each
implementation reads the data written by every other implementation in
order to drive consensus.

**Q**: Why use event streams at all? Why not just exchange roundtripped
test files?

**A**: Event streams allow for comparison of reader behavior. This
enables verification that expected errors happen at the correct point in
the stream, enabling more consistent error behavior between
implementations. It also increases the chances that reader errors will
be identified as such. Although this can't be used to determine that a
scalar value was read incorrectly (because the writer must be used to
serialize the value in the event), it can expose that the reader read
the structure of the data incorrectly (e.g. by providing the wrong type
of event, missing events, or adding superfluous events). This can help
the developer narrow the scope of the debugging effort. For example,
consider the input data "(++a)". Implementation A correctly reads this
as an s-expression with two elements: "++" and "a". Implementation B
reads this as an s-expression with a single element: "++a". A's writer
minimizes spacing in s-expressions, so both A and B re-write the stream
as "(++a)". Although the stream was roundtripped correctly, it was not
read correctly by both A and B. This difference would have been caught
with event-based read verification.

