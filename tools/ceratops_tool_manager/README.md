# Ceratops Tool Manager

One deterministic engine installs exact local Python tool releases, updates
installed tools, and inspects versions. CLI and stdio MCP use that same engine.
The manager also owns explicit source packaging through its CLI. It makes no
model/API calls and has no UI.

## Layout and supported runtime

Manager source files live directly in `tools/ceratops_tool_manager/`, beside
`pyproject.toml`. Hatch maps these modules into the installed Python package;
the standalone launcher stays outside the wheel.

Editable source belongs in the tool's owning repository. Each tool owns a
separate directory under `C:\AI-Agents-Tools`, including its packages,
environments, version selection, registry, cache, and locks. The manager's
directory is `C:\AI-Agents-Tools\ceratops_tool_manager`. Skills and Codex
configuration stay in `.codex`; the skill installer owns skill deployment.

```text
C:\AI-Agents-Tools\<tool-id>\
  bin\                              stable launchers (manager)
  artifacts\<version>\<manifest-sha256>\
  versions\<version>\<instance>\environment\
  current.json                      selected complete installation
  registry.json                     exact version-to-manifest mapping
  staging\                          packaging scratch, removed on return
  cache\                            this tool's package/build cache
  locks\                            this tool's kernel-released locks
```

Deployment uses existing global Windows x64 CPython 3.14.x and uv 0.12.10 or
newer 0.12.x. Both are validated outside the tool store before creating an
installation; the manager never downloads its own Python or uv. Each installed
version has a separate virtual environment for dependencies. Global Python
must remain available and compatible while these environments are used.

`pylock.toml` records exact dependency versions and artifact hashes. Wheels
are installed offline with uv's hash enforcement, followed by dependency and
package readiness checks. A manager update changes its wheel dependencies;
global Python and uv remain independently maintained prerequisites.

## First installation and use

From an active AI-Agent-Skills source checkout:

```powershell
python scripts/deploy-tool-manager.py
C:\AI-Agents-Tools\ceratops_tool_manager\bin\ceratops_tool_manager.cmd versions
```

The deployment script is a first-install development command. It validates global
prerequisites, builds and registers the source release, prepares the launchers,
and calls the same packaging and deployment code used after installation. It
provisions hash-locked Python libraries in temporary storage and removes that
storage on success or failure; no libraries need to be installed globally.
It changes no Codex
configuration. An incompatible or missing prerequisite fails before deployment
writes installation files.

| CLI command | MCP tool | Inputs |
| --- | --- | --- |
| `package --source <directory> [--lock]` | Not exposed | Reviewed tool source; optional lock refresh |
| `install <tool-id> <version>` | `install` | `tool_id`, `version` |
| `update <tool-id> <version>` | `update` | `tool_id`, `version` |
| `versions [tool-id]` | `versions` | optional `tool_id` |

Omitting a version-inspection identity selects `ceratops_tool_manager`.
Update requires an existing installation. Both modifying operations accept an
explicitly selected previous version through the same installation mechanism.
There is no separate rollback operation, automatic rollback subsystem,
create-tool endpoint, shell/script input, or installation/output path input.
The source directory accepted by `package` is a reviewed build input, not an
installation destination. Packaging never runs implicitly during `install`.

MCP returns structured result data and a compact equivalent JSON text block.
CLI writes JSON to stdout and returns exit code 2 with a diagnostic on stderr
for a failed operation. `installed_version` is the selected next-launch
version. `running_version` is the responding manager process version; it is
null for other tools because the manager does not supervise their processes.
Version inspection also returns available releases and the selected manifest
digest. `reconnection_required` reports a manager version difference.

## Development and release contracts

A source project contains normal `pyproject.toml` wheel packaging and a
`tool.json` object:

```json
{
  "schema": 1,
  "tool_id": "example_tool",
  "distribution": "example_tool",
  "module": "example_tool"
}
```

`tool_id` and distribution names use lowercase underscore-separated identifiers,
starting with a letter. Release versions are exact numeric `major.minor.patch`
values. Module names use lowercase Python import components. Windows device
names, separators, traversal, malformed identities, and unknown fields fail
validation. The source distribution and built wheel version must agree.

Use a pinned maintained build backend. The module's fixed readiness invocation
is `python -I -B -m <module> --deployment-check`. It must return exactly:

```json
{"tool_id": "example_tool", "version": "1.0.0", "ready": true}
```

