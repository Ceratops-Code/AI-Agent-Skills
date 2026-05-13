# Skill Design Non-Deterministic Checks

This file complements `skill-deterministic-contract.json`. The JSON contains machine-checkable skill source, metadata, shared-section, runtime-payload, public-doc, portability, and contract-reference-alignment checks. This file contains skill-design quality checks that need reviewer judgment.

## Good Skill Definition

A good skill is a scoped workflow contract that triggers only for the task class it can handle, captures the inputs needed to act, routes to the smallest relevant references or helper commands, keeps deterministic behavior in scripts or executable helpers when practical, states safety and blocker boundaries, defines evidence and completion gates, and tells the agent exactly what to report without turning the skill into a broad best-practices essay.

## Evidence Bundle

Use local evidence first:

- target source skill: `skills/<skill-name>/SKILL.md`
- skill metadata: `skills/<skill-name>/agents/openai.yaml`
- shared-section assignments and runtime payloads: `templates/skill-sections.json`
- deterministic skill contract: `contracts/skills/skill-deterministic-contract.json`
- source registry and example references: `contracts/source-docs.json`
- installed OpenAI skill examples, when present: `$CODEX_HOME/plugins/cache/openai-primary-runtime/*/*/skills/*/SKILL.md` and `$CODEX_HOME/plugins/cache/openai-curated/*/*/skills/*/SKILL.md`

Use installed OpenAI skills as pattern examples only. Compare at most 2-3 examples that match the current skill type or standards question, and record which specific design pattern each example informed.

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
| `ND.skill.scope-boundary` | Every skill source review | Confirm Goal, Inputs To Capture, Skill-Specific Rules, Boundaries, Done When, and Output Contract agree on one workflow surface and do not mix unrelated owners, artifacts, or lifecycle phases. |
| `ND.skill.workflow-contract` | Skills that tell the agent how to execute work | Confirm workflow steps are ordered by dependency, name the evidence needed for each decision, route blockers explicitly, and avoid ceremonial steps that do not change action or verification. |
| `ND.skill.deterministic-placement` | Skills with commands, scripts, generated artifacts, validators, or repeatable cleanup | Confirm deterministic behavior lives in scripts/helpers or exact command contracts when practical, and prompt text retains only high-level intent, routing, exceptions, and result-handling obligations. |
| `ND.skill.reference-discipline` | Skills that reference docs, examples, templates, assets, or installed OpenAI skills | Confirm references are loaded progressively, only the relevant files are named, examples are used as design patterns rather than authority, and any public/shared file uses portable paths such as `$CODEX_HOME` instead of user-local absolutes. |
| `ND.skill.context-economy` | Every skill source review | Confirm the skill minimizes routine reads, broad scans, repeated validation, and final-output verbosity while still preserving required evidence gates and blocker reporting. |
| `ND.skill.safety-and-state-boundaries` | Skills that mutate files, git state, external services, credentials, automations, or runtime installs | Confirm the skill names the safe default scope, asks before risky or destructive steps, classifies retained/stale state when needed, and does not silently widen from one sibling scope to another. |
| `ND.skill.output-and-closure` | Every skill source review | Confirm the output contract tells the agent what to report, what to omit, what unresolved blockers or retained state must remain visible, and what completion claim the checked evidence can actually support. |
| `ND.skill.openai-example-comparison` | Explicit skill-design refreshes or ambiguous high-quality-skill decisions | Compare the target against 2-3 relevant installed OpenAI skill examples and record the concrete pattern borrowed or rejected, such as render gates, request classification, tool-contract wording, error recovery, or publish-scope safety. |
