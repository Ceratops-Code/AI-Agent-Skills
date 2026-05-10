## Artifact Contract

- Treat `contracts/artifacts/artifact-deterministic-contract.json` as the source of truth for external deliverables, registry identity, package or image metadata, trusted publishing, provenance, live registry verification, and consumer smoke expectations.
- Run artifact checks only when the repo has an external artifact, the current change affects a releasable artifact, or the final answer makes an artifact or no-artifact claim.
- (D) Use `scripts/validation/github-validate-repo-artifact-contract.py --surface artifact --subset artifact` for artifact audits, uncertain registry state, or broad artifact claims.
- Do not run it solely to read back an exact publish, tag, or file-write command that already succeeded.
- Do not publish, tag, mutate registry state, delete packages, or change artifact credentials from an audit-only contract run; move into the publish or ship workflow when registry mutation is actually required.
