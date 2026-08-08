---
name: ceratops-credit-savings-analysis-old
description: Analyze recent Codex runs for avoidable credit spend with the pre-redesign workflow. Use only when the old credit savings analysis skill is explicitly requested.
---

# Ceratops Credit Savings Analysis - old

## Goal

Find avoidable credit spend in recent thread runs, including rework and
non-rework inefficiencies, then recommend the smallest control that would
materially reduce recurrence.

## Context

### Inputs To Capture

- Target thread or session. Use the current thread unless the user names a
  concrete thread title, thread id, or session file.
- Window under review: an `incremental closure` beginning after the previous
  completed closure, another user-stated boundary, the last `N` completed runs
  when specified, or the full thread when no boundary is stated.
- Resolve the selected session record through
  `$CODEX_HOME/session_index.jsonl`, `$CODEX_HOME/sessions/`, or
  `$CODEX_HOME/archived_sessions/`. Request semantic evidence only through
  `model-call-ledger.py --include-run TURN_ID`; do not parse session rows with
  ad hoc helpers. Visible context may identify scope but is not analysis
  evidence.
- (D) Before inspecting calls for either non-closure or closure analysis, run
  `python scripts/model-call-ledger.py (--thread-id THREAD_ID | --session
  SESSION) --summary --evidence-output USAGE_PATH [--last-runs N] [--top N]
  [--pricing-profile PRICING_PATH]`. For an `incremental closure`, set `N` to
  the completed runs strictly after the previous completed closure and exclude
  the boundary and active runs; omit `--last-runs` only for a full-thread
  window. The helper writes versioned sanitized per-run evidence, emits only
  compact totals and ranked turn IDs, and reports estimated credit cost only
  when the caller supplied valid rates.
- Treat `--summary` as evidence selection, not an analysis result. For every
  analysis request, continue through selected-turn semantic inspection and
  classification validation before answering.
- (D) Request semantic evidence only for selected turns with `python
  scripts/model-call-ledger.py (--thread-id THREAD_ID | --session SESSION)
  --evidence-output LEDGER_PATH --semantic-evidence-output SEMANTIC_PATH
  [--last-runs N] --include-run TURN_ID`; repeat `--include-run` only for
  additional turns justified by the compact rankings. The helper must preserve
  the fingerprint ledger at `LEDGER_PATH`, write versioned sanitized
  selected-run semantic evidence to `SEMANTIC_PATH`, and emit only compact
  selected-run IDs and counts. Keep `--closure` for callers that explicitly
  require its artifact-free fingerprint inventory; neither detail mode replaces
  the compact summary.
- (D) Before reporting, rerun `model-call-ledger.py` for the same source and
  window with `--classifications CLASSIFICATIONS_PATH`; the helper must reject
  missing, duplicate, or multiply classified calls and emit only
  validated per-run category totals.
- Whether the task is analysis-only or the user explicitly asked to apply a
  named control change.

Ask for the missing title, id, or session file only when the target thread
cannot be identified. If the selected session record cannot be resolved, stop
blocked; do not fall back to visible context.

## Constraints

### Skill-Specific Rules

- Count spend as avoidable only when it was preventable or reducible from
  available instructions, local evidence, stable contracts, tool output, or a
  cheap targeted check.
- Exclude ordinary model mistakes unless a concise durable producer control
  would sharply reduce the same class recurring.
- Treat preventable rework, duplicate investigation, broad reads, noisy output,
  oversized validation, stale checks, waits, reversions, and user corrections as
  candidate credit waste.
- Count model calls avoidable through existing evidence, direct helper
  composition, or same-pass draft-assess-revise work, even when the work
  succeeds.
- When a question was answerable from fresh sufficient selected-session context,
  treat file reads and commands used only to rediscover or reconfirm that
  context as candidate avoidable spend; exclude actions required by an active
  freshness, verification, safety, or workflow gate.
- Use credit-waste signals as prompts for analysis, not mandatory checks;
  inspect only categories visible in the selected evidence window.
- Prefer the smallest durable control: wording, deterministic helper, preflight,
  validation gate, then docs.
- For repeated stage commands, propose a narrow helper that runs the sequence
  and emits only the decision payload.
- Do not recommend altering the governance lifecycle's required
  proposal-iteration controller solely to reduce model calls; treat its
  required iterations as intentional workflow cost and count only avoidable
  work outside them.
- For unnecessary file reads, propose targeted paths, sections, selectors, or
  evidence reuse.
- Do not propose broad best-practice refreshes, large instruction rewrites, or
  high-maintenance controls unless smaller controls are demonstrably inadequate.
