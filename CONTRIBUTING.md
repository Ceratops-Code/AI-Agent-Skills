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
- Keep shared Ceratops rules in `templates/sections/` plus
  `templates/skill-sections.json`, keep the universal `core` section focused,
  keep GH-only wording in GH-only sections, keep GH org/repo/PR/code/artifact
  contract review in
  `skills/ceratops-gh-repo-lifecycle/references/contracts-review.md`, and keep
  skill consistency or skill-design contract upkeep in
  `skills/ceratops-skill-lifecycle/references/skills-consistency-and-contract-review.md`.
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
npm run lint:markdown
python -m pip install -r requirements-dev.txt
python -m yamllint .
python -m mypy
```

```powershell
python .\skills\ceratops-skill-lifecycle\scripts\validation\validate-skills-consistency.py --mode full
```

If the change affects workflow behavior, include a short test note in the PR
explaining how the skill was exercised or reviewed.
Run `python
.\skills\ceratops-skill-lifecycle\scripts\validation\validate-skills-consistency.py
--mode sections` only when shared section source files or
`templates/skill-sections.json` changed. Run `python
.\skills\ceratops-gh-repo-lifecycle\scripts\github-validate-pr-readiness-contract.py
--help` only when PR-readiness validator code or related skill claims changed.
The section mode validates section assignments and rejects stale source files
that still contain generated runtime blocks.
`skills/ceratops-skill-lifecycle/scripts/runtime/render-runtime-skills.py`
composes runtime `SKILL.md` files and copies declared payloads during install.
