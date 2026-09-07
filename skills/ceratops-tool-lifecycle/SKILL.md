---
name: ceratops-tool-lifecycle
description: Create, install, update, or inspect local Python tool versions.
---

# Ceratops Tool Lifecycle

## Goal

Guide tool development and exact local release deployment through one manager.

## Context

### Action References

- Create and package a tool: `references/create.md`
- Install the first deployment manager: `references/bootstrap.md`
- Install an exact tool release: `references/install.md`
- Update an installed tool: `references/update.md`
- Inspect tool versions: `references/versions.md`

### Inputs To Capture

- Selected action, tool identity, and exact numeric release version.
- Owning source repository and available registered releases.
- Whether Codex has reconnected to the selected manager version.

## Constraints

### Skill-Specific Rules

- Keep editable source in its owning repository and each tool's deployments
  and state in `C:\AI-Agents-Tools\<tool-id>`. Use validated global Python and
  uv with dependencies isolated in each installed version's environment.
- Keep skills and Codex registration under `.codex`; deploy this skill through
  `ceratops-skill-lifecycle` without copying tool executables into skill
  folders.
- Use the manager only from coding or development agents; omit its service
  from the restricted Forms agent's tool configuration.

### Boundaries

- Tool creation uses the ordinary development environment; the manager exposes
  only installation, update, and version inspection.
- Use exact registered releases. A selected previous version uses ordinary
  install or update. Failed candidates leave the active selection intact.
- Keep Git promotion and release publication in `ceratops-repo-lifecycle`;
  keep tool packaging and deployment in this skill.

### Workflow

1. Select the action matching the requested result; use versions for a generic
   status request and create only for an explicit development request.
2. Follow its reference and the manager's structured result. Route first-install
   absence through bootstrap only when installation is authorized.

## Done When

### Completion Gate

- The selected action passed its gate or its exact blocker is reported.
- Source, installed state, and callable MCP availability are distinguished.

### Output Contract

Report the outcome and any required reconnection, retained installations,
unresolved blocker, or unverified agent exposure.

### Example Invocation

`Use $ceratops-tool-lifecycle to inspect the manager's installed version.`
