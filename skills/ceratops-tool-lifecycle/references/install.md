# Install Action

## Goal

 Install the selected repository's declared tool version after candidate
validation.

## Workflow

1. For repository installation, use the selected checkout's `pyproject.toml`
   name and version. If it declares several tools, select by tool name.
   Run the installed manager from that checkout, or supply `--source` with
   its repository or tool directory:

   ```powershell
   C:\AI-Agents-Tools\ceratops_tool_manager\bin\ceratops_tool_manager.cmd install [--source <directory>] [--tool-name <name>]
   ```

   The command discovers declared tools, builds and registers the selected
   release, then installs it. It rejects ambiguous names before building and
   accepts no version override, artifact URL, command, or output path.
2. In an active AI-Agent-Skills checkout, install its manager source with
   `uv run --locked scripts/deploy-tool-manager.py`; this supports both first
   installation and an existing manager. Other tools use the installed CLI.
   If the manager is absent, follow bootstrap within the authorized scope.
   For an explicitly selected registered release, including a previous one,
   call MCP `install` with `tool_name` and `version`. MCP accepts no build
   source, command, script, artifact URL, or output path. Refresh missing or
   outdated source locks only through the create action's explicit packaging
   step; repository installation never rewrites the lock.
3. Treat a failed candidate as an installation failure; report its error and
   preserve the active installation. Fix the owning source or release inputs
   before another attempt when the cause is deterministic.
4. Inspect versions after success. For the manager itself, finish the current
   request and reconnect to activate the selected version on the next launch.

## Completion Gate

The installed tool name and version match the selected source metadata or the
explicitly requested registered release. Report reconnection separately.

## Output Contract

 Report installed tool name and version, required reconnection, or the exact
failure.
