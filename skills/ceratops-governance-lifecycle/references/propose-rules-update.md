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
5. From steps 1-4, draft the best-supported candidate under the rule-design
   contract using the shortest wording that changes only the explicitly
   targeted behavior and preserves every other behavior and enforcement
   strength. Keep deterministic procedure in its executable owner, resolve
   structural defects and every affected semantic review state, and identify
   each targeted change.
6. Before presenting the candidate, map every operative part and its
   enforcement strength, including named commands and examples, to unchanged
   behavior or the explicitly targeted fix; replay the failure and applicable
   history, rejecting any other behavior change or regression.
7. In the same reasoning pass, compare the candidate with the original and
   every recorded candidate and assessment. While any supported conclusion
   identifies a concrete improvement, revise and repeat steps 5-6; then submit
   the best candidate and its assessment to the iteration controller.
8. Report the selected correction, material alternative, regression result,
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

- (D) Run `scripts/iteration_controller.py` for every proposal to record
  iterations, retain the champion, and enforce stopping.
- For each issued iteration, complete steps 5-7. After submission, post one
  compact commentary status; do not repeat iteration logs in the final answer.

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
