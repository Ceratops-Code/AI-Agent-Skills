---
name: ceratops-credit-savings-analysis
description: Analyze recent Codex runs for avoidable credit spend, including deterministic rework, and recommend small prompt, rule, skill, helper, workflow, or validation controls.
---

# Ceratops Credit Savings Analysis

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
- (D) For non-closure analysis, run `python scripts/model-call-ledger.py
  --session PATH --evidence-output LEDGER_PATH [--last-runs N]
  [--include-run TURN_ID]`; it writes every completed run and model call to the
  sanitized ledger, emits only the run reconciliation summary, and includes
  full call details only for explicitly requested runs.
- (D) For closure analysis, run `python scripts/model-call-ledger.py
  (--thread-id THREAD_ID | --session SESSION) --closure [--last-runs N]
  [--include-run TURN_ID]`. For an `incremental closure`, set `N` to the
  completed runs strictly after the previous completed closure and exclude the
  boundary and active runs; omit `--last-runs` only for a full-thread closure.
  The helper emits one fingerprint-only selected-window call inventory by
  default, adds bounded sanitized action summaries only for explicitly included
  completed runs, and creates no evidence artifact.
- (D) Before reporting, rerun `model-call-ledger.py` for the same source and
  window with `--classifications CLASSIFICATIONS_PATH`; the existing helper
  must reject missing, duplicate, or multiply classified calls and emit only
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
  unimplemented; expose both call counts in the run table, but omit detailed
  implemented findings and recommendations.
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
- When still-unimplemented prompt-level savings cases exist, rank the top five
  evidence-backed cases, or all available cases when fewer exist, using only
  information available when each prompt was written; present them as
  `Original prompt | What happened | Cheaper wording` and exclude
  hindsight-dependent rewrites.

### Boundaries

- Use this skill for avoidable credit spend, including rework, repeated artifact
  iterations, failed output loops, stale cleanup, oversized validation,
  inefficient evidence gathering, and producer-failure analysis.
- If the active issue is one unresolved bug, use `$ceratops-task-lifecycle` with
  the `fixloop-break` or `execute-in-stages` action first.
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

- The inspected window and ledger evidence mode are stated; every model call is
  reconciled in the ledger and every completed run appears in the compact run
  table.
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

Start with `Blocked: <specific missing evidence or target>.` when missing
evidence prevents analysis. Otherwise start with
`Unimplemented avoidable spend: found.` or
`Unimplemented avoidable spend: none found.`

First show this exact run table:

```text
Completed run | Total model calls |
Avoidable calls - Fix Implemented |
Avoidable calls - Fix Unimplemented |
Token usage (total; input % of total/cached % of input/output % of total/reasoning output % of output)
```

Use each run's `started_at` date/time, not its turn ID, for `Completed run`, and
include a totals row. Show total tokens as an integer and each percentage to two
decimal places; do not show raw category token counts. For each
still-unimplemented control, show this exact control table:
`Proposed control | Calls saved per affected run |
Est. Percent of Affected Similar Runs |
Additional Calls per Affected Run for Implemented Fix |
Est. Calls Saving by Fix per Similar Run |
New Complexity Introduced by Fix |
One-time implementation cost (model calls) | Recommendation`.
Then report only still-unimplemented findings in detail, any required ranked
prompt-level table, excluded ordinary failures, and important evidence limits.
