# .env From The Working Directory Epic

**Status**: ✅ COMPLETED (2026-11-17)
**Goal**: The CLI loads the `.env` of the project it runs in, as the README says, wherever pql-test is installed

## Overview

The README says the CLI loads `.env` "by walking up from the current working directory". `cli.py` calls `load_dotenv()` with no path, and python-dotenv then searches upward from the calling file, `pql_test/cli.py`, not from the working directory. In this repository's editable install that finds `python/.env` from any folder; in a pip install it searches `site-packages` and never finds the user's project `.env`, so credentials a user put there are silently ignored.

---

## Load .env From The Working Directory

**Requirements**:
- Given a `.env` in the folder the CLI runs in, should load its variables
- Given a `.env` in a parent of the folder the CLI runs in, should load its variables
- Given a variable already set in the environment, should keep the environment's value over the `.env` value
- Given `PQL_TEST_HERMETIC` set, should load no `.env`

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

- **Tests**: `cd python && pytest` passes
- **Documentation**: the README's `.env` section matches the behavior
