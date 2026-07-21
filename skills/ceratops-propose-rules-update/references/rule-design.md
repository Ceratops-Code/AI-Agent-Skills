# Rule Design Contract

## Behavioral objective

Minimize behavioral delta: change only decisions needed to prevent the failure
while preserving recorded correct behavior. Word count and diff size are
secondary evidence.

## Rule form

Use one sentence when one condition determines one required behavior:

```text
[RULE-ID] When <condition>, require <behavior>.
```

Use the strongest unambiguous wording that accurately expresses the intended
rule.

Add an exception or relationship only when it changes the decision. Keep
scenarios outside governing instructions and use them as regression evidence.

## Size and enumeration

Keep a canonical rule within six 80-character lines. Split it when independent
conditions or actions can be named without weakening their interaction.

A normative enumeration may name at most three members. For a larger set,
state the common deciding property; when exact membership is operationally
required, store the closed set in deterministic data or a helper.

## Relationships

Use `requires` for a co-gate, `limits` when an independent guardrail narrows
another rule, and `overrides` when a specific rule wins incompatible
application. Do not carry an unresolved interaction into a candidate.

Merge coextensive guidance into one rule. Keep independently reusable behavior
separate and express only the directional relationship needed to interpret it.
When evidence cannot select one coherent result, present the exact decision
point before treating a candidate as complete.

## Scope interaction

Treat global instructions as the baseline for local instructions. A local rule
may add project behavior or narrow discretion the global rules leave open. It
may override a global rule only when that rule explicitly delegates the
decision to local scope. Otherwise repair the local rule or propose a global
delegation instead of retaining a contradiction.

Store local history with the local rule source and record any related global
rule IDs and the evaluated global-rule hash. Query both histories for a
cross-scope change. A project stack check must detect a stale global hash.
Revalidate known local references after changing a global rule; without a
registry, report broader local compatibility as unverified.

Use a JSON history object with `version: 2` and an `entries` array. Each entry
names affected rule IDs and records the causal and regression evidence required
by the source's checker.

## Acceptance

State the required invariant. Add a negative boundary only when it excludes a
distinct plausible failure not excluded by the invariant. Apply broad override
policy without repeating local user-override clauses.

Evaluate both local and structural intervention. Accept a candidate only when
it prevents the current failure and relevant recorded failures without
regressing recorded correct outcomes unless explicitly superseded.
