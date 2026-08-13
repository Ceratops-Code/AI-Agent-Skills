<!-- INTERNAL: include in skills that select among multiple action references -->

## Multi-Action Skill Contract

- Under `### Action References`, list each public action exactly once and map it
  to one direct `references/*.md` file titled `# <Action Name> Action`; reserve
  that title form for public action files.
- Select the single action whose stated output and resulting state match the
  user's request. Use the parent's named default for a generic request; ask only
  when two actions would produce materially different results and evidence
  cannot decide.
- Load only the selected action reference. Follow another action only through an
  explicit handoff from the current action.
- Treat the selected action reference as the source of truth for its inputs,
  constraints, helper contracts, workflow, completion gate, and output contract;
  keep only cross-action invariants in the parent.
- Completion requires the selected action's completion gate or an explicit
  blocker.
- Keep public actions and cross-action handoffs inside the parent skill; do not
  create standalone, alias, old-name, or pointer skill identities.
