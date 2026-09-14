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
- Install a repository tool or registered release: `references/install.md`
- Update an installed tool: `references/update.md`
- Inspect tool versions: `references/versions.md`

### Inputs To Capture

- Selected action and source checkout; tool name when selection is ambiguous.
- Exact numeric version only for explicitly selected registered releases.
- Owning source repository and available registered releases.
- Whether Codex has reconnected to the selected manager version.

## Constraints

### Skill-Specific Rules

- Keep editable source in its owning repository and each tool's deployments
  and state in `C:\AI-Agents-Tools\<tool-name>`. Use validated global Python and
  uv with dependencies isolated in each installed version's environment.
- Keep skills and Codex registration under `.codex`; deploy this skill through
  `ceratops-skill-lifecycle` without copying tool executables into skill
  folders.
- Use the manager only from coding or development agents; omit its service
  from the restricted Forms agent's tool configuration.

### Boundaries

- Create source in its owning repository. Repository installation uses the
  manager CLI to select, package, and install its declared name and version.
  MCP accepts only registered-release installation, update, and inspection.
- Read repository tool names and versions from `pyproject.toml`; never choose
  a separate version for repository installation. Explicit registered-release
  requests use MCP install or CLI/MCP update. Failed candidates leave the
  active selection intact.
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