- When the user asks to apply or draft a recommendation that would edit
  instructions, skills, automations, or helpers, provide the exact proposed
  change before mutating; otherwise name the target artifact and target
  behavior.
- Before reporting, classify each finding's control as implemented or still
  unimplemented. Keep complete per-run category counts in caller-selected
  machine evidence; mention implemented findings only when they materially
  change the recommendation.
- Before classification, inspect highest-call runs covering at least 80% of
  calls for avoidable call clusters; do not treat lack of inspection as
  evidence that a call was necessary.
- Classify every model call as necessary, avoidable with an implemented fix, or
  avoidable with an unimplemented fix, and map each fix only to calls it
  directly prevents.
- For each still-unimplemented control, compute `estimated calls saving by fix
  per affected run = calls saved per affected run - additional calls per
  affected run for the implemented fix`, then compute `estimated calls saving
  by fix per similar run = estimated calls saving by fix per affected run *
  estimated percent of affected similar runs expressed as a proportion`; rate
  `new complexity introduced by fix` as Low, Medium, or High based on added
  implementation and maintenance burden, and estimate one-time cost separately.
  Reject non-positive savings or costs unlikely to be recovered during the
  control's expected lifetime unless correctness or safety requires the control.
  When the user supplies a horizon, also compute net savings over it.
- Estimate affected-run frequency from triggering conditions and comparable
  evidence; state assumptions and a plausible range, use observations only as
  calibration, and test ROI at the range's low end.
- Merge recommendations that share the same producer and control.
- When prompt wording is a selected recommendation, show only the highest-value
  case as `Cheaper wording: <replacement>` with one brief cause statement; keep
  the original prompt and remaining cases in machine evidence.

### Boundaries

- Use this skill for avoidable credit spend, including rework, repeated artifact
  iterations, failed output loops, stale cleanup, oversized validation,
  inefficient evidence gathering, and producer-failure analysis.
- If the active issue is one unresolved bug, use normal diagnosis and fix flow
  before this analysis.
- If the user already knows the specific rule to change, use
  `$ceratops-governance-lifecycle` action `propose-rules-update`.

### Workflow

1. Build a compact timeline for each inspected run: goal, touched artifacts,
   checks, corrections, retries, and final state.
2. Mark each avoidable spend episode and the earliest point it could have been
   prevented or detected.
3. For each question followed by file reads or commands, compare those actions
   with fresh sufficient selected-session context available when the question
   was asked; count actions used only to rediscover or reconfirm that context
   as avoidable unless an active freshness, verification, safety, or workflow
   gate required them. Review other ledger-reconciled command, tool, and
   file-read choices only when a narrower command, selector, path, section, or
   existing evidence would have been sufficient.
4. Identify the producer or workflow choice that allowed the spend: prompt,
   rule, skill, automation, helper, validation, tool choice, workflow habit, or
   external dependency.
5. Choose the lowest-maintenance control that would have prevented or sharply
   reduced the spend.
6. Separate confirmed findings from plausible but unverified risks.

## Done When

### Completion Gate

- The inspected window and ledger evidence mode are recorded; every model call
  is reconciled and every completed run appears in caller-selected machine
  evidence.
- The existing ledger helper validated the final classifications against the
  exact selected source and window; inventory evidence alone does not satisfy
  this gate.
- Each finding ties to a concrete episode, cause, earliest prevention point,
  recommendation type, and expected impact.
- Ordinary model failures that could be confused with avoidable credit spend are
  explicitly excluded.
- A zero-finding result is invalid when based only on ledger counts or
  fingerprints; selected session rows must support dismissal of every visible
  candidate signal and every required output category.
- Any missing evidence or target-thread blocker is stated.

### Output Contract

Start with `Blocked: <specific missing evidence or target>.` only when missing
evidence prevents analysis. Otherwise lead with
`Recommendation: <highest-value control>.` or `Recommendation: none.`

Add at most two secondary recommendations, only when each requires a distinct
user action. For every reported recommendation, state only:

- `Why:` the concrete episode, cause, and earliest prevention point.
- `Impact:` observed calls saved per affected run and estimated calls saved per
  similar run; add at most one other statistic when it changes priority.
- `Action:` `Implement` or `Defer`, with the material confidence assumption or
  range.

When scale materially changes the decision, add one sentence with avoidable
calls versus total calls and either raw-token share or priced cost. Never
describe token volume as monetary or credit cost without a valid pricing
profile.

Keep exhaustive reconciliation, detailed classifications, timelines, matrices,
implemented findings, ordinary-failure inventories, and routine evidence limits
in caller-selected machine evidence. Emit them only when the user requests that
detail, and mention by default only a limitation that could change the
recommendation.
