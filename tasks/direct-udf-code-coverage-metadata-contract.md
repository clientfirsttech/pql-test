# Direct Test-UDF Metadata Contract

**Status**: ✅ VALIDATED (2026-09-22)
**Task**: [Validate Direct Test-UDF Metadata Contract](archive/2026-09-22-direct-udf-code-coverage.md#validate-direct-test-udf-metadata-contract)

Live XMLA evidence recorded against three local Power BI Desktop sessions:
`examples/SampleModel.SemanticModel`, `examples/RLS_Model.SemanticModel`,
`examples/OLS_Model.SemanticModel`. Connections resolved via the existing
`local/<model_name>` path (`resolve_xmla_connection` /
`_execute_dax_query`, no new connection code). This document is the
verified contract the "Define Direct Coverage Evidence" and "Implement
Coverage Collection" tasks should build against — it does not itself change
any runner/CLI code.

## Method

1. Discover test UDFs with `EVALUATE PQL.Assert.RetrieveTestsV2()` — same
   call `retrieve_tests()` already makes. Columns: `Name`, `Description`,
   `PQLAssert_ImpersonatedUserName`, `PQLAssert_RoleName` (the latter two are
   `INFO.ANNOTATIONS()` lookups baked into the UDF itself, not something the
   collector has to compute).
2. Pull the whole graph with `EVALUATE INFO.CALCDEPENDENCY()`. Columns:
   `DATABASE_NAME, OBJECT_TYPE, TABLE, OBJECT, EXPRESSION,
   REFERENCED_OBJECT_TYPE, REFERENCED_TABLE, REFERENCED_OBJECT,
   REFERENCED_EXPRESSION, QUERY`. This is **one row per single-hop edge for
   the entire model**, not a per-object transitive tree.
3. **Direct edge from a test UDF** = a row where `OBJECT_TYPE = "FUNCTION"`
   and `OBJECT` is exactly a discovered test-UDF name. Filtering this way is
   what satisfies "without including dependencies that originate only from
   PQL.Assert helper functions": a chain like `Schema.DEV.Tests →
   PQL.Assert.Col.ShouldExist → MarvelFact[Name]` appears as **two separate
   rows** (`OBJECT = Schema.DEV.Tests → REFERENCED_OBJECT =
   PQL.Assert.Col.ShouldExist`, and separately `OBJECT =
   PQL.Assert.Col.ShouldExist → REFERENCED_OBJECT = ...`); restricting
   `OBJECT` to the test-UDF name set naturally keeps only the first hop and
   drops the helper-internal hop. No text/AST parsing needed for this part.

## Per-category source and identifier shape

| Category | Reachable as a direct edge from a test UDF? | `REFERENCED_OBJECT_TYPE` | Identifier shape |
|---|---|---|---|
| Table | Yes — verified (`DataQuality.DEV.Tests → MarvelFact`, `RLS.ANY.Tests → Groups`) | `TABLE` (or `CALC_TABLE` for a calculated table) | `REFERENCED_TABLE` == `REFERENCED_OBJECT` == table name |
| Column (plain) | Yes — verified (`DataQuality.DEV.Tests → MarvelFact[Name]`, etc.) | `COLUMN` | `REFERENCED_TABLE` + `REFERENCED_OBJECT` (column name) |
| Calculated column | Shape confirmed live, but not exercised by any *test* UDF edge in the three sampled models (only non-test objects referenced one, e.g. a measure → `CALC_COLUMN`) | `CALC_COLUMN` | Same shape as `COLUMN`: `REFERENCED_TABLE` + `REFERENCED_OBJECT` |
| Measure | Yes — verified (`Calcs.DEV.Tests → MarvelFact[Number of Characters]`) | `MEASURE` | `REFERENCED_TABLE` (home table) + `REFERENCED_OBJECT` (measure name) |
| Relationship | **No** | n/a | See "Not reachable" below |
| Partition | **No** | n/a | See "Not reachable" below |
| Role | **No** (not as an edge *from* the FUNCTION node) | n/a — see `ROWS_ALLOWED` below | See "Roles" below |

Full set of `OBJECT_TYPE` / `REFERENCED_OBJECT_TYPE` values actually observed
across the three models: `ACTIVE_RELATIONSHIP, ATTRIBUTE_HIERARCHY,
CALC_COLUMN, CALC_TABLE, COLUMN, FUNCTION, MEASURE, M_EXPRESSION, PARTITION,
ROWS_ALLOWED, TABLE`. **`ROLE` and `RELATIONSHIP` never appear as a type
value at all** — this is a hard constraint on what CALCDEPENDENCY can ever
tell a collector, not a sampling gap.

## Categories not identifiable from direct UDF metadata

Per the epic's third requirement, each gets explicit evidence/exclusion
behavior instead of transitive inference:

### Relationships — exclude from CALCDEPENDENCY-based evidence

`PQL.Assert.Relationship.ShouldExist(testName, fromTable, fromColumn,
toTable, toColumn)` takes the relationship endpoints as **string
literals** and resolves them at runtime via `INFO.VIEW.RELATIONSHIPS()`
inside the helper. The only CALCDEPENDENCY row this produces is
`Schema.DEV.Tests (FUNCTION) → PQL.Assert.Relationship.ShouldExist
(FUNCTION)` — never an edge to the relationship itself. Relationships *do*
appear in CALCDEPENDENCY as `OBJECT_TYPE = "ACTIVE_RELATIONSHIP"` rows (keyed
by a GUID, `REFERENCED_OBJECT_TYPE = "COLUMN"`), but those edges originate
from the relationship object, never from a test UDF or its helper —
confirmed on both SampleModel (relationship test present) and RLS_Model.
**Decision for the next task**: relationship coverage evidence, if
implemented, must come from parsing each test UDF's DAX expression text
(`INFO.USERDEFINEDFUNCTIONS()[EXPRESSION]` — already fetched for discovery)
for literal `PQL.Assert.Relationship.ShouldExist(...)` calls and extracting
its 4 string arguments — not from CALCDEPENDENCY. Until/unless that parsing
is implemented, relationships should be reported as an **unavailable
category** (per the epic's fourth "Implement Coverage Collection"
requirement), not silently zero.

### Partitions — exclude entirely, no assertion surface exists

No `PQL.Assert.*` helper targets partitions in any of the three example
models' function libraries. CALCDEPENDENCY's `PARTITION` rows only link
partition → partition/`M_EXPRESSION` (a table's own incremental-refresh/M
lineage), never `FUNCTION → PARTITION`. **Decision**: partitions have no
current direct-evidence path and no test surface to evidence them from —
list every partition as excluded with reason "no PQL.Assert helper targets
partitions", not as uncovered.

### Roles — indirect via annotation + `ROWS_ALLOWED`, not a direct edge

Role application happens through the ADOMD connection string (`Roles=` /
`EffectiveUserName=`), not a DAX dependency. A test UDF carries its target
role as the `PQLAssert_RoleName` annotation (already surfaced by
`RetrieveTestsV2()`, e.g. `RLS.ANY.Tests` → `PQLAssert_RoleName = "West"`).
CALCDEPENDENCY separately exposes each role's row-filter as
`OBJECT_TYPE = "ROWS_ALLOWED"`, `OBJECT = <role name>`,
`REFERENCED_OBJECT_TYPE = "TABLE"`, `REFERENCED_TABLE/REFERENCED_OBJECT =
<filtered table>` — verified on RLS_Model (`ROWS_ALLOWED "West" →
Groups`) and OLS_Model (`ROWS_ALLOWED "West" → Admin Table`, `→ Hidden
Column Table`). **Decision**: role-to-table coverage evidence is a **join**,
not a direct CALCDEPENDENCY edge from the FUNCTION node —
`PQLAssert_RoleName` (from the test UDF annotation) → `OBJECT` on
`ROWS_ALLOWED` rows → `REFERENCED_TABLE`. `INFO.ROLES()` (`ID, Name,
ModelPermission, ...`) and `INFO.TABLEPERMISSIONS()` (`RoleID, TableID,
FilterExpression, MetadataPermission`) are the canonical live sources for
role identity and filter definitions if the collector needs to cross-check
or enumerate all roles regardless of test coverage — `INFO.VIEW.ROLES()`
does **not** exist (confirmed by a live `Failed to resolve name` error) and
must not be used.

OLS assertions (`PQL.Assert.OLS.TableShouldBeHidden/Visible`,
`ColumnShouldBeHidden/Visible`) have the same string-argument problem as
relationships — verified on OLS_Model, every edge from `OLS_West.ANY.Tests`
/ `OLS_Admin.ANY.Tests` is `FUNCTION → FUNCTION` only (to the helper), never
to the table/column under test. Same decision as relationships: requires
DAX-expression-text parsing, not CALCDEPENDENCY, and is unavailable until
that's built.

## Representative raw evidence

```
SampleModel — Schema.DEV.Tests direct edges:
  FUNCTION Schema.DEV.Tests -> FUNCTION PQL.Assert.Col.ShouldExist
  FUNCTION Schema.DEV.Tests -> FUNCTION PQL.Assert.Tbl.ShouldExist
  FUNCTION Schema.DEV.Tests -> FUNCTION PQL.Assert.Relationship.ShouldExist
  (no edge to any TABLE/COLUMN/relationship object — all three helper calls
  take string args; only the helper FUNCTION itself is a direct dependency)

SampleModel — DataQuality.DEV.Tests direct edges (excerpt):
  FUNCTION DataQuality.DEV.Tests -> TABLE MarvelFact
  FUNCTION DataQuality.DEV.Tests -> COLUMN MarvelFact[Name]
  FUNCTION DataQuality.DEV.Tests -> COLUMN MarvelFact[Appearances]
  FUNCTION DataQuality.DEV.Tests -> FUNCTION PQL.Assert.Col.ShouldNotBeNull

SampleModel — Calcs.DEV.Tests direct edges (excerpt):
  FUNCTION Calcs.DEV.Tests -> MEASURE MarvelFact[Number of Characters]
  FUNCTION Calcs.DEV.Tests -> COLUMN DateDim[Year]

RLS_Model — RLS.ANY.Tests direct edges (all 3):
  FUNCTION RLS.ANY.Tests -> TABLE Groups
  FUNCTION RLS.ANY.Tests -> COLUMN Groups[Group Name]
  FUNCTION RLS.ANY.Tests -> FUNCTION PQL.Assert.ShouldEqualExactly
  annotation PQLAssert_RoleName = "West" (on RLS.ANY.Tests itself)
  ROWS_ALLOWED "West" -> TABLE Groups   (separate CALCDEPENDENCY row, not
                                          linked to RLS.ANY.Tests by any edge —
                                          only by the shared role name)

OLS_Model — OLS_West.ANY.Tests / OLS_Admin.ANY.Tests direct edges (all 4):
  FUNCTION OLS_West.ANY.Tests  -> FUNCTION PQL.Assert.OLS.TableShouldBeHidden
  FUNCTION OLS_West.ANY.Tests  -> FUNCTION PQL.Assert.OLS.ColumnShouldBeHidden
  FUNCTION OLS_Admin.ANY.Tests -> FUNCTION PQL.Assert.OLS.TableShouldBeVisible
  FUNCTION OLS_Admin.ANY.Tests -> FUNCTION PQL.Assert.OLS.ColumnShouldBeVisible
  (no edge to "Admin Table" / "Hidden Column Table" themselves)

INFO.ROLES() (RLS_Model):            ID=18 Name=West, ID=19 Name=East
INFO.TABLEPERMISSIONS() (RLS_Model): RoleID=18 -> TableID=10 (Groups),
                                      FilterExpression = [Group Name] == "West"
```

## Follow-ups for the next tasks

- "Define Direct Coverage Evidence" should treat `TABLE`/`CALC_TABLE`,
  `COLUMN`/`CALC_COLUMN`, and `MEASURE` as the only categories with a true
  direct-edge evidence path from `OBJECT = <test UDF name>` rows.
- Relationships and OLS table/column targets need DAX-expression-text
  parsing against `INFO.USERDEFINEDFUNCTIONS()[EXPRESSION]` if they are to
  be evidenced at all; until built, report them as unavailable categories,
  never as zero coverage.
- Partitions have no assertion surface in the current PQL.Assert function
  library — exclude with reason, don't count as uncovered.
- Roles need the `PQLAssert_RoleName` annotation → `ROWS_ALLOWED` join
  described above; `INFO.ROLES()` / `INFO.TABLEPERMISSIONS()` are the
  fallback enumeration sources. Do not call `INFO.VIEW.ROLES()` — it does
  not exist.
