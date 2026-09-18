# Install Action

## Goal

 Install the selected repository's declared tool version after candidate
validation.

## SDLC execution

`sdlc/sdlc.yml` routes tool installation to this action; the manager itself
reads tool `pyproject.toml` and `tool.json`, not SDLC. Earlier SDLC bindings use
`--source` to build a tool directly. SDLC v4 returns the selected tool and its
package prerequisite records to this action. For a package-backed tool, run the
package's declared build action and require its wheel validation to pass. Select
exactly one wheel matching its artifact directory and filename pattern. The tool
source must declare that package at the wheel's exact version. Pass the wheel
and the package's `pylock.toml` to the manager; do not pass package source as
tool source. A tool without a package prerequisite keeps the source-build path.

## Workflow

1. For repository installation, use the selected checkout's `pyproject.toml`
   name and version. If it declares several tools, select by tool name.
   Run the installed manager from that checkout, or supply `--source` with
   its repository or tool directory. For a package-backed tool, supply its
   already validated wheel and package lock as well:

   ```powershell
   C:\AI-Agents-Tools\ceratops_tool_manager\bin\ceratops_tool_manager.cmd install --source <tool-directory> [--tool-name <name>] --package-wheel <package-wheel.whl> --package-lock <package-pylock.toml>
   ```

   Omit both package flags for a source-built tool without a package
   prerequisite. The manager builds only the selected tool source, registers
   the tool wheel with the supplied package wheel and locked third-party
   wheels, then installs that exact set. It rejects ambiguous names before
   building and accepts no version override, artifact URL, or output path.
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