Readiness checks dependencies and necessary local prerequisites without
modifying user data. Create and test tools in their owning development
repositories; tool creation never runs through this manager.

After the manager's first installation, use its public launcher from any
directory; an AI-Agent-Skills checkout is not required:

```powershell
C:\AI-Agents-Tools\ceratops_tool_manager\bin\ceratops_tool_manager.cmd package --source <tool-source> --lock
C:\AI-Agents-Tools\ceratops_tool_manager\bin\ceratops_tool_manager.cmd package --source <tool-source>
```

The first command writes a standard `pylock.toml` for review and commit. The
second builds the wheel, fetches compatible hash-locked PyPI dependency wheels,
and registers one immutable local artifact record without installing or
activating it. Both commands are implemented inside the installed manager.
Packaging executes reviewed build code and downloads dependencies; it is an
explicit CLI capability, not an MCP operation or public-repository upload.
The standalone installer reuses this implementation from source only for the
first manager installation. Manager self-updates use the installed CLI to
package a new source version, followed by ordinary `install` and reconnection.

The release manifest is a closed JSON object containing `schema`, `tool_id`,
`version`, `distribution`, `module`, and `wheels`. Each wheel has exactly a
`filename` and `sha256`. The engine validates every field, digest, wheel
archive, and the tool's distribution metadata before execution. All artifact
paths are derived from validated identities. Each tool's registry has only
`schema`, its matching `tool_id`, and `versions`; its mapping is
`versions[version] = manifest_sha256`.
An existing identity/version cannot be reassigned to different artifact bytes.
Use a new version for changed releases.

## Activation and self-update

The engine creates a unique candidate directory at its final immutable path,
installs its environment, checks dependencies, and runs readiness. Virtual
environments are never moved after creation. Only then does an atomic JSON
replacement of that tool's `current.json` select the candidate. This file
records the exact version and installation folder to launch. A failed candidate
is removed and the prior selection stays
intact. Per-tool operating-system locks serialize writes
and are released when the owning process exits, including a crash.

Self-update uses this same sequence. The current process completes its request
from its existing directory; its files are never overwritten. The stable
launcher reads its own `current.json` at the next launch, so a new CLI
process or
MCP reconnection uses the selected version. Already running versions continue
to work. Completed inactive environments are intentionally retained for those
processes; no automated deletion or process-supervision subsystem is included.
Abrupt process termination can leave an unselected candidate for explicit
maintenance; it cannot activate an incomplete candidate.

## Codex registration and Forms boundary

The repository's `.codex/config.toml` registers only this service for trusted
development checkouts. It uses global `python`, the manager folder's installed
launcher, and `--mcp`, with the exact
three-tool allowlist. It does not modify the user
global configuration or another project's configuration. Registration alone
does not prove the current Codex task has loaded the connection. Verify callable
tools in that task separately; this setup does not restart the desktop app.

Keep the restricted Forms agent in its separate restricted configuration,
without this service or shell/development capabilities. MCP stdio inherits
the launching host's authority and has no independent agent-role identity.
Do not launch Forms inside a development checkout that grants deployment.
A shared/global registration requires a verified Forms exclusion first.
The registry and reviewed package code are trusted development inputs;
readiness execution is not a sandbox for untrusted wheels.

## Validation

`tests/tool_manager` covers the shared engine, CLI, actual SDK dispatch,
first-install and packaging boundaries, checkout-independent packaging,
failures, locks, path rejection, and
self-update state. The normal repository validator selects it through
`tests/test-impact.json`. Development dependencies are in
`requirements-dev.txt`.

For explicit acceptance against a bootstrapped local installation, register
two compatible manager releases, select the earlier release, then run:

```powershell
python scripts/check-tool-manager.py --scratch <task-temp-root> --self-update-version <version>
```

This checks real manager installation/update/previous-version selection and
rejection of an unregistered release. It keeps one MCP connection alive during
self-update, verifies the old version can still answer, and verifies the new
version after reconnection. The requested manager version is the final installed
state. The check installs no sample tool. Inactive manager environments remain
available for running processes. Unit tests create temporary wheel inputs and
cover candidate failures without installing a test project on the machine.
Evidence is written as `tool_deployment_check.json` in the supplied scratch
directory. This explicit acceptance command is not run by ordinary CI.

Packaging uses [uv](https://docs.astral.sh/uv/pip/compile/) and the
[official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).
Codex's [MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
defines project configuration and tool allowlists.
