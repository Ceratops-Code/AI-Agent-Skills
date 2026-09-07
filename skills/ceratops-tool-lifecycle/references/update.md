# Update Action

## Goal

Select an exact release for an already installed tool.

## Workflow

1. Capture the installed tool and selected exact release. If absent, use the
   install action. If the release is unregistered, package its reviewed source
   through the create workflow before updating.
2. Call MCP `update` with `tool_id` and `version`, or run:

   ```powershell
   C:\AI-Agents-Tools\ceratops-tool-manager\bin\ceratops-tool-manager.cmd update <tool-id> <version>
   ```

   Explicitly selecting a previous release uses this same operation.
3. On failure, report the error and leave the active selection intact. On
   success, inspect versions. Existing process files remain available in their
   immutable installation directories; deployment does not terminate processes.
4. For a self-update, complete the current request normally and reconnect for
   the selected manager to run. Report both versions while they differ.

## Completion Gate

The selected installed version matches the request; any running manager
difference and retained process installations are accurately reported.

## Output Contract

Report installed version, running manager difference, and reconnection needs.
