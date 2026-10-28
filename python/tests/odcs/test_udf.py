# SPDX-License-Identifier: MIT
"""Reading DAX user-defined functions (and their PQL.Assert version) from TMDL."""

from __future__ import annotations

from pathlib import Path

import pytest

from pql_test.odcs.udf import (
    library_versions,
    model_functions,
    parse_functions,
    version_key,
)

REPO = Path(__file__).resolve().parents[3]

MODEL_STYLE = """\
/// Asserts that a value is TRUE.
function 'PQL.Assert.ShouldBeTrue' =
\t\t(testName : STRING, actualCondition : BOOLEAN) =>
\t\t\tVAR _Passed = actualCondition = TRUE

\t\t\tRETURN ROW("TestName", testName, "Passed", _Passed)
\tlineageTag: 0dbfc874-e203-42e1-a200-0c1c75585008

\tannotation DAXLIB_PackageId = PQL.Assert

\tannotation DAXLIB_PackageVersion = 0.4.0

function Plain.Helper =
\t\t(x : INT64, label : STRING = "a, (b)") => x + 1
\tannotation DAXLIB_PackageId = Other
"""

SCRIPT_STYLE = """\
createOrReplace
\t/// Returns the installed version.
\tfunction 'PQL.Assert.LibraryVersion' =
\t\t\t() => "0.8.0"
\t\tannotation DAXLIB_PackageId = PQL.Assert
\t\tannotation DAXLIB_PackageVersion = 0.8.0
"""


class TestParseFunctions:
    def test_model_file_functions_with_annotations(self):
        given = "a model functions.tmdl with two functions"
        should = "read each name, expression, and annotation, ignoring lineageTag"

        first, second = parse_functions(MODEL_STYLE)

        assert (first.name, first.package, first.version, second.name, second.package, second.version) == (
            "PQL.Assert.ShouldBeTrue",
            "PQL.Assert",
            "0.4.0",
            "Plain.Helper",
            "Other",
            None,
        ), f"{given}: {should}"

    def test_expression_is_dedented_and_keeps_blank_lines(self):
        given = "a multi-line function body with a blank line"
        should = "return the dedented body, blank line kept, no properties"

        fn = parse_functions(MODEL_STYLE)[0]

        assert fn.expression == (
            "(testName : STRING, actualCondition : BOOLEAN) =>\n"
            "\tVAR _Passed = actualCondition = TRUE\n"
            "\n"
            '\tRETURN ROW("TestName", testName, "Passed", _Passed)'
        ), f"{given}: {should}"

    def test_parameters_split_at_top_level_commas_only(self):
        given = "a parameter default holding a comma and parentheses inside a string"
        should = "split into two parameters and mark only the defaulted one optional"

        params = parse_functions(MODEL_STYLE)[1].parameters

        assert [(p.name, p.type, p.optional) for p in params] == [
            ("x", "INT64", False),
            ("label", "STRING", True),
        ], f"{given}: {should}"

    def test_daxlib_script_file(self):
        given = "a DAX Lib createOrReplace script with indented functions"
        should = "read the function, with no parameters"

        (fn,) = parse_functions(SCRIPT_STYLE)

        assert (fn.name, fn.expression, fn.parameters, fn.version) == (
            "PQL.Assert.LibraryVersion",
            '() => "0.8.0"',
            (),
            "0.8.0",
        ), f"{given}: {should}"

    def test_define_text_for_a_query(self):
        given = "a function to define in a DAX query"
        should = "render FUNCTION <name> = <expression>, indented for a DEFINE block"

        (fn,) = parse_functions(SCRIPT_STYLE)

        assert fn.define() == '\tFUNCTION PQL.Assert.LibraryVersion = () => "0.8.0"', f"{given}: {should}"

    def test_annotation_indented_with_mixed_whitespace(self):
        given = "an annotation indented deeper than the body with a tab and spaces (as in PQL.Assert 0.8.0)"
        should = "still read it as an annotation, not as part of the expression"
        text = "function 'F.G' =\n\t\t() =>\n\t\t\t1\n\t    annotation DAXLIB_PackageId = F\n"

        (fn,) = parse_functions(text)

        assert (fn.expression, fn.package) == ("() =>\n\t1", "F"), f"{given}: {should}"

    def test_body_lines_indented_less_than_the_first_stay_in_the_body(self):
        given = "a body whose later lines are indented less than its first line"
        should = "keep every line up to the properties"
        text = "function 'F.G' =\n\t\t\t(x : STRING) =>\n\t\tVAR y = x\n\t\tRETURN y\n\tannotation DAXLIB_PackageId = F\n"

        (fn,) = parse_functions(text)

        assert (fn.expression.splitlines()[-1].strip(), fn.package) == ("RETURN y", "F"), f"{given}: {should}"

    def test_comments_in_the_parameter_list_are_ignored(self):
        given = "a parameter list with // and /* */ comments, and a // inside a string default"
        should = "read only the parameter names, types, and defaults"
        text = (
            "function 'F.G' =\n\t\t(\n\t\t\t// the x\n\t\t\tx : INT64, /* why */ url : STRING = \"http://a\"\n"
            "\t\t) => x\n"
        )

        (fn,) = parse_functions(text)

        assert [(p.name, p.type, p.optional) for p in fn.parameters] == [
            ("x", "INT64", False),
            ("url", "STRING", True),
        ], f"{given}: {should}"

    def test_fenced_expression(self):
        given = "a TMDL ``` fenced expression"
        should = "read the lines between the fences as the expression"
        text = "function 'F.G' = ```\n\t\t() =>\n\t\t\t1\n\t\t```\n\tannotation DAXLIB_PackageId = F\n"

        (fn,) = parse_functions(text)

        assert (fn.expression, fn.package) == ("() =>\n\t1", "F"), f"{given}: {should}"


class TestVersions:
    @pytest.mark.parametrize("text, key", [("0.8.0", (0, 8, 0)), ("0.10.1", (0, 10, 1)), ("1.2", (1, 2)), ("x", ())])
    def test_version_key_orders_numerically(self, text, key):
        assert version_key(text) == key, f"given {text!r}: should give {key}"

    def test_library_versions_counts_only_the_package(self):
        given = "functions from PQL.Assert and another package"
        should = "count PQL.Assert functions per version"

        assert library_versions(parse_functions(MODEL_STYLE)) == {"0.4.0": 1}, f"{given}: {should}"

    def test_sample_model(self):
        given = "examples/SampleModel"
        should = "read every PQL.Assert function at a single version"

        versions = library_versions(model_functions(REPO / "examples" / "SampleModel.SemanticModel"))

        assert len(versions) == 1, f"{given}: {should} (got {versions})"

    def test_model_without_functions_file(self, tmp_path):
        given = "a semantic model folder with no definition/functions.tmdl"
        should = "return no functions"

        assert model_functions(tmp_path) == [], f"{given}: {should}"
