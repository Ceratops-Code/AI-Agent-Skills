# Deploy Managed Skills Action

## Goal

Deploy the exact manifest-managed skill batch without invoking repository
deployment operations or the independent bootstrap installer.

## Context

### Script Bundle

- Bind `<skill-root>` to the directory containing this action's parent
  `SKILL.md`; require `<skill-root>/scripts/runtime/install-managed-skills.py`
  before the first call. Invoke that exact path with the working directory
  equal to its `--repo-root` value; stop if absent and never resolve it relative
  to that repository.
- Source-validation handoff: `references/source-validate.md` with the same
  source checkout and `full` mode.
- (D) Managed runtime transaction: `python
  "<skill-root>/scripts/runtime/install-managed-skills.py" --repo-root <repo-root>
  [--install-root <skills-root>] [--skill <name>...]
  [--remove-skill <name>...] [--base-revision <full-sha>]` from the installed
  or source lifecycle bundle.

- Before classifying or replacing runtime paths, the installer changes its
  process working directory to the verified `<repo-root>`.

### Inputs To Capture

- Source checkout, install root, validation profile, and deployment mode.
- Exact selected or removed skills when the mode is not all-managed.
- Full base revision only for an explicitly requested affected-set deployment.

## Constraints

- Enter through `$ceratops-repo-lifecycle` for promotion or shipping; run its
  repository `deploy` operation first when declared.
- Never invoke `sdlc/sdlc.yml` or `scripts/deploy-skills.py` from
  this action.
- Do not pass bootstrap version metadata into the runtime transaction. Runtime
  ownership compatibility is governed by `RUNTIME_MANIFEST_SCHEMA`.
- Stage and validate the complete selected runtime batch in hidden transaction
  directories under the install root before activation.

## Workflow

1. Follow `source-validate` in `full` mode for the exact source checkout.
   Reuse its passing result only while those source inputs remain unchanged.
   The default SDLC action binding owns both full source validation and managed
   installation; it stops before installation if source validation fails.
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
