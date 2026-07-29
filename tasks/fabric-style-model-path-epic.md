# Fabric-Style Model Path Epic

**Status**: 🚧 IN PROGRESS (2026-05-27)
**Goal**: Make the canonical service-path syntax `<workspace>.Workspace/<model>.SemanticModel` so the CLI surface matches Fabric's filesystem-layout convention (workspaces are `.Workspace` directories, semantic models are `.SemanticModel` directories). Keep the legacy `<workspace>.<model>` dot notation working with a deprecation warning so existing pipelines do not break the day users upgrade.

## Overview

`parse_model_identifier` in [runner.py:271](python/pql_test/runner.py#L271) currently recognises three model-path formats:

1. `<filesystem_path>` — traditional PBIP root directory.
2. `local/<model_name>` — locally-open Power BI Desktop instance by name.
3. `<workspace>.<semanticmodel>` — Fabric service dot notation (e.g. `MyWorkspace.MyModel`).

Format 3 is concise but ambiguous: a workspace name with a dot in it (allowed) collides with the parser's last-dot split. It also drifts from how Fabric itself names artefacts on disk — every Fabric workspace export looks like:

```
MyWorkspace.Workspace/
    MyModel.SemanticModel/
        definition/
        DAXQueries/
        ...
    MyReport.Report/
    ...
```

The new canonical syntax mirrors that path exactly: `MyWorkspace.Workspace/MyModel.SemanticModel`. Users typing it out think in terms of the workspace artefact they are targeting, not in terms of an opaque dot delimiter. Underneath, the resolver still calls `resolve_service_xmla_connection_by_name(workspace_name, model_name, opts)` exactly as today.

---

## Accept the New Fabric-Style Path Syntax

**Requirements**:
- Given `pql-test run-tests "MyWorkspace.Workspace/MyModel.SemanticModel"`, should parse as `kind='service'`, `workspace_name='MyWorkspace'`, `model_name='MyModel'`, and produce the same XMLA resolution result as today's `MyWorkspace.MyModel` dot notation
- Given the path-syntax form uses a Windows-style backslash (`MyWorkspace.Workspace\MyModel.SemanticModel`), should be accepted equivalently to the forward-slash form
- Given a workspace name that legitimately contains a dot (e.g. `My.Workspace.Workspace/MyModel.SemanticModel`), should still parse correctly because the new format anchors on the `.Workspace` and `.SemanticModel` suffixes, not on a single dot split
- Given an actual filesystem directory at the same string (`./MyWorkspace.Workspace/MyModel.SemanticModel` exists on disk), should fall back to filesystem-path resolution rather than mis-treating it as a service path

## Keep the Legacy `<workspace>.<model>` Form Working with a Deprecation Warning

**Requirements**:
- Given `pql-test run-tests "MyWorkspace.MyModel"` (legacy dot notation), should continue to resolve as `kind='service'` and produce the same connection it does today (no behavior break)
- Given the legacy form is used, should emit a one-line stderr warning recommending the new canonical syntax (e.g. *"Note: `<workspace>.<model>` is deprecated; use `<workspace>.Workspace/<model>.SemanticModel`."*), printed once per invocation
- Given the warning fires, should NOT pollute the stdout JSON output that scripts/CI parse — warnings must go to stderr

## Update Help Text and README to Show the New Format

**Requirements**:
- Given a user runs `--help` on `run-tests` or `retrieve-tests` or `retrieve-test`, should see the new format listed first in the "MODEL_PATH accepts three formats" block, with the legacy form noted as deprecated
- Given a user reads `README.md` §"Model Path Formats", should see the new format documented as canonical and the legacy form documented as a deprecated alias
- Given a user reads `README.md` examples for `run-tests` / `retrieve-tests`, should see Fabric-style paths in the demos (with at least one legacy example kept for migration clarity)
