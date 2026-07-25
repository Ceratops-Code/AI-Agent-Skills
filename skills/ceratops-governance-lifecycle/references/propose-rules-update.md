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
   an interacting instruction stack. Use compact lookup for current rules and
   direct graph neighbors. Add `--full` when renamed or retired rules, a
   supersession decision, or uncertain relevance requires the complete log.
   Invalid fields block the remaining proposal workflow. If history does not
   exist, use targeted source history and state that recorded decision history
   was unavailable.
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

Append one decision for each approved rule change using the decision-only fields
defined by the rule-design contract. Preserve prior entries and identify an
earlier decision in the new decision text only when its rationale is
intentionally replaced or narrowed. Do not rewrite prior entries for rule
renames, removals, or implementation evolution; append the new decision those
changes represent. Run the source's rule and history checkers; they must reject
invalid fields without treating historical rule IDs as current references.

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
leaves the rule graph structurally valid, preserves the append-only decision
log, and is better than the current state and material alternative.
Otherwise change the intervention or report the unresolved decision point.

### Output Contract

Report only the selected exact change, its decision and regression evidence,
the disposition of every touched overlap or conflict, and unresolved impact;
do not present a candidate with an unresolved relationship as accepted.
