# Review Action

## Goal

Find consequential disagreements between a design document, implementation,
and declared sources of truth. Report evidence and the smallest credible fix.

## Inputs

Resolve repository, design document, comparison scope, and intended baseline.
Read `design-document-contract.md` and `validator.md`. Preserve the document,
code, configuration, and Git state throughout review.

## Workflow

1. Read governing instructions, the authoritative document, its references, and
   declared ownership and precedence. Distinguish implemented design, accepted
   future design, and proposals before judging contradictions. When ownership
   is unclear, report the exact competing artifacts and affected decision.
2. Map the contract topics to existing headings. Preserve project terminology.
   If the document lacks embedded machine metadata, pass `--mapping` with a
   caller-owned temporary JSON projection of its existing facts and headings.
   Mark missing facts as unverified; do not invent owners or authority. Missing
   mapping syntax alone is a mechanical limitation, not an architectural defect.
3. Run the mechanical helper and retain its bounded result. Continue semantic
   review even when a parser or mapping is unavailable; report precisely which
   checks could not run. Do not modify or install dependencies in the target
   repository during review. Remove owned temporary evidence when consumed.
4. Compare important claims with targeted code, configuration, tests, deployment,
   and normative documents. Inspect happy paths and material failure/recovery
   paths. Check view/prose agreement, data ownership, boundaries, integration
   contracts, migrations, quality claims, and decisions using the contract.
   Prefer existing behavior tests or structured configuration evidence for a
   disputed executable claim; source text alone does not establish behavior.
5. For each suspected inconsistency, try to disprove it using version, scope,
   environment, source precedence, and intended-versus-current distinctions.
   Confirm a finding only when the evidence demonstrates conflicting claims in
   the same relevant scope. Otherwise record the precise unverified claim and
   missing evidence, without inflating it into a confirmed inconsistency.
6. Rank confirmed findings by consequence using the rubric below. Name each
   conflicting artifact with exact path and line or section, explain the risk,
   and propose the smallest credible correction in its owning surface. Separate
   evidence-backed missing required content from speculative improvements.
   Do not add generic style advice, reformat the document, or implement fixes.

## Severity and Finding Format

| Severity | Consequence |
| --- | --- |
| Critical | Credible immediate exposure to severe security compromise, irreversible data loss, or a system-wide operational failure. |
| High | A material architectural or contract mismatch can break an important workflow, security boundary, migration, or recovery promise. |
| Medium | A bounded inconsistency can mislead implementation or operations, or a required design decision is missing with a concrete risk. |
| Low | A precise, consequential reference or narrow factual defect with limited impact. |

For each confirmed finding, provide severity, claim, exact conflicting
artifacts, evidence, risk, and smallest fix. Use a separate unverified-coverage
list with topic, inspected scope, missing evidence, and next verification step.
Severity reflects consequence, not the number of missing headings.

## Completion Gate

Every reported inconsistency has scoped evidence, risk, and a credible owning
fix. Contract topics and required view decisions have been reviewed or marked
unverified. State which mechanical checks passed or could not run. A result
with no confirmed inconsistencies must still identify coverage limits and must
not imply exhaustive correctness. Target files and Git state remain unchanged.

## Output Contract

Return confirmed findings in severity order, then material unverified coverage
and the mechanical-check result. If none are confirmed, say so with the reviewed
scope. Write a persistent report only when requested.
