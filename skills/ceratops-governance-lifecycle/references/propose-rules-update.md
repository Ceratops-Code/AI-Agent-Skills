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
8. In the final proposal, explain exactly why the selected correction is better
   than the current text and each material alternative, naming the deciding
   evidence and tradeoffs; include the regression result and remaining
   uncertainty.

## Applying an approved change

Before applying an approved rule mutation, complete workflow step 6 against the
exact current text. The deterministic helper validates mechanical application;
it does not prove semantic equivalence. The model remains responsible for
mapping every operative part of the old text, including commands and examples,
to preserved behavior or an explicitly approved change.

- (D) For every approved rule or TOML edit or history-only ID repair,
  create one request naming the complete rule stack, any exact validated
  champion and hash, every approved history append or ID migration, caller-selected
  validation evidence, the verified task-temp root, and exact request,
  champion, and evidence ownership; then run `python
  scripts/apply_rules_update.py --request <path>`.
- TOML targets require null history and Markdown policy; apply their exact
  approved text and parse the reopened file without reformatting. An empty
  history-operation list is allowed only for TOML-only edits. Mixed rule,
  history, and TOML writes share one rollback transaction.
- (D) The helper must verify current source and policy hashes and, when a
  champion is present, its hash, expected-old uniqueness, and mechanical
  validity through `validate_rule_candidate.py` with fixing disabled; apply
  approved rule replacement text unchanged and without reformatting; reuse
  rule-graph and history validation; preserve encoding and line endings; cover
  every changed current rule ID in history; protect coupled writes with
  rollback; reopen and revalidate exact bytes; remove only unchanged explicitly
  disposable artifacts after success; preserve them on failure; and emit only
  `OK` or one compact actionable error.
- (D) For an ID migration, the helper must apply approved one-to-one mappings
  simultaneously to exact rule-ID tokens in every history field,
  stable-deduplicate `rules` arrays, require approved exact semantic
  replacements where substitution would change meaning, preserve all other
  content and entry order, and prove no old ID remains. It may perform a
  history-only ID repair only when each old ID is absent and each new ID is
  present in the current rule stack.

Append one decision per approved rule change and apply any approved ID migration
under the history contract in [rule-design.md](rule-design.md).

## Iterative optimization

- (D) Construct each proposal with
  `python scripts/proposal-workflow.py construct --spec SPEC`.

Use `ceratops-governance-proposal-spec.v1` with the complete ordered rule sources,
histories, selected rule IDs, exact replacements, failure and regression
evidence, mutation authority, expected side effects, iteration limit, and
verified task-temp root. Use null history only when none exists and include one
history-backed source. Context-only sources have no replacements and require
history and selected rule IDs.

The helper derives request paths and disposable ownership, captures current
context rule text, and seeds the first candidate. It preserves the caller's
spec; finalization removes generated inputs and retains the validated champion.
For a supplied complete request with explicit paths or ownership, use
`python scripts/proposal-workflow.py prepare --request REQUEST` instead.

Both paths set `markdown_policy` to null in requests. The helper must resolve
and hash the skill-owned `references/.markdownlint.json` for Markdown targets;
TOML targets retain null policy and must parse without reformatting. It must
verify current source and skill-policy hashes, write compact context evidence,
initialize candidate-validation state, and open iteration 1 without mutating a
governed target. Before writing context or opening an iteration, reject existing
Markdown errors outside the declared replacement ranges. Errors within those
ranges may be repaired by the proposal; final whole-target validation still
applies.

- (D) After writing each pending structured candidate and semantic assessment,
  run `python scripts/proposal-workflow.py advance --state STATE --outcome
  OUTCOME --regressions RESULT`. Before hashing or recording, the controller
  must call the validator's shared implementation. The validator must repair
  only permitted whitespace in candidate artifacts, validate every complete
  prospective target and applicable rule stack and history, prove idempotence,
  atomically replace the candidate only after all targets pass, and write
  detailed evidence to the pending caller-selected path. Mechanical failure
  must leave the candidate recoverable and the same iteration pending without
  recording a semantic rejection; success records the fixed artifact,
  assessment, outcome, evidence, hashes, and state before opening a successor.
- (D) Before final output, run `python scripts/proposal-workflow.py finalize
  --state STATE`. The helper must reject incomplete runs, path escapes, links,
  repository or governed targets, undeclared artifacts, and changed owned
  inputs; copy the exact validated champion to the declared protected output;
  preserve user-owned or undeclared inputs; delegate controller cleanup; and
  remove every owned request, original/regression input, context evidence,
  state, and iteration artifact. Emit only `OK` or one compact actionable
  error.
- For each issued iteration, complete steps 5-7. After submission, post one
  compact commentary status; do not repeat iteration logs in the final answer.

## Done When

### Completion Gate

A proposal is complete only when it prevents the current recorded failure,
leaves the rule graph structurally valid, preserves the decision log under its
append-and-ID-migration contract, and is better than the current state and
material alternative.
Otherwise change the intervention or report the unresolved decision point.

### Output Contract

Report only the selected exact change, why it is better than the current text
and each material alternative, its regression evidence, the disposition of
every touched relationship or self-review finding, and unresolved impact; do not
present a candidate with an unresolved relationship as accepted.

For every overlap, limit, or self-review finding such as `self: list-heavy` in
scope, quote the exact text from each affected rule that creates the finding
(not necessarily the whole rule), state the behavior those excerpts enforce,
and propose the smallest repair limited to those excerpts when possible. Use the
same exact-text, behavior, and repair format for any relation or review type not
named here.
