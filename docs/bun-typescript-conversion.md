# Converting pql-test from Python to Bun + TypeScript

This document describes the concrete steps, known limitations, and ready-to-use
AI prompts for porting the `pql-test` Python project to a Bun-native TypeScript
implementation.

---

## Table of contents

1. [Why Bun + TypeScript?](#1-why-bun--typescript)
2. [Current Python architecture](#2-current-python-architecture)
3. [Target Bun + TypeScript architecture](#3-target-bun--typescript-architecture)
4. [Critical limitation: ADOMD.NET / XMLA connectivity](#4-critical-limitation-adomdnet--xmla-connectivity)
5. [Conversion steps](#5-conversion-steps)
   - [Step 1 – Scaffold the Bun project](#step-1--scaffold-the-bun-project)
   - [Step 2 – Port data types and enums](#step-2--port-data-types-and-enums)
   - [Step 3 – Port model discovery](#step-3--port-model-discovery)
   - [Step 4 – Port XMLA / ADOMD.NET connectivity](#step-4--port-xmla--adomdnet-connectivity)
   - [Step 5 – Port REST API helpers and MSAL auth](#step-5--port-rest-api-helpers-and-msal-auth)
   - [Step 6 – Port the CLI](#step-6--port-the-cli)
   - [Step 7 – Port output formatters](#step-7--port-output-formatters)
   - [Step 8 – Port the test suite](#step-8--port-the-test-suite)
   - [Step 9 – Build, bundle, and package](#step-9--build-bundle-and-package)
   - [Step 10 – Update CI workflows](#step-10--update-ci-workflows)
6. [File-by-file mapping](#6-file-by-file-mapping)
7. [Dependency mapping](#7-dependency-mapping)
8. [Limitations and known gaps](#8-limitations-and-known-gaps)
9. [AI prompts for the conversion](#9-ai-prompts-for-the-conversion)

---

## 1. Why Bun + TypeScript?

| Concern | Python | Bun + TypeScript |
|---|---|---|
| Startup time | 200–400 ms (interpreter + imports) | < 50 ms (native binary) |
| Single-binary distribution | `pyinstaller` / complex | `bun build --compile` → one exe |
| Type safety | Runtime dataclass, Optional | Compile-time interfaces, strict null checks |
| Native test runner | pytest | `bun test` (built-in, Jest-compatible) |
| Package manager | pip + pyproject.toml | `bun install` + package.json |
| Cross-platform JSON/HTTP | stdlib | Bun `fetch`, `Bun.file`, `node:fs` |
| .NET interop (ADOMD.NET) | `pythonnet` / `clr` | **No native equivalent — see §4** |

---

## 2. Current Python architecture

```
python/
├── pql_test_runner.py    # Core library (~1 000 lines)
│   ├── Enums / dataclasses (Environment, PqlTest, TestResult, TestSuite,
│   │         XmlaConnectionOptions, ResolvedXmlaConnection, LocalPbiInstance)
│   ├── ADOMD.NET loader (pythonnet / clr — Windows only)
│   ├── Model discovery  (_find_semantic_model_dir, _collect_dax_test_files,
│   │                      _parse_dax_test_file)
│   ├── Local PBI Desktop detection (EnumWindows via ctypes, psutil, port file)
│   ├── XMLA connection resolution (resolve_xmla_connection,
│   │         resolve_local_xmla_connection, _detect_local_pbi_desktop_port)
│   ├── Power BI REST API helpers (_resolve_pbi_workspace_and_dataset_names)
│   ├── MSAL token acquisition (_acquire_service_principal_token)
│   ├── DAX query execution (_execute_dax_query via AdomdConnection)
│   └── Public API (retrieve_tests, retrieve_test_by_name,
│                    run_test, run_tests, run_tests_from_model)
│
├── pql_test_cli.py       # Click CLI (~720 lines)
│   ├── check-prereqs
│   ├── retrieve-tests
│   ├── retrieve-test
│   └── run-tests
│         (with --log-format github | azuredevops output formatters)
│
└── tests/
    ├── conftest.py                # tmp_model fixture, sample_model_path
    ├── test_pql_test_runner.py    # Unit tests (~995 lines)
    ├── test_pql_test_cli.py       # CLI integration tests (~552 lines)
    └── test_live_service.py       # Live XMLA tests (skipped without creds)
```

Key third-party dependencies:

| Package | Role |
|---|---|
| `pythonnet` (`clr`) | Load ADOMD.NET `.dll` into the Python process |
| `pyadomd` | Thin ADOMD wrapper (optional; `clr` used directly) |
| `msal` | OAuth2 client-credentials flow for service principals |
| `click` | CLI argument parsing |
| `psutil` | Process/port enumeration for local PBI Desktop detection |
| `python-dotenv` | Auto-load `.env` credentials file |

---

## 3. Target Bun + TypeScript architecture

```
src/
├── types.ts            # Interfaces + enums (replaces Python dataclasses)
├── endpoints.ts        # Cloud-environment → API URL mapping
├── discovery.ts        # PBIP model discovery (replaces _find_* / _collect_*)
├── auth.ts             # MSAL / OAuth2 token acquisition (@azure/msal-node)
├── pbiApi.ts           # Power BI REST API helpers (fetch-based)
├── xmla.ts             # XMLA / ADOMD.NET connectivity (see §4)
├── connection.ts       # Connection resolution logic
├── runner.ts           # run_test, run_tests, run_tests_from_model
├── cli.ts              # CLI entry-point (commander or citty)
├── formatters/
│   ├── human.ts        # Human-readable output
│   ├── github.ts       # ::group:: / ::error:: annotations
│   └── azuredevops.ts  # ##[group] / ##[error] / ##vso annotations
└── index.ts            # Public API re-exports

tests/
├── discovery.test.ts
├── runner.test.ts
├── cli.test.ts
└── live.test.ts        # Skipped without PQL_* env vars

package.json            # name: "pql-test", bin: "src/cli.ts"
tsconfig.json
bunfig.toml             # Bun-specific config
```

---

## 4. Critical limitation: ADOMD.NET / XMLA connectivity

> **This is the hardest part of the conversion and the most important limitation
> to understand before starting.**

The Python implementation uses `pythonnet` (`clr`) to load
`Microsoft.PowerBI.AdomdClient.dll` (a .NET assembly) directly into the Python
process.  There is **no equivalent in the JavaScript / Bun ecosystem**.

### Options for TypeScript XMLA connectivity

| Approach | Viability | Notes |
|---|---|---|
| **`node-adodb`** | ⚠️ Limited | Wraps ADO/OLEDB via a child process + `wscript`. Works on Windows only; XMLA/MSOLAP not well-tested. |
| **`mssql` + `tedious`** | ❌ Wrong protocol | TDS (SQL Server), not XMLA/ADOMD. |
| **`xmla4js`** | ⚠️ Abandoned | Pure-JS XMLA over HTTP. Supports XMLA Discover/Execute but not modern Power BI Premium auth. Would need significant patching for bearer-token auth. |
| **Custom HTTP XMLA** | ✅ Recommended | Power BI Premium/Fabric XMLA endpoints accept plain HTTP POST with an `Authorization: Bearer <token>` header and an XML SOAP envelope. No .NET assembly needed. Works cross-platform. |
| **Child process (`pql-test` Python)** | ✅ Transitional | Call the existing Python CLI as a child process. Avoids re-implementing XMLA. Useful while the HTTP XMLA layer is being built. |
| **`@azure-rest/synapse-artifacts`** or REST API polling | ❌ Different use-case | Dataset refresh API, not direct DAX query execution. |

### Recommended XMLA approach for the TypeScript port

Use the **XMLA over HTTP** protocol directly with `fetch`.  Power BI Premium
and Fabric XMLA endpoints support the standard XMLA XML/A 1.1 SOAP envelope:

```
POST https://wabi-us-north-central-redirect.analysis.windows.net/xmla
Authorization: Bearer <access_token>
Content-Type: text/xml; charset=utf-8
SOAPAction: "urn:schemas-microsoft-com:xml-analysis:Execute"

<?xml version="1.0" encoding="utf-8"?>
<Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">
  <Body>
    <Execute xmlns="urn:schemas-microsoft-com:xml-analysis">
      <Command>
        <Statement>EVALUATE ...</Statement>
      </Command>
      <Properties>
        <PropertyList>
          <Catalog>DatasetDisplayName</Catalog>
        </PropertyList>
      </Properties>
    </Execute>
  </Body>
</Envelope>
```

The SOAP response returns rows in the `<root>` element under
`<return><root xmlns="urn:schemas-microsoft-com:xml-analysis:rowset">`.
Parse with a lightweight XML parser (`fast-xml-parser` or Bun's built-in
`HTMLRewriter`).

**Local Power BI Desktop** also exposes an HTTP XMLA endpoint on
`http://localhost:<port>/xmla`, so the same fetch-based approach works for both
local and remote connections once the port is known.

---

## 5. Conversion steps

### Step 1 – Scaffold the Bun project

```bash
# In the repository root
mkdir -p bun
cd bun

bun init -y          # creates package.json, tsconfig.json, index.ts
```

Edit `package.json`:

```json
{
  "name": "pql-test",
  "version": "0.1.0",
  "description": "Run DAX tests in Power BI PBIP models via XMLA",
  "bin": "src/cli.ts",
  "scripts": {
    "test":  "bun test",
    "build": "bun build src/cli.ts --compile --outfile pql-test",
    "check": "tsc --noEmit"
  },
  "dependencies": {
    "@azure/msal-node": "^2.6.0",
    "commander": "^12.0.0",
    "dotenv": "^16.4.0",
    "fast-xml-parser": "^4.4.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "typescript": "^5.4.0"
  }
}
```

`tsconfig.json` recommended settings:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "outDir": "dist",
    "types": ["bun-types", "node"]
  },
  "include": ["src/**/*", "tests/**/*"]
}
```

---

### Step 2 – Port data types and enums

`src/types.ts` — direct translation of all Python dataclasses:

```typescript
// Python: class Environment(str, Enum)
export enum Environment {
  Public    = "Public",
  Germany   = "Germany",
  China     = "China",
  USGov     = "USGov",
  USGovHigh = "USGovHigh",
  USGovDoD  = "USGovDoD",
}

// Python: @dataclass class PqlTest
export interface PqlTest {
  name: string;
  filePath: string;
  source: string;
  description?: string;
}

// Python: @dataclass class TestResult
export interface TestResult {
  testName: string;
  passed: boolean;
  message: string;
  skipped?: boolean;
  error?: string;
  durationMs?: number;
  actual?: string;
  expected?: string;
  suiteName?: string;
}

// Python: @dataclass class TestSuite
export interface TestSuite {
  modelPath: string;
  tests: PqlTest[];
  results: TestResult[];
  passed: number;
  failed: number;
  skipped: number;
  total: number;
}

// Python: @dataclass class XmlaConnectionOptions
export interface XmlaConnectionOptions {
  tenantId?:    string;
  workspaceId?: string;
  datasetId?:   string;
  clientId?:    string;
  clientSecret?: string;
  environment?: Environment;
}

// Python: @dataclass class ResolvedXmlaConnection
export interface ResolvedXmlaConnection {
  server: string;
  catalog: string;
  tenantId?:    string;
  clientId?:    string;
  clientSecret?: string;
  accessToken?: string;
}

// Python: @dataclass class LocalPbiInstance
export interface LocalPbiInstance {
  modelName: string;
  server: string;
  catalog: string;
}

// Python: @dataclass class Endpoints
export interface Endpoints {
  apiPrefix:   string;
  resourceUrl: string;
  loginUrl:    string;
}
```

---

### Step 3 – Port model discovery

`src/discovery.ts` — replaces `_find_semantic_model_dir`, `_collect_dax_test_files`,
`_parse_dax_test_file`, `retrieve_tests`, `retrieve_test_by_name`:

```typescript
import { readdirSync, existsSync, readFileSync, statSync } from "node:fs";
import { join, basename, extname } from "node:path";
import type { PqlTest } from "./types";

export function findSemanticModelDir(modelPath: string): string | null {
  if (!existsSync(modelPath)) return null;
  const stat = statSync(modelPath);
  // Passed the .SemanticModel directory directly
  if (stat.isDirectory() && basename(modelPath).endsWith(".SemanticModel"))
    return modelPath;
  // Passed a .pbip file — scan its parent directory
  const scanDir = !stat.isDirectory() ? join(modelPath, "..") : modelPath;
  // Scan the directory for a .SemanticModel subdirectory
  for (const entry of readdirSync(scanDir)) {
    const full = join(scanDir, entry);
    if (entry.endsWith(".SemanticModel") && statSync(full).isDirectory())
      return full;
  }
  return null;
}

export function collectDaxTestFiles(semanticModelDir: string): string[] {
  const daxDir = join(semanticModelDir, "DAXQueries");
  if (!existsSync(daxDir)) return [];
  return readdirSync(daxDir)
    .filter(f => f.endsWith(".Tests.dax"))
    .map(f => join(daxDir, f))
    .sort();
}

export function parseDaxTestFile(filePath: string): PqlTest {
  const source = readFileSync(filePath, "utf-8");
  const name   = basename(filePath, extname(filePath)); // stem without .dax
  // Note: DAX FUNCTION names in practice use only word characters and dots
  // (e.g. "Calculations.DEV").  The pattern matches the same set that the
  // Python original does; extend if your test files use other characters.
  const funcMatch = source.match(/FUNCTION\s+([\w.]+)\s*=/i);
  return {
    name,
    filePath,
    source,
    description: funcMatch ? `DAX function: ${funcMatch[1]}` : undefined,
  };
}

export function retrieveTests(modelPath: string): PqlTest[] {
  const dir = findSemanticModelDir(modelPath);
  if (!dir) return [];
  return collectDaxTestFiles(dir).map(parseDaxTestFile);
}

export function retrieveTestByName(
  modelPath: string,
  testName: string,
): PqlTest | undefined {
  return retrieveTests(modelPath).find(
    t => t.name.toLowerCase() === testName.toLowerCase(),
  );
}
```

---

### Step 4 – Port XMLA / ADOMD.NET connectivity

`src/xmla.ts` — replaces `_execute_dax_query` using HTTP XMLA (see §4):

```typescript
import { XMLParser } from "fast-xml-parser";
import type { ResolvedXmlaConnection } from "./types";

const parser = new XMLParser({ ignoreAttributes: false });

/** Build the XMLA Execute SOAP envelope for a DAX query. */
function buildSoapEnvelope(dax: string, catalog: string): string {
  // Escape XML special characters in the DAX source
  const escaped = dax
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return `<?xml version="1.0" encoding="utf-8"?>
<Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">
  <Body>
    <Execute xmlns="urn:schemas-microsoft-com:xml-analysis">
      <Command><Statement>${escaped}</Statement></Command>
      <Properties>
        <PropertyList>
          <Catalog>${catalog}</Catalog>
          <Format>Tabular</Format>
        </PropertyList>
      </Properties>
    </Execute>
  </Body>
</Envelope>`;
}

/** Parse the XML/A rowset response into an array of column→value objects. */
function parseRowset(xml: string): Record<string, string>[] {
  const doc = parser.parse(xml);
  // Navigate: Envelope > Body > ExecuteResponse > return > root > row
  const root =
    doc?.["soap:Envelope"]?.["soap:Body"]?.["ExecuteResponse"]?.["return"]?.[
      "root"
    ] ??
    doc?.Envelope?.Body?.ExecuteResponse?.return?.root;
  if (!root) return [];
  const rows: unknown[] = Array.isArray(root.row)
    ? root.row
    : root.row
    ? [root.row]
    : [];
  return rows.map(r => {
    const row = r as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(row)
        .filter(([k]) => !k.startsWith("@"))
        .map(([k, v]) => [k, String(v ?? "")]),
    );
  });
}

/** Case-insensitive column lookup (mirrors Python _get_col). */
export function getCol(row: Record<string, string>, key: string): string {
  const lower = key.toLowerCase();
  for (const [k, v] of Object.entries(row)) {
    const kl = k.toLowerCase();
    if (kl === lower || kl.endsWith(`[${lower}]`)) return v;
  }
  return "";
}

/** Execute a DAX query against the XMLA endpoint via HTTP. */
export async function executeDaxQuery(
  conn: ResolvedXmlaConnection,
  daxQuery: string,
): Promise<Record<string, string>[]> {
  // Determine the XMLA URL
  // Remote Power BI Premium/Fabric: server = powerbi://api.powerbi.com/v1.0/myorg/WorkspaceName
  // Local Power BI Desktop:         server = localhost:NNNNN  (or 127.0.0.1:NNNNN)
  const isLocal =
    conn.server.startsWith("localhost") ||
    conn.server.startsWith("127.") ||   // covers 127.0.0.1 and the full 127.x.x.x range
    conn.server.startsWith("[::1]");    // IPv6 loopback
  const url = isLocal
    ? `http://${conn.server}/xmla`
    : `https://${conn.server.replace(/^powerbi:\/\//, "")}/xmla`;

  const headers: Record<string, string> = {
    "Content-Type": "text/xml; charset=utf-8",
    "SOAPAction":   '"urn:schemas-microsoft-com:xml-analysis:Execute"',
  };
  if (conn.accessToken) {
    headers["Authorization"] = `Bearer ${conn.accessToken}`;
  }

  const response = await fetch(url, {
    method: "POST",
    headers,
    body: buildSoapEnvelope(daxQuery, conn.catalog),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`XMLA HTTP ${response.status}: ${body.slice(0, 400)}`);
  }

  return parseRowset(await response.text());
}
```

---

### Step 5 – Port REST API helpers and MSAL auth

`src/auth.ts` — replaces `_acquire_service_principal_token` using
`@azure/msal-node` (the official MSAL TypeScript library, used by
Invoke-DQVTesting's C# counterpart):

```typescript
import { ConfidentialClientApplication } from "@azure/msal-node";

export async function acquireServicePrincipalToken(
  tenantId: string,
  clientId: string,
  clientSecret: string,
  opts: { loginUrl?: string; resourceUrl?: string } = {},
): Promise<string> {
  const loginUrl   = opts.loginUrl   ?? "https://login.microsoftonline.com";
  const resourceUrl = opts.resourceUrl ?? "https://analysis.windows.net/powerbi/api";

  const app = new ConfidentialClientApplication({
    auth: {
      clientId,
      clientSecret,
      authority: `${loginUrl}/${tenantId}`,
    },
  });

  const result = await app.acquireTokenByClientCredential({
    scopes: [`${resourceUrl}/.default`],
  });

  if (!result?.accessToken) {
    throw new Error("Failed to acquire access token from MSAL");
  }
  return result.accessToken;
}
```

`src/pbiApi.ts` — replaces `_resolve_pbi_workspace_and_dataset_names`:

```typescript
export async function resolvePbiWorkspaceAndDatasetNames(
  workspaceId: string,
  datasetId: string,
  accessToken: string,
  apiPrefix = "https://api.powerbi.com",
): Promise<{ workspaceName: string; datasetName: string }> {
  const base = `${apiPrefix}/v1.0/myorg`;
  const headers = { Authorization: `Bearer ${accessToken}` };

  const wsRes   = await fetch(`${base}/groups/${workspaceId}`, { headers });
  const dsRes   = await fetch(`${base}/groups/${workspaceId}/datasets/${datasetId}`, { headers });

  if (!wsRes.ok) throw new Error(`Workspace lookup failed: ${wsRes.status}`);
  if (!dsRes.ok) throw new Error(`Dataset lookup failed: ${dsRes.status}`);

  const ws = await wsRes.json() as { name: string };
  const ds = await dsRes.json() as { name: string };

  return { workspaceName: ws.name, datasetName: ds.name };
}
```

---

### Step 6 – Port the CLI

`src/cli.ts` — replaces `pql_test_cli.py` using `commander`:

```typescript
#!/usr/bin/env bun
import { Command } from "commander";
import { config as dotenv } from "dotenv";
import { runTestsFromModel } from "./runner";
import { retrieveTests, retrieveTestByName } from "./discovery";
import { printGithub, printAzureDevOps, printHuman } from "./formatters/human";

dotenv(); // load .env

const program = new Command("pql-test")
  .version("0.1.0");

// ── check-prereqs ─────────────────────────────────────────────────────────
program.command("check-prereqs")
  .description("Verify runtime dependencies")
  .action(cmdCheckPrereqs);

// ── retrieve-tests ────────────────────────────────────────────────────────
program.command("retrieve-tests <modelPath>")
  .option("--human",   "Human-readable output")
  .option("--verbose", "Include file paths and connection info")
  .action(async (modelPath, opts) => { /* ... */ });

// ── retrieve-test ─────────────────────────────────────────────────────────
program.command("retrieve-test <modelPath> <name>")
  .option("--human",   "Human-readable output")
  .option("--verbose", "Also print DAX source")
  .action(async (modelPath, name, opts) => { /* ... */ });

// ── run-tests ─────────────────────────────────────────────────────────────
program.command("run-tests <modelPath>")
  .option("--test <name>",    "Run only the named test suite")
  .option("--verbose",        "Per-assertion detail")
  .option("--output <file>",  "Write JSON results to file")
  .option("--log-format <fmt>", "github | azuredevops")
  .option("--tenant-id <id>",    "Azure AD tenant ID")
    .default("tenant-id",    process.env.PQL_TENANT_ID)
  .option("--workspace-id <id>", "Power BI workspace GUID")
    .default("workspace-id", process.env.PQL_WORKSPACE_ID)
  .option("--dataset-id <id>",   "Dataset / semantic model GUID")
    .default("dataset-id",   process.env.PQL_DATASET_ID)
  .option("--client-id <id>",    "Service principal client ID")
    .default("client-id",    process.env.PQL_CLIENT_ID)
  .option("--client-secret <s>", "Service principal client secret")
    .default("client-secret",process.env.PQL_CLIENT_SECRET)
  .action(async (modelPath, opts) => { /* ... */ });

program.parseAsync(process.argv);
```

---

### Step 7 – Port output formatters

`src/formatters/github.ts` — direct translation of `_print_results_github`:

```typescript
import type { TestSuite } from "../types";

export function printGithub(suite: TestSuite): void {
  for (const result of suite.results) {
    if (result.skipped) {
      console.log(`::notice title=SKIP::${result.testName}`);
      continue;
    }
    if (result.passed) {
      console.log(`::notice title=PASS::${result.testName}`);
    } else {
      console.log(
        `::error title=FAIL::${result.testName} | ` +
        `Expected: ${result.expected ?? ""} | ` +
        `Actual: ${result.actual ?? ""}`,
      );
    }
  }
  const exitCode = suite.failed > 0 ? 1 : 0;
  process.exitCode = exitCode;
}
```

---

### Step 8 – Port the test suite

Bun includes a built-in Jest-compatible test runner.  `tests/discovery.test.ts`
replaces `test_pql_test_runner.py` for the discovery layer:

```typescript
import { describe, it, expect, beforeEach } from "bun:test";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { retrieveTests, retrieveTestByName } from "../src/discovery";

const TMP = "/tmp/pql-test-bun-tests";

beforeEach(() => {
  rmSync(TMP, { recursive: true, force: true });
  mkdirSync(join(TMP, "model.SemanticModel", "DAXQueries"), { recursive: true });
});

describe("retrieveTests", () => {
  it("returns empty array when no DAXQueries folder exists", () => {
    expect(retrieveTests("/nonexistent")).toEqual([]);
  });

  it("discovers Tests.dax files", () => {
    writeFileSync(
      join(TMP, "model.SemanticModel", "DAXQueries", "Calcs.DEV.Tests.dax"),
      "EVALUATE ROW()",
    );
    const tests = retrieveTests(TMP);
    expect(tests).toHaveLength(1);
    expect(tests[0]!.name).toBe("Calcs.DEV.Tests");
  });
});
```

---

### Step 9 – Build, bundle, and package

```bash
# Development (run directly from source, no compile step)
bun run src/cli.ts check-prereqs

# Type-check only
bun run check

# Produce a single self-contained executable (no Bun runtime needed)
bun build src/cli.ts --compile --outfile pql-test
# → pql-test (linux/mac) or pql-test.exe (windows)

# Run tests
bun test

# Run tests with coverage
bun test --coverage
```

---

### Step 10 – Update CI workflows

The existing `validate-plugin.yml` and `ci.yml` install and run the Python
CLI with `pip install ./python`.  After the Bun port is complete, update those
steps:

```yaml
# Before (Python)
- name: Set up Python
  uses: actions/setup-python@v5
  with: { python-version: '3.12' }
- run: pip install ./python

# After (Bun)
- name: Set up Bun
  uses: oven-sh/setup-bun@v1
  with: { bun-version: latest }
- name: Install dependencies
  run: bun install
  working-directory: bun
- name: Build CLI
  run: bun build src/cli.ts --compile --outfile ../pql-test
  working-directory: bun
```

> **Note:** Stage 3 (`run-tests-remote.yml`) uses `windows-latest` because
> the Python implementation needs ADOMD.NET.  Once the Bun port uses HTTP XMLA
> (§4) it can run on `ubuntu-latest`, removing the Windows dependency.

---

## 6. File-by-file mapping

| Python file | TypeScript equivalent | Notes |
|---|---|---|
| `pql_test_runner.py` (enums/dataclasses) | `src/types.ts` | `@dataclass` → `interface`; `Enum` → `enum` |
| `pql_test_runner.py` (endpoints) | `src/endpoints.ts` | Direct translation |
| `pql_test_runner.py` (discovery) | `src/discovery.ts` | `Path` → `node:path` + `node:fs` |
| `pql_test_runner.py` (PBI Desktop detect) | `src/localPbi.ts` | `psutil` → `node:child_process` (`tasklist`, `netstat`) or a Windows-only native addon; `ctypes.windll` → no equivalent |
| `pql_test_runner.py` (ADOMD.NET query) | `src/xmla.ts` | Biggest change: HTTP XMLA instead of `clr` |
| `pql_test_runner.py` (MSAL auth) | `src/auth.ts` | `msal` → `@azure/msal-node` |
| `pql_test_runner.py` (REST API) | `src/pbiApi.ts` | `urllib.request` → `fetch` |
| `pql_test_runner.py` (run_test/run_tests) | `src/runner.ts` | Async-first |
| `pql_test_cli.py` | `src/cli.ts` | `click` → `commander` |
| `pql_test_cli.py` (formatters) | `src/formatters/*.ts` | Direct translation |
| `tests/conftest.py` | `tests/fixtures.ts` | `tmp_model` → helper using `mkdirSync` |
| `tests/test_pql_test_runner.py` | `tests/runner.test.ts` | `pytest` → `bun test` |
| `tests/test_pql_test_cli.py` | `tests/cli.test.ts` | `CliRunner` → `Bun.spawnSync` |
| `tests/test_live_service.py` | `tests/live.test.ts` | `pytest.mark.live` → `if (!env.PQL_TENANT_ID) test.skip(...)` |
| `pyproject.toml` | `package.json` | — |
| `python/.env.example` | `bun/.env.example` | Same variable names |

---

## 7. Dependency mapping

| Python | npm/bun | Notes |
|---|---|---|
| `pythonnet` / `clr` | *(none)* | HTTP XMLA removes the need entirely |
| `pyadomd` | *(none)* | Replaced by HTTP XMLA (§4) |
| `msal` | `@azure/msal-node` | Official Microsoft SDK |
| `click` | `commander` or `citty` | Both have first-class TypeScript support |
| `psutil` | `node:child_process` + `systeminformation` | Process detection; `systeminformation` is cross-platform |
| `python-dotenv` | `dotenv` | Identical API |
| `pytest` | `bun test` | Built-in, no install needed |
| `pytest-cov` | `bun test --coverage` | Built-in |
| `dataclass` | TypeScript `interface` | Structural typing |
| `Enum` | TypeScript `enum` | — |
| `urllib.request` | `fetch` | Built into Bun/Node 18+ |
| `pathlib.Path` | `node:path` + `node:fs` | — |
| `re` | `RegExp` | — |
| `ctypes.windll` | `ffi-napi` or PowerShell child process | Windows only; needed only for local PBI detection via `EnumWindows` |

---

## 8. Limitations and known gaps

### 8.1 Local Power BI Desktop detection

The Python code uses two Windows-only mechanisms:

1. **`ctypes.windll.user32.EnumWindows`** — enumerate visible windows to find
   PBIDesktop.exe PIDs.  There is no cross-platform equivalent in Node.js/Bun.
   Workaround: call `tasklist /FI "IMAGENAME eq PBIDesktop.exe" /FO CSV` via
   `node:child_process`'s `execSync` on Windows.

2. **`psutil`** — enumerate TCP LISTEN ports per process.  Replacement:
   `netstat -ano` on Windows / `ss -tlnp` on Linux, parsed via `node:child_process`,
   or the `systeminformation` npm package.

The port file detection (`msmdsrv.port.txt`) is purely file-system based and
translates directly to `node:fs`.

> On **non-Windows platforms** local PBI Desktop detection is a no-op in both
> the Python and TypeScript versions.

### 8.2 HTTP XMLA and local PBI Desktop

Power BI Desktop's embedded AS engine exposes XMLA over HTTP at
`http://localhost:<port>/xmla` but does **not** require an `Authorization`
header for local connections.  The HTTP XMLA approach works for both remote
Premium/Fabric and local Desktop without any platform-specific native code.

### 8.3 `bun build --compile` and native addons

`bun build --compile` cannot bundle native `.node` addons.  If any dependency
(e.g. `ffi-napi` for `EnumWindows`) requires a native addon the resulting
binary will fail to run.  Use child-process fallbacks (`powershell`, `tasklist`,
`netstat`) instead.

### 8.4 XMLA XML parsing edge cases

The Python ADOMD.NET client handles all SOAP/XML parsing internally.  The
TypeScript HTTP XMLA layer must handle:
- SOAP faults (error responses)
- Empty result sets
- Multiple result sets in one response
- Column names with table prefix (`TableName[ColumnName]`)
- UTF-8 encoding in cell values

These are all manageable but require careful testing with real endpoints.

### 8.5 Windows-only ADOMD.NET for local development

If the team uses local Power BI Desktop for development, the Bun port will
still need to detect the AS port on Windows.  The pure-JS approach via
child process is slightly more fragile than `psutil` but has no .NET
dependency.

### 8.6 `bun:test` vs pytest feature parity

| pytest feature | `bun test` equivalent |
|---|---|
| `@pytest.fixture` | `beforeEach` / `beforeAll` helper functions |
| `tmp_path` | `mkdtempSync` from `node:fs` or `os.tmpdir()` |
| `@pytest.mark.live` | `test.skipIf(condition, ...)` |
| `pytest.raises` | `expect(() => ...).toThrow(...)` |
| `monkeypatch` | `jest.spyOn` / `mock.module` |
| `pytest-cov` | `bun test --coverage` |
| Parametrize | `it.each([[...], [...]])` |

### 8.7 ESM vs CJS

Bun uses ESM by default.  Ensure `"type": "module"` is set in `package.json`
and all imports use `.js` extensions (TypeScript resolves them to `.ts`).

---

## 9. AI prompts for the conversion

The following prompts are designed to be used with GitHub Copilot, Copilot Chat
in VS Code, or a similar AI coding assistant.  Each prompt targets a specific
conversion task and provides enough context for the AI to produce code that
follows the patterns already established in the Python source.

> **Note on line number references:** The prompts below include approximate line
> ranges for the current Python source files.  If the Python code has been
> modified since this document was written the line numbers may have shifted.
> Use the function and class names (which are stable) as your primary reference
> and treat line ranges as a starting point for a search.

---

### Prompt 1 — Project scaffold

```
I am converting a Python CLI tool called pql-test to Bun + TypeScript.
The Python project is at python/ and consists of:
  - python/pql_test_runner.py  (~1000 lines) — the core library
  - python/pql_test_cli.py     (~720 lines)  — a Click CLI
  - python/tests/              — pytest test suite

Create the Bun project scaffold at bun/ with:
  - package.json  (name "pql-test", bin "src/cli.ts", scripts for test/build/check)
  - tsconfig.json (strict mode, moduleResolution bundler, target ES2022)
  - bunfig.toml   (test timeout 30s, coverage enabled)
  - src/ and tests/ empty directories
  - bun/.env.example matching the PQL_* variables from python/.env.example

Do not write any application logic yet — just the project structure.
```

---

### Prompt 2 — Data types

```
Convert the Python dataclasses and enums from python/pql_test_runner.py
to TypeScript interfaces and enums in bun/src/types.ts.

Rules:
  - Python @dataclass → TypeScript interface (no class needed)
  - Python Optional[X] → X | undefined  (not X | null)
  - Python str Enum → TypeScript string enum
  - snake_case field names → camelCase (e.g. file_path → filePath)
  - Keep all docstrings as JSDoc comments

Source (paste the dataclass/enum section from pql_test_runner.py here):
[paste lines 109–260 of python/pql_test_runner.py]
```

---

### Prompt 3 — Model discovery

```
Convert the model discovery functions from python/pql_test_runner.py to
bun/src/discovery.ts.  Use node:fs and node:path only (no third-party
file-system libraries).

Python functions to convert:
  - _find_semantic_model_dir(model_path) → findSemanticModelDir(modelPath)
  - _find_pbip_file(model_path)          → findPbipFile(modelPath)
  - _collect_dax_test_files(dir)         → collectDaxTestFiles(dir)
  - _parse_dax_test_file(path)           → parseDaxTestFile(path)
  - retrieve_tests(model_path)           → retrieveTests(modelPath)
  - retrieve_test_by_name(path, name)    → retrieveTestByName(modelPath, name)

Import PqlTest from ./types.  All functions are synchronous (no async needed).
Use strict TypeScript — no any, no non-null assertions.

Source:
[paste lines 273–360 and 812–870 of python/pql_test_runner.py]
```

---

### Prompt 4 — HTTP XMLA connectivity

```
Implement bun/src/xmla.ts to execute DAX queries against a Power BI XMLA
endpoint using HTTP (not ADOMD.NET / pyadomd).

Requirements:
  1. Build a XMLA 1.1 SOAP Execute envelope with the DAX query and catalog name.
  2. POST to:
       - Remote: https://<server-without-powerbi://>/<path>/xmla
         with Authorization: Bearer <accessToken> header
       - Local PBI Desktop: http://localhost:<port>/xmla
         without an Authorization header
  3. Parse the XML/A rowset response using fast-xml-parser.
  4. Return rows as Record<string, string>[].
  5. Implement getCol(row, key) for case-insensitive column lookup
     (must handle bracket-notation "Table[Column]" names).
  6. Throw an Error with the SOAP fault detail when the response is a fault.

Import types from ./types.  Function signature:
  export async function executeDaxQuery(
    conn: ResolvedXmlaConnection,
    daxQuery: string,
  ): Promise<Record<string, string>[]>

Reference the Python original:
[paste lines 714–815 of python/pql_test_runner.py]
```

---

### Prompt 5 — MSAL authentication

```
Convert python/pql_test_runner.py's _acquire_service_principal_token function
to bun/src/auth.ts using @azure/msal-node (ConfidentialClientApplication).

Python function signature:
  _acquire_service_principal_token(
      tenant_id, client_id, client_secret,
      *, login_url, resource_url
  ) -> str

TypeScript target:
  export async function acquireServicePrincipalToken(
    tenantId: string,
    clientId: string,
    clientSecret: string,
    opts?: { loginUrl?: string; resourceUrl?: string },
  ): Promise<string>

Default loginUrl:    "https://login.microsoftonline.com"
Default resourceUrl: "https://analysis.windows.net/powerbi/api"
Throw a descriptive Error when token acquisition fails.
```

---

### Prompt 6 — Connection resolution

```
Convert the XMLA connection resolution logic from python/pql_test_runner.py
to bun/src/connection.ts.

Functions to convert:
  - resolve_xmla_connection(model_path, opts)    → resolveXmlaConnection(modelPath, opts)
  - resolve_local_xmla_connection(model_path)    → resolveLocalXmlaConnection(modelPath)
  - _detect_local_pbi_desktop_port()            → detectLocalPbiDesktopPort()
  - get_pbi_files_opened()                       → getPbiFilesOpened()

Notes on platform-specific code:
  - _get_pbi_process_window_titles() uses ctypes.windll — replace with
    execSync("tasklist /FI \"IMAGENAME eq PBIDesktop.exe\" /FO CSV") on Windows
    (process.platform === "win32") and return {} on other platforms.
  - psutil TCP port enumeration → execSync("netstat -ano") on Windows,
    parsed to find LISTEN ports per PID.
  - The msmdsrv.port.txt file detection is pure fs — translate directly.

Import from ./types, ./auth, ./pbiApi, ./xmla, ./endpoints.
All functions are async.

Source:
[paste lines 408–640 of python/pql_test_runner.py]
```

---

### Prompt 7 — Test runner

```
Convert the public test-execution API from python/pql_test_runner.py to
bun/src/runner.ts.

Functions:
  - run_test(test, connection, skip_message)       → runTest(...)
  - run_tests(tests, connection, skip_message)     → runTests(...)
  - run_tests_from_model(model_path, ...)          → runTestsFromModel(...)

All functions are async (executeDaxQuery is async).
Use the DEFAULT_SKIP_MESSAGE constant from the Python source.
Implement getCol from xmla.ts for column extraction.
Return TestSuite from runTestsFromModel.

Source:
[paste lines 858–1001 of python/pql_test_runner.py]
```

---

### Prompt 8 — CLI output formatters

```
Convert the three output formatters from python/pql_test_cli.py to TypeScript
in bun/src/formatters/:
  - _print_results()             → human.ts   printHuman(suite, verbose, preWarnings)
  - _print_results_github()      → github.ts  printGithub(suite, preWarnings)
  - _print_results_azuredevops() → azuredevops.ts  printAzureDevOps(suite, preWarnings)

Each formatter should call process.exit(suite.failed > 0 ? 1 : 0) at the end
when called from the CLI (pass an exit parameter: boolean = false to avoid
calling process.exit in tests).

Source:
[paste lines 192–390 of python/pql_test_cli.py]
```

---

### Prompt 9 — CLI entry-point

```
Convert python/pql_test_cli.py to bun/src/cli.ts using the commander package.

Commands to implement:
  check-prereqs   — check for @azure/msal-node and fast-xml-parser; report versions
  retrieve-tests  MODEL_PATH  [--test NAME] [--human] [--verbose]
  retrieve-test   MODEL_PATH  NAME  [--human] [--verbose]
  run-tests       MODEL_PATH  [--test NAME] [--verbose] [--output FILE]
                              [--log-format github|azuredevops]
                              [--tenant-id] [--workspace-id] [--dataset-id]
                              [--client-id] [--client-secret] [--environment]

Each option that has a PQL_* env-var fallback must read process.env at startup.
Load dotenv at the top of the file before parsing options.
Use process.exitCode (not process.exit) so async cleanup still runs.

Source:
[paste lines 389–720 of python/pql_test_cli.py]
```

---

### Prompt 10 — Test suite

```
Convert python/tests/test_pql_test_runner.py to bun/tests/runner.test.ts using
bun:test (Jest-compatible API).

Mapping:
  - @pytest.fixture tmp_model → beforeEach that creates a temp dir with mkdirSync
  - pytest.raises(X) → expect(() => fn()).toThrow()
  - unittest.mock.patch → mock.module from bun:test or jest.spyOn
  - @pytest.mark.skipif(not HAS_X) → test.skipIf(!hasX, ...)

Keep all existing test descriptions exactly as-is (translated to it() strings).
Do not use any type: any.

Source:
[paste the full content of python/tests/test_pql_test_runner.py]
```

---

### Prompt 11 — GitHub Actions CI update

```
Update .github/workflows/run-tests-remote.yml to support running the Bun
TypeScript version of pql-test.  The workflow should:

1. Accept an input "runtime" with values "python" (default) and "bun".
2. When runtime == "python": existing pip install + windows-latest behavior.
3. When runtime == "bun":
   a. Use ubuntu-latest (HTTP XMLA works cross-platform)
   b. Install Bun with oven-sh/setup-bun@v1
   c. Run bun install in the bun/ directory
   d. Run the CLI with: bun run bun/src/cli.ts run-tests ...
4. Keep the discover-models job and matrix strategy unchanged.
5. Preserve all existing PQL_* secret inputs.
```

---

*End of document.*
