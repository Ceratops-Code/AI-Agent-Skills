# Code Comment Non-Deterministic Contract

This contract is a local review rubric for comment sufficiency. It is not a deterministic checker and should not run during ordinary implementation, shipping, or skill-update work.

Use it during `ceratops-code-consistency-audit` when scripts, public APIs, automation helpers, contract validators, or non-obvious safety logic are in scope.

## Scope Policy

- Applies to repo scripts, CLI entrypoints, automation helpers, contract validators, and nontrivial project code touched by a consistency audit.
- Prefer project-local conventions when they exist.
- Do not research current language comment standards unless the user explicitly asks for a standards refresh.

## Required Comment Roles

- Public intent or usage contract.
- Non-obvious safety boundary.
- External API or filesystem side-effect boundary.
- Data shape or contract interpretation that is not obvious from names.
- Reason for intentionally unusual or conservative behavior.

## Discouraged Comment Roles

- Line-by-line restatement of simple code.
- Stale implementation history.
- Commented-out code.

## Prohibited Comment Roles

- TODO comments.

## Language Defaults

Python:
- Standalone scripts, reusable modules, and contract validators should have useful module docstrings.
- Public classes, public functions, dataclasses, and CLI entrypoints should have docstrings when behavior is not trivial.
- Non-obvious destructive, mutating, credential, network, or filesystem-boundary logic should have short intent or safety comments.

PowerShell:
- User-facing scripts should have a top-level comment or self-explanatory parameter block.
- Parameter names and validation should make common usage clear.
- Removal, move, branch, runtime-install, or generated-copy logic should have nearby intent or safety comments.

JavaScript or TypeScript:
- Header comments are useful for standalone scripts or non-obvious integration points.
- Exported APIs should use comments or JSDoc when behavior, side effects, or data shape is not obvious.
- Filesystem, network, package-publish, or credential-sensitive behavior should have concise safety comments.

Shell:
- User-facing scripts should have a header comment.
- Destructive commands, shell-option choices, traps, and non-obvious quoting or path handling should have nearby comments.

JSON contracts:
- Top-level purpose, scope, parameters, and remediation fields should explain intent without separate prose.
- Each check should carry enough id, description, expected value, source, and remediation data for deterministic scripts and reviewers to understand it.

## Review Checks

| ID | Review question |
| --- | --- |
| `ND.comments.sufficiency_for_maintenance` | Do comments explain the repo's non-obvious behavior, invariants, safety boundaries, and public script usage well enough for a future maintainer to update the code without reconstructing intent from history? |
| `ND.comments.readme_alignment` | Does the README describe the scripts and contracts that users actually run, without documenting retired helpers or generated internals as active workflow? |
