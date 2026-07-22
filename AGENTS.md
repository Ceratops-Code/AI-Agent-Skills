## Instruction enforcement

- [SKILLS-ENF-01] All instruction bullets in this file are mandatory,
  blocking, and closure-gating for the phase, action, decision, artifact, or
  response they govern.
  - overlaps: ENF-01
- [SKILLS-ENF-02] Do not proceed with or claim completion for any action,
  decision, artifact, or response when an applicable instruction bullet is
  unmet, unverifiable, or in conflict; report the blocker or conflict instead.
  - overlaps: ENF-02

Metadata: Project-specific rules for this skills repository.

Skills repo checkout and worktrees:

- [SKILLS-CHECKOUT-01] The primary skills repo checkout used to generate
  installed Ceratops skill copies must stay on local `main` tracking
  `origin/main` or a local `release/*` branch created from `main` for an active
  unpublished batch.
  - limits: FILE-02
- [SKILLS-WORKTREE-01] Do not develop or patch Ceratops skill source directly
  in the skills repo checkout during create, update, audit, or repair work. For
  any task that modifies skills, work in one thread-owned git worktree, name it
  after the thread rather than a subtask, reuse it for follow-on skill changes
  in the same thread unless conflicting branch histories or explicit user
  direction require a new one, and do not place it inside the skills repo
  checkout.
  - self: exceeds-limit, list-heavy
- [SKILLS-PREVIEW-01] Keep installed Ceratops skill folders generated from the
  skills repo checkout, not task worktrees. For unpublished local previews,
  refresh remote refs with `git fetch --prune origin`, merge ready worktree
  branches into the checkout's local `release/*` branch, and run
  `python scripts/install-skills.py` there instead of generating installed
  skills from task worktrees.
  - self: list-heavy
- [SKILLS-STAGE-01] Do not stage skill-source changes into a local `release/*`
  batch unless the task explicitly requests staging, shipping, or local preview
  sync.
  - limits: SKILLS-PREVIEW-01
- [SKILLS-SHIP-01] Skills-repo changes must ship from `release/*`, never
  directly from task or feature branches.
- [SKILLS-CREATE-01] New Ceratops skill creation is the only default-staging
  exception: `$ceratops-skill-lifecycle` create must finish with
  change-promotion and install verification unless the user opts out.
  - overrides: SKILLS-STAGE-01
- [SKILLS-SHIP-02] For staging or shipping, use `$ceratops-skill-lifecycle`
  change-promotion or ship-to-remote. After shipping, restore the checkout from
  `origin/main`, reinstall managed skills from `main`, and report retained
  worktrees or release branches.
  - self: list-heavy

Instruction and skill maintenance:

- [SKILLS-GOV-01] Before proposing or editing a repository control surface,
  including `AGENTS.md`, `automation.toml`, `SKILL.md`, skill manifests, shared
  sections, or helper contracts, re-open the relevant files from disk and use
  the current contents as the source of truth.
  - self: list-heavy
- [SKILLS-GOV-02] Treat recommendations about instruction, automation, skill,
  and helper-contract changes as advisory unless the user explicitly asks to
  apply a named change.
- [SKILLS-PORT-01] In repo-tracked files intended for public sharing or GitHub,
  including `AGENTS.md`, `automation.toml`, `SKILL.md`, generated runtime
  skill files, scripts, docs, and examples, do not hardcode user-local absolute
  filesystem paths unless an external runtime explicitly requires them; use
  repo-relative paths or portable variables such as `$CODEX_HOME`.
  - self: list-heavy
- [SKILLS-RUNTIME-01] For skill runtime workflows, invoke shared helpers through
  installed console commands, `python -m <module>` entrypoints, or scripts in
  the installed skill folder; do not locate shared helpers by absolute paths or
  by the repo's parent directory.
  - overlaps: HELP-01
- [SKILLS-MAINT-01] When a workflow needs a shared repo-maintenance script, run
  `scripts/<name>` from the active source checkout root when available, or the
  installed skill folder; when a helper is skill-local, run it from that skill
  folder or the corresponding source skill folder; stop as blocked if neither
  declared location contains it.
- [SKILLS-STYLE-01] Prefer concise, principle-based, machine-oriented wording;
  avoid example lists unless needed to disambiguate behavior.
  - overlaps: OUT-01, OUT-02
- [SKILLS-VERIFY-01] After instruction edits, verify the changed diff or
  reopened section and confirm no new duplicate, contradiction, or dropped
  behavior was introduced.
- [SKILLS-AUTO-01] When an automation uses a script or helper, compare prompt
  and code before finishing and keep outcome, blocker, cleanup, alert, and
  memory paths aligned.
  - self: list-heavy
- [SKILLS-HELP-01] Put deterministic, testable, or procedural automation
  behavior in scripts or helpers rather than prompt text when helpers exist.
- [SKILLS-CREDIT-01] When updating an automation, skill, instruction, or helper,
  assess whether the change could materially increase recurring or avoidable
  credit usage; if so, report that before treating the update as done.
  - self: list-heavy
