# GitHub Organization Health Non-Deterministic Checks

This file complements `github-org-deterministic-contract.json`. The organization
JSON covers API-checkable settings and screen-parity surfaces. This file covers
organization checks where GitHub exposes names or toggles but the real pass/fail
decision depends on intent, least privilege, security ownership, manual browser
confirmation, or whether a paid feature is intentionally unavailable.

## Evidence Bundle

Use one bundled evidence command for the ND checks instead of running a command
per check:

```powershell
python skills/ceratops-gh-repo-lifecycle/scripts/github-collect-nd-evidence.py --surface org --org ORG --json
```

The report groups fetched endpoints under each ND check ID. Browser confirmation
is still required only when API evidence is missing, ambiguous, plan-limited, or
screen parity is disputed.

## Review Result Values

- `pass`: reviewer found the intent satisfied and recorded evidence.
- `fail`: reviewer found a concrete mismatch.
- `approved_drift`: mismatch is allowed by the contract's approved drift
  profile.
- `blocked`: review needs unavailable permission, paid feature, missing admin
  access, or manual web UI access.
- `not_applicable`: organization plan, feature availability, or policy scope
  makes the check irrelevant.

## Non-Deterministic Check Definitions

| ID | Applies when | Review required |
| --- | --- | --- |
| `ND.org.identity-screen-parity` | Org profile, logo, display name, billing email, blog, location, or public profile text is user-facing | Confirm the visible organization identity is intentional, current, and matches the intended source organization where exact byte equality is not the right rule. |
| `ND.org.logo-visual-confirmation` | The avatar hash cannot be fetched, GitHub returns transformed image variants, or browser parity is disputed | Confirm in the browser that the org uses the intended custom logo, not a generated default avatar or stale upload. |
| `ND.org.member-role-intent` | Members, owners, outside collaborators, custom roles, or security managers differ from contract expectations | Confirm the people/role set is intended, least-privilege, and not a stale invite, missing owner, or forgotten collaborator. |
| `ND.org.team-purpose-and-permission-fit` | Teams or organization roles exist | Confirm team names, descriptions, privacy, maintainers, inherited access, and repo access fit the org operating model. |
| `ND.org.webhook-and-integration-intent` | Org webhooks, Actions secrets/variables, Dependabot secrets, private registries, or GitHub Apps affect behavior | Confirm each integration is still used, scoped to the right repositories, and has a real owner; secret values are not exposed by the API, so stale or wrong values need manual owner confirmation. |
| `ND.org.actions-policy-fit` | Actions policy, runner groups, selected actions, OIDC subject templates, artifact/log retention, fork PR approval, or hosted compute settings differ or are unavailable | Confirm the policy allows required workflows while preventing unwanted third-party action, runner, OIDC, retention, or fork-PR exposure. |
| `ND.org.security-configuration-intent` | Code security configurations, defaults, security managers, dependency submission, or paid security surfaces are present or missing | Confirm the security posture is intentional, no-extra-cost features are enabled when available, and paid GitHub Code Security or Secret Protection requirements are classified rather than silently required. |
| `ND.org.dependabot-private-registry-fit` | Dependabot repository access, Dependabot secrets, or private registry configurations exist | Confirm access is limited to intended repositories and registries, private registry credentials are still valid, and broad repository access is intentional. |
| `ND.org.dependabot-queue-fit` | Open Dependabot alerts or open Dependabot-authored PRs exist anywhere in the org | Confirm each item is active, fixed, superseded, blocked, intentionally retained, or safely mergeable; archived repo items are report-only unless the repo is explicitly reactivated. |
| `ND.org.custom-property-schema-fit` | Custom properties or repository metadata schema exists | Confirm names, allowed values, required flags, defaults, and descriptions remain useful and do not encode stale taxonomy. |
| `ND.org.moderation-and-community-fit` | Blocked users, interaction limits, issue types, issue fields, announcement banners, or reported-content policy differ or are unavailable | Confirm moderation state, intake fields, and org announcement text are intentional and not stale incident response. |
| `ND.org.ruleset-and-token-request-fit` | Organization rulesets or personal access token requests are enabled, unavailable, or plan-limited | Confirm rulesets and PAT approval policies match the org's merge and credential posture; when org rulesets return an expected plan-limit error, state whether to retain repo-level rulesets or upgrade the org plan. |
| `ND.org.paid-feature-classification` | Any endpoint returns plan-limited, enterprise-only, or permission-limited state | Confirm whether the gap is a paid feature, missing admin/security-manager permission, or true drift before deciding remediation. |
| `ND.org.source-doc-recheck` | GitHub has renamed, moved, or plan-gated an org setting, or API and browser state disagree | Recheck current official GitHub docs and the browser UI before deciding drift. |
