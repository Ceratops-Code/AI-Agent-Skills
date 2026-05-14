## Instruction enforcement
- All instruction bullets in this file are mandatory, blocking, and
  closure-gating for the phase, action, decision, artifact, or response they govern.
- Do not proceed with or claim completion for any action, decision, artifact, or
  response when an applicable instruction bullet is unmet, unverifiable, or in
  conflict; report the blocker or conflict instead.

Metadata: Project-specific rules for this skills repository.

Skills repo checkout and worktrees:
- The primary skills repo checkout used to generate installed Ceratops skill copies must stay either on local `main` tracking `origin/main` or on a local `release/*` branch created from `main` for an active unpublished batch.
- Do not develop or patch Ceratops skill source directly in the skills repo checkout during create, update, audit, or repair work; for any task that modifies skills, work in one thread-owned git worktree, name that worktree after the thread rather than a subtask, reuse it for follow-on skill changes in the same thread unless conflicting branch histories or explicit user direction require a new one, and do not place it inside the skills repo checkout.
- Keep installed Ceratops skill folders generated from the skills repo checkout path, not from task worktrees. For local preview of unpublished batches, refresh remote refs with `git fetch --prune origin`, then merge ready worktree branches into the skills repo checkout's local `release/*` branch and rerun `scripts/install-skills.ps1` instead of generating installed skills from task worktrees.
- Do not stage or merge skill-source changes into a local `release/*` batch unless the task explicitly requests staging, shipping, or local preview sync.
- New Ceratops skill creation is the only default-staging exception: `$ceratops-skill-lifecycle` create must finish with change-promotion and install verification unless the user opts out.
- For staging or shipping, use `$ceratops-skill-lifecycle` change-promotion or ship-to-remote. After shipping, restore the checkout from `origin/main`, reinstall managed skills from `main`, and report retained worktrees or release branches.

Instruction and skill maintenance:
- Before proposing or editing `AGENTS.md`, `automation.toml`, `SKILL.md`, shared skill sections, skill manifests, or helper-contract text, re-open the relevant files from disk and use the current contents as the source of truth.
- Treat recommendations about instruction, automation, skill, and helper-contract changes as advisory unless the user explicitly asks to apply a named change.
- In repo-tracked files intended for public sharing or GitHub, including repo-tracked `AGENTS.md`, `automation.toml`, `SKILL.md`, generated runtime skill files, scripts, docs, and examples, do not hardcode user-local absolute filesystem paths unless an external runtime explicitly requires them; use repo-relative paths or portable variables such as `$CODEX_HOME`.
- For skill runtime workflows, invoke shared helpers through installed console commands, `python -m <module>` entrypoints, or scripts copied into the installed skill folder; do not locate shared helpers by absolute paths or by the repo's parent directory.
- When a workflow needs a shared repo-maintenance script, run `scripts/<name>` from the active source checkout root when available, otherwise from the installed skill folder; when a helper is skill-local, run it from that skill folder or the corresponding source skill folder; stop as blocked if neither declared location contains it.
- Prefer concise, principle-based, machine-oriented wording; avoid example lists unless the examples are needed to disambiguate behavior.
- After instruction edits, verify the changed diff or reopened section and confirm no new duplicate, contradiction, or dropped behavior was introduced.
- When an automation uses a script or helper, compare prompt and code before finishing and keep outcome, blocker, cleanup, alert, and memory paths aligned.
- Put deterministic, testable, or procedural automation behavior in scripts or helpers rather than prompt text when such helpers exist.
- When updating an automation, skill, instruction, or related helper script, assess whether the change could materially increase recurring or avoidable credit usage; if so, report that before treating the update as done.
