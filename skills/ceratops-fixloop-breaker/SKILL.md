---
name: ceratops-fixloop-breaker
description: Break repeated failed fix loops by requiring full failure analysis before more code changes when repeated fixes have not solved the same symptom.
---

# Ceratops FixLoop Breaker

## Goal

Stop a repeated failed fix loop and identify a credible next fix only after the previous attempts, missed evidence, stale layers, and repeated symptom have been accounted for.

## Context

### Inputs To Capture

- The current user-visible symptom and how it reproduces.
- Every fix already attempted in the loop, including changed artifacts and validation evidence.
- The branch, runtime, config, generated files, cache, database, or external state that may have hidden or overwritten a previous fix.
- Whether the symptom may come from more than one code path or state path.

Infer the loop ledger from the current thread and local state before asking.

## Constraints

### Skill-Specific Rules

- Do not write code until the failure analysis identifies a new credible root-cause class or explains why code changes are blocked.
- Build a run-by-run ledger naming each previous hypothesis, changed artifact, verification evidence, and why that verification failed to cover the current symptom.
- Check whether previous fixes were overwritten, generated away, applied to the wrong branch, applied to the wrong runtime, hidden by stale state, or aimed at the wrong layer.
- Search every implementation, config, migration, generated source, database field, and runtime path that can produce the same symptom.
- Treat multiple independent producers of the same symptom as separate causes unless evidence proves one owner.
- If recent merges or inconsistent state make a clean fix impossible, report that blocker instead of patching around it.
- Before changing code, list all locations that must change together and the verification that proves the running system used them.

### Boundaries

- Use this skill when repeated attempts have failed or the user explicitly invokes a fix-loop break.
- If this is the first diagnostic pass for a new problem, use `$ceratops-task-execute-in-stages` instead.
- If the loop is caused by avoidable workflow rework rather than one current bug, consider `$ceratops-credit-savings-analysis` after the immediate blocker is understood.

### Workflow

1. Confirm the symptom and current reproduction evidence.
2. Build the previous-fix ledger from the thread, diffs, command output, and local state.
3. Map every place the behavior can be produced or overwritten.
4. Identify the first missed or false assumption that explains why the loop persisted.
5. Propose the smallest fix that addresses every active producer together, or stop with a blocker if the root cause remains unproven.

## Done When

### Completion Gate

- The failure ledger covers each previous attempted fix in the loop.
- The next code change, if any, is tied to a new credible root-cause class and all affected locations.
- The response states when root cause confidence is insufficient and no code change should be made.

### Output Contract

Report only:

- repeated symptom and reproduction evidence
- previous-fix ledger
- confirmed missed root-cause class or blocker
- proposed all-location fix and verification, if justified
