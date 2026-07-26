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
- Window under review: the user's last `N` completed runs, or the full thread
  when `N` is omitted.
- Resolve the selected session record through
  `$CODEX_HOME/session_index.jsonl`, `$CODEX_HOME/sessions/`, or
  `$CODEX_HOME/archived_sessions/`. Visible context may identify scope but is
  not analysis evidence.
- (D) For non-closure analysis, run `python scripts/model-call-ledger.py
  --session PATH --evidence-output LEDGER_PATH [--last-runs N]
  [--include-run TURN_ID]`; it writes every completed run and model call to the
  sanitized ledger, emits only the run reconciliation summary, and includes
  full call details only for explicitly requested runs.
- (D) For closure analysis, run `python scripts/model-call-ledger.py --closure
  --thread-id ID`, or pass `--session PATH` when the thread ID is unavailable;
  it emits one sanitized full-thread call inventory and creates no evidence
  artifact.
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
- Use credit-waste signals as prompts for analysis, not mandatory checks;
  inspect only categories visible in the selected evidence window.
- Prefer the smallest durable control: wording, deterministic helper, preflight,
  validation gate, then docs.
- For repeated stage commands, propose a narrow helper that runs the sequence
  and emits only the decision payload.
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
- Classify every model call as necessary, avoidable with an implemented fix, or
  avoidable with an unimplemented fix, and map each fix only to calls it
  directly prevents.
- For each still-unimplemented control, compute `long-term average saving/run =
  affected-run rate x saved/affected run - added/run` and estimate its one-time
  cost separately. Reject non-positive average savings or costs unlikely to be
  recovered during the control's expected lifetime unless correctness or safety
  requires the control. When the user supplies a horizon, also compute net
  savings over it.
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
3. Review ledger-recorded command, tool, and file-read choices for avoidable
   output volume, unnecessary file reads, repeated polling, and oversized
   validation; count only when a narrower command, selector, path, section, or
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
- Each finding ties to a concrete episode, cause, earliest prevention point,
  recommendation type, and expected impact.
- Ordinary model failures that could be confused with avoidable credit spend are
  explicitly excluded.
- Any missing evidence or target-thread blocker is stated.

### Output Contract

Start with `Blocked: <specific missing evidence or target>.` when missing
evidence prevents analysis. Otherwise start with
`Unimplemented avoidable spend: found.` or
`Unimplemented avoidable spend: none found.`

First show
`Run | Model Calls | Avoidable Calls with Implemented Fix |
Avoidable Calls with Unimplemented Fix`, reconciled totals, and available token
usage. For each still-unimplemented control, show
`Control | Saved/affected run | Forecast rate | Added/run |
Long-term average saving/run | One-time cost | Decision`. Then report only
still-unimplemented findings in detail, any required ranked prompt-level table,
excluded ordinary failures, and important evidence limits.
