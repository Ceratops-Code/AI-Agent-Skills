# Run Operation Action

## Goal

Execute one named structured operation from the repository's live
`deploy/deploy.yml` contract.

## Context

### Script Bundle

- (D) Operation runner:
  `python scripts/run-deploy-operation.py --repo-root PATH
  --contract deploy/deploy.yml --operation NAME
  [--parameter name=value...]
  [--parameter-if-declared name=value...]`.

## Constraints

- Run only an operation explicitly declared by the live contract.
- Treat every step as an argv array and execute it without a shell.
- Resolve the contract and every step working directory inside the repository.
- Require every explicit `--parameter` to be declared. Lifecycle callers may
  offer conditional parameters that satisfy declared names and are ignored
  otherwise.
- Require every declared parameter after conditional selection and replace only
  whole-argument `{name}` placeholders.
- Stop on the first failed step and retain only bounded failure output.
- Do not substitute prose instructions or invent missing commands.

## Done When

### Completion Gate

- Contract schema validation passed.
- Every step in the named operation completed in order.

### Output Contract

Report only the operation outcome, failed step when applicable, and anything
important not verified.
