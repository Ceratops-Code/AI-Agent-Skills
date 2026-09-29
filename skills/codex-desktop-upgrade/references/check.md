# Check Action

## Goal

Determine whether an official Codex desktop release is newer than the version
underlying the currently running managed runtime, summarize the intervening
official release notes, and recommend which patches merit retirement testing.

## Context

The running managed runtime's `.code-version.json` is authoritative for its
base version and effective patch set. Installed package metadata establishes
what is present on the computer; official Store metadata and OpenAI release
notes establish what is published when they expose an exact version.

## Constraints

### Boundaries

- This action is read-only. Do not import app code, run `AssessUpgrade`, build,
  patch, qualify, adopt, deploy, restart Codex, or edit patch decisions.
- Compare numeric versions with version-aware semantics, not lexical ordering.
- Distinguish the running base, locally installed official package, and latest
  published official version. Do not present the installed version as the
  latest published version unless official evidence establishes that identity.
- Use official OpenAI or Microsoft sources for release availability and notes.
  State when an exact Store version or complete version-to-note mapping is not
  exposed.
- Release-note similarity identifies only a retirement candidate. Recommend
  the `upgrade` action for behavior comparison before changing or removing any
  patch.

## Workflow

1. Resolve the active managed executable through the patcher's launcher and
   selected runtime state. Read its `.code-version.json`; record the exact base
   version, generation, effective patch names, and patcher source identity.
2. Read the installed official `OpenAI.Codex` package version. Retrieve the
   current official Store listing or package metadata and official OpenAI Codex
   desktop release notes. Record source links and retrieval dates.
3. Compare the newest officially evidenced version with the running base. If
   publication metadata does not expose an exact newer version, report that
   limitation instead of inferring one from dates or prose.
4. Summarize only release notes newer than the running base when a reliable
   version boundary exists; otherwise summarize the newest relevant entries and
   label the boundary uncertain.
5. Map each relevant native change to the effective patch set by behavior and
   owner. Classify patches as no apparent overlap, retirement candidate, or
   insufficient evidence. For each candidate, name the behavior that the
   `upgrade` action must verify.
6. Recommend no action when the running base is current. Otherwise recommend
   either a read-only `upgrade` assessment or a user-requested upgrade phase,
   clearly naming the required authorization and target version.

## Done When

### Completion Gate

The running-base comparison is supported by current official evidence, every
effective patch has a retirement disposition, and all unavailable or ambiguous
version boundaries are explicit.

### Output Contract

Report the running base, installed official version, latest officially
evidenced version, whether a newer release exists, linked release-note summary,
patch-by-patch candidate analysis, and one recommended next action. Do not claim
that any patch is retired or compatible.
