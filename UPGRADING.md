# Upgrading the AIDD Framework

This project uses the [AIDD Framework](https://github.com/paralleldrive/aidd) for AI-Driven Development. The framework files in `ai/`, `.cursor/`, and `AGENTS.md` come from the upstream project and can be updated to get the latest skills, commands, and best practices.

## Quick Upgrade

### Using npx (Recommended)

The simplest way to upgrade is using the AIDD CLI:

```bash
# Upgrade AIDD framework files in the current project
npx aidd .
```

This will update:
- `ai/` — Commands, skills, and scaffolds
- `.cursor/` — Cursor editor integration
- `AGENTS.md` — Agent guidelines

It will **not** overwrite:
- `aidd-custom/` — Your project-specific customizations
- `vision.md` — Your project vision
- `plan.md` — Your development plan
- `.github/agents/` — Your GitHub Copilot agent definitions
- `.github/copilot-instructions.md` — Your Copilot workspace instructions

### Using the Upgrade Script

A convenience script is provided for automated upgrades:

```bash
./scripts/aidd-upgrade.sh
```

### Manual Upgrade

If you prefer manual control, you can selectively copy files from the upstream repository:

```bash
# Clone or download the latest AIDD framework
git clone --depth 1 https://github.com/paralleldrive/aidd.git /tmp/aidd-latest

# Update framework files (preserves your customizations)
cp -r /tmp/aidd-latest/ai/* ai/
cp /tmp/aidd-latest/AGENTS.md AGENTS.md

# Update Cursor integration if using Cursor editor
# Note: .cursor is typically a symlink to ai/
# On Windows, you may need administrator privileges or use a directory junction instead:
#   mklink /J .cursor ai   (Windows cmd)
ln -sf ai .cursor

# Clean up
rm -rf /tmp/aidd-latest
```

## What Gets Updated

| Directory/File | Source | Updated by `npx aidd`? |
|---|---|---|
| `ai/commands/` | Upstream AIDD | ✅ Yes |
| `ai/skills/` | Upstream AIDD | ✅ Yes |
| `ai/scaffolds/` | Upstream AIDD | ✅ Yes |
| `AGENTS.md` | Upstream AIDD | ✅ Yes |
| `.cursor/` | Symlink to `ai/` | ✅ Yes |
| `aidd-custom/` | **Your project** | ❌ No (preserved) |
| `vision.md` | **Your project** | ❌ No (preserved) |
| `plan.md` | **Your project** | ❌ No (preserved) |
| `.github/agents/` | **Your project** | ❌ No (preserved) |
| `.github/copilot-instructions.md` | **Your project** | ❌ No (preserved) |
| `.vscode/` | **Your project** | ❌ No (preserved) |
| `COPILOT-QUICKSTART.md` | **Your project** | ❌ No (preserved) |

## GitHub Copilot Compatibility

The AIDD framework is fully compatible with GitHub Copilot. After upgrading:

1. **Agent definition** (`.github/agents/aidd.agent.md`) — Not modified by upgrades. Your Copilot agent configuration is preserved.
2. **Copilot instructions** (`.github/copilot-instructions.md`) — Not modified. Your workspace instructions are preserved.
3. **VS Code settings** (`.vscode/settings.json`) — Not modified. Your Copilot configuration is preserved.
4. **Skills and commands** — Updated from upstream. The `@aidd` agent in Copilot will use the latest skills.

## Checking Your AIDD Version

The upstream AIDD framework uses npm versioning:

```bash
# Check the latest available version
npm view aidd version

# See what version was used to initialize your project
# (if recorded in package.json)
cat package.json | grep aidd
```

## After Upgrading

1. **Review changes**: Check `git diff` to see what was updated
2. **Test the agent**: Open Copilot Chat and run `@aidd help` to verify
3. **Check custom skills**: Ensure your `aidd-custom/` skills still work with the new framework
4. **Commit**: Commit the updated framework files

```bash
git add ai/ .cursor/ AGENTS.md
git commit -m "chore: upgrade AIDD framework to latest"
```

## Troubleshooting

### Skills not loading after upgrade?

1. Reload VS Code: `Ctrl+Shift+P` → "Developer: Reload Window"
2. Verify skill files exist: `ls ai/skills/*/SKILL.md`
3. Check `index.md` files are regenerated (they are auto-generated from frontmatter)

### Custom skills conflicting with upstream?

If your `aidd-custom/` skills conflict with updated upstream skills:
1. Check the upstream changelog for breaking changes
2. Update your custom skill files to match the new interfaces
3. Custom skills in `aidd-custom/` always take priority over upstream skills

### Agent not responding to new commands?

New commands added in upstream require the agent definition to reference them. Check `.github/agents/aidd.agent.md` and update if needed.
