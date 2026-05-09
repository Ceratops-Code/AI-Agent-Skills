<!-- INTERNAL: include in Ceratops skills repo release-branch staging and shipping skills -->

## Release Branch Staging

- Treat the skills repo checkout's active `release/*` branch as the single local preview source of truth for the staged repo snapshot.
- Keep installed Ceratops skill folders generated from the skills repo checkout path, not from task worktrees.
- Reuse the same `release/*` branch name locally and remotely by default. Do not rename or remap it unless the user explicitly chooses that tradeoff.
- Refresh remote refs with `git fetch --prune origin` before judging whether a skills repo `release/*` branch already exists remotely, should be reused, or was already cleaned up.
- When the GH skill family was touched, confirm copied scripts and contract payloads exist in the relevant installed skill folders after the installer or restore step.
