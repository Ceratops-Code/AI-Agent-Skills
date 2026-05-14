# Skill Design Non-Deterministic Checks

This file complements `skill-deterministic-contract.json`. The JSON contains machine-checkable skill source, metadata, shared-section, runtime-payload, public-doc, portability, and contract-reference-alignment checks. This file contains skill-design quality checks that need reviewer judgment.

## Good Skill Definition

A good skill is a scoped workflow contract that triggers only for the task class it can handle, captures the inputs needed to act, routes to the smallest relevant references or helper commands, keeps deterministic behavior in scripts or executable helpers when practical, states safety and blocker boundaries, defines evidence and completion gates, and tells the agent exactly what to report without turning the skill into a broad best-practices essay.

## Common Skill Content Roles

Follow common skill practice as role-based structure, not fixed upstream or Ceratops H2 names. Ceratops skills may keep the local `Goal`, `Context`, `Constraints`, and `Done When` H2 layout. The deterministic contract still requires `Boundaries` and `Output Contract` subsections as local safety and closure anchors.

- `ND.skill.role-based-structure` requires reviews to confirm the content covers these roles directly in the skill body, in generated shared sections, or through clearly routed helper, `references/`, or `assets/` files:
  - triggering metadata: frontmatter description and `agents/openai.yaml` trigger only the intended task class.
  - scope and applicability: the skill names the workflow surface, required inputs, in-scope work, and out-of-scope work.
  - operating rules and constraints: the skill states safe defaults, blockers, risky-action boundaries, and source-of-truth precedence.
  - ordered workflow: execution steps are dependency-ordered, evidence-gated, and route failures before further mutation.
  - tool, script, and reference routing: deterministic or repeatable behavior is delegated to helpers when practical, and references are loaded progressively.
  - examples, templates, and gotchas: concrete examples, output templates, or non-obvious edge cases are included only when they reduce likely execution mistakes.
  - validation and completion criteria: the skill names the checks, evidence, final state, and retained risks required before claiming completion.
  - final output expectations: the skill says what to report, what to omit, and which blockers or retained state must remain visible.

## Evidence Bundle

Use local evidence first:

- target source skill: `skills/<skill-name>/SKILL.md`
- skill metadata: `skills/<skill-name>/agents/openai.yaml`
- shared-section assignments and runtime payloads: `templates/skill-sections.json`
- deterministic skill contract: `contracts/skills/skill-deterministic-contract.json`
- skill-standard source registry and example references: `contracts/source-docs.json`
- installed OpenAI skill examples, when present: `$CODEX_HOME/plugins/cache/openai-primary-runtime/*/*/skills/*/SKILL.md` and `$CODEX_HOME/plugins/cache/openai-curated/*/*/skills/*/SKILL.md`

Use upstream skill-standard sources listed in `contracts/source-docs.json` as standards evidence for skill format, folder structure, metadata, progressive disclosure, body content roles, and resource roles. Use installed OpenAI skills as pattern examples only. Compare at most 2-3 examples that match the current skill type or standards question, and record which specific design pattern each example informed.

Useful installed examples:

- `documents`: strict artifact rendering and visual QA gates for `.docx` work.
- `presentations`: request classification, audience/content gates, reference-loading limits, and artifact-specific QA.
- `spreadsheets`: tool contract, error recovery, formula/render verification, and concise final-output discipline.
- `github:yeet`: explicit publish scope, credential prerequisites, branch/commit/PR sequencing, and write-safety boundaries.

## Review Result Values

- `pass`: reviewer found the intent satisfied and recorded evidence.
- `fail`: reviewer found a concrete mismatch.
- `approved_drift`: mismatch is allowed by the current skill's documented scope or an active higher-precedence rule.
- `blocked`: review needs unavailable local skill examples, missing product decision, or unclear source-of-truth ownership.
- `not_applicable`: the skill type or requested scope does not require this check.

## Non-Deterministic Check Definitions

| ID | Applies when | Review required |
| --- | --- | --- |
| `ND.skill.trigger-fit` | Every skill source or metadata review | Confirm the frontmatter description, plugin/skill description, and default prompt trigger only the intended task class and do not make ordinary adjacent tasks overtrigger the skill. |
| `ND.skill.role-based-structure` | Every skill source review | Confirm the skill satisfies the `Common Skill Content Roles` checklist. |
| `ND.skill.scope-boundary` | Every skill source review | Confirm the skill's scope, inputs, rules, boundaries, completion gates, and output contract agree on one workflow surface and do not mix unrelated owners, artifacts, or lifecycle phases. |
| `ND.skill.workflow-contract` | Skills that tell the agent how to execute work | Confirm workflow steps are ordered by dependency, name the evidence needed for each decision, route blockers explicitly, and avoid ceremonial steps that do not change action or verification. |
| `ND.skill.deterministic-placement` | Skills with commands, scripts, generated artifacts, validators, or repeatable cleanup | Confirm deterministic behavior lives in scripts/helpers or exact command contracts when practical, and prompt text retains only high-level intent, routing, exceptions, and result-handling obligations. |
| `ND.skill.reference-discipline` | Skills that reference docs, examples, templates, assets, or installed OpenAI skills | Confirm references are loaded progressively, only the relevant files are named, variant-specific patterns, examples, configuration, and deep procedural detail live in skill-local `references/<topic>.md` files with clear `SKILL.md` routing, examples are used as design patterns rather than authority, and any public/shared file uses portable paths such as `$CODEX_HOME` instead of user-local absolutes. |
| `ND.skill.context-economy` | Every skill source review | Confirm the skill minimizes routine reads, broad scans, repeated validation, and final-output verbosity while still preserving required evidence gates and blocker reporting. |
| `ND.skill.safety-and-state-boundaries` | Skills that mutate files, git state, external services, credentials, automations, or runtime installs | Confirm the skill names the safe default scope, asks before risky or destructive steps, classifies retained/stale state when needed, and does not silently widen from one sibling scope to another. |
| `ND.skill.output-and-closure` | Every skill source review | Confirm the output contract tells the agent what to report, what to omit, what unresolved blockers or retained state must remain visible, and what completion claim the checked evidence can actually support. |
| `ND.skill.openai-example-comparison` | Explicit skill-design refreshes or ambiguous high-quality-skill decisions | Compare the target against 2-3 relevant installed OpenAI skill examples and record the concrete pattern borrowed or rejected, such as render gates, request classification, tool-contract wording, error recovery, or publish-scope safety. |
