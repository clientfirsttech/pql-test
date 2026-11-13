---
name: check-prereqs
description: Verify that all required packages and runtime dependencies for pql-test are available (Python >= 3.10, pyadomd, msal, psutil).
version: 0.2.1
---

Run `pql-test check-prereqs` to verify that all required packages and tools are installed before attempting to run DAX tests.

The command checks for:
- Python >= 3.10
- pyadomd (ADOMD.NET XMLA client, required for running DAX queries)
- msal (Azure AD / service-principal authentication)
- psutil (local Power BI Desktop detection, optional but required for `local/<model_name>` discovery)

If any prerequisite is missing, the command exits with code 1 and prints instructions for installing the missing package.

Usage:
```
pql-test check-prereqs
```
