## Repo Health Contracts

- Treat `contracts/github/github-repo-deterministic-contract.json` as the source of truth for live GitHub repository settings, Actions policy, branch or ruleset enforcement, security settings, queues, labels, releases, and stale GitHub state.
- Treat `contracts/code/code-repo-deterministic-contract.json` as the source of truth for repository contents, local file checks, workflow text, Dependabot config, CODEOWNERS validity, local git state, local path references, and secret-pattern scans.
- (D) Use `--surface repo` for live GitHub repository state, `--surface code` for content-only checks, `--surface artifact` for external deliverables, and `--surface all` only for full health, repo creation, or explicit broad audit work; when both repo state and code are in scope, use repeatable `--select surface:subset` entries in one validator process.
- (D) When a contract run is actually needed, use the narrowest subset that matches the activity: `settings`, `dependency`, `content`, `artifact`, `create`, or `health`.
- (D) Use `scripts/validation/github-validate-repo-artifact-contract.py` for audits, drift checks, uncertain state, or broad closure claims.
- Do not rerun it solely to read back a single setting or file write when the exact mutation command succeeded and no broader current-state claim depends on fresh evidence.
- Use `scripts/validation/github-collect-nd-evidence.py` for non-deterministic review evidence when deterministic output leaves an intent, paid/free, browser-visible, or prose-quality decision unresolved.
