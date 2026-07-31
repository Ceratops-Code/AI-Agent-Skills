# Governance Consistency Audit Action

## Goal

Audit active Codex governance as one cross-scope system without duplicating
domain audits owned by other lifecycle actions.

## Context

### Deterministic Helper Contract

- (D) From this skill directory, run `python scripts/governance-snapshot.py
  --projects-root <projects-root> --evidence-output <task-temp-file>` before
  deep-reading.
- (D) With `--evidence-output`, the helper atomically writes the complete
  `global-governance-consistency-audit/snapshot.v3` evidence and emits only
  `global-governance-consistency-audit/decision.v1` with the evidence path,
  stable state fingerprint, and decision-cluster counts; nonzero execution,
  unreadable JSON, or unreadable evidence blocks the audit.
- Reuse the evidence file for later audit decisions until an inventoried
  surface changes; query it instead of rerunning the helper, refresh only after
  such a change, and remove the task-temporary evidence before closing.
- (D) Project AGENTS discovery always excludes the projects-root `tmp` tree;
  for every other candidate, the containing Git worktree's ignore resolution
  is the only exclusion source.
- Use helper output as cheap-pass evidence for automation metadata, AGENTS
  classification, Git/worktree state, automation ignore coverage, directly
  referenced paths, structured rule-graph facts, and overlong `(D)` rule
  candidates.

### Scope

- Global `$CODEX_HOME/AGENTS.md` and every project-local or nested `AGENTS.md`
  under the selected projects root that is outside the root `tmp` tree and not
  excluded by its containing Git worktree's ignore rules, evaluated through
  its complete applicable global-to-local instruction stack.
- Installed `$CODEX_HOME/automations/*/automation.toml`, automation repository
  control files relevant to generated or runtime artifacts, and helpers directly
  referenced by an in-scope control file.
- Cross-scope ownership, instruction interaction, prompt/helper alignment,
  automation metadata, worktree policy, verification scope, and recurring
  credit-cost controls.

### Delegated Owners

- Use `$ceratops-skill-lifecycle` `skills-contract-review` for skill-design
  contracts, shared sections, runtime payloads, and standards upkeep.
- Use `$ceratops-skill-lifecycle` `skills-consistency-review` for active skill
  catalog, source, installer, and managed-runtime consistency.
- Use `$ceratops-repo-lifecycle` `contracts-review` for GitHub organization,
  repository, code, PR, artifact, and release contracts.

### Inputs To Capture

- `$CODEX_HOME`, automation root, projects root, current automation caller, and
  whether project-thread context or saved credit-usage evidence is available.
- Current official OpenAI model evidence only when model freshness or prompt
  guidance is materially in question.
- Any task-specific exceptions that narrow findings or authorize a mutation.

Infer roots from the active automation workspace and local environment; ask only
when the projects root remains ambiguous.

## Constraints

### Skill-Specific Rules

- Keep the audit report-only. When invoked by the
  `global-governance-consistency-audit` automation, updating a stale installed
  automation `model` field to the latest officially verified model is the only
  pre-authorized mutation; otherwise report it.
- Do not mutate AGENTS files, skills, helpers, repository configuration, Git
  state, managed runtime, or external services during the audit.
- Compare every inspected automation prompt with each helper it directly
  invokes; keep outcome, blocker, cleanup, alert, and memory paths aligned.
- Prefer local evidence and helper contracts. Use official OpenAI sources only
  to identify the latest model or resolve a concrete prompt-guidance ambiguity.
- Do not report `xhigh` alone. Reasoning-effort findings require evidence of
  avoidable cost, excessive breadth, weak stopping rules, or a better comparison
  path.
- Review config- and prompt-level credit waste without inferring actual usage or
  billing when saved local evidence is absent.
- Do not treat portable variables or relative paths alone as contradictions.
- Apply [rule-design.md](rule-design.md) as the only prose rule-graph and
  status-classification standard; helpers enforce its closed syntax, and audit
  prompts must not redefine it.

### Accepted Exceptions

- Do not report `global-dev-tools-update` requiring two routine tables, setting
  `report_required` to true, or monitoring Docker Hub MCP PRs.
- Do not report repeated instruction-enforcement or no-memory policy text in
  installed automation prompts.
- Do not report the `ceratops-all-contracts-review` display identity or the
  existing Sunday 07:00 schedule overlap among `ceratops-all-contracts-review`,
  `credits-saving-analysis`, and `global-repo-health-consistency`.

