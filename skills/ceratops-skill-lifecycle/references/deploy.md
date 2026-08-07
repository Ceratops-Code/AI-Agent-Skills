# Deploy Managed Skills Action

## Goal

Deploy the exact manifest-managed skill batch without invoking repository
deployment operations or the first-install bootstrap.

## Context

### Script Bundle

- (D) Source validation: `python
  skills/ceratops-skill-lifecycle/scripts/skills-consistency-source-validator.py
  --repo-root <repo-root> --mode full` from a source checkout, or the same
  script from the installed skill-lifecycle bundle.
- (D) Managed runtime transaction: `python
  scripts/runtime/install-managed-skills.py --repo-root <repo-root>
  [--install-root <skills-root>] [--skill <name>...]
  [--remove-skill <name>...] [--base-revision <full-sha>]` from the installed
  or source lifecycle bundle.

### Inputs To Capture

- Source checkout, install root, validation profile, and deployment mode.
- Exact selected or removed skills when the mode is not all-managed.
- Full base revision only for an explicitly requested affected-set deployment.

## Constraints

- Enter through `$ceratops-repo-lifecycle` for promotion or shipping; run its
  repository `deploy` operation first when declared.
- Never invoke `deploy/deploy.yml` or `scripts/install-skills-bootstrap.py` from
  this action.
- Do not pass bootstrap version metadata into the runtime transaction. Runtime
  ownership compatibility is governed by `RUNTIME_MANIFEST_SCHEMA`.
- Stage and validate the complete selected runtime batch in hidden transaction
  directories under the install root before activation.

## Workflow

1. Run full source validation from the skill-lifecycle bundle. Do not run the
   repository aggregate validator here.
2. Select exactly one runtime mode: all-managed by default, explicit selected
   and removed skills, or affected-set deployment from one full base revision.
3. Run the managed runtime installer once and treat cleanup-blocked output as a
   deployed result with retained cleanup debt.

## Done When

### Completion Gate

- Source validation passed and the exact runtime transaction completed.
- Any retained retired folders or decision-required affected set is reported.

### Output Contract

Report only the deployment mode, deployed and removed skills, retained cleanup
debt, or the exact blocker.
