# Install Action

## Goal

Activate one exact registered release after candidate validation.

## Workflow

1. Capture tool identity and exact version. Use versions to inspect registered
   releases when needed. An unknown release requires source packaging through
   the create workflow's packaging step in the owning development context.
2. Call MCP `install` with `tool_id` and `version`, or run:

   ```powershell
   C:\AI-Agents-Tools\ceratops-tool-manager\bin\ceratops-tool-manager.cmd install <tool-id> <version>
   ```

   The manager accepts no command, script, artifact URL, or output path input.
3. Treat a failed candidate as an installation failure; report its error and
   preserve the active installation. Fix the owning source or release inputs
   before another attempt when the cause is deterministic.
4. Inspect versions after success. For the manager itself, finish the current
   request and reconnect to activate the selected version on the next launch.

## Completion Gate

The returned installed version is the exact requested release. A selected
previous version follows this same installation path.

## Output Contract

Report installed version, required reconnection, or the exact failure.
