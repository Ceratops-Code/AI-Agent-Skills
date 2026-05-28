# Side-Task Handoff Action

## Goal

Produce one minimal copy-paste prompt for starting a side task in a new thread.

## Context

### Inputs To Capture

- The original task in one line, if it matters.
- What was discovered or concluded that created the side task.
- The side task's current objective.
- What stays in the current thread, if that matters.
- The exact repo names, PRs, tags, releases, automations, or external entities
  needed to identify the side task.
- The current evidence, conclusions, constraints, and next-step-critical details
  summarized in the prompt itself.
- Any active constraints or instructions that materially affect the side task.

Infer missing inputs from the current thread and local state before asking.

### Required Prompt Content

- What we were trying to do, in one short line if relevant
- What we came to eventually or discovered that created the side task
- What the objective is now
- What stays in the current thread, if relevant
- Self-contained evidence and context, kept minimal
- Active constraints or instructions that materially affect the work
- The first next step or question for the new thread

## Constraints

### Skill-Specific Rules

- Treat the original task as background. Include it in one short line only when
  needed.
- Optimize for the side task only. Ignore most of the original task unless it
  directly constrains the new thread.
- Produce a prompt, not a bundle and not instructions to use a follow-up handoff
  action.
- Prefer the discovered conclusion and current objective over chronology.
- Reuse fresh state already established in the current thread by default.
- Refresh only facts whose staleness would change or misdirect the first step in
  the new thread.
- Do not include file paths or source-of-truth reference lists; summarize the
  relevant file contents, evidence, and conclusions inside the prompt itself.
- Mention repo names, PR numbers, automation names, external URLs, or other
  non-file identifiers only when they are needed to identify the side task.
- Include what stays in the current thread only when it matters for scope
  control.
- Put active instructions or process constraints under constraints, summarized
  in prompt text.
- If the user says `include the following questions`, `including the questions`,
  or equivalent wording, carry those questions into the prompt as next-thread
  asks instead of answering them here.
- Do not ask for credentials unless verifying the handoff requires protected
  state that cannot be inferred locally.

### Boundaries

- Use this action only when the user wants to spin off a newly discovered
  sub-issue into a different thread.

### Workflow

#### 1. Isolate The Side Task

- Separate the side task from the original task.
- Keep only the original-task context needed to explain why the side task
  exists.

#### 2. Refresh Only First-Step-Critical State

- Apply the first-step refresh rules from Skill-Specific Rules before drafting
  the prompt.

#### 3. Emit A Paste-Ready Prompt

- Make the current objective and first next step explicit.
- Write the prompt as direct instruction to the new thread, not as commentary
  about a handoff artifact.

## Done When

### Completion Gate

- Verify the prompt includes the required content and enough self-contained
  context to start correctly without opening referenced files.
- Verify the prompt excludes irrelevant branches of the original task unless
  they materially constrain the side task.
- Verify the prompt does not list file paths or source-of-truth reference
  sections, and summarizes any needed file-derived evidence directly.
- Verify the prompt does not pretend a fresh re-check happened when it did not.

### Output Contract

Emit one copy-paste prompt for a new thread and nothing extra.

### Example Invocation

`Use $ceratops-tasks side-task-handoff to create a copy-paste prompt for
spinning this side issue into a new thread and keep the main task out unless it
directly matters.`
