# Full Handoff Action

## Goal

Produce one copy-paste prompt for continuing the whole task in a new thread.

## Context

### Inputs To Capture

- The task goal and desired completion state.
- The current confirmed state the new thread should trust.
- The next justified step or first unresolved decision.
- The exact repos, files, PRs, tags, releases, images, paths, or automations the
  next thread is likely to open immediately.
- Any active constraints or instructions that materially affect the work.

Infer missing inputs from the current thread and local state before asking.

### Required Prompt Content

- What we were trying to do
- What has already been established or completed
- What the objective is now
- Unresolved blockers or non-blocking debt, if material
- Exact source-of-truth refs, kept minimal
- Active constraints or instructions that materially affect the work
- The next justified step
- Deferred questions or next-thread asks, if any

## Constraints

### Skill-Specific Rules

- Treat this as moving the whole task, not spinning off a side issue.
- Produce a prompt, not a bundle and not instructions to use a follow-up handoff
  action.
- Do not broaden work just to make the prompt feel complete.
- Prefer current state, current objective, and next step over chronology.
- Reuse fresh state already established in the current thread by default.
- Refresh only facts whose staleness would change or misdirect the first step in
  the new thread.
- Keep refs exact but limited to the entities the next thread is likely to open
  first.
- Exclude solved branches unless they materially constrain the next step.
- Include only the refs the new thread is likely to need immediately.
- If the user says `include the following questions`, `including the questions`,
  or equivalent wording, carry those questions into the prompt as next-thread
  asks instead of answering them here.
- Do not ask for credentials unless verifying the handoff requires protected
  state that cannot be inferred locally.

### Boundaries

- Use this action only when the user wants to move the whole task into a
  different thread.

### Workflow

#### 1. Refresh Only First-Step-Critical State

- Apply the first-step refresh rules from Skill-Specific Rules before drafting
  the prompt.

#### 2. Compress To The Current Task State

- Prefer direct facts over chronology.
- Keep historical background to the minimum needed to avoid a wrong start.

#### 3. Emit A Paste-Ready Prompt

- Make the objective now and the next justified step explicit.
- Write the prompt as direct instruction to the new thread, not as commentary
  about a handoff artifact.

## Done When

### Completion Gate

- Verify the prompt includes the required content and enough exact refs to start
  correctly.
- Verify the prompt does not pretend a fresh re-check happened when it did not.

### Output Contract

Emit one copy-paste prompt for a new thread and nothing extra.

### Example Invocation

```text
Use $ceratops-task-lifecycle full-handoff to create a copy-paste prompt for
moving this whole task into a new thread.
```
