# Propose Rules Update Action

## Goal

Every confirmed failure must change the controlling instruction surface or its
deterministic enforcement.

Read [rule-design.md](rule-design.md) before drafting.

## Constraints

### Boundaries

Use this action for instruction-system changes. Route general prompt rewrites
through the parent skill's `optimize-prompt` action; answer diagnosis-only
requests without forcing a rule change.
Route approved skill-source mutations through `$ceratops-skill-lifecycle`
`update` after accepting the proposal.

## Workflow

1. Reconstruct the failed decision from current evidence. Identify the active
   instruction stack, chosen behavior, and required behavior without assuming a
   relevant rule, single cause, or owning artifact exists.
2. Inspect exact current text from every involved source. For global and local
   instructions, determine scope and precedence before evaluating interaction.
3. Resolve the current rule graph and structured history before drafting. For
   global rules, check
   `$CODEX_HOME/AGENTS.history.json`; for local rules, check
   `AGENTS.history.json` beside their `AGENTS.md`. From this skill directory,
   run `python scripts/rule_history.py lookup --history <history> --rules
   <rules> ID...`, repeating both options in effective global-to-local order for
   an interacting instruction stack.
   The helper must parse the canonical metadata syntax and select every direct
   directional or review-edge neighbor. Use the compact default for graph
   selection and add `--full` only when selected causal or regression evidence
   is needed. Obsolete references, invalid fields, or an over-limit history
   block the remaining proposal workflow: apply the smallest authorized cleanup
   first, rerun lookup, and only then continue. If history does not exist, use
   targeted source history and state that recorded behavioral history was
   unavailable.
4. Compare a local correction with a structural or non-rule correction. Select
   by prevention of the failure, regression safety, behavioral scope, and
   complexity; textual minimality does not win automatically.
5. Draft under the rule-design contract. Resolve structural defects and every
   affected semantic review state inside the candidate, and identify every
   intentional behavior change.
6. Before accepting a replacement, split, merge, or compression, map every
   operative part of the current text, including named commands and examples,
   to preserved candidate behavior or an intentional change reported for
   approval; then replay the current failure and relevant recorded history,
   rejecting any unaccounted or regressed behavior.
7. Report the selected correction, material alternative, regression result,
   and uncertainty.

## Applying an approved change

Clean history before applying any other approved rule change. Keep decisions
that still constrain current behavior; delete obsolete references, retracted or
overridden outcomes, and entries with no regression value. Replace renamed IDs
when their rationale remains active. Store only the decision-only fields defined
by the rule-design contract, and compact history when its deterministic limit is
reached. Name every deletion in the proposal so approval covers the exact
durable history change. Run the source's rule checker; its history binding must
reject unrecorded rule changes, obsolete references, invalid fields, and
over-limit history.

## Iterative optimization

Use `scripts/iteration_controller.py` when repeated optimization is requested or
one-pass comparison remains materially uncertain. The controller owns numbering,
artifact hashes, and stopping state; it does not judge semantic quality.

For each issued iteration, produce one candidate and one assessment. Compare it
with the original, champion, and regression evidence, then submit `improved` or
`no-improvement`. Improvement resets the streak. Stop when the controller
reports 200 iterations or ten consecutive non-improvements. Never claim state
the controller did not report.

## Done When

### Completion Gate

A proposal is complete only when it prevents the current recorded failure,
leaves the rule graph structurally valid, retains only applicable regression
history within its size limits, and is better than the current state and
material alternative.
Otherwise change the intervention or report the unresolved decision point.

### Output Contract

Report only the selected exact change, its decision and regression evidence,
the disposition of every touched overlap or conflict, and unresolved impact;
do not present a candidate with an unresolved relationship as accepted.
