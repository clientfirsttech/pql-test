# Contract Id References Epic

**Status**: 🔄 IN PROGRESS
**Goal**: Let a contract reference any model column, including a name with a space, by using ODCS id references, and say how when a reference fails.

## Overview

Power BI names usually contain spaces (`Date ID`), but an ODCS `table.property` reference allows only letters, digits, and `_` (v3.2 also `-`), and ODCS has no escape syntax, so `to: Date_Dim.Date ID` fails schema validation with two cryptic errors and `contract coverage` silently suggests nothing for the relationship. ODCS's answer is the fully qualified reference by `id` (`schema/<object id>/properties/<property id>`), which pql-test lists as "later". This epic resolves id references, makes lint explain a rejected reference and report one that names nothing, and has `coverage` suggest every uncovered relationship in whichever form its names allow.

---

## Resolve Id References

Resolve `schema/<object id>/properties/<property id>` relationship ends to model names.

**Requirements**:
- Given an id reference, with or without a leading `/`, should find the schema object by `id` and then the property by `id` among that object's properties, because ODCS ids are unique only within their containing array
- Given an id reference whose ids name nothing, should skip the rule saying which id is missing, and mark it as a broken reference rather than an unsupported one
- Given a reference to another file (`other.yaml#…`) or another path shape, should skip it with a reason
- Given an id-referenced relationship, should generate the same `Relationship.ShouldExist` call as the shorthand form, with `pbiTable` / `pbiColumn` still applied

---

## Explain Rejected References in Lint

Turn ODCS's schema errors for a reference into one actionable problem, and report references that name nothing.

**Requirements**:
- Given a `from` / `to` reference the ODCS schema rejects, should report one problem for it that names the allowed characters, says there is no escape syntax, and shows the id form, instead of the schema's two errors
- Given each escape attempt (a space, `"…"`, `[…]`, backticks, `\ `, `%20`), should fail lint with that problem
- Given a shorthand or id reference that names nothing in the contract, should fail lint, because lint claims every name resolves
- Given a composite relationship, should not fail lint, because it is valid ODCS that `mapping` reports as skipped

---

## Suggest Relationships in Coverage

`contract coverage` prints YAML for every uncovered relationship.

**Requirements**:
- Given an uncovered relationship whose contract names fit the shorthand pattern, should suggest a schema-level `foreignKey` with `from` / `to` under the foreign key's schema object
- Given one whose names do not, should suggest the id form, reuse ids the contract already has, and list the `id` to add to each element that lacks one, unique within its array
- Given a relationship end the contract does not list yet, should name it as the model does, as the table and column suggestions do
- Given the suggestion applied, should cover the relationship and pass lint, and the JSON report should carry the ids to add

---

## Document the Id Form

Docs and the contract skill explain reference forms, the escape limit, and the id form.

**Requirements**:
- Given docs/contracts.md, should explain the two reference forms, that names with spaces need the id form (or a `pbiColumn` rename), and drop "fully qualified references" from the not-yet-supported list
- Given the contract skill (source and packaged copies byte-identical), should show the id form for a column with a space
- Given the documentation and contract gap-check skills, should pass

---
