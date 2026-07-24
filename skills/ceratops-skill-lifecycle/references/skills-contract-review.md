# Skills Contract Review Action

## Goal

Refresh the skill-design standards in
`references/contracts/skill-deterministic-contract.json` and
`references/contracts/skill-nondeterministic-contract.json` against current
best practices from `references/skill-source-docs.json`.

## Context

### References

- Skill source-doc registry: `references/skill-source-docs.json`
- Skill deterministic contract:
  `references/contracts/skill-deterministic-contract.json`
- Skill non-deterministic contract:
  `references/contracts/skill-nondeterministic-contract.json`

### Inputs To Capture

- Whether the user wants a report-only review or approved contract updates.
- The standards question or contract area that requires current evidence.
- Whether the source-doc registry itself is stale or incomplete for that
  question.

Infer missing inputs from the contract files before asking.

## Constraints

### Boundaries

- Use this action only to maintain the skill source-doc registry and the two
  skill-design contracts.
- Do not audit whether any source or installed skill satisfies the contracts;
  use `skills-consistency-review` for manifest-backed installed-skill
  compliance.
- Do not run `skills-consistency-source-validator.py`; targeted skill
  validation belongs to `skills-consistency-review`.
- Do not inspect unrelated metadata, shared sections, runtime payloads,
  automation prompts, helpers, installers, or installed runtime copies.

### Skill-Specific Rules

- Treat official sources listed in `skill-source-docs.json` as standards
  authority and installed OpenAI skills only as bounded pattern evidence.
- Refresh evidence only for a concrete standards question; do not perform
  broad research when the existing evidence is current and sufficient.
- Keep deterministic, machine-checkable requirements in
  `skill-deterministic-contract.json` and judgment-dependent requirements in
  `skill-nondeterministic-contract.json`.
- Preserve stable check IDs, remediation classifications, scope, and evidence
  mappings unless current best-practice evidence requires a change.
- Treat the contracts as standards definitions, not evidence that any skill
  complies with them.
- Keep skill standards under this action's `references/` tree; do not recreate
  a repository-root contract payload.

## Workflow

### 1. Inspect current standards evidence

- Read `skill-source-docs.json` and both skill contracts.
- Identify the exact contract requirement whose currency, placement, or scope
  needs review.

### 2. Refresh only necessary sources

- Check the highest-priority current source capable of resolving the standards
  question.
- Use at most two or three relevant installed OpenAI skill examples when
  official guidance leaves a concrete pattern decision unresolved.
- Update source registry entries and capture dates only for evidence actually
  refreshed.

### 3. Reconcile the contracts

- Update the deterministic or non-deterministic contract according to the
  evidence type.
- Keep cross-contract references, check IDs, evidence keys, and remediation
  classifications internally consistent.
- Do not convert a skill-compliance finding into a standards change unless the
  referenced best-practice evidence shows the contract itself is wrong.

### 4. Verify contract artifacts

- Parse every changed JSON contract or registry file.
- Re-open the changed contract entries and confirm that no standard, check, or
  protection was unintentionally dropped.
- If changed contract sources must be available in the installed runtime, hand
  off to `change-promotion`.

## Done When

### Completion Gate

- Every reviewed contract claim is supported by current registered evidence or
  reported as unresolved.
- Deterministic and judgment-dependent requirements remain in their respective
  contracts with consistent IDs and references.
- No source skill, installed skill, repository validator, or runtime surface was
  treated as reviewed for compliance.

### Output Contract

Report only:

- source evidence refreshed
- contract entries added, changed, retained, or retired
- unresolved standards questions or unavailable evidence
- anything important not verified
