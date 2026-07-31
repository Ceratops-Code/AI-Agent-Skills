# Propose Rules Update Action

## Goal

Every confirmed failure must change the controlling instruction surface or its
deterministic enforcement.

Read and apply [rule-design.md](rule-design.md) before drafting.

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
   every source in the affected global and complete project scopes. Use compact
   lookup for current rules and direct graph neighbors. Add `--full` when
   renamed or retired rules, a supersession decision, or uncertain relevance
   requires the complete log. If history does not exist, use targeted source
   history and state that recorded decision history was unavailable.
4. Compare a local correction with a structural or non-rule correction. Select
   by prevention of the failure, regression safety, behavioral scope, and
   complexity; textual minimality does not win automatically.
5. From steps 1-4, draft the best-supported candidate under the rule-design
   contract using the shortest wording that changes only the explicitly
   targeted behavior and preserves every other behavior and enforcement
   strength. Keep deterministic procedure in its executable owner, resolve
   structural defects and every affected semantic review state, and identify
   each targeted change.
6. Before presenting a candidate, replay the failure and map every operative
   part and enforcement strength, including commands and examples, to the fix
   or preserved behavior; reject any unaccounted effect, historical regression,
   or conflict with an opposing active requirement.
7. In the same reasoning pass, compare the candidate with the original and
   every recorded candidate and assessment. While any supported conclusion
   identifies a concrete improvement, revise and repeat steps 5-6; then submit
   the best candidate and its assessment to the iteration controller.
8. Report the selected correction, material alternative, regression result,
   and uncertainty.

## Applying an approved change

Before applying an approved rule mutation, complete workflow step 6 against the
exact current text. The deterministic helper validates mechanical application;
it does not prove semantic equivalence. The model remains responsible for
mapping every operative part of the old text, including commands and examples,
to preserved behavior or an explicitly approved change.

- (D) For every approved rule mutation, create one request that names the
  affected global scope and every rule source in the complete project scope,
  each target rules and companion history source, each exact expected-old and
  replacement text, and every approved history append; then run `python
  scripts/apply_rules_update.py --request <path>`.
- (D) The helper must require each expected-old text to occur exactly once,
  construct and validate every candidate before replacing a target, reuse the
  rule-graph and history validators, preserve encoding and line endings, cover
  every changed rule ID in the approved append-only history operations, protect
  coupled writes with rollback, reopen and revalidate the result, and emit only
  `OK` or one compact actionable error.

Append one decision per approved rule change under the history contract in
[rule-design.md](rule-design.md).

## Iterative optimization

- (D) For every proposal, run `python scripts/iteration_controller.py init
  --state <path> --original <path> [--regressions <path>]
  [--max-iterations <count>] --open-first` to initialize state and open
  iteration 1; use `python scripts/iteration_controller.py next --state
  <path>` only for later iterations. The controller must record iterations,
  retain the champion, and enforce stopping.
- (D) Before final output, after the accepted proposal or approved mutation no
  longer needs controller artifacts, run `python
  scripts/iteration_controller.py finalize --state <path>`. Finalization must
  require complete state, delete only that state and its recorded candidate and
  assessment files under the sibling `iterations/` directory, remove that
  directory only when empty, preserve original and regression inputs, reject
  unexpected paths or contents before deletion, and emit only `OK` or one
  compact actionable error.
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
