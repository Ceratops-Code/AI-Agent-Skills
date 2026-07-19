<!-- INTERNAL: include in skills that select among multiple action references -->

## Multi-Action Skill Contract

- Load only the selected action reference unless the current action explicitly
  hands off to another action.
- Read the selected action file under `references/` and follow its inputs,
  constraints, helper contracts, workflow, completion gate, and output contract.
- If the selected action discovers another action owns the remaining work,
  switch through this multi-action skill and report the handoff reason only when
  it changes the user's next step.
- Do not claim completion unless the selected action reference was followed or
  the task was explicitly blocked.
- Keep cross-action handoffs inside this multi-action skill rather than creating
  standalone skill identities.
