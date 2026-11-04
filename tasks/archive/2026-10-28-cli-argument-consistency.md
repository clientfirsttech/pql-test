# CLI Argument Consistency Epic

**Status**: ✅ COMPLETED (2026-10-28)

**Changed during the work (2026-10-28):**
- `contract init` and `contract generate` take `-v`/`-q` but no `--format`: their result is files (or the contract and DAX on stdout), not a report. `contract lint` gained `--format json`.
- With `--format json`, stdout carries only the JSON (printed with `emit_result()`), and every other line goes to stderr automatically. Before, connection lines could precede the JSON.
- `code-coverage --format json --output FILE` keeps its old behaviour (only the file, plus a note). `--output` with `--format text` now also writes the JSON.
- A command with no extra detail to show accepts `--verbose` and ignores it.
**Goal**: The same option means the same thing on every `pql-test` command, and every old spelling keeps working as a hidden alias.

## Overview

A review of every command's parameters (2026-10-28) found that:
- no command offers `--quiet`, and `--verbose` exists on only 5 of 14 commands;
- output format is chosen three ways (`--format`, `--human`, or not at all);
- `--output` means three different things;
- "environment" means both the test environment (`--env`) and the Azure cloud (`auth login --environment`);
- `auth login` spells the credential flags differently from every other command;
- one suite is selected with `--test NAME` on two commands and a positional `NAME` on a third;
- `check-prereqs` and `auth status` have no JSON output.

**Decided 2026-10-28 (maintainer):** adopt one set of conventions across the CLI. Every old spelling keeps working as a hidden alias: it is left out of `--help`, prints a one-line deprecation warning on stderr, and behaves exactly as before.

**Conventions:**
1. **Verbosity**: every command that prints a report takes `-v/--verbose` and `-q/--quiet`. Quiet prints only the final summary line on stdout (warnings and errors still go to stderr) and never changes the exit code. Passing both is a usage error.
2. **Format**: `--format text|json` is the one way to ask for machine-readable output on every report command.
3. **`--output FILE` / `-o FILE`**: always writes the command's result to FILE, as well as the report on screen.
4. **Names**:
   - `--env` is the test environment;
   - the Azure cloud is `--cloud`;
   - credentials are `--tenant-id`, `--client-id`, and `--client-secret` everywhere.
5. **Suite selection**: `--test NAME` everywhere.

**Compatibility choices (easy to reverse):**
- `retrieve-tests` and `retrieve-test` keep JSON as their default format, because tools and agents already parse it. `--format text` is the new spelling of `--human`.
- `retrieve-test` keeps its positional `NAME` and also accepts `--test NAME`; exactly one is required.

---

## Verbosity and format

**Requirements**:
- Given any report command (`run-tests`, `retrieve-tests`, `retrieve-test`, `code-coverage`, `check-prereqs`, `auth status`, and `contract init|lint|coverage|generate|trace|run|doctor`), should accept `-v/--verbose` and `-q/--quiet`; given both, should exit 2
- Given `--quiet`, should print only the final summary line on stdout, keep warnings and errors on stderr, and keep the exit code
- Given `run-tests`, `check-prereqs`, or `auth status`, should accept `--format text|json`, with text the default
- Given `--human` on `retrieve-tests` or `retrieve-test`, should behave as `--format text` and warn that it is deprecated

---

## Output, names, and suite selection

**Requirements**:
- Given `--output FILE` on any command, should also accept `-o FILE`; given `code-coverage --output`, should write the JSON report without requiring `--format json`
- Given `auth login`, should show `--tenant-id`, `--client-id`, `--client-secret`, and `--cloud` in `--help`, and should still accept `--tenant`, `-u`/`--user`, `-p`/`--password`, and `--environment` as hidden aliases that warn
- Given `retrieve-test --test NAME`, should behave as the positional `NAME`; given both or neither, should exit 2

---

## Guard and docs

**Requirements**:
- Given a test that reads every command's parameters, should fail when a report command lacks `-v`/`-q`/`--format`, when `--output` lacks `-o`, or when a deprecated spelling appears in `--help`
- Given CONTRIBUTING, should document the conventions next to the CLI output conventions
- Given the README and every skill, should use the new spellings, and every flag in a skill should exist
