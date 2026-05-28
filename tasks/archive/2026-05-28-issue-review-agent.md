# Issue Review Agent Workflow Epic

**Status**: ✅ COMPLETED (2026-05-28)
**Goal**: Enable automated issue analysis and PR generation via GitHub Agentic Workflows

## Overview

DevOps engineers and repository maintainers need automated assistance in responding to issues with code changes. This workflow uses GitHub's Copilot engine to analyze issues, generate targeted code fixes, and automatically create pull requests. The agentic workflow format separates pre-computation (bash steps) from agent instructions, ensuring efficient and constrained AI-driven code changes.

---

## Create Agentic Workflow Structure

Create the GitHub Agentic Workflow file with proper engine configuration and metadata.

**Requirements**:
- Given workflow needs AI capabilities, should specify engine as copilot
- Given workflow creates PRs, should declare safe-outputs for create-pull-request
- Given workflow runs on issues, should trigger on issues opened and workflow_dispatch with issue_number input
- Given workflow modifies code, should configure appropriate permissions and checkout settings

---

## Add Pre-Execution Issue Analysis Steps

Implement bash steps that fetch and prepare issue data before agent execution.

**Requirements**:
- Given an issue number from trigger or input, should fetch issue via GitHub API
- Given issue is fetched, should extract title, body, labels, and metadata
- Given issue data is extracted, should save to /tmp/gh-aw/agent/ directory for agent consumption
- Given any step fails, should exit gracefully with error status

---

## Write Agent Instructions

Define natural language instructions that tell the Copilot agent how to process issue data and generate fixes.

**Requirements**:
- Given pre-computed issue data exists, should read from /tmp/gh-aw/agent/ directory
- Given issue describes a bug or feature, should identify relevant files and components
- Given target files are identified, should generate surgical code changes using edit tool
- Given changes are applied, should verify with git diff and create PR if changes exist

---

## Configure Tools and Constraints

Restrict agent to safe tool usage following the agentic workflow security model.

**Requirements**:
- Given agent needs file modification, should allow edit tool for all paths
- Given agent needs inspection, should allow bash commands for cat, echo, find, git diff only
- Given agent should not execute arbitrary code, should not allow unrestricted bash access
- Given workflow uses external analysis tools, should configure any MCP servers needed

---

## Add Workflow Documentation

Document the agentic workflow setup and usage patterns in repository.

**Requirements**:
- Given workflow is implemented, should add .github/workflows/README.md section for agentic workflows
- Given workflow uses pre-execution steps, should document the two-phase execution model
- Given workflow can be manually triggered, should document workflow_dispatch parameters
- Given workflow creates PRs automatically, should explain review and approval process
