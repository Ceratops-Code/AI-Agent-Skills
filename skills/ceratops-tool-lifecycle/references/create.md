# Create Action

## Goal

Create a tool's editable source and a reproducible release in its owning repo.

## Workflow

1. Establish the requested behavior and source owner. Use the ordinary coding
   environment and maintained packaging dependencies. Keep repository creation
   or Git release work in `ceratops-repo-lifecycle` when required.
2. Build a Python wheel project with an exact numeric `major.minor.patch`
   version and pinned build backend. Add the `tool.json` identity contract
   documented in the manager's source README. The supported runtime is global
   Windows x64 CPython 3.14; other runtime formats require manager development.
3. Implement the module's fixed `--deployment-check` readiness protocol. Its
   JSON must report exact tool identity and installed package version with
   `ready: true`; check required dependencies without modifying user data.
4. Add focused behavioral tests and usage documentation in the owning repo.
   Validate package readiness and failure behavior before registering a release.
5. From the active AI-Agent-Skills source checkout, run
   `python scripts/package-tool-release.py --source <tool-source> --lock` to
   record dependency artifacts, then review the lock and run the same command
   without `--lock` to build and register the exact release. Source maintenance
   runs from `scripts/`; these commands are not manager or MCP operations.
6. Hand authorized deployment to this skill's install action. Use a new version
   when artifact contents change; a published identity/version is immutable.

## Completion Gate

Source, manifest, packaging, focused tests, and documentation agree; the
registered artifact is exact. Report an installation separately when requested.

## Output Contract

Report the source owner, release version, deployment outcome, and blockers.
