# Versions Action

## Goal

Inspect exact installed and registered versions without executing tool code.

## Workflow

1. Call MCP `versions` with optional `tool_id`, or run:

   ```powershell
   C:\AI-Agents-Tools\ceratops-tool-manager\bin\ceratops-tool-manager.cmd versions [tool-id]
   ```

   Omitting the identity inspects the deployment manager.
2. Interpret `installed_version` as the version selected for the next launch,
   `available_versions` as registered releases, and `running_version` as the
   responding manager process version. Other tools have null running versions;
   the manager does not supervise their processes.
3. Report `reconnection_required` when true. Registration and callable Codex
   availability require direct connection evidence, separate from version data.

## Completion Gate

The response describes only checked state and requests no unneeded mutation.

## Output Contract

Report the requested versions and any required reconnection or corrupt state.
