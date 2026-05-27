# GitHub Artifact Health Non-Deterministic Checks

This file complements `artifact-deterministic-contract.json`. The JSON contains
deterministic artifact classification, metadata, workflow, registry, and
smoke-check requirements. This file captures checks that need review-owner
judgment, domain-specific interpretation, current official-doc review, or
browser/manual registry confirmation.

## Evidence Bundle

Use one bundled evidence command for the artifact ND checks instead of running a
command per check:

```powershell
python skills/ceratops-gh-repo-lifecycle/scripts/github-collect-nd-evidence.py --surface artifact --repo OWNER/REPO --local-repo-path PATH --json
```

Pass artifact identities with `--param artifact_contracts=[...]` when the
package, image, or registry name cannot be derived from local manifests. The
report maps each ND check ID to evidence keys and includes detected artifact
types, GitHub release metadata, local file signals, and available Docker Hub,
PyPI, or npm latest-version metadata.

## Review Result Values

- `pass`: reviewer found the intent satisfied and recorded evidence.
- `fail`: reviewer found a concrete mismatch.
- `approved_drift`: mismatch is allowed by the contract's approved drift
  profile.
- `blocked`: review needs unavailable permission, paid feature, missing registry
  access, missing artifact access, or a product decision.
- `not_applicable`: artifact type or source line does not apply.

## Non-Deterministic Check Definitions

| ID | Applies when | Review required |
| --- | --- | --- |
| `ND.artifact.scope-fit` | The repo has artifact signals, the current change affects a releasable artifact, or an artifact/no-artifact claim is planned | Confirm the artifact contract should run and identify which claim or change triggered it. |
| `ND.artifact.real-deliverable-intent` | Any artifact detector matches, or no-artifact is claimed | Confirm the real deliverable from project intent, README, release workflow, registry state, and user-facing docs instead of relying only on manifests. |
| `ND.artifact.identity-contract-fit` | Any external artifact exists or is planned | Confirm artifact name, registry, package/image coordinates, version source, release policy, tag style, changelog source, and post-publish consumer check describe the actual external contract. |
| `ND.artifact.audit-boundary` | Audit-only mode is active | Confirm the workflow stays in classify/report mode and does not mutate tags, releases, packages, registry state, credentials, or package ownership. |
| `ND.artifact.local-smoke-sufficiency` | A build/package/install/pull/run/consume check is required | Confirm the local and registry smoke checks are meaningful for the real consumer path rather than only testing an editable checkout or local build cache. |
| `ND.artifact.publish-necessity` | Publishing, tagging, release creation, or package upload is proposed | Confirm repo policy and the merged change actually require a public or private artifact release before any registry mutation. |
| `ND.artifact.version-policy-fit` | Any artifact version or release tag is derived | Confirm the chosen version source and tag style fit the ecosystem, repo policy, and existing release history. |
| `ND.artifact.live-endpoint-sufficiency` | Live registry, release, digest, package, or docs endpoint is checked | Confirm the endpoint is authoritative for the selected artifact, package visibility, and registry target. |
| `ND.artifact.identity-path-fit` | A publish workflow exists | Confirm trusted publishing, OIDC, or another short-lived identity path is supported by the real registry; when it is not, confirm token fallback is explicit and minimally scoped. |
| `ND.artifact.provenance-fit` | Attestations, provenance, SBOM, or linked artifact metadata are emitted or claimed | Confirm provenance verification uses GitHub or registry-specific tooling and that emitted metadata does not expose secrets or misleading build data. |
| `ND.pypi.package-contract-quality` | PyPI or Python package artifact is in scope | Confirm long description rendering, license metadata, Python version support, sdist/wheel choices, PyPI Trusted Publisher configuration, exact-version install, and attestation verification are appropriate. |
| `ND.npm.package-contract-quality` | npm package artifact is in scope | Confirm package contents, access mode, scope, dist-tag policy, npm trusted-publisher configuration, staged-publish approval path when used, provenance, build/test path, and consumer smoke install match the package. |
| `ND.docker.image-contract-quality` | Docker or OCI image artifact is in scope | Confirm image target, tags, base-image pinning strategy, build context, multi-stage use, non-root practicality, ports/health checks, smoke run, provenance, and SBOM policy fit the image. |
| `ND.maven.package-contract-quality` | Maven or Gradle-published artifact is in scope | Confirm group/artifact/version coordinates, namespace ownership, signing/source/javadoc expectations, publish portal behavior, and consumer dependency resolution fit the artifact. |
| `ND.nuget.package-contract-quality` | NuGet package artifact is in scope | Confirm package ID, metadata, README/license, repository/source link expectations, trusted publishing availability, pack/push path, and consumer install check fit the package. |
| `ND.crates.package-contract-quality` | crates.io or Cargo artifact is in scope | Confirm crate metadata, publish restrictions, README/docs expectations, package contents, cargo package/dry-run evidence, and consumer install/dependency check fit the crate. |
| `ND.rubygems.package-contract-quality` | RubyGems artifact is in scope | Confirm gemspec metadata, gem contents, trusted publisher configuration, build/push path, and consumer install check fit the gem. |
| `ND.powershell.package-contract-quality` | PowerShell Gallery module or script is in scope | Confirm manifest metadata, tags, license/project links, module manifest validation, publish path, and consumer install/import check fit the module or script. |
| `ND.github-packages.contract-quality` | GitHub Packages or GHCR is the registry | Confirm package linkage, access control, visibility, billing/quota implications for private packages, and token choice match the intended package use. |
| `ND.release-assets.contract-quality` | GitHub release assets, binaries, archives, installers, or CLI binaries are in scope | Confirm asset naming, checksums, release notes, prerelease/draft state, platform matrix, download path, and install/run smoke check are meaningful for users. |
| `ND.docs-site.contract-quality` | GitHub Pages or static docs site artifact is in scope | Confirm the site is a real deliverable, live URL and homepage are correct, docs navigation smoke check is meaningful, and stale published docs are classified. |
| `ND.iac-module.contract-quality` | Terraform module or Helm chart artifact is in scope | Confirm registry target, module/chart metadata, versioning, package/lint evidence, and consumer install/pull check fit the module. |
| `ND.sources.current-doc-recheck` | Exact registry feature availability, trusted publishing support, provenance behavior, or paid/free behavior affects the result | Recheck official GitHub or registry docs before deciding drift. |
