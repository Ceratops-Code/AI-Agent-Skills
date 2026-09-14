# Ceratops Tool Manager

One deterministic engine installs exact local Python tool releases, updates
installed tools, and inspects versions. CLI and stdio MCP use that same engine.
Repository installation selects a tool and reads its name and version from
 `pyproject.toml`, then packages and installs that release through the CLI. It
makes no
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
C:\AI-Agents-Tools\<tool-name>\
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

## Source installation and use

From an active AI-Agent-Skills source checkout:

```powershell
uv run --locked scripts/deploy-tool-manager.py
C:\AI-Agents-Tools\ceratops_tool_manager\bin\ceratops_tool_manager.cmd versions
```

The deployment script installs the source checkout's declared manager version,
including when a manager is already installed. It validates global
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
| `install [--source <directory>] [--tool-name <name>]` | Not exposed | Repository or tool source; defaults to the current directory |
| Not exposed | `install` | `tool_name`, `version` for an exact registered release |
| `update <tool-name> <version>` | `update` | `tool_name`, `version` |
| `versions [tool-name]` | `versions` | optional `tool_name` |

Omitting a version-inspection name selects `ceratops_tool_manager`.
Update requires an existing installation. MCP install and CLI/MCP update accept
an explicitly selected previous registered version through the same engine.
There is no separate rollback operation, automatic rollback subsystem,
create-tool endpoint, shell/script input, or installation/output path input.
Source directories accepted by CLI install and package are reviewed build
inputs. Install accepts no version override: it packages the selected source
release and activates exactly that name and version. A direct tool directory
needs no Git. Otherwise Git enumerates tracked and non-ignored untracked
`tool.json` declarations below the selected directory. Multiple tools require
`--tool-name`; duplicate names, absent matches, and failed queries stop before
building. Ignored environments are excluded.

For example, from a repository root:

```powershell
C:\AI-Agents-Tools\ceratops_tool_manager\bin\ceratops_tool_manager.cmd install --tool-name example_tool
```

Public CLI and MCP results identify the tool with `tool_name`. MCP returns
structured result data and a compact equivalent JSON text block.
CLI writes JSON to stdout and returns exit code 2 with a diagnostic on stderr
for a failed operation. `installed_version` is the selected next-launch
version. `running_version` is the responding manager process version; it is
null for other tools because the manager does not supervise their processes.
Version inspection also returns available releases and the selected manifest
digest. `reconnection_required` reports a manager version difference.

## Development and release contracts

A source project declares `[project].name` and a static `[project].version`
in `pyproject.toml`, plus normal wheel packaging. Its `tool.json` declares only
the readiness module:

```json
{
  "schema": 2,
  "module": "example_tool"
}
```

The project name supplies both the tool and distribution names. It starts with a
lowercase
letter, with single hyphens or underscores between alphanumeric segments.
Tool identities stay exact; distribution matching uses package-name
normalization. Release versions are exact numeric `major.minor.patch`
values. Module names use lowercase Python import components. Windows device
names, separators, traversal, malformed identities, and unknown fields fail
 validation. Source metadata must remain stable during the build, and its name
and version
must agree with the built wheel. Metadata and locks must stay inside the tool
 directory. Installation requires the existing `pylock.toml` and never refreshes
it.

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
The source installer uses this same implementation for first installation and
manager updates, including upgrades from an older CLI. Other repository tools
use CLI install. Reconnect after selecting a new manager version.

Persistent records and the fixed readiness response retain the schema-1
`tool_id` field required by existing launchers and installed tools. Its value
is the project name; it is not a separate identifier or source declaration.
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
 source selection, installation and packaging boundaries, checkout-independent
commands,
failures, locks, path rejection, and
 self-update state. The repository test runner selects it through
`tests/test-impact.json`. Development dependencies are declared in
`scripts/pyproject.toml` and resolved in `scripts/uv.lock`.

Unit tests use temporary wheel inputs and simulated deployment commands; they
do not install test versions of the manager. Real self-update and reconnection
are verified only during an explicitly requested manager update. Repository
validation does not change the installed manager or switch versions for tests.

Packaging uses [uv](https://docs.astral.sh/uv/pip/compile/) and the
[official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).
 Codex's
[MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
defines project configuration and tool allowlists.
