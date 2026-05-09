# Contributing

Contributions should keep skills practical, current, and safe.

## Rules

- Keep each skill self-contained under `skills/<skill-name>/`.
- Keep source `SKILL.md` files as portable delta-only skill definitions; runtime `SKILL.md` files are generated during install.
- Keep `agents/openai.yaml` aligned with the skill when changing trigger behavior.
- Keep reusable automation-run policy in `skills/ceratops-automation-run/` instead of duplicating the same alert, memory, and completion rules across automation prompts.
- Keep shared Ceratops rules in `templates/sections/` plus `templates/skill-sections.json`, keep the universal `core` section focused, keep GH-only wording in GH-only sections, and keep routine contract review in `skills/ceratops-contract-review/` instead of normal GH task skills.
- Do not add secrets, private endpoints, local machine paths, or org-internal procedures.
- Prefer current official docs over memory when changing GitHub, registry, or agent behavior.
- Add checklist items only when they are durable and broadly useful.
- Do not add boilerplate that is not relevant to these workflows.

## Validation

Run before opening a pull request:

```powershell
$runtimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) "ceratops-runtime-skills"
powershell -ExecutionPolicy Bypass -File .\scripts\install-skills.ps1 -RuntimeRoot $runtimeRoot -Validate full
```

If the change affects workflow behavior, include a short test note in the PR explaining how the skill was exercised or reviewed.
Run `powershell -ExecutionPolicy Bypass -File .\scripts\install-skills.ps1 -SkipInstall -Validate sections` only when shared section source files or `templates/skill-sections.json` changed. Run `python .\scripts\validation\github-validate-pr-readiness-contract.py --help` only when PR-readiness validator code or related skill claims changed.
The section mode validates section assignments and rejects stale source files that still contain generated runtime blocks. `scripts/render-runtime-skills.py` composes runtime `SKILL.md` files and copies declared payloads during install.
