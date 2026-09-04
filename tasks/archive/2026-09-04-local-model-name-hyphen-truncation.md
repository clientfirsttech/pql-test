# Local Model Name Hyphen Truncation Epic

**Status**: ✅ COMPLETED (2026-09-04)
**Goal**: `local/<model_name>` correctly matches models whose display name itself contains " - "

## Overview

Users whose Power BI Desktop model name contains a hyphen surrounded by spaces (e.g. "Component 4 - Daily Results Dashboard") can't run `pql-test run-tests "local/Component 4 - Daily Results Dashboard"` — it reports "No tests found" — while the truncated `local/Component 4` works. The window-title parser in `get_pbi_files_opened()` assumes the *last* " - " in a title always separates the model name from a trailing " - Power BI Desktop" app-name suffix, using `title.rfind(" - ")` unconditionally. On newer Power BI Desktop builds the title has no app-name suffix at all, so when the model name itself contains " - ", the parser wrongly truncates at that internal hyphen, silently registering the instance under a shorter name and breaking exact/substring matching for the real name.

---

## Fix window-title suffix stripping

Only strip the trailing `" - Power BI Desktop"` suffix when the title actually ends with it; otherwise use the full title as the model name.

**Requirements**:
- Given a window title ending in `" - Power BI Desktop"`, should strip only that suffix and keep any internal " - " in the model name intact
- Given a window title with no `" - Power BI Desktop"` suffix and containing " - " within the model name (e.g. "Component 4 - Daily Results Dashboard"), should use the full title as the model name unmodified
- Given the fixed model name, should still match via `local/<model_name>` substring lookup in `resolve_local_xmla_connection_by_name`

## Add regression tests

Cover both title shapes so this can't silently regress.

**Requirements**:
- Given `get_pbi_files_opened()` with a raw window title `"Component 4 - Daily Results Dashboard"` (no suffix), should resolve `model_name == "Component 4 - Daily Results Dashboard"`
- Given `get_pbi_files_opened()` with a raw window title `"Component 4 - Daily Results Dashboard - Power BI Desktop"`, should resolve `model_name == "Component 4 - Daily Results Dashboard"`
- Given `resolve_local_xmla_connection_by_name("Component 4 - Daily Results Dashboard", instances=...)` against an instance named `"Component 4 - Daily Results Dashboard"`, should return a match instead of `None`
