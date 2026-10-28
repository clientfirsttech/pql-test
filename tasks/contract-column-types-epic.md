# Contract Column Type Checks Epic

**Status**: 📋 PLANNED
**Goal**: Enforce an ODCS property's type (`logicalType`) against the semantic model, instead of reporting every type rule as skipped.

## Overview

A contract that declares column types gets a type rule per property, and `pql-test contract` reports all of them as skipped ("column data type checks are planned"). In `marvel.odcs.yaml` that is 9 of 17 rules. The PQL.Assert function they wait for, `Tbl.ColumnDataTypeShouldBe(testName, tableName, columnName, expectedType)`, already exists in every PQL.Assert version the examples use (0.4.0 to 0.8.0), and compares `expectedType` with `INFO.VIEW.COLUMNS()[DataType]`. What is missing is the translation from ODCS types to the model's type names.

The model's names were read from the deployed SampleModel on 2026-10-28, and match the TMDL `dataType` one to one:

| TMDL `dataType` | Model `DataType` |
|---|---|
| `string` | `Text` |
| `int64` | `Integer` |
| `double` | `Number` |
| `decimal` | `Currency` |
| `dateTime` | `Date` |
| `boolean` | `True/False` |
| `binary` | `Binary` |

**Decided 2026-10-28 (maintainer):**
- A `pbiDataType` custom property on a property pins the exact model type, like `pbiTable` and `pbiColumn`.
- Without it, `number` accepts `Number` or `Currency`.
- `physicalType` describes the source system, so it is not checked; a property with only a `physicalType` stays skipped and says why.
- `lint CONTRACT MODEL_PATH` also checks types offline from the TMDL.

---

## Map logicalType to a model type check

**Requirements**:
- Given `logicalType` `string`, `integer`, `boolean`, or `date`, should map to `Tbl.ColumnDataTypeShouldBe` with `Text`, `Integer`, `True/False`, or `Date`, in the Schema suite, on both the 0.7 and 0.8 catalogs
- Given `logicalType` `number`, should map to one check that passes for `Number` or `Currency`, and whose failure still names the expected and actual type
- Given `logicalType` `timestamp` or `time`, should map to `Date` and be reported as approximated, because the model has one date/time type
- Given a `pbiDataType` custom property, should check exactly that model type; given a value that is not a model type name, should skip the rule and list the valid names
- Given only a `physicalType`, or a `logicalType` with no model type, should stay skipped with a reason that says how to make it checkable

---

## Check types offline in lint

**Requirements**:
- Given `lint CONTRACT MODEL_PATH`, should report a problem for each column whose TMDL `dataType` is not a type the contract accepts, naming both types
- Given a column with no `dataType` in TMDL, should not report a type problem

---

## Docs, goldens, and live check

**Requirements**:
- Given the golden files and the coverage reports, should show the type rules as mapped (or approximated), with no other change
- Given docs/contracts.md and the contract skill, should list the type mapping and `pbiDataType`
- Given `python/tests/test_contract_live.py`, should still pass against the workspace's SampleModel, with the type rules passing
