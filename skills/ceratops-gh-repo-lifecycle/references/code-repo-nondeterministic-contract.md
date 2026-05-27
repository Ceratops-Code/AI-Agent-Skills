# Repo Code Non-Deterministic Checks

This file complements `code-repo-deterministic-contract.json`. The JSON contains
machine-checkable repository-content checks for local files, workflow text,
Dependabot config, CODEOWNERS, local git state, local path references, and
secret-pattern scans. This file contains content-quality and intent checks that
need reviewer judgment.

## Evidence Bundle

Use one bundled evidence command instead of running one command per check:

```powershell
python skills/ceratops-gh-repo-lifecycle/scripts/github-collect-nd-evidence.py --surface code --repo OWNER/REPO --local-repo-path PATH --json
```

The report maps each ND check ID to evidence keys and includes local scan
summaries, detected repo types, workflow and config signals, deterministic code
finding counts, and relevant GitHub validation endpoints such as CODEOWNERS
errors.
When live labels, Dependabot PR queues, alerts, or repository settings are also
in scope, collect a separate `--surface repo` evidence bundle.

## Review Result Values

- `pass`: reviewer found the intent satisfied and recorded evidence.
- `fail`: reviewer found a concrete mismatch.
- `approved_drift`: mismatch is allowed by the contract's approved drift
  profile.
- `blocked`: review needs unavailable local checkout, missing product decision,
  or unavailable validation endpoint.
- `not_applicable`: repository type or source line does not apply.

## Non-Deterministic Check Definitions

| ID | Applies when | Review required |
| --- | --- | --- |
| `ND.code.public-content-quality` | Repos where public or internal content files are expected | Confirm README, license, security policy, contributing guide, code of conduct, examples, install docs, issue forms, PR templates, and support docs contain repo-specific usable content rather than placeholders. |
| `ND.code.support-routing-quality` | Repos with homepage, support links, discussions, issues, or `SUPPORT.md` | Confirm support routing sends users to an active channel and does not conflict with issue templates or security reporting. |
| `ND.code.workflow-intent-and-pin-verification` | Repos with `.github/workflows/*` | Confirm every workflow still has a valid purpose, release workflows match artifact surfaces, full-SHA action comments point to the intended release, and reusable workflow tag refs are deliberate. |
| `ND.code.dependabot-policy-fit` | Package manifests or `.github/dependabot.yml` are present | Confirm detected ecosystems, grouping, open-PR limits, private registries, labels, and update cadence fit the repo instead of only being syntactically present. |
| `ND.code.local-state-classification` | Dirty git state, local generated files, local path references, or old automation references are present | Confirm each item is active, intentionally retained, approved drift, stale, or blocked before cleanup. |
| `ND.code.secret-pattern-intent` | Secret-like patterns are detected in local text files | Confirm whether each match is a real secret, a safe placeholder, test fixture, documentation example, approved drift, or blocked remediation. |
| `ND.code.comment-sufficiency` | Scripts, public APIs, automation helpers, contract checkers, or non-obvious safety logic are in scope | Use `skills/ceratops-gh-repo-lifecycle/references/code-comment-nondeterministic-contract.md` as the local review rubric and confirm comments explain intent, safety boundaries, external side effects, and public usage well enough for future maintenance without restating obvious code. |
| `ND.code.sources-current-doc-recheck` | Exact repo-content convention or generated-file behavior matters and local evidence is ambiguous | Recheck only the relevant official docs or local project standards before deciding drift. |
