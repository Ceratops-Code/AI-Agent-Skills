# Create Action

## Goal

Create a tool's editable source and a reproducible release in its owning repo.

## Workflow

1. Establish the requested behavior and source owner. Use the ordinary coding
   environment and maintained packaging dependencies. Keep repository creation
   or Git release work in `ceratops-repo-lifecycle` when required.
2. Declare the tool name and exact numeric `major.minor.patch` version in
   `pyproject.toml` with a pinned wheel build backend. Add the schema-2
   `tool.json` readiness-module contract documented in the manager README;
   it must not duplicate the project name or version. The supported runtime is
   global Windows x64 CPython 3.14; other formats require manager development.
3. Implement the module's fixed `--deployment-check` readiness protocol. Its
   JSON must report exact tool identity and installed package version with
   `ready: true`; check required dependencies without modifying user data.
4. Add focused behavioral tests and usage documentation in the owning repo.
   Validate package readiness and failure behavior before registering a release.
5. Use the installed manager's public CLI:

   ```powershell
   C:\AI-Agents-Tools\ceratops_tool_manager\bin\ceratops_tool_manager.cmd package --source <tool-source> --lock
   C:\AI-Agents-Tools\ceratops_tool_manager\bin\ceratops_tool_manager.cmd package --source <tool-source>
   ```

   Review `pylock.toml` between these commands. The first records locked
   dependencies; the second builds and registers that exact package without
   activating it. An AI-Agent-Skills checkout is not required. If the manager
   is absent, use bootstrap only when first installation is authorized.
6. Hand authorized deployment to this skill's install action. Use a new version
   when artifact contents change; a published identity/version is immutable.

## Completion Gate

Source, manifest, packaging, focused tests, and documentation agree; the
registered artifact is exact. Report an installation separately when requested.

## Output Contract

Report the source owner, release version, deployment outcome, and blockers.
