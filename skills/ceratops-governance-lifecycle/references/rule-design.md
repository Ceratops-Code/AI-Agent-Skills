# Rule Design Contract

## Behavioral objective

Minimize behavioral delta: change only decisions needed to prevent the failure
while preserving recorded correct behavior. Word count and diff size are
secondary evidence.

## Rule form

Every instruction rule in an applicable global or local `AGENTS.md` must use
the structured syntax parsed by `scripts/rule_graph.py`. A rule starts with one
globally stack-unique ID, uses the parser's canonical metadata syntax, and may
reference only IDs available in its effective global-to-local instruction
stack. Nested local files extend the stack of their ancestors.

Use one sentence when one condition determines one required behavior:

```text
[RULE-ID] When <condition>, require <behavior>.
```

Use the strongest unambiguous wording that accurately expresses the intended
rule.

Add an exception or relationship only when it changes the decision. Keep
scenarios outside governing instructions and use them as regression evidence.

Place metadata immediately after the rule body. Use only the parser's closed
metadata-key and value sets, canonical order, indentation, separators, and ID
grammar. Do not accept prose or backticked relation syntax as an alternative.

## Size and enumeration

Keep a canonical rule within six 80-character lines. Split it when independent
conditions or actions can be named without weakening their interaction.

A normative enumeration may name at most three members. For a larger set,
state the common deciding property; when exact membership is operationally
required, store the closed set in deterministic data or a helper.

`self: exceeds-limit` and `self: list-heavy` are approved non-blocking debt,
not structural failures. Their presence must match the current rule, remain an
audit finding, and be removed when the underlying debt is fixed. Size status is
deterministic; enumeration status requires focused semantic review.

## Relationships

Use `limits` when an independent guardrail narrows another rule and `overrides`
when a specific rule wins incompatible application. Do not introduce an
unresolved interaction in a candidate.

These relations are directional from the declaring rule to the target. Detect
every directed cycle. An `overrides` cycle is structurally invalid; `limits`
and mixed cycles require focused semantic review.

Treat `overlaps` and `conflicts` as symmetric review edges declared once. They
remain unresolved findings until semantic review selects a coherent outcome;
do not change involved behavior without resolving the edge or recording the
manual decision to retain it. Keep the current `CLOSE-01` and `REWORK-05`
conflict as a finding until that decision is made.

Merge coextensive guidance into one rule. Keep independently reusable behavior
separate and express only the directional relationship needed to interpret it.
When evidence cannot select one coherent result, present the exact decision
point before treating a candidate as complete.

Use deterministic checks for syntax, targets, duplicates, placement, statuses,
size, cycles, and stack legality. Use focused semantic review for missing,
unnecessary, mistyped, misdirected, incompatible, overlap, and conflict edges.

## Scope interaction

Treat global instructions as the baseline for local instructions. A local rule
may add project behavior or narrow discretion the global rules leave open. It
may override a global rule only when that rule explicitly delegates the
decision to local scope. Otherwise repair the local rule or propose a global
delegation instead of retaining a contradiction.

A global rule must not depend on a local rule. A local relation may target only
the global rules and ancestor-local rules in its effective stack. Validate IDs,
relations, and compatibility across the complete stack, not each file alone.

Store local history beside its local rule source and query every applicable
history in a cross-scope change. Revalidate current global and ancestor-local
rules directly; do not store dates, hashes, or source snapshots in history.

Use a JSON history object with `version: 2` and an `entries` array. Each entry
uses the decision-only schema owned by `scripts/rule_graph.py`: it names current
rule IDs and states the decision, why it exists, and its regression boundary.
History is regression memory, not an audit log: retain every decision and
rationale that still constrains current behavior, and delete obsolete
references, retracted or overridden outcomes, and entries with no remaining
regression value. Resolve obsolete history before other governance work; do not
continue with a report-only finding.

When a history file exceeds 8 KiB or 20 entries, compact it before other
governance work. Merge decisions only when their behavior, rationale, and
regression boundary remain explicit; the compacted file must meet both limits.

## Acceptance

State the required invariant. Add a negative boundary only when it excludes a
distinct plausible failure not excluded by the invariant. Apply broad override
policy without repeating local user-override clauses.

Evaluate both local and structural intervention. Accept a candidate only when
it prevents the current failure and relevant recorded failures without
regressing recorded correct outcomes unless explicitly superseded.
