# Security policy

## Reporting a vulnerability

Please report security vulnerabilities **privately**. Don't open a public issue.

- Use GitHub's **Report a vulnerability** button on this repository's
  [Security tab](https://github.com/clientfirsttech/pql-test/security/advisories/new) (private vulnerability reporting).

Include what you found, how to reproduce it, and the pql-test version (`pql-test --version`). We aim to acknowledge a report within 5 business days, and to agree a fix and disclosure date with you.

If you find a secret (a client secret, token, or key) in this repository or its history, report it the same way. Don't use or share it.

## Supported versions

Security fixes go into the latest release. Releases up to v0.1.x (BUSL-1.1) are not updated.

pql-test still installs on Python 3.9, which reached end of life in October 2025. Fixes for some dependencies (for example `requests`, `urllib3`, and `python-dotenv`) need Python 3.10 or later, so a Python 3.9 install keeps versions with known vulnerabilities. Use Python 3.10 or later.

## How this repository guards against leaks and flaws

- **Before every commit**, pre-commit hooks run:
  - gitleaks on the staged changes;
  - a private-key check;
  - bandit on the Python code.
- **On every push and pull request**, CI repeats those checks, plus:
  - gitleaks on the full history;
  - pip-audit on the runtime dependencies.
- **Dependabot** opens pull requests for dependency and GitHub Actions updates.

See [CONTRIBUTING.md](CONTRIBUTING.md#secrets-and-security-checks) for how to install the hooks.
