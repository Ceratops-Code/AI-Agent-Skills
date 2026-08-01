# Contributing

Contributions should keep skills practical, current, and safe.

## Rules

- Keep each skill self-contained under `skills/<skill-name>/`.
- Keep source `SKILL.md` files as portable delta-only skill definitions; runtime
  `SKILL.md` files are generated during install.
- Keep `agents/openai.yaml` aligned with the skill when changing trigger
  behavior.
- Keep reusable automation-run policy in `skills/ceratops-automation-run/`
  instead of duplicating the same alert, memory, and completion rules across
  automation prompts.
- Keep live shared Ceratops rules in `skills/sections/` and assignments in
  `skills/skill-sections.json`; keep the universal `core` section focused,
  keep GH-only wording in GH-only sections, keep GH org/repo/PR/code/artifact
  contract review in
  `skills/ceratops-repo-lifecycle/references/contracts-review.md`, keep
  repository skill consistency and contract compliance in
  `skills/ceratops-skill-lifecycle/references/skills-consistency-review.md`, and
  keep skill-design standards refresh in
  `skills/ceratops-skill-lifecycle/references/skills-contract-review.md`.
- Keep live deployment operations in `deploy/deploy.yml` as structured argv
  steps. Keep `skills/ceratops-skill-lifecycle/scripts/templates/skill-sections-template.json`
  and `templates/deploy-template.yml` as reusable skeletons rather than live
  repository configuration.
- Do not add secrets, private endpoints, local machine paths, or org-internal
  procedures.
- Prefer current official docs over memory when changing GitHub, registry, or
  agent behavior, and use installed OpenAI skills only as local pattern examples
  for skill-design review.
- Add checklist items only when they are durable and broadly useful.
- Do not add boilerplate that is not relevant to these workflows.

## Validation

Run before opening a pull request:

```powershell
npm ci
python -m pip install -r requirements-dev.txt
$env:REPOSITORY_VALIDATION_RENDER_DIR = Join-Path $env:TEMP "ceratops-skills"
$env:REPOSITORY_VALIDATION_EVIDENCE_FILE = Join-Path $env:TEMP "repository-validation.log"
python scripts/validate-repository.py
```

This is the same validation entrypoint used by CI. It assumes the declared
development dependencies are installed and writes complete first-failure
diagnostics only to the selected evidence file. Full source validation checks
`deploy/deploy.yml` and both reusable templates without executing a deployment
operation.

If the change affects workflow behavior, include a short test note in the PR
explaining how the skill was exercised or reviewed.
For targeted skill work, run `python
.\skills\ceratops-skill-lifecycle\scripts\skills-consistency-source-validator.py
--mode sections` only when shared section source files or
`skills/skill-sections.json` changed. Run the touched package or repository
lifecycle helper command with `--help` from
`skills/ceratops-repo-lifecycle/scripts` when its code or related skill claims
changed.
The section mode validates section assignments and rejects stale source files
that still contain generated runtime blocks.
`skills/ceratops-skill-lifecycle/scripts/runtime/managed_runtime_builder.py`
composes runtime `SKILL.md` files and copies declared payloads during install.