### Boundaries

- Use this action for cross-scope governance alignment, not broad repository,
  skill-contract, or GitHub contract audits.
- Do not run expensive tooling, broad live checks, large test suites, or web
  research unless the cheap pass exposes a concrete decision that needs them.

## Workflow

### 1. Build the cheap-pass inventory

- Run the deterministic helper once and inventory files, schedules, model and
  effort, workspaces, prompt names, helper references, memory/alert contracts,
  Git/worktree state, repeated text, rule IDs, metadata, statuses, histories,
  relation edges and cycles, stack interaction, and `(D)` rule-brevity
  candidates.
- If history contains invalid fields, route the exact repair through
  `propose-rules-update` before any other audit work. Apply it when authorized;
  otherwise stop and report only the repair blocker.
- Treat helper blockers, missing roots, parse failures, and inaccessible
  governing sources as explicit audit limits.

### 2. Select evidence clusters

- Group evidence by topic and deep-read only clusters with plausible
  contradiction, duplication, stale state, recurring credit waste, ambiguous
  ownership, classification drift, or current model/prompt-guidance drift.
- Do not invoke delegated domain audits unless the cheap pass exposes a concrete
  cross-scope dependency that this action cannot classify alone.

### 3. Review governance consistency

- Apply the deterministic and semantic-review boundaries in
  [rule-design.md](rule-design.md); review each rule body once without pairwise
  comparison and keep unresolved review edges as findings.
- Build relation candidates from sections, explicit ID references, semantic
  similarity, deterministic findings, and direct neighbors. Deep-read only
  those candidate pairs; do not compare every possible rule pair.
- Check instruction bullets and explicit class labels against declared or
  inherited force definitions; report conflicting closure behavior as
  instruction-classification drift.
- Check contradictions, duplicated broader rules, stale placeholders,
  wrong-scope rules, local files that should be delta-only, missing numbered
  response-shape rules, and rule shapes that should be split, merged, shortened,
  or moved into deterministic helpers.
- Check automation prompt/helper alignment, stale metadata and identities,
  overlapping schedules or responsibilities, avoidable inbox items, memory and
  alert contracts, noisy output, broad refreshes, unnecessary live checks, and
  weak evidence or stopping budgets.
- Check worktree-root placement, automation ignore coverage, duplicated
  worktree rules, and task work merged into local `release/*` branches without
  explicit staging or preview intent.
- Check claim-scope and verification-scope drift, including artifact-specific
  checks or end-to-end validation required beyond changed artifacts and claims.
- Review automation prompts against current GPT guidance for outcome-first
  contracts, success criteria, evidence budgets, missing-evidence behavior,
  stopping conditions, output shape, and reasoning effort.

### 4. Preserve known regression cases

- Keep analogous cases in scope for duplicated update automations, unconditional
  governing-file reopens, AGENTS-only audits, missing automation ignore coverage,
  artifact-closure overreach, recurring audits that spend credits detecting
  credit waste, and prompt stacks stale against current model guidance.

### 5. Apply the model-only exception

- When the automation-specific mutation exception applies, verify the latest
  model from an official source, update only stale automation `model` fields,
  and record each automation id with its old and new values.
- Do not apply any recommendation beyond that exact exception.

### 6. Close from aligned evidence

- Recompare the action, automation prompt, and bundled helper before finishing.
- Route each confirmed rule or relation defect through this lifecycle's
  `propose-rules-update` action for the smallest exact advisory correction; do
  not apply it during the audit.
- Rank findings by severity and config/prompt-level credit recommendations by
  impact and safety.
- Classify inaccessible thread context, absent usage evidence, and skipped
  delegated audits as explicit limits rather than silently weakening the claim.

## Done When

### Completion Gate

- The helper result, inspected control files, directly referenced helpers,
  accepted exceptions, delegated ownership, mutation boundary, and report agree.
- Every model field changed under the exception has current official evidence
  and old/new values.
- Important unverified areas and unavailable evidence are explicit.

### Output Contract

Report only:

- findings ordered by severity, with conflicting artifacts, exact inconsistency,
  risk, and smallest credible change
- approved `self` debt grouped by status and rule ID without treating it as a
  blocking defect
- a `Recommendations` section covering every finding and confirmed config- or
  prompt-level credit opportunity, or `None`
- automation model fields changed, with automation id and old/new model
- important areas checked and consistent
- important unverified areas and unavailable evidence

If no material finding exists, keep the report short and state the checked scope
and main residual limits.
